# Phase 7: Offline Desktop & Synchronization Architecture

## Executive Summary

Phase 7 designs the **Offline Desktop & Synchronization Architecture** for AuraStock's Tauri Windows desktop application. It enables warehouse floor workers to perform essential scanning, bin movements, receiving, putaway, blind cycle counting, and pick verification in low-connectivity or network-interrupted warehouse environments without risking inventory corruption.

The architecture is governed by an immutable foundation:
$$\mathbf{PostgreSQL\ is\ the\ Sole\ Authoritative\ System\ of\ Record.}$$
$$\mathbf{Local\ SQLite\ is\ a\ Temporary\ Cache\ and\ Append-Only\ Outbox\ Queue,\ NOT\ a\ Distributed\ Ledger.}$$

```
                               ┌──────────────────────────────────────────────┐
                               │           FASTAPI BACKEND (CENTRAL)          │
                               │  PostgreSQL Ledger • Costing • Traceability  │
                               └──────────────────────▲───────────────────────┘
                                                      │
                         HTTPS Sync Protocol (Handshake • Push Outbox • Pull Delta)
                         Idempotency Key (UUIDv7) • Server-Authoritative Reconciliation
                                                      │
                               ┌──────────────────────▼───────────────────────┐
                               │          TAURI WINDOWS DESKTOP APP           │
                               │  Local SQLite Cache • Outbox Queue • UI      │
                               └──────────────────────────────────────────────┘
```

---

## 1. Core Architectural Principles & Invariants

1. **Server-Authoritative Source of Truth**:
   - All physical inventory quantities, financial cost layers, COGS entries, and audit logs are authoritatively finalized on the central PostgreSQL server.
   - Local SQLite holds **unconfirmed local intents** and a **read-only cached snapshot** of warehouse master data.
2. **Server-Authoritative Costing Model (No Distributed FIFO/MWA)**:
   - Financial costing (FIFO layer matching, Moving Weighted Average updates, and historical COGS) is **never** calculated offline on local desktop clients.
   - Offline transactions record immutable physical facts: `(client_tx_id, timestamp, warehouse_id, bin_id, variant_id, qty, lot_number, serial_numbers)`.
   - `CostingService` processes these facts sequentially inside PostgreSQL database transactions upon sync ingestion, preserving historical cost immutability.
3. **Idempotent At-Least-Once Synchronization**:
   - Every offline mutation is tagged with a globally unique `client_transaction_id` (UUIDv7).
   - PostgreSQL enforces `UNIQUE (tenant_id, client_transaction_id)` via `sync_idempotency_log`. Retrying identical transactions is 100% idempotent and cannot produce double inventory postings.
4. **Deterministic Conflict Rejection (Reject Unsafe, Never Overwrite)**:
   - When offline operations conflict with server reality (e.g. concurrent pick of the same serial or insufficient bin stock), the server **rejects the conflicting transaction** (`409 Conflict`), logs a conflict audit, and notifies the client to resolve the discrepancy. The server **never silently overwrites or fabricates quantities**.

---

## 2. Operation Implementation Matrix (Phase 7A vs. Deferred)

| Operation | Offline Allowed? | UI Exists? | Local Persistence? | Outbox Mutation? | Server Handler? | Server Validation? | Idempotency? | Conflict Handling? | Automated Tests? | Implementation Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Barcode Lookup** | **YES** | Yes | Yes (Cache) | N/A (Read) | N/A (Read) | N/A | N/A | N/A | Yes | **Phase 7A Implemented** |
| **View Cached Inventory** | **YES** | Yes | Yes (Cache) | N/A (Read) | N/A (Read) | N/A | N/A | N/A | Yes | **Phase 7A Implemented** |
| **Bin Movement (Internal Move)** | **YES** | Yes | Yes (Outbox) | `BIN_TRANSFER` | `SyncService` | Yes (Stock check) | Yes | Yes (Rejection) | Yes | **Phase 7A Implemented** |
| **Floor Putaway (Staging $\to$ Storage)** | **YES** | Yes | Yes (Outbox) | `PUTAWAY` | `SyncService` | Yes (Staging check)| Yes | Yes (Rejection) | Yes | **Phase 7A Implemented** |
| **Goods Receipt (GRN on Approved PO)** | **YES** | Yes | Yes (Outbox) | `RECEIVE_GOODS` | `SyncService` | Yes (PO check) | Yes | Yes (Rejection) | Yes | **Phase 7A Implemented** |
| **Picking (Acquire Serial / Stock)** | **YES** | Yes | Yes (Outbox) | `PICK_ITEM` | `SyncService` | Yes (Serial lock) | Yes | Yes (409 Conflict)| Yes | **Phase 7A Implemented** |
| **Lot Master Registration** | **YES** | Yes | Yes (Outbox) | In `RECEIVE_GOODS` | `TraceabilitySvc`| Yes (Lot check) | Yes | Yes (Rejection) | Yes | **Phase 7A Implemented** |
| **Serial Number Registration** | **YES** | Yes | Yes (Outbox) | In `RECEIVE_GOODS` | `TraceabilitySvc`| Yes (Unique check)| Yes | Yes (Rejection) | Yes | **Phase 7A Implemented** |
| **Blind Cycle Counting** | **QUEUED** | Planned 7B | Schema Ready | `COUNT_SCAN` | Planned 7B | Server Variance | Yes | Planned 7B | Planned 7B | **Deferred to Phase 7B** |
| **Packing Carton Verification** | **QUEUED** | Planned 7B | Schema Ready | `PACK_ITEM` | Planned 7B | Session Check | Yes | Planned 7B | Planned 7B | **Deferred to Phase 7B** |
| **Customer Return (RMA Intake)** | **QUEUED** | Planned 7B | Schema Ready | `CUSTOMER_RETURN` | Planned 7B | Return Check | Yes | Planned 7B | Planned 7B | **Deferred to Phase 7B** |
| **Supplier Return (RTV Outbound)** | **NO** | Blocked | N/A | Blocked | Blocked | N/A | N/A | N/A | N/A | **Explicitly Deferred (Online Only)** |
| **Product Safety Recall** | **NO** | Blocked | N/A | Blocked | Blocked | N/A | N/A | N/A | N/A | **Explicitly Deferred (Online Only)** |

