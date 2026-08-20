import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class MaintenanceSchedule(Base, BaseModelMixin):
    __tablename__ = "maintenance_schedules"

    tenant_id = Column(String(36), nullable=False, index=True)
    schedule_name = Column(String(100), nullable=False)
    asset_id = Column(String(36), ForeignKey("fixed_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    work_center_id = Column(String(36), ForeignKey("work_centers.id", ondelete="SET NULL"), nullable=True, index=True)
    schedule_type = Column(String(30), default="CALENDAR_INTERVAL", nullable=False) # CALENDAR_INTERVAL, RUNTIME_HOURS
    frequency_days = Column(Integer, default=30, nullable=False) # Days between maintenance
    last_performed_at = Column(DateTime(timezone=True), nullable=True)
    next_due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    asset = relationship("FixedAsset", foreign_keys=[asset_id], lazy="selectin")
    work_center = relationship("WorkCenter", foreign_keys=[work_center_id], lazy="selectin")
    work_orders = relationship("MaintenanceWorkOrder", back_populates="schedule", lazy="selectin")

    __table_args__ = (
        Index("idx_maint_sched_due", "tenant_id", "next_due_at"),
    )

class MaintenanceWorkOrder(Base, BaseModelMixin):
    __tablename__ = "maintenance_work_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    mwo_number = Column(String(50), nullable=False, unique=True, index=True)
    schedule_id = Column(String(36), ForeignKey("maintenance_schedules.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_id = Column(String(36), ForeignKey("fixed_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    work_center_id = Column(String(36), ForeignKey("work_centers.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_technician_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    priority = Column(String(20), default="MEDIUM", nullable=False) # CRITICAL, HIGH, MEDIUM, LOW
    status = Column(String(30), default="DRAFT", nullable=False, index=True) # DRAFT, SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED
    expenditure_type = Column(String(30), default="REVENUE_EXPENSE", nullable=False) # REVENUE_EXPENSE, CAPITAL_IMPROVEMENT
    useful_life_extension_months = Column(Integer, default=0, nullable=False)
    scheduled_start_date = Column(DateTime(timezone=True), nullable=True)
    actual_completion_date = Column(DateTime(timezone=True), nullable=True)
    downtime_hours = Column(Numeric(10, 2), default=0.0, nullable=False)
    labor_hours = Column(Numeric(10, 2), default=0.0, nullable=False)
    journal_voucher_id = Column(String(36), ForeignKey("journal_vouchers.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)

    schedule = relationship("MaintenanceSchedule", back_populates="work_orders", lazy="selectin")
    asset = relationship("FixedAsset", foreign_keys=[asset_id], lazy="selectin")
    work_center = relationship("WorkCenter", foreign_keys=[work_center_id], lazy="selectin")
    technician = relationship("User", foreign_keys=[assigned_technician_id], lazy="selectin")
    journal_voucher = relationship("JournalVoucher", foreign_keys=[journal_voucher_id], lazy="selectin")
    spare_parts = relationship("MWOSparePart", back_populates="work_order", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_mwo_tenant_status", "tenant_id", "status"),
    )

class MWOSparePart(Base, BaseModelMixin):
    __tablename__ = "mwo_spare_parts"

    tenant_id = Column(String(36), nullable=False, index=True)
    mwo_id = Column(String(36), ForeignKey("maintenance_work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    location_bin_id = Column(String(36), ForeignKey("location_bins.id", ondelete="CASCADE"), nullable=False)
    quantity_required = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_consumed = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_cost = Column(Numeric(18, 4), default=0.0, nullable=False)

    work_order = relationship("MaintenanceWorkOrder", back_populates="spare_parts", lazy="selectin")
    item_variant = relationship("ItemVariant", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    bin = relationship("LocationBin", lazy="selectin")
