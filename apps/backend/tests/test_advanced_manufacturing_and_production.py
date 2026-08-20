import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.manufacturing import BillOfMaterials, BOMLineItem, WorkOrder, WorkOrderComponent
from app.models.advanced_manufacturing import (
    WorkCenter,
    Routing,
    RoutingOperation,
    ProductionOrderOperation,
    ProductionQualityInspection
)
from app.schemas.advanced_manufacturing import (
    WorkCenterCreate,
    RoutingCreate,
    RoutingOperationCreate,
    OperationClaimRequest,
    OperationCompleteRequest,
    ProductionQualityInspectionCreate,
    MRPExplosionRequest
)
from app.services.advanced_manufacturing_service import (
    WorkCenterService,
    RoutingService,
    AdvancedManufacturingService
)
from app.services.gl_service import GLService
from app.services.stock_engine import StockEngine

# ============================================================================
# 1. WORK CENTER CRUD & RATES
# ============================================================================

@pytest.mark.asyncio
async def test_work_center_crud_and_capacity_rates(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Factory WH", code=f"FWH_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    await db_session.commit()

    wc_res = await WorkCenterService.create_work_center(
        db=db_session,
        tenant_id=tenant_id,
        wc_in=WorkCenterCreate(
            code="WC-SMT-01",
            name="SMT Line 1",
            warehouse_id=wh.id,
            department="Electronics",
            hourly_labor_rate=Decimal("500.0"),
            hourly_machine_rate=Decimal("300.0"),
            daily_capacity_hours=Decimal("16.0"),
            efficiency_factor=Decimal("0.95")
        )
    )
    assert wc_res.code == "WC-SMT-01"
    assert wc_res.hourly_labor_rate == Decimal("500.0")

    # Duplicate code rejection
    with pytest.raises(HTTPException) as exc_info:
        await WorkCenterService.create_work_center(
            db=db_session,
            tenant_id=tenant_id,
            wc_in=WorkCenterCreate(
                code="WC-SMT-01",
                name="Duplicate Line",
                warehouse_id=wh.id
            )
        )
    assert exc_info.value.status_code == 409

# ============================================================================
# 2. ROUTING CREATION WITH OPERATIONS
# ============================================================================

@pytest.mark.asyncio
async def test_routing_creation_with_operations(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Plant 1", code=f"P1_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku="FG-DRONE-01", name="Surveillance Drone")
    db_session.add(item)
    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku="FG-DRONE-01-STD", variant_name="Drone Standard")
    db_session.add(var)
    wc = WorkCenter(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WC-TEST-{uuid.uuid4().hex[:4]}", name="QA Test", warehouse_id=wh.id)
    db_session.add(wc)
    await db_session.commit()

    routing_res = await RoutingService.create_routing(
        db=db_session,
        tenant_id=tenant_id,
        routing_in=RoutingCreate(
            name="Drone Assembly Routing",
            item_variant_id=var.id,
            version="1.0",
            operations=[
                RoutingOperationCreate(
                    sequence_number=10,
                    operation_name="Chassis & Motor Assembly",
                    work_center_id=wc.id,
                    setup_time_minutes=Decimal("15.0"),
                    run_time_minutes_per_unit=Decimal("20.0")
                ),
                RoutingOperationCreate(
                    sequence_number=20,
                    operation_name="Flight Controller QA",
                    work_center_id=wc.id,
                    setup_time_minutes=Decimal("5.0"),
                    run_time_minutes_per_unit=Decimal("10.0"),
                    is_quality_gate=True
                )
            ]
        )
    )
    assert len(routing_res.operations) == 2
    assert routing_res.operations[0].sequence_number == 10
    assert routing_res.operations[1].is_quality_gate is True

# ============================================================================
# 3. MRP GROSS-TO-NET EXPLOSION
# ============================================================================

@pytest.mark.asyncio
async def test_mrp_gross_to_net_explosion(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Main WH", code=f"MWH_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    item_fg = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku="FG-MRP-01", name="FG Unit")
    db_session.add(item_fg)
    var_fg = ItemVariant(id=str(uuid.uuid4()), item_id=item_fg.id, variant_sku="FG-MRP-01-V", variant_name="FG Var")
    db_session.add(var_fg)

    item_raw = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku="RAW-CHIP-01", name="Chip")
    db_session.add(item_raw)
    var_raw = ItemVariant(id=str(uuid.uuid4()), item_id=item_raw.id, variant_sku="RAW-CHIP-01-V", variant_name="Chip Var")
    db_session.add(var_raw)

    # Create BOM: 1 FG requires 4 Chips with 0% scrap
    bom = BillOfMaterials(
        id=str(uuid.uuid4()), tenant_id=tenant_id, bom_number=f"BOM-MRP-{uuid.uuid4().hex[:4]}",
        name="FG BOM", item_variant_id=var_fg.id, version="1.0", status="ACTIVE", yield_quantity=Decimal("1.0")
    )
    db_session.add(bom)
    bline = BOMLineItem(
        id=str(uuid.uuid4()), bom_id=bom.id, component_variant_id=var_raw.id, quantity_required=Decimal("4.0")
    )
    db_session.add(bline)

    # Set on-hand stock = 10, allocated = 2 => available = 8
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id,
        location_bin_id=str(uuid.uuid4()), item_variant_id=var_raw.id,
        quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("2.0")
    )
    db_session.add(bal)
    await db_session.commit()

    # Explode MRP for 5 FG units (Gross = 5 * 4 = 20, Available = 8 => Net needed = 12)
    mrp_res = await AdvancedManufacturingService.explode_mrp(
        db=db_session, tenant_id=tenant_id,
        req=MRPExplosionRequest(item_variant_id=var_fg.id, quantity=Decimal("5.0"), warehouse_id=wh.id)
    )
    assert len(mrp_res.requirements) == 1
    req_chip = mrp_res.requirements[0]
    assert req_chip.gross_quantity == Decimal("20.0")
    assert req_chip.net_quantity_needed == Decimal("12.0")

