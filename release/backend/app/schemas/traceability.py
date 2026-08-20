from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# ============================================================================
# STOCK LOT SCHEMAS
# ============================================================================

class StockLotCreate(BaseModel):
    item_variant_id: str
    lot_number: str = Field(..., min_length=1, max_length=100)
    supplier_id: Optional[str] = None
    supplier_lot_number: Optional[str] = None
    origin_grn_id: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    best_before_date: Optional[date] = None
    initial_quantity: Decimal = Field(default=Decimal("0.0"), ge=0)
    notes: Optional[str] = None

class StockLotUpdate(BaseModel):
    supplier_lot_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    best_before_date: Optional[date] = None
    status: Optional[str] = None # ACTIVE, QUARANTINED, RECALLED, EXPIRED, DEPLETED
    quarantine_reason: Optional[str] = None
    notes: Optional[str] = None

class StockLotResponse(BaseModel):
    id: str
    tenant_id: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    item_name: Optional[str] = None
    lot_number: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_lot_number: Optional[str] = None
    origin_grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    cost_layer_id: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    best_before_date: Optional[date] = None
    initial_quantity: float
    current_quantity: float
    status: str
    quarantine_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# ITEM SERIAL NUMBER SCHEMAS
# ============================================================================

class ItemSerialNumberCreate(BaseModel):
    warehouse_id: str
    item_variant_id: str
    serial_number: str = Field(..., min_length=1, max_length=100)
    lot_id: Optional[str] = None
    location_bin_id: Optional[str] = None
    origin_grn_id: Optional[str] = None
    notes: Optional[str] = None

class SerialBatchRegistrationRequest(BaseModel):
    warehouse_id: str
    item_variant_id: str
    lot_id: Optional[str] = None
    location_bin_id: str
    origin_grn_id: Optional[str] = None
    serial_numbers: List[str] = Field(..., min_length=1)

class ItemSerialNumberLifecycleUpdate(BaseModel):
    status: str # IN_STOCK, ALLOCATED, PICKED, DISPATCHED, RETURNED, QUARANTINED, RETURNED_TO_SUPPLIER, RETIRED
    location_bin_id: Optional[str] = None
    dispatched_shipment_id: Optional[str] = None
    quarantine_reason: Optional[str] = None
    notes: Optional[str] = None

class ItemSerialNumberResponse(BaseModel):
    id: str
    tenant_id: str
    warehouse_id: str
    warehouse_name: Optional[str] = None
    item_variant_id: str
    variant_sku: Optional[str] = None
    item_name: Optional[str] = None
    lot_id: Optional[str] = None
    lot_number: Optional[str] = None
    serial_number: str
    status: str
    location_bin_id: Optional[str] = None
    location_bin_code: Optional[str] = None
    origin_grn_id: Optional[str] = None
    grn_number: Optional[str] = None
    dispatched_shipment_id: Optional[str] = None
    shipment_number: Optional[str] = None
    quarantine_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ============================================================================
# TRACEABILITY & RECALL SCHEMAS
# ============================================================================

class ForwardTraceShipmentItem(BaseModel):
    shipment_id: str
    shipment_number: str
    sales_order_id: str
    so_number: str
    customer_id: str
    customer_name: str
    dispatched_at: datetime
    quantity_shipped: float
    serials_dispatched: List[str] = []

class ForwardTraceResponse(BaseModel):
    lot_id: str
    lot_number: str
    variant_sku: str
    item_name: str
    supplier_name: Optional[str] = None
    total_received_quantity: float
    current_warehouse_quantity: float
    total_dispatched_quantity: float
    warehouse_locations: List[Dict[str, Any]] = []
    affected_shipments: List[ForwardTraceShipmentItem] = []
    generated_at: datetime

class BackwardTraceResponse(BaseModel):
    searched_identifier: str # serial or shipment
    variant_sku: str
    item_name: str
    serial_number: Optional[str] = None
    lot_number: Optional[str] = None
    shipment_number: Optional[str] = None
    so_number: Optional[str] = None
    customer_name: Optional[str] = None
    grn_number: Optional[str] = None
    received_at: Optional[datetime] = None
    po_number: Optional[str] = None
    supplier_code: Optional[str] = None
    supplier_name: Optional[str] = None
    cost_layer_unit_cost: Optional[float] = None
    generated_at: datetime

class RecallExecutionRequest(BaseModel):
    lot_id: str
    recall_reason: str = Field(..., min_length=1)
    target_quarantine_bin_id: Optional[str] = None

class RecallExecutionResponse(BaseModel):
    lot_id: str
    lot_number: str
    variant_sku: str
    status: str
    recalled_at: datetime
    quarantined_units_count: float
    quarantined_serials_count: int
    affected_customers_count: int
    downloadable_containment_manifest_url: Optional[str] = None

# ============================================================================
# EXPIRY & FEFO SCHEMAS
# ============================================================================

class ExpiryHorizonItem(BaseModel):
    lot_id: str
    lot_number: str
    variant_sku: str
    item_name: str
    warehouse_id: str
    warehouse_name: str
    location_bin_code: str
    quantity_on_hand: float
    expiry_date: date
    days_until_expiry: int
    expiry_classification: str # EXPIRED, CRITICAL_30D, WARNING_60D, NORMAL_90D

class ExpiryHorizonResponse(BaseModel):
    total_lots_evaluated: int
    expired_lots_count: int
    critical_30d_count: int
    warning_60d_count: int
    lots: List[ExpiryHorizonItem] = []
    generated_at: datetime

class FEFOPickRecommendationItem(BaseModel):
    lot_id: str
    lot_number: str
    location_bin_id: str
    location_bin_code: str
    available_quantity: float
    expiry_date: Optional[date] = None
    recommended_pick_quantity: float
    pick_priority_sequence: int

class FEFOPickRecommendationResponse(BaseModel):
    item_variant_id: str
    variant_sku: str
    required_quantity: float
    recommendations: List[FEFOPickRecommendationItem] = []
    generated_at: datetime
