from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# FISCAL YEAR SCHEMAS
# ============================================================================

class FiscalYearCreate(BaseModel):
    fiscal_year_code: str # e.g. FY2026
    start_date: date # e.g. 2026-01-01
    end_date: date # e.g. 2026-12-31
    notes: Optional[str] = None

class AccountingPeriodResponse(BaseModel):
    id: str
    tenant_id: str
    fiscal_year_id: str
    period_code: str
    period_number: int
    start_date: date
    end_date: date
    status: str # FUTURE, OPEN, SOFT_CLOSED, CLOSED, FINALIZED
    closed_at: Optional[datetime] = None
    closed_by_user_id: Optional[str] = None
    closing_notes: Optional[str] = None
    created_at: datetime

class FiscalYearResponse(BaseModel):
    id: str
    tenant_id: str
    fiscal_year_code: str
    start_date: date
    end_date: date
    status: str # OPEN, CLOSED, FINALIZED
    notes: Optional[str] = None
    periods: List[AccountingPeriodResponse]
    created_at: datetime

# ============================================================================
# PERIOD CLOSING / STATE TRANSITION SCHEMAS
# ============================================================================

class PeriodStatusUpdateRequest(BaseModel):
    status: str # OPEN, SOFT_CLOSED, CLOSED, FINALIZED
    notes: Optional[str] = None

class PeriodChecklistItemResponse(BaseModel):
    id: str
    checkpoint_name: str
    is_completed: bool
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None

# ============================================================================
# YEAR-END CLOSING SCHEMAS
# ============================================================================

class YearEndClosingRequest(BaseModel):
    fiscal_year_id: str
    closing_date: date
    notes: Optional[str] = None

class YearEndClosingResponse(BaseModel):
    fiscal_year_id: str
    fiscal_year_code: str
    closing_voucher_id: str
    closing_voucher_number: str
    total_revenue_cleared: Decimal
    total_expense_cleared: Decimal
    net_retained_earnings_transferred: Decimal
    status: str # FINALIZED
    closed_at: datetime
