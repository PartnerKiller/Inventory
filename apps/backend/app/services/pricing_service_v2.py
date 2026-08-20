import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.pricing_v2 import PriceRule, RebateAgreement
from app.models.invoicing import CustomerCreditNote
from app.models.general_ledger import GLAccount
from app.schemas.pricing_v2 import (
    PriceRuleCreate,
    PriceRuleResponse,
    PriceQuoteRequest,
    PriceQuoteResponse,
    RebateAgreementCreate,
    RebateAgreementResponse,
    SettleRebateRequest
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

class PricingServiceV2:

    # ========================================================================
    # 1. DYNAMIC PRICE RULES & RESOLUTION
    # ========================================================================

    @staticmethod
    async def create_price_rule(
        db: AsyncSession,
        tenant_id: str,
        rule_in: PriceRuleCreate
    ) -> PriceRuleResponse:
        rule = PriceRule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rule_name=rule_in.rule_name,
            customer_id=rule_in.customer_id,
            customer_group=rule_in.customer_group.upper() if rule_in.customer_group else None,
            item_id=rule_in.item_id,
            min_quantity=rule_in.min_quantity,
            max_quantity=rule_in.max_quantity,
            discount_type=rule_in.discount_type.upper(),
            discount_value=rule_in.discount_value,
            start_date=rule_in.start_date,
            end_date=rule_in.end_date,
            priority=rule_in.priority,
            is_active=True
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)

        return PriceRuleResponse(
            id=rule.id,
            tenant_id=rule.tenant_id,
            rule_name=rule.rule_name,
            customer_id=rule.customer_id,
            customer_group=rule.customer_group,
            item_id=rule.item_id,
            min_quantity=rule.min_quantity,
            max_quantity=rule.max_quantity,
            discount_type=rule.discount_type,
            discount_value=rule.discount_value,
            start_date=rule.start_date,
            end_date=rule.end_date,
            priority=rule.priority,
            is_active=rule.is_active,
            created_at=rule.created_at
        )

    @staticmethod
    async def resolve_unit_price(
        db: AsyncSession,
        tenant_id: str,
        req: PriceQuoteRequest
    ) -> PriceQuoteResponse:
        o_date = req.order_date or date.today()
        grp = req.customer_group.upper() if req.customer_group else None

        # Query applicable active rules
        query = select(PriceRule).where(
            PriceRule.tenant_id == tenant_id,
            PriceRule.item_id == req.item_id,
            PriceRule.is_active == True,
            PriceRule.min_quantity <= req.quantity,
            or_(PriceRule.max_quantity == None, PriceRule.max_quantity >= req.quantity)
        )
        # Date validity filter
        query = query.where(
            or_(PriceRule.start_date == None, PriceRule.start_date <= o_date),
            or_(PriceRule.end_date == None, PriceRule.end_date >= o_date)
        )

        all_rules = (await db.execute(query)).scalars().all()

        # Match hierarchy: Customer Contract > Customer Group > Global
        matching_rules = []
        for r in all_rules:
            if r.customer_id and r.customer_id == req.customer_id:
                matching_rules.append((3, r.priority, r))
            elif r.customer_group and grp and r.customer_group == grp:
                matching_rules.append((2, r.priority, r))
            elif not r.customer_id and not r.customer_group:
                matching_rules.append((1, r.priority, r))

        # Sort by hierarchy tier desc, then priority desc, then min_quantity desc
        matching_rules.sort(key=lambda x: (x[0], x[1], x[2].min_quantity), reverse=True)

        if not matching_rules:
            # Base price fallback
            return PriceQuoteResponse(
                item_id=req.item_id,
                quantity=req.quantity,
                base_unit_price=req.base_price,
                resolved_unit_price=req.base_price,
                total_line_amount=(req.base_price * req.quantity).quantize(Decimal("0.0001")),
                discount_applied=Decimal("0.0"),
                discount_percentage=Decimal("0.0"),
                applied_rule_id=None,
                rule_name=None
            )

        best_rule: PriceRule = matching_rules[0][2]
        base_p = req.base_price

        if best_rule.discount_type == "PERCENTAGE":
            resolved = (base_p * (Decimal("1.0") - (best_rule.discount_value / Decimal("100.0")))).quantize(Decimal("0.0001"))
        elif best_rule.discount_type == "FIXED_PRICE":
            resolved = best_rule.discount_value.quantize(Decimal("0.0001"))
        elif best_rule.discount_type == "AMOUNT_OFF":
            resolved = max(Decimal("0.0"), base_p - best_rule.discount_value).quantize(Decimal("0.0001"))
        else:
            resolved = base_p

        discount_app = max(Decimal("0.0"), base_p - resolved)
        discount_pct = ((discount_app / base_p) * Decimal("100.0")).quantize(Decimal("0.01")) if base_p > Decimal("0.0") else Decimal("0.0")

        return PriceQuoteResponse(
            item_id=req.item_id,
            quantity=req.quantity,
            base_unit_price=base_p,
            resolved_unit_price=resolved,
            total_line_amount=(resolved * req.quantity).quantize(Decimal("0.0001")),
            discount_applied=discount_app,
            discount_percentage=discount_pct,
            applied_rule_id=best_rule.id,
            rule_name=best_rule.rule_name
        )

    # ========================================================================
    # 2. REBATE AGREEMENTS & SETTLEMENT ENGINE
    # ========================================================================

    @staticmethod
    async def create_rebate_agreement(
        db: AsyncSession,
        tenant_id: str,
        ag_in: RebateAgreementCreate
    ) -> RebateAgreementResponse:
        existing = (await db.execute(
            select(RebateAgreement).where(
                RebateAgreement.tenant_id == tenant_id,
                RebateAgreement.agreement_code == ag_in.agreement_code.upper()
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Rebate agreement '{ag_in.agreement_code}' already exists")

        agreement = RebateAgreement(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            agreement_code=ag_in.agreement_code.upper(),
            customer_id=ag_in.customer_id,
            start_date=ag_in.start_date,
            end_date=ag_in.end_date,
            target_spend_threshold=ag_in.target_spend_threshold,
            rebate_percentage=ag_in.rebate_percentage,
            status="ACTIVE",
            settled_amount=Decimal("0.0"),
            notes=ag_in.notes
        )
        db.add(agreement)
        await db.commit()
        await db.refresh(agreement)

        return RebateAgreementResponse(
            id=agreement.id,
            tenant_id=agreement.tenant_id,
            agreement_code=agreement.agreement_code,
            customer_id=agreement.customer_id,
            start_date=agreement.start_date,
            end_date=agreement.end_date,
            target_spend_threshold=agreement.target_spend_threshold,
            rebate_percentage=agreement.rebate_percentage,
            status=agreement.status,
            settled_amount=agreement.settled_amount,
            credit_note_id=agreement.credit_note_id,
            notes=agreement.notes,
            created_at=agreement.created_at
        )

    @staticmethod
    async def calculate_and_settle_rebate(
        db: AsyncSession,
        tenant_id: str,
        agreement_id: str,
        settle_in: SettleRebateRequest,
        user_id: Optional[str] = None
    ) -> RebateAgreementResponse:
        agreement = (await db.execute(
            select(RebateAgreement).where(
                RebateAgreement.id == agreement_id,
                RebateAgreement.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not agreement:
            raise HTTPException(status_code=404, detail="Rebate agreement not found")

        if agreement.status == "SETTLED":
            raise HTTPException(status_code=400, detail="Rebate agreement is already settled")

        spend = settle_in.actual_qualifying_spend or Decimal("0.0")

        # Threshold Check: If spend < target_spend_threshold -> 0 rebate
        if spend < agreement.target_spend_threshold:
            return RebateAgreementResponse(
                id=agreement.id,
                tenant_id=agreement.tenant_id,
                agreement_code=agreement.agreement_code,
                customer_id=agreement.customer_id,
                start_date=agreement.start_date,
                end_date=agreement.end_date,
                target_spend_threshold=agreement.target_spend_threshold,
                rebate_percentage=agreement.rebate_percentage,
                status=agreement.status,
                settled_amount=Decimal("0.0"),
                credit_note_id=agreement.credit_note_id,
                notes=agreement.notes,
                created_at=agreement.created_at
            )

        rebate_amount = (spend * (agreement.rebate_percentage / Decimal("100.0"))).quantize(Decimal("0.0001"))

        # Issue Customer Credit Note
        cn = CustomerCreditNote(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            credit_note_number=f"CN-REB-{uuid.uuid4().hex[:6].upper()}",
            customer_id=agreement.customer_id,
            amount=rebate_amount,
            notes=f"Volume Rebate Settlement for Agreement {agreement.agreement_code}",
            status="ISSUED"
        )
        db.add(cn)

        # Post GL Accounting: Dr 4100 Sales Rebates / Cr 1200 Accounts Receivable
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_4100 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "4100"))).scalar_one_or_none()
        if not acc_4100:
            # Create standard sales rebates contra-revenue account if missing
            acc_4100 = GLAccount(
                id=str(uuid.uuid4()), tenant_id=tenant_id, account_code="4100",
                account_name="Sales Discounts & Rebates", account_class="REVENUE",
                account_type="OPERATING_REVENUE", currency="USD", normal_balance="DEBIT",
                is_active=True, is_system=True
            )
            db.add(acc_4100)
            await db.commit()
            await db.refresh(acc_4100)

        acc_1200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200"))).scalar_one()

        await GLService.post_journal_voucher(
            db=db,
            tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=get_utc_now(),
                source_document_type="CUSTOMER_REBATE",
                source_document_id=cn.credit_note_number,
                notes=f"Volume Rebate Settlement {agreement.agreement_code}",
                lines=[
                    JournalEntryLineCreate(account_id=acc_4100.id, debit_amount=rebate_amount, credit_amount=Decimal("0.0"), memo="Customer volume rebate"),
                    JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("0.0"), credit_amount=rebate_amount, memo="AR reduction via rebate credit note")
                ]
            ),
            user_id=user_id
        )

        agreement.status = "SETTLED"
        agreement.settled_amount = rebate_amount
        agreement.credit_note_id = cn.id
        await db.commit()
        await db.refresh(agreement)

        return RebateAgreementResponse(
            id=agreement.id,
            tenant_id=agreement.tenant_id,
            agreement_code=agreement.agreement_code,
            customer_id=agreement.customer_id,
            start_date=agreement.start_date,
            end_date=agreement.end_date,
            target_spend_threshold=agreement.target_spend_threshold,
            rebate_percentage=agreement.rebate_percentage,
            status=agreement.status,
            settled_amount=agreement.settled_amount,
            credit_note_id=agreement.credit_note_id,
            notes=agreement.notes,
            created_at=agreement.created_at
        )
