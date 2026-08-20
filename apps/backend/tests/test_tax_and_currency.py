import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.models.tax_and_currency import CurrencyExchangeRate, TaxJurisdiction, TaxRate, TaxGroup, TaxGroupItem
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.tax_and_currency import (
    ExchangeRateCreate,
    TaxJurisdictionCreate,
    TaxRateCreate,
    TaxGroupCreate,
    TaxCalculationItemRequest
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.currency_service import CurrencyService
from app.services.tax_service import TaxService
from app.services.gl_service import GLService

# ============================================================================
# 1. HISTORICAL FX RATE LOCKING
# ============================================================================

@pytest.mark.asyncio
async def test_historical_fx_rate_locking(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    past_time = datetime.now(timezone.utc) - timedelta(days=10)

    # 1. Add historical rate USD/INR = 80.00 at T-10
    await CurrencyService.create_exchange_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=ExchangeRateCreate(from_currency="USD", to_currency="INR", rate=Decimal("80.000000"), effective_date=past_time)
    )

    # Historical lookup as of T-10
    rate_t10 = await CurrencyService.get_exchange_rate(db_session, tenant_id, from_currency="USD", to_currency="INR", as_of_date=past_time)
    assert rate_t10 == Decimal("80.000000")

    # 2. Add new current rate USD/INR = 85.00 at T_now
    await CurrencyService.create_exchange_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=ExchangeRateCreate(from_currency="USD", to_currency="INR", rate=Decimal("85.000000"), effective_date=datetime.now(timezone.utc))
    )

    # Historical lookup still returns 80.00
    rate_historical_still_80 = await CurrencyService.get_exchange_rate(db_session, tenant_id, from_currency="USD", to_currency="INR", as_of_date=past_time)
    assert rate_historical_still_80 == Decimal("80.000000")

    # Current lookup returns 85.00
    rate_current = await CurrencyService.get_exchange_rate(db_session, tenant_id, from_currency="USD", to_currency="INR")
    assert rate_current == Decimal("85.000000")

# ============================================================================
# 2. REALIZED FX GAIN / LOSS
# ============================================================================

@pytest.mark.asyncio
async def test_realized_fx_gain_accounting(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    inv_id = f"INV-FX-GAIN-{uuid.uuid4().hex[:4]}"

    # Booked AR = $1,000 | Settled Cash = $1,050 -> Realized FX Gain = $50
    jv_id = await CurrencyService.post_realized_fx_settlement(
        db=db_session, tenant_id=tenant_id, invoice_id=inv_id,
        original_base_amount=Decimal("1000.0"), settled_base_amount=Decimal("1050.0"), user_id=user_id
    )
    assert jv_id is not None

    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == jv_id))).scalar_one()
    gain_line = [l for l in jv.lines if l.account.account_code == "6300"][0]
    assert gain_line.credit_amount == Decimal("50.0")

@pytest.mark.asyncio
async def test_realized_fx_loss_accounting(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    inv_id = f"INV-FX-LOSS-{uuid.uuid4().hex[:4]}"

    # Booked AR = $1,000 | Settled Cash = $960 -> Realized FX Loss = $40
    jv_id = await CurrencyService.post_realized_fx_settlement(
        db=db_session, tenant_id=tenant_id, invoice_id=inv_id,
        original_base_amount=Decimal("1000.0"), settled_base_amount=Decimal("960.0"), user_id=user_id
    )
    assert jv_id is not None

    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == jv_id))).scalar_one()
    loss_line = [l for l in jv.lines if l.account.account_code == "6300"][0]
    assert loss_line.debit_amount == Decimal("40.0")

