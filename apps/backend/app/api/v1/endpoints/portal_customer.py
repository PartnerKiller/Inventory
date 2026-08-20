from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.base import get_utc_now
from app.schemas.portal import (
    CustomerProfileResponse,
    CustomerCatalogItemResponse,
    CustomerOrderCreateRequest,
    CustomerOrderResponse,
    CustomerReturnCreateRequest,
    CustomerReturnResponse,
    SecureDocumentTokenResponse
)
from app.services.portal_service import PortalService

router = APIRouter()

@router.get("/profile", response_model=CustomerProfileResponse)
async def get_customer_profile(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("customer:profile:read"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Not a customer portal session")
    return await PortalService.get_customer_profile(db, tenant_id, customer_id)

@router.get("/catalog", response_model=List[CustomerCatalogItemResponse])
async def get_customer_catalog(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("customer:catalog:read"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Not a customer portal session")
    return await PortalService.get_customer_catalog(db, tenant_id, customer_id)

@router.get("/orders", response_model=List[CustomerOrderResponse])
async def list_customer_orders(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("customer:orders:read"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Not a customer portal session")
    return await PortalService.get_customer_orders(db, tenant_id, customer_id)

@router.post("/orders", response_model=CustomerOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_customer_order(
    req: CustomerOrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("customer:orders:create"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Not a customer portal session")
    return await PortalService.create_customer_sales_order(db, tenant_id, customer_id, req, portal_user_id=claims.get("sub"))

@router.post("/orders/{so_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_customer_order(
    so_id: str,
    reason: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("customer:orders:cancel"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="Not a customer portal session")
    so = await PortalService.cancel_customer_sales_order(db, tenant_id, customer_id, so_id, reason, portal_user_id=claims.get("sub"))
    return {"message": "Sales order cancelled successfully", "so_number": so.so_number, "status": so.status}

@router.get("/documents/{document_type}/{document_id}/token", response_model=SecureDocumentTokenResponse)
async def get_document_download_token(
    document_type: str,
    document_id: str,
    claims: dict = Depends(require_permission("customer:orders:read"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id") or claims.get("entity_id")
    token_str = PortalService.generate_document_token(tenant_id, customer_id, document_type, document_id)
    return SecureDocumentTokenResponse(
        document_type=document_type,
        document_id=document_id,
        download_url=f"/api/v1/portal/customer/documents/download?token={token_str}",
        expires_at=PortalService.get_utc_now() if hasattr(PortalService, 'get_utc_now') else datetime.utcnow()
    )
