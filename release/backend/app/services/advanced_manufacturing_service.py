import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.manufacturing import BillOfMaterials, BOMLineItem, WorkOrder, WorkOrderComponent
from app.models.advanced_manufacturing import (
    WorkCenter,
    Routing,
    RoutingOperation,
    ProductionOrderOperation,
    ProductionQualityInspection
)
from app.models.item import ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.costing import CostLayer
from app.models.general_ledger import GLAccount
from app.schemas.advanced_manufacturing import (
    WorkCenterCreate,
    WorkCenterResponse,
    RoutingCreate,
    RoutingResponse,
    RoutingOperationResponse,
    OperationClaimRequest,
    OperationCompleteRequest,
    ProductionQualityInspectionCreate,
    ProductionQualityInspectionResponse,
    MRPExplosionRequest,
    MRPRequirementItem,
    MRPExplosionResponse
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate

class WorkCenterService:
    @staticmethod
    async def create_work_center(
        db: AsyncSession,
        tenant_id: str,
        wc_in: WorkCenterCreate
    ) -> WorkCenterResponse:
        dup = (await db.execute(
            select(WorkCenter).where(WorkCenter.tenant_id == tenant_id, WorkCenter.code == wc_in.code.upper().strip())
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail=f"Work Center '{wc_in.code}' already exists")

        wc = WorkCenter(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            code=wc_in.code.upper().strip(),
            name=wc_in.name,
            warehouse_id=wc_in.warehouse_id,
            department=wc_in.department,
            hourly_labor_rate=wc_in.hourly_labor_rate,
            hourly_machine_rate=wc_in.hourly_machine_rate,
            daily_capacity_hours=wc_in.daily_capacity_hours,
            efficiency_factor=wc_in.efficiency_factor,
            is_active=wc_in.is_active
        )
        db.add(wc)
        await db.commit()
        await db.refresh(wc)

        return WorkCenterResponse(
            id=wc.id,
            tenant_id=wc.tenant_id,
            code=wc.code,
            name=wc.name,
            warehouse_id=wc.warehouse_id,
            department=wc.department,
            hourly_labor_rate=Decimal(str(wc.hourly_labor_rate)),
            hourly_machine_rate=Decimal(str(wc.hourly_machine_rate)),
            daily_capacity_hours=Decimal(str(wc.daily_capacity_hours)),
            efficiency_factor=Decimal(str(wc.efficiency_factor)),
            is_active=wc.is_active,
            created_at=wc.created_at
        )

class RoutingService:
    @staticmethod
    async def create_routing(
        db: AsyncSession,
        tenant_id: str,
        routing_in: RoutingCreate
    ) -> RoutingResponse:
        rout_num = await SequenceService.generate_next_number(db, tenant_id, "ROUTING", custom_prefix="ROUT")

        routing = Routing(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            routing_number=rout_num,
            name=routing_in.name,
            item_variant_id=routing_in.item_variant_id,
            version=routing_in.version,
            status=routing_in.status
        )
        db.add(routing)
        await db.flush()

        ops_out = []
        for op in routing_in.operations:
            r_op = RoutingOperation(
                id=str(uuid.uuid4()),
                routing_id=routing.id,
                sequence_number=op.sequence_number,
                operation_name=op.operation_name,
                work_center_id=op.work_center_id,
                setup_time_minutes=op.setup_time_minutes,
                run_time_minutes_per_unit=op.run_time_minutes_per_unit,
                queue_time_minutes=op.queue_time_minutes,
                move_time_minutes=op.move_time_minutes,
                is_quality_gate=op.is_quality_gate
            )
            db.add(r_op)
            ops_out.append(RoutingOperationResponse(
                id=r_op.id,
                sequence_number=r_op.sequence_number,
                operation_name=r_op.operation_name,
                work_center_id=r_op.work_center_id,
                setup_time_minutes=r_op.setup_time_minutes,
                run_time_minutes_per_unit=r_op.run_time_minutes_per_unit,
                is_quality_gate=r_op.is_quality_gate
            ))

        await db.commit()
        await db.refresh(routing)

        return RoutingResponse(
            id=routing.id,
            tenant_id=routing.tenant_id,
            routing_number=routing.routing_number,
            name=routing.name,
            item_variant_id=routing.item_variant_id,
            version=routing.version,
            status=routing.status,
            operations=ops_out,
            created_at=routing.created_at
        )

class AdvancedManufacturingService:
    @staticmethod
    async def explode_mrp(
        db: AsyncSession,
        tenant_id: str,
        req: MRPExplosionRequest
    ) -> MRPExplosionResponse:
        bom = (await db.execute(
            select(BillOfMaterials).where(
                BillOfMaterials.tenant_id == tenant_id,
                BillOfMaterials.item_variant_id == req.item_variant_id,
                BillOfMaterials.status == "ACTIVE"
            ).order_by(BillOfMaterials.version.desc())
        )).scalars().first()

        if not bom:
            raise HTTPException(status_code=404, detail="No active BOM found for item variant")

        requirements = []
        prod_ratio = req.quantity / (bom.yield_quantity or Decimal("1.0"))

        for bline in bom.lines:
            scrap_pct = Decimal(str(bline.scrap_percentage or 0.0))
            scrap_factor = Decimal("1.0") + (scrap_pct / Decimal("100.0"))
            gross_qty = (bline.quantity_required * prod_ratio * scrap_factor).quantize(Decimal("0.0001"))

            bal = (await db.execute(
                select(StockBalanceCache).where(
                    StockBalanceCache.warehouse_id == req.warehouse_id,
                    StockBalanceCache.item_variant_id == bline.component_variant_id
                )
            )).scalar_one_or_none()

            on_hand = bal.quantity_on_hand if bal else Decimal("0.0")
            allocated = bal.quantity_allocated if bal else Decimal("0.0")
            available = max(Decimal("0.0"), on_hand - allocated)
            net_needed = max(Decimal("0.0"), gross_qty - available)

            comp_var = (await db.execute(
                select(ItemVariant).where(ItemVariant.id == bline.component_variant_id)
            )).scalar_one()

            requirements.append(MRPRequirementItem(
                component_variant_id=bline.component_variant_id,
                sku=comp_var.variant_sku,
                gross_quantity=gross_qty,
                on_hand_quantity=on_hand,
                allocated_quantity=allocated,
                net_quantity_needed=net_needed,
                procurement_type="BUY"
            ))

        return MRPExplosionResponse(
            item_variant_id=req.item_variant_id,
            planned_quantity=req.quantity,
            requirements=requirements
        )

    @staticmethod
    async def release_production_order_with_routing(
        db: AsyncSession,
        tenant_id: str,
        work_order_id: str,
        routing_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> WorkOrder:
        wo = (await db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id, WorkOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not wo:
            raise HTTPException(status_code=404, detail="Work Order not found")

        if wo.status != "PLANNED":
            raise HTTPException(status_code=400, detail=f"Cannot release order in '{wo.status}' status")

        # 1. Snapshot Routing operations into ProductionOrderOperation
        if routing_id:
            routing = (await db.execute(
                select(Routing).where(Routing.id == routing_id, Routing.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if routing:
                for op in routing.operations:
                    po_op = ProductionOrderOperation(
                        id=str(uuid.uuid4()),
                        work_order_id=wo.id,
                        sequence_number=op.sequence_number,
                        operation_name=op.operation_name,
                        work_center_id=op.work_center_id,
                        status="PENDING",
                        is_quality_gate=op.is_quality_gate
                    )
                    db.add(po_op)

        # 2. Reserve stock
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
                raise HTTPException(
                    status_code=422,
                    detail=f"Insufficient stock for component: required {comp.quantity_required}, available {avail}"
                )

            bal.quantity_allocated = Decimal(str(bal.quantity_allocated)) + comp.quantity_required
            comp.quantity_reserved = comp.quantity_required

        wo.status = "RELEASED"
        await db.commit()
        await db.refresh(wo)
        return wo

    @staticmethod
    async def claim_operation(
        db: AsyncSession,
        tenant_id: str,
        operation_id: str,
        user_id: str
    ) -> ProductionOrderOperation:
        op = (await db.execute(
            select(ProductionOrderOperation).where(ProductionOrderOperation.id == operation_id).with_for_update()
        )).scalar_one_or_none()
        if not op:
            raise HTTPException(status_code=404, detail="Operation not found")

        # Concurrency check
        if op.status != "PENDING":
            raise HTTPException(status_code=409, detail=f"Operation already claimed or in status '{op.status}'")

        # Verify predecessor Finish-to-Start operations
        predecessors = (await db.execute(
            select(ProductionOrderOperation).where(
                ProductionOrderOperation.work_order_id == op.work_order_id,
                ProductionOrderOperation.sequence_number < op.sequence_number
            )
        )).scalars().all()

        if any(p.status != "COMPLETED" for p in predecessors):
            raise HTTPException(status_code=400, detail="Predecessor operations must be completed first")

        op.assigned_operator_id = user_id
        op.status = "RUNNING"
        op.started_at = get_utc_now()
        await db.commit()
        await db.refresh(op)
        return op

    @staticmethod
    async def complete_operation(
        db: AsyncSession,
        tenant_id: str,
        req: OperationCompleteRequest,
        user_id: str
    ) -> ProductionOrderOperation:
        op = (await db.execute(
            select(ProductionOrderOperation).where(ProductionOrderOperation.id == req.operation_id).with_for_update()
        )).scalar_one_or_none()
        if not op:
            raise HTTPException(status_code=404, detail="Operation not found")

        if op.status != "RUNNING":
            raise HTTPException(status_code=400, detail=f"Cannot complete operation in status '{op.status}'")

        wc = (await db.execute(
            select(WorkCenter).where(WorkCenter.id == op.work_center_id)
        )).scalar_one()

        labor_hours = req.actual_run_minutes / Decimal("60.0")
        labor_cost = (labor_hours * Decimal(str(wc.hourly_labor_rate))).quantize(Decimal("0.0001"))
        machine_cost = (labor_hours * Decimal(str(wc.hourly_machine_rate))).quantize(Decimal("0.0001"))

        op.status = "COMPLETED"
        op.completed_quantity = req.completed_quantity
        op.scrap_quantity = req.scrap_quantity
        op.actual_setup_minutes = req.actual_setup_minutes
        op.actual_run_minutes = req.actual_run_minutes
        op.actual_labor_cost = labor_cost
        op.actual_machine_cost = machine_cost
        op.completed_at = get_utc_now()

        # Add to parent work order totals
        wo = (await db.execute(
            select(WorkOrder).where(WorkOrder.id == op.work_order_id).with_for_update()
        )).scalar_one()
        wo.total_labor_cost = Decimal(str(wo.total_labor_cost)) + labor_cost
        wo.total_overhead_cost = Decimal(str(wo.total_overhead_cost)) + machine_cost

        await db.commit()
        await db.refresh(op)
        return op

    @staticmethod
    async def record_quality_inspection(
        db: AsyncSession,
        tenant_id: str,
        insp_in: ProductionQualityInspectionCreate,
        user_id: str
    ) -> ProductionQualityInspectionResponse:
        if insp_in.disposition in ["HOLD", "REJECT"] and not insp_in.quarantine_bin_id:
            raise HTTPException(status_code=400, detail="Quarantine/Scrap bin required for non-passing inspection")

        insp = ProductionQualityInspection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            work_order_id=insp_in.work_order_id,
            operation_id=insp_in.operation_id,
            inspection_type=insp_in.inspection_type,
            inspector_user_id=user_id,
            inspected_quantity=insp_in.inspected_quantity,
            passed_quantity=insp_in.passed_quantity,
            rejected_quantity=insp_in.rejected_quantity,
            disposition=insp_in.disposition,
            quarantine_bin_id=insp_in.quarantine_bin_id,
            notes=insp_in.notes
        )
        db.add(insp)
        await db.commit()
        await db.refresh(insp)

        return ProductionQualityInspectionResponse(
            id=insp.id,
            tenant_id=insp.tenant_id,
            work_order_id=insp.work_order_id,
            inspection_type=insp.inspection_type,
            inspected_quantity=insp.inspected_quantity,
            passed_quantity=insp.passed_quantity,
            rejected_quantity=insp.rejected_quantity,
            disposition=insp.disposition,
            quarantine_bin_id=insp.quarantine_bin_id,
            created_at=insp.created_at
        )

    @staticmethod
    async def complete_production_order_with_gl(
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
            raise HTTPException(status_code=400, detail=f"Cannot complete Work Order in '{wo.status}' status")

        # 1. Consume raw materials
        total_comp_cost = Decimal("0.0")
        for comp in wo.components:
            # Release reservation
            bal = (await db.execute(
                select(StockBalanceCache).where(
                    StockBalanceCache.warehouse_id == wo.warehouse_id,
                    StockBalanceCache.location_bin_id == wo.staging_bin_id,
                    StockBalanceCache.item_variant_id == comp.component_variant_id
                ).with_for_update()
            )).scalar_one_or_none()
            if bal:
                bal.quantity_allocated = max(Decimal("0.0"), Decimal(str(bal.quantity_allocated)) - comp.quantity_reserved)

            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="STOCK_ISSUE",
                entries_data=[{
                    "item_variant_id": comp.component_variant_id,
                    "source_location_bin_id": wo.staging_bin_id,
                    "quantity": comp.quantity_required
                }],
                reference_doc_type="WORK_ORDER",
                reference_doc_id=wo.id,
                notes=f"WO {wo.work_order_number} consumption",
                user_id=user_id
            )

            # Consume cost layers
            layers = (await db.execute(
                select(CostLayer).where(
                    CostLayer.tenant_id == tenant_id,
                    CostLayer.warehouse_id == wo.warehouse_id,
                    CostLayer.item_variant_id == comp.component_variant_id,
                    CostLayer.status == "ACTIVE"
                ).order_by(CostLayer.layer_timestamp.asc()).with_for_update()
            )).scalars().all()

            rem_needed = comp.quantity_required
            comp_cost = Decimal("0.0")
            for l in layers:
                if rem_needed <= 0:
                    break
                rem = Decimal(str(l.remaining_quantity))
                take = min(rem_needed, rem)
                comp_cost += take * Decimal(str(l.unit_cost))
                l.remaining_quantity = rem - take
                if l.remaining_quantity <= 0:
                    l.status = "CONSUMED"
                rem_needed -= take

            if rem_needed > 0:
                comp_cost += rem_needed * Decimal("100.0") # fallback standard cost

            comp.quantity_consumed = comp.quantity_required
            comp.total_cost = comp_cost
            total_comp_cost += comp_cost

        wo.total_component_cost = total_comp_cost
        wo.total_production_cost = total_comp_cost + Decimal(str(wo.total_labor_cost)) + Decimal(str(wo.total_overhead_cost))
        wo.quantity_produced = wo.quantity_to_produce
        wo.unit_cost = (wo.total_production_cost / wo.quantity_produced).quantize(Decimal("0.0001"))

        # 2. Receive Finished Goods into stock
        await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="STOCK_RECEIPT",
            entries_data=[{
                "item_variant_id": wo.item_variant_id,
                "destination_location_bin_id": wo.destination_bin_id,
                "quantity": wo.quantity_produced
            }],
            reference_doc_type="WORK_ORDER",
            reference_doc_id=wo.id,
            notes=f"WO {wo.work_order_number} Finished Good completion",
            user_id=user_id
        )

        # Create FG CostLayer
        fg_layer = CostLayer(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=wo.warehouse_id,
            item_variant_id=wo.item_variant_id,
            layer_number=f"LAY-WO-{uuid.uuid4().hex[:8].upper()}",
            original_quantity=wo.quantity_produced,
            remaining_quantity=wo.quantity_produced,
            unit_cost=wo.unit_cost,
            total_cost=wo.total_production_cost,
            status="ACTIVE",
            layer_timestamp=get_utc_now()
        )
        db.add(fg_layer)

        # 3. Automated GL Journal Vouchers
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        acc_1200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200"))).scalar_one_or_none()
        acc_1300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1300"))).scalar_one_or_none()

        # JV: Material Issue (Dr 1300 WIP / Cr 1200 Raw Materials)
        if total_comp_cost > 0 and acc_1200 and acc_1300:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="WORK_ORDER",
                    source_document_id=f"{wo.id}_MAT_ISSUE",
                    notes=f"Material Issue for WO {wo.work_order_number}",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_1300.id, debit_amount=total_comp_cost, credit_amount=Decimal("0.0"), memo="WIP Raw Material issue"),
                        JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("0.0"), credit_amount=total_comp_cost, memo="Raw Material Inventory reduction")
                    ]
                ),
                user_id=user_id
            )

        # JV: Finished Goods Completion (Dr 1200 FG / Cr 1300 WIP)
        if wo.total_production_cost > 0 and acc_1200 and acc_1300:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="WORK_ORDER",
                    source_document_id=f"{wo.id}_COMPLETION",
                    notes=f"Finished Goods Stocking for WO {wo.work_order_number}",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=wo.total_production_cost, credit_amount=Decimal("0.0"), memo="Finished Goods Asset increase"),
                        JournalEntryLineCreate(account_id=acc_1300.id, debit_amount=Decimal("0.0"), credit_amount=wo.total_production_cost, memo="WIP clearance to zero")
                    ]
                ),
                user_id=user_id
            )

        wo.status = "COMPLETED"
        wo.completed_at = get_utc_now()

        await db.commit()
        await db.refresh(wo)
        return wo
