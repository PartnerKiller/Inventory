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
from app.models.intercompany import IntercompanyPartner, IntercompanyTransactionPair, ConsolidationRun, UnrealizedProfitElimination
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.accounting_period import FiscalYear, AccountingPeriod
from app.schemas.intercompany import (
    IntercompanyPartnerCreate,
    MirroredOrderCreate,
    ConsolidationRunCreate,
    UnrealizedProfitEliminationCreate
)
from app.services.intercompany_service import IntercompanyService
from app.services.gl_service import GLService

# ============================================================================
# 1. UNREALIZED INTERCOMPANY PROFIT ELIMINATION & BALANCED JV
# ============================================================================

@pytest.mark.asyncio
async def test_unrealized_profit_calculation_and_elimination_jv(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    # 1. Setup Fiscal Year & Accounting Period
    fy = FiscalYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_code=f"FY-UNR-{uuid.uuid4().hex[:4].upper()}",
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
        period_code=f"FY26-UNR-{uuid.uuid4().hex[:3].upper()}",
        period_number=8,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        status="OPEN"
    )
    db_session.add(period)

    # 2. Setup Partner & Item
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-UNR-{uuid.uuid4().hex[:4]}", name="Unrealized Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    partner = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="HQ to SUB3 Agreement",
            seller_company_id="CORP_HQ",
            buyer_company_id="CORP_SUB3",
            transfer_pricing_type="COST_PLUS",
            markup_percentage=Decimal("15.0")
        )
    )

    # 3. 40 units remain on hand in buyer entity with $15 unit markup -> $600.00 unrealized profit
    elim_res = await IntercompanyService.eliminate_unrealized_inventory_profit(
        db=db_session,
        tenant_id=tenant_id,
        req=UnrealizedProfitEliminationCreate(
            period_id=period.id,
            partner_id=partner.id,
            item_id=item.id,
            on_hand_quantity=Decimal("40.0"),
            unit_markup=Decimal("15.0")
        ),
        user_id=user_id
    )

    assert elim_res.total_unrealized_profit == Decimal("600.0")
    assert elim_res.status == "POSTED"
    assert elim_res.elimination_voucher_id is not None

    # 4. Verify balanced elimination JV
    jv = (await db_session.execute(select(JournalVoucher).where(JournalVoucher.id == elim_res.elimination_voucher_id))).scalar_one()
    assert len(jv.lines) == 2
    assert jv.lines[0].debit_amount == Decimal("600.0") # Dr 5000 COGS
    assert jv.lines[1].credit_amount == Decimal("600.0") # Cr 1210 Inventory Reserve

# ============================================================================
# 2. CLOSED PERIOD REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_unrealized_profit_closed_period_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    fy = FiscalYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_code=f"FY-CL2-{uuid.uuid4().hex[:4].upper()}",
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
        period_code=f"FY26-CL2-{uuid.uuid4().hex[:3].upper()}",
        period_number=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        status="CLOSED"
    )
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-CL-{uuid.uuid4().hex[:4]}", name="Closed Item", base_uom="PCS", is_active=True)
    db_session.add_all([closed_period, item])
    await db_session.commit()

    partner = await IntercompanyService.create_partner_relationship(
        db=db_session, tenant_id=tenant_id,
        partner_in=IntercompanyPartnerCreate(
            partner_name="HQ to SUB4",
            seller_company_id="CORP_HQ",
            buyer_company_id="CORP_SUB4",
            transfer_pricing_type="COST_PLUS",
            markup_percentage=Decimal("10.0")
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await IntercompanyService.eliminate_unrealized_inventory_profit(
            db=db_session, tenant_id=tenant_id,
            req=UnrealizedProfitEliminationCreate(
                period_id=closed_period.id,
                partner_id=partner.id,
                item_id=item.id,
                on_hand_quantity=Decimal("10.0"),
                unit_markup=Decimal("10.0")
            ),
            user_id=user_id
        )
    assert exc_info.value.status_code == 400
    assert "closed" in exc_info.value.detail.lower()

# ============================================================================
# 3. CONSOLIDATED TRIAL BALANCE & FINANCIAL STATEMENTS
# ============================================================================

@pytest.mark.asyncio
async def test_consolidated_trial_balance_and_financial_statements(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    fy = FiscalYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        fiscal_year_code=f"FY-REP-{uuid.uuid4().hex[:4].upper()}",
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
        period_code=f"FY26-REP-{uuid.uuid4().hex[:3].upper()}",
        period_number=9,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status="OPEN"
    )
    db_session.add(period)
    await db_session.commit()

    # 1. Consolidated Trial Balance
    tb = await IntercompanyService.get_consolidated_trial_balance(
        db=db_session, tenant_id=tenant_id, period_id=period.id
    )
    assert tb.is_balanced is True
    assert tb.total_consolidated_debit == tb.total_consolidated_credit

    # 2. Consolidated Financial Statements
    fs = await IntercompanyService.get_consolidated_financial_statements(
        db=db_session, tenant_id=tenant_id, period_id=period.id
    )
    assert fs.gross_profit == fs.total_revenue - fs.total_cogs
    assert fs.net_income == fs.gross_profit - fs.operating_expenses
