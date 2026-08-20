from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# ============================================================================
# AUTH & MEMBERSHIP SCHEMAS
# ============================================================================

class PortalLoginRequest(BaseModel):
    email: str
    password: str
    portal_type: str # CUSTOMER, SUPPLIER

class PortalLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    portal_user_id: str
    full_name: str
    email: str
    portal_type: str
    entity_id: str # customer_id or supplier_id
    entity_name: str
    role: str
    permissions: List[str]

class PortalInviteUserRequest(BaseModel):
    email: str
    role: Optional[str] = "MEMBER"

class PortalAcceptInviteRequest(BaseModel):
    token: str
    full_name: str
    password: str

class PortalUserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None

class SecureDocumentTokenResponse(BaseModel):
    document_type: str
    document_id: str
    download_url: str
    expires_at: datetime

# ============================================================================
# CUSTOMER PORTAL SCHEMAS (SANITIZED - ZERO INTERNAL MARGINS/COSTS)
# ============================================================================

class CustomerProfileResponse(BaseModel):
    id: str
    code: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    currency: str
    payment_terms: str
    credit_limit: float
    current_credit_exposure: float
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None

class CustomerCatalogItemResponse(BaseModel):
    item_id: str
    variant_id: str
    sku: str
    name: str
    variant_name: str
    unit_price: float
    is_in_stock: bool # Boolean indicator, no exact internal warehouse counts

class CustomerOrderLineCreate(BaseModel):
    item_variant_id: str
    quantity: Decimal

class CustomerOrderCreateRequest(BaseModel):
    customer_notes: Optional[str] = None
    shipping_address: Optional[Dict[str, Any]] = None
    lines: List[CustomerOrderLineCreate]

class CustomerOrderLineResponse(BaseModel):
    id: str
    item_variant_id: str
    sku: str
    variant_name: str
    quantity_ordered: float
    quantity_shipped: float
    unit_price: float
    line_total: float

class CustomerOrderResponse(BaseModel):
    id: str
    so_number: str
    status: str
    total_amount: float
    subtotal_amount: float
    tax_amount: float
    currency: str
    customer_notes: Optional[str] = None
    created_at: datetime
    lines: List[CustomerOrderLineResponse]

class CustomerReturnLineCreate(BaseModel):
    so_line_id: str
    quantity: Decimal
    reason: Optional[str] = None

class CustomerReturnCreateRequest(BaseModel):
    sales_order_id: str
    reason: Optional[str] = None
    lines: List[CustomerReturnLineCreate]

class CustomerReturnResponse(BaseModel):
    id: str
    return_number: str
    sales_order_id: str
    status: str
    rma_status: str
    returned_at: datetime

# ============================================================================
# SUPPLIER PORTAL SCHEMAS (SANITIZED - ZERO CUSTOMER/MARGIN LEAKS)
# ============================================================================

class SupplierProfileResponse(BaseModel):
    id: str
    code: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    currency: str
    payment_terms: str

class SupplierPOLineResponse(BaseModel):
    id: str
    item_variant_id: str
    sku: str
    variant_name: str
    quantity_ordered: float
    quantity_received: float
    unit_cost: float
    line_total: float

class SupplierPOResponse(BaseModel):
    id: str
    po_number: str
    status: str
    order_date: datetime
    promised_delivery_date: Optional[datetime] = None
    total_amount: float
    currency: str
    lines: List[SupplierPOLineResponse]

class SupplierPOConfirmRequest(BaseModel):
    promised_delivery_date: datetime
    notes: Optional[str] = None

class SupplierPORejectRequest(BaseModel):
    rejection_reason: str

class ASNLineCreate(BaseModel):
    po_line_id: str
    item_variant_id: str
    quantity_shipped: Decimal
    lot_number: Optional[str] = None
    serial_numbers: Optional[List[str]] = None

class CreateASNRequest(BaseModel):
    purchase_order_id: str
    carrier_code: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_arrival_date: datetime
    notes: Optional[str] = None
    lines: List[ASNLineCreate]

class ASNLineResponse(BaseModel):
    id: str
    po_line_id: str
    item_variant_id: str
    quantity_shipped: float
    lot_number: Optional[str] = None

class ASNResponse(BaseModel):
    id: str
    asn_number: str
    purchase_order_id: str
    po_number: Optional[str] = None
    carrier_code: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_arrival_date: datetime
    status: str
    created_at: datetime
    lines: List[ASNLineResponse] = []
