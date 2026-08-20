import uuid
import math
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, desc, asc
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.item import Item, ItemVariant, Barcode, ItemCategory
from app.models.ledger import StockBalanceCache
from app.models.warehouse import Warehouse, LocationBin
from app.models.base import get_utc_now
from app.schemas.item import (
    ItemCreate, ItemUpdate, ItemResponse, ItemDetailResponse,
    ItemVariantCreate, ItemVariantUpdate, ItemVariantResponse,
    BarcodeCreate, BarcodeResponse,
    ItemCategoryCreate, ItemCategoryUpdate, ItemCategoryResponse,
    VariantBinStock
)
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.services.audit_service import AuditService

router = APIRouter()

async def _fetch_full_item(db: AsyncSession, item_id: str, tenant_id: str) -> Optional[Item]:
    stmt = (
        select(Item)
        .options(
            selectinload(Item.variants).selectinload(ItemVariant.barcodes),
            selectinload(Item.category)
        )
        .where(Item.id == item_id, Item.tenant_id == tenant_id, Item.is_deleted == False)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def _build_item_response(db: AsyncSession, itm: Item, warehouse_id: Optional[str] = None) -> ItemResponse:
    variants_out = []
    item_total_stock = 0.0
    for v in itm.variants:
        if v.is_deleted:
            continue
        bal_stmt = select(
            func.sum(StockBalanceCache.quantity_on_hand),
            func.sum(StockBalanceCache.quantity_allocated)
        ).where(StockBalanceCache.item_variant_id == v.id)
        if warehouse_id:
            bal_stmt = bal_stmt.where(StockBalanceCache.warehouse_id == warehouse_id)
        bal_res = await db.execute(bal_stmt)
        q_hand, q_alloc = bal_res.first()
        q_hand = float(q_hand or 0.0)
        q_alloc = float(q_alloc or 0.0)
        q_avail = q_hand - q_alloc
        item_total_stock += q_hand

        barcodes_out = [
            BarcodeResponse(
                id=b.id,
                item_variant_id=b.item_variant_id,
                barcode_value=b.barcode_value,
                symbology=b.symbology,
                is_primary=b.is_primary
            ) for b in v.barcodes if not b.is_deleted
        ]

        variants_out.append(ItemVariantResponse(
            id=v.id,
            item_id=v.item_id,
            variant_sku=v.variant_sku,
            variant_name=v.variant_name,
            attributes=v.attributes or {},
            cost_price=float(v.cost_price),
            selling_price=float(v.selling_price),
            barcodes=barcodes_out,
            current_stock=q_hand,
            allocated_stock=q_alloc,
            available_stock=q_avail
        ))

    return ItemResponse(
        id=itm.id,
        tenant_id=itm.tenant_id,
        category_id=itm.category_id,
        category_name=itm.category.name if itm.category else None,
        sku=itm.sku,
        name=itm.name,
        description=itm.description,
        base_uom=itm.base_uom,
        valuation_method=itm.valuation_method,
        reorder_point=float(itm.reorder_point),
        reorder_quantity=float(itm.reorder_quantity),
        is_batch_tracked=itm.is_batch_tracked,
        is_serial_tracked=itm.is_serial_tracked,
        is_active=itm.is_active,
        variants=variants_out,
        total_stock=item_total_stock,
        created_at=itm.created_at,
        updated_at=itm.updated_at
    )

# ============================================================================
# CATEGORIES ENDPOINTS
# ============================================================================

@router.get("/categories", response_model=List[ItemCategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(
            ItemCategory,
            func.count(Item.id).label("item_count")
        )
        .outerjoin(Item, (Item.category_id == ItemCategory.id) & (Item.is_deleted == False))
        .where(ItemCategory.tenant_id == tenant_id, ItemCategory.is_deleted == False)
        .group_by(ItemCategory.id)
        .order_by(ItemCategory.name)
    )
    res = await db.execute(stmt)
    rows = res.fetchall()

    out = []
    for cat, count in rows:
        out.append(ItemCategoryResponse(
            id=cat.id,
            tenant_id=cat.tenant_id,
            parent_id=cat.parent_id,
            name=cat.name,
            code=cat.code,
            description=cat.description,
            item_count=count or 0,
            created_at=cat.created_at
        ))
    return out

@router.post("/categories", response_model=ItemCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    cat_in: ItemCategoryCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    code_check = await db.execute(
        select(ItemCategory).where(
            ItemCategory.tenant_id == tenant_id,
            ItemCategory.code == cat_in.code.upper(),
            ItemCategory.is_deleted == False
        )
    )
    if code_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category with code '{cat_in.code.upper()}' already exists in tenant"
        )

    cat = ItemCategory(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        parent_id=cat_in.parent_id,
        name=cat_in.name,
        code=cat_in.code.upper(),
        description=cat_in.description
    )
    db.add(cat)
    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="ItemCategory",
        entity_id=cat.id,
        user_id=claims.get("sub"),
        changes={"code": cat.code, "name": cat.name}
    )
    await db.commit()
    await db.refresh(cat)

    return ItemCategoryResponse(
        id=cat.id,
        tenant_id=cat.tenant_id,
        parent_id=cat.parent_id,
        name=cat.name,
        code=cat.code,
        description=cat.description,
        item_count=0,
        created_at=cat.created_at
    )

@router.put("/categories/{category_id}", response_model=ItemCategoryResponse)
async def update_category(
    category_id: str,
    cat_in: ItemCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(ItemCategory).where(
            ItemCategory.id == category_id,
            ItemCategory.tenant_id == tenant_id,
            ItemCategory.is_deleted == False
        )
    )
    cat = res.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if cat_in.code and cat_in.code.upper() != cat.code:
        code_check = await db.execute(
            select(ItemCategory).where(
                ItemCategory.tenant_id == tenant_id,
                ItemCategory.code == cat_in.code.upper(),
                ItemCategory.id != category_id,
                ItemCategory.is_deleted == False
            )
        )
        if code_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Category code '{cat_in.code.upper()}' is already in use")
        cat.code = cat_in.code.upper()

    if cat_in.name is not None:
        cat.name = cat_in.name
    if cat_in.description is not None:
        cat.description = cat_in.description
    if cat_in.parent_id is not None:
        cat.parent_id = cat_in.parent_id

    cat.updated_at = get_utc_now()
    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="UPDATE",
        entity_type="ItemCategory",
        entity_id=cat.id,
        user_id=claims.get("sub"),
        changes=cat_in.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(cat)

    count_res = await db.execute(select(func.count(Item.id)).where(Item.category_id == cat.id, Item.is_deleted == False))
    return ItemCategoryResponse(
        id=cat.id,
        tenant_id=cat.tenant_id,
        parent_id=cat.parent_id,
        name=cat.name,
        code=cat.code,
        description=cat.description,
        item_count=count_res.scalar() or 0,
        created_at=cat.created_at
    )

@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:delete"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(ItemCategory).where(
            ItemCategory.id == category_id,
            ItemCategory.tenant_id == tenant_id,
            ItemCategory.is_deleted == False
        )
    )
    cat = res.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    items_attached = await db.execute(
        select(func.count(Item.id)).where(Item.category_id == category_id, Item.is_deleted == False)
    )
    if (items_attached.scalar() or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete category with active products assigned. Reassign products first."
        )

    cat.is_deleted = True
    cat.updated_at = get_utc_now()
    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="DELETE",
        entity_type="ItemCategory",
        entity_id=cat.id,
        user_id=claims.get("sub")
    )
    await db.commit()
    return {"message": "Category deleted successfully"}


