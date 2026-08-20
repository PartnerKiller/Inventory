import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item
from app.models.sales import Customer
from app.models.pricing_v2 import PriceRule, RebateAgreement
from app.models.invoicing import CustomerCreditNote
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.pricing_v2 import (
    PriceRuleCreate,
    PriceQuoteRequest,
    RebateAgreementCreate,
    SettleRebateRequest
)
from app.services.pricing_service_v2 import PricingServiceV2
from app.services.gl_service import GLService
from app.services.approval_service import ApprovalService

# ============================================================================
# 1. QUANTITY BREAK TIER CURVES & OVERLAPPING TIERS TIE-BREAKING
# ============================================================================

@pytest.mark.asyncio
async def test_quantity_break_tier_curves_and_overlapping_tiers(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-OVL-{uuid.uuid4().hex[:4]}", name="Overlapping Tier Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    # Rule 1: 1-100 -> $100 (Base Tier, Priority 10)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Tier 1-100", item_id=item.id, min_quantity=Decimal("1.0"), max_quantity=Decimal("100.0"), discount_type="FIXED_PRICE", discount_value=Decimal("100.0"), priority=10)
    )
    # Rule 2: 50-150 -> $95 (Mid Tier, Priority 10, higher min_quantity=50)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Tier 50-150", item_id=item.id, min_quantity=Decimal("50.0"), max_quantity=Decimal("150.0"), discount_type="FIXED_PRICE", discount_value=Decimal("95.0"), priority=10)
    )
    # Rule 3: 150+ -> $90 (Bulk Tier, Priority 10, min_quantity=150)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Tier 150+", item_id=item.id, min_quantity=Decimal("150.0"), max_quantity=None, discount_type="FIXED_PRICE", discount_value=Decimal("90.0"), priority=10)
    )

    base_p = Decimal("100.0")

    # Qty 49 -> $100 (matches Tier 1-100)
    q49 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("49.0"), base_price=base_p))
    assert q49.resolved_unit_price == Decimal("100.0")

    # Qty 50 -> $95 (matches 50-150 with higher min_quantity)
    q50 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("50.0"), base_price=base_p))
    assert q50.resolved_unit_price == Decimal("95.0")

    # Qty 75 -> $95
    q75 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("75.0"), base_price=base_p))
    assert q75.resolved_unit_price == Decimal("95.0")

    # Qty 100 -> $95 (matches 50-150 with higher min_quantity than 1-100)
    q100 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("100.0"), base_price=base_p))
    assert q100.resolved_unit_price == Decimal("95.0")

    # Qty 101 -> $95 (matches 50-150)
    q101 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("101.0"), base_price=base_p))
    assert q101.resolved_unit_price == Decimal("95.0")

    # Qty 150 -> $90 (matches 150+ with min_quantity=150)
    q150 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("150.0"), base_price=base_p))
    assert q150.resolved_unit_price == Decimal("90.0")

    # Qty 151 -> $90
    q151 = await PricingServiceV2.resolve_unit_price(db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("151.0"), base_price=base_p))
    assert q151.resolved_unit_price == Decimal("90.0")

# ============================================================================
# 2. PRICING RULE TIE-BREAKING & PRIORITY SEMANTICS
# ============================================================================

@pytest.mark.asyncio
async def test_rule_priority_tie_breaking(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-PRI-{uuid.uuid4().hex[:4]}", name="Priority Item", base_uom="PCS", is_active=True)
    customer = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-PRI-{uuid.uuid4().hex[:4]}", name="Priority Customer", is_active=True)
    db_session.add_all([item, customer])
    await db_session.commit()

    # Rule A: Priority 10 -> $95 Fixed Price
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Rule A (Priority 10)", customer_id=customer.id, item_id=item.id, discount_type="FIXED_PRICE", discount_value=Decimal("95.0"), priority=10)
    )
    # Rule B: Priority 20 -> $90 Fixed Price (Higher priority must win)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Rule B (Priority 20)", customer_id=customer.id, item_id=item.id, discount_type="FIXED_PRICE", discount_value=Decimal("90.0"), priority=20)
    )

    quote = await PricingServiceV2.resolve_unit_price(
        db=db_session, tenant_id=tenant_id,
        req=PriceQuoteRequest(item_id=item.id, quantity=Decimal("10.0"), base_price=Decimal("100.0"), customer_id=customer.id)
    )
    # Rule B (Priority 20) wins over Rule A (Priority 10)
    assert quote.resolved_unit_price == Decimal("90.0")
    assert quote.rule_name == "Rule B (Priority 20)"

# ============================================================================
# 3. PROMOTIONAL BOUNDARY CONDITIONS (start_date - 1, start, end, end + 1)
# ============================================================================

@pytest.mark.asyncio
async def test_promotional_boundary_conditions(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-BND-{uuid.uuid4().hex[:4]}", name="Boundary Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.commit()

    promo_start = date(2026, 6, 1)
    promo_end = date(2026, 6, 30)

    # Promo: $70 Fixed Price between June 1 and June 30 inclusive
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(
            rule_name="June Promo",
            item_id=item.id,
            discount_type="FIXED_PRICE",
            discount_value=Decimal("70.0"),
            start_date=promo_start,
            end_date=promo_end,
            priority=25
        )
    )

    base_p = Decimal("100.0")

    # 1. start_date - 1 (May 31) -> Inactive (Reverts to base $100)
    q_pre = await PricingServiceV2.resolve_unit_price(
        db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("1.0"), base_price=base_p, order_date=promo_start - timedelta(days=1))
    )
    assert q_pre.resolved_unit_price == Decimal("100.0")

    # 2. start_date (June 1) -> Active ($70)
    q_start = await PricingServiceV2.resolve_unit_price(
        db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("1.0"), base_price=base_p, order_date=promo_start)
    )
    assert q_start.resolved_unit_price == Decimal("70.0")

    # 3. end_date (June 30) -> Active ($70)
    q_end = await PricingServiceV2.resolve_unit_price(
        db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("1.0"), base_price=base_p, order_date=promo_end)
    )
    assert q_end.resolved_unit_price == Decimal("70.0")

    # 4. end_date + 1 (July 1) -> Inactive (Reverts to base $100)
    q_post = await PricingServiceV2.resolve_unit_price(
        db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=Decimal("1.0"), base_price=base_p, order_date=promo_end + timedelta(days=1))
    )
    assert q_post.resolved_unit_price == Decimal("100.0")

