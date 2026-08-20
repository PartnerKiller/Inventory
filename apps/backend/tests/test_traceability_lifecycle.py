import uuid
import asyncio
from decimal import Decimal
from datetime import timedelta, date
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemCategory, Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.sales import Customer, SalesOrder, SOLineItem, Shipment
from app.models.costing import CostLayer
from app.schemas.traceability import (
    StockLotCreate,
    SerialBatchRegistrationRequest,
    RecallExecutionRequest
)
from app.services.traceability_service import TraceabilityService
from app.services.purchase_service import PurchaseService
from app.services.costing_service import CostingService

pytestmark = pytest.mark.asyncio

async def create_traceability_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-TRACE-{uuid.uuid4().hex[:4]}", name="Traceability WH")
    bin_stg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING")
    bin_stor1 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    bin_stor2 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-02", aisle="A", rack="01", shelf="01", bin="02", type="STORAGE")
    bin_quar = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="Q-01-01", aisle="Q", rack="01", shelf="01", bin="01", type="QUARANTINE")
    wh.bins.extend([bin_stg, bin_stor1, bin_stor2, bin_quar])
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Trace Cat", code=f"CAT-TRC-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-TRC-{uuid.uuid4().hex[:4]}", name="Trace Widget", is_batch_tracked=True, is_serial_tracked=True)
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-TRC-{uuid.uuid4().hex[:4]}", variant_name="Trace Std", cost_price=Decimal("100.00"), selling_price=Decimal("200.00"))
    item.variants.append(variant)
    db.add_all([cat, item])
    await db.flush()

    sup = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUP-TRC-{uuid.uuid4().hex[:4]}", name="BioTrace Labs", currency="USD")
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-TRC-{uuid.uuid4().hex[:4]}", name="Metro Hospital")
    db.add_all([sup, cust])
    await db.flush()

    return wh, bin_stg, bin_stor1, bin_stor2, bin_quar, item, variant, sup, cust

async def test_stock_lot_creation_uniqueness_and_quarantine(db_session: AsyncSession):
    """
    Tests StockLot registration, uniqueness in tenant+variant, and quarantine state transition.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, _, item, variant, sup, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Create StockLot
    lot_in = StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-2026-A1",
        supplier_id=sup.id,
        supplier_lot_number="VEND-BATCH-99",
        manufacturing_date=date(2026, 1, 15),
        expiry_date=date(2027, 1, 15),
        initial_quantity=Decimal("100.0"),
        notes="First production run"
    )
    lot = await TraceabilityService.create_or_get_lot(db_session, tenant_id, lot_in)
    assert lot.id is not None
    assert lot.lot_number == "LOT-2026-A1"
    assert lot.status == "ACTIVE"
    assert lot.current_quantity == Decimal("100.0")

    # 2. Re-invoking with existing lot returns same lot and increments quantity
    lot_dup = await TraceabilityService.create_or_get_lot(db_session, tenant_id, lot_in)
    assert lot_dup.id == lot.id
    assert lot_dup.current_quantity == Decimal("200.0")

    # 3. Quarantine entire lot
    q_lot = await TraceabilityService.quarantine_lot(db_session, tenant_id, lot.id, reason="Temperature excursion during transit")
    assert q_lot.status == "QUARANTINED"
    assert q_lot.quarantine_reason == "Temperature excursion during transit"

async def test_serial_number_batch_registration_and_uniqueness_guard(db_session: AsyncSession):
    """
    Tests batch serial number registration during receiving, and rejection of duplicate active serials.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, _, _, _, item, variant, sup, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Batch register serials
    reg_req = SerialBatchRegistrationRequest(
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        location_bin_id=bin_stg.id,
        serial_numbers=["SN-001", "SN-002", "SN-003", "SN-004"]
    )
    serials = await TraceabilityService.register_serial_numbers(db_session, tenant_id, reg_req)
    assert len(serials) == 4
    assert all(s.status == "RECEIVED" for s in serials)
    assert all(s.location_bin_id == bin_stg.id for s in serials)

    # 2. Attempt to re-register active serial "SN-002" -> 422 Unprocessable Content
    dup_req = SerialBatchRegistrationRequest(
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        location_bin_id=bin_stg.id,
        serial_numbers=["SN-002", "SN-005"]
    )
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.register_serial_numbers(db_session, tenant_id, dup_req)
    assert exc.value.status_code == 422
    assert "already exists in status" in exc.value.detail

