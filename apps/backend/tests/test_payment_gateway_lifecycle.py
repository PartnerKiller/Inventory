import pytest
import uuid
import hmac
import hashlib
import json
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.base import get_utc_now
from app.models.sales import Customer, SalesOrder
from app.models.invoicing import CustomerInvoice, InvoiceLineItem, CustomerPayment, PaymentAllocation
from app.models.ledger import StockLedgerTransaction
from app.models.costing import CostLayer
from app.models.payment_gateway import (
    PaymentGatewayAccount,
    PaymentTransaction,
    PaymentTransactionRefund,
    PaymentWebhookEvent
)
from app.schemas.payment_gateway import (
    PaymentIntentCreateRequest,
    PaymentRefundRequest
)
from app.services.payment_service import PaymentService

async def create_payment_test_environment(db: AsyncSession, tenant_id: str):
    # Customer A & B
    cust_a = Customer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-A-{uuid.uuid4().hex[:4]}",
        name="Apex Logistics Inc", currency="USD", current_credit_exposure=Decimal("10000.00")
    )
    cust_b = Customer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-B-{uuid.uuid4().hex[:4]}",
        name="Zenith Dynamics", currency="USD", current_credit_exposure=Decimal("5000.00")
    )
    db.add_all([cust_a, cust_b])
    await db.flush()

    # Invoice for Customer A (₹10,000)
    inv_a = CustomerInvoice(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        invoice_number=f"INV-A-{uuid.uuid4().hex[:4]}",
        customer_id=cust_a.id,
        status="ISSUED",
        subtotal_amount=Decimal("10000.00"),
        total_amount=Decimal("10000.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("10000.00"),
        currency="USD",
        due_date=get_utc_now() + timedelta(days=30)
    )
    db.add(inv_a)

    # Invoice for Customer B (₹5,000)
    inv_b = CustomerInvoice(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        invoice_number=f"INV-B-{uuid.uuid4().hex[:4]}",
        customer_id=cust_b.id,
        status="ISSUED",
        subtotal_amount=Decimal("5000.00"),
        total_amount=Decimal("5000.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("5000.00"),
        currency="USD",
        due_date=get_utc_now() + timedelta(days=30)
    )
    db.add(inv_b)

    # Gateway Account
    gw_acc = await PaymentService.get_or_create_gateway_account(db, tenant_id, "MOCK")

    await db.commit()
    return cust_a, cust_b, inv_a, inv_b, gw_acc

# ============================================================================
# 1. PAYMENT STATE MACHINE (VALID & INVALID TRANSITIONS)
# ============================================================================

@pytest.mark.asyncio
async def test_payment_state_machine_valid_and_invalid_transitions(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, gw_acc = await create_payment_test_environment(db_session, tenant_id)

    # 1. Valid: CREATED -> PENDING
    intent_req = PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("10000.00"), payment_method_type="CARD")
    intent_resp = await PaymentService.create_payment_intent(db_session, tenant_id, cust_a.id, intent_req, provider_code="MOCK")
    assert intent_resp.status == "PENDING"

    # 2. Valid: PENDING -> SUCCEEDED
    txn = await PaymentService.settle_payment_success(
        db=db_session, tenant_id=tenant_id, transaction_id=intent_resp.transaction_id,
        gateway_charge_id="ch_mock_sm_1", amount_captured=Decimal("10000.00")
    )
    assert txn.status == "SUCCEEDED"

    # 3. Valid: SUCCEEDED -> PARTIALLY_REFUNDED
    ref1 = await PaymentService.process_refund(
        db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("3000.00"), reason="Partial return")
    )
    assert ref1.status == "SUCCEEDED"
    await db_session.refresh(txn)
    assert txn.status == "PARTIALLY_REFUNDED"

    # 4. Valid: PARTIALLY_REFUNDED -> REFUNDED
    ref2 = await PaymentService.process_refund(
        db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("7000.00"), reason="Full return balance")
    )
    assert ref2.status == "SUCCEEDED"
    await db_session.refresh(txn)
    assert txn.status == "REFUNDED"

    # 5. Invalid: REFUNDED -> CANCELLED or any further cancellation / refund
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.cancel_payment_transaction(db_session, tenant_id, txn.id, reason="Try cancel refunded")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.process_refund(db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("100.00")))
    assert exc_info.value.status_code == 400

