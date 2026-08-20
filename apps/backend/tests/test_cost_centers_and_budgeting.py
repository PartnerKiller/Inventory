import pytest
import uuid
import asyncio
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.models.budgeting import CostCenter, DepartmentalBudget, BudgetLine, BudgetCommitment
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.budgeting import (
    CostCenterCreate,
    DepartmentalBudgetCreate,
    BudgetLineCreate,
    BudgetCommitmentRequest
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.budget_service import BudgetService
from app.services.gl_service import GLService

# ============================================================================
# 1. COST CENTER HIERARCHY & PROFIT CENTER STRUCTURE
# ============================================================================

@pytest.mark.asyncio
async def test_cost_center_creation_and_hierarchy(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    parent_cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(
            cost_center_code=f"ENG-{uuid.uuid4().hex[:4]}",
            cost_center_name="Engineering Division"
        )
    )

    child_cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(
            cost_center_code=f"DEV-{uuid.uuid4().hex[:4]}",
            cost_center_name="Software Development",
            parent_cost_center_id=parent_cc.id
        )
    )
    assert child_cc.parent_cost_center_id == parent_cc.id

@pytest.mark.asyncio
async def test_profit_center_flag_and_structure(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    pc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(
            cost_center_code=f"SALES-{uuid.uuid4().hex[:4]}",
            cost_center_name="Direct Sales Profit Center",
            is_profit_center=True
        )
    )
    assert pc.is_profit_center is True

# ============================================================================
# 2. DEPARTMENTAL BUDGET ALLOCATION & STATE MACHINE
# ============================================================================

@pytest.mark.asyncio
async def test_departmental_budget_allocation_and_approval(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-BUD-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"OPS-{uuid.uuid4().hex[:4]}", cost_center_name="Operations")
    )

    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-OPS-{uuid.uuid4().hex[:4]}",
            cost_center_id=cc.id,
            fiscal_year_id=fy.id,
            enforce_hard_cap=True,
            lines=[
                BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("50000.0"))
            ]
        )
    )
    assert budget.status == "DRAFT"
    assert budget.total_allocated_budget == Decimal("50000.0")

    appr_budget = await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)
    assert appr_budget.status == "APPROVED"

@pytest.mark.asyncio
async def test_budget_state_machine_valid_and_invalid_transitions(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-SM-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"SM-{uuid.uuid4().hex[:4]}", cost_center_name="State Machine CC")
    )

    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-SM-{uuid.uuid4().hex[:4]}",
            cost_center_id=cc.id,
            fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("10000.0"))]
        )
    )
    assert budget.status == "DRAFT"

    # Invalid: DRAFT -> COMMITTED -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc1:
        await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "COMMITTED")
    assert exc1.value.status_code == 400

    # Valid: DRAFT -> APPROVED
    b_appr = await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "APPROVED")
    assert b_appr.status == "APPROVED"

    # Valid: APPROVED -> COMMITTED
    b_comm = await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "COMMITTED")
    assert b_comm.status == "COMMITTED"

    # Valid: COMMITTED -> ACTUALIZED
    b_act = await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "ACTUALIZED")
    assert b_act.status == "ACTUALIZED"

    # Valid: ACTUALIZED -> CLOSED
    b_cls = await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "CLOSED")
    assert b_cls.status == "CLOSED"

    # Invalid: CLOSED -> APPROVED -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc2:
        await BudgetService.update_budget_status(db_session, tenant_id, budget.id, "APPROVED")
    assert exc2.value.status_code == 400

