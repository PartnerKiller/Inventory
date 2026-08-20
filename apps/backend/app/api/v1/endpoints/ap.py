from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.ap import VendorInvoice, VendorPayment, APMatchingTolerance
from app.schemas.ap import (
    VendorInvoiceCreate,
    VendorInvoiceResponse,
    VendorPaymentCreate,
    VendorPaymentResponse,
    APMatchingToleranceUpdate,
    APMatchingToleranceResponse,
    APAgingReportResponse
)
from app.services.ap_service import APService
from app.services.ap_matching_service import APMatchingService

router = APIRouter()

@router.get("/invoices", response_model=List[VendorInvoiceResponse])
async def list_vendor_invoices(
    supplier_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(VendorInvoice)
        .where(VendorInvoice.tenant_id == tenant_id, VendorInvoice.is_deleted == False)
    )
    if supplier_id:
        stmt = stmt.where(VendorInvoice.supplier_id == supplier_id)
    if status_filter:
        stmt = stmt.where(VendorInvoice.status == status_filter)

    stmt = stmt.order_by(desc(VendorInvoice.created_at))
    invoices = (await db.execute(stmt)).scalars().all()

    out = []
    for inv in invoices:
        out.append(VendorInvoiceResponse(
            id=inv.id,
            tenant_id=inv.tenant_id,
            invoice_number=inv.invoice_number,
            vendor_invoice_reference=inv.vendor_invoice_reference,
            purchase_order_id=inv.purchase_order_id,
            goods_receipt_id=inv.goods_receipt_id,
            supplier_id=inv.supplier_id,
            supplier_name=inv.supplier.name if inv.supplier else None,
            supplier_code=inv.supplier.code if inv.supplier else None,
            status=inv.status,
            match_status=inv.match_status,
            subtotal_amount=float(inv.subtotal_amount),
            discount_amount=float(inv.discount_amount),
            tax_amount=float(inv.tax_amount),
            total_amount=float(inv.total_amount),
            amount_paid=float(inv.amount_paid),
            balance_due=float(inv.balance_due),
            currency=inv.currency,
            invoice_date=inv.invoice_date,
            due_date=inv.due_date,
            notes=inv.notes,
            match_notes=inv.match_notes,
            approved_by_user_id=inv.approved_by_user_id,
            approved_at=inv.approved_at,
            created_at=inv.created_at,
            lines=[]
        ))
    return out

@router.post("/invoices", response_model=VendorInvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor_invoice(
    invoice_in: VendorInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    inv = await APService.create_vendor_invoice(db, tenant_id, invoice_in, user_id=claims.get("sub"))
    return VendorInvoiceResponse(
        id=inv.id,
        tenant_id=inv.tenant_id,
        invoice_number=inv.invoice_number,
        vendor_invoice_reference=inv.vendor_invoice_reference,
        purchase_order_id=inv.purchase_order_id,
        goods_receipt_id=inv.goods_receipt_id,
        supplier_id=inv.supplier_id,
        supplier_name=inv.supplier.name if inv.supplier else None,
        supplier_code=inv.supplier.code if inv.supplier else None,
        status=inv.status,
        match_status=inv.match_status,
        subtotal_amount=float(inv.subtotal_amount),
        discount_amount=float(inv.discount_amount),
        tax_amount=float(inv.tax_amount),
        total_amount=float(inv.total_amount),
        amount_paid=float(inv.amount_paid),
        balance_due=float(inv.balance_due),
        currency=inv.currency,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        notes=inv.notes,
        match_notes=inv.match_notes,
        approved_by_user_id=inv.approved_by_user_id,
        approved_at=inv.approved_at,
        created_at=inv.created_at,
        lines=[]
    )

@router.post("/invoices/{invoice_id}/approve", response_model=VendorInvoiceResponse)
async def approve_vendor_invoice_exception(
    invoice_id: str,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:approve"))
):
    tenant_id = claims["tenant_id"]
    inv = await APService.approve_exception_hold(db, tenant_id, invoice_id, user_id=claims.get("sub"), approval_notes=notes)
    return VendorInvoiceResponse(
        id=inv.id,
        tenant_id=inv.tenant_id,
        invoice_number=inv.invoice_number,
        vendor_invoice_reference=inv.vendor_invoice_reference,
        purchase_order_id=inv.purchase_order_id,
        goods_receipt_id=inv.goods_receipt_id,
        supplier_id=inv.supplier_id,
        supplier_name=inv.supplier.name if inv.supplier else None,
        supplier_code=inv.supplier.code if inv.supplier else None,
        status=inv.status,
        match_status=inv.match_status,
        subtotal_amount=float(inv.subtotal_amount),
        discount_amount=float(inv.discount_amount),
        tax_amount=float(inv.tax_amount),
        total_amount=float(inv.total_amount),
        amount_paid=float(inv.amount_paid),
        balance_due=float(inv.balance_due),
        currency=inv.currency,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        notes=inv.notes,
        match_notes=inv.match_notes,
        approved_by_user_id=inv.approved_by_user_id,
        approved_at=inv.approved_at,
        created_at=inv.created_at,
        lines=[]
    )

@router.post("/payments", response_model=VendorPaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_vendor_payment(
    payment_in: VendorPaymentCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    pay = await APService.record_vendor_payment(db, tenant_id, payment_in, user_id=claims.get("sub"))
    return VendorPaymentResponse(
        id=pay.id,
        tenant_id=pay.tenant_id,
        payment_number=pay.payment_number,
        supplier_id=pay.supplier_id,
        supplier_name=pay.supplier.name if pay.supplier else None,
        supplier_code=pay.supplier.code if pay.supplier else None,
        payment_method=pay.payment_method,
        amount=float(pay.amount),
        currency=pay.currency,
        payment_date=pay.payment_date,
        reference_number=pay.reference_number,
        status=pay.status,
        notes=pay.notes,
        created_at=pay.created_at,
        allocations=[]
    )

@router.post("/invoices/{invoice_id}/apply-debit-memo/{debit_memo_id}", response_model=VendorInvoiceResponse)
async def apply_debit_memo_to_invoice(
    invoice_id: str,
    debit_memo_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("purchasing:write"))
):
    tenant_id = claims["tenant_id"]
    inv = await APService.apply_debit_memo(db, tenant_id, invoice_id, debit_memo_id, user_id=claims.get("sub"))
    return VendorInvoiceResponse(
        id=inv.id,
        tenant_id=inv.tenant_id,
        invoice_number=inv.invoice_number,
        vendor_invoice_reference=inv.vendor_invoice_reference,
        purchase_order_id=inv.purchase_order_id,
        goods_receipt_id=inv.goods_receipt_id,
        supplier_id=inv.supplier_id,
        supplier_name=inv.supplier.name if inv.supplier else None,
        supplier_code=inv.supplier.code if inv.supplier else None,
        status=inv.status,
        match_status=inv.match_status,
        subtotal_amount=float(inv.subtotal_amount),
        discount_amount=float(inv.discount_amount),
        tax_amount=float(inv.tax_amount),
        total_amount=float(inv.total_amount),
        amount_paid=float(inv.amount_paid),
        balance_due=float(inv.balance_due),
        currency=inv.currency,
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        notes=inv.notes,
        match_notes=inv.match_notes,
        approved_by_user_id=inv.approved_by_user_id,
        approved_at=inv.approved_at,
        created_at=inv.created_at,
        lines=[]
    )

@router.get("/aging", response_model=APAgingReportResponse)
async def get_ap_aging_report(
    as_of_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    return await APService.get_ap_aging_report(db, tenant_id, as_of_date)
