from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class InvoiceLineCreate(BaseModel):
    item_variant_id: str
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    discount_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)
    tax_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)
    so_line_id: Optional[str] = None

class InvoiceLineResponse(BaseModel):
    id: str
    invoice_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    quantity: float
    unit_price: float
    discount_pct: float
    tax_pct: float
    line_total: float

    model_config = ConfigDict(from_attributes=True)

class CustomerInvoiceCreate(BaseModel):
    customer_id: str
    sales_order_id: Optional[str] = None
    issue_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    lines: Optional[List[InvoiceLineCreate]] = None

class CustomerInvoiceResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_number: str
    sales_order_id: Optional[str] = None
    customer_id: str
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    status: str
    subtotal_amount: float
    discount_amount: float
    tax_amount: float
    total_amount: float
    amount_paid: float
    balance_due: float
    currency: str
    issue_date: datetime
    due_date: datetime
    notes: Optional[str] = None
    lines: List[InvoiceLineResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PaymentAllocationItem(BaseModel):
    invoice_id: str
    amount: Decimal = Field(..., gt=0)

class CustomerPaymentCreate(BaseModel):
    customer_id: str
    payment_method: str = "BANK_TRANSFER" # CASH, BANK_TRANSFER, CREDIT_CARD, CHECK
    amount: Decimal = Field(..., gt=0)
    currency: str = "USD"
    payment_date: Optional[datetime] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    allocations: List[PaymentAllocationItem]

class PaymentAllocationResponse(BaseModel):
    id: str
    invoice_id: str
    invoice_number: Optional[str] = None
    amount_allocated: float
    allocated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CustomerPaymentResponse(BaseModel):
    id: str
    tenant_id: str
    payment_number: str
    customer_id: str
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    payment_method: str
    amount: float
    currency: str
    payment_date: datetime
    reference_number: Optional[str] = None
    status: str
    notes: Optional[str] = None
    allocations: List[PaymentAllocationResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CreditNoteCreate(BaseModel):
    customer_id: str
    sales_return_id: Optional[str] = None
    invoice_id: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    notes: Optional[str] = None

class CreditNoteResponse(BaseModel):
    id: str
    tenant_id: str
    credit_note_number: str
    customer_id: str
    customer_name: Optional[str] = None
    sales_return_id: Optional[str] = None
    invoice_id: Optional[str] = None
    amount: float
    status: str
    issue_date: datetime
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ARAgingBucket(BaseModel):
    bucket_label: str # "Current", "1-30 Days", "31-60 Days", "61-90 Days", "90+ Days"
    total_amount: float
    invoice_count: int

class CustomerARAgingSummary(BaseModel):
    customer_id: str
    customer_code: str
    customer_name: str
    total_outstanding: float
    current_amount: float
    days_1_30: float
    days_31_60: float
    days_61_90: float
    days_over_90: float

class ARAgingReportResponse(BaseModel):
    as_of_date: datetime
    total_receivables: float
    summary_buckets: List[ARAgingBucket]
    customer_summaries: List[CustomerARAgingSummary]
