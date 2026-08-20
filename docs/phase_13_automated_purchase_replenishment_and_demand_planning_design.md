# Phase 13 Design: Automated Purchase Replenishment & Demand Planning

## Executive Overview

Phase 13 establishes an automated, deterministic **Purchase Replenishment & Demand Planning Subsystem** for AuraStock. It bridges the gap between operational demand (Sales Order commitments and Manufacturing Work Order component consumption) and automated procurement (Purchase Order generation) without creating parallel inventory or costing engines.

### Architectural Invariants:
1. **Strict Engine Separation**:
   $$\text{StockEngine (Inventory Truth)} \longleftrightarrow \text{CostingService (Valuation)} \longleftrightarrow \text{Procurement (POs)} \longleftrightarrow \text{Sales (SO Demand)} \longleftrightarrow \text{Manufacturing (BOM Demand)}$$
2. **Three-Tier Procurement Gate**:
   $$\text{Recommendation (Analytics)} \xrightarrow{\text{User Selection}} \text{Draft PO (Procurement)} \xrightarrow{\text{Spend Approval}} \text{Approved PO (Authorized)}$$
   *Automated replenishment NEVER silently creates approved or committed purchase orders.*
3. **Non-Double-Counting Manufacturing Invariant**:
   Component stock allocated to `RELEASED` Work Orders is already reserved in `StockBalanceCache.quantity_allocated`. Unreserved component requirements from `PLANNED` Work Orders are added to net gross requirements, ensuring zero double-counting.

---

## 1. Mathematical & Calculation Methodology

### 1.1 Net Inventory Position & Available-to-Promise (ATP)
For each tuple `(Warehouse W, ItemVariant V)`:

$$\text{On-Hand Stock } (Q_{\text{on\_hand}}) = \sum \text{StockBalanceCache.quantity\_on\_hand}(W, V)$$

$$\text{Allocated Stock } (Q_{\text{allocated}}) = \sum \text{StockBalanceCache.quantity\_allocated}(W, V)$$

$$\text{Available Stock } (Q_{\text{avail}}) = \max(0, Q_{\text{on\_hand}} - Q_{\text{allocated}})$$

$$\text{Incoming Supply } (Q_{\text{incoming}}) = \sum_{\text{PO} \in \{\text{APPROVED, PARTIALLY\_RECEIVED}\}} (Q_{\text{ordered}} - Q_{\text{received}})$$

$$\text{Planned Production Demand } (Q_{\text{mfg\_planned}}) = \sum_{\text{WO} \in \{\text{PLANNED}\}} (Q_{\text{component\_required}} - Q_{\text{component\_consumed}})$$

$$\mathbf{\text{Net Inventory Position } (NIP) = Q_{\text{avail}} + Q_{\text{incoming}} - Q_{\text{mfg\_planned}}}$$

---

### 1.2 Demand Velocity & Average Daily Usage (ADU)
To provide robust forecasting resilient to outliers and seasonal shifts:
- **Historical Sales Velocity**: Calculated from authoritative `COGSRecord` shipments across 30, 90, and 180-day lookback windows:
  $$ADU_{30} = \frac{\sum_{\text{last 30d}} Q_{\text{shipped}}}{30}, \quad ADU_{90} = \frac{\sum_{\text{last 90d}} Q_{\text{shipped}}}{90}, \quad ADU_{180} = \frac{\sum_{\text{last 180d}} Q_{\text{shipped}}}{180}$$
- **Effective Weighted ADU**:
  $$ADU_{\text{effective}} = (0.50 \times ADU_{30}) + (0.35 \times ADU_{90}) + (0.15 \times ADU_{180})$$
- **Demand Trend Direction**:
  $$\text{Trend \%} = \frac{ADU_{30} - ADU_{90}}{ADU_{90}} \times 100$$
  - $\text{Trend \%} > +15\% \implies \text{ACCELERATING}$
  - $\text{Trend \%} < -15\% \implies \text{DECELERATING}$
  - Otherwise $\implies \text{STABLE}$

---

### 1.3 Dynamic Safety Stock ($SS$) & Reorder Point ($ROP$)
1. **Lead Time ($L$)**:
   - Retrieved from the preferred active `SupplierProduct.lead_time_days` (defaulting to 14 days if unconfigured).
2. **Safety Stock ($SS$)**:
   - Configurable safety stock days $D_{ss}$ (default = 7 days for fast-moving items, 14 days for slow-moving):
     $$SS = \text{round\_up}(ADU_{\text{effective}} \times D_{ss})$$
   - If historical demand standard deviation $\sigma_D$ is available: $SS = Z_{\alpha} \times \sigma_D \times \sqrt{L}$.
