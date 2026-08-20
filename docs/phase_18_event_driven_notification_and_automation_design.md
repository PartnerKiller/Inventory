# Phase 18 Design: Event-Driven Notification Engine & Background Automation

## Executive Overview

Phase 18 designs the **Event-Driven Notification Engine & Background Automation** subsystem for AuraStock. It decouples business domain services from external side-effects (emails, SMS, webhooks, push alerts, scheduled reports) through an asynchronous, transactional **Outbox Pattern**, an enterprise **Event Dispatcher**, a resilient **Background Job Queue** with exponential backoff and Dead-Letter Queues (DLQ), and a customizable **Notification Engine** supporting multi-channel preferences and sandboxed versioned templates.

### Core Architectural Invariants:
1. **Separation of Domain Core from Side-Effects**:
   $$\text{Domain Service} \xrightarrow[\text{Transaction}]{\text{Atomic}} \text{Business Table} + \text{EventOutbox} \xrightarrow[\text{Async}]{\text{Relay}} \text{Event Dispatcher} \longrightarrow \begin{cases} \text{Notification Service} \\ \text{Job Queue / Workers} \end{cases}$$
   *Business services (Sales, Inventory, Purchasing, Payments, Manufacturing, GL) NEVER directly invoke SMTP or external webhook APIs.*
2. **Reliability & Delivery Semantics**:
   The architecture strictly enforces **Effectively-Once Execution** via **At-Least-Once Delivery + Idempotent Consumer Processing**. True exactly-once delivery is not falsely claimed over distributed networks.
3. **SSRF & Security Isolation**:
   Outbound webhooks enforce strict Server-Side Request Forgery (SSRF) validation (blocking localhost, RFC 1918 private subnets, cloud metadata IPs). Templates are strictly sandboxed against template injection (SSTI).

---

## 1. Subsystem Architecture & Flow

```
                                  ┌──────────────────────────────┐
                                  │   Business Domain Service    │
                                  │ (Sales, Purchasing, GL, etc.)│
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼ (Atomic DB Transaction)
                        ┌─────────────────────────────────────────────────┐
                        │   Database: Business Records + EventOutbox Table│
                        └────────────────────────┬────────────────────────┘
                                                 │
                                                 ▼ (Async Polling / CDC Relay)
                                  ┌──────────────────────────────┐
                                  │    Outbox Event Dispatcher   │
                                  └──────────────┬───────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        ▼                                                 ▼
        ┌──────────────────────────────┐                  ┌──────────────────────────────┐
        │     Notification Service     │                  │      Job Queue / Workers     │
        ├──────────────────────────────┤                  ├──────────────────────────────┤
        │ • Multi-Channel Router       │                  │ • Immediate / Delayed Jobs   │
        │ • Template Engine (Sandboxed)│                  │ • Scheduled / Recurring Cron │
        │ • User/Tenant Preferences    │                  │ • Exponential Backoff Retry  │
        ├──────────────┬───────────────┤                  ├──────────────┬───────────────┤
        │              │               │                  │              │               │
        ▼              ▼               ▼                  ▼              ▼               ▼
   ┌─────────┐   ┌───────────┐   ┌──────────┐       ┌───────────┐  ┌───────────┐   ┌───────────┐
   │  Email  │   │  In-App   │   │ Outbound │       │ Low Stock │  │ Overdue AR│   │ Nightly   │
   │ (SMTP/  │   │   Inbox   │   │ Webhooks │       │ Demand    │  │ Invoice   │   │ Financial │
   │  SES)   │   │  (Toasts) │   │ (Signed) │       │ Planning  │  │ Aging     │   │ Reports   │
   └─────────┘   └───────────┘   └──────────┘       └───────────┘  └───────────┘   └───────────┘
```

---

## 2. Standard Domain Event Envelope

Every domain event emitted across AuraStock adheres to an immutable, versioned JSON schema:

```json
{
  "event_id": "evt_01J8F9A2B3C4D5E6F7G8H9J0K1",
  "event_type": "sales.order.allocated",
  "version": "1.0",
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "entity_type": "SalesOrder",
  "entity_id": "so_9f8e7d6c-5b4a-3210-fedc-ba9876543210",
  "occurred_at": "2026-08-19T01:30:00.000000Z",
  "correlation_id": "corr_req_123456789",
  "actor_id": "usr_alice_101",
  "payload": {
    "so_number": "SO-20260819-0001",
    "customer_id": "cust_acme_001",
    "warehouse_id": "wh_central_01",
    "total_amount": 10000.00,
    "allocated_lines": 3
  }
}
```

