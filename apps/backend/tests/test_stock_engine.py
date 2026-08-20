import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_items_and_barcode_lookup(client: AsyncClient):
    # Authenticate
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # List items
    items_res = await client.get("/api/v1/items", headers=headers)
    assert items_res.status_code == 200
    items_data = items_res.json()
    items = items_data.get("items", items_data)
    assert len(items) >= 3

    # Scan lookup barcode
    lookup_res = await client.post("/api/v1/barcodes/lookup", json={"barcode": "890123456789"}, headers=headers)
    assert lookup_res.status_code == 200
    lookup_data = lookup_res.json()
    assert lookup_data["found"] is True
    assert lookup_data["item_sku"] == "SKU-THM-100"
    assert lookup_data["current_stock"] == 120.0

@pytest.mark.asyncio
async def test_stock_ledger_transfer_and_balance_update(client: AsyncClient):
    # Authenticate
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get warehouses and bins
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    assert wh_res.status_code == 200
    whs = wh_res.json()
    austin_wh = next(w for w in whs if w["code"] == "WH-ATX-01")
    src_bin = next(b for b in austin_wh["bins"] if b["code"] == "ATX-A01-01")
    dst_bin = next(b for b in austin_wh["bins"] if b["code"] == "ATX-STG-01")

    # Get item variant
    items_res = await client.get("/api/v1/items?q=SKU-THM-100", headers=headers)
    items_data = items_res.json()
    items = items_data.get("items", items_data)
    item = items[0]
    variant_id = item["variants"][0]["id"]

    # Post stock transfer: 20 units from ATX-A01-01 to ATX-STG-01
    transfer_res = await client.post("/api/v1/ledger/transfers", json={
        "item_variant_id": variant_id,
        "source_bin_id": src_bin["id"],
        "destination_bin_id": dst_bin["id"],
        "quantity": 20.0,
        "notes": "Move to staging for quality inspection"
    }, headers=headers)
    assert transfer_res.status_code == 200

    # Verify ledger entries
    ledger_res = await client.get("/api/v1/ledger/entries", headers=headers)
    assert ledger_res.status_code == 200
    ledger_data = ledger_res.json()
    entries = ledger_data.get("items", ledger_data)
    assert len(entries) >= 5 # 4 initial + 1 transfer

    # Verify updated balances
    bal_res = await client.get(f"/api/v1/ledger/balances?warehouse_id={austin_wh['id']}&item_variant_id={variant_id}", headers=headers)
    assert bal_res.status_code == 200
    bal_data = bal_res.json()
    bals = bal_data.get("items", bal_data)
    
    src_bal = next(b for b in bals if b["bin_code"] == "ATX-A01-01")
    dst_bal = next(b for b in bals if b["bin_code"] == "ATX-STG-01")
    assert src_bal["quantity_on_hand"] == 100.0 # was 120 - 20 = 100
    assert dst_bal["quantity_on_hand"] == 20.0 # was 0 + 20 = 20

@pytest.mark.asyncio
async def test_insufficient_stock_raises_422(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    austin_wh = next(w for w in wh_res.json() if w["code"] == "WH-ATX-01")
    src_bin = next(b for b in austin_wh["bins"] if b["code"] == "ATX-A01-01")
    dst_bin = next(b for b in austin_wh["bins"] if b["code"] == "ATX-STG-01")

    items_res = await client.get("/api/v1/items?q=SKU-THM-100", headers=headers)
    items_data = items_res.json()
    items = items_data.get("items", items_data)
    item = items[0]
    variant_id = item["variants"][0]["id"]

    # Attempt to transfer 99,999 units (exceeds available stock)
    transfer_res = await client.post("/api/v1/ledger/transfers", json={
        "item_variant_id": variant_id,
        "source_bin_id": src_bin["id"],
        "destination_bin_id": dst_bin["id"],
        "quantity": 99999.0
    }, headers=headers)
    assert transfer_res.status_code == 422
    assert "Insufficient stock" in transfer_res.json()["detail"]
