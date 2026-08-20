from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# HANDSHAKE & DEVICE SCHEMAS
# ============================================================================

class SyncHandshakeRequest(BaseModel):
    device_identifier: str = Field(..., min_length=5, max_length=100)
    device_name: str = Field(..., min_length=1, max_length=150)
    platform: str = "WINDOWS_DESKTOP"
    app_version: str = "1.0.0"

class SyncHandshakeResponse(BaseModel):
    device_id: str
    device_name: str
    status: str
    sync_session_token: str
    lease_expires_at: datetime
    lease_duration_seconds: int
    server_time: datetime
    server_version: str = "1.0.0"

class SyncDeviceResponse(BaseModel):
    id: str
    tenant_id: str
    device_identifier: str
    device_name: str
    platform: str
    app_version: str
    status: str
    last_sync_at: Optional[datetime] = None
    active_lease_expires_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SyncDeviceRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1)

# ============================================================================
# UPSTREAM BATCH MUTATION SCHEMAS
# ============================================================================

class SyncMutationEnvelope(BaseModel):
    client_tx_id: str = Field(..., description="UUIDv7 unique mutation identifier generated locally")
    operation_type: str = Field(..., description="RECEIVE_GOODS, PUTAWAY, PICK_ITEM, PACK_ITEM, BIN_TRANSFER, COUNT_SCAN")
    warehouse_id: str
    payload: Dict[str, Any]
    client_timestamp: datetime

class SyncUpstreamBatchRequest(BaseModel):
    device_identifier: str
    mutations: List[SyncMutationEnvelope] = Field(..., min_length=1)

class SyncMutationAck(BaseModel):
    client_tx_id: str
    operation_type: str
    status: str # COMMITTED, REJECTED, CONFLICT
    server_tx_id: Optional[str] = None
    error_message: Optional[str] = None
    committed_at: datetime

class SyncUpstreamBatchResponse(BaseModel):
    total_received: int
    committed_count: int
    rejected_count: int
    conflict_count: int
    acks: List[SyncMutationAck] = []
    server_time: datetime

# ============================================================================
# DOWNSTREAM DELTA CACHE SCHEMAS
# ============================================================================

class DeltaItemResponse(BaseModel):
    id: str
    sku: str
    name: str
    base_uom: str
    valuation_method: str
    is_batch_tracked: bool
    is_serial_tracked: bool
    variants: List[Dict[str, Any]] = []

class DeltaBinResponse(BaseModel):
    id: str
    warehouse_id: str
    code: str
    aisle: str
    rack: str
    shelf: str
    bin: str
    type: str
    is_active: bool

class DeltaBalanceResponse(BaseModel):
    warehouse_id: str
    location_bin_id: str
    item_variant_id: str
    lot_id: Optional[str] = None
    quantity_on_hand: float
    quantity_allocated: float

class DeltaLotResponse(BaseModel):
    id: str
    item_variant_id: str
    lot_number: str
    expiry_date: Optional[str] = None
    status: str

class DeltaSerialResponse(BaseModel):
    id: str
    item_variant_id: str
    serial_number: str
    status: str
    location_bin_id: Optional[str] = None
    lot_id: Optional[str] = None

class SyncDownstreamResponse(BaseModel):
    warehouse_id: str
    server_time: datetime
    items: List[DeltaItemResponse] = []
    bins: List[DeltaBinResponse] = []
    balances: List[DeltaBalanceResponse] = []
    lots: List[DeltaLotResponse] = []
    serials: List[DeltaSerialResponse] = []

# ============================================================================
# BIDIRECTIONAL CHANGE-FEED SCHEMAS
# ============================================================================

class ChangeFeedItem(BaseModel):
    revision_id: int
    entity_type: str
    entity_id: str
    change_type: str
    payload: Dict[str, Any]
    created_at: datetime

class ChangeFeedResponse(BaseModel):
    current_server_revision: int
    since_revision: int
    count: int
    has_more: bool
    changes: List[ChangeFeedItem] = []

