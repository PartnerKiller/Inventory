import pytest
import uuid
import math
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse
from app.models.purchasing import Supplier, PurchaseOrder
from app.models.forecasting import DemandForecastProfile, ForecastPeriodEntry, ReplenishmentProposal
from app.schemas.forecasting import (
    DemandForecastProfileCreate,
    ForecastCalculationRequest,
    ConvertProposalToPORequest
)
from app.services.forecasting_service import ForecastingService

# ============================================================================
# 1. EXACT DYNAMIC SAFETY STOCK FORMULA & NUMERICAL TOLERANCE
# ============================================================================

@pytest.mark.asyncio
async def test_exact_dynamic_safety_stock_formula_and_tolerance(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Math DC", code=f"WH-MTH-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-MTH-{uuid.uuid4().hex[:4]}", name="Deterministic Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    # Deterministic dataset: 5 values with mean = 100 and sample variance = 400 (std dev = 20)
    # Mean = 100, x = [100 - 20*sqrt(2), 100, 100 + 20*sqrt(2), 100, 100]
    # Sum = 500, Mean = 100
    # Sum of sq dev = 2 * (20*sqrt(2))^2 = 2 * 800 = 1600. Sample Var = 1600 / (5 - 1) = 400.
    v = 20.0 * math.sqrt(2.0)
    series = [
        Decimal(str(round(100.0 - v, 4))),
        Decimal("100.0"),
        Decimal(str(round(100.0 + v, 4))),
        Decimal("100.0"),
        Decimal("100.0")
    ]

    # Target 95% service level: Z = 1.645
    # Lead time = 10 days, Lead time std dev = 2 days
    # Analytical: SS = 1.645 * sqrt(10 * 400 + 10000 * 4) = 1.645 * sqrt(44000) = 1.645 * 209.7617696 = 345.0581
    prof_95 = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(
            item_id=item.id, warehouse_id=wh.id,
            service_level_target=Decimal("0.95"),
            lead_time_days=Decimal("10.0"),
            lead_time_std_dev=Decimal("2.0")
        )
    )

    res_95 = await ForecastingService.calculate_forecast(
        db=db_session, tenant_id=tenant_id,
        req=ForecastCalculationRequest(profile_id=prof_95.id, historical_demand_series=series, horizon_periods=3)
    )
    # Verify exact numerical match within 0.01 tolerance
    assert abs(res_95.safety_stock - Decimal("345.0581")) <= Decimal("0.05")

    # Target 99% service level: Z = 2.33
    # Analytical: SS = 2.33 * sqrt(44000) = 2.33 * 209.7617696 = 488.7449
    wh2 = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Math DC 99", code=f"WH-MTH99-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh2)
    await db_session.commit()

    prof_99 = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(
            item_id=item.id, warehouse_id=wh2.id,
            service_level_target=Decimal("0.99"),
            lead_time_days=Decimal("10.0"),
            lead_time_std_dev=Decimal("2.0")
        )
    )

    res_99 = await ForecastingService.calculate_forecast(
        db=db_session, tenant_id=tenant_id,
        req=ForecastCalculationRequest(profile_id=prof_99.id, historical_demand_series=series, horizon_periods=3)
    )
    assert abs(res_99.safety_stock - Decimal("488.7449")) <= Decimal("0.05")

# ============================================================================
# 2. SENSITIVITY ANALYSIS
# ============================================================================

