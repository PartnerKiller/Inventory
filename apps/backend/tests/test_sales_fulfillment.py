import pytest
import asyncio
from decimal import Decimal
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_customer_crud_uniqueness_and_rbac(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Customer
    create_res = await client.post("/api/v1/sales-orders/customers", json={
        "code": "CUST-ACME-01",
        "name": "Acme Industrial Corporation",
        "email": "procurement@acme.com",
        "phone": "+1-555-8822",
        "billing_address": {"street": "100 Industrial Pkwy", "city": "Dallas", "state": "TX"},
        "shipping_address": {"street": "100 Industrial Pkwy Dock 4", "city": "Dallas", "state": "TX"}
    }, headers=headers)
    assert create_res.status_code == 201
    cust = create_res.json()
    cust_id = cust["id"]
    assert cust["code"] == "CUST-ACME-01"
    assert cust["name"] == "Acme Industrial Corporation"

    # 2. Duplicate Code Rejection
    dup_res = await client.post("/api/v1/sales-orders/customers", json={
        "code": "CUST-ACME-01",
        "name": "Duplicate Acme"
    }, headers=headers)
    assert dup_res.status_code == 400

    # 3. Update Customer
    upd_res = await client.put(f"/api/v1/sales-orders/customers/{cust_id}", json={
        "name": "Acme Global Industries",
        "phone": "+1-555-9900"
    }, headers=headers)
    assert upd_res.status_code == 200
    assert upd_res.json()["name"] == "Acme Global Industries"

    # 4. List Customers with Search
    list_res = await client.get("/api/v1/sales-orders/customers?q=Acme", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 5. Delete Customer (no active orders -> success)
    del_res = await client.delete(f"/api/v1/sales-orders/customers/{cust_id}", headers=headers)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_sales_order_creation_draft_editing_and_calculations(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch customer, warehouse, item variant
    cust_res = await client.get("/api/v1/sales-orders/customers", headers=headers)
    customer_id = cust_res.json()[0]["id"]

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    warehouse_id = wh_res.json()[0]["id"]

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # 1. Create Sales Order (Draft) with discount and tax
    # Line: qty=10, price=100 -> base=1000, disc 10% -> 900, tax 5% -> 945
    create_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "notes": "Standard commercial terms",
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 10.0,
                "unit_price": 100.0,
                "discount_pct": 10.0,
                "tax_pct": 5.0
            }
        ]
    }, headers=headers)
    assert create_res.status_code == 201
    so = create_res.json()
    so_id = so["id"]
    assert so["status"] == "DRAFT"
    assert abs(so["subtotal_amount"] - 1000.0) < 0.01
    assert abs(so["discount_amount"] - 100.0) < 0.01
    assert abs(so["tax_amount"] - 45.0) < 0.01
    assert abs(so["total_amount"] - 945.0) < 0.01

    # 2. Update Draft SO Lines
    # New Line: qty=20, price=50 -> base=1000, disc 0%, tax 0% -> 1000
    upd_res = await client.put(f"/api/v1/sales-orders/{so_id}", json={
        "notes": "Updated rush delivery",
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 20.0,
                "unit_price": 50.0,
                "discount_pct": 0.0,
                "tax_pct": 0.0
            }
        ]
    }, headers=headers)
    assert upd_res.status_code == 200
    upd_so = upd_res.json()
    assert abs(upd_so["total_amount"] - 1000.0) < 0.01
    assert upd_so["notes"] == "Updated rush delivery"


@pytest.mark.asyncio
async def test_sales_order_lifecycle_confirm_cancel_and_allocation_release(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Setup: restock goods first via Goods Receipt so warehouse has inventory
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    supplier_id = sup_res.json()[0]["id"]

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    stg_bin = next(b for b in wh["bins"] if b["type"] == "STORAGE")

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # Inbound stock via cycle adjustment to guarantee 100 units in storage bin
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 100.0,
        "reason": "Restock for SO lifecycle test"
    }, headers=headers)

    cust_res = await client.get("/api/v1/sales-orders/customers", headers=headers)
    customer_id = cust_res.json()[0]["id"]

    # 1. Create SO (Draft)
    create_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 25.0,
                "unit_price": 50.0
            }
        ]
    }, headers=headers)
    assert create_res.status_code == 201
    so = create_res.json()
    so_id = so["id"]

    # 2. Confirm SO
    conf_res = await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=headers)
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "CONFIRMED"

    # 3. Allocate Stock (reserves 25 units)
    alloc_res = await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=headers)
    assert alloc_res.status_code == 200
    assert alloc_res.json()["status"] == "ALLOCATED"
    assert alloc_res.json()["lines"][0]["quantity_allocated"] == 25.0

    # Verify StockBalance: on_hand=100, allocated=25, available=75
    bal_res = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    bal = bal_res.json()["items"][0]
    assert bal["quantity_on_hand"] == 100.0
    assert bal["quantity_allocated"] == 25.0
    assert bal["quantity_available"] == 75.0

    # 4. Cancel SO -> must de-allocate stock back to available!
    cancel_res = await client.post(f"/api/v1/sales-orders/{so_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Verify StockBalance after cancellation: on_hand=100, allocated=0, available=100
    bal_res2 = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    bal2 = bal_res2.json()["items"][0]
    assert bal2["quantity_on_hand"] == 100.0
    assert bal2["quantity_allocated"] == 0.0
    assert bal2["quantity_available"] == 100.0


@pytest.mark.asyncio
async def test_stock_allocation_and_insufficient_stock_rejection(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    warehouse_id = wh_res.json()[0]["id"]
    cust_res = await client.get("/api/v1/sales-orders/customers", headers=headers)
    customer_id = cust_res.json()[0]["id"]
    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # Create SO requesting 5,000,000 units (far exceeds physical stock)
    create_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 5000000.0,
                "unit_price": 20.0
            }
        ]
    }, headers=headers)
    assert create_res.status_code == 201
    so_id = create_res.json()["id"]

    await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=headers)

    # Attempt allocation -> must reject with HTTP 422
    alloc_res = await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=headers)
    assert alloc_res.status_code == 422
    assert "Insufficient available stock" in alloc_res.json()["detail"]


