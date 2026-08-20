from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# SUPPLIER SCORECARD SCHEMAS (PHASE 35)
# ============================================================================

class SupplierScorecardGenerateRequest(BaseModel):
    supplier_id: str
    period_code: str = "ALL_TIME" # e.g. 2026-Q1, 2026-01, ALL_TIME

class SupplierScorecardResponse(BaseModel):
    id: str
    tenant_id: str
    supplier_id: str
    period_code: str
    total_pos_count: int
    on_time_deliveries_count: int
    otd_percentage: Decimal
    total_received_units: Decimal
    rejected_units_count: Decimal
    quality_acceptance_percentage: Decimal
    price_variance_amount: Decimal
    price_compliance_percentage: Decimal
    overall_vendor_score: Decimal
    tier_grade: str
    evaluated_at: datetime
    notes: Optional[str] = None
    created_at: datetime
