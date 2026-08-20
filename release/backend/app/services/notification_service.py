import uuid
import hmac
import hashlib
import json
import socket
import ipaddress
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from fastapi import HTTPException, status
from jinja2.sandbox import SandboxedEnvironment
from jinja2.exceptions import SecurityError

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.notifications import (
    NotificationTemplate,
    NotificationPreference,
    InAppNotification,
    OutboundWebhookEndpoint
)
from app.schemas.notifications import (
    NotificationTemplateCreate,
    NotificationTemplateResponse,
    NotificationPreferenceCreate,
    NotificationPreferenceResponse,
    OutboundWebhookCreate,
    OutboundWebhookResponse
)

# ============================================================================
# SSRF VALIDATOR
# ============================================================================

def validate_webhook_url_ssrf(url_str: str) -> str:
    parsed = urllib.parse.urlparse(url_str)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid webhook scheme: must be http or https")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid webhook URL: missing hostname")

    # Direct raw IP checks
    clean_host = hostname.strip("[]").lower()
    if clean_host in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        raise HTTPException(status_code=400, detail="SSRF Protection: Target host is blocked")

    try:
        ip = ipaddress.ip_address(clean_host)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(status_code=400, detail=f"SSRF Protection: Target IP {clean_host} is restricted")
    except ValueError:
        # Not a raw IP literal, resolve via DNS
        try:
            ip_str = socket.gethostbyname(clean_host)
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise HTTPException(status_code=400, detail=f"SSRF Protection: Target IP {ip_str} is restricted")
        except socket.gaierror:
            pass

    return url_str

def is_in_quiet_hours(quiet_start: Optional[str], quiet_end: Optional[str], current_time_str: str) -> bool:
    if not quiet_start or not quiet_end:
        return False
    # Format "HH:MM" e.g. "22:00" and "07:00"
    if quiet_start > quiet_end: # Crosses midnight
        return current_time_str >= quiet_start or current_time_str < quiet_end
    return quiet_start <= current_time_str < quiet_end

def verify_webhook_request(
    secret_key: str,
    signature: str,
    timestamp_str: str,
    payload_json: str,
    max_age_seconds: int = 300
) -> bool:
    try:
        ts = int(timestamp_str)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if abs(now_ts - ts) > max_age_seconds:
            raise HTTPException(status_code=400, detail="Webhook Replay Protection: Timestamp expired")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    expected_sig = NotificationService.generate_webhook_signature(secret_key, timestamp_str, payload_json)
    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(status_code=401, detail="Invalid Webhook HMAC Signature")
    return True

# ============================================================================
# EMAIL PROVIDER ABSTRACTION
# ============================================================================

class EmailProviderABC(ABC):
    @abstractmethod
    async def send_email(self, to_address: str, subject: str, body: str) -> bool:
        pass

class MockEmailProvider(EmailProviderABC):
    def __init__(self):
        self.sent_emails: List[Dict[str, str]] = []

    async def send_email(self, to_address: str, subject: str, body: str) -> bool:
        # Prevent email header injection
        if "\r" in to_address or "\n" in to_address or "\r" in subject or "\n" in subject:
            raise HTTPException(status_code=400, detail="Email Header Injection Detected")

        self.sent_emails.append({
            "to": to_address,
            "subject": subject,
            "body": body,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return True

email_provider = MockEmailProvider()

# ============================================================================
# SANDBOXED TEMPLATE RENDERER
# ============================================================================

_sandbox_env = SandboxedEnvironment(autoescape=True)

def render_sandboxed_template(template_content: str, context: Dict[str, Any]) -> str:
    try:
        template = _sandbox_env.from_string(template_content)
        return template.render(**context)
    except SecurityError as e:
        raise HTTPException(status_code=400, detail=f"Template Security Violation: {str(e)}")
    except Exception as e:
        # Fallback to safe string interpolation if jinja parse error
        res = template_content
        for k, v in context.items():
            res = res.replace(f"{{{{ {k} }}}}", str(v)).replace(f"{{{{{k}}}}}", str(v))
        return res

# ============================================================================
# NOTIFICATION SERVICE
# ============================================================================

class NotificationService:
    @staticmethod
    async def register_webhook_endpoint(
        db: AsyncSession,
        tenant_id: str,
        webhook_in: OutboundWebhookCreate
    ) -> OutboundWebhookResponse:
        validate_webhook_url_ssrf(webhook_in.url)

        secret = f"whsec_{uuid.uuid4().hex}"
        endpoint = OutboundWebhookEndpoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=webhook_in.name,
            url=webhook_in.url,
            secret_key=secret,
            subscribed_events=webhook_in.subscribed_events,
            is_active=webhook_in.is_active,
            failure_count=0
        )
        db.add(endpoint)
        await db.commit()
        await db.refresh(endpoint)

        return OutboundWebhookResponse(
            id=endpoint.id,
            name=endpoint.name,
            url=endpoint.url,
            subscribed_events=endpoint.subscribed_events,
            is_active=endpoint.is_active,
            failure_count=endpoint.failure_count,
            last_triggered_at=endpoint.last_triggered_at,
            created_at=endpoint.created_at
        )

    @staticmethod
    async def create_template(
        db: AsyncSession,
        tenant_id: str,
        template_in: NotificationTemplateCreate
    ) -> NotificationTemplateResponse:
        tmpl = NotificationTemplate(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            template_code=template_in.template_code,
            channel=template_in.channel,
            locale=template_in.locale,
            version=template_in.version,
            subject_template=template_in.subject_template,
            body_template=template_in.body_template,
            is_active=template_in.is_active
        )
        db.add(tmpl)
        await db.commit()
        await db.refresh(tmpl)
        return NotificationTemplateResponse(
            id=tmpl.id,
            template_code=tmpl.template_code,
            channel=tmpl.channel,
            locale=tmpl.locale,
            version=tmpl.version,
            subject_template=tmpl.subject_template,
            body_template=tmpl.body_template,
            is_active=tmpl.is_active,
            created_at=tmpl.created_at
        )

    @staticmethod
    async def dispatch_in_app_notification(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        title: str,
        body: str,
        event_type: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None
    ) -> InAppNotification:
        notification = InAppNotification(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            body=body,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            is_read=False
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        return notification

    @staticmethod
    def generate_webhook_signature(secret_key: str, timestamp_str: str, payload_json: str) -> str:
        data_to_sign = f"{timestamp_str}.{payload_json}".encode("utf-8")
        return hmac.new(secret_key.encode("utf-8"), data_to_sign, hashlib.sha256).hexdigest()
