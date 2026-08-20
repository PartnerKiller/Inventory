import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.tax_and_currency import TaxJurisdiction, TaxRate, TaxGroup, TaxGroupItem
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.tax_and_currency import (
    TaxJurisdictionCreate,
    TaxJurisdictionResponse,
    TaxRateCreate,
    TaxRateResponse,
    TaxGroupCreate,
    TaxGroupResponse,
    TaxCalculationItemRequest,
    TaxCalculationResponse,
    TaxBreakdownItem,
    TaxSettlementReportResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

class TaxService:

    # ========================================================================
    # 1. JURISDICTIONS, RATES & GROUPS ADMINISTRATION
    # ========================================================================

    @staticmethod
    async def create_jurisdiction(
        db: AsyncSession,
        tenant_id: str,
        jur_in: TaxJurisdictionCreate
    ) -> TaxJurisdictionResponse:
        existing = (await db.execute(
            select(TaxJurisdiction).where(
                TaxJurisdiction.tenant_id == tenant_id,
                TaxJurisdiction.jurisdiction_code == jur_in.jurisdiction_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Jurisdiction '{jur_in.jurisdiction_code}' already exists")

        jur = TaxJurisdiction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            country_code=jur_in.country_code.upper(),
            jurisdiction_code=jur_in.jurisdiction_code.upper(),
            jurisdiction_name=jur_in.jurisdiction_name,
            jurisdiction_type=jur_in.jurisdiction_type,
            is_active=True
        )
        db.add(jur)
        await db.commit()
        await db.refresh(jur)

        return TaxJurisdictionResponse(
            id=jur.id,
            tenant_id=jur.tenant_id,
            country_code=jur.country_code,
            jurisdiction_code=jur.jurisdiction_code,
            jurisdiction_name=jur.jurisdiction_name,
            jurisdiction_type=jur.jurisdiction_type,
            is_active=jur.is_active,
            tax_rates=[],
            created_at=jur.created_at
        )

    @staticmethod
    async def create_tax_rate(
        db: AsyncSession,
        tenant_id: str,
        rate_in: TaxRateCreate
    ) -> TaxRateResponse:
        existing = (await db.execute(
            select(TaxRate).where(
                TaxRate.tenant_id == tenant_id,
                TaxRate.tax_code == rate_in.tax_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Tax rate '{rate_in.tax_code}' already exists")

        rate = TaxRate(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            jurisdiction_id=rate_in.jurisdiction_id,
            tax_code=rate_in.tax_code.upper(),
            tax_name=rate_in.tax_name,
            rate_percentage=rate_in.rate_percentage,
            tax_type=rate_in.tax_type,
            is_compound=rate_in.is_compound,
            is_active=True
        )
        db.add(rate)
        await db.commit()
        await db.refresh(rate)

        return TaxRateResponse(
            id=rate.id,
            tenant_id=rate.tenant_id,
            jurisdiction_id=rate.jurisdiction_id,
            tax_code=rate.tax_code,
            tax_name=rate.tax_name,
            rate_percentage=rate.rate_percentage,
            tax_type=rate.tax_type,
            is_compound=rate.is_compound,
            is_active=rate.is_active,
            created_at=rate.created_at
        )

    @staticmethod
    async def create_tax_group(
        db: AsyncSession,
        tenant_id: str,
        group_in: TaxGroupCreate
    ) -> TaxGroupResponse:
        existing = (await db.execute(
            select(TaxGroup).where(
                TaxGroup.tenant_id == tenant_id,
                TaxGroup.group_code == group_in.group_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Tax group '{group_in.group_code}' already exists")

        group = TaxGroup(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            group_code=group_in.group_code.upper(),
            group_name=group_in.group_name,
            description=group_in.description,
            is_active=True
        )
        db.add(group)

        rates_res: List[TaxRateResponse] = []
        for r_id in group_in.tax_rate_ids:
            r = (await db.execute(
                select(TaxRate).where(TaxRate.id == r_id, TaxRate.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if not r:
                raise HTTPException(status_code=404, detail=f"TaxRate ID '{r_id}' not found")
            item = TaxGroupItem(
                id=str(uuid.uuid4()),
                tax_group_id=group.id,
                tax_rate_id=r.id
            )
            db.add(item)
            rates_res.append(TaxRateResponse(
                id=r.id,
                tenant_id=r.tenant_id,
                jurisdiction_id=r.jurisdiction_id,
                tax_code=r.tax_code,
                tax_name=r.tax_name,
                rate_percentage=r.rate_percentage,
                tax_type=r.tax_type,
                is_compound=r.is_compound,
                is_active=r.is_active,
                created_at=r.created_at
            ))

        await db.commit()
        await db.refresh(group)

        return TaxGroupResponse(
            id=group.id,
            tenant_id=group.tenant_id,
            group_code=group.group_code,
            group_name=group.group_name,
            description=group.description,
            is_active=group.is_active,
            tax_rates=rates_res,
            created_at=group.created_at
        )

    # ========================================================================
    # 2. TAX CALCULATION ENGINE
    # ========================================================================

    @staticmethod
    async def calculate_tax(
        db: AsyncSession,
        tenant_id: str,
        calc_req: TaxCalculationItemRequest
    ) -> TaxCalculationResponse:
        applicable_rates: List[TaxRate] = []

        if calc_req.tax_group_id:
            group = (await db.execute(
                select(TaxGroup).where(TaxGroup.id == calc_req.tax_group_id, TaxGroup.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if group:
                items = (await db.execute(
                    select(TaxGroupItem).where(TaxGroupItem.tax_group_id == group.id)
                )).scalars().all()
                for it in items:
                    if it.tax_rate and it.tax_rate.is_active:
                        applicable_rates.append(it.tax_rate)
        elif calc_req.tax_rate_id:
            r = (await db.execute(
                select(TaxRate).where(TaxRate.id == calc_req.tax_rate_id, TaxRate.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if r and r.is_active:
                applicable_rates.append(r)

        total_tax = Decimal("0.0")
        breakdown: List[TaxBreakdownItem] = []
        base_amt = calc_req.taxable_amount

        for rate in applicable_rates:
            if calc_req.is_tax_inclusive:
                # Tax inclusive formula: Tax = Amount - (Amount / (1 + Rate/100))
                factor = Decimal("1.0") + (Decimal(str(rate.rate_percentage)) / Decimal("100.0"))
                net_base = (calc_req.taxable_amount / factor).quantize(Decimal("0.01"))
                t_amt = (calc_req.taxable_amount - net_base).quantize(Decimal("0.01"))
                base_amt = net_base
            else:
                # Tax exclusive: Tax = Base * Rate/100
                t_amt = ((base_amt * Decimal(str(rate.rate_percentage))) / Decimal("100.0")).quantize(Decimal("0.01"))

            total_tax += t_amt
            breakdown.append(TaxBreakdownItem(
                tax_rate_id=rate.id,
                tax_code=rate.tax_code,
                tax_name=rate.tax_name,
                rate_percentage=rate.rate_percentage,
                tax_amount=t_amt
            ))

        gross = (base_amt + total_tax) if not calc_req.is_tax_inclusive else calc_req.taxable_amount

        return TaxCalculationResponse(
            total_taxable_amount=base_amt,
            total_tax_amount=total_tax,
            gross_amount=gross,
            breakdown=breakdown
        )

    # ========================================================================
    # 3. STATUTORY TAX SETTLEMENT REPORT & DOUBLE-ENTRY GL
    # ========================================================================

    @staticmethod
    async def generate_tax_settlement_report(
        db: AsyncSession,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> TaxSettlementReportResponse:
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1400 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1400"))).scalar_one_or_none()
        acc_2200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2200"))).scalar_one_or_none()

        tot_input_credit = Decimal("0.0")
        tot_output_tax = Decimal("0.0")

        if acc_1400:
            # Input tax credit is Net DEBIT on Account 1400
            dr_1400 = (await db.execute(
                select(func.coalesce(func.sum(JournalEntryLine.debit_amount), Decimal("0.0"))).join(JournalVoucher).where(
                    JournalEntryLine.account_id == acc_1400.id,
                    JournalVoucher.tenant_id == tenant_id,
                    JournalVoucher.status == "POSTED",
                    JournalVoucher.voucher_date >= start_date,
                    JournalVoucher.voucher_date <= end_date
                )
            )).scalar() or Decimal("0.0")
            tot_input_credit = Decimal(str(dr_1400))

        if acc_2200:
            # Output tax liability is Net CREDIT on Account 2200
            cr_2200 = (await db.execute(
                select(func.coalesce(func.sum(JournalEntryLine.credit_amount), Decimal("0.0"))).join(JournalVoucher).where(
                    JournalEntryLine.account_id == acc_2200.id,
                    JournalVoucher.tenant_id == tenant_id,
                    JournalVoucher.status == "POSTED",
                    JournalVoucher.voucher_date >= start_date,
                    JournalVoucher.voucher_date <= end_date
                )
            )).scalar() or Decimal("0.0")
            tot_output_tax = Decimal(str(cr_2200))

        net_payable = (tot_output_tax - tot_input_credit).quantize(Decimal("0.01"))

        return TaxSettlementReportResponse(
            start_date=start_date,
            end_date=end_date,
            total_output_tax=tot_output_tax,
            total_input_tax_credit=tot_input_credit,
            net_tax_payable=net_payable,
            settlement_voucher_id=None
        )

    @staticmethod
    async def execute_tax_settlement(
        db: AsyncSession,
        tenant_id: str,
        settlement_date: datetime,
        output_tax_amount: Decimal,
        input_tax_credit_amount: Decimal,
        user_id: Optional[str] = None
    ) -> Any:
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
        acc_1400 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1400"))).scalar_one()
        acc_2200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2200"))).scalar_one()

        net_payable = (output_tax_amount - input_tax_credit_amount).quantize(Decimal("0.0001"))

        lines = [
            JournalEntryLineCreate(account_id=acc_2200.id, debit_amount=output_tax_amount, credit_amount=Decimal("0.0"), memo="Clear Output Tax Liability"),
            JournalEntryLineCreate(account_id=acc_1400.id, debit_amount=Decimal("0.0"), credit_amount=input_tax_credit_amount, memo="Offset Input Tax Credit"),
            JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=Decimal("0.0"), credit_amount=net_payable, memo="Net Tax Payment to Tax Authority")
        ]

        settle_key = f"TAX-SETTLE-{settlement_date.strftime('%Y%m')}"

        jv = await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=settlement_date,
                source_document_type="TAX_SETTLEMENT",
                source_document_id=settle_key,
                notes=f"Tax Settlement for Period {settlement_date.strftime('%Y-%m')}",
                lines=lines
            ),
            user_id=user_id
        )
        return jv
