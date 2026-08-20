# Phase 20 Design: Advanced Manufacturing & Production Control

## Executive Summary

Phase 20 designs the **Advanced Manufacturing & Production Control** subsystem for the AuraStock ERP platform. Building directly on the foundational BOM and Work Order structures established in Phase 12, Phase 20 expands manufacturing into an enterprise-grade discrete manufacturing control engine. It unifies **Hierarchical Multi-Level BOMs**, **Work Centers & Routing Operations**, **Material Requirements Planning (MRP)**, **Shop-Floor Operation Execution**, **Yield & Scrap Accounting**, **In-Process Quality Inspection Gates**, **WIP Cost Rollup**, and **Double-Entry General Ledger (GL) Integration**.

### Core Architectural Invariants:
1. **Unified Costing & Accounting**:
   $$\text{Production Cost} = \text{Direct Materials (FIFO/MWA)} + \text{Direct Labor} + \text{Machine Costs} + \text{Overhead Absorption} + \text{Scrap Variance}$$
   *Manufacturing uses the existing `CostingService` and `GLService`—no parallel or duplicated accounting engine is introduced.*
2. **Deterministic BOM & Routing Snapshots**:
   *When a Production Order is released, it captures an immutable snapshot of the active BOM revision and routing sequence. Subsequent edits to master data never mutate in-flight production orders.*
3. **Strict Inventory & Quality Isolation**:
   *Uninspected or rejected production items are routed to Quarantine/Scrap bins and can NEVER enter pickable unrestricted inventory.*
4. **Bi-Directional Lot/Serial Traceability**:
   *Full forward and backward lineage: Supplier Component Lot $\leftrightarrow$ Operation Material Issue $\leftrightarrow$ Production Order $\leftrightarrow$ Finished Good Serial/Lot.*

---

## 1. Manufacturing Subsystem Architecture & Lifecycle

```
                                  ┌──────────────────────────────┐
                                  │      Demand Aggregation      │
                                  │  (Sales Orders, ROP, Forecast)│
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │       Production Plan        │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │       Production Order       │
                                  └──────────────┬───────────────┘
                                                 │
                        ┌────────────────────────┼────────────────────────┐
                        ▼                        ▼                        ▼
                ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
                │   PLANNED    │────────►│   RELEASED   │────────►│ MATERIAL_    │
                └──────────────┘         └──────────────┘         │ RESERVED     │
                                                                  └──────┬───────┘
                                                                         │
                        ┌────────────────────────────────────────────────┘
                        ▼
                ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
                │ IN_PROGRESS  │────────►│ PARTIALLY_   │────────►│  COMPLETED   │
                │ (Operations) │         │  COMPLETED   │         │ (Final Insp) │
                └──────┬───────┘         └──────────────┘         └──────────────┘
                       │
                       ▼ (Exception Paths)
                ┌────────────────────────────────────────────────────────┐
                │  • ON_HOLD (Quality / Shortage)    • CANCELLED (Void)  │
                └────────────────────────────────────────────────────────┘
```

### 1.1 State Machine & Transition Rules

| From State | Allowed Target States | Valid Trigger Condition |
| :--- | :--- | :--- |
| **DRAFT** | `PLANNED`, `CANCELLED` | Order created with target finished good, quantity, and BOM reference |
| **PLANNED** | `RELEASED`, `ON_HOLD`, `CANCELLED` | BOM & Routing validated; scheduled start date assigned |
| **RELEASED** | `MATERIAL_RESERVED`, `ON_HOLD`, `CANCELLED` | Deterministic BOM/Routing snapshot created; component inventory checked |
| **MATERIAL_RESERVED** | `IN_PROGRESS`, `ON_HOLD`, `CANCELLED` | All required component balances locked in staging bin |
| **IN_PROGRESS** | `PARTIALLY_COMPLETED`, `COMPLETED`, `ON_HOLD` | First shop-floor operation started; material issued to WIP |
| **PARTIALLY_COMPLETED**| `IN_PROGRESS`, `COMPLETED`, `ON_HOLD` | Output batches completed & inspected; remaining quantity in progress |
| **COMPLETED** | `CLOSED` | 100% finished goods received into stock; WIP cleared to ₹0; variance posted |
| **ON_HOLD** | `RELEASED`, `IN_PROGRESS`, `CANCELLED` | Quality hold, machine breakdown, or material shortage resolved |
| **CANCELLED** | *Terminal* | Reserved inventory released; unconsumed materials returned; zero WIP |

