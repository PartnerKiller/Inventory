import pytest
import uuid
import math
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.purchasing import Supplier, SupplierProduct, PurchaseOrder, POLineItem
from app.models.manufacturing import WorkOrder, WorkOrderComponent, BillOfMaterials, BOMLineItem
from app.models.costing import COGSRecord, CostLayer, CostTransaction
from app.models.replenishment import (
    ReplenishmentConfig,
    ReplenishmentRun,
    ReplenishmentRecommendationItem
)
from app.schemas.replenishment import (
    ReplenishmentConfigCreate,
    GenerateDraftPOsRequest
)
from app.services.replenishment_service import ReplenishmentService
from app.services.analytics_service import AnalyticsService
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService

async def create_replenishment_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-RPL-{uuid.uuid4().hex[:4]}", name="Central Replenishment Hub")
    db.add(wh)
    await db.flush()

    bin_storage = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="RPL-STORE-01", type="STORAGE")
    db.add(bin_storage)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Commercial Goods", code=f"COMM-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    # Product A
    item_a = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-RPA-{uuid.uuid4().hex[:4]}", name="Industrial Relay 12V")
    db.add(item_a)
    await db.flush()

    var_a = ItemVariant(
        id=str(uuid.uuid4()), item_id=item_a.id, variant_sku=f"{item_a.sku}-V1",
        variant_name="Standard", cost_price=Decimal("10.00"), selling_price=Decimal("25.00")
    )
    db.add(var_a)

    # Supplier Acme
    supp = Supplier(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-{uuid.uuid4().hex[:4]}",
        name="Acme Components Ltd", currency="USD", is_active=True
    )
    db.add(supp)
    await db.flush()

    # Supplier Product Mapping with MOQ 20, Pack Size 5, Lead Time 10 days
    sp_a = SupplierProduct(
        id=str(uuid.uuid4()), tenant_id=tenant_id, supplier_id=supp.id, item_variant_id=var_a.id,
        supplier_sku="ACME-RELAY-12V", unit_cost=Decimal("10.00"), currency="USD",
        minimum_order_quantity=Decimal("20.0"), pack_size=Decimal("5.0"), lead_time_days=10,
        is_preferred=True, is_active=True
    )
    db.add(sp_a)

    await db.commit()
    return wh, bin_storage, var_a, supp, sp_a

# ============================================================================
# 1. COMPLETE NUMERICAL REPLENISHMENT SCENARIO
# ============================================================================

