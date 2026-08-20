from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# COST CENTER SCHEMAS
# ============================================================================

class CostCenterCreate(BaseModel):
    cost_center_code: str # e.g. CC-ENG-100
    cost_center_name: str
    parent_cost_center_id: Optional[str] = None
    department_head_user_id: Optional[str] = None
    is_profit_center: bool = False
    description: Optional[str] = None

class CostCenterResponse(BaseModel):
    id: str
    tenant_id: str
    cost_center_code: str
    cost_center_name: str
    parent_cost_center_id: Optional[str] = None
    department_head_user_id: Optional[str] = None
    is_profit_center: bool
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

# ============================================================================
# BUDGET LINE & BUDGET SCHEMAS
# ============================================================================

class BudgetLineCreate(BaseModel):
    period_code: str # e.g. 2026-01
    gl_account_id: str
    allocated_amount: Decimal

class BudgetLineResponse(BaseModel):
    id: str
    budget_id: str
    period_code: str
    gl_account_id: str
    allocated_amount: Decimal
    committed_amount: Decimal
    actual_amount: Decimal
    available_amount: Decimal

class DepartmentalBudgetCreate(BaseModel):
    budget_code: str # e.g. BUD-2026-ENG
    cost_center_id: str
    fiscal_year_id: str
    enforce_hard_cap: bool = True
    warning_threshold_percentage: Decimal = Decimal("80.0")
    notes: Optional[str] = None
    lines: List[BudgetLineCreate] = []

class DepartmentalBudgetResponse(BaseModel):
    id: str
    tenant_id: str
    budget_code: str
    cost_center_id: str
    fiscal_year_id: str
    total_allocated_budget: Decimal
    status: str
    enforce_hard_cap: bool
    warning_threshold_percentage: Decimal
    notes: Optional[str] = None
    budget_lines: List[BudgetLineResponse] = []
    created_at: datetime

# ============================================================================
# COMMITMENT & VARIANCE SCHEMAS
# ============================================================================

class BudgetCommitmentRequest(BaseModel):
    cost_center_id: str
    gl_account_id: str
    period_code: str
    amount: Decimal
    source_document_type: str # PURCHASE_ORDER
    source_document_id: str

class BudgetCommitmentResponse(BaseModel):
    id: str
    budget_line_id: str
    source_document_type: str
    source_document_id: str
    committed_amount: Decimal
    status: str
    warning_triggered: bool = False
    warning_message: Optional[str] = None

class CostCenterVarianceReport(BaseModel):
    cost_center_id: str
    cost_center_code: str
    cost_center_name: str
    period_code: Optional[str] = None
    total_allocated: Decimal
    total_committed: Decimal
    total_actual: Decimal
    total_variance: Decimal
    utilization_percentage: Decimal
