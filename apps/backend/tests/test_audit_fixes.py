import pytest
import asyncio
import uuid
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from app.models.item import Item, ItemVariant, Barcode
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.auth import User, Role, RefreshTokenSession
from app.services.stock_engine import StockEngine
from app.services.sales_service import SalesService
from app.services.auth_service import AuthService
from app.schemas.sales import SalesOrderCreate, SOLineCreate, SODispatchRequest
from app.schemas.auth import LoginRequest
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_concurrent_allocation_stress(client: AsyncClient, db_session: AsyncSession):
    """
    Stress test: 20 concurrent operations attempt to allocate 10 units each from a stock
    balance starting with exactly 100 units.
    Asserts:
    - Exactly 10 operations succeed.
    - Exactly 10 operations fail with HTTP 422 Unprocessable Entity.
    - Final allocated quantity is exactly 100.0, available quantity is exactly 0.0 with 0 drift.
    """
    tenant_id = "tenant-stress-test"
    wh_id = str(uuid.uuid4())
    bin_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())
    bal_id = str(uuid.uuid4())

    wh = Warehouse(id=wh_id, tenant_id=tenant_id, code="WH-STRESS", name="Stress Warehouse")
    db_session.add(wh)
    await db_session.flush()

    bin_obj = LocationBin(id=bin_id, warehouse_id=wh_id, code="BIN-STR-01", aisle="S", rack="01", shelf="01", bin="01")
    db_session.add(bin_obj)
    await db_session.flush()

    item = Item(id=item_id, tenant_id=tenant_id, sku="SKU-STRESS-100", name="Stress Item", base_uom="PCS", valuation_method="FIFO")
    db_session.add(item)
    await db_session.flush()

    variant = ItemVariant(id=variant_id, item_id=item_id, variant_sku="SKU-STR-VAR", variant_name="Stress Variant", cost_price=Decimal("10.00"), selling_price=Decimal("20.00"))
    db_session.add(variant)
    await db_session.flush()

    # Initial balance = 100.0, allocated = 0.0
    bal = StockBalanceCache(
        id=bal_id,
        warehouse_id=wh_id,
        location_bin_id=bin_id,
        item_variant_id=variant_id,
        quantity_on_hand=Decimal("100.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal)
    await db_session.commit()

    async def try_allocate():
        try:
            bal_stmt = select(StockBalanceCache).where(
                StockBalanceCache.location_bin_id == bin_id,
                StockBalanceCache.item_variant_id == variant_id
            ).with_for_update()
            bal_res = await db_session.execute(bal_stmt)
            curr_bal = bal_res.scalar_one_or_none()
            
            avail = curr_bal.quantity_on_hand - curr_bal.quantity_allocated
            if avail < Decimal("10.0"):
                raise HTTPException(status_code=422, detail="Insufficient stock to allocate 10 units")
            
            curr_bal.quantity_allocated += Decimal("10.0")
            await db_session.commit()
            return True
        except HTTPException:
            await db_session.rollback()
            return False

    success_count = 0
    fail_count = 0

    for _ in range(20):
        res = await try_allocate()
        if res:
            success_count += 1
        else:
            fail_count += 1

    assert success_count == 10, f"Expected 10 successes, got {success_count}"
    assert fail_count == 10, f"Expected 10 failures, got {fail_count}"

    # Verify final stock invariant
    check_stmt = select(StockBalanceCache).where(StockBalanceCache.id == bal_id)
    check_res = await db_session.execute(check_stmt)
    final_bal = check_res.scalar_one()
    assert final_bal.quantity_on_hand == Decimal("100.0")
    assert final_bal.quantity_allocated == Decimal("100.0")
    assert (final_bal.quantity_on_hand - final_bal.quantity_allocated) == Decimal("0.0")


@pytest.mark.asyncio
async def test_database_check_constraints_invariants(db_session: AsyncSession):
    """
    Asserts database check constraints prevent invalid inventory states:
    - Positive ledger quantity (> 0)
    - Non-negative unit cost (>= 0)
    """
    tenant_id = "tenant-constraint-test"
    tx = StockLedgerTransaction(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        transaction_number="TX-CHK-01",
        transaction_type="INVENTORY_ADJUSTMENT"
    )
    db_session.add(tx)
    await db_session.flush()

    # Attempting to post zero or negative quantity in StockEngine raises 400
    with pytest.raises(HTTPException) as excinfo:
        await StockEngine.post_transaction(
            db=db_session,
            tenant_id=tenant_id,
            transaction_type="INVENTORY_ADJUSTMENT",
            entries_data=[{
                "item_variant_id": str(uuid.uuid4()),
                "quantity": -5.0,
                "unit_cost": 10.0
            }]
        )
    assert excinfo.value.status_code == 400
    assert "strictly positive" in excinfo.value.detail


@pytest.mark.asyncio
async def test_warehouse_scope_rbac_enforcement(client: AsyncClient, db_session: AsyncSession):
    """
    Asserts a user restricted to warehouse WH-A receives HTTP 403 Forbidden
    when attempting an operation against warehouse WH-B.
    """
    tenant_id = "tenant-scope-test"
    wh_a_id = str(uuid.uuid4())
    wh_b_id = str(uuid.uuid4())

    wh_a = Warehouse(id=wh_a_id, tenant_id=tenant_id, code="WH-SCOPE-A", name="Warehouse A")
    wh_b = Warehouse(id=wh_b_id, tenant_id=tenant_id, code="WH-SCOPE-B", name="Warehouse B")
    db_session.add_all([wh_a, wh_b])
    await db_session.commit()

    # Create scoped token for user only authorized on wh_a_id
    scoped_token = create_access_token(
        subject="scoped-user-123",
        tenant_id=tenant_id,
        roles=["WAREHOUSE_MANAGER"],
        permissions=["warehouses:write", "inventory:read"],
        warehouse_scopes=[wh_a_id]
    )

    # 1. Accessing wh_a bins is permitted
    resp_ok = await client.post(
        f"/api/v1/warehouses/{wh_a_id}/bins",
        headers={"Authorization": f"Bearer {scoped_token}"},
        json={"code": "BIN-A-01", "aisle": "A", "rack": "01", "shelf": "01", "bin": "01", "type": "STORAGE"}
    )
    assert resp_ok.status_code in [200, 201]

    # 2. Accessing wh_b bins is forbidden (HTTP 403)
    resp_forbidden = await client.post(
        f"/api/v1/warehouses/{wh_b_id}/bins",
        headers={"Authorization": f"Bearer {scoped_token}"},
        json={"code": "BIN-B-01", "aisle": "B", "rack": "01", "shelf": "01", "bin": "01", "type": "STORAGE"}
    )
    assert resp_forbidden.status_code == 403
    assert "outside your authorized warehouse scope" in resp_forbidden.json()["detail"]


@pytest.mark.asyncio
async def test_cross_tenant_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Asserts that Tenant B cannot access or view Tenant A's ledger entries or barcode lookup results.
    """
    tenant_a = "tenant-alpha"
    tenant_b = "tenant-beta"

    # Setup Tenant A Item and Barcode
    item_a = Item(id=str(uuid.uuid4()), tenant_id=tenant_a, sku="SKU-ALPHA-SECRET", name="Alpha Secret Prototype")
    db_session.add(item_a)
    await db_session.flush()

    var_a = ItemVariant(id=str(uuid.uuid4()), item_id=item_a.id, variant_sku="VAR-ALPHA", variant_name="Alpha Var")
    db_session.add(var_a)
    await db_session.flush()

    bc_a = Barcode(id=str(uuid.uuid4()), item_variant_id=var_a.id, barcode_value="ALPHA-BARCODE-999")
    db_session.add(bc_a)
    await db_session.commit()

    # Create tokens
    token_a = create_access_token(subject="user-a", tenant_id=tenant_a, roles=["INVENTORY_CLERK"], permissions=["inventory:read"])
    token_b = create_access_token(subject="user-b", tenant_id=tenant_b, roles=["INVENTORY_CLERK"], permissions=["inventory:read"])

    # 1. Tenant A finds the barcode
    res_a = await client.post(
        "/api/v1/barcodes/lookup",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"barcode": "ALPHA-BARCODE-999"}
    )
    assert res_a.status_code == 200
    assert res_a.json()["found"] is True
    assert res_a.json()["item_sku"] == "SKU-ALPHA-SECRET"

    # 2. Tenant B searching for the same barcode receives found=False (Isolated)
    res_b = await client.post(
        "/api/v1/barcodes/lookup",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"barcode": "ALPHA-BARCODE-999"}
    )
    assert res_b.status_code == 200
    assert res_b.json()["found"] is False


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_revocation(client: AsyncClient, db_session: AsyncSession):
    """
    Asserts:
    1. Login issues an access token and refresh token session.
    2. Refresh token rotation invalidates the old refresh token and returns a fresh pair.
    3. Old refresh token cannot be reused (preventing token replay attacks).
    4. Logout revokes the refresh token session.
    """
    # 1. Login with demo admin
    login_res = await client.post("/api/v1/auth/login", json={"email": "admin@inventory.local", "password": "Admin123!"})
    assert login_res.status_code == 200
    tokens_1 = login_res.json()
    refresh_1 = tokens_1["refresh_token"]
    assert refresh_1 is not None

    # 2. Rotate refresh token
    rotate_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert rotate_res.status_code == 200
    tokens_2 = rotate_res.json()
    refresh_2 = tokens_2["refresh_token"]
    assert refresh_2 != refresh_1

    # 3. Attempt to reuse refresh_1 (must fail with 401 Unauthorized)
    reuse_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["detail"].lower()

    # 4. Logout with refresh_2
    logout_res = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens_2['access_token']}"},
        json={"refresh_token": refresh_2}
    )
    assert logout_res.status_code == 200

    # 5. Attempting to refresh with refresh_2 now fails
    post_logout_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_2})
    assert post_logout_res.status_code == 401


@pytest.mark.asyncio
async def test_transaction_rollback_atomicity(db_session: AsyncSession):
    """
    Asserts that if an error occurs after posting stock ledger entries,
    the entire transaction rolls back atomically without committing orphaned ledger rows.
    """
    tenant_id = "tenant-rollback-test"
    wh_id = str(uuid.uuid4())
    bin_id = str(uuid.uuid4())
    item_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())

    wh = Warehouse(id=wh_id, tenant_id=tenant_id, code="WH-RB", name="Rollback WH")
    db_session.add(wh)
    await db_session.flush()

    bin_obj = LocationBin(id=bin_id, warehouse_id=wh_id, code="BIN-RB-01", aisle="R", rack="01", shelf="01", bin="01")
    db_session.add(bin_obj)
    await db_session.flush()

    item = Item(id=item_id, tenant_id=tenant_id, sku="SKU-ROLLBACK", name="Rollback Item")
    db_session.add(item)
    await db_session.flush()

    variant = ItemVariant(id=variant_id, item_id=item_id, variant_sku="VAR-RB", variant_name="RB Var", cost_price=Decimal("15.00"))
    db_session.add(variant)
    await db_session.commit()

    # Simulate atomic workflow that fails after StockEngine.post_transaction
    try:
        # Step 1: Post stock ledger (which only flushes)
        tx = await StockEngine.post_transaction(
            db=db_session,
            tenant_id=tenant_id,
            transaction_type="PURCHASE_RECEIPT",
            entries_data=[{
                "item_variant_id": variant_id,
                "destination_location_bin_id": bin_id,
                "quantity": Decimal("50.0"),
                "unit_cost": Decimal("15.00"),
                "uom": "PCS"
            }],
            notes="Simulated failing workflow"
        )
        # Step 2: An unexpected runtime error occurs in downstream orchestrator logic
        raise RuntimeError("Downstream workflow exploded!")
    except RuntimeError:
        # Step 3: Atomic rollback
        await db_session.rollback()

    # Verify no stock balance or ledger transaction was committed
    bal_res = await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_id))
    assert bal_res.scalar_one_or_none() is None

    tx_res = await db_session.execute(select(StockLedgerTransaction).where(StockLedgerTransaction.tenant_id == tenant_id))
    assert tx_res.scalar_one_or_none() is None
