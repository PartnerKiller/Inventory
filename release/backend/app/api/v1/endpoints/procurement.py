from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.permissions import require_permission, get_current_user_claims
from app.schemas.purchasing import (
    PurchaseSuggestionsResponse,
    DraftPOFromSuggestionsRequest,
    DraftPOBatchResponse,
    PurchasePriceVarianceReportResponse,
    SupplierScorecardResponse,
    ProcurementDashboardResponse,
    SupplierProductCreate,
    SupplierProductResponse,
    SupplierReturnCreate,
    SupplierReturnResponse
)
from app.models.purchasing import SupplierProduct, Supplier, SupplierReturn
from app.models.item import ItemVariant, Item
from app.services.procurement_service import ProcurementService
from app.services.purchase_service import PurchaseService

router = APIRouter()

# ============================================================================
# REPLENISHMENT SUGGESTIONS & DRAFT PO BATCHING
# ============================================================================

@router.get("/suggestions", response_model=PurchaseSuggestionsResponse)
async def get_purchase_suggestions(
    warehouse_id: Optional[str] = Query(None, description="Optional warehouse scoping filter"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    """
    Computes replenishment-derived purchase suggestions with deterministic supplier selection.
    """
    tenant_id = claims["tenant_id"]
    return await ProcurementService.get_purchase_suggestions(db, tenant_id, warehouse_id=warehouse_id)

@router.post("/draft-po-from-suggestions", response_model=DraftPOBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_draft_pos_from_suggestions(
    req: DraftPOFromSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    """
    Generates reviewable Draft Purchase Orders grouped by supplier from selected suggestions.
    Does NOT mutate stock balances or costing layers.
    """
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    return await ProcurementService.create_draft_pos_from_suggestions(db, tenant_id, req, user_id=user_id)

# ============================================================================
# SUPPLIER-PRODUCT CATALOG ENDPOINTS
# ============================================================================

@router.get("/suppliers/{supplier_id}/products", response_model=List[SupplierProductResponse])
async def list_supplier_products(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    """
    Lists all catalog products and contracted purchasing prices for a supplier.
    """
    tenant_id = claims["tenant_id"]
    stmt = (
        select(SupplierProduct, Supplier, ItemVariant, Item)
        .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
        .join(ItemVariant, SupplierProduct.item_variant_id == ItemVariant.id)
        .join(Item, ItemVariant.item_id == Item.id)
        .where(
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.is_deleted == False
        )
        .order_by(SupplierProduct.is_preferred.desc(), Item.name.asc())
    )
    rows = (await db.execute(stmt)).fetchall()

    out = []
    for sp, sup, var, it in rows:
        out.append(SupplierProductResponse(
            id=sp.id,
            tenant_id=sp.tenant_id,
            supplier_id=sup.id,
            supplier_name=sup.name,
            supplier_code=sup.code,
            item_variant_id=var.id,
            variant_sku=var.variant_sku,
            item_name=it.name,
            supplier_sku=sp.supplier_sku,
            supplier_product_name=sp.supplier_product_name,
            unit_cost=float(sp.unit_cost),
            currency=sp.currency,
            minimum_order_quantity=float(sp.minimum_order_quantity),
            pack_size=float(sp.pack_size),
            lead_time_days=sp.lead_time_days,
            is_preferred=sp.is_preferred,
            is_active=sp.is_active,
            effective_from=sp.effective_from,
            effective_to=sp.effective_to,
            created_at=sp.created_at
        ))
    return out

@router.post("/suppliers/{supplier_id}/products", response_model=SupplierProductResponse, status_code=status.HTTP_201_CREATED)
async def map_supplier_product(
    supplier_id: str,
    sp_in: SupplierProductCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    """
    Maps an item variant to a supplier catalog with MOQ, pack size, lead time, and contracted cost.
    """
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    sp = await PurchaseService.create_or_update_supplier_product(db, tenant_id, supplier_id, sp_in, user_id=user_id)

    # Fetch relationships for response
    sup = (await db.execute(select(Supplier).where(Supplier.id == sp.supplier_id))).scalar_one()
    var = (await db.execute(select(ItemVariant).where(ItemVariant.id == sp.item_variant_id))).scalar_one()
    it = (await db.execute(select(Item).where(Item.id == var.item_id))).scalar_one()

    return SupplierProductResponse(
        id=sp.id,
        tenant_id=sp.tenant_id,
        supplier_id=sup.id,
        supplier_name=sup.name,
        supplier_code=sup.code,
        item_variant_id=var.id,
        variant_sku=var.variant_sku,
        item_name=it.name,
        supplier_sku=sp.supplier_sku,
        supplier_product_name=sp.supplier_product_name,
        unit_cost=float(sp.unit_cost),
        currency=sp.currency,
        minimum_order_quantity=float(sp.minimum_order_quantity),
        pack_size=float(sp.pack_size),
        lead_time_days=sp.lead_time_days,
        is_preferred=sp.is_preferred,
        is_active=sp.is_active,
        effective_from=sp.effective_from,
        effective_to=sp.effective_to,
        created_at=sp.created_at
    )

# ============================================================================
# SUPPLIER RETURNS (RTV)
# ============================================================================

@router.post("/returns", response_model=SupplierReturnResponse, status_code=status.HTTP_201_CREATED)
async def process_supplier_return(
    ret_in: SupplierReturnCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    """
    Processes a Return to Vendor (RTV), deducting physical stock and depleting cost layers.
    """
    tenant_id = claims["tenant_id"]
    user_id = claims.get("user_id")
    ret = await PurchaseService.process_supplier_return(db, tenant_id, ret_in, user_id=user_id)

    # Fetch detail
    stmt = (
        select(SupplierReturn)
        .where(SupplierReturn.id == ret.id, SupplierReturn.tenant_id == tenant_id)
    )
    r = (await db.execute(stmt)).scalar_one()
    
    return SupplierReturnResponse(
        id=r.id,
        tenant_id=r.tenant_id,
        return_number=r.return_number,
        supplier_id=r.supplier_id,
        supplier_name=r.supplier.name,
        warehouse_id=r.warehouse_id,
        warehouse_name=r.warehouse.name,
        purchase_order_id=r.purchase_order_id,
        status=r.status,
        return_reason=r.return_reason,
        total_refund_amount=float(r.total_refund_amount),
        returned_at=r.returned_at,
        notes=r.notes,
        lines=[
            {
                "id": l.id,
                "item_variant_id": l.item_variant_id,
                "variant_sku": l.variant.variant_sku,
                "item_name": l.variant.variant_name or l.variant.variant_sku,
                "source_location_bin_id": l.source_location_bin_id,
                "source_bin_code": l.source_bin.code if l.source_bin else None,
                "quantity_returned": float(l.quantity_returned),
                "unit_cost": float(l.unit_cost),
                "total_cost": float(l.total_cost),
                "batch_number": l.batch_number
            }
            for l in r.lines
        ]
    )

# ============================================================================
# PPV, SCORECARDS & PROCUREMENT DASHBOARD
# ============================================================================

@router.get("/ppv-report", response_model=PurchasePriceVarianceReportResponse)
async def get_ppv_report(
    supplier_id: Optional[str] = Query(None),
    days_back: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    """
    Calculates Purchase Price Variance (PPV) against standard costs.
    """
    tenant_id = claims["tenant_id"]
    return await ProcurementService.get_purchase_price_variance_report(db, tenant_id, supplier_id=supplier_id, days_back=days_back)

@router.get("/supplier-scorecards", response_model=SupplierScorecardResponse)
async def get_supplier_scorecards(
    supplier_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    """
    Computes supplier performance scorecards (OTD %, Fill Rate %, Mean Lead Time, PPV).
    """
    tenant_id = claims["tenant_id"]
    return await ProcurementService.get_supplier_scorecards(db, tenant_id, supplier_id=supplier_id)

@router.get("/dashboard", response_model=ProcurementDashboardResponse)
async def get_procurement_dashboard(
    warehouse_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    """
    Aggregates procurement operational KPIs, pipeline counts, suggestions, and scorecards.
    """
    tenant_id = claims["tenant_id"]
    return await ProcurementService.get_procurement_dashboard(db, tenant_id, warehouse_id=warehouse_id)
