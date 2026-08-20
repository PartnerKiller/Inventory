# Phase 35 Design Discovery: Post-Phase-34 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 34**, AuraStock is a comprehensive, enterprise-grade Enterprise Resource Planning (ERP) platform. It provides double-entry stock valuation, FIFO/moving-average costing layers, multi-echelon SCM nodes, multi-level BOMs and routing locks, statutory accounting periods and fiscal year closing ceremonies, multi-currency historical rate locking, enterprise GST/VAT tax settlements, fixed asset capitalization and automated depreciation, cost center budgeting and commitment overrun guards, Holt-Winters demand forecasting, multi-level approval workflows with Delegation of Authority (DoA), B2B dynamic pricing with customer volume rebates, Prometheus observability with distributed tracing, Multi-Entity Intercompany Trade with Automated Mirrored Transactions, Unrealized Intercompany Inventory-Profit Elimination & Consolidated Financial Reporting, Enterprise Document Management (EDMS) with Cryptographic SHA-256 Versioned File Attachments & Multi-Role Compliance Audit Sign-Off Workflows, Enterprise Preventive Maintenance & Asset Work Orders, and **Fixed Asset Capital Improvements, Asset Enhancement Work Orders & Revised Depreciation Schedules**.

### Complete Platform Scope (Phases 1–34):
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
- **Preventive Maintenance & Work Orders (P33)**: Calendar and runtime-hour recurrence schedules, maintenance work orders (MWO) with technician tracking, double-entry spare parts consumption, and ordinary repairs expense posting (Dr `6150` / Cr `1200`).
- **Capital Improvements & Depreciation Recalculation (P34)**: Major asset enhancement classification on MWO, GL capitalization (Dr `1500` / Cr `1200`), cost basis and useful life incrementation, and automated straight-line depreciation schedule recalculation under IAS 16 / ASC 360.

---

## 2. Post-Phase-34 Architecture Map

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
│ 7. Telemetry, Group Consolidation, Compliance & Asset Lifecycle (Phases 29–34)                          │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Prometheus Scrape Endpoint (`/metrics`) & Distributed Tracing (`X-Trace-ID`, `X-Response-Time`)      │
│ • Group Consolidation Elimination Engine (Dr 4000 / Cr 5000 and Dr 2300 / Cr 1300)                     │
│ • Unrealized Intercompany Profit Elimination (Dr 5000 / Cr 1210 Inventory Reserve) (Phase 31)           │
│ • Consolidated Financial Reporting Engine (Consolidated Trial Balance, P&L, Balance Sheet) (Phase 31)  │
│ • EDMS Polymorphic Attachments, SHA-256 Tamper Probes & Compliance Sign-Off Workflows (Phase 32)       │
│ • Preventive Maintenance Scheduling & Work Orders with Spare Parts Stock & GL Accounting (Phase 33)    │
│ • Asset Capital Improvements, MWO Capitalization (Dr 1500) & Depreciation Recalculation (Phase 34)     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Reconciliation of Prior Completed Phases (Phases 17–34)

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
| **Phase 33** | Preventive Maintenance & Work Orders | **CLOSED** | [`apps/backend/app/models/maintenance.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/maintenance.py) & `maintenance_service.py` (`test_enterprise_maintenance_and_work_orders.py`) |
| **Phase 34** | Capital Improvements & Depreciation Recalculation | **CLOSED** | [`apps/backend/app/models/fixed_asset.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/fixed_asset.py) & `fixed_asset_service.py` (`test_fixed_asset_capital_improvements.py`) |

---

## 4. Consolidated Deferred Capability Register

| Deferred Capability | Origin Phase | Status | Business & Statutory Impact | Priority | Dependencies |
| :--- | :---: | :---: | :--- | :---: | :--- |
| **Maintenance Capital Improvements** | Phase 33 | **RESOLVED (P34)** | Capitalization of major asset enhancements & depreciation recalculation. | P1 | Fixed Assets, Maintenance. |
| **Unrealized Intercompany Profit Elimination** | Phase 30 | **RESOLVED (P31)** | Elimination of internal markups in affiliate inventory & Consolidated P&L. | P1 | Intercompany, GL. |
| **Supplier Performance Scorecards & Delivery KPIs** | Phase 27/30 | **ACTIVE GAP** | Automated vendor evaluation on On-Time Delivery (OTD), Quality Rejection Rates, and Price Variance (PPV). | **P1** | Purchasing, Quality, AP 3-Way Match. |
| **Fixed Asset Impairment Loss & Revaluation Reserve** | Phase 24 | **ACTIVE GAP** | IAS 36 Impairment testing and revaluation surplus accounting. | **P2** | Fixed Assets, GL. |
| **Customer Loyalty Points & Tiered Rewards Program** | Phase 28 | **ACTIVE GAP** | Points accrual rules and redemption on B2C sales orders. | **P3** | Sales Orders, Customer Portal. |

