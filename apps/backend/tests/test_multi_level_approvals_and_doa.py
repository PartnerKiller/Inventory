import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.auth import User, Role
from app.models.approval import ApprovalRule, ApprovalRequest, ApprovalStep, ApprovalDelegation
from app.schemas.approval import (
    ApprovalRuleCreate,
    ApprovalRequestCreate,
    ApprovalActionRequest,
    ApprovalDelegationCreate
)
from app.services.approval_service import ApprovalService

# ============================================================================
# 1. TIERED SPEND AUTHORIZATION & SEQUENTIAL PROGRESSION
# ============================================================================

@pytest.mark.asyncio
async def test_tiered_spend_authorization_and_sequential_progression(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    mgr_user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"mgr-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    cfo_user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"cfo-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add_all([mgr_user, cfo_user])
    await db_session.commit()

    # Tier 1: PO $50k+ -> Step 1: Manager
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="PO Step 1", entity_type="PURCHASE_ORDER", min_amount=Decimal("50000.0"), step_number=1, approver_user_id=mgr_user.id)
    )
    # Tier 2: PO $50k+ -> Step 2: CFO
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="PO Step 2", entity_type="PURCHASE_ORDER", min_amount=Decimal("50000.0"), step_number=2, approver_user_id=cfo_user.id)
    )

    # 1. Low-value PO ($1,000) -> Auto-approved immediately
    req_low = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id="PO-LOW-1", document_reference="PO-LOW-1", total_amount=Decimal("1000.0"))
    )
    assert req_low.status == "APPROVED"
    assert req_low.total_steps == 0

    # 2. High-value PO ($80,000) -> Requires 2 steps
    req_high = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id="PO-HIGH-1", document_reference="PO-HIGH-1", total_amount=Decimal("80000.0"))
    )
    assert req_high.status == "PENDING"
    assert req_high.total_steps == 2

    # Step 2 approver cannot approve before Step 1 finishes -> HTTP 403
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.process_step_action(
            db=db_session, tenant_id=tenant_id, request_id=req_high.id, user_id=cfo_user.id,
            action_in=ApprovalActionRequest(action="APPROVE")
        )
    assert exc_info.value.status_code == 403

    # Step 1 approved -> Advances to IN_REVIEW, step moves to 2
    res_s1 = await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req_high.id, user_id=mgr_user.id,
        action_in=ApprovalActionRequest(action="APPROVE", comments="Manager approved")
    )
    assert res_s1.status == "IN_REVIEW"
    assert res_s1.current_step_number == 2

    # Step 2 approved -> Moves to APPROVED
    res_s2 = await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req_high.id, user_id=cfo_user.id,
        action_in=ApprovalActionRequest(action="APPROVE", comments="CFO final signoff")
    )
    assert res_s2.status == "APPROVED"

# ============================================================================
# 2. PO & GRN RELEASE LOCK
# ============================================================================

@pytest.mark.asyncio
async def test_po_and_grn_release_lock(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-po-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    po_id = f"PO-{uuid.uuid4().hex[:6]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="PO Guard", entity_type="PURCHASE_ORDER", min_amount=Decimal("1000.0"), step_number=1, approver_user_id=approver.id)
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id=po_id, document_reference=po_id, total_amount=Decimal("20000.0"))
    )
    assert req.status == "PENDING"

    # Attempting to release / receive goods against pending PO -> BLOCKED (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="PURCHASE_ORDER", entity_id=po_id)
    assert exc_info.value.status_code == 400
    assert "Document Release Prohibited" in exc_info.value.detail

    # Approve PO
    await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=approver.id,
        action_in=ApprovalActionRequest(action="APPROVE", comments="PO Approved for Receiving")
    )

    # Validated release now succeeds with zero exceptions
    await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="PURCHASE_ORDER", entity_id=po_id)

# ============================================================================
# 3. AP & GL INVOICE RELEASE LOCK
# ============================================================================

