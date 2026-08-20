import uuid
import math
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, or_
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.models.sales import SalesOrder, Customer, SOLineItem, SOAllocation, Shipment, SalesReturn, SalesReturnLine
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemVariant, Item
from app.schemas.sales import (
    SalesOrderCreate, SalesOrderUpdate, SalesOrderResponse, SalesOrderDetailResponse,
    SOLineResponse, SOAllocationDetail, ShipmentResponse, SalesReturnResponse, SalesReturnLineResponse,
    SOAllocateRequest, SOPickRequest, SOPackRequest, SODispatchRequest, SalesReturnCreate,
    CustomerCreate, CustomerUpdate, CustomerResponse,
    CustomerAddressCreate, CustomerAddressResponse, CustomerContactCreate, CustomerContactResponse,
    SOPlaceHoldRequest, SOReleaseHoldRequest, SOCreditOverrideRequest, SODeliveryConfirmRequest, RMAInspectRequest
)
from app.schemas.common import PaginatedResponse, PaginationMeta
from app.services.sales_service import SalesService

router = APIRouter()

def _get_so_eager_options():
    return [
        selectinload(SalesOrder.customer),
        selectinload(SalesOrder.warehouse),
        selectinload(SalesOrder.lines)
        .selectinload(SOLineItem.variant)
        .selectinload(ItemVariant.item),
        selectinload(SalesOrder.lines)
        .selectinload(SOLineItem.allocations)
        .selectinload(SOAllocation.location_bin),
    ]

# ============================================================================
# CUSTOMERS
# ============================================================================

@router.get("/customers", response_model=List[CustomerResponse])
async def list_customers(
    q: Optional[str] = Query(None, description="Search by customer name or code"),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Customer).where(Customer.tenant_id == tenant_id, Customer.is_deleted == False)

    if is_active is not None:
        stmt = stmt.where(Customer.is_active == is_active)
    if q:
        search = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(search), Customer.code.ilike(search)))

    stmt = stmt.order_by(Customer.name.asc())
    res = await db.execute(stmt)
    customers = res.scalars().all()

    out = []
    for c in customers:
        cnt_stmt = select(func.count(SalesOrder.id)).where(
            SalesOrder.customer_id == c.id,
            SalesOrder.status.in_(["DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "PACKED"]),
            SalesOrder.is_deleted == False
        )
        cnt_res = await db.execute(cnt_stmt)
        active_cnt = cnt_res.scalar() or 0

        out.append(CustomerResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            code=c.code,
            name=c.name,
            email=c.email,
            phone=c.phone,
            billing_address=c.billing_address or {},
            shipping_address=c.shipping_address or {},
            is_active=c.is_active,
            active_orders_count=active_cnt,
            created_at=c.created_at
        ))
    return out


@router.post("/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    cust_in: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]

    # Unique customer code within tenant
    dup_stmt = select(Customer).where(
        Customer.code == cust_in.code.upper().strip(),
        Customer.tenant_id == tenant_id,
        Customer.is_deleted == False
    )
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Customer code '{cust_in.code.upper()}' already exists in tenant")

    cust = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=cust_in.code.upper().strip(),
        name=cust_in.name.strip(),
        email=cust_in.email.strip() if cust_in.email else None,
        phone=cust_in.phone.strip() if cust_in.phone else None,
        billing_address=cust_in.billing_address or {},
        shipping_address=cust_in.shipping_address or {},
        is_active=cust_in.is_active
    )
    db.add(cust)
    await db.commit()
    await db.refresh(cust)
    return cust


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id, Customer.is_deleted == False)
    res = await db.execute(stmt)
    cust = res.scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    return cust


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    cust_in: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id, Customer.is_deleted == False)
    res = await db.execute(stmt)
    cust = res.scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    if cust_in.name is not None:
        cust.name = cust_in.name.strip()
    if cust_in.email is not None:
        cust.email = cust_in.email.strip() or None
    if cust_in.phone is not None:
        cust.phone = cust_in.phone.strip() or None
    if cust_in.billing_address is not None:
        cust.billing_address = cust_in.billing_address
    if cust_in.shipping_address is not None:
        cust.shipping_address = cust_in.shipping_address
    if cust_in.is_active is not None:
        cust.is_active = cust_in.is_active

    await db.commit()
    await db.refresh(cust)
    return cust


