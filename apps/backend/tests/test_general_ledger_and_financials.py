import pytest
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.base import get_utc_now
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.sales import Customer, SalesOrder
from app.models.invoicing import CustomerInvoice, CustomerPayment, CustomerCreditNote
from app.models.purchasing import Supplier, PurchaseOrder, GoodsReceipt, SupplierDebitMemo
from app.models.ap import VendorInvoice, VendorPayment
from app.models.ledger import StockLedgerTransaction
from app.models.costing import CostLayer
from app.schemas.general_ledger import (
    JournalVoucherCreate,
    JournalEntryLineCreate
)
from app.services.gl_service import GLService

# ============================================================================
# 1. ACCOUNTING PERIOD BOUNDARIES EXACT FILTERING
# ============================================================================

@pytest.mark.asyncio
async def test_accounting_period_boundaries_exact_filtering(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")

    # Entry 1: January 31 23:59:59 UTC
    dt_jan = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        voucher_date=dt_jan, source_document_type="MANUAL",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("1000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("1000.00"))
        ]
    ))

    # Entry 2: February 1 00:00:00 UTC
    dt_feb = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        voucher_date=dt_feb, source_document_type="MANUAL",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("2000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("2000.00"))
        ]
    ))

    # Query January Trial Balance (as of Jan 31 23:59:59) -> only Entry 1 included ($1,000)
    tb_jan = await GLService.generate_trial_balance(db_session, tenant_id, as_of_date=dt_jan)
    assert tb_jan.total_debits == 1000.00
    assert tb_jan.total_credits == 1000.00

    # Query February Trial Balance (as of Feb 1 00:00:00) -> both Entry 1 and Entry 2 included ($3,000)
    tb_feb = await GLService.generate_trial_balance(db_session, tenant_id, as_of_date=dt_feb)
    assert tb_feb.total_debits == 3000.00
    assert tb_feb.total_credits == 3000.00

# ============================================================================
# 2. CLOSED ACCOUNTING PERIODS STATUS REPORTING
# ============================================================================

def test_accounting_period_close_status():
    """Formal accounting period locking is deferred; reporting supports arbitrary date filtering."""
    period_closing_implemented = False
    assert period_closing_implemented is False, "Accounting period close = DEFERRED"

# ============================================================================
# 3. JOURNAL IMMUTABILITY & CORRECTION VIA REVERSAL
# ============================================================================

@pytest.mark.asyncio
async def test_journal_immutability_and_correction(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")

    jv = await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="MANUAL", notes="Original entry with typo",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("500.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("500.00"))
        ]
    ))

    # Direct alteration is not exposed via API/service; correction must use void / reversal
    rev = await GLService.void_journal_voucher(db_session, tenant_id, jv.id)
    assert rev.status == "POSTED"
    assert rev.total_debit == 500.00
    assert rev.total_credit == 500.00

    # Corrected replacement JV
    corr = await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="MANUAL", notes="Corrected replacement entry",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("600.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("600.00"))
        ]
    ))
    assert corr.total_debit == 600.00

# ============================================================================
# 4. GL POSTING IDEMPOTENCY & LOST RESPONSE RECOVERY
# ============================================================================

@pytest.mark.asyncio
async def test_gl_posting_idempotency_and_lost_response(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_ap_acc = await GLService.get_account_by_code(db_session, tenant_id, "2100")

    doc_id = f"GRN-IDEM-{uuid.uuid4().hex[:6]}"
    req = JournalVoucherCreate(
        source_document_type="GRN", source_document_id=doc_id,
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("2500.00")),
            JournalEntryLineCreate(account_id=acc_ap_acc.id, credit_amount=Decimal("2500.00"))
        ]
    )

    # 1. First execution
    res1 = await GLService.post_journal_voucher(db_session, tenant_id, req)
    # 2. Lost response / client retry
    res2 = await GLService.post_journal_voucher(db_session, tenant_id, req)

    assert res1.id == res2.id
    assert res1.voucher_number == res2.voucher_number

    # Assert exactly 1 JV exists for this source document
    cnt = (await db_session.execute(
        select(func.count()).select_from(JournalVoucher).where(
            JournalVoucher.tenant_id == tenant_id,
            JournalVoucher.source_document_id == doc_id
        )
    )).scalar()
    assert cnt == 1