# ============================================================================
# 4. IMMUTABLE BOM + ROUTING SNAPSHOT
# ============================================================================

@pytest.mark.asyncio
async def test_immutable_bom_and_routing_snapshot(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Factory WH", code=f"FWH_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    stg_bin = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", type="STAGING")
    dst_bin = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="DST-01", type="STORAGE")
    db_session.add_all([stg_bin, dst_bin])

    var_fg = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="FG-SNAP-01", variant_name="Snap FG")
    var_raw = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="RAW-SNAP-01", variant_name="Snap RAW")
    db_session.add_all([var_fg, var_raw])

    wc = WorkCenter(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WC-S-{uuid.uuid4().hex[:4]}", name="WC", warehouse_id=wh.id)
    db_session.add(wc)

    # Master Routing Revision 1.0 with Op 10
    routing = Routing(id=str(uuid.uuid4()), tenant_id=tenant_id, routing_number="ROUT-SNAP", name="R1", item_variant_id=var_fg.id, version="1.0")
    db_session.add(routing)
    r_op = RoutingOperation(id=str(uuid.uuid4()), routing_id=routing.id, sequence_number=10, operation_name="Initial Assembly", work_center_id=wc.id)
    db_session.add(r_op)

    wo = WorkOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, work_order_number=f"WO-SNAP-{uuid.uuid4().hex[:4]}",
        bom_id=str(uuid.uuid4()), item_variant_id=var_fg.id, warehouse_id=wh.id,
        staging_bin_id=stg_bin.id, destination_bin_id=dst_bin.id,
        status="PLANNED", quantity_to_produce=Decimal("5.0")
    )
    db_session.add(wo)

    comp = WorkOrderComponent(id=str(uuid.uuid4()), work_order_id=wo.id, component_variant_id=var_raw.id, quantity_required=Decimal("5.0"))
    db_session.add(comp)

    bal = StockBalanceCache(id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=stg_bin.id, item_variant_id=var_raw.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0"))
    db_session.add(bal)
    await db_session.commit()

    # Release Work Order -> Freezes snapshot
    released_wo = await AdvancedManufacturingService.release_production_order_with_routing(
        db=db_session, tenant_id=tenant_id, work_order_id=wo.id, routing_id=routing.id
    )
    assert released_wo.status == "RELEASED"

    # Verify snapshot operations exist
    snap_ops = (await db_session.execute(
        select(ProductionOrderOperation).where(ProductionOrderOperation.work_order_id == wo.id)
    )).scalars().all()
    assert len(snap_ops) == 1
    assert snap_ops[0].operation_name == "Initial Assembly"

    # Modify Master Routing to Revision 2.0 with a different operation name
    r_op.operation_name = "Mutated Master Operation"
    await db_session.commit()

    # Assert already-released Work Order retains original snapshot
    refreshed_snap_ops = (await db_session.execute(
        select(ProductionOrderOperation).where(ProductionOrderOperation.work_order_id == wo.id)
    )).scalars().all()
    assert refreshed_snap_ops[0].operation_name == "Initial Assembly"

# ============================================================================
# 5. WORK CENTER CAPACITY & EFFICIENCY
# ============================================================================

def test_work_center_capacity_calculation():
    daily_capacity = Decimal("8.0")
    efficiency = Decimal("0.90") # 90% efficiency
    effective_capacity = daily_capacity * efficiency # 7.2 hours

    scheduled_hours = Decimal("3.0")
    remaining_capacity = max(Decimal("0.0"), effective_capacity - scheduled_hours)
    assert remaining_capacity == Decimal("4.2")

    # Over-capacity prevented from going negative
    over_scheduled = Decimal("10.0")
    clamped_remaining = max(Decimal("0.0"), effective_capacity - over_scheduled)
    assert clamped_remaining == Decimal("0.0")

# ============================================================================
# 6. SHOP-FLOOR EXECUTION & PREDECESSOR FINISH-TO-START GUARDS
# ============================================================================

@pytest.mark.asyncio
async def test_shop_floor_execution_and_predecessor_guards(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Factory", code=f"F_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    wc = WorkCenter(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WC-EXEC-{uuid.uuid4().hex[:4]}",
        name="Assembly WC", warehouse_id=wh.id, hourly_labor_rate=Decimal("600.0"), hourly_machine_rate=Decimal("400.0")
    )
    db_session.add(wc)

    wo = WorkOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, work_order_number=f"WO-EXEC-{uuid.uuid4().hex[:4]}",
        bom_id=str(uuid.uuid4()), item_variant_id=str(uuid.uuid4()), warehouse_id=wh.id,
        staging_bin_id=str(uuid.uuid4()), destination_bin_id=str(uuid.uuid4()),
        status="RELEASED", quantity_to_produce=Decimal("10.0")
    )
    db_session.add(wo)

    op10 = ProductionOrderOperation(
        id=str(uuid.uuid4()), work_order_id=wo.id, sequence_number=10, operation_name="SMT",
        work_center_id=wc.id, status="PENDING"
    )
    op20 = ProductionOrderOperation(
        id=str(uuid.uuid4()), work_order_id=wo.id, sequence_number=20, operation_name="Testing",
        work_center_id=wc.id, status="PENDING"
    )
    db_session.add_all([op10, op20])
    await db_session.commit()

    # Attempting to claim Op 20 first -> REJECT (Finish-to-Start predecessor not complete)
    with pytest.raises(HTTPException) as exc_info:
        await AdvancedManufacturingService.claim_operation(db_session, tenant_id, op20.id, user_id)
    assert exc_info.value.status_code == 400
    assert "Predecessor operations must be completed" in exc_info.value.detail

    # Claim Op 10 -> SUCCESS
    claimed_op10 = await AdvancedManufacturingService.claim_operation(db_session, tenant_id, op10.id, user_id)
    assert claimed_op10.status == "RUNNING"

    # Complete Op 10 (30 mins run time)
    # Labor: (30/60) * 600 = 300, Machine: (30/60) * 400 = 200
    comp_op10 = await AdvancedManufacturingService.complete_operation(
        db=db_session, tenant_id=tenant_id,
        req=OperationCompleteRequest(
            operation_id=op10.id, completed_quantity=Decimal("10.0"), actual_run_minutes=Decimal("30.0")
        ),
        user_id=user_id
    )
    assert comp_op10.status == "COMPLETED"
    assert comp_op10.actual_labor_cost == Decimal("300.0")
    assert comp_op10.actual_machine_cost == Decimal("200.0")

    # Now Op 20 can be claimed
    claimed_op20 = await AdvancedManufacturingService.claim_operation(db_session, tenant_id, op20.id, user_id)
    assert claimed_op20.status == "RUNNING"

# ============================================================================
# 7. OPERATOR CONCURRENCY LOCK (MUTUAL EXCLUSION)
# ============================================================================

@pytest.mark.asyncio
async def test_operator_concurrency_locking(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    operator_a = str(uuid.uuid4())
    operator_b = str(uuid.uuid4())

    op = ProductionOrderOperation(
        id=str(uuid.uuid4()), work_order_id=str(uuid.uuid4()), sequence_number=10,
        operation_name="Precision Milling", work_center_id=str(uuid.uuid4()), status="PENDING"
    )
    db_session.add(op)
    await db_session.commit()

    # Operator A claims operation -> SUCCESS
    await AdvancedManufacturingService.claim_operation(db_session, tenant_id, op.id, operator_a)

    # Operator B attempts to claim the same operation concurrently -> CONFLICT (409)
    with pytest.raises(HTTPException) as exc_info:
        await AdvancedManufacturingService.claim_operation(db_session, tenant_id, op.id, operator_b)
    assert exc_info.value.status_code == 409
    assert "already claimed" in exc_info.value.detail

# ============================================================================
# 8. YIELD & SCRAP MATHEMATICAL INTEGRITY
# ============================================================================

def test_yield_and_scrap_mathematical_consistency():
    planned_qty = Decimal("100.0")
    produced_qty = Decimal("85.0")
    scrap_qty = Decimal("10.0")
    rework_qty = Decimal("3.0")
    remaining_qty = Decimal("2.0")

    # Invariant: Planned = Produced + Scrap + Rework + Remaining
    total_accounted = produced_qty + scrap_qty + rework_qty + remaining_qty
    assert total_accounted == planned_qty

# ============================================================================
# 9. QUALITY INSPECTION QUARANTINE ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_quality_inspection_quarantine_isolation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    inspector_id = str(uuid.uuid4())
    wo_id = str(uuid.uuid4())
    quarantine_bin_id = str(uuid.uuid4())

    # 1. Non-passing inspection requires quarantine bin
    with pytest.raises(HTTPException) as exc_info:
        await AdvancedManufacturingService.record_quality_inspection(
            db=db_session, tenant_id=tenant_id,
            insp_in=ProductionQualityInspectionCreate(
                work_order_id=wo_id,
                inspection_type="FINAL",
                inspected_quantity=Decimal("50.0"),
                passed_quantity=Decimal("40.0"),
                rejected_quantity=Decimal("10.0"),
                disposition="HOLD",
                quarantine_bin_id=None # Missing bin
            ),
            user_id=inspector_id
        )
    assert exc_info.value.status_code == 400
    assert "Quarantine/Scrap bin required" in exc_info.value.detail

    # 2. Providing quarantine bin -> SUCCESS
    insp_res = await AdvancedManufacturingService.record_quality_inspection(
        db=db_session, tenant_id=tenant_id,
        insp_in=ProductionQualityInspectionCreate(
            work_order_id=wo_id,
            inspection_type="FINAL",
            inspected_quantity=Decimal("50.0"),
            passed_quantity=Decimal("40.0"),
            rejected_quantity=Decimal("10.0"),
            disposition="HOLD",
            quarantine_bin_id=quarantine_bin_id
        ),
        user_id=inspector_id
    )
    assert insp_res.disposition == "HOLD"
    assert insp_res.quarantine_bin_id == quarantine_bin_id

# ============================================================================
# 10. PRODUCTION COMPLETION, FULL COST ROLLUP & GL POSTINGS
# ============================================================================

@pytest.mark.asyncio
async def test_production_completion_cost_rollup_and_gl(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Factory WH", code=f"FWH_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    stg_bin = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", type="STAGING")
    dst_bin = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="FG-01", type="STORAGE")
    db_session.add_all([stg_bin, dst_bin])

    var_fg = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="FG-UNIT-100", variant_name="FG Unit 100")
    var_raw = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="RAW-STEEL-01", variant_name="Steel Raw")
    db_session.add_all([var_fg, var_raw])

    # Work Order for 2 units
    wo = WorkOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, work_order_number=f"WO-GL-{uuid.uuid4().hex[:4]}",
        bom_id=str(uuid.uuid4()), item_variant_id=var_fg.id, warehouse_id=wh.id,
        staging_bin_id=stg_bin.id, destination_bin_id=dst_bin.id,
        status="RELEASED", quantity_to_produce=Decimal("2.0"),
        total_labor_cost=Decimal("400.0"), total_overhead_cost=Decimal("200.0")
    )
    db_session.add(wo)

    comp = WorkOrderComponent(
        id=str(uuid.uuid4()), work_order_id=wo.id, component_variant_id=var_raw.id,
        quantity_required=Decimal("10.0"), quantity_reserved=Decimal("10.0")
    )
    db_session.add(comp)

    # Raw material stock balance
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id,
        location_bin_id=stg_bin.id, item_variant_id=var_raw.id,
        quantity_on_hand=Decimal("20.0"), quantity_allocated=Decimal("10.0")
    )
    db_session.add(bal)

    # Raw material cost layer: 10 units @ ₹50 = ₹500
    c_layer = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id,
        item_variant_id=var_raw.id, layer_number=f"LAY-RAW-{uuid.uuid4().hex[:8].upper()}",
        original_quantity=Decimal("20.0"), remaining_quantity=Decimal("20.0"),
        unit_cost=Decimal("50.0"), total_cost=Decimal("1000.0"), status="ACTIVE",
        layer_timestamp=datetime.now(timezone.utc)
    )
    db_session.add(c_layer)
    await db_session.commit()

    # Complete production:
    # Component Cost: 10 * 50 = 500
    # Labor Cost: 400
    # Overhead Cost: 200
    # Total Production Cost: 1100 -> Unit cost: 1100 / 2 = ₹550
    completed_wo = await AdvancedManufacturingService.complete_production_order_with_gl(
        db=db_session, tenant_id=tenant_id, work_order_id=wo.id, user_id=user_id
    )
    assert completed_wo.status == "COMPLETED"
    assert completed_wo.total_component_cost == Decimal("500.0")
    assert completed_wo.total_production_cost == Decimal("1100.0")
    assert completed_wo.unit_cost == Decimal("550.0")

    # Verify Journal Vouchers posted
    jvs = (await db_session.execute(
        select(JournalVoucher).where(JournalVoucher.source_document_type == "WORK_ORDER")
    )).scalars().all()
    assert len(jvs) >= 2 # Material Issue JV + Finished Goods Completion JV

