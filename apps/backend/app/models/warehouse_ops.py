from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now
from app.models.traceability import ItemSerialNumber

class CountSession(Base, BaseModelMixin):
    __tablename__ = "count_sessions"

    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    session_number = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, IN_PROGRESS, PENDING_REVIEW, APPROVED, REJECTED, RECOUNT_REQUESTED
    scope_type = Column(String(30), default="FULL_WAREHOUSE", nullable=False) # FULL_WAREHOUSE, ZONE, CATEGORY, CUSTOM_BINS
    notes = Column(Text, nullable=True)
    assigned_to_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    warehouse = relationship("Warehouse", lazy="selectin")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id], lazy="selectin")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id], lazy="selectin")
    lines = relationship("CountLine", back_populates="session", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_count_tenant_wh", "tenant_id", "warehouse_id"),
    )

class CountLine(Base, BaseModelMixin):
    __tablename__ = "count_lines"

    count_session_id = Column(String(36), ForeignKey("count_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    batch_id = Column(String(36), ForeignKey("stock_batches.id"), nullable=True)
    expected_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    counted_quantity = Column(Numeric(18, 4), nullable=True) # None until counted
    variance_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    variance_value = Column(Numeric(18, 4), default=0.0, nullable=False)
    is_recounted = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)

    session = relationship("CountSession", back_populates="lines")
    bin = relationship("LocationBin", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    batch = relationship("StockBatch", lazy="selectin")

class PickTask(Base, BaseModelMixin):
    __tablename__ = "pick_tasks"

    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    sales_order_id = Column(String(36), ForeignKey("sales_orders.id"), nullable=False, index=True)
    task_number = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, IN_PROGRESS, COMPLETED, CANCELLED
    assigned_to_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    warehouse = relationship("Warehouse", lazy="selectin")
    sales_order = relationship("SalesOrder", lazy="selectin")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id], lazy="selectin")
    lines = relationship("PickTaskLine", back_populates="task", cascade="all, delete-orphan", lazy="selectin")

class PickTaskLine(Base, BaseModelMixin):
    __tablename__ = "pick_task_lines"

    pick_task_id = Column(String(36), ForeignKey("pick_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    so_line_id = Column(String(36), ForeignKey("sales_order_lines.id"), nullable=False, index=True)
    location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    batch_id = Column(String(36), ForeignKey("stock_batches.id"), nullable=True)
    quantity_allocated = Column(Numeric(18, 4), nullable=False)
    quantity_picked = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, PICKED

    task = relationship("PickTask", back_populates="lines")
    so_line = relationship("SOLineItem", lazy="selectin")
    bin = relationship("LocationBin", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    batch = relationship("StockBatch", lazy="selectin")

class PackingSession(Base, BaseModelMixin):
    __tablename__ = "packing_sessions"

    tenant_id = Column(String(36), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id"), nullable=False, index=True)
    session_number = Column(String(50), unique=True, index=True, nullable=False)
    packed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    status = Column(String(30), default="OPEN", nullable=False) # OPEN, COMPLETED
    carton_count = Column(Numeric(10, 0), default=1, nullable=False)
    started_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    shipment = relationship("Shipment", lazy="selectin")
    packed_by = relationship("User", foreign_keys=[packed_by_user_id], lazy="selectin")
    items = relationship("PackingItem", back_populates="session", cascade="all, delete-orphan", lazy="selectin")

class PackingItem(Base, BaseModelMixin):
    __tablename__ = "packing_items"

    packing_session_id = Column(String(36), ForeignKey("packing_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    serial_number = Column(String(100), nullable=True)
    batch_number = Column(String(100), nullable=True)
    quantity_packed = Column(Numeric(18, 4), default=1.0, nullable=False)
    carton_number = Column(Numeric(10, 0), default=1, nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    session = relationship("PackingSession", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")
