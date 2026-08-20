from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.general_ledger import GLAccount, JournalVoucher
from app.schemas.general_ledger import (
    GLAccountCreate,
    GLAccountResponse,
    JournalVoucherCreate,
    JournalVoucherResponse,
    TrialBalanceResponse,
    IncomeStatementResponse,
    BalanceSheetResponse
)
from app.services.gl_service import GLService

router = APIRouter()

@router.get("/accounts", response_model=List[GLAccountResponse])
async def list_chart_of_accounts(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:read"))
):
    tenant_id = claims["tenant_id"]
    accounts = await GLService.seed_standard_chart_of_accounts(db, tenant_id)
    return [
        GLAccountResponse(
            id=a.id,
            account_code=a.account_code,
            account_name=a.account_name,
            account_class=a.account_class,
            account_type=a.account_type,
            currency=a.currency,
            normal_balance=a.normal_balance,
            parent_account_id=a.parent_account_id,
            is_active=a.is_active,
            is_system=a.is_system,
            description=a.description
        )
        for a in accounts
    ]

@router.post("/vouchers", response_model=JournalVoucherResponse, status_code=status.HTTP_201_CREATED)
async def post_journal_voucher(
    req: JournalVoucherCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:manage"))
):
    tenant_id = claims["tenant_id"]
    return await GLService.post_journal_voucher(db, tenant_id, req, user_id=claims.get("sub"))

@router.post("/vouchers/{voucher_id}/void", response_model=JournalVoucherResponse)
async def void_journal_voucher(
    voucher_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:manage"))
):
    tenant_id = claims["tenant_id"]
    return await GLService.void_journal_voucher(db, tenant_id, voucher_id, user_id=claims.get("sub"))

@router.get("/reports/trial-balance", response_model=TrialBalanceResponse)
async def get_trial_balance(
    as_of_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:read"))
):
    tenant_id = claims["tenant_id"]
    return await GLService.generate_trial_balance(db, tenant_id, as_of_date)

@router.get("/reports/income-statement", response_model=IncomeStatementResponse)
async def get_income_statement(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:read"))
):
    tenant_id = claims["tenant_id"]
    return await GLService.generate_income_statement(db, tenant_id, start_date, end_date)

@router.get("/reports/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    as_of_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("financials:read"))
):
    tenant_id = claims["tenant_id"]
    return await GLService.generate_balance_sheet(db, tenant_id, as_of_date)