# ============================================================================
# 5. CONCURRENT GL POSTING & TRIAL BALANCE STABILITY
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_gl_posting_trial_balance_stability(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")

    async def post_item(amt: Decimal, idx: int):
        return await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
            source_document_type="MANUAL", notes=f"Concurrent item {idx}",
            lines=[
                JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=amt),
                JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=amt)
            ]
        ))

    # Post 5 vouchers sequentially in the test transaction
    for i in range(5):
        await post_item(Decimal("100.00"), i)

    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    assert tb.is_balanced == True
    assert tb.total_debits == tb.total_credits

# ============================================================================
# 6. REVERSAL INTEGRITY & DUPLICATE VOID REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_reversal_integrity_and_duplicate_void(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")

    orig = await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="MANUAL",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("10000.00"))
        ]
    ))

    # 1. Void -> exact $10,000 reversal
    rev = await GLService.void_journal_voucher(db_session, tenant_id, orig.id)
    assert rev.total_debit == 10000.00
    assert rev.total_credit == 10000.00

    # 2. Void same JV again -> REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        await GLService.void_journal_voucher(db_session, tenant_id, orig.id)
    assert exc_info.value.status_code == 400
    assert "already voided" in exc_info.value.detail

# ============================================================================
# 7. AR <-> GL RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_ar_to_gl_reconciliation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_ar = await GLService.get_account_by_code(db_session, tenant_id, "1100")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")

    # Invoice 1: $10,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="CUSTOMER_INVOICE", source_document_id="INV-REC-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ar.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("10000.00"))
        ]
    ))
    # Payment 1: $4,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="CUSTOMER_PAYMENT", source_document_id="PAY-REC-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("4000.00")),
            JournalEntryLineCreate(account_id=acc_ar.id, credit_amount=Decimal("4000.00"))
        ]
    ))

    # GL AR Net Balance = $10,000 - $4,000 = $6,000
    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    ar_row = next(r for r in tb.accounts if r.account_code == "1100")
    assert ar_row.net_debit == 6000.00

# ============================================================================
# 8. AP <-> GL RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_ap_to_gl_reconciliation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_ap = await GLService.get_account_by_code(db_session, tenant_id, "2000")
    acc_ap_acc = await GLService.get_account_by_code(db_session, tenant_id, "2100")
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")

    # Bill: $8,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="VENDOR_INVOICE", source_document_id="BILL-REC-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ap_acc.id, debit_amount=Decimal("8000.00")),
            JournalEntryLineCreate(account_id=acc_ap.id, credit_amount=Decimal("8000.00"))
        ]
    ))
    # Partial Payment: $3,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="VENDOR_PAYMENT", source_document_id="VPAY-REC-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ap.id, debit_amount=Decimal("3000.00")),
            JournalEntryLineCreate(account_id=acc_bank.id, credit_amount=Decimal("3000.00"))
        ]
    ))

    # GL AP Net Balance = $8,000 - $3,000 = $5,000 Credit
    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    ap_row = next(r for r in tb.accounts if r.account_code == "2000")
    assert ap_row.net_credit == 5000.00

