from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_permission
from app.schemas.analytics import (
    SalesSummaryKPIs,
    ProductSalesAnalyticsItem,
    CustomerSalesAnalyticsItem,
    WarehouseSalesAnalyticsItem
)
from app.services.sales_analytics_service import SalesAnalyticsService

router = APIRouter()

@router.get("/summary", response_model=SalesSummaryKPIs)
async def get_sales_summary(
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    return await SalesAnalyticsService.get_executive_sales_summary(db, tenant_id, from_date, to_date)

@router.get("/by-product", response_model=List[ProductSalesAnalyticsItem])
async def get_sales_by_product(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    return await SalesAnalyticsService.get_sales_by_product(db, tenant_id)

@router.get("/by-customer", response_model=List[CustomerSalesAnalyticsItem])
async def get_sales_by_customer(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    return await SalesAnalyticsService.get_sales_by_customer(db, tenant_id)

@router.get("/by-warehouse", response_model=List[WarehouseSalesAnalyticsItem])
async def get_sales_by_warehouse(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    return await SalesAnalyticsService.get_sales_by_warehouse(db, tenant_id)
