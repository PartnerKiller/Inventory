import pytest
import uuid
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.auth import User, Role
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_warehouse_crud_and_rbac(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_code = f"WH-{uuid.uuid4().hex[:4].upper()}"

    # 1. Create Warehouse
    create_res = await client.post("/api/v1/warehouses", headers=headers, json={
        "code": wh_code,
        "name": "Midwest Distribution Center",
        "address": {"city": "Chicago", "state": "IL"}
    })
    assert create_res.status_code == 201
    wh = create_res.json()
    wh_id = wh["id"]
    assert wh["code"] == wh_code
    assert wh["total_bins"] >= 3 # Auto-created default functional bins

    # 2. Duplicate Code Rejection
    dup_res = await client.post("/api/v1/warehouses", headers=headers, json={
        "code": wh_code,
        "name": "Duplicate Warehouse"
    })
    assert dup_res.status_code == 400

    # 3. Update Warehouse
    update_res = await client.put(f"/api/v1/warehouses/{wh_id}", headers=headers, json={
        "name": "Midwest Mega Distribution Hub",
        "is_active": True
    })
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Midwest Mega Distribution Hub"

    # 4. Get Warehouse Detail
    detail_res = await client.get(f"/api/v1/warehouses/{wh_id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == wh_id

    # 5. Delete empty warehouse
    del_res = await client.delete(f"/api/v1/warehouses/{wh_id}", headers=headers)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_bin_crud_and_duplicate_code_prevention(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get Primary Warehouse
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh_list = wh_res.json()
    assert len(wh_list) > 0
    wh_id = wh_list[0]["id"]

    bin_code = f"BIN-{uuid.uuid4().hex[:4].upper()}"

    # 1. Create Bin
    create_bin_res = await client.post(f"/api/v1/warehouses/{wh_id}/bins", headers=headers, json={
        "code": bin_code,
        "aisle": "B",
        "rack": "04",
        "shelf": "02",
        "bin": "01",
        "type": "STORAGE"
    })
    assert create_bin_res.status_code == 201
    bin_data = create_bin_res.json()
    bin_id = bin_data["id"]
    assert bin_data["code"] == bin_code

    # 2. Duplicate Bin Code Rejection in same warehouse
    dup_bin_res = await client.post(f"/api/v1/warehouses/{wh_id}/bins", headers=headers, json={
        "code": bin_code,
        "type": "STORAGE"
    })
    assert dup_bin_res.status_code == 400

    # 3. Update Bin
    up_bin_res = await client.put(f"/api/v1/warehouses/{wh_id}/bins/{bin_id}", headers=headers, json={
        "type": "DAMAGE",
        "is_active": True
    })
    assert up_bin_res.status_code == 200
    assert up_bin_res.json()["type"] == "DAMAGE"

    # 4. Delete Empty Bin
    del_bin_res = await client.delete(f"/api/v1/warehouses/{wh_id}/bins/{bin_id}", headers=headers)
    assert del_bin_res.status_code == 200


@pytest.mark.asyncio
async def test_non_empty_bin_and_warehouse_deletion_protection(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Find bin holding stock from seed (WH-ATX-A01 has on-hand units)
    bals_res = await client.get("/api/v1/ledger/balances?stock_status=in_stock", headers=headers)
    assert bals_res.status_code == 200
    first_bal = bals_res.json()["items"][0]
    wh_id = first_bal["warehouse_id"]
    bin_id = first_bal["location_bin_id"]

    # 1. Attempt to delete non-empty bin
    del_bin_res = await client.delete(f"/api/v1/warehouses/{wh_id}/bins/{bin_id}", headers=headers)
    assert del_bin_res.status_code == 400
    assert "non-empty bin" in del_bin_res.json()["detail"]

    # 2. Attempt to delete warehouse with active stock
    del_wh_res = await client.delete(f"/api/v1/warehouses/{wh_id}", headers=headers)
    assert del_wh_res.status_code == 400
    assert "active stock" in del_wh_res.json()["detail"]


@pytest.mark.asyncio
async def test_same_and_cross_warehouse_transfers(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get warehouses and bins
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh_list = wh_res.json()
    assert len(wh_list) >= 2
    wh_main = wh_list[0]
    wh_secondary = wh_list[1]

    src_bin = next(b for b in wh_main["bins"] if b["type"] == "STORAGE")
    same_wh_dst_bin = next(b for b in wh_main["bins"] if b["type"] == "STAGING")
    cross_wh_dst_bin = next(b for b in wh_secondary["bins"] if b["type"] == "STORAGE")

    # Get an item with stock in src_bin
    bal_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={src_bin['id']}&stock_status=in_stock", headers=headers)
    bal_item = bal_res.json()["items"][0]
    var_id = bal_item["item_variant_id"]
    initial_avail = bal_item["quantity_available"]
    assert initial_avail >= 10

    # 1. Same Warehouse Transfer (5 units)
    transfer_same_res = await client.post("/api/v1/ledger/transfers", headers=headers, json={
        "item_variant_id": var_id,
        "source_bin_id": src_bin["id"],
        "destination_bin_id": same_wh_dst_bin["id"],
        "quantity": 5.0,
        "notes": "Internal bin consolidation"
    })
    assert transfer_same_res.status_code == 200
    assert "transaction_number" in transfer_same_res.json()

    # 2. Cross Warehouse Transfer (3 units)
    transfer_cross_res = await client.post("/api/v1/ledger/transfers", headers=headers, json={
        "item_variant_id": var_id,
        "source_bin_id": src_bin["id"],
        "destination_bin_id": cross_wh_dst_bin["id"],
        "quantity": 3.0,
        "notes": "Inter-facility transfer"
    })
    assert transfer_cross_res.status_code == 200

    # 3. Insufficient Stock Transfer Rejection (attempt to transfer 9999 units)
    insuf_res = await client.post("/api/v1/ledger/transfers", headers=headers, json={
        "item_variant_id": var_id,
        "source_bin_id": src_bin["id"],
        "destination_bin_id": cross_wh_dst_bin["id"],
        "quantity": 99999.0,
        "notes": "Overdraft attempt"
    })
    assert insuf_res.status_code == 422
    assert "Insufficient stock" in insuf_res.json()["detail"]

    # 4. Verify ledger entries created
    ledger_res = await client.get(f"/api/v1/ledger/entries?item_variant_id={var_id}", headers=headers)
    assert ledger_res.status_code == 200
    assert len(ledger_res.json()["items"]) >= 2


@pytest.mark.asyncio
async def test_stock_adjustment_cycle_count(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Pick a bin & variant
    bal_res = await client.get("/api/v1/ledger/balances?stock_status=in_stock", headers=headers)
    bal_item = bal_res.json()["items"][0]
    var_id = bal_item["item_variant_id"]
    bin_id = bal_item["location_bin_id"]
    current_qty = bal_item["quantity_on_hand"]

    # 1. Adjust stock upwards (+10 units)
    target_up = current_qty + 10.0
    adj_up_res = await client.post("/api/v1/ledger/adjustments", headers=headers, json={
        "item_variant_id": var_id,
        "location_bin_id": bin_id,
        "counted_quantity": target_up,
        "reason": "Quarterly physical cycle count found extra packaging units",
        "adjustment_type": "INVENTORY_ADJUSTMENT"
    })
    assert adj_up_res.status_code == 200
    assert adj_up_res.json()["variance"] == 10.0

    # 2. Adjust stock downwards (-5 units)
    target_down = target_up - 5.0
    adj_down_res = await client.post("/api/v1/ledger/adjustments", headers=headers, json={
        "item_variant_id": var_id,
        "location_bin_id": bin_id,
        "counted_quantity": target_down,
        "reason": "Damaged goods discarded during inspection",
        "adjustment_type": "SCRAP"
    })
    assert adj_down_res.status_code == 200
    assert adj_down_res.json()["variance"] == -5.0


@pytest.mark.asyncio
async def test_sequential_transfers_and_invariants(client: AsyncClient):
    """
    Tests sequential stock movements across multiple bins and verifies ledger balance invariants.
    """
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh_main = wh_res.json()[0]
    bin_a = wh_main["bins"][0]["id"]
    bin_b = wh_main["bins"][1]["id"]

    bal_res = await client.get("/api/v1/ledger/balances?stock_status=in_stock", headers=headers)
    var_id = bal_res.json()["items"][0]["item_variant_id"]

    # Pre-seed bin_a with 50 units
    await client.post("/api/v1/ledger/adjustments", headers=headers, json={
        "item_variant_id": var_id,
        "location_bin_id": bin_a,
        "counted_quantity": 50.0,
        "reason": "Pre-seed transfer test balance"
    })

    # Perform 5 consecutive transfers of 5 units each from bin_a to bin_b
    for _ in range(5):
        tr_res = await client.post("/api/v1/ledger/transfers", headers=headers, json={
            "item_variant_id": var_id,
            "source_bin_id": bin_a,
            "destination_bin_id": bin_b,
            "quantity": 5.0,
            "notes": "Incremental transfer"
        })
        assert tr_res.status_code == 200

    # Verify final balance in bin_a is exactly 25.0
    bal_a_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={bin_a}", headers=headers)
    bal_a = bal_a_res.json()["items"][0]
    assert bal_a["quantity_on_hand"] == 25.0
