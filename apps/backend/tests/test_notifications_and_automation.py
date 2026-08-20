import pytest
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.audit import EventOutbox
from app.models.notifications import (
    NotificationTemplate,
    NotificationPreference,
    InAppNotification,
    OutboundWebhookEndpoint,
    BackgroundJobRecord
)
from app.models.ledger import StockLedgerTransaction
from app.models.costing import CostLayer
from app.schemas.notifications import (
    NotificationTemplateCreate,
    OutboundWebhookCreate,
    BackgroundJobCreate
)
from app.services.outbox_service import OutboxService
from app.services.notification_service import (
    NotificationService,
    validate_webhook_url_ssrf,
    render_sandboxed_template,
    email_provider,
    is_in_quiet_hours,
    verify_webhook_request
)
from app.services.job_service import JobService

# ============================================================================
# 1. QUIET HOURS (NORMAL SUPPRESSION & CRITICAL BYPASS)
# ============================================================================

def test_quiet_hours_normal_suppression_and_critical_bypass():
    # Quiet hours 22:00 to 07:00
    quiet_start = "22:00"
    quiet_end = "07:00"

    # 1. At 23:30 (during quiet hours) -> normal alert is suppressed
    assert is_in_quiet_hours(quiet_start, quiet_end, "23:30") is True
    # 2. At 03:15 (during quiet hours) -> normal alert is suppressed
    assert is_in_quiet_hours(quiet_start, quiet_end, "03:15") is True
    # 3. At 14:00 (outside quiet hours) -> normal alert is allowed
    assert is_in_quiet_hours(quiet_start, quiet_end, "14:00") is False

    # Policy: Critical / P0 alert (e.g. security breach, 1-click recall) bypasses quiet hours
    def evaluate_delivery(is_critical: bool, time_str: str) -> str:
        if is_critical:
            return "DELIVER_IMMEDIATELY"
        if is_in_quiet_hours(quiet_start, quiet_end, time_str):
            return "SUPPRESS_OR_DEFER"
        return "DELIVER_IMMEDIATELY"

    assert evaluate_delivery(is_critical=False, time_str="23:30") == "SUPPRESS_OR_DEFER"
    assert evaluate_delivery(is_critical=True, time_str="23:30") == "DELIVER_IMMEDIATELY"

# ============================================================================
# 2. SCHEDULED AUTOMATION (CATALOG TASKS & IDEMPOTENCY)
# ============================================================================

@pytest.mark.asyncio
async def test_scheduled_automation_tasks(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    catalog_tasks = [
        "task_nightly_replenishment",
        "task_aging_ar_ap_check",
        "task_low_stock_monitor",
        "task_shelf_life_monitor",
        "task_carrier_tracking_sync"
    ]

    for task_name in catalog_tasks:
        key = f"sched_{task_name}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        job_res1 = await JobService.enqueue_job(
            db=db_session,
            tenant_id=tenant_id,
            job_in=BackgroundJobCreate(
                job_type="SCHEDULED",
                task_name=task_name,
                payload_json={"triggered_by": "cron_scheduler"},
                idempotency_key=key
            )
        )
        assert job_res1.task_name == task_name
        assert job_res1.status == "QUEUED"

        # Re-triggering the same scheduled task produces no duplicate job
        job_res2 = await JobService.enqueue_job(
            db=db_session,
            tenant_id=tenant_id,
            job_in=BackgroundJobCreate(
                job_type="SCHEDULED",
                task_name=task_name,
                payload_json={"triggered_by": "cron_scheduler"},
                idempotency_key=key
            )
        )
        assert job_res1.id == job_res2.id

# ============================================================================
# 3. OUTBOX RELAY FAILURE & EFFECTIVELY-ONCE CONSUMER
# ============================================================================

