import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, Date, JSON, Text, Integer, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class IntercompanyPartner(Base, BaseModelMixin):
    __tablename__ = "intercompany_partners"

    tenant_id = Column(String(36), nullable=False, index=True)
    partner_name = Column(String(100), nullable=False)
    seller_company_id = Column(String(50), nullable=False, index=True) # e.g. ENTITY_HQ
    buyer_company_id = Column(String(50), nullable=False, index=True) # e.g. ENTITY_SUB1
    transfer_pricing_type = Column(String(30), default="COST_PLUS", nullable=False) # COST_PLUS, FIXED_PRICE, CATALOG
    markup_percentage = Column(Numeric(10, 4), default=0.0, nullable=False) # e.g. 15.0 for 15% markup
    ar_intercompany_account_id = Column(String(36), ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True) # 1300 Due from Affiliates
    ap_intercompany_account_id = Column(String(36), ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True) # 2300 Due to Affiliates
    is_active = Column(Boolean, default=True, nullable=False)

    ar_account = relationship("GLAccount", foreign_keys=[ar_intercompany_account_id], lazy="selectin")
    ap_account = relationship("GLAccount", foreign_keys=[ap_intercompany_account_id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "seller_company_id", "buyer_company_id", name="uq_tenant_intercompany_pair"),
    )

class IntercompanyTransactionPair(Base, BaseModelMixin):
    __tablename__ = "intercompany_transaction_pairs"

    tenant_id = Column(String(36), nullable=False, index=True)
    partner_id = Column(String(36), ForeignKey("intercompany_partners.id", ondelete="CASCADE"), nullable=False, index=True)
    sales_order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sales_invoice_id = Column(String(36), ForeignKey("customer_invoices.id", ondelete="SET NULL"), nullable=True)
    purchase_bill_id = Column(String(36), ForeignKey("vendor_invoices.id", ondelete="SET NULL"), nullable=True)
    transfer_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    status = Column(String(30), default="LINKED", nullable=False, index=True) # LINKED, DISPATCHED, RECEIVED, ELIMINATED

    partner = relationship("IntercompanyPartner", lazy="selectin")
    sales_order = relationship("SalesOrder", lazy="selectin")
    purchase_order = relationship("PurchaseOrder", lazy="selectin")

class ConsolidationRun(Base, BaseModelMixin):
    __tablename__ = "consolidation_runs"

    tenant_id = Column(String(36), nullable=False, index=True)
    period_id = Column(String(36), ForeignKey("accounting_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    run_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False) # DRAFT, FINALIZED, VOIDED
    elimination_voucher_id = Column(String(36), ForeignKey("journal_vouchers.id", ondelete="SET NULL"), nullable=True)
    total_eliminated_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    notes = Column(Text, nullable=True)

    period = relationship("AccountingPeriod", lazy="selectin")
    elimination_voucher = relationship("JournalVoucher", lazy="selectin")

class UnrealizedProfitElimination(Base, BaseModelMixin):
    __tablename__ = "unrealized_profit_eliminations"

    tenant_id = Column(String(36), nullable=False, index=True)
    period_id = Column(String(36), ForeignKey("accounting_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    partner_id = Column(String(36), ForeignKey("intercompany_partners.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    on_hand_quantity = Column(Numeric(18, 4), default=0.0, nullable=False)
    unit_markup = Column(Numeric(18, 4), default=0.0, nullable=False)
    total_unrealized_profit = Column(Numeric(18, 4), default=0.0, nullable=False)
    elimination_voucher_id = Column(String(36), ForeignKey("journal_vouchers.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="POSTED", nullable=False) # POSTED, REVERSED

    period = relationship("AccountingPeriod", lazy="selectin")
    partner = relationship("IntercompanyPartner", lazy="selectin")
    item = relationship("Item", lazy="selectin")
    elimination_voucher = relationship("JournalVoucher", lazy="selectin")
