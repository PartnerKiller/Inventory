# Phase 10 Architecture & Design: Vendor Accounts Payable & 3-Way Match

## Executive Summary

Phase 10 extends the procurement lifecycle (Phase 5) and commercial financial capabilities (Phase 9) by establishing an authoritative **Vendor Accounts Payable (AP) and 3-Way Match Engine**.

The core mission of Phase 10 is to verify vendor billing integrity, prevent over-billing, control price variances, track AP liabilities, and manage supplier payment disbursements, while preserving strict architectural boundaries:
- **Inventory Truth**: Exclusively governed by `StockEngine` (double-entry ledger, zero negative stock).
- **Inventory Cost**: Exclusively governed by `CostingService` (FIFO/MWA cost layers, immutable COGS).
- **Procurement Truth**: Governed by `PurchaseService` / `ProcurementService` (PO lifecycle, GRN receipts, RTV returns).
- **AP Truth**: Governed by `APService` / `APMatchingService` (`VendorInvoice`, `VendorPayment`, `VendorCreditMemo`, 3-Way Matching).

---

## 1. Authoritative 3-Way Matching Flow

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ Purchase Order  │       │  Goods Receipt  │       │ Vendor Invoice  │
│      (PO)       │       │    Note (GRN)   │       │      (VI)       │
│ • Ordered Qty   │       │ • Received Qty  │       │ • Billed Qty    │
│ • Agreed Price  │       │ • Bin Location  │       │ • Billed Price  │
└────────┬────────┘       └────────┬────────┘       └────────┬────────┘
         │                         │                         │
         └────────────────► ┌──────┴──────┐ ◄────────────────┘
                            │  3-WAY      │
                            │  MATCHING   │
                            │  ENGINE     │
                            └──────┬──────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   [Within Tolerances]                       [Variance Exceeded]
              │                                         │
              ▼                                         ▼
     Status: MATCHED                           Status: EXCEPTION_HOLD
              │                                         │
              ▼                                         ▼
      Status: APPROVED                         Manager Approval / Override
              │                                         │
              └────────────────────┬────────────────────┘
                                   │
                                   ▼
                            [AP Liability]
                                   │
                                   ▼
                            Vendor Payment
                        & Multi-Bill Allocation
```

---

## 2. Capability Matrix

| Capability | Component / Service | Database Entity | Status | Description |
| :--- | :--- | :--- | :---: | :--- |
| **Vendor Invoice Intake** | `APService.create_vendor_invoice` | `VendorInvoice`, `VendorInvoiceLine` | **DESIGN** | Records vendor invoice with unique reference and line item details. |
| **3-Way Matching Engine** | `APMatchingService.match_invoice` | `VendorInvoice`, `APMatchingTolerance` | **DESIGN** | Compares PO, GRN, and VI lines for quantity and price variances. |
| **Tolerance Rules Engine** | `APMatchingService.evaluate_tolerance`| `APMatchingTolerance` | **DESIGN** | Evaluates % and absolute tolerance thresholds (e.g. 2% price variance). |
| **Exception Hold & Override** | `APService.approve_exception_hold` | `VendorInvoice` | **DESIGN** | Segregated managerial approval workflow for out-of-tolerance invoices. |
| **Duplicate Invoice Prevention**| `APService` (Unique constraint) | `VendorInvoice.uq_supplier_invoice` | **DESIGN** | Enforces uniqueness on `(tenant_id, supplier_id, vendor_invoice_reference)`. |
| **Vendor Payment Disbursements**| `APService.record_vendor_payment` | `VendorPayment`, `VendorPaymentAllocation`| **DESIGN** | Multi-bill payment allocations with atomic row locking (`with_for_update`). |
| **Debit/Credit Memo Linkage** | `APService.apply_debit_memo` | `SupplierDebitMemo`, `VendorInvoice` | **DESIGN** | Applies Phase 5 RTV debit memos against open vendor invoices. |
| **AP Aging Analytics** | `APAnalyticsService.get_ap_aging_report`| Computed Report | **DESIGN** | Duration buckets (`Current`, `1-30`, `31-60`, `61-90`, `90+` days). |
| **Purchase Price Variance (PPV)**| `CostingService` Integration | `CostTransaction` (PPV) | **DESIGN** | Captures price variance between PO and Vendor Invoice. |
| **Billing/Inventory Isolation** | Architectural Invariant | N/A | **DESIGN** | Proves AP actions never alter stock balances or cost layer quantities. |

---

## 3. Database Schema & Data Model Design

### 3.1 `VendorInvoice` (`vendor_invoices`)
```python
class VendorInvoice(Base, BaseModelMixin):
    __tablename__ = "vendor_invoices"

    tenant_id = Column(String(36), nullable=False, index=True)
    invoice_number = Column(String(50), unique=True, index=True, nullable=False) # Auto-generated internal INV-V-XXXX
    vendor_invoice_reference = Column(String(100), nullable=False, index=True) # Supplier's bill number
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    goods_receipt_id = Column(String(36), ForeignKey("goods_receipts.id"), nullable=True, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, MATCHED, EXCEPTION_HOLD, APPROVED, PARTIALLY_PAID, PAID, CANCELLED
    match_status = Column(String(30), default="UNMATCHED", nullable=False) # UNMATCHED, EXACT_MATCH, WITHIN_TOLERANCE, PRICE_VARIANCE_EXCEPTION, QUANTITY_VARIANCE_EXCEPTION
    subtotal_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    discount_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    tax_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    amount_paid = Column(Numeric(18, 4), default=0.0, nullable=False)
    balance_due = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    invoice_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text, nullable=True)
    match_notes = Column(Text, nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "vendor_invoice_reference", name="uq_vendor_invoice_ref"),
        Index("idx_vendor_inv_tenant_status", "tenant_id", "status"),
        Index("idx_vendor_inv_due_date", "tenant_id", "due_date"),
    )
