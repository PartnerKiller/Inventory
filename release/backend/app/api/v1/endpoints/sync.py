from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.permissions import require_permission, get_current_user_claims
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncHandshakeResponse,
    SyncUpstreamBatchRequest,
    SyncUpstreamBatchResponse,
    SyncDownstreamResponse,
    SyncDeviceResponse,
    SyncDeviceRevokeRequest,
    ChangeFeedResponse
)
from app.models.sync import SyncDevice
from app.services.sync_service import SyncService

router = APIRouter()

# ============================================================================
# SYNC PROTOCOL ENDPOINTS
# ============================================================================

@router.post("/handshake", response_model=SyncHandshakeResponse)
async def sync_handshake(
    req: SyncHandshakeRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:read"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id") or claims.get("sub")
    return await SyncService.handshake_device(db, tenant_id, user_id=user_id, req=req)

@router.post("/upstream", response_model=SyncUpstreamBatchResponse)
async def sync_upstream_batch(
    req: SyncUpstreamBatchRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:write"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id") or claims.get("sub")
    return await SyncService.process_upstream_batch(db, tenant_id, user_id=user_id, req=req)

@router.get("/downstream", response_model=SyncDownstreamResponse)
async def sync_downstream_delta(
    warehouse_id: str = Query(..., description="Target Warehouse ID for delta cache"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:read"))
):
    tenant_id = claims["tenant_id"]
    return await SyncService.get_downstream_delta(db, tenant_id, warehouse_id=warehouse_id)

@router.get("/feed", response_model=ChangeFeedResponse)
async def sync_change_feed(
    since_revision: int = Query(0, ge=0, description="Highest revision ID client has previously synchronized"),
    limit: int = Query(200, ge=1, le=1000, description="Max change records to stream in batch"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("warehouse:read"))
):
    tenant_id = claims["tenant_id"]
    return await SyncService.get_change_feed(db, tenant_id, since_revision=since_revision, limit=limit)

# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@router.get("/devices", response_model=List[SyncDeviceResponse])
async def list_sync_devices(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("administration:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(SyncDevice).where(SyncDevice.tenant_id == tenant_id).order_by(SyncDevice.created_at.desc())
    devices = (await db.execute(stmt)).scalars().all()
    return devices

@router.put("/devices/{device_id}/revoke", response_model=SyncDeviceResponse)
async def revoke_device(
    device_id: str,
    req: SyncDeviceRevokeRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("administration:write"))
):
    tenant_id = claims["tenant_id"]
    admin_user_id = claims.get("user_id") or claims.get("sub")
    return await SyncService.revoke_device(db, tenant_id, device_id=device_id, reason=req.reason, admin_user_id=admin_user_id)

@router.put("/devices/{device_id}/restore", response_model=SyncDeviceResponse)
async def restore_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("administration:write"))
):
    tenant_id = claims["tenant_id"]
    admin_user_id = claims.get("user_id") or claims.get("sub")
    return await SyncService.restore_device(db, tenant_id, device_id=device_id, admin_user_id=admin_user_id)
