import hmac
import hashlib
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

class RazorpayPaymentGatewayProvider(PaymentGatewayProvider):
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
        order_id = f"order_rzp_{hashlib.md5(idempotency_key.encode()).hexdigest()[:16]}"
        return GatewayIntentResult(
            gateway_intent_id=order_id,
            client_secret=f"{order_id}_secret",
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
        return GatewayCaptureResult(
            gateway_charge_id=f"pay_rzp_{gateway_intent_id[10:]}",
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
        return GatewayRefundResult(
            gateway_refund_id=f"rfnd_rzp_{gateway_charge_id[8:]}",
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
        event_id = payload_dict.get("event_id", "evt_rzp")
        event_type = payload_dict.get("event", "payment.captured")
        payment_entity = payload_dict.get("payload", {}).get("payment", {}).get("entity", {})

        order_id = payment_entity.get("order_id")
        charge_id = payment_entity.get("id")
        amount_raw = payment_entity.get("amount")
        amount = Decimal(str(amount_raw)) / 100 if amount_raw is not None else None
        currency = payment_entity.get("currency", "INR").upper()

        status = "SUCCEEDED"
        if "failed" in event_type:
            status = "FAILED"
        elif "refund" in event_type:
            status = "REFUNDED"

        return GatewayWebhookEventData(
            event_id=event_id,
            event_type=event_type,
            gateway_intent_id=order_id,
            gateway_charge_id=charge_id,
            amount=amount,
            currency=currency,
            status=status
        )
