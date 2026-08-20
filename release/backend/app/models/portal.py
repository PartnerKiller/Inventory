import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class PortalUser(Base, BaseModelMixin):
    __tablename__ = "portal_users"

    tenant_id = Column(String(36), nullable=False, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    portal_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    is_active = Column(Boolean, default=True, nullable=False)
    mfa_secret = Column(String(100), nullable=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    memberships = relationship("PortalUserMembership", back_populates="portal_user", cascade="all, delete-orphan", lazy="selectin")

class PortalUserMembership(Base, BaseModelMixin):
    __tablename__ = "portal_user_memberships"

    portal_user_id = Column(String(36), ForeignKey("portal_users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    entity_id = Column(String(36), nullable=False, index=True) # customer_id or supplier_id
    role = Column(String(30), default="MEMBER", nullable=False) # ADMIN, MEMBER, VIEWER
    is_active = Column(Boolean, default=True, nullable=False)

    portal_user = relationship("PortalUser", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("portal_user_id", "entity_type", "entity_id", name="uq_portal_user_entity"),
        Index("idx_portal_membership_entity", "tenant_id", "entity_type", "entity_id"),
    )

class PortalInvitation(Base, BaseModelMixin):
    __tablename__ = "portal_invitations"

    tenant_id = Column(String(36), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    entity_id = Column(String(36), nullable=False, index=True)
    role = Column(String(30), default="MEMBER", nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_user_id = Column(String(36), nullable=True)

class AdvanceShippingNotice(Base, BaseModelMixin):
    __tablename__ = "advance_shipping_notices"

    tenant_id = Column(String(36), nullable=False, index=True)
    asn_number = Column(String(50), unique=True, index=True, nullable=False) # ASN-YYYYMMDD-XXXX
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    carrier_code = Column(String(50), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    estimated_arrival_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), default="SUBMITTED", nullable=False) # SUBMITTED, IN_TRANSIT, RECEIVED, REJECTED
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")
    lines = relationship("ASNLineItem", back_populates="asn", cascade="all, delete-orphan", lazy="selectin")

class ASNLineItem(Base, BaseModelMixin):
    __tablename__ = "asn_line_items"

    asn_id = Column(String(36), ForeignKey("advance_shipping_notices.id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(36), ForeignKey("purchase_order_lines.id"), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    quantity_shipped = Column(Numeric(18, 4), nullable=False)
    lot_number = Column(String(100), nullable=True)
    serial_numbers = Column(JSON, nullable=True)

    asn = relationship("AdvanceShippingNotice", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
