import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class ReplenishmentConfig(Base, BaseModelMixin):
    __tablename__ = "replenishment_configs"

    tenant_id = Column(String(36), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True, index=True) # Null = Tenant Global Default
    reorder_method = Column(String(30), default="DYNAMIC_ROP", nullable=False) # DYNAMIC_ROP, MIN_MAX, PERIODIC
    min_quantity = Column(Numeric(18, 4), nullable=True) # For MIN_MAX method
    max_quantity = Column(Numeric(18, 4), nullable=True)
    safety_stock_days = Column(Integer, default=7, nullable=False)
    target_coverage_days = Column(Integer, default=30, nullable=False)
    fixed_safety_stock = Column(Numeric(18, 4), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    variant = relationship("ItemVariant", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "warehouse_id", name="uq_replenish_config_tenant_var_wh"),
    )

class ReplenishmentRun(Base, BaseModelMixin):
    __tablename__ = "replenishment_runs"

    tenant_id = Column(String(36), nullable=False, index=True)
    run_number = Column(String(50), unique=True, index=True, nullable=False) # RPL-YYYYMMDD-XXXX
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True, index=True)
    triggered_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    total_skus_evaluated = Column(Integer, default=0, nullable=False)
    total_recommendations = Column(Integer, default=0, nullable=False)
    total_estimated_spend = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="COMPLETED", nullable=False) # IN_PROGRESS, COMPLETED, FAILED

    warehouse = relationship("Warehouse", lazy="selectin")
    items = relationship("ReplenishmentRecommendationItem", back_populates="run", cascade="all, delete-orphan", lazy="selectin")

class ReplenishmentRecommendationItem(Base, BaseModelMixin):
    __tablename__ = "replenishment_recommendation_items"

    run_id = Column(String(36), ForeignKey("replenishment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=True, index=True)
    
    # Inventory Snapshot
    quantity_on_hand = Column(Numeric(18, 4), nullable=False)
    quantity_allocated = Column(Numeric(18, 4), nullable=False)
    quantity_available = Column(Numeric(18, 4), nullable=False)
    quantity_incoming = Column(Numeric(18, 4), nullable=False)
    quantity_mfg_planned = Column(Numeric(18, 4), default=0.0, nullable=False)
    net_inventory_position = Column(Numeric(18, 4), nullable=False)
    
    # Demand & Sizing
    average_daily_usage = Column(Numeric(18, 4), nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    safety_stock = Column(Numeric(18, 4), nullable=False)
    reorder_point = Column(Numeric(18, 4), nullable=False)
    target_maximum_stock = Column(Numeric(18, 4), nullable=False)
    minimum_order_quantity = Column(Numeric(18, 4), default=1.0, nullable=False)
    pack_size = Column(Numeric(18, 4), default=1.0, nullable=False)
    
    # Recommendation
    suggested_reorder_quantity = Column(Numeric(18, 4), nullable=False)
    estimated_unit_cost = Column(Numeric(18, 4), nullable=False)
    estimated_total_cost = Column(Numeric(18, 4), nullable=False)
    urgency_status = Column(String(30), nullable=False) # STOCKOUT_CRITICAL, REORDER_NOW, AT_RISK, HEALTHY, OVERSTOCKED
    suggested_order_date = Column(DateTime(timezone=True), nullable=False)
    
    # Procurement Conversion Tracking
    action_status = Column(String(30), default="PENDING", nullable=False) # PENDING, DRAFT_PO_CREATED, DISMISSED
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=True)

    run = relationship("ReplenishmentRun", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")
    supplier = relationship("Supplier", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")

    __table_args__ = (
        Index("idx_rpl_item_tenant_wh", "tenant_id", "warehouse_id"),
        Index("idx_rpl_item_action_status", "tenant_id", "action_status"),
    )
