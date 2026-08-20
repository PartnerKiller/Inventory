from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class BillOfMaterials(Base, BaseModelMixin):
    __tablename__ = "bills_of_materials"

    tenant_id = Column(String(36), nullable=False, index=True)
    bom_number = Column(String(50), unique=True, index=True, nullable=False) # BOM-XXXX
    name = Column(String(255), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    version = Column(String(20), default="1.0", nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # DRAFT, ACTIVE, OBSOLETE
    yield_quantity = Column(Numeric(18, 4), default=1.0, nullable=False)
    labor_cost_per_unit = Column(Numeric(18, 4), default=0.0, nullable=False)
    overhead_cost_per_unit = Column(Numeric(18, 4), default=0.0, nullable=False)
    notes = Column(Text, nullable=True)

    variant = relationship("ItemVariant", lazy="selectin")
    lines = relationship("BOMLineItem", back_populates="bom", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "version", name="uq_bom_variant_version"),
    )

class BOMLineItem(Base, BaseModelMixin):
    __tablename__ = "bom_line_items"

    bom_id = Column(String(36), ForeignKey("bills_of_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    component_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity_required = Column(Numeric(18, 4), nullable=False)
    scrap_percentage = Column(Numeric(5, 2), default=0.0, nullable=False)
    position = Column(Integer, default=1, nullable=False)
    notes = Column(Text, nullable=True)

    bom = relationship("BillOfMaterials", back_populates="lines")
    component_variant = relationship("ItemVariant", lazy="selectin")

class WorkOrder(Base, BaseModelMixin):
    __tablename__ = "work_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    work_order_number = Column(String(50), unique=True, index=True, nullable=False) # WO-XXXX
    bom_id = Column(String(36), ForeignKey("bills_of_materials.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    staging_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    destination_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, PLANNED, RELEASED, IN_PROGRESS, COMPLETED, CANCELLED
    quantity_to_produce = Column(Numeric(18, 4), nullable=False)
    quantity_produced = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_component_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_labor_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_overhead_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_production_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    planned_start_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    bom = relationship("BillOfMaterials", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    staging_bin = relationship("LocationBin", foreign_keys=[staging_bin_id], lazy="selectin")
    destination_bin = relationship("LocationBin", foreign_keys=[destination_bin_id], lazy="selectin")
    components = relationship("WorkOrderComponent", back_populates="work_order", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_wo_tenant_status", "tenant_id", "status"),
    )

class WorkOrderComponent(Base, BaseModelMixin):
    __tablename__ = "work_order_components"

    work_order_id = Column(String(36), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    component_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity_required = Column(Numeric(18, 4), nullable=False)
    quantity_reserved = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_consumed = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_cost = Column(Numeric(18, 4), default=0.0, nullable=False)

    work_order = relationship("WorkOrder", back_populates="components")
    component_variant = relationship("ItemVariant", lazy="selectin")

class DisassemblyOrder(Base, BaseModelMixin):
    __tablename__ = "disassembly_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    disassembly_number = Column(String(50), unique=True, index=True, nullable=False) # DIS-XXXX
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    source_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    destination_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    quantity_disassembled = Column(Numeric(18, 4), nullable=False)
    total_cost_recovered = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="COMPLETED", nullable=False) # COMPLETED, CANCELLED
    disassembled_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)
    performed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    variant = relationship("ItemVariant", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
