from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class VendorInvoice(Base, BaseModelMixin):
    __tablename__ = "vendor_invoices"

    tenant_id = Column(String(36), nullable=False, index=True)
    invoice_number = Column(String(50), unique=True, index=True, nullable=False) # Auto-generated INV-V-XXXX
    vendor_invoice_reference = Column(String(100), nullable=False, index=True) # Supplier's bill #
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    goods_receipt_id = Column(String(36), ForeignKey("goods_receipts.id"), nullable=True, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, MATCHED, EXCEPTION_HOLD, APPROVED, PARTIALLY_PAID, PAID, CANCELLED
    match_status = Column(String(30), default="UNMATCHED", nullable=False) # UNMATCHED, EXACT_MATCH, WITHIN_TOLERANCE, PRICE_VARIANCE_EXCEPTION, QUANTITY_VARIANCE_EXCEPTION
    subtotal_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    tax_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    amount_paid = Column(Numeric(18, 4), default=0.0, nullable=False)
    balance_due = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    invoice_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text, nullable=True)
    match_notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")
    goods_receipt = relationship("GoodsReceipt", lazy="selectin")
    lines = relationship("VendorInvoiceLine", back_populates="vendor_invoice", cascade="all, delete-orphan", lazy="selectin")
    allocations = relationship("VendorPaymentAllocation", back_populates="vendor_invoice", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "vendor_invoice_reference", name="uq_vendor_invoice_ref"),
        Index("idx_vendor_inv_tenant_status", "tenant_id", "status"),
        Index("idx_vendor_inv_due_date", "tenant_id", "due_date"),
    )

class VendorInvoiceLine(Base, BaseModelMixin):
    __tablename__ = "vendor_invoice_lines"

    vendor_invoice_id = Column(String(36), ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(36), ForeignKey("purchase_order_lines.id"), nullable=False)
    grn_line_id = Column(String(36), ForeignKey("goods_receipt_lines.id"), nullable=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    billed_quantity = Column(Numeric(18, 4), nullable=False)
    received_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    po_unit_price = Column(Numeric(18, 4), nullable=False)
    billed_unit_price = Column(Numeric(18, 4), nullable=False)
    price_variance_unit = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_price_variance = Column(Numeric(18, 4), default=0.0, nullable=False) # PPV
    tax_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    line_total = Column(Numeric(18, 4), nullable=False)

    vendor_invoice = relationship("VendorInvoice", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")

class VendorPayment(Base, BaseModelMixin):
    __tablename__ = "vendor_payments"

    tenant_id = Column(String(36), nullable=False, index=True)
    payment_number = Column(String(50), unique=True, index=True, nullable=False) # Auto-generated PAY-V-XXXX
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    payment_method = Column(String(30), default="BANK_TRANSFER", nullable=False) # BANK_TRANSFER, CHECK, CREDIT_CARD, CASH
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    payment_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    reference_number = Column(String(100), nullable=True) # Check # / Wire Ref
    status = Column(String(30), default="COMPLETED", nullable=False) # COMPLETED, VOIDED
    notes = Column(Text, nullable=True)
    disbursed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    supplier = relationship("Supplier", lazy="selectin")
    allocations = relationship("VendorPaymentAllocation", back_populates="vendor_payment", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_vendor_pay_tenant_date", "tenant_id", "payment_date"),
    )

class VendorPaymentAllocation(Base, BaseModelMixin):
    __tablename__ = "vendor_payment_allocations"

    vendor_payment_id = Column(String(36), ForeignKey("vendor_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_invoice_id = Column(String(36), ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_allocated = Column(Numeric(18, 4), nullable=False)
    allocated_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    vendor_payment = relationship("VendorPayment", back_populates="allocations")
    vendor_invoice = relationship("VendorInvoice", back_populates="allocations")

class APMatchingTolerance(Base, BaseModelMixin):
    __tablename__ = "ap_matching_tolerances"

    tenant_id = Column(String(36), nullable=False, unique=True, index=True)
    price_tolerance_pct = Column(Numeric(5, 2), default=2.0, nullable=False) # Default 2.0%
    price_tolerance_max_amount = Column(Numeric(18, 4), default=50.0, nullable=False) # Max absolute variance
    quantity_tolerance_pct = Column(Numeric(5, 2), default=0.0, nullable=False) # Default 0.0%
    auto_approve_within_tolerance = Column(Boolean, default=True, nullable=False)
