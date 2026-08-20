import math
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, or_, and_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.models.base import get_utc_now
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse
from app.models.sales import SalesOrder, Shipment
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.schemas.costing import (
    CostLayerResponse, CostLayerConsumptionResponse, ItemCostProfileResponse,
    CostTransactionResponse, COGSRecordResponse, OperationalValuationReportResponse,
    ValuationWarehouseBreakdown, ValuationProductBreakdown, CostingMethodUpdateRequest,
    OpeningCostLayerMigrationRequest, MigrationStatusResponse
)
from app.services.costing_service import CostingService

router = APIRouter()

@router.get("/layers", response_model=PaginatedResponse[CostLayerResponse])
async def list_cost_layers(
    warehouse_id: Optional[str] = Query(None),
    item_variant_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    stmt = (
        select(CostLayer, Warehouse, ItemVariant, Item)
        .join(Warehouse, CostLayer.warehouse_id == Warehouse.id)
        .join(ItemVariant, CostLayer.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(CostLayer.tenant_id == tenant_id, CostLayer.is_deleted == False)
    )

    if warehouse_id:
        stmt = stmt.where(CostLayer.warehouse_id == warehouse_id)
    if item_variant_id:
        stmt = stmt.where(CostLayer.item_variant_id == item_variant_id)
    if status_filter and status_filter.upper() != "ALL":
        stmt = stmt.where(CostLayer.status == status_filter.upper())

    count_stmt = (
        select(func.count(CostLayer.id))
        .where(CostLayer.tenant_id == tenant_id, CostLayer.is_deleted == False)
    )
    if warehouse_id:
        count_stmt = count_stmt.where(CostLayer.warehouse_id == warehouse_id)
    if item_variant_id:
        count_stmt = count_stmt.where(CostLayer.item_variant_id == item_variant_id)
    if status_filter and status_filter.upper() != "ALL":
        count_stmt = count_stmt.where(CostLayer.status == status_filter.upper())

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = stmt.order_by(desc(CostLayer.layer_timestamp)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    rows = res.fetchall()

    out = []
    for layer, wh, var, itm in rows:
        out.append(CostLayerResponse(
            id=layer.id,
            tenant_id=layer.tenant_id,
            warehouse_id=layer.warehouse_id,
            warehouse_name=wh.name,
            warehouse_code=wh.code,
            item_variant_id=layer.item_variant_id,
            variant_sku=var.variant_sku,
            variant_name=var.variant_name,
            item_sku=itm.sku,
            item_name=itm.name,
            layer_number=layer.layer_number,
            original_quantity=float(layer.original_quantity),
            remaining_quantity=float(layer.remaining_quantity),
            unit_cost=float(layer.unit_cost),
            total_cost=float(layer.total_cost),
            status=layer.status,
            layer_timestamp=layer.layer_timestamp,
            notes=layer.notes
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

@router.get("/profiles", response_model=List[ItemCostProfileResponse])
async def list_cost_profiles(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    stmt = (
        select(ItemCostProfile, Warehouse, ItemVariant, Item)
        .join(Warehouse, ItemCostProfile.warehouse_id == Warehouse.id)
        .join(ItemVariant, ItemCostProfile.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(ItemCostProfile.tenant_id == tenant_id, ItemCostProfile.is_deleted == False)
    )
    if warehouse_id:
        stmt = stmt.where(ItemCostProfile.warehouse_id == warehouse_id)

    stmt = stmt.order_by(Item.sku.asc(), Warehouse.code.asc())
    res = await db.execute(stmt)
    rows = res.fetchall()

    return [
        ItemCostProfileResponse(
            id=prof.id,
            tenant_id=prof.tenant_id,
            warehouse_id=prof.warehouse_id,
            warehouse_name=wh.name,
            warehouse_code=wh.code,
            item_variant_id=prof.item_variant_id,
            variant_sku=var.variant_sku,
            variant_name=var.variant_name,
            item_sku=itm.sku,
            item_name=itm.name,
            costing_method=prof.costing_method,
            current_quantity=float(prof.current_quantity),
            current_total_value=float(prof.current_total_value),
            moving_average_cost=float(prof.moving_average_cost),
            standard_cost=float(prof.standard_cost),
            last_cost_recalculated_at=prof.last_cost_recalculated_at
        )
        for prof, wh, var, itm in rows
    ]

@router.put("/profiles/{warehouse_id}/{item_variant_id}/method", response_model=ItemCostProfileResponse)
async def update_profile_costing_method(
    warehouse_id: str,
    item_variant_id: str,
    method_req: CostingMethodUpdateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:write"))
):
    tenant_id = claims["tenant_id"]
    check_warehouse_scope(claims, warehouse_id)

    profile = await CostingService.get_or_create_cost_profile(db, tenant_id, warehouse_id, item_variant_id)
    profile.costing_method = method_req.costing_method
    profile.last_cost_recalculated_at = get_utc_now()
    await db.commit()

    # Re-fetch with details
    stmt = (
        select(ItemCostProfile, Warehouse, ItemVariant, Item)
        .join(Warehouse, ItemCostProfile.warehouse_id == Warehouse.id)
        .join(ItemVariant, ItemCostProfile.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(ItemCostProfile.id == profile.id)
    )
    res = await db.execute(stmt)
    prof, wh, var, itm = res.first()

    return ItemCostProfileResponse(
        id=prof.id,
        tenant_id=prof.tenant_id,
        warehouse_id=prof.warehouse_id,
        warehouse_name=wh.name,
        warehouse_code=wh.code,
        item_variant_id=prof.item_variant_id,
        variant_sku=var.variant_sku,
        variant_name=var.variant_name,
        item_sku=itm.sku,
        item_name=itm.name,
        costing_method=prof.costing_method,
        current_quantity=float(prof.current_quantity),
        current_total_value=float(prof.current_total_value),
        moving_average_cost=float(prof.moving_average_cost),
        standard_cost=float(prof.standard_cost),
        last_cost_recalculated_at=prof.last_cost_recalculated_at
    )

@router.get("/transactions", response_model=PaginatedResponse[CostTransactionResponse])
async def list_cost_transactions(
    warehouse_id: Optional[str] = Query(None),
    item_variant_id: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    stmt = (
        select(CostTransaction)
        .options(
            selectinload(CostTransaction.warehouse),
            selectinload(CostTransaction.variant),
            selectinload(CostTransaction.consumptions).selectinload(CostLayerConsumption.cost_layer)
        )
        .where(CostTransaction.tenant_id == tenant_id, CostTransaction.is_deleted == False)
    )
    if warehouse_id:
        stmt = stmt.where(CostTransaction.warehouse_id == warehouse_id)
    if item_variant_id:
        stmt = stmt.where(CostTransaction.item_variant_id == item_variant_id)
    if transaction_type and transaction_type.upper() != "ALL":
        stmt = stmt.where(CostTransaction.transaction_type == transaction_type.upper())

    count_stmt = select(func.count(CostTransaction.id)).where(CostTransaction.tenant_id == tenant_id, CostTransaction.is_deleted == False)
    if warehouse_id:
        count_stmt = count_stmt.where(CostTransaction.warehouse_id == warehouse_id)
    if item_variant_id:
        count_stmt = count_stmt.where(CostTransaction.item_variant_id == item_variant_id)
    if transaction_type and transaction_type.upper() != "ALL":
        count_stmt = count_stmt.where(CostTransaction.transaction_type == transaction_type.upper())

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = stmt.order_by(desc(CostTransaction.posted_at)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    txs = res.scalars().all()

    out = []
    for tx in txs:
        consumptions_out = [
            CostLayerConsumptionResponse(
                id=c.id,
                cost_layer_id=c.cost_layer_id,
                cost_transaction_id=c.cost_transaction_id,
                quantity_consumed=float(c.quantity_consumed),
                unit_cost=float(c.unit_cost),
                total_cost=float(c.total_cost),
                consumed_at=c.consumed_at,
                layer_number=c.cost_layer.layer_number if c.cost_layer else None
            )
            for c in tx.consumptions
        ]

        out.append(CostTransactionResponse(
            id=tx.id,
            tenant_id=tx.tenant_id,
            cost_transaction_number=tx.cost_transaction_number,
            transaction_type=tx.transaction_type,
            stock_transaction_id=tx.stock_transaction_id,
            warehouse_id=tx.warehouse_id,
            warehouse_name=tx.warehouse.name if tx.warehouse else None,
            item_variant_id=tx.item_variant_id,
            variant_sku=tx.variant.variant_sku if tx.variant else None,
            quantity=float(tx.quantity),
            unit_cost=float(tx.unit_cost),
            total_cost_impact=float(tx.total_cost_impact),
            costing_method=tx.costing_method,
            posted_at=tx.posted_at,
            notes=tx.notes,
            consumptions=consumptions_out
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

@router.get("/cogs", response_model=PaginatedResponse[COGSRecordResponse])
async def list_cogs_records(
    sales_order_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:read"))
):
    tenant_id = claims["tenant_id"]

    stmt = (
        select(COGSRecord)
        .options(
            selectinload(COGSRecord.sales_order),
            selectinload(COGSRecord.shipment),
            selectinload(COGSRecord.variant).selectinload(ItemVariant.item)
        )
        .where(COGSRecord.tenant_id == tenant_id, COGSRecord.is_deleted == False)
    )
    if sales_order_id:
        stmt = stmt.where(COGSRecord.sales_order_id == sales_order_id)
    if start_date:
        stmt = stmt.where(COGSRecord.recognized_at >= start_date)
    if end_date:
        stmt = stmt.where(COGSRecord.recognized_at <= end_date)

    count_stmt = select(func.count(COGSRecord.id)).where(COGSRecord.tenant_id == tenant_id, COGSRecord.is_deleted == False)
    if sales_order_id:
        count_stmt = count_stmt.where(COGSRecord.sales_order_id == sales_order_id)
    if start_date:
        count_stmt = count_stmt.where(COGSRecord.recognized_at >= start_date)
    if end_date:
        count_stmt = count_stmt.where(COGSRecord.recognized_at <= end_date)

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = stmt.order_by(desc(COGSRecord.recognized_at)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    cogs_list = res.scalars().all()

    out = [
        COGSRecordResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            sales_order_id=c.sales_order_id,
            sales_order_number=c.sales_order.so_number if c.sales_order else None,
            shipment_id=c.shipment_id,
            shipment_number=c.shipment.shipment_number if c.shipment else None,
            cost_transaction_id=c.cost_transaction_id,
            item_variant_id=c.item_variant_id,
            variant_sku=c.variant.variant_sku if c.variant else None,
            item_name=c.variant.item.name if c.variant and c.variant.item else None,
            quantity_shipped=float(c.quantity_shipped),
            unit_cogs=float(c.unit_cogs),
            total_cogs_amount=float(c.total_cogs_amount),
            recognized_at=c.recognized_at
        )
        for c in cogs_list
    ]

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

@router.get("/valuation", response_model=OperationalValuationReportResponse)
async def get_operational_valuation_report(
    warehouse_id: Optional[str] = Query(None),
    costing_method: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    # 1. Product Variant breakdown
    prod_stmt = (
        select(Item, ItemVariant, ItemCostProfile)
        .join(ItemVariant, Item.id == ItemVariant.item_id)
        .join(ItemCostProfile, ItemVariant.id == ItemCostProfile.item_variant_id)
        .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
    )
    if warehouse_id:
        prod_stmt = prod_stmt.where(ItemCostProfile.warehouse_id == warehouse_id)
    if costing_method and costing_method.upper() != "ALL":
        prod_stmt = prod_stmt.where(ItemCostProfile.costing_method == costing_method.upper())

    prod_res = await db.execute(prod_stmt)
    prod_rows = prod_res.fetchall()

    product_breakdown = []
    total_val = Decimal("0.0")
    total_units = Decimal("0.0")
    valuation_by_method: Dict[str, Decimal] = {"FIFO": Decimal("0.0"), "WEIGHTED_AVERAGE": Decimal("0.0"), "STANDARD_COST": Decimal("0.0")}

    for itm, var, prof in prod_rows:
        qty = Decimal(str(prof.current_quantity))
        val = Decimal(str(prof.current_total_value))
        avg_cost = Decimal(str(prof.moving_average_cost))

        # Check active layers count for FIFO
        layer_count_stmt = select(func.count(CostLayer.id)).where(
            CostLayer.tenant_id == tenant_id,
            CostLayer.item_variant_id == var.id,
            CostLayer.warehouse_id == prof.warehouse_id,
            CostLayer.status == "ACTIVE"
        )
        layer_count = (await db.execute(layer_count_stmt)).scalar() or 0

        total_val += val
        total_units += qty
        valuation_by_method[prof.costing_method] = valuation_by_method.get(prof.costing_method, Decimal("0.0")) + val

        product_breakdown.append(ValuationProductBreakdown(
            item_id=itm.id,
            item_sku=itm.sku,
            item_name=itm.name,
            variant_id=var.id,
            variant_sku=var.variant_sku,
            variant_name=var.variant_name,
            costing_method=prof.costing_method,
            total_quantity=float(qty),
            unit_cost=float(avg_cost),
            total_valuation=float(val),
            active_layer_count=layer_count
        ))

    # 2. Warehouse breakdown
    wh_stmt = (
        select(Warehouse, func.sum(ItemCostProfile.current_quantity), func.sum(ItemCostProfile.current_total_value), func.count(ItemCostProfile.id))
        .join(ItemCostProfile, Warehouse.id == ItemCostProfile.warehouse_id)
        .where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        .group_by(Warehouse.id)
    )
    if warehouse_id:
        wh_stmt = wh_stmt.where(Warehouse.id == warehouse_id)

    wh_res = await db.execute(wh_stmt)
    warehouse_breakdown = [
        ValuationWarehouseBreakdown(
            warehouse_id=wh.id,
            warehouse_code=wh.code,
            warehouse_name=wh.name,
            total_quantity=float(wh_qty or 0.0),
            total_valuation=float(wh_val or 0.0),
            item_count=wh_cnt or 0
        )
        for wh, wh_qty, wh_val, wh_cnt in wh_res.fetchall()
    ]

    return OperationalValuationReportResponse(
        total_valuation=float(total_val),
        total_units=float(total_units),
        valuation_by_method={k: float(v) for k, v in valuation_by_method.items()},
        warehouse_breakdown=warehouse_breakdown,
        product_breakdown=product_breakdown,
        generated_at=get_utc_now()
    )

@router.post("/opening-layers", response_model=MigrationStatusResponse)
async def initialize_opening_cost_layers(
    mig_req: OpeningCostLayerMigrationRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("costing:write"))
):
    tenant_id = claims["tenant_id"]
    if mig_req.warehouse_id:
        check_warehouse_scope(claims, mig_req.warehouse_id)

    res = await CostingService.initialize_opening_cost_layers(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=mig_req.warehouse_id,
        default_cost_if_missing=mig_req.default_cost_if_missing or Decimal("0.0")
    )
    await db.commit()
    return MigrationStatusResponse(
        status="SUCCESS",
        migrated_layers_count=res["migrated_layers_count"],
        total_quantity_migrated=res["total_quantity_migrated"],
        total_valuation_migrated=res["total_valuation_migrated"],
        message=res["message"]
    )
