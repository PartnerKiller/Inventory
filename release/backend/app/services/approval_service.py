import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.auth import User, Role, user_roles_table
from app.models.approval import ApprovalRule, ApprovalRequest, ApprovalStep, ApprovalDelegation
from app.schemas.approval import (
    ApprovalRuleCreate,
    ApprovalRuleResponse,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    ApprovalStepResponse,
    ApprovalActionRequest,
    ApprovalDelegationCreate,
    ApprovalDelegationResponse
)

class ApprovalService:

    # ========================================================================
    # 1. APPROVAL RULES & DELEGATIONS
    # ========================================================================

    @staticmethod
    async def create_approval_rule(
        db: AsyncSession,
        tenant_id: str,
        rule_in: ApprovalRuleCreate
    ) -> ApprovalRuleResponse:
        rule = ApprovalRule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rule_name=rule_in.rule_name,
            entity_type=rule_in.entity_type.upper(),
            min_amount=rule_in.min_amount,
            max_amount=rule_in.max_amount,
            cost_center_id=rule_in.cost_center_id,
            step_number=rule_in.step_number,
            approver_role_id=rule_in.approver_role_id,
            approver_user_id=rule_in.approver_user_id,
            sla_hours=rule_in.sla_hours,
            is_active=True
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)

        return ApprovalRuleResponse(
            id=rule.id,
            tenant_id=rule.tenant_id,
            rule_name=rule.rule_name,
            entity_type=rule.entity_type,
            min_amount=rule.min_amount,
            max_amount=rule.max_amount,
            cost_center_id=rule.cost_center_id,
            step_number=rule.step_number,
            approver_role_id=rule.approver_role_id,
            approver_user_id=rule.approver_user_id,
            sla_hours=rule.sla_hours,
            is_active=rule.is_active,
            created_at=rule.created_at
        )

    @staticmethod
    async def create_delegation(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        del_in: ApprovalDelegationCreate
    ) -> ApprovalDelegationResponse:
        if user_id == del_in.delegate_user_id:
            raise HTTPException(status_code=400, detail="Cannot delegate approval authority to oneself")

        delegation = ApprovalDelegation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            delegate_user_id=del_in.delegate_user_id,
            start_date=del_in.start_date,
            end_date=del_in.end_date,
            reason=del_in.reason,
            is_active=True
        )
        db.add(delegation)
        await db.commit()
        await db.refresh(delegation)

        return ApprovalDelegationResponse(
            id=delegation.id,
            tenant_id=delegation.tenant_id,
            user_id=delegation.user_id,
            delegate_user_id=delegation.delegate_user_id,
            start_date=delegation.start_date,
            end_date=delegation.end_date,
            reason=delegation.reason,
            is_active=delegation.is_active,
            created_at=delegation.created_at
        )

    # ========================================================================
    # 2. APPROVAL REQUEST INITIATION & MULTI-STEP WORKFLOW
    # ========================================================================

    @staticmethod
    async def submit_for_approval(
        db: AsyncSession,
        tenant_id: str,
        req_in: ApprovalRequestCreate,
        user_id: Optional[str] = None
    ) -> ApprovalRequestResponse:
        # Query active rules for entity and amount
        query = select(ApprovalRule).where(
            ApprovalRule.tenant_id == tenant_id,
            ApprovalRule.entity_type == req_in.entity_type.upper(),
            ApprovalRule.is_active == True,
            ApprovalRule.min_amount <= req_in.total_amount,
            or_(ApprovalRule.max_amount == None, ApprovalRule.max_amount >= req_in.total_amount)
        )
        if req_in.cost_center_id:
            query = query.where(
                or_(ApprovalRule.cost_center_id == None, ApprovalRule.cost_center_id == req_in.cost_center_id)
            )
        else:
            query = query.where(ApprovalRule.cost_center_id == None)

        query = query.order_by(ApprovalRule.step_number.asc())
        rules = (await db.execute(query)).scalars().all()

        if not rules:
            # Auto-approved: No applicable approval rules configured
            req = ApprovalRequest(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                entity_type=req_in.entity_type.upper(),
                entity_id=req_in.entity_id,
                document_reference=req_in.document_reference,
                requested_by_user_id=user_id,
                total_amount=req_in.total_amount,
                cost_center_id=req_in.cost_center_id,
                status="APPROVED",
                current_step_number=0,
                total_steps=0
            )
            db.add(req)
            await db.commit()
            await db.refresh(req)

            return ApprovalRequestResponse(
                id=req.id,
                tenant_id=req.tenant_id,
                entity_type=req.entity_type,
                entity_id=req.entity_id,
                document_reference=req.document_reference,
                requested_by_user_id=req.requested_by_user_id,
                total_amount=req.total_amount,
                cost_center_id=req.cost_center_id,
                status=req.status,
                current_step_number=req.current_step_number,
                total_steps=req.total_steps,
                steps=[],
                created_at=req.created_at
            )

        # Create multi-step approval request
        req = ApprovalRequest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_type=req_in.entity_type.upper(),
            entity_id=req_in.entity_id,
            document_reference=req_in.document_reference,
            requested_by_user_id=user_id,
            total_amount=req_in.total_amount,
            cost_center_id=req_in.cost_center_id,
            status="PENDING",
            current_step_number=1,
            total_steps=len(rules)
        )
        db.add(req)

        step_responses = []
        for r in rules:
            step = ApprovalStep(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                request_id=req.id,
                step_number=r.step_number,
                approver_user_id=r.approver_user_id,
                assigned_role_id=r.approver_role_id,
                status="PENDING"
            )
            db.add(step)
            step_responses.append(step)

        await db.commit()
        await db.refresh(req)

        return ApprovalRequestResponse(
            id=req.id,
            tenant_id=req.tenant_id,
            entity_type=req.entity_type,
            entity_id=req.entity_id,
            document_reference=req.document_reference,
            requested_by_user_id=req.requested_by_user_id,
            total_amount=req.total_amount,
            cost_center_id=req.cost_center_id,
            status=req.status,
            current_step_number=req.current_step_number,
            total_steps=req.total_steps,
            steps=[
                ApprovalStepResponse(
                    id=s.id,
                    request_id=s.request_id,
                    step_number=s.step_number,
                    approver_user_id=s.approver_user_id,
                    assigned_role_id=s.assigned_role_id,
                    status=s.status,
                    action_by_user_id=s.action_by_user_id,
                    action_taken_at=s.action_taken_at,
                    comments=s.comments
                ) for s in step_responses
            ],
            created_at=req.created_at
        )

    # ========================================================================
    # 3. APPROVAL ACTION PROCESSING & DELEGATION VALIDATION
    # ========================================================================

    @staticmethod
    async def process_step_action(
        db: AsyncSession,
        tenant_id: str,
        request_id: str,
        user_id: str,
        action_in: ApprovalActionRequest
    ) -> ApprovalRequestResponse:
        req = (await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.id == request_id,
                ApprovalRequest.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not req:
            raise HTTPException(status_code=404, detail="Approval request not found")

        if req.status not in {"PENDING", "IN_REVIEW", "ESCALATED"}:
            raise HTTPException(status_code=400, detail=f"Cannot act on approval request in '{req.status}' state")

        curr_step = (await db.execute(
            select(ApprovalStep).where(
                ApprovalStep.request_id == req.id,
                ApprovalStep.step_number == req.current_step_number
            ).with_for_update()
        )).scalar_one_or_none()

        if not curr_step:
            raise HTTPException(status_code=404, detail="Current approval step not found")

        # Validate Approver Authorization (Direct User, Assigned Role, or Active Delegation)
        is_authorized = False
        if curr_step.approver_user_id == user_id:
            is_authorized = True
        elif curr_step.assigned_role_id:
            # Check user role
            has_role = (await db.execute(
                select(user_roles_table).where(
                    user_roles_table.c.user_id == user_id,
                    user_roles_table.c.role_id == curr_step.assigned_role_id
                )
            )).first()
            if has_role:
                is_authorized = True

        if not is_authorized and curr_step.approver_user_id:
            # Check active out-of-office delegation
            today = date.today()
            delegation = (await db.execute(
                select(ApprovalDelegation).where(
                    ApprovalDelegation.tenant_id == tenant_id,
                    ApprovalDelegation.user_id == curr_step.approver_user_id,
                    ApprovalDelegation.delegate_user_id == user_id,
                    ApprovalDelegation.start_date <= today,
                    ApprovalDelegation.end_date >= today,
                    ApprovalDelegation.is_active == True
                )
            )).scalar_one_or_none()
            if delegation:
                is_authorized = True

        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not authorized to act on this approval step"
            )

        # Process Action
        action_upper = action_in.action.upper()
        curr_step.action_by_user_id = user_id
        curr_step.action_taken_at = get_utc_now()
        curr_step.comments = action_in.comments

        if action_upper == "REJECT":
            curr_step.status = "REJECTED"
            req.status = "REJECTED"
        elif action_upper == "APPROVE":
            curr_step.status = "APPROVED"
            if req.current_step_number < req.total_steps:
                req.current_step_number += 1
                req.status = "IN_REVIEW"
            else:
                req.status = "APPROVED"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid action '{action_in.action}'")

        await db.commit()
        await db.refresh(req)

        steps = (await db.execute(
            select(ApprovalStep).where(ApprovalStep.request_id == req.id).order_by(ApprovalStep.step_number.asc())
        )).scalars().all()

        return ApprovalRequestResponse(
            id=req.id,
            tenant_id=req.tenant_id,
            entity_type=req.entity_type,
            entity_id=req.entity_id,
            document_reference=req.document_reference,
            requested_by_user_id=req.requested_by_user_id,
            total_amount=req.total_amount,
            cost_center_id=req.cost_center_id,
            status=req.status,
            current_step_number=req.current_step_number,
            total_steps=req.total_steps,
            steps=[
                ApprovalStepResponse(
                    id=s.id,
                    request_id=s.request_id,
                    step_number=s.step_number,
                    approver_user_id=s.approver_user_id,
                    assigned_role_id=s.assigned_role_id,
                    status=s.status,
                    action_by_user_id=s.action_by_user_id,
                    action_taken_at=s.action_taken_at,
                    comments=s.comments
                ) for s in steps
            ],
            created_at=req.created_at
        )

    # ========================================================================
    # 4. DOCUMENT RELEASE LOCK & SLA ESCALATION ENGINE
    # ========================================================================

    @staticmethod
    async def validate_document_release(
        db: AsyncSession,
        tenant_id: str,
        entity_type: str,
        entity_id: str
    ) -> None:
        """Enforces that a document with an approval workflow must be APPROVED prior to execution/posting."""
        req = (await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.entity_type == entity_type.upper(),
                ApprovalRequest.entity_id == entity_id
            ).order_by(ApprovalRequest.created_at.desc())
        )).scalars().first()

        if req and req.status != "APPROVED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document Release Prohibited: Approval status is '{req.status}'. Final approval is required before execution."
            )

    @staticmethod
    async def process_sla_escalations(
        db: AsyncSession,
        tenant_id: str,
        simulated_now: Optional[datetime] = None
    ) -> int:
        """Identifies pending approval requests that have exceeded their SLA window and escalates them idempotently."""
        now = simulated_now or get_utc_now()
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        pending_requests = (await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status.in_(["PENDING", "IN_REVIEW"])
            ).with_for_update()
        )).scalars().all()

        escalated_count = 0
        for req in pending_requests:
            curr_step = (await db.execute(
                select(ApprovalStep).where(
                    ApprovalStep.request_id == req.id,
                    ApprovalStep.step_number == req.current_step_number
                ).with_for_update()
            )).scalar_one_or_none()

            if curr_step and curr_step.status == "PENDING":
                # Find SLA hours from matching rule
                rule = (await db.execute(
                    select(ApprovalRule).where(
                        ApprovalRule.tenant_id == tenant_id,
                        ApprovalRule.entity_type == req.entity_type,
                        ApprovalRule.step_number == req.current_step_number
                    )
                )).scalars().first()
                sla_h = rule.sla_hours if rule else 24

                # Normalize created_at for offset-naive comparison
                created_at = req.created_at
                if hasattr(created_at, "tzinfo") and created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)

                # Check if elapsed time exceeds SLA
                if created_at + timedelta(hours=sla_h) <= now:
                    req.status = "ESCALATED"
                    curr_step.status = "ESCALATED"
                    escalated_count += 1

        if escalated_count > 0:
            await db.commit()

        return escalated_count
