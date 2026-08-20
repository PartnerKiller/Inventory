import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.sales import Customer, SalesOrder, SOLineItem
from app.models.purchasing import PurchaseOrder, POLineItem, Supplier
from app.models.warehouse import Warehouse
from app.models.intercompany import IntercompanyPartner, IntercompanyTransactionPair, ConsolidationRun
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.schemas.intercompany import (
    IntercompanyPartnerCreate,
    MirroredOrderCreate,
    ConsolidationRunCreate
)
from app.services.intercompany_service import IntercompanyService
from app.services.gl_service import GLService

# ============================================================================
# 1. TRADING PARTNER RELATIONSHIP & VALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_intercompany_partner_creation_and_validation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # 1. Successful partner pair creation (Entity HQ -> Entity SUB1)
    partner = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="HQ to SUB1 Trading Agreement",
            seller_company_id="ENTITY_HQ",
            buyer_company_id="ENTITY_SUB1",
            transfer_pricing_type="COST_PLUS",
            markup_percentage=Decimal("15.0")
        )
    )
    assert partner.seller_company_id == "ENTITY_HQ"
    assert partner.buyer_company_id == "ENTITY_SUB1"
    assert partner.markup_percentage == Decimal("15.0")
    assert partner.ar_intercompany_account_id is not None
    assert partner.ap_intercompany_account_id is not None

    # 2. Self-trading prohibited (Entity HQ -> Entity HQ) -> HTTP 400
    with pytest.raises(HTTPException) as exc_info:
        await IntercompanyService.create_partner_relationship(
            db=db_session, tenant_id=tenant_id,
            partner_in=IntercompanyPartnerCreate(
                partner_name="Self Trading",
                seller_company_id="ENTITY_HQ",
                buyer_company_id="ENTITY_HQ",
                transfer_pricing_type="COST_PLUS"
            )
        )
    assert exc_info.value.status_code == 400
    assert "distinct" in exc_info.value.detail

    # 3. Negative markup rejected -> HTTP 400
    with pytest.raises(HTTPException) as exc_info_neg:
        await IntercompanyService.create_partner_relationship(
            db=db_session, tenant_id=tenant_id,
            partner_in=IntercompanyPartnerCreate(
                partner_name="Negative Markup",
                seller_company_id="ENTITY_A",
                buyer_company_id="ENTITY_B",
                transfer_pricing_type="COST_PLUS",
                markup_percentage=Decimal("-5.0")
            )
        )
    assert exc_info_neg.value.status_code == 400
    assert "negative" in exc_info_neg.value.detail

