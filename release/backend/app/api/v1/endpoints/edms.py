from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.edms import (
    DocumentAttachmentCreate,
    DocumentAttachmentResponse,
    DocumentIntegrityCheckResponse,
    DocumentSignOffRequest,
    DocumentSignOffExecute,
    DocumentSignOffResponse
)
from app.services.edms_service import EDMSService

router = APIRouter()

# ============================================================================
# DOCUMENT ATTACHMENT ENDPOINTS
# ============================================================================

@router.post("/attachments", response_model=DocumentAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    doc_in: DocumentAttachmentCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await EDMSService.upload_attachment(
        db=db, tenant_id=claims["tenant_id"], doc_in=doc_in, user_id=claims["user_id"]
    )

@router.get("/attachments/{attachment_id}/verify", response_model=DocumentIntegrityCheckResponse)
async def verify_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await EDMSService.verify_attachment_integrity(
        db=db, tenant_id=claims["tenant_id"], attachment_id=attachment_id
    )

# ============================================================================
# AUDIT SIGN-OFF WORKFLOW ENDPOINTS
# ============================================================================

@router.post("/sign-offs/request", response_model=DocumentSignOffResponse, status_code=status.HTTP_201_CREATED)
async def request_sign_off(
    req: DocumentSignOffRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await EDMSService.request_sign_off(
        db=db, tenant_id=claims["tenant_id"], req=req
    )

@router.post("/sign-offs/execute", response_model=DocumentSignOffResponse)
async def execute_sign_off(
    req: DocumentSignOffExecute,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await EDMSService.execute_sign_off(
        db=db, tenant_id=claims["tenant_id"], req=req, signer_user_id=claims["user_id"]
    )
