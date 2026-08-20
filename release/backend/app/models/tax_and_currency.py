import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

# ============================================================================
# 1. CURRENCY & EXCHANGE RATES
# ============================================================================

class CurrencyExchangeRate(Base, BaseModelMixin):
    __tablename__ = "currency_exchange_rates"

    tenant_id = Column(String(36), nullable=False, index=True)
    from_currency = Column(String(10), nullable=False, index=True) # e.g. EUR, GBP, JPY
    to_currency = Column(String(10), nullable=False, index=True) # e.g. USD (Tenant Base)
    rate = Column(Numeric(18, 6), nullable=False)
    effective_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("idx_fx_lookup", "tenant_id", "from_currency", "to_currency", "effective_date"),
    )

# ============================================================================
# 2. TAX JURISDICTIONS & RATES
# ============================================================================

class TaxJurisdiction(Base, BaseModelMixin):
    __tablename__ = "tax_jurisdictions"

    tenant_id = Column(String(36), nullable=False, index=True)
    country_code = Column(String(10), nullable=False, index=True) # US, IN, GB, DE
    jurisdiction_code = Column(String(50), nullable=False, index=True) # US-CA, IN-MH, GB-VAT
    jurisdiction_name = Column(String(100), nullable=False)
    jurisdiction_type = Column(String(30), default="STATE", nullable=False) # FEDERAL, STATE, LOCAL
    is_active = Column(Boolean, default=True, nullable=False)

    tax_rates = relationship("TaxRate", back_populates="jurisdiction", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "jurisdiction_code", name="uq_tenant_jurisdiction_code"),
    )

class TaxRate(Base, BaseModelMixin):
    __tablename__ = "tax_rates"

    tenant_id = Column(String(36), nullable=False, index=True)
    jurisdiction_id = Column(String(36), ForeignKey("tax_jurisdictions.id", ondelete="CASCADE"), nullable=False, index=True)
    tax_code = Column(String(50), nullable=False, index=True) # CGST-9, SGST-9, IGST-18, VAT-20, SALES-TAX-8.25
    tax_name = Column(String(100), nullable=False)
    rate_percentage = Column(Numeric(10, 4), nullable=False) # e.g. 9.0000, 18.0000
    tax_type = Column(String(30), default="OUTPUT_TAX", nullable=False) # OUTPUT_TAX, INPUT_TAX_CREDIT, EXEMPT
    is_compound = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    jurisdiction = relationship("TaxJurisdiction", back_populates="tax_rates", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "tax_code", name="uq_tenant_tax_code"),
    )

class TaxGroup(Base, BaseModelMixin):
    __tablename__ = "tax_groups"

    tenant_id = Column(String(36), nullable=False, index=True)
    group_code = Column(String(50), nullable=False, index=True) # e.g. GST-18, VAT-STANDARD
    group_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    items = relationship("TaxGroupItem", back_populates="tax_group", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "group_code", name="uq_tenant_tax_group_code"),
    )

class TaxGroupItem(Base, BaseModelMixin):
    __tablename__ = "tax_group_items"

    tax_group_id = Column(String(36), ForeignKey("tax_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    tax_rate_id = Column(String(36), ForeignKey("tax_rates.id", ondelete="CASCADE"), nullable=False, index=True)

    tax_group = relationship("TaxGroup", back_populates="items")
    tax_rate = relationship("TaxRate", lazy="selectin")
