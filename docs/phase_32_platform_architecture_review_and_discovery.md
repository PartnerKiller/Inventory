# Phase 32 Design Discovery: Post-Phase-31 Platform Architecture Review

## 1. Executive Summary

Following the completion and formal closure of **Phases 1 through 31**, AuraStock is a fully integrated double-entry Enterprise Resource Planning (ERP) platform. It provides double-entry stock valuation, FIFO/moving-average costing layers, multi-echelon SCM nodes, multi-level BOMs and routing locks, statutory accounting periods and fiscal year closing ceremonies, multi-currency historical rate locking, enterprise GST/VAT tax settlements, fixed asset capitalization and automated depreciation, cost center budgeting and commitment overrun guards, Holt-Winters demand forecasting, multi-level approval workflows with Delegation of Authority (DoA), B2B dynamic pricing with customer volume rebates, Prometheus observability with distributed tracing, **Multi-Entity Intercompany Trade with Automated Mirrored Transactions**, and **Unrealized Intercompany Inventory-Profit Elimination & Consolidated Financial Reporting (Consolidated Trial Balance, P&L, Balance Sheet)**.

### Complete Platform Scope (Phases 1–31):
- **Core Inventory & Costing**: Double-entry stock ledger, FIFO/moving-average cost layers, lot/batch/serial traceability, 1-click product recall tree, and rapid barcode warehouse operations.
- **Manufacturing & Shop Floor**: Multi-level BOMs, work centers, routings, Finish-to-Start predecessor locks, and in-process quality quarantine gates.
- **Supply Chain & Edge Sync**: SCM node hierarchy, transfer orders with in-transit asset accounting (`1250`), landed freight cost capitalization, server-authoritative HMAC-verified edge sync with conflict backorders.
- **Commercial & Portals**: B2B customer & supplier self-service portals, sales orders, 3-way AP matching, payment gateway integration, customer invoicing, dynamic pricing break curves, and volume rebate settlements (Dr `4100` / Cr `1200`).
- **Statutory Accounting & GL**: Standard Chart of Accounts, balancing document JVs, trial balance, P&L, balance sheet, accounting period closing state machine with hard backdated posting guards, automated year-end retained earnings closing (`3100`), multi-currency exchange rates with realized/unrealized FX (`6300`), enterprise GST/VAT with Input Tax Credit (`1400`) vs Output Tax (`2200`), fixed asset capitalization (`1500`) and automated SLM/WDV depreciation schedules (`1550` / `6400`).
- **Management Accounting & Budgeting**: Cost Center & Profit Center hierarchy, departmental budget allocations per period & GL account, commitment accounting on Purchase Orders, soft warning thresholds, hard budget overrun blocks (HTTP 400), commitment actualization, and hierarchical variance rollups.
- **Planning & Intelligence**: Holt-Winters triple exponential smoothing, dynamic $Z$-score safety stock modeling ($SS = Z \times \sqrt{\bar{L} \times \sigma_D^2 + \bar{D}^2 \times \sigma_L^2}$), dynamic $ROP$, replenishment proposal generation, and 1-click conversion to authoritative Vendor Purchase Orders.
- **Governance & Control**: Tiered spend authorization matrix (DoA), sequential multi-step approval engine, document release locks (PO, GRN, AP, GL, Manual JV, Budget Overrun, Asset Disposal), SLA timeout escalations, and out-of-office delegate substitutions.
- **Observability & Diagnostics**: Prometheus telemetry scrape endpoint (`/metrics`), `TelemetryMiddleware` assigning and propagating `X-Trace-ID`, `X-Span-ID`, `X-Response-Time`, and deep diagnostic health probes (`/health/live`, `/health/ready`, `/health/subsystems`).
- **Multi-Entity Intercompany Trade & Consolidation (P30–31)**: Intercompany trading agreements, transfer pricing rules (`COST_PLUS`, `FIXED_PRICE`, `CATALOG`), automated mirrored Purchase Order generation from Intercompany Sales Orders, intercompany AR (`1300`) and AP (`2300`) clearing accounting, group consolidation elimination Journal Vouchers (Dr `4000` Revenue / Cr `5000` COGS and Dr `2300` Due to Affiliates / Cr `1300` Due from Affiliates), **Unrealized Inventory-Profit Elimination (Dr `5000` COGS / Cr `1210` Inventory Markup Reserve)**, and **Consolidated Financial Statement Reporting (Consolidated Trial Balance, Consolidated P&L, Consolidated Balance Sheet)**.

---

## 2. Post-Phase-31 Architecture Map

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
│ 7. Telemetry & Multi-Entity Group Consolidation (Phases 29–31)                                          │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Prometheus Scrape Endpoint (`/metrics`) & Distributed Tracing (`X-Trace-ID`, `X-Response-Time`)      │
│ • Group Consolidation Elimination Engine (Dr 4000 / Cr 5000 and Dr 2300 / Cr 1300)                     │
│ • Unrealized Intercompany Profit Elimination (Dr 5000 / Cr 1210 Inventory Reserve) (Phase 31)           │
│ • Consolidated Financial Reporting Engine (Consolidated Trial Balance, P&L, Balance Sheet) (Phase 31)  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Reconciliation of Prior Completed Phases (Phases 17–31)

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

---

## 4. Platform Gap & Risk Assessment

