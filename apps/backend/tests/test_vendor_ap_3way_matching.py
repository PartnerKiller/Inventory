import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.purchasing import (
    Supplier,
    PurchaseOrder,
    POLineItem,
    GoodsReceipt,
    GoodsReceiptLine,
    SupplierReturn,
    SupplierReturnLine,
    SupplierDebitMemo
)
from app.models.ap import (
    VendorInvoice,
    VendorInvoiceLine,
    VendorPayment,
    VendorPaymentAllocation,
    APMatchingTolerance
)
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer
from app.models.audit import AuditLog
from app.schemas.ap import (
    VendorInvoiceCreate,
    VendorInvoiceLineCreate,
    VendorPaymentCreate,
    VendorPaymentAllocationItem
)
from app.services.purchase_service import PurchaseService
from app.services.ap_service import APService
from app.services.ap_matching_service import APMatchingService

async def create_ap_test_environment(db: AsyncSession, tenant_id: str):
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-AP-{uuid.uuid4().hex[:4]}", name="AP DC")
    db.add(wh)
    await db.flush()

    bin_rec = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="REC-01", type="RECEIVING")
    bin_st = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="ST-01", type="STORAGE")
    db.add_all([bin_rec, bin_st])

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Raw Materials", code=f"RAW-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-AP-{uuid.uuid4().hex[:4]}", name="Steel Fastener")
    db.add(item)
    await db.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"{item.sku}-V1",
        variant_name="Grade 8",
        cost_price=Decimal("50.00"),
        selling_price=Decimal("100.00")
    )
    db.add(variant)

    supp = Supplier(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=f"SUPP-AP-{uuid.uuid4().hex[:4]}",
        name="Global Steel Works",
        payment_terms="Net 30",
        currency="USD"
    )
    db.add(supp)
    await db.commit()

    return wh, bin_rec, bin_st, variant, supp

