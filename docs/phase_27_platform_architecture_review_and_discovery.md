# Phase 27 Design Discovery: Post-Phase-26 Platform Architecture Review

## 1. Executive Summary

Following the structural completion and formal closure of **Phases 1 through 26**, AuraStock is a fully integrated, multi-company, multi-currency double-entry Enterprise Resource Planning (ERP) platform with complete physical inventory, shop-floor manufacturing, multi-echelon SCM, double-entry GL, statutory financial accounting, management cost centers, commitment budgeting, and statistical demand forecasting.

### Comprehensive Audit Summary:
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, and customer invoicing.
- **Statutory Accounting & GL**: Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, **Accounting Period closing state machine** with **hard backdated posting/void guards**, **automated Year-End retained earnings closing ceremony (`3100`)**, **Multi-Currency exchange rates with realized/unrealized FX (`6300`)**, **Enterprise Multi-Jurisdiction Tax Engine (GST/VAT)** with **Input Tax Credit (`1400`) / Output Tax (`2200`) settlement**, and **Fixed Asset capitalization & automated depreciation schedules (SLM/WDV)**.
- **Management Accounting & Budgeting**: **Cost Center & Profit Center hierarchy**, **Departmental Budget allocations per period & GL account**, **Commitment Accounting on Purchase Orders**, **soft warning thresholds**, **hard budget overrun blocking (HTTP 400)**, **commitment actualization**, and **hierarchical variance rollups**.
- **Demand Forecasting & Replenishment**: **Holt-Winters Triple Exponential Smoothing** (Level, Trend, Seasonality), **Dynamic Service-Level Safety Stock ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$)**, **Dynamic $ROP = (\bar{D} \times \bar{L}) + SS$**, **Automated Replenishment Proposals**, and **1-Click conversion to authoritative Vendor Purchase Orders**.
- **Identity & Automation**: Multi-tenant isolation, RFC 6238 TOTP MFA, session token families with reuse detection, OIDC SSO, transactional outbox relay, and background scheduler daemon.

---

## 2. Post-Phase-26 Platform Architecture Map

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
│ 4. Statutory & Mgmt Accounting │ 5. Planning & Replenishment (P26)     │ 6. Identity & Infrastructure   │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry General Ledger  │ • Holt-Winters Seasonal Forecasting   │ • Multi-Tenant Partitioning    │
│ • Accounting Period Lock (P22) │ • Dynamic Z-Score Safety Stock ($SS$) │ • RFC 6238 TOTP MFA Hardening  │
│ • Retained Earnings Close (P22)│ • Dynamic Reorder Point ($ROP$)       │ • OIDC / PKCE Single Sign-On   │
│ • FX & Tax Engine (GST/VAT)    │ • Automated Replenishment Proposals   │ • Token Family Rotation        │
│ • Fixed Assets & Deprec (1500) │ • 1-Click PO Conversion & Idempotency │ • Transactional Outbox Relay   │
│ • Cost Centers & Budgets (P25) │ • Lead-Time & Demand Variance Models  │ • Background Scheduler Daemon  │
└────────────────────────────────┴───────────────────────────────────────┴────────────────────────────────┘
```

---

## 3. Financial & Planning Integrity Audit

### Complete Planning-to-Financial Chain Verification:
$$\text{Demand History} \xrightarrow{\text{Holt-Winters}} \text{Forecast} \xrightarrow{\text{Z-Score Variance}} \text{Safety Stock} \xrightarrow{+ (\bar{D}\times\bar{L})} \text{ROP} \xrightarrow{\text{Stock Deficit}} \text{Proposal} \xrightarrow{\text{PO Conversion}} \text{Purchase Order}$$
$$\text{Purchase Order} \xrightarrow{\text{Commitment Accounting}} \text{Department Budget Line} \xrightarrow{\text{Goods Receipt}} \text{GRN / Stock Ledger} \xrightarrow{\text{3-Way Match}} \text{Vendor Invoice} \xrightarrow{\text{GL JV}} \text{AP (2000) / P&L (6000)}$$

### Audited Financial Invariants:
1. **Convergence**: Every material and financial transaction generates balanced double-entry Journal Vouchers (`Dr == Cr`) converging on the General Ledger (`GLAccount` & `JournalVoucher`).
2. **Budget Protection**: Purchase Orders generated from replenishment proposals strictly adhere to Phase 25 commitment accounting, checking available budget and enforcing hard caps or generating soft threshold warnings.
3. **Period Locking**: No document (PO, GRN, Invoice, Payment, Depreciation, Asset Disposal, Budget Commitment) can post or void into a `CLOSED` or `FINALIZED` accounting period.
4. **Historical FX Rates**: Invoices and payments retain fixed historical exchange rates, posting realized currency gains/losses to Account `6300`.
5. **Tax Compliance**: Automated split of Input Tax Credit (`1400`) and Output Tax (`2200`) with period-end tax settlement vouchers.

---

## 4. Reconciliation of Prior Completed Phases (Phases 17–26)

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

---

## 5. Platform Gap & Risk Assessment

Following the audit across all 26 phases, the remaining enterprise capabilities are classified below:

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Multi-Level Approval Workflows & Delegation of Authority (DoA)** | The ERP currently executes financial and procurement actions (POs, Vendor Bills, GL Manual Adjustments, Asset Write-offs, Budget Overrun Exceptions) directly upon user submission. In enterprise environments, spend and financial adjustments must be routed through configurable hierarchical approval tiers with Delegation of Authority (DoA) matrices, out-of-office delegate substitutions, and audit logging. | Without formal approval chains, organizations cannot enforce internal financial controls (SOX / statutory compliance), exposing businesses to unauthorized spend and rogue commitments. |
| **P2** | **Production Observability & OpenTelemetry Tracing** | Logging is currently JSON-structured but lacks distributed OpenTelemetry span propagation across edge nodes, background workers, and API gateways. | Telemetry and distributed tracing are valuable for high-scale microservices or multi-region deployments. |
| **P2** | **B2B Multi-Tier Dynamic Price Lists & Rebates** | System supports customer price lists; lacks progressive volume discount curves and retroactive sales rebate settlements. | Minor commercial flexibility enhancement. |
| **P3** | **Tauri Desktop Client Local Migration Runner** | Edge sync handles offline mutations via REST; local SQLite migrations require clean initialization during upgrades. | Minor operational consideration during desktop app updates. |

---

## 6. Ranked Phase 27 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 27 - P1)**: **Multi-Level Approval Workflows, Hierarchy-Based Spend Delegation of Authority (DoA) & Financial Escalation Engine**
   - *Objective*: Build a universal, multi-entity approval workflow engine enforcing tiered spending limits, role-based Delegation of Authority (DoA), approval escalation SLAs, delegate substitution (out-of-office), and approval action logs across Purchase Orders, Vendor Invoices, Manual Journal Vouchers, Budget Overrun Exceptions, and Asset Disposals.
   - *Business Value*: Essential for statutory governance (SOX / internal financial audit), prevents unauthorized multi-thousand-dollar commitments, and establishes enterprise managerial hierarchy controls.
   - *Dependencies*: Purchasing (`purchase_service.py`), Budgeting (`budget_service.py`), GL (`gl_service.py`), Fixed Assets (`fixed_asset_service.py`), Users & Roles (`auth.py`).
   - *Implementation Complexity*: Medium-High.
   - *Verification Complexity*: Deterministic (Tier threshold boundaries, multi-level sequential approvals, timeout escalations, delegate substitutions, rejection rollbacks).

2. **Rank 2 (Candidate Phase 28 - P2)**: **Enterprise OpenTelemetry Observability, Distributed Tracing & Prometheus Telemetry Engine**
   - *Objective*: OpenTelemetry span exporter, Prometheus `/metrics` scrape endpoint, worker queue depth metrics.
   - *Business Value*: High-volume cloud operational visibility.
   - *Dependencies*: Background jobs, Outbox relay.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 29 - P2)**: **B2B Multi-Tier Dynamic Price Lists, Volume Rebates & Contract Management**
   - *Objective*: Commercial discount tier curves and volume rebate settlements.
   - *Business Value*: Commercial sales flexibility.
   - *Dependencies*: Invoicing, Sales Orders.
   - *Implementation Complexity*: Medium.

---

## 7. Recommended Phase 27: Multi-Level Approval Workflows & Delegation of Authority (DoA)

### 7.1 Architecture & Workflow Model
1. **Tiered Spend Authorization Matrix**:
   - **Tier 1 ($<\$5,000)**: Auto-approved or single Department Manager approval.
   - **Tier 2 ($\$5,000\text{--}\$25,000)**: Department Manager $\to$ Division Director.
   - **Tier 3 ($\$25,000\text{--}\$100,000)**: Division Director $\to$ VP of Operations / Finance.
   - **Tier 4 ($>\$100,000$)**: CFO / Executive Board approval.
   - **Exception Tier (Budget Overrun)**: If an operation exceeds budget warning/cap, routes directly to Financial Controller.
2. **Approval Request Lifecycle & State Machine**:
   $$\text{PENDING\_APPROVAL} \xrightarrow{\text{Step 1 Approved}} \text{IN\_REVIEW} \xrightarrow{\text{Final Step Approved}} \text{APPROVED} \implies \text{Auto-Execute Document}$$
   $$\text{PENDING\_APPROVAL} \xrightarrow{\text{Rejected}} \text{REJECTED} \implies \text{Unlock/Cancel Document}$$
   $$\text{PENDING\_APPROVAL} \xrightarrow{\text{SLA Timeout}} \text{ESCALATED} \implies \text{Notify Next-in-Line Approver}$$
3. **Delegation & Delegate Substitution**:
   - Support temporary delegate assignment for out-of-office approvers with start/end date boundaries.

### 7.2 Data Models (`apps/backend/app/models/approval.py`)
- `ApprovalRule`: `tenant_id`, `entity_type` (`PURCHASE_ORDER`, `VENDOR_INVOICE`, `JOURNAL_VOUCHER`, `BUDGET_OVERRUN`, `ASSET_DISPOSAL`), `min_amount`, `max_amount`, `cost_center_id`, `step_number`, `approver_role_id`, `approver_user_id`, `sla_hours`, `is_active`.
- `ApprovalRequest`: `tenant_id`, `entity_type`, `entity_id`, `document_reference`, `requested_by_user_id`, `total_amount`, `cost_center_id`, `status` (`PENDING`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `ESCALATED`, `CANCELLED`), `current_step_number`, `total_steps`.
- `ApprovalStep`: `request_id`, `step_number`, `approver_user_id`, `assigned_role_id`, `status` (`PENDING`, `APPROVED`, `REJECTED`, `DELEGATED`, `SKIPPED`), `action_taken_at`, `comments`.
- `ApprovalDelegation`: `user_id`, `delegate_user_id`, `start_date`, `end_date`, `reason`, `is_active`.

---

## 8. Phase 27 Implementation Sequence

1. **Stage 27A — Data Models & Schemas**:
   - Create `apps/backend/app/models/approval.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/approval.py`.
2. **Stage 27B — Approval Engine Domain Service (`ApprovalService`)**:
   - Implement rule evaluation against document entity and amount.
   - Implement approval request initiation, multi-step sequential approval, rejection with rollback, delegate redirection, and SLA timeout escalation.
   - Integrate approval guards into `PurchaseService`, `GLService`, and `BudgetService`.
3. **Stage 27C — REST API Endpoints**:
   - Mount `/api/v1/approvals` router for managing rules, viewing pending approvals, submitting approve/reject decisions, and configuring delegations.
4. **Stage 27D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_multi_level_approvals_and_doa.py`.
   - Execute full platform regression across all backend test modules (>347 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.

---

## 9. Phase 27 Verification Strategy

1. **Tiered Spend Boundary Rules**: Verify documents $< \$5,000$ auto-approve or require 1 step, while $\$50,000$ documents require multi-tier sequential sign-off.
2. **Sequential Multi-Step Enforcement**: Verify Step 2 approver cannot approve before Step 1 completes.
3. **Rejection Rollback**: Verify rejecting at any step sets document to `REJECTED` and releases any pending locks.
4. **Delegation Substitution**: Verify active out-of-office delegation permits assigned delegate to approve on behalf of original approver.
5. **PO & GL Integration**: Verify high-value POs and manual JVs remain in `PENDING_APPROVAL` until workflow finishes, preventing premature inventory receipts or GL postings.
6. **Full Platform Regression**: All backend pytest test suites, frontend Vitest, TypeScript compiler, web build, and release packaging.