# ============================================================================
# 2. MIRRORED ORDER GENERATION, TRANSFER PRICING & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_mirrored_order_generation_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="HQ Warehouse", code=f"WH-HQ-{uuid.uuid4().hex[:4]}", is_active=True)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Internal Sub 1 Customer", code=f"CUST-INT-{uuid.uuid4().hex[:4]}", is_active=True)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-IC-{uuid.uuid4().hex[:4]}", name="Intercompany Widget", base_uom="PCS", is_active=True)
    db_session.add_all([wh, cust, item])
    await db_session.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"VAR-{item.sku}",
        variant_name="Default Variant",
        attributes={},
        cost_price=Decimal("80.0"),
        selling_price=Decimal("100.0")
    )
    db_session.add(variant)
    await db_session.commit()

    # Partner relationship with 15% markup
    partner = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="Global HQ to Sub 1",
            seller_company_id="CORP_HQ",
            buyer_company_id="CORP_SUB1",
            transfer_pricing_type="COST_PLUS",
            markup_percentage=Decimal("15.0")
        )
    )

    # Create Sales Order in Seller Entity (10 units @ $100 base = $1,000)
    so = SalesOrder(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        so_number=f"SO-IC-{uuid.uuid4().hex[:6].upper()}",
        customer_id=cust.id,
        warehouse_id=wh.id,
        status="CONFIRMED",
        total_amount=Decimal("1000.0")
    )
    db_session.add(so)
    await db_session.flush()

    so_item = SOLineItem(
        id=str(uuid.uuid4()),
        sales_order_id=so.id,
        item_variant_id=variant.id,
        quantity_ordered=Decimal("10.0"),
        unit_price=Decimal("100.0"),
        line_total=Decimal("1000.0")
    )
    db_session.add(so_item)
    await db_session.commit()

    # 1. Generate mirrored Purchase Order in Buyer Entity
    pair_res_1 = await IntercompanyService.create_mirrored_intercompany_order(
        db=db_session, tenant_id=tenant_id,
        req=MirroredOrderCreate(partner_id=partner.id, seller_sales_order_id=so.id),
        user_id=user_id
    )

    # Total with 15% markup = $100 * 1.15 * 10 = $1,150.00
    assert pair_res_1.transfer_amount == Decimal("1150.0")
    assert pair_res_1.status == "LINKED"

    # Verify mirrored Purchase Order exists
    po = (await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.id == pair_res_1.purchase_order_id))).scalar_one()
    assert po.total_amount == Decimal("1150.0")
    assert len(po.lines) == 1
    assert po.lines[0].unit_price == Decimal("115.0")
    assert po.lines[0].quantity_ordered == Decimal("10.0")

    # 2. Idempotent retry: Exact same request must return existing pair without creating duplicate PO
    pair_res_2 = await IntercompanyService.create_mirrored_intercompany_order(
        db=db_session, tenant_id=tenant_id,
        req=MirroredOrderCreate(partner_id=partner.id, seller_sales_order_id=so.id),
        user_id=user_id
    )
    assert pair_res_2.id == pair_res_1.id
    assert pair_res_2.purchase_order_id == pair_res_1.purchase_order_id

    # Verify total PO count remains exactly 1
    po_count = (await db_session.execute(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.po_number == po.po_number)
    )).scalar()
    assert po_count == 1

# ============================================================================
# 3. CONSOLIDATION ELIMINATION JOURNAL ENGINE & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_consolidation_elimination_journal_engine_and_idempotency(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Consolidation WH", code=f"WH-CNS-{uuid.uuid4().hex[:4]}", is_active=True)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Consolidation Cust", code=f"CUST-CNS-{uuid.uuid4().hex[:4]}", is_active=True)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-CNS-{uuid.uuid4().hex[:4]}", name="Consolidation Item", base_uom="PCS", is_active=True)
    
    # Fiscal Year & Accounting Period
    fy = FiscalYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_code=f"FY-{uuid.uuid4().hex[:4].upper()}",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN"
    )
    db_session.add(fy)
    await db_session.flush()

    period = AccountingPeriod(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_id=fy.id,
        period_code=f"FY26-M{uuid.uuid4().hex[:3].upper()}",
        period_number=8,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        status="OPEN"
    )
    db_session.add_all([wh, cust, item, period])
    await db_session.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"VAR-{item.sku}",
        variant_name="Default Variant",
        attributes={},
        cost_price=Decimal("80.0"),
        selling_price=Decimal("100.0")
    )
    db_session.add(variant)
    await db_session.commit()

    partner = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="HQ to SUB2",
            seller_company_id="CORP_HQ",
            buyer_company_id="CORP_SUB2",
            transfer_pricing_type="COST_PLUS",
            markup_percentage=Decimal("20.0")
        )
    )

    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-CNS-{uuid.uuid4().hex[:4].upper()}", customer_id=cust.id, warehouse_id=wh.id, status="CONFIRMED", total_amount=Decimal("5000.0"))
    db_session.add(so)
    await db_session.flush()
    so_item = SOLineItem(id=str(uuid.uuid4()), sales_order_id=so.id, item_variant_id=variant.id, quantity_ordered=Decimal("50.0"), unit_price=Decimal("100.0"), line_total=Decimal("5000.0"))
    db_session.add(so_item)
    await db_session.commit()

    # Create mirrored order: $5,000 + 20% = $6,000
    pair = await IntercompanyService.create_mirrored_intercompany_order(
        db=db_session, tenant_id=tenant_id,
        req=MirroredOrderCreate(partner_id=partner.id, seller_sales_order_id=so.id),
        user_id=user_id
    )
    assert pair.transfer_amount == Decimal("6000.0")

    # 1. First Consolidation Run
    cons_res_1 = await IntercompanyService.generate_consolidation_eliminations(
        db=db_session, tenant_id=tenant_id,
        cons_in=ConsolidationRunCreate(period_id=period.id, notes="Monthly group consolidation eliminations"),
        user_id=user_id
    )

    assert cons_res_1.status == "FINALIZED"
    assert cons_res_1.total_eliminated_amount == Decimal("6000.0")
    assert cons_res_1.elimination_voucher_id is not None

    # Verify balancing elimination JV lines
    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == cons_res_1.elimination_voucher_id))).scalar_one()
    assert sum(l.debit_amount for l in jv.lines) == cons_res_1.total_eliminated_amount * Decimal("2.0")
    assert sum(l.credit_amount for l in jv.lines) == cons_res_1.total_eliminated_amount * Decimal("2.0")
    assert len(jv.lines) == 4 # Dr 4000 / Cr 5000 and Dr 2300 / Cr 1300

    # 2. Second Consolidation Run on same period (Idempotency): No uneliminated pairs -> 0 eliminated, no duplicate JV
    cons_res_2 = await IntercompanyService.generate_consolidation_eliminations(
        db=db_session, tenant_id=tenant_id,
        cons_in=ConsolidationRunCreate(period_id=period.id, notes="Second run"),
        user_id=user_id
    )
    assert cons_res_2.status == "FINALIZED"
    assert cons_res_2.total_eliminated_amount == Decimal("0.0")
    assert cons_res_2.elimination_voucher_id is None

