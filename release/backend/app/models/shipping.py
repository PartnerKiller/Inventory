import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class CarrierAccount(Base, BaseModelMixin):
    __tablename__ = "carrier_accounts"

    tenant_id = Column(String(36), nullable=False, index=True)
    carrier_code = Column(String(50), nullable=False, index=True) # FEDEX, UPS, DHL, USPS, SHIPPO, EASYPOST, MOCK_EXPRESS
    account_name = Column(String(100), nullable=False)
    account_number = Column(String(100), nullable=True)
    api_key = Column(String(255), nullable=False)
    api_secret = Column(String(255), nullable=True)
    is_sandbox = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    default_service_level = Column(String(50), nullable=True)
    webhook_secret = Column(String(255), nullable=True)

    service_levels = relationship("ShippingServiceLevel", back_populates="account", cascade="all, delete-orphan", lazy="selectin")
    manifests = relationship("CarrierManifest", back_populates="account", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "carrier_code", "account_name", name="uq_carrier_account_name"),
    )

class ShippingServiceLevel(Base, BaseModelMixin):
    __tablename__ = "shipping_service_levels"

    tenant_id = Column(String(36), nullable=False, index=True)
    carrier_account_id = Column(String(36), ForeignKey("carrier_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    service_code = Column(String(50), nullable=False) # GROUND, EXPRESS_2DAY, OVERNIGHT
    service_name = Column(String(100), nullable=False)
    transit_days_estimate = Column(Integer, nullable=True)
    is_international = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    account = relationship("CarrierAccount", back_populates="service_levels")

    __table_args__ = (
        UniqueConstraint("carrier_account_id", "service_code", name="uq_account_service_code"),
    )

class ShipmentPackage(Base, BaseModelMixin):
    __tablename__ = "shipment_packages"

    tenant_id = Column(String(36), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    package_number = Column(Integer, default=1, nullable=False)
    package_type = Column(String(30), default="CUSTOM_BOX", nullable=False) # ENVELOPE, SMALL_BOX, MEDIUM_BOX, LARGE_BOX, PALLET, CUSTOM_BOX
    
    # Weight and Dimensions
    weight_kg = Column(Numeric(10, 3), nullable=False)
    length_cm = Column(Numeric(10, 2), nullable=False)
    width_cm = Column(Numeric(10, 2), nullable=False)
    height_cm = Column(Numeric(10, 2), nullable=False)
    dimensional_weight_kg = Column(Numeric(10, 3), nullable=False)
    
    # Logistics Identifiers
    tracking_number = Column(String(100), nullable=True, index=True)
    carrier_package_id = Column(String(100), nullable=True)
    label_format = Column(String(10), default="PDF", nullable=False) # PDF, ZPL, PNG
    label_url = Column(String(500), nullable=True)
    label_base64 = Column(Text, nullable=True) # For offline thermal printing

    shipment = relationship("Shipment", lazy="selectin")
    items = relationship("ShipmentPackageItem", back_populates="package", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_pkg_tenant_tracking", "tenant_id", "tracking_number"),
    )

class ShipmentPackageItem(Base, BaseModelMixin):
    __tablename__ = "shipment_package_items"

    package_id = Column(String(36), ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    serial_number = Column(String(100), nullable=True)
    batch_number = Column(String(100), nullable=True)

    package = relationship("ShipmentPackage", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")

class ShipmentTrackingEvent(Base, BaseModelMixin):
    __tablename__ = "shipment_tracking_events"

    tenant_id = Column(String(36), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id"), nullable=False, index=True)
    tracking_number = Column(String(100), nullable=False, index=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)
    carrier_status = Column(String(50), nullable=False)
    normalized_status = Column(String(30), nullable=False) # LABEL_CREATED, PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, EXCEPTION, RETURNED
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)

    shipment = relationship("Shipment", lazy="selectin")

    __table_args__ = (
        Index("idx_trk_event_tenant_track", "tenant_id", "tracking_number"),
        Index("idx_trk_event_time", "shipment_id", "event_timestamp"),
    )

class CarrierManifest(Base, BaseModelMixin):
    __tablename__ = "carrier_manifests"

    tenant_id = Column(String(36), nullable=False, index=True)
    manifest_number = Column(String(50), unique=True, index=True, nullable=False) # MNF-YYYYMMDD-XXXX
    carrier_account_id = Column(String(36), ForeignKey("carrier_accounts.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    manifest_url = Column(String(500), nullable=True)
    total_packages = Column(Integer, default=0, nullable=False)
    total_weight_kg = Column(Numeric(10, 3), default=0.0, nullable=False)
    status = Column(String(30), default="GENERATED", nullable=False) # GENERATED, SUBMITTED, CLOSED

    account = relationship("CarrierAccount", back_populates="manifests")
    warehouse = relationship("Warehouse", lazy="selectin")