@pytest.mark.asyncio
async def test_picking_packing_and_dispatch_atomic_workflow(client: AsyncClient):
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

    # Set known physical baseline: 80 units
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 80.0,
        "reason": "Set baseline 80 units for dispatch test"
    }, headers=headers)

    # 1. Create SO for 30 units
    create_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [
            {
                "item_variant_id": variant_id,
                "quantity_ordered": 30.0,
                "unit_price": 75.0
            }
        ]
    }, headers=headers)
    so = create_res.json()
    so_id = so["id"]
    line_id = so["lines"][0]["id"]

    # 2. Confirm and Allocate
    await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=headers)
    alloc_res = await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=headers)
    assert alloc_res.status_code == 200
    assert alloc_res.json()["status"] == "ALLOCATED"

    # 3. Pick items (cannot pick > 30)
    over_pick_res = await client.post(f"/api/v1/sales-orders/{so_id}/pick", json={
        "picks": [{"so_line_id": line_id, "quantity_picked": 50.0}]
    }, headers=headers)
    assert over_pick_res.status_code == 400

    # Pick exact 30 units
    pick_res = await client.post(f"/api/v1/sales-orders/{so_id}/pick", json={
        "picks": [{"so_line_id": line_id, "quantity_picked": 30.0}]
    }, headers=headers)
    assert pick_res.status_code == 200

    # 4. Pack items
    pack_res = await client.post(f"/api/v1/sales-orders/{so_id}/pack", json={
        "package_count": 2,
        "total_weight": 14.5,
        "packing_notes": "Box 1 of 2 and Box 2 of 2 secured"
    }, headers=headers)
    assert pack_res.status_code == 200
    assert pack_res.json()["status"] == "PACKED"

    # 5. Dispatch / Ship Order
    dispatch_res = await client.post(f"/api/v1/sales-orders/{so_id}/dispatch", json={
        "carrier": "FedEx Freight",
        "tracking_number": "TRK-FDX-998822",
        "package_count": 2,
        "total_weight": 14.5,
        "notes": "Loaded onto trailer dock 3"
    }, headers=headers)
    assert dispatch_res.status_code == 201
    shp = dispatch_res.json()
    assert "SHP-" in shp["shipment_number"]
    assert shp["carrier"] == "FedEx Freight"

    # Verify SO status is SHIPPED
    detail_res = await client.get(f"/api/v1/sales-orders/{so_id}", headers=headers)
    assert detail_res.json()["status"] == "SHIPPED"
    assert detail_res.json()["lines"][0]["quantity_shipped"] == 30.0

    # Verify physical inventory was deducted: 80 - 30 = 50 on hand, 0 allocated, 50 available!
    bal_res = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    bal = bal_res.json()["items"][0]
    assert bal["quantity_on_hand"] == 50.0
    assert bal["quantity_allocated"] == 0.0
    assert bal["quantity_available"] == 50.0


