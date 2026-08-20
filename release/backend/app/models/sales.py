from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class Customer(Base, BaseModelMixin):
    __tablename__ = "customers"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    tax_identifier = Column(String(100), nullable=True) # VAT / GST / EIN
    currency = Column(String(10), default="USD", nullable=False)
    payment_terms = Column(String(30), default="NET_30", nullable=False) # PREPAID, NET_15, NET_30, NET_60
    credit_limit = Column(Numeric(18, 4), default=0.0, nullable=False)
    current_credit_exposure = Column(Numeric(18, 4), default=0.0, nullable=False)
    billing_address = Column(JSON, nullable=True)
    shipping_address = Column(JSON, nullable=True)
    shipping_addresses = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    sales_orders = relationship("SalesOrder", back_populates="customer")
    addresses = relationship("CustomerAddress", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")
    contacts = relationship("CustomerContact", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")
    price_list_assignments = relationship("CustomerPriceList", back_populates="customer", cascade="all, delete-orphan", lazy="selectin")

class CustomerAddress(Base, BaseModelMixin):
    __tablename__ = "customer_addresses"

    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    address_type = Column(String(30), default="SHIPPING", nullable=False) # BILLING, SHIPPING
    label = Column(String(100), nullable=True) # e.g. "Main Distribution Center"
    street1 = Column(String(255), nullable=False)
    street2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(30), nullable=False)
    country = Column(String(100), default="USA", nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    customer = relationship("Customer", back_populates="addresses")

class CustomerContact(Base, BaseModelMixin):
    __tablename__ = "customer_contacts"

    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    job_title = Column(String(100), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)

    customer = relationship("Customer", back_populates="contacts")

# ============================================================================
# PRICING MODELS (8B.1)
# ============================================================================

class PriceList(Base, BaseModelMixin):
    __tablename__ = "price_lists"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    valid_from = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)

    items = relationship("PriceListItem", back_populates="price_list", cascade="all, delete-orphan", lazy="selectin")
    customer_assignments = relationship("CustomerPriceList", back_populates="price_list", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_price_list_tenant_code"),
    )

class PriceListItem(Base, BaseModelMixin):
    __tablename__ = "price_list_items"

    price_list_id = Column(String(36), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    base_price = Column(Numeric(18, 4), nullable=False)
    min_price = Column(Numeric(18, 4), nullable=True) # Floor price protection

    price_list = relationship("PriceList", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")
    tiers = relationship("PriceListTier", back_populates="item", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("price_list_id", "item_variant_id", name="uq_price_list_variant"),
    )

class PriceListTier(Base, BaseModelMixin):
    __tablename__ = "price_list_tiers"

    price_list_item_id = Column(String(36), ForeignKey("price_list_items.id", ondelete="CASCADE"), nullable=False, index=True)
    min_quantity = Column(Numeric(18, 4), nullable=False)
    unit_price = Column(Numeric(18, 4), nullable=False)
    discount_pct = Column(Numeric(5, 2), default=0.0, nullable=False)

    item = relationship("PriceListItem", back_populates="tiers")

class CustomerPriceList(Base, BaseModelMixin):
    __tablename__ = "customer_price_lists"

    tenant_id = Column(String(36), nullable=False, index=True)
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    price_list_id = Column(String(36), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(Integer, default=1, nullable=False) # Lower number = higher priority
    assigned_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    customer = relationship("Customer", back_populates="price_list_assignments")
    price_list = relationship("PriceList", back_populates="customer_assignments", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("customer_id", "price_list_id", name="uq_customer_price_list"),
    )

# ============================================================================
# SALES ORDER & MULTI-WAREHOUSE FULFILLMENT MODELS (8B.2)
# ============================================================================

class SalesOrder(Base, BaseModelMixin):
    __tablename__ = "sales_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    so_number = Column(String(50), unique=True, index=True, nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True) # Default primary warehouse
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, CONFIRMED, ON_HOLD, PARTIALLY_ALLOCATED, ALLOCATED, PICKING, PACKED, SHIPPED, DELIVERED, CANCELLED
    hold_reason = Column(String(255), nullable=True)
    hold_placed_at = Column(DateTime(timezone=True), nullable=True)
    hold_released_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    credit_limit_override_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    subtotal_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    tax_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    ordered_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    delivery_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    delivery_notes = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    customer = relationship("Customer", back_populates="sales_orders", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    lines = relationship("SOLineItem", back_populates="sales_order", cascade="all, delete-orphan", lazy="selectin")
    fulfillment_groups = relationship("SOFulfillmentGroup", back_populates="sales_order", cascade="all, delete-orphan", lazy="selectin")
    shipments = relationship("Shipment", back_populates="sales_order", lazy="selectin")
    returns = relationship("SalesReturn", back_populates="sales_order", lazy="selectin")

class SOFulfillmentGroup(Base, BaseModelMixin):
    """Fulfillment group for multi-warehouse split order routing."""
    __tablename__ = "sales_order_fulfillment_groups"

    sales_order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    group_number = Column(String(50), nullable=False) # e.g. "FG-SO1001-1"
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, ALLOCATED, PICKING, PACKED, SHIPPED, CANCELLED
    notes = Column(Text, nullable=True)

    sales_order = relationship("SalesOrder", back_populates="fulfillment_groups")
    warehouse = relationship("Warehouse", lazy="selectin")
    allocations = relationship("SOAllocation", back_populates="fulfillment_group", lazy="selectin")
    shipments = relationship("Shipment", back_populates="fulfillment_group", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("sales_order_id", "group_number", name="uq_so_group_number"),
    )

class SOLineItem(Base, BaseModelMixin):
    __tablename__ = "sales_order_lines"

    sales_order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity_ordered = Column(Numeric(18, 4), nullable=False)
    quantity_allocated = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_backordered = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_picked = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_shipped = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_returned = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_cancelled = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_price = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    tax_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    line_total = Column(Numeric(18, 4), default=0.0, nullable=False)

    sales_order = relationship("SalesOrder", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
    allocations = relationship("SOAllocation", back_populates="so_line", cascade="all, delete-orphan", lazy="selectin")

class SOAllocation(Base, BaseModelMixin):
    __tablename__ = "sales_order_allocations"

    so_line_id = Column(String(36), ForeignKey("sales_order_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    fulfillment_group_id = Column(String(36), ForeignKey("sales_order_fulfillment_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False, index=True)
    quantity_allocated = Column(Numeric(18, 4), nullable=False)

    so_line = relationship("SOLineItem", back_populates="allocations")
    fulfillment_group = relationship("SOFulfillmentGroup", back_populates="allocations")
    location_bin = relationship("LocationBin", lazy="selectin")

class Shipment(Base, BaseModelMixin):
    __tablename__ = "shipments"

    sales_order_id = Column(String(36), ForeignKey("sales_orders.id"), nullable=False, index=True)
    fulfillment_group_id = Column(String(36), ForeignKey("sales_order_fulfillment_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    shipment_number = Column(String(50), unique=True, index=True, nullable=False)
    carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    package_count = Column(Integer, default=1, nullable=False)
    total_weight = Column(Numeric(10, 2), nullable=True)
    shipped_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    dispatched_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    sales_order = relationship("SalesOrder", back_populates="shipments")
    fulfillment_group = relationship("SOFulfillmentGroup", back_populates="shipments")

class SalesReturn(Base, BaseModelMixin):
    __tablename__ = "sales_returns"

    sales_order_id = Column(String(36), ForeignKey("sales_orders.id"), nullable=False, index=True)
    return_number = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(String(30), default="COMPLETED", nullable=False) # COMPLETED, INSPECTING
    rma_status = Column(String(30), default="RECEIVED", nullable=False) # REQUESTED, RECEIVED, INSPECTED, RESTOCKED, SCRAPPED
    inspection_notes = Column(Text, nullable=True)
    disposition = Column(String(30), nullable=True) # RESTOCK, SCRAP, RETURN_TO_VENDOR
    inspected_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    returned_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    received_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    sales_order = relationship("SalesOrder", back_populates="returns")
    lines = relationship("SalesReturnLine", back_populates="sales_return", cascade="all, delete-orphan", lazy="selectin")

class SalesReturnLine(Base, BaseModelMixin):
    __tablename__ = "sales_return_lines"

    sales_return_id = Column(String(36), ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    so_line_id = Column(String(36), ForeignKey("sales_order_lines.id"), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    quantity_returned = Column(Numeric(18, 4), nullable=False)
    condition = Column(String(20), default="GOOD", nullable=False) # GOOD, DAMAGED
    destination_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)

    sales_return = relationship("SalesReturn", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
    destination_bin = relationship("LocationBin", lazy="selectin")
