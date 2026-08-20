import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class Supplier(Base, BaseModelMixin):
    __tablename__ = "suppliers"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(JSON, nullable=True)
    tax_identifier = Column(String(50), nullable=True) # GSTIN, VAT, EIN
    payment_terms = Column(String(100), default="Net 30", nullable=True)
    credit_limit = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False) # ACTIVE, ON_HOLD, INACTIVE
    is_active = Column(Boolean, default=True, nullable=False)

    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")
    contacts = relationship("SupplierContact", back_populates="supplier", cascade="all, delete-orphan", lazy="selectin")
    addresses = relationship("SupplierAddress", back_populates="supplier", cascade="all, delete-orphan", lazy="selectin")
    products = relationship("SupplierProduct", back_populates="supplier", cascade="all, delete-orphan", lazy="selectin")
    returns = relationship("SupplierReturn", back_populates="supplier", lazy="selectin")
    debit_memos = relationship("SupplierDebitMemo", back_populates="supplier", lazy="selectin")

class SupplierContact(Base, BaseModelMixin):
    __tablename__ = "supplier_contacts"

    tenant_id = Column(String(36), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    designation = Column(String(100), nullable=True) # Sales Rep, Account Manager, Logistics
    is_primary = Column(Boolean, default=False, nullable=False)

    supplier = relationship("Supplier", back_populates="contacts")

class SupplierAddress(Base, BaseModelMixin):
    __tablename__ = "supplier_addresses"

    tenant_id = Column(String(36), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    address_type = Column(String(30), default="ORDERING", nullable=False) # ORDERING, REMITTANCE, SHIPPING_ORIGIN
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(100), default="US", nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    supplier = relationship("Supplier", back_populates="addresses")

class SupplierProduct(Base, BaseModelMixin):
    __tablename__ = "supplier_products"

    tenant_id = Column(String(36), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_sku = Column(String(100), nullable=True)
    supplier_product_name = Column(String(255), nullable=True)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    minimum_order_quantity = Column(Numeric(18, 4), default=1.0, nullable=False)
    pack_size = Column(Numeric(18, 4), default=1.0, nullable=False)
    lead_time_days = Column(Integer, default=14, nullable=False)
    is_preferred = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Supplier", back_populates="products", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    price_histories = relationship("SupplierPriceHistory", back_populates="supplier_product", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "item_variant_id", name="uq_tenant_supplier_variant"),
        CheckConstraint("minimum_order_quantity > 0", name="chk_supp_prod_moq_pos"),
        CheckConstraint("pack_size > 0", name="chk_supp_prod_pack_pos"),
        CheckConstraint("lead_time_days >= 0", name="chk_supp_prod_lead_non_neg"),
    )

class SupplierPriceHistory(Base, BaseModelMixin):
    __tablename__ = "supplier_price_histories"

    tenant_id = Column(String(36), nullable=False, index=True)
    supplier_product_id = Column(String(36), ForeignKey("supplier_products.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_price = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    effective_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    source_document_type = Column(String(30), default="MANUAL_UPDATE", nullable=False) # MANUAL_UPDATE, PURCHASE_ORDER, GOODS_RECEIPT
    source_document_id = Column(String(36), nullable=True)
    change_reason = Column(String(255), nullable=True)
    recorded_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    supplier_product = relationship("SupplierProduct", back_populates="price_histories")

class PurchaseOrder(Base, BaseModelMixin):
    __tablename__ = "purchase_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    po_number = Column(String(50), unique=True, index=True, nullable=False)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    target_warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, PENDING_APPROVAL, APPROVED, PARTIALLY_RECEIVED, COMPLETED, CANCELLED
    subtotal_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    tax_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    freight_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    customs_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    exchange_rate_to_base = Column(Numeric(18, 6), default=1.0, nullable=False)
    ordered_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    expected_delivery_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(String(255), nullable=True)

    supplier = relationship("Supplier", back_populates="purchase_orders", lazy="selectin")
    target_warehouse = relationship("Warehouse", lazy="selectin")
    lines = relationship("POLineItem", back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin")
    receipts = relationship("GoodsReceipt", back_populates="purchase_order", lazy="selectin")
    returns = relationship("SupplierReturn", back_populates="purchase_order", lazy="selectin")

class POLineItem(Base, BaseModelMixin):
    __tablename__ = "purchase_order_lines"

    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity_ordered = Column(Numeric(18, 4), nullable=False)
    quantity_received = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_cancelled = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_price = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    tax_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    line_total = Column(Numeric(18, 4), default=0.0, nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")

class GoodsReceipt(Base, BaseModelMixin):
    __tablename__ = "goods_receipts"

    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    grn_number = Column(String(50), unique=True, index=True, nullable=False)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    received_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    received_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    warehouse = relationship("Warehouse", lazy="selectin")
    lines = relationship("GoodsReceiptLine", back_populates="goods_receipt", cascade="all, delete-orphan", lazy="selectin")

class GoodsReceiptLine(Base, BaseModelMixin):
    __tablename__ = "goods_receipt_lines"

    goods_receipt_id = Column(String(36), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(36), ForeignKey("purchase_order_lines.id"), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    quantity_received = Column(Numeric(18, 4), nullable=False)
    destination_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    batch_number = Column(String(100), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)

    goods_receipt = relationship("GoodsReceipt", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
    destination_bin = relationship("LocationBin", lazy="selectin")

class SupplierReturn(Base, BaseModelMixin):
    __tablename__ = "supplier_returns"

    tenant_id = Column(String(36), nullable=False, index=True)
    return_number = Column(String(50), unique=True, index=True, nullable=False)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=True, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(30), default="COMPLETED", nullable=False) # DRAFT, APPROVED, COMPLETED, CANCELLED
    return_reason = Column(String(50), nullable=False) # DEFECTIVE, DAMAGED_IN_TRANSIT, WRONG_SPECIFICATION, EXPIRED, OTHER
    total_refund_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    returned_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    returned_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="returns", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", back_populates="returns", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    lines = relationship("SupplierReturnLine", back_populates="supplier_return", cascade="all, delete-orphan", lazy="selectin")

class SupplierReturnLine(Base, BaseModelMixin):
    __tablename__ = "supplier_return_lines"

    supplier_return_id = Column(String(36), ForeignKey("supplier_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    source_location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    quantity_returned = Column(Numeric(18, 4), nullable=False)
    unit_cost = Column(Numeric(18, 4), nullable=False)
    total_cost = Column(Numeric(18, 4), nullable=False)
    batch_number = Column(String(100), nullable=True)

    supplier_return = relationship("SupplierReturn", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
    source_bin = relationship("LocationBin", lazy="selectin")

class SupplierDebitMemo(Base, BaseModelMixin):
    __tablename__ = "supplier_debit_memos"

    tenant_id = Column(String(36), nullable=False, index=True)
    memo_number = Column(String(50), unique=True, index=True, nullable=False)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_return_id = Column(String(36), ForeignKey("supplier_returns.id"), nullable=True, index=True)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(String(30), default="OPEN", nullable=False) # OPEN, APPLIED, VOIDED
    issued_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="debit_memos")
