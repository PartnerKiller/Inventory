# Phase 23 Design Discovery: Post-Phase-22 Platform Architecture Review

## 1. Executive Summary

With the successful completion and verification of **Phases 1 through 22**, the AuraStock platform stands as a full-scale, production-ready, double-entry Enterprise Resource Planning (ERP) platform.

### Platform Status Summary:
- **Core Ledger & Operations**: Double-entry physical stock ledger, FIFO/moving average cost layers, negative stock prevention, pessimistic row-level locking, rapid barcode scanning, 1-click product recall tree.
- **Commercial & Portals**: Sales orders, customer invoicing, AR settlements, payment gateway integration, B2B customer & supplier self-service portals.
- **Manufacturing & Production**: Multi-level BOMs, work centers, routings, shop-floor execution with operator concurrency locks, in-process quality inspection quarantine gates, automated WIP GL vouchers.
- **Supply Chain & Edge Sync**: Multi-echelon SCM nodes, transfer orders with in-transit asset accounting (`1250`), landed freight cost layer capitalization, server-authoritative edge sync with HMAC authentication and conflict backorders.
- **Financial Unification & Period Closing**: Real-time GL balancing, trial balances, balance sheets, income statements, **Accounting Period closing state machine** (`FUTURE` $\to$ `OPEN` $\to$ `SOFT_CLOSED` $\to$ `CLOSED` $\to$ `FINALIZED`), **hard backdated posting/void guards**, and **automated Year-End retained earnings closing ceremony** (Phases 17 & 22 completed).
- **Identity & Automation**: RFC 6238 TOTP MFA, session token families with reuse detection, OIDC SSO, transactional outbox relay, background scheduler/worker daemon.

---

## 2. Post-Phase-22 Platform Capability Matrix

| Domain Subsystem | Current Architectural State | Invariant & Correctness Guarantee | Verification Status |
| :--- | :--- | :--- | :---: |
| **Stock Ledger** | Double-entry physical inventory | Row-level locking on balance cache; zero negative stock; exact debit/credit | **VERIFIED (PASS)** |
| **Costing & Valuation** | FIFO & Moving Average layers | Unit cost preservation across transfers, production rollups, and receipts | **VERIFIED (PASS)** |
| **Traceability** | Lots, serials, batch numbers | Bi-directional tree: Supplier Lot $\leftrightarrow$ Work Order $\leftrightarrow$ Finished Serial | **VERIFIED (PASS)** |
| **Manufacturing** | Work centers, routings, BOMs | Immutable BOM snapshot upon release; Finish-to-Start predecessor locks | **VERIFIED (PASS)** |
| **Quality Control** | In-process & final QA gates | Non-passing units strictly routed to quarantine; blocked from pickable stock | **VERIFIED (PASS)** |
| **Supply Chain & SCM** | Multi-echelon nodes & transfers | In-transit asset Account `1250`; landed freight capitalized to `CostLayer` | **VERIFIED (PASS)** |
| **Edge Synchronization**| Server-authoritative sync | Offline classification guard; UUIDv7 replay protection; HMAC signing | **VERIFIED (PASS)** |
| **General Ledger** | Double-entry financial engine | Real-time balanced JVs; trial balance; automated document postings | **VERIFIED (PASS)** |
| **Period Closing** | Calendar period state machine | Hard block on backdated JVs into closed periods; void rejection | **VERIFIED (PASS)** |
| **Year-End Closing** | Annual closing ceremony | Temporary P&L accounts ($4000\text{--}6200$) zeroed to Retained Earnings (`3100`)| **VERIFIED (PASS)** |
| **Commercial Portals** | B2B Customer & Supplier portals | Role-scoped access; self-service invoices, ASN creation, catalog orders | **VERIFIED (PASS)** |
| **Identity & Security** | MFA TOTP, SSO, Session rotation | RFC 6238 TOTP, Argon2id recovery codes, token reuse cascade invalidation | **VERIFIED (PASS)** |
| **Automation & Jobs** | Outbox relay, scheduler worker | Tenant-scoped background tasks; quiet hours; automated replenishment | **VERIFIED (PASS)** |

---

## 3. Comprehensive Platform Gap & Risk Assessment

Following the audit of all 22 phases, the remaining enterprise gaps are classified below:

