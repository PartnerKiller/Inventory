import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.models.fixed_asset import FixedAssetClass, FixedAsset, DepreciationScheduleEntry
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.fixed_asset import (
    FixedAssetClassCreate,
    FixedAssetCreate,
    DepreciationBatchRunRequest,
    AssetDisposalRequest
)
from app.services.fixed_asset_service import FixedAssetService
from app.services.gl_service import GLService

# ============================================================================
# 1. FIXED ASSET CLASS CREATION
# ============================================================================

@pytest.mark.asyncio
async def test_fixed_asset_class_creation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"PLANT-{uuid.uuid4().hex[:4]}",
            class_name="Heavy Plant & Machinery",
            depreciation_method="STRAIGHT_LINE",
            useful_life_months=60,
            depreciation_rate_annual=Decimal("20.0")
        )
    )
    assert ac.useful_life_months == 60
    assert ac.depreciation_method == "STRAIGHT_LINE"

# ============================================================================
# 2. ASSET CAPITALIZATION & STRAIGHT-LINE (SLM) SCHEDULE GENERATION
# ============================================================================

@pytest.mark.asyncio
async def test_asset_capitalization_and_slm_schedule_generation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"COMP-{uuid.uuid4().hex[:4]}",
            class_name="IT Hardware",
            depreciation_method="STRAIGHT_LINE",
            useful_life_months=12,
            depreciation_rate_annual=Decimal("0.0")
        )
    )

    # Cost = $12,000 | Salvage = $0 | 12 Months -> Monthly Dep = $1,000
    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-SRV-{uuid.uuid4().hex[:4]}",
            asset_name="Enterprise Rack Server",
            asset_class_id=ac.id,
            purchase_cost=Decimal("12000.0"),
            salvage_value=Decimal("0.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            useful_life_months=12
        ),
        user_id=user_id
    )
    assert asset_res.purchase_cost == Decimal("12000.0")
    assert len(asset_res.schedule_entries) == 12
    assert asset_res.schedule_entries[0].depreciation_amount == Decimal("1000.0")
    assert asset_res.schedule_entries[11].remaining_book_value_after == Decimal("0.0")

    # Verify Capitalization JV posted: Dr 1500 $12,000 / Cr 2000 $12,000
    jvs = (await db_session.execute(
        select(JournalVoucher).where(
            JournalVoucher.tenant_id == tenant_id,
            JournalVoucher.source_document_type == "FIXED_ASSET_CAPITALIZATION",
            JournalVoucher.source_document_id == asset_res.id
        )
    )).scalars().all()
    assert len(jvs) == 1
    assert sum(l.debit_amount for l in jvs[0].lines) == Decimal("12000.0")

# ============================================================================
# 3. WRITTEN-DOWN-VALUE (WDV) SCHEDULE GENERATION
# ============================================================================

@pytest.mark.asyncio
async def test_written_down_value_schedule_generation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac_wdv = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"VEH-{uuid.uuid4().hex[:4]}",
            class_name="Delivery Fleet",
            depreciation_method="WRITTEN_DOWN_VALUE",
            useful_life_months=24,
            depreciation_rate_annual=Decimal("20.0")
        )
    )

    asset_wdv = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-VAN-{uuid.uuid4().hex[:4]}",
            asset_name="Delivery Van",
            asset_class_id=ac_wdv.id,
            purchase_cost=Decimal("50000.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            useful_life_months=24
        ),
        user_id=user_id
    )
    assert len(asset_wdv.schedule_entries) == 24
    assert asset_wdv.schedule_entries[0].depreciation_amount > asset_wdv.schedule_entries[1].depreciation_amount

# ============================================================================
# 4. MONTHLY DEPRECIATION BATCH RUNNER & GL POSTINGS
# ============================================================================

@pytest.mark.asyncio
async def test_monthly_depreciation_batch_runner_and_gl_postings(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"RUN-{uuid.uuid4().hex[:4]}", class_name="Run Asset Class", useful_life_months=12
        )
    )
    await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-RUN-{uuid.uuid4().hex[:4]}", asset_name="Run Asset",
            asset_class_id=ac.id, purchase_cost=Decimal("24000.0"),
            acquisition_date=date(2026, 1, 1), depreciation_start_date=date(2026, 1, 1), useful_life_months=12
        ),
        user_id=user_id
    )

    batch_res = await FixedAssetService.run_monthly_depreciation_batch(
        db=db_session, tenant_id=tenant_id,
        batch_req=DepreciationBatchRunRequest(period_code="2026-01"),
        user_id=user_id
    )
    assert batch_res.processed_assets_count >= 1
    assert batch_res.total_depreciation_amount > Decimal("0.0")
    assert batch_res.journal_voucher_id is not None

    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == batch_res.journal_voucher_id))).scalar_one()
    assert jv.status == "POSTED"
    assert sum(l.debit_amount for l in jv.lines) == batch_res.total_depreciation_amount