---

## 2. BOM Management & Revision Control

### 2.1 Multi-Level Hierarchical BOM Structure
- Multi-level parent-child tree supporting finished goods, sub-assemblies, phantom assemblies, and raw materials.
- **Phantom Assemblies**: Intermediate sub-assemblies flagged as `is_phantom = True` are exploded directly into raw components during MRP without creating separate intermediate production orders.
- **Scrap Factors**: Component lines support dual scrap modeling:
  $$\text{Total Component Required} = (\text{Quantity Per Unit} \times \text{Yield Qty} \times (1 + \text{Scrap \%})) + \text{Fixed Scrap Qty}$$
- **Alternate / Substitute Components**: Explicit mapping of secondary components with priority ranking and substitution approval flags.
- **Revision Control**: Master BOMs carry `version` (e.g. `1.0`, `1.1`, `2.0`), `effective_start_date`, and `effective_end_date`.

---

## 3. Work Centers, Machines & Routing Operations

```
                                  ┌──────────────────────────────┐
                                  │      Routing (Master)        │
                                  │  (e.g. ROUT-ELEC-ASSEMBLY)   │
                                  └──────────────┬───────────────┘
                                                 │
                        ┌────────────────────────┼────────────────────────┐
                        ▼                        ▼                        ▼
                ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
                │ Operation 10 │────────►│ Operation 20 │────────►│ Operation 30 │
                │ SMT Placement│         │ Wave Soldering│        │ Final Test   │
                ├──────────────┤         ├──────────────┤         ├──────────────┤
                │ Work Center: │         │ Work Center: │         │ Work Center: │
                │ WC-SMT-01    │         │ WC-SOLDER-01 │         │ WC-QA-01     │
                │ Setup: 30m   │         │ Setup: 15m   │         │ Setup: 10m   │
                │ Run: 2m/unit │         │ Run: 1m/unit │         │ Run: 3m/unit │
                └──────────────┘         └──────────────┘         └──────────────┘
```

### 3.1 Work Center Model (`WorkCenter`)
- `code`, `name`, `department`, `warehouse_id`
- `hourly_labor_rate`: Cost per operator hour
- `hourly_machine_rate`: Cost per machine operating hour
- `daily_capacity_hours`: Available hours per shift $\times$ shifts per day
- `efficiency_factor`: Nominal performance rating (e.g. $0.95 = 95\%$)

### 3.2 Operation Step Model (`ProductionOperation`)
- `sequence_number`: 10, 20, 30...
- `operation_name`, `work_center_id`, `assigned_machine_id`
- `setup_time_minutes`, `run_time_minutes_per_unit`, `queue_time_minutes`, `move_time_minutes`
- `status`: `PENDING` $\to$ `RUNNING` $\to$ `PAUSED` $\to$ `COMPLETED`
- `operator_user_id`: Claimed operator (enforces mutual exclusion against dual execution)

---

## 4. Material Planning (MRP) & Reservation Pipeline

```
Production Order Demand
          │
          ▼
Multi-Level BOM Explosion (Recursive)
          │
          ▼
Gross Component Requirements
          │
          ├── (-) Available On-Hand Stock (StockBalanceCache)
          ├── (+) Existing Sales / WO Reservations
          └── (-) Pending Approved Purchase Orders (In-Transit)
          │
          ▼
Net Component Requirements
          │
          ├── If Net > 0 and Component is "BUY"   ==> Auto-Draft Purchase Order
          ├── If Net > 0 and Component is "MAKE"  ==> Sub-Assembly Production Order
          └── If Net > 0 and Component in Spoke WH==> Inter-Warehouse Transfer Order
```

---

## 5. Lot & Serial Traceability Engine

