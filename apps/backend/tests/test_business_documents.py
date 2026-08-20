import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_business_documents_end_to_end_and_pdf_generation(client: AsyncClient):
    # 1. Login as Admin
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    assert login_res.status_code == 200
    admin_token = login_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Setup baseline entities
    wh_res = await client.get("/api/v1/warehouses", headers=admin_headers)
    wh = wh_res.json()[0]
    wh_id = wh["id"]
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=admin_headers)
    sup_id = sup_res.json()[0]["id"]
    items_res = await client.get("/api/v1/items", headers=admin_headers)
    item = items_res.json()["items"][0]
    variant_id = item["variants"][0]["id"]
    cust_res = await client.get("/api/v1/sales-orders/customers", headers=admin_headers)
    cust_id = cust_res.json()[0]["id"]

    # =========================================================================
    # 1. PURCHASE ORDER & GOODS RECEIPT (GRN)
    # =========================================================================
    po_res = await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 10.0, "unit_price": 50.0}]
    }, headers=admin_headers)
    assert po_res.status_code == 201
    po = po_res.json()
    po_id = po["id"]
    po_number = po["po_number"]

    # Approve PO
    await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=admin_headers)

    # Receive PO -> GRN
    bin_id = wh["bins"][0]["id"]
    grn_res = await client.post("/api/v1/purchase-orders/receive", json={
        "purchase_order_id": po_id,
        "warehouse_id": wh_id,
        "lines": [{
            "po_line_id": po["lines"][0]["id"],
            "item_variant_id": variant_id,
            "quantity_received": 10.0,
            "destination_bin_id": bin_id
        }]
    }, headers=admin_headers)
    assert grn_res.status_code == 201
    grn = grn_res.json()
    grn_id = grn["id"]

    # Verify PO Document Payload & PDF
    po_doc_res = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po_id}", headers=admin_headers)
    assert po_doc_res.status_code == 200
    po_doc = po_doc_res.json()
    assert po_doc["header"]["document_number"] == po_number
    assert po_doc["header"]["document_title"] == "PURCHASE ORDER"
    assert len(po_doc["lines"]) == 1
    assert po_doc["summary"]["grand_total"] == 500.0

    po_pdf_res = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po_id}/pdf", headers=admin_headers)
    assert po_pdf_res.status_code == 200
    assert po_pdf_res.headers["content-type"] == "application/pdf"
    assert len(po_pdf_res.content) > 1000
    assert po_pdf_res.content.startswith(b"%PDF")

    # Verify GRN Document Payload & PDF
    grn_doc_res = await client.get(f"/api/v1/documents/GOODS_RECEIPT/{grn_id}", headers=admin_headers)
    assert grn_doc_res.status_code == 200
    grn_doc = grn_doc_res.json()
    assert grn_doc["header"]["document_number"] == grn["grn_number"]
    assert grn_doc["header"]["document_title"] == "GOODS RECEIPT NOTE (GRN)"

    grn_pdf_res = await client.get(f"/api/v1/documents/GOODS_RECEIPT/{grn_id}/pdf", headers=admin_headers)
    assert grn_pdf_res.status_code == 200
    assert grn_pdf_res.content.startswith(b"%PDF")

    # =========================================================================
    # 2. SALES ORDER, INVOICE, PACKING SLIP, DELIVERY NOTE & RMA
    # =========================================================================
    so_res = await client.post("/api/v1/sales-orders", json={
        "customer_id": cust_id,
        "warehouse_id": wh_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 5.0, "unit_price": 95.0}]
    }, headers=admin_headers)
    assert so_res.status_code == 201
    so = so_res.json()
    so_id = so["id"]
    so_number = so["so_number"]

    # Confirm & Allocate
    await client.post(f"/api/v1/sales-orders/{so_id}/confirm", headers=admin_headers)
    await client.post(f"/api/v1/sales-orders/{so_id}/allocate", headers=admin_headers)

    # Pick
    await client.post(f"/api/v1/sales-orders/{so_id}/pick", json={
        "picks": [{"so_line_id": so["lines"][0]["id"], "source_bin_id": bin_id, "quantity_picked": 5.0}]
    }, headers=admin_headers)

    # Pack
    await client.post(f"/api/v1/sales-orders/{so_id}/pack", json={
        "packs": [{"so_line_id": so["lines"][0]["id"], "quantity_packed": 5.0}]
    }, headers=admin_headers)

    # Dispatch / Ship
    await client.post(f"/api/v1/sales-orders/{so_id}/dispatch", json={
        "shipping_carrier": "FedEx Priority",
        "tracking_number": "TRK-987654321",
        "notes": "Signature required"
    }, headers=admin_headers)

    # Verify Sales Order PDF
    so_doc_res = await client.get(f"/api/v1/documents/SALES_ORDER/{so_id}", headers=admin_headers)
    assert so_doc_res.status_code == 200
    assert so_doc_res.json()["header"]["document_number"] == so_number

    so_pdf_res = await client.get(f"/api/v1/documents/SALES_ORDER/{so_id}/pdf", headers=admin_headers)
    assert so_pdf_res.status_code == 200
    assert so_pdf_res.content.startswith(b"%PDF")

    # Verify Sales Invoice PDF
    inv_doc_res = await client.get(f"/api/v1/documents/SALES_INVOICE/{so_id}", headers=admin_headers)
    assert inv_doc_res.status_code == 200
    assert "INV-" in inv_doc_res.json()["header"]["document_number"]

    inv_pdf_res = await client.get(f"/api/v1/documents/SALES_INVOICE/{so_id}/pdf", headers=admin_headers)
    assert inv_pdf_res.status_code == 200
    assert inv_pdf_res.content.startswith(b"%PDF")

    # Verify Packing Slip PDF
    pack_doc_res = await client.get(f"/api/v1/documents/PACKING_SLIP/{so_id}", headers=admin_headers)
    assert pack_doc_res.status_code == 200
    assert pack_doc_res.json()["header"]["document_title"] == "WAREHOUSE PACKING SLIP"

    pack_pdf_res = await client.get(f"/api/v1/documents/PACKING_SLIP/{so_id}/pdf", headers=admin_headers)
    assert pack_pdf_res.status_code == 200
    assert pack_pdf_res.content.startswith(b"%PDF")

    # Verify Delivery Note PDF
    deliv_doc_res = await client.get(f"/api/v1/documents/DELIVERY_NOTE/{so_id}", headers=admin_headers)
    assert deliv_doc_res.status_code == 200
    assert deliv_doc_res.json()["header"]["document_title"] == "DISPATCH & DELIVERY NOTE"

    deliv_pdf_res = await client.get(f"/api/v1/documents/DELIVERY_NOTE/{so_id}/pdf", headers=admin_headers)
    assert deliv_pdf_res.status_code == 200
    assert deliv_pdf_res.content.startswith(b"%PDF")

    # Sales Return (RMA)
    rma_res = await client.post(f"/api/v1/sales-orders/{so_id}/returns", json={
        "notes": "Unopened items returned by customer",
        "lines": [{
            "so_line_id": so["lines"][0]["id"],
            "quantity_returned": 1.0,
            "condition": "GOOD",
            "destination_bin_id": bin_id
        }]
    }, headers=admin_headers)
    assert rma_res.status_code == 201
    rma_id = rma_res.json()["id"]

    rma_doc_res = await client.get(f"/api/v1/documents/SALES_RETURN/{rma_id}", headers=admin_headers)
    assert rma_doc_res.status_code == 200
    assert rma_doc_res.json()["header"]["document_title"] == "RETURN MERCHANDISE AUTHORIZATION (RMA)"

    rma_pdf_res = await client.get(f"/api/v1/documents/SALES_RETURN/{rma_id}/pdf", headers=admin_headers)
    assert rma_pdf_res.status_code == 200
    assert rma_pdf_res.content.startswith(b"%PDF")

    # =========================================================================
    # 3. STOCK TRANSFER & ADJUSTMENT SLIPS
    # =========================================================================
    bin2_id = wh["bins"][1]["id"]
    tx_transfer = (await client.post("/api/v1/ledger/transfers", json={
        "source_bin_id": bin_id,
        "destination_bin_id": bin2_id,
        "item_variant_id": variant_id,
        "quantity": 2.0,
        "notes": "Inter-bin staging transfer"
    }, headers=admin_headers)).json()
    transfer_tx_id = tx_transfer["transaction_id"]

    transfer_doc_res = await client.get(f"/api/v1/documents/STOCK_TRANSFER/{transfer_tx_id}", headers=admin_headers)
    assert transfer_doc_res.status_code == 200
    assert transfer_doc_res.json()["header"]["document_title"] == "INTERNAL STOCK TRANSFER DOCKET"

    transfer_pdf_res = await client.get(f"/api/v1/documents/STOCK_TRANSFER/{transfer_tx_id}/pdf", headers=admin_headers)
    assert transfer_pdf_res.status_code == 200
    assert transfer_pdf_res.content.startswith(b"%PDF")

    # Stock Adjustment Slip
    tx_adj = (await client.post("/api/v1/ledger/adjustments", json={
        "location_bin_id": bin2_id,
        "item_variant_id": variant_id,
        "counted_quantity": 3.0,
        "reason": "Routine cycle count verification"
    }, headers=admin_headers)).json()
    adj_tx_id = tx_adj["transaction_id"]

    adj_doc_res = await client.get(f"/api/v1/documents/STOCK_ADJUSTMENT/{adj_tx_id}", headers=admin_headers)
    assert adj_doc_res.status_code == 200
    assert adj_doc_res.json()["header"]["document_title"] == "INVENTORY ADJUSTMENT VOUCHER"

    adj_pdf_res = await client.get(f"/api/v1/documents/STOCK_ADJUSTMENT/{adj_tx_id}/pdf", headers=admin_headers)
    assert adj_pdf_res.status_code == 200
    assert adj_pdf_res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_barcode_label_sheet_generation(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = login_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Generate barcode label sheet
    label_res = await client.post("/api/v1/documents/barcodes/labels/pdf", json={
        "labels": [
            {
                "title": "Industrial IoT Sensor Pro",
                "sku": "SKU-IOT-001",
                "variant": "Standard",
                "barcode": "890123456789",
                "bin_code": "BIN-A1",
                "price_formatted": "$49.99"
            },
            {
                "title": "Precision Calibration Probe",
                "sku": "SKU-PRB-002",
                "variant": "High-Temp",
                "barcode": "890987654321",
                "bin_code": "BIN-B2",
                "price_formatted": "$129.00"
            }
        ],
        "copies_per_label": 2,
        "layout": "sticker"
    }, headers=admin_headers)

    assert label_res.status_code == 200
    assert label_res.headers["content-type"] == "application/pdf"
    assert len(label_res.content) > 1000
    assert label_res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_document_security_and_read_only_immutability(client: AsyncClient):
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=admin_headers)
    wh1 = wh_res.json()[0]
    wh2 = wh_res.json()[1]
    sup_id = (await client.get("/api/v1/purchase-orders/suppliers", headers=admin_headers)).json()[0]["id"]
    variant_id = (await client.get("/api/v1/items", headers=admin_headers)).json()["items"][0]["variants"][0]["id"]

    # Create PO in warehouse 2
    po = (await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup_id,
        "target_warehouse_id": wh2["id"],
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 5.0, "unit_price": 20.0}]
    }, headers=admin_headers)).json()

    # Create user scoped only to warehouse 1
    clerk_role = next(r for r in (await client.get("/api/v1/users/roles", headers=admin_headers)).json() if r["name"] == "WAREHOUSE_MANAGER")
    scoped_user = (await client.post("/api/v1/users", json={
        "email": "wh1.manager@inventory.local",
        "full_name": "WH1 Manager",
        "password": "ManagerPass123!",
        "role_ids": [clerk_role["id"]],
        "warehouse_ids": [wh1["id"]]
    }, headers=admin_headers)).json()

    scoped_login = await client.post("/api/v1/auth/login", json={
        "email": "wh1.manager@inventory.local",
        "password": "ManagerPass123!"
    })
    scoped_token = scoped_login.json()["access_token"]
    scoped_headers = {"Authorization": f"Bearer {scoped_token}"}

    # Attempt to access PO belonging to unauthorized warehouse 2 -> 403 Forbidden
    doc_res = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po['id']}", headers=scoped_headers)
    assert doc_res.status_code == 403

    pdf_res = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po['id']}/pdf", headers=scoped_headers)
    assert pdf_res.status_code == 403

    # Read-only immutability: Repeatedly requesting PDFs never changes PO status or quantities
    po_before = (await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=admin_headers)).json()
    for _ in range(3):
        await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po['id']}/pdf", headers=admin_headers)
    po_after = (await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=admin_headers)).json()
    assert po_before["status"] == po_after["status"]
    assert po_before["total_amount"] == po_after["total_amount"]