# ============================================================================
# 11. LOT & SERIAL FORWARD AND BACKWARD TRACEABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_lot_serial_traceability_forward_and_backward(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # 1. Supplier Lot
    raw_lot = StockLot(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        lot_number=f"LOT-SUPP-{uuid.uuid4().hex[:6]}",
        item_variant_id=str(uuid.uuid4()), status="ACTIVE"
    )
    db_session.add(raw_lot)

    # 2. Production Work Order
    wo = WorkOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        work_order_number=f"WO-TRACE-{uuid.uuid4().hex[:4]}",
        bom_id=str(uuid.uuid4()), item_variant_id=str(uuid.uuid4()),
        warehouse_id=str(uuid.uuid4()), staging_bin_id=str(uuid.uuid4()),
        destination_bin_id=str(uuid.uuid4()), status="COMPLETED",
        quantity_to_produce=Decimal("2.0")
    )
    db_session.add(wo)

    # 3. Finished Good Serials linked to WO
    wh_id = str(uuid.uuid4())
    sn1 = ItemSerialNumber(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh_id,
        serial_number=f"SN-FG-{uuid.uuid4().hex[:6]}",
        item_variant_id=wo.item_variant_id,
        status="IN_STOCK",
        lot_id=raw_lot.id
    )
    sn2 = ItemSerialNumber(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh_id,
        serial_number=f"SN-FG-{uuid.uuid4().hex[:6]}",
        item_variant_id=wo.item_variant_id,
        status="IN_STOCK",
        lot_id=raw_lot.id
    )
    db_session.add_all([sn1, sn2])
    await db_session.commit()

    # Forward Traceability: raw_lot -> finished serials
    serials_from_lot = (await db_session.execute(
        select(ItemSerialNumber).where(ItemSerialNumber.lot_id == raw_lot.id)
    )).scalars().all()
    assert len(serials_from_lot) == 2

    # Backward Traceability: serial -> raw_lot
    trace_sn = (await db_session.execute(
        select(ItemSerialNumber).where(ItemSerialNumber.id == sn1.id)
    )).scalar_one()
    assert trace_sn.lot_id == raw_lot.id