3. **Reorder Point ($ROP$)**:
   $$ROP = (ADU_{\text{effective}} \times L) + SS$$
4. **Target Maximum Stock ($Q_{\text{max}}$)**:
   - Configurable target coverage days $D_{\text{cov}}$ (e.g. 30 days):
     $$Q_{\text{max}} = ROP + (ADU_{\text{effective}} \times D_{\text{cov}})$$

---

### 1.4 Suggested Reorder Quantity ($RPQ$) & Supplier Packaging Constraints
When $NIP \le ROP$:
1. **Raw Unconstrained Requirement ($RPQ_{\text{raw}}$)**:
   $$RPQ_{\text{raw}} = \max(0, Q_{\text{max}} - NIP)$$
2. **Supplier Pack Size & MOQ Constraints**:
   - Let $MOQ$ be `SupplierProduct.minimum_order_quantity` (default = 1.0).
   - Let $PS$ be `SupplierProduct.pack_size` (default = 1.0).
   - The final recommended order quantity $RPQ_{\text{final}}$ is rounded up to the nearest integer multiple of $PS$, subject to $MOQ$:
     $$\text{Packs} = \left\lceil \frac{RPQ_{\text{raw}}}{PS} \right\rceil$$
     $$RPQ_{\text{packed}} = \text{Packs} \times PS$$
     $$\mathbf{RPQ_{\text{final}} = \max(MOQ, RPQ_{\text{packed}})}$$

---

### 1.5 Suggested Purchase Date & Delivery Date
- **Stock Coverage in Days ($Days_{\text{coverage}}$)**:
  $$Days_{\text{coverage}} = \begin{cases} \frac{Q_{\text{avail}}}{ADU_{\text{effective}}} & \text{if } ADU_{\text{effective}} > 0 \\ 999 & \text{if } ADU_{\text{effective}} = 0 \end{cases}$$
- **Runout Date**: $Date_{\text{runout}} = \text{Today} + Days_{\text{coverage}}$
- **Suggested Order Date**:
  $$Date_{\text{order}} = \max\left(\text{Today}, Date_{\text{runout}} - L\right)$$
- **Urgency Classification**:
  - `STOCKOUT_CRITICAL`: $Q_{\text{avail}} = 0$ or $NIP < 0$
  - `REORDER_NOW`: $NIP \le ROP$ and $Date_{\text{order}} \le \text{Today}$
  - `AT_RISK`: $ROP < NIP \le (ROP \times 1.20)$
  - `HEALTHY`: $NIP > ROP$ and $NIP \le Q_{\text{max}}$
  - `OVERSTOCKED`: $NIP > (Q_{\text{max}} \times 1.30)$

---

## 2. Multi-Warehouse & Supplier Intelligence

### 2.1 Supplier Selection Matrix
When generating replenishment recommendations, the engine evaluates available suppliers registered in `SupplierProduct`:
1. **Preferred Supplier Match**: If a supplier has `is_preferred = True` and active effective dates (`effective_from <= now <= effective_to`), they are prioritized.
2. **Best Cost / Lead Time Optimization**: If no preferred supplier exists, the engine selects the active supplier offering the lowest `unit_cost`. In tie-breaks, the supplier with the lowest `lead_time_days` is selected.
3. **Unavailable Supplier Fallback**: If no supplier is mapped for a variant, the recommendation is flagged with `supplier_status = "UNASSIGNED"` and estimated using standard variant cost price and default lead time (14 days).

### 2.2 Multi-Warehouse Distribution
- Each warehouse maintains independent replenishment policies (`ReplenishmentConfig`), enabling regional distribution centers to configure localized safety stock buffers, lead times, and target coverage.
- Draft POs are generated with specific `target_warehouse_id` matching the destination facility.

---

## 3. Data Model Design

### 3.1 Database Schema (`apps/backend/app/models/replenishment.py`)