# ============================================================================
# PRODUCTS / ITEMS LIST & CRUD
# ============================================================================

@router.get("", response_model=PaginatedResponse[ItemResponse])
async def list_items(
    q: Optional[str] = Query(None, description="Search by SKU, Name, or Barcode"),
    category_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None, description="Scope stock quantities to specific warehouse"),
    is_active: Optional[bool] = Query(None),
    stock_status: Optional[str] = Query(None, description="all, in_stock, low_stock, out_of_stock"),
    sort_by: str = Query("created_at", description="sku, name, created_at"),
    sort_dir: str = Query("desc", description="asc, desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    base_stmt = (
        select(Item)
        .options(
            selectinload(Item.variants).selectinload(ItemVariant.barcodes),
            selectinload(Item.category)
        )
        .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
    )

    if q:
        search = f"%{q.strip()}%"
        barcode_subquery = (
            select(ItemVariant.item_id)
            .join(Barcode, Barcode.item_variant_id == ItemVariant.id)
            .where(Barcode.barcode_value.ilike(search), Barcode.is_deleted == False)
        )
        variant_sku_subquery = (
            select(ItemVariant.item_id)
            .where(ItemVariant.variant_sku.ilike(search), ItemVariant.is_deleted == False)
        )
        base_stmt = base_stmt.where(
            or_(
                Item.name.ilike(search),
                Item.sku.ilike(search),
                Item.id.in_(barcode_subquery),
                Item.id.in_(variant_sku_subquery)
            )
        )

    if category_id:
        base_stmt = base_stmt.where(Item.category_id == category_id)

    if is_active is not None:
        base_stmt = base_stmt.where(Item.is_active == is_active)

    # Sorting
    sort_by_str = str(sort_by) if sort_by else "created_at"
    sort_dir_str = str(sort_dir) if sort_dir else "desc"
    order_col = Item.created_at
    if sort_by_str == "sku":
        order_col = Item.sku
    elif sort_by_str == "name":
        order_col = Item.name

    if sort_dir_str.lower() == "asc":
        base_stmt = base_stmt.order_by(asc(order_col))
    else:
        base_stmt = base_stmt.order_by(desc(order_col))

    # Total count calculation
    count_stmt = select(func.count(Item.id)).where(Item.tenant_id == tenant_id, Item.is_deleted == False)
    if q:
        count_stmt = count_stmt.where(
            or_(
                Item.name.ilike(search),
                Item.sku.ilike(search),
                Item.id.in_(barcode_subquery),
                Item.id.in_(variant_sku_subquery)
            )
        )
    if category_id:
        count_stmt = count_stmt.where(Item.category_id == category_id)
    if is_active is not None:
        count_stmt = count_stmt.where(Item.is_active == is_active)

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = base_stmt.offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    items = res.scalars().all()

    out = []
    for itm in items:
        resp = await _build_item_response(db, itm, warehouse_id=warehouse_id)
        if stock_status == "in_stock" and (resp.total_stock or 0.0) <= 0:
            continue
        if stock_status == "out_of_stock" and (resp.total_stock or 0.0) > 0:
            continue
        if stock_status == "low_stock" and (resp.total_stock or 0.0) > float(itm.reorder_point):
            continue
        out.append(resp)

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

