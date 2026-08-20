# AuraStock Enterprise ERP: Production Incident Recovery Runbooks

## 1. Overview & Standard Operating Procedure (SOP)
This document outlines the authoritative incident response procedures and recovery runbooks for operating the AuraStock ERP platform in a mission-critical enterprise production environment.

Every runbook adheres to the strict 5-stage lifecycle:
$$\text{Detection} \longrightarrow \text{Diagnosis} \longrightarrow \text{Recovery} \longrightarrow \text{Verification} \longrightarrow \text{Reconciliation}$$

---

## 2. Incident Runbooks

### Runbook 1: Application Server Outage (FastAPI / Web Tier)
- **Detection**: Automated uptime monitor or load balancer reports HTTP 502 / 503 errors; Prometheus `up == 0`.
- **Diagnosis**: Inspect container health logs: `docker logs -f aurastock-backend`. Check memory saturation or unhandled exceptions.
- **Recovery**:
  1. Restart the application container: `docker compose restart backend`.
  2. If memory leak detected, increase container resource limits in `docker-compose.prod.yml`.
  3. If transient port conflict, flush stale socket bindings.
- **Verification**: Query `/health/live` and `/health/ready` $\to$ expect HTTP 200 `{"status": "ok"}`.
- **Reconciliation**: Inspect `TelemetryMiddleware` for dropped requests and trigger outbox retry sweep.

---

### Runbook 2: Database Outage & Failover (PostgreSQL)
- **Detection**: Backend logs report `OperationalError: could not connect to server` or `/health/ready` returns HTTP 503.
- **Diagnosis**: Check PostgreSQL status `pg_isready -h localhost -p 5432`. Review disk space (`df -h`) and connection pool saturation.
- **Recovery**:
  1. If service stopped: `docker compose restart db` or `systemctl restart postgresql`.
  2. If primary node failed in high-availability cluster: Promote standby replica to primary (`pg_ctl promote`).
  3. Update backend database connection string in `.env` if failover endpoint IP changed.
- **Verification**: Backend `/health/subsystems` returns `"database": "UP"`.
- **Reconciliation**: Run `ReconciliationService.get_full_reconciliation_report()` to verify zero transaction corruption.

---

### Runbook 3: Failed Database Migration & Schema Rollback
- **Detection**: `alembic upgrade head` exits with non-zero code or table lock timeout.
- **Diagnosis**: Identify failing migration script in `alembic/versions/` and inspect database error log.
- **Recovery**:
  1. Execute deterministic downgrade to previous revision: `alembic downgrade -1`.
  2. If schema in partial state, restore pre-migration database snapshot from `backups/`.
  3. Fix migration SQL constraints/indexes and re-apply in maintenance window.
- **Verification**: Run `alembic current` and verify database tables match application ORM models.
- **Reconciliation**: Verify all foreign key integrity constraints and indexes.

---

### Runbook 4: Background Worker & Scheduler Stoppage
- **Detection**: Prometheus metric `background_jobs_in_progress` flatlines while queue grows; scheduled jobs (e.g. depreciation runs, MRP proposal generation) do not fire.
- **Diagnosis**: Inspect background worker logs: `docker logs -f aurastock-worker`. Check Redis/queue broker connectivity.
- **Recovery**:
  1. Restart background worker pool: `docker compose restart worker`.
  2. Check `BackgroundJobRecord` table in database for `FAILED` jobs.
- **Verification**: Trigger test job via `/api/v1/automation/jobs/trigger` and verify state moves to `COMPLETED`.
- **Reconciliation**: Re-run missed periodic jobs (e.g. daily exchange rate fetch, stock replenishment evaluation).

---

### Runbook 5: Transactional Outbox Dispatch Failure
- **Detection**: Prometheus metric `outbox_pending_events` spikes above threshold (> 50 events for > 5 minutes).
- **Diagnosis**: Check network connectivity to external webhook receivers, email SMTP gateway, or message broker.
- **Recovery**:
  1. Inspect `EventOutbox` records with `status == "FAILED"`.
  2. Fix network/credential issue.
  3. Force outbox relay sweep: `await OutboxService.dispatch_pending_events(db)`.
