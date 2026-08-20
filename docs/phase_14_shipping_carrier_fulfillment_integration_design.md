# Phase 14 Design: Shipping, Carrier & Fulfillment Integration

## Executive Overview

Phase 14 designs an enterprise-grade **Shipping, Carrier & Logistics Integration Subsystem** for AuraStock. It connects internal warehouse packing sessions and sales order fulfillment to external logistics providers, multi-carrier rate shopping, automated label generation (ZPL/PDF), multi-package tracking, end-of-day carrier manifests, and webhook delivery synchronization.

### Architectural Invariants:
1. **Strict Engine Separation**:
   $$\text{SalesService (Sales Order Truth)} \longleftrightarrow \text{StockEngine (Inventory Truth)} \longleftrightarrow \text{Warehouse Fulfillment} \longleftrightarrow \text{CarrierIntegration (Logistics)}$$
2. **Zero Direct Inventory Mutation by Carrier APIs**:
   External tracking events or carrier status changes (e.g. `IN_TRANSIT`, `DELIVERED`) NEVER directly alter inventory balances or cost layers. Physical inventory decrement occurs strictly at dispatch via [`StockEngine.post_transaction`](file:///d:/antigravity/Intentory%20Management%20Software/apps/backend/app/services/stock_engine.py#L16-L195).
3. **Pluggable Carrier Abstraction**:
   All carrier operations (FedEx, UPS, DHL, USPS, Shippo, EasyPost, Delhivery) conform to a unified `CarrierProvider` interface, allowing dynamic runtime configuration and multi-carrier rate comparison without vendor lock-in.

---

## 1. Provider Abstraction & Architecture

```
                                  ┌─────────────────────────────────────────┐
                                  │       Fulfillment / Packing Workbench   │
                                  └────────────────────┬────────────────────┘
                                                       │
                                                       ▼
                                  ┌─────────────────────────────────────────┐
                                  │        CarrierIntegrationService        │
                                  │   (Orchestrator, Idempotency, RBAC)     │
                                  └────────────────────┬────────────────────┘
                                                       │
                           ┌───────────────────────────┼───────────────────────────┐
                           ▼                           ▼                           ▼
                ┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
                │   EasyPostProvider  │     │   ShippoProvider    │     │   DirectFedEx / UPS │
                └──────────┬──────────┘     └──────────┬──────────┘     └──────────┬──────────┘
                           │                           │                           │
                           └───────────────────────────┼───────────────────────────┘
                                                       ▼
                                  ┌─────────────────────────────────────────┐
                                  │        Normalized Logistics Models      │
                                  │  • RateQuoteItem (Cost, Transit Days)   │
                                  │  • ShippingLabel (ZPL, PDF, Barcode)    │
                                  │  • TrackingEvent (Normalized Status)    │
                                  └─────────────────────────────────────────┘
```

### 1.1 Provider Interface (`apps/backend/app/services/carriers/base.py`)

```python
class CarrierProvider(ABC):
    @abstractmethod
    async def get_rates(self, account: CarrierAccount, request: RateQuoteRequest) -> List[RateQuoteItem]:
        """Calculates shipping rates across available service levels for given packages."""
        pass

    @abstractmethod
    async def create_shipment(self, account: CarrierAccount, request: CreateCarrierShipmentRequest) -> CarrierShipmentResult:
        """Generates labels, tracking numbers, and registers packages with the carrier."""
        pass

    @abstractmethod
    async def cancel_shipment(self, account: CarrierAccount, tracking_number: str) -> bool:
        """Voids a generated label and cancels pickup with the carrier."""
        pass

    @abstractmethod
    async def track_shipment(self, account: CarrierAccount, tracking_number: str) -> TrackingDetailsResponse:
        """Fetches live tracking status and event history from the carrier."""
        pass

    @abstractmethod
    async def create_manifest(self, account: CarrierAccount, shipment_ids: List[str]) -> ManifestResult:
        """Generates end-of-day SCAN form / manifest for carrier pickup."""
        pass
```

---

## 2. State Machine & Status Synchronization

### 2.1 Dual Lifecycle Synchronization Matrix

| Internal Fulfillment Status | External Carrier Status | Synchronized Action / Invariant |
| :--- | :--- | :--- |
| `PICKED` | *None* | Stock picked and staged at packing station. |
| `PACKED` | `LABEL_CREATED` | Packing session completed, packages weighed/measured, shipping label generated. Tracking number assigned. |
| `SHIPPED` | `PICKED_UP` / `IN_TRANSIT` | Goods physically loaded onto carrier truck. `StockEngine` issues inventory and depletes FIFO cost layers. |
| `SHIPPED` | `OUT_FOR_DELIVERY` | Carrier webhook received: tracking timeline updated, customer notification sent. |
| `DELIVERED` | `DELIVERED` | Delivery confirmed with proof of delivery (POD). `SalesOrder.status` transitions to `DELIVERED`. |
| `SHIPPED` | `EXCEPTION` / `FAILED_DELIVERY` | Carrier exception logged (e.g. incorrect address, recipient unavailable). Alert flagged for logistics team. |
| `RETURNED` | `RETURN_TO_SENDER` | Carrier returns package: initiates `SalesReturn` quarantine inspection before restock/scrap. |

---

## 3. Data Model Design

### 3.1 Database Schema (`apps/backend/app/models/shipping.py`)

```python
class CarrierAccount(Base, BaseModelMixin):
    __tablename__ = "carrier_accounts"

    tenant_id = Column(String(36), nullable=False, index=True)
    carrier_code = Column(String(50), nullable=False) # FEDEX, UPS, DHL, USPS, SHIPPO, EASYPOST, DELHIVERY
    account_name = Column(String(100), nullable=False)
    account_number = Column(String(100), nullable=True)
    api_key_encrypted = Column(Text, nullable=False)
    api_secret_encrypted = Column(Text, nullable=True)
    is_sandbox = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    default_service_level = Column(String(50), nullable=True)
    webhook_secret = Column(String(255), nullable=True)

class ShippingServiceLevel(Base, BaseModelMixin):
    __tablename__ = "shipping_service_levels"

    tenant_id = Column(String(36), nullable=False, index=True)
    carrier_account_id = Column(String(36), ForeignKey("carrier_accounts.id"), nullable=False, index=True)
    service_code = Column(String(50), nullable=False) # e.g. PRIORITY_OVERNIGHT, GROUND, EXPRESS_SAVER
    service_name = Column(String(100), nullable=False)
    transit_days_estimate = Column(Integer, nullable=True)
    is_international = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class ShipmentPackage(Base, BaseModelMixin):
    __tablename__ = "shipment_packages"

    tenant_id = Column(String(36), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    package_number = Column(Integer, default=1, nullable=False)
    package_type = Column(String(30), default="CUSTOM_BOX", nullable=False) # ENVELOPE, SMALL_BOX, MEDIUM_BOX, LARGE_BOX, PALLET, CUSTOM_BOX
    
    # Weight and Dimensions
    weight_kg = Column(Numeric(10, 3), nullable=False)
    length_cm = Column(Numeric(10, 2), nullable=False)
    width_cm = Column(Numeric(10, 2), nullable=False)
    height_cm = Column(Numeric(10, 2), nullable=False)
    dimensional_weight_kg = Column(Numeric(10, 3), nullable=False)
    
    # Logistics Identifiers
    tracking_number = Column(String(100), nullable=True, index=True)
    carrier_package_id = Column(String(100), nullable=True)
    label_format = Column(String(10), default="PDF", nullable=False) # PDF, ZPL, PNG
    label_url = Column(String(500), nullable=True)
    label_base64 = Column(Text, nullable=True) # For offline thermal printing

    shipment = relationship("Shipment", backref="packages")
    items = relationship("ShipmentPackageItem", back_populates="package", cascade="all, delete-orphan", lazy="selectin")

class ShipmentPackageItem(Base, BaseModelMixin):
    __tablename__ = "shipment_package_items"

    package_id = Column(String(36), ForeignKey("shipment_packages.id", ondelete="CASCADE"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    serial_number = Column(String(100), nullable=True)
    batch_number = Column(String(100), nullable=True)

    package = relationship("ShipmentPackage", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")

class ShipmentTrackingEvent(Base, BaseModelMixin):
    __tablename__ = "shipment_tracking_events"

    tenant_id = Column(String(36), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id"), nullable=False, index=True)
    tracking_number = Column(String(100), nullable=False, index=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)
    carrier_status = Column(String(50), nullable=False)
    normalized_status = Column(String(30), nullable=False) # LABEL_CREATED, PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, EXCEPTION, RETURNED
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)

class CarrierManifest(Base, BaseModelMixin):
    __tablename__ = "carrier_manifests"

    tenant_id = Column(String(36), nullable=False, index=True)
    manifest_number = Column(String(50), unique=True, index=True, nullable=False) # MNF-YYYYMMDD-XXXX
    carrier_account_id = Column(String(36), ForeignKey("carrier_accounts.id"), nullable=False)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False)
    manifest_url = Column(String(500), nullable=True)
    total_packages = Column(Integer, default=0, nullable=False)
    total_weight_kg = Column(Numeric(10, 3), default=0.0, nullable=False)
    status = Column(String(30), default="GENERATED", nullable=False) # GENERATED, SUBMITTED, CLOSED
```

---

## 4. Multi-Package & Rate Shopping Methodology

### 4.1 Volumetric & Dimensional Weight Calculation
$$\text{Dimensional Weight (kg)} = \frac{\text{Length (cm)} \times \text{Width (cm)} \times \text{Height (cm)}}{5000}$$
$$\text{Billable Weight} = \max(\text{Actual Scale Weight}, \text{Dimensional Weight})$$

### 4.2 Rate Shopping Engine
When packing completes:
1. System passes origin warehouse address, destination customer address, and all package dimensions/weights to active carrier accounts.
2. Carrier providers return real-time quotes in parallel (`asyncio.gather`).
3. Quotes are sorted by:
   - Lowest Cost (default)
   - Fastest Delivery
   - Best Value (weighted cost vs. transit days)
4. Purchasing / logistics manager selects the preferred rate or uses preconfigured tenant auto-rules.

---

## 5. Webhook Handling, Idempotency & Edge-Case Resilience

| Scenario | Architectural Guard & Failure Strategy |
| :--- | :--- |
| **Label Generated Twice** | Idempotency key `tenant_id:shipment_id:carrier_account_id` locks the transaction with `with_for_update()`. Retries return the existing label URL. |
| **Carrier API Timeout** | Exponential backoff retry with 3 attempts (1s, 2s, 4s) and circuit breaker. If carrier is unreachable, fallback to manual tracking number entry. |
| **Duplicate Webhook Delivery** | Webhook payload hashed (`SHA256(event_id + tracking_number + timestamp)`). Duplicate hashes are acknowledged with HTTP 200 without reprocessing. |
| **Out-of-Order Webhooks** | Events are ordered by `event_timestamp`. The shipment's top-level status is only advanced forward monotonically. |
| **Shipment Cancelled After Label** | `CarrierService.cancel_shipment` triggers void API on the carrier, voids the `ShippingLabel`, and unallocates the tracking number. |
| **Multi-Package Label Generation** | Master tracking number assigned to shipment; individual package tracking numbers assigned to child `ShipmentPackage` records. |
| **Offline Desktop Operation** | In offline mode, warehouse operators can enter manual tracking numbers and print offline ZPL templates; carrier registration queues for sync. |

---

## 6. REST API Design

| Method | Path | Permissions | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/shipping/accounts` | `shipping:read` | Lists configured carrier accounts. |
| `POST` | `/api/v1/shipping/accounts` | `shipping:write` | Configures new carrier credentials and service levels. |
| `POST` | `/api/v1/shipping/rate-shopping` | `shipping:read` | Fetches real-time rate comparison across carriers. |
| `POST` | `/api/v1/shipping/labels/generate` | `shipping:write` | Generates official carrier label (PDF/ZPL) and tracking numbers. |
| `POST` | `/api/v1/shipping/labels/{id}/void` | `shipping:write` | Voids label with carrier and cancels pickup. |
| `GET` | `/api/v1/shipping/tracking/{tracking_number}` | `shipping:read` | Fetches real-time tracking timeline and events. |
| `POST` | `/api/v1/shipping/webhooks/{carrier_code}` | *Public Webhook (HMAC Signature)* | Ingests carrier webhook tracking updates. |
| `POST` | `/api/v1/shipping/manifests` | `shipping:write` | Generates end-of-day carrier pickup manifest. |

---

## 7. Verification & Test Strategy

1. **Carrier Provider Mock Adapter**: Deterministic mock provider verifying rate shopping, label generation, cancellation, tracking, and manifests without external API dependencies.
2. **Dimensional Weight Math**: Exact validation of $L \times W \times H / 5000$ and billable weight selection.
3. **Multi-Package Labeling**: Verify 3-package shipment gets 1 master tracking number and 3 distinct package labels.
4. **Idempotent Label Generation**: Verify concurrent label requests on the same shipment produce exactly 1 label and 0 duplicates.
5. **Webhook Monotonic Progression**: Verify out-of-order webhook delivery preserves correct chronological status.
6. **Strict Inventory Non-Mutation**: Verify tracking event ingestion does NOT create `StockLedgerTransaction` or modify `CostLayer`.
7. **RBAC & Security**: Verify permissions `shipping:read`, `shipping:write`, and webhook HMAC signature validation.
