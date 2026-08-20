import pytest
import uuid
from decimal import Decimal
from httpx import AsyncClient
from app.core.security import create_access_token
from app.models.warehouse import Warehouse

@pytest.mark.asyncio
async def test_supplier_crud_uniqueness_and_rbac(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sup_code = f"SUP-{uuid.uuid4().hex[:4].upper()}"

    # 1. Create Supplier
    create_res = await client.post("/api/v1/purchase-orders/suppliers", headers=headers, json={
        "code": sup_code,
        "name": "Apex Micro Electronics Ltd",
        "email": "sales@apexmicro.com",
        "phone": "+1-555-0199",
        "payment_terms": "Net 45",
        "currency": "USD"
    })
    assert create_res.status_code == 201
    sup = create_res.json()
    sup_id = sup["id"]
    assert sup["code"] == sup_code
    assert sup["name"] == "Apex Micro Electronics Ltd"

    # 2. Duplicate Supplier Code Rejection
    dup_res = await client.post("/api/v1/purchase-orders/suppliers", headers=headers, json={
        "code": sup_code,
        "name": "Duplicate Supplier"
    })
    assert dup_res.status_code == 400

    # 3. Update Supplier
    up_res = await client.put(f"/api/v1/purchase-orders/suppliers/{sup_id}", headers=headers, json={
        "name": "Apex Micro Electronics Global",
        "payment_terms": "Net 60"
    })
    assert up_res.status_code == 200
    assert up_res.json()["name"] == "Apex Micro Electronics Global"
    assert up_res.json()["payment_terms"] == "Net 60"

    # 4. List Suppliers with Query
    list_res = await client.get(f"/api/v1/purchase-orders/suppliers?q={sup_code}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 5. Delete empty supplier
    del_res = await client.delete(f"/api/v1/purchase-orders/suppliers/{sup_id}", headers=headers)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_po_creation_draft_calculations_and_editing(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch supplier, warehouse, and items
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    sup_id = sup_res.json()[0]["id"]

    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh_id = wh_res.json()[0]["id"]

    item_res = await client.get("/api/v1/items?page_size=2", headers=headers)
    item_variant = item_res.json()["items"][0]["variants"][0]
    var_id = item_variant["id"]

    # 1. Create Purchase Order
    # Line: 10 units @ $50.00, discount 10%, tax 5%
    # Subtotal = $500.00, Discount = $50.00, Tax = 5% of $450 = $22.50, Total = $472.50
    po_res = await client.post("/api/v1/purchase-orders", headers=headers, json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh_id,
        "notes": "Initial test procurement order",
        "lines": [{
            "item_variant_id": var_id,
            "quantity_ordered": 10.0,
            "unit_price": 50.0,
            "discount_pct": 10.0,
            "tax_pct": 5.0
        }]
    })
    assert po_res.status_code == 201
    po = po_res.json()
    po_id = po["id"]
    assert po["status"] == "DRAFT"
    assert po["subtotal_amount"] == 500.0
    assert po["discount_amount"] == 50.0
    assert po["tax_amount"] == 22.5
    assert po["total_amount"] == 472.5

    # 2. Update Draft Purchase Order
    up_po_res = await client.put(f"/api/v1/purchase-orders/{po_id}", headers=headers, json={
        "notes": "Updated procurement specifications",
        "lines": [{
            "item_variant_id": var_id,
            "quantity_ordered": 20.0,
            "unit_price": 50.0,
            "discount_pct": 0.0,
            "tax_pct": 0.0
        }]
    })
    assert up_po_res.status_code == 200
    assert up_po_res.json()["total_amount"] == 1000.0


@pytest.mark.asyncio
async def test_po_lifecycle_submit_approval_and_cancel(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    sup_id = sup_res.json()[0]["id"]
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh_id = wh_res.json()[0]["id"]
    item_res = await client.get("/api/v1/items?page_size=1", headers=headers)
    var_id = item_res.json()["items"][0]["variants"][0]["id"]

    # 1. Create PO
    po_res = await client.post("/api/v1/purchase-orders", headers=headers, json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": var_id, "quantity_ordered": 5.0, "unit_price": 10.0}]
    })
    po_id = po_res.json()["id"]

    # 2. Submit for approval (DRAFT -> PENDING_APPROVAL)
    sub_res = await client.post(f"/api/v1/purchase-orders/{po_id}/submit", headers=headers)
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "PENDING_APPROVAL"

    # 3. Approve PO (PENDING_APPROVAL -> APPROVED)
    app_res = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers)
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "APPROVED"

    # 4. Cancel PO
    cancel_res = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_goods_receipt_partial_and_full_with_over_receipt_protection(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    sup_id = sup_res.json()[0]["id"]
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    wh_id = wh["id"]
    rcv_bin = next(b for b in wh["bins"] if b["type"] in ["RECEIVING", "STORAGE"])

    item_res = await client.get("/api/v1/items?page_size=1", headers=headers)
    var_id = item_res.json()["items"][0]["variants"][0]["id"]

    # Record initial stock balance
    bal_before_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={rcv_bin['id']}&item_variant_id={var_id}", headers=headers)
    bal_items = bal_before_res.json()["items"]
    initial_stock = bal_items[0]["quantity_on_hand"] if bal_items else 0.0

    # 1. Create and Approve PO for 10 units
    po_res = await client.post("/api/v1/purchase-orders", headers=headers, json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": var_id, "quantity_ordered": 10.0, "unit_price": 25.0}]
    })
    po_id = po_res.json()["id"]
    po_line_id = po_res.json()["lines"][0]["id"]

    # Critical Invariant: PO creation does NOT increase stock
    bal_check_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={rcv_bin['id']}&item_variant_id={var_id}", headers=headers)
    curr_items = bal_check_res.json()["items"]
    curr_stock = curr_items[0]["quantity_on_hand"] if curr_items else 0.0
    assert curr_stock == initial_stock

    await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers)

    # 2. Over-receipt rejection: attempt to receive 15 units (ordered: 10)
    over_gr_res = await client.post("/api/v1/purchase-orders/receive", headers=headers, json={
        "purchase_order_id": po_id,
        "warehouse_id": wh_id,
        "lines": [{
            "po_line_id": po_line_id,
            "item_variant_id": var_id,
            "quantity_received": 15.0,
            "destination_bin_id": rcv_bin["id"]
        }]
    })
    assert over_gr_res.status_code == 422
    assert "remaining order quantity is" in over_gr_res.json()["detail"]

    # 3. Partial Goods Receipt: Receive 4 units
    gr_part_res = await client.post("/api/v1/purchase-orders/receive", headers=headers, json={
        "purchase_order_id": po_id,
        "warehouse_id": wh_id,
        "lines": [{
            "po_line_id": po_line_id,
            "item_variant_id": var_id,
            "quantity_received": 4.0,
            "destination_bin_id": rcv_bin["id"]
        }]
    })
    assert gr_part_res.status_code == 201

    # Verify PO status is PARTIALLY_RECEIVED and remaining is 6
    po_detail_res = await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)
    assert po_detail_res.json()["status"] == "PARTIALLY_RECEIVED"
    assert po_detail_res.json()["lines"][0]["quantity_received"] == 4.0
    assert po_detail_res.json()["lines"][0]["quantity_remaining"] == 6.0

    # Verify inventory increased by exactly 4.0
    bal_mid_res = await client.get(f"/api/v1/ledger/balances?location_bin_id={rcv_bin['id']}&item_variant_id={var_id}", headers=headers)
    mid_stock = bal_mid_res.json()["items"][0]["quantity_on_hand"]
    assert mid_stock == initial_stock + 4.0

    # 4. Cannot cancel PO once partially received
    cancel_attempt = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=headers)
    assert cancel_attempt.status_code == 400

    # 5. Final Goods Receipt: Receive remaining 6 units with batch tracking
    gr_final_res = await client.post("/api/v1/purchase-orders/receive", headers=headers, json={
        "purchase_order_id": po_id,
        "warehouse_id": wh_id,
        "lines": [{
            "po_line_id": po_line_id,
            "item_variant_id": var_id,
            "quantity_received": 6.0,
            "destination_bin_id": rcv_bin["id"],
            "batch_number": "BATCH-2026-X1"
        }]
    })
    assert gr_final_res.status_code == 201

    # Verify PO is now COMPLETED
    po_final_res = await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers)
    assert po_final_res.json()["status"] == "COMPLETED"
    assert po_final_res.json()["lines"][0]["quantity_received"] == 10.0
    assert po_final_res.json()["lines"][0]["quantity_remaining"] == 0.0

    # Verify receipts history list
    assert len(po_final_res.json()["receipts"]) == 2


