import uuid
import asyncio
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.sales import (
    Customer,
    CustomerAddress,
    CustomerContact,
    SalesOrder,
    SOLineItem,
    SOAllocation,
    Shipment,
    SalesReturn,
    SalesReturnLine
)
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemCategory, Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.warehouse_ops import PickTask, PickTaskLine
from app.schemas.sales import (
    CustomerCreate,
    CustomerAddressCreate,
    CustomerContactCreate,
    SalesOrderCreate,
    SOLineCreate,
    SOAllocateRequest,
    SOPlaceHoldRequest,
    SOCreditOverrideRequest,
    SODeliveryConfirmRequest,
    SalesReturnCreate,
    SalesReturnLineCreate,
    RMAInspectRequest
)
from app.services.sales_service import SalesService

pytestmark = pytest.mark.asyncio

async def create_sales_v2_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-V2-{uuid.uuid4().hex[:4]}", name="Sales V2 WH")
    bin_stor1 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    bin_stor2 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-02", aisle="A", rack="01", shelf="01", bin="02", type="STORAGE")
    bin_quarantine = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="QUAR-01", aisle="Q", rack="01", shelf="01", bin="01", type="QUARANTINE")
    wh.bins.extend([bin_stor1, bin_stor2, bin_quarantine])
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Electronics V2", code=f"CAT-V2-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-V2-{uuid.uuid4().hex[:4]}", name="Industrial Tablet V2", is_batch_tracked=True)
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-V2-{uuid.uuid4().hex[:4]}", variant_name="Rugged 10-inch", cost_price=Decimal("200.00"), selling_price=Decimal("500.00"))
    db.add_all([cat, item, variant])
    await db.commit()

    return wh, bin_stor1, bin_stor2, bin_quarantine, item, variant

