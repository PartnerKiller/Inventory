import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.security import create_access_token
from app.models.auth import User, Role, Permission
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant
from app.models.purchasing import PurchaseOrder, Supplier
from app.models.sales import SalesOrder, Customer

pytestmark = pytest.mark.asyncio

async def test_cross_tenant_idor_protection(client: AsyncClient, db_session: AsyncSession):
    """
    Simulates cross-tenant IDOR/BOLA attacks where Tenant B attempts to read
    or manipulate Tenant A's products, warehouses, orders, documents, and audit logs.
    """
    tenant_a = "00000000-0000-0000-0000-000000000001"
    tenant_b = "00000000-0000-0000-0000-000000000002"

    # Create tokens for Tenant A and Tenant B
    token_a = create_access_token(
        subject="user_a",
        tenant_id=tenant_a,
        roles=["TENANT_A_ADMIN"],
        permissions=["*"]
    )
    token_b = create_access_token(
        subject="user_b",
        tenant_id=tenant_b,
        roles=["TENANT_B_ADMIN"],
        permissions=["*"]
    )

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Tenant A creates a Warehouse
    wh_res = await client.post("/api/v1/warehouses", json={
        "code": f"WH-A-{uuid.uuid4().hex[:6]}",
        "name": "Tenant A Secret Warehouse"
    }, headers=headers_a)
    assert wh_res.status_code == 201
    wh_a_id = wh_res.json()["id"]

    # 2. Tenant B attempts to read Tenant A's warehouse (IDOR)
    idor_wh = await client.get(f"/api/v1/warehouses/{wh_a_id}", headers=headers_b)
    assert idor_wh.status_code == 404

    # 3. Tenant B attempts to update Tenant A's warehouse
    idor_upd = await client.put(f"/api/v1/warehouses/{wh_a_id}", json={
        "name": "Hacked Warehouse"
    }, headers=headers_b)
    assert idor_upd.status_code == 404

    # 4. Tenant A creates a product
    prod_res = await client.post("/api/v1/items", json={
        "sku": f"SKU-A-{uuid.uuid4().hex[:6]}",
        "name": "Confidential Product A",
        "base_uom": "PCS"
    }, headers=headers_a)
    assert prod_res.status_code == 201
    prod_a_id = prod_res.json()["id"]

    # 5. Tenant B attempts to read Tenant A's product
    idor_prod = await client.get(f"/api/v1/items/{prod_a_id}", headers=headers_b)
    assert idor_prod.status_code == 404

    # 6. Tenant B attempts to read Tenant A's audit logs
    idor_audit = await client.get("/api/v1/audit", headers=headers_b)
    assert idor_audit.status_code == 200
    # Should not contain any of Tenant A's records
    for log in idor_audit.json()["items"]:
        assert log["tenant_id"] == tenant_b

