from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.permissions import get_current_user_claims, require_permission
from app.schemas.advanced_manufacturing import (
    WorkCenterCreate,
    WorkCenterResponse,
    RoutingCreate,
    RoutingResponse,
    OperationClaimRequest,
    OperationCompleteRequest,
    ProductionQualityInspectionCreate,
    ProductionQualityInspectionResponse,
    MRPExplosionRequest,
    MRPExplosionResponse
)
from app.services.advanced_manufacturing_service import (
    WorkCenterService,
    RoutingService,
    AdvancedManufacturingService
)

router = APIRouter()

# ============================================================================
# WORK CENTERS
# ============================================================================

@router.post("/work-centers", response_model=WorkCenterResponse)
async def create_work_center(
    wc_in: WorkCenterCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:manage_work_centers"))
):
    tenant_id = claims["tenant_id"]
    return await WorkCenterService.create_work_center(db, tenant_id, wc_in)

# ============================================================================
# ROUTINGS
# ============================================================================

@router.post("/routings", response_model=RoutingResponse)
async def create_routing(
    routing_in: RoutingCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:manage_routing"))
):
    tenant_id = claims["tenant_id"]
    return await RoutingService.create_routing(db, tenant_id, routing_in)

# ============================================================================
# MRP EXPLOSION
# ============================================================================

@router.post("/mrp/explode", response_model=MRPExplosionResponse)
async def explode_mrp(
    req: MRPExplosionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:read"))
):
    tenant_id = claims["tenant_id"]
    return await AdvancedManufacturingService.explode_mrp(db, tenant_id, req)

# ============================================================================
# SHOP-FLOOR OPERATIONS
# ============================================================================

@router.post("/operations/claim")
async def claim_operation(
    req: OperationClaimRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:execute"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]
    op = await AdvancedManufacturingService.claim_operation(db, tenant_id, req.operation_id, user_id)
    return {"message": f"Operation '{op.operation_name}' claimed successfully", "status": op.status}

@router.post("/operations/complete")
async def complete_operation(
    req: OperationCompleteRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:execute"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]
    op = await AdvancedManufacturingService.complete_operation(db, tenant_id, req, user_id)
    return {"message": f"Operation '{op.operation_name}' completed", "labor_cost": float(op.actual_labor_cost)}

# ============================================================================
# QUALITY INSPECTIONS
# ============================================================================

@router.post("/inspections", response_model=ProductionQualityInspectionResponse)
async def record_quality_inspection(
    insp_in: ProductionQualityInspectionCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("production:approve_quality"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]
    return await AdvancedManufacturingService.record_quality_inspection(db, tenant_id, insp_in, user_id)
