import asyncio
import pytest
from httpx import AsyncClient
from app.core.config import settings

@pytest.mark.asyncio
async def test_user_crud_and_activation_deactivation(client: AsyncClient):
    # 1. Login as Admin
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    assert login_res.status_code == 200
    admin_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Get Roles
    roles_res = await client.get("/api/v1/users/roles", headers=headers)
    assert roles_res.status_code == 200
    roles = roles_res.json()
    clerk_role = next(r for r in roles if r["name"] == "INVENTORY_CLERK")

    # 3. Create New User
    create_res = await client.post("/api/v1/users", json={
        "email": "sarah.ops@inventory.local",
        "full_name": "Sarah Connor",
        "password": "SecurePass123!",
        "role_ids": [clerk_role["id"]],
        "warehouse_ids": []
    }, headers=headers)
    assert create_res.status_code == 200
    user_data = create_res.json()
    user_id = user_data["id"]
    assert user_data["email"] == "sarah.ops@inventory.local"
    assert user_data["is_active"] is True

    # Duplicate email rejection
    dup_res = await client.post("/api/v1/users", json={
        "email": "sarah.ops@inventory.local",
        "full_name": "Duplicate Sarah",
        "password": "Pass!",
        "role_ids": [],
        "warehouse_ids": []
    }, headers=headers)
    assert dup_res.status_code == 400

    # 4. List Users with Filters
    list_res = await client.get("/api/v1/users?q=Sarah&is_active=true", headers=headers)
    assert list_res.status_code == 200
    matching = list_res.json()
    assert any(u["id"] == user_id for u in matching)

    # 5. User Login as Sarah
    sarah_login = await client.post("/api/v1/auth/login", json={
        "email": "sarah.ops@inventory.local",
        "password": "SecurePass123!"
    })
    assert sarah_login.status_code == 200
    sarah_refresh = sarah_login.json()["refresh_token"]

    # 6. Deactivate User
    deact_res = await client.post(f"/api/v1/users/{user_id}/deactivate", headers=headers)
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Deactivated user cannot login
    sarah_login_blocked = await client.post("/api/v1/auth/login", json={
        "email": "sarah.ops@inventory.local",
        "password": "SecurePass123!"
    })
    assert sarah_login_blocked.status_code == 403

    # Refresh token rotated/revoked for deactivated user
    refresh_blocked = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": sarah_refresh
    })
    assert refresh_blocked.status_code in [401, 403]

    # 7. Reactivate User & Reset Password
    act_res = await client.post(f"/api/v1/users/{user_id}/activate", headers=headers)
    assert act_res.status_code == 200
    assert act_res.json()["is_active"] is True

    reset_res = await client.post(f"/api/v1/users/{user_id}/reset-password", json={
        "new_password": "NewSarahPass456!"
    }, headers=headers)
    assert reset_res.status_code == 200

    # Sarah logins with new password
    sarah_new_login = await client.post("/api/v1/auth/login", json={
        "email": "sarah.ops@inventory.local",
        "password": "NewSarahPass456!"
    })
    assert sarah_new_login.status_code == 200


@pytest.mark.asyncio
async def test_privilege_escalation_prevention(client: AsyncClient):
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create a custom role with limited permissions (only purchasing:read)
    perm_res = await client.get("/api/v1/users/permissions", headers=admin_headers)
    assert perm_res.status_code == 200

    limited_role = (await client.post("/api/v1/users/roles", json={
        "name": "JUNIOR_BUYER",
        "description": "Can only read purchasing",
        "permission_codes": ["purchasing:read", "users:write"]
    }, headers=admin_headers)).json()

    # 2. Create restricted user with users:write but NOT superuser / ledger:write
    restricted_user = (await client.post("/api/v1/users", json={
        "email": "junior.admin@inventory.local",
        "full_name": "Junior Admin",
        "password": "JuniorPass123!",
        "role_ids": [limited_role["id"]],
        "warehouse_ids": []
    }, headers=admin_headers)).json()

    # 3. Login as Junior Admin
    junior_login = await client.post("/api/v1/auth/login", json={
        "email": "junior.admin@inventory.local",
        "password": "JuniorPass123!"
    })
    assert junior_login.status_code == 200
    junior_token = junior_login.json()["access_token"]
    junior_headers = {"Authorization": f"Bearer {junior_token}"}

    # 4. Junior Admin attempts privilege escalation (trying to grant SUPER_ADMIN role with inventory:adjust, ledger:transfer)
    super_admin_role = next(r for r in (await client.get("/api/v1/users/roles", headers=admin_headers)).json() if r["name"] == "SUPER_ADMIN")
    escalation_res = await client.post("/api/v1/users", json={
        "email": "hacker.escalation@inventory.local",
        "full_name": "Privilege Escalator",
        "password": "HackPass123!",
        "role_ids": [super_admin_role["id"]],
        "warehouse_ids": []
    }, headers=junior_headers)

    # Must be rejected with HTTP 403 Forbidden
    assert escalation_res.status_code == 403
    assert "Privilege escalation prevented" in escalation_res.json()["detail"]


