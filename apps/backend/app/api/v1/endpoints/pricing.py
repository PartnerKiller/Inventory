import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.sales import PriceList, PriceListItem, PriceListTier, CustomerPriceList
from app.schemas.pricing import (
    PriceListCreate,
    PriceListUpdate,
    PriceListResponse,
    PriceListItemCreate,
    PriceListItemResponse,
    PriceListTierResponse,
    CustomerPriceListAssignRequest,
    PriceResolutionRequest,
    PriceResolutionResponse
)
from app.services.pricing_service import PricingService

router = APIRouter()

@router.get("/price-lists", response_model=List[PriceListResponse])
async def list_price_lists(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(PriceList)
        .options(selectinload(PriceList.items))
        .where(PriceList.tenant_id == tenant_id, PriceList.is_deleted == False)
        .order_by(PriceList.is_default.desc(), PriceList.name.asc())
    )
    res = await db.execute(stmt)
    price_lists = res.scalars().all()

    out = []
    for pl in price_lists:
        out.append(PriceListResponse(
            id=pl.id,
            tenant_id=pl.tenant_id,
            code=pl.code,
            name=pl.name,
            currency=pl.currency,
            valid_from=pl.valid_from,
            valid_to=pl.valid_to,
            is_active=pl.is_active,
            is_default=pl.is_default,
            notes=pl.notes,
            items_count=len(pl.items) if pl.items else 0,
            created_at=pl.created_at
        ))
    return out

@router.post("/price-lists", response_model=PriceListResponse, status_code=status.HTTP_201_CREATED)
async def create_price_list(
    pl_in: PriceListCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    pl = await PricingService.create_price_list(db, tenant_id, pl_in, claims.get("sub"))
    return PriceListResponse(
        id=pl.id,
        tenant_id=pl.tenant_id,
        code=pl.code,
        name=pl.name,
        currency=pl.currency,
        valid_from=pl.valid_from,
        valid_to=pl.valid_to,
        is_active=pl.is_active,
        is_default=pl.is_default,
        notes=pl.notes,
        items_count=0,
        created_at=pl.created_at
    )

@router.post("/price-lists/{price_list_id}/items", response_model=PriceListItemResponse, status_code=status.HTTP_201_CREATED)
async def add_price_list_item(
    price_list_id: str,
    item_in: PriceListItemCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    item_obj = await PricingService.add_or_update_price_list_item(db, tenant_id, price_list_id, item_in, claims.get("sub"))
    
    fetch_stmt = (
        select(PriceListItem)
        .options(
            selectinload(PriceListItem.variant).selectinload(PriceListItem.variant.property.mapper.class_.item),
            selectinload(PriceListItem.tiers)
        )
        .where(PriceListItem.id == item_obj.id)
    )
    res = await db.execute(fetch_stmt)
    full_item = res.scalar_one()

    return PriceListItemResponse(
        id=full_item.id,
        price_list_id=full_item.price_list_id,
        item_variant_id=full_item.item_variant_id,
        item_sku=full_item.variant.item.sku if full_item.variant and full_item.variant.item else "",
        item_name=full_item.variant.item.name if full_item.variant and full_item.variant.item else "",
        variant_sku=full_item.variant.variant_sku if full_item.variant else "",
        variant_name=full_item.variant.variant_name if full_item.variant else None,
        base_price=float(full_item.base_price),
        min_price=float(full_item.min_price) if full_item.min_price else None,
        tiers=[
            PriceListTierResponse(
                id=t.id,
                price_list_item_id=t.price_list_item_id,
                min_quantity=float(t.min_quantity),
                unit_price=float(t.unit_price),
                discount_pct=float(t.discount_pct or 0.0)
            ) for t in full_item.tiers
        ]
    )

@router.post("/customers/{customer_id}/assign")
async def assign_customer_price_list(
    customer_id: str,
    assign_in: CustomerPriceListAssignRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    cpl = await PricingService.assign_customer_price_list(
        db, tenant_id, customer_id, assign_in.price_list_id, assign_in.priority, claims.get("sub")
    )
    return {"message": "Customer assigned to price list successfully", "customer_price_list_id": cpl.id}

@router.post("/resolve", response_model=PriceResolutionResponse)
async def resolve_price(
    req: PriceResolutionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    return await PricingService.resolve_unit_price(
        db=db,
        tenant_id=tenant_id,
        customer_id=req.customer_id,
        item_variant_id=req.item_variant_id,
        quantity=req.quantity
    )