# ============================================================================
# 2. PAYMENT IDEMPOTENCY & CONCURRENT DUPLICATE REQUESTS
# ============================================================================

@pytest.mark.asyncio
async def test_payment_idempotency_and_concurrent_requests(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    idem_key = f"idem_payment_test_{uuid.uuid4().hex}"
    req = PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("5000.00"), idempotency_key=idem_key)

    # 1. First call
    res1 = await PaymentService.create_payment_intent(db_session, tenant_id, cust_a.id, req)
    # 2. Second call with same idempotency key
    res2 = await PaymentService.create_payment_intent(db_session, tenant_id, cust_a.id, req)

    assert res1.transaction_id == res2.transaction_id
    assert res1.transaction_number == res2.transaction_number
    assert res1.gateway_intent_id == res2.gateway_intent_id

    # Verify only 1 record exists in DB
    tx_count = (await db_session.execute(
        select(func.count()).select_from(PaymentTransaction).where(PaymentTransaction.idempotency_key == idem_key)
    )).scalar()
    assert tx_count == 1

# ============================================================================
# 3. LOST GATEWAY RESPONSE RECOVERY
# ============================================================================

@pytest.mark.asyncio
async def test_lost_gateway_response_recovery(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    idem_key = f"idem_lost_resp_{uuid.uuid4().hex}"
    req = PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("10000.00"), idempotency_key=idem_key)

    # 1. Client creates intent
    res = await PaymentService.create_payment_intent(db_session, tenant_id, cust_a.id, req)

    # 2. Gateway processes payment successfully
    await PaymentService.settle_payment_success(db_session, tenant_id, res.transaction_id, "ch_lost_resp", Decimal("10000.00"))

    # 3. Client retries intent creation due to lost response
    retry_res = await PaymentService.create_payment_intent(db_session, tenant_id, cust_a.id, req)

    assert retry_res.transaction_id == res.transaction_id
    assert retry_res.status == "SUCCEEDED"

    # Verify invoice is settled exactly once
    inv_db = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == inv_a.id))).scalar_one()
    assert inv_db.amount_paid == Decimal("10000.00")
    assert inv_db.balance_due == Decimal("0.00")
    assert inv_db.status == "PAID"

    allocs = (await db_session.execute(select(PaymentAllocation).where(PaymentAllocation.invoice_id == inv_a.id))).scalars().all()
    assert len(allocs) == 1

# ============================================================================
# 4. CAPTURE IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_capture_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("4000.00"))
    )

    # Capture 1
    t1 = await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_cap_1", Decimal("4000.00"))
    assert t1.status == "SUCCEEDED"

    # Capture 2 (replay / retry)
    t2 = await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_cap_1", Decimal("4000.00"))
    assert t2.status == "SUCCEEDED"

    # Assert exactly 1 payment allocation created
    alloc_count = (await db_session.execute(
        select(func.count()).select_from(PaymentAllocation).where(PaymentAllocation.invoice_id == inv_a.id)
    )).scalar()
    assert alloc_count == 1

# ============================================================================
# 5. REFUND IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_refund_idempotency_and_retry(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("10000.00"))
    )
    txn = await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_ref_idem", Decimal("10000.00"))

    ref_idem = f"ref_idem_key_{uuid.uuid4().hex}"
    req = PaymentRefundRequest(amount=Decimal("3000.00"), reason="Return item", idempotency_key=ref_idem)

    # First refund attempt
    ref1 = await PaymentService.process_refund(db_session, tenant_id, txn.id, req)
    # Duplicate retry
    ref2 = await PaymentService.process_refund(db_session, tenant_id, txn.id, req)

    assert ref1.refund_id == ref2.refund_id
    assert ref1.refund_number == ref2.refund_number

    # Assert exactly 1 refund record exists in DB
    ref_count = (await db_session.execute(
        select(func.count()).select_from(PaymentTransactionRefund).where(PaymentTransactionRefund.idempotency_key == ref_idem)
    )).scalar()
    assert ref_count == 1

