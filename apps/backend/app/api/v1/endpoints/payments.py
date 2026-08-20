from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.payment_gateway import PaymentTransaction
from app.schemas.payment_gateway import (
    PaymentIntentCreateRequest,
    PaymentIntentResponse,
    PaymentRefundRequest,
    PaymentRefundResponse,
    PaymentTransactionResponse,
    WebhookIngestResponse
)
from app.services.payment_service import PaymentService

router = APIRouter()

@router.post("/intents", response_model=PaymentIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    req: PaymentIntentCreateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("invoicing:payments:create"))
):
    tenant_id = claims["tenant_id"]
    customer_id = claims.get("customer_id")
    if not customer_id:
        # If internal staff, resolve from invoice
        from app.models.invoicing import CustomerInvoice
        inv = (await db.execute(select(CustomerInvoice).where(CustomerInvoice.id == req.invoice_id))).scalar_one_or_none()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        customer_id = inv.customer_id

    return await PaymentService.create_payment_intent(
        db=db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        req=req,
        user_id=claims.get("sub")
    )

@router.post("/transactions/{transaction_id}/refund", response_model=PaymentRefundResponse)
async def refund_payment_transaction(
    transaction_id: str,
    req: PaymentRefundRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("invoicing:payments:manage"))
):
    tenant_id = claims["tenant_id"]
    return await PaymentService.process_refund(
        db=db,
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        req=req,
        user_id=claims.get("sub")
    )

@router.post("/webhooks/{provider_code}", response_model=WebhookIngestResponse)
async def ingest_payment_webhook(
    provider_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature")
):
    payload_bytes = await request.body()
    sig = x_signature or stripe_signature or x_razorpay_signature or ""
    # In multi-tenant environments, default to default tenant or resolve from header/query
    from app.core.config import settings
    tenant_id = settings.TENANT_DEFAULT_ID

    return await PaymentService.handle_webhook(
        db=db,
        tenant_id=tenant_id,
        provider_code=provider_code,
        payload_bytes=payload_bytes,
        signature_header=sig
    )
