import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class ApprovalRule(Base, BaseModelMixin):
    __tablename__ = "approval_rules"

    tenant_id = Column(String(36), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False, index=True) # PURCHASE_ORDER, VENDOR_INVOICE, JOURNAL_VOUCHER, BUDGET_OVERRUN, ASSET_DISPOSAL
    min_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    max_amount = Column(Numeric(18, 4), nullable=True) # None = unlimited
    cost_center_id = Column(String(36), ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True, index=True)
    step_number = Column(Integer, default=1, nullable=False) # 1, 2, 3...
    approver_role_id = Column(String(36), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    approver_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sla_hours = Column(Integer, default=24, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    cost_center = relationship("CostCenter", lazy="selectin")
    approver_role = relationship("Role", lazy="selectin")
    approver_user = relationship("User", lazy="selectin")

class ApprovalRequest(Base, BaseModelMixin):
    __tablename__ = "approval_requests"

    tenant_id = Column(String(36), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(String(36), nullable=False, index=True)
    document_reference = Column(String(100), nullable=False)
    requested_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    cost_center_id = Column(String(36), ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="PENDING", nullable=False, index=True) # PENDING, IN_REVIEW, APPROVED, REJECTED, ESCALATED, CANCELLED
    current_step_number = Column(Integer, default=1, nullable=False)
    total_steps = Column(Integer, default=1, nullable=False)

    cost_center = relationship("CostCenter", lazy="selectin")
    requested_by = relationship("User", lazy="selectin")
    steps = relationship("ApprovalStep", back_populates="request", cascade="all, delete-orphan", lazy="selectin", order_by="ApprovalStep.step_number")

class ApprovalStep(Base, BaseModelMixin):
    __tablename__ = "approval_steps"

    tenant_id = Column(String(36), nullable=False, index=True)
    request_id = Column(String(36), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    approver_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_role_id = Column(String(36), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, APPROVED, REJECTED, DELEGATED, SKIPPED
    action_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action_taken_at = Column(DateTime(timezone=True), nullable=True)
    comments = Column(Text, nullable=True)

    request = relationship("ApprovalRequest", back_populates="steps", lazy="selectin")
    approver_user = relationship("User", foreign_keys=[approver_user_id], lazy="selectin")
    assigned_role = relationship("Role", lazy="selectin")
    action_by_user = relationship("User", foreign_keys=[action_by_user_id], lazy="selectin")

class ApprovalDelegation(Base, BaseModelMixin):
    __tablename__ = "approval_delegations"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    delegate_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    delegate_user = relationship("User", foreign_keys=[delegate_user_id], lazy="selectin")
