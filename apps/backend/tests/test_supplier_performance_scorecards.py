import pytest
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine, SupplierReturn, SupplierReturnLine
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant
from app.models.vendor_scorecard import SupplierScorecard
from app.schemas.vendor_scorecard import SupplierScorecardGenerateRequest
from app.services.vendor_scorecard_service import VendorScorecardService

# ============================================================================
# 1. SUPPLIER SCORECARD CALCULATION & WEIGHTED TIER CLASSIFICATION
# ============================================================================

@pytest.mark.asyncio
async def test_supplier_scorecard_on_time_delivery_and_quality_scoring(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    # 1. Create Supplier
    supp = Supplier(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-PREF-{uuid.uuid4().hex[:4].upper()}",
        name="Precision Industrial Components Corp", is_active=True
    )
    db_session.add(supp)
    await db_session.flush()

    # 2. Create Warehouse & Item
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-VSC-{uuid.uuid4().hex[:4]}", name="Scorecard WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-VSC-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-BOLT-{uuid.uuid4().hex[:4]}", name="Titanium Flange Bolt", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Titanium Bolt M8", cost_price=Decimal("10.0"), selling_price=Decimal("20.0"))
    db_session.add(var)
    await db_session.flush()

    # 3. Create PO 1: Expected delivery in 5 days, Received on time (100 units)
    now_utc = datetime.now(timezone.utc)
    po1 = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-VSC-{uuid.uuid4().hex[:4].upper()}",
        supplier_id=supp.id, target_warehouse_id=wh.id, status="APPROVED",
        expected_delivery_at=now_utc + timedelta(days=5), ordered_at=now_utc
    )
    db_session.add(po1)
    await db_session.flush()

    po_line1 = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po1.id, item_variant_id=var.id,
        quantity_ordered=Decimal("100.0"), quantity_received=Decimal("100.0"), unit_price=Decimal("10.0"), line_total=Decimal("1000.0")
    )
    db_session.add(po_line1)

    gr1 = GoodsReceipt(
        id=str(uuid.uuid4()), purchase_order_id=po1.id, grn_number=f"GRN-VSC-{uuid.uuid4().hex[:4].upper()}",
        warehouse_id=wh.id, received_at=now_utc + timedelta(days=2) # Arrived early -> on time
    )
    db_session.add(gr1)

    # 4. Supplier Return: 2 defective units returned
    ret = SupplierReturn(
        id=str(uuid.uuid4()), tenant_id=tenant_id, return_number=f"RET-VSC-{uuid.uuid4().hex[:4].upper()}",
        supplier_id=supp.id, purchase_order_id=po1.id, warehouse_id=wh.id, status="COMPLETED",
        return_reason="DEFECTIVE", total_refund_amount=Decimal("20.0")
    )
    db_session.add(ret)
    await db_session.flush()

    ret_line = SupplierReturnLine(
        id=str(uuid.uuid4()), supplier_return_id=ret.id, item_variant_id=var.id,
        source_location_bin_id=bin_loc.id, quantity_returned=Decimal("2.0"), unit_cost=Decimal("10.0"), total_cost=Decimal("20.0")
    )
    db_session.add(ret_line)
    await db_session.commit()

    # 5. Generate Scorecard
    scorecard = await VendorScorecardService.generate_supplier_scorecard(
        db=db_session, tenant_id=tenant_id, supplier_id=supp.id, period_code="2026-Q1"
    )

    assert scorecard.supplier_id == supp.id
    assert scorecard.period_code == "2026-Q1"
    assert scorecard.total_pos_count == 1
    assert scorecard.on_time_deliveries_count == 1
    assert scorecard.otd_percentage == Decimal("100.00")
    assert scorecard.total_received_units == Decimal("100.0")
    assert scorecard.rejected_units_count == Decimal("2.0")
    assert scorecard.quality_acceptance_percentage == Decimal("98.00") # (98 / 100) * 100 = 98.00%
    # Overall score = (0.50 * 100) + (0.40 * 98) + (0.10 * 100) = 50 + 39.2 + 10 = 99.20
    assert scorecard.overall_vendor_score == Decimal("99.20")
    assert scorecard.tier_grade == "TIER_A_PREFERRED"

# ============================================================================
# 2. LATE DELIVERIES & QUALITY DEFECTS RESULT IN PROBATIONARY/RESTRICTED TIER
# ============================================================================

@pytest.mark.asyncio
async def test_late_delivery_and_defect_demotion(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    supp_late = Supplier(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-LATE-{uuid.uuid4().hex[:4].upper()}",
        name="Lagging Logistical Suppliers Ltd", is_active=True
    )
    db_session.add(supp_late)
    await db_session.flush()

    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-LATE-{uuid.uuid4().hex[:4]}", name="Late WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-LATE-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-PIPE-{uuid.uuid4().hex[:4]}", name="Steel Pipe", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Steel Pipe 2m", cost_price=Decimal("50.0"), selling_price=Decimal("80.0"))
    db_session.add(var)
    await db_session.flush()

    # PO Expected yesterday, received today -> LATE
    now_utc = datetime.now(timezone.utc)
    po_late = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-LATE-{uuid.uuid4().hex[:4].upper()}",
        supplier_id=supp_late.id, target_warehouse_id=wh.id, status="APPROVED",
        expected_delivery_at=now_utc - timedelta(days=2), ordered_at=now_utc - timedelta(days=10)
    )
    db_session.add(po_late)
    await db_session.flush()

    po_line = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po_late.id, item_variant_id=var.id,
        quantity_ordered=Decimal("50.0"), quantity_received=Decimal("50.0"), unit_price=Decimal("50.0"), line_total=Decimal("2500.0")
    )
    db_session.add(po_line)

    gr_late = GoodsReceipt(
        id=str(uuid.uuid4()), purchase_order_id=po_late.id, grn_number=f"GRN-LATE-{uuid.uuid4().hex[:4].upper()}",
        warehouse_id=wh.id, received_at=now_utc # Arrived 2 days late
    )
    db_session.add(gr_late)

    # 25 out of 50 units returned defective (50% defect rate)
    ret = SupplierReturn(
        id=str(uuid.uuid4()), tenant_id=tenant_id, return_number=f"RET-LATE-{uuid.uuid4().hex[:4].upper()}",
        supplier_id=supp_late.id, purchase_order_id=po_late.id, warehouse_id=wh.id, status="COMPLETED",
        return_reason="DEFECTIVE", total_refund_amount=Decimal("1250.0")
    )
    db_session.add(ret)
    await db_session.flush()

    ret_line = SupplierReturnLine(
        id=str(uuid.uuid4()), supplier_return_id=ret.id, item_variant_id=var.id,
        source_location_bin_id=bin_loc.id, quantity_returned=Decimal("25.0"), unit_cost=Decimal("50.0"), total_cost=Decimal("1250.0")
    )
    db_session.add(ret_line)
    await db_session.commit()

    scorecard = await VendorScorecardService.generate_supplier_scorecard(
        db=db_session, tenant_id=tenant_id, supplier_id=supp_late.id, period_code="2026-Q1"
    )

    assert scorecard.on_time_deliveries_count == 0
    assert scorecard.otd_percentage == Decimal("0.00")
    assert scorecard.quality_acceptance_percentage == Decimal("50.00")
    # Score = (0.50 * 0) + (0.40 * 50) + (0.10 * 100) = 0 + 20 + 10 = 30.00
    assert scorecard.overall_vendor_score == Decimal("30.00")
    assert scorecard.tier_grade == "TIER_D_RESTRICTED"