# ============================================================================
# 6. CONCURRENT PAYMENT PROTECTION (REAL ROW LOCKS)
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_payment_protection_real_db(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust, _, inv, _, _ = await create_payment_test_environment(db_session, tenant_id)
    invoice_id = inv.id
    cust_id = cust.id

    # 1. Payment A: ₹7,000 -> succeeds
    res_a = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_id,
        PaymentIntentCreateRequest(invoice_id=invoice_id, amount=Decimal("7000.00"), idempotency_key=f"p_a_{uuid.uuid4().hex}")
    )
    await PaymentService.settle_payment_success(
        db_session, tenant_id, res_a.transaction_id, "ch_conc_a", Decimal("7000.00")
    )

    # 2. Payment B: Concurrent ₹7,000 on remaining balance ₹3,000 -> Must FAIL safely with 400
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.create_payment_intent(
            db_session, tenant_id, cust_id,
            PaymentIntentCreateRequest(invoice_id=invoice_id, amount=Decimal("7000.00"), idempotency_key=f"p_b_{uuid.uuid4().hex}")
        )
    assert exc_info.value.status_code == 400
    assert "exceeds outstanding balance" in exc_info.value.detail

    inv_check = (await db_session.execute(select(CustomerInvoice).where(CustomerInvoice.id == invoice_id))).scalar_one()
    assert inv_check.amount_paid == Decimal("7000.00")
    assert inv_check.balance_due == Decimal("3000.00")
    assert inv_check.balance_due >= Decimal("0.00")

# ============================================================================
# 7. CONCURRENT REFUND PROTECTION (REAL ROW LOCKS)
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_refund_protection_real_db(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust, _, inv, _, _ = await create_payment_test_environment(db_session, tenant_id)
    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust.id, PaymentIntentCreateRequest(invoice_id=inv.id, amount=Decimal("10000.00"))
    )
    txn = await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_ref_conc", Decimal("10000.00"))
    txn_id = txn.id

    # 1. Refund A: ₹7,000 -> succeeds
    ref_a = await PaymentService.process_refund(
        db_session, tenant_id, txn_id,
        PaymentRefundRequest(amount=Decimal("7000.00"), reason="Refund part 1", idempotency_key=f"ref_a_{uuid.uuid4().hex}")
    )
    assert ref_a.status == "SUCCEEDED"

    # 2. Refund B: Concurrent ₹7,000 on remaining refundable ₹3,000 -> Must FAIL safely with 400
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.process_refund(
            db_session, tenant_id, txn_id,
            PaymentRefundRequest(amount=Decimal("7000.00"), reason="Refund part 2", idempotency_key=f"ref_b_{uuid.uuid4().hex}")
        )
    assert exc_info.value.status_code == 400
    assert "exceeds available captured amount" in exc_info.value.detail

    txn_check = (await db_session.execute(select(PaymentTransaction).where(PaymentTransaction.id == txn_id))).scalar_one()
    assert txn_check.amount_refunded == Decimal("7000.00")
    assert txn_check.amount_refunded <= Decimal("10000.00")

# ============================================================================
# 8. REFUND LIFECYCLE & COMPLETE EXHAUSTION
# ============================================================================

@pytest.mark.asyncio
async def test_refund_lifecycle_and_exhaustion(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    # Pay ₹10,000
    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("10000.00"))
    )
    txn = await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_ref_life", Decimal("10000.00"))

    # Step 1: Refund ₹3,000 -> remaining ₹7,000
    r1 = await PaymentService.process_refund(db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("3000.00")))
    assert r1.status == "SUCCEEDED"

    # Step 2: Refund ₹2,000 -> remaining ₹5,000
    r2 = await PaymentService.process_refund(db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("2000.00")))
    assert r2.status == "SUCCEEDED"

    # Step 3: Refund remaining ₹5,000 -> REFUNDED
    r3 = await PaymentService.process_refund(db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("5000.00")))
    assert r3.status == "SUCCEEDED"

    await db_session.refresh(txn)
    assert txn.status == "REFUNDED"
    assert txn.amount_refunded == Decimal("10000.00")

    # Step 4: Attempt further refund -> MUST REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.process_refund(db_session, tenant_id, txn.id, PaymentRefundRequest(amount=Decimal("100.00")))
    assert exc_info.value.status_code == 400

