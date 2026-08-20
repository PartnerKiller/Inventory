import uuid
import math
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, or_
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.models.purchasing import PurchaseOrder, Supplier, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemVariant, Item
from app.schemas.purchasing import (
    PurchaseOrderCreate, PurchaseOrderUpdate, PurchaseOrderResponse, PurchaseOrderDetailResponse,
    POLineResponse, GoodsReceiptCreate, GoodsReceiptResponse, GoodsReceiptLineResponse,
    SupplierCreate, SupplierUpdate, SupplierResponse
)
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.services.purchase_service import PurchaseService

router = APIRouter()

def _get_po_eager_options():
    return [
        selectinload(PurchaseOrder.supplier),
        selectinload(PurchaseOrder.target_warehouse),
        selectinload(PurchaseOrder.lines)
        .selectinload(POLineItem.variant)
        .selectinload(ItemVariant.item),
    ]

# ============================================================================
# SUPPLIERS
# ============================================================================

@router.get("/suppliers", response_model=List[SupplierResponse])
async def list_suppliers(
    q: Optional[str] = Query(None, description="Search by supplier name or code"),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)

    if is_active is not None:
        stmt = stmt.where(Supplier.is_active == is_active)
    if q:
        search = f"%{q.strip()}%"
        stmt = stmt.where(or_(Supplier.name.ilike(search), Supplier.code.ilike(search)))

    stmt = stmt.order_by(Supplier.name.asc())
    res = await db.execute(stmt)
    suppliers = res.scalars().all()

    out = []
    for s in suppliers:
        cnt_stmt = select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.supplier_id == s.id,
            PurchaseOrder.status.in_(["DRAFT", "PENDING_APPROVAL", "APPROVED", "PARTIALLY_RECEIVED"]),
            PurchaseOrder.is_deleted == False
        )
        cnt_res = await db.execute(cnt_stmt)
        active_cnt = cnt_res.scalar() or 0

        out.append(SupplierResponse(
            id=s.id,
            tenant_id=s.tenant_id,
            code=s.code,
            name=s.name,
            email=s.email,
            phone=s.phone,
            address=s.address or {},
            payment_terms=s.payment_terms,
            currency=s.currency,
            is_active=s.is_active,
            active_orders_count=active_cnt,
            created_at=s.created_at
        ))
    return out


@router.post("/suppliers", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    sup_in: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]

    dup_stmt = select(Supplier).where(
        Supplier.code == sup_in.code.upper().strip(),
        Supplier.tenant_id == tenant_id,
        Supplier.is_deleted == False
    )
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Supplier code '{sup_in.code.upper()}' already exists in tenant")

    sup = Supplier(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=sup_in.code.upper().strip(),
        name=sup_in.name.strip(),
        email=sup_in.email.strip() if sup_in.email else None,
        phone=sup_in.phone.strip() if sup_in.phone else None,
        address=sup_in.address or {},
        payment_terms=sup_in.payment_terms,
        currency=sup_in.currency.upper(),
        is_active=sup_in.is_active
    )
    db.add(sup)
    await db.commit()
    await db.refresh(sup)
    return sup


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
    res = await db.execute(stmt)
    sup = res.scalar_one_or_none()
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return sup


@router.put("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: str,
    sup_in: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
    res = await db.execute(stmt)
    sup = res.scalar_one_or_none()
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")

    if sup_in.name is not None:
        sup.name = sup_in.name.strip()
    if sup_in.email is not None:
        sup.email = sup_in.email.strip() or None
    if sup_in.phone is not None:
        sup.phone = sup_in.phone.strip() or None
    if sup_in.address is not None:
        sup.address = sup_in.address
    if sup_in.payment_terms is not None:
        sup.payment_terms = sup_in.payment_terms
    if sup_in.currency is not None:
        sup.currency = sup_in.currency.upper()
    if sup_in.is_active is not None:
        sup.is_active = sup_in.is_active

    await db.commit()
    await db.refresh(sup)
    return sup


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
    res = await db.execute(stmt)
    sup = res.scalar_one_or_none()
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")

    po_stmt = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.supplier_id == supplier_id,
        PurchaseOrder.status.in_(["DRAFT", "PENDING_APPROVAL", "APPROVED", "PARTIALLY_RECEIVED"]),
        PurchaseOrder.is_deleted == False
    )
    po_res = await db.execute(po_stmt)
    active_pos = po_res.scalar() or 0
    if active_pos > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot archive supplier '{sup.name}': {active_pos} active purchase order(s) exist"
        )

    sup.is_deleted = True
    sup.is_active = False
    await db.commit()
    return {"message": f"Supplier {sup.name} archived successfully"}


