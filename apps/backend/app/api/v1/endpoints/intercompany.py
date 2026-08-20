from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.intercompany import (
    IntercompanyPartnerCreate,
    IntercompanyPartnerResponse,
    MirroredOrderCreate,
    IntercompanyTransactionPairResponse,
    ConsolidationRunCreate,
    ConsolidationRunResponse,
    UnrealizedProfitEliminationCreate,
    UnrealizedProfitEliminationResponse,
    ConsolidatedTrialBalanceResponse,
    ConsolidatedFinancialStatementResponse
)
from app.services.intercompany_service import IntercompanyService

router = APIRouter()

# ============================================================================
# INTERCOMPANY PARTNER & MIRRORED ORDER ENDPOINTS
# ============================================================================

@router.post("/partners", response_model=IntercompanyPartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_partner(
    partner_in: IntercompanyPartnerCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.create_partner_relationship(
        db=db, tenant_id=claims["tenant_id"], partner_in=partner_in
    )

@router.post("/mirrored-order", response_model=IntercompanyTransactionPairResponse, status_code=status.HTTP_201_CREATED)
async def create_mirrored_order(
    req: MirroredOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.create_mirrored_intercompany_order(
        db=db, tenant_id=claims["tenant_id"], req=req, user_id=claims["user_id"]
    )

# ============================================================================
# CONSOLIDATION RUN ENDPOINTS
# ============================================================================

@router.post("/consolidations", response_model=ConsolidationRunResponse, status_code=status.HTTP_201_CREATED)
async def run_consolidation(
    cons_in: ConsolidationRunCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.generate_consolidation_eliminations(
        db=db, tenant_id=claims["tenant_id"], cons_in=cons_in, user_id=claims["user_id"]
    )

# ============================================================================
# UNREALIZED PROFIT ELIMINATION & CONSOLIDATED REPORTING (PHASE 31)
# ============================================================================

@router.post("/unrealized-profit/eliminate", response_model=UnrealizedProfitEliminationResponse, status_code=status.HTTP_201_CREATED)
async def eliminate_unrealized_profit(
    req: UnrealizedProfitEliminationCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.eliminate_unrealized_inventory_profit(
        db=db, tenant_id=claims["tenant_id"], req=req, user_id=claims["user_id"]
    )

@router.get("/reports/trial-balance", response_model=ConsolidatedTrialBalanceResponse)
async def get_consolidated_trial_balance(
    period_id: str = Query(..., description="Accounting Period ID"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.get_consolidated_trial_balance(
        db=db, tenant_id=claims["tenant_id"], period_id=period_id
    )

@router.get("/reports/financial-statements", response_model=ConsolidatedFinancialStatementResponse)
async def get_consolidated_financial_statements(
    period_id: str = Query(..., description="Accounting Period ID"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await IntercompanyService.get_consolidated_financial_statements(
        db=db, tenant_id=claims["tenant_id"], period_id=period_id
    )