- **Verification**: `outbox_pending_events` returns to 0.
- **Reconciliation**: Query downstream endpoints to confirm receipt and verify idempotent deduplication keys prevent duplicate processing.

---

### Runbook 6: Multi-Echelon Edge Synchronization Conflict
- **Detection**: SCM branch edge device reports `SYNC_CONFLICT` or `422 Unprocessable Entity` during `/api/v1/supply-chain/edge/sync` payload push.
- **Diagnosis**: Inspect conflict log in `EdgeSyncBatch`. Central warehouse stock was depleted before branch mutation arrived.
- **Recovery**:
  1. System automatically executes server-authoritative resolution, allocating available stock and creating conflict backorder.
  2. Branch edge receives authoritative reconciliation payload and updates local SQLite cache.
- **Verification**: Edge device queries `/api/v1/supply-chain/edge/status` $\to$ state becomes `SYNCED`.
- **Reconciliation**: Verify central and edge physical stock ledgers match `StockBalanceCache`.

---

### Runbook 7: Document File Corruption / Tamper Alarm
- **Detection**: Probe `/api/v1/edms/attachments/{id}/verify` returns `is_tampered: true` (SHA-256 checksum mismatch).
- **Diagnosis**: Inspect storage volume file integrity against `DocumentAttachment.sha256_checksum`.
- **Recovery**:
  1. Quarantine compromised file path.
  2. Restore original version from verified immutable S3/object storage backup.
  3. Re-verify cryptographic checksum: `hashlib.sha256(file_bytes).hexdigest()`.
- **Verification**: `verify_attachment_integrity` returns `is_valid: true`.
- **Reconciliation**: Audit log records tamper incident and security review sign-off.

---

### Runbook 8: Subledger Reconciliation Variance Alarm
- **Detection**: Continuous health check `/api/v1/finance/reconciliation/full` reports `is_fully_reconciled: false` or `total_variance_count > 0`.
- **Diagnosis**: Query `/api/v1/finance/reconciliation/{subledger}` (Inventory, AR, AP, Fixed Assets, Intercompany) to isolate the out-of-balance account.
- **Recovery**:
  1. Identify the unposted or failed document transaction causing the discrepancy.
  2. Post the compensating adjusting journal voucher or retry the document completion.
- **Verification**: Re-run `/api/v1/finance/reconciliation/full` $\to$ verify variance = $0.00$.
- **Reconciliation**: All 5 subledgers match General Ledger balances exactly.

---

### Runbook 9: Authentication & SSO Provider Outage
- **Detection**: Users encounter HTTP 500/504 when attempting OIDC / SAML SSO login.
- **Diagnosis**: Check external Identity Provider (Okta, Azure AD, Google Workspace) status.
- **Recovery**:
  1. Enable local password + TOTP MFA fallback authentication for emergency administrators.
  2. Refresh OIDC metadata cache and verify SSO signing certificates.
- **Verification**: Perform test login with test credentials and MFA verification code.
- **Reconciliation**: Review `UserSessionRecord` and invalidate stale SSO sessions.

---

### Runbook 10: Point-In-Time Database Disaster Recovery
- **Detection**: Complete hardware failure or unrecoverable database corruption.
- **Diagnosis**: Declare P0 disaster recovery event.
- **Recovery**:
  1. Provision fresh PostgreSQL instance.
  2. Locate latest automated verified backup in `backups/` or cloud storage: `aurastock_backup_YYYYMMDD_HHMMSS.sql`.
  3. Verify SHA-256 checksum in `manifest_YYYYMMDD_HHMMSS.json`.
  4. Restore database:
     ```bash
     psql -U postgres -d aurastock_prod -f backups/aurastock_backup_YYYYMMDD_HHMMSS.sql
     ```
  5. Run Alembic migrations to bring schema to current release: `alembic upgrade head`.
  6. Start backend, worker, and web services.
- **Verification**: Run diagnostic probes `/health/ready` and `/health/subsystems`.
- **Reconciliation**: Run `/api/v1/finance/reconciliation/full` to verify 100% data integrity with zero subledger variance.
