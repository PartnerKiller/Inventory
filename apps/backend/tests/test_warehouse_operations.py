import uuid
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.item import Item, ItemVariant, Barcode, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt
from app.models.sales import Customer, SalesOrder, SOLineItem, Shipment, SOAllocation
from app.models.costing import ItemCostProfile, CostLayer
from app.schemas.purchasing import PurchaseOrderCreate, POLineCreate, GoodsReceiptCreate, GoodsReceiptLineCreate
from app.services.warehouse_service import WarehouseService
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService
from app.services.sales_service import SalesService
from app.services.purchase_service import PurchaseService

pytestmark = pytest.mark.asyncio

async def create_warehouse_ops_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-OPS-{uuid.uuid4().hex[:4]}", name="Floor Operations WH")
    bin_staging = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING")
    bin_storage1 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    bin_storage2 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="B-02-01", aisle="B", rack="02", shelf="01", bin="01", type="STORAGE")
    wh.bins.extend([bin_staging, bin_storage1, bin_storage2])
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Ops Cat", code=f"CAT-OPS-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-OPS-{uuid.uuid4().hex[:4]}", name="Ops Widget", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-OPS-{uuid.uuid4().hex[:4]}", variant_name="Standard", cost_price=Decimal("45.00"), selling_price=Decimal("90.00"))
    barcode = Barcode(id=str(uuid.uuid4()), item_variant_id=variant.id, barcode_value=f"890{uuid.uuid4().hex[:10]}", is_primary=True)
    item.variants.append(variant)
    variant.barcodes.append(barcode)

    db.add_all([cat, item])
    await db.flush()

    return wh, bin_staging, bin_storage1, bin_storage2, item, variant, barcode

async def test_universal_barcode_resolver(db_session: AsyncSession):
    """
    Tests resolution of product barcodes, variant SKUs, bin codes, and document codes.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_staging, bin_storage1, _, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # 1. Resolve by variant barcode
    res_bar = await WarehouseService.resolve_barcode(db_session, tenant_id, barcode.barcode_value)
    assert res_bar.found is True
    assert res_bar.entity_type == "VARIANT"
    assert res_bar.identifier == variant.variant_sku
    assert res_bar.payload["variant_id"] == variant.id

    # 2. Resolve by variant SKU
    res_sku = await WarehouseService.resolve_barcode(db_session, tenant_id, variant.variant_sku)
    assert res_sku.found is True
    assert res_sku.entity_type == "VARIANT"

    # 3. Resolve by Bin Prefix
    res_bin_pref = await WarehouseService.resolve_barcode(db_session, tenant_id, f"BIN:{bin_storage1.code}")
    assert res_bin_pref.found is True
    assert res_bin_pref.entity_type == "LOCATION_BIN"
    assert res_bin_pref.identifier == bin_storage1.code
    assert res_bin_pref.payload["bin_id"] == bin_storage1.id

    # 4. Resolve by Raw Bin Code
    res_bin_raw = await WarehouseService.resolve_barcode(db_session, tenant_id, bin_staging.code)
    assert res_bin_raw.found is True
    assert res_bin_raw.entity_type == "LOCATION_BIN"

    # 5. Resolve unknown barcode
    res_unk = await WarehouseService.resolve_barcode(db_session, tenant_id, "NON_EXISTENT_999")
    assert res_unk.found is False
    assert res_unk.entity_type == "UNKNOWN"

async def test_putaway_staging_to_storage_and_cost_preservation(db_session: AsyncSession):
    """
    Tests transfer from staging bin to storage shelf.
    Asserts exact physical stock relocation and zero costing mutation.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_staging, bin_storage1, _, item, variant, _ = await create_warehouse_ops_environment(db_session, tenant_id)

    # Inbound 100 units @ $45.00 into STAGING bin
    bal_stg = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_staging.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("100.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal_stg)
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("100.0"), Decimal("45.00"))
    await db_session.flush()

    # Capture pre-putaway cost profile
    prof_before = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    cost_val_before = prof_before.current_total_value

    # Execute putaway of 60 units from Staging to Storage
    resp = await WarehouseService.execute_putaway(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        source_staging_bin_id=bin_staging.id,
        destination_storage_bin_id=bin_storage1.id,
        item_variant_id=variant.id,
        quantity=Decimal("60.0")
    )
    assert resp.success is True
    assert resp.transferred_quantity == 60.0

    # Verify physical balances
    await db_session.refresh(bal_stg)
    assert bal_stg.quantity_on_hand == Decimal("40.0")

    bal_dst = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_storage1.id,
            StockBalanceCache.item_variant_id == variant.id
        )
    )).scalar_one()
    assert bal_dst.quantity_on_hand == Decimal("60.0")

    # Verify Cost Basis is strictly preserved!
    prof_after = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert prof_after.current_total_value == cost_val_before