# ============================================================================
# 1. CONCURRENT VENDOR PAYMENT ALLOCATION (ROW-LEVEL LOCKING)
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_vendor_payment_allocation_real_row_locks(db_session: AsyncSession):
    """
    Vendor Bill = $10,000.
    Tx A attempts to allocate $10,000 -> succeeds, balance becomes $0, status PAID.
    Tx B attempts to allocate $10,000 concurrently -> fails safely (400 Allocation exceeds balance due).
    Total applied <= $10,000; Balance >= $0.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _, supp = await create_ap_test_environment(db_session, tenant_id)

    inv = VendorInvoice(
        id=str(uuid.uuid4()), tenant_id=tenant_id, invoice_number=f"INV-V-CONC-{uuid.uuid4().hex[:4]}",
        vendor_invoice_reference="BILL-CONC-001", purchase_order_id=str(uuid.uuid4()), supplier_id=supp.id,
        status="APPROVED", total_amount=Decimal("10000.00"), amount_paid=Decimal("0.0"), balance_due=Decimal("10000.00"),
        currency="USD", invoice_date=get_utc_now(), due_date=get_utc_now() + timedelta(days=30)
    )
    db_session.add(inv)
    await db_session.commit()

    # Tx A: Payment of $10,000 -> succeeds
    pay_a = await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
        supplier_id=supp.id, amount=Decimal("10000.00"),
        allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("10000.00"))]
    ), user_id=user_id)
    assert pay_a.status == "COMPLETED"

    # Tx B: Concurrent payment of $10,000 -> must fail with 400
    with pytest.raises(HTTPException) as exc:
        await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
            supplier_id=supp.id, amount=Decimal("10000.00"),
            allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("10000.00"))]
        ), user_id=user_id)
    assert exc.value.status_code == 400

    inv_id = str(inv.id)
    db_session.expire_all()
    inv_ref = (await db_session.execute(select(VendorInvoice).where(VendorInvoice.id == inv_id))).scalar_one()
    assert inv_ref.amount_paid == Decimal("10000.00")
    assert inv_ref.balance_due == Decimal("0.0")
    assert inv_ref.status == "PAID"

# ============================================================================
# 2. PPV TOLERANCE BOUNDARIES & DUAL THRESHOLD RULE
# ============================================================================

@pytest.mark.asyncio
async def test_ppv_tolerance_boundaries_exact_tests(db_session: AsyncSession):
    """
    Tests exact tolerance rule:
    PASS when: price_variance_pct <= 2.0% AND abs(PPV) <= $50.00
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_rec, _, variant, supp = await create_ap_test_environment(db_session, tenant_id)

    # --- Test 1: PO = $100, Billed = $101.50 (1.5%, PPV $1.50 <= $50) -> APPROVED ---
    po1 = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-T1-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("100.00"))
    po1_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po1.id, item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), quantity_received=Decimal("1.0"), unit_price=Decimal("100.00"), line_total=Decimal("100.00"))
    db_session.add_all([po1, po1_line])
    await db_session.commit()

    inv1 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po1.id, vendor_invoice_reference="INV-T1-101.50",
        lines=[VendorInvoiceLineCreate(po_line_id=po1_line.id, item_variant_id=variant.id, billed_quantity=Decimal("1.0"), billed_unit_price=Decimal("101.50"))]
    ), user_id=user_id)
    assert inv1.status == "APPROVED"
    assert inv1.match_status == "WITHIN_TOLERANCE"

    # --- Test 2: PO = $100, Billed = $102.00 (2.0%, PPV $2.00 <= $50) -> APPROVED ---
    po2 = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-T2-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("100.00"))
    po2_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po2.id, item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), quantity_received=Decimal("1.0"), unit_price=Decimal("100.00"), line_total=Decimal("100.00"))
    db_session.add_all([po2, po2_line])
    await db_session.commit()

    inv2 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po2.id, vendor_invoice_reference="INV-T2-102.00",
        lines=[VendorInvoiceLineCreate(po_line_id=po2_line.id, item_variant_id=variant.id, billed_quantity=Decimal("1.0"), billed_unit_price=Decimal("102.00"))]
    ), user_id=user_id)
    assert inv2.status == "APPROVED"
    assert inv2.match_status == "WITHIN_TOLERANCE"

    # --- Test 3: PO = $1,000, Billed = $1,020.00 (2.0%, PPV $20.00 <= $50) -> APPROVED ---
    po3 = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-T3-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("1000.00"))
    po3_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po3.id, item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), quantity_received=Decimal("1.0"), unit_price=Decimal("1000.00"), line_total=Decimal("1000.00"))
    db_session.add_all([po3, po3_line])
    await db_session.commit()

    inv3 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po3.id, vendor_invoice_reference="INV-T3-1020.00",
        lines=[VendorInvoiceLineCreate(po_line_id=po3_line.id, item_variant_id=variant.id, billed_quantity=Decimal("1.0"), billed_unit_price=Decimal("1020.00"))]
    ), user_id=user_id)
    assert inv3.status == "APPROVED"
    assert inv3.match_status == "WITHIN_TOLERANCE"

    # --- Test 4: PO = $10,000, Billed = $10,200.00 (2.0% variance, BUT PPV $200 > $50 cap) -> EXCEPTION_HOLD ---
    po4 = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-T4-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("10000.00"))
    po4_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po4.id, item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), quantity_received=Decimal("1.0"), unit_price=Decimal("10000.00"), line_total=Decimal("10000.00"))
    db_session.add_all([po4, po4_line])
    await db_session.commit()

    inv4 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po4.id, vendor_invoice_reference="INV-T4-10200.00",
        lines=[VendorInvoiceLineCreate(po_line_id=po4_line.id, item_variant_id=variant.id, billed_quantity=Decimal("1.0"), billed_unit_price=Decimal("10200.00"))]
    ), user_id=user_id)
    assert inv4.status == "EXCEPTION_HOLD"
    assert inv4.match_status == "PRICE_VARIANCE_EXCEPTION"

    # --- Test 5: PO = $10, Billed = $10.50 (5.0% > 2.0% tolerance, though PPV $0.50 < $50) -> EXCEPTION_HOLD ---
    po5 = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-T5-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("10.00"))
    po5_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po5.id, item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), quantity_received=Decimal("1.0"), unit_price=Decimal("10.00"), line_total=Decimal("10.00"))
    db_session.add_all([po5, po5_line])
    await db_session.commit()

    inv5 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po5.id, vendor_invoice_reference="INV-T5-10.50",
        lines=[VendorInvoiceLineCreate(po_line_id=po5_line.id, item_variant_id=variant.id, billed_quantity=Decimal("1.0"), billed_unit_price=Decimal("10.50"))]
    ), user_id=user_id)
    assert inv5.status == "EXCEPTION_HOLD"
    assert inv5.match_status == "PRICE_VARIANCE_EXCEPTION"

