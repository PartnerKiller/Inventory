from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class StockTransferRequest(BaseModel):
    item_variant_id: str
    source_bin_id: str
    destination_bin_id: str
    quantity: Decimal = Field(gt=0)
    batch_number: Optional[str] = None
    notes: Optional[str] = None

class StockAdjustmentRequest(BaseModel):
    item_variant_id: str
    location_bin_id: str
    adjustment_type: str = "INVENTORY_ADJUSTMENT" # INVENTORY_ADJUSTMENT, SCRAP, CYCLE_COUNT
    counted_quantity: Decimal = Field(ge=0) # New physical quantity
    batch_number: Optional[str] = None
    reason: str
    unit_cost: Optional[Decimal] = None

class StockLedgerEntryResponse(BaseModel):
    id: str
    transaction_id: str
    transaction_number: str
    transaction_type: str
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_name: str
    batch_number: Optional[str] = None
    serial_number: Optional[str] = None
    source_location_bin_id: Optional[str] = None
    source_bin_code: Optional[str] = None
    destination_location_bin_id: Optional[str] = None
    destination_bin_code: Optional[str] = None
    quantity: float
    uom: str
    unit_cost: float
    total_cost: float
    posted_by_user_id: Optional[str] = None
    posted_by_user_name: Optional[str] = None
    posted_at: datetime
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class StockBalanceResponse(BaseModel):
    id: str
    warehouse_id: str
    warehouse_code: str
    warehouse_name: str
    location_bin_id: str
    bin_code: str
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_sku: str
    variant_name: str
    batch_number: Optional[str] = None
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
