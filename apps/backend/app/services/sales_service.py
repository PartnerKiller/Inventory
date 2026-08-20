import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from fastapi import HTTPException, status
from app.models.sales import (
    SalesOrder,
    SOLineItem,
    SOAllocation,
    Shipment,
    SalesReturn,
    SalesReturnLine,
    Customer,
    CustomerAddress,
    CustomerContact
)
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemVariant, Item
from app.models.ledger import StockBalanceCache
from app.models.warehouse_ops import PickTask, PickTaskLine
from app.models.base import get_utc_now
from app.schemas.sales import (
    SalesOrderCreate,
    SalesOrderUpdate,
    SOAllocateRequest,
    SOPickRequest,
    SOPackRequest,
    SODispatchRequest,
    SalesReturnCreate,
    CustomerAddressCreate,
    CustomerContactCreate,
    RMAInspectRequest
)
from app.services.stock_engine import StockEngine
from app.services.audit_service import AuditService
from app.services.sequence_service import SequenceService
from app.services.costing_service import CostingService

class SalesService:
    @staticmethod
    def _compute_line_totals(lines_data: list) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """Calculates subtotal, discount, tax, and grand total."""
        subtotal = Decimal("0.0")
        discount_total = Decimal("0.0")
        tax_total = Decimal("0.0")

        for line in lines_data:
            qty = Decimal(str(line.quantity_ordered))
            price = Decimal(str(line.unit_price))
            disc_pct = Decimal(str(line.discount_pct or 0.0))
            tax_pct = Decimal(str(line.tax_pct or 0.0))

            base_amt = qty * price
            disc_amt = base_amt * (disc_pct / Decimal("100.0"))
            after_disc = base_amt - disc_amt
            tax_amt = after_disc * (tax_pct / Decimal("100.0"))

            subtotal += base_amt
            discount_total += disc_amt
            tax_total += tax_amt

        grand_total = subtotal - discount_total + tax_total
        return subtotal, discount_total, tax_total, grand_total

    @staticmethod
    async def create_customer_address(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        addr_in: CustomerAddressCreate
    ) -> CustomerAddress:
        cust = (await db.execute(
            select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        addr = CustomerAddress(
            id=str(uuid.uuid4()),
            customer_id=cust.id,
            address_type=addr_in.address_type,
            label=addr_in.label,
            street1=addr_in.street1,
            street2=addr_in.street2,
            city=addr_in.city,
            state=addr_in.state,
            postal_code=addr_in.postal_code,
            country=addr_in.country,
            is_default=addr_in.is_default
        )
        db.add(addr)
        await db.commit()
        await db.refresh(addr)
        return addr

    @staticmethod
    async def create_customer_contact(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        contact_in: CustomerContactCreate
    ) -> CustomerContact:
        cust = (await db.execute(
            select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        contact = CustomerContact(
            id=str(uuid.uuid4()),
            customer_id=cust.id,
            first_name=contact_in.first_name,
            last_name=contact_in.last_name,
            email=contact_in.email,
            phone=contact_in.phone,
            job_title=contact_in.job_title,
            is_primary=contact_in.is_primary
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact

    @classmethod
    async def calculate_customer_credit_exposure(
        cls,
        db: AsyncSession,
        tenant_id: str,
        customer_id: str
    ) -> Decimal:
        """Calculates total credit exposure from active non-delivered orders and customer open AR exposure."""
        stmt = select(func.coalesce(func.sum(SalesOrder.total_amount), 0.0)).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.customer_id == customer_id,
            SalesOrder.status.in_(["CONFIRMED", "ALLOCATED", "PARTIALLY_ALLOCATED", "PICKING", "PACKED", "SHIPPED"])
        )
        res = await db.execute(stmt)
        so_exposure = Decimal(str(res.scalar() or 0.0))

        cust = (await db.execute(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))).scalar_one_or_none()
        direct_exposure = Decimal(str(cust.current_credit_exposure or 0.0)) if cust else Decimal("0.0")

        return so_exposure + direct_exposure

    @staticmethod
    async def create_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_in: SalesOrderCreate,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        # Validate customer belongs to tenant
        cust_stmt = select(Customer).where(Customer.id == so_in.customer_id, Customer.tenant_id == tenant_id, Customer.is_deleted == False)
        cust_res = await db.execute(cust_stmt)
        if not cust_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Customer not found in tenant")

        # Validate warehouse belongs to tenant
        wh_stmt = select(Warehouse).where(Warehouse.id == so_in.warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        wh_res = await db.execute(wh_stmt)
        if not wh_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

        subtotal, disc_total, tax_total, grand_total = SalesService._compute_line_totals(so_in.lines)
        so_num = await SequenceService.generate_next_number(db, tenant_id, "SALES_ORDER")

        so = SalesOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            so_number=so_num,
            customer_id=so_in.customer_id,
            warehouse_id=so_in.warehouse_id,
            status="DRAFT",
            subtotal_amount=subtotal,
            discount_amount=disc_total,
            tax_amount=tax_total,
            total_amount=grand_total,
            ordered_at=get_utc_now(),
            notes=so_in.notes,
            created_by_user_id=user_id
        )
        db.add(so)

        for line in so_in.lines:
            qty = Decimal(str(line.quantity_ordered))
            price = Decimal(str(line.unit_price))
            disc_pct = Decimal(str(line.discount_pct or 0.0))
            tax_pct = Decimal(str(line.tax_pct or 0.0))

            base_amt = qty * price
            disc_amt = base_amt * (disc_pct / Decimal("100.0"))
            after_disc = base_amt - disc_amt
            tax_amt = after_disc * (tax_pct / Decimal("100.0"))
            line_tot = after_disc + tax_amt

            so_line = SOLineItem(
                id=str(uuid.uuid4()),
                sales_order_id=so.id,
                item_variant_id=line.item_variant_id,
                quantity_ordered=qty,
                quantity_allocated=Decimal("0.0"),
                quantity_backordered=Decimal("0.0"),
                quantity_picked=Decimal("0.0"),
                quantity_shipped=Decimal("0.0"),
                quantity_returned=Decimal("0.0"),
                quantity_cancelled=Decimal("0.0"),
                unit_price=price,
                discount_pct=disc_pct,
                tax_pct=tax_pct,
                line_total=line_tot
            )
            db.add(so_line)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"so_number": so_num, "total": float(grand_total)}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def update_draft_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        so_in: SalesOrderUpdate,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status != "DRAFT":
            raise HTTPException(status_code=400, detail=f"Only DRAFT sales orders can be edited (current status: '{so.status}')")

        if so_in.customer_id:
            cust_stmt = select(Customer).where(Customer.id == so_in.customer_id, Customer.tenant_id == tenant_id)
            cust_res = await db.execute(cust_stmt)
            if not cust_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Customer not found")
            so.customer_id = so_in.customer_id

        if so_in.warehouse_id:
            wh_stmt = select(Warehouse).where(Warehouse.id == so_in.warehouse_id, Warehouse.tenant_id == tenant_id)
            wh_res = await db.execute(wh_stmt)
            if not wh_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Warehouse not found")
            so.warehouse_id = so_in.warehouse_id

        if so_in.notes is not None:
            so.notes = so_in.notes

        if so_in.lines is not None:
            del_stmt = select(SOLineItem).where(SOLineItem.sales_order_id == so.id)
            del_res = await db.execute(del_stmt)
            for old_line in del_res.scalars().all():
                await db.delete(old_line)

            subtotal, disc_total, tax_total, grand_total = SalesService._compute_line_totals(so_in.lines)
            so.subtotal_amount = subtotal
            so.discount_amount = disc_total
            so.tax_amount = tax_total
            so.total_amount = grand_total

            for line in so_in.lines:
                qty = Decimal(str(line.quantity_ordered))
                price = Decimal(str(line.unit_price))
                disc_pct = Decimal(str(line.discount_pct or 0.0))
                tax_pct = Decimal(str(line.tax_pct or 0.0))

                base_amt = qty * price
                disc_amt = base_amt * (disc_pct / Decimal("100.0"))
                after_disc = base_amt - disc_amt
                tax_amt = after_disc * (tax_pct / Decimal("100.0"))
                line_tot = after_disc + tax_amt

                so_line = SOLineItem(
                    id=str(uuid.uuid4()),
                    sales_order_id=so.id,
                    item_variant_id=line.item_variant_id,
                    quantity_ordered=qty,
                    quantity_allocated=Decimal("0.0"),
                    quantity_backordered=Decimal("0.0"),
                    quantity_picked=Decimal("0.0"),
                    quantity_shipped=Decimal("0.0"),
                    quantity_returned=Decimal("0.0"),
                    quantity_cancelled=Decimal("0.0"),
                    unit_price=price,
                    discount_pct=disc_pct,
                    tax_pct=tax_pct,
                    line_total=line_tot
                )
                db.add(so_line)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="UPDATE",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": so.status, "total": float(so.total_amount)}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @classmethod
    async def confirm_sales_order(
        cls,
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["DRAFT", "ON_HOLD"]:
            raise HTTPException(status_code=400, detail=f"Cannot confirm sales order in '{so.status}' status")

        # Check customer credit limit
        cust = (await db.execute(
            select(Customer).where(Customer.id == so.customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()

        if cust and cust.payment_terms != "PREPAID" and cust.credit_limit > Decimal("0.0"):
            exposure = await cls.calculate_customer_credit_exposure(db, tenant_id, cust.id)
            if exposure + Decimal(str(so.total_amount)) > Decimal(str(cust.credit_limit)):
                so.status = "ON_HOLD"
                so.hold_reason = "CREDIT_LIMIT_EXCEEDED"
                so.hold_placed_at = get_utc_now()
                await AuditService.log_action(
                    db=db,
                    tenant_id=tenant_id,
                    action="CREDIT_HOLD",
                    entity_type="SalesOrder",
                    entity_id=so.id,
                    user_id=user_id,
                    changes={"status": "ON_HOLD", "reason": "CREDIT_LIMIT_EXCEEDED"}
                )
                await db.commit()
                await db.refresh(so)
                return so

        so.status = "CONFIRMED"
        so.hold_reason = None
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CONFIRM",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "CONFIRMED"}
        )
        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def override_credit_limit(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        reason: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status != "ON_HOLD" or so.hold_reason != "CREDIT_LIMIT_EXCEEDED":
            raise HTTPException(status_code=400, detail="Only orders on CREDIT_LIMIT_EXCEEDED hold can receive credit overrides")

        so.status = "CONFIRMED"
        so.hold_reason = None
        so.credit_limit_override_by_user_id = user_id
        so.notes = (so.notes or "") + f"\n[Credit Override]: {reason} (authorized by {user_id})"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREDIT_OVERRIDE",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "CONFIRMED", "reason": reason}
        )
        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def place_order_hold(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        reason: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status in ["SHIPPED", "DELIVERED", "CANCELLED"]:
            raise HTTPException(status_code=400, detail=f"Cannot place hold on order in '{so.status}' status")

        so.status = "ON_HOLD"
        so.hold_reason = reason
        so.hold_placed_at = get_utc_now()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PLACE_HOLD",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "ON_HOLD", "reason": reason}
        )
        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def release_order_hold(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status != "ON_HOLD":
            raise HTTPException(status_code=400, detail="Sales order is not currently on hold")

        so.status = "CONFIRMED"
        so.hold_reason = None
        so.hold_released_by_user_id = user_id
        if notes:
            so.notes = (so.notes or "") + f"\n[Hold Released]: {notes}"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="RELEASE_HOLD",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "CONFIRMED"}
        )
        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def allocate_stock(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        alloc_req: Optional[SOAllocateRequest] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        """
        Atomic Stock Allocation with Partial Allocation & Backorder Support.
        """
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["CONFIRMED", "ALLOCATED", "PARTIALLY_ALLOCATED"]:
            raise HTTPException(status_code=400, detail=f"Cannot allocate stock for order in '{so.status}' status (must be CONFIRMED)")

        allow_partial = alloc_req.allow_partial if alloc_req else False
        has_backorder = False

        for line in so.lines:
            qty_needed = Decimal(str(line.quantity_ordered)) - Decimal(str(line.quantity_allocated))
            if qty_needed <= Decimal("0.0"):
                continue

            var_id = line.item_variant_id

            bal_stmt = (
                select(StockBalanceCache)
                .where(
                    StockBalanceCache.warehouse_id == so.warehouse_id,
                    StockBalanceCache.item_variant_id == var_id
                )
                .order_by(StockBalanceCache.location_bin_id.asc(), StockBalanceCache.id.asc())
                .with_for_update()
            )
            bal_res = await db.execute(bal_stmt)
            balances = bal_res.scalars().all()

            total_avail = sum(Decimal(str(b.quantity_on_hand)) - Decimal(str(b.quantity_allocated)) for b in balances)
            if total_avail < qty_needed:
                if not allow_partial:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Cannot allocate SKU '{var_id}': Insufficient available stock in facility (short by {qty_needed - total_avail} units)"
                    )
                else:
                    has_backorder = True
                    line.quantity_backordered = qty_needed - total_avail

            # Allocate available
            for bal in balances:
                avail = Decimal(str(bal.quantity_on_hand)) - Decimal(str(bal.quantity_allocated))
                if avail > Decimal("0.0"):
                    alloc = min(qty_needed, avail)
                    bal.quantity_allocated = Decimal(str(bal.quantity_allocated)) + alloc
                    bal.updated_at = get_utc_now()
                    line.quantity_allocated = Decimal(str(line.quantity_allocated)) + alloc

                    alloc_obj = SOAllocation(
                        id=str(uuid.uuid4()),
                        so_line_id=line.id,
                        location_bin_id=bal.location_bin_id,
                        quantity_allocated=alloc
                    )
                    db.add(alloc_obj)

                    qty_needed -= alloc
                    if qty_needed <= Decimal("0.0"):
                        break

        so.status = "PARTIALLY_ALLOCATED" if has_backorder else "ALLOCATED"
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="ALLOCATE",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": so.status}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def generate_pick_task_for_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        user_id: Optional[str] = None
    ) -> PickTask:
        """
        Creates a warehouse PickTask and PickTaskLines from the Sales Order's active allocations.
        """
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["ALLOCATED", "PARTIALLY_ALLOCATED"]:
            raise HTTPException(status_code=400, detail=f"Cannot generate pick task for order in '{so.status}' status (must be ALLOCATED)")

        task_num = await SequenceService.generate_next_number(db, tenant_id, "PICK_TASK")
        pick_task = PickTask(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=so.warehouse_id,
            sales_order_id=so.id,
            task_number=task_num,
            status="PENDING",
            assigned_to_user_id=user_id
        )
        db.add(pick_task)
        await db.flush()

        for line in so.lines:
            for alloc in line.allocations:
                pick_line = PickTaskLine(
                    id=str(uuid.uuid4()),
                    pick_task_id=pick_task.id,
                    so_line_id=line.id,
                    location_bin_id=alloc.location_bin_id,
                    item_variant_id=line.item_variant_id,
                    quantity_allocated=alloc.quantity_allocated,
                    quantity_picked=Decimal("0.0"),
                    status="PENDING"
                )
                db.add(pick_line)

        so.status = "PICKING"
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="GENERATE_PICK_TASK",
            entity_type="PickTask",
            entity_id=pick_task.id,
            user_id=user_id,
            changes={"task_number": task_num, "so_number": so.so_number}
        )

        await db.commit()
        await db.refresh(pick_task)
        return pick_task

    @staticmethod
    async def pick_items(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        pick_req: SOPickRequest,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["ALLOCATED", "PICKING", "PARTIALLY_ALLOCATED"]:
            raise HTTPException(status_code=400, detail=f"Cannot pick items for order in '{so.status}' status")

        for pick_item in pick_req.picks:
            line_stmt = select(SOLineItem).where(SOLineItem.id == pick_item.so_line_id, SOLineItem.sales_order_id == so.id).with_for_update()
            line_res = await db.execute(line_stmt)
            so_line = line_res.scalar_one_or_none()
            if not so_line:
                raise HTTPException(status_code=404, detail=f"SO line {pick_item.so_line_id} not found on this order")

            new_picked = Decimal(str(so_line.quantity_picked)) + Decimal(str(pick_item.quantity_picked))
            if new_picked > Decimal(str(so_line.quantity_allocated)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot pick {pick_item.quantity_picked} units for line {so_line.id}; total picked would exceed allocated quantity ({so_line.quantity_allocated})"
                )
            so_line.quantity_picked = new_picked

        all_picked = all(l.quantity_picked >= l.quantity_allocated and l.quantity_allocated > 0 for l in so.lines)
        so.status = "PICKING" if not all_picked else "PACKED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PICK",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": so.status}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def pack_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        pack_req: SOPackRequest,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["ALLOCATED", "PICKING", "PACKED"]:
            raise HTTPException(status_code=400, detail=f"Cannot pack order in '{so.status}' status")

        so.status = "PACKED"
        if pack_req.packing_notes:
            so.notes = (so.notes or "") + f"\n[Packing Note]: {pack_req.packing_notes}"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PACK",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "PACKED", "package_count": pack_req.package_count}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def dispatch_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        dispatch_req: SODispatchRequest,
        user_id: Optional[str] = None,
        client_type: str = "WEB"
    ) -> Shipment:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["ALLOCATED", "PICKING", "PACKED"]:
            raise HTTPException(status_code=400, detail=f"Cannot dispatch sales order in '{so.status}' status (must be ALLOCATED or PACKED)")

        shipment_num = await SequenceService.generate_next_number(db, tenant_id, "SHIPMENT")
        shipment = Shipment(
            id=str(uuid.uuid4()),
            sales_order_id=so.id,
            shipment_number=shipment_num,
            carrier=dispatch_req.carrier,
            tracking_number=dispatch_req.tracking_number,
            package_count=dispatch_req.package_count,
            total_weight=dispatch_req.total_weight,
            shipped_at=get_utc_now(),
            dispatched_by_user_id=user_id,
            notes=dispatch_req.notes
        )
        db.add(shipment)
        await db.flush()

        ledger_entries_data = []

        for line in so.lines:
            qty_to_ship = Decimal(str(line.quantity_ordered)) - Decimal(str(line.quantity_shipped))
            if qty_to_ship <= Decimal("0.0"):
                continue

            bal_stmt = (
                select(StockBalanceCache)
                .where(
                    StockBalanceCache.warehouse_id == so.warehouse_id,
                    StockBalanceCache.item_variant_id == line.item_variant_id,
                    StockBalanceCache.quantity_allocated > 0
                )
                .order_by(StockBalanceCache.location_bin_id.asc(), StockBalanceCache.id.asc())
                .with_for_update()
            )
            bal_res = await db.execute(bal_stmt)
            balances = bal_res.scalars().all()

            var_stmt = select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == line.item_variant_id)
            var_res = await db.execute(var_stmt)
            variant, item = var_res.first()

            remaining_ship = qty_to_ship
            for bal in balances:
                allocated_in_bin = min(remaining_ship, Decimal(str(bal.quantity_allocated)))
                bal.quantity_allocated = Decimal(str(bal.quantity_allocated)) - allocated_in_bin
                bal.updated_at = get_utc_now()

                ledger_entries_data.append({
                    "item_variant_id": line.item_variant_id,
                    "quantity": allocated_in_bin,
                    "unit_cost": line.unit_price,
                    "source_location_bin_id": bal.location_bin_id,
                    "batch_number": bal.batch.batch_number if bal.batch else None,
                    "uom": item.base_uom or "PCS"
                })
                remaining_ship -= allocated_in_bin
                if remaining_ship <= Decimal("0.0"):
                    break

            line.quantity_shipped = line.quantity_ordered
            line.quantity_picked = line.quantity_ordered

        so.status = "SHIPPED"

        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="SALES_SHIPMENT",
            entries_data=ledger_entries_data,
            reference_doc_type="SALES_ORDER",
            reference_doc_id=so.id,
            user_id=user_id,
            notes=f"Dispatched Sales Order {so.so_number} under Shipment {shipment_num}",
            client_type=client_type
        )

        for line in so.lines:
            await CostingService.record_outbound_dispatch(
                db=db,
                tenant_id=tenant_id,
                warehouse_id=so.warehouse_id,
                item_variant_id=line.item_variant_id,
                quantity=Decimal(str(line.quantity_ordered)),
                sales_order_id=so.id,
                shipment_id=shipment.id,
                stock_transaction_id=tx.id,
                user_id=user_id
            )

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="DISPATCH",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "SHIPPED", "shipment_number": shipment_num}
        )

        await db.commit()
        await db.refresh(shipment)
        return shipment

    @staticmethod
    async def confirm_delivery(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        delivery_notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        """Confirms proof of delivery for a shipped sales order."""
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status != "SHIPPED":
            raise HTTPException(status_code=400, detail=f"Cannot confirm delivery for order in '{so.status}' status (must be SHIPPED)")

        so.status = "DELIVERED"
        so.delivery_confirmed_at = get_utc_now()
        so.delivery_notes = delivery_notes

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="DELIVERY_CONFIRM",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "DELIVERED"}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def cancel_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["DRAFT", "CONFIRMED", "ALLOCATED", "PARTIALLY_ALLOCATED", "PICKING", "ON_HOLD"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel sales order in '{so.status}' status (already dispatched or completed)")

        # Release any active stock reservations
        for line in so.lines:
            if line.quantity_allocated > Decimal("0.0"):
                bal_stmt = (
                    select(StockBalanceCache)
                    .where(
                        StockBalanceCache.warehouse_id == so.warehouse_id,
                        StockBalanceCache.item_variant_id == line.item_variant_id,
                        StockBalanceCache.quantity_allocated > 0
                    )
                    .with_for_update()
                )
                bal_res = await db.execute(bal_stmt)
                balances = bal_res.scalars().all()

                rem_release = Decimal(str(line.quantity_allocated))
                for bal in balances:
                    rel = min(rem_release, Decimal(str(bal.quantity_allocated)))
                    bal.quantity_allocated = Decimal(str(bal.quantity_allocated)) - rel
                    bal.updated_at = get_utc_now()
                    rem_release -= rel
                    if rem_release <= Decimal("0.0"):
                        break

                line.quantity_cancelled = line.quantity_ordered
                line.quantity_allocated = Decimal("0.0")
                line.quantity_picked = Decimal("0.0")

        so.status = "CANCELLED"
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CANCEL",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=user_id,
            changes={"status": "CANCELLED"}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def process_sales_return(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        return_in: SalesReturnCreate,
        user_id: Optional[str] = None,
        client_type: str = "WEB"
    ) -> SalesReturn:
        stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["SHIPPED", "DELIVERED"]:
            raise HTTPException(status_code=400, detail=f"Cannot process return against order in '{so.status}' status (must be SHIPPED or DELIVERED)")

        validated_returns = []
        for line_in in return_in.lines:
            line_stmt = select(SOLineItem).where(SOLineItem.id == line_in.so_line_id, SOLineItem.sales_order_id == so.id).with_for_update()
            line_res = await db.execute(line_stmt)
            so_line = line_res.scalar_one_or_none()
            if not so_line:
                raise HTTPException(status_code=404, detail=f"SO line {line_in.so_line_id} not found on this order")

            max_returnable = so_line.quantity_shipped - so_line.quantity_returned
            if line_in.quantity_returned > max_returnable:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot return {line_in.quantity_returned} units; maximum returnable is {max_returnable}"
                )

            bin_stmt = select(LocationBin).where(LocationBin.id == line_in.destination_bin_id, LocationBin.warehouse_id == so.warehouse_id)
            bin_res = await db.execute(bin_stmt)
            dest_bin = bin_res.scalar_one_or_none()
            if not dest_bin:
                raise HTTPException(status_code=404, detail=f"Destination bin {line_in.destination_bin_id} not found in facility")

            var_stmt = select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == so_line.item_variant_id)
            var_res = await db.execute(var_stmt)
            variant, item = var_res.first()

            validated_returns.append({
                "so_line": so_line,
                "line_in": line_in,
                "base_uom": item.base_uom or "PCS"
            })

        ret_num = await SequenceService.generate_next_number(db, tenant_id, "RETURN")
        sales_return = SalesReturn(
            id=str(uuid.uuid4()),
            sales_order_id=so.id,
            return_number=ret_num,
            status="COMPLETED",
            rma_status="RECEIVED",
            returned_at=get_utc_now(),
            received_by_user_id=user_id,
            notes=return_in.notes
        )
        db.add(sales_return)
        await db.flush()

        ledger_entries_data = []

        for ret_data in validated_returns:
            so_line = ret_data["so_line"]
            line_in = ret_data["line_in"]

            so_line.quantity_returned = Decimal(str(so_line.quantity_returned)) + line_in.quantity_returned

            ret_line = SalesReturnLine(
                id=str(uuid.uuid4()),
                sales_return_id=sales_return.id,
                so_line_id=so_line.id,
                item_variant_id=so_line.item_variant_id,
                quantity_returned=line_in.quantity_returned,
                condition=line_in.condition,
                destination_bin_id=line_in.destination_bin_id
            )
            db.add(ret_line)

            ledger_entries_data.append({
                "item_variant_id": so_line.item_variant_id,
                "quantity": line_in.quantity_returned,
                "unit_cost": so_line.unit_price,
                "destination_location_bin_id": line_in.destination_bin_id,
                "uom": ret_data["base_uom"]
            })

        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="SALES_RETURN",
            entries_data=ledger_entries_data,
            reference_doc_type="SALES_RETURN",
            reference_doc_id=sales_return.id,
            user_id=user_id,
            notes=f"Sales Return {ret_num} against {so.so_number}",
            client_type=client_type
        )

        for ret_data in validated_returns:
            line_in = ret_data["line_in"]
            so_line = ret_data["so_line"]
            await CostingService.record_customer_return(
                db=db,
                tenant_id=tenant_id,
                warehouse_id=so.warehouse_id,
                item_variant_id=so_line.item_variant_id,
                quantity=Decimal(str(line_in.quantity_returned)),
                sales_order_id=so.id,
                condition=line_in.condition,
                stock_transaction_id=tx.id,
                user_id=user_id
            )

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SALES_RETURN",
            entity_type="SalesReturn",
            entity_id=sales_return.id,
            user_id=user_id,
            changes={"return_number": ret_num, "so_number": so.so_number}
        )

        await db.commit()
        await db.refresh(sales_return)
        return sales_return

    @staticmethod
    async def inspect_sales_return(
        db: AsyncSession,
        tenant_id: str,
        return_id: str,
        inspect_req: RMAInspectRequest,
        user_id: Optional[str] = None
    ) -> SalesReturn:
        """
        Processes RMA quality inspection disposition:
        - RESTOCK: Moves inventory from quarantine bin to designated restock bin.
        - SCRAP: Marks return disposition as SCRAP.
        """
        stmt = select(SalesReturn).where(SalesReturn.id == return_id).with_for_update()
        res = await db.execute(stmt)
        ret = res.scalar_one_or_none()
        if not ret:
            raise HTTPException(status_code=404, detail="Sales Return not found")

        ret.rma_status = "INSPECTED"
        ret.disposition = inspect_req.disposition
        ret.inspection_notes = inspect_req.inspection_notes
        ret.inspected_by_user_id = user_id

        # If RESTOCK is specified and target bin provided, move items from quarantine to storage
        if inspect_req.disposition == "RESTOCK" and inspect_req.target_restock_bin_id:
            so = (await db.execute(select(SalesOrder).where(SalesOrder.id == ret.sales_order_id))).scalar_one()
            transfer_entries = []
            for rline in ret.lines:
                transfer_entries.append({
                    "item_variant_id": rline.item_variant_id,
                    "quantity": rline.quantity_returned,
                    "unit_cost": Decimal("0.0"),
                    "source_location_bin_id": rline.destination_bin_id, # Original quarantine bin
                    "destination_location_bin_id": inspect_req.target_restock_bin_id,
                    "uom": "PCS"
                })

            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="INVENTORY_TRANSFER",
                entries_data=transfer_entries,
                reference_doc_type="RMA_INSPECTION",
                reference_doc_id=ret.id,
                user_id=user_id,
                notes=f"RMA {ret.return_number} restocked to storage bin"
            )
            ret.rma_status = "RESTOCKED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="INSPECT_RMA",
            entity_type="SalesReturn",
            entity_id=ret.id,
            user_id=user_id,
            changes={"disposition": inspect_req.disposition, "rma_status": ret.rma_status}
        )

        await db.commit()
        await db.refresh(ret)
        return ret
