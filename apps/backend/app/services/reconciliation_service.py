import uuid
from decimal import Decimal
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.ledger import StockBalanceCache
from app.models.item import ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.invoicing import CustomerInvoice
from app.models.ap import VendorInvoice
from app.models.fixed_asset import FixedAsset
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.reconciliation import (
    SubledgerReconciliationItem,
    FullReconciliationReport
)
from app.services.gl_service import GLService

class ReconciliationService:

    @staticmethod
    async def _get_gl_net_balance(db: AsyncSession, tenant_id: str, account_code: str) -> Decimal:
        acc = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == account_code)
        )).scalar_one_or_none()
        if not acc:
            return Decimal("0.0000")

        stmt = select(
            func.coalesce(func.sum(JournalEntryLine.debit_amount), Decimal("0.0")),
            func.coalesce(func.sum(JournalEntryLine.credit_amount), Decimal("0.0"))
        ).join(JournalVoucher).where(
            JournalEntryLine.account_id == acc.id,
            JournalVoucher.tenant_id == tenant_id,
            JournalVoucher.status == "POSTED"
        )
        dr, cr = (await db.execute(stmt)).first()
        dr = Decimal(str(dr))
        cr = Decimal(str(cr))

        if acc.normal_balance == "DEBIT":
            return (dr - cr).quantize(Decimal("0.0001"))
        else:
            return (cr - dr).quantize(Decimal("0.0001"))

    @staticmethod
    async def reconcile_inventory_subledger(db: AsyncSession, tenant_id: str) -> SubledgerReconciliationItem:
        # Sum quantity_on_hand * cost_price across tenant's warehouses
        stmt = select(
            func.coalesce(
                func.sum(StockBalanceCache.quantity_on_hand * ItemVariant.cost_price),
                Decimal("0.0")
            )
        ).join(
            ItemVariant, StockBalanceCache.item_variant_id == ItemVariant.id
        ).join(
            LocationBin, StockBalanceCache.location_bin_id == LocationBin.id
        ).join(
            Warehouse, LocationBin.warehouse_id == Warehouse.id
        ).where(Warehouse.tenant_id == tenant_id)

        sub_bal = (await db.execute(stmt)).scalar() or Decimal("0.0")
        sub_bal = Decimal(str(sub_bal)).quantize(Decimal("0.0001"))

        gl_bal = await ReconciliationService._get_gl_net_balance(db, tenant_id, "1200")
        var_amt = abs(sub_bal - gl_bal).quantize(Decimal("0.0001"))

        return SubledgerReconciliationItem(
            subledger_name="INVENTORY",
            subledger_balance=sub_bal,
            gl_account_code="1200",
            gl_account_name="Inventory Asset",
            gl_balance=gl_bal,
            variance_amount=var_amt,
            is_in_balance=(var_amt == Decimal("0.0000")),
            notes="Physical inventory valuation vs GL 1200 Inventory Asset"
        )

    @staticmethod
    async def reconcile_ar_subledger(db: AsyncSession, tenant_id: str) -> SubledgerReconciliationItem:
        stmt = select(
            func.coalesce(
                func.sum(CustomerInvoice.balance_due),
                Decimal("0.0")
            )
        ).where(
            CustomerInvoice.tenant_id == tenant_id,
            CustomerInvoice.status.in_(["ISSUED", "PARTIALLY_PAID", "OVERDUE"])
        )
        sub_bal = (await db.execute(stmt)).scalar() or Decimal("0.0")
        sub_bal = Decimal(str(sub_bal)).quantize(Decimal("0.0001"))

        gl_bal = await ReconciliationService._get_gl_net_balance(db, tenant_id, "1100")
        var_amt = abs(sub_bal - gl_bal).quantize(Decimal("0.0001"))

        return SubledgerReconciliationItem(
            subledger_name="ACCOUNTS_RECEIVABLE",
            subledger_balance=sub_bal,
            gl_account_code="1100",
            gl_account_name="Accounts Receivable",
            gl_balance=gl_bal,
            variance_amount=var_amt,
            is_in_balance=(var_amt == Decimal("0.0000")),
            notes="Open customer invoices vs GL 1100 Accounts Receivable"
        )

    @staticmethod
    async def reconcile_ap_subledger(db: AsyncSession, tenant_id: str) -> SubledgerReconciliationItem:
        stmt = select(
            func.coalesce(
                func.sum(VendorInvoice.balance_due),
                Decimal("0.0")
            )
        ).where(
            VendorInvoice.tenant_id == tenant_id,
            VendorInvoice.status.in_(["APPROVED", "PARTIALLY_PAID"])
        )
        sub_bal = (await db.execute(stmt)).scalar() or Decimal("0.0")
        sub_bal = Decimal(str(sub_bal)).quantize(Decimal("0.0001"))

        gl_bal = await ReconciliationService._get_gl_net_balance(db, tenant_id, "2000")
        var_amt = abs(sub_bal - gl_bal).quantize(Decimal("0.0001"))

        return SubledgerReconciliationItem(
            subledger_name="ACCOUNTS_PAYABLE",
            subledger_balance=sub_bal,
            gl_account_code="2000",
            gl_account_name="Accounts Payable",
            gl_balance=gl_bal,
            variance_amount=var_amt,
            is_in_balance=(var_amt == Decimal("0.0000")),
            notes="Open vendor invoices vs GL 2000 Accounts Payable"
        )

    @staticmethod
    async def reconcile_fixed_assets_subledger(db: AsyncSession, tenant_id: str) -> SubledgerReconciliationItem:
        stmt = select(
            func.coalesce(
                func.sum(FixedAsset.current_book_value),
                Decimal("0.0")
            )
        ).where(
            FixedAsset.tenant_id == tenant_id,
            FixedAsset.status.in_(["ACTIVE", "DEPRECIATING"])
        )
        sub_bal = (await db.execute(stmt)).scalar() or Decimal("0.0")
        sub_bal = Decimal(str(sub_bal)).quantize(Decimal("0.0001"))

        gl_cost = await ReconciliationService._get_gl_net_balance(db, tenant_id, "1500")
        gl_acc_dep = await ReconciliationService._get_gl_net_balance(db, tenant_id, "1550")
        gl_net = (gl_cost - gl_acc_dep).quantize(Decimal("0.0001"))

        var_amt = abs(sub_bal - gl_net).quantize(Decimal("0.0001"))

        return SubledgerReconciliationItem(
            subledger_name="FIXED_ASSETS",
            subledger_balance=sub_bal,
            gl_account_code="1500/1550",
            gl_account_name="Fixed Assets Net Book Value",
            gl_balance=gl_net,
            variance_amount=var_amt,
            is_in_balance=(var_amt == Decimal("0.0000")),
            notes="Fixed asset register net book value vs GL 1500 - 1550"
        )

    @staticmethod
    async def reconcile_intercompany_clearing(db: AsyncSession, tenant_id: str) -> SubledgerReconciliationItem:
        due_from = await ReconciliationService._get_gl_net_balance(db, tenant_id, "1300")
        due_to = await ReconciliationService._get_gl_net_balance(db, tenant_id, "2300")
        var_amt = abs(due_from - due_to).quantize(Decimal("0.0001"))

        return SubledgerReconciliationItem(
            subledger_name="INTERCOMPANY",
            subledger_balance=due_from,
            gl_account_code="1300/2300",
            gl_account_name="Due from / Due to Affiliates",
            gl_balance=due_to,
            variance_amount=var_amt,
            is_in_balance=(var_amt == Decimal("0.0000")),
            notes="Reciprocal intercompany clearing balance parity check"
        )

    @staticmethod
    async def get_full_reconciliation_report(db: AsyncSession, tenant_id: str) -> FullReconciliationReport:
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        items = [
            await ReconciliationService.reconcile_inventory_subledger(db, tenant_id),
            await ReconciliationService.reconcile_ar_subledger(db, tenant_id),
            await ReconciliationService.reconcile_ap_subledger(db, tenant_id),
            await ReconciliationService.reconcile_fixed_assets_subledger(db, tenant_id),
            await ReconciliationService.reconcile_intercompany_clearing(db, tenant_id)
        ]

        variance_count = sum(1 for it in items if not it.is_in_balance)
        return FullReconciliationReport(
            tenant_id=tenant_id,
            reconciled_at=get_utc_now(),
            is_fully_reconciled=(variance_count == 0),
            total_variance_count=variance_count,
            items=items
        )