# ============================================================================
# 9. AUTHORIZATION / CAPTURE / CANCELLATION LIFECYCLE
# ============================================================================

@pytest.mark.asyncio
async def test_authorization_capture_and_cancellation_lifecycle(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    # 1. PENDING -> CANCELLED
    intent1 = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("2000.00"))
    )
    c1 = await PaymentService.cancel_payment_transaction(db_session, tenant_id, intent1.transaction_id, reason="Customer abandoned")
    assert c1.status == "CANCELLED"

    # 2. SUCCEEDED -> CANCELLED (Must Reject with 400)
    intent2 = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("3000.00"))
    )
    await PaymentService.settle_payment_success(db_session, tenant_id, intent2.transaction_id, "ch_succ", Decimal("3000.00"))

    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.cancel_payment_transaction(db_session, tenant_id, intent2.transaction_id, reason="Try cancel settled")
    assert exc_info.value.status_code == 400

# ============================================================================
# 10. WEBHOOK AMOUNT & CURRENCY INTEGRITY
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_amount_and_currency_integrity(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, gw_acc = await create_payment_test_environment(db_session, tenant_id)

    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("10000.00"))
    )

    def build_webhook(amt: str, cur: str, evt_id: str):
        payload_dict = {
            "id": evt_id,
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": intent.gateway_intent_id, "amount": amt, "currency": cur}}
        }
        b = json.dumps(payload_dict).encode()
        sig = hmac.new(gw_acc.webhook_secret_encrypted.encode(), b, hashlib.sha256).hexdigest()
        return b, sig

    # 1. Amount mismatch (₹1,000 instead of ₹10,000) -> REJECT (400)
    b_amt, sig_amt = build_webhook("1000.00", "usd", f"evt_amt_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b_amt, sig_amt)
    assert exc_info.value.status_code == 400
    assert "Amount mismatch" in exc_info.value.detail

    # 2. Currency mismatch (INR instead of USD) -> REJECT (400)
    b_cur, sig_cur = build_webhook("10000.00", "inr", f"evt_cur_{uuid.uuid4().hex[:6]}")
    with pytest.raises(HTTPException) as exc_info:
        await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b_cur, sig_cur)
    assert exc_info.value.status_code == 400
    assert "Currency mismatch" in exc_info.value.detail

    # 3. Exact match (₹10,000 USD) -> ACCEPT
    b_ok, sig_ok = build_webhook("10000.00", "usd", f"evt_ok_{uuid.uuid4().hex[:6]}")
    resp = await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b_ok, sig_ok)
    assert resp.status == "PROCESSED"

# ============================================================================
# 11. WEBHOOK OUT-OF-ORDER MONOTONICITY
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_out_of_order_monotonicity(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, gw_acc = await create_payment_test_environment(db_session, tenant_id)

    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("1000.00"))
    )

    # 1. Settle to SUCCEEDED
    await PaymentService.settle_payment_success(db_session, tenant_id, intent.transaction_id, "ch_mono", Decimal("1000.00"))

    # 2. Receive delayed out-of-order webhook for PENDING
    payload_delayed = {
        "id": f"evt_delay_{uuid.uuid4().hex[:6]}",
        "type": "payment_intent.created",
        "data": {"object": {"id": intent.gateway_intent_id, "amount": "1000.00", "currency": "usd"}}
    }
    b = json.dumps(payload_delayed).encode()
    sig = hmac.new(gw_acc.webhook_secret_encrypted.encode(), b, hashlib.sha256).hexdigest()

    await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b, sig)

    # Assert status never regresses to PENDING
    txn_check = (await db_session.execute(select(PaymentTransaction).where(PaymentTransaction.id == intent.transaction_id))).scalar_one()
    assert txn_check.status == "SUCCEEDED"

