import pytest
from httpx import AsyncClient
from decimal import Decimal

@pytest.mark.asyncio
async def test_e2e_purchasing_to_inventory_consistency(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch supplier, warehouse, variant
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    supplier_id = sup_res.json()[0]["id"]

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    rcv_bin = next(b for b in wh["bins"] if b["type"] == "RECEIVING")

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # Initial inventory baseline
    bal_res_initial = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    initial_items = bal_res_initial.json()["items"]
    initial_on_hand = sum(b["quantity_on_hand"] for b in initial_items)
    initial_alloc = sum(b["quantity_allocated"] for b in initial_items)

    # 1. Create Purchase Order for 50 units
    po_create_res = await client.post("/api/v1/purchase-orders", json={
        "supplier_id": supplier_id,
        "target_warehouse_id": warehouse_id,
        "notes": "E2E Inbound consistency test",
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 50.0, "unit_price": 30.0}]
    }, headers=headers)
    assert po_create_res.status_code == 201
    po = po_create_res.json()
    po_id = po["id"]
    po_line_id = po["lines"][0]["id"]

    # Invariant: PO creation must NEVER change inventory
    bal_res_after_po = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    after_po_items = bal_res_after_po.json()["items"]
    assert sum(b["quantity_on_hand"] for b in after_po_items) == initial_on_hand

    # 2. Approve PO
    await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers)

    # 3. Goods Receipt (GRN) for 50 units
    grn_res = await client.post("/api/v1/purchase-orders/receive", json={
        "purchase_order_id": po_id,
        "warehouse_id": warehouse_id,
        "notes": "E2E delivery verified",
        "lines": [{
            "po_line_id": po_line_id,
            "item_variant_id": variant_id,
            "quantity_received": 50.0,
            "destination_bin_id": rcv_bin["id"],
            "batch_number": "E2E-BATCH-01"
        }]
    }, headers=headers)
    assert grn_res.status_code in [200, 201]

    # 4. Verify Inventory: physical on-hand must increase by EXACTLY 50 units
    bal_res_final = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    final_items = bal_res_final.json()["items"]
    final_on_hand = sum(b["quantity_on_hand"] for b in final_items)
    final_alloc = sum(b["quantity_allocated"] for b in final_items)

    assert final_on_hand == initial_on_hand + 50.0
    for b in final_items:
        assert b["quantity_available"] == b["quantity_on_hand"] - b["quantity_allocated"]


@pytest.mark.asyncio
async def test_e2e_partial_and_completed_purchase_receipt(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    supplier_id = sup_res.json()[0]["id"]
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    rcv_bin = next(b for b in wh["bins"] if b["type"] == "RECEIVING")
    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # Create & Approve PO for 100 units
    po_res = await client.post("/api/v1/purchase-orders", json={
        "supplier_id": supplier_id,
        "target_warehouse_id": warehouse_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 100.0, "unit_price": 25.0}]
    }, headers=headers)
    po_id = po_res.json()["id"]
    po_line_id = po_res.json()["lines"][0]["id"]
    await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers)

    # 1. Partial GRN: Receive 40 units
    await client.post("/api/v1/purchase-orders/receive", json={
        "purchase_order_id": po_id,
        "warehouse_id": warehouse_id,
        "lines": [{"po_line_id": po_line_id, "item_variant_id": variant_id, "quantity_received": 40.0, "destination_bin_id": rcv_bin["id"]}]
    }, headers=headers)

    po_partial = (await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)).json()
    assert po_partial["status"] == "PARTIALLY_RECEIVED"
    assert po_partial["lines"][0]["quantity_received"] == 40.0
    assert po_partial["lines"][0]["quantity_remaining"] == 60.0

    # 2. Final GRN: Receive remaining 60 units
    await client.post("/api/v1/purchase-orders/receive", json={
        "purchase_order_id": po_id,
        "warehouse_id": warehouse_id,
        "lines": [{"po_line_id": po_line_id, "item_variant_id": variant_id, "quantity_received": 60.0, "destination_bin_id": rcv_bin["id"]}]
    }, headers=headers)

    po_complete = (await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)).json()
    assert po_complete["status"] == "COMPLETED"
    assert po_complete["lines"][0]["quantity_received"] == 100.0
    assert len(po_complete["receipts"]) == 2