@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    item_in: ItemCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]

    stmt = select(Item).where(Item.tenant_id == tenant_id, Item.sku == item_in.sku.upper(), Item.is_deleted == False)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Product SKU '{item_in.sku.upper()}' already exists in tenant")

    new_item = Item(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=item_in.category_id,
        sku=item_in.sku.upper().strip(),
        name=item_in.name.strip(),
        description=item_in.description,
        base_uom=item_in.base_uom,
        valuation_method=item_in.valuation_method,
        reorder_point=item_in.reorder_point,
        reorder_quantity=item_in.reorder_quantity,
        is_batch_tracked=item_in.is_batch_tracked,
        is_serial_tracked=item_in.is_serial_tracked,
        is_active=True
    )
    db.add(new_item)
    await db.flush()

    variants_to_create = item_in.variants
    if not variants_to_create:
        variants_to_create = [ItemVariantCreate(
            variant_sku=f"{new_item.sku}-STD",
            variant_name="Standard",
            attributes={},
            cost_price=Decimal("0.0"),
            selling_price=Decimal("0.0"),
            barcodes=[BarcodeCreate(barcode_value=f"{new_item.sku}001", symbology="CODE128", is_primary=True)]
        )]

    for var_data in variants_to_create:
        var_sku_check = await db.execute(
            select(ItemVariant)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(Item.tenant_id == tenant_id, ItemVariant.variant_sku == var_data.variant_sku.upper())
        )
        if var_sku_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Variant SKU '{var_data.variant_sku.upper()}' already exists")

        variant = ItemVariant(
            id=str(uuid.uuid4()),
            item_id=new_item.id,
            variant_sku=var_data.variant_sku.upper().strip(),
            variant_name=var_data.variant_name.strip(),
            attributes=var_data.attributes,
            cost_price=var_data.cost_price,
            selling_price=var_data.selling_price
        )
        db.add(variant)
        await db.flush()

        for bc in var_data.barcodes:
            bc_check = await db.execute(
                select(Barcode)
                .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
                .join(Item, ItemVariant.item_id == Item.id)
                .where(Item.tenant_id == tenant_id, Barcode.barcode_value == bc.barcode_value.strip())
            )
            if bc_check.scalar_one_or_none():
                raise HTTPException(status_code=400, detail=f"Barcode '{bc.barcode_value}' is already assigned to another item")

            b_obj = Barcode(
                id=str(uuid.uuid4()),
                item_variant_id=variant.id,
                barcode_value=bc.barcode_value.strip(),
                symbology=bc.symbology,
                is_primary=bc.is_primary
            )
            db.add(b_obj)

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="Item",
        entity_id=new_item.id,
        user_id=claims.get("sub"),
        changes={"sku": new_item.sku, "name": new_item.name}
    )

    await db.commit()

    full_item = await _fetch_full_item(db, new_item.id, tenant_id)
    return await _build_item_response(db, full_item)