# ============================================================================
# PURCHASE ORDERS
# ============================================================================

def _build_po_response(po: PurchaseOrder) -> PurchaseOrderResponse:
    lines_out = []
    for l in po.lines:
        ordered = float(l.quantity_ordered)
        received = float(l.quantity_received)
        
        variant_sku = ""
        variant_name = ""
        item_sku = ""
        item_name = ""

        if l.variant:
            variant_sku = l.variant.variant_sku
            variant_name = l.variant.variant_name or ""
            if l.variant.item:
                item_sku = l.variant.item.sku
                item_name = l.variant.item.name

        lines_out.append(POLineResponse(
            id=l.id,
            purchase_order_id=l.purchase_order_id,
            item_variant_id=l.item_variant_id,
            item_sku=item_sku,
            item_name=item_name,
            variant_sku=variant_sku,
            variant_name=variant_name,
            quantity_ordered=ordered,
            quantity_received=received,
            quantity_remaining=max(0.0, ordered - received),
            unit_price=float(l.unit_price),
            discount_pct=float(l.discount_pct or 0.0),
            tax_pct=float(l.tax_pct or 0.0),
            line_total=float(l.line_total)
        ))

    return PurchaseOrderResponse(
        id=po.id,
        tenant_id=po.tenant_id,
        po_number=po.po_number,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name if po.supplier else "",
        supplier_code=po.supplier.code if po.supplier else "",
        target_warehouse_id=po.target_warehouse_id,
        target_warehouse_name=po.target_warehouse.name if po.target_warehouse else "",
        target_warehouse_code=po.target_warehouse.code if po.target_warehouse else "",
        status=po.status,
        subtotal_amount=float(po.subtotal_amount or 0.0),
        discount_amount=float(po.discount_amount or 0.0),
        tax_amount=float(po.tax_amount or 0.0),
        total_amount=float(po.total_amount),
        ordered_at=po.ordered_at,
        expected_delivery_at=po.expected_delivery_at,
        notes=po.notes,
        lines=lines_out,
        created_at=po.created_at
    )


