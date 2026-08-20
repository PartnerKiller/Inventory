import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class SupplierScorecard(Base, BaseModelMixin):
    __tablename__ = "supplier_scorecards"

    tenant_id = Column(String(36), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    period_code = Column(String(50), nullable=False, index=True) # e.g. 2026-Q1, 2026-01, ALL_TIME

    total_pos_count = Column(Integer, default=0, nullable=False)
    on_time_deliveries_count = Column(Integer, default=0, nullable=False)
    otd_percentage = Column(Numeric(5, 2), default=0.0, nullable=False) # e.g. 95.50 %

    total_received_units = Column(Numeric(18, 4), default=0.0, nullable=False)
    rejected_units_count = Column(Numeric(18, 4), default=0.0, nullable=False)
    quality_acceptance_percentage = Column(Numeric(5, 2), default=100.0, nullable=False) # e.g. 98.00 %

    price_variance_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    price_compliance_percentage = Column(Numeric(5, 2), default=100.0, nullable=False)

    overall_vendor_score = Column(Numeric(5, 2), default=0.0, nullable=False) # 0 - 100.00
    tier_grade = Column(String(30), default="TIER_B_APPROVED", nullable=False) # TIER_A_PREFERRED, TIER_B_APPROVED, TIER_C_PROBATIONARY, TIER_D_RESTRICTED

    evaluated_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "period_code", name="uq_tenant_supplier_period_scorecard"),
    )
