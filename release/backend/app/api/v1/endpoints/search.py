from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.reports import GlobalSearchResponse
from app.services.report_service import ReportService

router = APIRouter()

@router.get("", response_model=GlobalSearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Search query across products, barcodes, customers, suppliers, POs, SOs, and facilities"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    return await ReportService.global_search(db, tenant_id, q)
