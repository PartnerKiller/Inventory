from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.reconciliation import (
    SubledgerReconciliationItem,
    FullReconciliationReport
)
from app.services.reconciliation_service import ReconciliationService

router = APIRouter()

@router.get("/full", response_model=FullReconciliationReport, status_code=status.HTTP_200_OK)
async def get_full_reconciliation(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Generate comprehensive cross-subsystem subledger reconciliation report."""
    return await ReconciliationService.get_full_reconciliation_report(
        db=db,
        tenant_id=claims.get("tenant_id", "default")
    )

@router.get("/inventory", response_model=SubledgerReconciliationItem, status_code=status.HTTP_200_OK)
async def reconcile_inventory(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Reconcile Physical Inventory Stock Balances vs GL Account 1200."""
    return await ReconciliationService.reconcile_inventory_subledger(
        db=db,
        tenant_id=claims.get("tenant_id", "default")
    )

@router.get("/ar", response_model=SubledgerReconciliationItem, status_code=status.HTTP_200_OK)
async def reconcile_ar(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Reconcile Open Customer Invoices vs GL Account 1100."""
    return await ReconciliationService.reconcile_ar_subledger(
        db=db,
        tenant_id=claims.get("tenant_id", "default")
    )

@router.get("/ap", response_model=SubledgerReconciliationItem, status_code=status.HTTP_200_OK)
async def reconcile_ap(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Reconcile Open Vendor Invoices vs GL Account 2000."""
    return await ReconciliationService.reconcile_ap_subledger(
        db=db,
        tenant_id=claims.get("tenant_id", "default")
    )

@router.get("/assets", response_model=SubledgerReconciliationItem, status_code=status.HTTP_200_OK)
async def reconcile_fixed_assets(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """Reconcile Fixed Asset Registry Net Book Value vs GL Accounts 1500 - 1550."""
    return await ReconciliationService.reconcile_fixed_assets_subledger(
        db=db,
        tenant_id=claims.get("tenant_id", "default")
    )