| Priority | Domain Area | Description of Gap | Business & Technical Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Multi-Currency & FX Accounting** | Invoices and POs currently assume single currency (`USD`); no automated foreign currency revaluation or realized/unrealized FX gain/loss journal vouchers. | Cross-border procurement and international customer billing produce currency distortion in financial statements. |
| **P1** | **Enterprise Tax Engine (GST/VAT)** | Basic sales tax percentage exists, but lacks multi-jurisdiction tax schedules (CGST/SGST/IGST for India, state/county sales tax for US, VAT for EU/UK), tax exemption rules, and Input Tax Credit (ITC) ledger accounts. | Inability to produce statutory tax audit schedules or claim input tax credits on vendor purchases. |
| **P2** | **Fixed Asset Management** | Physical equipment and machinery tracked informally; no automated monthly straight-line/declining balance depreciation runs posting to Accumulated Depreciation Asset accounts. | Manual calculation of asset depreciation and net book values required outside the ERP. |
| **P2** | **AI/Statistical Demand Forecasting** | Replenishment uses static/dynamic ROP; lacks seasonal ARIMA/exponential smoothing and historical sales regression models. | Inability to anticipate seasonal demand spikes or supplier lead-time fluctuations automatically. |
| **P3** | **Tauri Local SQLite Migrations** | Edge desktop clients sync mutations via REST, but local desktop SQLite schemas require manual startup verification on version updates. | Minor operational risk during desktop client upgrades. |

---

## 4. Prioritized Roadmap for Future Phases

