from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.maintenance import (
    MaintenanceScheduleCreate,
    MaintenanceScheduleResponse,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderComplete,
    MaintenanceWorkOrderResponse
)
from app.services.maintenance_service import MaintenanceService

router = APIRouter()

# ============================================================================
# PREVENTIVE MAINTENANCE SCHEDULES
# ============================================================================

@router.post("/schedules", response_model=MaintenanceScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    sched_in: MaintenanceScheduleCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await MaintenanceService.create_maintenance_schedule(
        db=db, tenant_id=claims["tenant_id"], sched_in=sched_in
    )

# ============================================================================
# MAINTENANCE WORK ORDERS
# ============================================================================

@router.post("/work-orders", response_model=MaintenanceWorkOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_work_order(
    mwo_in: MaintenanceWorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await MaintenanceService.create_maintenance_work_order(
        db=db, tenant_id=claims["tenant_id"], mwo_in=mwo_in
    )

@router.patch("/work-orders/{mwo_id}/status", response_model=MaintenanceWorkOrderResponse)
async def update_work_order_status(
    mwo_id: str,
    status: str = Query(..., description="New status (SCHEDULED, IN_PROGRESS, CANCELLED)"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await MaintenanceService.update_work_order_status(
        db=db, tenant_id=claims["tenant_id"], mwo_id=mwo_id, new_status=status
    )

@router.post("/work-orders/{mwo_id}/complete", response_model=MaintenanceWorkOrderResponse)
async def complete_work_order(
    mwo_id: str,
    comp_in: MaintenanceWorkOrderComplete,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    return await MaintenanceService.complete_maintenance_work_order(
        db=db, tenant_id=claims["tenant_id"], mwo_id=mwo_id, comp_in=comp_in, user_id=claims["user_id"]
    )
