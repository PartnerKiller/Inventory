from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.schemas.analytics import (
    InventoryAgingReportResponse,
    InventoryTurnoverReportResponse,
    StockClassificationReportResponse,
    DemandAndUsageResponse,
    ReplenishmentRecommendationsResponse,
    SupplierAnalyticsResponse,
    ExecutiveInventoryDashboardResponse
)
from app.services.analytics_service import AnalyticsService

router = APIRouter()

@router.get("/dashboard", response_model=ExecutiveInventoryDashboardResponse)
async def get_inventory_dashboard(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_executive_dashboard(db, tenant_id, warehouse_id)

@router.get("/aging", response_model=InventoryAgingReportResponse)
async def get_inventory_aging_report(
    warehouse_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_inventory_aging(db, tenant_id, warehouse_id, category_id)

@router.get("/turnover", response_model=InventoryTurnoverReportResponse)
async def get_inventory_turnover_report(
    warehouse_id: Optional[str] = Query(None),
    period_days: int = Query(90, ge=7, le=730),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_inventory_turnover(db, tenant_id, warehouse_id, period_days)

@router.get("/slow-moving", response_model=StockClassificationReportResponse)
async def get_slow_moving_stock_report(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_slow_moving_and_dead_stock(db, tenant_id, warehouse_id)

@router.get("/usage/{variant_id}", response_model=DemandAndUsageResponse)
async def get_variant_usage_analytics(
    variant_id: str,
    warehouse_id: Optional[str] = Query(None),
    period_days: int = Query(90, ge=14, le=365),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_demand_and_usage(db, tenant_id, variant_id, warehouse_id, period_days)

@router.get("/replenishment", response_model=ReplenishmentRecommendationsResponse)
async def get_replenishment_recommendations(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)

    return await AnalyticsService.get_replenishment_recommendations(db, tenant_id, warehouse_id)

@router.get("/suppliers", response_model=SupplierAnalyticsResponse)
async def get_supplier_analytics(
    supplier_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    return await AnalyticsService.get_supplier_analytics(db, tenant_id, supplier_id)