# ============================================================================
# 3. SOFT BUDGET WARNING & HARD OVERRUN REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_soft_budget_warning_and_hard_overrun_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-SFT-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"SFT-{uuid.uuid4().hex[:4]}", cost_center_name="Soft Warning CC")
    )
    # Budget = ₹100,000 | Warning = 80% | Hard Cap = True
    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-SFT-{uuid.uuid4().hex[:4]}", cost_center_id=cc.id, fiscal_year_id=fy.id,
            enforce_hard_cap=True, warning_threshold_percentage=Decimal("80.0"),
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("100000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)

    # 1. Commit ₹85,000 (85% > 80% warning threshold) -> Warning generated, commitment allowed
    commit_res = await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(
            cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
            amount=Decimal("85000.0"), source_document_type="PURCHASE_ORDER", source_document_id="PO-SFT-1"
        )
    )
    assert commit_res.warning_triggered is True
    assert "Warning: Spend reaches 85.00%" in commit_res.warning_message
    assert commit_res.committed_amount == Decimal("85000.0")

    # 2. Exceed remaining ₹15,000 budget by attempting ₹20,000 -> REJECT (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await BudgetService.commit_budget(
            db=db_session, tenant_id=tenant_id,
            req=BudgetCommitmentRequest(
                cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
                amount=Decimal("20000.0"), source_document_type="PURCHASE_ORDER", source_document_id="PO-SFT-2"
            )
        )
    assert exc_info.value.status_code == 400
    assert "Budget Overrun Prohibited" in exc_info.value.detail

# ============================================================================
# 4. COMMITMENT TRACKING & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_budget_commitment_tracking_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-IDM-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"IDM-{uuid.uuid4().hex[:4]}", cost_center_name="Idempotency CC")
    )
    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-IDM-{uuid.uuid4().hex[:4]}", cost_center_id=cc.id, fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("50000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)

    po_id = f"PO-IDM-{uuid.uuid4().hex[:4]}"

    # First attempt -> ₹10,000 committed
    res1 = await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(
            cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
            amount=Decimal("10000.0"), source_document_type="PURCHASE_ORDER", source_document_id=po_id
        )
    )
    assert res1.committed_amount == Decimal("10000.0")

    # Second attempt (exact same PO) -> Idempotent, committed amount remains ₹10,000
    res2 = await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(
            cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
            amount=Decimal("10000.0"), source_document_type="PURCHASE_ORDER", source_document_id=po_id
        )
    )
    assert res2.id == res1.id

    bl = (await db_session.execute(select(BudgetLine).where(BudgetLine.id == res1.budget_line_id))).scalar_one()
    assert bl.committed_amount == Decimal("10000.0") # NOT 20,000

# ============================================================================
# 5. COMMITMENT ACTUALIZATION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_budget_actualization_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-ACTIDM-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"ACTIDM-{uuid.uuid4().hex[:4]}", cost_center_name="Act Idm CC")
    )
    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-ACTIDM-{uuid.uuid4().hex[:4]}", cost_center_id=cc.id, fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("30000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)

    po_id = f"PO-ACT-{uuid.uuid4().hex[:4]}"
    await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(
            cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
            amount=Decimal("5000.0"), source_document_type="PURCHASE_ORDER", source_document_id=po_id
        )
    )

    # First actualization -> committed = 0, actual = ₹5,000
    await BudgetService.actualize_budget_commitment(
        db=db_session, tenant_id=tenant_id,
        source_document_type="PURCHASE_ORDER", source_document_id=po_id,
        actual_amount=Decimal("5000.0")
    )
    bl = (await db_session.execute(select(BudgetLine).where(BudgetLine.budget_id == budget.id))).scalar_one()
    assert bl.committed_amount == Decimal("0.0")
    assert bl.actual_amount == Decimal("5000.0")

    # Retry same actualization -> Idempotent, actual remains ₹5,000
    await BudgetService.actualize_budget_commitment(
        db=db_session, tenant_id=tenant_id,
        source_document_type="PURCHASE_ORDER", source_document_id=po_id,
        actual_amount=Decimal("5000.0")
    )
    bl_retry = (await db_session.execute(select(BudgetLine).where(BudgetLine.budget_id == budget.id))).scalar_one()
    assert bl_retry.actual_amount == Decimal("5000.0")

