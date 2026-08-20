import uuid
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc, case
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.purchasing import PurchaseOrder, POLineItem, Supplier, SupplierProduct
from app.models.manufacturing import WorkOrder, WorkOrderComponent
from app.models.costing import COGSRecord
from app.models.replenishment import (
    ReplenishmentConfig,
    ReplenishmentRun,
    ReplenishmentRecommendationItem
)
from app.schemas.replenishment import (
    ReplenishmentConfigCreate,
    GenerateDraftPOsRequest,
    GenerateDraftPOsResponse,
    GenerateDraftPOResultItem
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.costing_service import quantize_decimal

class ReplenishmentService:
    @staticmethod
    async def upsert_config(
        db: AsyncSession,
        tenant_id: str,
        cfg_in: ReplenishmentConfigCreate,
        user_id: Optional[str] = None
    ) -> ReplenishmentConfig:
        stmt = select(ReplenishmentConfig).where(
            ReplenishmentConfig.tenant_id == tenant_id,
            ReplenishmentConfig.item_variant_id == cfg_in.item_variant_id,
            ReplenishmentConfig.warehouse_id == cfg_in.warehouse_id
        ).with_for_update()
        cfg = (await db.execute(stmt)).scalar_one_or_none()

        if not cfg:
            cfg = ReplenishmentConfig(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                item_variant_id=cfg_in.item_variant_id,
                warehouse_id=cfg_in.warehouse_id,
                reorder_method=cfg_in.reorder_method or "DYNAMIC_ROP",
                min_quantity=cfg_in.min_quantity,
                max_quantity=cfg_in.max_quantity,
                safety_stock_days=cfg_in.safety_stock_days or 7,
                target_coverage_days=cfg_in.target_coverage_days or 30,
                fixed_safety_stock=cfg_in.fixed_safety_stock,
                is_active=cfg_in.is_active if cfg_in.is_active is not None else True
            )
            db.add(cfg)
        else:
            cfg.reorder_method = cfg_in.reorder_method or cfg.reorder_method
            cfg.min_quantity = cfg_in.min_quantity
            cfg.max_quantity = cfg_in.max_quantity
            cfg.safety_stock_days = cfg_in.safety_stock_days or cfg.safety_stock_days
            cfg.target_coverage_days = cfg_in.target_coverage_days or cfg.target_coverage_days
            cfg.fixed_safety_stock = cfg_in.fixed_safety_stock
            cfg.is_active = cfg_in.is_active if cfg_in.is_active is not None else cfg.is_active

        await db.commit()
        await db.refresh(cfg)
        return cfg

    @staticmethod
    async def execute_replenishment_run(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> ReplenishmentRun:
        now = get_utc_now()
        start_30d = now - timedelta(days=30)
        start_90d = now - timedelta(days=90)
        start_180d = now - timedelta(days=180)

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

        # 2. Fetch incoming PO quantities
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

        # 3. Fetch unreserved PLANNED manufacturing component demand
        mfg_stmt = (
            select(
                WorkOrder.warehouse_id,
                WorkOrderComponent.component_variant_id,
                func.sum(WorkOrderComponent.quantity_required - WorkOrderComponent.quantity_consumed)
            )
            .join(WorkOrder, WorkOrderComponent.work_order_id == WorkOrder.id)
            .where(
                WorkOrder.tenant_id == tenant_id,
                WorkOrder.status == "PLANNED",
                WorkOrder.is_deleted == False
            )
        )
        if warehouse_id:
            mfg_stmt = mfg_stmt.where(WorkOrder.warehouse_id == warehouse_id)

        mfg_stmt = mfg_stmt.group_by(WorkOrder.warehouse_id, WorkOrderComponent.component_variant_id)
        mfg_res = await db.execute(mfg_stmt)
        mfg_demand_by_wh_var = {(row[0], row[1]): Decimal(str(row[2] or 0.0)) for row in mfg_res.fetchall()}

        # 4. Fetch historical COGS consumption (30d, 90d, 180d)
        cogs_stmt = (
            select(
                COGSRecord.item_variant_id,
                func.sum(case((COGSRecord.recognized_at >= start_30d, COGSRecord.quantity_shipped), else_=0.0)),
                func.sum(case((COGSRecord.recognized_at >= start_90d, COGSRecord.quantity_shipped), else_=0.0)),
                func.sum(case((COGSRecord.recognized_at >= start_180d, COGSRecord.quantity_shipped), else_=0.0)),
            )
            .where(COGSRecord.tenant_id == tenant_id, COGSRecord.is_deleted == False)
            .group_by(COGSRecord.item_variant_id)
        )
        cogs_res = await db.execute(cogs_stmt)
        cogs_history = {row[0]: (Decimal(str(row[1] or 0.0)), Decimal(str(row[2] or 0.0)), Decimal(str(row[3] or 0.0))) for row in cogs_res.fetchall()}

        # 5. Fetch all active suppliers per variant
        supp_prod_stmt = (
            select(SupplierProduct)
            .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
            .where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.is_active == True,
                Supplier.is_active == True
            )
            .order_by(SupplierProduct.is_preferred.desc(), SupplierProduct.unit_cost.asc())
        )
        supp_prod_res = await db.execute(supp_prod_stmt)
        supp_products = supp_prod_res.scalars().all()
        # Key by item_variant_id -> first one is preferred or lowest cost
        supplier_map: Dict[str, SupplierProduct] = {}
        for sp in supp_products:
            if sp.item_variant_id not in supplier_map:
                supplier_map[sp.item_variant_id] = sp

        # 6. Fetch ReplenishmentConfigs
        cfg_stmt = select(ReplenishmentConfig).where(ReplenishmentConfig.tenant_id == tenant_id, ReplenishmentConfig.is_active == True)
        cfgs = (await db.execute(cfg_stmt)).scalars().all()
        cfg_map: Dict[Tuple[Optional[str], str], ReplenishmentConfig] = {}
        for c in cfgs:
            cfg_map[(c.warehouse_id, c.item_variant_id)] = c

        # 7. Warehouses and Item Variants
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

        run_num = await SequenceService.generate_next_number(db, tenant_id, "REPLENISHMENT_RUN", custom_prefix="RPL")
        rep_run = ReplenishmentRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            run_number=run_num,
            warehouse_id=warehouse_id,
            triggered_by_user_id=user_id,
            total_skus_evaluated=0,
            total_recommendations=0,
            total_estimated_spend=Decimal("0.0"),
            status="COMPLETED"
        )
        db.add(rep_run)
        await db.flush()

        total_skus = 0
        total_recs = 0
        total_spend = Decimal("0.0")

        for wh in warehouses:
            for variant, item in var_rows:
                total_skus += 1
                key = (wh.id, variant.id)
                on_hand, allocated = balances.get(key, (Decimal("0.0"), Decimal("0.0")))
                avail = max(Decimal("0.0"), on_hand - allocated)
                incoming = incoming_by_wh_var.get(key, Decimal("0.0"))
                mfg_demand = mfg_demand_by_wh_var.get(key, Decimal("0.0"))

                # Net Inventory Position
                nip = avail + incoming - mfg_demand

                # Calculate ADU
                c30, c90, c180 = cogs_history.get(variant.id, (Decimal("0.0"), Decimal("0.0"), Decimal("0.0")))
                adu30 = quantize_decimal(c30 / Decimal("30.0"), 4)
                adu90 = quantize_decimal(c90 / Decimal("90.0"), 4)
                adu180 = quantize_decimal(c180 / Decimal("180.0"), 4)
                effective_adu = quantize_decimal(
                    (Decimal("0.50") * adu30) + (Decimal("0.35") * adu90) + (Decimal("0.15") * adu180), 4
                )

                # Fetch config or default
                cfg = cfg_map.get((wh.id, variant.id)) or cfg_map.get((None, variant.id))
                safety_days = cfg.safety_stock_days if cfg else 7
                cov_days = cfg.target_coverage_days if cfg else 30

                # Supplier params
                sp = supplier_map.get(variant.id)
                lead_time = sp.lead_time_days if sp else 14
                moq = sp.minimum_order_quantity if sp else Decimal("1.0")
                pack_size = sp.pack_size if sp else Decimal("1.0")
                unit_cost = sp.unit_cost if sp else Decimal(str(variant.cost_price or 0.0))
                supp_id = sp.supplier_id if sp else None

                # Safety Stock & ROP
                if cfg and cfg.reorder_method == "MIN_MAX" and cfg.min_quantity is not None:
                    rop = cfg.min_quantity
                    target_stock = cfg.max_quantity or (rop * Decimal("2.0"))
                    safety_stock = rop * Decimal("0.3")
                else:
                    if cfg and cfg.fixed_safety_stock is not None:
                        safety_stock = cfg.fixed_safety_stock
                    else:
                        safety_stock = quantize_decimal(effective_adu * Decimal(str(safety_days)), 2) if effective_adu > 0 else Decimal("10.0")
                    rop = quantize_decimal((effective_adu * Decimal(str(lead_time))) + safety_stock, 2)
                    target_stock = quantize_decimal(rop + (effective_adu * Decimal(str(cov_days))), 2)

                # Suggested Reorder Quantity
                raw_rpq = max(Decimal("0.0"), target_stock - nip)
                if nip <= rop and raw_rpq > 0:
                    packs = math.ceil(float(raw_rpq / pack_size))
                    packed_qty = Decimal(str(packs)) * pack_size
                    suggested_qty = max(moq, packed_qty).quantize(Decimal("0.0001"))
                else:
                    suggested_qty = Decimal("0.0")

                # Urgency Status
                if on_hand == 0 or nip < 0:
                    urgency = "STOCKOUT_CRITICAL"
                elif nip <= rop:
                    urgency = "REORDER_NOW"
                elif nip <= (rop * Decimal("1.20")):
                    urgency = "AT_RISK"
                elif nip > (target_stock * Decimal("1.30")):
                    urgency = "OVERSTOCKED"
                else:
                    urgency = "HEALTHY"

                # Suggested order date
                if effective_adu > 0:
                    days_cov = max(0, int(float(avail / effective_adu)))
                    runout_date = now + timedelta(days=days_cov)
                    suggested_order_date = max(now, runout_date - timedelta(days=lead_time))
                else:
                    suggested_order_date = now

                item_spend = quantize_decimal(suggested_qty * unit_cost)
                if suggested_qty > 0:
                    total_recs += 1
                    total_spend += item_spend

                rec_item = ReplenishmentRecommendationItem(
                    id=str(uuid.uuid4()),
                    run_id=rep_run.id,
                    tenant_id=tenant_id,
                    warehouse_id=wh.id,
                    item_variant_id=variant.id,
                    supplier_id=supp_id,
                    quantity_on_hand=on_hand,
                    quantity_allocated=allocated,
                    quantity_available=avail,
                    quantity_incoming=incoming,
                    quantity_mfg_planned=mfg_demand,
                    net_inventory_position=nip,
                    average_daily_usage=effective_adu,
                    lead_time_days=lead_time,
                    safety_stock=safety_stock,
                    reorder_point=rop,
                    target_maximum_stock=target_stock,
                    minimum_order_quantity=moq,
                    pack_size=pack_size,
                    suggested_reorder_quantity=suggested_qty,
                    estimated_unit_cost=unit_cost,
                    estimated_total_cost=item_spend,
                    urgency_status=urgency,
                    suggested_order_date=suggested_order_date,
                    action_status="PENDING"
                )
                db.add(rec_item)

        rep_run.total_skus_evaluated = total_skus
        rep_run.total_recommendations = total_recs
        rep_run.total_estimated_spend = total_spend

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="EXECUTE_REPLENISHMENT_RUN",
            entity_type="ReplenishmentRun",
            entity_id=rep_run.id,
            user_id=user_id,
            changes={"run_number": run_num, "total_skus": total_skus, "recommendations": total_recs}
        )

        await db.commit()
        await db.refresh(rep_run)
        return rep_run

    @staticmethod
    async def generate_draft_purchase_orders(
        db: AsyncSession,
        tenant_id: str,
        req: GenerateDraftPOsRequest,
        user_id: Optional[str] = None
    ) -> GenerateDraftPOsResponse:
        """
        Converts selected ReplenishmentRecommendationItem records into Draft Purchase Orders,
        grouped by (tenant_id, supplier_id, warehouse_id).
        """
        if not req.recommendation_item_ids:
            raise HTTPException(status_code=400, detail="No recommendation items specified for PO generation")

        stmt = (
            select(ReplenishmentRecommendationItem)
            .where(
                ReplenishmentRecommendationItem.tenant_id == tenant_id,
                ReplenishmentRecommendationItem.id.in_(req.recommendation_item_ids),
                ReplenishmentRecommendationItem.action_status == "PENDING"
            )
            .with_for_update()
        )
        items = (await db.execute(stmt)).scalars().all()

        if not items:
            raise HTTPException(status_code=400, detail="No pending recommendation items found to convert")

        # Group by (supplier_id, warehouse_id)
        groups: Dict[Tuple[str, str], List[ReplenishmentRecommendationItem]] = {}
        for it in items:
            if not it.supplier_id:
                continue # Skip items without assigned supplier
            if it.suggested_reorder_quantity <= 0:
                continue
            key = (it.supplier_id, it.warehouse_id)
            if key not in groups:
                groups[key] = []
            groups[key].append(it)

        if not groups:
            raise HTTPException(status_code=400, detail="None of the selected items have an assigned supplier or quantity > 0")

        generated_pos: List[GenerateDraftPOResultItem] = []

        for (supp_id, wh_id), group_items in groups.items():
            po_num = await SequenceService.generate_next_number(db, tenant_id, "PURCHASE_ORDER", custom_prefix="PO")
            supp = (await db.execute(select(Supplier).where(Supplier.id == supp_id))).scalar_one()

            total_amount = sum([it.estimated_total_cost for it in group_items])

            po = PurchaseOrder(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                po_number=po_num,
                supplier_id=supp_id,
                target_warehouse_id=wh_id,
                status="DRAFT",
                currency=supp.currency or "USD",
                total_amount=total_amount,
                notes="Generated from Automated Replenishment Workbench",
                created_by_user_id=user_id
            )
            db.add(po)
            await db.flush()

            for it in group_items:
                pol = POLineItem(
                    id=str(uuid.uuid4()),
                    purchase_order_id=po.id,
                    item_variant_id=it.item_variant_id,
                    quantity_ordered=it.suggested_reorder_quantity,
                    quantity_received=Decimal("0.0"),
                    unit_price=it.estimated_unit_cost,
                    line_total=it.estimated_total_cost
                )
                db.add(pol)

                it.action_status = "DRAFT_PO_CREATED"
                it.purchase_order_id = po.id

            generated_pos.append(GenerateDraftPOResultItem(
                purchase_order_id=po.id,
                purchase_order_number=po_num,
                supplier_id=supp_id,
                supplier_name=supp.name,
                warehouse_id=wh_id,
                total_lines=len(group_items),
                total_amount=float(total_amount),
                status="DRAFT"
            ))

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="GENERATE_REPLENISHMENT_DRAFT_POS",
            entity_type="PurchaseOrder",
            entity_id=generated_pos[0].purchase_order_id if generated_pos else None,
            user_id=user_id,
            changes={"draft_pos_count": len(generated_pos), "items_processed": len(items)}
        )

        await db.commit()
        return GenerateDraftPOsResponse(
            generated_orders_count=len(generated_pos),
            purchase_orders=generated_pos
        )
