from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.fixed_asset import (
    FixedAssetClassCreate,
    FixedAssetClassResponse,
    FixedAssetCreate,
    FixedAssetResponse,
    DepreciationBatchRunRequest,
    DepreciationBatchRunResponse,
    AssetDisposalRequest,
    AssetDisposalResponse
)
from app.services.fixed_asset_service import FixedAssetService

router = APIRouter()

# ============================================================================
# FIXED ASSET CLASSES
# ============================================================================

@router.post("/classes", response_model=FixedAssetClassResponse, status_code=status.HTTP_201_CREATED)
async def create_fixed_asset_class(
    class_in: FixedAssetClassCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await FixedAssetService.create_asset_class(
        db=db, tenant_id=claims["tenant_id"], class_in=class_in
    )

# ============================================================================
# FIXED ASSET CAPITALIZATION
# ============================================================================

@router.post("/", response_model=FixedAssetResponse, status_code=status.HTTP_201_CREATED)
async def create_and_capitalize_fixed_asset(
    asset_in: FixedAssetCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db, tenant_id=claims["tenant_id"], asset_in=asset_in, user_id=claims["user_id"]
    )

# ============================================================================
# MONTHLY DEPRECIATION BATCH RUNNER
# ============================================================================

@router.post("/depreciate/batch", response_model=DepreciationBatchRunResponse)
async def run_monthly_depreciation_batch(
    batch_req: DepreciationBatchRunRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await FixedAssetService.run_monthly_depreciation_batch(
        db=db, tenant_id=claims["tenant_id"], batch_req=batch_req, user_id=claims["user_id"]
    )

# ============================================================================
# ASSET DISPOSAL & SALE
# ============================================================================

@router.post("/{asset_id}/dispose", response_model=AssetDisposalResponse)
async def dispose_fixed_asset(
    asset_id: str,
    disp_req: AssetDisposalRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await FixedAssetService.dispose_fixed_asset(
        db=db, tenant_id=claims["tenant_id"], asset_id=asset_id, disp_req=disp_req, user_id=claims["user_id"]
    )