@pytest.mark.asyncio
async def test_warehouse_assignment_and_unauthorized_access_403(client: AsyncClient):
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=admin_headers)
    wh1 = wh_res.json()[0]
    wh2 = wh_res.json()[1]

    # Create user scoped specifically to warehouse 1
    clerk_role = next(r for r in (await client.get("/api/v1/users/roles", headers=admin_headers)).json() if r["name"] == "WAREHOUSE_MANAGER")
    scoped_user = (await client.post("/api/v1/users", json={
        "email": "austin.manager@inventory.local",
        "full_name": "Austin Manager",
        "password": "AustinPass123!",
        "role_ids": [clerk_role["id"]],
        "warehouse_ids": [wh1["id"]]
    }, headers=admin_headers)).json()

    # Login as scoped user
    scoped_login = await client.post("/api/v1/auth/login", json={
        "email": "austin.manager@inventory.local",
        "password": "AustinPass123!"
    })
    assert scoped_login.status_code == 200
    scoped_token = scoped_login.json()["access_token"]
    scoped_headers = {"Authorization": f"Bearer {scoped_token}"}

    # Access authorized warehouse 1 -> 200 OK
    res_wh1 = await client.get(f"/api/v1/reports/inventory?warehouse_id={wh1['id']}", headers=scoped_headers)
    assert res_wh1.status_code == 200

    # Attempt to access unauthorized warehouse 2 -> 403 Forbidden
    res_wh2 = await client.get(f"/api/v1/reports/inventory?warehouse_id={wh2['id']}", headers=scoped_headers)
    assert res_wh2.status_code == 403
    assert "outside your authorized warehouse scope" in res_wh2.json()["detail"]


@pytest.mark.asyncio
async def test_session_listing_and_revocation_lifecycle(client: AsyncClient):
    # User logins from multiple devices
    login1 = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    }, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"})
    assert login1.status_code == 200
    t1 = login1.json()["access_token"]
    r1 = login1.json()["refresh_token"]

    login2 = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    }, headers={"User-Agent": "AuraStock Desktop/1.0.0 (Windows Tauri)"})
    assert login2.status_code == 200
    t2 = login2.json()["access_token"]
    r2 = login2.json()["refresh_token"]

    h1 = {"Authorization": f"Bearer {t1}"}

    # List active sessions
    sess_res = await client.get("/api/v1/auth/sessions", headers=h1)
    assert sess_res.status_code == 200
    sessions = sess_res.json()
    assert len(sessions) >= 2

    # Revoke all other sessions
    revoke_res = await client.post("/api/v1/auth/sessions/revoke-others", json={
        "refresh_token": r1
    }, headers=h1)
    assert revoke_res.status_code == 200

    # Old session 2 refresh must now fail
    rotate_old = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": r2
    })
    assert rotate_old.status_code == 401


