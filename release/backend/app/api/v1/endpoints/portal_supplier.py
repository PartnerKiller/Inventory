from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.base import get_utc_now
from app.schemas.portal import (
    SupplierProfileResponse,
    SupplierPOResponse,
    SupplierPOConfirmRequest,
    SupplierPORejectRequest,
    CreateASNRequest,
    ASNResponse
)
from app.services.portal_service import PortalService

router = APIRouter()

@router.get("/profile", response_model=SupplierProfileResponse)
async def get_supplier_profile(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("supplier:profile:read"))
):
    tenant_id = claims["tenant_id"]
    supplier_id = claims.get("supplier_id") or claims.get("entity_id")
    if not supplier_id:
        raise HTTPException(status_code=403, detail="Not a supplier portal session")
    return await PortalService.get_supplier_profile(db, tenant_id, supplier_id)

@router.get("/purchase-orders", response_model=List[SupplierPOResponse])
async def list_supplier_purchase_orders(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("supplier:purchase_orders:read"))
):
    tenant_id = claims["tenant_id"]
    supplier_id = claims.get("supplier_id") or claims.get("entity_id")
    if not supplier_id:
        raise HTTPException(status_code=403, detail="Not a supplier portal session")
    return await PortalService.get_supplier_purchase_orders(db, tenant_id, supplier_id)

@router.post("/purchase-orders/{po_id}/confirm", response_model=SupplierPOResponse)
async def confirm_purchase_order(
    po_id: str,
    req: SupplierPOConfirmRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("supplier:purchase_orders:confirm"))
):
    tenant_id = claims["tenant_id"]
    supplier_id = claims.get("supplier_id") or claims.get("entity_id")
    if not supplier_id:
        raise HTTPException(status_code=403, detail="Not a supplier portal session")
    return await PortalService.confirm_purchase_order(db, tenant_id, supplier_id, po_id, req, portal_user_id=claims.get("sub"))

@router.post("/purchase-orders/{po_id}/reject", response_model=SupplierPOResponse)
async def reject_purchase_order(
    po_id: str,
    req: SupplierPORejectRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("supplier:purchase_orders:reject"))
):
    tenant_id = claims["tenant_id"]
    supplier_id = claims.get("supplier_id") or claims.get("entity_id")
    if not supplier_id:
        raise HTTPException(status_code=403, detail="Not a supplier portal session")
    return await PortalService.reject_purchase_order(db, tenant_id, supplier_id, po_id, req, portal_user_id=claims.get("sub"))

@router.post("/asn", response_model=ASNResponse, status_code=status.HTTP_201_CREATED)
async def create_advance_shipping_notice(
    req: CreateASNRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("supplier:asn:create"))
):
    tenant_id = claims["tenant_id"]
    supplier_id = claims.get("supplier_id") or claims.get("entity_id")
    if not supplier_id:
        raise HTTPException(status_code=403, detail="Not a supplier portal session")
    return await PortalService.create_advance_shipping_notice(db, tenant_id, supplier_id, req, portal_user_id=claims.get("sub"))