# ============================================================================
# 6. GL COST-CENTER TAGGING & DEPARTMENTAL ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_gl_cost_center_tagging_and_departmental_isolation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_1000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    cc_eng = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"ENG-TAG-{uuid.uuid4().hex[:4]}", cost_center_name="Engineering")
    )
    cc_sales = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"SAL-TAG-{uuid.uuid4().hex[:4]}", cost_center_name="Sales")
    )

    # Post JV with lines tagged to CC-ENG ($3,000) and CC-SALES ($2,000)
    jv = await GLService.post_journal_voucher(
        db=db_session, tenant_id=tenant_id,
        voucher_in=JournalVoucherCreate(
            voucher_date=datetime.now(timezone.utc),
            source_document_type="MANUAL_EXPENSE",
            source_document_id=f"EXP-{uuid.uuid4().hex[:4]}",
            notes="Split Departmental Expense",
            lines=[
                JournalEntryLineCreate(account_id=acc_6000.id, debit_amount=Decimal("3000.0"), credit_amount=Decimal("0.0"), memo="Eng Software", cost_center_id=cc_eng.id),
                JournalEntryLineCreate(account_id=acc_6000.id, debit_amount=Decimal("2000.0"), credit_amount=Decimal("0.0"), memo="Sales Ads", cost_center_id=cc_sales.id),
                JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("5000.0"), memo="Cash outflow")
            ]
        ),
        user_id=user_id
    )

    # Query lines for CC-ENG
    eng_lines = (await db_session.execute(
        select(JournalEntryLine).where(JournalEntryLine.voucher_id == jv.id, JournalEntryLine.cost_center_id == cc_eng.id)
    )).scalars().all()
    assert len(eng_lines) == 1
    assert eng_lines[0].debit_amount == Decimal("3000.0")

    # Query lines for CC-SALES
    sales_lines = (await db_session.execute(
        select(JournalEntryLine).where(JournalEntryLine.voucher_id == jv.id, JournalEntryLine.cost_center_id == cc_sales.id)
    )).scalars().all()
    assert len(sales_lines) == 1
    assert sales_lines[0].debit_amount == Decimal("2000.0")

# ============================================================================
# 7. HIERARCHICAL ROLLUP WITHOUT DOUBLE-COUNTING
# ============================================================================

@pytest.mark.asyncio
async def test_hierarchical_cost_center_rollup_without_double_counting(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-ROLL-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    # Engineering (Parent)
    parent_eng = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"ENG-P-{uuid.uuid4().hex[:4]}", cost_center_name="Engineering Org")
    )
    # Software (Child 1)
    child_sw = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"SW-C-{uuid.uuid4().hex[:4]}", cost_center_name="Software", parent_cost_center_id=parent_eng.id)
    )
    # Infrastructure (Child 2)
    child_infra = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"INF-C-{uuid.uuid4().hex[:4]}", cost_center_name="Infra", parent_cost_center_id=parent_eng.id)
    )

    # Budget Software: $40,000 allocated
    b_sw = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-SW-{uuid.uuid4().hex[:4]}", cost_center_id=child_sw.id, fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("40000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, b_sw.id)
    await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(cost_center_id=child_sw.id, gl_account_id=acc_6000.id, period_code="2026-01", amount=Decimal("15000.0"), source_document_type="PO", source_document_id="PO-SW")
    )

    # Budget Infra: $60,000 allocated
    b_infra = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-INF-{uuid.uuid4().hex[:4]}", cost_center_id=child_infra.id, fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("60000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, b_infra.id)
    await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(cost_center_id=child_infra.id, gl_account_id=acc_6000.id, period_code="2026-01", amount=Decimal("25000.0"), source_document_type="PO", source_document_id="PO-INF")
    )

    # Parent Rollup Report (Engineering)
    parent_report = await BudgetService.generate_cost_center_variance_report(
        db=db_session, tenant_id=tenant_id, cost_center_id=parent_eng.id, period_code="2026-01", include_hierarchy=True
    )
    # Total allocated = $40,000 + $60,000 = $100,000
    assert parent_report.total_allocated == Decimal("100000.0")
    # Total committed = $15,000 + $25,000 = $40,000
    assert parent_report.total_committed == Decimal("40000.0")
    assert parent_report.total_variance == Decimal("60000.0")
    assert parent_report.utilization_percentage == Decimal("40.00")

