from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.invoicing import CustomerInvoice, CustomerPayment, CustomerCreditNote
from app.schemas.invoicing import (
    CustomerInvoiceCreate,
    CustomerInvoiceResponse,
    CustomerPaymentCreate,
    CustomerPaymentResponse,
    CreditNoteCreate,
    CreditNoteResponse,
    ARAgingReportResponse,
    InvoiceLineResponse,
    PaymentAllocationResponse
)
from app.services.invoicing_service import InvoicingService

router = APIRouter()

@router.get("/invoices", response_model=List[CustomerInvoiceResponse])
async def list_invoices(
    customer_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(CustomerInvoice)
        .options(selectinload(CustomerInvoice.lines).selectinload(InvoiceLineResponse.__dict__.get("variant", None) or CustomerInvoice.lines.property.mapper.class_.variant))
        .where(CustomerInvoice.tenant_id == tenant_id, CustomerInvoice.is_deleted == False)
    )
    if customer_id:
        stmt = stmt.where(CustomerInvoice.customer_id == customer_id)
    if status_filter:
        stmt = stmt.where(CustomerInvoice.status == status_filter)

    stmt = stmt.order_by(desc(CustomerInvoice.created_at))
    invoices = (await db.execute(stmt)).scalars().all()

    out = []
    for inv in invoices:
        out.append(CustomerInvoiceResponse(
            id=inv.id,
            tenant_id=inv.tenant_id,
            invoice_number=inv.invoice_number,
            sales_order_id=inv.sales_order_id,
            customer_id=inv.customer_id,
            customer_name=inv.customer.name if inv.customer else None,
            customer_code=inv.customer.code if inv.customer else None,
            status=inv.status,
            subtotal_amount=float(inv.subtotal_amount),
            discount_amount=float(inv.discount_amount),
            tax_amount=float(inv.tax_amount),
            total_amount=float(inv.total_amount),
            amount_paid=float(inv.amount_paid),
            balance_due=float(inv.balance_due),
            currency=inv.currency,
            issue_date=inv.issue_date,
            due_date=inv.due_date,
            notes=inv.notes,
            created_at=inv.created_at,
            lines=[]
        ))
    return out

@router.post("/invoices/from-sales-order/{so_id}", response_model=CustomerInvoiceResponse, status_code=status.HTTP_201_CREATED)
async def generate_invoice_from_sales_order(
    so_id: str,
    issue_date: Optional[datetime] = None,
    due_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    inv = await InvoicingService.create_invoice_from_sales_order(
        db=db, tenant_id=tenant_id, so_id=so_id, issue_date=issue_date, due_date=due_date, user_id=claims.get("sub")
    )
    return CustomerInvoiceResponse(
        id=inv.id,
        tenant_id=inv.tenant_id,
        invoice_number=inv.invoice_number,
        sales_order_id=inv.sales_order_id,
        customer_id=inv.customer_id,
        customer_name=inv.customer.name if inv.customer else None,
        customer_code=inv.customer.code if inv.customer else None,
        status=inv.status,
        subtotal_amount=float(inv.subtotal_amount),
        discount_amount=float(inv.discount_amount),
        tax_amount=float(inv.tax_amount),
        total_amount=float(inv.total_amount),
        amount_paid=float(inv.amount_paid),
        balance_due=float(inv.balance_due),
        currency=inv.currency,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        notes=inv.notes,
        created_at=inv.created_at,
        lines=[]
    )

@router.post("/payments", response_model=CustomerPaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payment_in: CustomerPaymentCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    pay = await InvoicingService.record_customer_payment(db, tenant_id, payment_in, claims.get("sub"))
    return CustomerPaymentResponse(
        id=pay.id,
        tenant_id=pay.tenant_id,
        payment_number=pay.payment_number,
        customer_id=pay.customer_id,
        customer_name=pay.customer.name if pay.customer else None,
        customer_code=pay.customer.code if pay.customer else None,
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

@router.post("/credit-notes", response_model=CreditNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    cn_in: CreditNoteCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("sales:write"))
):
    tenant_id = claims["tenant_id"]
    cn = await InvoicingService.create_credit_note_for_return(db, tenant_id, cn_in, claims.get("sub"))
    return CreditNoteResponse(
        id=cn.id,
        tenant_id=cn.tenant_id,
        credit_note_number=cn.credit_note_number,
        customer_id=cn.customer_id,
        customer_name=cn.customer.name if cn.customer else None,
        sales_return_id=cn.sales_return_id,
        invoice_id=cn.invoice_id,
        amount=float(cn.amount),
        status=cn.status,
        issue_date=cn.issue_date,
        notes=cn.notes,
        created_at=cn.created_at
    )

@router.get("/ar-aging", response_model=ARAgingReportResponse)
async def get_ar_aging_report(
    as_of_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("reports:view"))
):
    tenant_id = claims["tenant_id"]
    return await InvoicingService.get_ar_aging_report(db, tenant_id, as_of_date)
