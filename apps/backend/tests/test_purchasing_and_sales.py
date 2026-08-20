import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_po_creation_approval_and_receipt(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get supplier, warehouse, and item variant
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    supplier_id = sup_res.json()[0]["id"]

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    rcv_bin_id = next(b["id"] for b in wh["bins"] if b["type"] == "RECEIVING")

    items_res = await client.get("/api/v1/items", headers=headers)
    items_data = items_res.json()
    items = items_data.get("items", items_data)
    variant_id = items[0]["variants"][0]["id"]

    # 1. Create Purchase Order
    create_po_res = await client.post("/api/v1/purchase-orders", json={
        "supplier_id": supplier_id,
        "target_warehouse_id": warehouse_id,
        "notes": "Urgent restock batch",
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 50.0,
                "unit_price": 40.0
            }
        ]
    }, headers=headers)
    assert create_po_res.status_code in [200, 201]
    po = create_po_res.json()
    po_id = po["id"]
    po_line_id = po["lines"][0]["id"]
    assert po["status"] == "DRAFT"

    # 2. Approve Purchase Order
    approve_res = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers)
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "APPROVED"

    # 3. Receive Goods against Purchase Order
    receive_res = await client.post("/api/v1/purchase-orders/receive", json={
        "purchase_order_id": po_id,
        "warehouse_id": warehouse_id,
        "notes": "Delivered in full by freight carrier",
        "lines": [
            {
                "po_line_id": po_line_id,
                "item_variant_id": variant_id,
                "quantity_received": 50.0,
                "destination_bin_id": rcv_bin_id,
                "batch_number": "BATCH-TEST-2026"
            }
        ]
    }, headers=headers)
    assert receive_res.status_code in [200, 201]
    assert "GRN-" in receive_res.json()["grn_number"]

@pytest.mark.asyncio
async def test_dashboard_and_reports(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Dashboard Metrics
    dash_res = await client.get("/api/v1/reports/dashboard", headers=headers)
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash["total_items"] >= 3
    assert dash["total_warehouses"] >= 2
    assert dash["total_valuation"] > 0
    assert len(dash["recent_transactions"]) > 0

    # Valuation Report
    val_res = await client.get("/api/v1/reports/valuation", headers=headers)
    assert val_res.status_code == 200
    val = val_res.json()
    assert val["total_inventory_value"] > 0

    # Export CSV
    csv_res = await client.get("/api/v1/reports/valuation/export-csv", headers=headers)
    assert csv_res.status_code == 200
    assert "SKU,Item Name,Valuation Method" in csv_res.text
