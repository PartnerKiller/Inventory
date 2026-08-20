from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.accounting_period import (
    FiscalYearCreate,
    FiscalYearResponse,
    AccountingPeriodResponse,
    PeriodStatusUpdateRequest,
    YearEndClosingRequest,
    YearEndClosingResponse
)
from app.services.period_closing_service import PeriodClosingService

router = APIRouter()

# ============================================================================
# FISCAL YEAR MANAGEMENT
# ============================================================================

@router.post("/fiscal-years", response_model=FiscalYearResponse, status_code=status.HTTP_201_CREATED)
async def create_fiscal_year_with_periods(
    fy_in: FiscalYearCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PeriodClosingService.create_fiscal_year_with_periods(
        db=db, tenant_id=claims["tenant_id"], fy_in=fy_in
    )

# ============================================================================
# ACCOUNTING PERIOD STATUS & CLOSING
# ============================================================================

@router.put("/periods/{period_id}/status", response_model=AccountingPeriodResponse)
async def update_accounting_period_status(
    period_id: str,
    req: PeriodStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PeriodClosingService.update_period_status(
        db=db, tenant_id=claims["tenant_id"], period_id=period_id, req=req, user_id=claims["user_id"]
    )

# ============================================================================
# YEAR-END CLOSING CEREMONY
# ============================================================================

@router.post("/year-end/closing", response_model=YearEndClosingResponse)
async def execute_year_end_closing(
    req: YearEndClosingRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PeriodClosingService.execute_year_end_closing(
        db=db, tenant_id=claims["tenant_id"], req=req, user_id=claims["user_id"]
    )
