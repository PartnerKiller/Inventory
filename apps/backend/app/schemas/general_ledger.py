from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# CHART OF ACCOUNTS SCHEMAS
# ============================================================================

class GLAccountCreate(BaseModel):
    account_code: str # e.g. 1000, 1100, 1200, 2000, 3000, 4000, 5000, 6000
    account_name: str
    account_class: str # ASSET, LIABILITY, EQUITY, REVENUE, COGS, EXPENSE
    account_type: str # CURRENT_ASSET, INVENTORY_ASSET, ACCOUNTS_RECEIVABLE, BANK_AND_CASH, CURRENT_LIABILITY, ACCOUNTS_PAYABLE, RETAINED_EARNINGS, OPERATING_REVENUE, DIRECT_COGS, OPERATING_EXPENSE
    currency: str = "USD"
    normal_balance: str # DEBIT, CREDIT
    parent_account_id: Optional[str] = None
    description: Optional[str] = None

class GLAccountResponse(BaseModel):
    id: str
    account_code: str
    account_name: str
    account_class: str
    account_type: str
    currency: str
    normal_balance: str
    parent_account_id: Optional[str] = None
    is_active: bool
    is_system: bool
    description: Optional[str] = None

# ============================================================================
# JOURNAL VOUCHER SCHEMAS
# ============================================================================

class JournalEntryLineCreate(BaseModel):
    account_id: str
    debit_amount: Decimal = Decimal("0.0")
    credit_amount: Decimal = Decimal("0.0")
    currency: str = "USD"
    cost_center_id: Optional[str] = None
    memo: Optional[str] = None

class JournalEntryLineResponse(BaseModel):
    id: str
    account_id: str
    account_code: str
    account_name: str
    debit_amount: float
    credit_amount: float
    currency: str
    cost_center_id: Optional[str] = None
    memo: Optional[str] = None

class JournalVoucherCreate(BaseModel):
    voucher_date: Optional[datetime] = None
    source_document_type: str = "MANUAL" # GRN, SALES_DISPATCH, CUSTOMER_INVOICE, CUSTOMER_PAYMENT, VENDOR_INVOICE, VENDOR_PAYMENT, WORK_ORDER, INVENTORY_ADJUSTMENT, MANUAL
    source_document_id: Optional[str] = None
    notes: Optional[str] = None
    lines: List[JournalEntryLineCreate]

class JournalVoucherResponse(BaseModel):
    id: str
    voucher_number: str
    voucher_date: datetime
    source_document_type: str
    source_document_id: Optional[str] = None
    status: str
    posted_at: datetime
    notes: Optional[str] = None
    total_debit: float
    total_credit: float
    lines: List[JournalEntryLineResponse] = []

# ============================================================================
# FINANCIAL STATEMENTS SCHEMAS
# ============================================================================

class TrialBalanceRow(BaseModel):
    account_id: str
    account_code: str
    account_name: str
    account_class: str
    normal_balance: str
    total_debit: float
    total_credit: float
    net_debit: float
    net_credit: float

class TrialBalanceResponse(BaseModel):
    as_of_date: datetime
    currency: str
    total_debits: float
    total_credits: float
    is_balanced: bool
    accounts: List[TrialBalanceRow]

class IncomeStatementSection(BaseModel):
    account_code: str
    account_name: str
    amount: float

class IncomeStatementResponse(BaseModel):
    start_date: datetime
    end_date: datetime
    currency: str
    revenue_items: List[IncomeStatementSection]
    total_revenue: float
    cogs_items: List[IncomeStatementSection]
    total_cogs: float
    gross_margin: float
    gross_margin_pct: float
    expense_items: List[IncomeStatementSection]
    total_expenses: float
    net_income: float

class BalanceSheetSection(BaseModel):
    account_code: str
    account_name: str
    account_type: str
    amount: float

class BalanceSheetResponse(BaseModel):
    as_of_date: datetime
    currency: str
    assets: List[BalanceSheetSection]
    total_assets: float
    liabilities: List[BalanceSheetSection]
    total_liabilities: float
    equity: List[BalanceSheetSection]
    retained_earnings: float
    total_equity: float
    total_liabilities_and_equity: float
    is_balanced: bool