@pytest.mark.asyncio
async def test_ap_and_gl_invoice_release_lock(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-ap-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    bill_id = f"BILL-{uuid.uuid4().hex[:6]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="AP Guard", entity_type="VENDOR_INVOICE", min_amount=Decimal("500.0"), step_number=1, approver_user_id=approver.id)
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="VENDOR_INVOICE", entity_id=bill_id, document_reference=bill_id, total_amount=Decimal("12000.0"))
    )

    # Posting invoice while pending -> BLOCKED (HTTP 400)
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="VENDOR_INVOICE", entity_id=bill_id)
    assert exc_info.value.status_code == 400

    # Approve invoice
    await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=approver.id,
        action_in=ApprovalActionRequest(action="APPROVE")
    )
    # Posting now allowed
    await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="VENDOR_INVOICE", entity_id=bill_id)

# ============================================================================
# 4. MANUAL JOURNAL VOUCHER RELEASE LOCK
# ============================================================================

@pytest.mark.asyncio
async def test_manual_jv_release_lock(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-jv-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    jv_id = f"JV-{uuid.uuid4().hex[:6]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="JV Guard", entity_type="JOURNAL_VOUCHER", min_amount=Decimal("1000.0"), step_number=1, approver_user_id=approver.id)
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="JOURNAL_VOUCHER", entity_id=jv_id, document_reference=jv_id, total_amount=Decimal("50000.0"))
    )

    # Pending JV -> BLOCKED
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="JOURNAL_VOUCHER", entity_id=jv_id)
    assert exc_info.value.status_code == 400

    # Approve JV
    await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=approver.id,
        action_in=ApprovalActionRequest(action="APPROVE")
    )
    # Posting JV -> ALLOWED
    await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="JOURNAL_VOUCHER", entity_id=jv_id)

# ============================================================================
# 5. BUDGET OVERRUN & ASSET DISPOSAL APPROVAL LOCKS
# ============================================================================

@pytest.mark.asyncio
async def test_budget_overrun_and_asset_disposal_approval_locks(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-exc-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    # 1. Budget Overrun Exception
    bud_id = f"BUD-EXC-{uuid.uuid4().hex[:4]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="Budget Exception Guard", entity_type="BUDGET_OVERRUN", min_amount=Decimal("1.0"), step_number=1, approver_user_id=approver.id)
    )
    req_bud = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="BUDGET_OVERRUN", entity_id=bud_id, document_reference=bud_id, total_amount=Decimal("15000.0"))
    )
    with pytest.raises(HTTPException):
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="BUDGET_OVERRUN", entity_id=bud_id)
    await ApprovalService.process_step_action(db_session, tenant_id, req_bud.id, approver.id, ApprovalActionRequest(action="APPROVE"))
    await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="BUDGET_OVERRUN", entity_id=bud_id)

    # 2. Asset Disposal
    asset_id = f"AST-DISP-{uuid.uuid4().hex[:4]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="Asset Disposal Guard", entity_type="ASSET_DISPOSAL", min_amount=Decimal("1.0"), step_number=1, approver_user_id=approver.id)
    )
    req_ast = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="ASSET_DISPOSAL", entity_id=asset_id, document_reference=asset_id, total_amount=Decimal("45000.0"))
    )
    with pytest.raises(HTTPException):
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="ASSET_DISPOSAL", entity_id=asset_id)
    await ApprovalService.process_step_action(db_session, tenant_id, req_ast.id, approver.id, ApprovalActionRequest(action="APPROVE"))
    await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="ASSET_DISPOSAL", entity_id=asset_id)

