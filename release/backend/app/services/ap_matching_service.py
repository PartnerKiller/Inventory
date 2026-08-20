from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.ap import APMatchingTolerance, VendorInvoice, VendorInvoiceLine
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine

class APMatchingService:
    @staticmethod
    async def get_or_create_tolerances(
        db: AsyncSession,
        tenant_id: str
    ) -> APMatchingTolerance:
        stmt = select(APMatchingTolerance).where(APMatchingTolerance.tenant_id == tenant_id)
        tol = (await db.execute(stmt)).scalar_one_or_none()
        if not tol:
            tol = APMatchingTolerance(
                tenant_id=tenant_id,
                price_tolerance_pct=Decimal("2.0"),
                price_tolerance_max_amount=Decimal("50.0"),
                quantity_tolerance_pct=Decimal("0.0"),
                auto_approve_within_tolerance=True
            )
            db.add(tol)
            await db.flush()
        return tol

    @classmethod
    async def evaluate_3way_match(
        cls,
        db: AsyncSession,
        tenant_id: str,
        po: PurchaseOrder,
        grn: Optional[GoodsReceipt],
        lines_data: List[Dict[str, Any]]
    ) -> Tuple[str, str, List[Dict[str, Any]], str]:
        """
        Evaluates 3-way match across PO, GRN (if present), and vendor invoice lines.
        Returns: (overall_status, match_status, matched_line_results, match_notes)
        """
        tolerances = await cls.get_or_create_tolerances(db, tenant_id)

        # Build lookup maps for PO and GRN lines
        po_lines_map = {l.id: l for l in po.lines}
        grn_lines_map = {}
        if grn:
            grn_lines_map = {l.id: l for l in grn.lines}
        else:
            # Aggregate all receipts on PO
            for r in po.receipts:
                for rl in r.lines:
                    grn_lines_map[rl.po_line_id] = rl

        has_qty_exception = False
        has_price_exception = False
        has_variance = False
        match_notes = []
        line_results = []

        for line_in in lines_data:
            po_line_id = line_in["po_line_id"]
            grn_line_id = line_in.get("grn_line_id")
            billed_qty = Decimal(str(line_in["billed_quantity"]))
            billed_price = Decimal(str(line_in["billed_unit_price"]))
            tax_pct = Decimal(str(line_in.get("tax_pct", 0.0)))

            po_line = po_lines_map.get(po_line_id)
            if not po_line:
                has_qty_exception = True
                match_notes.append(f"PO line '{po_line_id}' not found on PO {po.po_number}")
                continue

            po_price = Decimal(str(po_line.unit_price))
            received_qty = Decimal(str(po_line.quantity_received or 0.0))
            if grn_line_id and grn_line_id in grn_lines_map:
                received_qty = Decimal(str(grn_lines_map[grn_line_id].quantity_received))

            # 1. Quantity Variance Check
            allowed_qty = received_qty * (Decimal("1.0") + (tolerances.quantity_tolerance_pct / Decimal("100.0")))
            if billed_qty > allowed_qty:
                has_qty_exception = True
                match_notes.append(
                    f"Quantity exception on item {po_line.variant.variant_sku if po_line.variant else po_line.item_variant_id}: "
                    f"Billed {billed_qty} > Received {received_qty}"
                )

            # 2. Price Variance Check (PPV)
            price_var_unit = billed_price - po_price
            tot_price_var = billed_qty * price_var_unit

            if po_price > Decimal("0.0"):
                price_var_pct = (abs(price_var_unit) / po_price) * Decimal("100.0")
            else:
                price_var_pct = Decimal("0.0") if billed_price == Decimal("0.0") else Decimal("100.0")

            if price_var_pct > Decimal("0.0"):
                has_variance = True

            if price_var_pct > tolerances.price_tolerance_pct or abs(tot_price_var) > tolerances.price_tolerance_max_amount:
                has_price_exception = True
                match_notes.append(
                    f"Price exception on item {po_line.variant.variant_sku if po_line.variant else po_line.item_variant_id}: "
                    f"Billed ${billed_price} vs PO ${po_price} ({price_var_pct:.2f}% variance, ${abs(tot_price_var):.2f} total variance)"
                )

            line_gross = billed_qty * billed_price
            line_tax = line_gross * (tax_pct / Decimal("100.0"))
            line_tot = line_gross + line_tax

            line_results.append({
                "po_line_id": po_line.id,
                "grn_line_id": grn_line_id,
                "item_variant_id": po_line.item_variant_id,
                "billed_quantity": billed_qty,
                "received_quantity": received_qty,
                "po_unit_price": po_price,
                "billed_unit_price": billed_price,
                "price_variance_unit": price_var_unit,
                "total_price_variance": tot_price_var,
                "tax_pct": tax_pct,
                "line_total": line_tot
            })

        # Determine overall match status
        if has_qty_exception:
            match_status = "QUANTITY_VARIANCE_EXCEPTION"
            overall_status = "EXCEPTION_HOLD"
        elif has_price_exception:
            match_status = "PRICE_VARIANCE_EXCEPTION"
            overall_status = "EXCEPTION_HOLD"
        elif has_variance:
            match_status = "WITHIN_TOLERANCE"
            overall_status = "APPROVED" if tolerances.auto_approve_within_tolerance else "MATCHED"
        else:
            match_status = "EXACT_MATCH"
            overall_status = "APPROVED"

        notes_str = "; ".join(match_notes) if match_notes else "3-Way Match Passed"
        return overall_status, match_status, line_results, notes_str