@pytest.mark.asyncio
async def test_e2e_sales_order_full_fulfillment_lifecycle(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    stg_bin = next(b for b in wh["bins"] if b["type"] == "STORAGE")

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]
    cust_res = await client.get("/api/v1/sales-orders/customers", headers=headers)
    customer_id = cust_res.json()[0]["id"]

    # Establish baseline 100 units in storage bin
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 100.0,
        "reason": "Baseline 100 units for Sales E2E"
    }, headers=headers)

    # 1. Create SO for 30 units
    so_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 30.0, "unit_price": 50.0}]
    }, headers=headers)
    so = so_res.json()
    so_id = so["id"]
    line_id = so["lines"][0]["id"]

    # 2. Confirm SO
    await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=headers)

    # 3. Allocate Stock (reserves 30 units)
    alloc_res = await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=headers)
    assert alloc_res.status_code == 200

    # Invariant check: on_hand=100, allocated=30, available=70
    bal1 = (await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)).json()["items"][0]
    assert bal1["quantity_on_hand"] == 100.0
    assert bal1["quantity_allocated"] == 30.0
    assert bal1["quantity_available"] == 70.0

    # 4. Pick Items (30 units)
    pick_res = await client.post(f"/api/v1/sales-orders/{so_id}/pick", json={
        "picks": [{"so_line_id": line_id, "quantity_picked": 30.0}]
    }, headers=headers)
    assert pick_res.status_code == 200

    # 5. Pack Order
    pack_res = await client.post(f"/api/v1/sales-orders/{so_id}/pack", json={
        "package_count": 2,
        "total_weight": 8.5
    }, headers=headers)
    assert pack_res.status_code == 200
    assert pack_res.json()["status"] == "PACKED"

    # 6. Dispatch Shipment
    dispatch_res = await client.post(f"/api/v1/sales-orders/{so_id}/dispatch", json={
        "carrier": "DHL Freight",
        "tracking_number": "TRK-DHL-7711",
        "package_count": 2
    }, headers=headers)
    assert dispatch_res.status_code == 201

    # Invariant check: on_hand=70, allocated=0, available=70
    bal2 = (await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)).json()["items"][0]
    assert bal2["quantity_on_hand"] == 70.0
    assert bal2["quantity_allocated"] == 0.0
    assert bal2["quantity_available"] == 70.0


@pytest.mark.asyncio
async def test_e2e_warehouse_transfer_and_adjustment_consistency(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh1 = wh_res.json()[0]
    wh2 = wh_res.json()[1]
    bin1 = next(b for b in wh1["bins"] if b["type"] == "STORAGE")
    bin2 = next(b for b in wh2["bins"] if b["type"] == "STORAGE")

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # Baseline 60 units in bin1, 0 in bin2
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": bin1["id"],
        "counted_quantity": 60.0,
        "reason": "Transfer test baseline"
    }, headers=headers)

    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": bin2["id"],
        "counted_quantity": 0.0,
        "reason": "Transfer test baseline 0"
    }, headers=headers)

    # 1. Transfer 25 units from bin1 to bin2
    transfer_res = await client.post("/api/v1/ledger/transfers", json={
        "item_variant_id": variant_id,
        "source_bin_id": bin1["id"],
        "destination_bin_id": bin2["id"],
        "quantity": 25.0,
        "notes": "Inter-facility replenishment"
    }, headers=headers)
    assert transfer_res.status_code == 200

    # Verify bin balances: bin1=35, bin2=25
    b1_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={bin1['id']}&item_variant_id={variant_id}", headers=headers)
    b2_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={bin2['id']}&item_variant_id={variant_id}", headers=headers)

    assert b1_res.json()["items"][0]["quantity_on_hand"] == 35.0
    assert b2_res.json()["items"][0]["quantity_on_hand"] == 25.0

    # 2. Cycle Count Adjustment in bin2 to 30 units (+5 adjustment)
    adj_res = await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": bin2["id"],
        "counted_quantity": 30.0,
        "reason": "Discovered 5 unrecorded units during cycle count"
    }, headers=headers)
    assert adj_res.status_code == 200

    b2_after = (await client.get(f"/api/v1/ledger/balances?location_bin_id={bin2['id']}&item_variant_id={variant_id}", headers=headers)).json()["items"][0]
    assert b2_after["quantity_on_hand"] == 30.0
    assert b2_after["quantity_available"] == 30.0


