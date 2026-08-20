import hmac
import hashlib
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional
from app.services.payments.base import (
    PaymentGatewayProvider,
    GatewayIntentResult,
    GatewayCaptureResult,
    GatewayCancelResult,
    GatewayRefundResult,
    GatewayWebhookEventData
)

class MockPaymentGatewayProvider(PaymentGatewayProvider):
    async def create_payment_intent(
        self,
        api_key: str,
        api_secret: Optional[str],
        amount: Decimal,
        currency: str,
        description: str,
        idempotency_key: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> GatewayIntentResult:
        intent_id = f"pi_mock_{hashlib.md5(idempotency_key.encode()).hexdigest()[:16]}"
        client_secret = f"{intent_id}_secret_{uuid.uuid4().hex[:12]}"
        return GatewayIntentResult(
            gateway_intent_id=intent_id,
            client_secret=client_secret,
            status="PENDING",
            amount=amount,
            currency=currency,
            metadata=metadata
        )

    async def capture_payment(
        self,
        api_key: str,
        api_secret: Optional[str],
        gateway_intent_id: str,
        amount: Decimal,
        currency: str
    ) -> GatewayCaptureResult:
        charge_id = f"ch_mock_{gateway_intent_id[8:]}"
        return GatewayCaptureResult(
            gateway_charge_id=charge_id,
            status="SUCCEEDED",
            amount_captured=amount,
            currency=currency
        )

    async def cancel_payment(
        self,
        api_key: str,
        api_secret: Optional[str],
        gateway_intent_id: str,
        reason: str
    ) -> GatewayCancelResult:
        return GatewayCancelResult(
            status="CANCELLED",
            message=reason
        )

    async def process_refund(
        self,
        api_key: str,
        api_secret: Optional[str],
        gateway_charge_id: str,
        amount: Decimal,
        currency: str,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None
    ) -> GatewayRefundResult:
        ref_id = f"re_mock_{uuid.uuid4().hex[:16]}"
        return GatewayRefundResult(
            gateway_refund_id=ref_id,
            status="SUCCEEDED",
            amount_refunded=amount,
            currency=currency
        )

    def verify_webhook_signature(
        self,
        webhook_secret: str,
        payload_bytes: bytes,
        signature_header: str
    ) -> bool:
        if not signature_header or not webhook_secret:
            return False
        expected_sig = hmac.new(webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signature_header)

    def parse_webhook_event(
        self,
        payload_dict: Dict[str, Any]
    ) -> GatewayWebhookEventData:
        event_id = payload_dict.get("id", str(uuid.uuid4()))
        event_type = payload_dict.get("type", "payment_intent.succeeded")
        data_obj = payload_dict.get("data", {}).get("object", {})

        intent_id = data_obj.get("id")
        charge_id = data_obj.get("latest_charge")
        amount_raw = data_obj.get("amount")
        amount = Decimal(str(amount_raw)) if amount_raw is not None else None
        currency = data_obj.get("currency", "usd").upper()

        status = "SUCCEEDED"
        if event_type in ["payment_intent.payment_failed", "payment.failed"]:
            status = "FAILED"
        elif event_type in ["payment_intent.canceled", "payment.canceled"]:
            status = "CANCELLED"
        elif event_type in ["charge.refunded", "payment.refunded"]:
            status = "REFUNDED"

        return GatewayWebhookEventData(
            event_id=event_id,
            event_type=event_type,
            gateway_intent_id=intent_id,
            gateway_charge_id=charge_id,
            amount=amount,
            currency=currency,
            status=status,
            error_message=data_obj.get("last_payment_error", {}).get("message")
        )