async def test_bin_to_bin_rapid_movement_and_atomic_balance(db_session: AsyncSession):
    """
    Tests intra-warehouse bin-to-bin movements with available stock validation.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_storage1, bin_storage2, item, variant, _ = await create_warehouse_ops_environment(db_session, tenant_id)

    # Seed 50 units in Storage Bin 1 (10 allocated, 40 available)
    bal_1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_storage1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("10.0")
    )
    db_session.add(bal_1)
    await db_session.flush()

    # Attempt to transfer 45 units (should fail because available is only 40)
    with pytest.raises(Exception):
        await WarehouseService.execute_bin_transfer(
            db=db_session,
            tenant_id=tenant_id,
            warehouse_id=wh.id,
            source_bin_id=bin_storage1.id,
            destination_bin_id=bin_storage2.id,
            item_variant_id=variant.id,
            quantity=Decimal("45.0")
        )

    # Valid transfer of 25 units
    res = await WarehouseService.execute_bin_transfer(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        source_bin_id=bin_storage1.id,
        destination_bin_id=bin_storage2.id,
        item_variant_id=variant.id,
        quantity=Decimal("25.0")
    )
    assert res.success is True
    assert res.transferred_quantity == 25.0

    await db_session.refresh(bal_1)
    assert bal_1.quantity_on_hand == Decimal("25.0")
    assert (bal_1.quantity_on_hand - bal_1.quantity_allocated) == Decimal("15.0")

    bal_2 = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_storage2.id,
            StockBalanceCache.item_variant_id == variant.id
        )
    )).scalar_one()
    assert bal_2.quantity_on_hand == Decimal("25.0")

async def test_cycle_count_session_workflow_and_approval_invariants(db_session: AsyncSession):
    """
    Tests two-person cycle count workflow:
    1. Clerk creates session and records floor counts. Stock is NOT mutated yet.
    2. Supervisor reviews variances (+5 units) and approves.
    3. Authoritative ledger adjustment and costing engine update execute automatically.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_storage1, _, item, variant, _ = await create_warehouse_ops_environment(db_session, tenant_id)

    # Seed 20 units in storage bin
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_storage1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("20.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("20.0"), Decimal("45.00"))
    await db_session.flush()

    # Step 1: Create Count Session
    session_res = await WarehouseService.create_count_session(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        scope_type="CUSTOM_BINS",
        bin_ids=[bin_storage1.id]
    )
    assert session_res.total_lines == 1
    assert session_res.lines[0].expected_quantity == 20.0

    # Step 2: Operator submits floor count of 25 units (+5 variance)
    submit_res = await WarehouseService.submit_count_results(
        db=db_session,
        tenant_id=tenant_id,
        session_id=session_res.id,
        counts=[{"location_bin_id": bin_storage1.id, "item_variant_id": variant.id, "counted_quantity": 25.0}]
    )
    assert submit_res.status == "PENDING_REVIEW"
    assert submit_res.lines[0].variance_quantity == 5.0
    assert submit_res.lines[0].variance_value == 225.0 # 5 * $45

    # INVARIANT CHECK: Inventory must NOT be mutated yet!
    await db_session.refresh(bal)
    assert bal.quantity_on_hand == Decimal("20.0")

    # Step 3: Supervisor approves session
    approve_res = await WarehouseService.approve_count_session(
        db=db_session,
        tenant_id=tenant_id,
        session_id=session_res.id,
        action="APPROVE"
    )
    assert approve_res.status == "APPROVED"

    # INVARIANT CHECK: Inventory and Costing must now be updated!
    await db_session.refresh(bal)
    assert bal.quantity_on_hand == Decimal("25.0")
    assert (bal.quantity_on_hand - bal.quantity_allocated) == Decimal("25.0")

    prof = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert prof.current_quantity == Decimal("25.0")

async def test_guided_picking_scan_rejections_and_route(db_session: AsyncSession):
    """
    Tests scan-verified guided picking with wrong-bin and wrong-product rejections.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_storage1, bin_storage2, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # Seed stock and create SO
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_storage1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)

    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-{uuid.uuid4().hex[:4]}", name="Pick Customer")
    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, customer_id=cust.id, so_number=f"SO-PCK-{uuid.uuid4().hex[:4]}", status="DRAFT")
    sol = SOLineItem(id=str(uuid.uuid4()), sales_order_id=so.id, item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("90.0"))
    so.lines.append(sol)
    db_session.add_all([cust, so])
    await db_session.flush()

    # Confirm and allocate SO
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id)
    await db_session.flush()

    # Step 1: Generate Pick Task
    pick_task = await WarehouseService.get_or_create_pick_task(db_session, tenant_id, so.id)
    assert pick_task.total_lines == 1
    pick_line = pick_task.lines[0]
    assert pick_line.quantity_allocated == 10.0

    # Step 2: Reject Wrong Bin Scan
    with pytest.raises(Exception):
        await WarehouseService.confirm_pick_line(
            db=db_session,
            tenant_id=tenant_id,
            pick_task_line_id=pick_line.id,
            scanned_bin_code="WRONG-BIN-CODE",
            scanned_item_barcode=variant.variant_sku,
            quantity_picked=Decimal("10.0")
        )

    # Step 3: Reject Wrong Product Scan
    with pytest.raises(Exception):
        await WarehouseService.confirm_pick_line(
            db=db_session,
            tenant_id=tenant_id,
            pick_task_line_id=pick_line.id,
            scanned_bin_code=bin_storage1.code,
            scanned_item_barcode="WRONG-PRODUCT-SKU",
            quantity_picked=Decimal("10.0")
        )

    # Step 4: Successful Scan Confirmation
    conf_res = await WarehouseService.confirm_pick_line(
        db=db_session,
        tenant_id=tenant_id,
        pick_task_line_id=pick_line.id,
        scanned_bin_code=bin_storage1.code,
        scanned_item_barcode=barcode.barcode_value,
        quantity_picked=Decimal("10.0")
    )
    assert conf_res.status == "COMPLETED"
    assert conf_res.picked_lines == 1

async def test_packing_scan_verification_and_dispatch_guard(db_session: AsyncSession):
    """
    Tests 100% scan verification requirement at packing bench.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_storage1, _, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # Create SO & Shipment
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-{uuid.uuid4().hex[:4]}", name="Pack Customer")
    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, customer_id=cust.id, so_number=f"SO-PKG-{uuid.uuid4().hex[:4]}", status="CONFIRMED")
    sol = SOLineItem(id=str(uuid.uuid4()), sales_order_id=so.id, item_variant_id=variant.id, quantity_ordered=Decimal("10.0"), unit_price=Decimal("90.0"))
    so.lines.append(sol)
    db_session.add_all([cust, so])
    await db_session.flush()

    # Confirm and allocate SO
    await SalesService.confirm_sales_order(db_session, tenant_id, so.id)
    await SalesService.allocate_stock(db_session, tenant_id, so.id)
    await db_session.flush()

    # Step 1: Generate Pick Task
    pick_task = await WarehouseService.get_or_create_pick_task(db_session, tenant_id, so.id)
    assert pick_task.total_lines == 1
    pick_line = pick_task.lines[0]
    assert pick_line.quantity_allocated == 10.0

    # Step 2: Reject Wrong Bin Scan
    with pytest.raises(Exception):
        await WarehouseService.confirm_pick_line(
            db=db_session,
            tenant_id=tenant_id,
            pick_task_line_id=pick_line.id,
            scanned_bin_code="WRONG-BIN-CODE",
            scanned_item_barcode=variant.variant_sku,
            quantity_picked=Decimal("10.0")
        )

    # Step 3: Reject Wrong Product Scan
    with pytest.raises(Exception):
        await WarehouseService.confirm_pick_line(
            db=db_session,
            tenant_id=tenant_id,
            pick_task_line_id=pick_line.id,
            scanned_bin_code=bin_storage1.code,
            scanned_item_barcode="WRONG-PRODUCT-SKU",
            quantity_picked=Decimal("10.0")
        )

    # Step 4: Successful Scan Confirmation
    conf_res = await WarehouseService.confirm_pick_line(
        db=db_session,
        tenant_id=tenant_id,
        pick_task_line_id=pick_line.id,
        scanned_bin_code=bin_storage1.code,
        scanned_item_barcode=barcode.barcode_value,
        quantity_picked=Decimal("10.0")
    )
    assert conf_res.status == "COMPLETED"
    assert conf_res.picked_lines == 1

