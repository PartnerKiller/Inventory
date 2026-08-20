from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.portal import PortalLoginRequest, PortalLoginResponse
from app.services.portal_service import PortalService

router = APIRouter()

@router.post("/login", response_model=PortalLoginResponse)
async def portal_login(
    req: PortalLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticates a B2B Customer or Supplier portal user.
    Returns JWT with entity_id (customer_id or supplier_id) and explicit portal permissions.
    """
    return await PortalService.authenticate_portal_user(db, req)
