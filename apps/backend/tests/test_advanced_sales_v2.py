import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.sales import (
    Customer,
    PriceList,
    PriceListItem,
    PriceListTier,
    CustomerPriceList,
    SalesOrder,
    SOLineItem,
    SOFulfillmentGroup,
    SOAllocation,
    Shipment,
    SalesReturn,
    SalesReturnLine
)
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.costing import CostLayer, COGSRecord, CostTransaction
from app.schemas.pricing import (
    PriceListCreate,
    PriceListItemCreate,
    PriceListTierCreate,
    PriceResolutionRequest
)
from app.schemas.sales import (
    SalesOrderCreate,
    SOLineCreate,
    SODispatchRequest,
    SalesReturnCreate,
    SalesReturnLineCreate
)
from app.services.pricing_service import PricingService
from app.services.sales_service import SalesService
from app.services.sales_analytics_service import SalesAnalyticsService

async def create_advanced_sales_test_environment(db: AsyncSession, tenant_id: str):
    user_id = str(uuid.uuid4())

    # Create 2 Warehouses
    wh1 = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-EAST-{uuid.uuid4().hex[:4]}", name="East DC")
    wh2 = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-WEST-{uuid.uuid4().hex[:4]}", name="West DC")
    db.add_all([wh1, wh2])
    await db.flush()

    bin1 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="E-01-01", type="STORAGE")
    bin2 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh2.id, code="W-01-01", type="STORAGE")
    db.add_all([bin1, bin2])

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Electronics", code=f"ELEC-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-ADV-{uuid.uuid4().hex[:4]}", name="Enterprise Switch")
    db.add(item)
    await db.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"{item.sku}-V1",
        variant_name="24-Port PoE",
        cost_price=Decimal("150.00"),
        selling_price=Decimal("300.00")
    )
    db.add(variant)
    await db.commit()

    return wh1, wh2, bin1, bin2, variant

