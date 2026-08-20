from sqlalchemy import Column, String, Boolean, Float, DateTime
from app.core.database import Base
from app.models.base import BaseModelMixin, generate_uuid, get_utc_now

class SystemSetting(Base, BaseModelMixin):
    __tablename__ = "system_settings"

    tenant_id = Column(String(36), unique=True, nullable=False, index=True)
    company_name = Column(String(255), default="AuraStock Enterprise", nullable=False)
    company_email = Column(String(255), nullable=True)
    company_phone = Column(String(50), nullable=True)
    logo_url = Column(String(500), nullable=True)
    currency = Column(String(10), default="USD", nullable=False)
    timezone = Column(String(50), default="UTC", nullable=False)
    date_format = Column(String(20), default="YYYY-MM-DD", nullable=False)

    default_warehouse_id = Column(String(36), nullable=True)
    default_receiving_bin_id = Column(String(36), nullable=True)
    default_damage_bin_id = Column(String(36), nullable=True)

    allow_negative_stock = Column(Boolean, default=False, nullable=False)
    auto_allocate_on_confirm = Column(Boolean, default=False, nullable=False)
    require_grn_inspection = Column(Boolean, default=False, nullable=False)

    default_payment_terms = Column(String(50), default="NET_30", nullable=False)
    default_tax_pct = Column(Float, default=0.0, nullable=False)
    require_po_approval = Column(Boolean, default=True, nullable=False)
    po_approval_threshold = Column(Float, default=1000.0, nullable=False)