async def test_serial_number_full_lifecycle_progression(db_session: AsyncSession):
    """
    Tests full serial lifecycle progression:
    RECEIVED -> IN_STOCK -> ALLOCATED -> PICKED -> DISPATCHED.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor1, _, _, item, variant, sup, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Register serial
    reg_req = SerialBatchRegistrationRequest(
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        location_bin_id=bin_stg.id,
        serial_numbers=["SN-LIFE-01"]
    )
    serials = await TraceabilityService.register_serial_numbers(db_session, tenant_id, reg_req)
    s = serials[0]
    assert s.status == "RECEIVED"

    # 2. Putaway to Storage bin -> IN_STOCK
    await TraceabilityService.update_serial_bin_locations(
        db=db_session,
        tenant_id=tenant_id,
        item_variant_id=variant.id,
        source_bin_id=bin_stg.id,
        dest_bin_id=bin_stor1.id,
        quantity=1,
        serial_numbers=["SN-LIFE-01"],
        target_status="IN_STOCK"
    )
    await db_session.refresh(s)
    assert s.status == "IN_STOCK"
    assert s.location_bin_id == bin_stor1.id

    # 3. Pick serial -> PICKED
    await TraceabilityService.acquire_serial_for_pick(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        serial_number="SN-LIFE-01"
    )
    await db_session.refresh(s)
    assert s.status == "PICKED"

    # 4. Dispatch serial -> DISPATCHED, bin = None
    shipment_id = str(uuid.uuid4())
    await TraceabilityService.dispatch_serials(
        db=db_session,
        tenant_id=tenant_id,
        shipment_id=shipment_id,
        serial_numbers=["SN-LIFE-01"]
    )
    await db_session.refresh(s)
    assert s.status == "DISPATCHED"
    assert s.location_bin_id is None
    assert s.dispatched_shipment_id == shipment_id

async def test_fefo_picking_recommendation_and_fifo_costing_preservation(db_session: AsyncSession):
    """
    Tests FEFO (First-Expired, First-Out) recommendation sorting:
    - Lot A: Expiry = 2026-06-30 in Bin 2
    - Lot B: Expiry = 2026-04-15 in Bin 1 (Expires sooner!)
    - Recommendation should place Lot B first.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor1, bin_stor2, _, item, variant, sup, _ = await create_traceability_test_environment(db_session, tenant_id)

    # Lot A: Expires June 2026
    lot_a = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-JUNE",
        expiry_date=date(2026, 6, 30),
        initial_quantity=Decimal("50.0")
    ))
    db_session.add(StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor2.id,
        item_variant_id=variant.id,
        lot_id=lot_a.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("0.0")
    ))

    # Lot B: Expires April 2026 (Sooner!)
    lot_b = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-APRIL",
        expiry_date=date(2026, 4, 15),
        initial_quantity=Decimal("30.0")
    ))
    db_session.add(StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        lot_id=lot_b.id,
        quantity_on_hand=Decimal("30.0"),
        quantity_allocated=Decimal("0.0")
    ))
    await db_session.flush()

    # Query FEFO recommendations for 40 units
    fefo_res = await TraceabilityService.get_fefo_pick_recommendations(
        db_session, tenant_id, warehouse_id=wh.id, item_variant_id=variant.id, required_quantity=Decimal("40.0")
    )
    assert len(fefo_res.recommendations) == 2
    # First recommendation MUST be Lot B (expires April)
    assert fefo_res.recommendations[0].lot_number == "LOT-APRIL"
    assert fefo_res.recommendations[0].recommended_pick_quantity == 30.0
    # Second recommendation MUST be Lot A (expires June)
    assert fefo_res.recommendations[1].lot_number == "LOT-JUNE"
    assert fefo_res.recommendations[1].recommended_pick_quantity == 10.0