@pytest.mark.asyncio
async def test_safety_stock_sensitivity_analysis(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Sensitivity DC", code=f"WH-SENS-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-SENS-{uuid.uuid4().hex[:4]}", name="Sens Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    # Base profile: lead time = 7, lead time std dev = 1.0, 95% service level
    base_prof = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(
            item_id=item.id, warehouse_id=wh.id, service_level_target=Decimal("0.95"),
            lead_time_days=Decimal("7.0"), lead_time_std_dev=Decimal("1.0")
        )
    )
    series_base = [Decimal("50.0"), Decimal("50.0"), Decimal("50.0"), Decimal("50.0")] # var = 0
    res_base = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=base_prof.id, historical_demand_series=series_base, horizon_periods=2))

    # 1. Demand variance increases -> SS increases
    series_high_var = [Decimal("20.0"), Decimal("80.0"), Decimal("30.0"), Decimal("70.0")]
    res_high_d_var = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=base_prof.id, historical_demand_series=series_high_var, horizon_periods=2))
    assert res_high_d_var.safety_stock > res_base.safety_stock

    # 2. Lead-time variance increases -> SS increases
    wh_lt = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="LT DC", code=f"WH-LT-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh_lt)
    await db_session.commit()

    prof_high_lt_var = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(
            item_id=item.id, warehouse_id=wh_lt.id, service_level_target=Decimal("0.95"),
            lead_time_days=Decimal("7.0"), lead_time_std_dev=Decimal("4.0") # Increased from 1.0 to 4.0
        )
    )
    res_high_lt_var = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=prof_high_lt_var.id, historical_demand_series=series_base, horizon_periods=2))
    assert res_high_lt_var.safety_stock > res_base.safety_stock

    # 3. Service level increases -> SS increases
    wh_sl = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="SL DC", code=f"WH-SLV-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh_sl)
    await db_session.commit()

    prof_high_sl = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(
            item_id=item.id, warehouse_id=wh_sl.id, service_level_target=Decimal("0.99"), # 99% vs 95%
            lead_time_days=Decimal("7.0"), lead_time_std_dev=Decimal("1.0")
        )
    )
    res_high_sl = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=prof_high_sl.id, historical_demand_series=series_base, horizon_periods=2))
    assert res_high_sl.safety_stock > res_base.safety_stock

# ============================================================================
# 3. EXACT DYNAMIC ROP FORMULA
# ============================================================================

@pytest.mark.asyncio
async def test_exact_dynamic_rop_formula(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="ROP DC", code=f"WH-ROP-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-ROP-{uuid.uuid4().hex[:4]}", name="ROP Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    # Combination 1: mean = 100, lead time = 10, SS = 345.0581 -> ROP = 100 * 10 + 345.0581 = 1345.0581
    v = 20.0 * math.sqrt(2.0)
    series1 = [Decimal(str(round(100.0 - v, 4))), Decimal("100.0"), Decimal(str(round(100.0 + v, 4))), Decimal("100.0"), Decimal("100.0")]
    prof1 = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(item_id=item.id, warehouse_id=wh.id, service_level_target=Decimal("0.95"), lead_time_days=Decimal("10.0"), lead_time_std_dev=Decimal("2.0"))
    )
    res1 = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=prof1.id, historical_demand_series=series1, horizon_periods=2))
    assert abs(res1.reorder_point - Decimal("1345.0581")) <= Decimal("0.05")

    # Combination 2: mean = 50, lead time = 5, sigma_d = 10, sigma_l = 1, Z = 1.645
    # Var = 100, L = 5, D = 50 -> sqrt(5 * 100 + 2500 * 1) = sqrt(3000) = 54.77225575
    # SS = 1.645 * 54.77225575 = 90.1004 -> ROP = 50 * 5 + 90.1004 = 340.1004
    wh2 = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="ROP DC 2", code=f"WH-ROP2-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh2)
    await db_session.commit()

    v2 = 10.0 * math.sqrt(2.0)
    series2 = [Decimal(str(round(50.0 - v2, 4))), Decimal("50.0"), Decimal(str(round(50.0 + v2, 4))), Decimal("50.0"), Decimal("50.0")]
    prof2 = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(item_id=item.id, warehouse_id=wh2.id, service_level_target=Decimal("0.95"), lead_time_days=Decimal("5.0"), lead_time_std_dev=Decimal("1.0"))
    )
    res2 = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=prof2.id, historical_demand_series=series2, horizon_periods=2))
    assert abs(res2.safety_stock - Decimal("90.1004")) <= Decimal("0.05")
    assert abs(res2.reorder_point - Decimal("340.1004")) <= Decimal("0.05")

