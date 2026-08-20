from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# PRICE RULE SCHEMAS
# ============================================================================

class PriceRuleCreate(BaseModel):
    rule_name: str
    customer_id: Optional[str] = None
    customer_group: Optional[str] = None # WHOLESALE, DISTRIBUTOR, RETAIL
    item_id: str
    min_quantity: Decimal = Decimal("1.0")
    max_quantity: Optional[Decimal] = None
    discount_type: str = "PERCENTAGE" # PERCENTAGE, FIXED_PRICE, AMOUNT_OFF
    discount_value: Decimal = Decimal("0.0")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    priority: int = 10

class PriceRuleResponse(BaseModel):
    id: str
    tenant_id: str
    rule_name: str
    customer_id: Optional[str] = None
    customer_group: Optional[str] = None
    item_id: str
    min_quantity: Decimal
    max_quantity: Optional[Decimal] = None
    discount_type: str
    discount_value: Decimal
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    priority: int
    is_active: bool
    created_at: datetime

# ============================================================================
# QUOTE & PRICE RESOLUTION SCHEMAS
# ============================================================================

class PriceQuoteRequest(BaseModel):
    item_id: str
    quantity: Decimal
    base_price: Decimal
    customer_id: Optional[str] = None
    customer_group: Optional[str] = None
    order_date: Optional[date] = None

class PriceQuoteResponse(BaseModel):
    item_id: str
    quantity: Decimal
    base_unit_price: Decimal
    resolved_unit_price: Decimal
    total_line_amount: Decimal
    discount_applied: Decimal
    discount_percentage: Decimal
    applied_rule_id: Optional[str] = None
    rule_name: Optional[str] = None

# ============================================================================
# REBATE AGREEMENT SCHEMAS
# ============================================================================

class RebateAgreementCreate(BaseModel):
    agreement_code: str
    customer_id: str
    start_date: date
    end_date: date
    target_spend_threshold: Decimal
    rebate_percentage: Decimal
    notes: Optional[str] = None

class RebateAgreementResponse(BaseModel):
    id: str
    tenant_id: str
    agreement_code: str
    customer_id: str
    start_date: date
    end_date: date
    target_spend_threshold: Decimal
    rebate_percentage: Decimal
    status: str
    settled_amount: Decimal
    credit_note_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

class SettleRebateRequest(BaseModel):
    actual_qualifying_spend: Optional[Decimal] = None
