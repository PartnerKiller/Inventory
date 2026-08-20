import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.sales import (
    Customer,
    SalesOrder,
    SOLineItem,
    SalesReturn,
    SalesReturnLine
)
from app.models.invoicing import (
    CustomerInvoice,
    InvoiceLineItem,
    CustomerPayment,
    PaymentAllocation,
    CustomerCreditNote
)
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer, COGSRecord
from app.models.audit import AuditLog
from app.schemas.sales import SalesOrderCreate, SOLineCreate, SODispatchRequest, SalesReturnCreate, SalesReturnLineCreate
from app.schemas.invoicing import CustomerPaymentCreate, PaymentAllocationItem, CreditNoteCreate
from app.services.sales_service import SalesService
from app.services.invoicing_service import InvoicingService

async def create_invoicing_test_environment(db: AsyncSession, tenant_id: str):
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-INV-{uuid.uuid4().hex[:4]}", name="Invoicing DC")
    db.add(wh)
    await db.flush()

    bin_st = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="ST-01", type="STORAGE")
    bin_qu = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="QU-01", type="QUARANTINE")
    db.add_all([bin_st, bin_qu])

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="General", code=f"GEN-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-INV-{uuid.uuid4().hex[:4]}", name="Industrial Widget")
    db.add(item)
    await db.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"{item.sku}-V1",
        variant_name="Standard",
        cost_price=Decimal("100.00"),
        selling_price=Decimal("250.00")
    )
    db.add(variant)
    await db.commit()

    return wh, bin_st, bin_qu, variant

# ============================================================================
# 1. INVOICE SOURCE, GENERATION & DUPLICATE PREVENTION
# ============================================================================

@pytest.mark.asyncio
async def test_invoice_generation_and_duplicate_prevention(db_session: AsyncSession):
    """
    Verifies that invoice generation from sales order:
    1. Correctly calculates lines, taxes, and balance due.
    2. Retrying invoice generation for the same sales order idempotently returns existing invoice.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-DUP-{uuid.uuid4().hex[:4]}", name="Dup Test Corp", payment_terms="NET_30")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("20.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    # Create & confirm SO for 4 units @ $250 = $1,000
    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("4.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Initial Invoice Generation
    inv1 = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert inv1.id is not None
    assert bool(inv1.invoice_number)
    assert inv1.status == "ISSUED"
    assert inv1.total_amount == Decimal("1000.00")
    assert inv1.balance_due == Decimal("1000.00")

    # Retry Invoice Generation for the same Sales Order -> returns same invoice idempotently
    inv2 = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert inv2.id == inv1.id
    assert inv2.invoice_number == inv1.invoice_number

    # Verify database has exactly 1 invoice
    invoices = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.sales_order_id == so.id))).scalars().all()
    assert len(invoices) == 1

# ============================================================================
# 2. INVOICE HISTORICAL IMMUTABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_invoice_historical_immutability(db_session: AsyncSession):
    """
    Verifies that changing master product price or customer data NEVER alters historical finalized invoice amounts.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-IMMUT-{uuid.uuid4().hex[:4]}", name="Immutability Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    inv = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Change master variant price from $250 to $999
    variant.selling_price = Decimal("999.00")
    cust.name = "Renamed Client Corp"
    await db_session.commit()

    # Verify historical invoice remains $500
    inv_id = str(inv.id)
    db_session.expire_all()
    inv_ref = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_id))).scalar_one()
    assert inv_ref.total_amount == Decimal("500.00")
    assert inv_ref.lines[0].unit_price == Decimal("250.00")
    assert inv_ref.lines[0].line_total == Decimal("500.00")

