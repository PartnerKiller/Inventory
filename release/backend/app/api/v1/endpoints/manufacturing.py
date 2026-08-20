from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.manufacturing import BillOfMaterials, WorkOrder, DisassemblyOrder
from app.schemas.manufacturing import (
    BillOfMaterialsCreate,
    BillOfMaterialsResponse,
    WorkOrderCreate,
    WorkOrderResponse,
    DisassemblyOrderCreate,
    DisassemblyOrderResponse
)
from app.services.manufacturing_service import ManufacturingService

router = APIRouter()

@router.get("/boms", response_model=List[BillOfMaterialsResponse])
async def list_boms(
    item_variant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(BillOfMaterials).where(BillOfMaterials.tenant_id == tenant_id, BillOfMaterials.is_deleted == False)
    if item_variant_id:
        stmt = stmt.where(BillOfMaterials.item_variant_id == item_variant_id)
    stmt = stmt.order_by(desc(BillOfMaterials.created_at))
    boms = (await db.execute(stmt)).scalars().all()

    out = []
    for b in boms:
        out.append(BillOfMaterialsResponse(
            id=b.id,
            tenant_id=b.tenant_id,
            bom_number=b.bom_number,
            name=b.name,
            item_variant_id=b.item_variant_id,
            variant_sku=b.variant.variant_sku if b.variant else None,
            variant_name=b.variant.variant_name if b.variant else None,
            version=b.version,
            status=b.status,
            yield_quantity=float(b.yield_quantity),
            labor_cost_per_unit=float(b.labor_cost_per_unit),
            overhead_cost_per_unit=float(b.overhead_cost_per_unit),
            notes=b.notes,
            lines=[],
            created_at=b.created_at
        ))
    return out

@router.post("/boms", response_model=BillOfMaterialsResponse, status_code=status.HTTP_201_CREATED)
async def create_bom(
    bom_in: BillOfMaterialsCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    bom = await ManufacturingService.create_bom(db, tenant_id, bom_in, user_id=claims.get("sub"))
    return BillOfMaterialsResponse(
        id=bom.id,
        tenant_id=bom.tenant_id,
        bom_number=bom.bom_number,
        name=bom.name,
        item_variant_id=bom.item_variant_id,
        variant_sku=bom.variant.variant_sku if bom.variant else None,
        variant_name=bom.variant.variant_name if bom.variant else None,
        version=bom.version,
        status=bom.status,
        yield_quantity=float(bom.yield_quantity),
        labor_cost_per_unit=float(bom.labor_cost_per_unit),
        overhead_cost_per_unit=float(bom.overhead_cost_per_unit),
        notes=bom.notes,
        lines=[],
        created_at=bom.created_at
    )

@router.get("/work-orders", response_model=List[WorkOrderResponse])
async def list_work_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(WorkOrder).where(WorkOrder.tenant_id == tenant_id, WorkOrder.is_deleted == False)
    if status_filter:
        stmt = stmt.where(WorkOrder.status == status_filter)
    stmt = stmt.order_by(desc(WorkOrder.created_at))
    wos = (await db.execute(stmt)).scalars().all()

    out = []
    for wo in wos:
        out.append(WorkOrderResponse(
            id=wo.id,
            tenant_id=wo.tenant_id,
            work_order_number=wo.work_order_number,
            bom_id=wo.bom_id,
            item_variant_id=wo.item_variant_id,
            variant_sku=wo.variant.variant_sku if wo.variant else None,
            variant_name=wo.variant.variant_name if wo.variant else None,
            warehouse_id=wo.warehouse_id,
            warehouse_name=wo.warehouse.name if wo.warehouse else None,
            staging_bin_id=wo.staging_bin_id,
            staging_bin_code=wo.staging_bin.code if wo.staging_bin else None,
            destination_bin_id=wo.destination_bin_id,
            destination_bin_code=wo.destination_bin.code if wo.destination_bin else None,
            status=wo.status,
            quantity_to_produce=float(wo.quantity_to_produce),
            quantity_produced=float(wo.quantity_produced),
            total_component_cost=float(wo.total_component_cost),
            total_labor_cost=float(wo.total_labor_cost),
            total_overhead_cost=float(wo.total_overhead_cost),
            total_production_cost=float(wo.total_production_cost),
            unit_cost=float(wo.unit_cost),
            planned_start_date=wo.planned_start_date,
            completed_at=wo.completed_at,
            notes=wo.notes,
            components=[],
            created_at=wo.created_at
        ))
    return out

@router.post("/work-orders", response_model=WorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    wo_in: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    wo = await ManufacturingService.create_work_order(db, tenant_id, wo_in, user_id=claims.get("sub"))
    return WorkOrderResponse(
        id=wo.id,
        tenant_id=wo.tenant_id,
        work_order_number=wo.work_order_number,
        bom_id=wo.bom_id,
        item_variant_id=wo.item_variant_id,
        variant_sku=wo.variant.variant_sku if wo.variant else None,
        variant_name=wo.variant.variant_name if wo.variant else None,
        warehouse_id=wo.warehouse_id,
        warehouse_name=wo.warehouse.name if wo.warehouse else None,
        staging_bin_id=wo.staging_bin_id,
        staging_bin_code=wo.staging_bin.code if wo.staging_bin else None,
        destination_bin_id=wo.destination_bin_id,
        destination_bin_code=wo.destination_bin.code if wo.destination_bin else None,
        status=wo.status,
        quantity_to_produce=float(wo.quantity_to_produce),
        quantity_produced=float(wo.quantity_produced),
        total_component_cost=float(wo.total_component_cost),
        total_labor_cost=float(wo.total_labor_cost),
        total_overhead_cost=float(wo.total_overhead_cost),
        total_production_cost=float(wo.total_production_cost),
        unit_cost=float(wo.unit_cost),
        planned_start_date=wo.planned_start_date,
        completed_at=wo.completed_at,
        notes=wo.notes,
        components=[],
        created_at=wo.created_at
    )

@router.post("/work-orders/{work_order_id}/release", response_model=WorkOrderResponse)
async def release_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    wo = await ManufacturingService.release_work_order(db, tenant_id, work_order_id, user_id=claims.get("sub"))
    return WorkOrderResponse(
        id=wo.id,
        tenant_id=wo.tenant_id,
        work_order_number=wo.work_order_number,
        bom_id=wo.bom_id,
        item_variant_id=wo.item_variant_id,
        variant_sku=wo.variant.variant_sku if wo.variant else None,
        variant_name=wo.variant.variant_name if wo.variant else None,
        warehouse_id=wo.warehouse_id,
        warehouse_name=wo.warehouse.name if wo.warehouse else None,
        staging_bin_id=wo.staging_bin_id,
        staging_bin_code=wo.staging_bin.code if wo.staging_bin else None,
        destination_bin_id=wo.destination_bin_id,
        destination_bin_code=wo.destination_bin.code if wo.destination_bin else None,
        status=wo.status,
        quantity_to_produce=float(wo.quantity_to_produce),
        quantity_produced=float(wo.quantity_produced),
        total_component_cost=float(wo.total_component_cost),
        total_labor_cost=float(wo.total_labor_cost),
        total_overhead_cost=float(wo.total_overhead_cost),
        total_production_cost=float(wo.total_production_cost),
        unit_cost=float(wo.unit_cost),
        planned_start_date=wo.planned_start_date,
        completed_at=wo.completed_at,
        notes=wo.notes,
        components=[],
        created_at=wo.created_at
    )

@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderResponse)
async def complete_work_order(
    work_order_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    wo = await ManufacturingService.complete_work_order(db, tenant_id, work_order_id, user_id=claims.get("sub"))
    return WorkOrderResponse(
        id=wo.id,
        tenant_id=wo.tenant_id,
        work_order_number=wo.work_order_number,
        bom_id=wo.bom_id,
        item_variant_id=wo.item_variant_id,
        variant_sku=wo.variant.variant_sku if wo.variant else None,
        variant_name=wo.variant.variant_name if wo.variant else None,
        warehouse_id=wo.warehouse_id,
        warehouse_name=wo.warehouse.name if wo.warehouse else None,
        staging_bin_id=wo.staging_bin_id,
        staging_bin_code=wo.staging_bin.code if wo.staging_bin else None,
        destination_bin_id=wo.destination_bin_id,
        destination_bin_code=wo.destination_bin.code if wo.destination_bin else None,
        status=wo.status,
        quantity_to_produce=float(wo.quantity_to_produce),
        quantity_produced=float(wo.quantity_produced),
        total_component_cost=float(wo.total_component_cost),
        total_labor_cost=float(wo.total_labor_cost),
        total_overhead_cost=float(wo.total_overhead_cost),
        total_production_cost=float(wo.total_production_cost),
        unit_cost=float(wo.unit_cost),
        planned_start_date=wo.planned_start_date,
        completed_at=wo.completed_at,
        notes=wo.notes,
        components=[],
        created_at=wo.created_at
    )

@router.post("/disassembly", response_model=DisassemblyOrderResponse, status_code=status.HTTP_201_CREATED)
async def disassemble_assembly(
    dis_in: DisassemblyOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    dis = await ManufacturingService.disassemble_assembly(db, tenant_id, dis_in, user_id=claims.get("sub"))
    return DisassemblyOrderResponse(
        id=dis.id,
        tenant_id=dis.tenant_id,
        disassembly_number=dis.disassembly_number,
        item_variant_id=dis.item_variant_id,
        variant_sku=dis.variant.variant_sku if dis.variant else None,
        warehouse_id=dis.warehouse_id,
        source_bin_id=dis.source_bin_id,
        destination_bin_id=dis.destination_bin_id,
        quantity_disassembled=float(dis.quantity_disassembled),
        total_cost_recovered=float(dis.total_cost_recovered),
        status=dis.status,
        disassembled_at=dis.disassembled_at,
        notes=dis.notes,
        created_at=dis.created_at
    )