# ============================================================================
# 5. BATCH DEPRECIATION IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_monthly_depreciation_batch_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"IDEM-{uuid.uuid4().hex[:4]}", class_name="Idem Asset Class", useful_life_months=12
        )
    )
    await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-IDEM-{uuid.uuid4().hex[:4]}", asset_name="Idem Asset",
            asset_class_id=ac.id, purchase_cost=Decimal("12000.0"),
            acquisition_date=date(2026, 2, 1), depreciation_start_date=date(2026, 2, 1), useful_life_months=12
        ),
        user_id=user_id
    )

    res1 = await FixedAssetService.run_monthly_depreciation_batch(
        db=db_session, tenant_id=tenant_id,
        batch_req=DepreciationBatchRunRequest(period_code="2026-02"),
        user_id=user_id
    )
    res2 = await FixedAssetService.run_monthly_depreciation_batch(
        db=db_session, tenant_id=tenant_id,
        batch_req=DepreciationBatchRunRequest(period_code="2026-02"),
        user_id=user_id
    )
    assert res1.journal_voucher_id == res2.journal_voucher_id
    assert res1.total_depreciation_amount == res2.total_depreciation_amount

# ============================================================================
# 6. ASSET DISPOSAL WITH GAIN ON SALE
# ============================================================================

@pytest.mark.asyncio
async def test_fixed_asset_disposal_with_gain_on_sale(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"FURN-{uuid.uuid4().hex[:4]}", class_name="Office Furniture", useful_life_months=12
        )
    )

    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-DESK-{uuid.uuid4().hex[:4]}", asset_name="Executive Desk",
            asset_class_id=ac.id, purchase_cost=Decimal("10000.0"),
            acquisition_date=date(2026, 1, 1), depreciation_start_date=date(2026, 1, 1), useful_life_months=12
        ),
        user_id=user_id
    )

    asset_db = (await db_session.execute(select(FixedAsset).where(FixedAsset.id == asset_res.id))).scalar_one()
    asset_db.accumulated_depreciation = Decimal("2000.0")
    await db_session.commit()

    disp_res = await FixedAssetService.dispose_fixed_asset(
        db=db_session, tenant_id=tenant_id, asset_id=asset_res.id,
        disp_req=AssetDisposalRequest(disposal_date=date(2026, 6, 1), disposal_amount=Decimal("9000.0")),
        user_id=user_id
    )
    assert disp_res.status == "DISPOSED"
    assert disp_res.gain_or_loss == Decimal("1000.0")

    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == disp_res.journal_voucher_id))).scalar_one()
    gain_line = [l for l in jv.lines if l.account.account_code == "6450"][0]
    assert gain_line.credit_amount == Decimal("1000.0")

# ============================================================================
# 7. ASSET DISPOSAL WITH LOSS ON SALE
# ============================================================================

@pytest.mark.asyncio
async def test_fixed_asset_disposal_with_loss_on_sale(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"TOOL-{uuid.uuid4().hex[:4]}", class_name="Shop Tools", useful_life_months=12
        )
    )

    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-TOOL-{uuid.uuid4().hex[:4]}", asset_name="Power Drill",
            asset_class_id=ac.id, purchase_cost=Decimal("5000.0"),
            acquisition_date=date(2026, 1, 1), depreciation_start_date=date(2026, 1, 1), useful_life_months=12
        ),
        user_id=user_id
    )
    asset_db = (await db_session.execute(select(FixedAsset).where(FixedAsset.id == asset_res.id))).scalar_one()
    asset_db.accumulated_depreciation = Decimal("1000.0")
    await db_session.commit()

    disp_res = await FixedAssetService.dispose_fixed_asset(
        db=db_session, tenant_id=tenant_id, asset_id=asset_res.id,
        disp_req=AssetDisposalRequest(disposal_date=date(2026, 6, 1), disposal_amount=Decimal("3500.0")),
        user_id=user_id
    )
    assert disp_res.gain_or_loss == Decimal("-500.0")

    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == disp_res.journal_voucher_id))).scalar_one()
    loss_line = [l for l in jv.lines if l.account.account_code == "6450"][0]
    assert loss_line.debit_amount == Decimal("500.0")