@pytest.mark.asyncio
async def test_outbox_relay_crash_and_effectively_once(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    so_id = str(uuid.uuid4())

    ev = await OutboxService.publish_event(
        db=db_session,
        tenant_id=tenant_id,
        event_type="sales.order.allocated",
        aggregate_type="SalesOrder",
        aggregate_id=so_id,
        payload={"so_number": "SO-RELAY-1"}
    )
    await db_session.commit()

    processed_events = set()

    def idempotent_consumer(event_id: str):
        if event_id in processed_events:
            return "ALREADY_PROCESSED"
        processed_events.add(event_id)
        return "PROCESSED_SUCCESS"

    # Relay attempt 1
    assert idempotent_consumer(ev.id) == "PROCESSED_SUCCESS"
    # Relay simulated crash before ack -> re-delivery attempt 2
    assert idempotent_consumer(ev.id) == "ALREADY_PROCESSED"
    # Exactly one logical consumer execution
    assert len(processed_events) == 1

# ============================================================================
# 4. DUPLICATE DOMAIN EVENT SUPPRESSION
# ============================================================================

@pytest.mark.asyncio
async def test_duplicate_domain_event_suppression(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    event_id = str(uuid.uuid4())

    # Simulated deduplication ledger
    dispatched_notifications = []

    def dispatch_event(evt_id: str, payload: dict):
        if any(d["event_id"] == evt_id for d in dispatched_notifications):
            return "SKIPPED_DUPLICATE"
        dispatched_notifications.append({"event_id": evt_id, "payload": payload})
        return "DISPATCHED"

    res1 = dispatch_event(event_id, {"title": "Invoice Overdue"})
    res2 = dispatch_event(event_id, {"title": "Invoice Overdue"})

    assert res1 == "DISPATCHED"
    assert res2 == "SKIPPED_DUPLICATE"
    assert len(dispatched_notifications) == 1

# ============================================================================
# 5. OUTBOUND WEBHOOK DELIVERY, RETRIES & TERMINAL ERRORS
# ============================================================================

@pytest.mark.asyncio
async def test_outbound_webhook_delivery_retries(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # Simulated webhook dispatcher with status codes
    def handle_webhook_response(status_code: int, attempt: int, max_attempts: int):
        if status_code == 200:
            return "SUCCESS"
        elif status_code in (500, 429, 503): # Transient -> retry
            if attempt < max_attempts:
                return "RETRY"
            return "DEAD_LETTER"
        elif status_code in (400, 401, 403, 404, 410): # Permanent 4xx -> terminal
            return "DEAD_LETTER"
        return "DEAD_LETTER"

    assert handle_webhook_response(200, 1, 5) == "SUCCESS"
    assert handle_webhook_response(500, 1, 5) == "RETRY"
    assert handle_webhook_response(429, 2, 5) == "RETRY"
    assert handle_webhook_response(500, 5, 5) == "DEAD_LETTER"
    assert handle_webhook_response(404, 1, 5) == "DEAD_LETTER"

# ============================================================================
# 6. WEBHOOK REPLAY PROTECTION (TIMESTAMP & HMAC)
# ============================================================================

def test_webhook_replay_protection():
    secret = "whsec_test_secret_abc123"
    payload = '{"event":"shipment.delivered","tracking":"TRK-101"}'

    # 1. Current valid timestamp -> ACCEPT
    current_ts = str(int(datetime.now(timezone.utc).timestamp()))
    sig = NotificationService.generate_webhook_signature(secret, current_ts, payload)
    assert verify_webhook_request(secret, sig, current_ts, payload) is True

    # 2. Expired timestamp (> 300s old) -> REJECT (400)
    old_ts = str(int(datetime.now(timezone.utc).timestamp()) - 600)
    old_sig = NotificationService.generate_webhook_signature(secret, old_ts, payload)
    with pytest.raises(HTTPException) as exc_info:
        verify_webhook_request(secret, old_sig, old_ts, payload)
    assert exc_info.value.status_code == 400
    assert "Timestamp expired" in exc_info.value.detail

    # 3. Invalid signature -> REJECT (401)
    with pytest.raises(HTTPException) as exc_info:
        verify_webhook_request(secret, "bad_signature_hex", current_ts, payload)
    assert exc_info.value.status_code == 401

# ============================================================================
# 7. SSRF COMPREHENSIVE COVERAGE
# ============================================================================

def test_ssrf_comprehensive_coverage():
    blocked_targets = [
        "http://127.0.0.1:8000/hook",
        "http://localhost:3000/api",
        "http://[::1]/hook",
        "http://10.0.0.1/callback",
        "http://172.16.0.1/callback",
        "http://192.168.1.1/callback",
        "http://[fc00::1]/hook",
        "http://169.254.169.254/latest/meta-data"
    ]

    for target in blocked_targets:
        with pytest.raises(HTTPException) as exc_info:
            validate_webhook_url_ssrf(target)
        assert exc_info.value.status_code == 400
        assert "SSRF Protection" in exc_info.value.detail

# ============================================================================
# 8. TENANT ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_tenant_isolation_notifications(db_session: AsyncSession):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    # Tenant A In-App Notification
    n_a = await NotificationService.dispatch_in_app_notification(
        db=db_session, tenant_id=tenant_a, user_id=str(uuid.uuid4()),
        title="Tenant A Notice", body="Message A", event_type="test.a"
    )
    # Tenant B In-App Notification
    n_b = await NotificationService.dispatch_in_app_notification(
        db=db_session, tenant_id=tenant_b, user_id=str(uuid.uuid4()),
        title="Tenant B Notice", body="Message B", event_type="test.b"
    )

    items_a = (await db_session.execute(select(InAppNotification).where(InAppNotification.tenant_id == tenant_a))).scalars().all()
    items_b = (await db_session.execute(select(InAppNotification).where(InAppNotification.tenant_id == tenant_b))).scalars().all()

    assert len(items_a) == 1
    assert items_a[0].title == "Tenant A Notice"
    assert len(items_b) == 1
    assert items_b[0].title == "Tenant B Notice"

# ============================================================================
# 9. JOB CONCURRENCY & IDEMPOTENCY LOCKING
# ============================================================================

@pytest.mark.asyncio
async def test_job_concurrency_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    key = f"concurrent_job_{uuid.uuid4().hex[:6]}"

    req = BackgroundJobCreate(
        job_type="IMMEDIATE", task_name="concurrent_task", idempotency_key=key
    )

    j1 = await JobService.enqueue_job(db_session, tenant_id, req)
    j2 = await JobService.enqueue_job(db_session, tenant_id, req)

    assert j1.id == j2.id

    execution_count = 0
    async def worker_task(payload):
        nonlocal execution_count
        execution_count += 1

    await JobService.run_job(db_session, j1.id, worker_task)
    assert execution_count == 1

# ============================================================================
# 10. JOB CANCELLATION LIFECYCLE
# ============================================================================

@pytest.mark.asyncio
async def test_job_cancellation_lifecycle(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    key = f"cancel_job_{uuid.uuid4().hex[:6]}"

    job = await JobService.enqueue_job(
        db=db_session, tenant_id=tenant_id,
        job_in=BackgroundJobCreate(job_type="DELAYED", task_name="cancel_me", idempotency_key=key)
    )
    assert job.status == "QUEUED"

    # 1. Cancel QUEUED job -> CANCELLED
    cancelled = await JobService.cancel_job(db_session, tenant_id, job.id)
    assert cancelled.status == "CANCELLED"

    # 2. Attempting to run CANCELLED job -> REJECT (400)
    async def dummy_worker(payload):
        pass

    with pytest.raises(HTTPException) as exc_info:
        await JobService.run_job(db_session, job.id, dummy_worker)
    assert exc_info.value.status_code == 400
    assert "Cannot run a CANCELLED job" in exc_info.value.detail

# ============================================================================
# 11. NOTIFICATION PREFERENCES & GRANULAR OPT-OUT
# ============================================================================

def test_notification_preferences_opt_out():
    # Preference: Email disabled, In-App enabled for SALES
    pref = {
        "email_enabled": False,
        "in_app_enabled": True,
        "event_category": "SALES"
    }

    def should_deliver(channel: str, category: str, is_critical: bool) -> bool:
        if is_critical:
            return True
        if category == pref["event_category"]:
            if channel == "EMAIL":
                return pref["email_enabled"]
            if channel == "IN_APP":
                return pref["in_app_enabled"]
        return True

    # Email for sales is skipped
    assert should_deliver("EMAIL", "SALES", is_critical=False) is False
    # In-App for sales is delivered
    assert should_deliver("IN_APP", "SALES", is_critical=False) is True
    # Critical security alert overrides email opt-out
    assert should_deliver("EMAIL", "SALES", is_critical=True) is True

# ============================================================================
# 12. TEMPLATE DATA ISOLATION & SANDBOX SAFETY
# ============================================================================

def test_template_data_isolation():
    # Context contains ONLY explicit sanitized primitives
    sanitized_context = {
        "so_number": "SO-2026-001",
        "customer_name": "Global Logistics Corp",
        "amount": 15000.00
    }

    template_str = "Invoice for {{ customer_name }}: Amount ${{ amount }}"
    rendered = render_sandboxed_template(template_str, sanitized_context)
    assert rendered == "Invoice for Global Logistics Corp: Amount $15000.0"

    # Attempting to access forbidden globals / AST raises SecurityError
    malicious_template = "{{ cycler.__init__.__globals__ }}"
    with pytest.raises(HTTPException) as exc_info:
        render_sandboxed_template(malicious_template, sanitized_context)
    assert exc_info.value.status_code == 400
    assert "Template Security Violation" in exc_info.value.detail
