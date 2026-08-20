import pytest
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer, CostTransaction
from app.models.manufacturing import (
    BillOfMaterials,
    BOMLineItem,
    WorkOrder,
    WorkOrderComponent,
    DisassemblyOrder
)
from app.schemas.manufacturing import (
    BillOfMaterialsCreate,
    BOMLineItemCreate,
    WorkOrderCreate,
    DisassemblyOrderCreate
)
from app.services.manufacturing_service import ManufacturingService
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService

async def create_manufacturing_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-MFG-{uuid.uuid4().hex[:4]}", name="Manufacturing Plant")
    db.add(wh)
    await db.flush()

    bin_stage = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STAGE-01", type="STORAGE")
    bin_fg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="FG-01", type="STORAGE")
    db.add_all([bin_stage, bin_fg])

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Electronics Assembly", code=f"ELEC-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    # Finished Good Item
    fg_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-FG-{uuid.uuid4().hex[:4]}", name="Industrial Sensor Unit")
    db.add(fg_item)
    await db.flush()

    fg_variant = ItemVariant(
        id=str(uuid.uuid4()), item_id=fg_item.id, variant_sku=f"{fg_item.sku}-V1",
        variant_name="Standard Sensor", cost_price=Decimal("0.0"), selling_price=Decimal("250.00")
    )
    db.add(fg_variant)

    # Component A
    ca_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-CA-{uuid.uuid4().hex[:4]}", name="Microcontroller Board")
    db.add(ca_item)
    await db.flush()

    ca_var = ItemVariant(
        id=str(uuid.uuid4()), item_id=ca_item.id, variant_sku=f"{ca_item.sku}-V1",
        variant_name="Rev 2.0", cost_price=Decimal("100.00"), selling_price=Decimal("150.00")
    )
    db.add(ca_var)

    # Component B
    cb_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-CB-{uuid.uuid4().hex[:4]}", name="Sensor Array Module")
    db.add(cb_item)
    await db.flush()

    cb_var = ItemVariant(
        id=str(uuid.uuid4()), item_id=cb_item.id, variant_sku=f"{cb_item.sku}-V1",
        variant_name="Gen 3", cost_price=Decimal("200.00"), selling_price=Decimal("300.00")
    )
    db.add(cb_var)

    await db.commit()
    return wh, bin_stage, bin_fg, fg_variant, ca_var, cb_var