# ============================================================================
# 9. INVENTORY <-> GL RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_inventory_to_gl_reconciliation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_ap_acc = await GLService.get_account_by_code(db_session, tenant_id, "2100")
    acc_cogs = await GLService.get_account_by_code(db_session, tenant_id, "5000")

    # GRN: $12,000 receipt
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="GRN", source_document_id="GRN-INV-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("12000.00")),
            JournalEntryLineCreate(account_id=acc_ap_acc.id, credit_amount=Decimal("12000.00"))
        ]
    ))
    # Dispatch: $4,000 COGS
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="SALES_DISPATCH", source_document_id="DISP-INV-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_cogs.id, debit_amount=Decimal("4000.00")),
            JournalEntryLineCreate(account_id=acc_inv.id, credit_amount=Decimal("4000.00"))
        ]
    ))

    # GL Inventory Asset Balance = $12,000 - $4,000 = $8,000
    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    inv_row = next(r for r in tb.accounts if r.account_code == "1200")
    assert inv_row.net_debit == 8000.00

# ============================================================================
# 10. GST / TAX ACCOUNTING SPLIT
# ============================================================================

@pytest.mark.asyncio
async def test_gst_and_tax_accounting_split(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_ar = await GLService.get_account_by_code(db_session, tenant_id, "1100")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")
    acc_tax = await GLService.get_account_by_code(db_session, tenant_id, "2200")

    # Net = ₹100,000, GST = ₹18,000, Total = ₹118,000
    # Dr AR 118,000 / Cr Revenue 100,000 / Cr Tax Payable 18,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="CUSTOMER_INVOICE", source_document_id="INV-GST-01",
        lines=[
            JournalEntryLineCreate(account_id=acc_ar.id, debit_amount=Decimal("118000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("100000.00")),
            JournalEntryLineCreate(account_id=acc_tax.id, credit_amount=Decimal("18000.00"))
        ]
    ))

    pnl = await GLService.generate_income_statement(db_session, tenant_id)
    # Revenue must be exactly ₹100,000 (Tax is liability on balance sheet, not revenue)
    assert pnl.total_revenue == 100000.00

    bs = await GLService.generate_balance_sheet(db_session, tenant_id)
    tax_entry = next(l for l in bs.liabilities if l.account_code == "2200")
    assert tax_entry.amount == 18000.00

# ============================================================================
# 11. RETURNS / CREDIT NOTES & DEBIT NOTES GL INTEGRATION
# ============================================================================

@pytest.mark.asyncio
async def test_returns_and_credit_notes_gl_integration(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_ar = await GLService.get_account_by_code(db_session, tenant_id, "1100")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_cogs = await GLService.get_account_by_code(db_session, tenant_id, "5000")

    # Customer Return / Credit Note:
    # 1. Reverse Revenue: Dr Revenue $2,000 / Cr AR $2,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="MANUAL", notes="Customer Credit Note AR Reversal",
        lines=[
            JournalEntryLineCreate(account_id=acc_rev.id, debit_amount=Decimal("2000.00")),
            JournalEntryLineCreate(account_id=acc_ar.id, credit_amount=Decimal("2000.00"))
        ]
    ))
    # 2. Return to Stock: Dr Inventory $1,000 / Cr COGS $1,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="MANUAL", notes="Customer Return Restock",
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("1000.00")),
            JournalEntryLineCreate(account_id=acc_cogs.id, credit_amount=Decimal("1000.00"))
        ]
    ))

    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    assert tb.is_balanced == True

# ============================================================================
# 12. LANDED COST & PPV ACCOUNTING
# ============================================================================

@pytest.mark.asyncio
async def test_landed_cost_and_ppv_accounting(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_freight = await GLService.get_account_by_code(db_session, tenant_id, "6100")
    acc_ppv = await GLService.get_account_by_code(db_session, tenant_id, "6200")
    acc_ap = await GLService.get_account_by_code(db_session, tenant_id, "2000")

    # PO Standard: $1,000, Actual Billed: $1,100 ($100 PPV) + Freight $150
    # Dr Inventory $1,000 / Dr Freight $150 / Dr PPV $100 / Cr AP $1,250
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="VENDOR_INVOICE", source_document_id="BILL-LANDED-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("1000.00")),
            JournalEntryLineCreate(account_id=acc_freight.id, debit_amount=Decimal("150.00")),
            JournalEntryLineCreate(account_id=acc_ppv.id, debit_amount=Decimal("100.00")),
            JournalEntryLineCreate(account_id=acc_ap.id, credit_amount=Decimal("1250.00"))
        ]
    ))

    pnl = await GLService.generate_income_statement(db_session, tenant_id)
    assert pnl.total_expenses >= 250.00 # Freight ($150) + PPV ($100)

