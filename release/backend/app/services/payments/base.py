from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel

class GatewayIntentResult(BaseModel):
    gateway_intent_id: str
    client_secret: Optional[str] = None
    status: str # PENDING, AUTHORIZED, SUCCEEDED
    amount: Decimal
    currency: str
    metadata: Optional[Dict[str, Any]] = None

class GatewayCaptureResult(BaseModel):
    gateway_charge_id: str
    status: str # CAPTURED, SUCCEEDED, FAILED
    amount_captured: Decimal
    currency: str

class GatewayCancelResult(BaseModel):
    status: str # CANCELLED, VOIDED
    message: Optional[str] = None

class GatewayRefundResult(BaseModel):
    gateway_refund_id: str
    status: str # SUCCEEDED, PENDING, FAILED
    amount_refunded: Decimal
    currency: str

class GatewayWebhookEventData(BaseModel):
    event_id: str
    event_type: str
    gateway_intent_id: Optional[str] = None
    gateway_charge_id: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    status: str # SUCCEEDED, FAILED, CANCELLED, REFUNDED
    refund_amount: Optional[Decimal] = None
    error_message: Optional[str] = None

class PaymentGatewayProvider(ABC):
    @abstractmethod
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
        pass

    @abstractmethod
    async def capture_payment(
        self,
        api_key: str,
        api_secret: Optional[str],
        gateway_intent_id: str,
        amount: Decimal,
        currency: str
    ) -> GatewayCaptureResult:
        pass

    @abstractmethod
    async def cancel_payment(
        self,
        api_key: str,
        api_secret: Optional[str],
        gateway_intent_id: str,
        reason: str
    ) -> GatewayCancelResult:
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        webhook_secret: str,
        payload_bytes: bytes,
        signature_header: str
    ) -> bool:
        pass

    @abstractmethod
    def parse_webhook_event(
        self,
        payload_dict: Dict[str, Any]
    ) -> GatewayWebhookEventData:
        pass
