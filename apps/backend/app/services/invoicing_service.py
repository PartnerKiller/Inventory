import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.invoicing import (
    CustomerInvoice,
    InvoiceLineItem,
    CustomerPayment,
    PaymentAllocation,
    CustomerCreditNote
)
from app.models.sales import Customer, SalesOrder, SOLineItem, SalesReturn
from app.models.item import ItemVariant, Item
from app.schemas.invoicing import (
    CustomerInvoiceCreate,
    CustomerPaymentCreate,
    CreditNoteCreate,
    ARAgingReportResponse,
    ARAgingBucket,
    CustomerARAgingSummary
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService

class InvoicingService:
    @staticmethod
    async def create_invoice_from_sales_order(
        db: AsyncSession,
        tenant_id: str,
        so_id: str,
        issue_date: Optional[datetime] = None,
        due_date: Optional[datetime] = None,
        user_id: Optional[str] = None
    ) -> CustomerInvoice:
        so_stmt = select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.tenant_id == tenant_id)
        res = await db.execute(so_stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales Order not found")

        if so.status not in ["CONFIRMED", "ALLOCATED", "PARTIALLY_ALLOCATED", "PICKING", "PACKED", "SHIPPED", "DELIVERED"]:
            raise HTTPException(status_code=400, detail=f"Cannot generate invoice for order in '{so.status}' status (must be confirmed/shipped)")

        # Duplicate invoice prevention for same Sales Order
        existing_inv = (await db.execute(
            select(CustomerInvoice).where(
                CustomerInvoice.sales_order_id == so_id,
                CustomerInvoice.tenant_id == tenant_id,
                CustomerInvoice.status.in_(["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID"])
            )
        )).scalar_one_or_none()
        if existing_inv:
            return existing_inv

        now = get_utc_now()
        iss_date = issue_date or now

        # Calculate due date from customer payment terms
        if not due_date:
            terms = so.customer.payment_terms if so.customer else "NET_30"
            days = 0 if terms == "PREPAID" else (15 if terms == "NET_15" else (60 if terms == "NET_60" else 30))
            calc_due = iss_date + timedelta(days=days)
        else:
            calc_due = due_date

        inv_num = await SequenceService.generate_next_number(db, tenant_id, "INVOICE")

        subtotal = Decimal("0.0")
        discount_tot = Decimal("0.0")
        tax_tot = Decimal("0.0")

        invoice = CustomerInvoice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            invoice_number=inv_num,
            sales_order_id=so.id,
            customer_id=so.customer_id,
            status="ISSUED",
            currency=so.currency,
            issue_date=iss_date,
            due_date=calc_due,
            issued_by_user_id=user_id,
            notes=f"Generated from Sales Order {so.so_number}"
        )
        db.add(invoice)
        await db.flush()

        for sline in so.lines:
            line_qty = Decimal(str(sline.quantity_ordered))
            unit_p = Decimal(str(sline.unit_price))
            disc_p = Decimal(str(sline.discount_pct or 0.0))
            tax_p = Decimal(str(sline.tax_pct or 0.0))

            gross = line_qty * unit_p
            disc_val = gross * (disc_p / Decimal("100.0"))
            net_line = gross - disc_val
            tax_val = net_line * (tax_p / Decimal("100.0"))
            tot_line = net_line + tax_val

            subtotal += gross
            discount_tot += disc_val
            tax_tot += tax_val

            inv_line = InvoiceLineItem(
                id=str(uuid.uuid4()),
                invoice_id=invoice.id,
                so_line_id=sline.id,
                item_variant_id=sline.item_variant_id,
                quantity=line_qty,
                unit_price=unit_p,
                discount_pct=disc_p,
                tax_pct=tax_p,
                line_total=tot_line
            )
            db.add(inv_line)

        grand_total = subtotal - discount_tot + tax_tot
        invoice.subtotal_amount = subtotal
        invoice.discount_amount = discount_tot
        invoice.tax_amount = tax_tot
        invoice.total_amount = grand_total
        invoice.amount_paid = Decimal("0.0")
        invoice.balance_due = grand_total

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_INVOICE",
            entity_type="CustomerInvoice",
            entity_id=invoice.id,
            user_id=user_id,
            changes={"invoice_number": inv_num, "total_amount": float(grand_total)}
        )

        await db.commit()
        await db.refresh(invoice)
        return invoice

    @staticmethod
    async def record_customer_payment(
        db: AsyncSession,
        tenant_id: str,
        payment_in: CustomerPaymentCreate,
        user_id: Optional[str] = None
    ) -> CustomerPayment:
        cust = (await db.execute(
            select(Customer).where(Customer.id == payment_in.customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        total_alloc = sum(Decimal(str(a.amount)) for a in payment_in.allocations)
        if total_alloc > Decimal(str(payment_in.amount)):
            raise HTTPException(status_code=400, detail="Allocated amounts exceed payment total amount")

        pay_num = await SequenceService.generate_next_number(db, tenant_id, "PAYMENT")

        payment = CustomerPayment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            payment_number=pay_num,
            customer_id=cust.id,
            payment_method=payment_in.payment_method,
            amount=payment_in.amount,
            currency=payment_in.currency,
            payment_date=payment_in.payment_date or get_utc_now(),
            reference_number=payment_in.reference_number,
            status="COMPLETED",
            notes=payment_in.notes,
            received_by_user_id=user_id
        )
        db.add(payment)
        await db.flush()

        for alloc in payment_in.allocations:
            alloc_amt = Decimal(str(alloc.amount))
            inv_stmt = select(CustomerInvoice).where(
                CustomerInvoice.id == alloc.invoice_id,
                CustomerInvoice.tenant_id == tenant_id
            ).with_for_update()
            inv = (await db.execute(inv_stmt)).scalar_one_or_none()
            if not inv:
                raise HTTPException(status_code=404, detail=f"Invoice '{alloc.invoice_id}' not found")

            if alloc_amt > Decimal(str(inv.balance_due)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Allocation ${alloc_amt} exceeds invoice {inv.invoice_number} balance due (${inv.balance_due})"
                )

            inv.amount_paid = Decimal(str(inv.amount_paid)) + alloc_amt
            inv.balance_due = Decimal(str(inv.balance_due)) - alloc_amt

            if inv.balance_due <= Decimal("0.0"):
                inv.status = "PAID"
            else:
                inv.status = "PARTIALLY_PAID"

            p_alloc = PaymentAllocation(
                id=str(uuid.uuid4()),
                payment_id=payment.id,
                invoice_id=inv.id,
                amount_allocated=alloc_amt,
                allocated_at=get_utc_now()
            )
            db.add(p_alloc)

        # Update customer credit exposure
        if cust.current_credit_exposure:
            cust.current_credit_exposure = max(Decimal("0.0"), Decimal(str(cust.current_credit_exposure)) - total_alloc)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="RECORD_PAYMENT",
            entity_type="CustomerPayment",
            entity_id=payment.id,
            user_id=user_id,
            changes={"payment_number": pay_num, "amount": float(payment.amount)}
        )

        await db.commit()
        await db.refresh(payment)
        return payment

    @staticmethod
    async def create_credit_note_for_return(
        db: AsyncSession,
        tenant_id: str,
        cn_in: CreditNoteCreate,
        user_id: Optional[str] = None
    ) -> CustomerCreditNote:
        cust = (await db.execute(
            select(Customer).where(Customer.id == cn_in.customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Prevent duplicate credit note for same RMA Return
        if cn_in.sales_return_id:
            existing_cn = (await db.execute(
                select(CustomerCreditNote).where(
                    CustomerCreditNote.sales_return_id == cn_in.sales_return_id,
                    CustomerCreditNote.tenant_id == tenant_id,
                    CustomerCreditNote.status.in_(["ISSUED", "APPLIED"])
                )
            )).scalar_one_or_none()
            if existing_cn:
                raise HTTPException(status_code=409, detail=f"Credit note already issued for Sales Return '{cn_in.sales_return_id}'")

        cn_num = await SequenceService.generate_next_number(db, tenant_id, "CREDIT_NOTE")

        cn = CustomerCreditNote(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            credit_note_number=cn_num,
            customer_id=cust.id,
            sales_return_id=cn_in.sales_return_id,
            invoice_id=cn_in.invoice_id,
            amount=cn_in.amount,
            status="ISSUED",
            issue_date=get_utc_now(),
            notes=cn_in.notes,
            created_by_user_id=user_id
        )
        db.add(cn)

        # If linked to invoice, apply credit
        if cn_in.invoice_id:
            inv = (await db.execute(
                select(CustomerInvoice).where(CustomerInvoice.id == cn_in.invoice_id, CustomerInvoice.tenant_id == tenant_id).with_for_update()
            )).scalar_one_or_none()
            if inv:
                cred_amt = min(Decimal(str(cn_in.amount)), Decimal(str(inv.balance_due)))
                inv.amount_paid = Decimal(str(inv.amount_paid)) + cred_amt
                inv.balance_due = Decimal(str(inv.balance_due)) - cred_amt
                if inv.balance_due <= Decimal("0.0"):
                    inv.status = "PAID"
                else:
                    inv.status = "PARTIALLY_PAID"
                cn.status = "APPLIED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_CREDIT_NOTE",
            entity_type="CustomerCreditNote",
            entity_id=cn.id,
            user_id=user_id,
            changes={"credit_note_number": cn_num, "amount": float(cn.amount)}
        )

        await db.commit()
        await db.refresh(cn)
        return cn

    @staticmethod
    async def get_ar_aging_report(
        db: AsyncSession,
        tenant_id: str,
        as_of_date: Optional[datetime] = None
    ) -> ARAgingReportResponse:
        as_of = as_of_date or get_utc_now()

        # Query all outstanding invoices
        stmt = (
            select(CustomerInvoice, Customer)
            .join(Customer, CustomerInvoice.customer_id == Customer.id)
            .where(
                CustomerInvoice.tenant_id == tenant_id,
                CustomerInvoice.status.in_(["ISSUED", "PARTIALLY_PAID", "OVERDUE"]),
                CustomerInvoice.balance_due > Decimal("0.0")
            )
        )
        rows = (await db.execute(stmt)).all()

        bucket_totals = {"Current": Decimal("0.0"), "1-30 Days": Decimal("0.0"), "31-60 Days": Decimal("0.0"), "61-90 Days": Decimal("0.0"), "90+ Days": Decimal("0.0")}
        bucket_counts = {"Current": 0, "1-30 Days": 0, "31-60 Days": 0, "61-90 Days": 0, "90+ Days": 0}
        customer_agings: Dict[str, Dict[str, Any]] = {}

        total_ar = Decimal("0.0")

        for inv, cust in rows:
            bal = Decimal(str(inv.balance_due))
            total_ar += bal

            # Calculate days overdue
            due = inv.due_date
            if due.tzinfo is None:
                due = due.replace(tzinfo=as_of.tzinfo)

            days_overdue = (as_of - due).days

            if days_overdue <= 0:
                b_name = "Current"
            elif days_overdue <= 30:
                b_name = "1-30 Days"
            elif days_overdue <= 60:
                b_name = "31-60 Days"
            elif days_overdue <= 90:
                b_name = "61-90 Days"
            else:
                b_name = "90+ Days"

            bucket_totals[b_name] += bal
            bucket_counts[b_name] += 1

            if cust.id not in customer_agings:
                customer_agings[cust.id] = {
                    "customer_id": cust.id,
                    "customer_code": cust.code,
                    "customer_name": cust.name,
                    "total_outstanding": Decimal("0.0"),
                    "current": Decimal("0.0"),
                    "d1_30": Decimal("0.0"),
                    "d31_60": Decimal("0.0"),
                    "d61_90": Decimal("0.0"),
                    "d90_plus": Decimal("0.0")
                }

            c_rec = customer_agings[cust.id]
            c_rec["total_outstanding"] += bal
            if b_name == "Current":
                c_rec["current"] += bal
            elif b_name == "1-30 Days":
                c_rec["d1_30"] += bal
            elif b_name == "31-60 Days":
                c_rec["d31_60"] += bal
            elif b_name == "61-90 Days":
                c_rec["d61_90"] += bal
            else:
                c_rec["d90_plus"] += bal

        summary_buckets = [
            ARAgingBucket(bucket_label=k, total_amount=float(bucket_totals[k]), invoice_count=bucket_counts[k])
            for k in ["Current", "1-30 Days", "31-60 Days", "61-90 Days", "90+ Days"]
        ]

        customer_summaries = [
            CustomerARAgingSummary(
                customer_id=c["customer_id"],
                customer_code=c["customer_code"],
                customer_name=c["customer_name"],
                total_outstanding=float(c["total_outstanding"]),
                current_amount=float(c["current"]),
                days_1_30=float(c["d1_30"]),
                days_31_60=float(c["d31_60"]),
                days_61_90=float(c["d61_90"]),
                days_over_90=float(c["d90_plus"])
            )
            for c in customer_agings.values()
        ]

        return ARAgingReportResponse(
            as_of_date=as_of,
            total_receivables=float(total_ar),
            summary_buckets=summary_buckets,
            customer_summaries=customer_summaries
        )
