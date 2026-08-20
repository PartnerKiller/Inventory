import uuid
import math
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.purchasing import (
    Supplier,
    SupplierProduct,
    SupplierPriceHistory,
    PurchaseOrder,
    POLineItem,
    GoodsReceipt,
    GoodsReceiptLine,
    SupplierReturn,
    SupplierReturnLine
)
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerEntry, StockLedgerTransaction
from app.models.costing import ItemCostProfile, COGSRecord, CostLayer
from app.schemas.purchasing import (
    PurchaseSuggestionItem,
    PurchaseSuggestionsResponse,
    DraftPOFromSuggestionsRequest,
    DraftPOBatchItem,
    DraftPOBatchResponse,
    PurchasePriceVarianceItem,
    PurchasePriceVarianceReportResponse,
    SupplierScorecardItem,
    SupplierScorecardResponse,
    ProcurementDashboardResponse,
    PurchaseOrderCreate,
    POLineCreate
)
from app.services.purchase_service import PurchaseService
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService

def quantize_decimal(val: Any, places: int = 2) -> Decimal:
    if val is None:
        return Decimal("0.0")
    d = Decimal(str(val))
    return d.quantize(Decimal(10) ** -places)

class ProcurementService:
    @staticmethod
    async def get_purchase_suggestions(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> PurchaseSuggestionsResponse:
        """
        Calculates replenishment-derived purchase suggestions with deterministic supplier selection.
        Applies MOQ and Pack Size constraints.
        """
        now = get_utc_now()
        start_90d = now - timedelta(days=90)

        # 1. Fetch physical stock balances grouped by (warehouse_id, item_variant_id)
        bal_stmt = (
            select(
                StockBalanceCache.warehouse_id,
                StockBalanceCache.item_variant_id,
                func.sum(StockBalanceCache.quantity_on_hand),
                func.sum(StockBalanceCache.quantity_allocated)
            )
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .where(Warehouse.tenant_id == tenant_id)
        )
        if warehouse_id:
            bal_stmt = bal_stmt.where(StockBalanceCache.warehouse_id == warehouse_id)

        bal_stmt = bal_stmt.group_by(StockBalanceCache.warehouse_id, StockBalanceCache.item_variant_id)
        bal_res = await db.execute(bal_stmt)
        balances = {(row[0], row[1]): (Decimal(str(row[2] or 0.0)), Decimal(str(row[3] or 0.0))) for row in bal_res.fetchall()}

        # 2. Incoming purchase order quantities
        po_stmt = (
            select(
                PurchaseOrder.target_warehouse_id,
                POLineItem.item_variant_id,
                func.sum(POLineItem.quantity_ordered - POLineItem.quantity_received - POLineItem.quantity_cancelled)
            )
            .join(PurchaseOrder, POLineItem.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.status.in_(["APPROVED", "PARTIALLY_RECEIVED"]),
                PurchaseOrder.is_deleted == False
            )
        )
        if warehouse_id:
            po_stmt = po_stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)

        po_stmt = po_stmt.group_by(PurchaseOrder.target_warehouse_id, POLineItem.item_variant_id)
        po_res = await db.execute(po_stmt)
        incoming_by_wh_var = {(row[0], row[1]): max(Decimal("0.0"), Decimal(str(row[2] or 0.0))) for row in po_res.fetchall()}

        # 3. 90-day consumption per variant for ADU
        cogs_stmt = (
            select(COGSRecord.item_variant_id, func.sum(COGSRecord.quantity_shipped))
            .where(
                COGSRecord.tenant_id == tenant_id,
                COGSRecord.recognized_at >= start_90d,
                COGSRecord.is_deleted == False
            )
            .group_by(COGSRecord.item_variant_id)
        )
        cogs_res = await db.execute(cogs_stmt)
        cogs_90d = {row[0]: Decimal(str(row[1] or 0.0)) for row in cogs_res.fetchall()}

        # 4. Fetch Warehouses and Variants
        wh_stmt = select(Warehouse).where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        if warehouse_id:
            wh_stmt = wh_stmt.where(Warehouse.id == warehouse_id)
        warehouses = (await db.execute(wh_stmt)).scalars().all()

        var_stmt = (
            select(ItemVariant, Item)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
        )
        var_rows = (await db.execute(var_stmt)).fetchall()

        # 5. Fetch all active SupplierProducts for tenant
        sp_stmt = (
            select(SupplierProduct, Supplier)
            .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
            .where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.is_active == True,
                Supplier.is_active == True,
                Supplier.status == "ACTIVE",
                Supplier.is_deleted == False
            )
            .order_by(
                SupplierProduct.is_preferred.desc(),
                SupplierProduct.unit_cost.asc(),
                SupplierProduct.lead_time_days.asc(),
                Supplier.code.asc()
            )
        )
        sp_rows = (await db.execute(sp_stmt)).fetchall()
        
        # Group supplier products by variant_id
        supp_by_variant: Dict[str, List[Tuple[SupplierProduct, Supplier]]] = {}
        for sp, s in sp_rows:
            if sp.item_variant_id not in supp_by_variant:
                supp_by_variant[sp.item_variant_id] = []
            supp_by_variant[sp.item_variant_id].append((sp, s))

        suggestions = []
        crit_count = 0
        reorder_count = 0
        total_est_spend = Decimal("0.0")

        for wh in warehouses:
            for variant, item in var_rows:
                key = (wh.id, variant.id)
                on_hand, allocated = balances.get(key, (Decimal("0.0"), Decimal("0.0")))
                available = max(Decimal("0.0"), on_hand - allocated)
                incoming = incoming_by_wh_var.get(key, Decimal("0.0"))

                # ADU
                consumed_90d = cogs_90d.get(variant.id, Decimal("0.0"))
                adu = quantize_decimal(consumed_90d / Decimal("90.0"), 4)

                # Deterministic Supplier Selection
                eligible_supps = supp_by_variant.get(variant.id, [])
                if eligible_supps:
                    chosen_sp, chosen_supp = eligible_supps[0]
                    supp_id = chosen_supp.id
                    supp_name = chosen_supp.name
                    supp_code = chosen_supp.code
                    supp_sku = chosen_sp.supplier_sku or variant.variant_sku
                    unit_cost = Decimal(str(chosen_sp.unit_cost))
                    curr = chosen_sp.currency
                    lead_time = chosen_sp.lead_time_days
                    moq = Decimal(str(chosen_sp.minimum_order_quantity or 1.0))
                    pack_size = Decimal(str(chosen_sp.pack_size or 1.0))
                    is_preferred = chosen_sp.is_preferred
                else:
                    # Fallback if no specific supplier mapping exists
                    supp_id = "UNKNOWN"
                    supp_name = "No Active Supplier Mapped"
                    supp_code = "NONE"
                    supp_sku = variant.variant_sku
                    unit_cost = Decimal(str(variant.cost_price or 0.0))
                    curr = "USD"
                    lead_time = 14
                    moq = Decimal("1.0")
                    pack_size = Decimal("1.0")
                    is_preferred = False

                safety_stock = quantize_decimal(adu * Decimal("7.0"), 2) if adu > 0 else Decimal("10.0")
                rop = quantize_decimal((adu * Decimal(str(lead_time))) + safety_stock, 2)
                target_stock = quantize_decimal(rop + (adu * Decimal("30.0")), 2)

                raw_rpq = max(Decimal("0.0"), target_stock - (available + incoming))

                if raw_rpq > 0:
                    # Apply pack size multiple
                    packs = math.ceil(float(raw_rpq / pack_size))
                    constrained_qty = max(moq, Decimal(str(packs)) * pack_size)
                else:
                    constrained_qty = Decimal("0.0")

                est_cost = quantize_decimal(constrained_qty * unit_cost, 2)

                if available == 0 and adu > 0:
                    urgency = "CRITICAL_STOCKOUT"
                    crit_count += 1
                    reorder_count += 1
                    total_est_spend += est_cost
                elif (available + incoming) <= rop and constrained_qty > 0:
                    urgency = "REORDER_REQUIRED"
                    reorder_count += 1
                    total_est_spend += est_cost
                else:
                    urgency = "HEALTHY"

                # Filter: include only items needing reorder or critical
                if urgency in ["CRITICAL_STOCKOUT", "REORDER_REQUIRED"]:
                    suggestions.append(PurchaseSuggestionItem(
                        variant_id=variant.id,
                        variant_sku=variant.variant_sku,
                        item_name=item.name,
                        warehouse_id=wh.id,
                        warehouse_name=wh.name,
                        supplier_id=supp_id,
                        supplier_name=supp_name,
                        supplier_code=supp_code,
                        supplier_sku=supp_sku,
                        unit_cost=float(unit_cost),
                        currency=curr,
                        quantity_on_hand=float(on_hand),
                        quantity_allocated=float(allocated),
                        quantity_available=float(available),
                        incoming_on_po=float(incoming),
                        reorder_point=float(rop),
                        target_stock=float(target_stock),
                        raw_recommended_quantity=float(raw_rpq),
                        pack_size=float(pack_size),
                        minimum_order_quantity=float(moq),
                        suggested_order_quantity=float(constrained_qty),
                        estimated_spend=float(est_cost),
                        lead_time_days=lead_time,
                        is_preferred_supplier=is_preferred,
                        urgency=urgency
                    ))

        # Sort: Critical first, then highest spend
        urgency_order = {"CRITICAL_STOCKOUT": 0, "REORDER_REQUIRED": 1, "HEALTHY": 2}
        suggestions.sort(key=lambda s: (urgency_order[s.urgency], -s.estimated_spend))

        return PurchaseSuggestionsResponse(
            total_suggestions=len(suggestions),
            critical_stockout_count=crit_count,
            reorder_required_count=reorder_count,
            total_estimated_spend=float(total_est_spend),
            suggestions=suggestions,
            generated_at=now
        )

    @staticmethod
    async def create_draft_pos_from_suggestions(
        db: AsyncSession,
        tenant_id: str,
        req: DraftPOFromSuggestionsRequest,
        user_id: Optional[str] = None
    ) -> DraftPOBatchResponse:
        """
        Batch-generates reviewable Draft Purchase Orders grouped by supplier from selected suggestions.
        Does NOT mutate physical stock or costing.
        """
        suggestions_res = await ProcurementService.get_purchase_suggestions(db, tenant_id, warehouse_id=req.warehouse_id)
        selected_set = set(req.suggestion_variant_ids)

        filtered = [s for s in suggestions_res.suggestions if s.variant_id in selected_set and s.supplier_id != "UNKNOWN"]
        if not filtered:
            raise HTTPException(status_code=422, detail="No eligible suggestions with valid supplier mappings found for selected variants")

        # Group by (supplier_id, warehouse_id)
        grouped: Dict[Tuple[str, str], List[PurchaseSuggestionItem]] = {}
        for item in filtered:
            key = (item.supplier_id, item.warehouse_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(item)

        created_pos = []
        total_lines = 0
        total_spend = Decimal("0.0")

        for (supp_id, wh_id), items in grouped.items():
            po_lines = []
            for it in items:
                po_lines.append(POLineCreate(
                    item_variant_id=it.variant_id,
                    quantity_ordered=Decimal(str(it.suggested_order_quantity)),
                    unit_price=Decimal(str(it.unit_cost)),
                    discount_pct=Decimal("0.0"),
                    tax_pct=Decimal("0.0")
                ))

            po_in = PurchaseOrderCreate(
                supplier_id=supp_id,
                target_warehouse_id=wh_id,
                currency=items[0].currency,
                expected_delivery_at=get_utc_now() + timedelta(days=items[0].lead_time_days),
                notes=f"Auto-generated Draft PO from Replenishment Suggestions on {get_utc_now().strftime('%Y-%m-%d')}",
                lines=po_lines
            )

            po = await PurchaseService.create_purchase_order(db, tenant_id, po_in, user_id=user_id)
            total_lines += len(po.lines)
            total_spend += Decimal(str(po.total_amount))

            created_pos.append(DraftPOBatchItem(
                supplier_id=supp_id,
                supplier_name=items[0].supplier_name,
                purchase_order_id=po.id,
                po_number=po.po_number,
                item_count=len(po.lines),
                total_amount=float(po.total_amount)
            ))

        return DraftPOBatchResponse(
            total_draft_pos_created=len(created_pos),
            total_lines_created=total_lines,
            total_estimated_spend=float(total_spend),
            draft_orders=created_pos
        )

    @staticmethod
    async def get_purchase_price_variance_report(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: Optional[str] = None,
        days_back: int = 90
    ) -> PurchasePriceVarianceReportResponse:
        """
        Calculates line-by-line Purchase Price Variance (PPV) between PO/Standard price and received GRN price.
        """
        now = get_utc_now()
        start_date = now - timedelta(days=days_back)

        stmt = (
            select(
                GoodsReceiptLine,
                GoodsReceipt,
                PurchaseOrder,
                POLineItem,
                Supplier,
                ItemVariant,
                Item
            )
            .join(GoodsReceipt, GoodsReceiptLine.goods_receipt_id == GoodsReceipt.id)
            .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
            .join(POLineItem, GoodsReceiptLine.po_line_id == POLineItem.id)
            .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
            .join(ItemVariant, GoodsReceiptLine.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                GoodsReceipt.received_at >= start_date
            )
        )
        if supplier_id:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)

        rows = (await db.execute(stmt)).fetchall()

        items_out = []
        net_ppv = Decimal("0.0")
        fav_ppv = Decimal("0.0")
        unfav_ppv = Decimal("0.0")

        for grl, gr, po, pol, sup, var, it in rows:
            qty_rec = Decimal(str(grl.quantity_received or 0.0))
            po_price = Decimal(str(pol.unit_price or 0.0))
            std_cost = Decimal(str(var.cost_price or pol.unit_price or 0.0))

            unit_ppv = po_price - std_cost
            tot_ppv = quantize_decimal(unit_ppv * qty_rec, 2)
            var_pct = float(quantize_decimal((unit_ppv / std_cost * Decimal("100.0")), 2)) if std_cost > 0 else 0.0

            net_ppv += tot_ppv
            if tot_ppv < 0:
                fav_ppv += abs(tot_ppv)
                cls = "FAVORABLE"
            elif tot_ppv > 0:
                unfav_ppv += tot_ppv
                cls = "UNFAVORABLE"
            else:
                cls = "ON_TARGET"

            items_out.append(PurchasePriceVarianceItem(
                grn_id=gr.id,
                grn_number=gr.grn_number,
                received_at=gr.received_at,
                po_id=po.id,
                po_number=po.po_number,
                supplier_id=sup.id,
                supplier_name=sup.name,
                variant_id=var.id,
                variant_sku=var.variant_sku,
                item_name=it.name,
                quantity_received=float(qty_rec),
                po_unit_price=float(po_price),
                standard_unit_cost=float(std_cost),
                received_unit_price=float(po_price),
                unit_ppv=float(unit_ppv),
                total_ppv=float(tot_ppv),
                variance_percentage=var_pct,
                variance_classification=cls
            ))

        return PurchasePriceVarianceReportResponse(
            total_receipt_lines_evaluated=len(items_out),
            net_ppv_amount=float(net_ppv),
            favorable_variance_amount=float(fav_ppv),
            unfavorable_variance_amount=float(unfav_ppv),
            lines=items_out,
            generated_at=now
        )

    @staticmethod
    async def get_supplier_scorecards(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: Optional[str] = None
    ) -> SupplierScorecardResponse:
        """
        Computes supplier performance scorecard: OTD %, Fill Rate %, Mean Lead Time, PPV.
        """
        now = get_utc_now()
        sup_stmt = select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
        if supplier_id:
            sup_stmt = sup_stmt.where(Supplier.id == supplier_id)

        suppliers = (await db.execute(sup_stmt)).scalars().all()
        items_out = []

        for sup in suppliers:
            # Query POs
            pos = (await db.execute(
                select(PurchaseOrder).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.is_deleted == False)
            )).scalars().all()

            total_pos = len(pos)
            completed_pos = sum(1 for p in pos if p.status == "COMPLETED")
            open_pos = [p for p in pos if p.status in ["APPROVED", "PARTIALLY_RECEIVED"]]
            open_count = len(open_pos)
            open_val = sum([Decimal(str(p.total_amount or 0.0)) for p in open_pos], Decimal("0.0"))
            total_spend = sum([Decimal(str(p.total_amount or 0.0)) for p in pos if p.status in ["COMPLETED", "PARTIALLY_RECEIVED"]], Decimal("0.0"))

            # Query GRNs for Lead Time & On-Time Delivery
            gr_stmt = (
                select(GoodsReceipt, PurchaseOrder)
                .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
                .where(PurchaseOrder.supplier_id == sup.id)
            )
            gr_rows = (await db.execute(gr_stmt)).fetchall()

            lead_times = []
            on_time_count = 0
            evaluated_otd_count = 0

            for gr, po in gr_rows:
                if po.ordered_at and gr.received_at:
                    gr_rec = gr.received_at.replace(tzinfo=timezone.utc) if gr.received_at.tzinfo is None else gr.received_at
                    po_app = po.ordered_at.replace(tzinfo=timezone.utc) if po.ordered_at.tzinfo is None else po.ordered_at
                    lead_times.append(max(0, (gr_rec - po_app).days))

                if po.expected_delivery_at and gr.received_at:
                    evaluated_otd_count += 1
                    exp_del = po.expected_delivery_at.replace(tzinfo=timezone.utc) if po.expected_delivery_at.tzinfo is None else po.expected_delivery_at
                    gr_rec = gr.received_at.replace(tzinfo=timezone.utc) if gr.received_at.tzinfo is None else gr.received_at
                    if gr_rec <= exp_del + timedelta(hours=23, minutes=59):
                        on_time_count += 1

            avg_lead = (sum(lead_times) / len(lead_times)) if lead_times else None
            median_lead = (sorted(lead_times)[len(lead_times) // 2]) if lead_times else None
            otd_pct = float(quantize_decimal((Decimal(str(on_time_count)) / Decimal(str(evaluated_otd_count)) * Decimal("100.0")), 1)) if evaluated_otd_count > 0 else 100.0

            # Fill rate
            po_lines_stmt = (
                select(func.sum(POLineItem.quantity_ordered), func.sum(POLineItem.quantity_received))
                .join(PurchaseOrder, POLineItem.purchase_order_id == PurchaseOrder.id)
                .where(PurchaseOrder.supplier_id == sup.id)
            )
            ord_sum, rec_sum = (await db.execute(po_lines_stmt)).first() or (0.0, 0.0)
            ord_qty = Decimal(str(ord_sum or 0.0))
            rec_qty = Decimal(str(rec_sum or 0.0))
            fill_rate = float(quantize_decimal((rec_qty / ord_qty * Decimal("100.0")), 1)) if ord_qty > 0 else 100.0

            # PPV for supplier
            ppv_res = await ProcurementService.get_purchase_price_variance_report(db, tenant_id, supplier_id=sup.id)

            items_out.append(SupplierScorecardItem(
                supplier_id=sup.id,
                supplier_name=sup.name,
                supplier_code=sup.code,
                status=sup.status,
                total_orders_placed=total_pos,
                total_orders_completed=completed_pos,
                open_orders_count=open_count,
                open_orders_value=float(open_val),
                total_spend=float(total_spend),
                average_lead_time_days=avg_lead,
                median_lead_time_days=float(median_lead) if median_lead is not None else None,
                on_time_delivery_rate_percentage=otd_pct,
                fulfillment_fill_rate_percentage=fill_rate,
                net_purchase_price_variance=ppv_res.net_ppv_amount
            ))

        return SupplierScorecardResponse(
            total_suppliers=len(items_out),
            scorecards=items_out,
            generated_at=now
        )

    @staticmethod
    async def get_procurement_dashboard(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> ProcurementDashboardResponse:
        """
        Aggregates procurement operational KPIs, draft counts, pending approvals, overdue POs, and scorecards.
        """
        now = get_utc_now()
        
        # 1. PO status breakdown
        po_stmt = select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
        if warehouse_id:
            po_stmt = po_stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)

        all_pos = (await db.execute(po_stmt)).scalars().all()

        draft_cnt = sum(1 for p in all_pos if p.status == "DRAFT")
        pending_cnt = sum(1 for p in all_pos if p.status == "PENDING_APPROVAL")
        open_pos = [p for p in all_pos if p.status in ["APPROVED", "PARTIALLY_RECEIVED"]]
        open_cnt = len(open_pos)
        open_val = sum([Decimal(str(p.total_amount or 0.0)) for p in open_pos], Decimal("0.0"))

        overdue_cnt = 0
        for p in open_pos:
            if p.expected_delivery_at:
                exp = p.expected_delivery_at.replace(tzinfo=timezone.utc) if p.expected_delivery_at.tzinfo is None else p.expected_delivery_at
                if exp < now:
                    overdue_cnt += 1

        # 2. Active suppliers count
        sup_stmt = select(func.count(Supplier.id)).where(Supplier.tenant_id == tenant_id, Supplier.status == "ACTIVE", Supplier.is_deleted == False)
        sup_cnt = (await db.execute(sup_stmt)).scalar() or 0

        # 3. Replenishment Suggestions
        sugg_res = await ProcurementService.get_purchase_suggestions(db, tenant_id, warehouse_id=warehouse_id)
        
        # 4. PPV 30d
        ppv_res = await ProcurementService.get_purchase_price_variance_report(db, tenant_id, days_back=30)

        # 5. Scorecards
        scorecards_res = await ProcurementService.get_supplier_scorecards(db, tenant_id)

        return ProcurementDashboardResponse(
            total_open_pos_count=open_cnt,
            total_open_pos_value=float(open_val),
            draft_pos_count=draft_cnt,
            pending_approvals_count=pending_cnt,
            overdue_pos_count=overdue_cnt,
            total_active_suppliers=sup_cnt,
            suggestions_reorder_count=sugg_res.reorder_required_count,
            suggestions_critical_count=sugg_res.critical_stockout_count,
            total_suggested_spend=sugg_res.total_estimated_spend,
            net_30d_ppv=ppv_res.net_ppv_amount,
            scorecards=scorecards_res.scorecards[:10],
            generated_at=now
        )