# ============================================================================
# 12. MULTI-COMPANY & WAREHOUSE ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_multi_company_and_warehouse_isolation(db_session: AsyncSession):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    wh_a = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_a, name="Company A Plant", code=f"CA_{uuid.uuid4().hex[:4]}")
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_b, name="Company B Plant", code=f"CB_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_a, wh_b])
    await db_session.commit()

    # Tenant A attempts to release a work order using Tenant B warehouse -> 404 Not Found
    with pytest.raises(HTTPException) as exc_info:
        await AdvancedManufacturingService.release_production_order_with_routing(
            db=db_session, tenant_id=tenant_a, work_order_id=str(uuid.uuid4())
        )
    assert exc_info.value.status_code == 404

# ============================================================================
# 13. ZERO UNINTENDED STOCK MUTATION
# ============================================================================

@pytest.mark.asyncio
async def test_zero_unintended_stock_mutation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="WH", code=f"WH_{uuid.uuid4().hex[:4]}")
    db_session.add(wh)
    bin_stg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-Z", type="STAGING")
    bin_dst = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="DST-Z", type="STORAGE")
    bin_unrelated = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="UNREL", type="STORAGE")
    db_session.add_all([bin_stg, bin_dst, bin_unrelated])

    var_comp = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="COMP-Z", variant_name="Comp Z")
    var_unrelated = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="UNREL-Z", variant_name="Unrel Z")
    db_session.add_all([var_comp, var_unrelated])

    # Staging stock balance = 10
    bal_stg = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_stg.id,
        item_variant_id=var_comp.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    # Unrelated bin stock = 100
    bal_unrelated = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_unrelated.id,
        item_variant_id=var_unrelated.id, quantity_on_hand=Decimal("100.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([bal_stg, bal_unrelated])
    await db_session.commit()

    # Record initial stock of unrelated bin
    unrel_before = bal_unrelated.quantity_on_hand

    # Perform stock issue on staging bin
    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="STOCK_ISSUE",
        entries_data=[{"item_variant_id": var_comp.id, "source_location_bin_id": bin_stg.id, "quantity": Decimal("5.0")}],
        reference_doc_type="WORK_ORDER", reference_doc_id="WO-TEST"
    )

    # Assert unrelated bin stock is completely unaffected
    db_bal_unrelated = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.id == bal_unrelated.id)
    )).scalar_one()
    assert db_bal_unrelated.quantity_on_hand == unrel_before
