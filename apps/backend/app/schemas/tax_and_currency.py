from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# CURRENCY & EXCHANGE RATE SCHEMAS
# ============================================================================

class ExchangeRateCreate(BaseModel):
    from_currency: str # e.g. EUR, GBP
    to_currency: str = "USD"
    rate: Decimal # e.g. 1.0850
    effective_date: Optional[datetime] = None

class ExchangeRateResponse(BaseModel):
    id: str
    tenant_id: str
    from_currency: str
    to_currency: str
    rate: Decimal
    effective_date: datetime
    is_active: bool
    created_at: datetime

class FXRevaluationRequest(BaseModel):
    revaluation_date: Optional[datetime] = None
    notes: Optional[str] = None

class FXRevaluationResponse(BaseModel):
    revaluation_date: datetime
    closing_voucher_id: Optional[str] = None
    total_unrealized_gain: Decimal
    total_unrealized_loss: Decimal
    net_fx_adjustment: Decimal
    revalued_account_count: int

# ============================================================================
# TAX JURISDICTION, RATE & GROUP SCHEMAS
# ============================================================================

class TaxJurisdictionCreate(BaseModel):
    country_code: str # US, IN, GB, DE
    jurisdiction_code: str # US-CA, IN-MH, GB-VAT
    jurisdiction_name: str
    jurisdiction_type: str = "STATE"

class TaxRateCreate(BaseModel):
    jurisdiction_id: str
    tax_code: str # CGST-9, SGST-9, IGST-18, VAT-20
    tax_name: str
    rate_percentage: Decimal
    tax_type: str = "OUTPUT_TAX"
    is_compound: bool = False

class TaxRateResponse(BaseModel):
    id: str
    tenant_id: str
    jurisdiction_id: str
    tax_code: str
    tax_name: str
    rate_percentage: Decimal
    tax_type: str
    is_compound: bool
    is_active: bool
    created_at: datetime

class TaxJurisdictionResponse(BaseModel):
    id: str
    tenant_id: str
    country_code: str
    jurisdiction_code: str
    jurisdiction_name: str
    jurisdiction_type: str
    is_active: bool
    tax_rates: List[TaxRateResponse] = []
    created_at: datetime

class TaxGroupCreate(BaseModel):
    group_code: str # GST-18, VAT-STD
    group_name: str
    description: Optional[str] = None
    tax_rate_ids: List[str]

class TaxGroupResponse(BaseModel):
    id: str
    tenant_id: str
    group_code: str
    group_name: str
    description: Optional[str] = None
    is_active: bool
    tax_rates: List[TaxRateResponse] = []
    created_at: datetime

# ============================================================================
# TAX CALCULATION SCHEMAS
# ============================================================================

class TaxCalculationItemRequest(BaseModel):
    tax_group_id: Optional[str] = None
    tax_rate_id: Optional[str] = None
    taxable_amount: Decimal
    is_tax_inclusive: bool = False

class TaxBreakdownItem(BaseModel):
    tax_rate_id: str
    tax_code: str
    tax_name: str
    rate_percentage: Decimal
    tax_amount: Decimal

class TaxCalculationResponse(BaseModel):
    total_taxable_amount: Decimal
    total_tax_amount: Decimal
    gross_amount: Decimal
    breakdown: List[TaxBreakdownItem]

class TaxSettlementReportResponse(BaseModel):
    start_date: datetime
    end_date: datetime
    total_output_tax: Decimal # Account 2200
    total_input_tax_credit: Decimal # Account 1400
    net_tax_payable: Decimal # Output - Input
    settlement_voucher_id: Optional[str] = None