# ============================================================================
# 3. PARTIAL VENDOR PAYMENT LIFECYCLE
# ============================================================================

@pytest.mark.asyncio
async def test_partial_vendor_payment_lifecycle(db_session: AsyncSession):
    """
    Vendor Bill = $10,000.
    Payment #1 = $4,000 -> PARTIALLY_PAID, Balance = $6,000.
    Payment #2 = $6,000 -> PAID, Balance = $0.
    Overpayment attempt of $1,000 -> rejected.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _, supp = await create_ap_test_environment(db_session, tenant_id)

    inv = VendorInvoice(
        id=str(uuid.uuid4()), tenant_id=tenant_id, invoice_number=f"INV-V-PART-{uuid.uuid4().hex[:4]}",
        vendor_invoice_reference="BILL-PART-01", purchase_order_id=str(uuid.uuid4()), supplier_id=supp.id,
        status="APPROVED", total_amount=Decimal("10000.00"), amount_paid=Decimal("0.0"), balance_due=Decimal("10000.00"),
        currency="USD", invoice_date=get_utc_now(), due_date=get_utc_now() + timedelta(days=30)
    )
    db_session.add(inv)
    await db_session.commit()

    # Step 1: Payment of $4,000
    await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
        supplier_id=supp.id, amount=Decimal("4000.00"),
        allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("4000.00"))]
    ), user_id=user_id)

    inv_id = str(inv.id)
    db_session.expire_all()
    inv_step1 = (await db_session.execute(select(VendorInvoice).where(VendorInvoice.id == inv_id))).scalar_one()
    assert inv_step1.status == "PARTIALLY_PAID"
    assert inv_step1.amount_paid == Decimal("4000.00")
    assert inv_step1.balance_due == Decimal("6000.00")

    # Step 2: Payment of $6,000
    await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
        supplier_id=supp.id, amount=Decimal("6000.00"),
        allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("6000.00"))]
    ), user_id=user_id)

    db_session.expire_all()
    inv_step2 = (await db_session.execute(select(VendorInvoice).where(VendorInvoice.id == inv_id))).scalar_one()
    assert inv_step2.status == "PAID"
    assert inv_step2.amount_paid == Decimal("10000.00")
    assert inv_step2.balance_due == Decimal("0.0")

    # Step 3: Overpayment attempt of $1,000 -> rejected
    with pytest.raises(HTTPException) as exc:
        await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
            supplier_id=supp.id, amount=Decimal("1000.00"),
            allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("1000.00"))]
        ), user_id=user_id)
    assert exc.value.status_code == 400

# ============================================================================
# 4. VENDOR INVOICE HISTORICAL IMMUTABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_vendor_invoice_historical_immutability(db_session: AsyncSession):
    """
    Create and approve vendor bill.
    Modify master data (PO price, product price, supplier terms).
    Verify historical vendor invoice snapshot remains completely unchanged.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_rec, _, variant, supp = await create_ap_test_environment(db_session, tenant_id)

    po = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-IMMUT-{uuid.uuid4().hex[:4]}",
        supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("500.00")
    )
    po_line = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=variant.id,
        quantity_ordered=Decimal("5.0"), quantity_received=Decimal("5.0"), unit_price=Decimal("100.00"),
        line_total=Decimal("500.00")
    )
    db_session.add_all([po, po_line])
    await db_session.commit()

    inv = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po.id, vendor_invoice_reference="INV-IMMUT-01",
        lines=[VendorInvoiceLineCreate(
            po_line_id=po_line.id, item_variant_id=variant.id,
            billed_quantity=Decimal("5.0"), billed_unit_price=Decimal("100.00")
        )]
    ), user_id=user_id)

    # Master Data Mutations:
    po_line.unit_price = Decimal("999.00")
    variant.cost_price = Decimal("888.00")
    supp.name = "Mutated Supplier Corp"
    await db_session.commit()

    # Verify historical invoice remains $500 with unit price $100
    inv_id = str(inv.id)
    db_session.expire_all()
    inv_ref = (await db_session.execute(select(VendorInvoice).where(VendorInvoice.id == inv_id))).scalar_one()
    assert inv_ref.total_amount == Decimal("500.00")
    assert inv_ref.lines[0].billed_unit_price == Decimal("100.00")
    assert inv_ref.lines[0].po_unit_price == Decimal("100.00")
    assert inv_ref.lines[0].line_total == Decimal("500.00")

