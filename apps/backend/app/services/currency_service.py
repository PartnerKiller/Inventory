import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.tax_and_currency import CurrencyExchangeRate
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.tax_and_currency import (
    ExchangeRateCreate,
    ExchangeRateResponse,
    FXRevaluationRequest,
    FXRevaluationResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

class CurrencyService:

    @staticmethod
    async def create_exchange_rate(
        db: AsyncSession,
        tenant_id: str,
        rate_in: ExchangeRateCreate
    ) -> ExchangeRateResponse:
        rate = CurrencyExchangeRate(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            from_currency=rate_in.from_currency.upper(),
            to_currency=rate_in.to_currency.upper(),
            rate=rate_in.rate,
            effective_date=rate_in.effective_date or get_utc_now(),
            is_active=True
        )
        db.add(rate)
        await db.commit()
        await db.refresh(rate)

        return ExchangeRateResponse(
            id=rate.id,
            tenant_id=rate.tenant_id,
            from_currency=rate.from_currency,
            to_currency=rate.to_currency,
            rate=rate.rate,
            effective_date=rate.effective_date,
            is_active=rate.is_active,
            created_at=rate.created_at
        )

    @staticmethod
    async def get_exchange_rate(
        db: AsyncSession,
        tenant_id: str,
        from_currency: str,
        to_currency: str = "USD",
        as_of_date: Optional[datetime] = None
    ) -> Decimal:
        if from_currency.upper() == to_currency.upper():
            return Decimal("1.0")

        target_dt = as_of_date or get_utc_now()
        rate_obj = (await db.execute(
            select(CurrencyExchangeRate).where(
                CurrencyExchangeRate.tenant_id == tenant_id,
                CurrencyExchangeRate.from_currency == from_currency.upper(),
                CurrencyExchangeRate.to_currency == to_currency.upper(),
                CurrencyExchangeRate.effective_date <= target_dt,
                CurrencyExchangeRate.is_active == True
            ).order_by(CurrencyExchangeRate.effective_date.desc())
        )).scalars().first()

        if not rate_obj:
            # Check inverse rate
            inv_rate = (await db.execute(
                select(CurrencyExchangeRate).where(
                    CurrencyExchangeRate.tenant_id == tenant_id,
                    CurrencyExchangeRate.from_currency == to_currency.upper(),
                    CurrencyExchangeRate.to_currency == from_currency.upper(),
                    CurrencyExchangeRate.effective_date <= target_dt,
                    CurrencyExchangeRate.is_active == True
                ).order_by(CurrencyExchangeRate.effective_date.desc())
            )).scalars().first()
            if inv_rate and inv_rate.rate > 0:
                return (Decimal("1.0") / Decimal(str(inv_rate.rate))).quantize(Decimal("0.000001"))
            return Decimal("1.0")

        return Decimal(str(rate_obj.rate))

    @staticmethod
    async def post_realized_fx_settlement(
        db: AsyncSession,
        tenant_id: str,
        invoice_id: str,
        original_base_amount: Decimal,
        settled_base_amount: Decimal,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Posts realized FX gain/loss when a foreign invoice is settled at a different spot rate.
        - If settled > original (Gain for AR) -> Dr Cash / Cr AR (orig) / Cr 6300 Realized FX Gain
        - If settled < original (Loss for AR) -> Dr Cash / Dr 6300 Realized FX Loss / Cr AR (orig)
        """
        diff = (settled_base_amount - original_base_amount).quantize(Decimal("0.0001"))
        if diff == Decimal("0.0"):
            return None

        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one_or_none()
        acc_1100 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1100"))).scalar_one_or_none()
        acc_6300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6300"))).scalar_one_or_none()

        if not (acc_1000 and acc_1100 and acc_6300):
            return None

        lines: List[JournalEntryLineCreate] = []
        if diff > Decimal("0.0"): # Realized FX Gain
            lines = [
                JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=settled_base_amount, credit_amount=Decimal("0.0"), memo="Cash received at settlement rate"),
                JournalEntryLineCreate(account_id=acc_1100.id, debit_amount=Decimal("0.0"), credit_amount=original_base_amount, memo="Clear AR at booked rate"),
                JournalEntryLineCreate(account_id=acc_6300.id, debit_amount=Decimal("0.0"), credit_amount=diff, memo="Realized FX Gain on foreign settlement")
            ]
        else: # Realized FX Loss
            lines = [
                JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=settled_base_amount, credit_amount=Decimal("0.0"), memo="Cash received at settlement rate"),
                JournalEntryLineCreate(account_id=acc_6300.id, debit_amount=abs(diff), credit_amount=Decimal("0.0"), memo="Realized FX Loss on foreign settlement"),
                JournalEntryLineCreate(account_id=acc_1100.id, debit_amount=Decimal("0.0"), credit_amount=original_base_amount, memo="Clear AR at booked rate")
            ]

        jv = await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=get_utc_now(),
                source_document_type="FX_SETTLEMENT",
                source_document_id=invoice_id,
                notes=f"Realized FX Settlement for Invoice {invoice_id}",
                lines=lines
            ),
            user_id=user_id
        )
        return jv.id

    @staticmethod
    async def execute_month_end_revaluation(
        db: AsyncSession,
        tenant_id: str,
        reval_date: datetime,
        foreign_ar_amount: Decimal,
        original_base_ar: Decimal,
        closing_rate: Decimal,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Revalues open foreign AR balance at period-end closing spot rate.
        Calculates unrealized gain/loss:
        Revalued Base = foreign_ar_amount * closing_rate
        Unrealized Gain/Loss = Revalued Base - original_base_ar
        """
        reval_key = f"FX-REVAL-{reval_date.strftime('%Y%m')}"
        revalued_base = (foreign_ar_amount * closing_rate).quantize(Decimal("0.0001"))
        diff = (revalued_base - original_base_ar).quantize(Decimal("0.0001"))
        if diff == Decimal("0.0"):
            return None

        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1100 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1100"))).scalar_one_or_none()
        acc_6300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6300"))).scalar_one_or_none()

        if not (acc_1100 and acc_6300):
            return None

        lines: List[JournalEntryLineCreate] = []
        if diff > Decimal("0.0"):
            lines = [
                JournalEntryLineCreate(account_id=acc_1100.id, debit_amount=diff, credit_amount=Decimal("0.0"), memo="Unrealized FX Gain on open AR revaluation"),
                JournalEntryLineCreate(account_id=acc_6300.id, debit_amount=Decimal("0.0"), credit_amount=diff, memo="Unrealized FX Gain on open AR revaluation")
            ]
        else:
            lines = [
                JournalEntryLineCreate(account_id=acc_6300.id, debit_amount=abs(diff), credit_amount=Decimal("0.0"), memo="Unrealized FX Loss on open AR revaluation"),
                JournalEntryLineCreate(account_id=acc_1100.id, debit_amount=Decimal("0.0"), credit_amount=abs(diff), memo="Unrealized FX Loss on open AR revaluation")
            ]

        jv = await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=reval_date,
                source_document_type="UNREALIZED_FX_REVALUATION",
                source_document_id=reval_key,
                notes=f"Unrealized FX Revaluation for {reval_date.strftime('%Y-%m')}",
                lines=lines
            ),
            user_id=user_id
        )
        return jv.id