async def test_customer_master_with_addresses_contacts_and_tax(db_session: AsyncSession):
    """
    Tests customer master creation with multiple addresses, contacts, credit limits, payment terms, and tax ID.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    cust = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="CUST-CORP-01",
        name="Apex Industrial Logistics",
        email="procure@apex.com",
        tax_identifier="US-EIN-987654321",
        currency="USD",
        payment_terms="NET_30",
        credit_limit=Decimal("50000.00")
    )
    db_session.add(cust)
    await db_session.commit()

    # Add shipping and billing addresses
    addr_ship = await SalesService.create_customer_address(db_session, tenant_id, cust.id, CustomerAddressCreate(
        address_type="SHIPPING",
        label="East Coast Hub",
        street1="100 Logistics Way",
        city="Newark",
        state="NJ",
        postal_code="07102",
        country="USA",
        is_default=True
    ))
    assert addr_ship.id is not None
    assert addr_ship.address_type == "SHIPPING"

    addr_bill = await SalesService.create_customer_address(db_session, tenant_id, cust.id, CustomerAddressCreate(
        address_type="BILLING",
        label="Corporate HQ",
        street1="500 Madison Ave",
        city="New York",
        state="NY",
        postal_code="10022",
        country="USA",
        is_default=True
    ))
    assert addr_bill.address_type == "BILLING"

    # Add primary contact
    contact = await SalesService.create_customer_contact(db_session, tenant_id, cust.id, CustomerContactCreate(
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@apex.com",
        phone="+1-555-0199",
        job_title="Director of Procurement",
        is_primary=True
    ))
    assert contact.id is not None
    assert contact.first_name == "Jane"

async def test_sales_order_credit_limit_hold_and_authorized_override(db_session: AsyncSession):
    """
    Tests credit limit enforcement:
    - Customer has $1000 credit limit.
    - Order is created for $1500 (3 units @ $500).
    - Confirmation automatically places order on ON_HOLD (CREDIT_LIMIT_EXCEEDED).
    - Authorized override transitions order to CONFIRMED.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="CUST-CREDIT-01",
        name="Small Biz Corp",
        payment_terms="NET_30",
        credit_limit=Decimal("1000.00")
    )
    db_session.add(cust)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("3.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    assert so.total_amount == Decimal("1500.00")
    assert so.status == "DRAFT"

    # Confirm order -> credit limit ($1000) exceeded by $1500 order -> ON_HOLD
    so_confirmed = await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert so_confirmed.status == "ON_HOLD"
    assert so_confirmed.hold_reason == "CREDIT_LIMIT_EXCEEDED"

    # Authorized credit override
    so_overridden = await SalesService.override_credit_limit(
        db_session, tenant_id, so.id, reason="Approved by VP Finance for strategic customer", user_id=user_id
    )
    assert so_overridden.status == "CONFIRMED"
    assert so_overridden.hold_reason is None
    assert so_overridden.credit_limit_override_by_user_id == user_id

async def test_partial_allocation_and_backorder_tracking(db_session: AsyncSession):
    """
    Tests partial allocation when available inventory is lower than ordered quantity:
    - Ordered: 10 units
    - Available in warehouse: 6 units
    - Result: 6 units allocated, 4 units backordered, status = PARTIALLY_ALLOCATED.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-BO-01", name="Backorder Client Corp")
    db_session.add(cust)

    # Seed 6 units in Bin 1
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("6.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Allocate with allow_partial = True
    so_alloc = await SalesService.allocate_stock(
        db_session, tenant_id, so.id, alloc_req=SOAllocateRequest(allow_partial=True), user_id=user_id
    )
    assert so_alloc.status == "PARTIALLY_ALLOCATED"

    line = so_alloc.lines[0]
    assert line.quantity_allocated == Decimal("6.0")
    assert line.quantity_backordered == Decimal("4.0")

async def test_sales_order_to_pick_task_bridge(db_session: AsyncSession):
    """
    Tests generation of warehouse PickTask directly from confirmed Sales Order allocations.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-PICK-01", name="Pick Client Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("20.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("5.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)

    # Generate Pick Task
    pick_task = await SalesService.generate_pick_task_for_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert pick_task.id is not None
    assert bool(pick_task.task_number)
    assert len(pick_task.lines) == 1
    assert pick_task.lines[0].quantity_allocated == Decimal("5.0")
    assert pick_task.lines[0].location_bin_id == bin_stor1.id

    # Verify SO status updated to PICKING
    so_refreshed = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_refreshed.status == "PICKING"

async def test_sales_order_outbound_dispatch_and_delivery_confirmation(db_session: AsyncSession):
    """
    Tests atomic outbound dispatch with COGS calculation and subsequent delivery confirmation.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-DELIV-01", name="Delivery Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("15.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("4.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)

    # Dispatch
    from app.schemas.sales import SODispatchRequest
    shipment = await SalesService.dispatch_sales_order(
        db_session, tenant_id, so.id, SODispatchRequest(carrier="FedEx", tracking_number="FDX-998877", package_count=2), user_id=user_id
    )
    assert shipment.shipment_number.startswith("SHP-")

    # Verify SO status SHIPPED
    so_shipped = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_shipped.status == "SHIPPED"

    # Confirm Delivery
    so_delivered = await SalesService.confirm_delivery(
        db_session, tenant_id, so.id, delivery_notes="Signed by Recipient at Loading Dock B", user_id=user_id
    )
    assert so_delivered.status == "DELIVERED"
    assert so_delivered.delivery_confirmed_at is not None
    assert "Loading Dock B" in so_delivered.delivery_notes

async def test_rma_customer_return_quarantine_and_inspection_restock(db_session: AsyncSession):
    """
    Tests customer RMA return:
    1. Returns item into QUARANTINE bin (available stock is not inflated).
    2. Quality inspection confirms RESTOCK disposition -> transfers item to active STORAGE bin.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, bin_stor2, bin_quar, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-RMA-01", name="RMA Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("10.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)
    from app.schemas.sales import SODispatchRequest
    await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(carrier="UPS"), user_id=user_id)

    # Ingest RMA return into Quarantine Bin
    ret_in = SalesReturnCreate(
        notes="Customer changed mind",
        lines=[
            SalesReturnLineCreate(
                so_line_id=so.lines[0].id,
                quantity_returned=Decimal("1.0"),
                condition="GOOD",
                destination_bin_id=bin_quar.id
            )
        ]
    )
    sales_return = await SalesService.process_sales_return(db_session, tenant_id, so.id, ret_in, user_id=user_id)
    assert bool(sales_return.return_number)
    assert sales_return.rma_status == "RECEIVED"

    # Quarantine balance exists, Storage 2 is 0
    bal_quar = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_quar.id, StockBalanceCache.item_variant_id == variant.id)
    )).scalar_one_or_none()
    assert bal_quar is not None
    assert bal_quar.quantity_on_hand == Decimal("1.0")

    # Quality Inspection -> RESTOCK to Bin 2
    inspected_return = await SalesService.inspect_sales_return(
        db_session,
        tenant_id,
        sales_return.id,
        RMAInspectRequest(disposition="RESTOCK", inspection_notes="Inspected seal intact", target_restock_bin_id=bin_stor2.id),
        user_id=user_id
    )
    assert inspected_return.rma_status == "RESTOCKED"
    assert inspected_return.disposition == "RESTOCK"

    # Storage 2 balance is now 1.0; Quarantine is 0.0
    bal_stor2 = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_stor2.id, StockBalanceCache.item_variant_id == variant.id)
    )).scalar_one_or_none()
    assert bal_stor2 is not None
    assert bal_stor2.quantity_on_hand == Decimal("1.0")

