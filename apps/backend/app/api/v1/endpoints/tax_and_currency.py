from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.tax_and_currency import (
    ExchangeRateCreate,
    ExchangeRateResponse,
    TaxJurisdictionCreate,
    TaxJurisdictionResponse,
    TaxRateCreate,
    TaxRateResponse,
    TaxGroupCreate,
    TaxGroupResponse,
    TaxCalculationItemRequest,
    TaxCalculationResponse,
    TaxSettlementReportResponse
)
from app.services.currency_service import CurrencyService
from app.services.tax_service import TaxService

router = APIRouter()

# ============================================================================
# CURRENCY EXCHANGE RATES
# ============================================================================

@router.post("/currency/exchange-rates", response_model=ExchangeRateResponse, status_code=status.HTTP_201_CREATED)
async def create_exchange_rate(
    rate_in: ExchangeRateCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await CurrencyService.create_exchange_rate(
        db=db, tenant_id=claims["tenant_id"], rate_in=rate_in
    )

# ============================================================================
# TAX JURISDICTIONS & RATES
# ============================================================================

@router.post("/tax/jurisdictions", response_model=TaxJurisdictionResponse, status_code=status.HTTP_201_CREATED)
async def create_tax_jurisdiction(
    jur_in: TaxJurisdictionCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await TaxService.create_jurisdiction(
        db=db, tenant_id=claims["tenant_id"], jur_in=jur_in
    )

@router.post("/tax/rates", response_model=TaxRateResponse, status_code=status.HTTP_201_CREATED)
async def create_tax_rate(
    rate_in: TaxRateCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await TaxService.create_tax_rate(
        db=db, tenant_id=claims["tenant_id"], rate_in=rate_in
    )

@router.post("/tax/groups", response_model=TaxGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_tax_group(
    group_in: TaxGroupCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await TaxService.create_tax_group(
        db=db, tenant_id=claims["tenant_id"], group_in=group_in
    )

@router.post("/tax/calculate", response_model=TaxCalculationResponse)
async def calculate_tax(
    calc_req: TaxCalculationItemRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await TaxService.calculate_tax(
        db=db, tenant_id=claims["tenant_id"], calc_req=calc_req
    )

@router.get("/tax/settlement-report", response_model=TaxSettlementReportResponse)
async def get_tax_settlement_report(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await TaxService.generate_tax_settlement_report(
        db=db, tenant_id=claims["tenant_id"], start_date=start_date, end_date=end_date
    )
