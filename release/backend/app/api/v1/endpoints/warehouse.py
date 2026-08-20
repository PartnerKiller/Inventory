from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims, require_permission
from app.services.warehouse_service import WarehouseService
from app.schemas.warehouse_ops import (
    BarcodeResolutionRequest, BarcodeResolutionResponse,
    PutawayExecutionRequest, PutawayExecutionResponse,
    BinTransferRequest, BinTransferResponse,
    CountSessionCreateRequest, CountSessionResponse,
    CountSessionSubmitRequest, CountSessionApprovalRequest,
    PickTaskResponse, PickLineConfirmRequest,
    PackingSessionResponse, PackingItemVerifyRequest, PackingItemVerifyResponse,
    LabelGenerationRequest, LabelGenerationResponse
)

router = APIRouter()

@router.post("/barcode/resolve", response_model=BarcodeResolutionResponse, summary="Universal Barcode Resolver")
async def resolve_barcode(
    payload: BarcodeResolutionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    return await WarehouseService.resolve_barcode(
        db=db,
        tenant_id=tenant_id,
        raw_barcode=payload.raw_barcode,
        warehouse_id=payload.warehouse_id
    )

@router.post("/putaway/execute", response_model=PutawayExecutionResponse, summary="Execute Staging to Storage Putaway")
async def execute_putaway(
    payload: PutawayExecutionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("ledger:transfer"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.execute_putaway(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=payload.warehouse_id,
        source_staging_bin_id=payload.source_staging_bin_id,
        destination_storage_bin_id=payload.destination_storage_bin_id,
        item_variant_id=payload.item_variant_id,
        quantity=Decimal(str(payload.quantity)),
        batch_id=payload.batch_id,
        user_id=user_id
    )

@router.post("/transfer/bin-to-bin", response_model=BinTransferResponse, summary="Rapid Intra-Warehouse Bin Movement")
async def execute_bin_transfer(
    payload: BinTransferRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("ledger:transfer"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.execute_bin_transfer(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=payload.warehouse_id,
        source_bin_id=payload.source_bin_id,
        destination_bin_id=payload.destination_bin_id,
        item_variant_id=payload.item_variant_id,
        quantity=Decimal(str(payload.quantity)),
        batch_id=payload.batch_id,
        user_id=user_id
    )

@router.post("/counts/sessions", response_model=CountSessionResponse, summary="Create Cycle Count Session")
async def create_count_session(
    payload: CountSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:adjust"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.create_count_session(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=payload.warehouse_id,
        scope_type=payload.scope_type,
        bin_ids=payload.bin_ids,
        category_id=payload.category_id,
        notes=payload.notes,
        user_id=user_id
    )

@router.get("/counts/{session_id}", response_model=CountSessionResponse, summary="Get Count Session Details")
async def get_count_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    return await WarehouseService.get_count_session(db, tenant_id, session_id)

@router.post("/counts/{session_id}/submit", response_model=CountSessionResponse, summary="Submit Floor Count Counts")
async def submit_count_results(
    session_id: str,
    payload: CountSessionSubmitRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:adjust"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    counts_dicts = [c.model_dump() for c in payload.counts]
    return await WarehouseService.submit_count_results(
        db=db,
        tenant_id=tenant_id,
        session_id=session_id,
        counts=counts_dicts,
        user_id=user_id
    )

@router.post("/counts/{session_id}/approve", response_model=CountSessionResponse, summary="Supervisor Review & Approval")
async def approve_count_session(
    session_id: str,
    payload: CountSessionApprovalRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:adjust"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.approve_count_session(
        db=db,
        tenant_id=tenant_id,
        session_id=session_id,
        action=payload.action,
        review_notes=payload.review_notes,
        supervisor_user_id=user_id
    )

@router.get("/picking/{sales_order_id}/task", response_model=PickTaskResponse, summary="Get Guided Pick Task")
async def get_pick_task(
    sales_order_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.get_or_create_pick_task(db, tenant_id, sales_order_id, user_id)

@router.post("/picking/confirm-line", response_model=PickTaskResponse, summary="Confirm Pick Line with Scan Verification")
async def confirm_pick_line(
    payload: PickLineConfirmRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.confirm_pick_line(
        db=db,
        tenant_id=tenant_id,
        pick_task_line_id=payload.pick_task_line_id,
        scanned_bin_code=payload.scanned_bin_code,
        scanned_item_barcode=payload.scanned_item_barcode,
        quantity_picked=Decimal(str(payload.quantity_picked)),
        user_id=user_id
    )

@router.get("/packing/{shipment_id}/session", response_model=PackingSessionResponse, summary="Get Packing Session")
async def get_packing_session(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.get_or_create_packing_session(db, tenant_id, shipment_id, user_id)

@router.post("/packing/verify-item", response_model=PackingItemVerifyResponse, summary="Scan Verify Packing Item")
async def verify_packing_item(
    payload: PackingItemVerifyRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:fulfill"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await WarehouseService.verify_packing_item(
        db=db,
        tenant_id=tenant_id,
        shipment_id=payload.shipment_id,
        scanned_barcode=payload.scanned_barcode,
        quantity=Decimal(str(payload.quantity)),
        carton_number=payload.carton_number,
        user_id=user_id
    )

@router.post("/labels/generate", response_model=LabelGenerationResponse, summary="Generate Printable Barcode Labels")
async def generate_labels(
    payload: LabelGenerationRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    tenant_id = claims["tenant_id"]
    return await WarehouseService.generate_labels(
        db=db,
        tenant_id=tenant_id,
        label_type=payload.label_type,
        entity_ids=payload.entity_ids,
        copies_per_item=payload.copies_per_item
    )
