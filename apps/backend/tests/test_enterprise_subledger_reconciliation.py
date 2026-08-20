import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.models.fixed_asset import FixedAssetClass, FixedAsset
from app.models.invoicing import CustomerInvoice
from app.models.ap import VendorInvoice
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.fixed_asset import FixedAssetClassCreate, FixedAssetCreate
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.reconciliation_service import ReconciliationService
from app.services.gl_service import GLService
from app.services.stock_engine import StockEngine
from app.services.fixed_asset_service import FixedAssetService

# ============================================================================
# 1. FULL RECONCILIATION REPORT ENGINE
# ============================================================================

@pytest.mark.asyncio
async def test_full_reconciliation_report_structure(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    report = await ReconciliationService.get_full_reconciliation_report(
        db=db_session, tenant_id=tenant_id
    )

    assert report.tenant_id == tenant_id
    assert len(report.items) == 5
    sub_names = [it.subledger_name for it in report.items]
    assert "INVENTORY" in sub_names
    assert "ACCOUNTS_RECEIVABLE" in sub_names
    assert "ACCOUNTS_PAYABLE" in sub_names
    assert "FIXED_ASSETS" in sub_names
    assert "INTERCOMPANY" in sub_names

# ============================================================================
# 2. INVENTORY & FIXED ASSET SUBLEDGER RECONCILIATION
# ============================================================================

@pytest.mark.asyncio
async def test_inventory_and_fixed_asset_reconciliation_in_balance(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)

    # 1. Physical Stock: 10 units @ $20.00 = $200.00 valuation
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-REC-{uuid.uuid4().hex[:4]}", name="Rec WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-REC-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-REC-{uuid.uuid4().hex[:4]}", name="Rec Item", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Rec Item Std", cost_price=Decimal("20.0"), selling_price=Decimal("30.0"))
    db_session.add(var)
    await db_session.flush()

    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_loc.id, "quantity": Decimal("10.0"), "unit_cost": Decimal("20.0")}],
        user_id=user_id
    )

    # Post matching GL Opening Inventory: Dr 1200 $200.00 / Cr 3000 $200.00
    acc_1200 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200"))).scalar_one()
    acc_3000 = (await db_session.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "3000"))).scalar_one()

    await GLService.post_journal_voucher(
        db=db_session, tenant_id=tenant_id,
        voucher_in=JournalVoucherCreate(
            voucher_date=datetime.now(timezone.utc),
            source_document_type="STOCK_OPENING",
            notes="Opening inventory balance",
            lines=[
                JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("200.0"), credit_amount=Decimal("0.0"), memo="Inventory Asset"),
                JournalEntryLineCreate(account_id=acc_3000.id, debit_amount=Decimal("0.0"), credit_amount=Decimal("200.0"), memo="Owner Equity")
            ]
        ),
        user_id=user_id
    )

    inv_rec = await ReconciliationService.reconcile_inventory_subledger(db_session, tenant_id)
    assert inv_rec.subledger_balance >= Decimal("200.0")
    assert inv_rec.gl_balance >= Decimal("200.0")

    # 2. Fixed Asset Subledger Reconciles with GL 1500 - 1550
    ac = await FixedAssetService.create_asset_class(
        db=db_session, tenant_id=tenant_id,
        class_in=FixedAssetClassCreate(
            class_code=f"EQ-{uuid.uuid4().hex[:4].upper()}",
            class_name="Testing Equipment",
            useful_life_months=36
        )
    )
    asset_res = await FixedAssetService.create_and_capitalize_fixed_asset(
        db=db_session, tenant_id=tenant_id,
        asset_in=FixedAssetCreate(
            asset_code=f"AST-REC-{uuid.uuid4().hex[:4].upper()}",
            asset_name="Server Rack",
            asset_class_id=ac.id,
            purchase_cost=Decimal("3000.0"),
            acquisition_date=date(2026, 1, 1),
            depreciation_start_date=date(2026, 1, 1),
            useful_life_months=36
        ),
        user_id=user_id
    )

    fa_rec = await ReconciliationService.reconcile_fixed_assets_subledger(db_session, tenant_id)
    assert fa_rec.subledger_balance >= Decimal("3000.0")
    assert fa_rec.gl_balance >= Decimal("3000.0")
    assert fa_rec.is_in_balance == True
