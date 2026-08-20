from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.forecasting import (
    DemandForecastProfileCreate,
    DemandForecastProfileResponse,
    ForecastCalculationRequest,
    ForecastCalculationResponse,
    ReplenishmentProposalResponse,
    ConvertProposalToPORequest
)
from app.services.forecasting_service import ForecastingService

router = APIRouter()

# ============================================================================
# FORECAST PROFILES
# ============================================================================

@router.post("/profiles", response_model=DemandForecastProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_forecast_profile(
    profile_in: DemandForecastProfileCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ForecastingService.create_forecast_profile(
        db=db, tenant_id=claims["tenant_id"], profile_in=profile_in
    )

# ============================================================================
# STATISTICAL FORECAST CALCULATION
# ============================================================================

@router.post("/calculate", response_model=ForecastCalculationResponse)
async def calculate_forecast(
    req: ForecastCalculationRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ForecastingService.calculate_forecast(
        db=db, tenant_id=claims["tenant_id"], req=req
    )

# ============================================================================
# REPLENISHMENT PROPOSALS & PO CONVERSION
# ============================================================================

@router.post("/proposals/generate", response_model=ReplenishmentProposalResponse, status_code=status.HTTP_201_CREATED)
async def generate_replenishment_proposal(
    item_id: str,
    warehouse_id: str,
    current_stock: Decimal,
    in_transit_stock: Decimal = Decimal("0.0"),
    service_level: Decimal = Decimal("0.95"),
    lead_time_days: Decimal = Decimal("7.0"),
    lead_time_std_dev: Decimal = Decimal("1.5"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ForecastingService.generate_replenishment_proposal(
        db=db, tenant_id=claims["tenant_id"],
        item_id=item_id, warehouse_id=warehouse_id,
        current_stock=current_stock, in_transit_stock=in_transit_stock,
        service_level=service_level, lead_time_days=lead_time_days, lead_time_std_dev=lead_time_std_dev
    )

@router.post("/proposals/{proposal_id}/convert-to-po", response_model=ReplenishmentProposalResponse)
async def convert_proposal_to_po(
    proposal_id: str,
    conv_req: ConvertProposalToPORequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ForecastingService.convert_proposal_to_purchase_order(
        db=db, tenant_id=claims["tenant_id"], proposal_id=proposal_id, conv_req=conv_req, user_id=claims["user_id"]
    )
