import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.ap import (
    VendorInvoice,
    VendorInvoiceLine,
    VendorPayment,
    VendorPaymentAllocation,
    APMatchingTolerance
)
from app.models.purchasing import Supplier, PurchaseOrder, GoodsReceipt, SupplierDebitMemo
from app.schemas.ap import (
    VendorInvoiceCreate,
    VendorPaymentCreate,
    APMatchingToleranceUpdate,
    APAgingReportResponse,
    APAgingBucket,
    SupplierAPAgingSummary
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.ap_matching_service import APMatchingService

class APService:
    @staticmethod
    async def create_vendor_invoice(
        db: AsyncSession,
        tenant_id: str,
        invoice_in: VendorInvoiceCreate,
        user_id: Optional[str] = None
    ) -> VendorInvoice:
        # Validate PO
        po_stmt = select(PurchaseOrder).where(PurchaseOrder.id == invoice_in.purchase_order_id, PurchaseOrder.tenant_id == tenant_id)
        po = (await db.execute(po_stmt)).scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status not in ["APPROVED", "PARTIALLY_RECEIVED", "COMPLETED"]:
            raise HTTPException(status_code=400, detail=f"Cannot bill PO in '{po.status}' status (must be approved/received)")

        # Validate GRN if specified
        grn = None
        if invoice_in.goods_receipt_id:
            grn_stmt = select(GoodsReceipt).where(GoodsReceipt.id == invoice_in.goods_receipt_id)
            grn = (await db.execute(grn_stmt)).scalar_one_or_none()
            if not grn:
                raise HTTPException(status_code=404, detail="Goods Receipt not found")

        # Duplicate Vendor Invoice Reference Prevention
        dup_stmt = select(VendorInvoice).where(
            VendorInvoice.tenant_id == tenant_id,
            VendorInvoice.supplier_id == po.supplier_id,
            VendorInvoice.vendor_invoice_reference == invoice_in.vendor_invoice_reference,
            VendorInvoice.status.in_(["DRAFT", "MATCHED", "EXCEPTION_HOLD", "APPROVED", "PARTIALLY_PAID", "PAID"])
        )
        existing = (await db.execute(dup_stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Vendor invoice reference '{invoice_in.vendor_invoice_reference}' already exists for this supplier"
            )

        now = get_utc_now()
        iss_date = invoice_in.invoice_date or now

        # Calculate due date from supplier terms
        if not invoice_in.due_date:
            terms = po.supplier.payment_terms if po.supplier else "Net 30"
            days = 0 if "Prepaid" in terms else (15 if "15" in terms else (60 if "60" in terms else 30))
            calc_due = iss_date + timedelta(days=days)
        else:
            calc_due = invoice_in.due_date

        inv_num = await SequenceService.generate_next_number(db, tenant_id, "VENDOR_INVOICE")

        # Execute 3-Way Match
        lines_data = [l.model_dump() for l in invoice_in.lines]
        overall_status, match_status, match_lines, match_notes = await APMatchingService.evaluate_3way_match(
            db, tenant_id, po, grn, lines_data
        )

        subtotal = Decimal("0.0")
        tax_total = Decimal("0.0")

        inv = VendorInvoice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            invoice_number=inv_num,
            vendor_invoice_reference=invoice_in.vendor_invoice_reference,
            purchase_order_id=po.id,
            goods_receipt_id=grn.id if grn else None,
            supplier_id=po.supplier_id,
            status=overall_status,
            match_status=match_status,
            currency=po.currency,
            invoice_date=iss_date,
            due_date=calc_due,
            notes=invoice_in.notes,
            match_notes=match_notes,
            created_by_user_id=user_id
        )
        db.add(inv)
        await db.flush()

        for mline in match_lines:
            subtotal += (mline["billed_quantity"] * mline["billed_unit_price"])
            tax_val = (mline["billed_quantity"] * mline["billed_unit_price"]) * (mline["tax_pct"] / Decimal("100.0"))
            tax_total += tax_val

            vi_line = VendorInvoiceLine(
                id=str(uuid.uuid4()),
                vendor_invoice_id=inv.id,
                po_line_id=mline["po_line_id"],
                grn_line_id=mline["grn_line_id"],
                item_variant_id=mline["item_variant_id"],
                billed_quantity=mline["billed_quantity"],
                received_quantity=mline["received_quantity"],
                po_unit_price=mline["po_unit_price"],
                billed_unit_price=mline["billed_unit_price"],
                price_variance_unit=mline["price_variance_unit"],
                total_price_variance=mline["total_price_variance"],
                tax_pct=mline["tax_pct"],
                line_total=mline["line_total"]
            )
            db.add(vi_line)

        grand_total = subtotal + tax_total
        inv.subtotal_amount = subtotal
        inv.tax_amount = tax_total
        inv.total_amount = grand_total
        inv.amount_paid = Decimal("0.0")
        inv.balance_due = grand_total

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_VENDOR_INVOICE",
            entity_type="VendorInvoice",
            entity_id=inv.id,
            user_id=user_id,
            changes={"invoice_number": inv_num, "total": float(grand_total), "match_status": match_status}
        )

        await db.commit()
        await db.refresh(inv)
        return inv

    @staticmethod
    async def approve_exception_hold(
        db: AsyncSession,
        tenant_id: str,
        invoice_id: str,
        user_id: str,
        approval_notes: Optional[str] = None
    ) -> VendorInvoice:
        stmt = select(VendorInvoice).where(
            VendorInvoice.id == invoice_id,
            VendorInvoice.tenant_id == tenant_id
        ).with_for_update()
        inv = (await db.execute(stmt)).scalar_one_or_none()
        if not inv:
            raise HTTPException(status_code=404, detail="Vendor Invoice not found")

        if inv.status != "EXCEPTION_HOLD":
            raise HTTPException(status_code=400, detail=f"Cannot approve invoice in '{inv.status}' status (must be EXCEPTION_HOLD)")

        # Segregation of Duties: Creator cannot self-approve out-of-tolerance invoices
        if inv.created_by_user_id and inv.created_by_user_id == user_id:
            raise HTTPException(status_code=403, detail="Segregation of Duties: Invoice creator cannot approve their own exception hold")

        inv.status = "APPROVED"
        inv.approved_by_user_id = user_id
        inv.approved_at = get_utc_now()
        if approval_notes:
            inv.notes = f"{inv.notes or ''} [Manager Override: {approval_notes}]".strip()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="APPROVE_VENDOR_INVOICE_EXCEPTION",
            entity_type="VendorInvoice",
            entity_id=inv.id,
            user_id=user_id,
            changes={"status": "APPROVED", "approved_by": user_id}
        )

        await db.commit()
        await db.refresh(inv)
        return inv

    @staticmethod
    async def record_vendor_payment(
        db: AsyncSession,
        tenant_id: str,
        payment_in: VendorPaymentCreate,
        user_id: Optional[str] = None
    ) -> VendorPayment:
        supp = (await db.execute(
            select(Supplier).where(Supplier.id == payment_in.supplier_id, Supplier.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not supp:
            raise HTTPException(status_code=404, detail="Supplier not found")

        total_alloc = sum(Decimal(str(a.amount)) for a in payment_in.allocations)
        if total_alloc > Decimal(str(payment_in.amount)):
            raise HTTPException(status_code=400, detail="Allocated amounts exceed payment total amount")

        pay_num = await SequenceService.generate_next_number(db, tenant_id, "VENDOR_PAYMENT")

        payment = VendorPayment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            payment_number=pay_num,
            supplier_id=supp.id,
            payment_method=payment_in.payment_method,
            amount=payment_in.amount,
            currency=payment_in.currency,
            payment_date=payment_in.payment_date or get_utc_now(),
            reference_number=payment_in.reference_number,
            status="COMPLETED",
            notes=payment_in.notes,
            disbursed_by_user_id=user_id
        )
        db.add(payment)
        await db.flush()

        for alloc in payment_in.allocations:
            alloc_amt = Decimal(str(alloc.amount))
            inv_stmt = select(VendorInvoice).where(
                VendorInvoice.id == alloc.vendor_invoice_id,
                VendorInvoice.tenant_id == tenant_id
            ).with_for_update()
            inv = (await db.execute(inv_stmt)).scalar_one_or_none()
            if not inv:
                raise HTTPException(status_code=404, detail=f"Vendor Invoice '{alloc.vendor_invoice_id}' not found")

            if inv.status not in ["APPROVED", "PARTIALLY_PAID"]:
                raise HTTPException(status_code=400, detail=f"Cannot disburse payment to unapproved bill '{inv.invoice_number}' (status: {inv.status})")

            if alloc_amt > Decimal(str(inv.balance_due)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Allocation ${alloc_amt} exceeds bill {inv.invoice_number} balance due (${inv.balance_due})"
                )

            inv.amount_paid = Decimal(str(inv.amount_paid)) + alloc_amt
            inv.balance_due = Decimal(str(inv.balance_due)) - alloc_amt

            if inv.balance_due <= Decimal("0.0"):
                inv.status = "PAID"
            else:
                inv.status = "PARTIALLY_PAID"

            p_alloc = VendorPaymentAllocation(
                id=str(uuid.uuid4()),
                vendor_payment_id=payment.id,
                vendor_invoice_id=inv.id,
                amount_allocated=alloc_amt,
                allocated_at=get_utc_now()
            )
            db.add(p_alloc)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="DISBURSE_VENDOR_PAYMENT",
            entity_type="VendorPayment",
            entity_id=payment.id,
            user_id=user_id,
            changes={"payment_number": pay_num, "amount": float(payment.amount)}
        )

        await db.commit()
        await db.refresh(payment)
        return payment

    @staticmethod
    async def apply_debit_memo(
        db: AsyncSession,
        tenant_id: str,
        invoice_id: str,
        debit_memo_id: str,
        user_id: Optional[str] = None
    ) -> VendorInvoice:
        inv = (await db.execute(
            select(VendorInvoice).where(VendorInvoice.id == invoice_id, VendorInvoice.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not inv:
            raise HTTPException(status_code=404, detail="Vendor Invoice not found")

        dm = (await db.execute(
            select(SupplierDebitMemo).where(SupplierDebitMemo.id == debit_memo_id, SupplierDebitMemo.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not dm:
            raise HTTPException(status_code=404, detail="Debit Memo not found")

        if dm.status != "OPEN":
            raise HTTPException(status_code=400, detail=f"Debit Memo is already '{dm.status}'")

        credit_amt = min(Decimal(str(dm.amount)), Decimal(str(inv.balance_due)))
        inv.amount_paid = Decimal(str(inv.amount_paid)) + credit_amt
        inv.balance_due = Decimal(str(inv.balance_due)) - credit_amt
        dm.status = "APPLIED"

        if inv.balance_due <= Decimal("0.0"):
            inv.status = "PAID"
        else:
            inv.status = "PARTIALLY_PAID"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="APPLY_DEBIT_MEMO",
            entity_type="VendorInvoice",
            entity_id=inv.id,
            user_id=user_id,
            changes={"debit_memo_id": dm.id, "credit_applied": float(credit_amt)}
        )

        await db.commit()
        await db.refresh(inv)
        return inv

    @staticmethod
    async def get_ap_aging_report(
        db: AsyncSession,
        tenant_id: str,
        as_of_date: Optional[datetime] = None
    ) -> APAgingReportResponse:
        as_of = as_of_date or get_utc_now()

        stmt = (
            select(VendorInvoice, Supplier)
            .join(Supplier, VendorInvoice.supplier_id == Supplier.id)
            .where(
                VendorInvoice.tenant_id == tenant_id,
                VendorInvoice.status.in_(["APPROVED", "PARTIALLY_PAID", "EXCEPTION_HOLD"]),
                VendorInvoice.balance_due > Decimal("0.0")
            )
        )
        rows = (await db.execute(stmt)).all()

        bucket_totals = {"Current": Decimal("0.0"), "1-30 Days": Decimal("0.0"), "31-60 Days": Decimal("0.0"), "61-90 Days": Decimal("0.0"), "90+ Days": Decimal("0.0")}
        bucket_counts = {"Current": 0, "1-30 Days": 0, "31-60 Days": 0, "61-90 Days": 0, "90+ Days": 0}
        supplier_agings: Dict[str, Dict[str, Any]] = {}

        total_ap = Decimal("0.0")

        for inv, supp in rows:
            bal = Decimal(str(inv.balance_due))
            total_ap += bal

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

            if supp.id not in supplier_agings:
                supplier_agings[supp.id] = {
                    "supplier_id": supp.id,
                    "supplier_code": supp.code,
                    "supplier_name": supp.name,
                    "total_outstanding": Decimal("0.0"),
                    "current": Decimal("0.0"),
                    "d1_30": Decimal("0.0"),
                    "d31_60": Decimal("0.0"),
                    "d61_90": Decimal("0.0"),
                    "d90_plus": Decimal("0.0")
                }

            s_rec = supplier_agings[supp.id]
            s_rec["total_outstanding"] += bal
            if b_name == "Current":
                s_rec["current"] += bal
            elif b_name == "1-30 Days":
                s_rec["d1_30"] += bal
            elif b_name == "31-60 Days":
                s_rec["d31_60"] += bal
            elif b_name == "61-90 Days":
                s_rec["d61_90"] += bal
            else:
                s_rec["d90_plus"] += bal

        summary_buckets = [
            APAgingBucket(bucket_label=k, total_amount=float(bucket_totals[k]), bill_count=bucket_counts[k])
            for k in ["Current", "1-30 Days", "31-60 Days", "61-90 Days", "90+ Days"]
        ]

        supplier_summaries = [
            SupplierAPAgingSummary(
                supplier_id=s["supplier_id"],
                supplier_code=s["supplier_code"],
                supplier_name=s["supplier_name"],
                total_outstanding=float(s["total_outstanding"]),
                current_amount=float(s["current"]),
                days_1_30=float(s["d1_30"]),
                days_31_60=float(s["d31_60"]),
                days_61_90=float(s["d61_90"]),
                days_over_90=float(s["d90_plus"])
            )
            for s in supplier_agings.values()
        ]

        return APAgingReportResponse(
            as_of_date=as_of,
            total_payables=float(total_ap),
            summary_buckets=summary_buckets,
            supplier_summaries=supplier_summaries
        )
