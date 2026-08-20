from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# ============================================================================
# CUSTOMER ADDRESS & CONTACT SCHEMAS
# ============================================================================

class CustomerAddressCreate(BaseModel):
    address_type: str = Field(default="SHIPPING", pattern="^(BILLING|SHIPPING)$")
    label: Optional[str] = None
    street1: str = Field(..., min_length=1, max_length=255)
    street2: Optional[str] = None
    city: str = Field(..., min_length=1, max_length=100)
    state: Optional[str] = None
    postal_code: str = Field(..., min_length=1, max_length=30)
    country: str = Field(default="USA", max_length=100)
    is_default: bool = False

class CustomerAddressResponse(BaseModel):
    id: str
    customer_id: str
    address_type: str
    label: Optional[str] = None
    street1: str
    street2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CustomerContactCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    job_title: Optional[str] = None
    is_primary: bool = False

class CustomerContactResponse(BaseModel):
    id: str
    customer_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    job_title: Optional[str] = None
    is_primary: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# CUSTOMER MASTER SCHEMAS
# ============================================================================

class CustomerCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_identifier: Optional[str] = None
    currency: str = Field(default="USD", max_length=10)
    payment_terms: str = Field(default="NET_30", pattern="^(PREPAID|NET_15|NET_30|NET_60)$")
    credit_limit: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0)
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    is_active: bool = True

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_identifier: Optional[str] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class CustomerResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_identifier: Optional[str] = None
    currency: str = "USD"
    payment_terms: str = "NET_30"
    credit_limit: float = 0.0
    current_credit_exposure: float = 0.0
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    is_active: bool
    active_orders_count: Optional[int] = 0
    addresses: List[CustomerAddressResponse] = []
    contacts: List[CustomerContactResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SALES ORDER LINE SCHEMAS
# ============================================================================

class SOLineCreate(BaseModel):
    item_variant_id: str
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    discount_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)
    tax_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)

class SOAllocationDetail(BaseModel):
    location_bin_id: str
    bin_code: str
    quantity_allocated: float

    model_config = ConfigDict(from_attributes=True)

class SOLineResponse(BaseModel):
    id: str
    sales_order_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_sku: str
    variant_name: Optional[str] = None
    quantity_ordered: float
    quantity_allocated: float = 0.0
    quantity_backordered: float = 0.0
    quantity_picked: float = 0.0
    quantity_shipped: float = 0.0
    quantity_returned: float = 0.0
    quantity_cancelled: float = 0.0
    unit_price: float
    discount_pct: float = 0.0
    tax_pct: float = 0.0
    line_total: float
    allocations: List[SOAllocationDetail] = []

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SALES ORDER SCHEMAS
# ============================================================================

class SalesOrderCreate(BaseModel):
    customer_id: str
    warehouse_id: str
    notes: Optional[str] = None
    lines: List[SOLineCreate] = Field(..., min_length=1)

class SalesOrderUpdate(BaseModel):
    customer_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[List[SOLineCreate]] = None

class ShipmentResponse(BaseModel):
    id: str
    shipment_number: str
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    package_count: int = 1
    total_weight: Optional[float] = None
    shipped_at: datetime
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class SalesReturnLineResponse(BaseModel):
    id: str
    so_line_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    quantity_returned: float
    condition: str
    destination_bin_id: str
    destination_bin_code: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class SalesReturnResponse(BaseModel):
    id: str
    return_number: str
    sales_order_id: str
    status: str
    rma_status: str = "RECEIVED"
    inspection_notes: Optional[str] = None
    disposition: Optional[str] = None
    returned_at: datetime
    notes: Optional[str] = None
    lines: List[SalesReturnLineResponse] = []

    model_config = ConfigDict(from_attributes=True)

class SalesOrderResponse(BaseModel):
    id: str
    tenant_id: str
    so_number: str
    customer_id: str
    customer_name: str
    customer_code: Optional[str] = None
    warehouse_id: str
    warehouse_name: str
    warehouse_code: Optional[str] = None
    status: str
    hold_reason: Optional[str] = None
    hold_placed_at: Optional[datetime] = None
    delivery_confirmed_at: Optional[datetime] = None
    delivery_notes: Optional[str] = None
    subtotal_amount: float = 0.0
    discount_amount: float = 0.0
    tax_amount: float = 0.0
    total_amount: float
    ordered_at: datetime
    notes: Optional[str] = None
    lines: List[SOLineResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SalesOrderDetailResponse(SalesOrderResponse):
    shipments: List[ShipmentResponse] = []
    returns: List[SalesReturnResponse] = []


# ============================================================================
# FULFILLMENT & LIFECYCLE WORKFLOW SCHEMAS
# ============================================================================

class SOPlaceHoldRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)

class SOReleaseHoldRequest(BaseModel):
    notes: Optional[str] = None

class SOCreditOverrideRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)

class SODeliveryConfirmRequest(BaseModel):
    delivery_notes: Optional[str] = None

class RMAInspectRequest(BaseModel):
    disposition: str = Field(..., pattern="^(RESTOCK|SCRAP|RETURN_TO_VENDOR)$")
    inspection_notes: Optional[str] = None
    target_restock_bin_id: Optional[str] = None

class SOAllocationItem(BaseModel):
    so_line_id: str
    location_bin_id: str
    quantity: Decimal = Field(..., gt=0)

class SOAllocateRequest(BaseModel):
    allocations: Optional[List[SOAllocationItem]] = None # If None, auto-allocates from available bins in warehouse
    allow_partial: bool = False # Set True to allow partial allocation with backorder recording

class SOPickItem(BaseModel):
    so_line_id: str
    quantity_picked: Decimal = Field(..., gt=0)

class SOPickRequest(BaseModel):
    picks: List[SOPickItem] = Field(..., min_length=1)

class SOPackRequest(BaseModel):
    package_count: int = Field(default=1, ge=1)
    total_weight: Optional[Decimal] = None
    packing_notes: Optional[str] = None

class SODispatchRequest(BaseModel):
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    package_count: int = Field(default=1, ge=1)
    total_weight: Optional[Decimal] = None
    notes: Optional[str] = None

class SalesReturnLineCreate(BaseModel):
    so_line_id: str
    quantity_returned: Decimal = Field(..., gt=0)
    condition: str = Field(default="GOOD", pattern="^(GOOD|DAMAGED)$")
    destination_bin_id: str

class SalesReturnCreate(BaseModel):
    notes: Optional[str] = None
    lines: List[SalesReturnLineCreate] = Field(..., min_length=1)
