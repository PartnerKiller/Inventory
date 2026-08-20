import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.fixed_asset import FixedAssetClass, FixedAsset, DepreciationScheduleEntry, AssetImprovement
from app.models.maintenance import MaintenanceSchedule, MaintenanceWorkOrder, MWOSparePart
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.fixed_asset import FixedAssetClassCreate, FixedAssetCreate
from app.schemas.maintenance import (
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderComplete,
    MWOSparePartCreate
)
from app.services.fixed_asset_service import FixedAssetService
from app.services.maintenance_service import MaintenanceService
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService

# ============================================================================
# 1. CAPITAL IMPROVEMENT MWO COMPLETION, GL CAPITALIZATION & RECALCULATION
# ============================================================================

@pytest.mark.asyncio
async def test_capital_improvement_mwo_completion_and_gl_capitalization(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    # 1. Create Asset Class & Capitalized Fixed Asset ($10,000, 60 months)
    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"PLANT-{uuid.uuid4().hex[:4].upper()}",
            class_name="Heavy Industrial Machinery",
            depreciation_method="STRAIGHT_LINE",
            useful_life_months=60
        )
    )

    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-CNC-{uuid.uuid4().hex[:4].upper()}",
            asset_name="5-Axis CNC Milling Center",
            asset_class_id=ac.id,
            purchase_cost=Decimal("10000.0"),
            salvage_value=Decimal("0.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            depreciation_method="STRAIGHT_LINE",
            useful_life_months=60
        ),
        user_id=user_id
    )

    # 2. Setup Warehouse Bin and High-Value Spindle Engine ($2,400.00)
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-CAP-{uuid.uuid4().hex[:4]}", name="Capital Equipment WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-CAP-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-SPINDLE-{uuid.uuid4().hex[:4]}", name="High-Power Spindle Motor", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Spindle Motor 15kW", cost_price=Decimal("2400.0"), selling_price=Decimal("3500.0"))
    db_session.add(var)
    await db_session.flush()

    # Stock Opening: 2 units @ $2,400.00
    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_loc.id, "quantity": Decimal("2.0"), "unit_cost": Decimal("2400.0")}],
        user_id=user_id
    )

    # 3. Create Capital Improvement MWO (1 unit @ $2,400.00, +12 months useful life)
    mwo = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(
            asset_id=asset_res.id,
            priority="CRITICAL",
            expenditure_type="CAPITAL_IMPROVEMENT",
            useful_life_extension_months=12,
            notes="Full CNC Spindle Motor Retrofit and Capacity Upgrade",
            spare_parts=[
                MWOSparePartCreate(
                    item_variant_id=var.id,
                    warehouse_id=wh.id,
                    location_bin_id=bin_loc.id,
                    quantity_required=Decimal("1.0"),
                    unit_cost=Decimal("2400.0")
                )
            ]
        )
    )

    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="SCHEDULED")
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="IN_PROGRESS")

    # 4. Complete MWO -> Triggers Capitalization and Schedule Recalculation
    comp_res = await MaintenanceService.complete_maintenance_work_order(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo.id,
        comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("8.0"), labor_hours=Decimal("12.0")),
        user_id=user_id
    )

    assert comp_res.status == "COMPLETED"
    assert comp_res.expenditure_type == "CAPITAL_IMPROVEMENT"
    assert comp_res.journal_voucher_id is not None

    # 5. Verify Capitalization GL Journal Voucher: Dr 1500 Fixed Assets / Cr 1200 Inventory
    jv = (await db_session.execute(
        select(JournalVoucher).where(JournalVoucher.id == comp_res.journal_voucher_id)
    )).scalar_one()
    assert jv.lines[0].debit_amount == Decimal("2400.0")
    # Verify Dr account is 1500 Fixed Assets (NOT 6150)
    acc_1500 = (await db_session.execute(select(GLAccount).where(GLAccount.id == jv.lines[0].account_id))).scalar_one()
    assert acc_1500.account_code == "1500"
    assert jv.lines[1].credit_amount == Decimal("2400.0")

    # 6. Verify Fixed Asset Carrying Cost and Useful Life Incremented
    updated_asset = (await db_session.execute(
        select(FixedAsset).where(FixedAsset.id == asset_res.id)
    )).scalar_one()
    assert updated_asset.purchase_cost == Decimal("12400.0") # 10,000 + 2,400
    assert updated_asset.current_book_value == Decimal("12400.0")
    assert updated_asset.useful_life_months == 72 # 60 + 12

    # 7. Verify AssetImprovement Record Created
    improvement = (await db_session.execute(
        select(AssetImprovement).where(AssetImprovement.mwo_id == mwo.id)
    )).scalar_one()
    assert improvement.capitalized_amount == Decimal("2400.0")
    assert improvement.useful_life_extension_months == 12
    assert improvement.status == "CAPITALIZED"

