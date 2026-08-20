from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.supply_chain import (
    SupplyChainNodeCreate,
    SupplyChainNodeResponse,
    TransferOrderCreate,
    TransferOrderResponse,
    TransferReceiveAction,
    SourcingPlanRequest,
    SourcingPlanResponse,
    EdgeSyncBatchRequest,
    EdgeSyncBatchResponse
)
from app.services.supply_chain_service import SupplyChainService
from app.services.edge_sync_engine import EdgeSyncEngine

router = APIRouter()

# ============================================================================
# SUPPLY CHAIN NODES
# ============================================================================

@router.post("/nodes", response_model=SupplyChainNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_supply_chain_node(
    node_in: SupplyChainNodeCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await SupplyChainService.create_node(
        db=db, tenant_id=claims["tenant_id"], node_in=node_in
    )

@router.post("/sourcing-plan", response_model=SourcingPlanResponse)
async def resolve_sourcing_plan(
    req: SourcingPlanRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await SupplyChainService.resolve_sourcing_plan(
        db=db, tenant_id=claims["tenant_id"], req=req
    )

# ============================================================================
# TRANSFER ORDERS
# ============================================================================

@router.post("/transfers", response_model=TransferOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer_order(
    trf_in: TransferOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await SupplyChainService.create_transfer_order(
        db=db, tenant_id=claims["tenant_id"], trf_in=trf_in
    )

@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOrderResponse)
async def dispatch_transfer_order(
    transfer_id: str,
    source_bin_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await SupplyChainService.dispatch_transfer_order(
        db=db, tenant_id=claims["tenant_id"], transfer_id=transfer_id,
        source_bin_id=source_bin_id, user_id=claims["user_id"]
    )

@router.post("/transfers/{transfer_id}/receive", response_model=TransferOrderResponse)
async def receive_transfer_order(
    transfer_id: str,
    receive_act: TransferReceiveAction,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await SupplyChainService.receive_transfer_order(
        db=db, tenant_id=claims["tenant_id"], transfer_id=transfer_id,
        receive_act=receive_act, user_id=claims["user_id"]
    )

# ============================================================================
# EDGE SYNC BATCH
# ============================================================================

@router.post("/sync/batch", response_model=EdgeSyncBatchResponse)
async def process_edge_sync_batch(
    batch_req: EdgeSyncBatchRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await EdgeSyncEngine.process_sync_batch(
        db=db, tenant_id=claims["tenant_id"], user_id=claims["user_id"], batch_req=batch_req
    )