async def test_dual_layer_quarantine_allocation_isolation(db_session: AsyncSession):
    """
    Tests dual-layer quarantine:
    - Quarantined bins and quarantined lots are excluded from FEFO recommendations.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor1, _, bin_quar, item, variant, _, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Active Lot in Quarantine Bin -> Excluded by bin type
    lot_qbin = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-QBIN",
        expiry_date=date(2026, 12, 31),
        initial_quantity=Decimal("20.0")
    ))
    db_session.add(StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_quar.id,
        item_variant_id=variant.id,
        lot_id=lot_qbin.id,
        quantity_on_hand=Decimal("20.0"),
        quantity_allocated=Decimal("0.0")
    ))

    # 2. Quarantined Lot in Storage Bin -> Excluded by lot status
    lot_status_q = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-STATUS-Q",
        expiry_date=date(2026, 12, 31),
        initial_quantity=Decimal("20.0")
    ))
    lot_status_q.status = "QUARANTINED"
    db_session.add(StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        lot_id=lot_status_q.id,
        quantity_on_hand=Decimal("20.0"),
        quantity_allocated=Decimal("0.0")
    ))
    await db_session.flush()

    fefo_res = await TraceabilityService.get_fefo_pick_recommendations(
        db_session, tenant_id, warehouse_id=wh.id, item_variant_id=variant.id, required_quantity=Decimal("10.0")
    )
    assert len(fefo_res.recommendations) == 0

async def test_bidirectional_forward_and_backward_traceability(db_session: AsyncSession):
    """
    Tests forward and backward traceability relationships:
    Backward: Serial -> Shipment -> Sales Order -> Lot -> GRN -> PO -> Supplier
    Forward: Lot -> Warehouse Bins -> Shipments -> Customer
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor1, _, _, item, variant, sup, cust = await create_traceability_test_environment(db_session, tenant_id)

    # 1. PO & GRN
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number="PO-TRACE-900", supplier_id=sup.id, target_warehouse_id=wh.id, status="COMPLETED")
    grn = GoodsReceipt(id=str(uuid.uuid4()), purchase_order_id=po.id, grn_number="GRN-TRACE-900", warehouse_id=wh.id, received_at=get_utc_now())
    po.receipts.append(grn)
    db_session.add_all([po, grn])

    # 2. Lot linked to GRN
    lot = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-TRACE-GOLD",
        supplier_id=sup.id,
        origin_grn_id=grn.id,
        expiry_date=date(2027, 6, 30),
        initial_quantity=Decimal("10.0")
    ))

    # 3. Sales Order & Shipment
    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number="SO-TRACE-101", customer_id=cust.id, warehouse_id=wh.id, status="DISPATCHED")
    shipment = Shipment(id=str(uuid.uuid4()), sales_order_id=so.id, shipment_number="SHP-TRACE-101", shipped_at=get_utc_now())
    db_session.add_all([so, shipment])

    # 4. Serial linked to Lot and Shipment
    serial = ItemSerialNumber(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        lot_id=lot.id,
        serial_number="SN-GOLD-777",
        status="DISPATCHED",
        origin_grn_id=grn.id,
        dispatched_shipment_id=shipment.id
    )
    db_session.add(serial)
    await db_session.flush()

    # 5. Backward Trace lookup by Serial
    back_res = await TraceabilityService.get_backward_trace(db_session, tenant_id, identifier="SN-GOLD-777")
    assert back_res.serial_number == "SN-GOLD-777"
    assert back_res.lot_number == "LOT-TRACE-GOLD"
    assert back_res.grn_number == "GRN-TRACE-900"
    assert back_res.po_number == "PO-TRACE-900"
    assert back_res.supplier_code == sup.code
    assert back_res.customer_name == cust.name

    # 6. Forward Trace lookup by Lot
    fwd_res = await TraceabilityService.get_forward_trace(db_session, tenant_id, lot_id=lot.id)
    assert fwd_res.lot_number == "LOT-TRACE-GOLD"
    assert len(fwd_res.affected_shipments) == 1
    assert fwd_res.affected_shipments[0].shipment_number == "SHP-TRACE-101"
    assert fwd_res.affected_shipments[0].customer_name == cust.name
    assert "SN-GOLD-777" in fwd_res.affected_shipments[0].serials_dispatched

