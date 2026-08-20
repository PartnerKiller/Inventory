import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.intercompany import IntercompanyPartner, IntercompanyTransactionPair, ConsolidationRun, UnrealizedProfitElimination
from app.models.sales import SalesOrder, SOLineItem
from app.models.purchasing import PurchaseOrder, POLineItem, Supplier
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.models.accounting_period import AccountingPeriod
from app.schemas.intercompany import (
    IntercompanyPartnerCreate,
    IntercompanyPartnerResponse,
    MirroredOrderCreate,
    IntercompanyTransactionPairResponse,
    ConsolidationRunCreate,
    ConsolidationRunResponse,
    UnrealizedProfitEliminationCreate,
    UnrealizedProfitEliminationResponse,
    ConsolidatedTrialBalanceLine,
    ConsolidatedTrialBalanceResponse,
    ConsolidatedFinancialStatementResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

class IntercompanyService:

    # ========================================================================
    # 1. TRADING PARTNER RELATIONSHIPS
    # ========================================================================

    @staticmethod
    async def create_partner_relationship(
        db: AsyncSession,
        tenant_id: str,
        partner_in: IntercompanyPartnerCreate
    ) -> IntercompanyPartnerResponse:
        if partner_in.seller_company_id == partner_in.buyer_company_id:
            raise HTTPException(status_code=400, detail="Seller and buyer entities must be distinct")

        if partner_in.markup_percentage < Decimal("0.0"):
            raise HTTPException(status_code=400, detail="Markup percentage cannot be negative")

        # Ensure standard intercompany clearing accounts exist
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)

        ar_acc_id = partner_in.ar_intercompany_account_id
        if not ar_acc_id:
            acc_1300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1300"))).scalar_one_or_none()
            if not acc_1300:
                acc_1300 = GLAccount(
                    id=str(uuid.uuid4()), tenant_id=tenant_id, account_code="1300",
                    account_name="Due from Affiliates (Intercompany AR)", account_class="ASSET",
                    account_type="CURRENT_ASSET", currency="USD", normal_balance="DEBIT",
                    is_active=True, is_system=True
                )
                db.add(acc_1300)
                await db.commit()
                await db.refresh(acc_1300)
            ar_acc_id = acc_1300.id

        ap_acc_id = partner_in.ap_intercompany_account_id
        if not ap_acc_id:
            acc_2300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2300"))).scalar_one_or_none()
            if not acc_2300:
                acc_2300 = GLAccount(
                    id=str(uuid.uuid4()), tenant_id=tenant_id, account_code="2300",
                    account_name="Due to Affiliates (Intercompany AP)", account_class="LIABILITY",
                    account_type="CURRENT_LIABILITY", currency="USD", normal_balance="CREDIT",
                    is_active=True, is_system=True
                )
                db.add(acc_2300)
                await db.commit()
                await db.refresh(acc_2300)
            ap_acc_id = acc_2300.id

        partner = IntercompanyPartner(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            partner_name=partner_in.partner_name,
            seller_company_id=partner_in.seller_company_id,
            buyer_company_id=partner_in.buyer_company_id,
            transfer_pricing_type=partner_in.transfer_pricing_type.upper(),
            markup_percentage=partner_in.markup_percentage,
            ar_intercompany_account_id=ar_acc_id,
            ap_intercompany_account_id=ap_acc_id,
            is_active=True
        )
        db.add(partner)
        await db.commit()
        await db.refresh(partner)

        return IntercompanyPartnerResponse(
            id=partner.id,
            tenant_id=partner.tenant_id,
            partner_name=partner.partner_name,
            seller_company_id=partner.seller_company_id,
            buyer_company_id=partner.buyer_company_id,
            transfer_pricing_type=partner.transfer_pricing_type,
            markup_percentage=partner.markup_percentage,
            ar_intercompany_account_id=partner.ar_intercompany_account_id,
            ap_intercompany_account_id=partner.ap_intercompany_account_id,
            is_active=partner.is_active,
            created_at=partner.created_at
        )

    # ========================================================================
    # 2. AUTOMATED MIRRORED TRANSACTION GENERATION & IDEMPOTENCY
    # ========================================================================

    @staticmethod
    async def create_mirrored_intercompany_order(
        db: AsyncSession,
        tenant_id: str,
        req: MirroredOrderCreate,
        user_id: Optional[str] = None
    ) -> IntercompanyTransactionPairResponse:
        # Check if mirrored order pair already exists (Idempotency Guard)
        existing_pair = (await db.execute(
            select(IntercompanyTransactionPair).where(
                IntercompanyTransactionPair.tenant_id == tenant_id,
                IntercompanyTransactionPair.sales_order_id == req.seller_sales_order_id,
                IntercompanyTransactionPair.partner_id == req.partner_id
            )
        )).scalar_one_or_none()
        if existing_pair:
            return IntercompanyTransactionPairResponse(
                id=existing_pair.id,
                tenant_id=existing_pair.tenant_id,
                partner_id=existing_pair.partner_id,
                sales_order_id=existing_pair.sales_order_id,
                purchase_order_id=existing_pair.purchase_order_id,
                sales_invoice_id=existing_pair.sales_invoice_id,
                purchase_bill_id=existing_pair.purchase_bill_id,
                transfer_amount=existing_pair.transfer_amount,
                status=existing_pair.status,
                created_at=existing_pair.created_at
            )

        partner = (await db.execute(
            select(IntercompanyPartner).where(
                IntercompanyPartner.id == req.partner_id,
                IntercompanyPartner.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not partner:
            raise HTTPException(status_code=404, detail="Intercompany partner not found")

        if not partner.is_active:
            raise HTTPException(status_code=400, detail="Intercompany partner relationship is inactive")

        so = (await db.execute(
            select(SalesOrder).where(
                SalesOrder.id == req.seller_sales_order_id,
                SalesOrder.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales order not found")

        # Provision or find internal affiliate supplier
        affiliate_supplier = (await db.execute(
            select(Supplier).where(
                Supplier.tenant_id == tenant_id,
                Supplier.name == partner.partner_name
            )
        )).scalar_one_or_none()
        if not affiliate_supplier:
            affiliate_supplier = Supplier(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                code=f"SUPP-IC-{uuid.uuid4().hex[:4].upper()}",
                name=partner.partner_name,
                currency="USD",
                is_active=True
            )
            db.add(affiliate_supplier)
            await db.flush()

        # Create mirrored Purchase Order in buyer's context
        po_number = f"PO-IC-{so.so_number}"
        po = PurchaseOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            po_number=po_number,
            supplier_id=affiliate_supplier.id,
            target_warehouse_id=so.warehouse_id,
            status="APPROVED",
            ordered_at=so.ordered_at,
            total_amount=Decimal("0.0"),
            currency="USD",
            created_by_user_id=user_id,
            notes=f"Mirrored from Intercompany SO {so.so_number}"
        )
        db.add(po)

        total_transfer_amt = Decimal("0.0")
        for so_item in so.lines:
            # Apply Transfer Pricing Policy
            if partner.transfer_pricing_type == "COST_PLUS":
                transfer_price = (so_item.unit_price * (Decimal("1.0") + (partner.markup_percentage / Decimal("100.0")))).quantize(Decimal("0.0001"))
            elif partner.transfer_pricing_type == "FIXED_PRICE":
                transfer_price = so_item.unit_price
            else: # CATALOG
                transfer_price = so_item.unit_price

            line_total = (transfer_price * so_item.quantity_ordered).quantize(Decimal("0.0001"))
            total_transfer_amt += line_total

            po_line = POLineItem(
                id=str(uuid.uuid4()),
                purchase_order_id=po.id,
                item_variant_id=so_item.item_variant_id,
                quantity_ordered=so_item.quantity_ordered,
                quantity_received=Decimal("0.0"),
                unit_price=transfer_price,
                line_total=line_total
            )
            db.add(po_line)

        po.total_amount = total_transfer_amt

        pair = IntercompanyTransactionPair(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            partner_id=partner.id,
            sales_order_id=so.id,
            purchase_order_id=po.id,
            transfer_amount=total_transfer_amt,
            status="LINKED"
        )
        db.add(pair)
        await db.commit()
        await db.refresh(pair)

        return IntercompanyTransactionPairResponse(
            id=pair.id,
            tenant_id=pair.tenant_id,
            partner_id=pair.partner_id,
            sales_order_id=pair.sales_order_id,
            purchase_order_id=pair.purchase_order_id,
            sales_invoice_id=pair.sales_invoice_id,
            purchase_bill_id=pair.purchase_bill_id,
            transfer_amount=pair.transfer_amount,
            status=pair.status,
            created_at=pair.created_at
        )

    # ========================================================================
    # 3. CONSOLIDATION ELIMINATION JOURNAL ENGINE
    # ========================================================================

    @staticmethod
    async def generate_consolidation_eliminations(
        db: AsyncSession,
        tenant_id: str,
        cons_in: ConsolidationRunCreate,
        user_id: Optional[str] = None
    ) -> ConsolidationRunResponse:
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.id == cons_in.period_id,
                AccountingPeriod.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Accounting period not found")

        # Phase 22 Closed-Period Protection Guard
        if period.status in ["CLOSED", "FINALIZED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot post consolidation eliminations to a {period.status} accounting period"
            )

        # Sum all linked intercompany trade pairs
        pairs = (await db.execute(
            select(IntercompanyTransactionPair).where(
                IntercompanyTransactionPair.tenant_id == tenant_id,
                IntercompanyTransactionPair.status.in_(["LINKED", "DISPATCHED", "RECEIVED"])
            ).with_for_update()
        )).scalars().all()

        total_eliminated = sum((p.transfer_amount for p in pairs), Decimal("0.0"))

        elim_jv_id = None
        if total_eliminated > Decimal("0.0"):
            # Ensure standard accounts exist
            acc_4000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "4000"))).scalar_one()
            acc_5000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "5000"))).scalar_one()
            acc_1300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1300"))).scalar_one()
            acc_2300 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2300"))).scalar_one()

            # Balancing Consolidation Elimination Voucher:
            # 1. Eliminate Intercompany Revenue & COGS: Dr 4000 (Revenue) / Cr 5000 (COGS)
            # 2. Eliminate Intercompany Reciprocal Balances: Dr 2300 (Due to Affiliates) / Cr 1300 (Due from Affiliates)
            jv_res = await GLService.post_journal_voucher(
                db=db,
                tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="CONSOLIDATION_ELIMINATION",
                    source_document_id=period.period_code,
                    notes=f"Consolidation Eliminations for Period {period.period_code}",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_4000.id, debit_amount=total_eliminated, credit_amount=Decimal("0.0"), memo="Eliminate intercompany revenue"),
                        JournalEntryLineCreate(account_id=acc_5000.id, debit_amount=Decimal("0.0"), credit_amount=total_eliminated, memo="Eliminate intercompany COGS"),
                        JournalEntryLineCreate(account_id=acc_2300.id, debit_amount=total_eliminated, credit_amount=Decimal("0.0"), memo="Eliminate intercompany AP"),
                        JournalEntryLineCreate(account_id=acc_1300.id, debit_amount=Decimal("0.0"), credit_amount=total_eliminated, memo="Eliminate intercompany AR")
                    ]
                ),
                user_id=user_id
            )
            elim_jv_id = jv_res.id

            for p in pairs:
                p.status = "ELIMINATED"

        run = ConsolidationRun(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            period_id=period.id,
            run_date=get_utc_now(),
            status="FINALIZED",
            elimination_voucher_id=elim_jv_id,
            total_eliminated_amount=total_eliminated,
            notes=cons_in.notes
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        return ConsolidationRunResponse(
            id=run.id,
            tenant_id=run.tenant_id,
            period_id=run.period_id,
            run_date=run.run_date,
            status=run.status,
            elimination_voucher_id=run.elimination_voucher_id,
            total_eliminated_amount=run.total_eliminated_amount,
            notes=run.notes,
            created_at=run.created_at
        )

    # ========================================================================
    # 4. UNREALIZED INTERCOMPANY INVENTORY-PROFIT ELIMINATION (PHASE 31)
    # ========================================================================

    @staticmethod
    async def eliminate_unrealized_inventory_profit(
        db: AsyncSession,
        tenant_id: str,
        req: UnrealizedProfitEliminationCreate,
        user_id: Optional[str] = None
    ) -> UnrealizedProfitEliminationResponse:
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.id == req.period_id,
                AccountingPeriod.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Accounting period not found")

        if period.status in ["CLOSED", "FINALIZED"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot post unrealized profit elimination to a closed accounting period"
            )

        if req.on_hand_quantity <= Decimal("0.0") or req.unit_markup <= Decimal("0.0"):
            raise HTTPException(status_code=400, detail="On-hand quantity and unit markup must be greater than zero")

        total_unrealized = (req.on_hand_quantity * req.unit_markup).quantize(Decimal("0.0001"))

        # Ensure Account 1210 (Contra-Asset / Inventory Reserve) exists
        acc_1210 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1210"))).scalar_one_or_none()
        if not acc_1210:
            acc_1210 = GLAccount(
                id=str(uuid.uuid4()), tenant_id=tenant_id, account_code="1210",
                account_name="Unrealized Intercompany Profit Reserve", account_class="ASSET",
                account_type="CURRENT_ASSET", currency="USD", normal_balance="CREDIT",
                is_active=True, is_system=True
            )
            db.add(acc_1210)
            await db.flush()

        acc_5000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "5000"))).scalar_one()

        # Post balanced elimination Journal Voucher:
        # Dr 5000 (Consolidated COGS) $U / Cr 1210 (Inventory Reserve) $U
        jv_res = await GLService.post_journal_voucher(
            db=db,
            tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=get_utc_now(),
                source_document_type="UNREALIZED_PROFIT_ELIMINATION",
                source_document_id=period.period_code,
                notes=f"Unrealized Inventory Profit Elimination for Period {period.period_code}",
                lines=[
                    JournalEntryLineCreate(account_id=acc_5000.id, debit_amount=total_unrealized, credit_amount=Decimal("0.0"), memo="Eliminate unrealized gross profit from ending inventory"),
                    JournalEntryLineCreate(account_id=acc_1210.id, debit_amount=Decimal("0.0"), credit_amount=total_unrealized, memo="Unrealized intercompany inventory profit reserve")
                ]
            ),
            user_id=user_id
        )

        elim_record = UnrealizedProfitElimination(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            period_id=period.id,
            partner_id=req.partner_id,
            item_id=req.item_id,
            on_hand_quantity=req.on_hand_quantity,
            unit_markup=req.unit_markup,
            total_unrealized_profit=total_unrealized,
            elimination_voucher_id=jv_res.id,
            status="POSTED"
        )
        db.add(elim_record)
        await db.commit()
        await db.refresh(elim_record)

        return UnrealizedProfitEliminationResponse(
            id=elim_record.id,
            tenant_id=elim_record.tenant_id,
            period_id=elim_record.period_id,
            partner_id=elim_record.partner_id,
            item_id=elim_record.item_id,
            on_hand_quantity=elim_record.on_hand_quantity,
            unit_markup=elim_record.unit_markup,
            total_unrealized_profit=elim_record.total_unrealized_profit,
            elimination_voucher_id=elim_record.elimination_voucher_id,
            status=elim_record.status,
            created_at=elim_record.created_at
        )

    # ========================================================================
    # 5. CONSOLIDATED FINANCIAL REPORTING ENGINE (PHASE 31)
    # ========================================================================

    @staticmethod
    async def get_consolidated_trial_balance(
        db: AsyncSession,
        tenant_id: str,
        period_id: str
    ) -> ConsolidatedTrialBalanceResponse:
        accounts = (await db.execute(
            select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.is_active == True)
        )).scalars().all()

        lines: List[ConsolidatedTrialBalanceLine] = []
        tot_deb = Decimal("0.0")
        tot_crd = Decimal("0.0")

        for acc in accounts:
            # Query standard entries
            std_debit = (await db.execute(
                select(func.sum(JournalEntryLine.debit_amount))
                .join(JournalVoucher, JournalVoucher.id == JournalEntryLine.journal_voucher_id)
                .where(
                    JournalVoucher.tenant_id == tenant_id,
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.source_document_type.not_in(["CONSOLIDATION_ELIMINATION", "UNREALIZED_PROFIT_ELIMINATION"])
                )
            )).scalar() or Decimal("0.0")

            std_credit = (await db.execute(
                select(func.sum(JournalEntryLine.credit_amount))
                .join(JournalVoucher, JournalVoucher.id == JournalEntryLine.journal_voucher_id)
                .where(
                    JournalVoucher.tenant_id == tenant_id,
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.source_document_type.not_in(["CONSOLIDATION_ELIMINATION", "UNREALIZED_PROFIT_ELIMINATION"])
                )
            )).scalar() or Decimal("0.0")

            # Query elimination entries
            elim_debit = (await db.execute(
                select(func.sum(JournalEntryLine.debit_amount))
                .join(JournalVoucher, JournalVoucher.id == JournalEntryLine.journal_voucher_id)
                .where(
                    JournalVoucher.tenant_id == tenant_id,
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.source_document_type.in_(["CONSOLIDATION_ELIMINATION", "UNREALIZED_PROFIT_ELIMINATION"])
                )
            )).scalar() or Decimal("0.0")

            elim_credit = (await db.execute(
                select(func.sum(JournalEntryLine.credit_amount))
                .join(JournalVoucher, JournalVoucher.id == JournalEntryLine.journal_voucher_id)
                .where(
                    JournalVoucher.tenant_id == tenant_id,
                    JournalEntryLine.account_id == acc.id,
                    JournalVoucher.source_document_type.in_(["CONSOLIDATION_ELIMINATION", "UNREALIZED_PROFIT_ELIMINATION"])
                )
            )).scalar() or Decimal("0.0")

            net_debit = std_debit + elim_debit
            net_credit = std_credit + elim_credit

            if acc.normal_balance == "DEBIT":
                consolidated_net = net_debit - net_credit
            else:
                consolidated_net = net_credit - net_debit

            tot_deb += net_debit
            tot_crd += net_credit

            lines.append(ConsolidatedTrialBalanceLine(
                account_code=acc.account_code,
                account_name=acc.account_name,
                account_class=acc.account_class,
                unconsolidated_debit=std_debit,
                unconsolidated_credit=std_credit,
                elimination_debit=elim_debit,
                elimination_credit=elim_credit,
                consolidated_net_balance=consolidated_net
            ))

        return ConsolidatedTrialBalanceResponse(
            tenant_id=tenant_id,
            period_id=period_id,
            lines=lines,
            total_consolidated_debit=tot_deb,
            total_consolidated_credit=tot_crd,
            is_balanced=(tot_deb == tot_crd)
        )

    @staticmethod
    async def get_consolidated_financial_statements(
        db: AsyncSession,
        tenant_id: str,
        period_id: str
    ) -> ConsolidatedFinancialStatementResponse:
        tb = await IntercompanyService.get_consolidated_trial_balance(db, tenant_id, period_id)
        
        rev = Decimal("0.0")
        cogs = Decimal("0.0")
        opex = Decimal("0.0")
        assets = Decimal("0.0")
        liab = Decimal("0.0")
        eq = Decimal("0.0")

        for line in tb.lines:
            if line.account_class == "REVENUE":
                rev += line.consolidated_net_balance
            elif line.account_code.startswith("5"):
                cogs += line.consolidated_net_balance
            elif line.account_class == "EXPENSE":
                opex += line.consolidated_net_balance
            elif line.account_class == "ASSET":
                assets += line.consolidated_net_balance
            elif line.account_class == "LIABILITY":
                liab += line.consolidated_net_balance
            elif line.account_class == "EQUITY":
                eq += line.consolidated_net_balance

        gross_profit = rev - cogs
        net_income = gross_profit - opex

        return ConsolidatedFinancialStatementResponse(
            tenant_id=tenant_id,
            period_id=period_id,
            total_revenue=rev,
            total_cogs=cogs,
            gross_profit=gross_profit,
            operating_expenses=opex,
            net_income=net_income,
            total_assets=assets,
            total_liabilities=liab,
            total_equity=eq
        )