# ============================================================================
# 8. PERIOD CLOSING LOCK INTEGRATION
# ============================================================================

@pytest.mark.asyncio
async def test_depreciation_period_closing_lock_integration(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-DEP-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    period_apr = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-04", period_number=4,
        start_date=date(2026, 4, 1), end_date=date(2026, 4, 30), status="CLOSED"
    )
    db_session.add(period_apr)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await FixedAssetService.run_monthly_depreciation_batch(
            db=db_session, tenant_id=tenant_id,
            batch_req=DepreciationBatchRunRequest(period_code="2026-04", run_date=date(2026, 4, 30))
        )
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail

# ============================================================================
# 9. PO/GRN -> FIXED ASSET CAPITALIZATION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_po_grn_fixed_asset_capitalization_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    po_id = f"PO-{uuid.uuid4().hex[:6]}"
    grn_id = f"GRN-{uuid.uuid4().hex[:6]}"

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"MCH-{uuid.uuid4().hex[:4]}", class_name="Machinery", useful_life_months=60
        )
    )

    # 1. Capitalize asset from PO/GRN
    asset = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-CNC-{uuid.uuid4().hex[:4]}",
            asset_name="CNC Milling Machine",
            asset_class_id=ac.id,
            source_po_id=po_id,
            source_grn_id=grn_id,
            purchase_cost=Decimal("75000.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            useful_life_months=60
        ),
        user_id=user_id
    )
    assert asset.source_po_id == po_id
    assert asset.source_grn_id == grn_id
    assert asset.purchase_cost == Decimal("75000.0")

    # 2. Attempt duplicate capitalization against the same GRN -> REJECT (HTTP 409)
    with pytest.raises(HTTPException) as exc_info:
        await FixedAssetService.create_and_capitalize_fixed_asset(
            db=db_session, tenant_id=tenant_id,
            asset_in=FixedAssetCreate(
                asset_code=f"AST-DUP-{uuid.uuid4().hex[:4]}",
                asset_name="Duplicate Asset",
                asset_class_id=ac.id,
                source_po_id=po_id,
                source_grn_id=grn_id,
                purchase_cost=Decimal("75000.0"),
                acquisition_date=date(2026, 1, 1),
                depreciation_start_date=date(2026, 1, 1)
            ),
            user_id=user_id
        )
    assert exc_info.value.status_code == 409
    assert "already capitalized" in exc_info.value.detail

# ============================================================================
# 10. FIXED ASSET LIFECYCLE STATE MACHINE & INVALID TRANSITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_fixed_asset_lifecycle_state_machine_and_invalid_transitions(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"LIFE-{uuid.uuid4().hex[:4]}", class_name="Lifecycle Class", useful_life_months=12
        )
    )

    asset = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-LIFE-{uuid.uuid4().hex[:4]}", asset_name="Lifecycle Asset",
            asset_class_id=ac.id, purchase_cost=Decimal("5000.0"),
            acquisition_date=date(2026, 1, 1), depreciation_start_date=date(2026, 1, 1)
        )
    )
    assert asset.status == "ACTIVE"

    # Valid: ACTIVE -> DEPRECIATING
    res_dep = await FixedAssetService.update_asset_status(db_session, tenant_id, asset.id, "DEPRECIATING")
    assert res_dep.status == "DEPRECIATING"

    # Valid: DEPRECIATING -> FULLY_DEPRECIATED
    res_full = await FixedAssetService.update_asset_status(db_session, tenant_id, asset.id, "FULLY_DEPRECIATED")
    assert res_full.status == "FULLY_DEPRECIATED"

    # Invalid: FULLY_DEPRECIATED -> ACTIVE -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await FixedAssetService.update_asset_status(db_session, tenant_id, asset.id, "ACTIVE")
    assert exc_info.value.status_code == 400
    assert "Illegal asset lifecycle transition" in exc_info.value.detail

    # Valid: FULLY_DEPRECIATED -> DISPOSED
    res_disp = await FixedAssetService.update_asset_status(db_session, tenant_id, asset.id, "DISPOSED")
    assert res_disp.status == "DISPOSED"

    # Invalid: DISPOSED -> ACTIVE -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info2:
        await FixedAssetService.update_asset_status(db_session, tenant_id, asset.id, "ACTIVE")
    assert exc_info2.value.status_code == 400