---

## 3. Local Desktop Storage (SQLite) Architecture & Encryption Status

### 3.1 Encryption Status Clarification
> [!IMPORTANT]
> **Phase 7A Local SQLite Encryption Status**:
> In Phase 7A, local SQLite functions as an **unencrypted local cache and append-only outbox queue** residing in the OS application data directory (`AppData/Local/AuraStock/offline.db`).
> Full **SQLCipher page-level at-rest encryption** (using 256-bit AES with keys derived from Windows DPAPI / TPM) is **explicitly deferred to Phase 7B**.
> In Phase 7A, device-level security is enforced via **cryptographic offline lease validation (8-hour window)** and **immediate server-side device revocation**.

### 3.2 SQLite Outbox Schema (`offline_sync_outbox`)
```sql
CREATE TABLE offline_sync_outbox (
    client_tx_id TEXT PRIMARY KEY,                       -- UUIDv7 generated locally (time-sortable)
    tenant_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,                         -- RECEIVE_GOODS, PUTAWAY, PICK_ITEM, BIN_TRANSFER
    payload_json TEXT NOT NULL,                           -- Complete payload with item_variant_id, qty, bin_id, lot_number, serials
    created_at TEXT NOT NULL,                             -- ISO8601 local timestamp
    status TEXT DEFAULT 'PENDING' NOT NULL,               -- PENDING, SYNCING, COMMITTED, REJECTED, CONFLICT
    retry_count INTEGER DEFAULT 0 NOT NULL,
    last_error TEXT,
    server_tx_id TEXT,                                    -- Authoritative StockLedgerTransaction ID upon ACK
    server_committed_at TEXT
);
CREATE INDEX idx_outbox_status ON offline_sync_outbox(status, created_at);
```

---

## 4. Synchronization Protocol & Endpoints

### 4.1 3-Step Protocol Flow
1. **Handshake & Cryptographic Lease** (`POST /api/v1/sync/handshake`):
   - Authenticates device hardware identifier and user credentials.
   - Issues `SyncSessionToken` with an **8-hour offline lease** (1 warehouse shift).
   - If device is marked `REVOKED`, handshake is rejected with `403 Forbidden`.
2. **Upstream Mutation Ingestion** (`POST /api/v1/sync/upstream`):
   - Accepts batch of `SyncMutationEnvelope` objects.
   - Enforces lease validity: if lease is expired ($> 8\text{ hours}$ without renewal), rejects with `401 Unauthorized`.
   - Enforces idempotency via `SyncIdempotencyLog` (`UNIQUE (tenant_id, client_transaction_id)`).
   - Executes mutations under PostgreSQL row locks (`SELECT FOR UPDATE`).
   - Server-authoritative costing: offline receipts generate `CostLayer` and `CostTransaction` records server-side.
3. **Downstream Delta Cache Pull** (`GET /api/v1/sync/downstream`):
   - Delivers updated items, variants, barcodes, location bins, stock balances, active lots, and serial numbers.

---

## 5. Security, Revocation & Isolation Architecture

- **Tenant Isolation**: All sync tables (`sync_devices`, `sync_idempotency_log`) are strictly partitioned by `tenant_id`. Mutations attempting to reference warehouses or items in another tenant are rejected with `404 Not Found`.
- **Device Revocation**: Super Admins can revoke any device via `PUT /api/v1/sync/devices/{id}/revoke`. Revoked devices are permanently blocked from upstream and downstream synchronization with `403 Forbidden`.
- **Lease Expiration Guard**: If a device stays disconnected beyond the 8-hour lease window, all upstream mutations are locked until online authentication is performed.

---

## 6. Comprehensive Test Verification

All 10 tests in `test_offline_synchronization.py` passed:
1. `test_sync_handshake_and_lease_issuance`: Device registration and 8-hour lease token generation.
2. `test_sync_upstream_idempotency_and_replay`: 5 identical batch submissions produce exactly 1 ledger transaction.
3. `test_sync_concurrent_serial_acquisition_collision`: Device A succeeds; Device B receives `409 Conflict`.
4. `test_sync_insufficient_stock_transfer_rejection`: Overdraw transfer safely rejected with 422.
5. `test_sync_offline_goods_receipt_with_server_costing`: Server-authoritative `CostLayer` and `StockLot` generation.
6. `test_sync_downstream_delta_retrieval`: Incremental master data and balance cache retrieval.
7. `test_sync_device_revocation_lockout`: Revoked device blocked with 403.
8. `test_sync_api_endpoints_and_rbac`: REST endpoint security and RBAC permissions.
9. `test_sync_lease_expiration_and_tenant_warehouse_isolation`: Expired lease (401) and cross-tenant warehouse protection.
10. `test_sync_network_interruption_and_partial_retry`: Retry with duplicate + fresh mutation safely resolves.
