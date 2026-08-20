from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# ============================================================================
# SUPPLIER CONTACT & ADDRESS SCHEMAS
# ============================================================================

class SupplierContactCreate(BaseModel):
    contact_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = "Sales Representative"
    is_primary: bool = False

class SupplierContactResponse(BaseModel):
    id: str
    supplier_id: str
    contact_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    is_primary: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SupplierAddressCreate(BaseModel):
    address_type: str = "ORDERING" # ORDERING, REMITTANCE, SHIPPING_ORIGIN
    address_line1: str = Field(..., min_length=1, max_length=255)
    address_line2: Optional[str] = None
    city: str = Field(..., min_length=1, max_length=100)
    state: Optional[str] = None
    postal_code: str = Field(..., min_length=1, max_length=20)
    country: str = "US"
    is_default: bool = False

class SupplierAddressResponse(BaseModel):
    id: str
    supplier_id: str
    address_type: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# SUPPLIER MASTER SCHEMAS
# ============================================================================

class SupplierCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    tax_identifier: Optional[str] = None
    payment_terms: str = "Net 30"
    credit_limit: Optional[Decimal] = Decimal("0.0")
    currency: str = "USD"
    status: str = "ACTIVE" # ACTIVE, ON_HOLD, INACTIVE
    is_active: bool = True
    contacts: Optional[List[SupplierContactCreate]] = None
    addresses: Optional[List[SupplierAddressCreate]] = None

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    tax_identifier: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None

class SupplierResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    tax_identifier: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_limit: float = 0.0
    currency: str
    status: str = "ACTIVE"
    is_active: bool
    active_orders_count: Optional[int] = 0
    contacts: List[SupplierContactResponse] = []
    addresses: List[SupplierAddressResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# SUPPLIER-PRODUCT CATALOG SCHEMAS
# ============================================================================

class SupplierProductCreate(BaseModel):
    item_variant_id: str
    supplier_sku: Optional[str] = None
    supplier_product_name: Optional[str] = None
    unit_cost: Decimal = Field(..., ge=0)
    currency: str = "USD"
    minimum_order_quantity: Decimal = Field(default=Decimal("1.0"), gt=0)
    pack_size: Decimal = Field(default=Decimal("1.0"), gt=0)
    lead_time_days: int = Field(default=14, ge=0)
    is_preferred: bool = False
    is_active: bool = True

class SupplierProductUpdate(BaseModel):
    supplier_sku: Optional[str] = None
    supplier_product_name: Optional[str] = None
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = None
    minimum_order_quantity: Optional[Decimal] = Field(default=None, gt=0)
    pack_size: Optional[Decimal] = Field(default=None, gt=0)
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    is_preferred: Optional[bool] = None
    is_active: Optional[bool] = None
    change_reason: Optional[str] = None

class SupplierPriceHistoryResponse(BaseModel):
    id: str
    supplier_product_id: str
    unit_price: float
    currency: str
    effective_date: datetime
    source_document_type: str
    source_document_id: Optional[str] = None
    change_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SupplierProductResponse(BaseModel):
    id: str
    tenant_id: str
    supplier_id: str
    supplier_name: Optional[str] = None
    supplier_code: Optional[str] = None
    item_variant_id: str
    variant_sku: Optional[str] = None
    item_name: Optional[str] = None
    supplier_sku: Optional[str] = None
    supplier_product_name: Optional[str] = None
    unit_cost: float
    currency: str
    minimum_order_quantity: float
    pack_size: float
    lead_time_days: int
    is_preferred: bool
    is_active: bool
    effective_from: datetime
    effective_to: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# PURCHASE ORDER LINE SCHEMAS
# ============================================================================

class POLineCreate(BaseModel):
    item_variant_id: str
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    discount_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)
    tax_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)

class POLineResponse(BaseModel):
    id: str
    purchase_order_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_sku: str
    variant_name: Optional[str] = None
    quantity_ordered: float
    quantity_received: float
    quantity_cancelled: float = 0.0
    quantity_remaining: float
    unit_price: float
    discount_pct: float = 0.0
    tax_pct: float = 0.0
    line_total: float

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# GOODS RECEIPT (GRN) SCHEMAS
# ============================================================================

class GoodsReceiptLineCreate(BaseModel):
    po_line_id: str
    item_variant_id: str
    quantity_received: Decimal = Field(..., gt=0)
    destination_bin_id: str
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None

class GoodsReceiptLineResponse(BaseModel):
    id: str
    po_line_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    quantity_received: float
    destination_bin_id: str
    destination_bin_code: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class GoodsReceiptCreate(BaseModel):
    purchase_order_id: str
    warehouse_id: str
    notes: Optional[str] = None
    lines: List[GoodsReceiptLineCreate] = Field(..., min_length=1)

class GoodsReceiptResponse(BaseModel):
    id: str
    grn_number: str
    purchase_order_id: str
    warehouse_id: str
    warehouse_name: Optional[str] = None
    received_at: datetime
    notes: Optional[str] = None
    lines: List[GoodsReceiptLineResponse] = []

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# PURCHASE ORDER SCHEMAS
# ============================================================================

class PurchaseOrderCreate(BaseModel):
    supplier_id: str
    target_warehouse_id: str
    currency: str = "USD"
    expected_delivery_at: Optional[datetime] = None
    notes: Optional[str] = None
    lines: List[POLineCreate] = Field(..., min_length=1)

class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[str] = None
    target_warehouse_id: Optional[str] = None
    expected_delivery_at: Optional[datetime] = None
    notes: Optional[str] = None
    lines: Optional[List[POLineCreate]] = None

