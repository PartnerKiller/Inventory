import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class PriceRule(Base, BaseModelMixin):
    __tablename__ = "price_rules_v2"

    tenant_id = Column(String(36), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    customer_group = Column(String(50), nullable=True, index=True) # e.g. WHOLESALE, DISTRIBUTOR, RETAIL
    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    min_quantity = Column(Numeric(18, 4), default=1.0, nullable=False)
    max_quantity = Column(Numeric(18, 4), nullable=True) # None = unlimited
    discount_type = Column(String(30), default="PERCENTAGE", nullable=False) # PERCENTAGE, FIXED_PRICE, AMOUNT_OFF
    discount_value = Column(Numeric(18, 4), default=0.0, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    priority = Column(Integer, default=10, nullable=False) # Higher number = higher priority
    is_active = Column(Boolean, default=True, nullable=False)

    customer = relationship("Customer", lazy="selectin")
    item = relationship("Item", lazy="selectin")

class RebateAgreement(Base, BaseModelMixin):
    __tablename__ = "rebate_agreements"

    tenant_id = Column(String(36), nullable=False, index=True)
    agreement_code = Column(String(50), nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    target_spend_threshold = Column(Numeric(18, 4), nullable=False)
    rebate_percentage = Column(Numeric(10, 4), nullable=False) # e.g. 5.0 (5%)
    status = Column(String(30), default="ACTIVE", nullable=False) # ACTIVE, SETTLED, EXPIRED, CANCELLED
    settled_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    credit_note_id = Column(String(36), ForeignKey("customer_credit_notes.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)

    customer = relationship("Customer", lazy="selectin")
    credit_note = relationship("CustomerCreditNote", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "agreement_code", name="uq_tenant_rebate_agreement_code"),
    )
