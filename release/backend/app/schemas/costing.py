from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from decimal import Decimal

class CostLayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    warehouse_id: str
    warehouse_name: Optional[str] = None
    warehouse_code: Optional[str] = None
    item_variant_id: str
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    layer_number: str
    original_quantity: float
    remaining_quantity: float
    unit_cost: float
    total_cost: float
    status: str
    layer_timestamp: datetime
    notes: Optional[str] = None

class CostLayerConsumptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cost_layer_id: str
    cost_transaction_id: str
    quantity_consumed: float
    unit_cost: float
    total_cost: float
    consumed_at: datetime
    layer_number: Optional[str] = None

class ItemCostProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    warehouse_id: str
    warehouse_name: Optional[str] = None
    warehouse_code: Optional[str] = None
    item_variant_id: str
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    costing_method: str
    current_quantity: float
    current_total_value: float
    moving_average_cost: float
    standard_cost: float
    last_cost_recalculated_at: datetime

class CostTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    cost_transaction_number: str
    transaction_type: str
    stock_transaction_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    warehouse_name: Optional[str] = None
    item_variant_id: Optional[str] = None
    variant_sku: Optional[str] = None
    quantity: float
    unit_cost: float
    total_cost_impact: float
    costing_method: str
    posted_at: datetime
    notes: Optional[str] = None
    consumptions: List[CostLayerConsumptionResponse] = []

class COGSRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    sales_order_id: str
    sales_order_number: Optional[str] = None
    shipment_id: str
    shipment_number: Optional[str] = None
    cost_transaction_id: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    item_name: Optional[str] = None
    quantity_shipped: float
    unit_cogs: float
    total_cogs_amount: float
    recognized_at: datetime

class ValuationProductBreakdown(BaseModel):
    item_id: str
    item_sku: str
    item_name: str
    variant_id: str
    variant_sku: str
    variant_name: str
    costing_method: str
    total_quantity: float
    unit_cost: float
    total_valuation: float
    active_layer_count: int = 0

class ValuationWarehouseBreakdown(BaseModel):
    warehouse_id: str
    warehouse_code: str
    warehouse_name: str
    total_quantity: float
    total_valuation: float
    item_count: int

class OperationalValuationReportResponse(BaseModel):
    report_title: str = "Operational Inventory Valuation"
    disclaimer: str = "Operational estimate based on configured inventory costing method. Not statutory financial statement."
    currency: str = "USD"
    total_valuation: float
    total_units: float
    valuation_by_method: Dict[str, float] = {}
    warehouse_breakdown: List[ValuationWarehouseBreakdown] = []
    product_breakdown: List[ValuationProductBreakdown] = []
    generated_at: datetime

class CostingMethodUpdateRequest(BaseModel):
    costing_method: str = Field(..., pattern="^(FIFO|WEIGHTED_AVERAGE|STANDARD_COST)$")

class OpeningCostLayerMigrationRequest(BaseModel):
    warehouse_id: Optional[str] = None
    override_zero_cost: bool = False
    default_cost_if_missing: Optional[Decimal] = Decimal("0.0")

class MigrationStatusResponse(BaseModel):
    status: str
    migrated_layers_count: int
    total_quantity_migrated: float
    total_valuation_migrated: float
    message: str
