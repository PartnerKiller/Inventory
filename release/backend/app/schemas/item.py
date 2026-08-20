from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

# --- Barcodes ---
class BarcodeCreate(BaseModel):
    barcode_value: str = Field(..., min_length=2, max_length=128)
    symbology: str = "CODE128" # CODE128, EAN13, UPCA, QR, DATAMATRIX
    is_primary: bool = False

class BarcodeResponse(BaseModel):
    id: str
    item_variant_id: str
    barcode_value: str
    symbology: str
    is_primary: bool

    model_config = ConfigDict(from_attributes=True)

# --- Categories ---
class ItemCategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    code: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[str] = None

class ItemCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    code: Optional[str] = Field(None, min_length=2, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[str] = None

class ItemCategoryResponse(BaseModel):
    id: str
    tenant_id: str
    parent_id: Optional[str] = None
    name: str
    code: str
    description: Optional[str] = None
    item_count: Optional[int] = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# --- Item Variants ---
class ItemVariantCreate(BaseModel):
    variant_sku: str = Field(..., min_length=2, max_length=100)
    variant_name: str = Field(..., min_length=1, max_length=255)
    attributes: Dict[str, Any] = {}
    cost_price: Decimal = Decimal("0.0")
    selling_price: Decimal = Decimal("0.0")
    barcodes: List[BarcodeCreate] = []

class ItemVariantUpdate(BaseModel):
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    cost_price: Optional[Decimal] = None
    selling_price: Optional[Decimal] = None

class ItemVariantResponse(BaseModel):
    id: str
    item_id: str
    variant_sku: str
    variant_name: str
    attributes: Dict[str, Any] = {}
    cost_price: float
    selling_price: float
    barcodes: List[BarcodeResponse] = []
    current_stock: Optional[float] = 0.0
    allocated_stock: Optional[float] = 0.0
    available_stock: Optional[float] = 0.0

    model_config = ConfigDict(from_attributes=True)

# --- Bin Stock Detail ---
class VariantBinStock(BaseModel):
    warehouse_id: str
    warehouse_name: str
    warehouse_code: str
    location_bin_id: str
    bin_code: str
    batch_number: Optional[str] = None
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float

# --- Items ---
class ItemCreate(BaseModel):
    category_id: Optional[str] = None
    sku: str = Field(..., min_length=2, max_length=100)
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    base_uom: str = "PCS"
    valuation_method: str = "FIFO" # FIFO, WEIGHTED_AVERAGE, STANDARD_COST
    reorder_point: Decimal = Decimal("10.0")
    reorder_quantity: Decimal = Decimal("50.0")
    is_batch_tracked: bool = False
    is_serial_tracked: bool = False
    variants: List[ItemVariantCreate] = []

class ItemUpdate(BaseModel):
    category_id: Optional[str] = None
    sku: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    base_uom: Optional[str] = None
    valuation_method: Optional[str] = None
    reorder_point: Optional[Decimal] = None
    reorder_quantity: Optional[Decimal] = None
    is_batch_tracked: Optional[bool] = None
    is_serial_tracked: Optional[bool] = None
    is_active: Optional[bool] = None

class ItemResponse(BaseModel):
    id: str
    tenant_id: str
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    sku: str
    name: str
    description: Optional[str] = None
    base_uom: str
    valuation_method: str
    reorder_point: float
    reorder_quantity: float
    is_batch_tracked: bool
    is_serial_tracked: bool
    is_active: bool
    variants: List[ItemVariantResponse] = []
    total_stock: Optional[float] = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ItemDetailResponse(ItemResponse):
    bin_stock_breakdown: List[VariantBinStock] = []

# --- Barcode Lookup ---
class BarcodeLookupResponse(BaseModel):
    found: bool
    barcode_value: str
    item_id: Optional[str] = None
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    variant_id: Optional[str] = None
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    cost_price: Optional[float] = None
    selling_price: Optional[float] = None
    current_stock: Optional[float] = None