```python
class ReplenishmentConfig(Base, BaseModelMixin):
    __tablename__ = "replenishment_configs"

    tenant_id = Column(String(36), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True, index=True) # Null = Tenant Global Default
    reorder_method = Column(String(30), default="DYNAMIC_ROP", nullable=False) # DYNAMIC_ROP, MIN_MAX, PERIODIC
    min_quantity = Column(Numeric(18, 4), nullable=True) # For MIN_MAX method
    max_quantity = Column(Numeric(18, 4), nullable=True)
    safety_stock_days = Column(Integer, default=7, nullable=False)
    target_coverage_days = Column(Integer, default=30, nullable=False)
    fixed_safety_stock = Column(Numeric(18, 4), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_variant_id", "warehouse_id", name="uq_replenish_config_tenant_var_wh"),
    )

class ReplenishmentRun(Base, BaseModelMixin):
    __tablename__ = "replenishment_runs"

    tenant_id = Column(String(36), nullable=False, index=True)
    run_number = Column(String(50), unique=True, index=True, nullable=False) # RPL-YYYYMMDD-XXXX
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True)
    triggered_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    total_skus_evaluated = Column(Integer, default=0, nullable=False)
    total_recommendations = Column(Integer, default=0, nullable=False)
    total_estimated_spend = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="COMPLETED", nullable=False) # IN_PROGRESS, COMPLETED, FAILED

    items = relationship("ReplenishmentRecommendationItem", back_populates="run", cascade="all, delete-orphan", lazy="selectin")

class ReplenishmentRecommendationItem(Base, BaseModelMixin):
    __tablename__ = "replenishment_recommendation_items"

    run_id = Column(String(36), ForeignKey("replenishment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id"), nullable=True, index=True)
    
    # Inventory Snapshot
    quantity_on_hand = Column(Numeric(18, 4), nullable=False)
    quantity_allocated = Column(Numeric(18, 4), nullable=False)
    quantity_available = Column(Numeric(18, 4), nullable=False)
    quantity_incoming = Column(Numeric(18, 4), nullable=False)
    quantity_mfg_planned = Column(Numeric(18, 4), default=0.0, nullable=False)
    net_inventory_position = Column(Numeric(18, 4), nullable=False)
    
    # Demand & Sizing
    average_daily_usage = Column(Numeric(18, 4), nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    safety_stock = Column(Numeric(18, 4), nullable=False)
    reorder_point = Column(Numeric(18, 4), nullable=False)
    target_maximum_stock = Column(Numeric(18, 4), nullable=False)
    minimum_order_quantity = Column(Numeric(18, 4), default=1.0, nullable=False)
    pack_size = Column(Numeric(18, 4), default=1.0, nullable=False)
    
    # Recommendation
    suggested_reorder_quantity = Column(Numeric(18, 4), nullable=False)
    estimated_unit_cost = Column(Numeric(18, 4), nullable=False)
    estimated_total_cost = Column(Numeric(18, 4), nullable=False)
    urgency_status = Column(String(30), nullable=False) # STOCKOUT_CRITICAL, REORDER_NOW, AT_RISK, HEALTHY, OVERSTOCKED
    suggested_order_date = Column(DateTime(timezone=True), nullable=False)
    
    # Procurement Conversion Tracking
    action_status = Column(String(30), default="PENDING", nullable=False) # PENDING, DRAFT_PO_CREATED, DISMISSED
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id"), nullable=True)

    run = relationship("ReplenishmentRun", back_populates="items")
    variant = relationship("ItemVariant", lazy="selectin")
    supplier = relationship("Supplier", lazy="selectin")
    warehouse = relationship("Warehouse", lazy="selectin")
```

---

## 4. 1-Click Draft PO Generation & Concurrency Guards

### 4.1 Grouping and Batch Generation
When a purchasing manager approves selected recommendation items:
1. Recommendation items with `action_status = "PENDING"` and valid `supplier_id` are grouped by:
   $$\text{Batch Key} = (\text{tenant\_id}, \text{supplier\_id}, \text{warehouse\_id})$$
2. For each distinct `(Supplier, Warehouse)` group:
   - A single draft `PurchaseOrder` is created with status `DRAFT` via `PurchaseService.create_purchase_order`.
   - PO line items are created with `item_variant_id`, `quantity_ordered = suggested_reorder_quantity`, and `unit_price = estimated_unit_cost`.
   - Recommendation items are updated to `action_status = "DRAFT_PO_CREATED"` and linked via `purchase_order_id`.
3. An audit event `GENERATE_REPLENISHMENT_DRAFT_POS` is logged.

### 4.2 Duplicate Prevention & Idempotency
- Row-level pessimistic locks (`with_for_update()`) are acquired on `ReplenishmentRecommendationItem` rows during conversion.
- If an item's `action_status` is already `DRAFT_PO_CREATED`, it is excluded from new PO creation.

---

