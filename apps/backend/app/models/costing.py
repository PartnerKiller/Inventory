from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class CostLayer(Base, BaseModelMixin):
    __tablename__ = "cost_layers"

    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    origin_transaction_id = Column(String(36), ForeignKey("stock_ledger_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    source_layer_id = Column(String(36), ForeignKey("cost_layers.id", ondelete="SET NULL"), nullable=True, index=True)
    layer_number = Column(String(100), unique=True, index=True, nullable=False)
    original_quantity = Column(Numeric(18, 4), nullable=False)
    remaining_quantity = Column(Numeric(18, 4), nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False) # ACTIVE, DEPLETED, CANCELLED
    layer_timestamp = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)

    warehouse = relationship("Warehouse", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    origin_transaction = relationship("StockLedgerTransaction", foreign_keys=[origin_transaction_id], lazy="selectin")
    source_layer = relationship("CostLayer", foreign_keys=[source_layer_id], remote_side="CostLayer.id", lazy="selectin")
    consumptions = relationship("CostLayerConsumption", back_populates="cost_layer", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint('original_quantity > 0', name='chk_cost_layer_original_qty_positive'),
        CheckConstraint('remaining_quantity >= 0', name='chk_cost_layer_remaining_qty_non_negative'),
        CheckConstraint('remaining_quantity <= original_quantity', name='chk_cost_layer_remaining_lte_original'),
        CheckConstraint('unit_cost >= 0', name='chk_cost_layer_unit_cost_non_negative'),
        CheckConstraint('total_cost >= 0', name='chk_cost_layer_total_cost_non_negative'),
        Index("idx_fifo_lookup", "tenant_id", "warehouse_id", "item_variant_id", "status", "layer_timestamp"),
    )

class CostLayerConsumption(Base, BaseModelMixin):
    __tablename__ = "cost_layer_consumptions"

    tenant_id = Column(String(36), nullable=False, index=True)
    cost_layer_id = Column(String(36), ForeignKey("cost_layers.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_transaction_id = Column(String(36), ForeignKey("cost_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity_consumed = Column(Numeric(18, 4), nullable=False)
    unit_cost = Column(Numeric(18, 4), nullable=False)
    total_cost = Column(Numeric(18, 4), nullable=False)
    consumed_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    cost_layer = relationship("CostLayer", back_populates="consumptions", lazy="selectin")
    cost_transaction = relationship("CostTransaction", back_populates="consumptions", lazy="selectin")

    __table_args__ = (
        CheckConstraint('quantity_consumed > 0', name='chk_consumption_qty_positive'),
        CheckConstraint('unit_cost >= 0', name='chk_consumption_unit_cost_non_negative'),
        CheckConstraint('total_cost >= 0', name='chk_consumption_total_cost_non_negative'),
        Index("idx_consumption_layer_time", "cost_layer_id", "consumed_at"),
    )

class ItemCostProfile(Base, BaseModelMixin):
    __tablename__ = "item_cost_profiles"

    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    costing_method = Column(String(30), default="FIFO", nullable=False) # FIFO, WEIGHTED_AVERAGE, STANDARD_COST
    current_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    current_total_value = Column(Numeric(18, 4), default=0.0, nullable=False)
    moving_average_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    standard_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    last_cost_recalculated_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")

    __table_args__ = (
        UniqueConstraint('tenant_id', 'warehouse_id', 'item_variant_id', name='uq_tenant_wh_variant_cost_profile'),
        CheckConstraint('current_quantity >= 0', name='chk_profile_qty_non_negative'),
        CheckConstraint('current_total_value >= 0', name='chk_profile_total_value_non_negative'),
        CheckConstraint('moving_average_cost >= 0', name='chk_profile_avg_cost_non_negative'),
        CheckConstraint('standard_cost >= 0', name='chk_profile_std_cost_non_negative'),
        Index("idx_cost_profile_lookup", "tenant_id", "warehouse_id", "item_variant_id"),
    )

class CostTransaction(Base, BaseModelMixin):
    __tablename__ = "cost_transactions"

    tenant_id = Column(String(36), nullable=False, index=True)
    stock_transaction_id = Column(String(36), ForeignKey("stock_ledger_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    cost_transaction_number = Column(String(100), unique=True, index=True, nullable=False)
    transaction_type = Column(String(50), nullable=False) # RECEIPT_COST, DISPATCH_COGS, TRANSFER_COST, ADJUSTMENT_COST, RETURN_COST, OPENING_STOCK
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="SET NULL"), nullable=True, index=True)
    quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_cost_impact = Column(Numeric(18, 4), default=0.0, nullable=False)
    costing_method = Column(String(30), default="FIFO", nullable=False)
    posted_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    posted_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    warehouse = relationship("Warehouse", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")
    stock_transaction = relationship("StockLedgerTransaction", lazy="selectin")
    posted_by = relationship("User", foreign_keys=[posted_by_user_id], lazy="selectin")
    consumptions = relationship("CostLayerConsumption", back_populates="cost_transaction", cascade="all, delete-orphan", lazy="selectin")
    cogs_records = relationship("COGSRecord", back_populates="cost_transaction", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_cost_tx_tenant_posted", "tenant_id", "posted_at"),
    )

class COGSRecord(Base, BaseModelMixin):
    __tablename__ = "cogs_records"

    tenant_id = Column(String(36), nullable=False, index=True)
    sales_order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_transaction_id = Column(String(36), ForeignKey("cost_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity_shipped = Column(Numeric(18, 4), nullable=False)
    unit_cogs = Column(Numeric(18, 4), nullable=False)
    total_cogs_amount = Column(Numeric(18, 4), nullable=False)
    recognized_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    sales_order = relationship("SalesOrder", lazy="selectin")
    shipment = relationship("Shipment", lazy="selectin")
    cost_transaction = relationship("CostTransaction", back_populates="cogs_records", lazy="selectin")
    variant = relationship("ItemVariant", lazy="selectin")

    __table_args__ = (
        CheckConstraint('quantity_shipped > 0', name='chk_cogs_qty_positive'),
        CheckConstraint('unit_cogs >= 0', name='chk_cogs_unit_cogs_non_negative'),
        CheckConstraint('total_cogs_amount >= 0', name='chk_cogs_total_amount_non_negative'),
        Index("idx_cogs_so_shipment", "sales_order_id", "shipment_id"),
        Index("idx_cogs_tenant_recognized", "tenant_id", "recognized_at"),
    )