### Standard Event Catalog:
- **Inventory**: `inventory.stock.low`, `inventory.transfer.dispatched`, `inventory.cycle_count.discrepancy`, `inventory.recall.initiated`
- **Sales & Logistics**: `sales.order.created`, `sales.order.allocated`, `sales.order.shipped`, `sales.order.delivered`, `sales.return.received`
- **Purchasing & AP**: `purchasing.po.approved`, `purchasing.grn.received`, `ap.invoice.matched`, `ap.invoice.overdue`
- **Invoicing & Payments**: `invoicing.invoice.issued`, `invoicing.invoice.overdue`, `payments.payment.succeeded`, `payments.refund.processed`
- **Manufacturing**: `manufacturing.wo.released`, `manufacturing.wo.completed`

---

## 3. Background Job Queue & Worker Model

### 3.1 Job States & Lifecycle
```
                 ┌───────────┐
                 │  QUEUED   │
                 └─────┬─────┘
                       │ (Worker picks up job)
                       ▼
                 ┌───────────┐
        ┌───────►│  RUNNING  │────────┐
        │        └─────┬─────┘        │
 (Retry on Fail)       │ (Success)    │ (Max Attempts Exhausted / Unrecoverable)
        │              ▼              ▼
  ┌───────────┐  ┌───────────┐  ┌───────────────┐
  │ RETRYING  │  │ SUCCEEDED │  │  DEAD_LETTER  │
  └─────┬─────┘  └───────────┘  └───────────────┘
        │
 (Exponential Backoff Delay)
```

### 3.2 Retry Strategy & Dead-Letter Queue (DLQ)
- **Exponential Backoff Formula**:
  $$T_{\text{retry}} = T_{\text{base}} \times 2^{\text{attempt}} + \text{jitter}$$
  where $T_{\text{base}} = 5\text{s}$, $\text{max\_retries} = 5$, and $\text{jitter} \in [0, 2\text{s}]$.
- **Dead-Letter Queue (DLQ)**:
  When $\text{attempt} > \text{max\_retries}$ or upon encountering unrecoverable poison errors (e.g. fatal payload corruption), jobs transition to `DEAD_LETTER`. Operators inspect stack traces and trigger manual replay via `/api/v1/automation/dlq/{job_id}/retry`.

---

## 4. Multi-Channel Notification Router

### 4.1 Channels & Provider Abstractions
1. **Email Channel (`EmailProviderABC`)**:
   - `MockEmailProvider`: In-memory capture for unit & integration testing.
   - `SMTPProvider` / `SESProvider`: Production outbound email with DKIM/SPF support.
   - Security: Rejection of `\r` or `\n` in headers to prevent email header injection.
2. **In-App Notification Channel**:
   - Real-time inbox for web and desktop users.
   - States: `UNREAD` $\to$ `READ` $\to$ `ARCHIVED`.
   - Polling / WebSocket notification counter.
3. **Outbound Webhooks (`WebhookDispatcher`)**:
   - HMAC-SHA256 signature generated over `timestamp.payload_bytes`.
   - Headers: `X-AuraStock-Signature`, `X-AuraStock-Timestamp`, `X-AuraStock-Event-ID`.
   - 5-minute replay tolerance window.
4. **System / Operator Alerts**:
   - High-priority security and operational alerts (e.g. recall quarantine triggers).

### 4.2 Sandboxed Versioned Template Engine
- Template Model: `NotificationTemplate` (`id`, `template_code`, `channel`, `locale`, `version`, `subject_template`, `body_template`).
- Rendered using sandboxed Jinja2 (blocking `__import__`, `eval`, `exec`, OS module access).

---

## 5. Notification Preferences & Permissions

### 5.1 Granular Preference Hierarchy
- **Tenant Defaults**: Global channel enable/disable per event type.
- **User Preferences**: Individual opt-in/opt-out for specific events and channels.
- **Quiet Hours**: Suppresses non-critical notifications between configured hours (e.g. 22:00–07:00 local time).
- **Critical Alert Overrides**: Security alerts, recall notices, and payment failures bypass quiet hours.

---

## 6. Proposed Data Models (`apps/backend/app/models/notifications.py`)