```

### 3.2 `VendorInvoiceLine` (`vendor_invoice_lines`)
```python
class VendorInvoiceLine(Base, BaseModelMixin):
    __tablename__ = "vendor_invoice_lines"

    vendor_invoice_id = Column(String(36), ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(36), ForeignKey("purchase_order_lines.id"), nullable=False)
    grn_line_id = Column(String(36), ForeignKey("goods_receipt_lines.id"), nullable=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    billed_quantity = Column(Numeric(18, 4), nullable=False)
    received_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    po_unit_price = Column(Numeric(18, 4), nullable=False)
    billed_unit_price = Column(Numeric(18, 4), nullable=False)
    price_variance_unit = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_price_variance = Column(Numeric(18, 4), default=0.0, nullable=False) # PPV
    tax_pct = Column(Numeric(5, 2), default=0.0, nullable=False)
    line_total = Column(Numeric(18, 4), nullable=False)
```

### 3.3 `VendorPayment` & `VendorPaymentAllocation`
```python
class VendorPayment(Base, BaseModelMixin):
    __tablename__ = "vendor_payments"

    tenant_id = Column(String(36), nullable=False, index=True)
    payment_number = Column(String(50), unique=True, index=True, nullable=False) # PAY-V-XXXX
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    payment_method = Column(String(30), default="BANK_TRANSFER", nullable=False) # BANK_TRANSFER, CHECK, CREDIT_CARD, CASH
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    payment_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    reference_number = Column(String(100), nullable=True) # Check # / Wire Ref
    status = Column(String(30), default="COMPLETED", nullable=False) # COMPLETED, VOIDED
    notes = Column(Text, nullable=True)
    disbursed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

class VendorPaymentAllocation(Base, BaseModelMixin):
    __tablename__ = "vendor_payment_allocations"

    vendor_payment_id = Column(String(36), ForeignKey("vendor_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_invoice_id = Column(String(36), ForeignKey("vendor_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_allocated = Column(Numeric(18, 4), nullable=False)
    allocated_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
```

### 3.4 `APMatchingTolerance`
```python
class APMatchingTolerance(Base, BaseModelMixin):
    __tablename__ = "ap_matching_tolerances"

    tenant_id = Column(String(36), nullable=False, unique=True, index=True)
    price_tolerance_pct = Column(Numeric(5, 2), default=2.0, nullable=False) # Default 2.0%
    price_tolerance_max_amount = Column(Numeric(18, 4), default=50.0, nullable=False) # Max absolute variance
    quantity_tolerance_pct = Column(Numeric(5, 2), default=0.0, nullable=False) # Default 0.0% (strict over-bill protection)
    auto_approve_within_tolerance = Column(Boolean, default=True, nullable=False)
```

---

## 4. 3-Way Matching Rules & Tolerance Engine

### 4.1 Matching Invariants & Formulae

1. **Quantity Verification**:
   $$\text{Quantity Variance} = \text{Billed Quantity} - \text{Received Quantity}$$
   $$\text{If } \text{Billed Quantity} > \text{Received Quantity} \times (1 + \text{Qty Tol \%}) \implies \mathbf{QUANTITY\_VARIANCE\_EXCEPTION}$$
2. **Price Variance (PPV) Verification**:
   $$\text{Price Variance Unit} = \text{Billed Unit Price} - \text{PO Unit Price}$$
   $$\text{Total Price Variance (PPV)} = \text{Billed Quantity} \times \text{Price Variance Unit}$$
   $$\text{Price Variance \%} = \left( \frac{|\text{Billed Unit Price} - \text{PO Unit Price}|}{\text{PO Unit Price}} \right) \times 100\%$$
   $$\text{If } \text{Price Variance \%} > \text{Price Tol \%} \text{ and } |\text{PPV}| > \text{Max Var Amount} \implies \mathbf{PRICE\_VARIANCE\_EXCEPTION}$$
3. **Match Status Resolution**:
   - If $\text{PPV} == 0$ and $\text{Qty Variance} == 0 \implies \mathbf{EXACT\_MATCH}$ (Auto-Approved).
   - If within configured tolerances $\implies \mathbf{WITHIN\_TOLERANCE}$ (Auto-Approved if enabled).
   - If variance exceeds tolerance $\implies \mathbf{EXCEPTION\_HOLD}$ (Requires manager override).

---

## 5. Implementation Phases (Phase 10 Plan)

- **Phase 10.1: Models, Database Tables & Schemas**:
  - Implement `VendorInvoice`, `VendorInvoiceLine`, `VendorPayment`, `VendorPaymentAllocation`, `APMatchingTolerance`.
  - Register in `models/__init__.py`.
  - Create Pydantic v2 schemas in `apps/backend/app/schemas/ap.py`.
- **Phase 10.2: AP & 3-Way Matching Domain Services**:
  - Implement `APMatchingService` with exact tolerance evaluations and PPV computations.
  - Implement `APService` for invoice intake, exception approvals, multi-bill payments, and debit memo adjustments.
  - Implement `APAnalyticsService` for duration-bucketed AP aging (`Current`, `1-30`, `31-60`, `61-90`, `90+` days).
- **Phase 10.3: REST API Endpoints & RBAC Integration**:
  - Register `/api/v1/ap/invoices`, `/api/v1/ap/payments`, `/api/v1/ap/tolerances`, `/api/v1/ap/aging`.
  - Enforce permissions: `purchasing:invoice_match`, `purchasing:invoice_approve`, `purchasing:payment_disburse`.
- **Phase 10.4: Automated Test Suite & Regression**:
  - Build [`test_vendor_ap_3way_matching.py`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/tests/test_vendor_ap_3way_matching.py) covering all 10 core verification scenarios.
  - Full backend pytest, frontend vitest, and build packaging validation.

---

## 6. Automated Verification Plan

| Test ID | Test Scenario | Expected Outcome |
| :-: | :--- | :--- |
| **1** | **Exact 3-Way Match** | Billed Qty == Received Qty & Billed Price == PO Price $\implies$ `EXACT_MATCH`, `APPROVED`. |
| **2** | **Quantity Variance Exceeded** | Billed Qty (12) > Received Qty (10) $\implies$ `QUANTITY_VARIANCE_EXCEPTION`, `EXCEPTION_HOLD`. |
| **3** | **Price Variance within Tolerance**| PO $100, Billed $101.50 (1.5% $\le$ 2.0% tolerance) $\implies$ `WITHIN_TOLERANCE`, `APPROVED`. |
| **4** | **Price Variance Exceeded** | PO $100, Billed $110.00 (10% > 2.0% tolerance) $\implies$ `PRICE_VARIANCE_EXCEPTION`, `EXCEPTION_HOLD`. |
| **5** | **Manager Override / Approval** | Manager with `purchasing:invoice_approve` approves exception hold $\implies$ transitions to `APPROVED`. Self-approval prevented. |
| **6** | **Duplicate Vendor Invoice Guard**| Same `supplier_id` + `vendor_invoice_reference` $\implies$ 409 Conflict. |
| **7** | **Multi-Invoice Vendor Payment** | Payment $10,000 applied to Bill A ($6,000) and Bill B ($4,000) $\implies$ both bills transition to `PAID` with balance = 0. |
| **8** | **Partial Vendor Payment** | Bill $10,000 with Payment $4,000 $\implies$ `PARTIALLY_PAID` (balance $6,000). |
| **9** | **Debit Memo Application (RTV)** | Apply Phase 5 RTV `SupplierDebitMemo` ($2,000) against Bill ($10,000) $\implies$ reduces balance due to $8,000. |
| **10** | **Billing/Inventory Strict Isolation**| AP invoice creation, match, and payment produce **zero** ledger transactions and leave physical stock balances and cost layers completely untouched. |