# ============================================================================
# 4. CLOSED ACCOUNTING PERIOD PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_closed_accounting_period_protection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    fy = FiscalYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_code=f"FY-CL-{uuid.uuid4().hex[:4].upper()}",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN"
    )
    db_session.add(fy)
    await db_session.flush()

    closed_period = AccountingPeriod(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_id=fy.id,
        period_code=f"FY26-CLOSED-{uuid.uuid4().hex[:3].upper()}",
        period_number=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        status="CLOSED"
    )
    db_session.add(closed_period)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await IntercompanyService.generate_consolidation_eliminations(
            db=db_session, tenant_id=tenant_id,
            cons_in=ConsolidationRunCreate(period_id=closed_period.id, notes="Attempt on closed period"),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "CLOSED" in exc_info.value.detail

# ============================================================================
# 5. TRANSFER PRICING VARIANTS (FIXED_PRICE & CATALOG)
# ============================================================================

@pytest.mark.asyncio
async def test_transfer_pricing_variants(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="WH Pricing", code=f"WH-PR-{uuid.uuid4().hex[:4]}", is_active=True)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Cust Pricing", code=f"CUST-PR-{uuid.uuid4().hex[:4]}", is_active=True)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-PR-{uuid.uuid4().hex[:4]}", name="Pricing Item", base_uom="PCS", is_active=True)
    db_session.add_all([wh, cust, item])
    await db_session.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item.id,
        variant_sku=f"VAR-{item.sku}",
        variant_name="Default Variant",
        attributes={},
        cost_price=Decimal("50.0"),
        selling_price=Decimal("100.0")
    )
    db_session.add(variant)
    await db_session.commit()

    # 1. FIXED_PRICE Partner
    partner_fp = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="Fixed Price Agreement",
            seller_company_id="CORP_HQ",
            buyer_company_id="CORP_FIXED",
            transfer_pricing_type="FIXED_PRICE"
        )
    )

    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-FP-{uuid.uuid4().hex[:4].upper()}", customer_id=cust.id, warehouse_id=wh.id, status="CONFIRMED", total_amount=Decimal("1000.0"))
    db_session.add(so)
    await db_session.flush()
    so_item = SOLineItem(id=str(uuid.uuid4()), sales_order_id=so.id, item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("100.0"), line_total=Decimal("1000.0"))
    db_session.add(so_item)
    await db_session.commit()

    pair_fp = await IntercompanyService.create_mirrored_intercompany_order(
        db=db_session, tenant_id=tenant_id,
        req=MirroredOrderCreate(partner_id=partner_fp.id, seller_sales_order_id=so.id),
        user_id=user_id
    )
    # Fixed price: Exact unit price without markup = $1,000.0
    assert pair_fp.transfer_amount == Decimal("1000.0")