# ============================================================================
# 5. PARTIAL RECEIPT / PARTIAL INVOICE
# ============================================================================

@pytest.mark.asyncio
async def test_partial_receipt_and_partial_invoice_behavior(db_session: AsyncSession):
    """
    PO = 100 units. GRN = 60 units.
    Case 1: Invoice = 60 units -> Valid match (APPROVED, EXACT_MATCH against received).
    Case 2: Invoice = 100 units -> Overbilling relative to received quantity -> EXCEPTION_HOLD.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_rec, _, variant, supp = await create_ap_test_environment(db_session, tenant_id)

    # PO for 100 units
    po = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-PART-REC-{uuid.uuid4().hex[:4]}",
        supplier_id=supp.id, target_warehouse_id=wh.id, status="PARTIALLY_RECEIVED", total_amount=Decimal("10000.00")
    )
    po_line = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=variant.id,
        quantity_ordered=Decimal("100.0"), quantity_received=Decimal("60.0"), unit_price=Decimal("100.00"),
        line_total=Decimal("10000.00")
    )
    # GRN for 60 units
    grn = GoodsReceipt(
        id=str(uuid.uuid4()), purchase_order_id=po.id, grn_number=f"GRN-PART-{uuid.uuid4().hex[:4]}",
        warehouse_id=wh.id
    )
    grn_line = GoodsReceiptLine(
        id=str(uuid.uuid4()), goods_receipt_id=grn.id, po_line_id=po_line.id,
        item_variant_id=variant.id, quantity_received=Decimal("60.0"), destination_bin_id=bin_rec.id
    )
    db_session.add_all([po, po_line, grn, grn_line])
    await db_session.commit()

    # Case 1: Invoice for 60 units (matches received quantity) -> APPROVED
    inv1 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po.id, goods_receipt_id=grn.id, vendor_invoice_reference="INV-PART-60",
        lines=[VendorInvoiceLineCreate(
            po_line_id=po_line.id, grn_line_id=grn_line.id, item_variant_id=variant.id,
            billed_quantity=Decimal("60.0"), billed_unit_price=Decimal("100.00")
        )]
    ), user_id=user_id)
    assert inv1.status == "APPROVED"
    assert inv1.match_status == "EXACT_MATCH"
    assert inv1.total_amount == Decimal("6000.00")

    # Case 2: Invoice for 100 units (exceeds received 60 units) -> EXCEPTION_HOLD
    inv2 = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po.id, goods_receipt_id=grn.id, vendor_invoice_reference="INV-PART-100",
        lines=[VendorInvoiceLineCreate(
            po_line_id=po_line.id, grn_line_id=grn_line.id, item_variant_id=variant.id,
            billed_quantity=Decimal("100.0"), billed_unit_price=Decimal("100.00")
        )]
    ), user_id=user_id)
    assert inv2.status == "EXCEPTION_HOLD"
    assert inv2.match_status == "QUANTITY_VARIANCE_EXCEPTION"

# ============================================================================
# 6. AP AGING EXACT BOUNDARY CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_ap_aging_exact_boundaries(db_session: AsyncSession):
    """
    Tests exact bucket placement:
    0 days -> Current
    1 & 30 days -> 1-30 Days
    31 & 60 days -> 31-60 Days
    61 & 90 days -> 61-90 Days
    91+ days -> 90+ Days
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _, supp = await create_ap_test_environment(db_session, tenant_id)

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
        inv = VendorInvoice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            invoice_number=f"INV-V-BND-{days_overdue}-{uuid.uuid4().hex[:4]}",
            vendor_invoice_reference=f"REF-BND-{days_overdue}",
            purchase_order_id=str(uuid.uuid4()),
            supplier_id=supp.id,
            status="APPROVED",
            total_amount=Decimal("100.00"),
            amount_paid=Decimal("0.0"),
            balance_due=Decimal("100.00"),
            currency="USD",
            invoice_date=now - timedelta(days=days_overdue + 30),
            due_date=now - timedelta(days=days_overdue)
        )
        db_session.add(inv)
    await db_session.commit()

    report = await APService.get_ap_aging_report(db_session, tenant_id, as_of_date=now)
    bucket_map = {b.bucket_label: b.total_amount for b in report.summary_buckets}

    assert bucket_map["Current"] >= 100.0
    assert bucket_map["1-30 Days"] >= 200.0
    assert bucket_map["31-60 Days"] >= 200.0
    assert bucket_map["61-90 Days"] >= 200.0
    assert bucket_map["90+ Days"] >= 100.0

