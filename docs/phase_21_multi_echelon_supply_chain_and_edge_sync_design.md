# Phase 21 Design: Multi-Echelon Supply Chain & Selective Edge Sync

## Executive Summary

Phase 21 establishes the **Multi-Echelon Supply Chain & Selective Edge Synchronization** architecture for the AuraStock ERP platform. It unifies multi-tier inventory network optimization ($\text{Supplier} \to \text{Central DC} \to \text{Regional DC} \to \text{Warehouse} \to \text{Edge Store/Field Location}$) with a hardened, server-authoritative **Edge Synchronization Engine** for desktop and edge devices.

### Core Architectural Invariants:
1. **Server-Authoritative Truth**:
   *The central server is the sole authoritative source of truth for global inventory balances and accounting states. Edge clients operate on local scoped caches and synchronize mutations via idempotent, version-checked event pipelines.*
2. **Unified In-Transit Accounting**:
   $$\text{Global Inventory} = \text{Source Stock} + \text{In-Transit Inventory} + \text{Destination Stock}$$
   *Inventory is NEVER counted simultaneously at source and destination, and in-transit value is explicitly tracked in General Ledger Account `1250 (Inventory In-Transit)`.*
3. **Multi-Echelon Demand Propagation**:
   *Edge and retail demand propagate upstream hierarchically without bullwhip amplification, prioritizing local transfers, regional transfers, internal manufacturing, and supplier procurement.*
4. **Deterministic Offline Conflict Resolution**:
   *Offline mutations are strictly classified as `SAFE_OFFLINE`, `SYNCHRONIZABLE_WITH_COMPENSATION`, or `REQUIRES_ONLINE`. Depleted stock conflicts trigger explicit compensating backorders rather than corrupting physical ledger mathematics.*

---

## 1. Supply-Chain Network Topology & Multi-Echelon Hierarchy

```
                                  ┌──────────────────────────────┐
                                  │      Global Suppliers        │
                                  └──────────────┬───────────────┘
                                                 │ (Purchase Orders / ASNs)
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │     Central DC (Tier 1)      │
                                  │  (Hub / Main Manufacturing)  │
                                  └──────────────┬───────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        │ (Inter-DC Bulk Transfers)                       │
                        ▼                                                 ▼
        ┌──────────────────────────────┐                  ┌──────────────────────────────┐
        │    Regional DC East (Tier 2) │                  │   Regional DC West (Tier 2)  │
        └──────────────┬───────────────┘                  └──────────────┬───────────────┘
                       │                                                 │
          ┌────────────┴────────────┐                       ┌────────────┴────────────┐
          ▼                         ▼                       ▼                         ▼
  ┌──────────────┐          ┌──────────────┐        ┌──────────────┐          ┌──────────────┐
  │ Local Plant  │          │ City WH (T3) │        │ Local Plant  │          │ City WH (T3) │
  └──────┬───────┘          └──────┬───────┘        └──────┬───────┘          └──────┬───────┘
         │                         │                       │                         │
         ▼                         ▼                       ▼                         ▼
  ┌──────────────┐          ┌──────────────┐        ┌──────────────┐          ┌──────────────┐
  │ Edge Depot   │          │ Retail Store │        │ Edge Depot   │          │ Retail Store │
  │ (Tauri Edge) │          │ (POS / Edge) │        │ (Tauri Edge) │          │ (POS / Edge) │
  └──────────────┘          └──────────────┘        └──────────────┘          └──────────────┘
```

### 1.1 Multi-Echelon Sourcing Priority Matrix

When an edge or warehouse node encounters inventory demand:

| Sourcing Tier | Source Option | Evaluation Criteria | Trigger Condition |
| :--- | :--- | :--- | :--- |
| **Tier 1: Local** | Local Warehouse Bin | Lead Time: $0$ days, Transfer Cost: ₹0 | $\text{On-Hand} - \text{Allocated} \ge \text{Demand}$ |
| **Tier 2: Spoke/Peer** | Peer Regional Warehouse | Lead Time: $1\text{--}2$ days, Surcharge: Low | Peer warehouse has excess stock above safety threshold |
| **Tier 3: Hub DC** | Central Distribution Center | Lead Time: $3\text{--}5$ days, Surcharge: Medium | Central DC has pipeline availability |
| **Tier 4: Production** | Internal Work Order | Lead Time: Routing Run Time, BOM availability | Item is `MAKE`, capacity available in work center |
| **Tier 5: External** | Supplier Purchase Order | Lead Time: Supplier Lead Time, MOQ enforced | Item is `BUY`, or internal capacity/stock exhausted |

---

## 2. Inter-Warehouse Transfer Orders & In-Transit Inventory Accounting

```
Source Warehouse                 In-Transit Pipeline                Destination Warehouse
       │                                  │                                   │
       │ 1. Create Transfer Order         │                                   │
       ├─────────────────────────────────►│                                   │
       │ 2. Reserve Source Stock          │                                   │
       │ 3. Pick & Dispatch               │                                   │
       ├─────────────────────────────────►│ (Inventory exits Source)          │
       │                                  │ Dr 1250 In-Transit Asset          │
       │                                  │ Cr 1200 Source Inventory          │
       │                                  │                                   │
       │                                  │ 4. Receive Goods (GRN)            │
       │                                  ├──────────────────────────────────►│
       │                                  │                                   │ 5. Inspect & Putaway
       │                                  │ (Inventory enters Destination)    │
       │                                  │ Dr 1200 Destination Inventory     │
       │                                  │ Cr 1250 In-Transit Asset          │
       │                                  │ Capitalize Freight to CostLayer   │
```

### 2.1 Transfer Discrepancy & Loss Handling
- **Partial Receipt**: Unreceived items remain in `IN_TRANSIT` status until reconciled or marked lost.
- **In-Transit Damage / Loss**:
  $$\text{Dr } 6000 \text{ Operating Expense (Transit Loss)} \quad / \quad \text{Cr } 1250 \text{ In-Transit Inventory Asset}$$
- **Freight Capitalization**: Freight surcharge $\Delta C$ is added to the landed unit cost in the destination `CostLayer`.

---

## 3. Selective Edge & Offline Synchronization Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │            Central Server (Authoritative)              │
                    ├────────────────────────────────────────────────────────┤
                    │ • PostgreSQL Core DB                                   │
                    │ • Transactional Outbox & Event Stream                  │
                    │ • Optimistic Concurrency & Monotonic Version Validator │
                    │ • Sync REST & WebSocket Gateway                        │
                    └───────────────────────────▲────────────────────────────┘
                                                │
                          (Encrypted Sync Stream via HTTPS / mTLS)
                                                │
                    ┌───────────────────────────▼────────────────────────────┐
                    │          Tauri Desktop / Edge Node (Local)             │
                    ├────────────────────────────────────────────────────────┤
                    │ • Local Encrypted SQLite Database                      │
                    │ • Offline Monotonic Mutation Queue (UUIDv7 client IDs) │
                    │ • Scoped Local Cache (Assigned Warehouse & Catalog)    │
                    │ • Replay Guard & Client Synchronization Daemon         │
                    └────────────────────────────────────────────────────────┘