# ============================================================================
# 6. SLA TIMEOUT ESCALATION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_sla_timeout_escalation_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-sla-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="Short SLA Rule", entity_type="PURCHASE_ORDER", min_amount=Decimal("100.0"), step_number=1, approver_user_id=approver.id, sla_hours=1)
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id="PO-SLA-1", document_reference="PO-SLA-1", total_amount=Decimal("5000.0"))
    )
    assert req.status == "PENDING"

    # Simulate 2 hours elapsed (> 1 hour SLA)
    future_now = datetime.now(timezone.utc) + timedelta(hours=2)
    escalated_count = await ApprovalService.process_sla_escalations(db=db_session, tenant_id=tenant_id, simulated_now=future_now)
    assert escalated_count == 1

    # Verify request status transitioned to ESCALATED
    updated_req = (await db_session.execute(select(ApprovalRequest).where(ApprovalRequest.id == req.id))).scalar_one()
    assert updated_req.status == "ESCALATED"

    # Repeated execution -> Idempotent, zero duplicate escalations
    repeat_count = await ApprovalService.process_sla_escalations(db=db_session, tenant_id=tenant_id, simulated_now=future_now)
    assert repeat_count == 0

# ============================================================================
# 7. DELEGATION + SLA INTERACTION & DATE BOUNDARIES
# ============================================================================

@pytest.mark.asyncio
async def test_delegation_plus_sla_interaction_and_date_boundaries(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    approver_a = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-a-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver A", is_active=True)
    delegate_b = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"del-b-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Delegate B", is_active=True)
    outsider_c = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"out-c-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Outsider C", is_active=True)
    db_session.add_all([approver_a, delegate_b, outsider_c])
    await db_session.commit()

    # Rule assigned to Approver A
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="Delegated Rule", entity_type="PURCHASE_ORDER", min_amount=Decimal("100.0"), step_number=1, approver_user_id=approver_a.id)
    )

    # Active delegation window for Delegate B (today is valid)
    today = date.today()
    await ApprovalService.create_delegation(
        db=db_session, tenant_id=tenant_id, user_id=approver_a.id,
        del_in=ApprovalDelegationCreate(
            delegate_user_id=delegate_b.id,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=5),
            reason="Vacation"
        )
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id="PO-DEL-1", document_reference="PO-DEL-1", total_amount=Decimal("3000.0"))
    )

    # Outsider C cannot approve -> HTTP 403
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.process_step_action(
            db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=outsider_c.id,
            action_in=ApprovalActionRequest(action="APPROVE")
        )
    assert exc_info.value.status_code == 403

    # Delegate B approves successfully within active delegation window
    del_res = await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=delegate_b.id,
        action_in=ApprovalActionRequest(action="APPROVE", comments="Approved as delegate")
    )
    assert del_res.status == "APPROVED"
    assert del_res.steps[0].action_by_user_id == delegate_b.id

# ============================================================================
# 8. REJECTION + PERMANENT RELEASE LOCK
# ============================================================================

@pytest.mark.asyncio
async def test_rejection_and_permanent_release_lock(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    approver = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"appr-rej-{uuid.uuid4().hex[:4]}@aurastock.io", password_hash="pw", full_name="Approver User", is_active=True)
    db_session.add(approver)
    await db_session.commit()

    po_id = f"PO-REJ-{uuid.uuid4().hex[:6]}"
    await ApprovalService.create_approval_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=ApprovalRuleCreate(rule_name="Rejection Guard", entity_type="PURCHASE_ORDER", min_amount=Decimal("500.0"), step_number=1, approver_user_id=approver.id)
    )

    req = await ApprovalService.submit_for_approval(
        db=db_session, tenant_id=tenant_id,
        req_in=ApprovalRequestCreate(entity_type="PURCHASE_ORDER", entity_id=po_id, document_reference=po_id, total_amount=Decimal("15000.0"))
    )

    # Reject step
    rej_res = await ApprovalService.process_step_action(
        db=db_session, tenant_id=tenant_id, request_id=req.id, user_id=approver.id,
        action_in=ApprovalActionRequest(action="REJECT", comments="Supplier price unacceptable")
    )
    assert rej_res.status == "REJECTED"

    # Document execution remains PERMANENTLY BLOCKED
    with pytest.raises(HTTPException) as exc_info:
        await ApprovalService.validate_document_release(db=db_session, tenant_id=tenant_id, entity_type="PURCHASE_ORDER", entity_id=po_id)
    assert exc_info.value.status_code == 400
    assert "Approval status is 'REJECTED'" in exc_info.value.detail
