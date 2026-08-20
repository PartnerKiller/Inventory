from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# MAINTENANCE SCHEDULE SCHEMAS
# ============================================================================

class MaintenanceScheduleCreate(BaseModel):
    schedule_name: str
    asset_id: Optional[str] = None
    work_center_id: Optional[str] = None
    schedule_type: str = "CALENDAR_INTERVAL"
    frequency_days: int = 30

class MaintenanceScheduleResponse(BaseModel):
    id: str
    tenant_id: str
    schedule_name: str
    asset_id: Optional[str] = None
    work_center_id: Optional[str] = None
    schedule_type: str
    frequency_days: int
    last_performed_at: Optional[datetime] = None
    next_due_at: datetime
    is_active: bool
    created_at: datetime

# ============================================================================
# MAINTENANCE WORK ORDER & SPARE PART SCHEMAS
# ============================================================================

class MWOSparePartCreate(BaseModel):
    item_variant_id: str
    warehouse_id: str
    location_bin_id: str
    quantity_required: Decimal
    unit_cost: Decimal

class MWOSparePartResponse(BaseModel):
    id: str
    mwo_id: str
    item_variant_id: str
    warehouse_id: str
    location_bin_id: str
    quantity_required: Decimal
    quantity_consumed: Decimal
    unit_cost: Decimal
    total_cost: Decimal

class MaintenanceWorkOrderCreate(BaseModel):
    schedule_id: Optional[str] = None
    asset_id: Optional[str] = None
    work_center_id: Optional[str] = None
    assigned_technician_id: Optional[str] = None
    priority: str = "MEDIUM" # CRITICAL, HIGH, MEDIUM, LOW
    expenditure_type: str = "REVENUE_EXPENSE" # REVENUE_EXPENSE, CAPITAL_IMPROVEMENT
    useful_life_extension_months: int = 0
    scheduled_start_date: Optional[datetime] = None
    notes: Optional[str] = None
    spare_parts: Optional[List[MWOSparePartCreate]] = None

class MaintenanceWorkOrderComplete(BaseModel):
    actual_completion_date: Optional[datetime] = None
    downtime_hours: Decimal = Decimal("0.0")
    labor_hours: Decimal = Decimal("0.0")
    notes: Optional[str] = None

class MaintenanceWorkOrderResponse(BaseModel):
    id: str
    tenant_id: str
    mwo_number: str
    schedule_id: Optional[str] = None
    asset_id: Optional[str] = None
    work_center_id: Optional[str] = None
    assigned_technician_id: Optional[str] = None
    priority: str
    status: str
    expenditure_type: str
    useful_life_extension_months: int
    scheduled_start_date: Optional[datetime] = None
    actual_completion_date: Optional[datetime] = None
    downtime_hours: Decimal
    labor_hours: Decimal
    journal_voucher_id: Optional[str] = None
    notes: Optional[str] = None
    spare_parts: List[MWOSparePartResponse] = []
    created_at: datetime
