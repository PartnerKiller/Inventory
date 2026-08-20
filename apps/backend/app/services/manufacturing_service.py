import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.manufacturing import (
    BillOfMaterials,
    BOMLineItem,
    WorkOrder,
    WorkOrderComponent,
    DisassemblyOrder
)
from app.models.item import ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.costing import CostLayer, CostLayerConsumption
from app.schemas.manufacturing import (
    BillOfMaterialsCreate,
    WorkOrderCreate,
    DisassemblyOrderCreate
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService, quantize_decimal

class ManufacturingService:
    @staticmethod
    async def create_bom(
        db: AsyncSession,
        tenant_id: str,
        bom_in: BillOfMaterialsCreate,
        user_id: Optional[str] = None
    ) -> BillOfMaterials:
        var = (await db.execute(
            select(ItemVariant).where(ItemVariant.id == bom_in.item_variant_id)
        )).scalar_one_or_none()
        if not var:
            raise HTTPException(status_code=404, detail="Finished Good item variant not found")

        # Check duplicate version
        dup = (await db.execute(
            select(BillOfMaterials).where(
                BillOfMaterials.tenant_id == tenant_id,
                BillOfMaterials.item_variant_id == bom_in.item_variant_id,
                BillOfMaterials.version == bom_in.version
            )
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"BOM version '{bom_in.version}' already exists for this variant")

        bom_num = await SequenceService.generate_next_number(db, tenant_id, "BOM", custom_prefix="BOM")

        bom = BillOfMaterials(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            bom_number=bom_num,
            name=bom_in.name,
            item_variant_id=bom_in.item_variant_id,
            version=bom_in.version or "1.0",
            status="ACTIVE",
            yield_quantity=bom_in.yield_quantity or Decimal("1.0"),
            labor_cost_per_unit=bom_in.labor_cost_per_unit or Decimal("0.0"),
            overhead_cost_per_unit=bom_in.overhead_cost_per_unit or Decimal("0.0"),
            notes=bom_in.notes
        )
        db.add(bom)
        await db.flush()

        for line_in in bom_in.lines:
            comp_var = (await db.execute(
                select(ItemVariant).where(ItemVariant.id == line_in.component_variant_id)
            )).scalar_one_or_none()
            if not comp_var:
                raise HTTPException(status_code=404, detail=f"Component variant '{line_in.component_variant_id}' not found")

            line = BOMLineItem(
                id=str(uuid.uuid4()),
                bom_id=bom.id,
                component_variant_id=line_in.component_variant_id,
                quantity_required=line_in.quantity_required,
                scrap_percentage=line_in.scrap_percentage or Decimal("0.0"),
                position=line_in.position or 1,
                notes=line_in.notes
            )
            db.add(line)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_BOM",
            entity_type="BillOfMaterials",
            entity_id=bom.id,
            user_id=user_id,
            changes={"bom_number": bom_num, "name": bom.name, "lines_count": len(bom_in.lines)}
        )

        await db.commit()
        await db.refresh(bom)
        return bom

    @staticmethod
    async def create_work_order(
        db: AsyncSession,
        tenant_id: str,
        wo_in: WorkOrderCreate,
        user_id: Optional[str] = None
    ) -> WorkOrder:
        bom = (await db.execute(
            select(BillOfMaterials).where(BillOfMaterials.id == wo_in.bom_id, BillOfMaterials.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not bom:
            raise HTTPException(status_code=404, detail="Bill of Materials not found")

        if bom.status != "ACTIVE":
            raise HTTPException(status_code=400, detail=f"Cannot produce using BOM in '{bom.status}' status")

        wh = (await db.execute(
            select(Warehouse).where(Warehouse.id == wo_in.warehouse_id, Warehouse.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Warehouse not found")

        wo_num = await SequenceService.generate_next_number(db, tenant_id, "WORK_ORDER", custom_prefix="WO")

        wo = WorkOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            work_order_number=wo_num,
            bom_id=bom.id,
            item_variant_id=bom.item_variant_id,
            warehouse_id=wh.id,
            staging_bin_id=wo_in.staging_bin_id,
            destination_bin_id=wo_in.destination_bin_id,
            status="PLANNED",
            quantity_to_produce=wo_in.quantity_to_produce,
            quantity_produced=Decimal("0.0"),
            planned_start_date=wo_in.planned_start_date or get_utc_now(),
            notes=wo_in.notes,
            created_by_user_id=user_id
        )
        db.add(wo)
        await db.flush()

        prod_ratio = wo_in.quantity_to_produce / (bom.yield_quantity or Decimal("1.0"))

        for bline in bom.lines:
            scrap_factor = Decimal("1.0") + (bline.scrap_percentage / Decimal("100.0"))
            qty_req = (bline.quantity_required * prod_ratio * scrap_factor).quantize(Decimal("0.0001"))

            comp = WorkOrderComponent(
                id=str(uuid.uuid4()),
                work_order_id=wo.id,
                component_variant_id=bline.component_variant_id,
                quantity_required=qty_req,
                quantity_reserved=Decimal("0.0"),
                quantity_consumed=Decimal("0.0"),
                unit_cost=Decimal("0.0"),
                total_cost=Decimal("0.0")
            )
            db.add(comp)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_WORK_ORDER",
            entity_type="WorkOrder",
            entity_id=wo.id,
            user_id=user_id,
            changes={"work_order_number": wo_num, "qty": float(wo_in.quantity_to_produce)}
        )

        await db.commit()
        await db.refresh(wo)
        return wo

    @staticmethod
    async def release_work_order(
        db: AsyncSession,
        tenant_id: str,
        work_order_id: str,
        user_id: Optional[str] = None
    ) -> WorkOrder:
        wo = (await db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id, WorkOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not wo:
            raise HTTPException(status_code=404, detail="Work Order not found")

        if wo.status not in ["DRAFT", "PLANNED"]:
            raise HTTPException(status_code=400, detail=f"Cannot release Work Order in '{wo.status}' status")

        # Reserve components
        for comp in wo.components:
            bal = (await db.execute(
                select(StockBalanceCache).where(
                    StockBalanceCache.warehouse_id == wo.warehouse_id,
                    StockBalanceCache.location_bin_id == wo.staging_bin_id,
                    StockBalanceCache.item_variant_id == comp.component_variant_id
                ).with_for_update()
            )).scalar_one_or_none()

            avail = (bal.quantity_on_hand - bal.quantity_allocated) if bal else Decimal("0.0")
            if avail < comp.quantity_required:
                comp_sku = comp.component_variant.variant_sku if comp.component_variant else comp.component_variant_id
                raise HTTPException(
                    status_code=422,
                    detail=f"Insufficient stock to release Work Order for component '{comp_sku}': required {comp.quantity_required}, available {avail}"
                )

            bal.quantity_allocated = Decimal(str(bal.quantity_allocated)) + comp.quantity_required
            comp.quantity_reserved = comp.quantity_required

        wo.status = "RELEASED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="RELEASE_WORK_ORDER",
            entity_type="WorkOrder",
            entity_id=wo.id,
            user_id=user_id,
            changes={"status": "RELEASED"}
        )

        await db.commit()
        await db.refresh(wo)
        return wo

    @staticmethod
    async def complete_work_order(
        db: AsyncSession,
        tenant_id: str,
        work_order_id: str,
        user_id: Optional[str] = None
    ) -> WorkOrder:
        wo = (await db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id, WorkOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not wo:
            raise HTTPException(status_code=404, detail="Work Order not found")

        if wo.status != "RELEASED":
            raise HTTPException(status_code=400, detail=f"Cannot complete Work Order in '{wo.status}' status (must be RELEASED)")

        total_component_cost = Decimal("0.0")

        # 1. Consume raw material components via StockEngine and CostingService
        for comp in wo.components:
            qty_to_issue = comp.quantity_required

            # Release reservation first so StockEngine can post the issue transaction
            bal = (await db.execute(
                select(StockBalanceCache).where(
                    StockBalanceCache.warehouse_id == wo.warehouse_id,
                    StockBalanceCache.location_bin_id == wo.staging_bin_id,
                    StockBalanceCache.item_variant_id == comp.component_variant_id
                ).with_for_update()
            )).scalar_one_or_none()
            if bal:
                bal.quantity_allocated = max(Decimal("0.0"), Decimal(str(bal.quantity_allocated)) - comp.quantity_reserved)

            # Post inventory issue
            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="STOCK_ISSUE",
                entries_data=[{
                    "item_variant_id": comp.component_variant_id,
                    "source_location_bin_id": wo.staging_bin_id,
                    "quantity": qty_to_issue
                }],
                reference_doc_type="WORK_ORDER",
                reference_doc_id=wo.id,
                notes=f"Work Order {wo.work_order_number} component consumption",
                user_id=user_id
            )

            # Deplete cost layers
            layers = (await db.execute(
                select(CostLayer).where(
                    CostLayer.tenant_id == tenant_id,
                    CostLayer.warehouse_id == wo.warehouse_id,
                    CostLayer.item_variant_id == comp.component_variant_id,
                    CostLayer.status == "ACTIVE"
                ).order_by(CostLayer.layer_timestamp.asc()).with_for_update()
            )).scalars().all()

            comp_cost = Decimal("0.0")
            rem_needed = qty_to_issue
            for layer in layers:
                if rem_needed <= 0:
                    break
                rem_layer = Decimal(str(layer.remaining_quantity))
                take = min(rem_needed, rem_layer)
                comp_cost += take * Decimal(str(layer.unit_cost))
                layer.remaining_quantity = quantize_decimal(rem_layer - take)
                if layer.remaining_quantity == 0:
                    layer.status = "DEPLETED"
                rem_needed -= take

            if rem_needed > 0 and len(layers) == 0:
                # Fallback to variant cost price if no layers
                var = (await db.execute(select(ItemVariant).where(ItemVariant.id == comp.component_variant_id))).scalar_one_or_none()
                std = Decimal(str(var.cost_price or 0.0)) if var else Decimal("0.0")
                comp_cost += rem_needed * std

            comp.quantity_consumed = qty_to_issue
            comp.total_cost = quantize_decimal(comp_cost)
            comp.unit_cost = quantize_decimal(comp_cost / qty_to_issue) if qty_to_issue > 0 else Decimal("0.0")
            total_component_cost += comp_cost

        # 2. Add Labor & Overhead
        bom = wo.bom
        produced_qty = wo.quantity_to_produce
        total_labor = quantize_decimal((bom.labor_cost_per_unit or Decimal("0.0")) * produced_qty)
        total_overhead = quantize_decimal((bom.overhead_cost_per_unit or Decimal("0.0")) * produced_qty)
        total_production_cost = quantize_decimal(total_component_cost + total_labor + total_overhead)
        unit_cost = quantize_decimal(total_production_cost / produced_qty) if produced_qty > 0 else Decimal("0.0")

        # 3. Post Finished Good Receipt via StockEngine
        await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="STOCK_RECEIPT",
            entries_data=[{
                "item_variant_id": wo.item_variant_id,
                "destination_location_bin_id": wo.destination_bin_id,
                "quantity": produced_qty,
                "unit_cost": unit_cost
            }],
            reference_doc_type="WORK_ORDER",
            reference_doc_id=wo.id,
            notes=f"Work Order {wo.work_order_number} finished good receipt",
            user_id=user_id
        )

        # 4. Mint Finished Good Cost Layer
        await CostingService.record_inbound_receipt(
            db=db,
            tenant_id=tenant_id,
            warehouse_id=wo.warehouse_id,
            item_variant_id=wo.item_variant_id,
            quantity=produced_qty,
            unit_cost=unit_cost,
            stock_transaction_id=wo.id,
            notes=f"Work Order {wo.work_order_number} finished good receipt",
            user_id=user_id
        )

        # 5. Update Work Order
        wo.status = "COMPLETED"
        wo.quantity_produced = produced_qty
        wo.total_component_cost = total_component_cost
        wo.total_labor_cost = total_labor
        wo.total_overhead_cost = total_overhead
        wo.total_production_cost = total_production_cost
        wo.unit_cost = unit_cost
        wo.completed_at = get_utc_now()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="COMPLETE_WORK_ORDER",
            entity_type="WorkOrder",
            entity_id=wo.id,
            user_id=user_id,
            changes={"status": "COMPLETED", "produced_qty": float(produced_qty), "unit_cost": float(unit_cost)}
        )

        await db.commit()
        await db.refresh(wo)
        return wo

    @staticmethod
    async def disassemble_assembly(
        db: AsyncSession,
        tenant_id: str,
        dis_in: DisassemblyOrderCreate,
        user_id: Optional[str] = None
    ) -> DisassemblyOrder:
        # Retrieve active BOM for disassembly recipe
        bom = (await db.execute(
            select(BillOfMaterials).where(
                BillOfMaterials.tenant_id == tenant_id,
                BillOfMaterials.item_variant_id == dis_in.item_variant_id,
                BillOfMaterials.status == "ACTIVE"
            )
        )).scalar_one_or_none()
        if not bom:
            raise HTTPException(status_code=400, detail="No active BOM found for this finished good variant")

        # 1. Issue Finished Good from source bin
        await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="STOCK_ISSUE",
            entries_data=[{
                "item_variant_id": dis_in.item_variant_id,
                "source_location_bin_id": dis_in.source_bin_id,
                "quantity": dis_in.quantity_disassembled
            }],
            reference_doc_type="DISASSEMBLY",
            notes="Assembly disassembly finished good issue",
            user_id=user_id
        )

        # Deplete FG layers
        fg_layers = (await db.execute(
            select(CostLayer).where(
                CostLayer.tenant_id == tenant_id,
                CostLayer.warehouse_id == dis_in.warehouse_id,
                CostLayer.item_variant_id == dis_in.item_variant_id,
                CostLayer.status == "ACTIVE"
            ).order_by(CostLayer.layer_timestamp.asc()).with_for_update()
        )).scalars().all()

        fg_cost_recovered = Decimal("0.0")
        rem_fg = dis_in.quantity_disassembled
        for layer in fg_layers:
            if rem_fg <= 0:
                break
            rem_layer = Decimal(str(layer.remaining_quantity))
            take = min(rem_fg, rem_layer)
            fg_cost_recovered += take * Decimal(str(layer.unit_cost))
            layer.remaining_quantity = quantize_decimal(rem_layer - take)
            if layer.remaining_quantity == 0:
                layer.status = "DEPLETED"
            rem_fg -= take

        if rem_fg > 0 and len(fg_layers) == 0:
            var = (await db.execute(select(ItemVariant).where(ItemVariant.id == dis_in.item_variant_id))).scalar_one_or_none()
            std = Decimal(str(var.cost_price or 0.0)) if var else Decimal("0.0")
            fg_cost_recovered += rem_fg * std

        # 2. Receipt Components back into destination bin
        dis_ratio = dis_in.quantity_disassembled / (bom.yield_quantity or Decimal("1.0"))
        dis_num = await SequenceService.generate_next_number(db, tenant_id, "DISASSEMBLY", custom_prefix="DIS")

        for bline in bom.lines:
            comp_qty = bline.quantity_required * dis_ratio
            comp_unit_cost = quantize_decimal(fg_cost_recovered / (len(bom.lines) * comp_qty)) if comp_qty > 0 else Decimal("0.0")

            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="STOCK_RECEIPT",
                entries_data=[{
                    "item_variant_id": bline.component_variant_id,
                    "destination_location_bin_id": dis_in.destination_bin_id,
                    "quantity": comp_qty,
                    "unit_cost": comp_unit_cost
                }],
                reference_doc_type="DISASSEMBLY",
                notes=f"Disassembly {dis_num} component recovery",
                user_id=user_id
            )

            await CostingService.record_inbound_receipt(
                db=db,
                tenant_id=tenant_id,
                warehouse_id=dis_in.warehouse_id,
                item_variant_id=bline.component_variant_id,
                quantity=comp_qty,
                unit_cost=comp_unit_cost,
                notes=f"Disassembly {dis_num} component recovery",
                user_id=user_id
            )

        dis_order = DisassemblyOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            disassembly_number=dis_num,
            item_variant_id=dis_in.item_variant_id,
            warehouse_id=dis_in.warehouse_id,
            source_bin_id=dis_in.source_bin_id,
            destination_bin_id=dis_in.destination_bin_id,
            quantity_disassembled=dis_in.quantity_disassembled,
            total_cost_recovered=fg_cost_recovered,
            status="COMPLETED",
            notes=dis_in.notes,
            performed_by_user_id=user_id
        )
        db.add(dis_order)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="DISASSEMBLE_ASSEMBLY",
            entity_type="DisassemblyOrder",
            entity_id=dis_order.id,
            user_id=user_id,
            changes={"disassembly_number": dis_num, "qty": float(dis_in.quantity_disassembled)}
        )

        await db.commit()
        await db.refresh(dis_order)
        return dis_order
