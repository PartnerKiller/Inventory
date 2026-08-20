# Phase 30 Design Discovery: Post-Phase-29 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 29**, AuraStock is an enterprise-grade, multi-company, multi-currency double-entry Enterprise Resource Planning (ERP) platform with complete inventory costing, shop-floor manufacturing, multi-echelon SCM, double-entry GL, statutory financial accounting, management cost centers, commitment budgeting, statistical demand forecasting, multi-level approval workflows with Delegation of Authority (DoA), B2B dynamic pricing with volume rebate settlements, and full Prometheus observability with distributed request tracing.

### Comprehensive Audit Summary:
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, customer invoicing, **Dynamic Pricing & Volume Breaks**, and **Customer Rebate Settlement Accounting (Dr `4100` / Cr `1200`)**.
- **Statutory Accounting & GL**: Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, **Accounting Period closing state machine** with **hard backdated posting/void guards**, **automated Year-End retained earnings closing ceremony (`3100`)**, **Multi-Currency exchange rates with realized/unrealized FX (`6300`)**, **Enterprise Multi-Jurisdiction Tax Engine (GST/VAT)** with **Input Tax Credit (`1400`) / Output Tax (`2200`) settlement**, and **Fixed Asset capitalization & automated depreciation schedules (SLM/WDV)**.
- **Management Accounting & Budgeting**: **Cost Center & Profit Center hierarchy**, **Departmental Budget allocations per period & GL account**, **Commitment Accounting on Purchase Orders**, **soft warning thresholds**, **hard budget overrun blocking (HTTP 400)**, **commitment actualization**, and **hierarchical variance rollups**.
- **Demand Forecasting & Replenishment**: **Holt-Winters Triple Exponential Smoothing** (Level, Trend, Seasonality), **Dynamic Service-Level Safety Stock ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$)**, **Dynamic $ROP = (\bar{D} \times \bar{L}) + SS$**, **Automated Replenishment Proposals**, and **1-Click conversion to authoritative Vendor Purchase Orders**.
- **Governance & Approval Workflows**: **Tiered Spend Authorization Matrix**, **Sequential Multi-Step Approvals**, **Document Release Locks** (PO, GRN, AP, GL, Manual JV, Budget Overrun, Asset Disposal), **SLA Timeout Escalation Engine**, and **Out-of-Office Delegation of Authority (DoA)**.
- **Observability & Telemetry (P29)**: **Prometheus Telemetry Scraper (`/metrics`)**, **Distributed Tracing (`X-Trace-ID`, `X-Span-ID`, `X-Response-Time`)**, **Deep Diagnostic Health Probes (`/health/live`, `/health/ready`, `/health/subsystems`)**, and **Outbox event trace context correlation**.
- **Identity & Automation**: Multi-tenant isolation, RFC 6238 TOTP MFA, session token families with reuse detection, OIDC SSO, transactional outbox relay, and background scheduler daemon.

---

## 2. Post-Phase-29 Platform Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           AuraStock ERP Platform                                        │
├────────────────────────────────┬───────────────────────────────────────┬────────────────────────────────┤
│ 1. Core Inventory & Valuation  │ 2. Commercial, Pricing & B2B Portals  │ 3. Manufacturing & SCM         │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry Stock Ledger    │ • Sales Orders & Customer Invoices    │ • Multi-Level BOMs & Work Ctrs │
│ • FIFO / Moving Average Cost   │ • Dynamic Price Rules & Volume Breaks │ • Shop-Floor Routing Locks     │
│ • Lot/Batch/Serial Traceability│ • Customer Rebate Settlement (P28)    │ • In-Process QA Gates          │
│ • 1-Click Product Recalls      │ • Vendor POs, GRN & 3-Way Match       │ • Multi-Echelon SCM Nodes      │
│ • Rapid Warehouse Barcoding    │ • B2B Customer & Supplier Portals     │ • Transfer Orders & In-Transit │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ 4. Statutory & Mgmt Accounting │ 5. Planning & Replenishment (P26)     │ 6. Governance & Control (P27)  │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry General Ledger  │ • Holt-Winters Seasonal Forecasting   │ • Tiered Spend Matrix (DoA)    │
│ • Accounting Period Lock (P22) │ • Dynamic Z-Score Safety Stock ($SS$) │ • Multi-Step Approval Engine   │
│ • Retained Earnings Close (P22)│ • Dynamic Reorder Point ($ROP$)       │ • Release Locks (PO/GRN/AP/GL) │
│ • FX & Tax Engine (GST/VAT)    │ • Automated Replenishment Proposals   │ • SLA Timeout Escalation       │
│ • Fixed Assets & Deprec (1500) │ • 1-Click PO Conversion & Idempotency │ • Delegate Substitution (OoO)  │
│ • Cost Centers & Budgets (P25) │ • Lead-Time & Demand Variance Models  │ • Permanent Rejection Halts    │
├────────────────────────────────┴───────────────────────────────────────┴────────────────────────────────┤
│ 7. Telemetry & Observability (Phase 29)                                                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Prometheus Scrape Endpoint (`/metrics`) exposing request rates, latencies, ledger throughput & queues │
│ • Distributed Tracing (`TelemetryMiddleware`) propagating `X-Trace-ID`, `X-Span-ID`, `X-Response-Time`  │
│ • Deep Subsystem Diagnostic Health Probes (`/health/live`, `/health/ready`, `/health/subsystems`)       │
│ • Transactional Outbox trace correlation payload persistence                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. End-to-End Business-Flow & Financial Integrity Audit

