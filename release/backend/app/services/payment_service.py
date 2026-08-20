import uuid
import json
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.sales import Customer
from app.models.invoicing import CustomerInvoice, CustomerPayment, PaymentAllocation, CustomerCreditNote
from app.models.payment_gateway import (
    PaymentGatewayAccount,
    PaymentTransaction,
    PaymentTransactionRefund,
    PaymentWebhookEvent
)
from app.schemas.payment_gateway import (
    PaymentIntentCreateRequest,
    PaymentIntentResponse,
    PaymentRefundRequest,
    PaymentRefundResponse,
    PaymentTransactionResponse,
    WebhookIngestResponse
)
from app.services.payments.base import PaymentGatewayProvider
from app.services.payments.mock_provider import MockPaymentGatewayProvider
from app.services.payments.stripe_adapter import StripePaymentGatewayProvider
from app.services.payments.razorpay_adapter import RazorpayPaymentGatewayProvider
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService

PROVIDERS: Dict[str, PaymentGatewayProvider] = {
    "MOCK": MockPaymentGatewayProvider(),
    "STRIPE": StripePaymentGatewayProvider(),
    "RAZORPAY": RazorpayPaymentGatewayProvider()
}

class PaymentService:
    @staticmethod
    def get_provider(provider_code: str) -> PaymentGatewayProvider:
        code = provider_code.upper()
        if code not in PROVIDERS:
            return PROVIDERS["MOCK"]
        return PROVIDERS[code]

    @staticmethod
    async def get_or_create_gateway_account(
        db: AsyncSession,
        tenant_id: str,
        provider_code: str = "MOCK"
    ) -> PaymentGatewayAccount:
        stmt = select(PaymentGatewayAccount).where(
            PaymentGatewayAccount.tenant_id == tenant_id,
            PaymentGatewayAccount.provider_code == provider_code.upper(),
            PaymentGatewayAccount.is_active == True
        )
        account = (await db.execute(stmt)).scalars().first()
        if not account:
            account = PaymentGatewayAccount(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                provider_code=provider_code.upper(),
                name=f"Primary {provider_code.title()} Gateway",
                api_key_encrypted=f"key_{provider_code.lower()}_{uuid.uuid4().hex[:12]}",
                webhook_secret_encrypted=f"whsec_{uuid.uuid4().hex[:16]}",
                is_active=True,
                is_test_mode=True,
                supported_currencies=["USD", "INR", "EUR"],
                supported_methods=["CARD", "BANK_TRANSFER", "UPI"]
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)
        return account

    @staticmethod
    async def create_payment_intent(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        req: PaymentIntentCreateRequest,
        provider_code: str = "MOCK",
        user_id: Optional[str] = None
    ) -> PaymentIntentResponse:
        idempotency_key = req.idempotency_key or f"idem_{uuid.uuid4().hex}"

        # Idempotency check: if intent already exists for this idempotency_key, return it
        existing_txn = (await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.tenant_id == tenant_id,
                PaymentTransaction.idempotency_key == idempotency_key
            )
        )).scalar_one_or_none()
        if existing_txn:
            return PaymentIntentResponse(
                transaction_id=existing_txn.id,
                transaction_number=existing_txn.transaction_number,
                invoice_id=existing_txn.invoice_id,
                amount=float(existing_txn.amount),
                currency=existing_txn.currency,
                status=existing_txn.status,
                provider_code=existing_txn.provider_code,
                gateway_intent_id=existing_txn.gateway_intent_id,
                client_secret=existing_txn.client_secret,
                idempotency_key=existing_txn.idempotency_key
            )

        invoice = (await db.execute(
            select(CustomerInvoice).where(
                CustomerInvoice.id == req.invoice_id,
                CustomerInvoice.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not invoice:
            raise HTTPException(status_code=404, detail="Customer invoice not found")

        if invoice.customer_id != customer_id:
            raise HTTPException(status_code=403, detail="Cross-customer payment forbidden: invoice belongs to another customer")

        if invoice.status in ["PAID", "CANCELLED"]:
            raise HTTPException(status_code=400, detail=f"Invoice is in '{invoice.status}' status and cannot accept payment")

        charge_amount = req.amount if req.amount is not None else invoice.balance_due
        if charge_amount <= Decimal("0.0"):
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

        if charge_amount > invoice.balance_due:
            raise HTTPException(status_code=400, detail=f"Payment amount ({charge_amount}) exceeds outstanding balance ({invoice.balance_due})")

        gateway_acc = await PaymentService.get_or_create_gateway_account(db, tenant_id, provider_code)
        provider = PaymentService.get_provider(gateway_acc.provider_code)

        txn_number = await SequenceService.generate_next_number(db, tenant_id, "PAYMENT_TXN", custom_prefix="TXN")

        intent_res = await provider.create_payment_intent(
            api_key=gateway_acc.api_key_encrypted,
            api_secret=gateway_acc.api_secret_encrypted,
            amount=charge_amount,
            currency=invoice.currency,
            description=f"Payment for invoice {invoice.invoice_number}",
            idempotency_key=idempotency_key,
            metadata={"invoice_id": invoice.id, "customer_id": customer_id, "txn_number": txn_number}
        )

        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transaction_number=txn_number,
            customer_id=customer_id,
            invoice_id=invoice.id,
            gateway_account_id=gateway_acc.id,
            provider_code=gateway_acc.provider_code,
            gateway_intent_id=intent_res.gateway_intent_id,
            amount=charge_amount,
            currency=invoice.currency,
            status=intent_res.status,
            payment_method_type=req.payment_method_type,
            idempotency_key=idempotency_key,
            client_secret=intent_res.client_secret
        )
        db.add(txn)
        await db.commit()
        await db.refresh(txn)

        return PaymentIntentResponse(
            transaction_id=txn.id,
            transaction_number=txn.transaction_number,
            invoice_id=txn.invoice_id,
            amount=float(txn.amount),
            currency=txn.currency,
            status=txn.status,
            provider_code=txn.provider_code,
            gateway_intent_id=txn.gateway_intent_id,
            client_secret=txn.client_secret,
            idempotency_key=txn.idempotency_key
        )

    @staticmethod
    async def settle_payment_success(
        db: AsyncSession,
        tenant_id: str,
        transaction_id: str,
        gateway_charge_id: str,
        amount_captured: Decimal,
        user_id: Optional[str] = None
    ) -> PaymentTransaction:
        txn = (await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not txn:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        # Monotonicity: if already succeeded, do not duplicate AR records
        if txn.status == "SUCCEEDED":
            return txn

        invoice = (await db.execute(
            select(CustomerInvoice).where(
                CustomerInvoice.id == txn.invoice_id,
                CustomerInvoice.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Associated customer invoice not found")

        # Create authoritative CustomerPayment in AR ledger
        pmt_num = await SequenceService.generate_next_number(db, tenant_id, "CUSTOMER_PAYMENT", custom_prefix="PAY")
        pmt = CustomerPayment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            payment_number=pmt_num,
            customer_id=txn.customer_id,
            payment_method="CREDIT_CARD" if txn.payment_method_type == "CARD" else txn.payment_method_type,
            amount=amount_captured,
            currency=txn.currency,
            reference_number=txn.transaction_number,
            status="COMPLETED",
            notes=f"Settled via {txn.provider_code} gateway (Charge ID: {gateway_charge_id})"
        )
        db.add(pmt)
        await db.flush()

        alloc = PaymentAllocation(
            id=str(uuid.uuid4()),
            payment_id=pmt.id,
            invoice_id=invoice.id,
            amount_allocated=amount_captured
        )
        db.add(alloc)

        # Update invoice balance
        invoice.amount_paid = (invoice.amount_paid + amount_captured).quantize(Decimal("0.0001"))
        invoice.balance_due = max(Decimal("0.0"), (invoice.total_amount - invoice.amount_paid).quantize(Decimal("0.0001")))
        if invoice.balance_due <= Decimal("0.0"):
            invoice.status = "PAID"
        else:
            invoice.status = "PARTIALLY_PAID"

        # Update customer credit exposure
        cust = (await db.execute(select(Customer).where(Customer.id == txn.customer_id))).scalar_one_or_none()
        if cust:
            cust.current_credit_exposure = max(Decimal("0.0"), cust.current_credit_exposure - amount_captured)

        # Update transaction status
        txn.status = "SUCCEEDED"
        txn.amount_captured = amount_captured
        txn.gateway_charge_id = gateway_charge_id

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PAYMENT_SETTLED",
            entity_type="PaymentTransaction",
            entity_id=txn.id,
            user_id=user_id,
            changes={
                "transaction_number": txn.transaction_number,
                "amount_captured": float(amount_captured),
                "invoice_balance_due": float(invoice.balance_due),
                "invoice_status": invoice.status
            }
        )

        await db.commit()
        await db.refresh(txn)
        return txn

    @staticmethod
    async def process_refund(
        db: AsyncSession,
        tenant_id: str,
        transaction_id: str,
        req: PaymentRefundRequest,
        user_id: Optional[str] = None
    ) -> PaymentRefundResponse:
        txn = (await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not txn:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        if txn.status not in ["SUCCEEDED", "PARTIALLY_REFUNDED"]:
            raise HTTPException(status_code=400, detail=f"Cannot refund transaction in '{txn.status}' status")

        available_to_refund = txn.amount_captured - txn.amount_refunded
        if req.amount <= Decimal("0.0"):
            raise HTTPException(status_code=400, detail="Refund amount must be greater than zero")

        if req.amount > available_to_refund:
            raise HTTPException(status_code=400, detail=f"Refund amount ({req.amount}) exceeds available captured amount ({available_to_refund})")

        idempotency_key = req.idempotency_key or f"ref_idem_{uuid.uuid4().hex}"

        # Refund Idempotency: Return existing refund if idempotency_key matches
        existing_refund = (await db.execute(
            select(PaymentTransactionRefund).where(
                PaymentTransactionRefund.tenant_id == tenant_id,
                PaymentTransactionRefund.idempotency_key == idempotency_key
            )
        )).scalar_one_or_none()
        if existing_refund:
            return PaymentRefundResponse(
                refund_id=existing_refund.id,
                refund_number=existing_refund.refund_number,
                transaction_id=existing_refund.transaction_id,
                amount=float(existing_refund.amount),
                currency=existing_refund.currency,
                status=existing_refund.status,
                reason=existing_refund.reason,
                created_at=existing_refund.created_at
            )

        gateway_acc = (await db.execute(
            select(PaymentGatewayAccount).where(PaymentGatewayAccount.id == txn.gateway_account_id)
        )).scalar_one()
        provider = PaymentService.get_provider(gateway_acc.provider_code)

        refund_res = await provider.process_refund(
            api_key=gateway_acc.api_key_encrypted,
            api_secret=gateway_acc.api_secret_encrypted,
            gateway_charge_id=txn.gateway_charge_id or txn.gateway_intent_id or "ch_default",
            amount=req.amount,
            currency=txn.currency,
            reason=req.reason,
            idempotency_key=idempotency_key
        )

        ref_num = await SequenceService.generate_next_number(db, tenant_id, "REFUND", custom_prefix="REF")
        refund = PaymentTransactionRefund(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            refund_number=ref_num,
            transaction_id=txn.id,
            gateway_refund_id=refund_res.gateway_refund_id,
            amount=req.amount,
            currency=txn.currency,
            reason=req.reason,
            status=refund_res.status,
            idempotency_key=idempotency_key
        )
        db.add(refund)

        # Update transaction refunded total
        txn.amount_refunded = (txn.amount_refunded + req.amount).quantize(Decimal("0.0001"))
        if txn.amount_refunded >= txn.amount_captured:
            txn.status = "REFUNDED"
        else:
            txn.status = "PARTIALLY_REFUNDED"

        # Reopen invoice balance symmetrically
        invoice = (await db.execute(
            select(CustomerInvoice).where(CustomerInvoice.id == txn.invoice_id).with_for_update()
        )).scalar_one_or_none()

        if invoice:
            invoice.amount_paid = max(Decimal("0.0"), (invoice.amount_paid - req.amount).quantize(Decimal("0.0001")))
            invoice.balance_due = (invoice.total_amount - invoice.amount_paid).quantize(Decimal("0.0001"))
            if invoice.amount_paid <= Decimal("0.0"):
                invoice.status = "ISSUED"
            else:
                invoice.status = "PARTIALLY_PAID"

        # Restore customer credit exposure
        cust = (await db.execute(select(Customer).where(Customer.id == txn.customer_id))).scalar_one_or_none()
        if cust:
            cust.current_credit_exposure = cust.current_credit_exposure + req.amount

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PAYMENT_REFUNDED",
            entity_type="PaymentTransactionRefund",
            entity_id=refund.id,
            user_id=user_id,
            changes={
                "refund_number": refund.refund_number,
                "amount": float(req.amount),
                "transaction_status": txn.status,
                "invoice_balance_due": float(invoice.balance_due) if invoice else 0.0
            }
        )

        await db.commit()
        await db.refresh(refund)

        return PaymentRefundResponse(
            refund_id=refund.id,
            refund_number=refund.refund_number,
            transaction_id=refund.transaction_id,
            amount=float(refund.amount),
            currency=refund.currency,
            status=refund.status,
            reason=refund.reason,
            created_at=refund.created_at
        )

    @staticmethod
    async def cancel_payment_transaction(
        db: AsyncSession,
        tenant_id: str,
        transaction_id: str,
        reason: str = "User cancelled checkout",
        user_id: Optional[str] = None
    ) -> PaymentTransaction:
        txn = (await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not txn:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        if txn.status in ["SUCCEEDED", "CAPTURED", "REFUNDED", "PARTIALLY_REFUNDED"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel payment transaction in '{txn.status}' status")

        if txn.status == "CANCELLED":
            return txn

        gateway_acc = (await db.execute(
            select(PaymentGatewayAccount).where(PaymentGatewayAccount.id == txn.gateway_account_id)
        )).scalar_one()
        provider = PaymentService.get_provider(gateway_acc.provider_code)

        if txn.gateway_intent_id:
            await provider.cancel_payment(
                api_key=gateway_acc.api_key_encrypted,
                api_secret=gateway_acc.api_secret_encrypted,
                gateway_intent_id=txn.gateway_intent_id,
                reason=reason
            )

        txn.status = "CANCELLED"
        txn.error_message = reason

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PAYMENT_CANCELLED",
            entity_type="PaymentTransaction",
            entity_id=txn.id,
            user_id=user_id,
            changes={"status": "CANCELLED", "reason": reason}
        )

        await db.commit()
        await db.refresh(txn)
        return txn

    @staticmethod
    async def reconcile_transaction(
        db: AsyncSession,
        tenant_id: str,
        transaction_id: str,
        gateway_status: str,
        gateway_charge_id: Optional[str] = None,
        gateway_amount: Optional[Decimal] = None
    ) -> PaymentTransaction:
        txn = (await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not txn:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        if gateway_status == "SUCCEEDED" and txn.status in ["PENDING", "AUTHORIZED", "CAPTURED"]:
            return await PaymentService.settle_payment_success(
                db=db,
                tenant_id=tenant_id,
                transaction_id=txn.id,
                gateway_charge_id=gateway_charge_id or f"ch_recon_{uuid.uuid4().hex[:8]}",
                amount_captured=gateway_amount or txn.amount
            )

        if gateway_status == "FAILED" and txn.status == "SUCCEEDED":
            await AuditService.log_action(
                db=db,
                tenant_id=tenant_id,
                action="RECONCILIATION_DISCREPANCY",
                entity_type="PaymentTransaction",
                entity_id=txn.id,
                changes={"local_status": txn.status, "gateway_status": gateway_status}
            )
            await db.commit()

        return txn

    @staticmethod
    async def handle_webhook(
        db: AsyncSession,
        tenant_id: str,
        provider_code: str,
        payload_bytes: bytes,
        signature_header: str
    ) -> WebhookIngestResponse:
        gateway_acc = await PaymentService.get_or_create_gateway_account(db, tenant_id, provider_code)
        provider = PaymentService.get_provider(gateway_acc.provider_code)

        if not provider.verify_webhook_signature(gateway_acc.webhook_secret_encrypted or "", payload_bytes, signature_header):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

        try:
            payload_dict = json.loads(payload_bytes.decode())
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed JSON webhook payload")

        event_data = provider.parse_webhook_event(payload_dict)

        # Idempotency check: uq_payment_webhook_event
        existing_evt = (await db.execute(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.tenant_id == tenant_id,
                PaymentWebhookEvent.provider_code == provider_code.upper(),
                PaymentWebhookEvent.event_id == event_data.event_id
            )
        )).scalar_one_or_none()

        if existing_evt:
            return WebhookIngestResponse(
                status="ALREADY_PROCESSED",
                event_id=event_data.event_id,
                processed=True,
                message="Duplicate webhook event ignored"
            )

        webhook_log = PaymentWebhookEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            gateway_account_id=gateway_acc.id,
            provider_code=provider_code.upper(),
            event_id=event_data.event_id,
            event_type=event_data.event_type,
            payload_json=payload_dict,
            signature=signature_header,
            status="RECEIVED"
        )
        db.add(webhook_log)
        await db.flush()

        # Find matching payment transaction
        txn = None
        if event_data.gateway_intent_id:
            txn = (await db.execute(
                select(PaymentTransaction).where(
                    PaymentTransaction.tenant_id == tenant_id,
                    PaymentTransaction.gateway_intent_id == event_data.gateway_intent_id
                )
            )).scalar_one_or_none()

        if txn:
            # Currency Integrity
            if event_data.currency and event_data.currency.upper() != txn.currency.upper():
                webhook_log.status = "FAILED"
                webhook_log.error_message = f"Currency mismatch: expected {txn.currency}, got {event_data.currency}"
                await db.commit()
                raise HTTPException(status_code=400, detail=webhook_log.error_message)

            # Amount Integrity
            if event_data.amount is not None and event_data.amount != txn.amount:
                webhook_log.status = "FAILED"
                webhook_log.error_message = f"Amount mismatch: expected {txn.amount}, got {event_data.amount}"
                await db.commit()
                raise HTTPException(status_code=400, detail=webhook_log.error_message)

            # Monotonic State Transition
            if event_data.status == "SUCCEEDED":
                if txn.status != "REFUNDED":
                    await PaymentService.settle_payment_success(
                        db=db,
                        tenant_id=tenant_id,
                        transaction_id=txn.id,
                        gateway_charge_id=event_data.gateway_charge_id or "ch_wh_confirmed",
                        amount_captured=event_data.amount or txn.amount
                    )
            elif event_data.status == "FAILED" and txn.status not in ["SUCCEEDED", "REFUNDED", "PARTIALLY_REFUNDED"]:
                txn.status = "FAILED"
                txn.error_message = event_data.error_message or "Payment failed at gateway"
                await db.commit()

        webhook_log.status = "PROCESSED"
        await db.commit()

        return WebhookIngestResponse(
            status="PROCESSED",
            event_id=event_data.event_id,
            processed=True,
            message="Webhook event processed successfully"
        )