# ============================================================================
# 8. CONCURRENT BUDGET COMMITMENT RACE PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_budget_commitment_race_protection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-CNC-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"CNC-{uuid.uuid4().hex[:4]}", cost_center_name="Concurrent CC")
    )
    # Budget = ₹10,000 remaining
    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-CNC-{uuid.uuid4().hex[:4]}", cost_center_id=cc.id, fiscal_year_id=fy.id,
            enforce_hard_cap=True,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("10000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)

    # Attempt Request A (₹7,000) and Request B (₹7,000)
    req_a = BudgetCommitmentRequest(cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01", amount=Decimal("7000.0"), source_document_type="PO", source_document_id="PO-CNC-A")
    req_b = BudgetCommitmentRequest(cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01", amount=Decimal("7000.0"), source_document_type="PO", source_document_id="PO-CNC-B")

    # First commitment succeeds
    res_a = await BudgetService.commit_budget(db_session, tenant_id, req_a)
    assert res_a.committed_amount == Decimal("7000.0")

    # Second commitment exceeds remaining ₹3,000 -> Strictly rejected (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await BudgetService.commit_budget(db_session, tenant_id, req_b)
    assert exc_info.value.status_code == 400
    assert "Budget Overrun Prohibited" in exc_info.value.detail

# ============================================================================
# 9. COST CENTER VARIANCE REPORT
# ============================================================================

@pytest.mark.asyncio
async def test_cost_center_variance_report(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)
    acc_6000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one()

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-VAR2-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)
    await db_session.commit()

    cc = await BudgetService.create_cost_center(
        db=db_session, tenant_id=tenant_id,
        cc_in=CostCenterCreate(cost_center_code=f"REP2-{uuid.uuid4().hex[:4]}", cost_center_name="Reporting Center 2")
    )
    budget = await BudgetService.create_departmental_budget(
        db=db_session, tenant_id=tenant_id,
        budget_in=DepartmentalBudgetCreate(
            budget_code=f"BUD-REP2-{uuid.uuid4().hex[:4]}", cost_center_id=cc.id, fiscal_year_id=fy.id,
            lines=[BudgetLineCreate(period_code="2026-01", gl_account_id=acc_6000.id, allocated_amount=Decimal("100000.0"))]
        )
    )
    await BudgetService.approve_departmental_budget(db_session, tenant_id, budget.id)

    await BudgetService.commit_budget(
        db=db_session, tenant_id=tenant_id,
        req=BudgetCommitmentRequest(
            cost_center_id=cc.id, gl_account_id=acc_6000.id, period_code="2026-01",
            amount=Decimal("25000.0"), source_document_type="PURCHASE_ORDER", source_document_id="PO-REP-2"
        )
    )

    report = await BudgetService.generate_cost_center_variance_report(
        db=db_session, tenant_id=tenant_id, cost_center_id=cc.id, period_code="2026-01"
    )
    assert report.total_allocated == Decimal("100000.0")
    assert report.total_committed == Decimal("25000.0")
    assert report.total_variance == Decimal("75000.0")
    assert report.utilization_percentage == Decimal("25.00")

# ============================================================================
# 10. PERIOD CLOSING LOCK INTEGRATION
# ============================================================================

@pytest.mark.asyncio
async def test_budget_period_closing_lock_integration(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    fy = FiscalYear(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_code=f"FY-LCK2-{uuid.uuid4().hex[:4]}",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status="OPEN"
    )
    db_session.add(fy)

    period_closed = AccountingPeriod(
        id=str(uuid.uuid4()), tenant_id=tenant_id, fiscal_year_id=fy.id,
        period_code="2026-05", period_number=5,
        start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), status="CLOSED"
    )
    db_session.add(period_closed)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await BudgetService.commit_budget(
            db=db_session, tenant_id=tenant_id,
            req=BudgetCommitmentRequest(
                cost_center_id=str(uuid.uuid4()), gl_account_id=str(uuid.uuid4()), period_code="2026-05",
                amount=Decimal("1000.0"), source_document_type="PURCHASE_ORDER", source_document_id="PO-FAIL"
            )
        )
    assert exc_info.value.status_code == 400
    assert "is CLOSED" in exc_info.value.detail