@router.get("", response_model=PaginatedResponse[PurchaseOrderResponse])
async def list_purchase_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    supplier_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by PO number or supplier name"),
    sort_by: str = Query("ordered_at", pattern="^(ordered_at|po_number|total_amount|status)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    base_stmt = (
        select(PurchaseOrder)
        .options(*_get_po_eager_options())
        .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    )

    if status_filter and status_filter.upper() != "ALL":
        base_stmt = base_stmt.where(PurchaseOrder.status == status_filter.upper())
    if supplier_id:
        base_stmt = base_stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if warehouse_id:
        base_stmt = base_stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)
    if q:
        search = f"%{q.strip()}%"
        base_stmt = base_stmt.where(or_(PurchaseOrder.po_number.ilike(search), Supplier.name.ilike(search)))

    count_stmt = (
        select(func.count(PurchaseOrder.id))
        .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    )
    if status_filter and status_filter.upper() != "ALL":
        count_stmt = count_stmt.where(PurchaseOrder.status == status_filter.upper())
    if supplier_id:
        count_stmt = count_stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if warehouse_id:
        count_stmt = count_stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)
    if q:
        search = f"%{q.strip()}%"
        count_stmt = count_stmt.where(or_(PurchaseOrder.po_number.ilike(search), Supplier.name.ilike(search)))

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    sort_col = getattr(PurchaseOrder, sort_by, PurchaseOrder.ordered_at)
    order_func = desc if sort_dir == "desc" else asc
    offset = (page - 1) * page_size
    paged_stmt = base_stmt.order_by(order_func(sort_col)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    pos = res.scalars().all()

    out = [_build_po_response(po) for po in pos]

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


@router.post("", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    po_in: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    check_warehouse_scope(claims, po_in.target_warehouse_id)
    po = await PurchaseService.create_purchase_order(
        db=db,
        tenant_id=claims["tenant_id"],
        po_in=po_in,
        user_id=claims.get("sub")
    )
    # Re-fetch with all eager loads
    fetch_stmt = select(PurchaseOrder).options(*_get_po_eager_options()).where(PurchaseOrder.id == po.id)
    res = await db.execute(fetch_stmt)
    full_po = res.scalar_one()
    return _build_po_response(full_po)


@router.get("/{po_id}", response_model=PurchaseOrderDetailResponse)
async def get_purchase_order_detail(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(PurchaseOrder)
        .options(*_get_po_eager_options())
        .where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    )
    res = await db.execute(stmt)
    po = res.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    check_warehouse_scope(claims, po.target_warehouse_id)
    base_resp = _build_po_response(po)

    # Fetch Receipts with eager loads
    gr_stmt = (
        select(GoodsReceipt)
        .options(
            selectinload(GoodsReceipt.warehouse),
            selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.destination_bin),
            selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.variant).selectinload(ItemVariant.item)
        )
        .where(GoodsReceipt.purchase_order_id == po.id)
        .order_by(desc(GoodsReceipt.received_at))
    )
    gr_res = await db.execute(gr_stmt)
    gr_list = gr_res.scalars().all()

    receipts_out = []
    for gr in gr_list:
        lines_gr = []
        for gl in gr.lines:
            item_sku = gl.variant.item.sku if gl.variant and gl.variant.item else ""
            item_name = gl.variant.item.name if gl.variant and gl.variant.item else ""
            lines_gr.append(GoodsReceiptLineResponse(
                id=gl.id,
                po_line_id=gl.po_line_id,
                item_variant_id=gl.item_variant_id,
                item_sku=item_sku,
                item_name=item_name,
                quantity_received=float(gl.quantity_received),
                destination_bin_id=gl.destination_bin_id,
                destination_bin_code=gl.destination_bin.code if gl.destination_bin else "",
                batch_number=gl.batch_number,
                expiry_date=gl.expiry_date
            ))

        receipts_out.append(GoodsReceiptResponse(
            id=gr.id,
            grn_number=gr.grn_number,
            purchase_order_id=gr.purchase_order_id,
            warehouse_id=gr.warehouse_id,
            warehouse_name=gr.warehouse.name if gr.warehouse else "",
            received_at=gr.received_at,
            notes=gr.notes,
            lines=lines_gr
        ))

    return PurchaseOrderDetailResponse(
        **base_resp.model_dump(),
        receipts=receipts_out
    )


