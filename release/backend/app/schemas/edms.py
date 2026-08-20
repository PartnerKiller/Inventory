from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

# ============================================================================
# DOCUMENT ATTACHMENT SCHEMAS
# ============================================================================

class DocumentAttachmentCreate(BaseModel):
    entity_type: str
    entity_id: str
    file_name: str
    mime_type: str = "application/pdf"
    file_content_base64: str

class DocumentAttachmentResponse(BaseModel):
    id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    file_name: str
    file_size: int
    mime_type: str
    sha256_hash: str
    version: int
    is_latest: bool
    uploaded_by_user_id: Optional[str] = None
    created_at: datetime

class DocumentIntegrityCheckResponse(BaseModel):
    attachment_id: str
    file_name: str
    sha256_hash: str
    is_authentic: bool
    status: str

# ============================================================================
# DOCUMENT SIGN-OFF SCHEMAS
# ============================================================================

class DocumentSignOffRequest(BaseModel):
    attachment_id: str
    sign_off_role: str
    notes: Optional[str] = None

class DocumentSignOffExecute(BaseModel):
    sign_off_id: str
    status: str = "SIGNED" # SIGNED, REJECTED
    notes: Optional[str] = None

class DocumentSignOffResponse(BaseModel):
    id: str
    tenant_id: str
    attachment_id: str
    sign_off_role: str
    signer_user_id: Optional[str] = None
    status: str
    digital_signature: Optional[str] = None
    notes: Optional[str] = None
    signed_at: Optional[datetime] = None
    created_at: datetime