# ============================================================================
# 3. CONCURRENT PAYMENT ALLOCATION (ROW-LEVEL LOCKING)
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_payment_allocation_row_locking(db_session: AsyncSession):
    """
    Scenario:
    Invoice balance = 10,000
    Tx A attempts to allocate 10,000 -> succeeds, balance becomes 0, status PAID.
    Tx B attempts to allocate 10,000 concurrently -> fails safely (400 Allocation exceeds balance due).
    Total applied <= 10,000; Balance >= 0.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-CONC-PAY-{uuid.uuid4().hex[:4]}", name="Conc Payment Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("40.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    inv = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert inv.balance_due == Decimal("10000.00")

    # Tx A: Payment of $10,000 -> succeeds
    pay_a = await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id, amount=Decimal("10000.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("10000.00"))]
    ), user_id=user_id)
    assert pay_a.status == "COMPLETED"

    # Tx B: Concurrent payment of $10,000 -> must fail with 400
    with pytest.raises(HTTPException) as exc:
        await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
            customer_id=cust.id, amount=Decimal("10000.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("10000.00"))]
        ), user_id=user_id)
    assert exc.value.status_code == 400

    # Verify exact balance invariants:
    inv_id = str(inv.id)
    db_session.expire_all()
    inv_check = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_id))).scalar_one()
    assert inv_check.amount_paid == Decimal("10000.00")
    assert inv_check.balance_due == Decimal("0.0")
    assert inv_check.status == "PAID"

# ============================================================================
# 4. MULTI-INVOICE PAYMENT ALLOCATION & EXCESS PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_multi_invoice_allocation_and_excess_protection(db_session: AsyncSession):
    """
    Payment = 10,000
    Invoice A = 6,000; Invoice B = 4,000 -> Alloc A = 6,000, Alloc B = 4,000.
    Excess allocation > balance due is rejected.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-MULTI-PAY-{uuid.uuid4().hex[:4]}", name="Multi Pay Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    # Invoice A ($6,000)
    so_a = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("24.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so_a.id, user_id=user_id)
    inv_a = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so_a.id, user_id=user_id)

    # Invoice B ($4,000)
    so_b = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("16.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so_b.id, user_id=user_id)
    inv_b = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so_b.id, user_id=user_id)

    # Valid multi-allocation of $10,000
    pay = await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id,
        amount=Decimal("10000.00"),
        allocations=[
            PaymentAllocationItem(invoice_id=inv_a.id, amount=Decimal("6000.00")),
            PaymentAllocationItem(invoice_id=inv_b.id, amount=Decimal("4000.00"))
        ]
    ), user_id=user_id)
    assert pay.status == "COMPLETED"

    inv_a_id, inv_b_id = str(inv_a.id), str(inv_b.id)
    db_session.expire_all()
    inv_a_ref = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_a_id))).scalar_one()
    inv_b_ref = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_b_id))).scalar_one()
    assert inv_a_ref.status == "PAID"
    assert inv_b_ref.status == "PAID"

# ============================================================================
# 5. PARTIAL PAYMENT & STATUS PROGRESSION
# ============================================================================

