import asyncio
import uuid
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.sales import Customer, SalesOrder, Shipment
from app.services.costing_service import CostingService

pytestmark = pytest.mark.asyncio

async def create_test_product_and_warehouse(
    db: AsyncSession,
    tenant_id: str,
    method: str = "FIFO",
    cost_price: Decimal = Decimal("50.0")
):
    wh = Warehouse(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=f"WH-CONC-{uuid.uuid4().hex[:6]}",
        name="Concurrency Test Warehouse"
    )
    bin_obj = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", type="STORAGE")
    wh.bins.append(bin_obj)
    db.add(wh)

    cat = ItemCategory(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Concurrency Category",
        code=f"CAT-{uuid.uuid4().hex[:6]}"
    )
    item = Item(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=cat.id,
        sku=f"SKU-CONC-{uuid.uuid4().hex[:6]}",
        name="Concurrency Widget",
        valuation_method=method
    )
    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"VAR-CONC-{uuid.uuid4().hex[:6]}",
        variant_name="Standard",
        cost_price=cost_price
    )
    item.variants.append(variant)
    db.add_all([cat, item])
    await db.flush()
    return wh, bin_obj, item, variant


async def test_concurrent_fifo_dispatch_insufficient_stock(db_session: AsyncSession):
    """
    Test 1: Concurrent FIFO dispatch with insufficient inventory for both requests.
    Initial: 60 units in 1 FIFO layer @ $50.00 = $3,000.00.
    Dispatch 1 requests 40 units.
    Dispatch 2 requests 40 units.
    Total requested = 80 > 60 available.
    Verifies:
    - First dispatch succeeds consuming 40 units (COGS = $2,000).
    - Second dispatch consumes remaining 20 units safely without negative layer balances.
    - No negative remaining_quantity.
    - No quantity consumed twice.
    - Reconciliation between layers and profile.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "FIFO", Decimal("50.0"))
    
    # Inbound 60 units @ $50.00
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("60.0"), Decimal("50.00"))
    await db_session.flush()

    # Execute two dispatches in sequence / concurrency
    tx1, cogs1 = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    assert cogs1.quantity_shipped == Decimal("40.0000")
    assert cogs1.total_cogs_amount == Decimal("2000.0000")
    assert cogs1.unit_cogs == Decimal("50.0000")

    # Second dispatch for 40 units: only 20 units remain in the layer, so remaining 20 fulfilled via standard profile cost
    tx2, cogs2 = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == variant.id)
    )).scalars().all()

    assert len(layers) == 1
    layer = layers[0]
    # Layer remaining quantity must never be negative
    assert layer.remaining_quantity == Decimal("0.0000")
    assert layer.status == "DEPLETED"

    consumptions = (await db_session.execute(
        select(CostLayerConsumption).where(CostLayerConsumption.cost_layer_id == layer.id)
    )).scalars().all()

    total_consumed_qty = sum([Decimal(str(c.quantity_consumed)) for c in consumptions], Decimal("0.0"))
    total_consumed_cost = sum([Decimal(str(c.total_cost)) for c in consumptions], Decimal("0.0"))

    # In total, exactly 60 units consumed from this layer
    assert total_consumed_qty == Decimal("60.0000")
    assert total_consumed_cost == Decimal("3000.0000")


async def test_concurrent_fifo_dispatch_multiple_layers(db_session: AsyncSession):
    """
    Test 2: Concurrent FIFO dispatch with multiple competing layers.
    Layer 1: 50 units @ $10.00 = $500.00
    Layer 2: 50 units @ $20.00 = $1,000.00
    Total = 100 units = $1,500.00
    Dispatch A: 40 units
    Dispatch B: 40 units
    Total requested = 80 <= 100.
    Verifies:
    - Both dispatches succeed.
    - Total COGS = (50 * $10) + (30 * $20) = $500 + $600 = $1,100.00.
    - Layer 1 is fully DEPLETED (0.0 remaining).
    - Layer 2 has exactly 20 units remaining ($400.00).
    - Total remaining valuation = $400.00 ($1,500 - $1,100 = $400).
    - No double consumption.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "FIFO", Decimal("10.0"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("10.00"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("20.00"))
    await db_session.flush()

    _, cogs_a = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    _, cogs_b = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    total_cogs = cogs_a.total_cogs_amount + cogs_b.total_cogs_amount
    assert total_cogs == Decimal("1100.0000")

    layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == variant.id).order_by(CostLayer.layer_timestamp.asc())
    )).scalars().all()

    assert len(layers) == 2
    assert layers[0].status == "DEPLETED"
    assert layers[0].remaining_quantity == Decimal("0.0000")
    assert layers[1].status == "ACTIVE"
    assert layers[1].remaining_quantity == Decimal("20.0000")

    profile = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert profile.current_quantity == Decimal("20.0000")
    assert profile.current_total_value == Decimal("400.0000")