# ============================================================================
# 3. UNREALIZED FX MONTH-END REVALUATION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_unrealized_fx_month_end_revaluation_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    reval_dt = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)

    # Open foreign AR: €10,000 booked @ 1.08 = $10,800. Month-end spot rate = 1.10 -> Revalued = $11,000 (Gain = $200)
    jv_id1 = await CurrencyService.execute_month_end_revaluation(
        db=db_session, tenant_id=tenant_id, reval_date=reval_dt,
        foreign_ar_amount=Decimal("10000.0"), original_base_ar=Decimal("10800.0"), closing_rate=Decimal("1.1000")
    )
    assert jv_id1 is not None

    # Idempotent re-execution returns identical existing voucher
    jv_id2 = await CurrencyService.execute_month_end_revaluation(
        db=db_session, tenant_id=tenant_id, reval_date=reval_dt,
        foreign_ar_amount=Decimal("10000.0"), original_base_ar=Decimal("10800.0"), closing_rate=Decimal("1.1000")
    )
    assert jv_id1 == jv_id2

    # Verify single voucher exists for this month-end revaluation
    jvs = (await db_session.execute(
        select(JournalVoucher).where(
            JournalVoucher.tenant_id == tenant_id,
            JournalVoucher.source_document_type == "UNREALIZED_FX_REVALUATION",
            JournalVoucher.source_document_id == f"FX-REVAL-{reval_dt.strftime('%Y%m')}"
        )
    )).scalars().all()
    assert len(jvs) == 1

# ============================================================================
# 4. GST INTRA-STATE (CGST+SGST) VS INTER-STATE (IGST)
# ============================================================================

@pytest.mark.asyncio
async def test_gst_intra_vs_inter_state(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    jur_mh = await TaxService.create_jurisdiction(
        db=db_session, tenant_id=tenant_id,
        jur_in=TaxJurisdictionCreate(country_code="IN", jurisdiction_code=f"IN-MH-{uuid.uuid4().hex[:4]}", jurisdiction_name="Maharashtra", jurisdiction_type="STATE")
    )

    cgst = await TaxService.create_tax_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=TaxRateCreate(jurisdiction_id=jur_mh.id, tax_code=f"CGST-9-{uuid.uuid4().hex[:4]}", tax_name="CGST 9%", rate_percentage=Decimal("9.0"))
    )
    sgst = await TaxService.create_tax_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=TaxRateCreate(jurisdiction_id=jur_mh.id, tax_code=f"SGST-9-{uuid.uuid4().hex[:4]}", tax_name="SGST 9%", rate_percentage=Decimal("9.0"))
    )
    igst = await TaxService.create_tax_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=TaxRateCreate(jurisdiction_id=jur_mh.id, tax_code=f"IGST-18-{uuid.uuid4().hex[:4]}", tax_name="IGST 18%", rate_percentage=Decimal("18.0"))
    )

    group_intra = await TaxService.create_tax_group(
        db=db_session, tenant_id=tenant_id,
        group_in=TaxGroupCreate(group_code=f"GST-INTRA-{uuid.uuid4().hex[:4]}", group_name="Intra-State GST (CGST+SGST)", tax_rate_ids=[cgst.id, sgst.id])
    )

    # 1. Intra-State Calculation (CGST 9% + SGST 9%)
    calc_intra = await TaxService.calculate_tax(
        db=db_session, tenant_id=tenant_id,
        calc_req=TaxCalculationItemRequest(tax_group_id=group_intra.id, taxable_amount=Decimal("1000.0"))
    )
    assert calc_intra.total_tax_amount == Decimal("180.0")
    assert len(calc_intra.breakdown) == 2
    assert calc_intra.breakdown[0].tax_amount == Decimal("90.0")
    assert calc_intra.breakdown[1].tax_amount == Decimal("90.0")

    # 2. Inter-State Calculation (IGST 18%)
    calc_inter = await TaxService.calculate_tax(
        db=db_session, tenant_id=tenant_id,
        calc_req=TaxCalculationItemRequest(tax_rate_id=igst.id, taxable_amount=Decimal("1000.0"))
    )
    assert calc_inter.total_tax_amount == Decimal("180.0")
    assert len(calc_inter.breakdown) == 1
    assert calc_inter.breakdown[0].tax_amount == Decimal("180.0")

# ============================================================================
# 5. TAX INCLUSIVE VS EXCLUSIVE & EXEMPT TRANSACTIONS
# ============================================================================

