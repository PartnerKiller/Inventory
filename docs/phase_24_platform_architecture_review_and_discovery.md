# Phase 24 Design Discovery: Post-Phase-23 Platform Architecture Review

## 1. Executive Summary

Following the completion and verification of **Phases 1 through 23**, AuraStock is a fully unified, multi-company, multi-currency double-entry Enterprise Resource Planning (ERP) platform.

### Comprehensive Audit Summary:
- **Core Physical Inventory**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/serial/batch traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start operation locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost layer capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, and customer invoicing.
- **Financial Unification & Compliance**: Standard Chart of Accounts, real-time balancing document JVs, trial balances, income statements, balance sheets, **Accounting Period closing state machine** with **hard backdated posting/void guards**, **automated Year-End retained earnings closing ceremony**, **Multi-Currency exchange rates with realized/unrealized FX accounting (`6300`)**, and **Enterprise Multi-Jurisdiction Tax Engine (GST/VAT)** with **Input Tax Credit (`1400`) / Output Tax (`2200`) settlement**.
- **Identity & Automation**: Multi-tenant isolation, RFC 6238 TOTP MFA, session token families with reuse detection, OIDC SSO, transactional outbox relay, and background scheduler daemon.

---

## 2. Post-Phase-23 Platform Capability Matrix

| Domain Subsystem | Current State | Correctness & Invariant Guarantees | Verification Status |
| :--- | :--- | :--- | :---: |
| **Physical Stock Ledger** | Double-entry balance cache | Row-level locking; zero negative stock; exact debit/credit balancing | **VERIFIED (PASS)** |
| **Inventory Costing** | FIFO & Moving Average | Cost layer preservation across transfers, production rollups, and receipts | **VERIFIED (PASS)** |
| **Traceability** | Serial/Lot/Batch genealogy | Bi-directional tree: Supplier Lot $\leftrightarrow$ Work Order $\leftrightarrow$ Finished Serial | **VERIFIED (PASS)** |
| **Manufacturing** | Work centers, routings, BOMs | Immutable BOM snapshot upon release; predecessor operation locks | **VERIFIED (PASS)** |
| **Quality Control** | In-process QA gates | Non-passing units routed to quarantine bin; blocked from sales allocation | **VERIFIED (PASS)** |
| **Supply Chain & SCM** | Multi-tier nodes & transfers | In-transit asset Account `1250`; landed freight capitalized to `CostLayer` | **VERIFIED (PASS)** |
| **Edge Synchronization**| Server-authoritative sync | Offline classification guard; UUIDv7 replay protection; HMAC signing | **VERIFIED (PASS)** |
| **General Ledger** | Double-entry financial engine | Real-time balanced JVs; trial balance; automated document postings | **VERIFIED (PASS)** |
| **Period Closing** | Calendar period state machine | Hard block on backdated JVs into closed periods; void rejection | **VERIFIED (PASS)** |
| **Year-End Closing** | Annual closing ceremony | Temporary P&L accounts ($4000\text{--}6200$) zeroed to Retained Earnings (`3100`)| **VERIFIED (PASS)** |
| **Multi-Currency & FX** | Exchange rates & FX ledger | Rate locking at document date; Realized & Unrealized FX Gain/Loss (`6300`)| **VERIFIED (PASS)** |
| **Enterprise Tax Engine** | Multi-tier GST/VAT/Sales Tax | Intra/Inter-state split; Input Tax Credit (`1400`) vs Output Tax (`2200`) | **VERIFIED (PASS)** |
| **Commercial Portals** | B2B Customer & Supplier | Role-scoped access; self-service invoices, ASN creation, catalog orders | **VERIFIED (PASS)** |
| **Identity & Security** | MFA TOTP, SSO, Sessions | RFC 6238 TOTP, Argon2id recovery codes, token reuse cascade invalidation | **VERIFIED (PASS)** |
| **Automation & Jobs** | Outbox relay, scheduler worker | Tenant-scoped background tasks; quiet hours; automated replenishment | **VERIFIED (PASS)** |

---

## 3. Reconciliation of Previously Deferred Items

