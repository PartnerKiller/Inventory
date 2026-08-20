# Phase 31 Design Discovery: Post-Phase-30 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 30**, AuraStock is a fully integrated double-entry Enterprise Resource Planning (ERP) platform. It provides double-entry stock valuation, FIFO/moving-average costing layers, multi-echelon SCM nodes, multi-level BOMs and routing locks, statutory accounting periods and fiscal year closing ceremonies, multi-currency historical rate locking, enterprise GST/VAT tax settlements, fixed asset capitalization and automated depreciation, cost center budgeting and commitment overrun guards, Holt-Winters demand forecasting, multi-level approval workflows with Delegation of Authority (DoA), B2B dynamic pricing with customer volume rebates, Prometheus observability with distributed tracing, and **Multi-Entity Intercompany Trade with Automated Mirrored Transactions & Group Elimination Journals**.

### Complete Platform Scope (Phases 1–30):
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, customer invoicing, dynamic pricing break curves, and volume rebate settlements (Dr `4100` / Cr `1200`).
- **Statutory Accounting & GL**: Standard Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, accounting period closing state machine with hard backdated posting guards, automated year-end retained earnings closing (`3100`), multi-currency exchange rates with realized/unrealized FX (`6300`), enterprise GST/VAT with Input Tax Credit (`1400`) vs Output Tax (`2200`), fixed asset capitalization (`1500`) and automated SLM/WDV depreciation schedules (`1550` / `6400`).
- **Management Accounting & Budgeting**: Cost Center & Profit Center hierarchy, departmental budget allocations per period & GL account, commitment accounting on Purchase Orders, soft warning thresholds, hard budget overrun blocks (HTTP 400), commitment actualization, and hierarchical variance rollups.
- **Planning & Intelligence**: Holt-Winters triple exponential smoothing, dynamic $Z$-score safety stock modeling ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$), dynamic $ROP$, replenishment proposal generation, and 1-click conversion to authoritative Vendor Purchase Orders.
- **Governance & Control**: Tiered spend authorization matrix (DoA), sequential multi-step approval engine, document release locks (PO, GRN, AP, GL, Manual JV, Budget Overrun, Asset Disposal), SLA timeout escalations, and out-of-office delegate substitutions.
- **Observability & Diagnostics**: Prometheus telemetry scrape endpoint (`/metrics`), `TelemetryMiddleware` assigning and propagating `X-Trace-ID`, `X-Span-ID`, `X-Response-Time`, and deep diagnostic health probes (`/health/live`, `/health/ready`, `/health/subsystems`).
- **Multi-Entity Intercompany Trade (P30)**: Intercompany trading agreements, transfer pricing rules (`COST_PLUS`, `FIXED_PRICE`, `CATALOG`), automated mirrored Purchase Order generation from Intercompany Sales Orders, intercompany AR (`1300`) and AP (`2300`) clearing accounting, and group consolidation elimination Journal Vouchers (Dr `4000` Revenue / Cr `5000` COGS and Dr `2300` Due to Affiliates / Cr `1300` Due from Affiliates).

---

## 2. Post-Phase-30 Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           AuraStock ERP Platform                                        │
├────────────────────────────────┬───────────────────────────────────────┬────────────────────────────────┤
│ 1. Core Inventory & Valuation  │ 2. Commercial, Pricing & Intercompany │ 3. Manufacturing & SCM         │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry Stock Ledger    │ • Sales Orders & Invoices             │ • Multi-Level BOMs & Work Ctrs │
│ • FIFO / Moving Average Cost   │ • Dynamic Price Rules & Rebates       │ • Shop-Floor Routing Locks     │
│ • Lot/Batch/Serial Traceability│ • Intercompany Partners & Trading     │ • In-Process QA Quarantine     │
│ • 1-Click Product Recalls      │ • Automated Mirrored POs (P30)        │ • Multi-Echelon SCM Nodes      │
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
│ 7. Telemetry & Multi-Entity Consolidation (Phases 29–30)                                                │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Prometheus Scrape Endpoint (`/metrics`) exposing counters, latencies, and queue depth metrics         │
│ • Distributed Tracing (`TelemetryMiddleware`) propagating `X-Trace-ID` and latency headers              │
│ • Deep Subsystem Diagnostic Health Probes (`/health/live`, `/health/ready`, `/health/subsystems`)       │
│ • Group Consolidation Elimination Engine (Dr 4000 / Cr 5000 and Dr 2300 / Cr 1300)                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Critical Deferred Item Audit: Unrealized Intercompany Profit Elimination

