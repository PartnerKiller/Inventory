from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# SUPPLY CHAIN NODE SCHEMAS
# ============================================================================

class SupplyChainNodeCreate(BaseModel):
    node_code: str
    node_name: str
    node_type: str # CENTRAL_DC, REGIONAL_DC, WAREHOUSE, RETAIL_EDGE, SUPPLIER
    warehouse_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    lead_time_days: int = 1
    sourcing_priority: int = 1

class SupplyChainNodeResponse(BaseModel):
    id: str
    tenant_id: str
    node_code: str
    node_name: str
    node_type: str
    warehouse_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    lead_time_days: int
    sourcing_priority: int
    is_active: bool
    created_at: datetime

# ============================================================================
# TRANSFER ORDER SCHEMAS
# ============================================================================

class TransferOrderLineCreate(BaseModel):
    item_variant_id: str
    quantity_requested: Decimal

class TransferOrderCreate(BaseModel):
    source_warehouse_id: str
    destination_warehouse_id: str
    in_transit_bin_id: str
    destination_bin_id: str
    freight_charge: Decimal = Decimal("0.0")
    carrier_tracking_number: Optional[str] = None
    notes: Optional[str] = None
    lines: List[TransferOrderLineCreate]

class TransferOrderLineResponse(BaseModel):
    id: str
    item_variant_id: str
    quantity_requested: Decimal
    quantity_shipped: Decimal
    quantity_received: Decimal
    quantity_damaged: Decimal
    unit_cost: Decimal

class TransferOrderResponse(BaseModel):
    id: str
    tenant_id: str
    transfer_number: str
    source_warehouse_id: str
    destination_warehouse_id: str
    in_transit_bin_id: str
    destination_bin_id: str
    status: str
    freight_charge: Decimal
    dispatched_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    carrier_tracking_number: Optional[str] = None
    notes: Optional[str] = None
    lines: List[TransferOrderLineResponse]
    created_at: datetime

class TransferDispatchAction(BaseModel):
    pass

class TransferReceiveLineAction(BaseModel):
    item_variant_id: str
    quantity_received: Decimal
    quantity_damaged: Decimal = Decimal("0.0")
    damage_bin_id: Optional[str] = None

class TransferReceiveAction(BaseModel):
    received_lines: List[TransferReceiveLineAction]

# ============================================================================
# SOURCING PLAN SCHEMAS
# ============================================================================

class SourcingPlanRequest(BaseModel):
    item_variant_id: str
    demand_quantity: Decimal
    requesting_warehouse_id: str

class SourcingOption(BaseModel):
    tier: str # LOCAL_STOCK, REGIONAL_TRANSFER, CENTRAL_TRANSFER, PRODUCTION_MAKE, SUPPLIER_BUY
    source_id: str # Warehouse ID, DC ID, WorkCenter ID, or Supplier ID
    source_name: str
    available_quantity: Decimal
    lead_time_days: int
    estimated_unit_cost: Decimal
    recommended: bool

class SourcingPlanResponse(BaseModel):
    item_variant_id: str
    demand_quantity: Decimal
    requesting_warehouse_id: str
    options: List[SourcingOption]

# ============================================================================
# EDGE SYNC SCHEMAS
# ============================================================================

class EdgeMutationItem(BaseModel):
    client_transaction_id: str # UUIDv7
    operation_type: str # COUNT_SCAN, PICK_ITEM, PACK_ITEM, BIN_TRANSFER, POS_SALE, RECEIVE_GOODS, WO_COMPLETE, BOM_EDIT, PO_APPROVE, GL_CLOSE
    warehouse_id: str
    item_variant_id: Optional[str] = None
    source_bin_id: Optional[str] = None
    destination_bin_id: Optional[str] = None
    quantity: Optional[Decimal] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

class EdgeSyncBatchRequest(BaseModel):
    device_id: str
    batch_id: str
    hmac_signature: Optional[str] = None
    mutations: List[EdgeMutationItem]

class EdgeMutationResult(BaseModel):
    client_transaction_id: str
    status: str # COMMITTED, CONFLICT, REJECTED
    server_transaction_id: Optional[str] = None
    error_detail: Optional[str] = None
    compensating_action: Optional[str] = None

class EdgeSyncBatchResponse(BaseModel):
    batch_id: str
    device_id: str
    processed_count: int
    results: List[EdgeMutationResult]
