from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime

class BarcodeResolutionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    raw_barcode: str
    warehouse_id: Optional[str] = None

class BarcodeResolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    found: bool
    entity_type: str # VARIANT, LOCATION_BIN, PURCHASE_ORDER, GOODS_RECEIPT, SALES_ORDER, SHIPMENT, PACKAGE, UNKNOWN
    identifier: str
    display_title: str
    display_subtitle: Optional[str] = None
    payload: Dict[str, Any] = {}

class GoodsReceiptScanLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    po_line_id: str
    item_variant_id: str
    quantity_received: float = Field(gt=0)
    staging_bin_id: str
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    serial_numbers: Optional[List[str]] = None

class GoodsReceiptScanSubmit(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    purchase_order_id: str
    lines: List[GoodsReceiptScanLine]
    notes: Optional[str] = None

class PutawayExecutionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    warehouse_id: str
    source_staging_bin_id: str
    destination_storage_bin_id: str
    item_variant_id: str
    quantity: float = Field(gt=0)
    batch_id: Optional[str] = None

class PutawayExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    success: bool
    transaction_id: str
    transaction_number: str
    source_bin_code: str
    destination_bin_code: str
    item_variant_sku: str
    transferred_quantity: float
    timestamp: datetime

class BinTransferRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    warehouse_id: str
    source_bin_id: str
    destination_bin_id: str
    item_variant_id: str
    quantity: float = Field(gt=0)
    batch_id: Optional[str] = None

class BinTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    success: bool
    transaction_id: str
    transaction_number: str
    source_bin_code: str
    destination_bin_code: str
    item_variant_sku: str
    transferred_quantity: float
    timestamp: datetime

class CountLineSubmitItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    location_bin_id: str
    item_variant_id: str
    counted_quantity: float = Field(ge=0)
    batch_id: Optional[str] = None
    notes: Optional[str] = None

class CountSessionCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    warehouse_id: str
    scope_type: str = "FULL_WAREHOUSE" # FULL_WAREHOUSE, ZONE, CATEGORY, CUSTOM_BINS
    bin_ids: Optional[List[str]] = None
    category_id: Optional[str] = None
    notes: Optional[str] = None

class CountLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    count_session_id: str
    location_bin_id: str
    bin_code: str
    item_variant_id: str
    variant_sku: str
    item_name: str
    expected_quantity: float
    counted_quantity: Optional[float] = None
    variance_quantity: float
    unit_cost: float
    variance_value: float
    is_recounted: bool

class CountSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    warehouse_id: str
    warehouse_name: str
    session_number: str
    status: str
    scope_type: str
    notes: Optional[str] = None
    total_lines: int
    total_counted_lines: int
    total_variance_quantity: float
    total_variance_value: float
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    lines: List[CountLineResponse] = []

class CountSessionSubmitRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    counts: List[CountLineSubmitItem]

class CountSessionApprovalRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: str = "APPROVE" # APPROVE, RECOUNT, REJECT
    review_notes: Optional[str] = None

class PickTaskLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    pick_task_id: str
    so_line_id: str
    location_bin_id: str
    bin_code: str
    bin_aisle: str
    bin_rack: str
    bin_shelf: str
    bin_position: str
    item_variant_id: str
    variant_sku: str
    item_name: str
    quantity_allocated: float
    quantity_picked: float
    status: str

class PickTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    warehouse_id: str
    sales_order_id: str
    sales_order_number: str
    task_number: str
    status: str
    total_lines: int
    picked_lines: int
    lines: List[PickTaskLineResponse]

class PickLineConfirmRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pick_task_line_id: str
    scanned_bin_code: str
    scanned_item_barcode: str
    quantity_picked: float = Field(gt=0)

class PackingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    item_variant_id: str
    variant_sku: str
    item_name: str
    quantity_packed: float
    carton_number: int
    scanned_at: datetime

class PackingSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    shipment_id: str
    session_number: str
    status: str
    carton_count: int
    total_ordered_quantity: float
    total_packed_quantity: float
    is_fully_verified: bool
    items: List[PackingItemResponse] = []

class PackingItemVerifyRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    shipment_id: str
    scanned_barcode: str
    quantity: float = 1.0
    carton_number: int = 1

class PackingItemVerifyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    verified: bool
    message: str
    item_variant_sku: str
    item_name: str
    quantity_packed_total: float
    quantity_required_total: float
    is_order_complete: bool

class LabelItemPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    label_type: str # VARIANT, BIN, GRN, SHIPPING_CARTON
    entity_id: str
    title: str
    subtitle: Optional[str] = None
    barcode_payload: str
    barcode_human_readable: str
    symbology: str = "CODE128"

class LabelGenerationRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    label_type: str # VARIANT, BIN, GRN, SHIPPING_CARTON
    entity_ids: List[str]
    copies_per_item: int = 1

class LabelGenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    total_labels: int
    labels: List[LabelItemPayload]