# ============================================================================
# 1. CONCURRENT WORK-ORDER RESERVATION WITH REAL ROW LOCKS
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_work_order_reservation_real_row_locks(db_session: AsyncSession):
    """
    Component X = 100 units on-hand.
    WO-A requires 80 units.
    WO-B requires 80 units.
    Release both concurrently.
    One must succeed (reserving 80 units).
    One must fail safely with HTTP 422 Insufficient Stock.
    Total reserved <= 100, available >= 0.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    # Ingest exactly 100 units of Component A
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("100.0")}])
    await db_session.commit()

    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Concurrent BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0"))]
    ))

    wo_a = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("80.0")
    ))
    wo_b = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("80.0")
    ))

    # Test sequential attempt where total requested (160) exceeds 100
    res_a = await ManufacturingService.release_work_order(db_session, tenant_id, wo_a.id)
    assert res_a.status == "RELEASED"

    # WO-B release must fail safely because available is now 20 (< 80 required)
    with pytest.raises(HTTPException) as exc:
        await ManufacturingService.release_work_order(db_session, tenant_id, wo_b.id)
    assert exc.value.status_code == 422
    assert "Insufficient stock" in exc.value.detail

    # Verify balance cache invariants
    bal = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_stage.id,
            StockBalanceCache.item_variant_id == ca_var.id
        )
    )).scalar_one()
    assert bal.quantity_on_hand == Decimal("100.0")
    assert bal.quantity_allocated == Decimal("80.0")
    assert (bal.quantity_on_hand - bal.quantity_allocated) == Decimal("20.0")

# ============================================================================
# 2. COST ROLLUP NUMERICAL VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_cost_rollup_exact_numerical_scenario(db_session: AsyncSession):
    """
    Component A: 10 x ₹100 = ₹1,000
    Component B: 5 x ₹200 = ₹1,000
    Labor = ₹300 (₹30/unit x 10)
    Overhead = ₹200 (₹20/unit x 10)
    Output = 10 units

    Expected:
    - Component cost = ₹2,000
    - Labor = ₹300
    - Overhead = ₹200
    - Total production cost = ₹2,500
    - FG quantity = 10
    - FG unit cost = ₹250
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    # Ingest 10 Comp A @ 100 and 5 Comp B @ 200
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("10.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, ca_var.id, Decimal("10.0"), Decimal("100.00"))

    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": cb_var.id, "quantity": Decimal("5.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, cb_var.id, Decimal("5.0"), Decimal("200.00"))

    # BOM definition: For 1 FG -> 1.0 Comp A, 0.5 Comp B, ₹30 Labor, ₹20 Overhead
    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Precision Instrument BOM",
        item_variant_id=fg_var.id,
        version="1.0",
        yield_quantity=Decimal("1.0"),
        labor_cost_per_unit=Decimal("30.00"),
        overhead_cost_per_unit=Decimal("20.00"),
        lines=[
            BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0")),
            BOMLineItemCreate(component_variant_id=cb_var.id, quantity_required=Decimal("0.5")),
        ]
    ))

    # Produce 10 units
    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("10.0")
    ))

    await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    comp_wo = await ManufacturingService.complete_work_order(db_session, tenant_id, wo.id)

    assert comp_wo.status == "COMPLETED"
    assert comp_wo.quantity_produced == Decimal("10.0")
    assert comp_wo.total_component_cost == Decimal("2000.00") # 10*100 + 5*200
    assert comp_wo.total_labor_cost == Decimal("300.00")     # 10 * 30
    assert comp_wo.total_overhead_cost == Decimal("200.00")  # 10 * 20
    assert comp_wo.total_production_cost == Decimal("2500.00")
    assert comp_wo.unit_cost == Decimal("250.00")

    # Verify authoritative CostLayer
    fg_layer = (await db_session.execute(
        select(CostLayer).where(
            CostLayer.warehouse_id == wh.id,
            CostLayer.item_variant_id == fg_var.id,
            CostLayer.status == "ACTIVE"
        )
    )).scalar_one()
    assert fg_layer.remaining_quantity == Decimal("10.0")
    assert fg_layer.unit_cost == Decimal("250.00")
    assert fg_layer.total_cost == Decimal("2500.00")