### Complete Control-Plane & Financial Flow:
1. **Commercial Flow**: $\text{Contract} \to \text{Price Quote (P28)} \to \text{Sales Order} \to \text{Approval Lock (P27)} \to \text{Shipment} \to \text{Invoice} \to \text{Tax (P23)} \to \text{AR (1200)} \to \text{GL}$
2. **Procurement Flow**: $\text{Demand} \to \text{Holt-Winters Forecast (P26)} \to \text{Dynamic ROP} \to \text{Proposal} \to \text{PO} \to \text{Approval Lock} \to \text{Commitment (P25)} \to \text{GRN} \to \text{AP (2000)}$
3. **Observability Trace**: $\text{HTTP Request} \to \text{TelemetryMiddleware (X-Trace-ID)} \to \text{Service Mutation} \to \text{Outbox Event} \to \text{Prometheus Counter Increment}$

---

## 4. Reconciliation of Prior Completed Phases (Phases 17–29)

| Phase | Description | Status in Repository | Verification Evidence |
| :---: | :--- | :---: | :--- |
| **Phase 17** | Double-Entry General Ledger & Financial Reporting | **CLOSED** | [`apps/backend/app/models/general_ledger.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/general_ledger.py) & `gl_service.py` (`test_general_ledger.py`) |
| **Phase 18** | Notifications Engine & Background Scheduler | **CLOSED** | [`apps/backend/app/models/notifications.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/notifications.py) & `scheduler_service.py` (`test_notifications_and_scheduler.py`) |
| **Phase 19** | Authentication Hardening, TOTP MFA & OIDC SSO | **CLOSED** | [`apps/backend/app/models/auth_security.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/auth_security.py) & `auth_security_service.py` (`test_auth_hardening_mfa_and_sso.py`) |
| **Phase 20** | Advanced Manufacturing, Routing & QA Gates | **CLOSED** | [`apps/backend/app/models/advanced_manufacturing.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/advanced_manufacturing.py) & `advanced_manufacturing_service.py` (`test_advanced_manufacturing.py`) |
| **Phase 21** | Multi-Echelon SCM & Selective Edge Sync | **CLOSED** | [`apps/backend/app/models/supply_chain.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/supply_chain.py) & `supply_chain_service.py` (`test_supply_chain_and_edge_sync.py`) |
| **Phase 22** | Accounting Period Closing & Year-End Close | **CLOSED** | [`apps/backend/app/models/accounting_period.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/accounting_period.py) & `period_closing_service.py` (`test_period_closing_and_year_end.py`) |
| **Phase 23** | Multi-Currency & Enterprise Tax Engine | **CLOSED** | [`apps/backend/app/models/tax_and_currency.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/tax_and_currency.py) & `tax_and_currency_service.py` (`test_tax_and_currency.py`) |
| **Phase 24** | Fixed Asset Lifecycle & Automated Depreciation | **CLOSED** | [`apps/backend/app/models/fixed_asset.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/fixed_asset.py) & `fixed_asset_service.py` (`test_fixed_assets_and_depreciation.py`) |
| **Phase 25** | Cost Centers & Departmental Budgeting | **CLOSED** | [`apps/backend/app/models/budgeting.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/budgeting.py) & `budget_service.py` (`test_cost_centers_and_budgeting.py`) |
| **Phase 26** | Demand Forecasting & Statistical Replenishment | **CLOSED** | [`apps/backend/app/models/forecasting.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/forecasting.py) & `forecasting_service.py` (`test_demand_forecasting_and_replenishment.py`) |
| **Phase 27** | Multi-Level Approvals & Delegation of Authority | **CLOSED** | [`apps/backend/app/models/approval.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/approval.py) & `approval_service.py` (`test_multi_level_approvals_and_doa.py`) |
| **Phase 28** | Dynamic Pricing & Customer Rebates | **CLOSED** | [`apps/backend/app/models/pricing_v2.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/pricing_v2.py) & `pricing_service_v2.py` (`test_dynamic_pricing_and_rebates.py`) |
| **Phase 29** | Observability & Prometheus Telemetry | **CLOSED** | [`apps/backend/app/core/telemetry.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/core/telemetry.py) & `health.py` (`test_enterprise_observability_and_metrics.py`) |

---

## 5. Platform Gap & Risk Assessment

Following the audit across all 29 phases, the remaining enterprise capabilities are classified below:

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Multi-Entity Intercompany Trade & Consolidation Elimination Engine** | AuraStock supports multi-tenant and multi-company schemas, but lacks automated mirrored intercompany transactions (where an Intercompany SO in Entity A automatically provisions a matching PO in Entity B) and consolidation elimination journal entries that eliminate intercompany revenue (`4000`), COGS (`5000`), AR (`1300`), and AP (`2300`) to produce consolidated financial statements. | Multi-entity conglomerates suffer from manual duplicate order entry, mismatched intercompany ledger balances, and distorted consolidated corporate financial statements. |
| **P2** | **Enterprise Document Management & Compliance Sign-Off** | System generates PDF invoices and purchase orders; lacks cloud blob-backed versioned document management and cryptographic checksum audit logging. | Secondary file archiving capability. |
| **P3** | **Tauri Desktop Client Local Migration Runner** | Edge sync handles offline mutations via REST; local SQLite migrations require clean initialization during upgrades. | Minor operational consideration during desktop app updates. |

---

## 6. Ranked Phase 30 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 30 - P1)**: **Multi-Entity Intercompany Trade, Automated Mirrored Transactions & Group Elimination Journal Engine**
   - *Objective*: Implement an end-to-end Intercompany Trade & Consolidation Elimination Engine:
     - `IntercompanyRelationship`: Trading partner entity definitions, transfer pricing markup rules (Cost-Plus %, Fixed Price), and default clearing accounts (Account `1300` Due from Affiliates / Account `2300` Due to Affiliates).
     - `Mirrored Transaction Automation`: Intercompany SO in Entity A automatically provisions a mirrored PO in Entity B; dispatching in Entity A initiates in-transit receipt in Entity B.
     - `Consolidation Elimination Engine`: Automated generation of balancing elimination journal vouchers clearing intercompany sales (`4000`), COGS (`5000`), AR (`1300`), and AP (`2300`) to produce group consolidated financial reports.
   - *Business Value*: Eliminates manual duplicate order entry across subsidiaries, guarantees balanced intercompany AR/AP clearing accounts, and ensures statutory group consolidation compliance.
   - *Dependencies*: Sales Orders, Purchase Orders, General Ledger (`gl_service.py`), SCM Transfers, Period Closing.
   - *Implementation Complexity*: Medium-High.
   - *Verification Complexity*: Deterministic (Mirrored PO generation, transfer price markup math, balanced elimination journal vouchers, consolidated trial balance).

2. **Rank 2 (Candidate Phase 31 - P2)**: **Enterprise Document Management, Versioned File Attachments & Audit Compliance Sign-Off Workflows**
   - *Objective*: Versioned document storage with cryptographic SHA-256 signatures.
   - *Business Value*: Regulatory compliance file management.
   - *Dependencies*: Storage abstraction, Audit logs.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 32 - P2)**: **Field Service & Preventive Maintenance Management Engine**
   - *Objective*: Preventive asset maintenance schedules and field service tickets.
   - *Business Value*: After-sales service support.
   - *Dependencies*: Work Centers, Items Master.
   - *Implementation Complexity*: Medium.

---

## 7. Recommended Phase 30: Multi-Entity Intercompany Trade & Consolidation Eliminations

### 7.1 Architecture & Workflow Model
1. **Intercompany Relationship & Transfer Pricing Rules**:
   - Relationship definition between Parent / Subsidiary legal entities.
   - Transfer pricing policy: `COST_PLUS_PERCENTAGE`, `FIXED_TRANSFER_PRICE`, or `CATALOG_PRICE`.
   - Intercompany Clearing Accounts: Account `1300` (Due from Affiliates) and Account `2300` (Due to Affiliates).
2. **Automated Mirrored Transaction Flow**:
   $$\text{Company A (Seller): Intercompany SO} \xrightarrow{\text{Auto-Provision}} \text{Company B (Buyer): Mirrored Intercompany PO}$$
   $$\text{Company A: Dispatches Goods} \implies \text{Stock Ledger: Transfer Out} \implies \text{Company B: In-Transit Receipt}$$
   $$\text{Company A: Customer Invoice} \implies \text{Dr 1300 (Due from B) / Cr 4000 (Sales)}$$
   $$\text{Company B: Vendor Bill} \implies \text{Dr 1200 (Inventory Asset) / Cr 2300 (Due to A)}$$
3. **Consolidation Elimination Journal Engine**:
   - Consolidates parent and subsidiary trial balances and generates balancing elimination entries:
     $$\text{Dr } 4000\text{ (Intercompany Revenue)} \quad / \quad \text{Cr } 5000\text{ (Intercompany COGS)}$$
     $$\text{Dr } 2300\text{ (Due to Affiliates)} \quad / \quad \text{Cr } 1300\text{ (Due from Affiliates)}$$

### 7.2 Data Models (`apps/backend/app/models/intercompany.py`)
- `IntercompanyPartner`: `tenant_id`, `seller_company_id`, `buyer_company_id`, `transfer_pricing_type` (`COST_PLUS`, `FIXED_PRICE`, `CATALOG`), `markup_percentage`, `ar_intercompany_account_id`, `ap_intercompany_account_id`, `is_active`.
- `IntercompanyTransactionPair`: `tenant_id`, `sales_order_id`, `purchase_order_id`, `sales_invoice_id`, `purchase_bill_id`, `transfer_order_id`, `status` (`LINKED`, `DISPATCHED`, `RECEIVED`, `ELIMINATED`).
- `ConsolidationRun`: `tenant_id`, `period_id`, `run_date`, `status` (`DRAFT`, `FINALIZED`), `elimination_voucher_id`.

---

## 8. Phase 30 Implementation Sequence

1. **Stage 30A — Data Models & Schemas**:
   - Create `apps/backend/app/models/intercompany.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/intercompany.py`.
2. **Stage 30B — Intercompany Domain Service (`IntercompanyService`)**:
   - Implement partner configuration and transfer pricing calculation.
   - Implement mirrored PO generation from Intercompany SO.
   - Implement consolidated elimination journal generator (Dr `4000` / Cr `5000` and Dr `2300` / Cr `1300`).
3. **Stage 30C — REST API Endpoints**:
   - Mount `/api/v1/intercompany` router for partners, mirrored transaction creation, and consolidation runs.
4. **Stage 30D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_intercompany_trade_and_consolidation.py`.
   - Execute full platform regression across all backend test modules (>366 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.

---

## 9. Phase 30 Verification Strategy

1. **Mirrored Transaction Creation**: Verify creating an Intercompany SO in Entity A automatically provisions a matching PO in Entity B.
2. **Transfer Pricing Calculation**: Verify Cost-Plus % markup computes correct intercompany unit pricing.
3. **Intercompany Clearing Accounting**: Verify seller invoice posts to Account `1300` and buyer bill posts to Account `2300`.
4. **Consolidation Elimination JVs**: Verify running consolidation eliminates intercompany revenues, COGS, and reciprocal AR/AP clearing accounts.
5. **Full Platform Regression**: Backend pytest, frontend Vitest, TypeScript compiler, web build, and packaging.
