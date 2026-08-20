# Phase 33 Design Discovery: Post-Phase-32 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 32**, AuraStock is a fully integrated double-entry Enterprise Resource Planning (ERP) platform. It provides double-entry stock valuation, FIFO/moving-average costing layers, multi-echelon SCM nodes, multi-level BOMs and routing locks, statutory accounting periods and fiscal year closing ceremonies, multi-currency historical rate locking, enterprise GST/VAT tax settlements, fixed asset capitalization and automated depreciation, cost center budgeting and commitment overrun guards, Holt-Winters demand forecasting, multi-level approval workflows with Delegation of Authority (DoA), B2B dynamic pricing with customer volume rebates, Prometheus observability with distributed tracing, Multi-Entity Intercompany Trade with Automated Mirrored Transactions, Unrealized Intercompany Inventory-Profit Elimination & Consolidated Financial Reporting (Consolidated Trial Balance, P&L, Balance Sheet), and **Enterprise Document Management (EDMS) with Cryptographic SHA-256 Versioned File Attachments & Multi-Role Compliance Audit Sign-Off Workflows**.

### Complete Platform Scope (Phases 1–32):
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, customer invoicing, dynamic pricing break curves, and volume rebate settlements (Dr `4100` / Cr `1200`).
- **Statutory Accounting & GL**: Standard Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, accounting period closing state machine with hard backdated posting guards, automated year-end retained earnings closing (`3100`), multi-currency exchange rates with realized/unrealized FX (`6300`), enterprise GST/VAT with Input Tax Credit (`1400`) vs Output Tax (`2200`), fixed asset capitalization (`1500`) and automated SLM/WDV depreciation schedules (`1550` / `6400`).
- **Management Accounting & Budgeting**: Cost Center & Profit Center hierarchy, departmental budget allocations per period & GL account, commitment accounting on Purchase Orders, soft warning thresholds, hard budget overrun blocks (HTTP 400), commitment actualization, and hierarchical variance rollups.
- **Planning & Intelligence**: Holt-Winters triple exponential smoothing, dynamic $Z$-score safety stock modeling ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$), dynamic $ROP$, replenishment proposal generation, and 1-click conversion to authoritative Vendor Purchase Orders.
- **Governance & Control**: Tiered spend authorization matrix (DoA), sequential multi-step approval engine, document release locks (PO, GRN, AP, GL, Manual JV, Budget Overrun, Asset Disposal), SLA timeout escalations, and out-of-office delegate substitutions.
- **Observability & Diagnostics**: Prometheus telemetry scrape endpoint (`/metrics`), `TelemetryMiddleware` assigning and propagating `X-Trace-ID`, `X-Span-ID`, `X-Response-Time`, and deep diagnostic health probes (`/health/live`, `/health/ready`, `/health/subsystems`).
- **Multi-Entity Intercompany Trade & Consolidation (P30–31)**: Intercompany trading agreements, transfer pricing rules (`COST_PLUS`, `FIXED_PRICE`, `CATALOG`), automated mirrored Purchase Order generation from Intercompany Sales Orders, intercompany AR (`1300`) and AP (`2300`) clearing accounting, group consolidation elimination Journal Vouchers (Dr `4000` Revenue / Cr `5000` COGS and Dr `2300` Due to Affiliates / Cr `1300` Due from Affiliates), Unrealized Inventory-Profit Elimination (Dr `5000` COGS / Cr `1210` Inventory Markup Reserve), and Consolidated Financial Statement Reporting (Consolidated Trial Balance, Consolidated P&L, Consolidated Balance Sheet).
- **Document Management & Compliance Sign-Off (P32)**: Polymorphic document attachments bound to core business aggregates (POs, SOs, Invoices, GRNs, Assets, JVs), automated versioning with `is_latest` tracking, cryptographic SHA-256 tamper verification probes, and multi-role audit compliance sign-off workflows with HMAC-SHA256 digital signatures.

---

## 2. Post-Phase-32 Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           AuraStock ERP Platform                                        │
├────────────────────────────────┬───────────────────────────────────────┬────────────────────────────────┤
│ 1. Core Inventory & Valuation  │ 2. Commercial, Pricing & Intercompany │ 3. Manufacturing & SCM         │
├────────────────────────────────┼───────────────────────────────────────┼────────────────────────────────┤
│ • Double-Entry Stock Ledger    │ • Sales Orders & Invoices             │ • Multi-Level BOMs & Work Ctrs │
│ • FIFO / Moving Average Cost   │ • Dynamic Price Rules & Rebates       │ • Shop-Floor Routing Locks     │
│ • Lot/Batch/Serial Traceability│ • Intercompany Partners & Trading     │ • In-Process QA Quarantine     │
│ • 1-Click Product Recalls      │ • Mirrored POs & Intercompany AR/AP   │ • Multi-Echelon SCM Nodes      │
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
│ 7. Telemetry, Group Consolidation & Document Compliance (Phases 29–32)                                  │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Prometheus Scrape Endpoint (`/metrics`) & Distributed Tracing (`X-Trace-ID`, `X-Response-Time`)      │
│ • Group Consolidation Elimination Engine (Dr 4000 / Cr 5000 and Dr 2300 / Cr 1300)                     │
│ • Unrealized Intercompany Profit Elimination (Dr 5000 / Cr 1210 Inventory Reserve) (Phase 31)           │
│ • Consolidated Financial Reporting Engine (Consolidated Trial Balance, P&L, Balance Sheet) (Phase 31)  │
│ • EDMS Polymorphic Attachments, SHA-256 Tamper Probes & Compliance Sign-Off Workflows (Phase 32)       │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Reconciliation of Prior Completed Phases (Phases 17–32)

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
| **Phase 31** | Unrealized Profit & Consolidated Reporting | **CLOSED** | [`apps/backend/app/models/intercompany.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/intercompany.py) & `intercompany_service.py` (`test_unrealized_profit_and_consolidated_reporting.py`) |
| **Phase 32** | Document Management & Audit Sign-Off | **CLOSED** | [`apps/backend/app/models/edms.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/edms.py) & `edms_service.py` (`test_document_management_and_signoff.py`) |

---

## 4. Platform Gap & Risk Assessment

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Enterprise Preventive Maintenance, Asset Work Orders & Field Service Scheduling Engine** | Fixed assets (Phase 24) track asset acquisition, capitalization, and depreciation, and manufacturing (Phase 20) tracks work center routings, but there is no integrated engine for automated preventive maintenance scheduling (calendar intervals or meter runtime), maintenance work orders (MWO), spare parts inventory consumption from double-entry stock ledger, labor cost tracking, and equipment downtime logging. | Unplanned machinery breakdowns disrupt manufacturing schedules, spare parts consumed in maintenance are unaccounted for, and asset operating costs cannot be tracked accurately against GL Maintenance Expense (`6150`). |
| **P2** | **Customer Loyalty Points & Tiered Rewards Program Engine** | Dynamic pricing and volume breaks are implemented; B2C points-based loyalty remains a secondary commercial feature. | Nice-to-have commercial feature. |
| **P3** | **Vendor Supplier Scorecard, Performance KPI & SLA Compliance Engine** | Vendor POs, 3-way match, and returns are implemented; automated vendor delivery scorecards remain a future optimization. | Secondary procurement analytics. |

---

## 5. Ranked Phase 33 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 33 - P1)**: **Enterprise Preventive Maintenance, Asset Work Orders & Field Service Scheduling Engine**
   - *Objective*: Implement an end-to-end Enterprise Asset Maintenance & Field Service Engine:
     - `MaintenanceSchedule`: `tenant_id`, `asset_id` (or `work_center_id`), `schedule_type` (`CALENDAR_INTERVAL`, `RUNTIME_HOURS`), `frequency_days`, `last_performed_at`, `next_due_at`, `is_active`.
     - `MaintenanceWorkOrder`: `tenant_id`, `mwo_number`, `asset_id`, `schedule_id`, `work_center_id`, `assigned_technician_id`, `priority` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), `status` (`DRAFT`, `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`), `scheduled_start_date`, `actual_completion_date`, `downtime_hours`, `labor_hours`, `notes`.
     - `MWOSparePart`: `tenant_id`, `mwo_id`, `item_variant_id`, `quantity_required`, `quantity_consumed`, `unit_cost`, `total_cost`.
     - Integration with `StockEngine`: Completing maintenance with spare parts automatically issues stock ledger transaction (`MAINTENANCE_CONSUMPTION`), crediting Inventory Asset (`1200`) and debiting Maintenance & Repair Expense (`6150`).
   - *Business Value*: Eliminates unplanned equipment breakdowns, automates spare parts inventory depletion, and provides precise asset lifecycle operating cost analytics.
   - *Dependencies*: Fixed Assets (`fixed_asset.py`), Work Centers (`advanced_manufacturing.py`), Stock Ledger (`StockEngine`), GL (`gl_service.py`).
   - *Implementation Complexity*: Medium-High.
   - *Verification Complexity*: Deterministic (Schedule recurrence triggers, spare part stock ledger mutations, GL Dr `6150` / Cr `1200`, MWO state machine transitions).

2. **Rank 2 (Candidate Phase 34 - P2)**: **Customer Loyalty Points & Tiered Rewards Program Engine**
   - *Objective*: Points accrual and redemption rules for repeat buyers.
   - *Business Value*: B2C customer retention.
   - *Dependencies*: Sales Orders, Customer Portal.
   - *Implementation Complexity*: Low-Medium.

3. **Rank 3 (Candidate Phase 35 - P2)**: **Vendor Supplier Scorecard, Performance KPI & SLA Compliance Engine**
   - *Objective*: Automated vendor scoring based on on-time delivery, quality rejection rate, and invoice matching accuracy.
   - *Business Value*: Procurement vendor ranking.
   - *Dependencies*: Purchasing, Quality, AP.
   - *Implementation Complexity*: Medium.

---

## 6. Recommended Phase 33: Enterprise Asset Maintenance & Field Service Engine

### 6.1 Architecture & Workflow Model
1. **Preventive Maintenance Scheduling**:
   - Configurable recurrence triggers (`CALENDAR_INTERVAL`, `RUNTIME_HOURS`).
   - Automated due-date calculation and work order generation.
2. **Maintenance Work Order (MWO) Execution & Lifecycle**:
   - `DRAFT` $\to$ `SCHEDULED` $\to$ `IN_PROGRESS` $\to$ `COMPLETED` (or `CANCELLED`).
   - Tracks assigned technician, actual labor hours, equipment downtime hours, and maintenance task checklists.
3. **Double-Entry Stock Ledger & Financial GL Integration**:
   - Consuming spare parts automatically posts a double-entry inventory issue:
     $$\text{Stock Ledger: Decrement Warehouse Bin Quantity}$$
     $$\text{Dr } 6150\text{ (Equipment Maintenance & Repairs Expense)} \quad / \quad \text{Cr } 1200\text{ (Inventory Asset)}$$

---

## 7. Phase 33 Implementation Sequence

1. **Stage 33A — Data Models & Schemas**:
   - Create `apps/backend/app/models/maintenance.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/maintenance.py`.
2. **Stage 33B — Domain Service (`MaintenanceService`)**:
   - Implement schedule creation and due-date calculation.
   - Implement MWO lifecycle state machine transitions.
   - Implement spare part consumption and GL journal voucher posting (Dr `6150` / Cr `1200`).
3. **Stage 33C — REST API Endpoints**:
   - Mount `/api/v1/maintenance/schedules` and `/api/v1/maintenance/work-orders`.
4. **Stage 33D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_enterprise_maintenance_and_work_orders.py`.
   - Execute full platform regression across all backend test modules (>377 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.
