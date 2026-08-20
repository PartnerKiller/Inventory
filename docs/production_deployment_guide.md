# AuraStock Enterprise Production Deployment & Infrastructure Guide

## 1. System Architecture Overview

AuraStock Enterprise is deployed as an immutable containerized stack orchestrated via Docker Compose or Kubernetes:
- **Nginx Reverse Proxy**: Terminating TLS 1.2/1.3, enforcing HTTP $\rightarrow$ HTTPS redirection, HSTS, security headers, and static SPA delivery with WebSocket upgrade.
- **FastAPI Application Backend**: Multi-worker asynchronous API server executing under non-root user `appuser`.
- **PostgreSQL 16 Engine**: ACID-compliant persistent database isolated to internal bridge network (`aurastock_internal`).
- **Redis 7 In-Memory Broker**: Queue broker and cache for asynchronous background tasks.
- **ARQ Background Worker**: Executes event outbox processing, inventory valuation rollups, and **recurring daily database backups at 02:00 UTC** via `BackupService`.
- **Persistent Storage Volumes**: `pgdata` (PostgreSQL tables), `redisdata` (Broker state), and `backupdata` (Gzip compressed, SHA-256 verified backup archives).

---

## 2. Infrastructure & Host Sizing

### Minimum Production Host Requirements
- **CPU**: 4 vCPUs (x86_64)
- **RAM**: 8 GB RAM (16 GB recommended for high-volume order processing)
- **Storage**: 100 GB SSD/NVMe (Mounted at `/var/lib/docker` with automated snapshot capabilities)
- **Operating System**: Ubuntu 22.04 LTS / Debian 12 / RHEL 9 / Amazon Linux 2023
- **Container Runtime**: Docker Engine 24.0+ & Docker Compose v2.20+

---

## 3. Environment & Secret Management

Create a production `.env` file from `.env.production.example`:
```bash
cp .env.production.example .env
chmod 600 .env
```

### Essential Production Secrets Checklist:
1. `POSTGRES_PASSWORD`: High-entropy database password (32+ characters).
2. `SECRET_KEY`: High-entropy cryptographic token signing key:
   ```bash
   openssl rand -hex 32
   ```
3. `BACKEND_CORS_ORIGINS`: JSON array restricting allowed web origins to your verified domain (e.g., `["https://inventory.yourcompany.com"]`).

> [!CAUTION]
> Never commit production `.env` files into source control repositories.

---

## 4. Initial Deployment Procedure

### Step 1: Clone Repository & Configure Environment
```bash
git clone https://github.com/your-org/aurastock.git /opt/aurastock
cd /opt/aurastock
cp .env.production.example .env
# Edit .env with production passwords and secret keys
nano .env
```

### Step 2: Build and Launch Container Topology
```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

### Step 3: Verify Container Health Status
```bash
docker compose -f deploy/docker-compose.yml ps
```
Ensure `aurastock_backend`, `aurastock_postgres`, `aurastock_redis`, `aurastock_worker`, and `aurastock_web` report `healthy` or `running`.

---

## 5. TLS Certificate Setup & Renewal (Let's Encrypt / Certbot)

### Option A: Certbot Automated TLS Provisioning
```bash
# Obtain certificate using webroot
docker run -it --rm --name certbot \
  -v "/etc/letsencrypt:/etc/letsencrypt" \
  -v "/var/lib/letsencrypt:/var/lib/letsencrypt" \
  -v "/opt/aurastock/certbot/www:/var/www/certbot" \
  certbot/certbot certonly --webroot \
  -w /var/www/certbot \
  -d inventory.yourcompany.com \
  --email security@yourcompany.com --agree-tos --no-eff-email
```

### Option B: Corporate / Custom Wildcard SSL
Place your certificates in `deploy/nginx/ssl/`:
- `deploy/nginx/ssl/cert.pem`
- `deploy/nginx/ssl/key.pem`

---

## 6. Production-Safe Database Migration Workflow

Arbitrary database migrations cannot universally guarantee zero downtime unless structured using backward/forward compatible phased releases. When deploying schema updates, AuraStock enforces the **Expand $\rightarrow$ Migrate $\rightarrow$ Contract** pattern combined with the **Backup-Before-Migration Mandate**:

### Phased Migration Architecture (Expand $\rightarrow$ Migrate $\rightarrow$ Contract)
1. **Phase 1 (Expand)**: Add new nullable columns, tables, or non-blocking indexes in Alembic migrations. The database remains fully backward-compatible with the currently running application replicas.
2. **Phase 2 (Migrate / Dual-Write)**: Deploy the updated application release. The application begins reading/writing the new schema structures while maintaining fallback support. Execute backfill scripts on existing rows if required.
3. **Phase 3 (Contract)**: After all backend replicas are upgraded and verified, apply a subsequent migration to enforce non-null constraints, clean up deprecated columns/tables, or remove obsolete triggers.

### Migration Execution Procedure:
```bash
# 1. Trigger pre-migration verified snapshot (Backup-Before-Migration Mandate)
docker exec -it aurastock_backend python -c "from app.services.backup_service import BackupService; print(BackupService.create_backup())"

# 2. Execute schema migrations
docker exec -it aurastock_backend alembic upgrade head

# 3. Execute post-migration read-only data integrity verification
docker exec -it aurastock_backend python -c "
import asyncio
from app.core.database import AsyncSessionLocal
from app.services.integrity_service import IntegrityService

async def check():
    async with AsyncSessionLocal() as session:
        r = await IntegrityService.run_full_integrity_check(session, '00000000-0000-0000-0000-000000000001')
        print('Integrity status:', r['overall_status'], 'Discrepancies:', r['discrepancies_count'])
        assert r['overall_status'] == 'HEALTHY'

asyncio.run(check())
"
```

---

## 7. Scheduled Backup Architecture

- **Execution Cadence**: Recurring daily at `02:00 UTC`.
- **Engine**: ARQ cron scheduler configured in `apps/backend/app/worker.py` invoking `BackupService.create_backup()`.
- **Integrity Guarantee**: Each snapshot calculates SHA-256 hash, validates file headers, and stores archives in the persistent `backupdata` volume.
- **Retention**: Prunes historical snapshots older than the configured `BACKUP_RETENTION_COUNT` (default 7 snapshots).

---

## 8. Deployment Security Review & Hardening

- [x] **Network Isolation**: PostgreSQL (`5432`) and Redis (`6379`) are isolated to `aurastock_internal` bridge network with zero public host port bindings.
- [x] **Non-Root Execution**: Backend and worker run under unprivileged UID `1000` (`appuser`).
- [x] **Credential Redaction**: `SensitiveDataFilter` masks tokens, passwords, and Authorization headers in logs.
- [x] **Strict CORS**: Permitted origins strictly restricted via `BACKEND_CORS_ORIGINS`.
- [x] **Security Headers**: HSTS, X-Content-Type-Options, X-Frame-Options, and CSP active on Nginx reverse proxy.
