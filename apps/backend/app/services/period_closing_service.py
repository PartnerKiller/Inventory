import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone
from calendar import monthrange
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.accounting_period import FiscalYear, AccountingPeriod, PeriodClosingChecklist
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.accounting_period import (
    FiscalYearCreate,
    FiscalYearResponse,
    AccountingPeriodResponse,
    PeriodStatusUpdateRequest,
    YearEndClosingRequest,
    YearEndClosingResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

STANDARD_CHECKPOINTS = [
    "Unbilled Goods Receipts (GRN) Accruals Reconciled",
    "Accounts Receivable (AR) Invoices & Payments Settled",
    "Accounts Payable (AP) Vendor Invoices Matched",
    "Physical Inventory & Stock Balance Counts Posted",
    "Bank & Cash Accounts Reconciled",
    "Fixed Asset & Depreciation Schedules Calculated"
]

class PeriodClosingService:

    # ========================================================================
    # 1. FISCAL YEAR & PERIOD INITIALIZATION
    # ========================================================================

    @staticmethod
    async def create_fiscal_year_with_periods(
        db: AsyncSession,
        tenant_id: str,
        fy_in: FiscalYearCreate
    ) -> FiscalYearResponse:
        existing = (await db.execute(
            select(FiscalYear).where(
                FiscalYear.tenant_id == tenant_id,
                FiscalYear.fiscal_year_code == fy_in.fiscal_year_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Fiscal Year '{fy_in.fiscal_year_code}' already exists")

        fy = FiscalYear(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            fiscal_year_code=fy_in.fiscal_year_code,
            start_date=fy_in.start_date,
            end_date=fy_in.end_date,
            status="OPEN",
            notes=fy_in.notes
        )
        db.add(fy)

        periods: List[AccountingPeriod] = []
        year_num = fy_in.start_date.year

        for month in range(1, 13):
            _, last_day = monthrange(year_num, month)
            p_start = date(year_num, month, 1)
            p_end = date(year_num, month, last_day)
            p_code = f"{year_num}-{month:02d}"

            period = AccountingPeriod(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                fiscal_year_id=fy.id,
                period_code=p_code,
                period_number=month,
                start_date=p_start,
                end_date=p_end,
                status="OPEN" if month == 1 else "FUTURE"
            )
            db.add(period)
            periods.append(period)

            # Add Standard Checkpoints
            for chk in STANDARD_CHECKPOINTS:
                chk_item = PeriodClosingChecklist(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    period_id=period.id,
                    checkpoint_name=chk,
                    is_completed=False
                )
                db.add(chk_item)

        await db.commit()
        await db.refresh(fy)

        return FiscalYearResponse(
            id=fy.id,
            tenant_id=fy.tenant_id,
            fiscal_year_code=fy.fiscal_year_code,
            start_date=fy.start_date,
            end_date=fy.end_date,
            status=fy.status,
            notes=fy.notes,
            periods=[
                AccountingPeriodResponse(
                    id=p.id,
                    tenant_id=p.tenant_id,
                    fiscal_year_id=p.fiscal_year_id,
                    period_code=p.period_code,
                    period_number=p.period_number,
                    start_date=p.start_date,
                    end_date=p.end_date,
                    status=p.status,
                    closed_at=p.closed_at,
                    closed_by_user_id=p.closed_by_user_id,
                    closing_notes=p.closing_notes,
                    created_at=p.created_at
                ) for p in periods
            ],
            created_at=fy.created_at
        )

    # ========================================================================
    # 2. PERIOD STATE MACHINE & CLOSING CEREMONIES
    # ========================================================================

    @staticmethod
    async def update_period_status(
        db: AsyncSession,
        tenant_id: str,
        period_id: str,
        req: PeriodStatusUpdateRequest,
        user_id: Optional[str] = None
    ) -> AccountingPeriodResponse:
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.id == period_id,
                AccountingPeriod.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Accounting Period not found")

        valid_statuses = {"FUTURE", "OPEN", "SOFT_CLOSED", "CLOSED", "FINALIZED"}
        if req.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid period status: {req.status}")

        if period.status == "FINALIZED":
            raise HTTPException(status_code=400, detail="Cannot mutate a FINALIZED accounting period")

        period.status = req.status
        period.closing_notes = req.notes
        if req.status in {"CLOSED", "FINALIZED"}:
            period.closed_at = get_utc_now()
            period.closed_by_user_id = user_id

        await db.commit()
        await db.refresh(period)

        return AccountingPeriodResponse(
            id=period.id,
            tenant_id=period.tenant_id,
            fiscal_year_id=period.fiscal_year_id,
            period_code=period.period_code,
            period_number=period.period_number,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            closed_at=period.closed_at,
            closed_by_user_id=period.closed_by_user_id,
            closing_notes=period.closing_notes,
            created_at=period.created_at
        )

    # ========================================================================
    # 3. TRANSACTION POSTING DATE VALIDATOR (GL INTERCEPTOR)
    # ========================================================================

    @staticmethod
    async def validate_posting_date(
        db: AsyncSession,
        tenant_id: str,
        posting_date: date,
        user_role: Optional[str] = None
    ) -> None:
        """
        Validates whether the transaction/posting date falls within an eligible accounting period.
        - If period is CLOSED or FINALIZED -> Rejects with HTTP 400 Bad Request.
        - If period is SOFT_CLOSED and user is not controller/admin -> Rejects with HTTP 403 Forbidden.
        """
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.start_date <= posting_date,
                AccountingPeriod.end_date >= posting_date
            )
        )).scalar_one_or_none()

        if not period:
            # No formal period configured for this date -> Allow by default or require setup
            return

        if period.status in {"CLOSED", "FINALIZED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Accounting Period '{period.period_code}' is {period.status}. Postings and modifications are strictly prohibited."
            )

        if period.status == "SOFT_CLOSED":
            if user_role not in {"ADMIN", "ROLE_ADMIN", "CONTROLLER", "ROLE_CONTROLLER"}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Accounting Period '{period.period_code}' is SOFT_CLOSED. Operational postings are locked; only financial controllers may post adjustments."
                )

    # ========================================================================
    # 4. YEAR-END CLOSING CEREMONY (P&L TO RETAINED EARNINGS)
    # ========================================================================

    @staticmethod
    async def execute_year_end_closing(
        db: AsyncSession,
        tenant_id: str,
        req: YearEndClosingRequest,
        user_id: Optional[str] = None
    ) -> YearEndClosingResponse:
        fy = (await db.execute(
            select(FiscalYear).where(
                FiscalYear.id == req.fiscal_year_id,
                FiscalYear.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not fy:
            raise HTTPException(status_code=404, detail="Fiscal Year not found")

        # 1. Verify all accounting periods are closed
        open_periods = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.fiscal_year_id == fy.id,
                AccountingPeriod.status.in_(["OPEN", "FUTURE", "SOFT_CLOSED"])
            )
        )).scalars().all()

        if open_periods:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot execute year-end closing: {len(open_periods)} accounting periods remain OPEN/SOFT_CLOSED."
            )

        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        # 2. Query cumulative balances for Revenue, COGS, Overhead, and Expense accounts
        # P&L Account classes: REVENUE, COGS, EXPENSE
        pl_accounts = (await db.execute(
            select(GLAccount).where(
                GLAccount.tenant_id == tenant_id,
                GLAccount.account_class.in_(["REVENUE", "COGS", "EXPENSE"])
            )
        )).scalars().all()

        closing_lines: List[JournalEntryLineCreate] = []
        total_rev_cleared = Decimal("0.0")
        total_exp_cleared = Decimal("0.0")

        for acc in pl_accounts:
            # Compute net balance from posted journal lines in this fiscal year
            dr_sum = (await db.execute(
                select(func.coalesce(func.sum(JournalEntryLine.debit_amount), Decimal("0.0"))).join(JournalVoucher).where(
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.tenant_id == tenant_id,
                    JournalVoucher.status == "POSTED",
                    func.date(JournalVoucher.voucher_date) >= fy.start_date,
                    func.date(JournalVoucher.voucher_date) <= fy.end_date
                )
            )).scalar() or Decimal("0.0")

            cr_sum = (await db.execute(
                select(func.coalesce(func.sum(JournalEntryLine.credit_amount), Decimal("0.0"))).join(JournalVoucher).where(
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.tenant_id == tenant_id,
                    JournalVoucher.status == "POSTED",
                    func.date(JournalVoucher.voucher_date) >= fy.start_date,
                    func.date(JournalVoucher.voucher_date) <= fy.end_date
                )
            )).scalar() or Decimal("0.0")

            net_dr = Decimal(str(dr_sum)) - Decimal(str(cr_sum))

            if acc.account_class == "REVENUE":
                # Revenue has normal CREDIT balance -> Debit to zero out
                net_rev = Decimal(str(cr_sum)) - Decimal(str(dr_sum))
                if net_rev > Decimal("0.0"):
                    closing_lines.append(JournalEntryLineCreate(
                        account_id=acc.id, debit_amount=net_rev, credit_amount=Decimal("0.0"), memo=f"Year-End Close: Zero {acc.account_code}"
                    ))
                    total_rev_cleared += net_rev
            else:
                # Expenses / COGS have normal DEBIT balance -> Credit to zero out
                if net_dr > Decimal("0.0"):
                    closing_lines.append(JournalEntryLineCreate(
                        account_id=acc.id, debit_amount=Decimal("0.0"), credit_amount=net_dr, memo=f"Year-End Close: Zero {acc.account_code}"
                    ))
                    total_exp_cleared += net_dr

        # Net Retained Earnings transfer = Total Revenue - Total Expenses
        net_income = total_rev_cleared - total_exp_cleared

        # Lookup Retained Earnings Account 3100
        re_acc = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "3100")
        )).scalar_one_or_none()

        if not re_acc:
            raise HTTPException(status_code=500, detail="Retained Earnings Account (3100) not found")

        if net_income > Decimal("0.0"):
            # Net Profit -> Credit Retained Earnings
            closing_lines.append(JournalEntryLineCreate(
                account_id=re_acc.id, debit_amount=Decimal("0.0"), credit_amount=net_income, memo="Year-End Net Profit to Retained Earnings"
            ))
        elif net_income < Decimal("0.0"):
            # Net Loss -> Debit Retained Earnings
            closing_lines.append(JournalEntryLineCreate(
                account_id=re_acc.id, debit_amount=abs(net_income), credit_amount=Decimal("0.0"), memo="Year-End Net Loss from Retained Earnings"
            ))

        # 3. Post Year-End Closing Journal Voucher
        closing_jv = None
        if len(closing_lines) >= 2:
            closing_jv = await GLService.post_journal_voucher(
                db=db,
                tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=datetime.combine(req.closing_date, datetime.min.time(), tzinfo=timezone.utc),
                    source_document_type="YEAR_END_CLOSING",
                    source_document_id=fy.id,
                    notes=f"Year-End Closing Ceremony for {fy.fiscal_year_code}",
                    lines=closing_lines
                ),
                user_id=user_id
            )

        # 4. Finalize Fiscal Year & All Accounting Periods
        fy.status = "FINALIZED"
        for p in fy.periods:
            p.status = "FINALIZED"

        await db.commit()

        return YearEndClosingResponse(
            fiscal_year_id=fy.id,
            fiscal_year_code=fy.fiscal_year_code,
            closing_voucher_id=closing_jv.id if closing_jv else "N/A",
            closing_voucher_number=closing_jv.voucher_number if closing_jv else "JV-NONE",
            total_revenue_cleared=total_rev_cleared,
            total_expense_cleared=total_exp_cleared,
            net_retained_earnings_transferred=net_income,
            status="FINALIZED",
            closed_at=get_utc_now()
        )