@pytest.mark.asyncio
async def test_tax_inclusive_exclusive_and_exempt(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    jur = await TaxService.create_jurisdiction(
        db=db_session, tenant_id=tenant_id,
        jur_in=TaxJurisdictionCreate(country_code="US", jurisdiction_code=f"US-CA-{uuid.uuid4().hex[:4]}", jurisdiction_name="California", jurisdiction_type="STATE")
    )
    tax_18 = await TaxService.create_tax_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=TaxRateCreate(jurisdiction_id=jur.id, tax_code=f"TAX-18-{uuid.uuid4().hex[:4]}", tax_name="Standard 18%", rate_percentage=Decimal("18.0"))
    )
    tax_exempt = await TaxService.create_tax_rate(
        db=db_session, tenant_id=tenant_id,
        rate_in=TaxRateCreate(jurisdiction_id=jur.id, tax_code=f"EXEMPT-{uuid.uuid4().hex[:4]}", tax_name="Zero Rated Exempt", rate_percentage=Decimal("0.0"), tax_type="EXEMPT")
    )

    # 1. Exclusive: Base 100 + 18% -> Total 118
    calc_ex = await TaxService.calculate_tax(
        db=db_session, tenant_id=tenant_id,
        calc_req=TaxCalculationItemRequest(tax_rate_id=tax_18.id, taxable_amount=Decimal("100.0"), is_tax_inclusive=False)
    )
    assert calc_ex.total_taxable_amount == Decimal("100.0")
    assert calc_ex.total_tax_amount == Decimal("18.0")
    assert calc_ex.gross_amount == Decimal("118.0")

    # 2. Inclusive: Gross 118 inclusive of 18% -> Base 100, Tax 18
    calc_inc = await TaxService.calculate_tax(
        db=db_session, tenant_id=tenant_id,
        calc_req=TaxCalculationItemRequest(tax_rate_id=tax_18.id, taxable_amount=Decimal("118.0"), is_tax_inclusive=True)
    )
    assert calc_inc.total_taxable_amount == Decimal("100.0")
    assert calc_inc.total_tax_amount == Decimal("18.0")
    assert calc_inc.gross_amount == Decimal("118.0")

    # 3. Exempt: Base 500 @ 0% -> Tax 0
    calc_exempt = await TaxService.calculate_tax(
        db=db_session, tenant_id=tenant_id,
        calc_req=TaxCalculationItemRequest(tax_rate_id=tax_exempt.id, taxable_amount=Decimal("500.0"))
    )
    assert calc_exempt.total_tax_amount == Decimal("0.0")

# ============================================================================
# 6. TAX SETTLEMENT GL & INPUT TAX CREDIT (ITC) OFFSET
# ============================================================================

@pytest.mark.asyncio
async def test_tax_settlement_gl_offset_and_clearing(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    settle_dt = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)

    # Input Tax Credit = $180, Output Tax = $300 -> Net Payable = $120
    jv_settle = await TaxService.execute_tax_settlement(
        db=db_session, tenant_id=tenant_id, settlement_date=settle_dt,
        output_tax_amount=Decimal("300.0"), input_tax_credit_amount=Decimal("180.0"), user_id=user_id
    )
    assert jv_settle.source_document_type == "TAX_SETTLEMENT"
    assert jv_settle.status == "POSTED"

    # Verify Journal Entry Lines
    assert sum(l.debit_amount for l in jv_settle.lines) == Decimal("300.0")
    assert sum(l.credit_amount for l in jv_settle.lines) == Decimal("300.0")

# ============================================================================
# 7. PERIOD CLOSING INTEGRATION
# ============================================================================

@pytest.mark.asyncio
async def test_tax_and_fx_period_closing_lock_integration(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # Create CLOSED period for July 2026
    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-TAX-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    period_jul = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-07-LOCK", period_number=7,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31), status="CLOSED"
    )
    db_session.add(period_jul)
    await db_session.commit()

    # Attempt to post FX revaluation in closed July period -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await CurrencyService.execute_month_end_revaluation(
            db=db_session, tenant_id=tenant_id,
            reval_date=datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
            foreign_ar_amount=Decimal("1000.0"), original_base_ar=Decimal("1000.0"), closing_rate=Decimal("1.05")
        )
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail

    # Attempt to post Tax Settlement in closed July period -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await TaxService.execute_tax_settlement(
            db=db_session, tenant_id=tenant_id,
            settlement_date=datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc),
            output_tax_amount=Decimal("200.0"), input_tax_credit_amount=Decimal("100.0")
        )
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail
