import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class FixedAssetClass(Base, BaseModelMixin):
    __tablename__ = "fixed_asset_classes"

    tenant_id = Column(String(36), nullable=False, index=True)
    class_code = Column(String(50), nullable=False, index=True) # BUILDINGS, PLANT_MACHINERY, VEHICLES, COMPUTERS_IT, FURNITURE_FIXTURES
    class_name = Column(String(100), nullable=False)
    depreciation_method = Column(String(30), default="STRAIGHT_LINE", nullable=False) # STRAIGHT_LINE, WRITTEN_DOWN_VALUE
    useful_life_months = Column(Integer, default=60, nullable=False) # e.g. 60 months (5 years)
    depreciation_rate_annual = Column(Numeric(10, 4), default=0.0, nullable=False) # e.g. 20.0000 %
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    assets = relationship("FixedAsset", back_populates="asset_class", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "class_code", name="uq_tenant_asset_class_code"),
    )

class FixedAsset(Base, BaseModelMixin):
    __tablename__ = "fixed_assets"

    tenant_id = Column(String(36), nullable=False, index=True)
    asset_code = Column(String(50), nullable=False, index=True) # AST-2026-0001
    asset_name = Column(String(150), nullable=False)
    asset_class_id = Column(String(36), ForeignKey("fixed_asset_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True, index=True)
    serial_number = Column(String(100), nullable=True)
    source_po_id = Column(String(36), nullable=True, index=True)
    source_grn_id = Column(String(36), nullable=True, index=True)
    purchase_cost = Column(Numeric(18, 4), nullable=False)
    salvage_value = Column(Numeric(18, 4), default=0.0, nullable=False)
    acquisition_date = Column(Date, nullable=False)
    depreciation_start_date = Column(Date, nullable=False)
    depreciation_method = Column(String(30), default="STRAIGHT_LINE", nullable=False)
    useful_life_months = Column(Integer, default=60, nullable=False)
    depreciation_rate_annual = Column(Numeric(10, 4), default=0.0, nullable=False)
    current_book_value = Column(Numeric(18, 4), nullable=False)
    accumulated_depreciation = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # DRAFT, ACTIVE, DEPRECIATING, FULLY_DEPRECIATED, DISPOSED, SCRAPPED
    disposal_date = Column(Date, nullable=True)
    disposal_amount = Column(Numeric(18, 4), nullable=True)
    notes = Column(Text, nullable=True)

    asset_class = relationship("FixedAssetClass", back_populates="assets", lazy="selectin")
    schedule_entries = relationship("DepreciationScheduleEntry", back_populates="asset", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_code", name="uq_tenant_asset_code"),
    )

class DepreciationScheduleEntry(Base, BaseModelMixin):
    __tablename__ = "depreciation_schedule_entries"

    tenant_id = Column(String(36), nullable=False, index=True)
    fixed_asset_id = Column(String(36), ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    period_code = Column(String(50), nullable=False, index=True) # e.g. 2026-01
    scheduled_date = Column(Date, nullable=False)
    depreciation_amount = Column(Numeric(18, 4), nullable=False)
    accumulated_depreciation_after = Column(Numeric(18, 4), nullable=False)
    remaining_book_value_after = Column(Numeric(18, 4), nullable=False)
    status = Column(String(30), default="SCHEDULED", nullable=False) # SCHEDULED, POSTED, SKIPPED
    posted_at = Column(DateTime(timezone=True), nullable=True)
    journal_voucher_id = Column(String(36), ForeignKey("journal_vouchers.id"), nullable=True)

    asset = relationship("FixedAsset", back_populates="schedule_entries", lazy="selectin")
    journal_voucher = relationship("JournalVoucher", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("fixed_asset_id", "period_code", name="uq_asset_period_depreciation"),
    )

class AssetImprovement(Base, BaseModelMixin):
    __tablename__ = "asset_improvements"

    tenant_id = Column(String(36), nullable=False, index=True)
    asset_id = Column(String(36), ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    mwo_id = Column(String(36), nullable=True, index=True)
    improvement_name = Column(String(150), nullable=False)
    capitalized_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    useful_life_extension_months = Column(Integer, default=0, nullable=False)
    capitalization_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    status = Column(String(30), default="CAPITALIZED", nullable=False) # CAPITALIZED, VOIDED
    journal_voucher_id = Column(String(36), ForeignKey("journal_vouchers.id", ondelete="SET NULL"), nullable=True)

    asset = relationship("FixedAsset", lazy="selectin")
    journal_voucher = relationship("JournalVoucher", lazy="selectin")
