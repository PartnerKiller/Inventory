from sqlalchemy import Column, String, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin

class Warehouse(Base, BaseModelMixin):
    __tablename__ = "warehouses"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    bins = relationship("LocationBin", back_populates="warehouse", cascade="all, delete-orphan", lazy="selectin")

class LocationBin(Base, BaseModelMixin):
    __tablename__ = "location_bins"

    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True)
    aisle = Column(String(20), default="A", nullable=False)
    rack = Column(String(20), default="01", nullable=False)
    shelf = Column(String(20), default="01", nullable=False)
    bin = Column(String(20), default="01", nullable=False)
    type = Column(String(50), default="STORAGE", nullable=False) # STORAGE, RECEIVING, SHIPPING, STAGING, DAMAGE, VIRTUAL_ADJUSTMENT
    is_active = Column(Boolean, default=True, nullable=False)

    warehouse = relationship("Warehouse", back_populates="bins")
