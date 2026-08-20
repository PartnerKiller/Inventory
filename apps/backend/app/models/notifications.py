import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Integer, DateTime, JSON, Text, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class NotificationTemplate(Base, BaseModelMixin):
    __tablename__ = "notification_templates"

    tenant_id = Column(String(36), nullable=False, index=True)
    template_code = Column(String(50), nullable=False, index=True) # e.g. STOCK_LOW_ALERT, INVOICE_OVERDUE, ORDER_SHIPPED
    channel = Column(String(30), nullable=False) # EMAIL, IN_APP, WEBHOOK, SYSTEM
    locale = Column(String(10), default="en", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    subject_template = Column(String(255), nullable=True)
    body_template = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("idx_template_tenant_code_chan", "tenant_id", "template_code", "channel", "locale"),
    )

class NotificationPreference(Base, BaseModelMixin):
    __tablename__ = "notification_preferences"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    entity_type = Column(String(30), nullable=True) # CUSTOMER, SUPPLIER, INTERNAL
    entity_id = Column(String(36), nullable=True)
    event_category = Column(String(50), nullable=False) # INVENTORY, SALES, PURCHASING, FINANCE, SECURITY
    email_enabled = Column(Boolean, default=True, nullable=False)
    in_app_enabled = Column(Boolean, default=True, nullable=False)
    webhook_enabled = Column(Boolean, default=True, nullable=False)
    quiet_hours_start = Column(String(5), nullable=True) # e.g. "22:00"
    quiet_hours_end = Column(String(5), nullable=True)   # e.g. "07:00"

    __table_args__ = (
        Index("idx_pref_tenant_user_cat", "tenant_id", "user_id", "event_category"),
    )

class InAppNotification(Base, BaseModelMixin):
    __tablename__ = "in_app_notifications"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    event_type = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(36), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_inapp_tenant_user_read", "tenant_id", "user_id", "is_read"),
    )

class OutboundWebhookEndpoint(Base, BaseModelMixin):
    __tablename__ = "outbound_webhook_endpoints"

    tenant_id = Column(String(36), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(2048), nullable=False)
    secret_key = Column(String(255), nullable=False)
    subscribed_events = Column(JSON, default=list, nullable=False) # ["sales.*", "inventory.stock.low"]
    is_active = Column(Boolean, default=True, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)

class BackgroundJobRecord(Base, BaseModelMixin):
    __tablename__ = "background_jobs"

    tenant_id = Column(String(36), nullable=False, index=True)
    job_type = Column(String(50), nullable=False, index=True) # IMMEDIATE, DELAYED, RECURRING
    task_name = Column(String(100), nullable=False, index=True) # run_replenishment, check_overdue_invoices
    payload_json = Column(JSON, default=dict, nullable=False)
    status = Column(String(30), default="QUEUED", nullable=False, index=True) # QUEUED, RUNNING, SUCCEEDED, RETRYING, DEAD_LETTER, CANCELLED
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), default=get_utc_now, nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    idempotency_key = Column(String(100), index=True, nullable=False)

    __table_args__ = (
        Index("idx_jobs_tenant_status_sched", "tenant_id", "status", "scheduled_for"),
    )