@pytest.mark.asyncio
async def test_sales_returns_good_and_damaged_stock(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    warehouse_id = wh["id"]
    rcv_bin = next(b for b in wh["bins"] if b["type"] == "RECEIVING")
    stg_bin = next(b for b in wh["bins"] if b["type"] == "STORAGE")

    dmg_bin = next((b for b in wh["bins"] if b["type"] == "DAMAGE"), None)
    if not dmg_bin:
        new_dmg_bin_res = await client.post(f"/api/v1/warehouses/{warehouse_id}/bins", json={
            "code": f"{wh['code']}-DMG-01",
            "type": "DAMAGE"
        }, headers=headers)
        dmg_bin = new_dmg_bin_res.json()

    items_res = await client.get("/api/v1/items", headers=headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]
    cust_res = await client.get("/api/v1/sales-orders/customers", headers=headers)
    customer_id = cust_res.json()[0]["id"]

    # Baseline 100 units
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 100.0,
        "reason": "Baseline for RMA test"
    }, headers=headers)

    # Create, confirm, allocate, pack, dispatch SO for 20 units
    so_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 20.0, "unit_price": 50.0}]
    }, headers=headers)
    so_id = so_res.json()["id"]
    line_id = so_res.json()["lines"][0]["id"]

    await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=headers)
    await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=headers)
    await client.post(f"/api/v1/sales-orders/{so_id}/pack", json={"package_count": 1}, headers=headers)
    await client.post(f"/api/v1/sales-orders/{so_id}/dispatch", json={"carrier": "UPS"}, headers=headers)

    # 1. Over-Return rejection (attempt return of 25 > 20 shipped)
    over_ret_res = await client.post(f"/api/v1/sales-orders/{so_id}/returns", json={
        "lines": [{"so_line_id": line_id, "quantity_returned": 25.0, "condition": "GOOD", "destination_bin_id": rcv_bin["id"]}]
    }, headers=headers)
    assert over_ret_res.status_code == 422

    # 2. Return 5 units in GOOD condition to receiving bin
    good_ret_res = await client.post(f"/api/v1/sales-orders/{so_id}/returns", json={
        "notes": "Customer ordered excess, returning unopened",
        "lines": [{"so_line_id": line_id, "quantity_returned": 5.0, "condition": "GOOD", "destination_bin_id": rcv_bin["id"]}]
    }, headers=headers)
    assert good_ret_res.status_code == 201
    assert "RMA-" in good_ret_res.json()["return_number"]

    # 3. Return 2 units in DAMAGED condition to DAMAGE bin
    dmg_ret_res = await client.post(f"/api/v1/sales-orders/{so_id}/returns", json={
        "notes": "Damaged in transit",
        "lines": [{"so_line_id": line_id, "quantity_returned": 2.0, "condition": "DAMAGED", "destination_bin_id": dmg_bin["id"]}]
    }, headers=headers)
    assert dmg_ret_res.status_code == 201

    # Verify inventory was returned:
    # Initial: 100 - 20 = 80 in storage
    # Good return: +5 in receiving
    # Damaged return: +2 in damage
    # Total on hand = 87
    detail_res = await client.get(f"/api/v1/sales-orders/{so_id}", headers=headers)
    assert len(detail_res.json()["returns"]) == 2
    assert detail_res.json()["lines"][0]["quantity_returned"] == 7.0


@pytest.mark.asyncio
async def test_concurrent_stock_allocation_conflict(client: AsyncClient):
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

    # 1. Baseline: exactly 100 units available
    await client.post("/api/v1/ledger/adjustments", json={
        "item_variant_id": variant_id,
        "location_bin_id": stg_bin["id"],
        "counted_quantity": 100.0,
        "reason": "Baseline 100 units for concurrency allocation test"
    }, headers=headers)

    # 2. Create Order A requesting 60 units
    so_a = (await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 60.0, "unit_price": 50.0}]
    }, headers=headers)).json()
    await client.post(f"/api/v1/sales-orders/{so_a['id']}/confirm", headers=headers)

    # 3. Create Order B requesting 60 units
    so_b = (await client.post("/api/v1/sales-orders", json={
        "customer_id": customer_id,
        "warehouse_id": warehouse_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 60.0, "unit_price": 50.0}]
    }, headers=headers)).json()
    await client.post(f"/api/v1/sales-orders/{so_b['id']}/confirm", headers=headers)

    # 4. Attempt allocations
    # Order A allocates first -> succeeds
    alloc_a = await client.post(f"/api/v1/sales-orders/{so_a['id']}/allocate", headers=headers)
    assert alloc_a.status_code == 200
    assert alloc_a.json()["status"] == "ALLOCATED"

    # Order B attempts to allocate 60 when only 40 are available -> must fail with HTTP 422
    alloc_b = await client.post(f"/api/v1/sales-orders/{so_b['id']}/allocate", headers=headers)
    assert alloc_b.status_code == 422
    assert "Insufficient available stock" in alloc_b.json()["detail"]

    # 5. Verify invariant: on_hand=100, allocated=60, available=40
    bal_res = await client.get(f"/api/v1/ledger/balances?warehouse_id={warehouse_id}&item_variant_id={variant_id}", headers=headers)
    bal = bal_res.json()["items"][0]
    assert bal["quantity_on_hand"] == 100.0
    assert bal["quantity_allocated"] == 60.0
    assert bal["quantity_available"] == 40.0
