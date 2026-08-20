from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# APPROVAL RULE SCHEMAS
# ============================================================================

class ApprovalRuleCreate(BaseModel):
    rule_name: str
    entity_type: str # PURCHASE_ORDER, VENDOR_INVOICE, JOURNAL_VOUCHER, BUDGET_OVERRUN, ASSET_DISPOSAL
    min_amount: Decimal = Decimal("0.0")
    max_amount: Optional[Decimal] = None
    cost_center_id: Optional[str] = None
    step_number: int = 1
    approver_role_id: Optional[str] = None
    approver_user_id: Optional[str] = None
    sla_hours: int = 24

class ApprovalRuleResponse(BaseModel):
    id: str
    tenant_id: str
    rule_name: str
    entity_type: str
    min_amount: Decimal
    max_amount: Optional[Decimal] = None
    cost_center_id: Optional[str] = None
    step_number: int
    approver_role_id: Optional[str] = None
    approver_user_id: Optional[str] = None
    sla_hours: int
    is_active: bool
    created_at: datetime

# ============================================================================
# APPROVAL REQUEST & STEP SCHEMAS
# ============================================================================

class ApprovalStepResponse(BaseModel):
    id: str
    request_id: str
    step_number: int
    approver_user_id: Optional[str] = None
    assigned_role_id: Optional[str] = None
    status: str # PENDING, APPROVED, REJECTED, DELEGATED, SKIPPED
    action_by_user_id: Optional[str] = None
    action_taken_at: Optional[datetime] = None
    comments: Optional[str] = None

class ApprovalRequestCreate(BaseModel):
    entity_type: str
    entity_id: str
    document_reference: str
    total_amount: Decimal
    cost_center_id: Optional[str] = None

class ApprovalRequestResponse(BaseModel):
    id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    document_reference: str
    requested_by_user_id: Optional[str] = None
    total_amount: Decimal
    cost_center_id: Optional[str] = None
    status: str # PENDING, IN_REVIEW, APPROVED, REJECTED, ESCALATED, CANCELLED
    current_step_number: int
    total_steps: int
    steps: List[ApprovalStepResponse] = []
    created_at: datetime

class ApprovalActionRequest(BaseModel):
    action: str # APPROVE, REJECT
    comments: Optional[str] = None

# ============================================================================
# APPROVAL DELEGATION SCHEMAS
# ============================================================================

class ApprovalDelegationCreate(BaseModel):
    delegate_user_id: str
    start_date: date
    end_date: date
    reason: Optional[str] = None

class ApprovalDelegationResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    delegate_user_id: str
    start_date: date
    end_date: date
    reason: Optional[str] = None
    is_active: bool
    created_at: datetime