async def test_packing_scan_verification_and_dispatch_guard(db_session: AsyncSession):
    """
    Tests 100% scan verification requirement at packing bench.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_storage1, _, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # Create SO & Shipment
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-{uuid.uuid4().hex[:4]}", name="Pack Customer")
    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh.id, customer_id=cust.id, so_number=f"SO-PKG-{uuid.uuid4().hex[:4]}", status="CONFIRMED")
    sol = SOLineItem(id=str(uuid.uuid4()), sales_order_id=so.id, item_variant_id=variant.id, quantity_ordered=Decimal("2.0"), unit_price=Decimal("90.0"))
    so.lines.append(sol)
    shipment = Shipment(id=str(uuid.uuid4()), sales_order_id=so.id, shipment_number=f"SHP-PKG-{uuid.uuid4().hex[:4]}")
    db_session.add_all([cust, so, shipment])
    await db_session.flush()

    # Step 1: Initialize Packing Session
    pack_sess = await WarehouseService.get_or_create_packing_session(db_session, tenant_id, shipment.id)
    assert pack_sess.is_fully_verified is False
    assert pack_sess.total_ordered_quantity == 2.0
    assert pack_sess.total_packed_quantity == 0.0

    # Step 2: Scan 1st unit
    v1 = await WarehouseService.verify_packing_item(
        db=db_session,
        tenant_id=tenant_id,
        shipment_id=shipment.id,
        scanned_barcode=barcode.barcode_value,
        quantity=Decimal("1.0"),
        carton_number=1
    )
    assert v1.verified is True
    assert v1.is_order_complete is False
    assert v1.quantity_packed_total == 1.0

    # Step 3: Scan 2nd unit -> completes order!
    v2 = await WarehouseService.verify_packing_item(
        db=db_session,
        tenant_id=tenant_id,
        shipment_id=shipment.id,
        scanned_barcode=variant.variant_sku,
        quantity=Decimal("1.0"),
        carton_number=1
    )
    assert v2.verified is True
    assert v2.is_order_complete is True
    assert v2.quantity_packed_total == 2.0

    # Step 4: Over-packing attempt fails
    with pytest.raises(Exception):
        await WarehouseService.verify_packing_item(
            db=db_session,
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            scanned_barcode=variant.variant_sku,
            quantity=Decimal("1.0"),
            carton_number=1
        )

async def test_warehouse_api_endpoints_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """
    Tests REST API endpoints for floor warehouse operations with RBAC claims.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="floor_supervisor",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    wh, bin_staging, bin_storage1, _, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # Barcode resolve
    res = await client.post("/api/v1/warehouse/barcode/resolve", headers=headers, json={"raw_barcode": barcode.barcode_value})
    assert res.status_code == 200
    assert res.json()["found"] is True

    # Label generation
    lbl_res = await client.post("/api/v1/warehouse/labels/generate", headers=headers, json={
        "label_type": "VARIANT",
        "entity_ids": [variant.id],
        "copies_per_item": 2
    })
    assert lbl_res.status_code == 200
    assert lbl_res.json()["total_labels"] == 2

