import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.base import get_utc_now
from app.schemas.warehouse import (
    WarehouseCreate, WarehouseUpdate, WarehouseResponse,
    LocationBinCreate, LocationBinUpdate, LocationBinResponse
)
from app.services.audit_service import AuditService

router = APIRouter()

VALID_BIN_TYPES = {"STORAGE", "RECEIVING", "SHIPPING", "STAGING", "DAMAGE", "VIRTUAL_ADJUSTMENT"}

# ============================================================================
# WAREHOUSE MANAGEMENT
# ============================================================================

@router.get("", response_model=List[WarehouseResponse])
async def list_warehouses(
    q: Optional[str] = Query(None, description="Search warehouse by name or code"),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    scopes = claims.get("warehouse_scopes", [])
    has_wildcard = "*" in claims.get("permissions", [])

    stmt = (
        select(Warehouse)
        .options(selectinload(Warehouse.bins))
        .where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    )

    if scopes and not has_wildcard:
        stmt = stmt.where(Warehouse.id.in_(scopes))

    if is_active is not None:
        stmt = stmt.where(Warehouse.is_active == is_active)

    if q:
        search = f"%{q.strip()}%"
        stmt = stmt.where((Warehouse.name.ilike(search)) | (Warehouse.code.ilike(search)))

    res = await db.execute(stmt)
    warehouses = res.scalars().all()

    out = []
    for w in warehouses:
        active_bins = [b for b in w.bins if not b.is_deleted]
        bin_ids = [b.id for b in active_bins]

        total_stock = 0.0
        if bin_ids:
            stock_res = await db.execute(
                select(func.sum(StockBalanceCache.quantity_on_hand))
                .where(StockBalanceCache.location_bin_id.in_(bin_ids))
            )
            total_stock = float(stock_res.scalar() or 0.0)

        bin_responses = []
        for b in active_bins:
            occ_res = await db.execute(
                select(func.count(StockBalanceCache.id))
                .where(StockBalanceCache.location_bin_id == b.id, StockBalanceCache.quantity_on_hand > 0)
            )
            bin_responses.append(LocationBinResponse(
                id=b.id,
                warehouse_id=b.warehouse_id,
                code=b.code,
                aisle=b.aisle,
                rack=b.rack,
                shelf=b.shelf,
                bin=b.bin,
                type=b.type,
                is_active=b.is_active,
                occupied_items_count=occ_res.scalar() or 0,
                created_at=b.created_at
            ))

        out.append(WarehouseResponse(
            id=w.id,
            tenant_id=w.tenant_id,
            code=w.code,
            name=w.name,
            address=w.address,
            is_active=w.is_active,
            total_bins=len(bin_responses),
            total_stock_on_hand=total_stock,
            bins=bin_responses,
            created_at=w.created_at,
            updated_at=w.updated_at
        ))
    return out

@router.post("", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    wh_in: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    
    # Check duplicate code within tenant
    stmt = select(Warehouse).where(
        Warehouse.tenant_id == tenant_id,
        Warehouse.code == wh_in.code.upper().strip(),
        Warehouse.is_deleted == False
    )
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Warehouse with code '{wh_in.code.upper().strip()}' already exists in tenant"
        )

    wh = Warehouse(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=wh_in.code.upper().strip(),
        name=wh_in.name.strip(),
        address=wh_in.address or {},
        is_active=True
    )
    db.add(wh)
    await db.flush()

    # Automatically create default functional bins
    default_bins = [
        LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code=f"{wh.code}-RCV-01", aisle="R", rack="01", shelf="01", bin="01", type="RECEIVING"),
        LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code=f"{wh.code}-STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING"),
        LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code=f"{wh.code}-A01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE"),
    ]
    for b in default_bins:
        db.add(b)

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="Warehouse",
        entity_id=wh.id,
        user_id=claims.get("sub"),
        changes={"code": wh.code, "name": wh.name}
    )

    await db.commit()
    await db.refresh(wh)

    return await get_warehouse_detail(wh.id, db, claims)

