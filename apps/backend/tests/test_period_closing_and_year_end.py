import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.accounting_period import FiscalYear, AccountingPeriod, PeriodClosingChecklist
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.accounting_period import (
    FiscalYearCreate,
    PeriodStatusUpdateRequest,
    YearEndClosingRequest
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.period_closing_service import PeriodClosingService
from app.services.gl_service import GLService

# ============================================================================
# 1. FISCAL YEAR CREATION & 12 PERIOD GENERATION
# ============================================================================

@pytest.mark.asyncio
async def test_fiscal_year_creation_and_12_period_generation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    fy_res = await PeriodClosingService.create_fiscal_year_with_periods(
        db=db_session,
        tenant_id=tenant_id,
        fy_in=FiscalYearCreate(
            fiscal_year_code=f"FY2026_{uuid.uuid4().hex[:4]}",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            notes="Statutory Fiscal Year 2026"
        )
    )
    assert fy_res.status == "OPEN"
    assert len(fy_res.periods) == 12
    assert fy_res.periods[0].period_code.endswith("-01")
    assert fy_res.periods[0].status == "OPEN"
    assert fy_res.periods[11].period_code.endswith("-12")
    assert fy_res.periods[11].status == "FUTURE"

# ============================================================================
# 2. PERIOD STATE MACHINE TRANSITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_period_state_transitions(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    period = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code=f"2026-P-{uuid.uuid4().hex[:4]}", period_number=1,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), status="OPEN"
    )
    db_session.add(period)
    await db_session.commit()

    # Transition to SOFT_CLOSED
    sc_res = await PeriodClosingService.update_period_status(
        db=db_session, tenant_id=tenant_id, period_id=period.id,
        req=PeriodStatusUpdateRequest(status="SOFT_CLOSED", notes="Month-end review in progress"),
        user_id=user_id
    )
    assert sc_res.status == "SOFT_CLOSED"

    # Transition to CLOSED
    closed_res = await PeriodClosingService.update_period_status(
        db=db_session, tenant_id=tenant_id, period_id=period.id,
        req=PeriodStatusUpdateRequest(status="CLOSED", notes="Month closed by controller"),
        user_id=user_id
    )
    assert closed_res.status == "CLOSED"
    assert closed_res.closed_at is not None
    assert closed_res.closed_by_user_id == user_id

# ============================================================================
# 3. BACKDATED POSTING INTO CLOSED PERIOD REJECTED
# ============================================================================

@pytest.mark.asyncio
async def test_backdated_posting_into_closed_period_rejected(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    # Create CLOSED period for January 2026
    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-LOCK-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    period_jan = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-01-LOCK", period_number=1,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), status="CLOSED"
    )
    db_session.add(period_jan)

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_1000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
    acc_4000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "4000"))).scalar_one()
    await db_session.commit()

    # Attempt to post backdated JV into closed January period -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await GLService.post_journal_voucher(
            db=db_session, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                source_document_type="MANUAL",
                notes="Backdated adjustment into closed period",
                lines=[
                    JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=Decimal("500.0"), credit_amount=Decimal("0.0")),
                    JournalEntryLineCreate(account_id=acc_4000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("500.0"))
                ]
            ),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail

# ============================================================================
# 4. VOID IN CLOSED PERIOD REJECTED
# ============================================================================

@pytest.mark.asyncio
async def test_void_in_closed_period_rejected(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_1000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
    acc_4000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "4000"))).scalar_one()

    # Create JV in February (OPEN)
    jv = await GLService.post_journal_voucher(
        db=db_session, tenant_id=tenant_id,
        voucher_in=JournalVoucherCreate(
            voucher_date=datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc),
            source_document_type="MANUAL",
            notes="Feb standard entry",
            lines=[
                JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=Decimal("100.0"), credit_amount=Decimal("0.0")),
                JournalEntryLineCreate(account_id=acc_4000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("100.0"))
            ]
        ),
        user_id=user_id
    )

    # Now close February Accounting Period
    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-FEB-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    period_feb = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-02-LOCK", period_number=2,
        start_date=date(2026, 2, 1), end_date=date(2026, 2, 28), status="CLOSED"
    )
    db_session.add(period_feb)
    await db_session.commit()

    # Attempt to void the February JV -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await GLService.void_journal_voucher(db=db_session, tenant_id=tenant_id, voucher_id=jv.id, user_id=user_id)
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail

# ============================================================================
# 5. SOFT-CLOSED ROLE-BASED OVERRIDE
# ============================================================================

@pytest.mark.asyncio
async def test_soft_closed_role_based_override(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-SC-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 3, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    period_mar = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-03-SOFT", period_number=3,
        start_date=date(2026, 3, 1), end_date=date(2026, 3, 31), status="SOFT_CLOSED"
    )
    db_session.add(period_mar)
    await db_session.commit()

    # Standard warehouse clerk role -> REJECT (HTTP 403)
    with pytest.raises(HTTPException) as exc_info:
        await PeriodClosingService.validate_posting_date(
            db=db_session, tenant_id=tenant_id, posting_date=date(2026, 3, 15), user_role="OPERATOR"
        )
    assert exc_info.value.status_code == 403
    assert "only financial controllers" in exc_info.value.detail

    # Financial Controller role -> PASS
    await PeriodClosingService.validate_posting_date(
        db=db_session, tenant_id=tenant_id, posting_date=date(2026, 3, 15), user_role="ROLE_CONTROLLER"
    )

# ============================================================================
# 6. YEAR-END CLOSING CEREMONY (P&L TO RETAINED EARNINGS)
# ============================================================================

@pytest.mark.asyncio
async def test_year_end_closing_ceremony_pnl_to_retained_earnings(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-YEAR-END-{uuid.uuid4().hex[:4]}",
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    # 12 periods all CLOSED
    for m in range(1, 13):
        p = AccountingPeriod(
            id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
            period_code=f"2025-{m:02d}", period_number=m,
            start_date=date(2025, m, 1), end_date=date(2025, m, 28), status="CLOSED"
        )
        db_session.add(p)

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_1000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
    acc_4000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "4000"))).scalar_one()
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()
    acc_3100 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "3100"))).scalar_one()
    await db_session.commit()

    # Post 2025 Revenue = ₹10,000 (Account 4000)
    jv1 = JournalVoucher(
        id=str(uuid.uuid4()), tenant_id=tenant_id, voucher_number=f"JV-REV-{uuid.uuid4().hex[:4]}",
        voucher_date=datetime(2025, 6, 1, tzinfo=timezone.utc), source_document_type="MANUAL", status="POSTED"
    )
    db_session.add(jv1)
    db_session.add(JournalEntryLine(id=str(uuid.uuid4()), voucher_id=jv1.id, account_id=acc_1000.id, debit_amount=Decimal("10000.0"), credit_amount=Decimal("0.0")))
    db_session.add(JournalEntryLine(id=str(uuid.uuid4()), voucher_id=jv1.id, account_id=acc_4000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("10000.0")))

    # Post 2025 Expense = ₹4,000 (Account 6000)
    jv2 = JournalVoucher(
        id=str(uuid.uuid4()), tenant_id=tenant_id, voucher_number=f"JV-EXP-{uuid.uuid4().hex[:4]}",
        voucher_date=datetime(2025, 7, 1, tzinfo=timezone.utc), source_document_type="MANUAL", status="POSTED"
    )
    db_session.add(jv2)
    db_session.add(JournalEntryLine(id=str(uuid.uuid4()), voucher_id=jv2.id, account_id=acc_6000.id, debit_amount=Decimal("4000.0"), credit_amount=Decimal("0.0")))
    db_session.add(JournalEntryLine(id=str(uuid.uuid4()), voucher_id=jv2.id, account_id=acc_1000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("4000.0")))
    await db_session.commit()

    # Net Income = 10,000 (Rev) - 4,000 (Exp) = ₹6,000
    # Execute Year-End Closing
    close_res = await PeriodClosingService.execute_year_end_closing(
        db=db_session, tenant_id=tenant_id,
        req=YearEndClosingRequest(fiscal_year_id=fy.id, closing_date=date(2025, 12, 31)),
        user_id=user_id
    )
    assert close_res.status == "FINALIZED"
    assert close_res.total_revenue_cleared == Decimal("10000.0")
    assert close_res.total_expense_cleared == Decimal("4000.0")
    assert close_res.net_retained_earnings_transferred == Decimal("6000.0")
