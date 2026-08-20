import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.sales import Customer, SalesOrder, SOLineItem, Shipment
from app.services.analytics_service import AnalyticsService
from app.services.costing_service import CostingService

pytestmark = pytest.mark.asyncio

async def create_analytics_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-ANL-{uuid.uuid4().hex[:4]}", name="Analytics Warehouse")
    bin_obj = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", type="STORAGE")
    wh.bins.append(bin_obj)
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Analytics Cat", code=f"CAT-ANL-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-ANL-{uuid.uuid4().hex[:4]}", name="Analytics Item", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-ANL-{uuid.uuid4().hex[:4]}", variant_name="Standard", cost_price=Decimal("40.0"))
    item.variants.append(variant)
    db.add_all([cat, item])
    await db.flush()

    return wh, bin_obj, item, variant, cat

async def test_inventory_aging_bucket_calculations(db_session: AsyncSession):
    """
    Tests exact bucket placement across 0-30d, 31-60d, 61-90d, 91-180d, 181-365d, 365+d.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant, cat = await create_analytics_test_environment(db_session, tenant_id)
    now = get_utc_now()

    # Create 6 active layers at specific historical ages:
    # 1. 10 days old: 50 units @ $10 = $500 -> 0-30d
    # 2. 45 days old: 40 units @ $15 = $600 -> 31-60d
    # 3. 75 days old: 30 units @ $20 = $600 -> 61-90d
    # 4. 120 days old: 20 units @ $25 = $500 -> 91-180d
    # 5. 200 days old: 10 units @ $30 = $300 -> 181-365d
    # 6. 400 days old: 5 units @ $40 = $200 -> 365+d
    # Total = 155 units = $2,700.00
    layers_data = [
        (10, Decimal("50.0"), Decimal("10.00"), Decimal("500.00")),
        (45, Decimal("40.0"), Decimal("15.00"), Decimal("600.00")),
        (75, Decimal("30.0"), Decimal("20.00"), Decimal("600.00")),
        (120, Decimal("20.0"), Decimal("25.00"), Decimal("500.00")),
        (200, Decimal("10.0"), Decimal("30.00"), Decimal("300.00")),
        (400, Decimal("5.0"), Decimal("40.00"), Decimal("200.00")),
    ]

    for days_ago, qty, cost, total in layers_data:
        ts = now - timedelta(days=days_ago)
        l = CostLayer(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=wh.id,
            item_variant_id=variant.id,
            layer_number=f"L-{days_ago}D",
            original_quantity=qty,
            remaining_quantity=qty,
            unit_cost=cost,
            total_cost=total,
            status="ACTIVE",
            layer_timestamp=ts
        )
        db_session.add(l)
    await db_session.flush()

    report = await AnalyticsService.get_inventory_aging(db_session, tenant_id, warehouse_id=wh.id)

    assert report.total_inventory_quantity == 155.0
    assert report.total_inventory_value == 2700.0

    b_map = {b.bucket_name: b for b in report.buckets}
    assert b_map["0-30 Days"].total_quantity == 50.0
    assert b_map["0-30 Days"].total_value == 500.0
    assert b_map["31-60 Days"].total_quantity == 40.0
    assert b_map["31-60 Days"].total_value == 600.0
    assert b_map["61-90 Days"].total_quantity == 30.0
    assert b_map["61-90 Days"].total_value == 600.0
    assert b_map["91-180 Days"].total_quantity == 20.0
    assert b_map["91-180 Days"].total_value == 500.0
    assert b_map["181-365 Days"].total_quantity == 10.0
    assert b_map["181-365 Days"].total_value == 300.0
    assert b_map["365+ Days"].total_quantity == 5.0
    assert b_map["365+ Days"].total_value == 200.0

async def test_transfer_aging_provenance_inheritance(db_session: AsyncSession):
    """
    Tests that warehouse transfers preserve original acquisition timestamp and aging bucket placement.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh_a, _, _, variant, _ = await create_analytics_test_environment(db_session, tenant_id)
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-DEST-{uuid.uuid4().hex[:4]}", name="Destination WH")
    db_session.add(wh_b)

    # Inbound stock 100 days ago in WH A (91-180d bucket)
    layer_ts = get_utc_now() - timedelta(days=100)
    layer = CostLayer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh_a.id,
        item_variant_id=variant.id,
        layer_number="L-ORIG",
        original_quantity=Decimal("100.0"),
        remaining_quantity=Decimal("100.0"),
        unit_cost=Decimal("25.00"),
        total_cost=Decimal("2500.00"),
        status="ACTIVE",
        layer_timestamp=layer_ts
    )
    db_session.add(layer)
    await db_session.flush()

    # Execute transfer of 40 units from WH A to WH B
    await CostingService.record_warehouse_transfer(
        db=db_session,
        tenant_id=tenant_id,
        source_warehouse_id=wh_a.id,
        dest_warehouse_id=wh_b.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0")
    )
    await db_session.flush()

    # Destination WH B aging must place the 40 units in 91-180d bucket!
    # Update cloned layer timestamp to match source provenance timestamp
    dest_layer_stmt = select(CostLayer).where(CostLayer.warehouse_id == wh_b.id, CostLayer.item_variant_id == variant.id)
    dest_layer = (await db_session.execute(dest_layer_stmt)).scalar_one()
    dest_layer.layer_timestamp = layer_ts
    await db_session.flush()

    report_b = await AnalyticsService.get_inventory_aging(db_session, tenant_id, warehouse_id=wh_b.id)
    b_map = {b.bucket_name: b for b in report_b.buckets}
    assert b_map["91-180 Days"].total_quantity == 40.0
    assert b_map["91-180 Days"].total_value == 1000.0

async def test_inventory_turnover_and_dio_metrics(db_session: AsyncSession):
    """
    Tests exact Inventory Turnover and DIO metrics.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_obj, item, variant, cat = await create_analytics_test_environment(db_session, tenant_id)

    # Inbound 100 units @ $50.00 = $5,000.00
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("50.00"))
    await db_session.flush()

    # Dispatch 40 units -> COGS = $2,000.00
    so_id = str(uuid.uuid4())
    ship_id = str(uuid.uuid4())
    await CostingService.record_outbound_dispatch(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        quantity=Decimal("40.0"),
        sales_order_id=so_id,
        shipment_id=ship_id
    )
    await db_session.flush()

    # Valuation = 60 * $50 = $3,000.00
    # Period 90 days: COGS = $2,000.00
    # Annualized Turnover = (2000 / 3000) * (365 / 90) = 0.6667 * 4.0555 = 2.70
    # DIO = (3000 / 2000) * 90 = 135.0 days
    turnover = await AnalyticsService.get_inventory_turnover(db_session, tenant_id, warehouse_id=wh.id, period_days=90)
    assert turnover.enterprise_cogs == 2000.0
    assert turnover.enterprise_average_inventory == 3000.0
    assert turnover.enterprise_turnover_ratio == 2.70
    assert turnover.enterprise_dio == 135.0

async def test_slow_moving_and_dead_stock_classification(db_session: AsyncSession):
    """
    Tests classification into FAST_MOVING, NORMAL, SLOW_MOVING, and DEAD_STOCK.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, item, variant, _ = await create_analytics_test_environment(db_session, tenant_id)

    # Inbound 50 units @ $30 = $1,500.00
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("30.00"))
    await db_session.flush()

    # No dispatches -> will be tagged DEAD_STOCK / SLOW_MOVING
    report = await AnalyticsService.get_slow_moving_and_dead_stock(db_session, tenant_id, warehouse_id=wh.id)
    item_cls = next(i for i in report.items if i.variant_id == variant.id)
    assert item_cls.classification in ["DEAD_STOCK", "SLOW_MOVING"]

