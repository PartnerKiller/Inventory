from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# INTERCOMPANY PARTNER SCHEMAS
# ============================================================================

class IntercompanyPartnerCreate(BaseModel):
    partner_name: str
    seller_company_id: str
    buyer_company_id: str
    transfer_pricing_type: str = "COST_PLUS" # COST_PLUS, FIXED_PRICE, CATALOG
    markup_percentage: Decimal = Decimal("0.0") # e.g. 15.0
    ar_intercompany_account_id: Optional[str] = None
    ap_intercompany_account_id: Optional[str] = None

class IntercompanyPartnerResponse(BaseModel):
    id: str
    tenant_id: str
    partner_name: str
    seller_company_id: str
    buyer_company_id: str
    transfer_pricing_type: str
    markup_percentage: Decimal
    ar_intercompany_account_id: Optional[str] = None
    ap_intercompany_account_id: Optional[str] = None
    is_active: bool
    created_at: datetime

# ============================================================================
# MIRRORED ORDER PAIR SCHEMAS
# ============================================================================

class MirroredOrderCreate(BaseModel):
    partner_id: str
    seller_sales_order_id: str

class IntercompanyTransactionPairResponse(BaseModel):
    id: str
    tenant_id: str
    partner_id: str
    sales_order_id: str
    purchase_order_id: str
    sales_invoice_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    transfer_amount: Decimal
    status: str
    created_at: datetime

# ============================================================================
# CONSOLIDATION RUN SCHEMAS
# ============================================================================

class ConsolidationRunCreate(BaseModel):
    period_id: str
    notes: Optional[str] = None

class ConsolidationRunResponse(BaseModel):
    id: str
    tenant_id: str
    period_id: str
    run_date: datetime
    status: str
    elimination_voucher_id: Optional[str] = None
    total_eliminated_amount: Decimal
    notes: Optional[str] = None
    created_at: datetime

# ============================================================================
# UNREALIZED INTERCOMPANY PROFIT ELIMINATION SCHEMAS (PHASE 31)
# ============================================================================

class UnrealizedProfitEliminationCreate(BaseModel):
    period_id: str
    partner_id: str
    item_id: str
    on_hand_quantity: Decimal
    unit_markup: Decimal

class UnrealizedProfitEliminationResponse(BaseModel):
    id: str
    tenant_id: str
    period_id: str
    partner_id: str
    item_id: str
    on_hand_quantity: Decimal
    unit_markup: Decimal
    total_unrealized_profit: Decimal
    elimination_voucher_id: Optional[str] = None
    status: str
    created_at: datetime

# ============================================================================
# CONSOLIDATED FINANCIAL REPORTING SCHEMAS (PHASE 31)
# ============================================================================

class ConsolidatedTrialBalanceLine(BaseModel):
    account_code: str
    account_name: str
    account_class: str
    unconsolidated_debit: Decimal
    unconsolidated_credit: Decimal
    elimination_debit: Decimal
    elimination_credit: Decimal
    consolidated_net_balance: Decimal

class ConsolidatedTrialBalanceResponse(BaseModel):
    tenant_id: str
    period_id: str
    lines: List[ConsolidatedTrialBalanceLine]
    total_consolidated_debit: Decimal
    total_consolidated_credit: Decimal
    is_balanced: bool

class ConsolidatedFinancialStatementResponse(BaseModel):
    tenant_id: str
    period_id: str
    total_revenue: Decimal
    total_cogs: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    net_income: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