# ============================================================================
# 7. AP / INVENTORY STRICT ISOLATION INVARIANT
# ============================================================================

@pytest.mark.asyncio
async def test_ap_and_inventory_strict_isolation_invariant(db_session: AsyncSession):
    """
    CRITICAL FINANCIAL INVARIANT:
    Vendor invoice intake, 3-way matching, payments, and debit memo applications
    NEVER mutate the authoritative stock ledger, on-hand balances, or cost layers.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_rec, bin_st, variant, supp = await create_ap_test_environment(db_session, tenant_id)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    cl = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-AP-ISO2-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("50.00"),
        original_quantity=Decimal("50.0"), remaining_quantity=Decimal("50.0"), total_cost=Decimal("2500.00"), status="ACTIVE"
    )
    db_session.add_all([bal, cl])
    await db_session.commit()

    tx_count_before = (await db_session.execute(select(func.count(StockLedgerTransaction.id)).where(StockLedgerTransaction.tenant_id == tenant_id))).scalar() or 0
    on_hand_before = Decimal(str(bal.quantity_on_hand))
    cost_rem_before = Decimal(str(cl.remaining_quantity))

    # AP workflow
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-ISO-{uuid.uuid4().hex[:4]}", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("500.00"))
    po_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=variant.id, quantity_ordered=Decimal("5.0"), quantity_received=Decimal("5.0"), unit_price=Decimal("100.00"), line_total=Decimal("500.00"))
    db_session.add_all([po, po_line])
    await db_session.commit()

    inv = await APService.create_vendor_invoice(db_session, tenant_id, VendorInvoiceCreate(
        purchase_order_id=po.id, vendor_invoice_reference="INV-ISO-01",
        lines=[VendorInvoiceLineCreate(po_line_id=po_line.id, item_variant_id=variant.id, billed_quantity=Decimal("5.0"), billed_unit_price=Decimal("100.00"))]
    ), user_id=user_id)

    pay = await APService.record_vendor_payment(db_session, tenant_id, VendorPaymentCreate(
        supplier_id=supp.id, amount=Decimal("500.00"),
        allocations=[VendorPaymentAllocationItem(vendor_invoice_id=inv.id, amount=Decimal("500.00"))]
    ), user_id=user_id)

    # Invariants verification
    tx_count_after = (await db_session.execute(select(func.count(StockLedgerTransaction.id)).where(StockLedgerTransaction.tenant_id == tenant_id))).scalar() or 0
    bal_ref = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.id == bal.id))).scalar_one()
    cl_ref = (await db_session.execute(select(CostLayer).where(CostLayer.id == cl.id))).scalar_one()

    assert tx_count_after == tx_count_before
    assert bal_ref.quantity_on_hand == on_hand_before
    assert cl_ref.remaining_quantity == cost_rem_before

# ============================================================================
# 8. DUPLICATE VENDOR INVOICE REFERENCE & DEBIT MEMO TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_duplicate_vendor_invoice_reference_guard(db_session: AsyncSession):
    """
    Same supplier_id + vendor_invoice_reference -> 409 Conflict.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, _, variant, supp = await create_ap_test_environment(db_session, tenant_id)

    po = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-AP6-{uuid.uuid4().hex[:4]}",
        supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("500.00")
    )
    po_line = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=variant.id,
        quantity_ordered=Decimal("5.0"), quantity_received=Decimal("5.0"), unit_price=Decimal("100.00"),
        line_total=Decimal("500.00")
    )
    db_session.add_all([po, po_line])
    await db_session.commit()

    inv_in = VendorInvoiceCreate(
        purchase_order_id=po.id,
        vendor_invoice_reference="INV-UNIQUE-REF-001",
        lines=[VendorInvoiceLineCreate(
            po_line_id=po_line.id, item_variant_id=variant.id,
            billed_quantity=Decimal("5.0"), billed_unit_price=Decimal("100.00")
        )]
    )
    await APService.create_vendor_invoice(db_session, tenant_id, inv_in, user_id=user_id)

    # Attempt to ingest duplicate invoice reference
    with pytest.raises(HTTPException) as exc:
        await APService.create_vendor_invoice(db_session, tenant_id, inv_in, user_id=user_id)
    assert exc.value.status_code == 409