# ============================================================================
# 2. REVENUE EXPENSE REMAINS ORDINARY REPAIRS (DR 6150)
# ============================================================================

@pytest.mark.asyncio
async def test_ordinary_maintenance_remains_expensed_and_leaves_asset_untouched(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"VEH-{uuid.uuid4().hex[:4].upper()}",
            class_name="Delivery Fleet",
            depreciation_method="STRAIGHT_LINE",
            useful_life_months=48
        )
    )

    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-VAN-{uuid.uuid4().hex[:4].upper()}",
            asset_name="Cargo Delivery Van",
            asset_class_id=ac.id,
            purchase_cost=Decimal("5000.0"),
            salvage_value=Decimal("0.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            useful_life_months=48
        ),
        user_id=user_id
    )

    # Warehouse & Oil Filter ($50.00)
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-EXP-{uuid.uuid4().hex[:4]}", name="Van Parts WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-OIL-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-OIL-{uuid.uuid4().hex[:4]}", name="Engine Oil Filter", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Oil Filter Standard", cost_price=Decimal("50.0"), selling_price=Decimal("80.0"))
    db_session.add(var)
    await db_session.flush()

    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_loc.id, "quantity": Decimal("10.0"), "unit_cost": Decimal("50.0")}],
        user_id=user_id
    )

    # Ordinary Maintenance MWO (REVENUE_EXPENSE)
    mwo = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(
            asset_id=asset_res.id,
            priority="LOW",
            expenditure_type="REVENUE_EXPENSE",
            notes="Routine 10,000km Engine Oil and Filter Change",
            spare_parts=[
                MWOSparePartCreate(
                    item_variant_id=var.id,
                    warehouse_id=wh.id,
                    location_bin_id=bin_loc.id,
                    quantity_required=Decimal("1.0"),
                    unit_cost=Decimal("50.0")
                )
            ]
        )
    )

    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="SCHEDULED")
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="IN_PROGRESS")

    comp_res = await MaintenanceService.complete_maintenance_work_order(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo.id,
        comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("1.0"), labor_hours=Decimal("1.5")),
        user_id=user_id
    )

    assert comp_res.status == "COMPLETED"
    assert comp_res.expenditure_type == "REVENUE_EXPENSE"

    # GL Journal Voucher is Dr 6150 Maintenance Expense
    jv = (await db_session.execute(
        select(JournalVoucher).where(JournalVoucher.id == comp_res.journal_voucher_id)
    )).scalar_one()
    acc_6150 = (await db_session.execute(select(GLAccount).where(GLAccount.id == jv.lines[0].account_id))).scalar_one()
    assert acc_6150.account_code == "6150"

    # Asset carrying cost and useful life remain untouched
    asset_check = (await db_session.execute(
        select(FixedAsset).where(FixedAsset.id == asset_res.id)
    )).scalar_one()
    assert asset_check.purchase_cost == Decimal("5000.0")
    assert asset_check.useful_life_months == 48
