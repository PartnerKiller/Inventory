from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.permissions import require_permission, check_warehouse_scope
from app.schemas.reports import (
    DashboardMetricsResponse, ValuationReportResponse,
    InventoryReportResponse, PurchasingReportResponse, SalesReportResponse,
    GlobalSearchResponse
)
from app.services.report_service import ReportService

router = APIRouter()

@router.get("/dashboard", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics(
    warehouse_id: Optional[str] = Query(None, description="Optional facility filter"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)
    tenant_id = claims["tenant_id"]
    return await ReportService.get_dashboard_metrics(db, tenant_id, warehouse_id=warehouse_id)

@router.get("/inventory", response_model=InventoryReportResponse)
async def get_inventory_report(
    warehouse_id: Optional[str] = Query(None),
    stock_status: Optional[str] = Query("ALL", pattern="^(ALL|IN_STOCK|LOW_STOCK|OUT_OF_STOCK)$"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)
    tenant_id = claims["tenant_id"]
    return await ReportService.get_inventory_report(
        db=db,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        stock_status=stock_status
    )

@router.get("/purchasing", response_model=PurchasingReportResponse)
async def get_purchasing_report(
    supplier_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)
    tenant_id = claims["tenant_id"]
    return await ReportService.get_purchasing_report(
        db=db,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        warehouse_id=warehouse_id
    )

@router.get("/sales", response_model=SalesReportResponse)
async def get_sales_report(
    customer_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    if warehouse_id:
        check_warehouse_scope(claims, warehouse_id)
    tenant_id = claims["tenant_id"]
    return await ReportService.get_sales_report(
        db=db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        warehouse_id=warehouse_id
    )

@router.get("/valuation", response_model=ValuationReportResponse)
async def get_valuation_report(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    return await ReportService.get_valuation_report(db, tenant_id)

@router.get("/valuation/export-csv")
async def export_valuation_csv(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    rep = await ReportService.get_valuation_report(db, tenant_id)
    headers = ["SKU", "Item Name", "Valuation Method", "Total Quantity", "Unit Cost ($)", "Total Valuation ($)"]
    rows = [
        [i.sku, i.name, i.valuation_method, i.total_quantity, i.unit_cost, i.total_valuation]
        for i in rep.items
    ]
    csv_data = ReportService.generate_csv_export(headers, rows)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory_valuation_report.csv"}
    )
