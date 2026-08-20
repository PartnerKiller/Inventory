import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class WorkCenter(Base, BaseModelMixin):
    __tablename__ = "work_centers"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True) # WC-SMT-01
    name = Column(String(100), nullable=False)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    department = Column(String(100), nullable=True)
    hourly_labor_rate = Column(Numeric(18, 4), default=0.0, nullable=False)
    hourly_machine_rate = Column(Numeric(18, 4), default=0.0, nullable=False)
    daily_capacity_hours = Column(Numeric(8, 2), default=16.0, nullable=False)
    efficiency_factor = Column(Numeric(5, 2), default=1.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_work_center_tenant_code"),
        Index("idx_wc_tenant_wh", "tenant_id", "warehouse_id"),
    )

class Routing(Base, BaseModelMixin):
    __tablename__ = "routings"

    tenant_id = Column(String(36), nullable=False, index=True)
    routing_number = Column(String(50), unique=True, index=True, nullable=False) # ROUT-001
    name = Column(String(255), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    version = Column(String(20), default="1.0", nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # ACTIVE, DRAFT, OBSOLETE

    variant = relationship("ItemVariant", lazy="selectin")
    operations = relationship("RoutingOperation", back_populates="routing", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "version", name="uq_routing_variant_version"),
    )

class RoutingOperation(Base, BaseModelMixin):
    __tablename__ = "routing_operations"

    routing_id = Column(String(36), ForeignKey("routings.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False) # 10, 20, 30
    operation_name = Column(String(100), nullable=False)
    work_center_id = Column(String(36), ForeignKey("work_centers.id"), nullable=False, index=True)
    setup_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    run_time_minutes_per_unit = Column(Numeric(8, 2), default=1.0, nullable=False)
    queue_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    move_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    is_quality_gate = Column(Boolean, default=False, nullable=False)

    routing = relationship("Routing", back_populates="operations")
    work_center = relationship("WorkCenter", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("routing_id", "sequence_number", name="uq_routing_sequence"),
    )

class ProductionOrderOperation(Base, BaseModelMixin):
    __tablename__ = "production_order_operations"

    work_order_id = Column(String(36), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    operation_name = Column(String(100), nullable=False)
    work_center_id = Column(String(36), ForeignKey("work_centers.id"), nullable=False, index=True)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, RUNNING, PAUSED, COMPLETED
    assigned_operator_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actual_setup_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    actual_run_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    actual_labor_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    actual_machine_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    completed_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    scrap_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    is_quality_gate = Column(Boolean, default=False, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    work_order = relationship("WorkOrder", lazy="selectin")
    work_center = relationship("WorkCenter", lazy="selectin")
    assigned_operator = relationship("User", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("work_order_id", "sequence_number", name="uq_wo_operation_sequence"),
    )

class ProductionQualityInspection(Base, BaseModelMixin):
    __tablename__ = "production_quality_inspections"

    tenant_id = Column(String(36), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=False, index=True)
    operation_id = Column(String(36), ForeignKey("production_order_operations.id"), nullable=True, index=True)
    inspection_type = Column(String(30), default="IN_PROCESS", nullable=False) # IN_PROCESS, FINAL
    inspector_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    inspected_quantity = Column(Numeric(18, 4), nullable=False)
    passed_quantity = Column(Numeric(18, 4), nullable=False)
    rejected_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    disposition = Column(String(30), default="PASS", nullable=False) # PASS, HOLD, REJECT, REWORK
    quarantine_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=True)
    notes = Column(Text, nullable=True)

    work_order = relationship("WorkOrder", lazy="selectin")
    inspector = relationship("User", lazy="selectin")
    quarantine_bin = relationship("LocationBin", lazy="selectin")