## 5. REST API Architecture

| Method | Path | Permissions | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/replenishment/runs` | `procurement:write` | Triggers a deterministic replenishment calculation run. |
| `GET` | `/api/v1/replenishment/runs` | `procurement:read` | Lists historical replenishment runs with summary metrics. |
| `GET` | `/api/v1/replenishment/runs/{id}` | `procurement:read` | Retrieves full recommendation breakdown for a run. |
| `POST` | `/api/v1/replenishment/generate-draft-pos` | `procurement:write` | Converts selected recommendation items into draft POs. |
| `GET` | `/api/v1/replenishment/configs` | `procurement:read` | Retrieves per-variant / per-warehouse replenishment rules. |
| `PUT` | `/api/v1/replenishment/configs` | `procurement:write` | Configures min/max, safety stock days, and target coverage. |

---

## 6. Comprehensive Edge-Case Analysis

| Edge Case Scenario | System Behavior & Invariant |
| :--- | :--- |
| **Zero Historical Demand ($ADU = 0$)** | Falls back to configured `ReplenishmentConfig.min_quantity` or default safety buffer ($10.0$ units). Does not create infinite orders. |
| **New Product / Zero Sales History** | Uses `standard_cost` from `ItemVariant` and default 14-day lead time. Recommends initial stocking based on min-max config. |
| **Overstocked Inventory ($NIP > Q_{\text{max}}$)** | $RPQ_{\text{raw}} = 0 \implies$ No order recommended; flagged with `urgency_status = OVERSTOCKED`. |
| **Negative Available Stock ($Q_{\text{on\_hand}} < Q_{\text{allocated}}$)** | $Q_{\text{avail}} = 0$, $NIP$ accounts for shortfall. Flagged with `urgency_status = STOCKOUT_CRITICAL`. |
| **Stock Already on Inbound PO** | Inbound quantity from approved POs is added to $NIP$, preventing redundant purchase orders. |
| **Manufacturing Component Demand** | Unreserved components from `PLANNED` Work Orders are included in $Q_{\text{mfg\_planned}}$. Components on `RELEASED` orders are already in $Q_{\text{allocated}}$, strictly preventing double-counting. |
| **Supplier Minimum Order Quantity (MOQ)** | If $RPQ_{\text{packed}} < MOQ$, the order quantity is automatically rounded up to $MOQ$. |
| **Supplier Pack Sizing** | Fractional requirement is rounded up using ceiling division: $\lceil RPQ_{\text{raw}} / PS \rceil \times PS$. |
| **Supplier Expired / Unmapped** | Recommendation created with `supplier_id = None`, alert flagged, allowing manual supplier selection during PO generation. |
| **Concurrent Replenishment Runs** | Sequence service generates unique `RPL-YYYYMMDD-XXXX` run numbers. Row locks on `ReplenishmentRecommendationItem` prevent duplicate PO creation. |

---

## 7. Verification & Test Strategy Plan

| Test Scenario | Verification Objective |
| :--- | :--- |
| **1. Net Inventory Position Math** | Verify $NIP = Q_{\text{avail}} + Q_{\text{incoming}} - Q_{\text{mfg\_planned}}$ across diverse inventory balances. |
| **2. ADU & Weighted Velocity** | Verify $ADU_{30}$, $ADU_{90}$, $ADU_{180}$ and trend percentage math against authoritative `COGSRecord` entries. |
| **3. Safety Stock & ROP** | Verify $ROP = (ADU \times L) + SS$ with exact decimal precision. |
| **4. MOQ & Pack Size Rounding** | Verify raw requirement 13 with Pack Size 5 and MOQ 20 produces exactly 20 (Pack size 15 < MOQ 20 $\implies$ 20). |
| **5. Manufacturing Demand Isolation** | Verify `PLANNED` WO components increase demand, while `RELEASED` WO components use existing allocation without double-counting. |
| **6. 1-Click Draft PO Generation** | Verify grouping by `(Supplier, Warehouse)` creates separate draft POs with matching lines and updates item status. |
| **7. Duplicate PO Prevention** | Retrying draft PO creation on already processed items produces 0 duplicate POs. |
| **8. Zero Approval Invariant** | Confirm generated purchase orders have status `DRAFT` and never `APPROVED`. |
| **9. Multi-Warehouse Independence** | Verify Warehouse A reorders independently of Warehouse B inventory. |
| **10. REST API & RBAC** | Verify permissions `procurement:read` and `procurement:write` on all replenishment routes. |