class PurchaseOrderResponse(BaseModel):
    id: str
    tenant_id: str
    po_number: str
    supplier_id: str
    supplier_name: str
    supplier_code: Optional[str] = None
    target_warehouse_id: str
    target_warehouse_name: str
    target_warehouse_code: Optional[str] = None
    status: str
    subtotal_amount: float = 0.0
    discount_amount: float = 0.0
    tax_amount: float = 0.0
    freight_amount: float = 0.0
    customs_amount: float = 0.0
    total_amount: float
    currency: str = "USD"
    ordered_at: datetime
    expected_delivery_at: Optional[datetime] = None
    notes: Optional[str] = None
    lines: List[POLineResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PurchaseOrderDetailResponse(PurchaseOrderResponse):
    receipts: List[GoodsReceiptResponse] = []

# ============================================================================
# SUPPLIER RETURNS (RTV) & DEBIT MEMOS
# ============================================================================

class SupplierReturnLineCreate(BaseModel):
    item_variant_id: str
    source_location_bin_id: str
    quantity_returned: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)
    batch_number: Optional[str] = None

class SupplierReturnCreate(BaseModel):
    supplier_id: str
    warehouse_id: str
    purchase_order_id: Optional[str] = None
    return_reason: str = "DEFECTIVE" # DEFECTIVE, DAMAGED_IN_TRANSIT, WRONG_SPECIFICATION, EXPIRED, OTHER
    notes: Optional[str] = None
    lines: List[SupplierReturnLineCreate] = Field(..., min_length=1)

class SupplierReturnLineResponse(BaseModel):
    id: str
    item_variant_id: str
    variant_sku: str
    item_name: str
    source_location_bin_id: str
    source_bin_code: Optional[str] = None
    quantity_returned: float
    unit_cost: float
    total_cost: float
    batch_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class SupplierReturnResponse(BaseModel):
    id: str
    tenant_id: str
    return_number: str
    supplier_id: str
    supplier_name: str
    warehouse_id: str
    warehouse_name: str
    purchase_order_id: Optional[str] = None
    status: str
    return_reason: str
    total_refund_amount: float
    returned_at: datetime
    notes: Optional[str] = None
    lines: List[SupplierReturnLineResponse] = []

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# PROCUREMENT & REPLENISHMENT SUGGESTIONS SCHEMAS
# ============================================================================

class PurchaseSuggestionItem(BaseModel):
    variant_id: str
    variant_sku: str
    item_name: str
    warehouse_id: str
    warehouse_name: str
    supplier_id: str
    supplier_name: str
    supplier_code: str
    supplier_sku: Optional[str] = None
    unit_cost: float
    currency: str
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float
    incoming_on_po: float
    reorder_point: float
    target_stock: float
    raw_recommended_quantity: float
    pack_size: float
    minimum_order_quantity: float
    suggested_order_quantity: float
    estimated_spend: float
    lead_time_days: int
    is_preferred_supplier: bool
    urgency: str # CRITICAL_STOCKOUT, REORDER_REQUIRED, HEALTHY

class PurchaseSuggestionsResponse(BaseModel):
    total_suggestions: int
    critical_stockout_count: int
    reorder_required_count: int
    total_estimated_spend: float
    suggestions: List[PurchaseSuggestionItem] = []
    generated_at: datetime

class DraftPOFromSuggestionsRequest(BaseModel):
    suggestion_variant_ids: List[str] = Field(..., min_length=1)
    warehouse_id: Optional[str] = None

class DraftPOBatchItem(BaseModel):
    supplier_id: str
    supplier_name: str
    purchase_order_id: str
    po_number: str
    item_count: int
    total_amount: float

class DraftPOBatchResponse(BaseModel):
    total_draft_pos_created: int
    total_lines_created: int
    total_estimated_spend: float
    draft_orders: List[DraftPOBatchItem] = []

# ============================================================================
# PURCHASE PRICE VARIANCE (PPV) & SCORECARD SCHEMAS
# ============================================================================

class PurchasePriceVarianceItem(BaseModel):
    grn_id: str
    grn_number: str
    received_at: datetime
    po_id: str
    po_number: str
    supplier_id: str
    supplier_name: str
    variant_id: str
    variant_sku: str
    item_name: str
    quantity_received: float
    po_unit_price: float
    standard_unit_cost: float
    received_unit_price: float
    unit_ppv: float
    total_ppv: float
    variance_percentage: float
    variance_classification: str # FAVORABLE, UNFAVORABLE, ON_TARGET

class PurchasePriceVarianceReportResponse(BaseModel):
    total_receipt_lines_evaluated: int
    net_ppv_amount: float
    favorable_variance_amount: float
    unfavorable_variance_amount: float
    lines: List[PurchasePriceVarianceItem] = []
    generated_at: datetime

class SupplierScorecardItem(BaseModel):
    supplier_id: str
    supplier_name: str
    supplier_code: str
    status: str
    total_orders_placed: int
    total_orders_completed: int
    open_orders_count: int
    open_orders_value: float
    total_spend: float
    average_lead_time_days: Optional[float] = None
    median_lead_time_days: Optional[float] = None
    on_time_delivery_rate_percentage: float
    fulfillment_fill_rate_percentage: float
    net_purchase_price_variance: float

class SupplierScorecardResponse(BaseModel):
    total_suppliers: int
    scorecards: List[SupplierScorecardItem] = []
    generated_at: datetime

class ProcurementDashboardResponse(BaseModel):
    total_open_pos_count: int
    total_open_pos_value: float
    draft_pos_count: int
    pending_approvals_count: int
    overdue_pos_count: int
    total_active_suppliers: int
    suggestions_reorder_count: int
    suggestions_critical_count: int
    total_suggested_spend: float
    net_30d_ppv: float
    scorecards: List[SupplierScorecardItem] = []
    generated_at: datetime
