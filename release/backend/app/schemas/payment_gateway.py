from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# ============================================================================
# GATEWAY ACCOUNT SCHEMAS
# ============================================================================

class PaymentGatewayAccountCreate(BaseModel):
    provider_code: str # STRIPE, RAZORPAY, MOCK
    name: str
    api_key: str
    api_secret: Optional[str] = None
    webhook_secret: Optional[str] = None
    is_test_mode: bool = True
    supported_currencies: Optional[List[str]] = ["USD", "INR", "EUR"]
    supported_methods: Optional[List[str]] = ["CARD", "BANK_TRANSFER", "UPI"]
    settings_json: Optional[Dict[str, Any]] = None

class PaymentGatewayAccountResponse(BaseModel):
    id: str
    provider_code: str
    name: str
    is_active: bool
    is_test_mode: bool
    supported_currencies: List[str]
    supported_methods: List[str]

# ============================================================================
# PAYMENT TRANSACTION SCHEMAS
# ============================================================================

class PaymentIntentCreateRequest(BaseModel):
    invoice_id: str
    amount: Optional[Decimal] = None # If None, defaults to invoice balance_due
    payment_method_type: str = "CARD" # CARD, UPI, BANK_TRANSFER
    idempotency_key: Optional[str] = None

class PaymentIntentResponse(BaseModel):
    transaction_id: str
    transaction_number: str
    invoice_id: str
    amount: float
    currency: str
    status: str
    provider_code: str
    gateway_intent_id: Optional[str] = None
    client_secret: Optional[str] = None
    idempotency_key: str

class PaymentCaptureRequest(BaseModel):
    amount: Optional[Decimal] = None

class PaymentRefundRequest(BaseModel):
    amount: Decimal
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None

class PaymentRefundResponse(BaseModel):
    refund_id: str
    refund_number: str
    transaction_id: str
    amount: float
    currency: str
    status: str
    reason: Optional[str] = None
    created_at: datetime

class PaymentTransactionResponse(BaseModel):
    id: str
    transaction_number: str
    customer_id: str
    invoice_id: str
    provider_code: str
    gateway_intent_id: Optional[str] = None
    gateway_charge_id: Optional[str] = None
    amount: float
    amount_captured: float
    amount_refunded: float
    currency: str
    status: str
    payment_method_type: str
    created_at: datetime
    refunds: List[PaymentRefundResponse] = []

class WebhookIngestResponse(BaseModel):
    status: str
    event_id: str
    processed: bool
    message: Optional[str] = None
