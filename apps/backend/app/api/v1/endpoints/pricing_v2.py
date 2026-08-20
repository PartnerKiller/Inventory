from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.pricing_v2 import (
    PriceRuleCreate,
    PriceRuleResponse,
    PriceQuoteRequest,
    PriceQuoteResponse,
    RebateAgreementCreate,
    RebateAgreementResponse,
    SettleRebateRequest
)
from app.services.pricing_service_v2 import PricingServiceV2

router = APIRouter()

# ============================================================================
# PRICE RULES & QUOTE RESOLUTION
# ============================================================================

@router.post("/rules", response_model=PriceRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_price_rule(
    rule_in: PriceRuleCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PricingServiceV2.create_price_rule(
        db=db, tenant_id=claims["tenant_id"], rule_in=rule_in
    )

@router.post("/quote", response_model=PriceQuoteResponse)
async def resolve_price_quote(
    req: PriceQuoteRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PricingServiceV2.resolve_unit_price(
        db=db, tenant_id=claims["tenant_id"], req=req
    )

# ============================================================================
# REBATE AGREEMENTS & SETTLEMENT
# ============================================================================

@router.post("/rebates", response_model=RebateAgreementResponse, status_code=status.HTTP_201_CREATED)
async def create_rebate_agreement(
    ag_in: RebateAgreementCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PricingServiceV2.create_rebate_agreement(
        db=db, tenant_id=claims["tenant_id"], ag_in=ag_in
    )

@router.post("/rebates/{agreement_id}/settle", response_model=RebateAgreementResponse)
async def settle_rebate_agreement(
    agreement_id: str,
    settle_in: SettleRebateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await PricingServiceV2.calculate_and_settle_rebate(
        db=db, tenant_id=claims["tenant_id"], agreement_id=agreement_id, settle_in=settle_in, user_id=claims["user_id"]
    )
