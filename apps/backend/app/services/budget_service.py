import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.models.budgeting import CostCenter, DepartmentalBudget, BudgetLine, BudgetCommitment
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.budgeting import (
    CostCenterCreate,
    CostCenterResponse,
    BudgetLineCreate,
    BudgetLineResponse,
    DepartmentalBudgetCreate,
    DepartmentalBudgetResponse,
    BudgetCommitmentRequest,
    BudgetCommitmentResponse,
    CostCenterVarianceReport
)

class BudgetService:

    # ========================================================================
    # 1. COST CENTER MANAGEMENT
    # ========================================================================

    @staticmethod
    async def create_cost_center(
        db: AsyncSession,
        tenant_id: str,
        cc_in: CostCenterCreate
    ) -> CostCenterResponse:
        existing = (await db.execute(
            select(CostCenter).where(
                CostCenter.tenant_id == tenant_id,
                CostCenter.cost_center_code == cc_in.cost_center_code.upper()
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Cost Center '{cc_in.cost_center_code}' already exists")

        cc = CostCenter(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            cost_center_code=cc_in.cost_center_code.upper(),
            cost_center_name=cc_in.cost_center_name,
            parent_cost_center_id=cc_in.parent_cost_center_id,
            department_head_user_id=cc_in.department_head_user_id,
            is_profit_center=cc_in.is_profit_center,
            description=cc_in.description,
            is_active=True
        )
        db.add(cc)
        await db.commit()
        await db.refresh(cc)

        return CostCenterResponse(
            id=cc.id,
            tenant_id=cc.tenant_id,
            cost_center_code=cc.cost_center_code,
            cost_center_name=cc.cost_center_name,
            parent_cost_center_id=cc.parent_cost_center_id,
            department_head_user_id=cc.department_head_user_id,
            is_profit_center=cc.is_profit_center,
            description=cc.description,
            is_active=cc.is_active,
            created_at=cc.created_at
        )

    # ========================================================================
    # 2. DEPARTMENTAL BUDGET ALLOCATION & STATE MACHINE
    # ========================================================================

    VALID_BUDGET_TRANSITIONS = {
        "DRAFT": {"APPROVED"},
        "APPROVED": {"COMMITTED", "LOCKED", "CLOSED"},
        "COMMITTED": {"ACTUALIZED", "LOCKED", "CLOSED"},
        "ACTUALIZED": {"CLOSED"},
        "LOCKED": {"CLOSED"},
        "CLOSED": set()
    }

    @staticmethod
    async def create_departmental_budget(
        db: AsyncSession,
        tenant_id: str,
        budget_in: DepartmentalBudgetCreate
    ) -> DepartmentalBudgetResponse:
        existing = (await db.execute(
            select(DepartmentalBudget).where(
                DepartmentalBudget.tenant_id == tenant_id,
                or_(
                    DepartmentalBudget.budget_code == budget_in.budget_code.upper(),
                    and_(
                        DepartmentalBudget.cost_center_id == budget_in.cost_center_id,
                        DepartmentalBudget.fiscal_year_id == budget_in.fiscal_year_id
                    )
                )
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Budget for Cost Center in this Fiscal Year already exists")

        total_alloc = sum(l.allocated_amount for l in budget_in.lines)

        budget = DepartmentalBudget(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            budget_code=budget_in.budget_code.upper(),
            cost_center_id=budget_in.cost_center_id,
            fiscal_year_id=budget_in.fiscal_year_id,
            total_allocated_budget=total_alloc,
            status="DRAFT",
            enforce_hard_cap=budget_in.enforce_hard_cap,
            warning_threshold_percentage=budget_in.warning_threshold_percentage,
            notes=budget_in.notes
        )
        db.add(budget)

        lines: List[BudgetLine] = []
        for line_in in budget_in.lines:
            bl = BudgetLine(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                budget_id=budget.id,
                period_code=line_in.period_code,
                gl_account_id=line_in.gl_account_id,
                allocated_amount=line_in.allocated_amount,
                committed_amount=Decimal("0.0"),
                actual_amount=Decimal("0.0")
            )
            db.add(bl)
            lines.append(bl)

        await db.commit()
        await db.refresh(budget)

        return DepartmentalBudgetResponse(
            id=budget.id,
            tenant_id=budget.tenant_id,
            budget_code=budget.budget_code,
            cost_center_id=budget.cost_center_id,
            fiscal_year_id=budget.fiscal_year_id,
            total_allocated_budget=budget.total_allocated_budget,
            status=budget.status,
            enforce_hard_cap=budget.enforce_hard_cap,
            warning_threshold_percentage=budget.warning_threshold_percentage,
            notes=budget.notes,
            budget_lines=[
                BudgetLineResponse(
                    id=l.id,
                    budget_id=l.budget_id,
                    period_code=l.period_code,
                    gl_account_id=l.gl_account_id,
                    allocated_amount=l.allocated_amount,
                    committed_amount=l.committed_amount,
                    actual_amount=l.actual_amount,
                    available_amount=l.allocated_amount - l.committed_amount - l.actual_amount
                ) for l in lines
            ],
            created_at=budget.created_at
        )

    @staticmethod
    async def update_budget_status(
        db: AsyncSession,
        tenant_id: str,
        budget_id: str,
        new_status: str
    ) -> DepartmentalBudgetResponse:
        budget = (await db.execute(
            select(DepartmentalBudget).where(
                DepartmentalBudget.id == budget_id,
                DepartmentalBudget.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")

        allowed = BudgetService.VALID_BUDGET_TRANSITIONS.get(budget.status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal budget state transition from {budget.status} to {new_status}"
            )

        budget.status = new_status
        await db.commit()
        await db.refresh(budget)

        lines = (await db.execute(select(BudgetLine).where(BudgetLine.budget_id == budget.id))).scalars().all()

        return DepartmentalBudgetResponse(
            id=budget.id,
            tenant_id=budget.tenant_id,
            budget_code=budget.budget_code,
            cost_center_id=budget.cost_center_id,
            fiscal_year_id=budget.fiscal_year_id,
            total_allocated_budget=budget.total_allocated_budget,
            status=budget.status,
            enforce_hard_cap=budget.enforce_hard_cap,
            warning_threshold_percentage=budget.warning_threshold_percentage,
            notes=budget.notes,
            budget_lines=[
                BudgetLineResponse(
                    id=l.id,
                    budget_id=l.budget_id,
                    period_code=l.period_code,
                    gl_account_id=l.gl_account_id,
                    allocated_amount=l.allocated_amount,
                    committed_amount=l.committed_amount,
                    actual_amount=l.actual_amount,
                    available_amount=l.allocated_amount - l.committed_amount - l.actual_amount
                ) for l in lines
            ],
            created_at=budget.created_at
        )

    @staticmethod
    async def approve_departmental_budget(
        db: AsyncSession,
        tenant_id: str,
        budget_id: str
    ) -> DepartmentalBudgetResponse:
        return await BudgetService.update_budget_status(db, tenant_id, budget_id, "APPROVED")

    # ========================================================================
    # 3. COMMITMENT ACCOUNTING, WARNINGS & OVERRUN ENFORCEMENT
    # ========================================================================

    @staticmethod
    async def commit_budget(
        db: AsyncSession,
        tenant_id: str,
        req: BudgetCommitmentRequest
    ) -> BudgetCommitmentResponse:
        # Check if period is closed
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.period_code == req.period_code
            )
        )).scalar_one_or_none()
        if period and period.status in {"CLOSED", "FINALIZED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Accounting Period '{period.period_code}' is {period.status}. Budget commitments are prohibited."
            )

        # Idempotency Check: Return existing active commitment
        existing_commitment = (await db.execute(
            select(BudgetCommitment).where(
                BudgetCommitment.tenant_id == tenant_id,
                BudgetCommitment.source_document_type == req.source_document_type,
                BudgetCommitment.source_document_id == req.source_document_id
            )
        )).scalar_one_or_none()

        if existing_commitment:
            return BudgetCommitmentResponse(
                id=existing_commitment.id,
                budget_line_id=existing_commitment.budget_line_id,
                source_document_type=existing_commitment.source_document_type,
                source_document_id=existing_commitment.source_document_id,
                committed_amount=existing_commitment.committed_amount,
                status=existing_commitment.status,
                warning_triggered=False,
                warning_message="Existing commitment returned (Idempotent)"
            )

        # Find active budget for Cost Center
        budget = (await db.execute(
            select(DepartmentalBudget).where(
                DepartmentalBudget.tenant_id == tenant_id,
                DepartmentalBudget.cost_center_id == req.cost_center_id,
                DepartmentalBudget.status.in_(["APPROVED", "COMMITTED", "ACTUALIZED"])
            ).with_for_update()
        )).scalar_one_or_none()

        if not budget:
            raise HTTPException(status_code=404, detail="No approved budget found for this Cost Center")

        # Find budget line for period & GL account
        line = (await db.execute(
            select(BudgetLine).where(
                BudgetLine.budget_id == budget.id,
                BudgetLine.period_code == req.period_code,
                BudgetLine.gl_account_id == req.gl_account_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not line:
            raise HTTPException(status_code=404, detail=f"No budget line configured for period {req.period_code} and GL account")

        projected_spend = line.committed_amount + line.actual_amount + req.amount
        if budget.enforce_hard_cap and projected_spend > line.allocated_amount:
            overrun = projected_spend - line.allocated_amount
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Budget Overrun Prohibited: Requested commitment ${req.amount} exceeds remaining available budget by ${overrun}"
            )

        # Check soft warning threshold
        warning_triggered = False
        warning_message = None
        if line.allocated_amount > Decimal("0.0"):
            utilization_pct = (projected_spend / line.allocated_amount * Decimal("100.0")).quantize(Decimal("0.01"))
            if utilization_pct >= budget.warning_threshold_percentage:
                warning_triggered = True
                warning_message = f"Warning: Spend reaches {utilization_pct}% of allocated budget (Threshold: {budget.warning_threshold_percentage}%)"

        # Create BudgetCommitment
        commitment = BudgetCommitment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            budget_line_id=line.id,
            source_document_type=req.source_document_type,
            source_document_id=req.source_document_id,
            committed_amount=req.amount,
            status="ACTIVE"
        )
        db.add(commitment)

        line.committed_amount += req.amount
        if budget.status == "APPROVED":
            budget.status = "COMMITTED"

        await db.commit()

        return BudgetCommitmentResponse(
            id=commitment.id,
            budget_line_id=commitment.budget_line_id,
            source_document_type=commitment.source_document_type,
            source_document_id=commitment.source_document_id,
            committed_amount=commitment.committed_amount,
            status=commitment.status,
            warning_triggered=warning_triggered,
            warning_message=warning_message
        )

    @staticmethod
    async def actualize_budget_commitment(
        db: AsyncSession,
        tenant_id: str,
        source_document_type: str,
        source_document_id: str,
        actual_amount: Decimal
    ) -> None:
        commitment = (await db.execute(
            select(BudgetCommitment).where(
                BudgetCommitment.tenant_id == tenant_id,
                BudgetCommitment.source_document_type == source_document_type,
                BudgetCommitment.source_document_id == source_document_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not commitment or commitment.status == "ACTUALIZED":
            return # Idempotent: Ignore if already actualized or absent

        line = (await db.execute(
            select(BudgetLine).where(BudgetLine.id == commitment.budget_line_id).with_for_update()
        )).scalar_one()

        line.committed_amount = max(Decimal("0.0"), line.committed_amount - commitment.committed_amount)
        line.actual_amount += actual_amount
        commitment.status = "ACTUALIZED"

        budget = (await db.execute(select(DepartmentalBudget).where(DepartmentalBudget.id == line.budget_id).with_for_update())).scalar_one()
        if budget.status in {"APPROVED", "COMMITTED"}:
            budget.status = "ACTUALIZED"

        await db.commit()

    # ========================================================================
    # 4. HIERARCHICAL ROLLUP & VARIANCE REPORTS
    # ========================================================================

    @staticmethod
    async def _get_all_descendant_cost_center_ids(db: AsyncSession, tenant_id: str, cost_center_id: str) -> Set[str]:
        result_ids = {cost_center_id}
        queue = [cost_center_id]
        while queue:
            curr = queue.pop(0)
            children = (await db.execute(
                select(CostCenter.id).where(CostCenter.tenant_id == tenant_id, CostCenter.parent_cost_center_id == curr)
            )).scalars().all()
            for child_id in children:
                if child_id not in result_ids:
                    result_ids.add(child_id)
                    queue.append(child_id)
        return result_ids

    @staticmethod
    async def generate_cost_center_variance_report(
        db: AsyncSession,
        tenant_id: str,
        cost_center_id: str,
        period_code: Optional[str] = None,
        include_hierarchy: bool = True
    ) -> CostCenterVarianceReport:
        cc = (await db.execute(
            select(CostCenter).where(CostCenter.id == cost_center_id, CostCenter.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost Center not found")

        if include_hierarchy:
            cc_ids = await BudgetService._get_all_descendant_cost_center_ids(db, tenant_id, cost_center_id)
        else:
            cc_ids = {cost_center_id}

        query = select(BudgetLine).join(DepartmentalBudget).where(
            DepartmentalBudget.tenant_id == tenant_id,
            DepartmentalBudget.cost_center_id.in_(list(cc_ids))
        )
        if period_code:
            query = query.where(BudgetLine.period_code == period_code)

        lines = (await db.execute(query)).scalars().all()

        tot_alloc = sum(l.allocated_amount for l in lines)
        tot_commit = sum(l.committed_amount for l in lines)
        tot_actual = sum(l.actual_amount for l in lines)
        tot_spent = tot_commit + tot_actual
        variance = tot_alloc - tot_spent
        utilization = (tot_spent / tot_alloc * Decimal("100.0")).quantize(Decimal("0.01")) if tot_alloc > 0 else Decimal("0.0")

        return CostCenterVarianceReport(
            cost_center_id=cc.id,
            cost_center_code=cc.cost_center_code,
            cost_center_name=cc.cost_center_name,
            period_code=period_code,
            total_allocated=tot_alloc,
            total_committed=tot_commit,
            total_actual=tot_actual,
            total_variance=variance,
            utilization_percentage=utilization
        )
