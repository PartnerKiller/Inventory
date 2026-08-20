from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.vendor_scorecard import (
    SupplierScorecardGenerateRequest,
    SupplierScorecardResponse
)
from app.services.vendor_scorecard_service import VendorScorecardService

router = APIRouter()

@router.post("/generate", response_model=SupplierScorecardResponse, status_code=status.HTTP_200_OK)
async def generate_scorecard(
    req: SupplierScorecardGenerateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Generate or refresh a quantitative supplier scorecard."""
    return await VendorScorecardService.generate_supplier_scorecard(
        db=db,
        tenant_id=claims.get("tenant_id", "default"),
        supplier_id=req.supplier_id,
        period_code=req.period_code
    )

@router.get("", response_model=List[SupplierScorecardResponse], status_code=status.HTTP_200_OK)
async def list_scorecards(
    supplier_id: Optional[str] = Query(None, description="Filter by supplier ID"),
    period_code: Optional[str] = Query(None, description="Filter by evaluation period code"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """List historical supplier scorecards."""
    return await VendorScorecardService.get_supplier_scorecards(
        db=db,
        tenant_id=claims.get("tenant_id", "default"),
        supplier_id=supplier_id,
        period_code=period_code
    )