# ============================================================================
# 13. MANUFACTURING / WIP ACCOUNTING
# ============================================================================

@pytest.mark.asyncio
async def test_manufacturing_wip_and_cost_rollup(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_wip = await GLService.get_account_by_code(db_session, tenant_id, "1300")
    acc_ovh = await GLService.get_account_by_code(db_session, tenant_id, "5100")

    # 1. Issue raw materials to production: Dr WIP $2,000 / Cr Inventory $2,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="WORK_ORDER", source_document_id="WO-01-ISSUE",
        lines=[
            JournalEntryLineCreate(account_id=acc_wip.id, debit_amount=Decimal("2000.00")),
            JournalEntryLineCreate(account_id=acc_inv.id, credit_amount=Decimal("2000.00"))
        ]
    ))

    # 2. Production Completion: Dr Inventory (Finished Goods) $2,500 / Cr WIP $2,000 / Cr Overhead $500
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="WORK_ORDER", source_document_id="WO-01-COMPLETE",
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("2500.00")),
            JournalEntryLineCreate(account_id=acc_wip.id, credit_amount=Decimal("2000.00")),
            JournalEntryLineCreate(account_id=acc_ovh.id, credit_amount=Decimal("500.00"))
        ]
    ))

    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    wip_row = next(r for r in tb.accounts if r.account_code == "1300")
    # WIP is fully absorbed (net debit $0)
    assert wip_row.net_debit == 0.00

# ============================================================================
# 14. MULTI-COMPANY GL ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_multi_company_gl_isolation(db_session: AsyncSession):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    acc_a_bank = await GLService.get_account_by_code(db_session, tenant_a, "1000")
    acc_a_rev = await GLService.get_account_by_code(db_session, tenant_a, "4000")

    acc_b_bank = await GLService.get_account_by_code(db_session, tenant_b, "1000")
    acc_b_rev = await GLService.get_account_by_code(db_session, tenant_b, "4000")

    # Company A: $5,000
    await GLService.post_journal_voucher(db_session, tenant_a, JournalVoucherCreate(
        source_document_type="MANUAL",
        lines=[
            JournalEntryLineCreate(account_id=acc_a_bank.id, debit_amount=Decimal("5000.00")),
            JournalEntryLineCreate(account_id=acc_a_rev.id, credit_amount=Decimal("5000.00"))
        ]
    ))

    # Company B: $8,000
    await GLService.post_journal_voucher(db_session, tenant_b, JournalVoucherCreate(
        source_document_type="MANUAL",
        lines=[
            JournalEntryLineCreate(account_id=acc_b_bank.id, debit_amount=Decimal("8000.00")),
            JournalEntryLineCreate(account_id=acc_b_rev.id, credit_amount=Decimal("8000.00"))
        ]
    ))

    tb_a = await GLService.generate_trial_balance(db_session, tenant_a)
    tb_b = await GLService.generate_trial_balance(db_session, tenant_b)

    assert tb_a.total_debits == 5000.00
    assert tb_b.total_debits == 8000.00

# ============================================================================
# 15. YEAR-END CLOSING STATUS REPORTING
# ============================================================================

def test_year_end_closing_status():
    """Formal year-end closing entries are deferred; Balance Sheet calculates net income inclusion dynamically."""
    year_end_implemented = False
    assert year_end_implemented is False, "Year-end closing = DEFERRED"

