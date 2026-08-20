import uuid
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.purchasing import Supplier, PurchaseOrder
from app.models.sales import Customer, SalesOrder
from app.services.costing_service import CostingService

pytestmark = pytest.mark.asyncio

async def test_fifo_single_and_multi_layer_consumption(client: AsyncClient, db_session: AsyncSession):
    """
    Tests FIFO layer creation, partial consumption, and multi-layer depletion
    with exact numerical verification.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Setup Warehouse and Product
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-FIFO-{uuid.uuid4().hex[:4]}", name="FIFO Test Warehouse")
    bin_obj = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", type="STORAGE")
    wh.bins.append(bin_obj)
    db_session.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Costing Category", code=f"CAT-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-FIFO-{uuid.uuid4().hex[:4]}", name="FIFO Widget", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-FIFO-{uuid.uuid4().hex[:4]}", variant_name="Standard", cost_price=Decimal("50.0"))
    item.variants.append(variant)
    db_session.add_all([cat, item])
    await db_session.commit()

    # 2. Inbound 3 sequential FIFO Receipts at different price points:
    # Layer 1: 50 units @ $10.00 = $500.00
    # Layer 2: 50 units @ $15.00 = $750.00
    # Layer 3: 50 units @ $20.00 = $1,000.00
    # Total Initial: 150 units = $2,250.00
    tx1 = await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("10.00"))
    tx2 = await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("15.00"))
    tx3 = await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("20.00"))
    await db_session.commit()

    # Verify 3 active layers
    layers_stmt = select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == variant.id).order_by(CostLayer.layer_timestamp.asc())
    layers = (await db_session.execute(layers_stmt)).scalars().all()
    assert len(layers) == 3
    assert layers[0].remaining_quantity == Decimal("50.0")
    assert layers[0].unit_cost == Decimal("10.00")
    assert layers[1].remaining_quantity == Decimal("50.0")
    assert layers[1].unit_cost == Decimal("15.00")
    assert layers[2].remaining_quantity == Decimal("50.0")
    assert layers[2].unit_cost == Decimal("20.00")

    # 3. Dispatch 80 units
    # Expected consumption:
    # - 50 units from Layer 1 @ $10.00 = $500.00 (Layer 1 fully depleted)
    # - 30 units from Layer 2 @ $15.00 = $450.00 (Layer 2 has 20 units remaining)
    # Expected COGS: $500.00 + $450.00 = $950.00
    dummy_so_id = str(uuid.uuid4())
    dummy_ship_id = str(uuid.uuid4())
    cost_tx, cogs = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("80.0"),
        sales_order_id=dummy_so_id,
        shipment_id=dummy_ship_id
    )
    await db_session.commit()

    # Assertions on COGS
    assert cogs.quantity_shipped == Decimal("80.0")
    assert cogs.total_cogs_amount == Decimal("950.00")
    assert cogs.unit_cogs == Decimal("11.8750") # $950 / 80

    # Refresh and inspect layer statuses
    layers = (await db_session.execute(layers_stmt)).scalars().all()
    assert layers[0].status == "DEPLETED"
    assert layers[0].remaining_quantity == Decimal("0.0")
    assert layers[1].status == "ACTIVE"
    assert layers[1].remaining_quantity == Decimal("20.0") # 50 - 30
    assert layers[2].status == "ACTIVE"
    assert layers[2].remaining_quantity == Decimal("50.0")

    # Inspect CostLayerConsumption records
    cons_stmt = select(CostLayerConsumption).where(CostLayerConsumption.cost_transaction_id == cost_tx.id).order_by(CostLayerConsumption.consumed_at.asc())
    consumptions = (await db_session.execute(cons_stmt)).scalars().all()
    assert len(consumptions) == 2
    assert consumptions[0].cost_layer_id == layers[0].id
    assert consumptions[0].quantity_consumed == Decimal("50.0")
    assert consumptions[0].unit_cost == Decimal("10.00")
    assert consumptions[0].total_cost == Decimal("500.00")
    assert consumptions[1].cost_layer_id == layers[1].id
    assert consumptions[1].quantity_consumed == Decimal("30.0")
    assert consumptions[1].unit_cost == Decimal("15.00")
    assert consumptions[1].total_cost == Decimal("450.00")

    # Remaining valuation: (20 * $15) + (50 * $20) = $300 + $1000 = $1,300.00
    # Reconciliation: $2,250.00 - $950.00 = $1,300.00
    profile = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert profile.current_quantity == Decimal("70.0")
    assert profile.current_total_value == Decimal("1300.00")

async def test_moving_weighted_average_and_historical_cogs_immutability(db_session: AsyncSession):
    """
    Tests Moving Weighted Average (MWA) formula recalculation, dispatch at running average,
    and historical COGS immutability across subsequent price changes.
    """
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-MWA-{uuid.uuid4().hex[:4]}", name="MWA Test Warehouse")
    bin_obj = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="B-01-01", type="STORAGE")
    wh.bins.append(bin_obj)
    db_session.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="MWA Category", code=f"CAT-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-MWA-{uuid.uuid4().hex[:4]}", name="MWA Item", valuation_method="WEIGHTED_AVERAGE")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-MWA-{uuid.uuid4().hex[:4]}", variant_name="MWA Variant", cost_price=Decimal("50.0"))
    item.variants.append(variant)
    db_session.add_all([cat, item])
    await db_session.commit()

    # Step 1: Initial Receipt: 100 units @ $50.00 = $5,000.00. Average = $50.00
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("50.00"))
    profile = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert profile.moving_average_cost == Decimal("50.0000")
    assert profile.current_quantity == Decimal("100.0000")
    assert profile.current_total_value == Decimal("5000.0000")

    # Step 2: Second Receipt: 100 units @ $60.00 = $6,000.00.
    # New Average = ($5,000 + $6,000) / (100 + 100) = $11,000 / 200 = $55.00/unit
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("60.00"))
    await db_session.refresh(profile)
    assert profile.current_quantity == Decimal("200.0000")
    assert profile.current_total_value == Decimal("11000.0000")
    assert profile.moving_average_cost == Decimal("55.0000")

    # Step 3: Outbound Dispatch of 120 units
    # COGS = 120 * $55.00 = $6,600.00
    dummy_so = str(uuid.uuid4())
    dummy_ship = str(uuid.uuid4())
    tx_disp, cogs1 = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("120.0"),
        sales_order_id=dummy_so,
        shipment_id=dummy_ship
    )
    await db_session.commit()

    assert cogs1.total_cogs_amount == Decimal("6600.0000")
    assert cogs1.unit_cogs == Decimal("55.0000")

    await db_session.refresh(profile)
    assert profile.current_quantity == Decimal("80.0000")
    assert profile.current_total_value == Decimal("4400.0000")
    assert profile.moving_average_cost == Decimal("55.0000") # Unchanged by dispatch

    # Step 4: Subsequent Inbound Receipt at significantly higher cost: 100 units @ $70.00 = $7,000.00
    # New Average = ($4,400 + $7,000) / (80 + 100) = $11,400 / 180 = $63.3333/unit
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("70.00"))
    await db_session.commit()
    await db_session.refresh(profile)
    assert profile.current_quantity == Decimal("180.0000")
    assert profile.current_total_value == Decimal("11400.0000")
    assert profile.moving_average_cost == Decimal("63.3333")

    # Step 5: Verify Historical Immutability of COGS Record 1
    cogs_verify = (await db_session.execute(select(COGSRecord).where(COGSRecord.id == cogs1.id))).scalar_one()
    assert cogs_verify.total_cogs_amount == Decimal("6600.0000")
    assert cogs_verify.unit_cogs == Decimal("55.0000")

async def test_warehouse_transfer_cost_preservation_and_provenance(db_session: AsyncSession):
    """
    Tests inter-warehouse transfer cost layer cloning, provenance linking, and zero P&L impact.
    """
    tenant_id = settings.TENANT_DEFAULT_ID

    wh_a = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-TR-A-{uuid.uuid4().hex[:4]}", name="Source Warehouse")
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-TR-B-{uuid.uuid4().hex[:4]}", name="Destination Warehouse")
    db_session.add_all([wh_a, wh_b])

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Transfer Cat", code=f"CAT-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-TR-{uuid.uuid4().hex[:4]}", name="Transfer Item", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-TR-{uuid.uuid4().hex[:4]}", variant_name="Transfer Var", cost_price=Decimal("40.0"))
    item.variants.append(variant)
    db_session.add_all([cat, item])
    await db_session.commit()

    # Inbound 100 units @ $42.50 into Warehouse A
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh_a.id, variant.id, Decimal("100.0"), Decimal("42.50"))
    await db_session.commit()

    # Transfer 40 units from Warehouse A to Warehouse B
    tx_out, tx_in = await CostingService.record_warehouse_transfer(
        db=db_session,
        tenant_id=tenant_id,
        source_warehouse_id=wh_a.id,
        dest_warehouse_id=wh_b.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0")
    )
    await db_session.commit()

    # Zero P&L: Total Out Cost equals Total In Cost
    assert tx_out.total_cost_impact == Decimal("1700.0000") # 40 * $42.50
    assert tx_in.total_cost_impact == Decimal("1700.0000")

    # Verify Cloned Layer in Warehouse B
    dest_layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh_b.id, CostLayer.item_variant_id == variant.id)
    )).scalars().all()

    assert len(dest_layers) == 1
    assert dest_layers[0].original_quantity == Decimal("40.0")
    assert dest_layers[0].remaining_quantity == Decimal("40.0")
    assert dest_layers[0].unit_cost == Decimal("42.50")
    assert dest_layers[0].source_layer_id is not None # Provenance maintained

    # Verify Source Layer in Warehouse A has 60 units remaining
    src_layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh_a.id, CostLayer.item_variant_id == variant.id)
    )).scalars().all()
    assert src_layers[0].remaining_quantity == Decimal("60.0")

async def test_returns_and_adjustments_costing(db_session: AsyncSession):
    """
    Tests saleable customer returns restoring original acquisition cost,
    and positive/negative inventory adjustments.
    """
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-ADJ-{uuid.uuid4().hex[:4]}", name="Adj WH")
    db_session.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Adj Cat", code=f"CAT-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-ADJ-{uuid.uuid4().hex[:4]}", name="Adj Item", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-ADJ-{uuid.uuid4().hex[:4]}", variant_name="Adj Var", cost_price=Decimal("30.0"))
    item.variants.append(variant)
    db_session.add_all([cat, item])
    await db_session.commit()

    # 1. Positive adjustment (+20 units @ $35.00)
    tx_pos = await CostingService.record_inventory_adjustment(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity_diff=Decimal("20.0"),
        unit_cost=Decimal("35.00"),
        reason="Physical count surplus"
    )
    await db_session.commit()
    assert tx_pos.total_cost_impact == Decimal("700.0000") # 20 * $35

    # 2. Dispatch 10 units
    so_id = str(uuid.uuid4())
    ship_id = str(uuid.uuid4())
    _, cogs = await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("10.0"),
        sales_order_id=so_id,
        shipment_id=ship_id
    )
    await db_session.commit()
    assert cogs.unit_cogs == Decimal("35.0000")
    assert cogs.total_cogs_amount == Decimal("350.0000")

    # 3. Customer Return: Return 5 units (Good condition)
    ret_tx = await CostingService.record_customer_return(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("5.0"),
        sales_order_id=so_id,
        condition="GOOD"
    )
    await db_session.commit()
    assert ret_tx.unit_cost == Decimal("35.0000")
    assert ret_tx.total_cost_impact == Decimal("175.0000")

    # 4. Negative adjustment (-5 units)
    tx_neg = await CostingService.record_inventory_adjustment(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity_diff=Decimal("-5.0"),
        reason="Damaged in transit"
    )
    await db_session.commit()
    assert tx_neg.total_cost_impact == Decimal("175.0000")

async def test_costing_apis_and_operational_valuation_report(client: AsyncClient, db_session: AsyncSession):
    """
    Tests Costing REST API endpoints for layers, profiles, COGS, and valuation reports with RBAC.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Seed opening layers
    mig_res = await client.post("/api/v1/costing/opening-layers", json={
        "default_cost_if_missing": 25.0
    }, headers=headers)
    assert mig_res.status_code == 200
    assert mig_res.json()["status"] == "SUCCESS"

    # List layers
    layers_res = await client.get("/api/v1/costing/layers", headers=headers)
    assert layers_res.status_code == 200
    assert "items" in layers_res.json()

    # List profiles
    profiles_res = await client.get("/api/v1/costing/profiles", headers=headers)
    assert profiles_res.status_code == 200
    assert len(profiles_res.json()) > 0

    # Operational Valuation Report
    val_res = await client.get("/api/v1/costing/valuation", headers=headers)
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["report_title"] == "Operational Inventory Valuation"
    assert "disclaimer" in val_data
    assert "total_valuation" in val_data
    assert "warehouse_breakdown" in val_data
    assert "product_breakdown" in val_data