@pytest.mark.asyncio
async def test_complete_numerical_replenishment_scenario(db_session: AsyncSession):
    """
    Exact scenario:
    - On-hand = 100
    - Allocated = 20 (Available = 80)
    - Approved Inbound PO = 30
    - Unreserved Planned WO demand = 10
    - NIP = (100 - 20) + 30 - 10 = 100.0000

    Historical Shipments:
    - Last 30d: 300 units -> ADU30 = 10.0
    - Last 90d: 540 units -> ADU90 = 6.0
    - Last 180d: 720 units -> ADU180 = 4.0
    - ADUeffective = (0.50 * 10) + (0.35 * 6) + (0.15 * 4) = 5.0 + 2.1 + 0.6 = 7.7000

    Sizing:
    - Lead Time = 10 days, Safety Stock Days = 7, Target Coverage = 30 days
    - SS = 7.7 * 7 = 53.90 -> 53.90
    - ROP = (7.7 * 10) + 53.90 = 77.0 + 53.90 = 130.90
    - Target Max Stock = 130.90 + (7.7 * 30) = 130.90 + 231.0 = 361.90
    - Raw Requirement = 361.90 - 100 = 261.90
    - Pack Size = 25, MOQ = 50
    - Pack rounding: ceil(261.90 / 25) * 25 = 11 * 25 = 275.00
    - Final suggested quantity = max(50, 275) = 275.0000
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, sp_a = await create_replenishment_test_environment(db_session, tenant_id)

    # Reconfigure SupplierProduct for exact scenario
    sp_a.minimum_order_quantity = Decimal("50.0")
    sp_a.pack_size = Decimal("25.0")
    sp_a.lead_time_days = 10

    # 1. On hand = 100, Allocated = 20
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_storage.id, "item_variant_id": var_a.id, "quantity": Decimal("100.0")}])
    bal = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.warehouse_id == wh.id, StockBalanceCache.item_variant_id == var_a.id))).scalar_one()
    bal.quantity_allocated = Decimal("20.0")

    # 2. Approved Inbound PO = 30
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number="PO-NUM-100", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("300.00"))
    db_session.add(po)
    await db_session.flush()
    pol = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=var_a.id, quantity_ordered=Decimal("30.0"), quantity_received=Decimal("0.0"), unit_price=Decimal("10.00"), line_total=Decimal("300.00"))
    db_session.add(pol)

    # 3. Unreserved Planned WO demand = 10
    bom = BillOfMaterials(id=str(uuid.uuid4()), tenant_id=tenant_id, bom_number="BOM-NUM-100", name="Assy", item_variant_id=var_a.id, version="1.0", status="ACTIVE")
    db_session.add(bom)
    await db_session.flush()
    wo = WorkOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, work_order_number="WO-NUM-100", bom_id=bom.id, item_variant_id=var_a.id, warehouse_id=wh.id, staging_bin_id=bin_storage.id, destination_bin_id=bin_storage.id, status="PLANNED", quantity_to_produce=Decimal("10.0"))
    db_session.add(wo)
    await db_session.flush()
    woc = WorkOrderComponent(id=str(uuid.uuid4()), work_order_id=wo.id, component_variant_id=var_a.id, quantity_required=Decimal("10.0"), quantity_consumed=Decimal("0.0"))
    db_session.add(woc)

    # 4. COGS shipments: 300 in 30d, 240 in 90d (total 540), 180 in 180d (total 720)
    cost_tx = CostTransaction(id=str(uuid.uuid4()), tenant_id=tenant_id, transaction_type="COGS_RECOGNITION", cost_transaction_number=f"CTX-{uuid.uuid4().hex[:6]}", item_variant_id=var_a.id, warehouse_id=wh.id, quantity=Decimal("720.0"), unit_cost=Decimal("10.00"), total_cost_impact=Decimal("7200.00"))
    db_session.add(cost_tx)
    await db_session.flush()

    now = get_utc_now()
    c1 = COGSRecord(id=str(uuid.uuid4()), tenant_id=tenant_id, item_variant_id=var_a.id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()), cost_transaction_id=cost_tx.id, quantity_shipped=Decimal("300.0"), unit_cogs=Decimal("10.00"), total_cogs_amount=Decimal("3000.00"), recognized_at=now - timedelta(days=10))
    c2 = COGSRecord(id=str(uuid.uuid4()), tenant_id=tenant_id, item_variant_id=var_a.id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()), cost_transaction_id=cost_tx.id, quantity_shipped=Decimal("240.0"), unit_cogs=Decimal("10.00"), total_cogs_amount=Decimal("2400.00"), recognized_at=now - timedelta(days=50))
    c3 = COGSRecord(id=str(uuid.uuid4()), tenant_id=tenant_id, item_variant_id=var_a.id, sales_order_id=str(uuid.uuid4()), shipment_id=str(uuid.uuid4()), cost_transaction_id=cost_tx.id, quantity_shipped=Decimal("180.0"), unit_cogs=Decimal("10.00"), total_cogs_amount=Decimal("1800.00"), recognized_at=now - timedelta(days=120))
    db_session.add_all([c1, c2, c3])
    await db_session.commit()

    rep_run = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    item_rec = next(it for it in rep_run.items if it.item_variant_id == var_a.id)

    assert item_rec.quantity_on_hand == Decimal("100.0000")
    assert item_rec.quantity_allocated == Decimal("20.0000")
    assert item_rec.quantity_available == Decimal("80.0000")
    assert item_rec.quantity_incoming == Decimal("30.0000")
    assert item_rec.quantity_mfg_planned == Decimal("10.0000")
    assert item_rec.net_inventory_position == Decimal("100.0000") # (100-20) + 30 - 10
    assert item_rec.average_daily_usage == Decimal("7.7000")
    assert item_rec.safety_stock == Decimal("53.9000")
    assert item_rec.reorder_point == Decimal("130.9000")
    assert item_rec.target_maximum_stock == Decimal("361.9000")
    assert item_rec.suggested_reorder_quantity == Decimal("275.0000")
    assert item_rec.urgency_status == "REORDER_NOW"

# ============================================================================
# 2. SAFETY STOCK & ROP BEHAVIORAL VARIATIONS
# ============================================================================

@pytest.mark.asyncio
async def test_safety_stock_and_rop_variations(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, sp_a = await create_replenishment_test_environment(db_session, tenant_id)

    # Test A: Fixed Safety Stock = 50
    await ReplenishmentService.upsert_config(db_session, tenant_id, ReplenishmentConfigCreate(
        item_variant_id=var_a.id, warehouse_id=wh.id, fixed_safety_stock=Decimal("50.0")
    ))
    rep_run = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    item_rec = next(it for it in rep_run.items if it.item_variant_id == var_a.id)
    assert item_rec.safety_stock == Decimal("50.0000")

    # Test B: MIN_MAX Method (min = 100, max = 300)
    await ReplenishmentService.upsert_config(db_session, tenant_id, ReplenishmentConfigCreate(
        item_variant_id=var_a.id, warehouse_id=wh.id, reorder_method="MIN_MAX",
        min_quantity=Decimal("100.0"), max_quantity=Decimal("300.0")
    ))
    rep_run2 = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    item_rec2 = next(it for it in rep_run2.items if it.item_variant_id == var_a.id)
    assert item_rec2.reorder_point == Decimal("100.0000")
    assert item_rec2.target_maximum_stock == Decimal("300.0000")

# ============================================================================
# 3. DEMAND TREND CLASSIFICATION IN ANALYTICS
# ============================================================================

@pytest.mark.asyncio
async def test_demand_trend_classification_analytics(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, _ = await create_replenishment_test_environment(db_session, tenant_id)

    from app.models.ledger import StockLedgerEntry
    now = get_utc_now()
    
    # 1. Recent Sales Shipment: 300 units 10 days ago
    tx1 = StockLedgerTransaction(
        id=str(uuid.uuid4()), tenant_id=tenant_id, transaction_number=f"TX-SALES-{uuid.uuid4().hex[:6]}",
        transaction_type="SALES_SHIPMENT", posted_at=now - timedelta(days=10)
    )
    db_session.add(tx1)
    await db_session.flush()
    e1 = StockLedgerEntry(
        id=str(uuid.uuid4()), transaction_id=tx1.id, item_variant_id=var_a.id,
        source_location_bin_id=bin_storage.id, quantity=Decimal("300.0"), unit_cost=Decimal("10.00"), total_cost=Decimal("3000.00")
    )
    db_session.add(e1)

    # 2. Older Sales Shipment: 50 units 60 days ago
    tx2 = StockLedgerTransaction(
        id=str(uuid.uuid4()), tenant_id=tenant_id, transaction_number=f"TX-SALES-{uuid.uuid4().hex[:6]}",
        transaction_type="SALES_SHIPMENT", posted_at=now - timedelta(days=60)
    )
    db_session.add(tx2)
    await db_session.flush()
    e2 = StockLedgerEntry(
        id=str(uuid.uuid4()), transaction_id=tx2.id, item_variant_id=var_a.id,
        source_location_bin_id=bin_storage.id, quantity=Decimal("50.0"), unit_cost=Decimal("10.00"), total_cost=Decimal("500.00")
    )
    db_session.add(e2)
    await db_session.commit()

    demand_resp = await AnalyticsService.get_demand_and_usage(db_session, tenant_id, var_a.id, period_days=90)
    assert demand_resp.trend_direction == "ACCELERATING"
    assert demand_resp.usage_trend_percentage > 15.0

# ============================================================================
# 4. OPEN-PO DEMAND PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_open_po_demand_protection(db_session: AsyncSession):
    """
    On-hand = 20
    Demand / Target Stock = 100
    Approved Inbound PO = 100
    Net Inventory Position = 20 + 100 = 120 > ROP (e.g. 50).
    System must NOT recommend another purchase order.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, _ = await create_replenishment_test_environment(db_session, tenant_id)

    # 20 on hand
    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_storage.id, "item_variant_id": var_a.id, "quantity": Decimal("20.0")}])

    # 100 units already on inbound approved PO
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number="PO-OPEN-SUPPLY", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("1000.00"))
    db_session.add(po)
    await db_session.flush()
    pol = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=var_a.id, quantity_ordered=Decimal("100.0"), quantity_received=Decimal("0.0"), unit_price=Decimal("10.00"), line_total=Decimal("1000.00"))
    db_session.add(pol)
    await db_session.commit()

    rep_run = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    item_rec = next(it for it in rep_run.items if it.item_variant_id == var_a.id)

    assert item_rec.net_inventory_position == Decimal("120.0000")
    assert item_rec.suggested_reorder_quantity == Decimal("0.0000") # No redundant order
    assert item_rec.urgency_status in ["HEALTHY", "OVERSTOCKED"]