| Priority | Subsystem Domain | Description of Gap | Business & Architectural Impact |
| :---: | :--- | :--- | :--- |
| **P1** | **Enterprise Document Management, Versioned File Attachments & Audit Compliance Sign-Off Workflows** | Across all 31 ERP modules (Purchase Orders, Goods Receipts, Vendor Invoices, Customer Sales Orders, Quality Inspection Certificates, Fixed Asset Acquisition Deeds, Journal Vouchers, and Consolidation Runs), enterprise businesses require authoritative, tamper-proof, version-controlled document attachment storage (e.g. signed vendor contracts, physical bill of lading scans, customs clearance documents, supplier certificates of analysis, asset title deeds, auditor review workpapers) with cryptographic SHA-256 integrity hashing, MIME-type validation, RBAC-gated access control, and formal audit compliance sign-off workflows (SOX / ISO 9001 / IFRS audit sign-offs). | Without an integrated document management engine, transactions lack auditable physical source proof, exposing the organization to statutory audit deficiencies and compliance penalties. |
| **P2** | **Field Service & Preventive Maintenance Management Engine** | Work center routings and shop-floor tracking are implemented; after-sales field maintenance tickets remain a potential future extension. | Specialized service industry capability. |
| **P3** | **Customer Loyalty Points & Tiered Rewards Program Engine** | Dynamic pricing and volume discounts are implemented; B2C points-based loyalty remains optional. | Nice-to-have commercial feature. |

---

## 5. Ranked Phase 32 Candidates

### Candidate Comparison Matrix:

1. **Rank 1 (Recommended Phase 32 - P1)**: **Enterprise Document Management, Versioned File Attachments & Audit Compliance Sign-Off Workflows**
   - *Objective*: Implement an end-to-end Enterprise Document Management System (EDMS):
     - `DocumentAttachment`: `tenant_id`, `entity_type` (`PURCHASE_ORDER`, `SALES_ORDER`, `VENDOR_INVOICE`, `GOODS_RECEIPT`, `FIXED_ASSET`, `JOURNAL_VOUCHER`, `QUALITY_INSPECTION`), `entity_id`, `file_name`, `file_size`, `mime_type`, `sha256_hash`, `storage_path`, `version`, `uploaded_by_user_id`.
     - `DocumentSignOff`: `tenant_id`, `attachment_id`, `sign_off_role` (`INTERNAL_AUDITOR`, `CFO`, `QUALITY_MANAGER`, `COMPLIANCE_OFFICER`), `signer_user_id`, `status` (`PENDING`, `SIGNED`, `REJECTED`), `digital_signature_hash`, `signed_at`.
     - Cryptographic SHA-256 tamper-proof file verification & secure download endpoints.
   - *Business Value*: Guarantees SOX / ISO 9001 / IFRS audit compliance, binds immutable digital evidence to transactions across all 31 modules, and provides formal electronic sign-off workflows.
   - *Dependencies*: Base database, RBAC permissions, Audit Trail (`audit.py`).
   - *Implementation Complexity*: Medium.
   - *Verification Complexity*: Deterministic (SHA-256 checksum verification, multi-version file upload, role sign-off transitions, tamper detection).

2. **Rank 2 (Candidate Phase 33 - P2)**: **Field Service & Preventive Maintenance Management Engine**
   - *Objective*: Preventive asset maintenance schedules and field service tickets.
   - *Business Value*: Field operations support.
   - *Dependencies*: Work Centers, Items Master.
   - *Implementation Complexity*: Medium.

3. **Rank 3 (Candidate Phase 34 - P2)**: **Customer Loyalty Points & Tiered Rewards Program Engine**
   - *Objective*: Points accrual and redemption rules for repeat buyers.
   - *Business Value*: B2C customer retention.
   - *Dependencies*: Sales Orders, Customer Portal.
   - *Implementation Complexity*: Low-Medium.

---

## 6. Recommended Phase 32: Enterprise Document Management & Audit Compliance Sign-Off

### 6.1 Architecture & Workflow Model
1. **Generic Polymorphic Attachment Registry (`DocumentAttachment`)**:
   - Attaches files to any core ERP business aggregate (`PURCHASE_ORDER`, `GOODS_RECEIPT`, `VENDOR_INVOICE`, `SALES_ORDER`, `FIXED_ASSET`, `JOURNAL_VOUCHER`, `CONSOLIDATION_RUN`).
   - Computes and stores cryptographic SHA-256 checksum upon upload to detect byte tampering.
   - Supports automated file versioning (Version 1, Version 2, etc.) for updated contract revisions.
2. **Audit Compliance Sign-Off Workflow (`DocumentSignOff`)**:
   - Requires designated compliance officers / auditors to review and cryptographically sign off on attached evidence.
   - State machine: `PENDING` $\to$ `SIGNED` or `REJECTED`.
   - Recording digital signature hash: $\text{HMAC-SHA256}(\text{attachment\_hash} + \text{signer\_id} + \text{timestamp})$.

---

## 7. Phase 32 Implementation Sequence

1. **Stage 32A — Data Models & Schemas**:
   - Create `apps/backend/app/models/edms.py`.
   - Register models in `apps/backend/app/models/__init__.py`.
   - Create schemas in `apps/backend/app/schemas/edms.py`.
2. **Stage 32B — Domain Service (`DocumentManagementService`)**:
   - Implement upload with SHA-256 hashing and version incrementation.
   - Implement compliance sign-off workflow with signature generation.
   - Implement tamper verification probe.
3. **Stage 32C — REST API Endpoints**:
   - Mount `/api/v1/documents/attachments` and `/api/v1/documents/sign-offs`.
4. **Stage 32D — Automated Tests & Full Platform Regression**:
   - Create `apps/backend/tests/test_document_management_and_signoff.py`.
   - Execute full platform regression across all backend test modules (>374 tests), frontend Vitest (37 tests), TypeScript, web build, and packaging.