```
       [Supplier Component Lot A]      [Supplier Component Lot B]
                   │                               │
                   └───────────────┬───────────────┘
                                   │ (Material Issue via StockEngine)
                                   ▼
                    [Production Order: WO-2026-001]
                    [Operation 10: Component Assembly]
                                   │
                                   ▼ (Production Completion & Serial Gen)
                     [Finished Good: FG-SEN-100]
                     [Serial Number: SN-2026-000101]
                                   │
                                   ▼ (Dispatch via SalesService)
                      [Sales Order: SO-2026-008]
                      [Customer: Global Defense Corp]
```

---

## 6. Yield, Scrap & In-Process Quality Controls

### 6.1 Yield Accounting Equation
$$\text{Planned Quantity} = \text{Produced Good Units} + \text{Scrap Units} + \text{Rework Units} + \text{Remaining In-Progress}$$
- **Scrap Classification**:
  - `EXPECTED_SCRAP`: Standard loss budgeted in BOM line scrap factor.
  - `UNEXPECTED_SCRAP`: Machine malfunction or human defect charged to Scrap Variance Expense (Account 6000).
  - `RECOVERABLE`: Off-cuts restocked to raw material bins at salvage value.
  - `NON_RECOVERABLE`: Zero salvage value write-off.

### 6.2 Quality Inspection Gates
- **Inspection Points**: Defined on specific routing operations (e.g. Op 30 Final Inspection).
- **Inspection Disposition**:
  - `PASS`: Units received into Destination Bin as pickable unrestricted inventory.
  - `HOLD`: Units transferred to Quarantine Bin (locked against picking and allocation).
  - `REJECT`: Units transferred to Scrap Bin; inventory value written off.
  - `REWORK`: Units routed to Rework Operation sequence.

---

## 7. Costing & General Ledger (GL) Accounting Integration

```
1. Material Issue to WIP:
   Dr 1300  Work-in-Progress (WIP) Asset          ₹50,000
       Cr 1200  Raw Material Inventory Asset             ₹50,000

2. Direct Labor & Machine Overhead Absorption:
   Dr 1300  Work-in-Progress (WIP) Asset          ₹15,000
       Cr 5100  Production Overhead / Labor Absorption   ₹15,000

3. Production Completion (Finished Goods Stocking):
   Dr 1200  Finished Goods Inventory Asset        ₹65,000
       Cr 1300  Work-in-Progress (WIP) Asset             ₹65,000

4. Scrap Variance Write-Off (if unexpected scrap occurs):
   Dr 6000  Scrap Loss / Variance Expense          ₹3,000
       Cr 1300  Work-in-Progress (WIP) Asset              ₹3,000

5. Finished Goods Dispatch (Sales Delivery):
   Dr 5000  Cost of Goods Sold (COGS)             ₹65,000
       Cr 1200  Finished Goods Inventory Asset           ₹65,000
```

---

## 8. Proposed Data Models (`apps/backend/app/models/advanced_manufacturing.py`)

```python
class WorkCenter(Base, BaseModelMixin):
    __tablename__ = "work_centers"

    tenant_id = Column(String(36), nullable=False, index=True)
    code = Column(String(50), nullable=False, index=True) # WC-SMT-01
    name = Column(String(100), nullable=False)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    department = Column(String(100), nullable=True)
    hourly_labor_rate = Column(Numeric(18, 4), default=0.0, nullable=False)
    hourly_machine_rate = Column(Numeric(18, 4), default=0.0, nullable=False)
    daily_capacity_hours = Column(Numeric(8, 2), default=16.0, nullable=False)
    efficiency_factor = Column(Numeric(5, 2), default=1.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class Routing(Base, BaseModelMixin):
    __tablename__ = "routings"

    tenant_id = Column(String(36), nullable=False, index=True)
    routing_number = Column(String(50), unique=True, index=True, nullable=False) # ROUT-001
    name = Column(String(255), nullable=False)
    item_variant_id = Column(String(36), ForeignKey("item_variants.id"), nullable=False, index=True)
    version = Column(String(20), default="1.0", nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False)

class RoutingOperation(Base, BaseModelMixin):
    __tablename__ = "routing_operations"

    routing_id = Column(String(36), ForeignKey("routings.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False) # 10, 20, 30
    operation_name = Column(String(100), nullable=False)
    work_center_id = Column(String(36), ForeignKey("work_centers.id"), nullable=False)
    setup_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    run_time_minutes_per_unit = Column(Numeric(8, 2), default=1.0, nullable=False)
    queue_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    move_time_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    is_quality_gate = Column(Boolean, default=False, nullable=False)

class ProductionOrderOperation(Base, BaseModelMixin):
    __tablename__ = "production_order_operations"

    production_order_id = Column(String(36), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    operation_name = Column(String(100), nullable=False)
    work_center_id = Column(String(36), ForeignKey("work_centers.id"), nullable=False)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, RUNNING, PAUSED, COMPLETED
    assigned_operator_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actual_setup_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    actual_run_minutes = Column(Numeric(8, 2), default=0.0, nullable=False)
    actual_labor_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    actual_machine_cost = Column(Numeric(18, 4), default=0.0, nullable=False)
    completed_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    scrap_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)

class ProductionQualityInspection(Base, BaseModelMixin):
    __tablename__ = "production_quality_inspections"

    tenant_id = Column(String(36), nullable=False, index=True)
    production_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=False, index=True)
    operation_id = Column(String(36), ForeignKey("production_order_operations.id"), nullable=True)
    inspection_type = Column(String(30), nullable=False) # IN_PROCESS, FINAL
    inspector_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    inspected_quantity = Column(Numeric(18, 4), nullable=False)
    passed_quantity = Column(Numeric(18, 4), nullable=False)
    rejected_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    disposition = Column(String(30), nullable=False) # PASS, HOLD, REJECT, REWORK
    notes = Column(Text, nullable=True)
```

