from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class ReplenishmentConfigCreate(BaseModel):
    item_variant_id: str
    warehouse_id: Optional[str] = None
    reorder_method: Optional[str] = "DYNAMIC_ROP"
    min_quantity: Optional[Decimal] = None
    max_quantity: Optional[Decimal] = None
    safety_stock_days: Optional[int] = 7
    target_coverage_days: Optional[int] = 30
    fixed_safety_stock: Optional[Decimal] = None
    is_active: Optional[bool] = True

class ReplenishmentConfigResponse(BaseModel):
    id: str
    tenant_id: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    warehouse_id: Optional[str] = None
    warehouse_name: Optional[str] = None
    reorder_method: str
    min_quantity: Optional[float] = None
    max_quantity: Optional[float] = None
    safety_stock_days: int
    target_coverage_days: int
    fixed_safety_stock: Optional[float] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ReplenishmentRecommendationItemResponse(BaseModel):
    id: str
    run_id: str
    warehouse_id: str
    warehouse_name: Optional[str] = None
    item_variant_id: str
    variant_sku: Optional[str] = None
    item_name: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float
    quantity_incoming: float
    quantity_mfg_planned: float
    net_inventory_position: float
    
    average_daily_usage: float
    lead_time_days: int
    safety_stock: float
    reorder_point: float
    target_maximum_stock: float
    minimum_order_quantity: float
    pack_size: float
    
    suggested_reorder_quantity: float
    estimated_unit_cost: float
    estimated_total_cost: float
    urgency_status: str
    suggested_order_date: datetime
    
    action_status: str
    purchase_order_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ReplenishmentRunResponse(BaseModel):
    id: str
    tenant_id: str
    run_number: str
    warehouse_id: Optional[str] = None
    warehouse_name: Optional[str] = None
    triggered_by_user_id: Optional[str] = None
    total_skus_evaluated: int
    total_recommendations: int
    total_estimated_spend: float
    status: str
    created_at: datetime
    items: List[ReplenishmentRecommendationItemResponse] = []

    model_config = ConfigDict(from_attributes=True)

class GenerateDraftPOsRequest(BaseModel):
    recommendation_item_ids: List[str]

class GenerateDraftPOResultItem(BaseModel):
    purchase_order_id: str
    purchase_order_number: str
    supplier_id: str
    supplier_name: str
    warehouse_id: str
    total_lines: int
    total_amount: float
    status: str

class GenerateDraftPOsResponse(BaseModel):
    generated_orders_count: int
    purchase_orders: List[GenerateDraftPOResultItem]