@router.delete("/customers/{customer_id}")
async def delete_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id, Customer.is_deleted == False)
    res = await db.execute(stmt)
    cust = res.scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Guard: Active sales orders check
    so_stmt = select(func.count(SalesOrder.id)).where(
        SalesOrder.customer_id == customer_id,
        SalesOrder.status.in_(["DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "PACKED"]),
        SalesOrder.is_deleted == False
    )
    so_res = await db.execute(so_stmt)
    active_sos = so_res.scalar() or 0
    if active_sos > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot archive customer '{cust.name}': {active_sos} active sales order(s) exist"
        )

    cust.is_deleted = True
    cust.is_active = False
    await db.commit()
    return {"message": f"Customer {cust.name} archived successfully"}


@router.post("/customers/{customer_id}/addresses", response_model=CustomerAddressResponse, status_code=status.HTTP_201_CREATED)
async def add_customer_address(
    customer_id: str,
    addr_in: CustomerAddressCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    return await SalesService.create_customer_address(db, tenant_id, customer_id, addr_in)


@router.post("/customers/{customer_id}/contacts", response_model=CustomerContactResponse, status_code=status.HTTP_201_CREATED)
async def add_customer_contact(
    customer_id: str,
    contact_in: CustomerContactCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    return await SalesService.create_customer_contact(db, tenant_id, customer_id, contact_in)


# ============================================================================
# SALES ORDERS
# ============================================================================

def _build_so_response(so: SalesOrder) -> SalesOrderResponse:
    lines_out = []
    for l in so.lines:
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

        alloc_out = []
        if hasattr(l, "allocations") and l.allocations:
            for al in l.allocations:
                alloc_out.append(SOAllocationDetail(
                    location_bin_id=al.location_bin_id,
                    bin_code=al.location_bin.code if al.location_bin else "",
                    quantity_allocated=float(al.quantity_allocated)
                ))

        lines_out.append(SOLineResponse(
            id=l.id,
            sales_order_id=l.sales_order_id,
            item_variant_id=l.item_variant_id,
            item_sku=item_sku,
            item_name=item_name,
            variant_sku=variant_sku,
            variant_name=variant_name,
            quantity_ordered=float(l.quantity_ordered),
            quantity_allocated=float(l.quantity_allocated or 0.0),
            quantity_backordered=float(l.quantity_backordered or 0.0),
            quantity_picked=float(l.quantity_picked or 0.0),
            quantity_shipped=float(l.quantity_shipped or 0.0),
            quantity_returned=float(l.quantity_returned or 0.0),
            quantity_cancelled=float(l.quantity_cancelled or 0.0),
            unit_price=float(l.unit_price),
            discount_pct=float(l.discount_pct or 0.0),
            tax_pct=float(l.tax_pct or 0.0),
            line_total=float(l.line_total),
            allocations=alloc_out
        ))

    return SalesOrderResponse(
        id=so.id,
        tenant_id=so.tenant_id,
        so_number=so.so_number,
        customer_id=so.customer_id,
        customer_name=so.customer.name if so.customer else "",
        customer_code=so.customer.code if so.customer else "",
        warehouse_id=so.warehouse_id,
        warehouse_name=so.warehouse.name if so.warehouse else "",
        warehouse_code=so.warehouse.code if so.warehouse else "",
        status=so.status,
        hold_reason=so.hold_reason,
        hold_placed_at=so.hold_placed_at,
        delivery_confirmed_at=so.delivery_confirmed_at,
        delivery_notes=so.delivery_notes,
        subtotal_amount=float(so.subtotal_amount or 0.0),
        discount_amount=float(so.discount_amount or 0.0),
        tax_amount=float(so.tax_amount or 0.0),
        total_amount=float(so.total_amount),
        ordered_at=so.ordered_at,
        notes=so.notes,
        lines=lines_out,
        created_at=so.created_at
    )


@router.get("", response_model=PaginatedResponse[SalesOrderResponse])
async def list_sales_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    customer_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by SO number or customer name"),
    sort_by: str = Query("ordered_at", pattern="^(ordered_at|so_number|total_amount|status)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    base_stmt = (
        select(SalesOrder)
        .options(*_get_so_eager_options())
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .where(SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    )

    if status_filter and status_filter.upper() != "ALL":
        base_stmt = base_stmt.where(SalesOrder.status == status_filter.upper())
    if customer_id:
        base_stmt = base_stmt.where(SalesOrder.customer_id == customer_id)
    if warehouse_id:
        base_stmt = base_stmt.where(SalesOrder.warehouse_id == warehouse_id)
    if q:
        search = f"%{q.strip()}%"
        base_stmt = base_stmt.where(or_(SalesOrder.so_number.ilike(search), Customer.name.ilike(search)))

    count_stmt = (
        select(func.count(SalesOrder.id))
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .where(SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    )
    if status_filter and status_filter.upper() != "ALL":
        count_stmt = count_stmt.where(SalesOrder.status == status_filter.upper())
    if customer_id:
        count_stmt = count_stmt.where(SalesOrder.customer_id == customer_id)
    if warehouse_id:
        count_stmt = count_stmt.where(SalesOrder.warehouse_id == warehouse_id)
    if q:
        search = f"%{q.strip()}%"
        count_stmt = count_stmt.where(or_(SalesOrder.so_number.ilike(search), Customer.name.ilike(search)))

    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    sort_col = getattr(SalesOrder, sort_by, SalesOrder.ordered_at)
    order_func = desc if sort_dir == "desc" else asc
    offset = (page - 1) * page_size
    paged_stmt = base_stmt.order_by(order_func(sort_col)).offset(offset).limit(page_size)
    res = await db.execute(paged_stmt)
    sos = res.scalars().all()

    out = [_build_so_response(so) for so in sos]

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


@router.post("", response_model=SalesOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_sales_order(
    so_in: SalesOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    check_warehouse_scope(claims, so_in.warehouse_id)
    so = await SalesService.create_sales_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_in=so_in,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.get("/{so_id}", response_model=SalesOrderDetailResponse)
async def get_sales_order_detail(
    so_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    res = await db.execute(stmt)
    so = res.scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="Sales Order not found")

    check_warehouse_scope(claims, so.warehouse_id)
    base_resp = _build_so_response(so)

    # Fetch Shipments
    shp_stmt = select(Shipment).where(Shipment.sales_order_id == so.id).order_by(desc(Shipment.shipped_at))
    shp_res = await db.execute(shp_stmt)
    shipments = [
        ShipmentResponse(
            id=s.id,
            shipment_number=s.shipment_number,
            carrier=s.carrier,
            tracking_number=s.tracking_number,
            package_count=s.package_count,
            total_weight=float(s.total_weight) if s.total_weight else None,
            shipped_at=s.shipped_at,
            notes=s.notes
        ) for s in shp_res.scalars().all()
    ]

    # Fetch Returns
    ret_stmt = (
        select(SalesReturn)
        .options(
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.variant).selectinload(ItemVariant.item),
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.destination_bin)
        )
        .where(SalesReturn.sales_order_id == so.id)
        .order_by(desc(SalesReturn.returned_at))
    )
    ret_res = await db.execute(ret_stmt)
    returns_out = []
    for r in ret_res.scalars().all():
        lines_r = [
            SalesReturnLineResponse(
                id=rl.id,
                so_line_id=rl.so_line_id,
                item_variant_id=rl.item_variant_id,
                item_sku=rl.variant.item.sku if rl.variant and rl.variant.item else "",
                item_name=rl.variant.item.name if rl.variant and rl.variant.item else "",
                quantity_returned=float(rl.quantity_returned),
                condition=rl.condition,
                destination_bin_id=rl.destination_bin_id,
                destination_bin_code=rl.destination_bin.code if rl.destination_bin else ""
            ) for rl in r.lines
        ]
        returns_out.append(SalesReturnResponse(
            id=r.id,
            return_number=r.return_number,
            sales_order_id=r.sales_order_id,
            status=r.status,
            returned_at=r.returned_at,
            notes=r.notes,
            lines=lines_r
        ))

    return SalesOrderDetailResponse(
        **base_resp.model_dump(),
        shipments=shipments,
        returns=returns_out
    )


@router.put("/{so_id}", response_model=SalesOrderResponse)
async def update_draft_sales_order(
    so_id: str,
    so_in: SalesOrderUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")

    check_warehouse_scope(claims, existing_so.warehouse_id)
    if so_in.warehouse_id:
        check_warehouse_scope(claims, so_in.warehouse_id)

    so = await SalesService.update_draft_sales_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        so_in=so_in,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/confirm", response_model=SalesOrderResponse)
async def confirm_sales_order(
    so_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    so = await SalesService.confirm_sales_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/allocate", response_model=SalesOrderResponse)
async def allocate_sales_order_stock(
    so_id: str,
    alloc_req: Optional[SOAllocateRequest] = None,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:allocate"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    so = await SalesService.allocate_stock(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        alloc_req=alloc_req,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/pick", response_model=SalesOrderResponse)
async def pick_sales_order_items(
    so_id: str,
    pick_req: SOPickRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    so = await SalesService.pick_items(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        pick_req=pick_req,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/pack", response_model=SalesOrderResponse)
async def pack_sales_order(
    so_id: str,
    pack_req: SOPackRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    so = await SalesService.pack_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        pack_req=pack_req,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/dispatch", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def dispatch_sales_order(
    so_id: str,
    dispatch_req: SODispatchRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    shipment = await SalesService.dispatch_sales_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        dispatch_req=dispatch_req,
        user_id=claims.get("sub"),
        client_type=claims.get("client_type", "WEB")
    )
    return ShipmentResponse(
        id=shipment.id,
        shipment_number=shipment.shipment_number,
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        package_count=shipment.package_count,
        total_weight=float(shipment.total_weight) if shipment.total_weight else None,
        shipped_at=shipment.shipped_at,
        notes=shipment.notes
    )


@router.post("/{so_id}/cancel", response_model=SalesOrderResponse)
async def cancel_sales_order(
    so_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    so = await SalesService.cancel_sales_order(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        user_id=claims.get("sub")
    )
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.delete("/{so_id}")
async def delete_draft_sales_order(
    so_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    res = await db.execute(stmt)
    so = res.scalar_one_or_none()
    if not so:
        raise HTTPException(status_code=404, detail="Sales Order not found")

    check_warehouse_scope(claims, so.warehouse_id)

    if so.status != "DRAFT":
        raise HTTPException(status_code=400, detail=f"Cannot delete sales order in '{so.status}' status (only DRAFT SOs can be deleted)")

    so.is_deleted = True
    await db.commit()
    return {"message": f"Sales order {so.so_number} deleted"}


@router.post("/{so_id}/returns", response_model=SalesReturnResponse, status_code=status.HTTP_201_CREATED)
async def process_sales_order_return(
    so_id: str,
    return_in: SalesReturnCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    existing_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
    existing_res = await db.execute(existing_stmt)
    existing_so = existing_res.scalar_one_or_none()
    if not existing_so:
        raise HTTPException(status_code=404, detail="Sales Order not found")
    check_warehouse_scope(claims, existing_so.warehouse_id)

    sales_return = await SalesService.process_sales_return(
        db=db,
        tenant_id=claims["tenant_id"],
        so_id=so_id,
        return_in=return_in,
        user_id=claims.get("sub"),
        client_type=claims.get("client_type", "WEB")
    )

    fetch_stmt = (
        select(SalesReturn)
        .options(
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.variant).selectinload(ItemVariant.item),
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.destination_bin)
        )
        .where(SalesReturn.id == sales_return.id)
    )
    res = await db.execute(fetch_stmt)
    full_ret = res.scalar_one()

    lines_r = [
        SalesReturnLineResponse(
            id=rl.id,
            so_line_id=rl.so_line_id,
            item_variant_id=rl.item_variant_id,
            item_sku=rl.variant.item.sku if rl.variant and rl.variant.item else "",
            item_name=rl.variant.item.name if rl.variant and rl.variant.item else "",
            quantity_returned=float(rl.quantity_returned),
            condition=rl.condition,
            destination_bin_id=rl.destination_bin_id,
            destination_bin_code=rl.destination_bin.code if rl.destination_bin else ""
        ) for rl in full_ret.lines
    ]

    return SalesReturnResponse(
        id=full_ret.id,
        return_number=full_ret.return_number,
        sales_order_id=full_ret.sales_order_id,
        status=full_ret.status,
        rma_status=full_ret.rma_status,
        inspection_notes=full_ret.inspection_notes,
        disposition=full_ret.disposition,
        returned_at=full_ret.returned_at,
        notes=full_ret.notes,
        lines=lines_r
    )


@router.post("/{so_id}/hold", response_model=SalesOrderResponse)
async def place_order_hold(
    so_id: str,
    hold_in: SOPlaceHoldRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    so = await SalesService.place_order_hold(db, tenant_id, so_id, hold_in.reason, claims.get("sub"))
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/release-hold", response_model=SalesOrderResponse)
async def release_order_hold(
    so_id: str,
    rel_in: SOReleaseHoldRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:confirm"))
):
    tenant_id = claims["tenant_id"]
    so = await SalesService.release_order_hold(db, tenant_id, so_id, rel_in.notes, claims.get("sub"))
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/credit-override", response_model=SalesOrderResponse)
async def override_credit_limit(
    so_id: str,
    ovr_in: SOCreditOverrideRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:credit_override"))
):
    tenant_id = claims["tenant_id"]
    so = await SalesService.override_credit_limit(db, tenant_id, so_id, ovr_in.reason, claims.get("sub"))
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/{so_id}/generate-pick-task")
async def generate_pick_task(
    so_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:write"))
):
    tenant_id = claims["tenant_id"]
    pick_task = await SalesService.generate_pick_task_for_sales_order(db, tenant_id, so_id, claims.get("sub"))
    return {
        "message": f"Pick task {pick_task.task_number} generated successfully",
        "pick_task_id": pick_task.id,
        "task_number": pick_task.task_number
    }


@router.post("/{so_id}/confirm-delivery", response_model=SalesOrderResponse)
async def confirm_delivery(
    so_id: str,
    del_in: SODeliveryConfirmRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    so = await SalesService.confirm_delivery(db, tenant_id, so_id, del_in.delivery_notes, claims.get("sub"))
    fetch_stmt = select(SalesOrder).options(*_get_so_eager_options()).where(SalesOrder.id == so.id)
    res = await db.execute(fetch_stmt)
    return _build_so_response(res.scalar_one())


@router.post("/returns/{return_id}/inspect", response_model=SalesReturnResponse)
async def inspect_sales_return(
    return_id: str,
    inspect_in: RMAInspectRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:return"))
):
    tenant_id = claims["tenant_id"]
    sales_return = await SalesService.inspect_sales_return(db, tenant_id, return_id, inspect_in, claims.get("sub"))
    fetch_stmt = (
        select(SalesReturn)
        .options(
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.variant).selectinload(ItemVariant.item),
            selectinload(SalesReturn.lines).selectinload(SalesReturnLine.destination_bin)
        )
        .where(SalesReturn.id == sales_return.id)
    )
    res = await db.execute(fetch_stmt)
    full_ret = res.scalar_one()

    lines_r = [
        SalesReturnLineResponse(
            id=rl.id,
            so_line_id=rl.so_line_id,
            item_variant_id=rl.item_variant_id,
            item_sku=rl.variant.item.sku if rl.variant and rl.variant.item else "",
            item_name=rl.variant.item.name if rl.variant and rl.variant.item else "",
            quantity_returned=float(rl.quantity_returned),
            condition=rl.condition,
            destination_bin_id=rl.destination_bin_id,
            destination_bin_code=rl.destination_bin.code if rl.destination_bin else ""
        ) for rl in full_ret.lines
    ]

    return SalesReturnResponse(
        id=full_ret.id,
        return_number=full_ret.return_number,
        sales_order_id=full_ret.sales_order_id,
        status=full_ret.status,
        rma_status=full_ret.rma_status,
        inspection_notes=full_ret.inspection_notes,
        disposition=full_ret.disposition,
        returned_at=full_ret.returned_at,
        notes=full_ret.notes,
        lines=lines_r
    )