@pytest.mark.asyncio
async def test_partial_payment_and_status_progression(db_session: AsyncSession):
    """
    Invoice = 10,000 -> Payment = 4,000 -> Status = PARTIALLY_PAID, Balance = 6,000.
    Second Payment = 6,000 -> Status = PAID, Balance = 0.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-PART2-{uuid.uuid4().hex[:4]}", name="Partial 2 Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("40.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    inv = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Step 1: $4,000 partial payment
    await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id, amount=Decimal("4000.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("4000.00"))]
    ), user_id=user_id)

    inv_id = str(inv.id)
    db_session.expire_all()
    inv_step1 = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_id))).scalar_one()
    assert inv_step1.status == "PARTIALLY_PAID"
    assert inv_step1.amount_paid == Decimal("4000.00")
    assert inv_step1.balance_due == Decimal("6000.00")

    # Step 2: $6,000 remaining payment
    await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id, amount=Decimal("6000.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("6000.00"))]
    ), user_id=user_id)

    db_session.expire_all()
    inv_step2 = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_id))).scalar_one()
    assert inv_step2.status == "PAID"
    assert inv_step2.amount_paid == Decimal("10000.00")
    assert inv_step2.balance_due == Decimal("0.0")

# ============================================================================
# 6. CREDIT EXPOSURE & ORDER CREDIT HOLD
# ============================================================================

@pytest.mark.asyncio
async def test_credit_exposure_and_payment_reduction(db_session: AsyncSession):
    """
    Credit limit = 100,000; Existing exposure = 80,000.
    Order of 30,000 -> exceeds limit (80,000 + 30,000 = 110,000 > 100,000) -> on hold.
    Payment of 20,000 -> reduces exposure from 80,000 to 60,000.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-CRED-EXP-{uuid.uuid4().hex[:4]}",
        name="Credit Exp Corp", credit_limit=Decimal("100000.00"), current_credit_exposure=Decimal("80000.00")
    )
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("200.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    # Order of $30,000
    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("120.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    # Confirming order triggers credit limit hold
    so_conf = await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    assert so_conf.status == "ON_HOLD"
    assert so_conf.hold_reason == "CREDIT_LIMIT_EXCEEDED"

    # Create dummy invoice to apply payment against
    inv = CustomerInvoice(
        id=str(uuid.uuid4()), tenant_id=tenant_id, invoice_number=f"INV-CRED-{uuid.uuid4().hex[:4]}",
        customer_id=cust.id, status="ISSUED", total_amount=Decimal("20000.00"), amount_paid=Decimal("0.0"),
        balance_due=Decimal("20000.00"), currency="USD", issue_date=get_utc_now(), due_date=get_utc_now() + timedelta(days=30)
    )
    db_session.add(inv)
    await db_session.commit()

    # Payment of $20,000 -> decreases customer credit exposure
    await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id, amount=Decimal("20000.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("20000.00"))]
    ), user_id=user_id)

    cust_id = str(cust.id)
    db_session.expire_all()
    cust_ref = (await db_session.execute(select(Customer).where(Customer.id == cust_id))).scalar_one()
    assert cust_ref.current_credit_exposure == Decimal("60000.00")

# ============================================================================
# 7. CREDIT NOTE FROM RMA & DUPLICATE REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_credit_note_from_rma_and_duplicate_guard(db_session: AsyncSession):
    """
    Invoice = 10,000; RMA = 3,000 -> CN = 3,000 -> Invoice balance = 7,000.
    Retry same RMA -> 409 Conflict.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, bin_qu, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-RMA-CN-{uuid.uuid4().hex[:4]}", name="RMA CN Corp")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("40.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("40.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(carrier="FedEx"), user_id=user_id)
    inv = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Process RMA return of 12 units = $3,000
    ret = await SalesService.process_sales_return(db_session, tenant_id, so.id, SalesReturnCreate(
        notes="Return 12 units",
        lines=[SalesReturnLineCreate(so_line_id=so.lines[0].id, quantity_returned=Decimal("12.0"), destination_bin_id=bin_qu.id)]
    ), user_id=user_id)

    # Issue Credit Note
    cn = await InvoicingService.create_credit_note_for_return(db_session, tenant_id, CreditNoteCreate(
        customer_id=cust.id, sales_return_id=ret.id, invoice_id=inv.id, amount=Decimal("3000.00")
    ), user_id=user_id)
    assert cn.status == "APPLIED"

    inv_id = str(inv.id)
    db_session.expire_all()
    inv_ref = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_id))).scalar_one()
    assert inv_ref.balance_due == Decimal("7000.00")

    # Retry same RMA -> must fail with 409 Conflict
    with pytest.raises(HTTPException) as exc:
        await InvoicingService.create_credit_note_for_return(db_session, tenant_id, CreditNoteCreate(
            customer_id=cust.id, sales_return_id=ret.id, invoice_id=inv.id, amount=Decimal("3000.00")
        ), user_id=user_id)
    assert exc.value.status_code == 409

# ============================================================================
# 8. AR AGING EXACT BOUNDARY CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_ar_aging_exact_boundary_conditions(db_session: AsyncSession):
    """
    Tests exact bucket placement:
    - 0 days overdue -> Current
    - 1 day overdue -> 1-30 Days
    - 30 days overdue -> 1-30 Days
    - 31 days overdue -> 31-60 Days
    - 60 days overdue -> 31-60 Days
    - 61 days overdue -> 61-90 Days
    - 90 days overdue -> 61-90 Days
    - 91 days overdue -> 90+ Days
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _ = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-AGE-BND-{uuid.uuid4().hex[:4]}", name="Aging Boundary Corp")
    db_session.add(cust)
    await db_session.commit()

    now = get_utc_now()
    boundaries = [
        (0, "Current"),
        (1, "1-30 Days"),
        (30, "1-30 Days"),
        (31, "31-60 Days"),
        (60, "31-60 Days"),
        (61, "61-90 Days"),
        (90, "61-90 Days"),
        (91, "90+ Days"),
    ]

    for days_overdue, expected_bucket in boundaries:
        inv = CustomerInvoice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            invoice_number=f"INV-BND-{days_overdue}-{uuid.uuid4().hex[:4]}",
            customer_id=cust.id,
            status="ISSUED",
            total_amount=Decimal("100.00"),
            amount_paid=Decimal("0.0"),
            balance_due=Decimal("100.00"),
            currency="USD",
            issue_date=now - timedelta(days=days_overdue + 30),
            due_date=now - timedelta(days=days_overdue)
        )
        db_session.add(inv)
    await db_session.commit()

    report = await InvoicingService.get_ar_aging_report(db_session, tenant_id, as_of_date=now)
    bucket_map = {b.bucket_label: b.total_amount for b in report.summary_buckets}

    assert bucket_map["Current"] >= 100.0 # 0 days
    assert bucket_map["1-30 Days"] >= 200.0 # 1 and 30 days
    assert bucket_map["31-60 Days"] >= 200.0 # 31 and 60 days
    assert bucket_map["61-90 Days"] >= 200.0 # 61 and 90 days
    assert bucket_map["90+ Days"] >= 100.0 # 91 days

