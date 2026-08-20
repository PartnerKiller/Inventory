import pytest
import uuid
import time
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from app.main import app
from app.core.config import settings
from app.core.telemetry import TelemetryCollector
from app.models.audit import EventOutbox

# ============================================================================
# 1. PROMETHEUS METRICS GENERATION & EXPOSITION
# ============================================================================

@pytest.mark.asyncio
async def test_prometheus_metrics_generation_and_exposition():
    TelemetryCollector.reset()

    # Record sample domain metrics
    TelemetryCollector.record_http_request("GET", "/api/v1/items", 200, 0.045)
    TelemetryCollector.record_stock_transaction("RECEIPT")
    TelemetryCollector.record_gl_voucher("CUSTOMER_INVOICE")
    TelemetryCollector.record_approval("APPROVED", "PURCHASE_ORDER")
    TelemetryCollector.record_edge_sync("SUCCESS")
    TelemetryCollector.set_gauge("aurastock_outbox_pending_events", 0.0)

    metrics_text = TelemetryCollector.generate_prometheus_metrics()

    assert "# HELP aurastock_http_requests_total" in metrics_text
    assert "# TYPE aurastock_http_requests_total counter" in metrics_text
    assert 'aurastock_http_requests_total{method="GET",path="/api/v1/items",status="200"} 1.0' in metrics_text
    assert "# HELP aurastock_stock_ledger_transactions_total" in metrics_text
    assert 'aurastock_stock_ledger_transactions_total{type="RECEIPT"} 1.0' in metrics_text
    assert "# HELP aurastock_gl_vouchers_posted_total" in metrics_text
    assert 'aurastock_gl_vouchers_posted_total{source_type="CUSTOMER_INVOICE"} 1.0' in metrics_text
    assert "# HELP aurastock_approval_requests_total" in metrics_text
    assert 'aurastock_approval_requests_total{entity_type="PURCHASE_ORDER",status="APPROVED"} 1.0' in metrics_text
    assert "# HELP aurastock_edge_sync_mutations_total" in metrics_text
    assert 'aurastock_edge_sync_mutations_total{status="SUCCESS"} 1.0' in metrics_text

# ============================================================================
# 2. TELEMETRY MIDDLEWARE & DISTRIBUTED TRACING HEADERS
# ============================================================================

@pytest.mark.asyncio
async def test_telemetry_middleware_and_distributed_tracing(client: AsyncClient):
    # 1. Request without X-Trace-ID -> Middleware automatically assigns new trace ID
    res1 = await client.get("/api/v1/health/live")
    assert res1.status_code == status.HTTP_200_OK
    assert "X-Trace-ID" in res1.headers
    assert "X-Span-ID" in res1.headers
    assert "X-Response-Time" in res1.headers
    assert res1.headers["X-Trace-ID"].startswith("trace-")

    # 2. Request with incoming distributed X-Trace-ID -> Middleware preserves trace ID
    custom_trace = "trace-custom-distributed-uuid-12345"
    res2 = await client.get("/api/v1/health/live", headers={"X-Trace-ID": custom_trace})
    assert res2.status_code == status.HTTP_200_OK
    assert res2.headers["X-Trace-ID"] == custom_trace

# ============================================================================
# 3. DEEP DIAGNOSTIC HEALTH PROBES & GL INTEGRITY
# ============================================================================

@pytest.mark.asyncio
async def test_deep_diagnostic_health_probes_and_gl_integrity(client: AsyncClient):
    # 1. /api/v1/health/live -> Liveness probe
    res_live = await client.get("/api/v1/health/live")
    assert res_live.status_code == status.HTTP_200_OK
    body_live = res_live.json()
    assert body_live["status"] == "ALIVE"
    assert body_live["service"] == "aurastock-backend"

    # 2. /api/v1/health/ready -> Readiness probe
    res_ready = await client.get("/api/v1/health/ready")
    assert res_ready.status_code == status.HTTP_200_OK
    body_ready = res_ready.json()
    assert body_ready["status"] == "READY"
    assert body_ready["database"] == "CONNECTED"

    # 3. /api/v1/health/subsystems -> Deep diagnostic probe
    res_sub = await client.get("/api/v1/health/subsystems")
    assert res_sub.status_code == status.HTTP_200_OK
    body_sub = res_sub.json()
    assert "subsystems" in body_sub
    assert body_sub["subsystems"]["database"]["status"] == "HEALTHY"
    assert body_sub["subsystems"]["general_ledger"]["status"] == "HEALTHY"
    assert body_sub["subsystems"]["approval_engine"]["status"] == "HEALTHY"
    assert body_sub["subsystems"]["transactional_outbox"]["status"] == "HEALTHY"

# ============================================================================
# 4. SENSITIVE DATA PROTECTION IN TELEMETRY & METRICS
# ============================================================================

@pytest.mark.asyncio
async def test_sensitive_data_protection_in_metrics_and_health(client: AsyncClient):
    # Verify no passwords, secrets, or JWT keys appear in /metrics
    res_m = await client.get("/api/v1/metrics")
    metrics_body = res_m.text
    assert "SECRET" not in metrics_body
    assert "password" not in metrics_body.lower()
    assert "token" not in metrics_body.lower()
    assert "Bearer" not in metrics_body

    # Verify no secrets appear in /health/subsystems
    res_h = await client.get("/api/v1/health/subsystems")
    health_body = res_h.text
    assert "SECRET" not in health_body
    assert "password" not in health_body.lower()
    assert "token" not in health_body.lower()

# ============================================================================
# 5. OUTBOX & ASYNC TRACE CONTEXT CORRELATION
# ============================================================================

@pytest.mark.asyncio
async def test_outbox_trace_context_correlation(db_session: AsyncSession):
    trace_id = f"trace-{uuid.uuid4().hex}"

    event = EventOutbox(
        id=str(uuid.uuid4()),
        event_type="STOCK_ADJUSTMENT_POSTED",
        aggregate_type="INVENTORY",
        aggregate_id="adj-123",
        payload={"item_id": "item-123", "qty": 10, "trace_id": trace_id},
        status="PENDING"
    )
    db_session.add(event)
    await db_session.commit()

    # Verify trace context is stored in outbox event payload
    saved_event = await db_session.get(EventOutbox, event.id)
    assert saved_event.payload["trace_id"] == trace_id