@router.get("/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse_detail(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    stmt = (
        select(Warehouse)
        .options(selectinload(Warehouse.bins))
        .where(Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    )
    res = await db.execute(stmt)
    wh = res.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

    active_bins = [b for b in wh.bins if not b.is_deleted]
    bin_ids = [b.id for b in active_bins]

    total_stock = 0.0
    if bin_ids:
        stock_res = await db.execute(
            select(func.sum(StockBalanceCache.quantity_on_hand))
            .where(StockBalanceCache.location_bin_id.in_(bin_ids))
        )
        total_stock = float(stock_res.scalar() or 0.0)

    bin_responses = []
    for b in active_bins:
        occ_res = await db.execute(
            select(func.count(StockBalanceCache.id))
            .where(StockBalanceCache.location_bin_id == b.id, StockBalanceCache.quantity_on_hand > 0)
        )
        bin_responses.append(LocationBinResponse(
            id=b.id,
            warehouse_id=b.warehouse_id,
            code=b.code,
            aisle=b.aisle,
            rack=b.rack,
            shelf=b.shelf,
            bin=b.bin,
            type=b.type,
            is_active=b.is_active,
            occupied_items_count=occ_res.scalar() or 0,
            created_at=b.created_at
        ))

    return WarehouseResponse(
        id=wh.id,
        tenant_id=wh.tenant_id,
        code=wh.code,
        name=wh.name,
        address=wh.address,
        is_active=wh.is_active,
        total_bins=len(bin_responses),
        total_stock_on_hand=total_stock,
        bins=bin_responses,
        created_at=wh.created_at,
        updated_at=wh.updated_at
    )

@router.put("/{warehouse_id}", response_model=WarehouseResponse)
async def update_warehouse(
    warehouse_id: str,
    wh_in: WarehouseUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    stmt = select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    res = await db.execute(stmt)
    wh = res.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

    if wh_in.name is not None:
        wh.name = wh_in.name.strip()
    if wh_in.address is not None:
        wh.address = wh_in.address
    if wh_in.is_active is not None:
        wh.is_active = wh_in.is_active

    wh.updated_at = get_utc_now()

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="UPDATE",
        entity_type="Warehouse",
        entity_id=wh.id,
        user_id=claims.get("sub"),
        changes=wh_in.model_dump(exclude_unset=True)
    )

    await db.commit()
    return await get_warehouse_detail(wh.id, db, claims)

@router.delete("/{warehouse_id}")
async def delete_warehouse(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    stmt = select(Warehouse).options(selectinload(Warehouse.bins)).where(
        Warehouse.id == warehouse_id,
        Warehouse.tenant_id == tenant_id,
        Warehouse.is_deleted == False
    )
    res = await db.execute(stmt)
    wh = res.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

    # Safety constraint: check if any bins in warehouse hold active stock
    bin_ids = [b.id for b in wh.bins]
    if bin_ids:
        stock_check = await db.execute(
            select(func.sum(StockBalanceCache.quantity_on_hand)).where(
                StockBalanceCache.location_bin_id.in_(bin_ids),
                StockBalanceCache.quantity_on_hand > 0
            )
        )
        total_stock = stock_check.scalar() or 0
        if total_stock > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete warehouse '{wh.code}' containing {total_stock} units of active stock. Transfer or adjust stock to zero first."
            )

    wh.is_deleted = True
    wh.updated_at = get_utc_now()

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="DELETE",
        entity_type="Warehouse",
        entity_id=wh.id,
        user_id=claims.get("sub")
    )

    await db.commit()
    return {"message": f"Warehouse '{wh.code}' archived successfully"}


# ============================================================================
# BIN MANAGEMENT
# ============================================================================