```python
class NotificationTemplate(Base, BaseModelMixin):
    __tablename__ = "notification_templates"

    tenant_id = Column(String(36), nullable=False, index=True)
    template_code = Column(String(50), nullable=False, index=True) # e.g. STOCK_LOW_ALERT, INVOICE_OVERDUE
    channel = Column(String(30), nullable=False) # EMAIL, IN_APP, WEBHOOK, SYSTEM
    locale = Column(String(10), default="en", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    subject_template = Column(String(255), nullable=True)
    body_template = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class NotificationPreference(Base, BaseModelMixin):
    __tablename__ = "notification_preferences"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    entity_type = Column(String(30), nullable=True) # CUSTOMER, SUPPLIER, INTERNAL
    entity_id = Column(String(36), nullable=True)
    event_category = Column(String(50), nullable=False) # INVENTORY, SALES, PURCHASING, FINANCE
    email_enabled = Column(Boolean, default=True, nullable=False)
    in_app_enabled = Column(Boolean, default=True, nullable=False)
    webhook_enabled = Column(Boolean, default=True, nullable=False)
    quiet_hours_start = Column(String(5), nullable=True) # "22:00"
    quiet_hours_end = Column(String(5), nullable=True)   # "07:00"

class InAppNotification(Base, BaseModelMixin):
    __tablename__ = "in_app_notifications"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    event_type = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(36), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

class OutboundWebhookEndpoint(Base, BaseModelMixin):
    __tablename__ = "outbound_webhook_endpoints"

    tenant_id = Column(String(36), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    secret_encrypted = Column(Text, nullable=False)
    subscribed_events = Column(JSON, nullable=False) # ["sales.*", "inventory.stock.low"]
    is_active = Column(Boolean, default=True, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)

class BackgroundJobRecord(Base, BaseModelMixin):
    __tablename__ = "background_jobs"

    tenant_id = Column(String(36), nullable=False, index=True)
    job_type = Column(String(50), nullable=False, index=True) # IMMEDIATE, DELAYED, RECURRING
    task_name = Column(String(100), nullable=False, index=True) # e.g. run_replenishment, check_overdue_invoices
    payload_json = Column(JSON, nullable=False)
    status = Column(String(30), default="QUEUED", nullable=False, index=True) # QUEUED, RUNNING, SUCCEEDED, RETRYING, DEAD_LETTER, CANCELLED
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
```

---

## 7. Scheduled Recurring Automation Catalog

| Task Name | Schedule (Cron) | Operational Purpose |
| :--- | :--- | :--- |
| `task_nightly_replenishment` | `0 2 * * *` (2:00 AM) | Executes ADU demand velocity analysis and generates draft replenishment POs |
| `task_aging_ar_ap_check` | `0 6 * * *` (6:00 AM) | Recalculates overdue invoices/bills and dispatches automated reminder notifications |
| `task_low_stock_monitor` | `*/30 * * * *` (30 mins) | Scans for items below Safety Stock / ROP and dispatches urgent alerts |
| `task_shelf_life_monitor` | `0 1 * * *` (1:00 AM) | Evaluates expiring lots and alerts warehouse managers for FEFO prioritization |
| `task_carrier_tracking_sync`| `*/15 * * * *` (15 mins) | Polls active shipments for carrier tracking status synchronizations |

---

## 8. Security & Threat Model

| Threat Vector | Severity | Mitigation Strategy |
| :--- | :---: | :--- |
| **Outbound Webhook SSRF** | Critical | Strict IP validation; blocks loopback (`127.0.0.0/8`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and link-local cloud metadata (`169.254.169.254`). |
| **Template Injection (SSTI)** | Critical | Sandboxed template execution blocking Python runtime execution or AST exploitation. |
| **Email Header Injection** | High | Sanitizes recipient emails and subject strings, stripping all newline characters (`\r`, `\n`). |
| **Webhook Secret Disclosure** | High | Secret encrypted at rest; HMAC signature calculated server-side in constant time. |
| **Poison Queue DoS** | Medium | Failed jobs with bad payloads transition to Dead-Letter Queue (DLQ) after 5 retries without blocking other jobs. |

---

## 9. Verification & Test Strategy

1. **Transactional Outbox Integrity**: Verify committed business transaction emits Outbox event; rolled back transaction produces 0 Outbox events.
2. **Multi-Channel Notification Dispatch**: Test email, in-app inbox creation, and signed outbound webhook delivery.
3. **Outbound Webhook SSRF Rejection**: Assert webhook registration targeting `http://127.0.0.1`, `http://localhost`, or `http://169.254.169.254` is rejected (HTTP 400).
4. **Sandboxed Template Rendering**: Test variable interpolation; assert malicious syntax (e.g. `{{ ''.__class__.__mro__ }}`) is blocked safely.
5. **Job Retry Exponential Backoff & DLQ**: Simulate transient failures $\implies$ verify retry count increments with backoff; verify transition to `DEAD_LETTER` after 5 failures.
6. **Notification Quiet Hours & Opt-Out**: Verify non-critical notifications during quiet hours are suppressed or deferred.
7. **Zero Inventory/Costing Mutation**: Assert background notification engine causes zero mutations to physical stock or cost layers.
