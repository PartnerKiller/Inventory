from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class PriceListTierCreate(BaseModel):
    min_quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    discount_pct: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)

class PriceListTierResponse(BaseModel):
    id: str
    price_list_item_id: str
    min_quantity: float
    unit_price: float
    discount_pct: float

    model_config = ConfigDict(from_attributes=True)

class PriceListItemCreate(BaseModel):
    item_variant_id: str
    base_price: Decimal = Field(..., ge=0)
    min_price: Optional[Decimal] = Field(default=None, ge=0)
    tiers: Optional[List[PriceListTierCreate]] = None

class PriceListItemResponse(BaseModel):
    id: str
    price_list_id: str
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_sku: str
    variant_name: Optional[str] = None
    base_price: float
    min_price: Optional[float] = None
    tiers: List[PriceListTierResponse] = []

    model_config = ConfigDict(from_attributes=True)

class PriceListCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(default="USD", max_length=10)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_active: bool = True
    is_default: bool = False
    notes: Optional[str] = None

class PriceListUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    notes: Optional[str] = None

class PriceListResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    currency: str
    valid_from: datetime
    valid_to: Optional[datetime] = None
    is_active: bool
    is_default: bool
    notes: Optional[str] = None
    items_count: Optional[int] = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CustomerPriceListAssignRequest(BaseModel):
    customer_id: str
    price_list_id: str
    priority: int = 1

class PriceResolutionRequest(BaseModel):
    customer_id: Optional[str] = None
    item_variant_id: str
    quantity: Decimal = Field(default=Decimal("1.0"), gt=0)

class PriceResolutionResponse(BaseModel):
    item_variant_id: str
    unit_price: float
    discount_pct: float
    effective_unit_price: float
    matched_rule: str # "CUSTOMER_PRICE_LIST_TIER", "CUSTOMER_PRICE_LIST", "DEFAULT_PRICE_LIST_TIER", "DEFAULT_PRICE_LIST", "VARIANT_BASE_PRICE"
    price_list_id: Optional[str] = None
    price_list_name: Optional[str] = None
    currency: str = "USD"