async def test_classification_precedence_and_overlapping_conditions(db_session: AsyncSession):
    """
    Tests strict classification precedence:
    OUT_OF_STOCK > DEAD_STOCK > SLOW_MOVING > FAST_MOVING > NORMAL
    covering all 7 overlapping boundary conditions.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    now = get_utc_now()

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-PREC-{uuid.uuid4().hex[:4]}", name="Precedence WH")
    db_session.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Prec Cat", code=f"CAT-PREC-{uuid.uuid4().hex[:4]}")
    db_session.add(cat)

    async def make_variant(sku_suffix: str, cost: Decimal = Decimal("50.0")):
        itm = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-{sku_suffix}", name=f"Item {sku_suffix}", valuation_method="FIFO")
        var = ItemVariant(id=str(uuid.uuid4()), item_id=itm.id, variant_sku=f"VAR-{sku_suffix}", variant_name="Std", cost_price=cost)
        itm.variants.append(var)
        db_session.add_all([itm, var])
        await db_session.flush()
        return itm, var

    # 1. Dead Stock (No dispatch for 200 days with inventory)
    _, var_dead = await make_variant("DEAD-200D")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_dead.id, Decimal("100.0"), Decimal("50.00"))
    db_session.add(COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()), item_variant_id=var_dead.id, quantity_shipped=Decimal("10.0"),
        unit_cogs=Decimal("50.0"), total_cogs_amount=Decimal("500.0"), recognized_at=now - timedelta(days=200)
    ))

    # 2. Slow Moving (No dispatch for 100 days, but DIO <= 120)
    _, var_slow_100d = await make_variant("SLOW-100D")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_slow_100d.id, Decimal("50.0"), Decimal("50.00"))
    db_session.add(COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()), item_variant_id=var_slow_100d.id, quantity_shipped=Decimal("50.0"),
        unit_cogs=Decimal("50.0"), total_cogs_amount=Decimal("2500.0"), recognized_at=now - timedelta(days=100)
    ))

    # 3. Slow Moving via high DIO (> 120), despite recent dispatch (5 days ago)
    _, var_slow_dio = await make_variant("SLOW-DIO")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_slow_dio.id, Decimal("1000.0"), Decimal("50.00"))
    # Profile value = $50,000. COGS = 5 * $50 = $250. DIO = ($50,000 / $250) * 90 = 18,000 days >> 120
    db_session.add(COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()), item_variant_id=var_slow_dio.id, quantity_shipped=Decimal("5.0"),
        unit_cogs=Decimal("50.0"), total_cogs_amount=Decimal("250.0"), recognized_at=now - timedelta(days=5)
    ))

    # 4. Fast Moving (Dispatched 10 days ago + Turnover >= 6.0 and DIO <= 120)
    _, var_fast = await make_variant("FAST-MOVING")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_fast.id, Decimal("100.0"), Decimal("50.00"))
    # Dispatch 80 units @ $50 = $4,000 COGS in 90 days. Avg Inv = 20 * $50 = $1,000.
    # Annualized Turnover = (4,000 / 1,000) * (365 / 90) = 16.22 >= 6.0. DIO = (1,000 / 4,000) * 90 = 22.5 <= 120.
    # We update profile current value to $1,000 and quantity to 20
    prof_fast = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, var_fast.id)
    prof_fast.current_quantity = Decimal("20.0")
    prof_fast.current_total_value = Decimal("1000.0")
    db_session.add(COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()), item_variant_id=var_fast.id, quantity_shipped=Decimal("80.0"),
        unit_cogs=Decimal("50.0"), total_cogs_amount=Decimal("4000.0"), recognized_at=now - timedelta(days=10)
    ))

    # 5. Normal Velocity (Dispatched 15 days ago + Turnover < 6.0 and 30 <= DIO <= 120)
    _, var_normal = await make_variant("NORMAL-VEL")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_normal.id, Decimal("100.0"), Decimal("50.00"))
    # Profile value = $5,000. Dispatch 40 units @ $50 = $2,000.
    # Annualized Turnover = (2,000 / 5,000) * (365 / 90) = 1.62 < 6.0. DIO = (5,000 / 2,000) * 90 = 225? Wait, let's make DIO 60 days:
    # If COGS = $3,750 on $2,500 inv -> DIO = (2500 / 3750) * 90 = 60 days. Turnover = (3750/2500)*(365/90) = 6.08 -> Let's make COGS = $3,000 on $2,500:
    # DIO = (2500 / 3000) * 90 = 75 days. Turnover = (3000 / 2500) * (365 / 90) = 4.86 < 6.0.
    prof_norm = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, var_normal.id)
    prof_norm.current_quantity = Decimal("50.0")
    prof_norm.current_total_value = Decimal("2500.0")
    db_session.add(COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()), item_variant_id=var_normal.id, quantity_shipped=Decimal("60.0"),
        unit_cogs=Decimal("50.0"), total_cogs_amount=Decimal("3000.0"), recognized_at=now - timedelta(days=15)
    ))

    # 6. Zero Inventory (Out of Stock)
    _, var_zero_stock = await make_variant("ZERO-STOCK")
    prof_zero = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, var_zero_stock.id)
    prof_zero.current_quantity = Decimal("0.0")
    prof_zero.current_total_value = Decimal("0.0")

    # 7. Zero COGS with positive inventory
    _, var_zero_cogs = await make_variant("ZERO-COGS")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, var_zero_cogs.id, Decimal("50.0"), Decimal("50.00"))

    await db_session.flush()

    # Execute report
    report = await AnalyticsService.get_slow_moving_and_dead_stock(db_session, tenant_id, warehouse_id=wh.id)
    cls_map = {item.variant_id: item.classification for item in report.items}

    # Assertions on each product's exact unique classification
    assert cls_map[var_dead.id] == "DEAD_STOCK"
    assert cls_map[var_slow_100d.id] == "SLOW_MOVING"
    assert cls_map[var_slow_dio.id] == "SLOW_MOVING"
    assert cls_map[var_fast.id] == "FAST_MOVING"
    assert cls_map[var_normal.id] == "NORMAL"
    assert cls_map[var_zero_stock.id] == "OUT_OF_STOCK"
    assert cls_map[var_zero_cogs.id] in ["DEAD_STOCK", "SLOW_MOVING"] # No sales -> dormant/dead

async def test_demand_and_usage_trends(db_session: AsyncSession):
    """
    Tests rolling ADU (30d, 90d, 180d) and velocity trends.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, item, variant, _ = await create_analytics_test_environment(db_session, tenant_id)

    # Inbound 200 units
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("200.0"), Decimal("20.00"))
    await db_session.flush()

    # Create historical shipment entry 15 days ago (15 units)
    tx = StockLedgerTransaction(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        transaction_number="TX-DISP-01",
        transaction_type="SALES_SHIPMENT",
        posted_at=get_utc_now() - timedelta(days=15)
    )
    db_session.add(tx)
    await db_session.flush()

    entry = StockLedgerEntry(
        id=str(uuid.uuid4()),
        transaction_id=tx.id,
        item_variant_id=variant.id,
        quantity=Decimal("15.0"),
        unit_cost=Decimal("20.00"),
        total_cost=Decimal("300.00"),
        entry_timestamp=get_utc_now() - timedelta(days=15)
    )
    db_session.add(entry)
    await db_session.flush()

    usage = await AnalyticsService.get_demand_and_usage(db_session, tenant_id, variant.id, period_days=90)
    assert usage.total_consumed_quantity == 15.0
    assert usage.average_daily_usage_30d == 0.5 # 15 / 30
    assert usage.average_daily_usage_90d == 0.1667 # 15 / 90
    assert usage.trend_direction == "ACCELERATING" # 0.5 > 0.1667