# ============================================================================
# 5. MANUFACTURING DEMAND & NON-DOUBLE-COUNTING
# ============================================================================

@pytest.mark.asyncio
async def test_manufacturing_non_double_counting(db_session: AsyncSession):
    """
    On-hand = 100
    Allocated = 30 (representing a RELEASED Work Order already reserving stock)
    Inbound PO = 20
    Planned Unreserved WO demand = 15

    Expected NIP = (100 - 30) + 20 - 15 = 75.0000
    Verify the 30 units in quantity_allocated are NOT subtracted twice.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, _ = await create_replenishment_test_environment(db_session, tenant_id)

    await StockEngine.post_transaction(db_session, tenant_id, "STOCK_RECEIPT", [{"destination_location_bin_id": bin_storage.id, "item_variant_id": var_a.id, "quantity": Decimal("100.0")}])
    bal = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.warehouse_id == wh.id, StockBalanceCache.item_variant_id == var_a.id))).scalar_one()
    bal.quantity_allocated = Decimal("30.0")

    # Inbound PO = 20
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number="PO-MFG-INBOUND", supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("200.00"))
    db_session.add(po)
    await db_session.flush()
    pol = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=var_a.id, quantity_ordered=Decimal("20.0"), quantity_received=Decimal("0.0"), unit_price=Decimal("10.00"), line_total=Decimal("200.00"))
    db_session.add(pol)

    # PLANNED WO = 15
    bom = BillOfMaterials(id=str(uuid.uuid4()), tenant_id=tenant_id, bom_number="BOM-MFG-DEM", name="Assy", item_variant_id=var_a.id, version="1.0", status="ACTIVE")
    db_session.add(bom)
    await db_session.flush()
    wo = WorkOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, work_order_number="WO-MFG-DEM", bom_id=bom.id, item_variant_id=var_a.id, warehouse_id=wh.id, staging_bin_id=bin_storage.id, destination_bin_id=bin_storage.id, status="PLANNED", quantity_to_produce=Decimal("15.0"))
    db_session.add(wo)
    await db_session.flush()
    woc = WorkOrderComponent(id=str(uuid.uuid4()), work_order_id=wo.id, component_variant_id=var_a.id, quantity_required=Decimal("15.0"), quantity_consumed=Decimal("0.0"))
    db_session.add(woc)
    await db_session.commit()

    rep_run = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    item_rec = next(it for it in rep_run.items if it.item_variant_id == var_a.id)

    assert item_rec.quantity_available == Decimal("70.0000") # 100 - 30
    assert item_rec.quantity_incoming == Decimal("20.0000")
    assert item_rec.quantity_mfg_planned == Decimal("15.0000")
    assert item_rec.net_inventory_position == Decimal("75.0000")

# ============================================================================
# 6. DETERMINISTIC SUPPLIER SELECTION
# ============================================================================

@pytest.mark.asyncio
async def test_deterministic_supplier_selection(db_session: AsyncSession):
    """
    Preferred Supplier vs Cheaper Supplier:
    - Supplier A: $12.00, is_preferred = True
    - Supplier B: $8.00, is_preferred = False
    Preferred supplier takes precedence.
    When preferred is deactivated, cheapest active supplier is selected.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp_a, sp_a = await create_replenishment_test_environment(db_session, tenant_id)

    sp_a.unit_cost = Decimal("12.00")
    sp_a.is_preferred = True

    # Supplier B (Cheaper but not preferred)
    supp_b = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-B-{uuid.uuid4().hex[:4]}", name="Discount Supplier", currency="USD", is_active=True)
    db_session.add(supp_b)
    await db_session.flush()

    sp_b = SupplierProduct(
        id=str(uuid.uuid4()), tenant_id=tenant_id, supplier_id=supp_b.id, item_variant_id=var_a.id,
        supplier_sku="DISC-RELAY", unit_cost=Decimal("8.00"), currency="USD",
        minimum_order_quantity=Decimal("1.0"), pack_size=Decimal("1.0"), lead_time_days=14,
        is_preferred=False, is_active=True
    )
    db_session.add(sp_b)
    await db_session.commit()

    # 1. Preferred supplier selected
    run1 = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    rec1 = next(it for it in run1.items if it.item_variant_id == var_a.id)
    assert rec1.supplier_id == supp_a.id
    assert rec1.estimated_unit_cost == Decimal("12.0000")

    # 2. Deactivate Preferred Supplier -> Cheaper supplier takes over
    sp_a.is_active = False
    await db_session.commit()

    run2 = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    rec2 = next(it for it in run2.items if it.item_variant_id == var_a.id)
    assert rec2.supplier_id == supp_b.id
    assert rec2.estimated_unit_cost == Decimal("8.0000")