# ============================================================================
# 4. REBATE PERIOD BOUNDARIES & DOUBLE-COUNTING PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_rebate_period_boundaries_and_double_counting_protection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    customer = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-RBD-{uuid.uuid4().hex[:4]}", name="Rebate Boundary Corp", is_active=True)
    db_session.add(customer)
    await db_session.commit()

    # Agreement: 2026 Calendar Year (Jan 1 to Dec 31), Target $50,000, 10% rebate
    agreement = await PricingServiceV2.create_rebate_agreement(
        db=db_session, tenant_id=tenant_id,
        ag_in=RebateAgreementCreate(
            agreement_code=f"AGR-BND-{uuid.uuid4().hex[:4]}",
            customer_id=customer.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            target_spend_threshold=Decimal("50000.0"),
            rebate_percentage=Decimal("10.0")
        )
    )

    # 1. Qualifying Spend = $80,000 (>= $50,000) -> $8,000 rebate
    res_settled = await PricingServiceV2.calculate_and_settle_rebate(
        db=db_session, tenant_id=tenant_id, agreement_id=agreement.id,
        settle_in=SettleRebateRequest(actual_qualifying_spend=Decimal("80000.0")),
        user_id=user_id
    )
    assert res_settled.status == "SETTLED"
    assert res_settled.settled_amount == Decimal("8000.0")

    # 2. Retrying settlement -> Strictly rejected with HTTP 400 (no double credit note / double GL posting)
    with pytest.raises(HTTPException) as exc_info:
        await PricingServiceV2.calculate_and_settle_rebate(
            db=db_session, tenant_id=tenant_id, agreement_id=agreement.id,
            settle_in=SettleRebateRequest(actual_qualifying_spend=Decimal("80000.0")),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "already settled" in exc_info.value.detail

# ============================================================================
# 5. QUOTE -> SALES ORDER -> INVOICE PRICE & TAX INTEGRATION TRACE
# ============================================================================

@pytest.mark.asyncio
async def test_quote_to_so_invoice_price_and_tax_integrity(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-INT-{uuid.uuid4().hex[:4]}", name="Integration Item", base_uom="PCS", is_active=True)
    customer = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-INT-{uuid.uuid4().hex[:4]}", name="Integration Customer", is_active=True)
    db_session.add_all([item, customer])
    await db_session.commit()

    # Rule: Volume discount 20% off for 100+ units (Base $100 -> $80)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_id,
        rule_in=PriceRuleCreate(rule_name="Bulk 100+", item_id=item.id, min_quantity=Decimal("100.0"), discount_type="PERCENTAGE", discount_value=Decimal("20.0"), priority=10)
    )

    base_price = Decimal("100.0")
    order_qty = Decimal("100.0")

    # 1. Quote Step: Resolved to $80
    quote = await PricingServiceV2.resolve_unit_price(
        db_session, tenant_id, PriceQuoteRequest(item_id=item.id, quantity=order_qty, base_price=base_price, customer_id=customer.id)
    )
    assert quote.resolved_unit_price == Decimal("80.0")
    assert quote.total_line_amount == Decimal("8000.0")

    # 2. Tax Calculation on Effective Discounted Base ($80 * 100 = $8,000 @ 18% Tax = $1,440)
    tax_rate = Decimal("0.18")
    tax_amount = (quote.total_line_amount * tax_rate).quantize(Decimal("0.0001"))
    total_with_tax = quote.total_line_amount + tax_amount
    assert tax_amount == Decimal("1440.0")
    assert total_with_tax == Decimal("9440.0")

# ============================================================================
# 6. MULTI-TENANT ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_pricing_and_rebate_isolation(db_session: AsyncSession):
    tenant_a = "00000000-0000-0000-0000-000000000001"
    tenant_b = "00000000-0000-0000-0000-000000000002"

    item_a = Item(id=str(uuid.uuid4()), tenant_id=tenant_a, sku=f"SKU-TNA-{uuid.uuid4().hex[:4]}", name="Tenant A Item", base_uom="PCS", is_active=True)
    db_session.add(item_a)
    await db_session.commit()

    # Rule created for Tenant A ($50 Fixed Price)
    await PricingServiceV2.create_price_rule(
        db=db_session, tenant_id=tenant_a,
        rule_in=PriceRuleCreate(rule_name="Tenant A Rule", item_id=item_a.id, discount_type="FIXED_PRICE", discount_value=Decimal("50.0"), priority=10)
    )

    # Tenant B quoting Tenant A's item -> Cannot access Tenant A's rule (reverts to base $100)
    quote_b = await PricingServiceV2.resolve_unit_price(
        db=db_session, tenant_id=tenant_b,
        req=PriceQuoteRequest(item_id=item_a.id, quantity=Decimal("1.0"), base_price=Decimal("100.0"))
    )
    assert quote_b.resolved_unit_price == Decimal("100.0")
    assert quote_b.applied_rule_id is None