@router.get("/{item_id}", response_model=ItemDetailResponse)
async def get_item_detail(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    itm = await _fetch_full_item(db, item_id, tenant_id)
    if not itm:
        raise HTTPException(status_code=404, detail="Item not found in tenant")

    variants_out = []
    item_total_stock = 0.0
    bin_stock_breakdown = []

    for v in itm.variants:
        if v.is_deleted:
            continue
        bal_stmt = (
            select(StockBalanceCache, Warehouse, LocationBin)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .where(StockBalanceCache.item_variant_id == v.id)
        )
        bal_res = await db.execute(bal_stmt)
        bals = bal_res.fetchall()

        q_hand_total = 0.0
        q_alloc_total = 0.0
        for b_cache, wh, bin_obj in bals:
            qh = float(b_cache.quantity_on_hand)
            qa = float(b_cache.quantity_allocated)
            q_hand_total += qh
            q_alloc_total += qa
            if qh > 0 or qa > 0:
                bin_stock_breakdown.append(VariantBinStock(
                    warehouse_id=wh.id,
                    warehouse_name=wh.name,
                    warehouse_code=wh.code,
                    location_bin_id=bin_obj.id,
                    bin_code=bin_obj.code,
                    batch_number=b_cache.batch.batch_number if b_cache.batch else None,
                    quantity_on_hand=qh,
                    quantity_allocated=qa,
                    quantity_available=qh - qa
                ))

        item_total_stock += q_hand_total

        barcodes_out = [
            BarcodeResponse(
                id=b.id,
                item_variant_id=b.item_variant_id,
                barcode_value=b.barcode_value,
                symbology=b.symbology,
                is_primary=b.is_primary
            ) for b in v.barcodes if not b.is_deleted
        ]

        variants_out.append(ItemVariantResponse(
            id=v.id,
            item_id=v.item_id,
            variant_sku=v.variant_sku,
            variant_name=v.variant_name,
            attributes=v.attributes or {},
            cost_price=float(v.cost_price),
            selling_price=float(v.selling_price),
            barcodes=barcodes_out,
            current_stock=q_hand_total,
            allocated_stock=q_alloc_total,
            available_stock=q_hand_total - q_alloc_total
        ))

    return ItemDetailResponse(
        id=itm.id,
        tenant_id=itm.tenant_id,
        category_id=itm.category_id,
        category_name=itm.category.name if itm.category else None,
        sku=itm.sku,
        name=itm.name,
        description=itm.description,
        base_uom=itm.base_uom,
        valuation_method=itm.valuation_method,
        reorder_point=float(itm.reorder_point),
        reorder_quantity=float(itm.reorder_quantity),
        is_batch_tracked=itm.is_batch_tracked,
        is_serial_tracked=itm.is_serial_tracked,
        is_active=itm.is_active,
        variants=variants_out,
        total_stock=item_total_stock,
        bin_stock_breakdown=bin_stock_breakdown,
        created_at=itm.created_at,
        updated_at=itm.updated_at
    )

@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    item_in: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    itm = await _fetch_full_item(db, item_id, tenant_id)
    if not itm:
        raise HTTPException(status_code=404, detail="Item not found in tenant")

    if item_in.sku and item_in.sku.upper() != itm.sku:
        sku_check = await db.execute(
            select(Item).where(
                Item.tenant_id == tenant_id,
                Item.sku == item_in.sku.upper(),
                Item.id != item_id,
                Item.is_deleted == False
            )
        )
        if sku_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Product SKU '{item_in.sku.upper()}' is already in use")
        itm.sku = item_in.sku.upper().strip()

    if item_in.name is not None:
        itm.name = item_in.name.strip()
    if item_in.description is not None:
        itm.description = item_in.description
    if item_in.category_id is not None:
        itm.category_id = item_in.category_id
    if item_in.base_uom is not None:
        itm.base_uom = item_in.base_uom
    if item_in.valuation_method is not None:
        itm.valuation_method = item_in.valuation_method
    if item_in.reorder_point is not None:
        itm.reorder_point = item_in.reorder_point
    if item_in.reorder_quantity is not None:
        itm.reorder_quantity = item_in.reorder_quantity
    if item_in.is_batch_tracked is not None:
        itm.is_batch_tracked = item_in.is_batch_tracked
    if item_in.is_serial_tracked is not None:
        itm.is_serial_tracked = item_in.is_serial_tracked
    if item_in.is_active is not None:
        itm.is_active = item_in.is_active

    itm.updated_at = get_utc_now()

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="UPDATE",
        entity_type="Item",
        entity_id=itm.id,
        user_id=claims.get("sub"),
        changes=item_in.model_dump(exclude_unset=True)
    )

    await db.commit()

    full_item = await _fetch_full_item(db, itm.id, tenant_id)
    return await _build_item_response(db, full_item)