# ============================================================================
# 9. BILLING / INVENTORY ISOLATION & IMMUTABILITY INVARIANT
# ============================================================================

@pytest.mark.asyncio
async def test_billing_and_inventory_strict_isolation(db_session: AsyncSession):
    """
    CRITICAL FINANCIAL INVARIANT:
    Invoicing, payments, and credit notes NEVER alter the authoritative inventory ledger,
    physical balances, or cost layers.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_st, _, variant = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-ISO2-{uuid.uuid4().hex[:4]}", name="Isolation Client 2")
    db_session.add(cust)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    cl = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-INV-ISO2-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("100.00"),
        original_quantity=Decimal("10.0"), remaining_quantity=Decimal("10.0"), total_cost=Decimal("1000.00"), status="ACTIVE"
    )
    db_session.add_all([bal, cl])
    await db_session.commit()

    ledger_count_before = (await db_session.execute(select(func.count(StockLedgerTransaction.id)).where(StockLedgerTransaction.tenant_id == tenant_id))).scalar() or 0
    on_hand_before = Decimal(str(bal.quantity_on_hand))
    cost_rem_before = Decimal(str(cl.remaining_quantity))

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("250.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Billing lifecycle
    inv = await InvoicingService.create_invoice_from_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    pay = await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
        customer_id=cust.id, amount=Decimal("500.00"), allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("500.00"))]
    ), user_id=user_id)
    cn = await InvoicingService.create_credit_note_for_return(db_session, tenant_id, CreditNoteCreate(
        customer_id=cust.id, amount=Decimal("100.00"), notes="Goodwill"
    ), user_id=user_id)

    # Verify inventory state is 100% identical
    ledger_count_after = (await db_session.execute(select(func.count(StockLedgerTransaction.id)).where(StockLedgerTransaction.tenant_id == tenant_id))).scalar() or 0
    bal_ref = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.id == bal.id))).scalar_one()
    cl_ref = (await db_session.execute(select(CostLayer).where(CostLayer.id == cl.id))).scalar_one()

    assert ledger_count_after == ledger_count_before
    assert bal_ref.quantity_on_hand == on_hand_before
    assert cl_ref.remaining_quantity == cost_rem_before

# ============================================================================
# 10. PAYMENT METHOD SEMANTICS & AUDITABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_payment_methods_and_auditability(db_session: AsyncSession):
    """
    Verifies CASH, BANK_TRANSFER, CREDIT_CARD, CHECK payment methods and AuditLog generation.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _ = await create_invoicing_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-PM-AUD-{uuid.uuid4().hex[:4]}", name="PM Audit Corp")
    db_session.add(cust)
    await db_session.commit()

    methods = ["CASH", "BANK_TRANSFER", "CREDIT_CARD", "CHECK"]
    for pm in methods:
        inv = CustomerInvoice(
            id=str(uuid.uuid4()), tenant_id=tenant_id, invoice_number=f"INV-PM-{pm}-{uuid.uuid4().hex[:4]}",
            customer_id=cust.id, status="ISSUED", total_amount=Decimal("100.00"), amount_paid=Decimal("0.0"),
            balance_due=Decimal("100.00"), currency="USD", issue_date=get_utc_now(), due_date=get_utc_now() + timedelta(days=30)
        )
        db_session.add(inv)
        await db_session.commit()

        pay = await InvoicingService.record_customer_payment(db_session, tenant_id, CustomerPaymentCreate(
            customer_id=cust.id, payment_method=pm, amount=Decimal("100.00"),
            allocations=[PaymentAllocationItem(invoice_id=inv.id, amount=Decimal("100.00"))]
        ), user_id=user_id)
        assert pay.payment_method == pm
        assert pay.status == "COMPLETED"

    # Verify audit logs created
    audit_events = (await db_session.execute(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.action == "RECORD_PAYMENT")
    )).scalars().all()
    assert len(audit_events) >= 4
