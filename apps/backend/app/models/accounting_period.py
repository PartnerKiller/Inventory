import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class FiscalYear(Base, BaseModelMixin):
    __tablename__ = "fiscal_years"

    tenant_id = Column(String(36), nullable=False, index=True)
    fiscal_year_code = Column(String(50), nullable=False, index=True) # e.g. FY2026
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(30), default="OPEN", nullable=False) # OPEN, CLOSED, FINALIZED
    notes = Column(Text, nullable=True)

    periods = relationship("AccountingPeriod", back_populates="fiscal_year", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "fiscal_year_code", name="uq_tenant_fiscal_year_code"),
        Index("idx_fy_tenant_dates", "tenant_id", "start_date", "end_date"),
    )

class AccountingPeriod(Base, BaseModelMixin):
    __tablename__ = "accounting_periods"

    tenant_id = Column(String(36), nullable=False, index=True)
    fiscal_year_id = Column(String(36), ForeignKey("fiscal_years.id", ondelete="CASCADE"), nullable=False, index=True)
    period_code = Column(String(50), nullable=False, index=True) # e.g. 2026-01, 2026-02
    period_number = Column(Integer, nullable=False) # 1 to 12
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(30), default="FUTURE", nullable=False) # FUTURE, OPEN, SOFT_CLOSED, CLOSED, FINALIZED
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    closing_notes = Column(Text, nullable=True)

    fiscal_year = relationship("FiscalYear", back_populates="periods", lazy="selectin")
    closed_by = relationship("User", foreign_keys=[closed_by_user_id], lazy="selectin")
    checklist_items = relationship("PeriodClosingChecklist", back_populates="period", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "period_code", name="uq_tenant_period_code"),
        Index("idx_period_tenant_dates", "tenant_id", "start_date", "end_date"),
    )

class PeriodClosingChecklist(Base, BaseModelMixin):
    __tablename__ = "period_closing_checklist"

    tenant_id = Column(String(36), nullable=False, index=True)
    period_id = Column(String(36), ForeignKey("accounting_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    checkpoint_name = Column(String(150), nullable=False) # e.g. Unbilled GRN Reconciled, Bank Reconciliation Complete, Physical Inventory Count
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    period = relationship("AccountingPeriod", back_populates="checklist_items", lazy="selectin")
    completed_by = relationship("User", foreign_keys=[completed_by_user_id], lazy="selectin")