@router.delete("/{item_id}")
async def delete_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:delete"))
):
    tenant_id = claims["tenant_id"]
    itm = await _fetch_full_item(db, item_id, tenant_id)
    if not itm:
        raise HTTPException(status_code=404, detail="Item not found in tenant")

    # Safety constraint: Check if any variant has active on-hand stock
    variant_ids = [v.id for v in itm.variants if not v.is_deleted]
    if variant_ids:
        stock_check = await db.execute(
            select(func.sum(StockBalanceCache.quantity_on_hand)).where(
                StockBalanceCache.item_variant_id.in_(variant_ids),
                StockBalanceCache.quantity_on_hand > 0
            )
        )
        total_stock = stock_check.scalar() or 0
        if total_stock > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete product '{itm.sku}' with active inventory balance ({total_stock} units on hand). Adjust or transfer stock to zero before archiving."
            )

    itm.is_deleted = True
    itm.updated_at = get_utc_now()

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="DELETE",
        entity_type="Item",
        entity_id=itm.id,
        user_id=claims.get("sub")
    )

    await db.commit()
    return {"message": f"Product '{itm.sku}' archived successfully"}


# ============================================================================
# VARIANTS & BARCODES NESTED CRUD
# ============================================================================

@router.post("/{item_id}/variants", response_model=ItemVariantResponse, status_code=status.HTTP_201_CREATED)
async def add_item_variant(
    item_id: str,
    var_in: ItemVariantCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    itm = await _fetch_full_item(db, item_id, tenant_id)
    if not itm:
        raise HTTPException(status_code=404, detail="Parent product not found in tenant")

    # Check variant SKU uniqueness
    var_check = await db.execute(
        select(ItemVariant)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(Item.tenant_id == tenant_id, ItemVariant.variant_sku == var_in.variant_sku.upper())
    )
    if var_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Variant SKU '{var_in.variant_sku.upper()}' already exists")

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=itm.id,
        variant_sku=var_in.variant_sku.upper().strip(),
        variant_name=var_in.variant_name.strip(),
        attributes=var_in.attributes or {},
        cost_price=var_in.cost_price,
        selling_price=var_in.selling_price
    )
    db.add(variant)
    await db.flush()

    barcodes_out = []
    for bc in var_in.barcodes:
        b_obj = Barcode(
            id=str(uuid.uuid4()),
            item_variant_id=variant.id,
            barcode_value=bc.barcode_value.strip(),
            symbology=bc.symbology,
            is_primary=bc.is_primary
        )
        db.add(b_obj)
        barcodes_out.append(BarcodeResponse(
            id=b_obj.id,
            item_variant_id=variant.id,
            barcode_value=b_obj.barcode_value,
            symbology=b_obj.symbology,
            is_primary=b_obj.is_primary
        ))

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="ItemVariant",
        entity_id=variant.id,
        user_id=claims.get("sub"),
        changes={"variant_sku": variant.variant_sku, "item_id": itm.id}
    )

    await db.commit()
    await db.refresh(variant)

    return ItemVariantResponse(
        id=variant.id,
        item_id=variant.item_id,
        variant_sku=variant.variant_sku,
        variant_name=variant.variant_name,
        attributes=variant.attributes or {},
        cost_price=float(variant.cost_price),
        selling_price=float(variant.selling_price),
        barcodes=barcodes_out,
        current_stock=0.0,
        allocated_stock=0.0,
        available_stock=0.0
    )

