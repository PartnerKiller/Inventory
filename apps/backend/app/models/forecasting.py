import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class DemandForecastProfile(Base, BaseModelMixin):
    __tablename__ = "demand_forecast_profiles"

    tenant_id = Column(String(36), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    model_type = Column(String(30), default="HOLT_WINTERS", nullable=False) # HOLT_WINTERS, MOVING_AVERAGE, LINEAR_REGRESSION
    seasonality_periods = Column(Integer, default=12, nullable=False) # e.g. 12 months or 4 quarters
    alpha = Column(Numeric(10, 4), default=0.2, nullable=False) # Level smoothing parameter
    beta = Column(Numeric(10, 4), default=0.1, nullable=False) # Trend smoothing parameter
    gamma = Column(Numeric(10, 4), default=0.3, nullable=False) # Seasonality smoothing parameter
    service_level_target = Column(Numeric(10, 4), default=0.95, nullable=False) # 0.95 (95%), 0.99 (99%)
    lead_time_days = Column(Numeric(10, 2), default=7.0, nullable=False) # Lead time in days
    lead_time_std_dev = Column(Numeric(10, 2), default=1.5, nullable=False) # Lead time standard deviation
    is_active = Column(Boolean, default=True, nullable=False)

    item = relationship("Item", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    forecast_entries = relationship("ForecastPeriodEntry", back_populates="profile", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", "warehouse_id", name="uq_tenant_item_wh_forecast_profile"),
    )

class ForecastPeriodEntry(Base, BaseModelMixin):
    __tablename__ = "forecast_period_entries"

    tenant_id = Column(String(36), nullable=False, index=True)
    profile_id = Column(String(36), ForeignKey("demand_forecast_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    period_date = Column(Date, nullable=False, index=True)
    historical_actual_demand = Column(Numeric(18, 4), default=0.0, nullable=False)
    forecasted_demand = Column(Numeric(18, 4), default=0.0, nullable=False)
    calculated_safety_stock = Column(Numeric(18, 4), default=0.0, nullable=False)
    calculated_rop = Column(Numeric(18, 4), default=0.0, nullable=False)

    profile = relationship("DemandForecastProfile", back_populates="forecast_entries", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("profile_id", "period_date", name="uq_profile_period_forecast"),
    )

class ReplenishmentProposal(Base, BaseModelMixin):
    __tablename__ = "replenishment_proposals"

    tenant_id = Column(String(36), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    suggested_order_qty = Column(Numeric(18, 4), nullable=False)
    current_stock_on_hand = Column(Numeric(18, 4), nullable=False)
    in_transit_qty = Column(Numeric(18, 4), default=0.0, nullable=False)
    calculated_rop = Column(Numeric(18, 4), nullable=False)
    calculated_safety_stock = Column(Numeric(18, 4), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, CONVERTED_TO_PO, REJECTED
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)

    item = relationship("Item", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")