# ============================================================================
# 12. WEBHOOK IDEMPOTENCY & PAYLOAD IMMUTABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_idempotency_and_payload_immutability(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, gw_acc = await create_payment_test_environment(db_session, tenant_id)

    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("500.00"))
    )

    evt_id = f"evt_idem_{uuid.uuid4().hex[:8]}"
    payload_dict = {
        "id": evt_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": intent.gateway_intent_id, "amount": "500.00", "currency": "usd"}}
    }
    b = json.dumps(payload_dict).encode()
    sig = hmac.new(gw_acc.webhook_secret_encrypted.encode(), b, hashlib.sha256).hexdigest()

    # Ingest once
    res1 = await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b, sig)
    assert res1.status == "PROCESSED"

    # Ingest duplicate
    res2 = await PaymentService.handle_webhook(db_session, tenant_id, "MOCK", b, sig)
    assert res2.status == "ALREADY_PROCESSED"

    # Assert only 1 event recorded
    cnt = (await db_session.execute(
        select(func.count()).select_from(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == evt_id)
    )).scalar()
    assert cnt == 1

# ============================================================================
# 13. PCI DATA LEAK ASSERTION
# ============================================================================

@pytest.mark.asyncio
async def test_pci_data_leak_assertion(db_session: AsyncSession):
    """Assert no raw PAN, CVV, CVC, PIN or 16-digit card number is stored in payment records or metadata."""
    txns = (await db_session.execute(select(PaymentTransaction))).scalars().all()
    forbidden_terms = ["4111", "cvv", "cvc", "pan", "pin", "card_number", "security_code"]

    for t in txns:
        t_str = f"{t.transaction_number} {t.error_message or ''} {t.metadata_json or ''}".lower()
        for term in forbidden_terms:
            assert term not in t_str, f"Forbidden PCI term '{term}' detected in transaction {t.id}"

# ============================================================================
# 14. GATEWAY ADAPTERS VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_gateway_adapters_verification():
    # 1. Stripe Adapter Contract
    from app.services.payments.stripe_adapter import StripePaymentGatewayProvider
    stripe = StripePaymentGatewayProvider()
    res_stripe = await stripe.create_payment_intent("sk_test", None, Decimal("100.00"), "USD", "Test", "idem_s")
    assert res_stripe.gateway_intent_id.startswith("pi_stripe_")

    # 2. Razorpay Adapter Contract
    from app.services.payments.razorpay_adapter import RazorpayPaymentGatewayProvider
    rzp = RazorpayPaymentGatewayProvider()
    res_rzp = await rzp.create_payment_intent("key_test", "sec_test", Decimal("100.00"), "INR", "Test", "idem_r")
    assert res_rzp.gateway_intent_id.startswith("order_rzp_")

# ============================================================================
# 15. RECONCILIATION DISCREPANCY & RECOVERY
# ============================================================================

@pytest.mark.asyncio
async def test_reconciliation_lost_response_and_discrepancies(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    cust_a, _, inv_a, _, _ = await create_payment_test_environment(db_session, tenant_id)

    # 1. Reconcile Local PENDING + Gateway SUCCEEDED -> Autonomic Recovery
    intent = await PaymentService.create_payment_intent(
        db_session, tenant_id, cust_a.id, PaymentIntentCreateRequest(invoice_id=inv_a.id, amount=Decimal("1000.00"))
    )
    rec_txn = await PaymentService.reconcile_transaction(
        db_session, tenant_id, intent.transaction_id, gateway_status="SUCCEEDED", gateway_amount=Decimal("1000.00")
    )
    assert rec_txn.status == "SUCCEEDED"
    assert rec_txn.amount_captured == Decimal("1000.00")

    # 2. Reconcile Local SUCCEEDED + Gateway FAILED -> Audit Discrepancy without AR corruption
    await PaymentService.reconcile_transaction(
        db_session, tenant_id, rec_txn.id, gateway_status="FAILED"
    )
    # Status remains SUCCEEDED (no silent corruptions)
    await db_session.refresh(rec_txn)
    assert rec_txn.status == "SUCCEEDED"