@pytest.mark.asyncio
async def test_unapproved_po_receipt_rejection(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=headers)
    sup_id = sup_res.json()[0]["id"]
    wh_res = await client.get("/api/v1/warehouses", headers=headers)
    wh = wh_res.json()[0]
    wh_id = wh["id"]
    bin_id = wh["bins"][0]["id"]

    item_res = await client.get("/api/v1/items?page_size=1", headers=headers)
    var_id = item_res.json()["items"][0]["variants"][0]["id"]

    # 1. Create Draft PO
    po_res = await client.post("/api/v1/purchase-orders", headers=headers, json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": var_id, "quantity_ordered": 8.0, "unit_price": 15.0}]
    })
    po_id = po_res.json()["id"]
    po_line_id = po_res.json()["lines"][0]["id"]

    # Attempt to receive goods while PO is still DRAFT (must be rejected with HTTP 400)
    gr_res = await client.post("/api/v1/purchase-orders/receive", headers=headers, json={
        "purchase_order_id": po_id,
        "warehouse_id": wh_id,
        "lines": [{
            "po_line_id": po_line_id,
            "item_variant_id": var_id,
            "quantity_received": 8.0,
            "destination_bin_id": bin_id
        }]
    })
    assert gr_res.status_code == 400
    assert "must be APPROVED" in gr_res.json()["detail"]
