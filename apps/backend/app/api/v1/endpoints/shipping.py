from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.shipping import CarrierAccount, CarrierManifest
from app.schemas.shipping import (
    CarrierAccountCreate,
    CarrierAccountResponse,
    RateShoppingRequest,
    RateShoppingResponse,
    GenerateShippingLabelRequest,
    ShippingLabelResponse,
    VoidShippingLabelRequest,
    IngestTrackingEventRequest,
    ShipmentTrackingTimelineResponse,
    CreateCarrierManifestRequest,
    CarrierManifestResponse
)
from app.services.carrier_service import CarrierService

router = APIRouter()

@router.get("/accounts", response_model=List[CarrierAccountResponse])
async def list_carrier_accounts(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(CarrierAccount).where(CarrierAccount.tenant_id == tenant_id, CarrierAccount.is_deleted == False)
    accs = (await db.execute(stmt)).scalars().all()
    return accs

@router.post("/accounts", response_model=CarrierAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_carrier_account(
    acc_in: CarrierAccountCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:write"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.create_carrier_account(db, tenant_id, acc_in, user_id=claims.get("sub"))

@router.post("/rate-shopping", response_model=RateShoppingResponse)
async def perform_rate_shopping(
    req: RateShoppingRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:read"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.rate_shopping(db, tenant_id, req)

@router.post("/labels/generate", response_model=ShippingLabelResponse)
async def generate_shipping_label(
    req: GenerateShippingLabelRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:write"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.generate_shipping_label(db, tenant_id, req, user_id=claims.get("sub"))

@router.post("/labels/void", response_model=bool)
async def void_shipping_label(
    req: VoidShippingLabelRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:write"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.void_shipping_label(db, tenant_id, req, user_id=claims.get("sub"))

@router.get("/tracking/{tracking_number}", response_model=ShipmentTrackingTimelineResponse)
async def get_tracking_timeline(
    tracking_number: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:read"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.get_tracking_timeline(db, tenant_id, tracking_number)

import hmac
import hashlib
from fastapi import Request, Header

@router.post("/webhooks/events", status_code=status.HTTP_200_OK)
async def ingest_tracking_webhook_event(
    req: IngestTrackingEventRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_carrier_signature: Optional[str] = Header(None, alias="X-Carrier-Signature")
):
    # Lookup CarrierAccount for webhook verification if secret is configured
    acc_stmt = select(CarrierAccount).where(CarrierAccount.carrier_code == req.carrier_code.upper(), CarrierAccount.is_active == True)
    acc = (await db.execute(acc_stmt)).scalars().first()

    if acc and acc.webhook_secret:
        if not x_carrier_signature:
            raise HTTPException(status_code=401, detail="Missing X-Carrier-Signature header")

        body_bytes = await request.body()
        expected_sig = hmac.new(acc.webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, x_carrier_signature):
            raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    evt = await CarrierService.ingest_tracking_event(db, tenant_id="00000000-0000-0000-0000-000000000001", req=req)
    return {"status": "ACK", "event_id": evt.id}

@router.post("/manifests", response_model=CarrierManifestResponse, status_code=status.HTTP_201_CREATED)
async def create_carrier_manifest(
    req: CreateCarrierManifestRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("shipping:write"))
):
    tenant_id = claims["tenant_id"]
    return await CarrierService.create_carrier_manifest(db, tenant_id, req, user_id=claims.get("sub"))
