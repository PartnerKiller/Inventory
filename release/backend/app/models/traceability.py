import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class StockLot(Base, BaseModelMixin):
    __tablename__ = "stock_lots"

    tenant_id = Column(String(36), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_number = Column(String(100), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=True, index=True)
    supplier_lot_number = Column(String(100), nullable=True)
    origin_grn_id = Column(String(36), ForeignKey("goods_receipts.id"), nullable=True, index=True)
    cost_layer_id = Column(String(36), ForeignKey("cost_layers.id"), nullable=True, index=True)
    manufacturing_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True, index=True)
    best_before_date = Column(Date, nullable=True)
    initial_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    current_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # ACTIVE, QUARANTINED, RECALLED, EXPIRED, DEPLETED
    quarantine_reason = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    variant = relationship("ItemVariant", lazy="selectin")
    supplier = relationship("Supplier", lazy="selectin")
    origin_grn = relationship("GoodsReceipt", lazy="selectin")
    cost_layer = relationship("CostLayer", lazy="selectin")
    serials = relationship("ItemSerialNumber", back_populates="lot", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "lot_number", name="uq_tenant_variant_lot"),
        CheckConstraint("current_quantity >= 0", name="chk_lot_qty_non_negative"),
        Index("idx_lots_tenant_expiry", "tenant_id", "expiry_date"),
        Index("idx_lots_tenant_status", "tenant_id", "status"),
    )

class ItemSerialNumber(Base, BaseModelMixin):
    __tablename__ = "item_serial_numbers"

    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(String(36), ForeignKey("stock_lots.id", ondelete="SET NULL"), nullable=True, index=True)
    serial_number = Column(String(100), nullable=False, index=True)
    status = Column(String(30), default="IN_STOCK", nullable=False) # RECEIVED, IN_STOCK, ALLOCATED, PICKED, DISPATCHED, RETURNED, QUARANTINED, RETURNED_TO_SUPPLIER, RETIRED
    location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=True, index=True)
    origin_grn_id = Column(String(36), ForeignKey("goods_receipts.id"), nullable=True, index=True)
    dispatched_shipment_id = Column(String(36), ForeignKey("shipments.id"), nullable=True, index=True)
    quarantine_reason = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    warehouse = relationship("Warehouse", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    lot = relationship("StockLot", back_populates="serials", lazy="selectin")
    bin = relationship("LocationBin", lazy="selectin")
    origin_grn = relationship("GoodsReceipt", lazy="selectin")
    shipment = relationship("Shipment", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "serial_number", name="uq_tenant_variant_serial"),
        Index("idx_serials_tenant_status", "tenant_id", "status"),
        Index("idx_serials_tenant_warehouse", "tenant_id", "warehouse_id"),
    )