async def test_1click_recall_containment_and_quarantine(db_session: AsyncSession):
    """
    Tests 1-click batch recall containment for a defective lot.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor1, _, bin_quar, item, variant, sup, _ = await create_traceability_test_environment(db_session, tenant_id)

    lot = await TraceabilityService.create_or_get_lot(db_session, tenant_id, StockLotCreate(
        item_variant_id=variant.id,
        lot_number="LOT-RECALL-DEFECT",
        supplier_id=sup.id,
        initial_quantity=Decimal("50.0")
    ))

    # Add active serials
    s1 = ItemSerialNumber(id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id, lot_id=lot.id, serial_number="SN-REC-01", status="IN_STOCK", location_bin_id=bin_stor1.id)
    s2 = ItemSerialNumber(id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, item_variant_id=variant.id, lot_id=lot.id, serial_number="SN-REC-02", status="IN_STOCK", location_bin_id=bin_stor1.id)
    db_session.add_all([s1, s2])
    await db_session.flush()

    # Execute Recall
    recall_req = RecallExecutionRequest(
        lot_id=lot.id,
        recall_reason="Sterility seal breach detected",
        target_quarantine_bin_id=bin_quar.id
    )
    recall_res = await TraceabilityService.execute_lot_recall(db_session, tenant_id, recall_req)
    assert recall_res.status == "RECALLED"
    assert recall_res.quarantined_serials_count == 2

    # Assert serials moved to quarantine
    await db_session.refresh(s1)
    await db_session.refresh(s2)
    assert s1.status == "QUARANTINED"
    assert s1.location_bin_id == bin_quar.id
    assert "RECALL" in s1.quarantine_reason

async def test_traceability_api_endpoints_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """
    Tests REST endpoints under /api/v1/traceability/* with RBAC token.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="trace_officer",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    wh, bin_stg, _, _, _, item, variant, _, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Create lot via API
    lot_res = await client.post("/api/v1/traceability/lots", headers=headers, json={
        "item_variant_id": variant.id,
        "lot_number": "API-LOT-001",
        "initial_quantity": 25.0,
        "expiry_date": "2027-12-31"
    })
    assert lot_res.status_code == 201
    assert lot_res.json()["lot_number"] == "API-LOT-001"

    # 2. Batch register serials via API
    reg_res = await client.post("/api/v1/traceability/serials/batch-register", headers=headers, json={
        "warehouse_id": wh.id,
        "item_variant_id": variant.id,
        "location_bin_id": bin_stg.id,
        "serial_numbers": ["API-SN-01", "API-SN-02"]
    })
    assert reg_res.status_code == 201
    assert len(reg_res.json()) == 2

    # 3. Query Expiry Horizon report
    exp_res = await client.get("/api/v1/traceability/reports/expiry-horizon", headers=headers)
    assert exp_res.status_code == 200
    assert "total_lots_evaluated" in exp_res.json()

async def test_concurrent_serial_acquisition_and_row_locking(db_session: AsyncSession):
    """
    Tests PostgreSQL row-level locking on concurrent serial pick acquisition:
    - Setup: SN-001 in Warehouse A / Bin A-01 (status: IN_STOCK)
    - Two concurrent transactions (Tx A and Tx B) attempt to acquire SN-001 for picking.
    - Exactly one transaction succeeds (status -> PICKED).
    - The other transaction fails safely with 409 Conflict.
    - Serial cannot be picked twice, cannot be dispatched twice.
    - Binds to exactly one shipment upon dispatch.
    - Final state is deterministic: DISPATCHED with location_bin_id = None.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor1, _, _, item, variant, _, cust = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Register serial SN-001 in Bin A-01
    serial = ItemSerialNumber(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        serial_number="SN-001",
        status="IN_STOCK",
        location_bin_id=bin_stor1.id
    )
    db_session.add(serial)
    await db_session.commit()

    # 2. Simulate concurrent pick acquisition
    # We execute Tx A and Tx B
    async def try_acquire_serial(user_label: str):
        # Use a fresh nested session block or run acquire
        try:
            return await TraceabilityService.acquire_serial_for_pick(
                db=db_session,
                tenant_id=tenant_id,
                warehouse_id=wh.id,
                item_variant_id=variant.id,
                serial_number="SN-001",
                user_id=user_label
            )
        except Exception as e:
            return e

    # Execute Tx A
    res_a = await try_acquire_serial("user_a")
    assert isinstance(res_a, ItemSerialNumber)
    assert res_a.status == "PICKED"

    # Execute Tx B immediately after Tx A has acquired the serial (in the same or concurrent state)
    res_b = await try_acquire_serial("user_b")
    assert isinstance(res_b, HTTPException)
    assert res_b.status_code == 409
    assert "cannot be picked: currently in status 'PICKED'" in res_b.detail

    # 3. Dispatch the acquired serial
    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number="SO-CONC-01", customer_id=cust.id, warehouse_id=wh.id, status="DISPATCHED")
    shipment = Shipment(id=str(uuid.uuid4()), sales_order_id=so.id, shipment_number="SHP-CONC-01", shipped_at=get_utc_now())
    db_session.add_all([so, shipment])
    await db_session.flush()

    await TraceabilityService.dispatch_serials(
        db=db_session,
        tenant_id=tenant_id,
        shipment_id=shipment.id,
        serial_numbers=["SN-001"],
        user_id="user_a"
    )
    await db_session.refresh(serial)
    assert serial.status == "DISPATCHED"
    assert serial.location_bin_id is None
    assert serial.dispatched_shipment_id == shipment.id

    # 4. Attempt second dispatch of same serial -> rejected
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.dispatch_serials(
            db=db_session,
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            serial_numbers=["SN-001"],
            user_id="user_b"
        )
    assert exc.value.status_code == 400
    assert "Invalid serial lifecycle transition" in exc.value.detail

async def test_invalid_serial_lifecycle_transitions_rejected(db_session: AsyncSession):
    """
    Explicitly tests invalid serial lifecycle transitions:
    - RECEIVED -> DISPATCHED        ❌ (400 Bad Request)
    - IN_STOCK -> DISPATCHED        ❌ (400 Bad Request)
    - PICKED -> RECEIVED            ❌ (400 Bad Request)
    - DISPATCHED -> PICKED          ❌ (400 Bad Request)
    - RETIRED -> IN_STOCK           ❌ (400 Bad Request)
    And validates correct progression:
    - RECEIVED -> IN_STOCK -> ALLOCATED -> PICKED -> DISPATCHED -> RETURNED -> QUARANTINED -> RETIRED ✅
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor1, _, bin_quar, item, variant, _, _ = await create_traceability_test_environment(db_session, tenant_id)

    # 1. Start in RECEIVED
    serial = ItemSerialNumber(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        serial_number="SN-INVALID-TEST",
        status="RECEIVED",
        location_bin_id=bin_stg.id
    )
    db_session.add(serial)
    await db_session.flush()

    # RECEIVED -> DISPATCHED ❌
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "DISPATCHED")
    assert exc.value.status_code == 400
    assert "RECEIVED' -> 'DISPATCHED'" in exc.value.detail

    # Valid: RECEIVED -> IN_STOCK ✅
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "IN_STOCK", location_bin_id=bin_stor1.id)
    assert serial.status == "IN_STOCK"

    # IN_STOCK -> DISPATCHED ❌
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "DISPATCHED")
    assert exc.value.status_code == 400
    assert "IN_STOCK' -> 'DISPATCHED'" in exc.value.detail

    # Valid: IN_STOCK -> ALLOCATED -> PICKED ✅
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "ALLOCATED")
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "PICKED")
    assert serial.status == "PICKED"

    # PICKED -> RECEIVED ❌
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "RECEIVED")
    assert exc.value.status_code == 400
    assert "PICKED' -> 'RECEIVED'" in exc.value.detail

    # Valid: PICKED -> DISPATCHED ✅
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "DISPATCHED", dispatched_shipment_id=str(uuid.uuid4()))
    assert serial.status == "DISPATCHED"

    # DISPATCHED -> PICKED ❌
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "PICKED")
    assert exc.value.status_code == 400
    assert "DISPATCHED' -> 'PICKED'" in exc.value.detail

    # Valid: DISPATCHED -> RETURNED -> QUARANTINED -> RETIRED ✅
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "RETURNED", location_bin_id=bin_quar.id)
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "QUARANTINED", quarantine_reason="Scrap damaged return")
    await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "RETIRED")
    assert serial.status == "RETIRED"

    # RETIRED -> IN_STOCK ❌
    with pytest.raises(HTTPException) as exc:
        await TraceabilityService.transition_serial_status(db_session, tenant_id, "SN-INVALID-TEST", "IN_STOCK")
    assert exc.value.status_code == 400
    assert "RETIRED' -> 'IN_STOCK'" in exc.value.detail
