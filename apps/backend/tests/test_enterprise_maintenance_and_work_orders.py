import pytest
import uuid
import asyncio
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
from app.models.fixed_asset import FixedAsset
from app.models.advanced_manufacturing import WorkCenter
from app.models.maintenance import MaintenanceSchedule, MaintenanceWorkOrder, MWOSparePart
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.schemas.maintenance import (
    MaintenanceScheduleCreate,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderComplete,
    MWOSparePartCreate
)
from app.services.maintenance_service import MaintenanceService
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService

# ============================================================================
# 1. RECURRENCE MODES (CALENDAR VS RUNTIME-HOURS)
# ============================================================================

@pytest.mark.asyncio
async def test_calendar_and_runtime_hour_recurrence_modes(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # 1. Calendar Interval Schedule (30 days)
    sched_cal = await MaintenanceService.create_maintenance_schedule(
        db=db_session,
        tenant_id=tenant_id,
        sched_in=MaintenanceScheduleCreate(
            schedule_name="Monthly Conveyor Belt Lubrication",
            schedule_type="CALENDAR_INTERVAL",
            frequency_days=30
        )
    )
    assert sched_cal.schedule_type == "CALENDAR_INTERVAL"
    assert sched_cal.frequency_days == 30
    assert sched_cal.next_due_at is not None

    # 2. Runtime Hours Schedule (500 operating hours)
    sched_run = await MaintenanceService.create_maintenance_schedule(
        db=db_session,
        tenant_id=tenant_id,
        sched_in=MaintenanceScheduleCreate(
            schedule_name="Turbine 500-Hour Overhaul",
            schedule_type="RUNTIME_HOURS",
            frequency_days=20 # 20 days expected run interval
        )
    )
    assert sched_run.schedule_type == "RUNTIME_HOURS"
    assert sched_run.frequency_days == 20

# ============================================================================
# 2. STATE MACHINE, CANCELLATION SEMANTICS & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_mwo_lifecycle_cancellation_and_completion_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    # 1. DRAFT -> CANCELLED
    mwo1 = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(priority="LOW", notes="Cancelled Draft Test")
    )
    mwo1_canc = await MaintenanceService.update_work_order_status(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo1.id, new_status="CANCELLED"
    )
    assert mwo1_canc.status == "CANCELLED"

    # 2. SCHEDULED -> CANCELLED
    mwo2 = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(priority="MEDIUM", notes="Cancelled Scheduled Test")
    )
    await MaintenanceService.update_work_order_status(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo2.id, new_status="SCHEDULED"
    )
    mwo2_canc = await MaintenanceService.update_work_order_status(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo2.id, new_status="CANCELLED"
    )
    assert mwo2_canc.status == "CANCELLED"

    # 3. Completion Idempotency Guard
    mwo3 = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(priority="HIGH", notes="Completion Idempotency Test")
    )
    await MaintenanceService.update_work_order_status(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo3.id, new_status="SCHEDULED"
    )
    await MaintenanceService.update_work_order_status(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo3.id, new_status="IN_PROGRESS"
    )

    # First Completion -> Success
    res1 = await MaintenanceService.complete_maintenance_work_order(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo3.id,
        comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("1.0"), labor_hours=Decimal("2.0")),
        user_id=user_id
    )
    assert res1.status == "COMPLETED"

    # Second Completion -> Rejection (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await MaintenanceService.complete_maintenance_work_order(
            db=db_session, tenant_id=tenant_id, mwo_id=mwo3.id,
            comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("1.0"), labor_hours=Decimal("2.0")),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "only in_progress" in exc_info.value.detail.lower()

    # Completed MWO cannot be cancelled -> Rejection (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await MaintenanceService.update_work_order_status(
            db=db_session, tenant_id=tenant_id, mwo_id=mwo3.id, new_status="CANCELLED"
        )
    assert exc_info.value.status_code == 400

# ============================================================================
# 3. STOCK RESERVATION VS CONSUMPTION TIMING & INSUFFICIENT INVENTORY
# ============================================================================

