from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal

class BOMLineItemCreate(BaseModel):
    component_variant_id: str
    quantity_required: Decimal = Field(..., gt=0)
    scrap_percentage: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0, le=100)
    position: Optional[int] = 1
    notes: Optional[str] = None

class BOMLineItemResponse(BaseModel):
    id: str
    bom_id: str
    component_variant_id: str
    component_sku: Optional[str] = None
    component_name: Optional[str] = None
    quantity_required: float
    scrap_percentage: float
    position: int
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class BillOfMaterialsCreate(BaseModel):
    name: str = Field(..., min_length=1)
    item_variant_id: str
    version: Optional[str] = "1.0"
    yield_quantity: Optional[Decimal] = Field(default=Decimal("1.0"), gt=0)
    labor_cost_per_unit: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0)
    overhead_cost_per_unit: Optional[Decimal] = Field(default=Decimal("0.0"), ge=0)
    notes: Optional[str] = None
    lines: List[BOMLineItemCreate]

class BillOfMaterialsResponse(BaseModel):
    id: str
    tenant_id: str
    bom_number: str
    name: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    version: str
    status: str
    yield_quantity: float
    labor_cost_per_unit: float
    overhead_cost_per_unit: float
    notes: Optional[str] = None
    lines: List[BOMLineItemResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class WorkOrderCreate(BaseModel):
    bom_id: str
    warehouse_id: str
    staging_bin_id: str
    destination_bin_id: str
    quantity_to_produce: Decimal = Field(..., gt=0)
    planned_start_date: Optional[datetime] = None
    notes: Optional[str] = None

class WorkOrderComponentResponse(BaseModel):
    id: str
    work_order_id: str
    component_variant_id: str
    component_sku: Optional[str] = None
    component_name: Optional[str] = None
    quantity_required: float
    quantity_reserved: float
    quantity_consumed: float
    unit_cost: float
    total_cost: float

    model_config = ConfigDict(from_attributes=True)

class WorkOrderResponse(BaseModel):
    id: str
    tenant_id: str
    work_order_number: str
    bom_id: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    warehouse_id: str
    warehouse_name: Optional[str] = None
    staging_bin_id: str
    staging_bin_code: Optional[str] = None
    destination_bin_id: str
    destination_bin_code: Optional[str] = None
    status: str
    quantity_to_produce: float
    quantity_produced: float
    total_component_cost: float
    total_labor_cost: float
    total_overhead_cost: float
    total_production_cost: float
    unit_cost: float
    planned_start_date: datetime
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    components: List[WorkOrderComponentResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DisassemblyOrderCreate(BaseModel):
    item_variant_id: str
    warehouse_id: str
    source_bin_id: str
    destination_bin_id: str
    quantity_disassembled: Decimal = Field(..., gt=0)
    notes: Optional[str] = None

class DisassemblyOrderResponse(BaseModel):
    id: str
    tenant_id: str
    disassembly_number: str
    item_variant_id: str
    variant_sku: Optional[str] = None
    warehouse_id: str
    source_bin_id: str
    destination_bin_id: str
    quantity_disassembled: float
    total_cost_recovered: float
    status: str
    disassembled_at: datetime
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