# ============================================================================
# 7. MULTI-WAREHOUSE AND MULTI-SUPPLIER GROUPING
# ============================================================================

@pytest.mark.asyncio
async def test_multi_warehouse_and_multi_supplier_draft_po_grouping(db_session: AsyncSession):
    """
    Creates recommendations across:
    - WH-A + Supplier-A
    - WH-B + Supplier-A
    - WH-A + Supplier-B
    Converts all into draft POs and verifies exactly 3 distinct Purchase Orders are created.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh_a, bin_a, var_a, supp_a, _ = await create_replenishment_test_environment(db_session, tenant_id)

    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-B-{uuid.uuid4().hex[:4]}", name="Secondary DC")
    supp_b = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-B-{uuid.uuid4().hex[:4]}", name="Global Parts", currency="USD", is_active=True)
    db_session.add_all([wh_b, supp_b])
    await db_session.flush()

    run = ReplenishmentRun(id=str(uuid.uuid4()), tenant_id=tenant_id, run_number="RPL-MULTI-GROUP", status="COMPLETED")
    db_session.add(run)
    await db_session.flush()

    # Recommendation 1: WH-A + Supp-A
    r1 = ReplenishmentRecommendationItem(
        id=str(uuid.uuid4()), run_id=run.id, tenant_id=tenant_id, warehouse_id=wh_a.id, item_variant_id=var_a.id,
        supplier_id=supp_a.id, quantity_on_hand=Decimal("0.0"), quantity_allocated=Decimal("0.0"), quantity_available=Decimal("0.0"),
        quantity_incoming=Decimal("0.0"), net_inventory_position=Decimal("0.0"), average_daily_usage=Decimal("5.0"),
        lead_time_days=10, safety_stock=Decimal("10.0"), reorder_point=Decimal("60.0"), target_maximum_stock=Decimal("100.0"),
        minimum_order_quantity=Decimal("10.0"), pack_size=Decimal("5.0"), suggested_reorder_quantity=Decimal("50.0"),
        estimated_unit_cost=Decimal("10.00"), estimated_total_cost=Decimal("500.00"), urgency_status="REORDER_NOW",
        suggested_order_date=get_utc_now(), action_status="PENDING"
    )
    # Recommendation 2: WH-B + Supp-A
    r2 = ReplenishmentRecommendationItem(
        id=str(uuid.uuid4()), run_id=run.id, tenant_id=tenant_id, warehouse_id=wh_b.id, item_variant_id=var_a.id,
        supplier_id=supp_a.id, quantity_on_hand=Decimal("0.0"), quantity_allocated=Decimal("0.0"), quantity_available=Decimal("0.0"),
        quantity_incoming=Decimal("0.0"), net_inventory_position=Decimal("0.0"), average_daily_usage=Decimal("5.0"),
        lead_time_days=10, safety_stock=Decimal("10.0"), reorder_point=Decimal("60.0"), target_maximum_stock=Decimal("100.0"),
        minimum_order_quantity=Decimal("10.0"), pack_size=Decimal("5.0"), suggested_reorder_quantity=Decimal("50.0"),
        estimated_unit_cost=Decimal("10.00"), estimated_total_cost=Decimal("500.00"), urgency_status="REORDER_NOW",
        suggested_order_date=get_utc_now(), action_status="PENDING"
    )
    # Recommendation 3: WH-A + Supp-B
    r3 = ReplenishmentRecommendationItem(
        id=str(uuid.uuid4()), run_id=run.id, tenant_id=tenant_id, warehouse_id=wh_a.id, item_variant_id=var_a.id,
        supplier_id=supp_b.id, quantity_on_hand=Decimal("0.0"), quantity_allocated=Decimal("0.0"), quantity_available=Decimal("0.0"),
        quantity_incoming=Decimal("0.0"), net_inventory_position=Decimal("0.0"), average_daily_usage=Decimal("5.0"),
        lead_time_days=10, safety_stock=Decimal("10.0"), reorder_point=Decimal("60.0"), target_maximum_stock=Decimal("100.0"),
        minimum_order_quantity=Decimal("10.0"), pack_size=Decimal("5.0"), suggested_reorder_quantity=Decimal("50.0"),
        estimated_unit_cost=Decimal("10.00"), estimated_total_cost=Decimal("500.00"), urgency_status="REORDER_NOW",
        suggested_order_date=get_utc_now(), action_status="PENDING"
    )
    db_session.add_all([r1, r2, r3])
    await db_session.commit()

    resp = await ReplenishmentService.generate_draft_purchase_orders(
        db_session, tenant_id, GenerateDraftPOsRequest(recommendation_item_ids=[r1.id, r2.id, r3.id])
    )
    assert resp.generated_orders_count == 3
    combos = {(po.supplier_id, po.warehouse_id) for po in resp.purchase_orders}
    assert (supp_a.id, wh_a.id) in combos
    assert (supp_a.id, wh_b.id) in combos
    assert (supp_b.id, wh_a.id) in combos

# ============================================================================
# 8. DRAFT-ONLY SAFETY INVARIANT
# ============================================================================

@pytest.mark.asyncio
async def test_draft_only_safety_invariant(db_session: AsyncSession):
    """
    Asserts that automated replenishment only ever generates DRAFT Purchase Orders.
    Zero silent spend authorization, zero stock transactions, zero cost layers created.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_storage, var_a, supp, _ = await create_replenishment_test_environment(db_session, tenant_id)

    rep_run = await ReplenishmentService.execute_replenishment_run(db_session, tenant_id, warehouse_id=wh.id)
    pending_items = [it for it in rep_run.items if it.item_variant_id == var_a.id and it.suggested_reorder_quantity > 0]
    selected_id = pending_items[0].id

    resp = await ReplenishmentService.generate_draft_purchase_orders(
        db_session, tenant_id, GenerateDraftPOsRequest(recommendation_item_ids=[selected_id])
    )
    po_id = resp.purchase_orders[0].purchase_order_id

    po = (await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one()
    assert po.status == "DRAFT"
    assert po.approved_at is None
    assert po.approved_by_user_id is None

    # Verify no stock movements or cost layers exist for this PO
    stock_txs = (await db_session.execute(
        select(StockLedgerTransaction).where(StockLedgerTransaction.reference_document_id == po.id)
    )).scalars().all()
    assert len(stock_txs) == 0

    cost_layers = (await db_session.execute(
        select(CostLayer).where(CostLayer.item_variant_id == var_a.id, CostLayer.status == "ACTIVE")
    )).scalars().all()
    assert len(cost_layers) == 0