```

### 3.1 Offline Transaction Classification Matrix

| Transaction Type | Offline Classification | Concurrency Policy | Server Reconciliation Policy |
| :--- | :--- | :--- | :--- |
| **Cycle Count / Physical Scan** | `SAFE_OFFLINE` | Last-write timestamp | Direct ingestion into count audit queue |
| **Guided Picking / Packing** | `SAFE_OFFLINE` | Local reservation lock | Validated against server pick session ID |
| **Bin-to-Bin Rapid Movement** | `SAFE_OFFLINE` | Local warehouse scope | Atomic ledger post upon synchronization |
| **Edge POS Checkout / Sales** | `SYNCHRONIZABLE_WITH_COMPENSATION` | Optimistic concurrency | If stock exhausted, creates backorder + alert |
| **Goods Receipt (PO / Transfer)**| `SYNCHRONIZABLE` | Document lock | Matches against open PO/Transfer order lines |
| **Work Order Operation Complete**| `SAFE_OFFLINE` | Operator session lock | Posts labor hours and WIP updates on sync |
| **Master BOM / Routing Edit** | `REQUIRES_ONLINE` | Server-authoritative | **Forbidden offline** (UI disabled) |
| **Supplier PO Approval** | `REQUIRES_ONLINE` | Server-authoritative | **Forbidden offline** (UI disabled) |
| **GL Period Close / JV Post** | `REQUIRES_ONLINE` | Server-authoritative | **Forbidden offline** (UI disabled) |
| **Customer Credit Limit Override**| `REQUIRES_ONLINE` | Server-authoritative | **Forbidden offline** (UI disabled) |

---

## 4. Deterministic Conflict Resolution & Compensation Rules

```
Edge Client Mutation (Sync Payload)
              │
              ▼
Central Sync Gateway (Pessimistic Row Lock on StockBalanceCache)
              │
              ├── [Case 1: Sufficient Stock Exists]
              │   ├── Apply StockLedgerTransaction
              │   ├── Update StockBalanceCache
              │   ├── Log SyncIdempotencyLog (status = "COMMITTED")
              │   └── Return Success ACK + Server Tx ID
              │
              ├── [Case 2: Duplicate Client Transaction ID]
              │   ├── Idempotency Hit: Retrieve existing committed response
              │   └── Return ACK without re-executing (Effectively-Once)
              │
              └── [Case 3: Stock Depleted by Intervening Central Sale]
                  ├── Log SyncIdempotencyLog (status = "CONFLICT")
                  ├── Create Compensating Document (Backorder / Variance)
                  ├── Dispatch Real-Time Alert to Store Manager
                  └── Return CONFLICT payload with required compensation steps
```

---

## 5. Proposed Data Models (`apps/backend/app/models/supply_chain.py`)

```python
class SupplyChainNode(Base, BaseModelMixin):
    __tablename__ = "supply_chain_nodes"

    tenant_id = Column(String(36), nullable=False, index=True)
    node_code = Column(String(50), unique=True, index=True, nullable=False) # DC-CENTRAL, DC-EAST, STORE-101
    node_name = Column(String(150), nullable=False)
    node_type = Column(String(30), nullable=False) # CENTRAL_DC, REGIONAL_DC, WAREHOUSE, RETAIL_EDGE, SUPPLIER
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True, index=True)
    parent_node_id = Column(String(36), ForeignKey("supply_chain_nodes.id"), nullable=True, index=True)
    lead_time_days = Column(Integer, default=1, nullable=False)
    sourcing_priority = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    warehouse = relationship("Warehouse", lazy="selectin")
    parent_node = relationship("SupplyChainNode", remote_side="SupplyChainNode.id", lazy="selectin")

