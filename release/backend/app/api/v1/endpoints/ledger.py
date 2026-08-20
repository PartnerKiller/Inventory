import math
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_
from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.models.ledger import StockLedgerEntry, StockLedgerTransaction, StockBalanceCache
from app.models.item import ItemVariant, Item
from app.models.warehouse import Warehouse, LocationBin
from app.schemas.ledger import StockLedgerEntryResponse, StockBalanceResponse, StockTransferRequest, StockAdjustmentRequest
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService

router = APIRouter()

# ============================================================================
# LEDGER ENTRIES & AUDIT TRAIL
# ============================================================================

@router.get("/entries", response_model=PaginatedResponse[StockLedgerEntryResponse])
async def list_ledger_entries(
    warehouse_id: Optional[str] = Query(None),
    item_variant_id: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by transaction number, SKU, item name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("ledger:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    base_stmt = (
        select(StockLedgerEntry, StockLedgerTransaction, ItemVariant, Item)
        .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
        .join(ItemVariant, StockLedgerEntry.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(StockLedgerTransaction.tenant_id == tenant_id)
    )

    if item_variant_id:
        base_stmt = base_stmt.where(StockLedgerEntry.item_variant_id == item_variant_id)

    if transaction_type:
        base_stmt = base_stmt.where(StockLedgerTransaction.transaction_type == transaction_type.upper())

    if q:
        search = f"%{q.strip()}%"
        base_stmt = base_stmt.where(
            or_(
                StockLedgerTransaction.transaction_number.ilike(search),
                Item.sku.ilike(search),
                Item.name.ilike(search),
                ItemVariant.variant_sku.ilike(search)
            )
        )

    count_stmt = (
        select(func.count(StockLedgerEntry.id))
        .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
        .join(ItemVariant, StockLedgerEntry.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(StockLedgerTransaction.tenant_id == tenant_id)
    )
    if item_variant_id:
        count_stmt = count_stmt.where(StockLedgerEntry.item_variant_id == item_variant_id)
    if transaction_type:
        count_stmt = count_stmt.where(StockLedgerTransaction.transaction_type == transaction_type.upper())
    if q:
        search = f"%{q.strip()}%"
        count_stmt = count_stmt.where(
            or_(
                StockLedgerTransaction.transaction_number.ilike(search),
                Item.sku.ilike(search),
                Item.name.ilike(search),
                ItemVariant.variant_sku.ilike(search)
            )
        )

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = base_stmt.order_by(desc(StockLedgerEntry.entry_timestamp)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    rows = res.fetchall()

    out = []
    for entry, tx, variant, item in rows:
        out.append(StockLedgerEntryResponse(
            id=entry.id,
            transaction_id=tx.id,
            transaction_number=tx.transaction_number,
            transaction_type=tx.transaction_type,
            item_variant_id=variant.id,
            item_sku=item.sku,
            item_name=item.name,
            variant_name=variant.variant_name,
            batch_number=entry.batch.batch_number if entry.batch else None,
            serial_number=entry.serial_number,
            source_location_bin_id=entry.source_location_bin_id,
            source_bin_code=entry.source_bin.code if entry.source_bin else None,
            destination_location_bin_id=entry.destination_location_bin_id,
            destination_bin_code=entry.destination_bin.code if entry.destination_bin else None,
            quantity=float(entry.quantity),
            uom=entry.uom,
            unit_cost=float(entry.unit_cost),
            total_cost=float(entry.total_cost),
            posted_by_user_id=tx.posted_by_user_id,
            posted_by_user_name=tx.posted_by.full_name if tx.posted_by else None,
            posted_at=entry.entry_timestamp,
            notes=tx.notes
        ))

    return PaginatedResponse(
        items=out,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )
    )


# ============================================================================
# STOCK BALANCES & INVENTORY OVERVIEW
# ============================================================================

@router.get("/balances", response_model=PaginatedResponse[StockBalanceResponse])
async def list_stock_balances(
    warehouse_id: Optional[str] = Query(None),
    location_bin_id: Optional[str] = Query(None),
    item_variant_id: Optional[str] = Query(None),
    stock_status: Optional[str] = Query(None, description="all, in_stock, out_of_stock"),
    q: Optional[str] = Query(None, description="Search by SKU, item name, variant SKU, or bin code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    base_stmt = (
        select(StockBalanceCache, Warehouse, LocationBin, ItemVariant, Item)
        .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
        .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
        .join(ItemVariant, StockBalanceCache.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    )

    if warehouse_id:
        base_stmt = base_stmt.where(StockBalanceCache.warehouse_id == warehouse_id)
    if location_bin_id:
        base_stmt = base_stmt.where(StockBalanceCache.location_bin_id == location_bin_id)
    if item_variant_id:
        base_stmt = base_stmt.where(StockBalanceCache.item_variant_id == item_variant_id)

    if stock_status == "in_stock":
        base_stmt = base_stmt.where(StockBalanceCache.quantity_on_hand > 0)
    elif stock_status == "out_of_stock":
        base_stmt = base_stmt.where(StockBalanceCache.quantity_on_hand == 0)

    if q:
        search = f"%{q.strip()}%"
        base_stmt = base_stmt.where(
            or_(
                Item.sku.ilike(search),
                Item.name.ilike(search),
                ItemVariant.variant_sku.ilike(search),
                LocationBin.code.ilike(search)
            )
        )

    count_stmt = (
        select(func.count(StockBalanceCache.id))
        .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
        .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
        .join(ItemVariant, StockBalanceCache.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
    )
    if warehouse_id:
        count_stmt = count_stmt.where(StockBalanceCache.warehouse_id == warehouse_id)
    if location_bin_id:
        count_stmt = count_stmt.where(StockBalanceCache.location_bin_id == location_bin_id)
    if item_variant_id:
        count_stmt = count_stmt.where(StockBalanceCache.item_variant_id == item_variant_id)
    if stock_status == "in_stock":
        count_stmt = count_stmt.where(StockBalanceCache.quantity_on_hand > 0)
    elif stock_status == "out_of_stock":
        count_stmt = count_stmt.where(StockBalanceCache.quantity_on_hand == 0)
    if q:
        search = f"%{q.strip()}%"
        count_stmt = count_stmt.where(
            or_(
                Item.sku.ilike(search),
                Item.name.ilike(search),
                ItemVariant.variant_sku.ilike(search),
                LocationBin.code.ilike(search)
            )
        )

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = base_stmt.order_by(desc(StockBalanceCache.updated_at)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    rows = res.fetchall()

    out = []
    for bal, wh, bin_obj, variant, item in rows:
        q_hand = float(bal.quantity_on_hand)
        q_alloc = float(bal.quantity_allocated)
        out.append(StockBalanceResponse(
            id=bal.id,
            warehouse_id=wh.id,
            warehouse_code=wh.code,
            warehouse_name=wh.name,
            location_bin_id=bin_obj.id,
            bin_code=bin_obj.code,
            item_variant_id=variant.id,
            item_sku=item.sku,
            item_name=item.name,
            variant_sku=variant.variant_sku,
            variant_name=variant.variant_name,
            batch_number=bal.batch.batch_number if bal.batch else None,
            quantity_on_hand=q_hand,
            quantity_allocated=q_alloc,
            quantity_available=q_hand - q_alloc,
            updated_at=bal.updated_at
        ))

    return PaginatedResponse(
        items=out,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )
    )


# ============================================================================
# STOCK TRANSFERS
# ============================================================================

@router.post("/transfers")
async def record_stock_transfer(
    transfer_req: StockTransferRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("ledger:transfer"))
):
    tenant_id = claims["tenant_id"]

    if transfer_req.source_bin_id == transfer_req.destination_bin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination bins cannot be identical"
        )

    # Verify source bin & warehouse
    src_res = await db.execute(
        select(LocationBin, Warehouse)
        .join(Warehouse, LocationBin.warehouse_id == Warehouse.id)
        .where(LocationBin.id == transfer_req.source_bin_id, Warehouse.tenant_id == tenant_id)
    )
    src_row = src_res.first()
    if not src_row:
        raise HTTPException(status_code=404, detail="Source bin not found in tenant")
    src_bin, src_wh = src_row
    check_warehouse_scope(claims, src_wh.id)

    # Verify dest bin & warehouse
    dst_res = await db.execute(
        select(LocationBin, Warehouse)
        .join(Warehouse, LocationBin.warehouse_id == Warehouse.id)
        .where(LocationBin.id == transfer_req.destination_bin_id, Warehouse.tenant_id == tenant_id)
    )
    dst_row = dst_res.first()
    if not dst_row:
        raise HTTPException(status_code=404, detail="Destination bin not found in tenant")
    dst_bin, dst_wh = dst_row
    check_warehouse_scope(claims, dst_wh.id)

    # Find unit cost from variant
    var_res = await db.execute(
        select(ItemVariant, Item)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(ItemVariant.id == transfer_req.item_variant_id, Item.tenant_id == tenant_id)
    )
    var_row = var_res.first()
    if not var_row:
        raise HTTPException(status_code=404, detail="Item variant not found in tenant")
    variant, item = var_row

    # Execute deterministic row-locked ledger transfer
    tx_type = "TRANSFER_OUT" if src_wh.id != dst_wh.id else "INVENTORY_ADJUSTMENT"
    tx = await StockEngine.post_transaction(
        db=db,
        tenant_id=tenant_id,
        transaction_type=tx_type,
        entries_data=[{
            "item_variant_id": transfer_req.item_variant_id,
            "source_location_bin_id": transfer_req.source_bin_id,
            "destination_location_bin_id": transfer_req.destination_bin_id,
            "quantity": transfer_req.quantity,
            "unit_cost": variant.cost_price,
            "batch_number": transfer_req.batch_number,
            "uom": item.base_uom or "PCS"
        }],
        user_id=claims.get("sub"),
        notes=transfer_req.notes or f"Transfer from {src_bin.code} to {dst_bin.code}"
    )

    # If cross-warehouse transfer, execute cost basis transfer (FIFO layer clone or MWA blend)
    if src_wh.id != dst_wh.id:
        await CostingService.record_warehouse_transfer(
            db=db,
            tenant_id=tenant_id,
            source_warehouse_id=src_wh.id,
            dest_warehouse_id=dst_wh.id,
            item_variant_id=transfer_req.item_variant_id,
            quantity=Decimal(str(transfer_req.quantity)),
            stock_transaction_id=tx.id,
            user_id=claims.get("sub")
        )

    # Outer orchestrator atomic commit
    await db.commit()
    return {
        "message": "Transfer posted successfully",
        "transaction_id": tx.id,
        "transaction_number": tx.transaction_number,
        "source_bin": src_bin.code,
        "destination_bin": dst_bin.code,
        "quantity": float(transfer_req.quantity)
    }


# ============================================================================
# STOCK ADJUSTMENTS
# ============================================================================

@router.post("/adjustments")
async def record_stock_adjustment(
    adj_req: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:adjust"))
):
    tenant_id = claims["tenant_id"]

    if not adj_req.reason or not adj_req.reason.strip():
        raise HTTPException(status_code=400, detail="Adjustment reason is required")

    # Verify bin and warehouse scope
    bin_res = await db.execute(
        select(LocationBin, Warehouse)
        .join(Warehouse, LocationBin.warehouse_id == Warehouse.id)
        .where(LocationBin.id == adj_req.location_bin_id, Warehouse.tenant_id == tenant_id)
    )
    bin_row = bin_res.first()
    if not bin_row:
        raise HTTPException(status_code=404, detail="Location bin not found in tenant")
    bin_obj, bin_wh = bin_row
    check_warehouse_scope(claims, bin_wh.id)

    # Current balance across all batches in the selected bin with pessimistic lock
    bal_stmt = select(StockBalanceCache).where(
        StockBalanceCache.location_bin_id == adj_req.location_bin_id,
        StockBalanceCache.item_variant_id == adj_req.item_variant_id
    ).with_for_update()
    bal_res = await db.execute(bal_stmt)
    bals = bal_res.scalars().all()

    current_qty = sum([Decimal(str(b.quantity_on_hand)) for b in bals], Decimal("0.0"))
    
    diff = adj_req.counted_quantity - current_qty
    if diff == 0:
        return {"message": "No quantity variance detected; balances are already aligned"}

    var_res = await db.execute(
        select(ItemVariant, Item)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(ItemVariant.id == adj_req.item_variant_id, Item.tenant_id == tenant_id)
    )
    var_row = var_res.first()
    if not var_row:
        raise HTTPException(status_code=404, detail="Item variant not found in tenant")
    variant, item = var_row
    unit_cost = adj_req.unit_cost or (variant.cost_price if variant else Decimal("0.0"))

    if diff > 0:
        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type=adj_req.adjustment_type,
            entries_data=[{
                "item_variant_id": adj_req.item_variant_id,
                "destination_location_bin_id": adj_req.location_bin_id,
                "quantity": diff,
                "unit_cost": unit_cost,
                "batch_number": adj_req.batch_number,
                "uom": item.base_uom or "PCS"
            }],
            user_id=claims.get("sub"),
            notes=f"Physical Count Adjustment (+{diff}): {adj_req.reason}"
        )
    else:
        abs_diff = abs(diff)
        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type=adj_req.adjustment_type,
            entries_data=[{
                "item_variant_id": adj_req.item_variant_id,
                "source_location_bin_id": adj_req.location_bin_id,
                "quantity": abs_diff,
                "unit_cost": unit_cost,
                "batch_number": adj_req.batch_number,
                "uom": item.base_uom or "PCS"
            }],
            user_id=claims.get("sub"),
            notes=f"Physical Count Adjustment (-{abs_diff}): {adj_req.reason}"
        )

    # Record Inventory Cost Adjustment in Costing Subsystem
    await CostingService.record_inventory_adjustment(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=bin_wh.id,
        item_variant_id=adj_req.item_variant_id,
        quantity_diff=diff,
        unit_cost=Decimal(str(unit_cost)),
        stock_transaction_id=tx.id,
        reason=adj_req.reason,
        user_id=claims.get("sub")
    )

    # Outer orchestrator atomic commit
    await db.commit()
    return {
        "message": "Adjustment recorded successfully",
        "transaction_id": tx.id,
        "transaction_number": tx.transaction_number,
        "variance": float(diff),
        "new_balance": float(adj_req.counted_quantity)
    }