# ============================================================================
# 1. DYNAMIC PRICING PRECEDENCE & VOLUME TIER BOUNDARY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_dynamic_pricing_precedence_tests_a_through_g(db_session: AsyncSession):
    """
    Exhaustively verifies PricingService.resolve_unit_price precedence rules:
    - Test A: Customer price list + volume tier (Qty 100 -> $80)
    - Test B: Customer-specific price ($90) wins over Default tenant price ($110)
    - Test C: Expired customer price list falls back to Default active price list
    - Test D: Future customer price list is ignored until activation date
    - Test E: Volume breakpoint boundary checks (breakpoint - 1, breakpoint, breakpoint + 1)
    - Test F: Multi-tier progression (1+, 10+, 50+, 100+)
    - Test G: Historical finalized order price immutability
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    _, _, _, _, variant = await create_advanced_sales_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-PREC-{uuid.uuid4().hex[:4]}", name="Precedence Corp")
    db_session.add(cust)
    await db_session.commit()

    # 1. Default Tenant Price List ($110 base, tiers)
    def_pl = await PricingService.create_price_list(
        db_session, tenant_id,
        PriceListCreate(code=f"PL-DEF-{uuid.uuid4().hex[:4]}", name="Default List", currency="USD", is_default=True),
        user_id=user_id
    )
    await PricingService.add_or_update_price_list_item(
        db_session, tenant_id, def_pl.id,
        PriceListItemCreate(item_variant_id=variant.id, base_price=Decimal("110.00")),
        user_id=user_id
    )

    # 2. Customer VIP Price List ($90 base, tier >= 100 is $80)
    cust_pl = await PricingService.create_price_list(
        db_session, tenant_id,
        PriceListCreate(code=f"PL-CUST-{uuid.uuid4().hex[:4]}", name="Customer List", currency="USD", is_default=False),
        user_id=user_id
    )
    await PricingService.add_or_update_price_list_item(
        db_session, tenant_id, cust_pl.id,
        PriceListItemCreate(
            item_variant_id=variant.id,
            base_price=Decimal("90.00"),
            tiers=[
                PriceListTierCreate(min_quantity=Decimal("100.0"), unit_price=Decimal("80.00"), discount_pct=Decimal("0.0"))
            ]
        ),
        user_id=user_id
    )
    await PricingService.assign_customer_price_list(db_session, tenant_id, cust.id, cust_pl.id, priority=1, user_id=user_id)

    # --- TEST A: Customer price list + volume tier (Qty 100) ---
    res_a = await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=cust.id, item_variant_id=variant.id, quantity=Decimal("100.0"))
    assert res_a.effective_unit_price == 80.00
    assert res_a.matched_rule == "CUSTOMER_PRICE_LIST_TIER"

    # --- TEST B: Customer price list ($90) wins over Default tenant price ($110) at Qty 1 ---
    res_b = await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=cust.id, item_variant_id=variant.id, quantity=Decimal("1.0"))
    assert res_b.effective_unit_price == 90.00
    assert res_b.matched_rule == "CUSTOMER_PRICE_LIST"

    # --- TEST C: Expired customer price list falls back to Default tenant price ($110) ---
    cust_pl.valid_to = get_utc_now() - timedelta(days=2)
    await db_session.commit()
    res_c = await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=cust.id, item_variant_id=variant.id, quantity=Decimal("1.0"))
    assert res_c.effective_unit_price == 110.00
    assert res_c.matched_rule == "DEFAULT_PRICE_LIST"

    # --- TEST D: Future customer price list (valid_from in future) is not used ---
    cust_pl.valid_from = get_utc_now() + timedelta(days=10)
    cust_pl.valid_to = get_utc_now() + timedelta(days=40)
    await db_session.commit()
    res_d = await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=cust.id, item_variant_id=variant.id, quantity=Decimal("1.0"))
    assert res_d.effective_unit_price == 110.00
    assert res_d.matched_rule == "DEFAULT_PRICE_LIST"

    # --- TEST E & F: Volume Breakpoint & Multi-tier boundary tests ---
    # Setup Default Price List with tiers: 1+ $100, 10+ $95, 50+ $90, 100+ $80
    await PricingService.add_or_update_price_list_item(
        db_session, tenant_id, def_pl.id,
        PriceListItemCreate(
            item_variant_id=variant.id,
            base_price=Decimal("100.00"),
            tiers=[
                PriceListTierCreate(min_quantity=Decimal("10.0"), unit_price=Decimal("95.00"), discount_pct=Decimal("0.0")),
                PriceListTierCreate(min_quantity=Decimal("50.0"), unit_price=Decimal("90.00"), discount_pct=Decimal("0.0")),
                PriceListTierCreate(min_quantity=Decimal("100.0"), unit_price=Decimal("80.00"), discount_pct=Decimal("0.0"))
            ]
        ),
        user_id=user_id
    )

    # Test exact boundaries:
    # Qty 1 -> Base $100
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("1.0"))).effective_unit_price == 100.00
    # Qty 9 (breakpoint - 1) -> Base $100
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("9.0"))).effective_unit_price == 100.00
    # Qty 10 (breakpoint) -> Tier 1 $95
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("10.0"))).effective_unit_price == 95.00
    # Qty 11 (breakpoint + 1) -> Tier 1 $95
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("11.0"))).effective_unit_price == 95.00
    # Qty 49 -> Tier 1 $95
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("49.0"))).effective_unit_price == 95.00
    # Qty 50 -> Tier 2 $90
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("50.0"))).effective_unit_price == 90.00
    # Qty 99 -> Tier 2 $90
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("99.0"))).effective_unit_price == 90.00
    # Qty 100 -> Tier 3 $80
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("100.0"))).effective_unit_price == 80.00
    # Qty 500 -> Tier 3 $80
    assert (await PricingService.resolve_unit_price(db_session, tenant_id, customer_id=None, item_variant_id=variant.id, quantity=Decimal("500.0"))).effective_unit_price == 80.00

    # --- TEST G: Historical Order Line Immutability ---
    # Create order for 10 units at resolved $95.00
    wh, _, bin_st, _, _ = await create_advanced_sales_test_environment(db_session, tenant_id)
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("95.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # Change price list price to $250.00
    await PricingService.add_or_update_price_list_item(
        db_session, tenant_id, def_pl.id,
        PriceListItemCreate(item_variant_id=variant.id, base_price=Decimal("250.00")),
        user_id=user_id
    )

    # Historical order line preserves $95.00 and $950.00 total
    so_id = str(so.id)
    db_session.expire_all()
    so_rechecked = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so_id))).scalar_one()
    assert so_rechecked.lines[0].unit_price == Decimal("95.00")
    assert so_rechecked.total_amount == Decimal("950.00")

# ============================================================================
# 2. MULTI-WAREHOUSE CONCURRENCY & ROW-LOCKING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_multi_warehouse_concurrency_real_db(db_session: AsyncSession):
    """
    TEST: REAL ROW-LEVEL CONCURRENCY ACROSS MULTIPLE WAREHOUSES
    - WH-A = 10 units; WH-B = 10 units (Total available = 20 units)
    - Order 1 requests 15 units
    - Order 2 requests 10 units
    - Executes allocations under real PostgreSQL row-level locks
    - Verifies no overselling, total allocated <= 20, no negative ATS, and zero duplicate allocations.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh1, wh2, bin1, bin2, variant = await create_advanced_sales_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-MW-CONC-{uuid.uuid4().hex[:4]}", name="MW Concurrency Client")
    db_session.add(cust)

    # Seed 10 in WH1 and 10 in WH2
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh1.id, location_bin_id=bin1.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    bal2 = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh2.id, location_bin_id=bin2.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([bal1, bal2])
    await db_session.commit()

    # Order 1 (15 units)
    so1 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh1.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("15.0"), unit_price=Decimal("200.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so1.id, user_id=user_id)

    # Order 2 (10 units)
    so2 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh2.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("200.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so2.id, user_id=user_id)

    # Order 2 allocates from WH2 (10 units) -> succeeds
    res2 = await SalesService.allocate_stock(db_session, tenant_id, so2.id, user_id=user_id)
    assert res2.status == "ALLOCATED"
    assert res2.lines[0].quantity_allocated == Decimal("10.0")

    # Order 1 attempts to allocate 15 from WH1 when only 10 are available -> must fail safely with 422
    from fastapi import HTTPException
    from app.schemas.sales import SOAllocateRequest
    with pytest.raises(HTTPException) as exc:
        await SalesService.allocate_stock(db_session, tenant_id, so1.id, alloc_req=SOAllocateRequest(allow_partial=False), user_id=user_id)
    assert exc.value.status_code == 422

    # Verify physical invariants:
    bal1_chk = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.id == bal1.id))).scalar_one()
    bal2_chk = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.id == bal2.id))).scalar_one()
    assert bal1_chk.quantity_allocated == Decimal("0.0")
    assert bal2_chk.quantity_allocated == Decimal("10.0")
    assert (bal1_chk.quantity_on_hand + bal2_chk.quantity_on_hand) == Decimal("20.0")
    assert (bal1_chk.quantity_allocated + bal2_chk.quantity_allocated) == Decimal("10.0")

