import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, DateTime, JSON, Text, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class UserMFASecurity(Base, BaseModelMixin):
    __tablename__ = "user_mfa_security"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_type = Column(String(30), default="INTERNAL", nullable=False) # INTERNAL, PORTAL_CUSTOMER, PORTAL_SUPPLIER
    user_id = Column(String(36), nullable=False, index=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret = Column(String(100), nullable=True) # Base32 secret
    last_totp_timestep = Column(Integer, default=0, nullable=False) # Replay protection
    enrolled_at = Column(DateTime(timezone=True), nullable=True)

    recovery_codes = relationship("MFARecoveryCode", back_populates="mfa_security", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_type", "user_id", name="uq_user_mfa"),
        Index("idx_mfa_tenant_user", "tenant_id", "user_type", "user_id"),
    )

class MFARecoveryCode(Base, BaseModelMixin):
    __tablename__ = "mfa_recovery_codes"

    mfa_security_id = Column(String(36), ForeignKey("user_mfa_security.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    mfa_security = relationship("UserMFASecurity", back_populates="recovery_codes")

    __table_args__ = (
        Index("idx_mfa_code_user_used", "user_id", "is_used"),
    )

class UserSessionRecord(Base, BaseModelMixin):
    __tablename__ = "user_sessions"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_type = Column(String(30), default="INTERNAL", nullable=False) # INTERNAL, PORTAL_CUSTOMER, PORTAL_SUPPLIER
    user_id = Column(String(36), nullable=False, index=True)
    family_id = Column(String(36), nullable=False, index=True) # Cryptographic token family
    refresh_token_hash = Column(String(255), unique=True, nullable=False, index=True)
    device_name = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    status = Column(String(20), default="ACTIVE", nullable=False) # ACTIVE, USED, REVOKED
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_active_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    __table_args__ = (
        Index("idx_session_tenant_user_family", "tenant_id", "user_id", "family_id"),
    )

class SSOConfiguration(Base, BaseModelMixin):
    __tablename__ = "sso_configurations"

    tenant_id = Column(String(36), nullable=False, unique=True, index=True)
    domain = Column(String(100), nullable=False, unique=True, index=True) # e.g. acme.com
    provider_type = Column(String(30), default="OIDC", nullable=False) # OIDC, SAML2
    issuer_url = Column(String(2048), nullable=False)
    client_id = Column(String(255), nullable=False)
    client_secret = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    allow_password_fallback = Column(Boolean, default=True, nullable=False)
