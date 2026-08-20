# Phase 15 Design: B2B Customer & Supplier Portals

## Executive Overview

Phase 15 designs the **B2B Customer & Supplier Portals** subsystem for AuraStock. It provides secure, multi-tenant, self-service digital workspaces for external business partners (Customers and Suppliers) while maintaining strict tenant isolation, entity-level data boundaries, separate portal RBAC permissions, and sanitized data transfer objects (DTOs) that prevent any leak of internal costs, margins, supplier relationships, or inventory truth.

### Core Architectural Invariants:
1. **Engine Separation & Flow Isolation**:
   $$\text{Customer Portal} \longrightarrow \text{SalesService (SO Truth)} \longrightarrow \text{StockEngine (Internal Inventory Truth)}$$
   $$\text{Supplier Portal} \longrightarrow \text{PurchaseService (PO/GRN Truth)} \longrightarrow \text{AP/Costing (Internal AP Truth)}$$
   *Portal users NEVER directly call [`StockEngine`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/services/stock_engine.py#L14-L40) or [`CostingService`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/services/costing_service.py).*
2. **Strict Company & Tenant Isolation**:
   - Customer Portal sessions are locked to `(tenant_id, customer_id)`.
   - Supplier Portal sessions are locked to `(tenant_id, supplier_id)`.
   - Any attempt to access cross-company or cross-tenant records yields immediate HTTP 403 / 404 with audit security alerts.
3. **Data Sanitization Guarantee**:
   All portal-facing API responses strip internal costs, margin percentages, landed cost breakdowns, supplier master lists, internal warehouse bin locations, and internal staff notes.

---

## 1. Portal Capability Matrix

| Capability | Customer Portal | Supplier Portal | Internal ERP |
| :--- | :---: | :---: | :---: |
| **Authentication & Profile** | Self-service MFA, invite members, edit contact info | Self-service MFA, invite staff, edit banking info | Full user & RBAC management |
| **Catalog & Pricing** | View assigned price lists, product SKU catalog | View supplier catalog, lead times, MOQ | Master product & price lists |
| **Orders** | Create draft orders, view confirmed/shipped orders | View authorized POs, confirm delivery dates | Full SO & PO management |
| **Fulfillment & Logistics** | View carrier tracking, package weights, delivery ETA | Submit Advance Shipping Notice (ASN) & tracking | Pack, label, rate-shop, dispatch |
| **Invoicing & Payments** | View issued AR invoices, balances, pay online | View submitted bills, 3-way match & AP payment status | Full AR, AP, General Ledger |
| **Returns & RMAs** | Submit return request (RMA), track return status | Receive return-to-vendor (RTV) debit memos | Quarantine, inspect, restock/scrap |
| **Internal Margins & Costs** | **STRICTLY BLOCKED** | **STRICTLY BLOCKED** | Authorized staff only |

---

## 2. Authentication & Authorization Model

```
                                  ┌─────────────────────────────────────────┐
                                  │           Unified Auth Gateway          │
                                  │    POST /api/v1/portal/auth/login       │
                                  └────────────────────┬────────────────────┘
                                                       │
                                 ┌─────────────────────┴─────────────────────┐
                                 ▼                                           ▼
                    ┌────────────────────────┐                  ┌────────────────────────┐
                    │  Customer Portal User  │                  │  Supplier Portal User  │
                    │  Claims:               │                  │  Claims:               │
                    │  • tenant_id           │                  │  • tenant_id           │
                    │  • customer_id         │                  │  • supplier_id         │
                    │  • portal_type=CUSTOMER│                  │  • portal_type=SUPPLIER│
                    │  • permissions: [...]  │                  │  • permissions: [...]  │
                    └────────────┬───────────┘                  └────────────┬───────────┘
                                 │                                           │
                                 ▼                                           ▼
                    ┌────────────────────────┐                  ┌────────────────────────┐
                    │  Customer API Router   │                  │   Supplier API Router  │
                    │  (/api/v1/portal/cust) │                  │  (/api/v1/portal/supp) │
                    └────────────────────────┘                  └────────────────────────┘
```

### 2.1 Portal Permissions

```
Customer Portal:
• customer:profile:read / customer:profile:write
• customer:users:manage (invite/deactivate company users)
• customer:catalog:read (view assigned products and customer-specific prices)
• customer:orders:read / customer:orders:create / customer:orders:cancel
• customer:invoices:read / customer:payments:create
• customer:shipments:read / customer:tracking:read
• customer:returns:create / customer:returns:read

Supplier Portal:
• supplier:profile:read / supplier:profile:write
• supplier:users:manage (invite/deactivate supplier staff)
• supplier:catalog:read / supplier:catalog:update
• supplier:purchase_orders:read / supplier:purchase_orders:confirm / supplier:purchase_orders:reject
• supplier:asn:create / supplier:asn:read
• supplier:invoices:read / supplier:invoices:submit
• supplier:payments:read
```

---

## 3. Data Model Design (`apps/backend/app/models/portal.py`)

```python
class PortalUser(Base, BaseModelMixin):
    __tablename__ = "portal_users"

    tenant_id = Column(String(36), nullable=False, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    portal_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    is_active = Column(Boolean, default=True, nullable=False)
    mfa_secret = Column(String(100), nullable=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    memberships = relationship("PortalUserMembership", back_populates="portal_user", cascade="all, delete-orphan", lazy="selectin")

class PortalUserMembership(Base, BaseModelMixin):
    __tablename__ = "portal_user_memberships"

    portal_user_id = Column(String(36), ForeignKey("portal_users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    entity_id = Column(String(36), nullable=False, index=True) # customer_id or supplier_id
    role = Column(String(30), default="MEMBER", nullable=False) # ADMIN, MEMBER, VIEWER
    is_active = Column(Boolean, default=True, nullable=False)

    portal_user = relationship("PortalUser", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("portal_user_id", "entity_type", "entity_id", name="uq_portal_user_entity"),
    )

class PortalInvitation(Base, BaseModelMixin):
    __tablename__ = "portal_invitations"

    tenant_id = Column(String(36), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False) # CUSTOMER, SUPPLIER
    entity_id = Column(String(36), nullable=False, index=True)
    role = Column(String(30), default="MEMBER", nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_user_id = Column(String(36), nullable=True)

class AdvanceShippingNotice(Base, BaseModelMixin):
    __tablename__ = "advance_shipping_notices"

    tenant_id = Column(String(36), nullable=False, index=True)
    asn_number = Column(String(50), unique=True, index=True, nullable=False) # ASN-YYYYMMDD-XXXX
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=False, index=True)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    carrier_code = Column(String(50), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    estimated_arrival_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), default="SUBMITTED", nullable=False) # SUBMITTED, IN_TRANSIT, RECEIVED, REJECTED
    notes = Column(Text, nullable=True)

    items = relationship("ASNLineItem", back_populates="asn", cascade="all, delete-orphan", lazy="selectin")
```

---

## 4. API Design

### 4.1 Customer Portal Endpoints (`/api/v1/portal/customer`)
- `POST /auth/login`: Customer authentication, returns JWT with `customer_id`.
- `GET /profile`: View customer billing/shipping details and balance.
- `GET /catalog`: Browse master catalog filtered by customer's active price list.
- `GET /orders`: List sales orders for `customer_id`.
- `POST /orders`: Submit a new draft sales order (delegates to `SalesService`).
- `GET /invoices`: View outstanding and historical customer invoices.
- `POST /returns`: Submit an RMA return request for a delivered sales order.
- `GET /shipments/{id}/tracking`: View real-time carrier tracking timeline.

### 4.2 Supplier Portal Endpoints (`/api/v1/portal/supplier`)
- `POST /auth/login`: Supplier authentication, returns JWT with `supplier_id`.
- `GET /profile`: View supplier contact and payment terms.
- `GET /purchase-orders`: List purchase orders issued to `supplier_id`.
- `POST /purchase-orders/{id}/confirm`: Confirm PO with promised delivery date.
- `POST /purchase-orders/{id}/reject`: Reject PO with formal reason.
- `POST /asn`: Submit Advance Shipping Notice with carrier tracking and item lots.
- `GET /invoices`: View vendor bills and 3-way match status.

---

## 5. Security & Threat Modeling

| Threat Vector | Mitigation Strategy |
| :--- | :--- |
| **Predictable ID Document Enumeration** | Signed short-lived document download URLs (HMAC-SHA256, 15-min expiry) verified against `(tenant_id, entity_id)`. |
| **Cross-Company Data Leak** | ORM repository layer automatically injects `customer_id == claims.customer_id` into all queries. |
| **Internal Margin/Cost Leak** | Dedicated Pydantic response models (`CustomerSOLineResponse`, `SupplierPOResponse`) strictly omit `cost_price`, `cogs`, `margin_pct`, `supplier_id`. |
| **Account Lockout & Brute Force** | 5 consecutive failed logins trigger a 15-minute account lock. |
| **Concurrent PO Confirmation** | Optimistic locking via version stamp or row lock on PO status transition. |
| **User Revocation While Active** | JWT check verifies `is_active` on `PortalUser` and `PortalUserMembership` on sensitive mutations. |

---

## 6. Verification & Test Strategy

1. **Strict Customer Isolation**: Test that Customer A querying Customer B's order ID returns HTTP 404 / 403.
2. **Strict Supplier Isolation**: Test that Supplier A querying Supplier B's PO returns HTTP 404 / 403.
3. **Data Sanitization Test**: Assert response JSON for Customer order and Supplier PO contains 0 instances of `cost_price`, `unit_cost`, `margin`, `landed_cost`.
4. **Order & Return Flow**: Assert customer order creation creates a legitimate `SalesOrder` via `SalesService` without directly mutating `StockEngine`.
5. **PO Confirmation & ASN**: Assert supplier PO confirmation updates `PurchaseOrder.status` and ASN creation notifies warehouse receiving.
6. **Document Download Security**: Test expired, forged, and cross-company document tokens are rejected.
7. **RBAC & Invitation Replay Protection**: Assert invitation tokens can only be used once and expired tokens fail.
