from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# ============================================================================
# WORK CENTER SCHEMAS
# ============================================================================

class WorkCenterCreate(BaseModel):
    code: str
    name: str
    warehouse_id: str
    department: Optional[str] = None
    hourly_labor_rate: Decimal = Decimal("0.0")
    hourly_machine_rate: Decimal = Decimal("0.0")
    daily_capacity_hours: Decimal = Decimal("16.0")
    efficiency_factor: Decimal = Decimal("1.0")
    is_active: bool = True

class WorkCenterResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    warehouse_id: str
    department: Optional[str] = None
    hourly_labor_rate: Decimal
    hourly_machine_rate: Decimal
    daily_capacity_hours: Decimal
    efficiency_factor: Decimal
    is_active: bool
    created_at: datetime

# ============================================================================
# ROUTING SCHEMAS
# ============================================================================

class RoutingOperationCreate(BaseModel):
    sequence_number: int
    operation_name: str
    work_center_id: str
    setup_time_minutes: Decimal = Decimal("0.0")
    run_time_minutes_per_unit: Decimal = Decimal("1.0")
    queue_time_minutes: Decimal = Decimal("0.0")
    move_time_minutes: Decimal = Decimal("0.0")
    is_quality_gate: bool = False

class RoutingCreate(BaseModel):
    name: str
    item_variant_id: str
    version: str = "1.0"
    status: str = "ACTIVE"
    operations: List[RoutingOperationCreate] = []

class RoutingOperationResponse(BaseModel):
    id: str
    sequence_number: int
    operation_name: str
    work_center_id: str
    setup_time_minutes: Decimal
    run_time_minutes_per_unit: Decimal
    is_quality_gate: bool

class RoutingResponse(BaseModel):
    id: str
    tenant_id: str
    routing_number: str
    name: str
    item_variant_id: str
    version: str
    status: str
    operations: List[RoutingOperationResponse]
    created_at: datetime

# ============================================================================
# SHOP-FLOOR EXECUTION SCHEMAS
# ============================================================================

class OperationClaimRequest(BaseModel):
    operation_id: str

class OperationCompleteRequest(BaseModel):
    operation_id: str
    completed_quantity: Decimal
    scrap_quantity: Decimal = Decimal("0.0")
    actual_setup_minutes: Decimal = Decimal("0.0")
    actual_run_minutes: Decimal = Decimal("0.0")

class ProductionQualityInspectionCreate(BaseModel):
    work_order_id: str
    operation_id: Optional[str] = None
    inspection_type: str = "IN_PROCESS" # IN_PROCESS, FINAL
    inspected_quantity: Decimal
    passed_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0.0")
    disposition: str = "PASS" # PASS, HOLD, REJECT, REWORK
    quarantine_bin_id: Optional[str] = None
    notes: Optional[str] = None

class ProductionQualityInspectionResponse(BaseModel):
    id: str
    tenant_id: str
    work_order_id: str
    inspection_type: str
    inspected_quantity: Decimal
    passed_quantity: Decimal
    rejected_quantity: Decimal
    disposition: str
    quarantine_bin_id: Optional[str] = None
    created_at: datetime

# ============================================================================
# MRP SCHEMAS
# ============================================================================

class MRPExplosionRequest(BaseModel):
    item_variant_id: str
    quantity: Decimal
    warehouse_id: str

class MRPRequirementItem(BaseModel):
    component_variant_id: str
    sku: str
    gross_quantity: Decimal
    on_hand_quantity: Decimal
    allocated_quantity: Decimal
    net_quantity_needed: Decimal
    procurement_type: str # BUY, MAKE

class MRPExplosionResponse(BaseModel):
    item_variant_id: str
    planned_quantity: Decimal
    requirements: List[MRPRequirementItem]