| Deferred Item | Originating Phase | Current Status | Codebase & Test Verification Evidence |
| :--- | :---: | :---: | :--- |
| **Formal Accounting Period Closing** | Phase 17 | **RESOLVED & VERIFIED (Phase 22)** | `AccountingPeriod` state machine with hard backdated posting guards in `period_closing_service.py` & `test_period_closing_and_year_end.py` |
| **Formal Year-End Closing Batch** | Phase 17 | **RESOLVED & VERIFIED (Phase 22)** | Automated zeroing of temporary accounts $4000\text{--}6200$ to Equity Account $3100$ in `test_period_closing_and_year_end.py` |
| **Authentication Hardening / MFA / SSO** | Phase 19 | **RESOLVED & VERIFIED (Phase 19 & 22)** | `apps/backend/app/models/auth_security.py`, `totp_service.py`, `sso_service.py`, `test_auth_hardening_mfa_and_sso.py` |
| **In-Transit Asset Tracking (1250)** | Phase 21 | **RESOLVED & VERIFIED (Phase 21)** | Double-entry in-transit asset accounting and landed freight capitalization in `test_supply_chain_and_edge_sync.py` |
| **Multi-Currency & Tax Settlement** | Phase 23 | **RESOLVED & VERIFIED (Phase 23)** | Realized FX gain/loss (6300), ITC (1400), Output Tax (2200), and tax settlement in `test_tax_and_currency.py` |

---

## 4. Comprehensive Platform Gap & Risk Assessment

Following the audit of all 23 phases, the remaining enterprise capabilities are classified below:

| Priority | Subsystem Domain | Description of Gap | Business & Technical Impact | Recommended Action |
| :---: | :--- | :--- | :--- | :--- |
| **P1** | **Fixed Asset Management & Depreciation** | Physical plant, machinery, vehicles, and equipment are tracked without automated capitalization from PO/GRN, monthly depreciation schedules (SLM/WDV), or asset disposal accounting. | Property, Plant & Equipment (PP&E) is the final major balance sheet asset class missing from automated double-entry accounting. | **Phase 24 Scope: Fixed Asset Lifecycle, Capitalization & Automated Depreciation Engine** |
| **P2** | **Cost Center & Departmental Budgeting** | GL journal entries are posted at company/tenant level without departmental cost center tagging or budget vs actual variance controls. | Management accounting and departmental cost allocation require external spreadsheets. | Future Phase: Cost Center Allocation & Budgetary Controls |
| **P2** | **AI/Statistical Demand Forecasting** | Replenishment uses static/dynamic ROP; lacks seasonal ARIMA/exponential smoothing on historical sales velocity. | Seasonal inventory spikes must be planned manually. | Future Phase: AI Demand Intelligence |
| **P3** | **Tauri Desktop Local Schema Migrations** | Local SQLite on edge devices syncs mutations via REST, but local schema changes require clean initialization. | Minor operational maintenance during client updates. | Future Phase: Desktop Client Lifecycle |

---

## 5. Prioritized Platform Roadmap

```
Phase 24 (Single Highest-Value Immediate Focus - P1):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 24: Fixed Asset Lifecycle, Capitalization &                      │
│           Automated Depreciation Engine                                │
│ • Fixed Asset Registry (Machinery, Vehicles, Computers, Buildings)     │
│ • Asset Capitalization from Procurement / GRN                          │
│ • Straight-Line (SLM) & Written-Down-Value (WDV) Depreciation Schedules│
│ • Automated Monthly Depreciation Batch Runs (Dr 6400 / Cr 1550)        │
│ • Asset Transfer between Locations & Maintenance Capitalization        │
│ • Asset Retirement, Disposal & Gain/Loss on Asset Sale Accounting      │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 25 (Management Accounting - P2):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 25: Cost Center Allocation, Departmental Budgets & Variance      │
│ • Cost centers & profit centers tagging on GL journal lines            │
│ • Annual/Monthly departmental budget allocation & variance reporting   │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 26 (Intelligence - P2):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 26: AI Demand Intelligence & Dynamic Multi-Echelon Replenishment │
│ • Seasonal Holt-Winters & ARIMA forecasting models                     │
│ • Lead-time confidence intervals and service-level safety stocks       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Proposed Phase 24 Architecture: Fixed Asset Lifecycle & Depreciation Engine

### 6.1 Fixed Asset Lifecycle State Machine

$$\text{DRAFT} \xrightarrow{\text{Capitalize}} \text{ACTIVE} \xrightarrow{\text{Monthly Run}} \text{DEPRECIATING} \xrightarrow{\text{Retire/Sell}} \text{DISPOSED} \Big/ \text{SCRAPPED}$$

- **Asset Classes**:
  - `BUILDINGS` (Useful Life: 30 yrs, SLM)
  - `PLANT_MACHINERY` (Useful Life: 10 yrs, WDV 15%)
  - `VEHICLES` (Useful Life: 5 yrs, WDV 20%)
  - `COMPUTERS_IT` (Useful Life: 3 yrs, SLM)
  - `FURNITURE_FIXTURES` (Useful Life: 10 yrs, SLM)

### 6.2 Standard Chart of Accounts (COA) Integration for Fixed Assets

```
Balance Sheet Assets:
• Account 1500: Fixed Assets - Acquisition Cost (Class: ASSET, Normal: DEBIT)
• Account 1550: Accumulated Depreciation - Fixed Assets (Class: ASSET, Normal: CREDIT - Contra Asset)

