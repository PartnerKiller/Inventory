import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class CostCenter(Base, BaseModelMixin):
    __tablename__ = "cost_centers"

    tenant_id = Column(String(36), nullable=False, index=True)
    cost_center_code = Column(String(50), nullable=False, index=True) # e.g. CC-ENG-100
    cost_center_name = Column(String(100), nullable=False)
    parent_cost_center_id = Column(String(36), ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True, index=True)
    department_head_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_profit_center = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    parent_cost_center = relationship("CostCenter", remote_side="CostCenter.id", backref="sub_cost_centers", lazy="selectin")
    budgets = relationship("DepartmentalBudget", back_populates="cost_center", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "cost_center_code", name="uq_tenant_cost_center_code"),
    )

class DepartmentalBudget(Base, BaseModelMixin):
    __tablename__ = "departmental_budgets"

    tenant_id = Column(String(36), nullable=False, index=True)
    budget_code = Column(String(50), nullable=False, index=True) # e.g. BUD-2026-ENG
    cost_center_id = Column(String(36), ForeignKey("cost_centers.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year_id = Column(String(36), ForeignKey("fiscal_years.id", ondelete="CASCADE"), nullable=False, index=True)
    total_allocated_budget = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, APPROVED, COMMITTED, ACTUALIZED, LOCKED, CLOSED
    enforce_hard_cap = Column(Boolean, default=True, nullable=False) # If True, blocks PO overruns
    warning_threshold_percentage = Column(Numeric(10, 2), default=80.0, nullable=False) # e.g. 80.0%
    notes = Column(Text, nullable=True)

    cost_center = relationship("CostCenter", back_populates="budgets", lazy="selectin")
    fiscal_year = relationship("FiscalYear", lazy="selectin")
    budget_lines = relationship("BudgetLine", back_populates="budget", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "budget_code", name="uq_tenant_budget_code"),
        UniqueConstraint("tenant_id", "cost_center_id", "fiscal_year_id", name="uq_tenant_cc_fy_budget"),
    )

class BudgetLine(Base, BaseModelMixin):
    __tablename__ = "budget_lines"

    tenant_id = Column(String(36), nullable=False, index=True)
    budget_id = Column(String(36), ForeignKey("departmental_budgets.id", ondelete="CASCADE"), nullable=False, index=True)
    period_code = Column(String(50), nullable=False, index=True) # e.g. 2026-01
    gl_account_id = Column(String(36), ForeignKey("gl_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    allocated_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    committed_amount = Column(Numeric(18, 4), default=0.0, nullable=False) # Reserved by POs
    actual_amount = Column(Numeric(18, 4), default=0.0, nullable=False) # Actualized from Invoices/GL

    budget = relationship("DepartmentalBudget", back_populates="budget_lines", lazy="selectin")
    gl_account = relationship("GLAccount", lazy="selectin")
    commitments = relationship("BudgetCommitment", back_populates="budget_line", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("budget_id", "period_code", "gl_account_id", name="uq_budget_period_gl_account"),
    )

class BudgetCommitment(Base, BaseModelMixin):
    __tablename__ = "budget_commitments"

    tenant_id = Column(String(36), nullable=False, index=True)
    budget_line_id = Column(String(36), ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    source_document_type = Column(String(50), nullable=False, index=True) # PURCHASE_ORDER, EXPENSE_REQUISITION
    source_document_id = Column(String(50), nullable=False, index=True)
    committed_amount = Column(Numeric(18, 4), nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # ACTIVE, RELEASED, ACTUALIZED

    budget_line = relationship("BudgetLine", back_populates="commitments", lazy="selectin")