---

## 9. Security, RBAC & Audit Architecture

### 9.1 Fine-Grained Permissions
- `production:read`: View orders, operations, WIP, and schedule
- `production:create`: Draft new production plans and work orders
- `production:release`: Release orders, take BOM snapshots, lock component reservations
- `production:execute`: Shop-floor operation start/pause/resume/complete
- `production:complete`: Finalize production, generate serials, roll up costs to Finished Goods
- `production:cancel`: Cancel orders and return materials to stock
- `production:manage_bom`: Author and approve Bill of Materials revisions
- `production:manage_routing`: Author and maintain routings and operation sequences
- `production:manage_work_centers`: Configure work centers, rates, and shift capacities
- `production:approve_quality`: Perform quality inspections and assign dispositions

---

## 10. Verification Plan

1. **Production Order State Transitions**: Test valid progression (`DRAFT` $\to$ `PLANNED` $\to$ `RELEASED` $\to$ `MATERIAL_RESERVED` $\to$ `IN_PROGRESS` $\to$ `COMPLETED`); reject illegal skips (e.g. `PLANNED` $\to$ `COMPLETED`).
2. **Immutable BOM Snapshot**: Modify master BOM after releasing a work order $\implies$ verify in-flight production order retains original revision.
3. **Work Center Capacity Calculation**: Verify scheduled operations decrement remaining capacity hours accurately.
4. **Operation Shop-Floor Execution**: Start, pause, resume, and complete operation steps sequentially; verify predecessor Finish-to-Start constraint.
5. **Shop-Floor Concurrency Lock**: Two operators attempting to claim the same operation step $\implies$ exactly one succeeds; second operator rejected.
6. **Yield & Scrap Mathematical Consistency**: Assert $\text{Planned} = \text{Produced} + \text{Scrap} + \text{Rework} + \text{Remaining}$.
7. **Quality Gate Quarantine Isolation**: Rejected or held units move to Quarantine/Scrap bin; verify sales orders cannot allocate or pick held units.
8. **Cost Rollup & Layer Creation**: Verify materials + labor + machine + overhead roll into Finished Goods unit cost in `CostLayer`.
9. **General Ledger Reconciliation**: Verify automated JVs for Material Issue (Dr WIP/Cr Raw), Labor (Dr WIP/Cr Overhead), and Completion (Dr Finished Goods/Cr WIP) balance to ₹0 WIP.
10. **Bi-Directional Lot/Serial Traceability**: Trace finished good serial back to component lots; trace component lot forward to affected finished good serials.
11. **Multi-Company & Warehouse Isolation**: Assert Company A production cannot consume Company B inventory; Warehouse A cannot consume Warehouse B bins.
12. **Zero Unintended Stock Mutation**: Production operations only mutate explicitly staging/destination bins.
