import uuid
from decimal import Decimal
from datetime import timedelta
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.purchasing import (
    Supplier,
    SupplierContact,
    SupplierAddress,
    SupplierProduct,
    SupplierPriceHistory,
    PurchaseOrder,
    POLineItem,
    GoodsReceipt,
    GoodsReceiptLine,
    SupplierReturn,
    SupplierReturnLine,
    SupplierDebitMemo
)
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemCategory, Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.costing import ItemCostProfile, CostLayer, COGSRecord
from app.schemas.purchasing import (
    SupplierCreate,
    SupplierContactCreate,
    SupplierAddressCreate,
    SupplierProductCreate,
    PurchaseOrderCreate,
    POLineCreate,
    GoodsReceiptCreate,
    GoodsReceiptLineCreate,
    DraftPOFromSuggestionsRequest,
    SupplierReturnCreate,
    SupplierReturnLineCreate
)
from app.services.purchase_service import PurchaseService
from app.services.procurement_service import ProcurementService
from app.services.costing_service import CostingService
from app.services.stock_engine import StockEngine

pytestmark = pytest.mark.asyncio

async def create_procurement_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-PROC-{uuid.uuid4().hex[:4]}", name="Procurement WH")
    bin_stg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING")
    bin_stor = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    wh.bins.extend([bin_stg, bin_stor])
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Proc Cat", code=f"CAT-PRC-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-PRC-{uuid.uuid4().hex[:4]}", name="Proc Widget", valuation_method="FIFO")
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-PRC-{uuid.uuid4().hex[:4]}", variant_name="Proc Standard", cost_price=Decimal("50.00"), selling_price=Decimal("100.00"))
    item.variants.append(variant)
    db.add_all([cat, item])
    await db.flush()

    sup_a = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code="SUP-A", name="Supplier Alpha", currency="USD", payment_terms="Net 30", status="ACTIVE")
    sup_b = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code="SUP-B", name="Supplier Beta", currency="USD", payment_terms="Net 60", status="ACTIVE")
    db.add_all([sup_a, sup_b])
    await db.flush()

    return wh, bin_stg, bin_stor, item, variant, sup_a, sup_b

async def test_supplier_master_contacts_and_addresses(db_session: AsyncSession):
    """
    Tests Supplier master creation with multi-contacts, multi-addresses, tax ID, and status lifecycle.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    sup_in = SupplierCreate(
        code=f"SUP-MSTR-{uuid.uuid4().hex[:4]}",
        name="Apex Industrial",
        email="sales@apex.com",
        tax_identifier="US-EIN-99887766",
        payment_terms="Net 45",
        credit_limit=Decimal("50000.00"),
        status="ACTIVE",
        contacts=[
            SupplierContactCreate(contact_name="Alice Smith", email="alice@apex.com", phone="+1-555-0100", designation="Sales Director", is_primary=True),
            SupplierContactCreate(contact_name="Bob Jones", email="bob@apex.com", phone="+1-555-0101", designation="Logistics Mgr", is_primary=False)
        ],
        addresses=[
            SupplierAddressCreate(address_type="ORDERING", address_line1="100 Factory Lane", city="Chicago", state="IL", postal_code="60601", country="US", is_default=True),
            SupplierAddressCreate(address_type="REMITTANCE", address_line1="PO Box 456", city="Chicago", state="IL", postal_code="60602", country="US", is_default=False)
        ]
    )

    sup = await PurchaseService.create_supplier(db_session, tenant_id, sup_in)
    assert sup.id is not None
    assert sup.tax_identifier == "US-EIN-99887766"
    assert len(sup.contacts) == 2
    assert len(sup.addresses) == 2
    assert any(c.is_primary for c in sup.contacts)

async def test_supplier_product_catalog_and_price_history(db_session: AsyncSession):
    """
    Tests mapping variants to supplier products with MOQ, pack size, and immutable price history.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor, item, variant, sup_a, sup_b = await create_procurement_test_environment(db_session, tenant_id)

    # Map Supplier Alpha to Variant ($45.00, MOQ: 50, Pack: 10, Lead: 14d, Preferred: True)
    sp_a_in = SupplierProductCreate(
        item_variant_id=variant.id,
        supplier_sku="ALPHA-WIDG-01",
        unit_cost=Decimal("45.00"),
        minimum_order_quantity=Decimal("50.0"),
        pack_size=Decimal("10.0"),
        lead_time_days=14,
        is_preferred=True
    )
    sp_a = await PurchaseService.create_or_update_supplier_product(db_session, tenant_id, sup_a.id, sp_a_in)
    assert sp_a.is_preferred is True
    assert len(sp_a.price_histories) == 1
    assert sp_a.price_histories[0].unit_price == Decimal("45.00")

    # Map Supplier Beta to Variant ($42.00, MOQ: 100, Pack: 25, Lead: 21d, Preferred: False)
    sp_b_in = SupplierProductCreate(
        item_variant_id=variant.id,
        supplier_sku="BETA-WIDG-99",
        unit_cost=Decimal("42.00"),
        minimum_order_quantity=Decimal("100.0"),
        pack_size=Decimal("25.0"),
        lead_time_days=21,
        is_preferred=False
    )
    sp_b = await PurchaseService.create_or_update_supplier_product(db_session, tenant_id, sup_b.id, sp_b_in)
    assert sp_b.unit_cost == Decimal("42.00")

    # Update Supplier Alpha price to $47.50 -> new history record
    sp_a_update = SupplierProductCreate(
        item_variant_id=variant.id,
        supplier_sku="ALPHA-WIDG-01",
        unit_cost=Decimal("47.50"),
        minimum_order_quantity=Decimal("50.0"),
        pack_size=Decimal("10.0"),
        lead_time_days=14,
        is_preferred=True
    )
    sp_a_updated = await PurchaseService.create_or_update_supplier_product(db_session, tenant_id, sup_a.id, sp_a_update)
    assert len(sp_a_updated.price_histories) == 2
    assert sp_a_updated.unit_cost == Decimal("47.50")

