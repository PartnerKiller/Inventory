from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# SUBLEDGER RECONCILIATION SCHEMAS (PHASE 36)
# ============================================================================

class SubledgerReconciliationItem(BaseModel):
    subledger_name: str # INVENTORY, ACCOUNTS_RECEIVABLE, ACCOUNTS_PAYABLE, FIXED_ASSETS, INTERCOMPANY
    subledger_balance: Decimal
    gl_account_code: str
    gl_account_name: str
    gl_balance: Decimal
    variance_amount: Decimal
    is_in_balance: bool # variance == 0.00
    notes: Optional[str] = None

class FullReconciliationReport(BaseModel):
    tenant_id: str
    reconciled_at: datetime
    is_fully_reconciled: bool
    total_variance_count: int
    items: List[SubledgerReconciliationItem]
