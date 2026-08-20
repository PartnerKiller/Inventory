import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.general_ledger import (
    GLAccountCreate,
    GLAccountResponse,
    JournalEntryLineCreate,
    JournalEntryLineResponse,
    JournalVoucherCreate,
    JournalVoucherResponse,
    TrialBalanceRow,
    TrialBalanceResponse,
    IncomeStatementSection,
    IncomeStatementResponse,
    BalanceSheetSection,
    BalanceSheetResponse
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService

STANDARD_COA = [
    {"code": "1000", "name": "Cash and Bank", "class": "ASSET", "type": "BANK_AND_CASH", "normal": "DEBIT"},
    {"code": "1100", "name": "Accounts Receivable", "class": "ASSET", "type": "ACCOUNTS_RECEIVABLE", "normal": "DEBIT"},
    {"code": "1200", "name": "Inventory Asset", "class": "ASSET", "type": "INVENTORY_ASSET", "normal": "DEBIT"},
    {"code": "1250", "name": "Inventory In-Transit Asset", "class": "ASSET", "type": "INVENTORY_ASSET", "normal": "DEBIT"},
    {"code": "1300", "name": "Work-in-Progress (WIP) Asset", "class": "ASSET", "type": "CURRENT_ASSET", "normal": "DEBIT"},
    {"code": "1400", "name": "Input Tax Credit / Recoverable VAT", "class": "ASSET", "type": "CURRENT_ASSET", "normal": "DEBIT"},
    {"code": "1500", "name": "Fixed Assets - Acquisition Cost", "class": "ASSET", "type": "CURRENT_ASSET", "normal": "DEBIT"},
    {"code": "1550", "name": "Accumulated Depreciation - Fixed Assets", "class": "ASSET", "type": "CURRENT_ASSET", "normal": "CREDIT"},
    {"code": "2000", "name": "Accounts Payable", "class": "LIABILITY", "type": "ACCOUNTS_PAYABLE", "normal": "CREDIT"},
    {"code": "2100", "name": "AP Accrual / Unbilled GRN", "class": "LIABILITY", "type": "CURRENT_LIABILITY", "normal": "CREDIT"},
    {"code": "2200", "name": "Sales Tax / GST Payable", "class": "LIABILITY", "type": "CURRENT_LIABILITY", "normal": "CREDIT"},
    {"code": "3000", "name": "Common Stock / Owner Equity", "class": "EQUITY", "type": "RETAINED_EARNINGS", "normal": "CREDIT"},
    {"code": "3100", "name": "Retained Earnings", "class": "EQUITY", "type": "RETAINED_EARNINGS", "normal": "CREDIT"},
    {"code": "4000", "name": "Sales Revenue", "class": "REVENUE", "type": "OPERATING_REVENUE", "normal": "CREDIT"},
    {"code": "5000", "name": "Cost of Goods Sold (COGS)", "class": "COGS", "type": "DIRECT_COGS", "normal": "DEBIT"},
    {"code": "5100", "name": "Production Overhead / Absorption", "class": "COGS", "type": "DIRECT_COGS", "normal": "DEBIT"},
    {"code": "6000", "name": "Operating Expenses", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"},
    {"code": "6100", "name": "Shipping & Freight Expense", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"},
    {"code": "6200", "name": "Purchase Price Variance (PPV)", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"},
    {"code": "6300", "name": "Foreign Exchange (FX) Gain/Loss", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"},
    {"code": "6400", "name": "Depreciation & Amortization Expense", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"},
    {"code": "6450", "name": "Gain / Loss on Disposal of Fixed Assets", "class": "EXPENSE", "type": "OPERATING_EXPENSE", "normal": "DEBIT"}
]

class GLService:
    @staticmethod
    async def seed_standard_chart_of_accounts(db: AsyncSession, tenant_id: str) -> List[GLAccount]:
        existing = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id))).scalars().all()
        if existing:
            return existing

        created = []
        for defn in STANDARD_COA:
            acc = GLAccount(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                account_code=defn["code"],
                account_name=defn["name"],
                account_class=defn["class"],
                account_type=defn["type"],
                currency="USD",
                normal_balance=defn["normal"],
                is_active=True,
                is_system=True
            )
            db.add(acc)
            created.append(acc)

        await db.commit()
        for a in created:
            await db.refresh(a)
        return created

    @staticmethod
    async def get_account_by_code(db: AsyncSession, tenant_id: str, account_code: str) -> GLAccount:
        acc = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == account_code)
        )).scalar_one_or_none()
        if not acc:
            await GLService.seed_standard_chart_of_accounts(db, tenant_id)
            acc = (await db.execute(
                select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == account_code)
            )).scalar_one_or_none()
        if not acc:
            raise HTTPException(status_code=404, detail=f"GL Account '{account_code}' not found")
        return acc

    @staticmethod
    async def post_journal_voucher(
        db: AsyncSession,
        tenant_id: str,
        voucher_in: JournalVoucherCreate,
        user_id: Optional[str] = None
    ) -> JournalVoucherResponse:
        if len(voucher_in.lines) < 2:
            raise HTTPException(status_code=400, detail="Journal voucher must contain at least two entries")

        total_dr = sum(l.debit_amount for l in voucher_in.lines).quantize(Decimal("0.0001"))
        total_cr = sum(l.credit_amount for l in voucher_in.lines).quantize(Decimal("0.0001"))

        if total_dr <= Decimal("0.0"):
            raise HTTPException(status_code=400, detail="Journal voucher total debit must be greater than zero")

        if total_dr != total_cr:
            raise HTTPException(
                status_code=400,
                detail=f"Unbalanced Journal Voucher: Total Debits ({total_dr}) must equal Total Credits ({total_cr})"
            )

        # Validate Accounting Period Lock
        target_v_date = voucher_in.voucher_date or get_utc_now()
        target_date = target_v_date.date() if hasattr(target_v_date, "date") else target_v_date
        from app.models.accounting_period import AccountingPeriod
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.start_date <= target_date,
                AccountingPeriod.end_date >= target_date
            )
        )).scalar_one_or_none()
        if period and period.status in {"CLOSED", "FINALIZED"} and voucher_in.source_document_type != "YEAR_END_CLOSING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Accounting Period '{period.period_code}' is {period.status}. Postings and modifications are strictly prohibited."
            )

        # Idempotency: Return existing posted voucher for same source document
        if voucher_in.source_document_type != "MANUAL" and voucher_in.source_document_id:
            existing_jv = (await db.execute(
                select(JournalVoucher).where(
                    JournalVoucher.tenant_id == tenant_id,
                    JournalVoucher.source_document_type == voucher_in.source_document_type,
                    JournalVoucher.source_document_id == voucher_in.source_document_id,
                    JournalVoucher.status == "POSTED"
                )
            )).scalar_one_or_none()
            if existing_jv:
                lines_res = [
                    JournalEntryLineResponse(
                        id=l.id,
                        account_id=l.account_id,
                        account_code=l.account.account_code if l.account else "",
                        account_name=l.account.account_name if l.account else "",
                        debit_amount=float(l.debit_amount),
                        credit_amount=float(l.credit_amount),
                        currency=l.currency,
                        memo=l.memo
                    )
                    for l in existing_jv.lines
                ]
                tot_d = sum(l.debit_amount for l in existing_jv.lines)
                tot_c = sum(l.credit_amount for l in existing_jv.lines)
                return JournalVoucherResponse(
                    id=existing_jv.id,
                    voucher_number=existing_jv.voucher_number,
                    voucher_date=existing_jv.voucher_date,
                    source_document_type=existing_jv.source_document_type,
                    source_document_id=existing_jv.source_document_id,
                    status=existing_jv.status,
                    posted_at=existing_jv.posted_at,
                    notes=existing_jv.notes,
                    total_debit=float(tot_d),
                    total_credit=float(tot_c),
                    lines=lines_res
                )

        jv_num = await SequenceService.generate_next_number(db, tenant_id, "JOURNAL_VOUCHER", custom_prefix="JV")

        jv = JournalVoucher(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            voucher_number=jv_num,
            voucher_date=voucher_in.voucher_date or get_utc_now(),
            source_document_type=voucher_in.source_document_type,
            source_document_id=voucher_in.source_document_id,
            status="POSTED",
            posted_at=get_utc_now(),
            notes=voucher_in.notes,
            created_by_user_id=user_id
        )
        db.add(jv)
        await db.flush()

        lines_out: List[JournalEntryLineResponse] = []
        for line_in in voucher_in.lines:
            acc = (await db.execute(
                select(GLAccount).where(GLAccount.id == line_in.account_id, GLAccount.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if not acc:
                raise HTTPException(status_code=404, detail=f"Account ID '{line_in.account_id}' not found")

            entry = JournalEntryLine(
                id=str(uuid.uuid4()),
                voucher_id=jv.id,
                account_id=acc.id,
                debit_amount=line_in.debit_amount,
                credit_amount=line_in.credit_amount,
                currency=line_in.currency,
                cost_center_id=line_in.cost_center_id,
                memo=line_in.memo
            )
            db.add(entry)
            lines_out.append(JournalEntryLineResponse(
                id=entry.id,
                account_id=acc.id,
                account_code=acc.account_code,
                account_name=acc.account_name,
                debit_amount=float(entry.debit_amount),
                credit_amount=float(entry.credit_amount),
                currency=entry.currency,
                cost_center_id=entry.cost_center_id,
                memo=entry.memo
            ))

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="POST_JOURNAL_VOUCHER",
            entity_type="JournalVoucher",
            entity_id=jv.id,
            user_id=user_id,
            changes={"voucher_number": jv.voucher_number, "total_debit": float(total_dr), "total_credit": float(total_cr)}
        )

        await db.commit()
        await db.refresh(jv)

        return JournalVoucherResponse(
            id=jv.id,
            voucher_number=jv.voucher_number,
            voucher_date=jv.voucher_date,
            source_document_type=jv.source_document_type,
            source_document_id=jv.source_document_id,
            status=jv.status,
            posted_at=jv.posted_at,
            notes=jv.notes,
            total_debit=float(total_dr),
            total_credit=float(total_cr),
            lines=lines_out
        )

    @staticmethod
    async def void_journal_voucher(
        db: AsyncSession,
        tenant_id: str,
        voucher_id: str,
        user_id: Optional[str] = None
    ) -> JournalVoucherResponse:
        jv = (await db.execute(
            select(JournalVoucher).where(JournalVoucher.id == voucher_id, JournalVoucher.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not jv:
            raise HTTPException(status_code=404, detail="Journal voucher not found")

        if jv.status == "VOIDED":
            raise HTTPException(status_code=400, detail="Journal voucher is already voided")

        # Validate Accounting Period Lock on original voucher
        orig_v_date = jv.voucher_date
        orig_date = orig_v_date.date() if hasattr(orig_v_date, "date") else orig_v_date
        from app.models.accounting_period import AccountingPeriod
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.start_date <= orig_date,
                AccountingPeriod.end_date >= orig_date
            )
        )).scalar_one_or_none()
        if period and period.status in {"CLOSED", "FINALIZED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Accounting Period '{period.period_code}' is {period.status}. Voiding transactions in closed periods is strictly prohibited."
            )

        jv.status = "VOIDED"

        # Create reversing voucher
        rev_lines = [
            JournalEntryLineCreate(
                account_id=l.account_id,
                debit_amount=l.credit_amount,
                credit_amount=l.debit_amount,
                currency=l.currency,
                memo=f"Reversal of {jv.voucher_number}"
            )
            for l in jv.lines
        ]

        rev_req = JournalVoucherCreate(
            voucher_date=get_utc_now(),
            source_document_type="MANUAL",
            source_document_id=jv.voucher_number,
            notes=f"Reversal voucher for {jv.voucher_number}",
            lines=rev_lines
        )

        await db.commit()
        return await GLService.post_journal_voucher(db, tenant_id, rev_req, user_id=user_id)

    @staticmethod
    async def generate_trial_balance(
        db: AsyncSession,
        tenant_id: str,
        as_of_date: Optional[datetime] = None
    ) -> TrialBalanceResponse:
        cutoff = as_of_date or get_utc_now()
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.is_active == True).order_by(GLAccount.account_code)
        )).scalars().all()

        rows: List[TrialBalanceRow] = []
        tot_deb = Decimal("0.0")
        tot_cred = Decimal("0.0")

        for acc in accounts:
            # Query posted lines
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.debit_amount), Decimal("0.0")),
                func.coalesce(func.sum(JournalEntryLine.credit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == acc.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date <= cutoff
            )
            dr, cr = (await db.execute(stmt)).first()
            dr = Decimal(str(dr)).quantize(Decimal("0.0001"))
            cr = Decimal(str(cr)).quantize(Decimal("0.0001"))

            tot_deb += dr
            tot_cred += cr

            net_dr = max(Decimal("0.0"), dr - cr) if acc.normal_balance == "DEBIT" else Decimal("0.0")
            net_cr = max(Decimal("0.0"), cr - dr) if acc.normal_balance == "CREDIT" else Decimal("0.0")

            rows.append(TrialBalanceRow(
                account_id=acc.id,
                account_code=acc.account_code,
                account_name=acc.account_name,
                account_class=acc.account_class,
                normal_balance=acc.normal_balance,
                total_debit=float(dr),
                total_credit=float(cr),
                net_debit=float(net_dr),
                net_credit=float(net_cr)
            ))

        is_balanced = (tot_deb == tot_cred)
        return TrialBalanceResponse(
            as_of_date=cutoff,
            currency="USD",
            total_debits=float(tot_deb),
            total_credits=float(tot_cred),
            is_balanced=is_balanced,
            accounts=rows
        )

    @staticmethod
    async def generate_income_statement(
        db: AsyncSession,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> IncomeStatementResponse:
        start = start_date or (get_utc_now() - timedelta(days=365))
        end = end_date or get_utc_now()
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        # Revenue
        rev_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "REVENUE")
        )).scalars().all()
        rev_items: List[IncomeStatementSection] = []
        tot_rev = Decimal("0.0")
        for a in rev_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date >= start,
                JournalVoucher.voucher_date <= end
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            if val != Decimal("0.0"):
                rev_items.append(IncomeStatementSection(account_code=a.account_code, account_name=a.account_name, amount=float(val)))
                tot_rev += val

        # COGS
        cogs_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "COGS")
        )).scalars().all()
        cogs_items: List[IncomeStatementSection] = []
        tot_cogs = Decimal("0.0")
        for a in cogs_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date >= start,
                JournalVoucher.voucher_date <= end
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            if val != Decimal("0.0"):
                cogs_items.append(IncomeStatementSection(account_code=a.account_code, account_name=a.account_name, amount=float(val)))
                tot_cogs += val

        gross_margin = tot_rev - tot_cogs
        margin_pct = float((gross_margin / tot_rev * 100).quantize(Decimal("0.01"))) if tot_rev > 0 else 0.0

        # Expenses
        exp_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "EXPENSE")
        )).scalars().all()
        exp_items: List[IncomeStatementSection] = []
        tot_exp = Decimal("0.0")
        for a in exp_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date >= start,
                JournalVoucher.voucher_date <= end
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            if val != Decimal("0.0"):
                exp_items.append(IncomeStatementSection(account_code=a.account_code, account_name=a.account_name, amount=float(val)))
                tot_exp += val

        net_income = gross_margin - tot_exp

        return IncomeStatementResponse(
            start_date=start,
            end_date=end,
            currency="USD",
            revenue_items=rev_items,
            total_revenue=float(tot_rev),
            cogs_items=cogs_items,
            total_cogs=float(tot_cogs),
            gross_margin=float(gross_margin),
            gross_margin_pct=margin_pct,
            expense_items=exp_items,
            total_expenses=float(tot_exp),
            net_income=float(net_income)
        )

    @staticmethod
    async def generate_balance_sheet(
        db: AsyncSession,
        tenant_id: str,
        as_of_date: Optional[datetime] = None
    ) -> BalanceSheetResponse:
        cutoff = as_of_date or get_utc_now()
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        # Assets (Debit - Credit)
        asset_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "ASSET")
        )).scalars().all()
        assets: List[BalanceSheetSection] = []
        tot_assets = Decimal("0.0")
        for a in asset_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date <= cutoff
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            assets.append(BalanceSheetSection(account_code=a.account_code, account_name=a.account_name, account_type=a.account_type, amount=float(val)))
            tot_assets += val

        # Liabilities (Credit - Debit)
        liab_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "LIABILITY")
        )).scalars().all()
        liabilities: List[BalanceSheetSection] = []
        tot_liabilities = Decimal("0.0")
        for a in liab_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date <= cutoff
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            liabilities.append(BalanceSheetSection(account_code=a.account_code, account_name=a.account_name, account_type=a.account_type, amount=float(val)))
            tot_liabilities += val

        # Equity base
        eq_accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_class == "EQUITY")
        )).scalars().all()
        equity_items: List[BalanceSheetSection] = []
        tot_eq_base = Decimal("0.0")
        for a in eq_accounts:
            stmt = select(
                func.coalesce(func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount), Decimal("0.0"))
            ).join(JournalVoucher).where(
                JournalEntryLine.account_id == a.id,
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.status == "POSTED",
                JournalVoucher.voucher_date <= cutoff
            )
            val = Decimal(str((await db.execute(stmt)).scalar() or 0.0))
            equity_items.append(BalanceSheetSection(account_code=a.account_code, account_name=a.account_name, account_type=a.account_type, amount=float(val)))
            tot_eq_base += val

        # Retained Earnings = Cumulative Net Income (Revenue - COGS - Expenses)
        rev_tot = (await db.execute(
            select(func.coalesce(func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount), Decimal("0.0")))
            .join(JournalVoucher).join(GLAccount)
            .where(GLAccount.account_class == "REVENUE", JournalVoucher.tenant_id == tenant_id, JournalVoucher.status == "POSTED", JournalVoucher.voucher_date <= cutoff)
        )).scalar() or Decimal("0.0")

        cogs_tot = (await db.execute(
            select(func.coalesce(func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount), Decimal("0.0")))
            .join(JournalVoucher).join(GLAccount)
            .where(GLAccount.account_class == "COGS", JournalVoucher.tenant_id == tenant_id, JournalVoucher.status == "POSTED", JournalVoucher.voucher_date <= cutoff)
        )).scalar() or Decimal("0.0")

        exp_tot = (await db.execute(
            select(func.coalesce(func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount), Decimal("0.0")))
            .join(JournalVoucher).join(GLAccount)
            .where(GLAccount.account_class == "EXPENSE", JournalVoucher.tenant_id == tenant_id, JournalVoucher.status == "POSTED", JournalVoucher.voucher_date <= cutoff)
        )).scalar() or Decimal("0.0")

        cum_net_income = Decimal(str(rev_tot)) - Decimal(str(cogs_tot)) - Decimal(str(exp_tot))
        tot_equity = tot_eq_base + cum_net_income

        tot_liab_and_eq = tot_liabilities + tot_equity
        is_balanced = (tot_assets == tot_liab_and_eq)

        return BalanceSheetResponse(
            as_of_date=cutoff,
            currency="USD",
            assets=assets,
            total_assets=float(tot_assets),
            liabilities=liabilities,
            total_liabilities=float(tot_liabilities),
            equity=equity_items,
            retained_earnings=float(cum_net_income),
            total_equity=float(tot_equity),
            total_liabilities_and_equity=float(tot_liab_and_eq),
            is_balanced=is_balanced
        )