---

## 5. Ranked Phase 35 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 35 - P1)**: **Supplier Performance Scorecards, Delivery KPI & Vendor Quality Rating Engine**
   - *Objective*: Implement an end-to-end Supplier Performance & Vendor Rating Engine:
     - `SupplierScorecard`: `tenant_id`, `supplier_id`, `period_code`, `total_pos_count`, `on_time_deliveries_count`, `otd_percentage`, `total_received_units`, `rejected_units_count`, `quality_acceptance_percentage`, `price_variance_amount`, `overall_vendor_score` (0–100), `tier_grade` (`TIER_A_PREFERRED`, `TIER_B_APPROVED`, `TIER_C_PROBATIONARY`, `TIER_D_RESTRICTED`), `evaluated_at`.
     - Automated metrics calculation:
       $$\text{OTD \%} = \frac{\text{On-Time GRNs}}{\text{Total GRNs}} \times 100$$
       $$\text{Quality \%} = \frac{\text{Accepted Units}}{\text{Total Received Units}} \times 100$$
       $$\text{Vendor Score} = (0.50 \times \text{OTD \%}) + (0.40 \times \text{Quality \%}) + (0.10 \times \text{Price Compliance \%})$$
     - REST API endpoints for scheduled/on-demand scorecard generation and ranking.
   - *Business Value*: Eliminates supplier delivery bottlenecks, penalizes chronic quality defect vendors, and feeds directly into Replenishment Proposal vendor selection (Phase 26).
   - *Dependencies*: Purchasing (`PurchaseOrder`), Goods Receipt (`GoodsReceipt`), Quality Quarantine (`QuarantineRecord`), Vendor Invoices (`VendorInvoice`).
   - *Implementation Complexity*: Medium.
   - *Verification Complexity*: Deterministic (OTD math, quality acceptance percentage, composite score weighting, tier grade thresholds).

2. **Rank 2 (Candidate Phase 36 - P2)**: **Fixed Asset Impairment Loss & Revaluation Reserve Engine (IAS 36)**
   - *Objective*: Asset fair value testing, impairment write-downs (Dr `6460` / Cr `1550`), and revaluation surplus (Dr `1500` / Cr `3200`).
   - *Business Value*: Statutory compliance with IAS 36.
   - *Dependencies*: Fixed Assets, GL.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 37 - P2)**: **Customer Loyalty Points & Tiered Rewards Program Engine**
   - *Objective*: Points accrual and redemption rules for repeat buyers.
   - *Business Value*: B2C customer retention.
   - *Dependencies*: Sales Orders, Customer Portal.
   - *Implementation Complexity*: Low-Medium.

---

## 6. Recommended Phase 35: Supplier Performance Scorecards & Vendor Quality Rating

### 6.1 Architecture & Workflow Model
1. **Automated KPI Data Aggregation**:
   - Queries `PurchaseOrder` (promised dates vs actual GRN receiving dates).
   - Queries `GoodsReceipt` & QA inspection passes vs quarantine rejects.
   - Queries `VendorInvoice` for purchase price variance (PPV).
2. **Weighted Scoring Model**:
   - Computes weighted score: $S = 0.50 \cdot \text{OTD} + 0.40 \cdot \text{QA} + 0.10 \cdot \text{PPV\_Compliance}$.
   - Classifies vendor tier:
     - $\ge 90 \to \text{TIER\_A\_PREFERRED}$
     - $75 - 89 \to \text{TIER\_B\_APPROVED}$
     - $60 - 74 \to \text{TIER\_C\_PROBATIONARY}$
     - $< 60 \to \text{TIER\_D\_RESTRICTED}$
3. **Scorecard History & Portal Visibility**:
   - Persists historical quarterly/monthly scorecards for trend analytics and supplier self-service portal visibility.

---

## 7. Phase 35 Implementation Sequence

1. **Stage 35A — Data Models & Schemas**:
   - Create `apps/backend/app/models/vendor_scorecard.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/vendor_scorecard.py`.
2. **Stage 35B — Domain Service (`VendorScorecardService`)**:
   - Implement `generate_supplier_scorecard(tenant_id, supplier_id, period_code)`.
   - Implement `get_supplier_scorecard_history(tenant_id, supplier_id)`.
3. **Stage 35C — REST API Endpoints**:
   - Mount `/api/v1/procurement/scorecards`.
4. **Stage 35D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_supplier_performance_scorecards.py`.
   - Execute full platform regression across all backend test modules (>384 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.