### 3.1 Accounting Nature & Financial Statement Impact
When Entity A sells inventory to Entity B at a markup (e.g. transfer price $115 on cost $100, generating $15 intercompany profit):
- If Entity B sells the inventory to an external third-party customer before period end: the $15 profit is fully realized by the corporate group.
- If Entity B retains the inventory on hand at period end: the consolidated ending inventory is overstated by $15, and group net income is inflated by $15 unearned profit.
- **Required Consolidation Elimination Entry**:
  $$\text{Dr } 5000\text{ (Consolidated COGS)} \quad \$15 \quad / \quad \text{Cr } 1210\text{ (Unrealized Intercompany Inventory Profit Reserve)} \quad \$15$$
  *(or Cr 1200 Inventory Asset, reducing inventory to original group cost)*.

### 3.2 Feasibility within Existing Inventory & Costing Architecture
- In AuraStock, `CostLayer` and `ItemCostProfile` in `apps/backend/app/models/costing.py` track inventory valuation by warehouse.
- When an intercompany purchase order is received via GRN, the receiving warehouse creates a `CostLayer` at the transfer unit price.
- By tracking `IntercompanyTransactionPair` linked to `PurchaseOrder` lines and comparing `quantity_received` vs `quantity_consumed` (from `CostLayerConsumption` and remaining `CostLayer.remaining_quantity`), the system can deterministically calculate:
  $$\text{Unrealized Profit} = \text{Remaining On-Hand Qty} \times (\text{Transfer Unit Price} - \text{Original Seller Cost})$$
- This capability directly completes multi-entity group financial reporting (Consolidated Trial Balance, Consolidated P&L, Consolidated Balance Sheet).

---

