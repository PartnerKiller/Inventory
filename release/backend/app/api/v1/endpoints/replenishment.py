from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.replenishment import ReplenishmentConfig, ReplenishmentRun, ReplenishmentRecommendationItem
from app.schemas.replenishment import (
    ReplenishmentConfigCreate,
    ReplenishmentConfigResponse,
    ReplenishmentRunResponse,
    ReplenishmentRecommendationItemResponse,
    GenerateDraftPOsRequest,
    GenerateDraftPOsResponse
)
from app.services.replenishment_service import ReplenishmentService

router = APIRouter()

@router.get("/configs", response_model=List[ReplenishmentConfigResponse])
async def list_replenishment_configs(
    warehouse_id: Optional[str] = Query(None),
    item_variant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("procurement:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(ReplenishmentConfig).where(ReplenishmentConfig.tenant_id == tenant_id, ReplenishmentConfig.is_deleted == False)
    if warehouse_id:
        stmt = stmt.where(ReplenishmentConfig.warehouse_id == warehouse_id)
    if item_variant_id:
        stmt = stmt.where(ReplenishmentConfig.item_variant_id == item_variant_id)
    
    cfgs = (await db.execute(stmt)).scalars().all()
    out = []
    for c in cfgs:
        out.append(ReplenishmentConfigResponse(
            id=c.id,
            tenant_id=c.tenant_id,
            item_variant_id=c.item_variant_id,
            variant_sku=c.variant.variant_sku if c.variant else None,
            warehouse_id=c.warehouse_id,
            warehouse_name=c.warehouse.name if c.warehouse else None,
            reorder_method=c.reorder_method,
            min_quantity=float(c.min_quantity) if c.min_quantity is not None else None,
            max_quantity=float(c.max_quantity) if c.max_quantity is not None else None,
            safety_stock_days=c.safety_stock_days,
            target_coverage_days=c.target_coverage_days,
            fixed_safety_stock=float(c.fixed_safety_stock) if c.fixed_safety_stock is not None else None,
            is_active=c.is_active,
            created_at=c.created_at
        ))
    return out

@router.put("/configs", response_model=ReplenishmentConfigResponse)
async def upsert_replenishment_config(
    cfg_in: ReplenishmentConfigCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("procurement:write"))
):
    tenant_id = claims["tenant_id"]
    cfg = await ReplenishmentService.upsert_config(db, tenant_id, cfg_in, user_id=claims.get("sub"))
    return ReplenishmentConfigResponse(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        item_variant_id=cfg.item_variant_id,
        variant_sku=cfg.variant.variant_sku if cfg.variant else None,
        warehouse_id=cfg.warehouse_id,
        warehouse_name=cfg.warehouse.name if cfg.warehouse else None,
        reorder_method=cfg.reorder_method,
        min_quantity=float(cfg.min_quantity) if cfg.min_quantity is not None else None,
        max_quantity=float(cfg.max_quantity) if cfg.max_quantity is not None else None,
        safety_stock_days=cfg.safety_stock_days,
        target_coverage_days=cfg.target_coverage_days,
        fixed_safety_stock=float(cfg.fixed_safety_stock) if cfg.fixed_safety_stock is not None else None,
        is_active=cfg.is_active,
        created_at=cfg.created_at
    )

@router.post("/runs", response_model=ReplenishmentRunResponse, status_code=status.HTTP_201_CREATED)
async def trigger_replenishment_run(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("procurement:write"))
):
    tenant_id = claims["tenant_id"]
    rep_run = await ReplenishmentService.execute_replenishment_run(db, tenant_id, warehouse_id, user_id=claims.get("sub"))
    
    items_out = []
    for it in rep_run.items:
        items_out.append(ReplenishmentRecommendationItemResponse(
            id=it.id,
            run_id=it.run_id,
            warehouse_id=it.warehouse_id,
            warehouse_name=it.warehouse.name if it.warehouse else None,
            item_variant_id=it.item_variant_id,
            variant_sku=it.variant.variant_sku if it.variant else None,
            item_name=it.variant.item.name if it.variant and it.variant.item else None,
            supplier_id=it.supplier_id,
            supplier_name=it.supplier.name if it.supplier else None,
            quantity_on_hand=float(it.quantity_on_hand),
            quantity_allocated=float(it.quantity_allocated),
            quantity_available=float(it.quantity_available),
            quantity_incoming=float(it.quantity_incoming),
            quantity_mfg_planned=float(it.quantity_mfg_planned),
            net_inventory_position=float(it.net_inventory_position),
            average_daily_usage=float(it.average_daily_usage),
            lead_time_days=it.lead_time_days,
            safety_stock=float(it.safety_stock),
            reorder_point=float(it.reorder_point),
            target_maximum_stock=float(it.target_maximum_stock),
            minimum_order_quantity=float(it.minimum_order_quantity),
            pack_size=float(it.pack_size),
            suggested_reorder_quantity=float(it.suggested_reorder_quantity),
            estimated_unit_cost=float(it.estimated_unit_cost),
            estimated_total_cost=float(it.estimated_total_cost),
            urgency_status=it.urgency_status,
            suggested_order_date=it.suggested_order_date,
            action_status=it.action_status,
            purchase_order_id=it.purchase_order_id
        ))

    return ReplenishmentRunResponse(
        id=rep_run.id,
        tenant_id=rep_run.tenant_id,
        run_number=rep_run.run_number,
        warehouse_id=rep_run.warehouse_id,
        warehouse_name=rep_run.warehouse.name if rep_run.warehouse else None,
        triggered_by_user_id=rep_run.triggered_by_user_id,
        total_skus_evaluated=rep_run.total_skus_evaluated,
        total_recommendations=rep_run.total_recommendations,
        total_estimated_spend=float(rep_run.total_estimated_spend),
        status=rep_run.status,
        created_at=rep_run.created_at,
        items=items_out
    )

@router.get("/runs", response_model=List[ReplenishmentRunResponse])
async def list_replenishment_runs(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("procurement:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(ReplenishmentRun).where(ReplenishmentRun.tenant_id == tenant_id).order_by(desc(ReplenishmentRun.created_at))
    runs = (await db.execute(stmt)).scalars().all()
    
    out = []
    for r in runs:
        out.append(ReplenishmentRunResponse(
            id=r.id,
            tenant_id=r.tenant_id,
            run_number=r.run_number,
            warehouse_id=r.warehouse_id,
            warehouse_name=r.warehouse.name if r.warehouse else None,
            triggered_by_user_id=r.triggered_by_user_id,
            total_skus_evaluated=r.total_skus_evaluated,
            total_recommendations=r.total_recommendations,
            total_estimated_spend=float(r.total_estimated_spend),
            status=r.status,
            created_at=r.created_at,
            items=[]
        ))
    return out

@router.post("/generate-draft-pos", response_model=GenerateDraftPOsResponse)
async def generate_draft_purchase_orders(
    req: GenerateDraftPOsRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("procurement:write"))
):
    tenant_id = claims["tenant_id"]
    return await ReplenishmentService.generate_draft_purchase_orders(db, tenant_id, req, user_id=claims.get("sub"))