@router.put("/{item_id}/variants/{variant_id}", response_model=ItemVariantResponse)
async def update_item_variant(
    item_id: str,
    variant_id: str,
    var_in: ItemVariantUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(ItemVariant)
        .options(selectinload(ItemVariant.barcodes))
        .join(Item, ItemVariant.item_id == Item.id)
        .where(
            ItemVariant.id == variant_id,
            ItemVariant.item_id == item_id,
            Item.tenant_id == tenant_id,
            Item.is_deleted == False
        )
    )
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    if var_in.variant_sku and var_in.variant_sku.upper() != variant.variant_sku:
        check_sku = await db.execute(
            select(ItemVariant)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(
                Item.tenant_id == tenant_id,
                ItemVariant.variant_sku == var_in.variant_sku.upper(),
                ItemVariant.id != variant_id
            )
        )
        if check_sku.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Variant SKU '{var_in.variant_sku.upper()}' is already in use")
        variant.variant_sku = var_in.variant_sku.upper().strip()

    if var_in.variant_name is not None:
        variant.variant_name = var_in.variant_name.strip()
    if var_in.cost_price is not None:
        variant.cost_price = var_in.cost_price
    if var_in.selling_price is not None:
        variant.selling_price = var_in.selling_price
    if var_in.attributes is not None:
        variant.attributes = var_in.attributes

    variant.updated_at = get_utc_now()
    await db.commit()

    # Re-fetch with loaded barcodes
    fresh_res = await db.execute(
        select(ItemVariant)
        .options(selectinload(ItemVariant.barcodes))
        .where(ItemVariant.id == variant_id)
    )
    fresh_var = fresh_res.scalar_one()

    bal_stmt = select(
        func.sum(StockBalanceCache.quantity_on_hand),
        func.sum(StockBalanceCache.quantity_allocated)
    ).where(StockBalanceCache.item_variant_id == variant.id)
    bal_res = await db.execute(bal_stmt)
    q_hand, q_alloc = bal_res.first()
    q_hand = float(q_hand or 0.0)
    q_alloc = float(q_alloc or 0.0)

    barcodes_out = [
        BarcodeResponse(
            id=b.id,
            item_variant_id=b.item_variant_id,
            barcode_value=b.barcode_value,
            symbology=b.symbology,
            is_primary=b.is_primary
        ) for b in fresh_var.barcodes if not b.is_deleted
    ]

    return ItemVariantResponse(
        id=fresh_var.id,
        item_id=fresh_var.item_id,
        variant_sku=fresh_var.variant_sku,
        variant_name=fresh_var.variant_name,
        attributes=fresh_var.attributes or {},
        cost_price=float(fresh_var.cost_price),
        selling_price=float(fresh_var.selling_price),
        barcodes=barcodes_out,
        current_stock=q_hand,
        allocated_stock=q_alloc,
        available_stock=q_hand - q_alloc
    )

