from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# ============================================================================
# DOMAIN EVENT ENVELOPE
# ============================================================================

class DomainEventEnvelope(BaseModel):
    event_id: str
    event_type: str
    version: str = "1.0"
    tenant_id: str
    entity_type: str
    entity_id: str
    occurred_at: datetime
    correlation_id: Optional[str] = None
    actor_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

# ============================================================================
# TEMPLATE SCHEMAS
# ============================================================================

class NotificationTemplateCreate(BaseModel):
    template_code: str
    channel: str # EMAIL, IN_APP, WEBHOOK, SYSTEM
    locale: str = "en"
    version: int = 1
    subject_template: Optional[str] = None
    body_template: str
    is_active: bool = True

class NotificationTemplateResponse(BaseModel):
    id: str
    template_code: str
    channel: str
    locale: str
    version: int
    subject_template: Optional[str] = None
    body_template: str
    is_active: bool
    created_at: datetime

# ============================================================================
# PREFERENCE SCHEMAS
# ============================================================================

class NotificationPreferenceCreate(BaseModel):
    user_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    event_category: str # INVENTORY, SALES, PURCHASING, FINANCE, SECURITY
    email_enabled: bool = True
    in_app_enabled: bool = True
    webhook_enabled: bool = True
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

class NotificationPreferenceResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    event_category: str
    email_enabled: bool
    in_app_enabled: bool
    webhook_enabled: bool
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

# ============================================================================
# IN-APP NOTIFICATION SCHEMAS
# ============================================================================

class InAppNotificationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    body: str
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

class InAppNotificationMarkReadRequest(BaseModel):
    notification_ids: List[str]

# ============================================================================
# OUTBOUND WEBHOOK SCHEMAS
# ============================================================================

class OutboundWebhookCreate(BaseModel):
    name: str
    url: str
    subscribed_events: List[str] # ["sales.*", "inventory.stock.low"]
    is_active: bool = True

class OutboundWebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    subscribed_events: List[str]
    is_active: bool
    failure_count: int
    last_triggered_at: Optional[datetime] = None
    created_at: datetime

# ============================================================================
# BACKGROUND JOB SCHEMAS
# ============================================================================

class BackgroundJobCreate(BaseModel):
    job_type: str = "IMMEDIATE" # IMMEDIATE, DELAYED, RECURRING
    task_name: str
    payload_json: Dict[str, Any] = Field(default_factory=dict)
    scheduled_for: Optional[datetime] = None
    max_attempts: int = 5
    idempotency_key: str

class BackgroundJobResponse(BaseModel):
    id: str
    job_type: str
    task_name: str
    payload_json: Dict[str, Any]
    status: str
    attempt_count: int
    max_attempts: int
    scheduled_for: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    idempotency_key: str
    created_at: datetime
