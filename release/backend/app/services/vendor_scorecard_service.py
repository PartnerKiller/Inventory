import uuid
from decimal import Decimal
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine, SupplierReturn, SupplierReturnLine
from app.models.ap import VendorInvoice, VendorInvoiceLine
from app.models.vendor_scorecard import SupplierScorecard
from app.schemas.vendor_scorecard import SupplierScorecardResponse

class VendorScorecardService:

    @staticmethod
    async def generate_supplier_scorecard(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        period_code: str = "ALL_TIME",
        notes: Optional[str] = None
    ) -> SupplierScorecardResponse:
        supplier = (await db.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found")

        # 1. Fetch Purchase Orders for Supplier
        pos = (await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.status.in_(["APPROVED", "PARTIALLY_RECEIVED", "COMPLETED"])
            )
        )).scalars().all()

        total_pos = len(pos)
        on_time_count = 0
        total_delivered_pos = 0

        for po in pos:
            if po.receipts:
                total_delivered_pos += 1
                if po.expected_delivery_at:
                    latest_receipt_time = max(r.received_at for r in po.receipts)
                    if latest_receipt_time <= po.expected_delivery_at:
                        on_time_count += 1
                else:
                    on_time_count += 1

        if total_delivered_pos > 0:
            otd_pct = (Decimal(str(on_time_count)) / Decimal(str(total_delivered_pos)) * Decimal("100.0")).quantize(Decimal("0.01"))
        else:
            otd_pct = Decimal("100.00")

        # 2. Fetch Received Units & Rejections (Quality Acceptance)
        total_received = Decimal("0.0")
        for po in pos:
            for line in po.lines:
                total_received += line.quantity_received

        returns = (await db.execute(
            select(SupplierReturn).where(
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.supplier_id == supplier_id,
                SupplierReturn.status.in_(["APPROVED", "COMPLETED"])
            )
        )).scalars().all()

        total_rejected = Decimal("0.0")
        for ret in returns:
            for r_line in ret.lines:
                total_rejected += r_line.quantity_returned

        if total_received > Decimal("0.0"):
            accepted_units = max(Decimal("0.0"), total_received - total_rejected)
            qa_pct = ((accepted_units / total_received) * Decimal("100.0")).quantize(Decimal("0.01"))
        else:
            qa_pct = Decimal("100.00")

        # 3. Price Variance & Compliance
        price_compliance_pct = Decimal("100.00")
        price_variance = Decimal("0.0000")

        # 4. Overall Weighted Score & Tier Grade
        # Score = 0.50 * OTD + 0.40 * QA + 0.10 * Price Compliance
        overall_score = (
            (otd_pct * Decimal("0.50")) +
            (qa_pct * Decimal("0.40")) +
            (price_compliance_pct * Decimal("0.10"))
        ).quantize(Decimal("0.01"))

        if overall_score >= Decimal("90.00"):
            tier = "TIER_A_PREFERRED"
        elif overall_score >= Decimal("75.00"):
            tier = "TIER_B_APPROVED"
        elif overall_score >= Decimal("60.00"):
            tier = "TIER_C_PROBATIONARY"
        else:
            tier = "TIER_D_RESTRICTED"

        # 5. Upsert SupplierScorecard
        scorecard = (await db.execute(
            select(SupplierScorecard).where(
                SupplierScorecard.tenant_id == tenant_id,
                SupplierScorecard.supplier_id == supplier_id,
                SupplierScorecard.period_code == period_code
            ).with_for_update()
        )).scalar_one_or_none()

        now_utc = get_utc_now()
        if not scorecard:
            scorecard = SupplierScorecard(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                period_code=period_code,
                total_pos_count=total_pos,
                on_time_deliveries_count=on_time_count,
                otd_percentage=otd_pct,
                total_received_units=total_received,
                rejected_units_count=total_rejected,
                quality_acceptance_percentage=qa_pct,
                price_variance_amount=price_variance,
                price_compliance_percentage=price_compliance_pct,
                overall_vendor_score=overall_score,
                tier_grade=tier,
                evaluated_at=now_utc,
                notes=notes
            )
            db.add(scorecard)
        else:
            scorecard.total_pos_count = total_pos
            scorecard.on_time_deliveries_count = on_time_count
            scorecard.otd_percentage = otd_pct
            scorecard.total_received_units = total_received
            scorecard.rejected_units_count = total_rejected
            scorecard.quality_acceptance_percentage = qa_pct
            scorecard.price_variance_amount = price_variance
            scorecard.price_compliance_percentage = price_compliance_pct
            scorecard.overall_vendor_score = overall_score
            scorecard.tier_grade = tier
            scorecard.evaluated_at = now_utc
            if notes:
                scorecard.notes = notes

        await db.commit()
        await db.refresh(scorecard)

        return SupplierScorecardResponse(
            id=scorecard.id,
            tenant_id=scorecard.tenant_id,
            supplier_id=scorecard.supplier_id,
            period_code=scorecard.period_code,
            total_pos_count=scorecard.total_pos_count,
            on_time_deliveries_count=scorecard.on_time_deliveries_count,
            otd_percentage=scorecard.otd_percentage,
            total_received_units=scorecard.total_received_units,
            rejected_units_count=scorecard.rejected_units_count,
            quality_acceptance_percentage=scorecard.quality_acceptance_percentage,
            price_variance_amount=scorecard.price_variance_amount,
            price_compliance_percentage=scorecard.price_compliance_percentage,
            overall_vendor_score=scorecard.overall_vendor_score,
            tier_grade=scorecard.tier_grade,
            evaluated_at=scorecard.evaluated_at,
            notes=scorecard.notes,
            created_at=scorecard.created_at
        )

    @staticmethod
    async def get_supplier_scorecards(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: Optional[str] = None,
        period_code: Optional[str] = None
    ) -> List[SupplierScorecardResponse]:
        query = select(SupplierScorecard).where(SupplierScorecard.tenant_id == tenant_id)
        if supplier_id:
            query = query.where(SupplierScorecard.supplier_id == supplier_id)
        if period_code:
            query = query.where(SupplierScorecard.period_code == period_code)
        query = query.order_by(SupplierScorecard.evaluated_at.desc())

        results = (await db.execute(query)).scalars().all()
        return [
            SupplierScorecardResponse(
                id=sc.id,
                tenant_id=sc.tenant_id,
                supplier_id=sc.supplier_id,
                period_code=sc.period_code,
                total_pos_count=sc.total_pos_count,
                on_time_deliveries_count=sc.on_time_deliveries_count,
                otd_percentage=sc.otd_percentage,
                total_received_units=sc.total_received_units,
                rejected_units_count=sc.rejected_units_count,
                quality_acceptance_percentage=sc.quality_acceptance_percentage,
                price_variance_amount=sc.price_variance_amount,
                price_compliance_percentage=sc.price_compliance_percentage,
                overall_vendor_score=sc.overall_vendor_score,
                tier_grade=sc.tier_grade,
                evaluated_at=sc.evaluated_at,
                notes=sc.notes,
                created_at=sc.created_at
            ) for sc in results
        ]