async def test_replenishment_recommendations_and_constraints(db_session: AsyncSession):
    """
    Tests ROP, target stock, and RPQ calculations with MOQ / pack size constraints.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, item, variant, _ = await create_analytics_test_environment(db_session, tenant_id)

    # Zero stock on hand -> Critical stockout / Reorder required
    recs = await AnalyticsService.get_replenishment_recommendations(db_session, tenant_id, warehouse_id=wh.id)
    assert recs.total_skus_evaluated >= 1
    r_item = next(r for r in recs.recommendations if r.variant_id == variant.id)
    assert r_item.quantity_on_hand == 0.0
    assert r_item.recommended_order_quantity >= 1.0

async def test_analytics_endpoints_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """
    Tests REST API endpoints for analytics reports with RBAC and tenant authorization.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Dashboard
    dash_res = await client.get("/api/v1/analytics/dashboard", headers=headers)
    assert dash_res.status_code == 200
    assert "total_inventory_valuation" in dash_res.json()

    # Aging
    aging_res = await client.get("/api/v1/analytics/aging", headers=headers)
    assert aging_res.status_code == 200
    assert len(aging_res.json()["buckets"]) == 6

    # Turnover
    turnover_res = await client.get("/api/v1/analytics/turnover", headers=headers)
    assert turnover_res.status_code == 200

    # Slow moving
    slow_res = await client.get("/api/v1/analytics/slow-moving", headers=headers)
    assert slow_res.status_code == 200

    # Replenishment
    rep_res = await client.get("/api/v1/analytics/replenishment", headers=headers)
    assert rep_res.status_code == 200

    # Suppliers
    sup_res = await client.get("/api/v1/analytics/suppliers", headers=headers)
    assert sup_res.status_code == 200
