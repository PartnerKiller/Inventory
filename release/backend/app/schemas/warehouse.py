from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

# --- Location Bins ---
class LocationBinCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    aisle: str = "A"
    rack: str = "01"
    shelf: str = "01"
    bin: str = "01"
    type: str = "STORAGE" # STORAGE, RECEIVING, SHIPPING, STAGING, DAMAGE, VIRTUAL_ADJUSTMENT

class LocationBinUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=2, max_length=50)
    aisle: Optional[str] = None
    rack: Optional[str] = None
    shelf: Optional[str] = None
    bin: Optional[str] = None
    type: Optional[str] = None # STORAGE, RECEIVING, SHIPPING, STAGING, DAMAGE, VIRTUAL_ADJUSTMENT
    is_active: Optional[bool] = None

class LocationBinResponse(BaseModel):
    id: str
    warehouse_id: str
    code: str
    aisle: str
    rack: str
    shelf: str
    bin: str
    type: str
    is_active: bool
    created_at: datetime
    occupied_items_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)

# --- Warehouses ---
class WarehouseCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=255)
    address: Optional[Dict[str, Any]] = None

class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    address: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class WarehouseResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    address: Optional[Dict[str, Any]] = None
    is_active: bool
    total_bins: Optional[int] = 0
    total_stock_on_hand: Optional[float] = 0.0
    bins: List[LocationBinResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