## 4. Reconciliation of Prior Completed Phases (Phases 17–30)

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
| **Phase 30** | Multi-Entity Intercompany Trade & Consolidation | **CLOSED** | [`apps/backend/app/models/intercompany.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/intercompany.py) & `intercompany_service.py` (`test_intercompany_trade_and_consolidation.py`) |

---

## 5. Platform Gap & Risk Assessment

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Unrealized Intercompany Inventory-Profit Elimination & Consolidated Financial Reporting Engine** | Phase 30 established intercompany trade and basic revenue/COGS/clearing eliminations, but deferred unrealized profit elimination on ending inventory held by affiliates and consolidated financial reporting across multi-entity hierarchies. | Uneliminated inventory markups distort consolidated asset valuation and group profitability, violating IFRS 10 / US GAAP ASC 810 statutory consolidation requirements. |
| **P2** | **Enterprise Document Management & Compliance Sign-Off** | System produces standard PDF reports; lacks blob storage backend for attachment versioning and cryptographic SHA-256 audit sign-offs. | Secondary document retention capability. |
| **P3** | **Field Service & Preventive Maintenance Management Engine** | Work center routings and shop-floor tracking are implemented; after-sales field maintenance tickets remain a potential future extension. | Specialized service industry capability. |

---

## 6. Ranked Phase 31 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 31 - P1)**: **Unrealized Intercompany Inventory-Profit Elimination & Consolidated Financial Reporting Engine**
   - *Objective*: Complete multi-entity consolidation by:
     - Calculating unrealized markup on intercompany inventory remaining on-hand at period close across buyer entities.
     - Generating balanced unrealized profit elimination JVs: Dr `5000` (Consolidated COGS) / Cr `1210` (Unrealized Intercompany Profit Reserve).
     - Providing a unified Consolidated Financial Reporting Engine (Consolidated Trial Balance, Consolidated P&L, Consolidated Balance Sheet) that rolls up multi-entity balances and nets all elimination entries.
   - *Business Value*: Guarantees 100% IFRS 10 / US GAAP ASC 810 group statutory compliance and eliminates distorted balance sheets in multi-company corporate hierarchies.
   - *Dependencies*: General Ledger (`gl_service.py`), Intercompany (`intercompany_service.py`), Costing (`CostLayer`), Period Closing (`AccountingPeriod`).
   - *Implementation Complexity*: Medium-High.
   - *Verification Complexity*: Deterministic (Markup math on ending inventory layers, balanced reserve elimination JVs, consolidated financial statement rollups).

2. **Rank 2 (Candidate Phase 32 - P2)**: **Enterprise Document Management, Versioned File Attachments & Audit Compliance Sign-Off Workflows**
   - *Objective*: Blob storage file management with cryptographic SHA-256 signatures.
   - *Business Value*: Archival compliance file management.
   - *Dependencies*: Storage abstraction, Audit logs.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 33 - P2)**: **Field Service & Preventive Maintenance Management Engine**
   - *Objective*: Preventive asset maintenance schedules and field service tickets.
   - *Business Value*: Field operations support.
   - *Dependencies*: Work Centers, Items Master.
   - *Implementation Complexity*: Medium.

---

## 7. Recommended Phase 31: Unrealized Intercompany Profit & Consolidated Reporting Engine

### 7.1 Architecture & Workflow Model
1. **On-Hand Intercompany Inventory Markup Tracking**:
   - For every `IntercompanyTransactionPair` with received inventory, query active `CostLayer` records at the receiving warehouse.
   - Calculate remaining on-hand quantity $Q_{\text{on\_hand}}$ and markup per unit $M = P_{\text{transfer}} - C_{\text{seller}}$.
   - Compute total unrealized intercompany profit:
     $$U = \sum \left( Q_{\text{on\_hand}} \times M \right)$$
2. **Automated Unrealized Profit Elimination Journal**:
   - Posts balanced elimination voucher:
     $$\text{Dr } 5000\text{ (Consolidated COGS)} \quad U \quad / \quad \text{Cr } 1210\text{ (Unrealized Intercompany Profit Reserve)} \quad U$$
3. **Consolidated Financial Statement Engine**:
   - `get_consolidated_trial_balance(tenant_id, period_id)`: Combines entity account balances and applies all period elimination JVs.
   - `get_consolidated_income_statement(tenant_id, period_id)`: Group Revenue, Eliminations, Net Consolidated P&L.
   - `get_consolidated_balance_sheet(tenant_id, period_id)`: Group Assets, Net of Eliminated Intercompany AR/AP and Inventory Markup Reserve.

---

## 8. Phase 31 Implementation Sequence

1. **Stage 31A — Data Models & Schemas**:
   - Create `apps/backend/app/models/consolidation_v2.py` (or extend `intercompany.py`).
   - Add `UnrealizedProfitElimination` model.
   - Create schemas in `apps/backend/app/schemas/consolidation_v2.py`.
2. **Stage 31B — Consolidated Reporting & Unrealized Profit Domain Service**:
   - `calculate_unrealized_intercompany_profit`
   - `post_unrealized_profit_elimination_jv`
   - `get_consolidated_financial_statements` (Trial Balance, P&L, Balance Sheet).
3. **Stage 31C — REST API Endpoints**:
   - Mount `/api/v1/intercompany/unrealized-profit` and `/api/v1/intercompany/consolidated-reports`.
4. **Stage 31D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_unrealized_profit_and_consolidated_reporting.py`.
   - Execute full platform regression across all backend test modules (>371 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.