@router.put("/{po_id}", response_model=PurchaseOrderResponse)
async def update_draft_purchase_order(
    po_id: str,
    po_in: PurchaseOrderUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_po = existing_res.scalar_one_or_none()
    if not existing_po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    check_warehouse_scope(claims, existing_po.target_warehouse_id)
    if po_in.target_warehouse_id:
        check_warehouse_scope(claims, po_in.target_warehouse_id)

    po = await PurchaseService.update_draft_purchase_order(
        db=db,
        tenant_id=claims["tenant_id"],
        po_id=po_id,
        po_in=po_in,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(PurchaseOrder).options(*_get_po_eager_options()).where(PurchaseOrder.id == po.id)
    res = await db.execute(fetch_stmt)
    return _build_po_response(res.scalar_one())


@router.post("/{po_id}/submit", response_model=PurchaseOrderResponse)
async def submit_po_for_approval(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_po = existing_res.scalar_one_or_none()
    if not existing_po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    check_warehouse_scope(claims, existing_po.target_warehouse_id)

    po = await PurchaseService.submit_for_approval(
        db=db,
        tenant_id=claims["tenant_id"],
        po_id=po_id,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(PurchaseOrder).options(*_get_po_eager_options()).where(PurchaseOrder.id == po.id)
    res = await db.execute(fetch_stmt)
    return _build_po_response(res.scalar_one())


@router.post("/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:approve"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_po = existing_res.scalar_one_or_none()
    if not existing_po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    check_warehouse_scope(claims, existing_po.target_warehouse_id)

    po = await PurchaseService.approve_purchase_order(
        db=db,
        tenant_id=claims["tenant_id"],
        po_id=po_id,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(PurchaseOrder).options(*_get_po_eager_options()).where(PurchaseOrder.id == po.id)
    res = await db.execute(fetch_stmt)
    return _build_po_response(res.scalar_one())


@router.post("/{po_id}/cancel", response_model=PurchaseOrderResponse)
async def cancel_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_po = existing_res.scalar_one_or_none()
    if not existing_po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    check_warehouse_scope(claims, existing_po.target_warehouse_id)

    po = await PurchaseService.cancel_purchase_order(
        db=db,
        tenant_id=claims["tenant_id"],
        po_id=po_id,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(PurchaseOrder).options(*_get_po_eager_options()).where(PurchaseOrder.id == po.id)
    res = await db.execute(fetch_stmt)
    return _build_po_response(res.scalar_one())


@router.delete("/{po_id}")
async def delete_draft_purchase_order(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
    res = await db.execute(stmt)
    po = res.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    check_warehouse_scope(claims, po.target_warehouse_id)

    if po.status != "DRAFT":
        raise HTTPException(status_code=400, detail=f"Cannot delete purchase order in '{po.status}' status (only DRAFT POs can be deleted)")

    po.is_deleted = True
    await db.commit()
    return {"message": f"Purchase order {po.po_number} deleted"}


# ============================================================================
# GOODS RECEIPT (GRN)
# ============================================================================

@router.post("/receive", response_model=GoodsReceiptResponse, status_code=status.HTTP_201_CREATED)
async def receive_goods(
    gr_in: GoodsReceiptCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:receive"))
):
    check_warehouse_scope(claims, gr_in.warehouse_id)
    gr = await PurchaseService.receive_goods(
        db=db,
        tenant_id=claims["tenant_id"],
        gr_in=gr_in,
        user_id=claims.get("sub"),
        client_type=claims.get("client_type", "WEB")
    )

    fetch_stmt = (
        select(GoodsReceipt)
        .options(
            selectinload(GoodsReceipt.warehouse),
            selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.destination_bin),
            selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.variant).selectinload(ItemVariant.item)
        )
        .where(GoodsReceipt.id == gr.id)
    )
    res = await db.execute(fetch_stmt)
    full_gr = res.scalar_one()

    lines_gr = []
    for gl in full_gr.lines:
        item_sku = gl.variant.item.sku if gl.variant and gl.variant.item else ""
        item_name = gl.variant.item.name if gl.variant and gl.variant.item else ""
        lines_gr.append(GoodsReceiptLineResponse(
            id=gl.id,
            po_line_id=gl.po_line_id,
            item_variant_id=gl.item_variant_id,
            item_sku=item_sku,
            item_name=item_name,
            quantity_received=float(gl.quantity_received),
            destination_bin_id=gl.destination_bin_id,
            destination_bin_code=gl.destination_bin.code if gl.destination_bin else "",
            batch_number=gl.batch_number,
            expiry_date=gl.expiry_date
        ))

    return GoodsReceiptResponse(
        id=full_gr.id,
        grn_number=full_gr.grn_number,
        purchase_order_id=full_gr.purchase_order_id,
        warehouse_id=full_gr.warehouse_id,
        warehouse_name=full_gr.warehouse.name if full_gr.warehouse else "",
        received_at=full_gr.received_at,
        notes=full_gr.notes,
        lines=lines_gr
    )
