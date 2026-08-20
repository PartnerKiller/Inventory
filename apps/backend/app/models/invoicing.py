from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class CustomerInvoice(Base, BaseModelMixin):
    __tablename__ = "customer_invoices"

    tenant_id = Column(String(36), nullable=False, index=True)
    invoice_number = Column(String(50), unique=True, index=True, nullable=False)
    sales_order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, ISSUED, PARTIALLY_PAID, PAID, CANCELLED, OVERDUE
    subtotal_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    tax_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    amount_paid = Column(Numeric(18, 4), default=0.0, nullable=False)
    balance_due = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    issue_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text, nullable=True)
    issued_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    customer = relationship("Customer", lazy="selectin")
    sales_order = relationship("SalesOrder", lazy="selectin")
    lines = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin")
    allocations = relationship("PaymentAllocation", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin")
    credit_notes = relationship("CustomerCreditNote", back_populates="invoice", lazy="selectin")

    __table_args__ = (
        Index("idx_invoice_tenant_status", "tenant_id", "status"),
        Index("idx_invoice_due_date", "tenant_id", "due_date"),
    )

class InvoiceLineItem(Base, BaseModelMixin):
    __tablename__ = "invoice_lines"

    invoice_id = Column(String(36), ForeignKey("customer_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    so_line_id = Column(String(36), ForeignKey("sales_order_lines.id", ondelete="SET NULL"), nullable=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit_price = Column(Numeric(18, 4), nullable=False)
    discount_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    tax_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    line_total = Column(Numeric(18, 4), nullable=False)

    invoice = relationship("CustomerInvoice", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")

class CustomerPayment(Base, BaseModelMixin):
    __tablename__ = "customer_payments"

    tenant_id = Column(String(36), nullable=False, index=True)
    payment_number = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    payment_method = Column(String(30), default="BANK_TRANSFER", nullable=False) # CASH, BANK_TRANSFER, CREDIT_CARD, CHECK
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    payment_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    reference_number = Column(String(100), nullable=True) # e.g. Check #, Wire Ref
    status = Column(String(30), default="COMPLETED", nullable=False) # COMPLETED, VOIDED
    notes = Column(Text, nullable=True)
    received_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    customer = relationship("Customer", lazy="selectin")
    allocations = relationship("PaymentAllocation", back_populates="payment", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_payment_tenant_date", "tenant_id", "payment_date"),
    )

class PaymentAllocation(Base, BaseModelMixin):
    __tablename__ = "payment_allocations"

    payment_id = Column(String(36), ForeignKey("customer_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(String(36), ForeignKey("customer_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_allocated = Column(Numeric(18, 4), nullable=False)
    allocated_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    payment = relationship("CustomerPayment", back_populates="allocations")
    invoice = relationship("CustomerInvoice", back_populates="allocations")

class CustomerCreditNote(Base, BaseModelMixin):
    __tablename__ = "customer_credit_notes"

    tenant_id = Column(String(36), nullable=False, index=True)
    credit_note_number = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    sales_return_id = Column(String(36), ForeignKey("sales_returns.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_id = Column(String(36), ForeignKey("customer_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    amount = Column(Numeric(18, 4), nullable=False)
    status = Column(String(30), default="ISSUED", nullable=False) # ISSUED, APPLIED, VOIDED
    issue_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    customer = relationship("Customer", lazy="selectin")
    sales_return = relationship("SalesReturn", lazy="selectin")
    invoice = relationship("CustomerInvoice", back_populates="credit_notes")