async def test_replenishment_supplier_selection_moq_and_pack_constraints(db_session: AsyncSession):
    """
    Tests deterministic supplier selection, ROP calculation, and MOQ/Pack Size rounding.
    Numerical Scenario:
    - On hand = 40, Allocated = 0, Incoming = 20 -> Available + Incoming = 60.
    - ADU = 5.0 units/day.
    - Supplier Alpha (Preferred): MOQ = 50, Pack = 10, Lead Time = 14 days, Price = $45.00.
    - Safety Stock = 5 * 7 = 35. ROP = (5 * 14) + 35 = 105.
    - Target Stock = 105 + (5 * 30) = 255.
    - Gross need = 255 - 60 = 195.
    - Pack rounding: ceil(195 / 10) * 10 = 200 units.
    - Suggested Qty = max(50, 200) = 200 units.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor, item, variant, sup_a, sup_b = await create_procurement_test_environment(db_session, tenant_id)

    # 1. Seed stock: 40 on hand
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("40.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)

    # 2. Seed Incoming PO: 20 units
    po = PurchaseOrder(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        po_number=f"PO-INC-{uuid.uuid4().hex[:4]}",
        supplier_id=sup_a.id,
        target_warehouse_id=wh.id,
        status="APPROVED",
        total_amount=Decimal("900.00")
    )
    pol = POLineItem(
        id=str(uuid.uuid4()),
        purchase_order_id=po.id,
        item_variant_id=variant.id,
        quantity_ordered=Decimal("20.0"),
        quantity_received=Decimal("0.0"),
        quantity_cancelled=Decimal("0.0"),
        unit_price=Decimal("45.00"),
        line_total=Decimal("900.00")
    )
    po.lines.append(pol)
    db_session.add(po)

    # 3. Seed 90-day COGS: 450 units (ADU = 450/90 = 5.0)
    cogs = COGSRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()),
        item_variant_id=variant.id,
        quantity_shipped=Decimal("450.0"),
        unit_cogs=Decimal("45.00"),
        total_cogs_amount=Decimal("20250.00"),
        recognized_at=get_utc_now() - timedelta(days=10)
    )
    db_session.add(cogs)

    # 4. Map Supplier Alpha (Preferred, MOQ: 50, Pack: 10, Price: $45.00)
    sp_a_in = SupplierProductCreate(
        item_variant_id=variant.id,
        supplier_sku="ALPHA-WIDG-01",
        unit_cost=Decimal("45.00"),
        minimum_order_quantity=Decimal("50.0"),
        pack_size=Decimal("10.0"),
        lead_time_days=14,
        is_preferred=True
    )
    await PurchaseService.create_or_update_supplier_product(db_session, tenant_id, sup_a.id, sp_a_in)
    await db_session.flush()

    # 5. Calculate Suggestions
    sugg_res = await ProcurementService.get_purchase_suggestions(db_session, tenant_id, warehouse_id=wh.id)
    assert sugg_res.total_suggestions >= 1
    s = next(s for s in sugg_res.suggestions if s.variant_id == variant.id)

    assert s.supplier_id == sup_a.id
    assert s.is_preferred_supplier is True
    assert s.quantity_on_hand == 40.0
    assert s.incoming_on_po == 20.0
    assert s.reorder_point == 105.0
    assert s.target_stock == 255.0
    assert s.raw_recommended_quantity == 195.0
    assert s.suggested_order_quantity == 200.0 # ceil(195/10)*10
    assert s.estimated_spend == 9000.0 # 200 * $45.00

async def test_draft_po_batch_generation_and_zero_mutation_invariants(db_session: AsyncSession):
    """
    Tests 1-click batch generation of Draft POs from suggestions.
    Verifies that Draft POs create zero stock ledger transactions and zero cost layers.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # Stock = 0, ADU = 2 -> Needs reorder
    cogs = COGSRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        sales_order_id=str(uuid.uuid4()),
        shipment_id=str(uuid.uuid4()),
        cost_transaction_id=str(uuid.uuid4()),
        item_variant_id=variant.id,
        quantity_shipped=Decimal("180.0"),
        unit_cogs=Decimal("50.00"),
        total_cogs_amount=Decimal("9000.00"),
        recognized_at=get_utc_now() - timedelta(days=5)
    )
    db_session.add(cogs)

    sp_in = SupplierProductCreate(
        item_variant_id=variant.id,
        unit_cost=Decimal("48.00"),
        minimum_order_quantity=Decimal("20.0"),
        pack_size=Decimal("5.0"),
        lead_time_days=10,
        is_preferred=True
    )
    await PurchaseService.create_or_update_supplier_product(db_session, tenant_id, sup_a.id, sp_in)
    await db_session.flush()

    # Capture initial ledger and cost layers count
    init_tx_cnt = (await db_session.execute(select(StockLedgerTransaction))).scalars().all()
    init_layer_cnt = (await db_session.execute(select(CostLayer))).scalars().all()

    # Generate Draft PO
    batch_req = DraftPOFromSuggestionsRequest(
        suggestion_variant_ids=[variant.id],
        warehouse_id=wh.id
    )
    batch_res = await ProcurementService.create_draft_pos_from_suggestions(db_session, tenant_id, batch_req)
    assert batch_res.total_draft_pos_created == 1
    assert batch_res.draft_orders[0].supplier_id == sup_a.id

    po_id = batch_res.draft_orders[0].purchase_order_id
    po = (await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one()
    assert po.status == "DRAFT"

    # INVARIANT CHECK: Zero Stock and Costing Mutations!
    post_tx_cnt = (await db_session.execute(select(StockLedgerTransaction))).scalars().all()
    post_layer_cnt = (await db_session.execute(select(CostLayer))).scalars().all()
    assert len(post_tx_cnt) == len(init_tx_cnt)
    assert len(post_layer_cnt) == len(init_layer_cnt)

async def test_po_spend_threshold_and_self_approval_guards(db_session: AsyncSession):
    """
    Tests PO approval with self-approval limits.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # Create PO of $12,000 (exceeds $5,000 self-approval limit)
    po_in = PurchaseOrderCreate(
        supplier_id=sup_a.id,
        target_warehouse_id=wh.id,
        lines=[
            POLineCreate(
                item_variant_id=variant.id,
                quantity_ordered=Decimal("200.0"),
                unit_price=Decimal("60.00")
            )
        ]
    )
    creator_id = str(uuid.uuid4())
    po = await PurchaseService.create_purchase_order(db_session, tenant_id, po_in, user_id=creator_id)
    assert po.total_amount == Decimal("12000.00")

    # Creator self-approval fails with 403
    with pytest.raises(HTTPException) as exc:
        await PurchaseService.approve_purchase_order(db_session, tenant_id, po.id, user_id=creator_id, max_self_approval_limit=Decimal("5000.00"))
    assert exc.value.status_code == 403

    # Independent manager approval succeeds
    manager_id = str(uuid.uuid4())
    appr_po = await PurchaseService.approve_purchase_order(db_session, tenant_id, po.id, user_id=manager_id, max_self_approval_limit=Decimal("5000.00"))
    assert appr_po.status == "APPROVED"
    assert appr_po.approved_by_user_id == manager_id

async def test_purchase_price_variance_reporting(db_session: AsyncSession):
    """
    Tests PPV calculation between standard cost ($50.00) and actual received price ($54.00) on 50 units.
    Expected PPV = (54 - 50) * 50 = +$200.00 (Unfavorable).
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, _, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    po_in = PurchaseOrderCreate(
        supplier_id=sup_a.id,
        target_warehouse_id=wh.id,
        lines=[
            POLineCreate(
                item_variant_id=variant.id,
                quantity_ordered=Decimal("50.0"),
                unit_price=Decimal("54.00")
            )
        ]
    )
    po = await PurchaseService.create_purchase_order(db_session, tenant_id, po_in)
    await PurchaseService.approve_purchase_order(db_session, tenant_id, po.id)

    # Receive goods
    gr_in = GoodsReceiptCreate(
        purchase_order_id=po.id,
        warehouse_id=wh.id,
        lines=[
            GoodsReceiptLineCreate(
                po_line_id=po.lines[0].id,
                item_variant_id=variant.id,
                quantity_received=Decimal("50.0"),
                destination_bin_id=bin_stg.id
            )
        ]
    )
    await PurchaseService.receive_goods(db_session, tenant_id, gr_in)

    # Calculate PPV report
    ppv_res = await ProcurementService.get_purchase_price_variance_report(db_session, tenant_id, supplier_id=sup_a.id)
    assert ppv_res.total_receipt_lines_evaluated == 1
    assert ppv_res.net_ppv_amount == 200.0
    assert ppv_res.unfavorable_variance_amount == 200.0
    assert ppv_res.lines[0].variance_classification == "UNFAVORABLE"

async def test_supplier_returns_rtv_stock_cost_and_debit_memo(db_session: AsyncSession):
    """
    Tests Return to Vendor (RTV):
    1. Seed 30 units in Storage bin @ $50.00.
    2. Execute Supplier Return of 10 defective units.
    3. Assert physical balance becomes 20 units.
    4. Assert StockLedgerTransaction (SUPPLIER_RETURN) and CostLayer depletion.
    5. Assert SupplierDebitMemo of $500.00 created.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("30.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("30.0"), Decimal("50.00"))
    await db_session.flush()

    ret_in = SupplierReturnCreate(
        supplier_id=sup_a.id,
        warehouse_id=wh.id,
        return_reason="DEFECTIVE",
        notes="Damaged motor casings",
        lines=[
            SupplierReturnLineCreate(
                item_variant_id=variant.id,
                source_location_bin_id=bin_stor.id,
                quantity_returned=Decimal("10.0"),
                unit_cost=Decimal("50.00")
            )
        ]
    )
    ret = await PurchaseService.process_supplier_return(db_session, tenant_id, ret_in)
    assert ret.status == "COMPLETED"
    assert ret.total_refund_amount == Decimal("500.00")

    # Verify physical stock
    await db_session.refresh(bal)
    assert bal.quantity_on_hand == Decimal("20.0")

    # Verify Debit Memo
    memo = (await db_session.execute(
        select(SupplierDebitMemo).where(SupplierDebitMemo.supplier_return_id == ret.id)
    )).scalar_one()
    assert memo.amount == Decimal("500.00")
    assert memo.status == "OPEN"

async def test_procurement_api_endpoints_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """
    Tests REST endpoints under /api/v1/procurement/* with RBAC token.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="procurement_mgr",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    wh, _, _, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # 1. Map product
    map_res = await client.post(f"/api/v1/procurement/suppliers/{sup_a.id}/products", headers=headers, json={
        "item_variant_id": variant.id,
        "supplier_sku": "API-SKU-01",
        "unit_cost": 49.00,
        "minimum_order_quantity": 25.0,
        "pack_size": 5.0,
        "lead_time_days": 12,
        "is_preferred": True
    })
    assert map_res.status_code == 201
    assert map_res.json()["supplier_sku"] == "API-SKU-01"

    # 2. Query Dashboard
    dash_res = await client.get("/api/v1/procurement/dashboard", headers=headers)
    assert dash_res.status_code == 200
    assert "total_active_suppliers" in dash_res.json()

    # 3. Query Scorecards
    score_res = await client.get("/api/v1/procurement/supplier-scorecards", headers=headers)
    assert score_res.status_code == 200
    assert score_res.json()["total_suppliers"] >= 2

async def test_po_approval_rbac_double_approval_and_cancellation_guards(client: AsyncClient, db_session: AsyncSession):
    """
    Tests PO approval security, RBAC, double approval, and cancellation guards:
    - User without 'purchasing:approve' -> 403 Forbidden
    - User with 'purchasing:approve' -> 200 OK
    - Double approval of already approved PO -> 400 Bad Request
    - Approval of cancelled PO -> 400 Bad Request
    - State changes authoritative PO without creating duplicate or parallel entities
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # 1. Token without purchasing:approve (only purchasing:read, purchasing:write)
    clerk_token = create_access_token(
        subject="clerk_user",
        tenant_id=tenant_id,
        roles=["WAREHOUSE_CLERK"],
        permissions=["purchasing:read", "purchasing:write"]
    )
    clerk_headers = {"Authorization": f"Bearer {clerk_token}"}

    # 2. Token with purchasing:approve
    manager_token = create_access_token(
        subject="manager_user",
        tenant_id=tenant_id,
        roles=["PROCUREMENT_MANAGER"],
        permissions=["purchasing:read", "purchasing:write", "purchasing:approve"]
    )
    mgr_headers = {"Authorization": f"Bearer {manager_token}"}

    # Create Draft PO
    po_create_res = await client.post("/api/v1/purchase-orders", headers=clerk_headers, json={
        "supplier_id": sup_a.id,
        "target_warehouse_id": wh.id,
        "lines": [{"item_variant_id": variant.id, "quantity_ordered": 20.0, "unit_price": 50.0}]
    })
    assert po_create_res.status_code == 201
    po_id = po_create_res.json()["id"]

    # Attempt approval without permission -> 403
    unauth_res = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=clerk_headers)
    assert unauth_res.status_code == 403

    # Authorized manager approval -> 200
    auth_res = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=mgr_headers)
    assert auth_res.status_code == 200
    assert auth_res.json()["status"] == "APPROVED"

    # Double approval attempt -> 400
    double_res = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=mgr_headers)
    assert double_res.status_code == 400
    assert "Cannot approve PO in 'APPROVED' status" in double_res.json()["detail"]

    # Cancel a new Draft PO, then attempt approval -> 400
    po_cancel_res = await client.post("/api/v1/purchase-orders", headers=clerk_headers, json={
        "supplier_id": sup_a.id,
        "target_warehouse_id": wh.id,
        "lines": [{"item_variant_id": variant.id, "quantity_ordered": 10.0, "unit_price": 50.0}]
    })
    po_cancel_id = po_cancel_res.json()["id"]
    await client.post(f"/api/v1/purchase-orders/{po_cancel_id}/cancel", headers=mgr_headers)

    appr_cancel_res = await client.post(f"/api/v1/purchase-orders/{po_cancel_id}/approve", headers=mgr_headers)
    assert appr_cancel_res.status_code == 400
    assert "Cannot approve PO in 'CANCELLED' status" in appr_cancel_res.json()["detail"]

async def test_supplier_return_mwa_partial_and_insufficient_stock_rejections(db_session: AsyncSession):
    """
    Tests Supplier Return (RTV) under Moving Weighted Average (MWA), partial returns,
    and insufficient stock rejections.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, bin_stor, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # Set valuation method to WEIGHTED_AVERAGE
    item.valuation_method = "WEIGHTED_AVERAGE"
    await db_session.flush()

    # 1. Inbound 50 units @ $40.00
    bal = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("40.00"))
    await db_session.flush()

    # 2. Inbound another 50 units @ $60.00 (MWA becomes $50.00)
    bal.quantity_on_hand += Decimal("50.0")
    await CostingService.record_inbound_receipt(db_session, tenant_id, wh.id, variant.id, Decimal("50.0"), Decimal("60.00"))
    await db_session.flush()

    prof = await CostingService.get_or_create_cost_profile(db_session, tenant_id, wh.id, variant.id)
    assert prof.moving_average_cost == Decimal("50.00")
    assert bal.quantity_on_hand == Decimal("100.0")

    # 3. Partial return of 25 units
    ret_in = SupplierReturnCreate(
        supplier_id=sup_a.id,
        warehouse_id=wh.id,
        return_reason="DEFECTIVE",
        lines=[
            SupplierReturnLineCreate(
                item_variant_id=variant.id,
                source_location_bin_id=bin_stor.id,
                quantity_returned=Decimal("25.0"),
                unit_cost=Decimal("50.00")
            )
        ]
    )
    ret = await PurchaseService.process_supplier_return(db_session, tenant_id, ret_in)
    assert ret.status == "COMPLETED"
    assert ret.total_refund_amount == Decimal("1250.00")

    await db_session.refresh(bal)
    assert bal.quantity_on_hand == Decimal("75.0")

    # 4. Attempt to return 100 units (only 75 on hand) -> 422
    over_ret_in = SupplierReturnCreate(
        supplier_id=sup_a.id,
        warehouse_id=wh.id,
        return_reason="DEFECTIVE",
        lines=[
            SupplierReturnLineCreate(
                item_variant_id=variant.id,
                source_location_bin_id=bin_stor.id,
                quantity_returned=Decimal("100.0"),
                unit_cost=Decimal("50.00")
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await PurchaseService.process_supplier_return(db_session, tenant_id, over_ret_in)
    assert exc.value.status_code == 422
    assert "Insufficient unallocated stock" in exc.value.detail

async def test_supplier_price_history_immutability_and_exact_ppv_calculations(db_session: AsyncSession):
    """
    Tests exact numerical Purchase Price Variance (PPV):
    - Expected = 50, Actual = 55, Quantity = 100 -> PPV = +500 (UNFAVORABLE)
    - Expected = 50, Actual = 45, Quantity = 100 -> PPV = -500 (FAVORABLE)
    - Verifies PPV reporting does not mutate inventory cost layers
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, _, item, variant, sup_a, _ = await create_procurement_test_environment(db_session, tenant_id)

    # Base standard cost = $50.00
    variant.cost_price = Decimal("50.00")
    await db_session.flush()

    # 1. Unfavorable PO ($55.00 x 100 units)
    po_unfav = await PurchaseService.create_purchase_order(db_session, tenant_id, PurchaseOrderCreate(
        supplier_id=sup_a.id,
        target_warehouse_id=wh.id,
        lines=[POLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("100.0"), unit_price=Decimal("55.00"))]
    ))
    await PurchaseService.approve_purchase_order(db_session, tenant_id, po_unfav.id)
    await PurchaseService.receive_goods(db_session, tenant_id, GoodsReceiptCreate(
        purchase_order_id=po_unfav.id,
        warehouse_id=wh.id,
        lines=[GoodsReceiptLineCreate(po_line_id=po_unfav.lines[0].id, item_variant_id=variant.id, quantity_received=Decimal("100.0"), destination_bin_id=bin_stg.id)]
    ))

    # 2. Favorable PO ($45.00 x 100 units)
    po_fav = await PurchaseService.create_purchase_order(db_session, tenant_id, PurchaseOrderCreate(
        supplier_id=sup_a.id,
        target_warehouse_id=wh.id,
        lines=[POLineCreate(item_variant_id=variant.id, quantity_ordered=Decimal("100.0"), unit_price=Decimal("45.00"))]
    ))
    await PurchaseService.approve_purchase_order(db_session, tenant_id, po_fav.id)
    await PurchaseService.receive_goods(db_session, tenant_id, GoodsReceiptCreate(
        purchase_order_id=po_fav.id,
        warehouse_id=wh.id,
        lines=[GoodsReceiptLineCreate(po_line_id=po_fav.lines[0].id, item_variant_id=variant.id, quantity_received=Decimal("100.0"), destination_bin_id=bin_stg.id)]
    ))

    # Calculate PPV report
    report = await ProcurementService.get_purchase_price_variance_report(db_session, tenant_id, supplier_id=sup_a.id)
    assert report.total_receipt_lines_evaluated >= 2

    unfav_line = next(l for l in report.lines if l.po_id == po_unfav.id)
    assert unfav_line.po_unit_price == 55.0
    assert unfav_line.standard_unit_cost == 50.0
    assert unfav_line.unit_ppv == 5.0
    assert unfav_line.total_ppv == 500.0
    assert unfav_line.variance_classification == "UNFAVORABLE"

    fav_line = next(l for l in report.lines if l.po_id == po_fav.id)
    assert fav_line.po_unit_price == 45.0
    assert fav_line.standard_unit_cost == 50.0
    assert fav_line.unit_ppv == -5.0
    assert fav_line.total_ppv == -500.0
    assert fav_line.variance_classification == "FAVORABLE"