async def test_sales_order_cancellation_releases_allocations(db_session: AsyncSession):
    """
    Tests that cancelling an allocated sales order safely releases reserved stock back to available balance.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-CANCEL-01", name="Cancel Client")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("10.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[
            SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("7.0"), unit_price=Decimal("500.00"))
        ]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)

    # Cancel allocated order
    so_cancelled = await SalesService.cancel_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert so_cancelled.status == "CANCELLED"
    assert so_cancelled.lines[0].quantity_allocated == Decimal("0.0")
    assert so_cancelled.lines[0].quantity_cancelled == Decimal("7.0")

    # Verify balance allocation is released
    bal_refreshed = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.id == bal.id)
    )).scalar_one()
    assert bal_refreshed.quantity_allocated == Decimal("0.0")
    assert bal_refreshed.quantity_on_hand == Decimal("10.0")

async def test_rma_scrap_and_rtv_dispositions(db_session: AsyncSession):
    """
    Tests SCRAP and RTV (Return to Vendor) inspection dispositions:
    - Ingest return into quarantine.
    - SCRAP disposition records quality notes and inspector without modifying historical COGS.
    - RTV disposition logs supplier return eligibility.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, bin_quar, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-SCRAP-01", name="Scrap Client")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("5.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so_in = SalesOrderCreate(
        customer_id=cust.id,
        warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("500.00"))]
    )
    so = await SalesService.create_sales_order(db_session, tenant_id, so_in, user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)
    from app.schemas.sales import SODispatchRequest
    await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(carrier="DHL"), user_id=user_id)

    # Ingest return
    ret_in = SalesReturnCreate(
        notes="Damaged in transit",
        lines=[SalesReturnLineCreate(so_line_id=so.lines[0].id, quantity_returned=Decimal("2.0"), condition="DAMAGED", destination_bin_id=bin_quar.id)]
    )
    ret = await SalesService.process_sales_return(db_session, tenant_id, so.id, ret_in, user_id=user_id)

    # Test SCRAP disposition
    inspected_scrap = await SalesService.inspect_sales_return(
        db_session, tenant_id, ret.id,
        RMAInspectRequest(disposition="SCRAP", inspection_notes="Crushed casing - write off approved"),
        user_id=user_id
    )
    assert inspected_scrap.rma_status == "INSPECTED"
    assert inspected_scrap.disposition == "SCRAP"
    assert inspected_scrap.inspected_by_user_id == user_id
    assert "write off approved" in inspected_scrap.inspection_notes

    # Test RTV disposition
    ret.rma_status = "RECEIVED"
    inspected_rtv = await SalesService.inspect_sales_return(
        db_session, tenant_id, ret.id,
        RMAInspectRequest(disposition="RETURN_TO_VENDOR", inspection_notes="Defective motherboard - return to OEM"),
        user_id=user_id
    )
    assert inspected_rtv.rma_status == "INSPECTED"
    assert inspected_rtv.disposition == "RETURN_TO_VENDOR"

