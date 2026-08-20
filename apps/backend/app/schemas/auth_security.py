from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# ============================================================================
# MFA SCHEMAS
# ============================================================================

class MFAEnrollResponse(BaseModel):
    secret: str
    qr_uri: str
    recovery_codes: List[str]

class MFAVerifyActivateRequest(BaseModel):
    totp_code: str

class MFAChallengeRequest(BaseModel):
    mfa_token: str
    totp_code: Optional[str] = None
    recovery_code: Optional[str] = None

class MFADisableRequest(BaseModel):
    totp_code: str

# ============================================================================
# SESSION SCHEMAS
# ============================================================================

class UserSessionResponse(BaseModel):
    id: str
    user_id: str
    family_id: str
    device_name: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str
    expires_at: datetime
    last_active_at: datetime

# ============================================================================
# SSO SCHEMAS
# ============================================================================

class SSOConfigCreate(BaseModel):
    domain: str
    provider_type: str = "OIDC"
    issuer_url: str
    client_id: str
    client_secret: str
    is_active: bool = True
    allow_password_fallback: bool = True

class SSOConfigResponse(BaseModel):
    id: str
    tenant_id: str
    domain: str
    provider_type: str
    issuer_url: str
    client_id: str
    is_active: bool
    allow_password_fallback: bool
    created_at: datetime

class SSOInitiateResponse(BaseModel):
    auth_url: str
    state: str

class SSOCallbackRequest(BaseModel):
    code: str
    state: str
    code_verifier: Optional[str] = None
