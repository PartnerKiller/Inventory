# Phase 28 Design Discovery: Post-Phase-27 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 27**, AuraStock is a unified, multi-company, multi-currency double-entry Enterprise Resource Planning (ERP) platform with complete inventory costing, shop-floor manufacturing, multi-echelon SCM, double-entry GL, statutory financial accounting, management cost centers, commitment budgeting, statistical demand forecasting, and multi-level approval workflows with Delegation of Authority (DoA).

### Comprehensive Audit Summary:
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, and customer invoicing.
- **Statutory Accounting & GL**: Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, **Accounting Period closing state machine** with **hard backdated posting/void guards**, **automated Year-End retained earnings closing ceremony (`3100`)**, **Multi-Currency exchange rates with realized/unrealized FX (`6300`)**, **Enterprise Multi-Jurisdiction Tax Engine (GST/VAT)** with **Input Tax Credit (`1400`) / Output Tax (`2200`) settlement**, and **Fixed Asset capitalization & automated depreciation schedules (SLM/WDV)**.
- **Management Accounting & Budgeting**: **Cost Center & Profit Center hierarchy**, **Departmental Budget allocations per period & GL account**, **Commitment Accounting on Purchase Orders**, **soft warning thresholds**, **hard budget overrun blocking (HTTP 400)**, **commitment actualization**, and **hierarchical variance rollups**.
- **Demand Forecasting & Replenishment**: **Holt-Winters Triple Exponential Smoothing** (Level, Trend, Seasonality), **Dynamic Service-Level Safety Stock ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$)**, **Dynamic $ROP = (\bar{D} \times \bar{L}) + SS$**, **Automated Replenishment Proposals**, and **1-Click conversion to authoritative Vendor Purchase Orders**.
- **Governance & Approval Workflows**: **Tiered Spend Authorization Matrix**, **Sequential Multi-Step Approvals**, **Document Release Locks** (PO, GRN, AP, GL, Manual JV, Budget Overrun, Asset Disposal), **SLA Timeout Escalation Engine**, and **Out-of-Office Delegation of Authority (DoA)**.
- **Identity & Automation**: Multi-tenant isolation, RFC 6238 TOTP MFA, session token families with reuse detection, OIDC SSO, transactional outbox relay, and background scheduler daemon.

---