@router.delete("/{item_id}/variants/{variant_id}")
async def delete_item_variant(
    item_id: str,
    variant_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:delete"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(ItemVariant)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(
            ItemVariant.id == variant_id,
            ItemVariant.item_id == item_id,
            Item.tenant_id == tenant_id,
            Item.is_deleted == False
        )
    )
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    stock_check = await db.execute(
        select(func.sum(StockBalanceCache.quantity_on_hand)).where(
            StockBalanceCache.item_variant_id == variant_id,
            StockBalanceCache.quantity_on_hand > 0
        )
    )
    total_stock = stock_check.scalar() or 0
    if total_stock > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete variant with {total_stock} units in stock")

    variant.is_deleted = True
    variant.updated_at = get_utc_now()
    await db.commit()
    return {"message": "Variant archived successfully"}

@router.post("/{item_id}/variants/{variant_id}/barcodes", response_model=BarcodeResponse, status_code=status.HTTP_201_CREATED)
async def add_variant_barcode(
    item_id: str,
    variant_id: str,
    bc_in: BarcodeCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:write"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(ItemVariant)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(
            ItemVariant.id == variant_id,
            ItemVariant.item_id == item_id,
            Item.tenant_id == tenant_id,
            Item.is_deleted == False
        )
    )
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Variant not found in tenant")

    bc_check = await db.execute(
        select(Barcode)
        .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(Item.tenant_id == tenant_id, Barcode.barcode_value == bc_in.barcode_value.strip())
    )
    if bc_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Barcode '{bc_in.barcode_value}' is already assigned")

    b_obj = Barcode(
        id=str(uuid.uuid4()),
        item_variant_id=variant_id,
        barcode_value=bc_in.barcode_value.strip(),
        symbology=bc_in.symbology,
        is_primary=bc_in.is_primary
    )
    db.add(b_obj)
    await db.commit()
    await db.refresh(b_obj)

    return BarcodeResponse(
        id=b_obj.id,
        item_variant_id=b_obj.item_variant_id,
        barcode_value=b_obj.barcode_value,
        symbology=b_obj.symbology,
        is_primary=b_obj.is_primary
    )

@router.delete("/{item_id}/variants/{variant_id}/barcodes/{barcode_id}")
async def delete_variant_barcode(
    item_id: str,
    variant_id: str,
    barcode_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:delete"))
):
    tenant_id = claims["tenant_id"]
    res = await db.execute(
        select(Barcode)
        .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(
            Barcode.id == barcode_id,
            Barcode.item_variant_id == variant_id,
            ItemVariant.item_id == item_id,
            Item.tenant_id == tenant_id
        )
    )
    bc = res.scalar_one_or_none()
    if not bc:
        raise HTTPException(status_code=404, detail="Barcode not found")

    bc.is_deleted = True
    bc.updated_at = get_utc_now()
    await db.commit()
    return {"message": "Barcode deleted successfully"}
