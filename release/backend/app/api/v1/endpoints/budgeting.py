from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.budgeting import (
    CostCenterCreate,
    CostCenterResponse,
    DepartmentalBudgetCreate,
    DepartmentalBudgetResponse,
    BudgetCommitmentRequest,
    BudgetCommitmentResponse,
    CostCenterVarianceReport
)
from app.services.budget_service import BudgetService

router = APIRouter()

# ============================================================================
# COST CENTERS
# ============================================================================

@router.post("/cost-centers", response_model=CostCenterResponse, status_code=status.HTTP_201_CREATED)
async def create_cost_center(
    cc_in: CostCenterCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await BudgetService.create_cost_center(
        db=db, tenant_id=claims["tenant_id"], cc_in=cc_in
    )

# ============================================================================
# DEPARTMENTAL BUDGETS
# ============================================================================

@router.post("/", response_model=DepartmentalBudgetResponse, status_code=status.HTTP_201_CREATED)
async def create_departmental_budget(
    budget_in: DepartmentalBudgetCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await BudgetService.create_departmental_budget(
        db=db, tenant_id=claims["tenant_id"], budget_in=budget_in
    )

@router.post("/{budget_id}/approve", response_model=DepartmentalBudgetResponse)
async def approve_departmental_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await BudgetService.approve_departmental_budget(
        db=db, tenant_id=claims["tenant_id"], budget_id=budget_id
    )

# ============================================================================
# COMMITMENT ACCOUNTING & VARIANCE
# ============================================================================

@router.post("/commit", response_model=BudgetCommitmentResponse)
async def commit_budget(
    req: BudgetCommitmentRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await BudgetService.commit_budget(
        db=db, tenant_id=claims["tenant_id"], req=req
    )

@router.get("/cost-centers/{cost_center_id}/variance", response_model=CostCenterVarianceReport)
async def get_cost_center_variance_report(
    cost_center_id: str,
    period_code: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await BudgetService.generate_cost_center_variance_report(
        db=db, tenant_id=claims["tenant_id"], cost_center_id=cost_center_id, period_code=period_code
    )