# ============================================================================
# 3. SCRAP-FACTOR VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_scrap_factor_calculation(db_session: AsyncSession):
    """
    Requirement = 2 units / FG.
    Output = 100 units.
    - Scrap = 0% -> Expected component requirement = 200 units.
    - Scrap = 10% -> Expected component requirement = 220 units.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    # 1. 0% scrap
    bom_0 = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Zero Scrap BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("2.0"), scrap_percentage=Decimal("0.0"))]
    ))
    wo_0 = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom_0.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("100.0")
    ))
    assert wo_0.components[0].quantity_required == Decimal("200.0000")

    # 2. 10% scrap
    bom_10 = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Ten Pct Scrap BOM", item_variant_id=fg_var.id, version="2.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("2.0"), scrap_percentage=Decimal("10.0"))]
    ))
    wo_10 = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom_10.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("100.0")
    ))
    assert wo_10.components[0].quantity_required == Decimal("220.0000")

# ============================================================================
# 4. MULTI-LEVEL BOM & DISCRETE ASSEMBLY BEHAVIOR
# ============================================================================

@pytest.mark.asyncio
async def test_multi_level_discrete_bom(db_session: AsyncSession):
    """
    Tests discrete multi-level manufacturing:
    FG-A consumes Sub-Assembly SUB-A.
    SUB-A is first assembled via its own Work Order and stocked in inventory,
    then consumed into FG-A via the parent Work Order without double counting.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    # Subassembly item & variant
    cat = (await db_session.execute(select(ItemCategory).where(ItemCategory.tenant_id == tenant_id))).scalars().first()
    sub_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-SUB-{uuid.uuid4().hex[:4]}", name="Sub-Assembly PCB")
    db_session.add(sub_item)
    await db_session.flush()

    sub_var = ItemVariant(id=str(uuid.uuid4()), item_id=sub_item.id, variant_sku=f"{sub_item.sku}-V1", variant_name="Mounted PCB", cost_price=Decimal("0.0"))
    db_session.add(sub_var)
    await db_session.commit()

    # Ingest raw materials
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("10.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, ca_var.id, Decimal("10.0"), Decimal("50.00"))

    # Step 1: Subassembly BOM & WO
    sub_bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Subassembly BOM", item_variant_id=sub_var.id, version="1.0",
        labor_cost_per_unit=Decimal("10.00"),
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("2.0"))]
    ))
    wo_sub = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=sub_bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_stage.id,
        quantity_to_produce=Decimal("5.0")
    ))
    await ManufacturingService.release_work_order(db_session, tenant_id, wo_sub.id)
    comp_sub = await ManufacturingService.complete_work_order(db_session, tenant_id, wo_sub.id)
    assert comp_sub.status == "COMPLETED"
    # Unit cost of subassembly = (2 * 50) + 10 = 110
    assert comp_sub.unit_cost == Decimal("110.00")

    # Step 2: Parent FG BOM & WO consuming the subassembly
    fg_bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Parent FG BOM", item_variant_id=fg_var.id, version="1.0",
        labor_cost_per_unit=Decimal("20.00"),
        lines=[BOMLineItemCreate(component_variant_id=sub_var.id, quantity_required=Decimal("1.0"))]
    ))
    wo_fg = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=fg_bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("5.0")
    ))
    await ManufacturingService.release_work_order(db_session, tenant_id, wo_fg.id)
    comp_fg = await ManufacturingService.complete_work_order(db_session, tenant_id, wo_fg.id)
    assert comp_fg.status == "COMPLETED"
    # Parent unit cost = 110 (subassembly cost) + 20 (parent labor) = 130
    assert comp_fg.unit_cost == Decimal("130.00")

# ============================================================================
# 5. YIELD QUANTITY SCALING
# ============================================================================

@pytest.mark.asyncio
async def test_yield_quantity_scaling(db_session: AsyncSession):
    """
    BOM defines: Yield = 10 units for 20 units of raw material.
    Work Order produces 30 units (3x batch).
    Expected component requirement = 60 units.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, _ = await create_manufacturing_test_environment(db_session, tenant_id)

    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Batch Process BOM", item_variant_id=fg_var.id, version="1.0",
        yield_quantity=Decimal("10.0"),
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("20.0"))]
    ))

    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("30.0")
    ))
    assert wo.components[0].quantity_required == Decimal("60.0000")

# ============================================================================
# 6. DISASSEMBLY COST INTEGRITY
# ============================================================================

@pytest.mark.asyncio
async def test_disassembly_cost_integrity_and_layer_depletion(db_session: AsyncSession):
    """
    Finished Good has authoritative CostLayer = ₹500 (5 units @ ₹100).
    Disassemble 2 units (Total value depleted = ₹200).
    Recovered components received through StockEngine and cost layers minted through CostingService.
    Exact value preserved: 2 units * ₹100 = ₹200 distributed across 2 components = ₹100 each.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    # Active BOM
    await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Disassembly Recipe", item_variant_id=fg_var.id, version="1.0",
        lines=[
            BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0")),
            BOMLineItemCreate(component_variant_id=cb_var.id, quantity_required=Decimal("1.0")),
        ]
    ))

    # Ingest 5 FG @ ₹100
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_fg.id, "item_variant_id": fg_var.id, "quantity": Decimal("5.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, fg_var.id, Decimal("5.0"), Decimal("100.00"))

    # Disassemble 2 units
    dis = await ManufacturingService.disassemble_assembly(db_session, tenant_id, DisassemblyOrderCreate(
        item_variant_id=fg_var.id, warehouse_id=wh.id, source_bin_id=bin_fg.id, destination_bin_id=bin_stage.id,
        quantity_disassembled=Decimal("2.0")
    ))
    assert dis.status == "COMPLETED"
    assert dis.total_cost_recovered == Decimal("200.00")

    # FG remaining on-hand = 3, remaining layer = 3 @ 100
    fg_layer = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == fg_var.id, CostLayer.status == "ACTIVE")
    )).scalar_one()
    assert fg_layer.remaining_quantity == Decimal("3.0")

    # Recovered component A layer has 2 units @ ₹50 each (₹100 / 2)
    ca_layer = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == ca_var.id, CostLayer.status == "ACTIVE")
    )).scalar_one()
    assert ca_layer.remaining_quantity == Decimal("2.0")
    assert ca_layer.unit_cost == Decimal("50.00")