@router.get("/{warehouse_id}/bins", response_model=List[LocationBinResponse])
async def list_warehouse_bins(
    warehouse_id: str,
    type: Optional[str] = Query(None, description="STORAGE, RECEIVING, SHIPPING, STAGING, DAMAGE, VIRTUAL_ADJUSTMENT"),
    is_active: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="Search by bin code"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    wh_stmt = select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    wh_res = await db.execute(wh_stmt)
    if not wh_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

    stmt = select(LocationBin).where(LocationBin.warehouse_id == warehouse_id, LocationBin.is_deleted == False)

    if type:
        stmt = stmt.where(LocationBin.type == type.upper())
    if is_active is not None:
        stmt = stmt.where(LocationBin.is_active == is_active)
    if q:
        stmt = stmt.where(LocationBin.code.ilike(f"%{q.strip()}%"))

    stmt = stmt.order_by(LocationBin.code)
    res = await db.execute(stmt)
    bins = res.scalars().all()

    out = []
    for b in bins:
        occ_res = await db.execute(
            select(func.count(StockBalanceCache.id))
            .where(StockBalanceCache.location_bin_id == b.id, StockBalanceCache.quantity_on_hand > 0)
        )
        out.append(LocationBinResponse(
            id=b.id,
            warehouse_id=b.warehouse_id,
            code=b.code,
            aisle=b.aisle,
            rack=b.rack,
            shelf=b.shelf,
            bin=b.bin,
            type=b.type,
            is_active=b.is_active,
            occupied_items_count=occ_res.scalar() or 0,
            created_at=b.created_at
        ))
    return out

@router.post("/{warehouse_id}/bins", response_model=LocationBinResponse, status_code=status.HTTP_201_CREATED)
async def create_location_bin(
    warehouse_id: str,
    bin_in: LocationBinCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    wh_stmt = select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    wh_res = await db.execute(wh_stmt)
    wh = wh_res.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

    bin_type = bin_in.type.upper().strip()
    if bin_type not in VALID_BIN_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid bin type '{bin_type}'. Must be one of: {sorted(list(VALID_BIN_TYPES))}")

    # Check duplicate bin code within the warehouse
    bin_code = bin_in.code.upper().strip()
    dup_check = await db.execute(
        select(LocationBin).where(
            LocationBin.warehouse_id == warehouse_id,
            LocationBin.code == bin_code,
            LocationBin.is_deleted == False
        )
    )
    if dup_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Bin code '{bin_code}' already exists in warehouse '{wh.code}'")

    new_bin = LocationBin(
        id=str(uuid.uuid4()),
        warehouse_id=warehouse_id,
        code=bin_code,
        aisle=bin_in.aisle.strip(),
        rack=bin_in.rack.strip(),
        shelf=bin_in.shelf.strip(),
        bin=bin_in.bin.strip(),
        type=bin_type,
        is_active=True
    )
    db.add(new_bin)
    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="LocationBin",
        entity_id=new_bin.id,
        user_id=claims.get("sub"),
        changes={"code": new_bin.code, "type": new_bin.type, "warehouse_id": warehouse_id}
    )

    await db.commit()
    await db.refresh(new_bin)

    return LocationBinResponse(
        id=new_bin.id,
        warehouse_id=new_bin.warehouse_id,
        code=new_bin.code,
        aisle=new_bin.aisle,
        rack=new_bin.rack,
        shelf=new_bin.shelf,
        bin=new_bin.bin,
        type=new_bin.type,
        is_active=new_bin.is_active,
        occupied_items_count=0,
        created_at=new_bin.created_at
    )

@router.put("/{warehouse_id}/bins/{bin_id}", response_model=LocationBinResponse)
async def update_location_bin(
    warehouse_id: str,
    bin_id: str,
    bin_in: LocationBinUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    stmt = select(LocationBin).where(
        LocationBin.id == bin_id,
        LocationBin.warehouse_id == warehouse_id,
        LocationBin.is_deleted == False
    )
    res = await db.execute(stmt)
    bin_obj = res.scalar_one_or_none()
    if not bin_obj:
        raise HTTPException(status_code=404, detail="Location bin not found in warehouse")

    if bin_in.code and bin_in.code.upper().strip() != bin_obj.code:
        new_code = bin_in.code.upper().strip()
        dup_check = await db.execute(
            select(LocationBin).where(
                LocationBin.warehouse_id == warehouse_id,
                LocationBin.code == new_code,
                LocationBin.id != bin_id,
                LocationBin.is_deleted == False
            )
        )
        if dup_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Bin code '{new_code}' already exists in warehouse")
        bin_obj.code = new_code

    if bin_in.type:
        bin_type = bin_in.type.upper().strip()
        if bin_type not in VALID_BIN_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid bin type '{bin_type}'")
        bin_obj.type = bin_type

    if bin_in.aisle is not None:
        bin_obj.aisle = bin_in.aisle.strip()
    if bin_in.rack is not None:
        bin_obj.rack = bin_in.rack.strip()
    if bin_in.shelf is not None:
        bin_obj.shelf = bin_in.shelf.strip()
    if bin_in.bin is not None:
        bin_obj.bin = bin_in.bin.strip()
    if bin_in.is_active is not None:
        bin_obj.is_active = bin_in.is_active

    bin_obj.updated_at = get_utc_now()
    await db.commit()
    await db.refresh(bin_obj)

    occ_res = await db.execute(
        select(func.count(StockBalanceCache.id))
        .where(StockBalanceCache.location_bin_id == bin_obj.id, StockBalanceCache.quantity_on_hand > 0)
    )

    return LocationBinResponse(
        id=bin_obj.id,
        warehouse_id=bin_obj.warehouse_id,
        code=bin_obj.code,
        aisle=bin_obj.aisle,
        rack=bin_obj.rack,
        shelf=bin_obj.shelf,
        bin=bin_obj.bin,
        type=bin_obj.type,
        is_active=bin_obj.is_active,
        occupied_items_count=occ_res.scalar() or 0,
        created_at=bin_obj.created_at
    )

@router.delete("/{warehouse_id}/bins/{bin_id}")
async def delete_location_bin(
    warehouse_id: str,
    bin_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouses:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    stmt = select(LocationBin).where(
        LocationBin.id == bin_id,
        LocationBin.warehouse_id == warehouse_id,
        LocationBin.is_deleted == False
    )
    res = await db.execute(stmt)
    bin_obj = res.scalar_one_or_none()
    if not bin_obj:
        raise HTTPException(status_code=404, detail="Location bin not found in warehouse")

    # Protection: Only allow deletion of EMPTY bins
    stock_check = await db.execute(
        select(func.sum(StockBalanceCache.quantity_on_hand), func.sum(StockBalanceCache.quantity_allocated))
        .where(StockBalanceCache.location_bin_id == bin_id)
    )
    row = stock_check.first()
    q_hand = float(row[0] or 0.0) if row else 0.0
    q_alloc = float(row[1] or 0.0) if row else 0.0

    if q_hand > 0 or q_alloc > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete non-empty bin '{bin_obj.code}' (Contains {q_hand} on-hand, {q_alloc} allocated units). Transfer or adjust stock to zero first."
        )

    bin_obj.is_deleted = True
    bin_obj.updated_at = get_utc_now()

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="DELETE",
        entity_type="LocationBin",
        entity_id=bin_obj.id,
        user_id=claims.get("sub")
    )

    await db.commit()
    return {"message": f"Location bin '{bin_obj.code}' deleted successfully"}