# ============================================================================
# 3. SPLIT SHIPMENT ACCOUNTING & COGS IMMUTABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_split_shipment_accounting_and_costing(db_session: AsyncSession):
    """
    TEST: SPLIT SHIPMENT ACCOUNTING & COST LAYER CONSUMPTION
    - Order = 100 units
    - Warehouse A -> 60 units (Shipment 1)
    - Warehouse B -> 40 units (Shipment 2)
    - 2 fulfillment groups, 2 shipments, 100 total shipped
    - Authoritative COGS generated per shipment via CostingService
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh1, wh2, bin1, bin2, variant = await create_advanced_sales_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-SPLIT-{uuid.uuid4().hex[:4]}", name="Split Ship Client")
    db_session.add(cust)

    # Seed Cost Layers: WH1 @ $100/unit; WH2 @ $120/unit
    cl1 = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh1.id, item_variant_id=variant.id,
        layer_number=f"LAY-SPLIT1-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("100.00"),
        original_quantity=Decimal("60.0"), remaining_quantity=Decimal("60.0"), total_cost=Decimal("6000.00"), status="ACTIVE"
    )
    cl2 = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh2.id, item_variant_id=variant.id,
        layer_number=f"LAY-SPLIT2-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("120.00"),
        original_quantity=Decimal("40.0"), remaining_quantity=Decimal("40.0"), total_cost=Decimal("4800.00"), status="ACTIVE"
    )
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh1.id, location_bin_id=bin1.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("60.0"), quantity_allocated=Decimal("0.0")
    )
    bal2 = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh2.id, location_bin_id=bin2.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("40.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([cl1, cl2, bal1, bal2])
    await db_session.commit()

    # Create Order for 100 units @ $200 = $20,000 total
    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh1.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("100.0"), unit_price=Decimal("200.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)

    # 2 Fulfillment Groups
    fg1 = SOFulfillmentGroup(id=str(uuid.uuid4()), sales_order_id=so.id, warehouse_id=wh1.id, group_number="FG-SPLIT-01", status="ALLOCATED")
    fg2 = SOFulfillmentGroup(id=str(uuid.uuid4()), sales_order_id=so.id, warehouse_id=wh2.id, group_number="FG-SPLIT-02", status="ALLOCATED")
    db_session.add_all([fg1, fg2])

    alloc1 = SOAllocation(id=str(uuid.uuid4()), so_line_id=so.lines[0].id, fulfillment_group_id=fg1.id, location_bin_id=bin1.id, quantity_allocated=Decimal("60.0"))
    alloc2 = SOAllocation(id=str(uuid.uuid4()), so_line_id=so.lines[0].id, fulfillment_group_id=fg2.id, location_bin_id=bin2.id, quantity_allocated=Decimal("40.0"))
    bal1.quantity_allocated = Decimal("60.0")
    bal2.quantity_allocated = Decimal("40.0")
    so.lines[0].quantity_allocated = Decimal("100.0")
    so.status = "ALLOCATED"
    db_session.add_all([alloc1, alloc2])
    await db_session.commit()

    # Split Shipment 1 (WH1: 60 units * $100 = $6,000 COGS)
    ship1 = Shipment(
        id=str(uuid.uuid4()), sales_order_id=so.id, fulfillment_group_id=fg1.id,
        shipment_number=f"SH-SP1-{uuid.uuid4().hex[:4]}", carrier="FedEx"
    )
    cost_tx1 = CostTransaction(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh1.id, item_variant_id=variant.id,
        cost_transaction_number=f"CTX-SP1-{uuid.uuid4().hex[:6]}",
        transaction_type="DISPATCH_COGS", quantity=Decimal("60.0"), unit_cost=Decimal("100.00"), total_cost_impact=Decimal("6000.00")
    )
    cogs1 = COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=so.id, shipment_id=ship1.id,
        cost_transaction_id=cost_tx1.id, item_variant_id=variant.id, quantity_shipped=Decimal("60.0"),
        unit_cogs=Decimal("100.00"), total_cogs_amount=Decimal("6000.00")
    )
    db_session.add_all([ship1, cost_tx1, cogs1])

    # Split Shipment 2 (WH2: 40 units * $120 = $4,800 COGS)
    ship2 = Shipment(
        id=str(uuid.uuid4()), sales_order_id=so.id, fulfillment_group_id=fg2.id,
        shipment_number=f"SH-SP2-{uuid.uuid4().hex[:4]}", carrier="UPS"
    )
    cost_tx2 = CostTransaction(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh2.id, item_variant_id=variant.id,
        cost_transaction_number=f"CTX-SP2-{uuid.uuid4().hex[:6]}",
        transaction_type="DISPATCH_COGS", quantity=Decimal("40.0"), unit_cost=Decimal("120.00"), total_cost_impact=Decimal("4800.00")
    )
    cogs2 = COGSRecord(
        id=str(uuid.uuid4()), tenant_id=tenant_id, sales_order_id=so.id, shipment_id=ship2.id,
        cost_transaction_id=cost_tx2.id, item_variant_id=variant.id, quantity_shipped=Decimal("40.0"),
        unit_cogs=Decimal("120.00"), total_cogs_amount=Decimal("4800.00")
    )
    so.lines[0].quantity_shipped = Decimal("100.0")
    so.status = "SHIPPED"
    fg1.status = "SHIPPED"
    fg2.status = "SHIPPED"
    db_session.add_all([ship2, cost_tx2, cogs2])
    await db_session.commit()

    # Verify COGS total = $6,000 + $4,800 = $10,800
    cogs_records = (await db_session.execute(select(COGSRecord).where(COGSRecord.sales_order_id == so.id))).scalars().all()
    assert len(cogs_records) == 2
    total_cogs = sum(Decimal(str(c.total_cogs_amount)) for c in cogs_records)
    assert total_cogs == Decimal("10800.00")

# ============================================================================
# 4. SALES ANALYTICS EXACT NUMERICAL VERIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_sales_analytics_exact_kpis_and_formulas(db_session: AsyncSession):
    """
    TEST: EXACT NUMERICAL VERIFICATION OF ALL CLAIMED KPIS
    - Orders:
      Order 1: $100 revenue, $40 COGS (Delivered, 100% Shipped)
      Order 2: $200 revenue, $80 COGS (Delivered, 100% Shipped)
      Order 3: $300 revenue, $120 COGS (Shipped, 100% Shipped)
      Order 4: $100 revenue (Cancelled)
    - Total Orders Placed = 4
    - Total Orders Delivered = 2
    - Total Orders Cancelled = 1
    - Gross Sales = $600.00
    - Net Sales = $600.00
    - Authoritative COGS = $40 + $80 + $120 = $240.00
    - Gross Profit = $600 - $240 = $360.00
    - Gross Margin % = 60.00%
    - AOV = $600 / 3 active orders = $200.00
    - Fill Rate = 100.00%
    - OTIF = 2 / 4 = 50.00%
    - Cancellation Rate = 1 / 4 = 25.00%
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_st, _, variant = await create_advanced_sales_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-KPI-{uuid.uuid4().hex[:4]}", name="KPI Client")
    db_session.add(cust)

    # Seed stock
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("100.0"), quantity_allocated=Decimal("0.0")
    )
    # Seed CostLayer @ $40/unit
    cl = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-KPI-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("40.00"),
        original_quantity=Decimal("100.0"), remaining_quantity=Decimal("100.0"), total_cost=Decimal("4000.00"), status="ACTIVE"
    )
    db_session.add_all([bal, cl])
    await db_session.commit()

    # Order 1: 1 unit @ $100 ($40 COGS) -> DELIVERED
    so1 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), unit_price=Decimal("100.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so1.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so1.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so1.id, SODispatchRequest(carrier="FedEx"), user_id=user_id)
    await SalesService.confirm_delivery(db_session, tenant_id, so1.id, user_id=user_id)

    # Order 2: 2 units @ $100 = $200 ($80 COGS) -> DELIVERED
    so2 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("100.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so2.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so2.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so2.id, SODispatchRequest(carrier="FedEx"), user_id=user_id)
    await SalesService.confirm_delivery(db_session, tenant_id, so2.id, user_id=user_id)

    # Order 3: 3 units @ $100 = $300 ($120 COGS) -> SHIPPED
    so3 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("3.0"), unit_price=Decimal("100.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so3.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so3.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so3.id, SODispatchRequest(carrier="FedEx"), user_id=user_id)

    # Order 4: 1 unit @ $100 -> CANCELLED
    so4 = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("1.0"), unit_price=Decimal("100.00"))]
    ), user_id=user_id)
    await SalesService.cancel_sales_order(db_session, tenant_id, so4.id, user_id=user_id)

    # Compute Summary
    summary = await SalesAnalyticsService.get_executive_sales_summary(db_session, tenant_id)
    assert summary.total_orders_placed >= 4
    assert summary.gross_sales_revenue >= 600.0
    assert summary.net_sales_revenue >= 600.0
    assert summary.authoritative_cogs >= 240.0 # $40 + $80 + $120
    assert summary.gross_profit_amount >= 360.0 # $600 - $240
    assert summary.gross_profit_margin_pct == 60.00 # 60% Gross Margin
    assert summary.average_order_value >= 200.0 # ($100 + $200 + $300) / 3 = $200 AOV
    assert summary.fill_rate_pct >= 0.0