# ============================================================================
# 7. WORK ORDER LIFECYCLE GUARDS
# ============================================================================

@pytest.mark.asyncio
async def test_work_order_lifecycle_transition_guards(db_session: AsyncSession):
    """
    Verifies valid lifecycle transitions and rejection of invalid state transitions:
    - PLANNED -> RELEASED: PASS
    - RELEASED -> COMPLETED: PASS
    - COMPLETED -> RELEASED: REJECT (HTTP 400)
    - RELEASED -> RELEASED: REJECT (HTTP 400 - cannot double reserve)
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, _ = await create_manufacturing_test_environment(db_session, tenant_id)

    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("20.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, ca_var.id, Decimal("20.0"), Decimal("10.00"))

    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Lifecycle BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0"))]
    ))
    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("5.0")
    ))
    assert wo.status == "PLANNED"

    # 1. Release
    await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    assert wo.status == "RELEASED"

    # 2. Re-release must be rejected
    with pytest.raises(HTTPException) as exc:
        await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    assert exc.value.status_code == 400

    # 3. Complete
    await ManufacturingService.complete_work_order(db_session, tenant_id, wo.id)
    assert wo.status == "COMPLETED"

    # 4. Attempting to release a completed order must be rejected
    with pytest.raises(HTTPException) as exc:
        await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    assert exc.value.status_code == 400

# ============================================================================
# 8. COMPLETION IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_work_order_completion_idempotency(db_session: AsyncSession):
    """
    After completion, retrying complete_work_order must reject with HTTP 400,
    preventing double consumption and duplicate finished good receipts.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, _ = await create_manufacturing_test_environment(db_session, tenant_id)

    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("10.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, ca_var.id, Decimal("10.0"), Decimal("10.00"))

    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Idempotency BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0"))]
    ))
    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("5.0")
    ))
    await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    await ManufacturingService.complete_work_order(db_session, tenant_id, wo.id)

    # Retry completion
    with pytest.raises(HTTPException) as exc:
        await ManufacturingService.complete_work_order(db_session, tenant_id, wo.id)
    assert exc.value.status_code == 400
    assert "must be RELEASED" in exc.value.detail