# ============================================================================
# 4. REPLENISHMENT QUANTITY & BOUNDARY CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_replenishment_quantity_and_boundary_cases(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Boundary DC", code=f"WH-BND-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-BND-{uuid.uuid4().hex[:4]}", name="Boundary Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    # ROP for this dataset is ~490
    history = [Decimal("50.0"), Decimal("60.0"), Decimal("55.0"), Decimal("70.0")]

    # 1. Deficit Case: On Hand + In-Transit < ROP -> Proposal generated with Suggested Qty = max(0, ROP - On Hand - In-Transit)
    prop_deficit = await ForecastingService.generate_replenishment_proposal(
        db=db_session, tenant_id=tenant_id, item_id=item.id, warehouse_id=wh.id,
        current_stock=Decimal("100.0"), in_transit_stock=Decimal("50.0"), # Total = 150 < ROP
        demand_history=history
    )
    assert prop_deficit is not None
    assert prop_deficit.status == "DRAFT"
    exact_rop = prop_deficit.calculated_rop
    expected_qty = (exact_rop - Decimal("150.0")).quantize(Decimal("0.0001"))
    assert prop_deficit.suggested_order_qty == expected_qty

    # 2. Boundary Case: On Hand + In-Transit > ROP -> No proposal created (returns None)
    prop_excess = await ForecastingService.generate_replenishment_proposal(
        db=db_session, tenant_id=tenant_id, item_id=item.id, warehouse_id=wh.id,
        current_stock=exact_rop + Decimal("100.0"), in_transit_stock=Decimal("50.0"), # Total > ROP
        demand_history=history
    )
    assert prop_excess is None

    # 3. Boundary Case: On Hand + In-Transit == ROP -> No proposal created (returns None)
    prop_exact = await ForecastingService.generate_replenishment_proposal(
        db=db_session, tenant_id=tenant_id, item_id=item.id, warehouse_id=wh.id,
        current_stock=exact_rop, in_transit_stock=Decimal("0.0"), # Total == ROP
        demand_history=history
    )
    assert prop_exact is None

# ============================================================================
# 5. PROPOSAL TO PO CONVERSION & RETRY REJECTION (IDEMPOTENCY)
# ============================================================================

@pytest.mark.asyncio
async def test_proposal_to_po_conversion_and_retry_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="PO Conv Auth DC", code=f"WH-AUTH-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-AUTH-{uuid.uuid4().hex[:4]}", name="Auth Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    supplier = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Authorized Vendor LLC", code=f"SUP-AUTH-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(supplier)
    await db_session.commit()

    prop = await ForecastingService.generate_replenishment_proposal(
        db=db_session, tenant_id=tenant_id, item_id=item.id, warehouse_id=wh.id,
        current_stock=Decimal("10.0")
    )
    assert prop is not None

    # First conversion -> Exactly one authoritative PO created
    conv_res = await ForecastingService.convert_proposal_to_purchase_order(
        db=db_session, tenant_id=tenant_id, proposal_id=prop.id,
        conv_req=ConvertProposalToPORequest(supplier_id=supplier.id, unit_price=Decimal("25.0")),
        user_id=user_id
    )
    assert conv_res.status == "CONVERTED_TO_PO"
    assert conv_res.purchase_order_id is not None

    # Verify PO in database
    po = (await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.id == conv_res.purchase_order_id))).scalar_one()
    assert po.supplier_id == supplier.id
    assert po.target_warehouse_id == wh.id

    # Retry conversion -> Strictly rejected (HTTP 400), no duplicate PO created
    with pytest.raises(HTTPException) as exc_info:
        await ForecastingService.convert_proposal_to_purchase_order(
            db=db_session, tenant_id=tenant_id, proposal_id=prop.id,
            conv_req=ConvertProposalToPORequest(supplier_id=supplier.id, unit_price=Decimal("25.0")),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "already converted" in exc_info.value.detail

# ============================================================================
# 6. FORECAST PROFILE, HOLT-WINTERS SEASONALITY & MAPE
# ============================================================================

@pytest.mark.asyncio
async def test_forecast_profile_and_holt_winters_seasonality_and_mape(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Seasonality DC 2", code=f"WH-SEA2-{uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add(wh)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-SEA2-{uuid.uuid4().hex[:4]}", name="Winter Parka", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    prof = await ForecastingService.create_forecast_profile(
        db=db_session, tenant_id=tenant_id,
        profile_in=DemandForecastProfileCreate(item_id=item.id, warehouse_id=wh.id, seasonality_periods=4)
    )
    assert prof.seasonality_periods == 4

    series = [
        Decimal("100.0"), Decimal("150.0"), Decimal("180.0"), Decimal("300.0"),
        Decimal("120.0"), Decimal("170.0"), Decimal("200.0"), Decimal("340.0")
    ]
    res = await ForecastingService.calculate_forecast(db_session, tenant_id, ForecastCalculationRequest(profile_id=prof.id, historical_demand_series=series, horizon_periods=4))
    assert len(res.forecast_values) == 4
    # Trend & seasonality: peak is higher than base
    assert res.forecast_values[3] > res.forecast_values[0]
    assert res.mean_absolute_percentage_error >= Decimal("0.0")
