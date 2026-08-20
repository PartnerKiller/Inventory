import pytest
import uuid
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.item import Item, ItemVariant, Barcode, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_category_crud_and_item_count(client: AsyncClient):
    # Authenticate admin
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Category
    cat_code = f"CAT-{uuid.uuid4().hex[:4].upper()}"
    create_res = await client.post(
        "/api/v1/items/categories",
        headers=headers,
        json={"name": "Industrial Hardware", "code": cat_code, "description": "High-durability components"}
    )
    assert create_res.status_code == 201
    cat_data = create_res.json()
    cat_id = cat_data["id"]
    assert cat_data["name"] == "Industrial Hardware"

    # 2. Duplicate Category Code Rejection
    dup_res = await client.post(
        "/api/v1/items/categories",
        headers=headers,
        json={"name": "Duplicate Hardware", "code": cat_code}
    )
    assert dup_res.status_code == 400

    # 3. Update Category
    update_res = await client.put(
        f"/api/v1/items/categories/{cat_id}",
        headers=headers,
        json={"name": "Heavy Industrial Hardware"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Heavy Industrial Hardware"

    # 4. List Categories
    list_res = await client.get("/api/v1/items/categories", headers=headers)
    assert list_res.status_code == 200
    assert any(c["id"] == cat_id for c in list_res.json())

    # 5. Delete Category
    del_res = await client.delete(f"/api/v1/items/categories/{cat_id}", headers=headers)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_product_creation_and_duplicate_sku_rejection(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sku = f"SKU-TEST-{uuid.uuid4().hex[:6].upper()}"
    bc_val = f"BC-{uuid.uuid4().hex[:8].upper()}"

    # 1. Create Product with custom variant and barcode
    prod_payload = {
        "sku": sku,
        "name": "Precision Digital Caliper",
        "description": "0-150mm Stainless steel digital caliper",
        "base_uom": "PCS",
        "valuation_method": "FIFO",
        "reorder_point": 15.0,
        "reorder_quantity": 60.0,
        "is_batch_tracked": True,
        "variants": [
            {
                "variant_sku": f"{sku}-PRO",
                "variant_name": "Pro Edition",
                "cost_price": 32.50,
                "selling_price": 68.00,
                "barcodes": [
                    {"barcode_value": bc_val, "symbology": "CODE128", "is_primary": True}
                ]
            }
        ]
    }

    create_res = await client.post("/api/v1/items", headers=headers, json=prod_payload)
    assert create_res.status_code == 201
    prod = create_res.json()
    assert prod["sku"] == sku
    assert prod["name"] == "Precision Digital Caliper"
    assert len(prod["variants"]) == 1
    assert prod["variants"][0]["barcodes"][0]["barcode_value"] == bc_val

    # 2. Duplicate SKU rejection
    dup_res = await client.post("/api/v1/items", headers=headers, json=prod_payload)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]


@pytest.mark.asyncio
async def test_product_update_and_detail(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sku = f"SKU-UPD-{uuid.uuid4().hex[:6].upper()}"
    create_res = await client.post("/api/v1/items", headers=headers, json={
        "sku": sku,
        "name": "Initial Product Name",
        "base_uom": "PCS",
        "valuation_method": "WEIGHTED_AVERAGE",
        "reorder_point": 5.0,
        "reorder_quantity": 25.0
    })
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]

    # 1. Update Product
    update_res = await client.put(f"/api/v1/items/{item_id}", headers=headers, json={
        "name": "Updated Product Name Deluxe",
        "reorder_point": 12.0,
        "is_active": False
    })
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["name"] == "Updated Product Name Deluxe"
    assert updated["reorder_point"] == 12.0
    assert updated["is_active"] is False

    # 2. Get Detail
    detail_res = await client.get(f"/api/v1/items/{item_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == item_id
    assert "bin_stock_breakdown" in detail


@pytest.mark.asyncio
async def test_product_variants_nested_crud(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sku = f"SKU-VAR-{uuid.uuid4().hex[:6].upper()}"
    create_res = await client.post("/api/v1/items", headers=headers, json={
        "sku": sku,
        "name": "Multi-Variant Power Drill",
        "base_uom": "PCS"
    })
    item_id = create_res.json()["id"]

    # 1. Add new variant
    v_sku = f"{sku}-20V"
    add_var_res = await client.post(f"/api/v1/items/{item_id}/variants", headers=headers, json={
        "variant_sku": v_sku,
        "variant_name": "20V Max Brushless",
        "cost_price": 75.0,
        "selling_price": 149.99,
        "barcodes": [
            {"barcode_value": f"BC-{v_sku}", "symbology": "CODE128", "is_primary": True}
        ]
    })
    assert add_var_res.status_code == 201
    var_data = add_var_res.json()
    var_id = var_data["id"]

    # 2. Update variant
    up_var_res = await client.put(f"/api/v1/items/{item_id}/variants/{var_id}", headers=headers, json={
        "selling_price": 139.99,
        "variant_name": "20V Max Brushless (Discounted)"
    })
    assert up_var_res.status_code == 200
    assert up_var_res.json()["selling_price"] == 139.99

    # 3. Add additional barcode
    add_bc_res = await client.post(f"/api/v1/items/{item_id}/variants/{var_id}/barcodes", headers=headers, json={
        "barcode_value": f"QR-{v_sku}",
        "symbology": "QR"
    })
    assert add_bc_res.status_code == 201
    bc_id = add_bc_res.json()["id"]

    # 4. Delete barcode
    del_bc_res = await client.delete(f"/api/v1/items/{item_id}/variants/{var_id}/barcodes/{bc_id}", headers=headers)
    assert del_bc_res.status_code == 200

    # 5. Delete variant
    del_var_res = await client.delete(f"/api/v1/items/{item_id}/variants/{var_id}", headers=headers)
    assert del_var_res.status_code == 200


@pytest.mark.asyncio
async def test_product_deletion_stock_protection(client: AsyncClient, db_session: AsyncSession):
    """
    Asserts that attempting to delete an item with positive physical stock balance is rejected with HTTP 400.
    """
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Find item with stock (SKU-THM-100 from seed has 120 units)
    items_res = await client.get("/api/v1/items?q=SKU-THM-100", headers=headers)
    thm_item = items_res.json()["items"][0]

    # Attempt to delete
    del_res = await client.delete(f"/api/v1/items/{thm_item['id']}", headers=headers)
    assert del_res.status_code == 400
    assert "active inventory balance" in del_res.json()["detail"]


@pytest.mark.asyncio
async def test_product_search_filtering_sorting_and_pagination(client: AsyncClient):
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Search by name
    search_res = await client.get("/api/v1/items?q=Sensor", headers=headers)
    assert search_res.status_code == 200
    assert len(search_res.json()["items"]) >= 1

    # 2. Filter by status
    in_stock_res = await client.get("/api/v1/items?stock_status=in_stock", headers=headers)
    assert in_stock_res.status_code == 200
    assert all(i["total_stock"] > 0 for i in in_stock_res.json()["items"])

    # 3. Sort by SKU ascending
    sort_res = await client.get("/api/v1/items?sort_by=sku&sort_dir=asc", headers=headers)
    assert sort_res.status_code == 200
    skus = [i["sku"] for i in sort_res.json()["items"]]
    assert skus == sorted(skus)

    # 4. Pagination
    page_res = await client.get("/api/v1/items?page=1&page_size=2", headers=headers)
    assert page_res.status_code == 200
    pag = page_res.json()["pagination"]
    assert pag["page"] == 1
    assert pag["page_size"] == 2
    assert pag["total_items"] >= 3
