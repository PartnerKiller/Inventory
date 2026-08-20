from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.permissions import require_permission, get_current_user_claims
from app.schemas.traceability import (
    StockLotCreate,
    StockLotUpdate,
    StockLotResponse,
    ItemSerialNumberResponse,
    SerialBatchRegistrationRequest,
    ForwardTraceResponse,
    BackwardTraceResponse,
    RecallExecutionRequest,
    RecallExecutionResponse,
    ExpiryHorizonResponse,
    FEFOPickRecommendationResponse
)
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.item import ItemVariant, Item
from app.services.traceability_service import TraceabilityService

router = APIRouter()

# ============================================================================
# STOCK LOTS
# ============================================================================

@router.get("/lots", response_model=List[StockLotResponse])
async def list_stock_lots(
    variant_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(StockLot, ItemVariant, Item)
        .join(ItemVariant, StockLot.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(StockLot.tenant_id == tenant_id, StockLot.is_deleted == False)
    )
    if variant_id:
        stmt = stmt.where(StockLot.item_variant_id == variant_id)
    if status_filter:
        stmt = stmt.where(StockLot.status == status_filter)

    stmt = stmt.order_by(StockLot.expiry_date.asc().nulls_last(), StockLot.created_at.desc())
    rows = (await db.execute(stmt)).fetchall()

    out = []
    for lot, var, it in rows:
        out.append(StockLotResponse(
            id=lot.id,
            tenant_id=lot.tenant_id,
            item_variant_id=var.id,
            variant_sku=var.variant_sku,
            item_name=it.name,
            lot_number=lot.lot_number,
            supplier_id=lot.supplier_id,
            supplier_name=lot.supplier.name if lot.supplier else None,
            supplier_lot_number=lot.supplier_lot_number,
            origin_grn_id=lot.origin_grn_id,
            grn_number=lot.origin_grn.grn_number if lot.origin_grn else None,
            cost_layer_id=lot.cost_layer_id,
            manufacturing_date=lot.manufacturing_date,
            expiry_date=lot.expiry_date,
            best_before_date=lot.best_before_date,
            initial_quantity=float(lot.initial_quantity),
            current_quantity=float(lot.current_quantity),
            status=lot.status,
            quarantine_reason=lot.quarantine_reason,
            notes=lot.notes,
            created_at=lot.created_at
        ))
    return out

@router.post("/lots", response_model=StockLotResponse, status_code=status.HTTP_201_CREATED)
async def create_stock_lot(
    lot_in: StockLotCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:manage_lots"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    lot = await TraceabilityService.create_or_get_lot(db, tenant_id, lot_in, user_id=user_id)
    await db.commit()
    await db.refresh(lot)

    var = (await db.execute(select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == lot.item_variant_id))).first()
    variant, item = var

    return StockLotResponse(
        id=lot.id,
        tenant_id=lot.tenant_id,
        item_variant_id=variant.id,
        variant_sku=variant.variant_sku,
        item_name=item.name,
        lot_number=lot.lot_number,
        supplier_id=lot.supplier_id,
        supplier_name=lot.supplier.name if lot.supplier else None,
        supplier_lot_number=lot.supplier_lot_number,
        origin_grn_id=lot.origin_grn_id,
        manufacturing_date=lot.manufacturing_date,
        expiry_date=lot.expiry_date,
        best_before_date=lot.best_before_date,
        initial_quantity=float(lot.initial_quantity),
        current_quantity=float(lot.current_quantity),
        status=lot.status,
        quarantine_reason=lot.quarantine_reason,
        notes=lot.notes,
        created_at=lot.created_at
    )

# ============================================================================
# ITEM SERIAL NUMBERS
# ============================================================================

@router.get("/serials", response_model=List[ItemSerialNumberResponse])
async def list_serials(
    warehouse_id: Optional[str] = Query(None),
    variant_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(ItemSerialNumber, ItemVariant, Item)
        .join(ItemVariant, ItemSerialNumber.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(ItemSerialNumber.tenant_id == tenant_id)
    )
    if warehouse_id:
        stmt = stmt.where(ItemSerialNumber.warehouse_id == warehouse_id)
    if variant_id:
        stmt = stmt.where(ItemSerialNumber.item_variant_id == variant_id)
    if status_filter:
        stmt = stmt.where(ItemSerialNumber.status == status_filter)

    rows = (await db.execute(stmt)).fetchall()

    out = []
    for s, var, it in rows:
        out.append(ItemSerialNumberResponse(
            id=s.id,
            tenant_id=s.tenant_id,
            warehouse_id=s.warehouse_id,
            warehouse_name=s.warehouse.name if s.warehouse else None,
            item_variant_id=var.id,
            variant_sku=var.variant_sku,
            item_name=it.name,
            lot_id=s.lot_id,
            lot_number=s.lot.lot_number if s.lot else None,
            serial_number=s.serial_number,
            status=s.status,
            location_bin_id=s.location_bin_id,
            location_bin_code=s.bin.code if s.bin else None,
            origin_grn_id=s.origin_grn_id,
            grn_number=s.origin_grn.grn_number if s.origin_grn else None,
            dispatched_shipment_id=s.dispatched_shipment_id,
            shipment_number=s.shipment.shipment_number if s.shipment else None,
            quarantine_reason=s.quarantine_reason,
            notes=s.notes,
            created_at=s.created_at
        ))
    return out

@router.post("/serials/batch-register", response_model=List[ItemSerialNumberResponse], status_code=status.HTTP_201_CREATED)
async def batch_register_serials(
    req: SerialBatchRegistrationRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:manage_serials"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    serials = await TraceabilityService.register_serial_numbers(db, tenant_id, req, user_id=user_id)
    await db.commit()

    var = (await db.execute(select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == req.item_variant_id))).first()
    variant, item = var

    return [
        ItemSerialNumberResponse(
            id=s.id,
            tenant_id=s.tenant_id,
            warehouse_id=s.warehouse_id,
            item_variant_id=variant.id,
            variant_sku=variant.variant_sku,
            item_name=item.name,
            lot_id=s.lot_id,
            serial_number=s.serial_number,
            status=s.status,
            location_bin_id=s.location_bin_id,
            origin_grn_id=s.origin_grn_id,
            created_at=s.created_at
        )
        for s in serials
    ]

# ============================================================================
# TRACEABILITY, QUARANTINE & RECALL
# ============================================================================

@router.get("/trace/forward", response_model=ForwardTraceResponse)
async def get_forward_trace(
    lot_id: str = Query(..., description="Target StockLot ID to trace forward"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:read"))
):
    tenant_id = claims["tenant_id"]
    return await TraceabilityService.get_forward_trace(db, tenant_id, lot_id=lot_id)

@router.get("/trace/backward", response_model=BackwardTraceResponse)
async def get_backward_trace(
    identifier: str = Query(..., description="Serial number or shipment identifier to trace backward"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:read"))
):
    tenant_id = claims["tenant_id"]
    return await TraceabilityService.get_backward_trace(db, tenant_id, identifier=identifier)

@router.post("/recalls/execute", response_model=RecallExecutionResponse)
async def execute_lot_recall(
    req: RecallExecutionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:recall"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await TraceabilityService.execute_lot_recall(db, tenant_id, req, user_id=user_id)

@router.get("/reports/expiry-horizon", response_model=ExpiryHorizonResponse)
async def get_expiry_horizon(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("traceability:read"))
):
    tenant_id = claims["tenant_id"]
    return await TraceabilityService.get_expiry_horizon(db, tenant_id, warehouse_id=warehouse_id)

@router.get("/picking/fefo-recommendations", response_model=FEFOPickRecommendationResponse)
async def get_fefo_recommendations(
    warehouse_id: str = Query(...),
    item_variant_id: str = Query(...),
    required_quantity: float = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:read"))
):
    tenant_id = claims["tenant_id"]
    return await TraceabilityService.get_fefo_pick_recommendations(
        db, tenant_id, warehouse_id=warehouse_id, item_variant_id=item_variant_id, required_quantity=Decimal(str(required_quantity))
    )