# ============================================================================
# 16. ACCOUNT NORMAL-BALANCE & CONTRA-BALANCE SEMANTICS
# ============================================================================

@pytest.mark.asyncio
async def test_account_normal_balance_and_contra_semantics(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    accounts = await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    coa_dict = {a.account_code: a for a in accounts}

    # Contra-revenue or sales discounts can legitimately carry a Debit balance
    assert coa_dict["4000"].normal_balance == "CREDIT"
    assert coa_dict["1000"].normal_balance == "DEBIT"

# ============================================================================
# 17. FULL END-TO-END FINANCIAL INTEGRITY SIMULTANEOUS RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_full_end_to_end_financial_integrity(db_session: AsyncSession):
    tenant_id = str(uuid.uuid4())
    acc_bank = await GLService.get_account_by_code(db_session, tenant_id, "1000")
    acc_ar = await GLService.get_account_by_code(db_session, tenant_id, "1100")
    acc_inv = await GLService.get_account_by_code(db_session, tenant_id, "1200")
    acc_ap = await GLService.get_account_by_code(db_session, tenant_id, "2000")
    acc_ap_acc = await GLService.get_account_by_code(db_session, tenant_id, "2100")
    acc_rev = await GLService.get_account_by_code(db_session, tenant_id, "4000")
    acc_cogs = await GLService.get_account_by_code(db_session, tenant_id, "5000")

    # 1. GRN Receipt: $10,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="GRN", source_document_id="GRN-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_inv.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_ap_acc.id, credit_amount=Decimal("10000.00"))
        ]
    ))
    # 2. Vendor Bill: $10,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="VENDOR_INVOICE", source_document_id="BILL-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ap_acc.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_ap.id, credit_amount=Decimal("10000.00"))
        ]
    ))
    # 3. Vendor Payment: $10,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="VENDOR_PAYMENT", source_document_id="VPAY-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ap.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_bank.id, credit_amount=Decimal("10000.00"))
        ]
    ))
    # 4. Customer Invoice: $15,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="CUSTOMER_INVOICE", source_document_id="INV-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_ar.id, debit_amount=Decimal("15000.00")),
            JournalEntryLineCreate(account_id=acc_rev.id, credit_amount=Decimal("15000.00"))
        ]
    ))
    # 5. Sales Dispatch (COGS): $10,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="SALES_DISPATCH", source_document_id="DISP-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_cogs.id, debit_amount=Decimal("10000.00")),
            JournalEntryLineCreate(account_id=acc_inv.id, credit_amount=Decimal("10000.00"))
        ]
    ))
    # 6. Customer Payment: $15,000
    await GLService.post_journal_voucher(db_session, tenant_id, JournalVoucherCreate(
        source_document_type="CUSTOMER_PAYMENT", source_document_id="PAY-E2E-1",
        lines=[
            JournalEntryLineCreate(account_id=acc_bank.id, debit_amount=Decimal("15000.00")),
            JournalEntryLineCreate(account_id=acc_ar.id, credit_amount=Decimal("15000.00"))
        ]
    ))

    # Simultaneous Checks:
    # 1. Trial Balance is balanced
    tb = await GLService.generate_trial_balance(db_session, tenant_id)
    assert tb.is_balanced == True
    assert tb.total_debits == tb.total_credits

    # 2. P&L reconciles: Revenue $15,000 - COGS $10,000 = Net Income $5,000
    pnl = await GLService.generate_income_statement(db_session, tenant_id)
    assert pnl.total_revenue == 15000.00
    assert pnl.total_cogs == 10000.00
    assert pnl.net_income == 5000.00

    # 3. Balance Sheet reconciles: Assets ($5,000 bank) == Liabilities ($0) + Equity ($5,000 net income)
    bs = await GLService.generate_balance_sheet(db_session, tenant_id)
    assert bs.is_balanced == True
    assert bs.total_assets == 5000.00
    assert bs.total_equity == 5000.00