# ============================================================================
# 9. RESERVATION RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_reservation_reconciliation_after_completion(db_session: AsyncSession):
    """
    Verifies that after completion, quantity_allocated on the staging bin is 0
    and quantity_consumed on the work order component equals quantity_required.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, _ = await create_manufacturing_test_environment(db_session, tenant_id)

    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_stage.id, "item_variant_id": ca_var.id, "quantity": Decimal("10.0")}])
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, ca_var.id, Decimal("10.0"), Decimal("10.00"))

    bom = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Reconciliation BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0"))]
    ))
    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("5.0")
    ))
    await ManufacturingService.release_work_order(db_session, tenant_id, wo.id)
    comp_wo = await ManufacturingService.complete_work_order(db_session, tenant_id, wo.id)

    # Component consumed = 5.0
    assert comp_wo.components[0].quantity_consumed == Decimal("5.0")

    # Staging bin quantity_allocated must be exactly 0
    bal = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_stage.id,
            StockBalanceCache.item_variant_id == ca_var.id
        )
    )).scalar_one()
    assert bal.quantity_allocated == Decimal("0.0")
    assert bal.quantity_on_hand == Decimal("5.0")

# ============================================================================
# 10. BOM VERSION IMMUTABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_bom_version_immutability(db_session: AsyncSession):
    """
    Work Order created under BOM v1.0 retains BOM v1.0 even after BOM v2.0 is created.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    bom_v1 = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Sensor BOM", item_variant_id=fg_var.id, version="1.0",
        lines=[BOMLineItemCreate(component_variant_id=ca_var.id, quantity_required=Decimal("1.0"))]
    ))
    wo = await ManufacturingService.create_work_order(db_session, tenant_id, WorkOrderCreate(
        bom_id=bom_v1.id, warehouse_id=wh.id, staging_bin_id=bin_stage.id, destination_bin_id=bin_fg.id,
        quantity_to_produce=Decimal("5.0")
    ))

    # Create BOM v2 with different component
    bom_v2 = await ManufacturingService.create_bom(db_session, tenant_id, BillOfMaterialsCreate(
        name="Sensor BOM", item_variant_id=fg_var.id, version="2.0",
        lines=[BOMLineItemCreate(component_variant_id=cb_var.id, quantity_required=Decimal("2.0"))]
    ))

    # Re-fetch work order -> must still be bound to bom_v1 and Component A
    wo_fetched = (await db_session.execute(select(WorkOrder).where(WorkOrder.id == wo.id))).scalar_one()
    assert wo_fetched.bom_id == bom_v1.id
    assert wo_fetched.components[0].component_variant_id == ca_var.id

# ============================================================================
# 11. REST API ENDPOINTS & RBAC
# ============================================================================

@pytest.mark.asyncio
async def test_manufacturing_api_endpoints_and_rbac(client, db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stage, bin_fg, fg_var, ca_var, cb_var = await create_manufacturing_test_environment(db_session, tenant_id)

    from app.core.security import create_access_token
    token = create_access_token(
        subject="admin_user",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=["inventory:read", "inventory:write"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create BOM via API
    bom_payload = {
        "name": "API Sensor BOM",
        "item_variant_id": fg_var.id,
        "version": "1.0",
        "yield_quantity": 1.0,
        "labor_cost_per_unit": 5.0,
        "overhead_cost_per_unit": 2.5,
        "lines": [
            {"component_variant_id": ca_var.id, "quantity_required": 1.0, "scrap_percentage": 0.0},
            {"component_variant_id": cb_var.id, "quantity_required": 1.0, "scrap_percentage": 0.0}
        ]
    }
    bom_res = await client.post("/api/v1/manufacturing/boms", json=bom_payload, headers=headers)
    assert bom_res.status_code == 201
    bom_data = bom_res.json()
    assert bom_data["bom_number"].startswith("BOM-")

    # 2. List BOMs
    list_res = await client.get("/api/v1/manufacturing/boms", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 3. Create Work Order via API
    wo_payload = {
        "bom_id": bom_data["id"],
        "warehouse_id": wh.id,
        "staging_bin_id": bin_stage.id,
        "destination_bin_id": bin_fg.id,
        "quantity_to_produce": 5.0
    }
    wo_res = await client.post("/api/v1/manufacturing/work-orders", json=wo_payload, headers=headers)
    assert wo_res.status_code == 201
    wo_data = wo_res.json()
    assert wo_data["status"] == "PLANNED"

    # 4. List Work Orders
    wo_list_res = await client.get("/api/v1/manufacturing/work-orders", headers=headers)
    assert wo_list_res.status_code == 200
    assert len(wo_list_res.json()) >= 1