## 2. Post-Phase-27 Platform Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           AuraStock ERP Platform                                        │
├────────────────────────────────┬───────────────────────────────────────┬────────────────────────────────┤
│ 1. Core Inventory & Valuation  │ 2. Commercial & B2B Portals           │ 3. Manufacturing & SCM         │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry Stock Ledger    │ • Sales Orders & Customer Invoices    │ • Multi-Level BOMs & Work Ctrs │
│ • FIFO / Moving Average Cost   │ • AR Allocations & Payment Gateways   │ • Shop-Floor Routing Locks     │
│ • Lot/Batch/Serial Traceability│ • Vendor POs, GRN & 3-Way Match       │ • In-Process QA Gates          │
│ • 1-Click Product Recalls      │ • B2B Customer & Supplier Portals     │ • Multi-Echelon SCM Nodes      │
│ • Rapid Warehouse Barcoding    │ • Customer Credit Limits & ASN        │ • Transfer Orders & In-Transit │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ 4. Statutory & Mgmt Accounting │ 5. Planning & Replenishment (P26)     │ 6. Governance & Control (P27)  │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry General Ledger  │ • Holt-Winters Seasonal Forecasting   │ • Tiered Spend Matrix (DoA)    │
│ • Accounting Period Lock (P22) │ • Dynamic Z-Score Safety Stock ($SS$) │ • Multi-Step Approval Engine   │
│ • Retained Earnings Close (P22)│ • Dynamic Reorder Point ($ROP$)       │ • Release Locks (PO/GRN/AP/GL) │
│ • FX & Tax Engine (GST/VAT)    │ • Automated Replenishment Proposals   │ • SLA Timeout Escalation       │
│ • Fixed Assets & Deprec (1500) │ • 1-Click PO Conversion & Idempotency │ • Delegate Substitution (OoO)  │
│ • Cost Centers & Budgets (P25) │ • Lead-Time & Demand Variance Models  │ • Permanent Rejection Halts    │
└────────────────────────────────┴───────────────────────────────────────┴────────────────────────────────┘
```

---

## 3. Financial, Planning & Governance Integrity Audit

### Complete Control-Plane Flow:
$$\text{Sales Velocity} \xrightarrow{\text{Forecast}} \text{Proposal} \xrightarrow{\text{PO Create}} \text{Tiered Approval Rule} \xrightarrow{\text{PENDING}} \text{Document Release Lock}$$
$$\text{Approval Step 1} \xrightarrow{\text{Manager}} \text{IN\_REVIEW} \xrightarrow{\text{Step 2 CFO}} \text{APPROVED} \implies \text{PO Released} \implies \text{Commitment Reserved (P25)}$$
$$\text{Physical Goods Arrive} \implies \text{Validate Release (P27)} \implies \text{GRN / Stock Ledger} \implies \text{3-Way Match AP} \implies \text{GL JV Posted}$$

### Audited Financial Invariants:
1. **Convergence**: Every material and financial mutation converges on the General Ledger (`GLAccount` & `JournalVoucher`).
2. **Release Protection**: No document (PO, GRN, AP Bill, Manual JV, Budget Overrun, Asset Disposal) can be executed, received, or posted while in `PENDING_APPROVAL`, `IN_REVIEW`, `ESCALATED`, or `REJECTED`.
3. **Period Locking**: No document can post or void into a `CLOSED` or `FINALIZED` accounting period.
4. **Historical FX & Tax Integrity**: Realized/unrealized FX gains/losses post to Account `6300`; Input Tax Credit (`1400`) and Output Tax (`2200`) settle cleanly with balanced JVs.

---

## 4. Reconciliation of Prior Completed Phases (Phases 17–27)

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

---

## 5. Platform Gap & Risk Assessment

Following the audit across all 27 phases, the remaining enterprise capabilities are classified below:

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **B2B Multi-Tier Dynamic Pricing & Customer Rebate Settlement** | Commercial sales currently use static flat price lists per customer without progressive quantity break tier curves (e.g. 1–49 units @ \$100, 50–199 units @ \$90, 200+ units @ \$80), promotional validity windows, customer group discount matrices, and retroactive volume rebates (e.g. 5% annual rebate credit note if cumulative spend $> \$500,000$). | B2B distributor contracts and enterprise wholesale sales cannot enforce volume tier pricing or settle contract rebates automatically, leading to manual spreadsheet calculations and billing errors. |
| **P2** | **Production Observability & OpenTelemetry Tracing** | Logging is structured JSON but lacks distributed OpenTelemetry span propagation across edge nodes, background workers, and API gateways. | Telemetry and distributed tracing are valuable for high-scale microservices or multi-region deployments. |
| **P2** | **Global Intercompany Transactions & Elimination Entries** | System supports multi-company and multi-tenant partitioning; lacks automated intercompany sales/purchase order pairs and consolidation elimination entries. | Valuable for complex conglomerate multi-legal-entity structures. |
| **P3** | **Tauri Desktop Client Local Migration Runner** | Edge sync handles offline mutations via REST; local SQLite migrations require clean initialization during upgrades. | Minor operational consideration during desktop app updates. |

---

## 6. Ranked Phase 28 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 28 - P1)**: **B2B Multi-Tier Dynamic Pricing Lists, Progressive Volume Discount Curves & Customer Rebate Settlement Engine**
   - *Objective*: Implement a comprehensive pricing and rebate management engine:
     - Tiered volume quantity break curves (`QuantityBreakTier`).
     - Customer group and channel pricing rules.
     - Contract promotional date windows with priority resolution.
     - Retroactive customer volume rebate agreements with automated calculation and Credit Note / GL posting (Dr `4100` Sales Rebates / Cr `1200` AR / `CustomerCreditNote`).
   - *Business Value*: Automates complex B2B commercial contract pricing, eliminates billing disputes, and streamlines wholesale distributor rebate settlements.
   - *Dependencies*: Sales Orders (`sales_orders.py`), Invoicing & AR (`invoicing.py`), Customer Portal (`portal_customer.py`), General Ledger (`gl_service.py`).
   - *Implementation Complexity*: Medium-High.
   - *Verification Complexity*: Deterministic (Quantity break boundary calculations, promotion priority resolution, rebate accrual math, credit note issuance).

2. **Rank 2 (Candidate Phase 29 - P2)**: **Enterprise OpenTelemetry Observability, Distributed Tracing & Prometheus Telemetry Engine**
   - *Objective*: OpenTelemetry span exporter, Prometheus `/metrics` scrape endpoint, worker queue depth metrics.
   - *Business Value*: High-volume cloud operational visibility.
   - *Dependencies*: Background jobs, Outbox relay.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 30 - P2)**: **Global Intercompany Transactions, Elimination Entries & Multi-Entity Consolidation Engine**
   - *Objective*: Automated intercompany sales/purchase order pairs and consolidation eliminations.
   - *Business Value*: Conglomerate multi-entity accounting.
   - *Dependencies*: General Ledger, Period Closing.
   - *Implementation Complexity*: High.

---

## 7. Recommended Phase 28: Dynamic Pricing & Customer Rebates

### 7.1 Pricing Hierarchy & Resolution Rules
1. **Price Resolution Priority**:
   $$\text{Customer-Specific Contract Price} \to \text{Customer Group Promotional Price} \to \text{Volume Tier Break} \to \text{Base Catalog Price}$$
2. **Progressive Quantity Break Curves**:
   - Tier 1: $1\text{--}49\text{ units} \implies \$100.00$
   - Tier 2: $50\text{--}199\text{ units} \implies \$90.00$ (10% discount)
   - Tier 3: $200+\text{ units} \implies \$80.00$ (20% discount)
3. **Retroactive Volume Rebate Agreements**:
   - Calculation: If $\sum \text{Invoiced Sales in Period} \ge \text{Target Spend Threshold}$, calculate $\text{Rebate Amount} = \text{Actual Sales} \times \text{Rebate \%}$.
   - Settlement: Automated generation of `CustomerCreditNote` and GL Journal Voucher:
     $$\text{Dr } 4100\text{ (Sales Discounts \& Rebates)} \quad / \quad \text{Cr } 1200\text{ (Accounts Receivable)}$$

### 7.2 Data Models (`apps/backend/app/models/pricing_v2.py`)
- `PriceRule`: `tenant_id`, `rule_name`, `customer_id`, `customer_group`, `item_id`, `min_quantity`, `max_quantity`, `discount_type` (`PERCENTAGE`, `FIXED_PRICE`, `AMOUNT_OFF`), `discount_value`, `start_date`, `end_date`, `priority`, `is_active`.
- `RebateAgreement`: `tenant_id`, `agreement_code`, `customer_id`, `start_date`, `end_date`, `target_spend_threshold`, `rebate_percentage`, `status` (`DRAFT`, `ACTIVE`, `SETTLED`, `EXPIRED`), `settled_amount`, `credit_note_id`.

---

## 8. Phase 28 Implementation Sequence

1. **Stage 28A — Data Models & Schemas**:
   - Create `apps/backend/app/models/pricing_v2.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/pricing_v2.py`.
2. **Stage 28B — Dynamic Pricing & Rebate Domain Service (`PricingServiceV2`)**:
   - Implement price resolution engine with quantity break curves and priority ordering.
   - Implement rebate calculation, spend threshold tracking, and automated Credit Note / GL posting.
3. **Stage 28C — REST API Endpoints**:
   - Mount `/api/v1/pricing/v2` router for rules, dynamic price quote resolution, and rebate agreements.
4. **Stage 28D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_dynamic_pricing_and_rebates.py`.
   - Execute full platform regression across all backend test modules (>355 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.

---

## 9. Phase 28 Verification Strategy

1. **Quantity Break Tiers**: Verify unit price adjusts dynamically based on ordered quantity across tier boundaries (e.g. 10 vs 50 vs 250 units).
2. **Promotional Validity Windows**: Verify promotional prices apply only within active date ranges and revert to standard price when expired.
3. **Price Resolution Priority**: Verify customer-specific contract overrides group discount and standard price list.
4. **Rebate Threshold Accrual**: Verify customer spend below threshold yields zero rebate; spend meeting/exceeding threshold accrues exact rebate.
5. **Rebate Credit Note & GL Posting**: Verify rebate settlement creates `CustomerCreditNote` and balanced Journal Voucher (Dr `4100` / Cr `1200`).
6. **Full Platform Regression**: Backend pytest, frontend Vitest, TypeScript compiler, web build, and packaging.
