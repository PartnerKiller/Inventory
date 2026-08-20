# Production PostgreSQL Backup & Restore Operational Procedure

## 1. Overview
This document specifies the authoritative backup, retention, and disaster recovery restore procedure for the **AuraStock Enterprise Inventory Management System** backed by PostgreSQL 16+.

---

## 2. Backup Strategy & Automation Classification

It is important to distinguish the current operational state of the backup subsystems:

| Capability | Status | Description |
| :--- | :--- | :--- |
| **Automated Backup Creation When Invoked** | **IMPLEMENTED** | `BackupService.create_backup()` automatically generates timestamped archives, computes SHA-256 hashes, verifies archive integrity, and prunes expired snapshots according to retention policies. |
| **On-Demand Backup API & UI** | **IMPLEMENTED** | Administrators can trigger on-demand backups via `POST /api/v1/operations/backups` or the Operations Dashboard UI. |
| **Scheduled Production Backup Automation** | **NOT YET CONFIGURED** | Automated recurring scheduling (e.g., nightly cron, Kubernetes CronJob, Windows Task Scheduler, or ARQ cron job) is not currently configured in the runtime environment. Scheduled cadence must be configured at the infrastructure level. |

---

## 3. Backup Engine Details

### Technical Specification
- **Tooling**: Standard native `pg_dump` with custom binary archive format (`-F c`) and gzip compression.
- **Credential Handling**: Read directly from the environment (`PGPASSWORD` / `DATABASE_URL`) without passing cleartext credentials as command-line arguments or recording them in log output.
- **Integrity Validation**: Automated post-backup SHA-256 checksum calculation, non-zero byte size verification, and archive header validation.
- **Retention Policy**: Retains the last 7 historical snapshots by default (configurable via `BACKUP_RETENTION_COUNT` / `BACKUP_DIR`).

### On-Demand Backup Command (CLI)
```bash
# Automated via BackupService Python CLI / Endpoint:
python -c "from app.services.backup_service import BackupService; print(BackupService.create_backup())"
```

### Manual PostgreSQL Native Dump
```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  -h "$POSTGRES_HOST" \
  -p "$POSTGRES_PORT" \
  -U "$POSTGRES_USER" \
  -F c \
  -b \
  -v \
  -f "/backups/aurastock_pg_$(date +%Y%m%d_%H%M%S).sql.gz" \
  "$POSTGRES_DB"
```

### Recommended Infrastructure Schedule (e.g., Daily Cron at 02:00 UTC)
To enable automated scheduling in production, configure an infrastructure-level cron entry:
```bash
0 2 * * * cd /app && python -c "from app.services.backup_service import BackupService; BackupService.create_backup()" >> /var/log/backup_cron.log 2>&1
```

---

## 4. Disaster Recovery & Restore Procedure

Follow these step-by-step instructions to perform a deterministic restore into a clean PostgreSQL database instance:

### Step 1: Provision Fresh Database
Ensure the target database instance is reachable and create an empty database:
```sql
DROP DATABASE IF EXISTS inventory_db_restore;
CREATE DATABASE inventory_db_restore WITH OWNER = inventory_user ENCODING = 'UTF8';
```

### Step 2: Restore from Verified Backup Archive
Execute `pg_restore` against the newly provisioned database:
```bash
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
  -h "$POSTGRES_HOST" \
  -p "$POSTGRES_PORT" \
  -U "$POSTGRES_USER" \
  -d inventory_db_restore \
  -v \
  --clean \
  --if-exists \
  "/backups/aurastock_pg_YYYYMMDD_HHMMSS.sql.gz"
```

### Step 3: Run Database Migrations
Apply any pending schema migrations to align with the running backend version:
```bash
DATABASE_URL="postgresql+asyncpg://inventory_user:pass@localhost:5432/inventory_db_restore" \
alembic upgrade head
```

### Step 4: Execute Post-Restore Entity Verification Checklist
Run the read-only integrity audit to verify complete recovery of critical business tables:

```python
import asyncio
from app.core.database import AsyncSessionLocal
from app.services.integrity_service import IntegrityService

async def verify_restore():
    async with AsyncSessionLocal() as session:
        result = await IntegrityService.run_full_integrity_check(session, "00000000-0000-0000-0000-000000000001")
        print(f"Overall Invariant Status: {result['overall_status']}")
        print(f"Checks Performed: {result['checks_performed']}")
        print(f"Discrepancies: {result['discrepancies_count']}")
        assert result["overall_status"] == "HEALTHY", "Restore data integrity verification failed!"

asyncio.run(verify_restore())
```

### Entity Recovery Checklist:
- [x] **User Accounts & Roles**: Validate Super Admin and assigned warehouse managers exist.
- [x] **Product Master & Variants**: Verify SKUs, categories, and UOM definitions.
- [x] **Stock Balances**: Verify $available = on\_hand - allocated$ holds across all bin records.
- [x] **Double-Entry Stock Ledger**: Verify cumulative ledger transaction sums match on-hand balances.
- [x] **Purchase Orders & GRN**: Verify received quantities match goods receipt line records.
- [x] **Sales Orders & Shipments**: Verify shipped quantities match dispatch records.
- [x] **Cryptographic Audit Trail**: Verify immutable audit logs and hash chains are intact.
