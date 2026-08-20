import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockLedgerTransaction, StockLedgerEntry, StockBalanceCache
from app.models.sales import SalesOrder, SOLineItem, Shipment
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, Supplier
from app.services.costing_service import quantize_decimal
from app.schemas.analytics import (
    InventoryAgingReportResponse, AgingBucketDetail,
    InventoryTurnoverReportResponse, TurnoverMetricItem,
    StockClassificationReportResponse, StockMovementClassificationItem,
    DemandAndUsageResponse, UsageTimeBucket,
    ReplenishmentRecommendationsResponse, ReplenishmentRecommendationItem,
    SupplierAnalyticsResponse, SupplierPerformanceItem,
    ExecutiveInventoryDashboardResponse
)

class AnalyticsService:
    @staticmethod
    async def get_inventory_aging(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        category_id: Optional[str] = None
    ) -> InventoryAgingReportResponse:
        """
        Calculates operational inventory aging across 6 standard duration buckets
        using authoritative CostLayer acquisition timestamps.
        """
        stmt = (
            select(CostLayer, ItemVariant, Item)
            .join(ItemVariant, CostLayer.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(
                CostLayer.tenant_id == tenant_id,
                CostLayer.status == "ACTIVE",
                CostLayer.remaining_quantity > 0,
                CostLayer.is_deleted == False
            )
        )
        if warehouse_id:
            stmt = stmt.where(CostLayer.warehouse_id == warehouse_id)
        if category_id:
            stmt = stmt.where(Item.category_id == category_id)

        res = await db.execute(stmt)
        rows = res.fetchall()

        now = get_utc_now()
        buckets_def = [
            {"name": "0-30 Days", "min": 0, "max": 30, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
            {"name": "31-60 Days", "min": 31, "max": 60, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
            {"name": "61-90 Days", "min": 61, "max": 90, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
            {"name": "91-180 Days", "min": 91, "max": 180, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
            {"name": "181-365 Days", "min": 181, "max": 365, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
            {"name": "365+ Days", "min": 366, "max": None, "qty": Decimal("0.0"), "val": Decimal("0.0"), "items": set()},
        ]

        total_qty = Decimal("0.0")
        total_val = Decimal("0.0")

        for layer, var, itm in rows:
            rem_qty = Decimal(str(layer.remaining_quantity))
            unit_c = Decimal(str(layer.unit_cost))
            layer_val = quantize_decimal(rem_qty * unit_c)

            layer_ts = layer.layer_timestamp
            if layer_ts.tzinfo is None:
                layer_ts = layer_ts.replace(tzinfo=timezone.utc)
            delta_days = (now - layer_ts).days
            if delta_days < 0:
                delta_days = 0

            total_qty += rem_qty
            total_val += layer_val

            for b in buckets_def:
                if b["max"] is not None:
                    if b["min"] <= delta_days <= b["max"]:
                        b["qty"] += rem_qty
                        b["val"] += layer_val
                        b["items"].add(var.id)
                        break
                else:
                    if delta_days >= b["min"]:
                        b["qty"] += rem_qty
                        b["val"] += layer_val
                        b["items"].add(var.id)
                        break

        bucket_details = []
        for b in buckets_def:
            b_val = b["val"]
            pct = float(quantize_decimal((b_val / total_val * Decimal("100.0")), 2)) if total_val > 0 else 0.0
            bucket_details.append(AgingBucketDetail(
                bucket_name=b["name"],
                min_days=b["min"],
                max_days=b["max"],
                total_quantity=float(b["qty"]),
                total_value=float(b_val),
                item_count=len(b["items"]),
                percentage_of_total_value=pct
            ))

        return InventoryAgingReportResponse(
            total_inventory_quantity=float(total_qty),
            total_inventory_value=float(total_val),
            buckets=bucket_details,
            generated_at=now
        )

    @staticmethod
    async def get_inventory_turnover(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        period_days: int = 90
    ) -> InventoryTurnoverReportResponse:
        """
        Calculates Inventory Turnover Ratio and Days Inventory Outstanding (DIO)
        over the specified measurement window.
        """
        now = get_utc_now()
        start_date = now - timedelta(days=period_days)

        # 1. Period COGS per variant
        cogs_stmt = (
            select(
                COGSRecord.item_variant_id,
                func.sum(COGSRecord.total_cogs_amount)
            )
            .where(
                COGSRecord.tenant_id == tenant_id,
                COGSRecord.recognized_at >= start_date,
                COGSRecord.recognized_at <= now,
                COGSRecord.is_deleted == False
            )
            .group_by(COGSRecord.item_variant_id)
        )
        cogs_res = await db.execute(cogs_stmt)
        cogs_by_variant = {row[0]: Decimal(str(row[1] or 0.0)) for row in cogs_res.fetchall()}

        # 2. Profiles and Items
        prof_stmt = (
            select(ItemCostProfile, ItemVariant, Item, ItemCategory)
            .join(ItemVariant, ItemCostProfile.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .outerjoin(ItemCategory, Item.category_id == ItemCategory.id)
            .where(ItemCostProfile.tenant_id == tenant_id, ItemCostProfile.is_deleted == False)
        )
        if warehouse_id:
            prof_stmt = prof_stmt.where(ItemCostProfile.warehouse_id == warehouse_id)

        prof_res = await db.execute(prof_stmt)
        rows = prof_res.fetchall()

        items_out = []
        enterprise_cogs = Decimal("0.0")
        enterprise_val = Decimal("0.0")

        # Group by variant (in case multi-warehouse)
        grouped_variants: Dict[str, Dict[str, Any]] = {}
        for prof, var, itm, cat in rows:
            vid = var.id
            if vid not in grouped_variants:
                grouped_variants[vid] = {
                    "variant": var,
                    "item": itm,
                    "category": cat,
                    "quantity": Decimal("0.0"),
                    "valuation": Decimal("0.0"),
                }
            grouped_variants[vid]["quantity"] += Decimal(str(prof.current_quantity))
            grouped_variants[vid]["valuation"] += Decimal(str(prof.current_total_value))

        for vid, data in grouped_variants.items():
            var = data["variant"]
            itm = data["item"]
            cat = data["category"]
            qty = data["quantity"]
            val = data["valuation"]
            var_cogs = cogs_by_variant.get(vid, Decimal("0.0"))

            enterprise_cogs += var_cogs
            enterprise_val += val

            # Annualized Turnover = (COGS / AvgInv) * (365 / period_days)
            annual_factor = Decimal("365.0") / Decimal(str(period_days))
            if val > 0:
                itr = quantize_decimal((var_cogs / val) * annual_factor, 2)
                dio = float(quantize_decimal((val / var_cogs) * Decimal(str(period_days)), 1)) if var_cogs > 0 else None
            else:
                itr = Decimal("0.0")
                dio = 0.0 if var_cogs > 0 else None

            if itr >= Decimal("6.0"):
                vel = "FAST_VELOCITY"
            elif itr >= Decimal("2.0"):
                vel = "NORMAL_VELOCITY"
            elif itr > Decimal("0.0"):
                vel = "SLOW_VELOCITY"
            else:
                vel = "DORMANT"

            items_out.append(TurnoverMetricItem(
                item_id=itm.id,
                item_sku=itm.sku,
                item_name=itm.name,
                variant_id=var.id,
                variant_sku=var.variant_sku,
                category_name=cat.name if cat else None,
                cogs_period=float(var_cogs),
                average_inventory_value=float(val),
                current_quantity_on_hand=float(qty),
                turnover_ratio=float(itr),
                days_inventory_outstanding=dio,
                velocity_status=vel
            ))

        ent_annual_factor = Decimal("365.0") / Decimal(str(period_days))
        ent_itr = quantize_decimal((enterprise_cogs / enterprise_val) * ent_annual_factor, 2) if enterprise_val > 0 else Decimal("0.0")
        ent_dio = float(quantize_decimal((enterprise_val / enterprise_cogs) * Decimal(str(period_days)), 1)) if enterprise_cogs > 0 else None

        return InventoryTurnoverReportResponse(
            period_days=period_days,
            period_start=start_date,
            period_end=now,
            enterprise_cogs=float(enterprise_cogs),
            enterprise_average_inventory=float(enterprise_val),
            enterprise_turnover_ratio=float(ent_itr),
            enterprise_dio=ent_dio,
            items=items_out,
            generated_at=now
        )

    @staticmethod
    async def get_slow_moving_and_dead_stock(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> StockClassificationReportResponse:
        """
        Classifies stock into FAST_MOVING, NORMAL, SLOW_MOVING, and DEAD_STOCK
        based on days since last dispatch, turnover velocity, and DIO.
        """
        now = get_utc_now()
        turnover_report = await AnalyticsService.get_inventory_turnover(db, tenant_id, warehouse_id, period_days=90)
        turnover_by_vid = {item.variant_id: item for item in turnover_report.items}

        # Query last dispatch date per variant
        last_disp_stmt = (
            select(COGSRecord.item_variant_id, func.max(COGSRecord.recognized_at))
            .where(COGSRecord.tenant_id == tenant_id, COGSRecord.is_deleted == False)
            .group_by(COGSRecord.item_variant_id)
        )
        last_disp_res = await db.execute(last_disp_stmt)
        last_dispatch_dates = {row[0]: row[1] for row in last_disp_res.fetchall()}

        items_out = []
        slow_val = Decimal("0.0")
        dead_val = Decimal("0.0")
        counts = {"FAST_MOVING": 0, "NORMAL": 0, "SLOW_MOVING": 0, "DEAD_STOCK": 0, "OUT_OF_STOCK": 0}

        for vid, t_item in turnover_by_vid.items():
            qty = Decimal(str(t_item.current_quantity_on_hand))
            val = Decimal(str(t_item.average_inventory_value))
            last_date = last_dispatch_dates.get(vid)

            if last_date:
                if last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=timezone.utc)
                days_since = (now - last_date).days
            else:
                days_since = 999

            if qty <= 0:
                cls = "OUT_OF_STOCK"
            elif days_since > 180:
                cls = "DEAD_STOCK"
                dead_val += val
            elif days_since > 90 or (t_item.days_inventory_outstanding and t_item.days_inventory_outstanding > 120):
                cls = "SLOW_MOVING"
                slow_val += val
            elif t_item.turnover_ratio >= 6.0 and days_since <= 30:
                cls = "FAST_MOVING"
            else:
                cls = "NORMAL"

            counts[cls] = counts.get(cls, 0) + 1

            items_out.append(StockMovementClassificationItem(
                variant_id=t_item.variant_id,
                variant_sku=t_item.variant_sku,
                item_name=t_item.item_name,
                category_name=t_item.category_name,
                classification=cls,
                quantity_on_hand=float(qty),
                current_valuation=float(val),
                days_since_last_dispatch=days_since if days_since != 999 else None,
                last_dispatch_date=last_date,
                turnover_ratio=t_item.turnover_ratio,
                days_inventory_outstanding=t_item.days_inventory_outstanding
            ))

        return StockClassificationReportResponse(
            total_slow_moving_value=float(slow_val),
            total_dead_stock_value=float(dead_val),
            fast_moving_count=counts.get("FAST_MOVING", 0),
            normal_count=counts.get("NORMAL", 0),
            slow_moving_count=counts.get("SLOW_MOVING", 0),
            dead_stock_count=counts.get("DEAD_STOCK", 0),
            items=items_out,
            generated_at=now
        )

    @staticmethod
    async def get_demand_and_usage(
        db: AsyncSession,
        tenant_id: str,
        variant_id: str,
        warehouse_id: Optional[str] = None,
        period_days: int = 90
    ) -> DemandAndUsageResponse:
        """
        Calculates granular historical consumption velocity, multi-window ADU, and demand trends.
        """
        now = get_utc_now()
        start_date = now - timedelta(days=period_days)

        # Variant details
        var_stmt = (
            select(ItemVariant, Item)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(ItemVariant.id == variant_id, Item.tenant_id == tenant_id)
        )
        var_res = await db.execute(var_stmt)
        var_row = var_res.first()
        if not var_row:
            raise HTTPException(status_code=404, detail="Item variant not found in tenant")
        variant, item = var_row

        # Query outbound shipments from StockLedgerEntry
        entry_stmt = (
            select(StockLedgerEntry, StockLedgerTransaction)
            .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
            .where(
                StockLedgerTransaction.tenant_id == tenant_id,
                StockLedgerEntry.item_variant_id == variant_id,
                StockLedgerTransaction.transaction_type == "SALES_SHIPMENT",
                StockLedgerTransaction.posted_at >= (now - timedelta(days=180))
            )
        )
        entry_res = await db.execute(entry_stmt)
        entries = entry_res.fetchall()

        # Compute ADU over 30d, 90d, 180d
        sum_30d = Decimal("0.0")
        sum_90d = Decimal("0.0")
        sum_180d = Decimal("0.0")
        total_period_consumed = Decimal("0.0")

        # Time buckets (weekly over period_days)
        bucket_count = max(1, period_days // 7)
        buckets = []
        for i in range(bucket_count):
            b_end = now - timedelta(days=i * 7)
            b_start = b_end - timedelta(days=7)
            buckets.append({
                "label": f"Week -{i+1}",
                "start": b_start,
                "end": b_end,
                "qty": Decimal("0.0"),
                "cost": Decimal("0.0"),
                "dispatches": 0
            })

        for entry, tx in entries:
            ts = tx.posted_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta_days = (now - ts).days
            qty = Decimal(str(entry.quantity))
            cost = Decimal(str(entry.total_cost))

            if delta_days <= 30:
                sum_30d += qty
            if delta_days <= 90:
                sum_90d += qty
                total_period_consumed += qty
            if delta_days <= 180:
                sum_180d += qty

            for b in buckets:
                if b["start"] <= ts < b["end"]:
                    b["qty"] += qty
                    b["cost"] += cost
                    b["dispatches"] += 1
                    break

        adu_30 = quantize_decimal(sum_30d / Decimal("30.0"), 4)
        adu_90 = quantize_decimal(sum_90d / Decimal("90.0"), 4)
        adu_180 = quantize_decimal(sum_180d / Decimal("180.0"), 4)

        if adu_90 > 0:
            trend_pct = float(quantize_decimal(((adu_30 - adu_90) / adu_90) * Decimal("100.0"), 2))
        else:
            trend_pct = 0.0

        if trend_pct > 15.0:
            trend_dir = "ACCELERATING"
        elif trend_pct < -15.0:
            trend_dir = "DECELERATING"
        else:
            trend_dir = "STABLE"

        buckets_out = [
            UsageTimeBucket(
                period_label=b["label"],
                start_date=b["start"],
                end_date=b["end"],
                consumed_quantity=float(b["qty"]),
                consumed_cost=float(b["cost"]),
                dispatch_count=b["dispatches"]
            )
            for b in reversed(buckets)
        ]

        return DemandAndUsageResponse(
            variant_id=variant.id,
            variant_sku=variant.variant_sku,
            item_name=item.name,
            measurement_period_days=period_days,
            total_consumed_quantity=float(total_period_consumed),
            average_daily_usage_30d=float(adu_30),
            average_daily_usage_90d=float(adu_90),
            average_daily_usage_180d=float(adu_180),
            usage_trend_percentage=trend_pct,
            trend_direction=trend_dir,
            time_buckets=buckets_out,
            generated_at=now
        )

    @staticmethod
    async def get_replenishment_recommendations(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> ReplenishmentRecommendationsResponse:
        """
        Calculates deterministic replenishment recommendations (ROP and RPQ)
        constrained by lead times, safety stocks, MOQs, and pack sizes.
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
                func.sum(POLineItem.quantity_ordered - POLineItem.quantity_received)
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
        incoming_by_wh_var = {(row[0], row[1]): Decimal(str(row[2] or 0.0)) for row in po_res.fetchall()}

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

        # 4. Fetch all active variants and warehouses
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

        recommendations = []
        total_skus = 0
        reorder_count = 0
        stockout_count = 0
        total_spend = Decimal("0.0")

        for wh in warehouses:
            for variant, item in var_rows:
                total_skus += 1
                key = (wh.id, variant.id)
                on_hand, allocated = balances.get(key, (Decimal("0.0"), Decimal("0.0")))
                available = max(Decimal("0.0"), on_hand - allocated)
                incoming = incoming_by_wh_var.get(key, Decimal("0.0"))

                # ADU
                consumed_90d = cogs_90d.get(variant.id, Decimal("0.0"))
                adu = quantize_decimal(consumed_90d / Decimal("90.0"), 4)

                lead_time = 14 # default lead time days
                safety_stock = quantize_decimal(adu * Decimal("7.0"), 2) if adu > 0 else Decimal("10.0")
                rop = quantize_decimal((adu * Decimal(str(lead_time))) + safety_stock, 2)
                target_stock = quantize_decimal(rop + (adu * Decimal("30.0")), 2)

                raw_rpq = max(Decimal("0.0"), target_stock - (available + incoming))

                moq = Decimal("1.0")
                pack_size = Decimal("1.0")

                if raw_rpq > 0:
                    # Constrain with Pack Size and MOQ
                    packs = math.ceil(float(raw_rpq / pack_size))
                    constrained_rpq = max(moq, Decimal(str(packs)) * pack_size)
                else:
                    constrained_rpq = Decimal("0.0")

                cost_price = Decimal(str(variant.cost_price or 0.0))
                est_cost = quantize_decimal(constrained_rpq * cost_price, 2)

                # Urgency determination
                if available == 0 and adu > 0:
                    urgency = "CRITICAL_STOCKOUT"
                    stockout_count += 1
                    reorder_count += 1
                    total_spend += est_cost
                elif (available + incoming) <= rop and constrained_rpq > 0:
                    urgency = "REORDER_REQUIRED"
                    reorder_count += 1
                    total_spend += est_cost
                else:
                    urgency = "HEALTHY"

                recommendations.append(ReplenishmentRecommendationItem(
                    variant_id=variant.id,
                    variant_sku=variant.variant_sku,
                    item_name=item.name,
                    warehouse_id=wh.id,
                    warehouse_name=wh.name,
                    quantity_on_hand=float(on_hand),
                    quantity_allocated=float(allocated),
                    quantity_available=float(available),
                    incoming_on_po=float(incoming),
                    average_daily_usage=float(adu),
                    lead_time_days=lead_time,
                    safety_stock=float(safety_stock),
                    reorder_point=float(rop),
                    target_stock=float(target_stock),
                    raw_recommended_quantity=float(raw_rpq),
                    recommended_order_quantity=float(constrained_rpq),
                    minimum_order_quantity=float(moq),
                    pack_size=float(pack_size),
                    estimated_reorder_cost=float(est_cost),
                    urgency=urgency
                ))

        # Sort recommendations: Critical first, then Reorder Required, then healthy
        urgency_order = {"CRITICAL_STOCKOUT": 0, "REORDER_REQUIRED": 1, "HEALTHY": 2}
        recommendations.sort(key=lambda r: (urgency_order[r.urgency], -r.estimated_reorder_cost))

        return ReplenishmentRecommendationsResponse(
            total_skus_evaluated=total_skus,
            skus_requiring_reorder=reorder_count,
            critical_stockout_skus=stockout_count,
            total_recommended_spend=float(total_spend),
            recommendations=recommendations,
            generated_at=now
        )

    @staticmethod
    async def get_supplier_analytics(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: Optional[str] = None
    ) -> SupplierAnalyticsResponse:
        """
        Aggregates supplier performance, actual historical lead time, fill rate %, and open commitments.
        """
        now = get_utc_now()
        sup_stmt = select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
        if supplier_id:
            sup_stmt = sup_stmt.where(Supplier.id == supplier_id)

        suppliers = (await db.execute(sup_stmt)).scalars().all()

        items_out = []
        for sup in suppliers:
            # Query POs
            po_stmt = select(PurchaseOrder).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.is_deleted == False)
            pos = (await db.execute(po_stmt)).scalars().all()

            total_orders = len(pos)
            completed_orders = sum(1 for p in pos if p.status == "COMPLETED")
            open_pos = [p for p in pos if p.status in ["APPROVED", "PARTIALLY_RECEIVED"]]
            open_po_count = len(open_pos)
            open_po_val = sum([Decimal(str(p.total_amount or 0.0)) for p in open_pos], Decimal("0.0"))
            total_spend = sum([Decimal(str(p.total_amount or 0.0)) for p in pos if p.status in ["COMPLETED", "PARTIALLY_RECEIVED"]], Decimal("0.0"))

            # Calculate average lead time from GRNs
            gr_stmt = (
                select(GoodsReceipt, PurchaseOrder)
                .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
                .where(PurchaseOrder.supplier_id == sup.id)
            )
            gr_rows = (await db.execute(gr_stmt)).fetchall()

            lead_times = []
            for gr, po in gr_rows:
                if po.ordered_at and gr.received_at:
                    gr_rec = gr.received_at.replace(tzinfo=timezone.utc) if gr.received_at.tzinfo is None else gr.received_at
                    po_app = po.ordered_at.replace(tzinfo=timezone.utc) if po.ordered_at.tzinfo is None else po.ordered_at
                    delta = (gr_rec - po_app).days
                    if delta >= 0:
                        lead_times.append(delta)

            avg_lead_time = (sum(lead_times) / len(lead_times)) if lead_times else None

            # Calculate fill rate
            po_lines_stmt = (
                select(func.sum(POLineItem.quantity_ordered), func.sum(POLineItem.quantity_received))
                .join(PurchaseOrder, POLineItem.purchase_order_id == PurchaseOrder.id)
                .where(PurchaseOrder.supplier_id == sup.id)
            )
            ord_sum, rec_sum = (await db.execute(po_lines_stmt)).first() or (0.0, 0.0)
            ord_qty = Decimal(str(ord_sum or 0.0))
            rec_qty = Decimal(str(rec_sum or 0.0))
            fill_rate = float(quantize_decimal((rec_qty / ord_qty * Decimal("100.0")), 1)) if ord_qty > 0 else 100.0

            items_out.append(SupplierPerformanceItem(
                supplier_id=sup.id,
                supplier_name=sup.name,
                supplier_code=sup.code,
                total_orders_placed=total_orders,
                total_orders_completed=completed_orders,
                average_lead_time_days=avg_lead_time,
                fulfillment_fill_rate_percentage=fill_rate,
                total_spend=float(total_spend),
                open_po_count=open_po_count,
                open_po_value=float(open_po_val)
            ))

        return SupplierAnalyticsResponse(
            total_suppliers_evaluated=len(items_out),
            suppliers=items_out,
            generated_at=now
        )

    @staticmethod
    async def get_executive_dashboard(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> ExecutiveInventoryDashboardResponse:
        """
        Aggregates enterprise inventory health metrics into an executive dashboard view.
        """
        now = get_utc_now()
        aging = await AnalyticsService.get_inventory_aging(db, tenant_id, warehouse_id)
        turnover = await AnalyticsService.get_inventory_turnover(db, tenant_id, warehouse_id, period_days=90)
        movement = await AnalyticsService.get_slow_moving_and_dead_stock(db, tenant_id, warehouse_id)
        replenishment = await AnalyticsService.get_replenishment_recommendations(db, tenant_id, warehouse_id)

        aging_summary = {b.bucket_name: b.total_value for b in aging.buckets}
        fast_moving = [m for m in movement.items if m.classification == "FAST_MOVING"][:5]

        # Active SKU count
        var_stmt = select(func.count(ItemVariant.id)).join(Item, ItemVariant.item_id == Item.id).where(Item.tenant_id == tenant_id, Item.is_deleted == False)
        sku_count = (await db.execute(var_stmt)).scalar() or 0

        # Low stock count
        low_stock_count = sum(1 for r in replenishment.recommendations if r.urgency in ["CRITICAL_STOCKOUT", "REORDER_REQUIRED"])

        return ExecutiveInventoryDashboardResponse(
            total_inventory_valuation=aging.total_inventory_value,
            total_units_on_hand=aging.total_inventory_quantity,
            active_sku_count=sku_count,
            annualized_turnover_ratio=turnover.enterprise_turnover_ratio,
            days_inventory_outstanding=turnover.enterprise_dio,
            low_stock_sku_count=low_stock_count,
            slow_moving_valuation=movement.total_slow_moving_value,
            dead_stock_valuation=movement.total_dead_stock_value,
            reorder_required_sku_count=replenishment.skus_requiring_reorder,
            aging_summary=aging_summary,
            top_fast_moving_items=fast_moving,
            generated_at=now
        )
