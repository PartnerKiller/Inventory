from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.approval import (
    ApprovalRuleCreate,
    ApprovalRuleResponse,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    ApprovalActionRequest,
    ApprovalDelegationCreate,
    ApprovalDelegationResponse
)
from app.services.approval_service import ApprovalService

router = APIRouter()

# ============================================================================
# APPROVAL RULES & DELEGATION ENDPOINTS
# ============================================================================

@router.post("/rules", response_model=ApprovalRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_approval_rule(
    rule_in: ApprovalRuleCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ApprovalService.create_approval_rule(
        db=db, tenant_id=claims["tenant_id"], rule_in=rule_in
    )

@router.post("/delegations", response_model=ApprovalDelegationResponse, status_code=status.HTTP_201_CREATED)
async def create_delegation(
    del_in: ApprovalDelegationCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ApprovalService.create_delegation(
        db=db, tenant_id=claims["tenant_id"], user_id=claims["user_id"], del_in=del_in
    )

# ============================================================================
# APPROVAL WORKFLOW REQUESTS & ACTIONS
# ============================================================================

@router.post("/requests", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED)
async def submit_for_approval(
    req_in: ApprovalRequestCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ApprovalService.submit_for_approval(
        db=db, tenant_id=claims["tenant_id"], req_in=req_in, user_id=claims["user_id"]
    )

@router.post("/requests/{request_id}/action", response_model=ApprovalRequestResponse)
async def process_step_action(
    request_id: str,
    action_in: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await ApprovalService.process_step_action(
        db=db, tenant_id=claims["tenant_id"], request_id=request_id, user_id=claims["user_id"], action_in=action_in
    )
