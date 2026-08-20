from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class VendorInvoiceLineCreate(BaseModel):
    po_line_id: str
    grn_line_id: Optional[str] = None
    item_variant_id: str
    billed_quantity: Decimal = Field(..., gt=0)
    billed_unit_price: Decimal = Field(..., ge=0)
    tax_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)

class VendorInvoiceLineResponse(BaseModel):
    id: str
    vendor_invoice_id: str
    po_line_id: str
    grn_line_id: Optional[str] = None
    item_variant_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    billed_quantity: float
    received_quantity: float
    po_unit_price: float
    billed_unit_price: float
    price_variance_unit: float
    total_price_variance: float
    tax_pct: float
    line_total: float

    model_config = ConfigDict(from_attributes=True)

class VendorInvoiceCreate(BaseModel):
    purchase_order_id: str
    goods_receipt_id: Optional[str] = None
    vendor_invoice_reference: str = Field(..., min_length=1)
    invoice_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    lines: List[VendorInvoiceLineCreate]

class VendorInvoiceResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_number: str
    vendor_invoice_reference: str
    purchase_order_id: str
    goods_receipt_id: Optional[str] = None
    supplier_id: str
    supplier_name: Optional[str] = None
    supplier_code: Optional[str] = None
    status: str
    match_status: str
    subtotal_amount: float
    discount_amount: float
    tax_amount: float
    total_amount: float
    amount_paid: float
    balance_due: float
    currency: str
    invoice_date: datetime
    due_date: datetime
    notes: Optional[str] = None
    match_notes: Optional[str] = None
    approved_by_user_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    lines: List[VendorInvoiceLineResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VendorPaymentAllocationItem(BaseModel):
    vendor_invoice_id: str
    amount: Decimal = Field(..., gt=0)

class VendorPaymentCreate(BaseModel):
    supplier_id: str
    payment_method: str = "BANK_TRANSFER" # BANK_TRANSFER, CHECK, CREDIT_CARD, CASH
    amount: Decimal = Field(..., gt=0)
    currency: str = "USD"
    payment_date: Optional[datetime] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    allocations: List[VendorPaymentAllocationItem]

class VendorPaymentAllocationResponse(BaseModel):
    id: str
    vendor_invoice_id: str
    invoice_number: Optional[str] = None
    amount_allocated: float
    allocated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VendorPaymentResponse(BaseModel):
    id: str
    tenant_id: str
    payment_number: str
    supplier_id: str
    supplier_name: Optional[str] = None
    supplier_code: Optional[str] = None
    payment_method: str
    amount: float
    currency: str
    payment_date: datetime
    reference_number: Optional[str] = None
    status: str
    notes: Optional[str] = None
    allocations: List[VendorPaymentAllocationResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class APMatchingToleranceUpdate(BaseModel):
    price_tolerance_pct: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    price_tolerance_max_amount: Decimal = Field(default=Decimal("50.0"), ge=0)
    quantity_tolerance_pct: Decimal = Field(default=Decimal("0.0"), ge=0, le=100)
    auto_approve_within_tolerance: bool = True

class APMatchingToleranceResponse(BaseModel):
    tenant_id: str
    price_tolerance_pct: float
    price_tolerance_max_amount: float
    quantity_tolerance_pct: float
    auto_approve_within_tolerance: bool

    model_config = ConfigDict(from_attributes=True)

class APAgingBucket(BaseModel):
    bucket_label: str
    total_amount: float
    bill_count: int

class SupplierAPAgingSummary(BaseModel):
    supplier_id: str
    supplier_code: str
    supplier_name: str
    total_outstanding: float
    current_amount: float
    days_1_30: float
    days_31_60: float
    days_61_90: float
    days_over_90: float

class APAgingReportResponse(BaseModel):
    as_of_date: datetime
    total_payables: float
    summary_buckets: List[APAgingBucket]
    supplier_summaries: List[SupplierAPAgingSummary]