@pytest.mark.asyncio
async def test_stock_consumption_timing_and_insufficient_stock_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-STK-{uuid.uuid4().hex[:4]}", name="Spares WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-SP-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-FILTER-{uuid.uuid4().hex[:4]}", name="Air Filter", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Standard Filter", cost_price=Decimal("15.0"), selling_price=Decimal("25.0"))
    db_session.add(var)
    await db_session.flush()

    # Initial stock: 10 units
    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_loc.id, "quantity": Decimal("10.0"), "unit_cost": Decimal("15.0")}],
        user_id=user_id
    )

    # 1. Create MWO requiring 3 units
    mwo = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(
            priority="HIGH",
            spare_parts=[MWOSparePartCreate(item_variant_id=var.id, warehouse_id=wh.id, location_bin_id=bin_loc.id, quantity_required=Decimal("3.0"), unit_cost=Decimal("15.0"))]
        )
    )

    # Step DRAFT -> No stock mutation
    bal_draft = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_loc.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_draft.quantity_on_hand == Decimal("10.0")

    # Step SCHEDULED -> No stock mutation
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="SCHEDULED")
    bal_sched = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_loc.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_sched.quantity_on_hand == Decimal("10.0")

    # Step IN_PROGRESS -> No stock mutation
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="IN_PROGRESS")
    bal_prog = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_loc.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_prog.quantity_on_hand == Decimal("10.0")

    # Step COMPLETED -> Authoritative consumption (10 - 3 = 7)
    await MaintenanceService.complete_maintenance_work_order(
        db=db_session, tenant_id=tenant_id, mwo_id=mwo.id,
        comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("1.0"), labor_hours=Decimal("1.0")),
        user_id=user_id
    )
    bal_done = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_loc.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_done.quantity_on_hand == Decimal("7.0")

    # 2. Insufficient Stock Failure Test: Create MWO requiring 100 units (only 7 on hand)
    mwo_excess = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(
            priority="CRITICAL",
            spare_parts=[MWOSparePartCreate(item_variant_id=var.id, warehouse_id=wh.id, location_bin_id=bin_loc.id, quantity_required=Decimal("100.0"), unit_cost=Decimal("15.0"))]
        )
    )
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo_excess.id, new_status="SCHEDULED")
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo_excess.id, new_status="IN_PROGRESS")

    with pytest.raises(HTTPException) as exc_info:
        await MaintenanceService.complete_maintenance_work_order(
            db=db_session, tenant_id=tenant_id, mwo_id=mwo_excess.id,
            comp_in=MaintenanceWorkOrderComplete(downtime_hours=Decimal("1.0"), labor_hours=Decimal("1.0")),
            user_id=user_id
        )
    assert exc_info.value.status_code == 422 # Insufficient stock in bin
    assert "insufficient stock" in exc_info.value.detail.lower()

    # Verify atomic rollback: balance remains 7.0
    bal_after_fail = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_loc.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_after_fail.quantity_on_hand == Decimal("7.0")

# ============================================================================
# 4. CLOSED ACCOUNTING PERIOD GUARD
# ============================================================================

@pytest.mark.asyncio
async def test_closed_accounting_period_protection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-MNT-{uuid.uuid4().hex[:4].upper()}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.flush()

    closed_period = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id, period_code=f"P-MNT-CL-{uuid.uuid4().hex[:3].upper()}",
        period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), status="CLOSED"
    )
    db_session.add(closed_period)
    await db_session.commit()

    mwo = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_id,
        mwo_in=MaintenanceWorkOrderCreate(priority="HIGH", notes="Closed Period Test")
    )
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="SCHEDULED")
    await MaintenanceService.update_work_order_status(db=db_session, tenant_id=tenant_id, mwo_id=mwo.id, new_status="IN_PROGRESS")

    # Attempt completion backdated into closed period (Jan 15, 2026) -> Rejected
    with pytest.raises(HTTPException) as exc_info:
        await MaintenanceService.complete_maintenance_work_order(
            db=db_session, tenant_id=tenant_id, mwo_id=mwo.id,
            comp_in=MaintenanceWorkOrderComplete(
                actual_completion_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                downtime_hours=Decimal("1.0"), labor_hours=Decimal("1.0")
            ),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "closed" in exc_info.value.detail.lower()

# ============================================================================
# 5. TENANT ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_tenant_isolation_guards(db_session: AsyncSession):
    tenant_a = settings.TENANT_DEFAULT_ID
    tenant_b = str(uuid.uuid4())

    mwo_a = await MaintenanceService.create_maintenance_work_order(
        db=db_session, tenant_id=tenant_a,
        mwo_in=MaintenanceWorkOrderCreate(priority="MEDIUM", notes="Tenant A MWO")
    )

    # Tenant B attempting to update or complete Tenant A's MWO -> HTTP 404
    with pytest.raises(HTTPException) as exc_info:
        await MaintenanceService.update_work_order_status(
            db=db_session, tenant_id=tenant_b, mwo_id=mwo_a.id, new_status="SCHEDULED"
        )
    assert exc_info.value.status_code == 404
