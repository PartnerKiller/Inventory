# Phase 17 Design Review: Platform Consolidation & Remaining ERP Gaps

## Executive Summary

Over **Phases 1 through 16**, AuraStock has evolved from a double-entry inventory ledger into an end-to-end, multi-tenant enterprise ERP platform encompassing Master Data, Multi-Warehouse Operations, Traceability, Sales & Purchasing Lifecycles, Costing & Valuation, Light Manufacturing, Automated Demand Planning, Logistics & Shipping, B2B Portals, and Payment Gateways.

This Phase 17 review performs a **comprehensive platform audit** to evaluate what has been accomplished, identify outstanding gaps and technical debt, and establish the strategic architectural roadmap for **Phases 17–21**.

---

## 1. Current Platform Capability Map (Phases 1–16)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  AuraStock ERP Platform                                │
├──────────────────────────┬──────────────────────────┬──────────────────────────────────┤
│ Core Inventory & Ledger  │ Supply Chain & Ops       │ Financials & Commerce            │
├──────────────────────────┼──────────────────────────┼──────────────────────────────────┤
│ • Double-Entry Ledger    │ • Sales Orders & Picking │ • Invoicing & AR Allocations     │
│ • Multi-Warehouse & Bins │ • Purchasing & GRN       │ • Vendor AP & 3-Way Match        │
│ • Lot & Serial Tracking  │ • Light Manufacturing    │ • Multi-Gateway (Stripe/Razorpay)│
│ • FEFO Pick Logic        │ • Demand Planning & ROP  │ • Inventory Costing (FIFO/MWA)   │
│ • Cycle Counts & Adjust  │ • Carrier & Shipping     │ • B2B Customer & Supplier Portals│
│ • Desktop Sync / Tauri   │ • Reverse Logistics (RMA)│ • Audit Trail & Event Outbox     │
└──────────────────────────┴──────────────────────────┴──────────────────────────────────┘
```

---

## 2. Codebase Debt & Deferred Marker Inventory

| Marker / Item | Location | Current State | Priority | Resolution Path |
| :--- | :--- | :--- | :---: | :--- |
| **MFA / TOTP** | `models/portal.py`, `models/users.py`, `test_b2b_customer_and_supplier_portals.py` | Schema columns `mfa_secret` and `is_mfa_enabled` scaffolded; RFC 6238 endpoint verification deferred | **P1** | Implement TOTP setup, QR code generation, and verification middleware |
| **Live Gateway Validation** | `test_payment_gateway_lifecycle.py` | Mock fully tested; Stripe & Razorpay contract tested; Live credential verification deferred | **P2** | Add optional sandbox CLI integration verification test runner |
| **Dynamic Valuation Depletion** | `services/report_service.py:612`, `ReportsPage.tsx:635` | Valuation estimate computed from on-hand balances; dynamic multi-layer depletion reporting | **P1** | Add real-time FIFO layer depletion analytics report |
| **Starlette 422 Deprecation** | `test_advanced_sales_v2.py`, `test_warehouse_inventory.py`, etc. | Starlette deprecation warning for `HTTP_422_UNPROCESSABLE_ENTITY` | **P2** | Modernize status code references to `HTTP_422_UNPROCESSABLE_CONTENT` |

---

## 3. Comprehensive Remaining-Gap Matrix

### 3.1 Financial & General Ledger (GL) Gaps
- **General Ledger (GL) Chart of Accounts (COA) [P0]**: While AR, AP, Invoicing, and Costing exist, AuraStock currently lacks a unified Chart of Accounts (Assets, Liabilities, Equity, Revenue, COGS, Expenses) with automated Journal Voucher (JV) posting rules for inventory transactions, sales, payments, and vendor bills.
- **Multi-Currency Forex Realized/Unrealized Gain/Loss [P1]**: Invoices and payments track currencies, but exchange rate fluctuations between invoice date and payment date do not currently generate automated FX variance journal entries.
- **Tax Engine & Summary Reporting (GST / VAT) [P1]**: Tax percentages are stored on lines, but a unified tax authority reconciliation ledger is missing.

### 3.2 Security, Identity & Authentication Gaps
- **Enterprise MFA / TOTP (RFC 6238) [P0]**: Portal users and internal staff require time-based one-time password verification for high-privilege operations and login challenges.
- **SAML 2.0 / OIDC Single Sign-On (SSO) [P1]**: Enterprise tenants require federated authentication with Okta, Azure AD, or Google Workspace.
- **Session Revocation & Distributed Token Blacklisting [P1]**: Immediate revocation across distributed instances via Redis token blacklist upon user deactivation.

### 3.3 Operations, Notifications & Observability Gaps
- **Multi-Channel Notification Engine [P0]**: Automated email (SMTP/SES), webhook, and in-app alerts for critical business events:
  - Low stock below ROP
  - PO approved / GRN received
  - Sales order allocated / shipped
  - Overdue customer invoices / AP bills
  - Quarantine recall containment triggered
- **Background Task Scheduling & Cron Engine (Celery/ARQ/Redis) [P1]**: Scheduled nightly demand planning runs, recurring subscription invoices, and automated backup rotations.
- **OpenTelemetry Distributed Tracing & Health Dashboard [P2]**: Metrics on ledger transaction throughput, gateway latency, and sync queue lag.

### 3.4 Manufacturing & Supply Chain Advanced Gaps
- **Work Center Capacities & Machine Routing [P1]**: BOM and Work Orders exist, but machine workstation scheduling, operation routing steps, and scrap tracking are not yet modeled.
- **Multi-Echelon Replenishment Cascading [P2]**: Central Hub to Regional DC replenishment transfer order generation.
- **Blanket Purchase Orders & Call-Off Schedules [P2]**: Long-term supplier contract tracking against periodic release orders.

### 3.5 Offline Synchronization Gaps
- **Selective Sync Partitions (Warehouse-Level Sync Scoping) [P1]**: Currently, full tenant catalog is synchronized; mobile warehouse scanners should sync only assigned warehouse inventory to reduce footprint.
- **Delta-Compression for Large Sync Payloads [P2]**: Binary delta or compressed JSON sync chunks for low-bandwidth warehouse environments.

---

## 4. Priority Categorization Summary

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ P0 — Critical Correctness / Financial / Security Blockers                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ 1. General Ledger (GL) & Double-Entry Chart of Accounts Engine                      │
│ 2. Enterprise MFA / TOTP Authentication & Security Hardening                        │
│ 3. Automated Event-Driven Multi-Channel Notification Engine (Email/Webhooks/Alerts) │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ P1 — Important Production Gaps                                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ 4. Multi-Currency Forex Gain/Loss & Tax Settlement Engine (GST/VAT)                 │
│ 5. Advanced Manufacturing: Work Centers, Machine Routing & Scrap Accounting         │
│ 6. Background Job Queue & Scheduled Automation (Celery / Async Workers)             │
│ 7. Warehouse Selective Offline Partitioning & Delta-Sync                           │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ P2 — Useful Enterprise Enhancements                                                 │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ 8. Multi-Echelon Replenishment Cascades (Hub-to-Spoke Transfer Orders)             │
│ 9. Enterprise SSO (SAML 2.0 / OIDC Federated Auth)                                  │
│ 10. Carrier Freight Matrix & Shipping Invoice Audit Reconciliation                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Recommended Strategic Roadmap (Phases 17–21)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 17: General Ledger (GL), Chart of Accounts & Financial Unification   │
│ • Chart of Accounts (Assets, Liabilities, Equity, Revenue, Expense, COGS)   │
│ • Automated Journal Voucher (JV) posting for Inventory, Sales, AP, AR, Cost │
│ • Trial Balance, Balance Sheet, Income Statement (P&L) Real-Time Analytics  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 18: Multi-Channel Notification Engine & Background Job Automation     │
│ • Event-driven notification bus (Low stock, ROP, Order Shipped, Invoice Due)│
│ • SMTP / Email templates, Webhook dispatch, In-app alerts                   │
│ • Scheduled cron jobs (Nightly Replenishment, Aging AR/AP recalculations)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 19: Security Hardening, MFA/TOTP & Enterprise Identity (SSO)          │
│ • RFC 6238 TOTP enrollment, QR code, and mandatory MFA policy enforcement   │
│ • SAML 2.0 / OIDC enterprise Single Sign-On                                 │
│ • Distributed token revocation & enhanced session security                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 20: Advanced Manufacturing: Work Centers, Routing & WIP Accounting   │
│ • Work Centers, Machine capacities, Labor hourly rates                      │
│ • Multi-step production routing, Operation step sign-offs, Scrap tracking   │
│ • Work-in-Progress (WIP) GL ledger tracking and production variance rollup  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 21: Enterprise Multi-Echelon Supply Chain & Selective Edge Sync       │
│ • Hub-and-spoke multi-warehouse transfer replenishment automation           │
│ • Selective warehouse sync partitions for mobile edge devices               │
│ • Vendor performance scorecarding & dynamic supplier ratings                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Dependency Graph & Architectural Rationale

1. **Why Phase 17 Must Be General Ledger (GL) & Financial Unification**:
   - Every single operational event currently executed in AuraStock—Stock Ledger movements, Cost Layer FIFO depletions, Sales Invoices, AR Payments, Gateway Settlements, Vendor Bills, 3-Way Match PPV variances, and Manufacturing Cost Rollups—has direct accounting impact.
   - Operating these subsystems without a unified General Ledger (GL) creates financial fragmentation. A real-time double-entry GL binds all 16 previous phases into a GAAP/IFRS compliant financial core.

2. **Why Phase 18 is Notifications & Background Automation**:
   - Operational workflows (Demand Planning recommendations, Shipping tracking updates, Overdue AR alerts) currently execute synchronously on API triggers. Background job queuing and proactive notification dispatch give enterprise users autonomic alerting.

3. **Why Phase 19 is Security & MFA Hardening**:
   - Closing the deferred MFA/TOTP requirement from Phase 15 and adding SAML SSO protects the expanded portal and financial attack surfaces.

4. **Why Phase 20 is Advanced Manufacturing Routing**:
   - Builds directly on Phase 12 (BOM & Work Orders) and Phase 17 (GL WIP accounts) to complete full discrete manufacturing capabilities.

5. **Why Phase 21 is Multi-Echelon Supply Chain & Edge Optimization**:
   - Scales the multi-warehouse architecture across large regional distribution networks with optimized offline edge data footprints.