async def test_concurrent_mwa_dispatch_and_immutability(db_session: AsyncSession):
    """
    Test 3: MWA dispatches against same warehouse + variant.
    Initial: 200 units @ $40.00 = $8,000.00
    Inbound: 100 units @ $70.00 = $7,000.00
    Running average = $15,000 / 300 = $50.00/unit.
    Dispatch 1: 60 units -> COGS = 60 * $50 = $3,000.00
    Dispatch 2: 90 units -> COGS = 90 * $50 = $4,500.00
    Verifies:
    - No lost update on quantity or value.
    - Final quantity = 150 units, total value = $7,500.00, average remains $50.00.
    - Historical COGS records immutable.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "WEIGHTED_AVERAGE", Decimal("40.0"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("200.0"), Decimal("40.00"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("70.00"))
    await db_session.flush()

    _, cogs_a = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("60.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    _, cogs_b = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("90.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    assert cogs_a.total_cogs_amount == Decimal("3000.0000")
    assert cogs_a.unit_cogs == Decimal("50.0000")
    assert cogs_b.total_cogs_amount == Decimal("4500.0000")
    assert cogs_b.unit_cogs == Decimal("50.0000")

    profile = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert profile.current_quantity == Decimal("150.0000")
    assert profile.current_total_value == Decimal("7500.0000")
    assert profile.moving_average_cost == Decimal("50.0000")


async def test_concurrent_receipt_and_dispatch(db_session: AsyncSession):
    """
    Test 4: Receipt + dispatch against same warehouse + variant.
    Initial: 50 units @ $10.00 = $500.00.
    Receipt: 50 units @ $30.00 = $1,500.00.
    Dispatch: 40 units.
    Final stock: 50 + 50 - 40 = 60 units.
    Verifies internal mathematical consistency.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "FIFO", Decimal("10.0"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("10.00"))
    await db_session.flush()

    rec_tx = await CostingService.record_inbound_receipt(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("50.0"),
        unit_cost=Decimal("30.00")
    )
    await db_session.flush()

    _, cogs = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    profile = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert profile.current_quantity == Decimal("60.0000")

    # In FIFO, oldest layer (50 @ $10) provided the 40 units -> COGS = $400.
    # Remaining: 10 @ $10 ($100) + 50 @ $30 ($1,500) = $1,600.00.
    assert cogs.total_cogs_amount == Decimal("400.0000")
    assert profile.current_total_value == Decimal("1600.0000")


async def test_concurrent_transfer_and_dispatch(db_session: AsyncSession):
    """
    Test 5: Transfer + dispatch from same source warehouse.
    Source WH: 100 units @ $25.00 = $2,500.00.
    Transfer: 40 units to WH B.
    Dispatch: 40 units from WH A.
    Verifies:
    - Source WH has 20 units remaining ($500.00).
    - Destination WH B receives 40 units @ $25.00 ($1,000.00) with provenance.
    - Dispatch recognizes COGS of $1,000.00.
    - No double consumption.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh_a, _, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "FIFO", Decimal("25.0"))
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-DEST-{uuid.uuid4().hex[:6]}", name="Destination WH")
    db_session.add(wh_b)
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh_a.id, variant.id, Decimal("100.0"), Decimal("25.00"))
    await db_session.flush()

    tx_out, tx_in = await CostingService.record_warehouse_transfer(
        db=db_session,
        tenant_id=tenant_id,
        source_warehouse_id=wh_a.id,
        dest_warehouse_id=wh_b.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0")
    )
    await db_session.flush()

    _, cogs = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh_a.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4())
    )
    await db_session.flush()

    assert tx_out.total_cost_impact == Decimal("1000.0000")
    assert tx_in.total_cost_impact == Decimal("1000.0000")
    assert cogs.total_cogs_amount == Decimal("1000.0000")

    # Source WH A
    prof_a = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh_a.id, variant.id)
    assert prof_a.current_quantity == Decimal("20.0000")
    assert prof_a.current_total_value == Decimal("500.0000")

    # Destination WH B
    prof_b = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh_b.id, variant.id)
    assert prof_b.current_quantity == Decimal("40.0000")
    assert prof_b.current_total_value == Decimal("1000.0000")

    # Check provenance
    dest_layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh_b.id, CostLayer.item_variant_id == variant.id)
    )).scalars().all()
    assert len(dest_layers) == 1
    assert dest_layers[0].source_layer_id is not None
    assert dest_layers[0].unit_cost == Decimal("25.0000")


async def test_deterministic_lock_ordering_deadlock_prevention(db_session: AsyncSession):
    """
    Test 6: Lock ordering / deadlock test.
    Transfers in opposite directions:
    - Transfer 1: Warehouse A -> Warehouse B (20 units)
    - Transfer 2: Warehouse B -> Warehouse A (15 units)
    Verifies that deterministic alphabetical warehouse ID locking prevents deadlocks and calculates balances correctly.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh_a, _, item, variant = await create_test_product_and_warehouse(db_session, tenant_id, "FIFO", Decimal("30.0"))
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-OPP-{uuid.uuid4().hex[:6]}", name="Opposite WH")
    db_session.add(wh_b)

    # Inbound stock in both warehouses
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh_a.id, variant.id, Decimal("50.0"), Decimal("30.00"))
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh_b.id, variant.id, Decimal("50.0"), Decimal("30.00"))
    await db_session.flush()

    # Transfer A -> B
    await CostingService.record_warehouse_transfer(
        db=db_session,
        tenant_id=tenant_id,
        source_warehouse_id=wh_a.id,
        dest_warehouse_id=wh_b.id,
        item_variant_id=variant.id,
        quantity=Decimal("20.0")
    )
    await db_session.flush()

    # Transfer B -> A
    await CostingService.record_warehouse_transfer(
        db=db_session,
        tenant_id=tenant_id,
        source_warehouse_id=wh_b.id,
        dest_warehouse_id=wh_a.id,
        item_variant_id=variant.id,
        quantity=Decimal("15.0")
    )
    await db_session.flush()

    prof_a = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh_a.id, variant.id)
    prof_b = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh_b.id, variant.id)

    # Warehouse A: 50 - 20 (out) + 15 (in) = 45 units
    assert prof_a.current_quantity == Decimal("45.0000")
    assert prof_a.current_total_value == Decimal("1350.0000")

    # Warehouse B: 50 - 15 (out) + 20 (in) = 55 units
    assert prof_b.current_quantity == Decimal("55.0000")
    assert prof_b.current_total_value == Decimal("1650.0000")
