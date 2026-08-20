# Phase 16 Design: Payment Gateway Integration & Payment Lifecycle

## Executive Overview

Phase 16 designs the **Payment Gateway Integration & Payment Lifecycle** subsystem for AuraStock. It provides an enterprise-grade, multi-provider payment processing engine that seamlessly supports online customer portal checkout, manual back-office payments, automated authorizations, captures, partial payments, refunds, gateway webhooks, and bank reconciliations while strictly preserving double-entry accounting and accounts receivable (AR) ledger integrity.

### Core Architectural Invariants:
1. **Engine Separation & Flow Isolation**:
   $$\text{Customer Portal / ERP UI} \longrightarrow \text{PaymentService} \longrightarrow \text{PaymentGatewayAdapter} \longrightarrow \text{External Gateway}$$
   *External gateways and webhooks NEVER directly mutate [`StockEngine`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/services/stock_engine.py#L14-L40), [`CostingService`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/services/costing_service.py), or raw AR records.*
2. **Authoritative State Transitions Only**:
   Browser/client requests are NEVER permitted to mark a payment as `SUCCEEDED`. Only a cryptographically verified webhook or an authoritative server-to-server gateway verification call can transition a payment to `SUCCEEDED`.
3. **Double-Entry AR Integration**:
   Payment success automatically creates authoritative [`CustomerPayment`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/invoicing.py#L52-L73) and [`PaymentAllocation`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/invoicing.py#L74-L84) records, reducing [`CustomerInvoice.balance_due`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/models/invoicing.py#L19) and customer credit exposure. Refunds symmetrically reverse invoice balances and allocations.
4. **PCI Compliance Zero-Knowledge Guarantee**:
   AuraStock strictly enforces a zero raw PAN (Primary Account Number), CVV, or card PIN storage policy. All card data is handled via provider-hosted checkout sessions or client-side tokenization (e.g. Stripe Elements, Razorpay Checkout).

---

## 1. Payment Lifecycle State Machine

```
                              ┌───────────────────┐
                              │      CREATED      │
                              └─────────┬─────────┘
                                        │ (Create Checkout Session / Intent)
                                        ▼
                              ┌───────────────────┐
        ┌────────────────────►│      PENDING      │◄────────────────────┐
        │                     └─────────┬─────────┘                     │
  (Two-Step Auth)                       │ (Direct Sale / Single-Step)   │ (Retry on Lost Response)
        ▼                               ▼                               │
  ┌────────────┐                  ┌───────────┐                         │
  │ AUTHORIZED │                  │ CAPTURED  │─────────────────────────┘
  └─────┬──────┘                  └─────┬─────┘
        │ (Capture Command)             │ (Authoritative Settlement Confirmed)
        ▼                               ▼
  ┌────────────┐                  ┌───────────┐
  │  CAPTURED  │                  │ SUCCEEDED │
  └────────────┘                  └─────┬─────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │ (Partial Refund)                      │ (Full Refund)
                    ▼                                       ▼
          ┌───────────────────┐                   ┌───────────────────┐
          │ PARTIALLY_REFUNDED│                   │     REFUNDED      │
          └───────────────────┘                   └───────────────────┘

  Terminal Failure States (from CREATED, PENDING, or AUTHORIZED):
  • FAILED: Payment declined by issuing bank, insufficient funds, expired card.
  • CANCELLED: Checkout session expired, cancelled by customer, or voided by merchant.
```

### 1.1 Valid State Transition Matrix

| Current State | Next State | Trigger / Condition | AR / Balance Impact |
| :--- | :--- | :--- | :--- |
| `CREATED` | `PENDING` | Checkout session created / intent dispatched | None |
| `CREATED` | `CANCELLED` | Session aborted or customer dismissed checkout | None |
| `PENDING` | `AUTHORIZED` | Pre-authorization hold placed by gateway | None (Hold only) |
| `PENDING` | `CAPTURED` | Single-step payment authorization & capture | None (Awaiting final confirmation) |
| `PENDING` | `SUCCEEDED` | Immediate settlement verified | Reduce `balance_due`, post `CustomerPayment` |
| `PENDING` | `FAILED` | Gateway decline / processing error | None |
| `AUTHORIZED` | `CAPTURED` | Merchant executes capture API | None (Pending final settlement) |
| `AUTHORIZED` | `CANCELLED` | Merchant voids authorization | None |
| `CAPTURED` | `SUCCEEDED` | Authoritative webhook confirms fund capture | Reduce `balance_due`, post `CustomerPayment` |
| `SUCCEEDED` | `PARTIALLY_REFUNDED`| Approved refund where $\text{Refund} < \text{Paid}$ | Increase `balance_due` by refund amount |
| `SUCCEEDED` | `REFUNDED` | Approved refund where $\text{Refund} == \text{Paid}$ | Restore full `balance_due`, invoice `ISSUED` |

---

## 2. Multi-Provider Gateway Abstraction

```
                              ┌──────────────────────────────┐
                              │        PaymentService        │
                              └──────────────┬───────────────┘
                                             │
                                             ▼
                              ┌──────────────────────────────┐
                              │  PaymentGatewayProvider ABC  │
                              └──────────────┬───────────────┘
                                             │
                 ┌───────────────────────────┼───────────────────────────┐
                 ▼                           ▼                           ▼
        ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
        │  StripeAdapter  │         │ RazorpayAdapter │         │   MockAdapter   │
        │ • create_intent │         │ • create_order  │         │ • deterministic │
        │ • capture_funds │         │ • capture_funds │         │ • sim latency   │
        │ • process_refund│         │ • process_refund│         │ • sim failures  │
        │ • verify_webhook│         │ • verify_webhook│         │ • zero external │
        └─────────────────┘         └─────────────────┘         └─────────────────┘
```

### 2.1 Provider Interface (`app/services/payments/base.py`)

```python
class PaymentGatewayProvider(ABC):
    @abstractmethod
    async def create_payment_intent(self, account: PaymentGatewayAccount, req: PaymentIntentCreateRequest) -> GatewayIntentResult:
        """Initializes payment intent/order on gateway."""
        pass

    @abstractmethod
    async def capture_payment(self, account: PaymentGatewayAccount, gateway_intent_id: str, amount: Decimal) -> GatewayCaptureResult:
        """Captures pre-authorized payment."""
        pass

    @abstractmethod
    async def cancel_payment(self, account: PaymentGatewayAccount, gateway_intent_id: str, reason: str) -> GatewayCancelResult:
        """Voids authorization or cancels pending session."""
        pass

    @abstractmethod
    async def process_refund(self, account: PaymentGatewayAccount, req: GatewayRefundRequest) -> GatewayRefundResult:
        """Submits refund to gateway."""
        pass

    @abstractmethod
    def verify_webhook_signature(self, account: PaymentGatewayAccount, payload_bytes: bytes, headers: Dict[str, str]) -> Tuple[bool, Optional[str]]:
        """Verifies webhook signature using HMAC-SHA256."""
        pass

    @abstractmethod
    def parse_webhook_event(self, payload_dict: Dict[str, Any]) -> GatewayWebhookEventData:
        """Normalizes provider-specific webhook event payload."""
        pass
```

---

## 3. Data Model Design (`apps/backend/app/models/payment_gateway.py`)

```python
class PaymentGatewayAccount(Base, BaseModelMixin):
    __tablename__ = "payment_gateway_accounts"

    tenant_id = Column(String(36), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False) # STRIPE, RAZORPAY, MOCK
    name = Column(String(100), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    api_secret_encrypted = Column(Text, nullable=True)
    webhook_secret_encrypted = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_test_mode = Column(Boolean, default=True, nullable=False)
    supported_currencies = Column(JSON, default=["USD", "INR", "EUR"], nullable=False)
    supported_methods = Column(JSON, default=["CARD", "BANK_TRANSFER", "UPI"], nullable=False)
    settings_json = Column(JSON, nullable=True)

class PaymentTransaction(Base, BaseModelMixin):
    __tablename__ = "payment_transactions"

    tenant_id = Column(String(36), nullable=False, index=True)
    transaction_number = Column(String(50), unique=True, index=True, nullable=False) # TXN-YYYYMMDD-XXXX
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    invoice_id = Column(String(36), ForeignKey("customer_invoices.id"), nullable=False, index=True)
    gateway_account_id = Column(String(36), ForeignKey("payment_gateway_accounts.id"), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False)
    
    # Gateway Identifiers
    gateway_intent_id = Column(String(100), unique=True, index=True, nullable=True)
    gateway_charge_id = Column(String(100), index=True, nullable=True)
    
    amount = Column(Numeric(18, 4), nullable=False)
    amount_captured = Column(Numeric(18, 4), default=0.0, nullable=False)
    amount_refunded = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    
    status = Column(String(30), default="CREATED", nullable=False, index=True)
    payment_method_type = Column(String(50), default="CARD", nullable=False)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
    
    client_secret = Column(String(255), nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    customer = relationship("Customer", lazy="selectin")
    invoice = relationship("CustomerInvoice", lazy="selectin")
    gateway_account = relationship("PaymentGatewayAccount", lazy="selectin")
    refunds = relationship("PaymentTransactionRefund", back_populates="transaction", cascade="all, delete-orphan", lazy="selectin")

class PaymentTransactionRefund(Base, BaseModelMixin):
    __tablename__ = "payment_transaction_refunds"

    tenant_id = Column(String(36), nullable=False, index=True)
    refund_number = Column(String(50), unique=True, index=True, nullable=False) # REF-YYYYMMDD-XXXX
    transaction_id = Column(String(36), ForeignKey("payment_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    gateway_refund_id = Column(String(100), index=True, nullable=True)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    reason = Column(String(255), nullable=True)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, SUCCEEDED, FAILED
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
    
    transaction = relationship("PaymentTransaction", back_populates="refunds")

class PaymentWebhookEvent(Base, BaseModelMixin):
    __tablename__ = "payment_webhook_events"

    tenant_id = Column(String(36), nullable=False, index=True)
    gateway_account_id = Column(String(36), ForeignKey("payment_gateway_accounts.id"), nullable=False, index=True)
    provider_code = Column(String(50), nullable=False)
    event_id = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(JSON, nullable=False)
    signature = Column(String(255), nullable=False)
    status = Column(String(30), default="RECEIVED", nullable=False) # RECEIVED, PROCESSED, IGNORED, FAILED
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_code", "event_id", name="uq_payment_webhook_event"),
    )
```

---

## 4. Accounting & Double-Entry AR Settlement

### 4.1 Payment Numerical Scenario (Partial Payments)
- **Customer Invoice Total**: ₹10,000.00
- **Payment 1 (Credit Card)**: ₹4,000.00
  $$\text{amount\_paid} = ₹4,000.00 \quad \text{balance\_due} = ₹6,000.00 \quad \text{status} = \text{PARTIALLY\_PAID}$$
  $$\text{Customer.current\_credit\_exposure} \mathrel{-}= ₹4,000.00$$
- **Payment 2 (UPI)**: ₹6,000.00
  $$\text{amount\_paid} = ₹10,000.00 \quad \text{balance\_due} = ₹0.00 \quad \text{status} = \text{PAID}$$
  $$\text{Customer.current\_credit\_exposure} \mathrel{-}= ₹6,000.00$$

### 4.2 Refund Numerical Scenario
- **Customer Invoice Total**: ₹10,000.00 (Fully Paid, $\text{balance\_due} = ₹0$)
- **Refund Executed**: ₹3,000.00
  $$\text{amount\_paid} = ₹7,000.00 \quad \text{balance\_due} = ₹3,000.00 \quad \text{status} = \text{PARTIALLY\_PAID}$$
  $$\text{Customer.current\_credit\_exposure} \mathrel{+}= ₹3,000.00$$
- **Customer Credit Note**: Automatically generated and linked to the refund for audit symmetry.

---

## 5. Security & Threat Model

| Threat Vector | Severity | Mitigation Strategy |
| :--- | :---: | :--- |
| **Forged Webhook Events** | Critical | Constant-time HMAC-SHA256 signature verification using stored account webhook secrets. |
| **Webhook Replay Attacks** | High | Strict idempotency via `uq_payment_webhook_event` unique constraint and 5-minute timestamp tolerance. |
| **Client Payment Fabrication** | Critical | Portal endpoints CANNOT set `status = SUCCEEDED`. Only server-to-server gateway verification triggers settlement. |
| **Cross-Customer Invoice Sniping** | High | Payment intent creation strictly enforces `invoice.customer_id == claims.customer_id`. |
| **Overpayment / Duplicate Charge** | High | Invoicing lock `with_for_update()` validates `intent_amount <= invoice.balance_due`. |
| **PCI Scope Contamination** | Critical | Zero card numbers or CVVs stored in AuraStock database; client tokenization only. |

---

## 6. Verification & Test Strategy

1. **Deterministic Mock Gateway**: Complete mock provider supporting success, decline, timeout, network error, and webhook simulations.
2. **State Machine Transitions**: Assert all valid transitions (`CREATED` $\to$ `PENDING` $\to$ `AUTHORIZED` $\to$ `CAPTURED` $\to$ `SUCCEEDED` $\to$ `REFUNDED`) and reject illegal transitions (e.g. `REFUNDED` $\to$ `PENDING`).
3. **Idempotent Intent & Webhook Ingestion**: Submit duplicate intents and duplicate webhooks $\implies$ assert 0 duplicate charges or duplicate AR entries.
4. **Out-of-Order Webhook Monotonicity**: Submit `SUCCEEDED` webhook followed by delayed `PENDING` webhook $\implies$ status never regresses.
5. **Partial Payment & Partial Refund AR Scenarios**: Verify exact numerical arithmetic on invoice balances and credit exposure.
6. **Cross-Customer Invoice Payment Protection**: Assert Customer A attempting to pay Customer B's invoice yields HTTP 403 / 404.
7. **Zero Inventory/Costing Mutation**: Assert `StockLedgerTransaction` and `CostLayer` counts remain identical throughout all payment and refund lifecycles.