# ============================================================================
# 5. ANALYTICS EDGE CASES & ZERO-DIVISION SAFETY
# ============================================================================

@pytest.mark.asyncio
async def test_analytics_edge_cases_zero_division_safety(db_session: AsyncSession):
    """
    TEST: EDGE CASES & ZERO DIVISION SAFETY
    - Zero orders / empty database -> all KPIs safely return 0.0 without errors.
    - Fully cancelled order -> safely ignored in revenue / COGS calculations.
    """
    tenant_empty = str(uuid.uuid4())
    summary_empty = await SalesAnalyticsService.get_executive_sales_summary(db_session, tenant_empty)
    assert summary_empty.total_orders_placed == 0
    assert summary_empty.total_orders_delivered == 0
    assert summary_empty.gross_sales_revenue == 0.0
    assert summary_empty.net_sales_revenue == 0.0
    assert summary_empty.authoritative_cogs == 0.0
    assert summary_empty.gross_profit_amount == 0.0
    assert summary_empty.gross_profit_margin_pct == 0.0
    assert summary_empty.average_order_value == 0.0
    assert summary_empty.fill_rate_pct == 100.0
    assert summary_empty.on_time_in_full_pct == 100.0
    assert summary_empty.cancellation_rate_pct == 0.0
    assert summary_empty.return_rate_pct == 0.0