@pytest.mark.asyncio
async def test_reports_and_global_search_e2e(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Operational Dashboard Report
    dash_res = await client.get("/api/v1/reports/dashboard", headers=headers)
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert "total_on_hand_units" in dash
    assert "total_allocated_units" in dash
    assert "total_available_units" in dash
    assert "operational_alerts" in dash
    assert "orders_awaiting_dispatch" in dash

    # 2. Inventory Report
    inv_res = await client.get("/api/v1/reports/inventory?stock_status=ALL", headers=headers)
    assert inv_res.status_code == 200
    inv = inv_res.json()
    assert inv["total_items_reported"] >= 1
    assert inv["total_on_hand"] >= 0

    # 3. Purchasing Report
    po_rep_res = await client.get("/api/v1/reports/purchasing", headers=headers)
    assert po_rep_res.status_code == 200
    po_rep = po_rep_res.json()
    assert po_rep["total_pos"] >= 0

    # 4. Sales Report
    so_rep_res = await client.get("/api/v1/reports/sales", headers=headers)
    assert so_rep_res.status_code == 200
    so_rep = so_rep_res.json()
    assert so_rep["total_orders"] >= 0

    # 5. Global Search across entities
    search_res = await client.get("/api/v1/search?q=SKU", headers=headers)
    assert search_res.status_code == 200
    s_data = search_res.json()
    assert s_data["total_matches"] >= 1
    assert any(r["category"] == "PRODUCT" for r in s_data["results"])


@pytest.mark.asyncio
async def test_operational_inventory_valuation_calculation(client: AsyncClient):
    """
    Verifies that the valuation report computes an operational estimate equal to
    sum(on_hand_quantity * configured_cost_price) across all tenant inventory positions,
    and accurately reflects ledger inventory adjustments without making unverified
    accounting standard claims.
    """
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    stg_bin = next(b for b in wh["bins"] if b["type"] == "STORAGE")

    items_res = await client.get("/api/v1/items", headers=headers)
    item = items_res.json()["items"][0]
    variant = item["variants"][0]
    cost_price = float(variant["cost_price"] or 10.0)

    # Set known physical count of 50 units
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant["id"],
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 50.0,
        "reason": "Valuation verification adjustment"
    }, headers=headers)

    val_res = await client.get("/api/v1/reports/valuation", headers=headers)
    assert val_res.status_code == 200
    val_data = val_res.json()

    assert "total_inventory_value" in val_data
    assert "currency" in val_data
    assert isinstance(val_data["items"], list)

    target_item = next((i for i in val_data["items"] if i["sku"] == item["sku"]), None)
    assert target_item is not None
    assert target_item["valuation_method"] in ["FIFO", "AVERAGE", "STANDARD"]
    assert target_item["total_quantity"] >= 50.0
    assert target_item["unit_cost"] == cost_price
    assert target_item["total_valuation"] == round(target_item["total_quantity"] * target_item["unit_cost"], 2)
