from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, JSON, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin

class ItemCategory(Base, BaseModelMixin):
    __tablename__ = "item_categories"

    tenant_id = Column(String(36), nullable=False, index=True)
    parent_id = Column(String(36), ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)

    items = relationship("Item", back_populates="category")

class Item(Base, BaseModelMixin):
    __tablename__ = "items"

    tenant_id = Column(String(36), nullable=False, index=True)
    category_id = Column(String(36), ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    base_uom = Column(String(20), default="PCS", nullable=False) # PCS, KG, BOX, MTR, LTR
    valuation_method = Column(String(20), default="FIFO", nullable=False) # FIFO, WEIGHTED_AVERAGE, STANDARD_COST
    reorder_point = Column(Numeric(15, 4), default=10, nullable=False)
    reorder_quantity = Column(Numeric(15, 4), default=50, nullable=False)
    is_batch_tracked = Column(Boolean, default=False, nullable=False)
    is_serial_tracked = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    category = relationship("ItemCategory", back_populates="items", lazy="selectin")
    variants = relationship("ItemVariant", back_populates="item", cascade="all, delete-orphan", lazy="selectin")
    uom_conversions = relationship("UomConversion", back_populates="item", cascade="all, delete-orphan", lazy="selectin")

class ItemVariant(Base, BaseModelMixin):
    __tablename__ = "item_variants"

    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_sku = Column(String(100), unique=True, index=True, nullable=False)
    variant_name = Column(String(255), nullable=False)
    attributes = Column(JSON, default=dict, nullable=False)
    cost_price = Column(Numeric(18, 4), default=0.0, nullable=False)
    selling_price = Column(Numeric(18, 4), default=0.0, nullable=False)

    item = relationship("Item", back_populates="variants", lazy="selectin")
    barcodes = relationship("Barcode", back_populates="variant", cascade="all, delete-orphan", lazy="selectin")

class Barcode(Base, BaseModelMixin):
    __tablename__ = "barcodes"

    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    barcode_value = Column(String(128), unique=True, index=True, nullable=False)
    symbology = Column(String(50), default="CODE128", nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    variant = relationship("ItemVariant", back_populates="barcodes")

class UomConversion(Base, BaseModelMixin):
    __tablename__ = "uom_conversions"

    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    from_uom = Column(String(20), nullable=False)
    to_uom = Column(String(20), nullable=False)
    conversion_factor = Column(Numeric(18, 6), default=1.0, nullable=False)

    item = relationship("Item", back_populates="uom_conversions")