```
Phase 23 (Single Highest-Value Immediate Focus - P1):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 23: Multi-Currency Accounting, FX Revaluation &                  │
│           Enterprise Tax Engine (GST / VAT / Sales Tax)               │
│ • Currency exchange rate table with historical timestamp tracking      │
│ • Multi-currency Purchase Orders, Invoices, and AR/AP Settlements      │
│ • Automated Realized & Unrealized FX Gain/Loss GL Vouchers (Acc 6300)   │
│ • Multi-jurisdiction tax rules (inclusive/exclusive, compound tax)     │
│ • Input Tax Credit (ITC) / Output Tax liability double-entry ledger    │
│ • Statutory Tax Summary & Reconciliation Report exports                │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 24 (Operational - P2):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 24: Fixed Asset Lifecycle, Capitalization & Depreciation Engine  │
│ • Fixed asset registration, asset classes, and useful life definitions │
│ • Straight-line and declining-balance automated monthly depreciation   │
│ • Asset disposal, write-off, and gain/loss on asset sale accounting    │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 25 (Intelligence - P2):
┌────────────────────────────────────────────────────────────────────────┐
│ Phase 25: AI Demand Intelligence & Dynamic Multi-Echelon Forecasting   │
│ • Seasonal Holt-Winters & ARIMA forecasting models                     │
│ • Lead-time confidence intervals and service-level safety stocks       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Proposed Phase 23 Architecture: Multi-Currency & Enterprise Tax Engine

### 5.1 Multi-Currency Data Model & Real-Time FX Revaluation

```
Currency Exchange Rates (Base Currency = Tenant Default, e.g. USD / INR)
┌───────────────────────┬───────────────────┬───────────────┬─────────────────────────┐
│ From Currency         │ To Currency       │ Rate          │ Effective Date          │
├───────────────────────┼───────────────────┼───────────────┼─────────────────────────┤
│ EUR                   │ USD               │ 1.0850        │ 2026-08-01 00:00:00     │
│ GBP                   │ USD               │ 1.2800        │ 2026-08-01 00:00:00     │
│ JPY                   │ USD               │ 0.0068        │ 2026-08-01 00:00:00     │
└───────────────────────┴───────────────────┴───────────────┴─────────────────────────┘
```

#### FX Accounting Journal Entries:
1. **Foreign Invoice Created (€10,000 @ 1.08 = $10,800)**:
   $$\text{Dr } 1100 \text{ AR (\$10,800)} \quad / \quad \text{Cr } 4000 \text{ Sales Revenue (\$10,800)}$$
2. **Customer Settles Invoice when Rate moves to 1.10 (€10,000 @ 1.10 = $11,000)**:
   $$\text{Dr } 1000 \text{ Cash (\$11,000)} \quad / \quad \text{Cr } 1100 \text{ AR (\$10,800)} \quad / \quad \text{Cr } 6300 \text{ Realized FX Gain (\$200)}$$
3. **Period-End Unrealized FX Revaluation**:
   - Revalues open foreign AR/AP balances at month-end closing spot rates and posts balancing Unrealized FX Gain/Loss JVs.

---

### 5.2 Enterprise Multi-Jurisdiction Tax Engine (GST / VAT / Sales Tax)

#### Tax Architecture Rules:
- **Tax Jurisdictions**: National (Federal GST/VAT), State/Provincial, Local/Municipal.
- **Tax Types**:
  - `OUTPUT_TAX`: Tax collected on sales (Liability: Account `2200 Sales Tax / GST Payable`).
  - `INPUT_TAX_CREDIT`: Tax paid on procurement (Asset: Account `1400 Input Tax Credit / Recoverable VAT`).
  - `EXEMPT`: Zero-rated or export sales.
- **Double-Entry Tax Flow**:
  1. **Vendor Purchase ($1,000 + 18% GST = $1,180)**:
     $$\text{Dr } 1200 \text{ Inventory (\$1,000)} \quad / \quad \text{Dr } 1400 \text{ Input Tax Credit (\$180)} \quad / \quad \text{Cr } 2000 \text{ AP (\$1,180)}$$
  2. **Customer Sale ($2,000 + 18% GST = $2,360)**:
     $$\text{Dr } 1100 \text{ AR (\$2,360)} \quad / \quad \text{Cr } 4000 \text{ Revenue (\$2,000)} \quad / \quad \text{Cr } 2200 \text{ Output GST Payable (\$360)}$$
  3. **Month-End Tax Settlement (Net Payable = Output \$360 - Input \$180 = \$180)**:
     $$\text{Dr } 2200 \text{ Output GST (\$360)} \quad / \quad \text{Cr } 1400 \text{ Input Tax (\$180)} \quad / \quad \text{Cr } 1000 \text{ Cash Settlement (\$180)}$$

---

## 6. Phase 23 Implementation Sequence

1. **Stage 23A — Data Models & Schemas**:
   - Create `apps/backend/app/models/tax_and_currency.py` (`CurrencyExchangeRate`, `TaxJurisdiction`, `TaxRate`, `TaxGroup`, `TaxItemMapping`).
   - Create Pydantic schemas in `apps/backend/app/schemas/tax_and_currency.py`.
2. **Stage 23B — Multi-Currency & FX Revaluation Service**:
   - Implement `CurrencyService` supporting exchange rate resolution, foreign transaction conversion, and month-end automated unrealized FX revaluation JVs.
3. **Stage 23C — Enterprise Tax Engine**:
   - Implement `TaxService` supporting inclusive/exclusive calculation, compound rates, reverse charges, and automated double-entry GL postings to Accounts `1400 (Input Tax Credit)` and `2200 (Output Tax Payable)`.
4. **Stage 23D — Commercial Integration**:
   - Connect `TaxService` and `CurrencyService` into `SalesService` (Invoicing), `PurchaseService` (GRN/PO), and `APService` (3-way match).
5. **Stage 23E — Endpoints, Verification & Platform Regression**:
   - Mount `/api/v1/tax` and `/api/v1/currency` REST routers.
   - Build targeted automated tests in `test_tax_and_currency.py`.
   - Execute full platform regression across all 38 backend test modules, frontend Vitest, and release packaging.

---

## 7. Phase 23 Verification Strategy

1. **Exchange Rate Precision & Historical Rates**: Verify transaction locks exchange rate at document creation date; rate changes do not mutate posted history.
2. **Realized FX Gain/Loss Accounting**: Test invoice generated at Rate $R_1$, settled at Rate $R_2$; verify differential posts to Account `6300 (Realized FX Gain/Loss)`.
3. **Month-End Unrealized FX Revaluation**: Open foreign AR/AP revalued at period-end closing spot rate; balancing JV posted.
4. **Multi-Jurisdiction Tax Calculation**: Test single-tier (US State), split-tier (India CGST 9% + SGST 9%), and compound taxes.
5. **Input Tax Credit (ITC) Offset**: Verify vendor purchase posts Dr `1400`, customer sale posts Cr `2200`, and tax settlement zeroes both accounts with exact net payment.
6. **Statutory Tax Export**: Export tax reconciliation summary for period range with exact breakdown of taxable bases and collected taxes.
7. **Full Platform Regression**: Backend pytest (>311 tests), frontend Vitest (37 tests), TypeScript, web production build, and packaging.
