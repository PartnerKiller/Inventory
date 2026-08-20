import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class PaymentGatewayAccount(Base, BaseModelMixin):
    __tablename__ = "payment_gateway_accounts"

    tenant_id = Column(String(36), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False) # STRIPE, RAZORPAY, MOCK
    name = Column(String(100), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    api_secret_encrypted = Column(Text, nullable=True)
    webhook_secret_encrypted = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_test_mode = Column(Boolean, default=True, nullable=False)
    supported_currencies = Column(JSON, default=["USD", "INR", "EUR"], nullable=False)
    supported_methods = Column(JSON, default=["CARD", "BANK_TRANSFER", "UPI"], nullable=False)
    settings_json = Column(JSON, nullable=True)

    transactions = relationship("PaymentTransaction", back_populates="gateway_account", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_gateway_tenant_provider", "tenant_id", "provider_code"),
    )

class PaymentTransaction(Base, BaseModelMixin):
    __tablename__ = "payment_transactions"

    tenant_id = Column(String(36), nullable=False, index=True)
    transaction_number = Column(String(50), unique=True, index=True, nullable=False) # TXN-YYYYMMDD-XXXX
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    invoice_id = Column(String(36), ForeignKey("customer_invoices.id"), nullable=False, index=True)
    gateway_account_id = Column(String(36), ForeignKey("payment_gateway_accounts.id"), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False)
    
    # Gateway Identifiers
    gateway_intent_id = Column(String(100), unique=True, index=True, nullable=True)
    gateway_charge_id = Column(String(100), index=True, nullable=True)
    
    amount = Column(Numeric(18, 4), nullable=False)
    amount_captured = Column(Numeric(18, 4), default=0.0, nullable=False)
    amount_refunded = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    
    status = Column(String(30), default="CREATED", nullable=False, index=True) # CREATED, PENDING, AUTHORIZED, CAPTURED, SUCCEEDED, FAILED, CANCELLED, PARTIALLY_REFUNDED, REFUNDED
    payment_method_type = Column(String(50), default="CARD", nullable=False)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
    
    client_secret = Column(String(255), nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    customer = relationship("Customer", lazy="selectin")
    invoice = relationship("CustomerInvoice", lazy="selectin")
    gateway_account = relationship("PaymentGatewayAccount", back_populates="transactions", lazy="selectin")
    refunds = relationship("PaymentTransactionRefund", back_populates="transaction", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_payment_tenant_invoice", "tenant_id", "invoice_id"),
        Index("idx_payment_tenant_status", "tenant_id", "status"),
    )

class PaymentTransactionRefund(Base, BaseModelMixin):
    __tablename__ = "payment_transaction_refunds"

    tenant_id = Column(String(36), nullable=False, index=True)
    refund_number = Column(String(50), unique=True, index=True, nullable=False) # REF-YYYYMMDD-XXXX
    transaction_id = Column(String(36), ForeignKey("payment_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    gateway_refund_id = Column(String(100), index=True, nullable=True)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    reason = Column(String(255), nullable=True)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, SUCCEEDED, FAILED
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
    
    transaction = relationship("PaymentTransaction", back_populates="refunds")

class PaymentWebhookEvent(Base, BaseModelMixin):
    __tablename__ = "payment_webhook_events"

    tenant_id = Column(String(36), nullable=False, index=True)
    gateway_account_id = Column(String(36), ForeignKey("payment_gateway_accounts.id"), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False)
    event_id = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(JSON, nullable=False)
    signature = Column(String(255), nullable=False)
    status = Column(String(30), default="RECEIVED", nullable=False) # RECEIVED, PROCESSED, IGNORED, FAILED
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_code", "event_id", name="uq_payment_webhook_event"),
    )