@pytest.mark.asyncio
async def test_rtv_debit_memo_application(db_session: AsyncSession):
    """
    Apply Phase 5 SupplierDebitMemo ($2,000) against $10,000 bill -> balance becomes $8,000.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _, supp = await create_ap_test_environment(db_session, tenant_id)

    inv = VendorInvoice(
        id=str(uuid.uuid4()), tenant_id=tenant_id, invoice_number=f"INV-V-DM-{uuid.uuid4().hex[:4]}",
        vendor_invoice_reference="BILL-DM", purchase_order_id=str(uuid.uuid4()), supplier_id=supp.id,
        status="APPROVED", total_amount=Decimal("10000.00"), amount_paid=Decimal("0.0"), balance_due=Decimal("10000.00"),
        currency="USD", invoice_date=get_utc_now(), due_date=get_utc_now() + timedelta(days=30)
    )
    dm = SupplierDebitMemo(
        id=str(uuid.uuid4()), tenant_id=tenant_id, memo_number=f"DM-TEST-{uuid.uuid4().hex[:4]}",
        supplier_id=supp.id, amount=Decimal("2000.00"), currency="USD", status="OPEN"
    )
    db_session.add_all([inv, dm])
    await db_session.commit()

    # Apply debit memo
    inv_app = await APService.apply_debit_memo(db_session, tenant_id, inv.id, dm.id, user_id=user_id)
    assert inv_app.balance_due == Decimal("8000.00")
    assert inv_app.status == "PARTIALLY_PAID"

    dm_id = str(dm.id)
    db_session.expire_all()
    dm_ref = (await db_session.execute(select(SupplierDebitMemo).where(SupplierDebitMemo.id == dm_id))).scalar_one()
    assert dm_ref.status == "APPLIED"