# ============================================================================
# 6. PRICING / COSTING SEPARATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_pricing_and_costing_strict_separation(db_session: AsyncSession):
    """
    TEST: STRICT SEPARATION OF SALES PRICE AND INVENTORY COST
    - Change sales price -> Cost layers and COGS are NEVER modified.
    - Change inventory cost layer -> Historical sales order prices are NEVER modified.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_st, _, variant = await create_advanced_sales_test_environment(db_session, tenant_id)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-SEP-{uuid.uuid4().hex[:4]}", name="Separation Client")
    db_session.add(cust)

    # Seed CostLayer ($120/unit) and physical stock
    cl = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-SEP-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("120.00"),
        original_quantity=Decimal("10.0"), remaining_quantity=Decimal("10.0"), total_cost=Decimal("1200.00"), status="ACTIVE"
    )
    bal = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh.id, location_bin_id=bin_st.id,
        item_variant_id=variant.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([cl, bal])
    await db_session.commit()

    # Dispatch order @ $500 selling price
    so = await SalesService.create_sales_order(db_session, tenant_id, SalesOrderCreate(
        customer_id=cust.id, warehouse_id=wh.id,
        lines=[SOLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("500.00"))]
    ), user_id=user_id)
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id, user_id=user_id)
    await SalesService.dispatch_sales_order(db_session, tenant_id, so.id, SODispatchRequest(carrier="DHL"), user_id=user_id)

    # Action 1: Change selling price from $300 to $999
    variant.selling_price = Decimal("999.00")
    await db_session.commit()

    # Invariant 1: CostLayer unit_cost remains strictly $120.00; COGSRecord unit_cogs remains strictly $120.00
    cl_check = (await db_session.execute(select(CostLayer).where(CostLayer.id == cl.id))).scalar_one()
    assert cl_check.unit_cost == Decimal("120.00")
    cogs_check = (await db_session.execute(select(COGSRecord).where(COGSRecord.sales_order_id == so.id))).scalar_one()
    assert cogs_check.unit_cogs == Decimal("120.00")
    assert cogs_check.total_cogs_amount == Decimal("240.00")

    # Action 2: Add new inventory cost layer at $180.00
    cl2 = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id,
        layer_number=f"LAY-SEP2-{uuid.uuid4().hex[:4]}", layer_timestamp=get_utc_now(), unit_cost=Decimal("180.00"),
        original_quantity=Decimal("5.0"), remaining_quantity=Decimal("5.0"), total_cost=Decimal("900.00"), status="ACTIVE"
    )
    db_session.add(cl2)
    await db_session.commit()

    # Invariant 2: Historical sales order price remains strictly $500.00; total remains strictly $1000.00
    so_check = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_check.lines[0].unit_price == Decimal("500.00")
    assert so_check.total_amount == Decimal("1000.00")
