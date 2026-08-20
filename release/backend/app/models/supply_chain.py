import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class SupplyChainNode(Base, BaseModelMixin):
    __tablename__ = "supply_chain_nodes"

    tenant_id = Column(String(36), nullable=False, index=True)
    node_code = Column(String(50), unique=True, index=True, nullable=False) # e.g. DC-CENTRAL, DC-EAST, STORE-101
    node_name = Column(String(150), nullable=False)
    node_type = Column(String(30), nullable=False) # CENTRAL_DC, REGIONAL_DC, WAREHOUSE, RETAIL_EDGE, SUPPLIER
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=True, index=True)
    parent_node_id = Column(String(36), ForeignKey("supply_chain_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_time_days = Column(Integer, default=1, nullable=False)
    sourcing_priority = Column(Integer, default=1, nullable=False) # 1 = Highest, 2 = Secondary, etc.
    is_active = Column(Boolean, default=True, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")
    parent_node = relationship("SupplyChainNode", remote_side="SupplyChainNode.id", lazy="selectin")

    __table_args__ = (
        Index("idx_node_tenant_type", "tenant_id", "node_type"),
    )

class TransferOrder(Base, BaseModelMixin):
    __tablename__ = "transfer_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    transfer_number = Column(String(50), unique=True, index=True, nullable=False) # TRF-YYYYMMDD-XXXX
    source_warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    destination_warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    in_transit_bin_id = Column(String(36), ForeignKey("location_bins.id", ondelete="CASCADE"), nullable=False)
    destination_bin_id = Column(String(36), ForeignKey("location_bins.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, APPROVED, IN_TRANSIT, PARTIALLY_RECEIVED, COMPLETED, CANCELLED
    freight_charge = Column(Numeric(18, 4), default=0.0, nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    carrier_tracking_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id], lazy="selectin")
    destination_warehouse = relationship("Warehouse", foreign_keys=[destination_warehouse_id], lazy="selectin")
    in_transit_bin = relationship("LocationBin", foreign_keys=[in_transit_bin_id], lazy="selectin")
    destination_bin = relationship("LocationBin", foreign_keys=[destination_bin_id], lazy="selectin")
    lines = relationship("TransferOrderLine", back_populates="transfer_order", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_trf_tenant_status", "tenant_id", "status"),
    )

class TransferOrderLine(Base, BaseModelMixin):
    __tablename__ = "transfer_order_lines"

    transfer_order_id = Column(String(36), ForeignKey("transfer_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity_requested = Column(Numeric(18, 4), nullable=False)
    quantity_shipped = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_received = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_damaged = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)

    transfer_order = relationship("TransferOrder", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")

class EdgeSyncBatch(Base, BaseModelMixin):
    __tablename__ = "edge_sync_batches"

    tenant_id = Column(String(36), nullable=False, index=True)
    batch_id = Column(String(64), unique=True, index=True, nullable=False)
    device_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    mutation_count = Column(Integer, default=0, nullable=False)
    status = Column(String(30), default="PROCESSED", nullable=False) # PROCESSED, PARTIAL_CONFLICT, REJECTED
    hmac_signature = Column(String(256), nullable=True)
    processed_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