Income Statement Expenses:
• Account 6400: Depreciation & Amortization Expense (Class: EXPENSE, Normal: DEBIT)
• Account 6450: Gain / Loss on Disposal of Fixed Assets (Class: EXPENSE, Normal: DEBIT)
```

### 6.3 Double-Entry Accounting Flows

1. **Asset Capitalization ($50,000 Equipment acquired via PO)**:
   $$\text{Dr } 1500 \text{ Fixed Asset Cost (\$50,000)} \quad / \quad \text{Cr } 2000 \text{ Accounts Payable (\$50,000)}$$
2. **Monthly Straight-Line Depreciation ($50,000 cost, $2,000 salvage, 5 yrs = $800/mo)**:
   $$\text{Dr } 6400 \text{ Depreciation Expense (\$800)} \quad / \quad \text{Cr } 1550 \text{ Accumulated Depreciation (\$800)}$$
3. **Asset Disposal / Sale after 2 yrs ($50,000 cost, $19,200 Acc Dep, sold for $35,000 Cash)**:
   - Book Value = $50,000 - $19,200 = $30,800.
   - Gain on Sale = $35,000 - $30,800 = $4,200.
   $$\text{Dr } 1000 \text{ Cash (\$35,000)} \quad / \quad \text{Dr } 1550 \text{ Acc Dep (\$19,200)} \quad / \quad \text{Cr } 1500 \text{ Asset Cost (\$50,000)} \quad / \quad \text{Cr } 6450 \text{ Gain on Sale (\$4,200)}$$

---

## 7. Phase 24 Implementation Sequence

1. **Stage 24A — Data Models & Schemas**:
   - Create `apps/backend/app/models/fixed_asset.py` (`FixedAssetClass`, `FixedAsset`, `DepreciationSchedule`, `DepreciationEntry`).
   - Register in `apps/backend/app/models/__init__.py`.
   - Update `STANDARD_COA` in `apps/backend/app/services/gl_service.py` with Accounts `1500`, `1550`, `6400`, `6450`.
   - Create schemas in `apps/backend/app/schemas/fixed_asset.py`.
2. **Stage 24B — Fixed Asset & Depreciation Domain Service**:
   - Implement `FixedAssetService`:
     - Asset registration and capitalization from PO/GRN.
     - Schedule generation for Straight-Line Method (SLM) and Written-Down-Value (WDV).
     - Automated monthly depreciation batch runner creating balanced GL vouchers (Dr `6400` / Cr `1550`).
     - Asset transfer between warehouse facilities.
     - Asset retirement, scrap, and sale with automatic gain/loss calculation (Account `6450`).
3. **Stage 24C — REST API Endpoints**:
   - Mount `/api/v1/assets` router for asset classes, fixed assets, depreciation schedules, batch runs, and disposal.
4. **Stage 24D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_fixed_assets_and_depreciation.py`.
   - Execute full platform regression across all backend test modules (>319 tests), frontend Vitest (37 tests), TypeScript, web production build, and packaging.

---

## 8. Phase 24 Verification Strategy

1. **Asset Capitalization**: Verify asset registration creates balancing JV (Dr `1500` / Cr `2000` or `1000`) and generates depreciation schedule.
2. **Straight-Line Depreciation (SLM)**: Verify monthly depreciation is constant: $\frac{\text{Cost} - \text{Salvage}}{\text{Useful Months}}$.
3. **Written-Down-Value (WDV)**: Verify monthly depreciation is proportional to remaining book value: $\text{Book Value} \times \frac{\text{Rate}}{12}$.
4. **Depreciation Batch Runner & Idempotency**: Running the monthly depreciation batch creates balancing JV (Dr `6400` / Cr `1550`) and re-running in the same period returns cached ACK with zero duplicate entries.
5. **Period Closing Integration**: Verify depreciation batch into a `CLOSED` accounting period is strictly rejected (HTTP 400).
6. **Asset Disposal & Gain/Loss on Sale**: Verify asset sale clears cost (Cr `1500`), clears accumulated depreciation (Dr `1550`), records cash (Dr `1000`), and balances gain/loss into Account `6450`.
7. **Full Platform Regression**: Backend pytest, frontend Vitest, TypeScript compiler, web build, and release packaging.