class TransferOrder(Base, BaseModelMixin):
    __tablename__ = "transfer_orders"

    tenant_id = Column(String(36), nullable=False, index=True)
    transfer_number = Column(String(50), unique=True, index=True, nullable=False) # TRF-YYYYMMDD-XXXX
    source_warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    destination_warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    in_transit_bin_id = Column(String(36), ForeignKey("location_bins.id"), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, APPROVED, IN_TRANSIT, PARTIALLY_RECEIVED, COMPLETED, CANCELLED
    freight_charge = Column(Numeric(18, 4), default=0.0, nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)

    lines = relationship("TransferOrderLine", back_populates="transfer_order", cascade="all, delete-orphan", lazy="selectin")

class TransferOrderLine(Base, BaseModelMixin):
    __tablename__ = "transfer_order_lines"

    transfer_order_id = Column(String(36), ForeignKey("transfer_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    quantity_requested = Column(Numeric(18, 4), nullable=False)
    quantity_shipped = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_received = Column(Numeric(18, 4), default=0.0, nullable=False)
    quantity_damaged = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_cost = Column(Numeric(18, 4), default=0.0, nullable=False)

    transfer_order = relationship("TransferOrder", back_populates="lines")
    variant = relationship("ItemVariant", lazy="selectin")
```

---

## 6. General Ledger (GL) Accounting Integration

```
1. Transfer Order Dispatch (Source WH to Transit):
   Dr 1250  In-Transit Inventory Asset           ₹100,000
       Cr 1200  Source Inventory Asset (Raw/FG)         ₹100,000

2. Transfer Freight Surcharge:
   Dr 1250  In-Transit Inventory Asset             ₹5,000
       Cr 2000  Accounts Payable (Freight Carrier)        ₹5,000

3. Destination Warehouse Receipt:
   Dr 1200  Destination Inventory Asset          ₹105,000  (Landed unit cost adjusted)
       Cr 1250  In-Transit Inventory Asset              ₹105,000

4. Transit Loss / Damage Write-Off (if discrepancy occurs):
   Dr 6000  Operating Expense (Inventory Loss)     ₹4,000
       Cr 1250  In-Transit Inventory Asset                ₹4,000
```

---

## 7. Security, Threat Model & Edge Device Protections

| Threat Vector | Severity | Mitigation Strategy |
| :--- | :---: | :--- |
| **Compromised / Stolen Edge Device** | Critical | Instant remote device revocation (`status = "REVOKED"` on `SyncDevice`); device encryption keys destroyed via local lease expiration. |
| **Forged Offline Mutation Sync** | Critical | Every edge batch signed with HMAC-SHA256 device key; mutations validated against user's server-side permissions and warehouse scopes. |
| **Event Replay / Sequence Tampering** | High | Monotonic client transaction IDs (UUIDv7); replay caught via `SyncIdempotencyLog` returning cached results with zero duplicate ledger execution. |
| **Cross-Tenant Sync Escape** | Critical | Server sync handlers strictly enforce `tenant_id == claims["tenant_id"]` across all entity queries and mutation batches. |

---

## 8. Verification Plan

1. **Multi-Echelon Sourcing Hierarchy**: Verify demand at Edge queries local stock $\to$ peer warehouse $\to$ central DC $\to$ draft PO in exact priority order.
2. **Transfer Order Lifecycle**: Test $\text{DRAFT} \to \text{APPROVED} \to \text{IN\_TRANSIT} \to \text{RECEIVED}$; verify source stock decrements and in-transit increments atomically.
3. **In-Transit Costing & GL Balancing**: Verify Dr 1250 In-Transit / Cr 1200 Source upon dispatch; verify Dr 1200 Dest / Cr 1250 In-Transit upon receipt; landed cost capitalized into `CostLayer`.
4. **Offline Classification Enforcement**: Verify `REQUIRES_ONLINE` operations (BOM edit, GL close, PO approval) are strictly blocked when device is in offline mode.
5. **Sync Idempotency & Replay Protection**: Submit identical client sync batch twice $\implies$ exactly one logical execution; second submission returns cached ACK.
6. **Depleted Stock Conflict Compensation**: Simulate concurrent sale of last unit while Edge is offline $\implies$ server flags `CONFLICT`, logs incident, and creates compensating backorder without corrupting ledger math.
7. **Transit Loss Write-Off**: Verify damaged goods write off from `1250 (In-Transit)` to `6000 (Expense)` with balanced double-entry JVs.
8. **Tenant & Node Isolation**: Company A edge devices cannot synchronize or access Company B warehouses or transfer orders.
9. **Zero Inventory Math Corruption**: Hard invariant $\text{On-Hand} = \text{Available} + \text{Allocated} + \text{In-Transit} + \text{Quarantined}$ strictly holds before and after all sync operations.