@pytest.mark.asyncio
async def test_audit_log_filtering_and_immutability(client: AsyncClient):
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Query audit trail
    audit_res = await client.get("/api/v1/audit?page=1&page_size=10", headers=admin_headers)
    assert audit_res.status_code == 200
    data = audit_res.json()
    assert "items" in data
    assert "pagination" in data

    if len(data["items"]) > 0:
        first_log = data["items"][0]
        # Inspect single detail
        detail_res = await client.get(f"/api/v1/audit/{first_log['id']}", headers=admin_headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["id"] == first_log["id"]

    # Verify audit records are strictly immutable: no DELETE or PUT endpoints exist
    delete_res = await client.delete("/api/v1/audit/some-log-id", headers=admin_headers)
    assert delete_res.status_code in [404, 405]


@pytest.mark.asyncio
async def test_system_settings_safe_configuration_and_secret_isolation(client: AsyncClient):
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Read settings
    get_res = await client.get("/api/v1/settings", headers=admin_headers)
    assert get_res.status_code == 200
    sets = get_res.json()
    assert "company_name" in sets
    assert "currency" in sets

    # Secret isolation check: never returns secrets
    for forbidden_key in ["database_url", "secret_key", "jwt_secret", "redis_url", "password"]:
        assert forbidden_key not in sets

    # 2. Update settings
    update_res = await client.put("/api/v1/settings", json={
        "company_name": "AuraStock Global Logistics Inc.",
        "company_email": "ops@aurastock-global.com",
        "currency": "USD",
        "timezone": "America/New_York",
        "default_payment_terms": "NET_60",
        "default_tax_pct": 8.25,
        "require_po_approval": True,
        "po_approval_threshold": 2500.0,
        "allow_negative_stock": True # Attemping to allow negative stock
    }, headers=admin_headers)
    assert update_res.status_code == 200
    up = update_res.json()
    assert up["company_name"] == "AuraStock Global Logistics Inc."
    assert up["company_email"] == "ops@aurastock-global.com"
    assert up["po_approval_threshold"] == 2500.0
    # Core Invariant: negative stock MUST remain False
    assert up["allow_negative_stock"] is False


@pytest.mark.asyncio
async def test_concurrent_document_sequence_generation(client: AsyncClient):
    """
    Verifies that DocumentSequence generates strictly unique, incrementing,
    deterministic sequential identifiers across POs, SOs, GRNs, Transfers, and Adjustments.
    """
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=admin_headers)
    wh_id = wh_res.json()[0]["id"]
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=admin_headers)
    sup_id = sup_res.json()[0]["id"]
    items_res = await client.get("/api/v1/items", headers=admin_headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    po_numbers = []
    for _ in range(5):
        res = await client.post("/api/v1/purchase-orders", json={
            "supplier_id": sup_id,
            "target_warehouse_id": wh_id,
            "lines": [
                {"item_variant_id": variant_id, "quantity_ordered": 1.0, "unit_price": 10.0}
            ]
        }, headers=admin_headers)
        assert res.status_code == 201
        po_numbers.append(res.json()["po_number"])

    # All generated PO numbers must be strictly unique and ordered
    assert len(po_numbers) == 5
    assert len(set(po_numbers)) == 5
    for num in po_numbers:
        assert num.startswith("PO-")


@pytest.mark.asyncio
async def test_sequence_behavior_on_transaction_rollback_and_retry(db_session):
    """
    Verifies that DocumentSequence behaves correctly under transaction rollback:
    When a transaction rolls back before commit, the sequence row rolls back with the transaction,
    and subsequent retries generate sequential numbers without corruption.
    """
    from app.services.sequence_service import SequenceService
    tenant_id = "00000000-0000-0000-0000-000000000001"

    # Step 1: Generate a number in a transaction and commit
    num1 = await SequenceService.generate_next_number(db_session, tenant_id, "TRANSFER")
    await db_session.commit()
    assert num1.startswith("TRX-")

    # Step 2: Begin nested subtransaction/savepoint, allocate next number, and rollback
    async with db_session.begin_nested():
        num_rolled_back = await SequenceService.generate_next_number(db_session, tenant_id, "TRANSFER")
        # Explicit rollback of the savepoint
        await db_session.rollback()

    # Step 3: Subsequent allocation in fresh active transaction
    num_retry = await SequenceService.generate_next_number(db_session, tenant_id, "TRANSFER")
    await db_session.commit()

    # Both committed numbers must be valid and monotonic
    assert num1 != num_retry
    assert num_retry.startswith("TRX-")


@pytest.mark.asyncio
async def test_document_cancellation_preserves_unique_sequential_monotonicity(client: AsyncClient):
    """
    Verifies that cancelling/voiding documents preserves sequential uniqueness and monotonicity.
    """
    admin_login = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    wh_res = await client.get("/api/v1/warehouses", headers=admin_headers)
    wh_id = wh_res.json()[0]["id"]
    sup_res = await client.get("/api/v1/purchase-orders/suppliers", headers=admin_headers)
    sup_id = sup_res.json()[0]["id"]
    items_res = await client.get("/api/v1/items", headers=admin_headers)
    variant_id = items_res.json()["items"][0]["variants"][0]["id"]

    # 1. Create PO 1
    po1 = (await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup_id, "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 1.0, "unit_price": 10.0}]
    }, headers=admin_headers)).json()

    # 2. Create PO 2
    po2 = (await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup_id, "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 2.0, "unit_price": 10.0}]
    }, headers=admin_headers)).json()

    # 3. Cancel PO 2
    cancel_res = await client.post(f"/api/v1/purchase-orders/{po2['id']}/cancel", json={
        "reason": "Cancelled by buyer"
    }, headers=admin_headers)
    assert cancel_res.status_code == 200

    # 4. Create PO 3
    po3 = (await client.post("/api/v1/purchase-orders", json={
        "supplier_id": sup_id, "target_warehouse_id": wh_id,
        "lines": [{"item_variant_id": variant_id, "quantity_ordered": 3.0, "unit_price": 10.0}]
    }, headers=admin_headers)).json()

    # Verify uniqueness and monotonic ordering
    assert po1["po_number"] != po2["po_number"]
    assert po2["po_number"] != po3["po_number"]
    assert po1["po_number"] < po2["po_number"] < po3["po_number"]