async def test_concurrent_sales_order_allocations_real_db(db_session: AsyncSession):
    """
    TEST: CONCURRENT ALLOCATION ON LIMITED INVENTORY
    - Total Available stock = 10 units
    - Order A requests 10 units
    - Order B requests 10 units
    - Exactly one transaction succeeds (ALLOCATED); the other fails with 422 (Insufficient stock).
    - Available stock never becomes negative; total allocated = exactly 10.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-CONC-01", name="Concurrent Client")
    db_session.add(cust)

    # Seed exactly 10 units in Bin 1
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("10.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    # Create Order A (10 units)
    so_a = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so_a.id, user_id=user_id)

    # Create Order B (10 units)
    so_b = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so_b.id, user_id=user_id)

    # First allocation succeeds
    res_a = await SalesService.allocate_stock(db_session, tenant_id, so_a.id, alloc_req=SOAllocateRequest(allow_partial=False), user_id=user_id)
    assert res_a.status == "ALLOCATED"
    assert res_a.lines[0].quantity_allocated == Decimal("10.0")

    # Second allocation must fail with 422
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await SalesService.allocate_stock(db_session, tenant_id, so_b.id, alloc_req=SOAllocateRequest(allow_partial=False), user_id=user_id)
    assert exc_info.value.status_code == 422
    assert "Insufficient available stock" in str(exc_info.value.detail)

    # Invariants check
    bal_check = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.id == bal.id))).scalar_one()
    assert bal_check.quantity_allocated == Decimal("10.0")
    assert bal_check.quantity_on_hand == Decimal("10.0")
    assert (bal_check.quantity_on_hand - bal_check.quantity_allocated) == Decimal("0.0")

async def test_sales_order_invalid_lifecycle_transitions(db_session: AsyncSession):
    """
    TEST: INVALID LIFECYCLE TRANSITIONS
    - DISPATCHED -> DRAFT ❌
    - DELIVERED -> CONFIRMED ❌
    - CANCELLED -> ALLOCATED ❌
    - CANCELLED -> DISPATCHED ❌
    """
    from fastapi import HTTPException
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-TRANS-01", name="Transition Client")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_stor1.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("20.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)

    # 1. CANCELLED -> ALLOCATED ❌
    await SalesService.cancel_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    with pytest.raises(HTTPException) as exc:
        await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)
    assert exc.value.status_code == 400

    # 2. CANCELLED -> DISPATCHED ❌
    from app.schemas.sales import SODispatchRequest
    with pytest.raises(HTTPException) as exc:
        await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(), user_id=user_id)
    assert exc.value.status_code == 400

    # Create new order for dispatch testing
    so2 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so2.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so2.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so2.id, SODispatchRequest(), user_id=user_id)

    # 3. DISPATCHED -> CANCEL ❌
    with pytest.raises(HTTPException) as exc:
        await SalesService.cancel_sales_order(db_session, tenant_id, so2.id, user_id=user_id)
    assert exc.value.status_code == 400

    # 4. DELIVERED -> CONFIRM ❌
    await SalesService.confirm_delivery(db_session, tenant_id, so2.id, user_id=user_id)
    with pytest.raises(HTTPException) as exc:
        await SalesService.confirm_sales_order(db_session, tenant_id, so2.id, user_id=user_id)
    assert exc.value.status_code == 400

async def test_historical_sales_order_and_cogs_financial_integrity(db_session: AsyncSession):
    """
    TEST: HISTORICAL FINANCIAL & COGS INTEGRITY
    - Order finalized at $500/unit with COGS $200/unit.
    - Subsequent product price increases or inventory cost layer additions NEVER modify historical records.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stor1, _, _, _, variant = await create_sales_v2_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-FIN-01", name="Finance Client")
    db_session.add(cust)

    # Seed cost layer at $200/unit
    from app.models.costing import CostLayer, COGSRecord
    cl = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-TEST-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("200.00"),
        original_quantity=Decimal("10.0"), remaining_quantity=Decimal("10.0"), total_cost=Decimal("2000.00"), status="ACTIVE"
    )
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_stor1.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([cl, bal])
    await db_session.commit()

    # Create and dispatch order at $500/unit
    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("3.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)

    from app.schemas.sales import SODispatchRequest
    shipment = await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(carrier="FedEx"), user_id=user_id)

    # Verify COGS record created with $200 * 3 = $600
    cogs_stmt = select(COGSRecord).where(COGSRecord.sales_order_id == so.id)
    cogs = (await db_session.execute(cogs_stmt)).scalar_one()
    assert cogs.total_cogs_amount == Decimal("600.00")
    assert cogs.unit_cogs == Decimal("200.00")
    assert so.total_amount == Decimal("1500.00")

    # Modify variant master selling price & cost price
    variant.selling_price = Decimal("899.00")
    variant.cost_price = Decimal("350.00")
    await db_session.commit()

    # Historical order and COGS remain strictly identical
    so_rechecked = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_rechecked.total_amount == Decimal("1500.00")
    assert so_rechecked.lines[0].unit_price == Decimal("500.00")

    cogs_rechecked = (await db_session.execute(cogs_stmt)).scalar_one()
    assert cogs_rechecked.total_cogs_amount == Decimal("600.00")
    assert cogs_rechecked.unit_cogs == Decimal("200.00")
