from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class StockBatch(Base, BaseModelMixin):
    __tablename__ = "stock_batches"

    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_number = Column(String(100), nullable=False, index=True)
    manufacturing_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    cost_per_unit = Column(Numeric(18, 4), default=0.0, nullable=False)

    __table_args__ = (
        UniqueConstraint('item_variant_id', 'batch_number', name='uq_variant_batch'),
        CheckConstraint('cost_per_unit >= 0', name='chk_batch_cost_non_negative'),
    )

class StockLedgerTransaction(Base, BaseModelMixin):
    __tablename__ = "stock_ledger_transactions"

    tenant_id = Column(String(36), nullable=False, index=True)
    transaction_number = Column(String(100), unique=True, index=True, nullable=False)
    transaction_type = Column(String(50), nullable=False) # PURCHASE_RECEIPT, SALES_SHIPMENT, TRANSFER_IN, TRANSFER_OUT, INVENTORY_ADJUSTMENT, SCRAP, CYCLE_COUNT
    reference_document_type = Column(String(50), nullable=True) # PURCHASE_ORDER, SALES_ORDER, TRANSFER_ORDER, MANUAL_ADJUSTMENT
    reference_document_id = Column(String(36), nullable=True, index=True)
    posted_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)

    entries = relationship("StockLedgerEntry", back_populates="transaction", cascade="all, delete-orphan", lazy="selectin")
    posted_by = relationship("User", foreign_keys=[posted_by_user_id], lazy="selectin")

    __table_args__ = (
        Index("idx_tx_tenant_posted_at", "tenant_id", "posted_at"),
    )

class StockLedgerEntry(Base, BaseModelMixin):
    __tablename__ = "stock_ledger_entries"

    transaction_id = Column(String(36), ForeignKey("stock_ledger_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    batch_id = Column(String(36), ForeignKey("stock_batches.id"), nullable=True)
    lot_id = Column(String(36), ForeignKey("stock_lots.id"), nullable=True, index=True)
    serial_number = Column(String(100), nullable=True)
    source_location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=True, index=True)
    destination_location_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=True, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    uom = Column(String(20), default="PCS", nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    entry_timestamp = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    transaction = relationship("StockLedgerTransaction", back_populates="entries")
    variant = relationship("ItemVariant", lazy="selectin")
    batch = relationship("StockBatch", lazy="selectin")
    lot = relationship("StockLot", lazy="selectin")
    source_bin = relationship("LocationBin", foreign_keys=[source_location_bin_id], lazy="selectin")
    destination_bin = relationship("LocationBin", foreign_keys=[destination_location_bin_id], lazy="selectin")

    __table_args__ = (
        CheckConstraint('quantity > 0', name='chk_ledger_quantity_positive'),
        CheckConstraint('unit_cost >= 0', name='chk_ledger_unit_cost_non_negative'),
        Index("idx_ledger_variant_time", "item_variant_id", "entry_timestamp"),
        Index("idx_ledger_tx_id", "transaction_id"),
    )

class StockBalanceCache(Base, BaseModelMixin):
    __tablename__ = "stock_balance_cache"

    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    location_bin_id = Column(String(36), ForeignKey("location_bins.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(36), ForeignKey("stock_batches.id"), nullable=True)
    lot_id = Column(String(36), ForeignKey("stock_lots.id"), nullable=True, index=True)
    quantity_on_hand = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_allocated = Column(Numeric(18, 4), default=0.0, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")
    bin = relationship("LocationBin", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    batch = relationship("StockBatch", lazy="selectin")
    lot = relationship("StockLot", lazy="selectin")

    __table_args__ = (
        UniqueConstraint('location_bin_id', 'item_variant_id', 'batch_id', 'lot_id', name='uq_bin_variant_batch_lot'),
        CheckConstraint('quantity_on_hand >= 0', name='chk_stock_on_hand_non_negative'),
        CheckConstraint('quantity_allocated >= 0', name='chk_stock_allocated_non_negative'),
        CheckConstraint('quantity_on_hand >= quantity_allocated', name='chk_stock_available_non_negative'),
        Index("idx_stock_balance_lookup", "warehouse_id", "item_variant_id"),
    )