async def test_end_to_end_receiving_to_staging_to_putaway(db_session: AsyncSession):
    """
    Tests complete integration pipeline:
    1. PO Creation and Approval
    2. Authoritative GRN Receiving into STAGING location bin via PurchaseService
    3. Immutable ledger posting & Costing Layer creation
    4. Barcode resolution of arriving variant
    5. Phase 4D Putaway execution from STAGING bin to STORAGE bin via WarehouseService
    6. Verifies ledger entries, balance relocation, and 100% cost basis preservation
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_staging, bin_storage1, _, item, variant, barcode = await create_warehouse_ops_environment(db_session, tenant_id)

    # 1. Supplier & PO
    supplier = Supplier(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=f"SUP-{uuid.uuid4().hex[:4]}",
        name="Inbound Supplier",
        payment_terms="Net 30"
    )
    db_session.add(supplier)
    await db_session.flush()

    po_in = PurchaseOrderCreate(
        supplier_id=supplier.id,
        target_warehouse_id=wh.id,
        lines=[
            POLineCreate(
                item_variant_id=variant.id,
                quantity_ordered=Decimal("50.0"),
                unit_price=Decimal("40.00")
            )
        ]
    )
    po = await PurchaseService.create_purchase_order(db_session, tenant_id, po_in)
    await PurchaseService.approve_purchase_order(db_session, tenant_id, po.id)
    await db_session.flush()

    # 2. Authoritative GRN Receiving into STAGING Bin
    gr_in = GoodsReceiptCreate(
        purchase_order_id=po.id,
        warehouse_id=wh.id,
        lines=[
            GoodsReceiptLineCreate(
                po_line_id=po.lines[0].id,
                item_variant_id=variant.id,
                quantity_received=Decimal("50.0"),
                destination_bin_id=bin_staging.id
            )
        ]
    )
    gr = await PurchaseService.receive_goods(db_session, tenant_id, gr_in)
    assert gr.grn_number is not None
    await db_session.refresh(po)
    assert po.status == "COMPLETED"

    # Verify stock in STAGING bin
    bal_stg = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_staging.id,
            StockBalanceCache.item_variant_id == variant.id
        )
    )).scalar_one()
    assert bal_stg.quantity_on_hand == Decimal("50.0")

    # Capture initial cost profile
    prof_initial = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert prof_initial.current_quantity == Decimal("50.0")
    assert prof_initial.current_total_value == Decimal("2000.00") # 50 * $40

    # 3. Barcode scan resolution
    resolved = await WarehouseService.resolve_barcode(db_session, tenant_id, barcode.barcode_value)
    assert resolved.found is True
    assert resolved.payload["variant_id"] == variant.id

    # 4. Floor Putaway: STAGING -> STORAGE Bin
    putaway_res = await WarehouseService.execute_putaway(
        db=db_session,
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        source_staging_bin_id=bin_staging.id,
        destination_storage_bin_id=bin_storage1.id,
        item_variant_id=variant.id,
        quantity=Decimal("50.0")
    )
    assert putaway_res.success is True
    assert putaway_res.transferred_quantity == 50.0

    # 5. Verify stock relocated and cost preserved
    await db_session.refresh(bal_stg)
    assert bal_stg.quantity_on_hand == Decimal("0.0")

    bal_dst = (await db_session.execute(
        select(StockBalanceCache).where(
            StockBalanceCache.warehouse_id == wh.id,
            StockBalanceCache.location_bin_id == bin_storage1.id,
            StockBalanceCache.item_variant_id == variant.id
        )
    )).scalar_one()
    assert bal_dst.quantity_on_hand == Decimal("50.0")

    # Cost value must remain exactly $2000.00
    prof_after = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert prof_after.current_quantity == Decimal("50.0")
    assert prof_after.current_total_value == Decimal("2000.00")