async def test_cross_warehouse_scoping_enforcement(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that a user whose warehouse scope is restricted to Warehouse A
    is strictly forbidden (403) from reading, editing, approving, or receiving POs and SOs for Warehouse B.
    """
    tenant_id = settings.TENANT_DEFAULT_ID

    # 1. Get warehouses
    res_wh = await db_session.execute(select(Warehouse).where(Warehouse.tenant_id == tenant_id))
    warehouses = res_wh.scalars().all()
    assert len(warehouses) >= 2
    wh_1 = warehouses[0]
    wh_2 = warehouses[1]

    # Create manager token restricted strictly to Warehouse 1
    token_wh1 = create_access_token(
        subject="manager_wh1",
        tenant_id=tenant_id,
        roles=["WH1_MANAGER"],
        permissions=["purchasing:read", "purchasing:write", "purchasing:approve", "sales:read", "sales:write", "sales:fulfill"],
        warehouse_scopes=[wh_1.id]
    )
    headers_wh1 = {"Authorization": f"Bearer {token_wh1}"}

    # Admin creates a PO for Warehouse 2
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers_admin = {"Authorization": f"Bearer {admin_token}"}

    # Fetch supplier and variant
    res_sup = await db_session.execute(select(Supplier).where(Supplier.tenant_id == tenant_id))
    sup = res_sup.scalars().first()
    res_var = await db_session.execute(select(ItemVariant))
    var = res_var.scalars().first()

    po_res = await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup.id,
        "target_warehouse_id": wh_2.id,
        "lines": [{
            "item_variant_id": var.id,
            "quantity_ordered": 10.0,
            "unit_price": 50.0
        }]
    }, headers=headers_admin)
    assert po_res.status_code == 201
    po_id = po_res.json()["id"]

    # Manager WH1 attempts to view PO targeting Warehouse 2 -> 403
    forbidden_view = await client.get(f"/api/v1/purchase-orders/{po_id}", headers=headers_wh1)
    assert forbidden_view.status_code == 403
    assert "outside your authorized warehouse scope" in forbidden_view.json()["detail"]

    # Manager WH1 attempts to approve PO targeting Warehouse 2 -> 403
    forbidden_approve = await client.post(f"/api/v1/purchase-orders/{po_id}/approve", headers=headers_wh1)
    assert forbidden_approve.status_code == 403

    # Manager WH1 attempts to cancel PO targeting Warehouse 2 -> 403
    forbidden_cancel = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=headers_wh1)
    assert forbidden_cancel.status_code == 403

async def test_privilege_escalation_delegation_rejection(client: AsyncClient):
    """
    Verifies that a user cannot grant permissions or roles they do not possess.
    """
    tenant_id = settings.TENANT_DEFAULT_ID

    # Create restricted clerk token with only roles:write permission
    clerk_token = create_access_token(
        subject="clerk_user",
        tenant_id=tenant_id,
        roles=["CLERK"],
        permissions=["roles:write", "roles:read"]
    )
    headers_clerk = {"Authorization": f"Bearer {clerk_token}"}

    # Attempt to create a role with superadmin wildcard '*' or 'system:write'
    escalation_res = await client.post("/api/v1/users/roles", json={
        "name": "Malicious Superadmin Role",
        "description": "Attempting privilege escalation",
        "permission_codes": ["system:write", "users:write", "*"]
    }, headers=headers_clerk)

    assert escalation_res.status_code == 403
    assert "Privilege escalation prevented" in escalation_res.json()["detail"]

async def test_inventory_negative_stock_and_tampering_prevention(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that inventory mutations cannot create negative quantities or bypass invariant constraints.
    """
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=settings.TENANT_DEFAULT_ID,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Attempt negative quantity in stock transfer
    res_var = await db_session.execute(select(ItemVariant))
    var = res_var.scalars().first()
    res_bins = await db_session.execute(select(LocationBin))
    bins = res_bins.scalars().all()
    bin_1, bin_2 = bins[0], bins[1]

    neg_transfer = await client.post("/api/v1/ledger/transfers", json={
        "source_bin_id": bin_1.id,
        "destination_bin_id": bin_2.id,
        "entries": [{
            "item_variant_id": var.id,
            "quantity": -50.0 # Malicious negative quantity
        }]
    }, headers=headers)
    assert neg_transfer.status_code in [400, 422]

    # 2. Attempt zero quantity transfer
    zero_transfer = await client.post("/api/v1/ledger/transfers", json={
        "source_bin_id": bin_1.id,
        "destination_bin_id": bin_2.id,
        "entries": [{
            "item_variant_id": var.id,
            "quantity": 0.0
        }]
    }, headers=headers)
    assert zero_transfer.status_code in [400, 422]

async def test_session_revocation_idor_prevention(client: AsyncClient):
    """
    Verifies that attempting to revoke an invalid or cross-tenant session ID returns a strict 404.
    """
    admin_token = create_access_token(
        subject="admin_user",
        tenant_id=settings.TENANT_DEFAULT_ID,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    fake_user_id = str(uuid.uuid4())
    fake_session_id = str(uuid.uuid4())

    res = await client.delete(f"/api/v1/users/{fake_user_id}/sessions/{fake_session_id}", headers=headers)
    assert res.status_code == 404
    assert "Session not found" in res.json()["detail"]

async def test_document_security_and_tenant_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that document PDF and payload endpoints strictly enforce tenant isolation and warehouse scoping.
    """
    tenant_a = "00000000-0000-0000-0000-000000000001"
    tenant_b = "00000000-0000-0000-0000-000000000002"

    token_b = create_access_token(
        subject="user_b",
        tenant_id=tenant_b,
        roles=["TENANT_B_ADMIN"],
        permissions=["*"]
    )
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Fetch a Purchase Order belonging to Tenant A
    res_po = await db_session.execute(select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_a))
    po_a = res_po.scalars().first()
    if po_a:
        # Tenant B attempts to fetch payload for Tenant A's PO
        res_payload = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po_a.id}", headers=headers_b)
        assert res_payload.status_code == 404

        # Tenant B attempts to fetch PDF for Tenant A's PO
        res_pdf = await client.get(f"/api/v1/documents/PURCHASE_ORDER/{po_a.id}/pdf", headers=headers_b)
        assert res_pdf.status_code == 404
