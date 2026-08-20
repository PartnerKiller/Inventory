from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# FORECAST PROFILE SCHEMAS
# ============================================================================

class DemandForecastProfileCreate(BaseModel):
    item_id: str
    warehouse_id: str
    model_type: str = "HOLT_WINTERS" # HOLT_WINTERS, MOVING_AVERAGE, LINEAR_REGRESSION
    seasonality_periods: int = 12
    alpha: Decimal = Decimal("0.2")
    beta: Decimal = Decimal("0.1")
    gamma: Decimal = Decimal("0.3")
    service_level_target: Decimal = Decimal("0.95")
    lead_time_days: Decimal = Decimal("7.0")
    lead_time_std_dev: Decimal = Decimal("1.5")

class DemandForecastProfileResponse(BaseModel):
    id: str
    tenant_id: str
    item_id: str
    warehouse_id: str
    model_type: str
    seasonality_periods: int
    alpha: Decimal
    beta: Decimal
    gamma: Decimal
    service_level_target: Decimal
    lead_time_days: Decimal
    lead_time_std_dev: Decimal
    is_active: bool
    created_at: datetime

# ============================================================================
# FORECAST CALCULATION & ENTRIES
# ============================================================================

class ForecastCalculationRequest(BaseModel):
    profile_id: str
    historical_demand_series: List[Decimal] # Ordered historical observations
    horizon_periods: int = 3 # Forecast periods ahead

class ForecastPeriodEntryResponse(BaseModel):
    id: str
    profile_id: str
    period_date: date
    historical_actual_demand: Decimal
    forecasted_demand: Decimal
    calculated_safety_stock: Decimal
    calculated_rop: Decimal

class ForecastCalculationResponse(BaseModel):
    profile_id: str
    model_type: str
    fitted_values: List[Decimal]
    forecast_values: List[Decimal]
    safety_stock: Decimal
    reorder_point: Decimal
    mean_absolute_percentage_error: Decimal

# ============================================================================
# REPLENISHMENT PROPOSALS
# ============================================================================

class ReplenishmentProposalResponse(BaseModel):
    id: str
    tenant_id: str
    item_id: str
    warehouse_id: str
    suggested_order_qty: Decimal
    current_stock_on_hand: Decimal
    in_transit_qty: Decimal
    calculated_rop: Decimal
    calculated_safety_stock: Decimal
    status: str
    purchase_order_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

class ConvertProposalToPORequest(BaseModel):
    supplier_id: str
    unit_price: Decimal
