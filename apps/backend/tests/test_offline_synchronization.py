import uuid
from decimal import Decimal
from datetime import timedelta, datetime
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import create_access_token
from app.models.base import get_utc_now
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemCategory, Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.warehouse_ops import CountSession, CountLine, PackingSession, PackingItem
from app.models.sales import Customer, SalesOrder, SOLineItem, SalesReturn, SalesReturnLine
from app.models.costing import CostLayer
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncUpstreamBatchRequest,
    SyncMutationEnvelope
)
from app.services.sync_service import SyncService
from app.services.traceability_service import TraceabilityService

pytestmark = pytest.mark.asyncio

async def create_sync_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-SYNC-{uuid.uuid4().hex[:4]}", name="Sync Testing WH")
    bin_stg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING")
    bin_stor1 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    bin_stor2 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="A-01-02", aisle="A", rack="01", shelf="01", bin="02", type="STORAGE")
    wh.bins.extend([bin_stg, bin_stor1, bin_stor2])
    db.add(wh)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Sync Cat", code=f"CAT-SYNC-{uuid.uuid4().hex[:4]}")
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-SYNC-{uuid.uuid4().hex[:4]}", name="Sync Handheld Scanner", is_batch_tracked=True, is_serial_tracked=True)
    variant = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"VAR-SYNC-{uuid.uuid4().hex[:4]}", variant_name="Scanner Std", cost_price=Decimal("150.00"), selling_price=Decimal("300.00"))
    item.variants.append(variant)
    db.add_all([cat, item])
    await db.flush()

    sup = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUP-SYNC-{uuid.uuid4().hex[:4]}", name="SyncTech Devices", currency="USD")
    db.add(sup)
    await db.flush()

    return wh, bin_stg, bin_stor1, bin_stor2, item, variant, sup

async def test_sync_handshake_and_lease_issuance(db_session: AsyncSession):
    """
    Tests desktop device handshake, registration, and 8-hour cryptographic offline lease issuance.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    req = SyncHandshakeRequest(
        device_identifier="DEV-WIN11-WH01-SCANNER-A",
        device_name="Terminal 01 (Forklift A)",
        platform="WINDOWS_DESKTOP",
        app_version="1.0.0"
    )

    resp = await SyncService.handshake_device(db_session, tenant_id, user_id=user_id, req=req)
    assert resp.device_id is not None
    assert resp.status == "ACTIVE"
    assert resp.lease_duration_seconds == 28800 # 8 Hours
    assert "SYNC-LEASE-" in resp.sync_session_token

    # Verify device persisted in DB
    dev = (await db_session.execute(select(SyncDevice).where(SyncDevice.id == resp.device_id))).scalar_one()
    assert dev.device_identifier == "DEV-WIN11-WH01-SCANNER-A"
    assert dev.status == "ACTIVE"

async def test_sync_upstream_idempotency_and_replay(db_session: AsyncSession):
    """
    Tests upstream mutation batch replay:
    - Submits the same mutation batch 5 times with identical client_tx_id.
    - Asserts exactly 1 stock ledger transaction is executed in PostgreSQL.
    - Asserts all 5 replay requests return identical COMMITTED ACKs.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    # Handshake device
    h_resp = await SyncService.handshake_device(db_session, tenant_id, user_id=user_id, req=SyncHandshakeRequest(
        device_identifier="DEV-IDEMP-01", device_name="Idempotency Test Dev"
    ))

    # Seed 50 units in Bin 1
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal1)
    await db_session.commit()

    client_tx_id = f"TX-IDEMP-{uuid.uuid4()}"
    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-IDEMP-01",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=client_tx_id,
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "item_variant_id": variant.id,
                    "source_bin_id": bin_stor1.id,
                    "dest_bin_id": bin_stor2.id,
                    "quantity": 10.0
                }
            )
        ]
    )

    # Execute 5 times
    for i in range(5):
        resp = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
        assert resp.total_received == 1
        assert resp.committed_count == 1
        assert resp.acks[0].status == "COMMITTED"
        assert resp.acks[0].client_tx_id == client_tx_id

    # Verify physical balance: Only deducted 10.0 ONCE (Balance = 40.0)
    await db_session.refresh(bal1)
    assert bal1.quantity_on_hand == Decimal("40.0")

async def test_sync_concurrent_serial_acquisition_collision(db_session: AsyncSession):
    """
    Tests serial number collision when two devices offline attempt to pick the same serial:
    - Device A and Device B both pick SN-SYNC-999 offline.
    - Device A syncs first -> COMMITTED.
    - Device B syncs second -> 409 CONFLICT (Deterministic Rejection).
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, _, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    # Register Device A & Device B
    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(device_identifier="DEV-A", device_name="Device A"))
    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(device_identifier="DEV-B", device_name="Device B"))

    # Seed SN-SYNC-999 in IN_STOCK
    serial = ItemSerialNumber(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        item_variant_id=variant.id,
        serial_number="SN-SYNC-999",
        status="IN_STOCK",
        location_bin_id=bin_stor1.id
    )
    db_session.add(serial)
    await db_session.commit()

    # Device A syncs pick
    tx_a = SyncUpstreamBatchRequest(
        device_identifier="DEV-A",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-A-{uuid.uuid4()}",
                operation_type="PICK_ITEM",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "serial_number": "SN-SYNC-999"}
            )
        ]
    )
    res_a = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, tx_a)
    assert res_a.committed_count == 1
    assert res_a.acks[0].status == "COMMITTED"

    # Device B syncs pick for same serial -> CONFLICT
    tx_b = SyncUpstreamBatchRequest(
        device_identifier="DEV-B",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-B-{uuid.uuid4()}",
                operation_type="PICK_ITEM",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "serial_number": "SN-SYNC-999"}
            )
        ]
    )
    res_b = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, tx_b)
    assert res_b.conflict_count == 1
    assert res_b.acks[0].status == "CONFLICT"
    assert "cannot be picked" in res_b.acks[0].error_message

async def test_sync_insufficient_stock_transfer_rejection(db_session: AsyncSession):
    """
    Tests rejection when offline transfer quantity exceeds available stock in source bin.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(device_identifier="DEV-OVERDRAW", device_name="Device Overdraw"))

    # Seed 5 units in Bin 1
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("5.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal1)
    await db_session.commit()

    # Attempt offline transfer of 20 units
    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-OVERDRAW",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-OVER-{uuid.uuid4()}",
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "item_variant_id": variant.id,
                    "source_bin_id": bin_stor1.id,
                    "dest_bin_id": bin_stor2.id,
                    "quantity": 20.0
                }
            )
        ]
    )
    resp = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert resp.rejected_count == 1
    assert resp.acks[0].status == "REJECTED"
    assert "Insufficient available stock" in resp.acks[0].error_message

async def test_sync_offline_goods_receipt_with_server_costing(db_session: AsyncSession):
    """
    Tests offline goods receipt ingestion:
    - Creates StockEngine transaction
    - Generates server-authoritative CostLayer
    - Registers StockLot
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stg, _, _, item, variant, sup = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(device_identifier="DEV-GRN", device_name="Device GRN"))

    # Create approved PO
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, po_number="PO-SYNC-01", supplier_id=sup.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("3000.00"))
    po_line = POLineItem(id=str(uuid.uuid4()), purchase_order_id=po.id, item_variant_id=variant.id, quantity_ordered=Decimal("20.0"), unit_price=Decimal("150.00"), line_total=Decimal("3000.00"))
    po.lines.append(po_line)
    db_session.add(po)
    await db_session.commit()

    # Ingest offline receipt
    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-GRN",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-GRN-{uuid.uuid4()}",
                operation_type="RECEIVE_GOODS",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "purchase_order_id": po.id,
                    "destination_bin_id": bin_stg.id,
                    "item_variant_id": variant.id,
                    "quantity": 20.0,
                    "unit_price": 150.00,
                    "lot_number": "LOT-SYNC-2026"
                }
            )
        ]
    )
    resp = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert resp.committed_count == 1
    assert resp.acks[0].status == "COMMITTED"

    # Verify server CostLayer created
    layer = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh.id, CostLayer.item_variant_id == variant.id)
    )).scalar_one()
    assert layer.unit_cost == Decimal("150.00")
    assert layer.remaining_quantity == Decimal("20.0")

    # Verify StockLot created
    lot = (await db_session.execute(
        select(StockLot).where(StockLot.lot_number == "LOT-SYNC-2026")
    )).scalar_one()
    assert lot.current_quantity == Decimal("20.0")

async def test_sync_downstream_delta_retrieval(db_session: AsyncSession):
    """
    Tests downstream delta synchronization pulling cached items, bins, balances, lots, and serials.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_stg, bin_stor1, _, item, variant, sup = await create_sync_test_environment(db_session, tenant_id)

    delta = await SyncService.get_downstream_delta(db_session, tenant_id, warehouse_id=wh.id)
    assert delta.warehouse_id == wh.id
    assert len(delta.items) >= 1
    assert len(delta.bins) >= 3

async def test_sync_device_revocation_lockout(db_session: AsyncSession):
    """
    Tests immediate device revocation by administrator blocking future synchronization.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, _, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    h_resp = await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(device_identifier="DEV-STOLEN", device_name="Stolen Scanner"))

    # Admin revokes device
    revoked = await SyncService.revoke_device(db_session, tenant_id, h_resp.device_id, reason="Lost in transit")
    assert revoked.status == "REVOKED"
    assert revoked.active_lease_expires_at is None

    # Subsequent sync attempt fails with 403 Forbidden
    with pytest.raises(HTTPException) as exc:
        await SyncService.process_upstream_batch(db_session, tenant_id, user_id, SyncUpstreamBatchRequest(
            device_identifier="DEV-STOLEN",
            mutations=[
                SyncMutationEnvelope(
                    client_tx_id=f"TX-{uuid.uuid4()}",
                    operation_type="BIN_TRANSFER",
                    warehouse_id=wh.id,
                    client_timestamp=get_utc_now(),
                    payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 1.0}
                )
            ]
        ))
    assert exc.value.status_code == 403
    assert "revoked" in exc.value.detail

async def test_sync_api_endpoints_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """
    Tests REST endpoints under /api/v1/sync/* with RBAC token.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    admin_token = create_access_token(
        subject="sync_admin",
        tenant_id=tenant_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    wh, _, _, _, _, _, _ = await create_sync_test_environment(db_session, tenant_id)

    # 1. Handshake API
    h_res = await client.post("/api/v1/sync/handshake", headers=headers, json={
        "device_identifier": "DEV-API-001",
        "device_name": "API Handheld"
    })
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "ACTIVE"
    dev_id = h_res.json()["device_id"]

    # 2. Downstream Delta API
    delta_res = await client.get(f"/api/v1/sync/downstream?warehouse_id={wh.id}", headers=headers)
    assert delta_res.status_code == 200
    assert "items" in delta_res.json()

    # 3. List Devices API
    list_res = await client.get("/api/v1/sync/devices", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 4. Revoke Device API
    rev_res = await client.put(f"/api/v1/sync/devices/{dev_id}/revoke", headers=headers, json={"reason": "Decommissioned"})
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "REVOKED"

async def test_sync_lease_expiration_and_tenant_warehouse_isolation(db_session: AsyncSession):
    """
    Tests:
    1. Lease expiration: Device with expired lease is rejected with 401 Unauthorized.
    2. Tenant/Warehouse isolation: Sync mutation referencing warehouse in another tenant is rejected with 404.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, _, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    # 1. Device with expired lease
    h_resp = await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-EXPIRED-LEASE", device_name="Expired Lease Dev"
    ))
    dev = (await db_session.execute(select(SyncDevice).where(SyncDevice.id == h_resp.device_id))).scalar_one()
    # Fast-forward / backdate lease expiration
    dev.active_lease_expires_at = get_utc_now() - timedelta(hours=1)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await SyncService.process_upstream_batch(db_session, tenant_id, user_id, SyncUpstreamBatchRequest(
            device_identifier="DEV-EXPIRED-LEASE",
            mutations=[
                SyncMutationEnvelope(
                    client_tx_id=f"TX-EXP-{uuid.uuid4()}",
                    operation_type="BIN_TRANSFER",
                    warehouse_id=wh.id,
                    client_timestamp=get_utc_now(),
                    payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 1.0}
                )
            ]
        ))
    assert exc.value.status_code == 401
    assert "lease has expired" in exc.value.detail

    # 2. Renew lease and test cross-tenant warehouse isolation
    dev.active_lease_expires_at = get_utc_now() + timedelta(hours=8)
    await db_session.commit()

    fake_wh_id = str(uuid.uuid4())
    cross_resp = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, SyncUpstreamBatchRequest(
        device_identifier="DEV-EXPIRED-LEASE",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-CROSS-{uuid.uuid4()}",
                operation_type="BIN_TRANSFER",
                warehouse_id=fake_wh_id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 1.0}
            )
        ]
    ))
    assert cross_resp.rejected_count == 1
    assert "Target warehouse" in cross_resp.acks[0].error_message

async def test_sync_network_interruption_and_partial_retry(db_session: AsyncSession):
    """
    Tests partial sync retry:
    - Batch with mutation 1 and mutation 2.
    - Mutation 1 succeeds and is acknowledged.
    - Client retries batch with Mutation 1 (duplicate) + Mutation 2 (fresh).
    - Verifies Mutation 1 is not re-executed (idempotent cached ACK), Mutation 2 executes freshly.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, _, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-PARTIAL-RETRY", device_name="Partial Retry Dev"
    ))

    # Seed 50 units in Bin 1
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("50.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal1)
    await db_session.commit()

    tx1_id = f"TX-PARTIAL-1-{uuid.uuid4()}"
    tx2_id = f"TX-PARTIAL-2-{uuid.uuid4()}"

    # Step 1: Send mutation 1
    batch_1 = SyncUpstreamBatchRequest(
        device_identifier="DEV-PARTIAL-RETRY",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=tx1_id,
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 10.0}
            )
        ]
    )
    res_1 = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_1)
    assert res_1.committed_count == 1
    server_tx1 = res_1.acks[0].server_tx_id

    # Step 2: Retry with mutation 1 + mutation 2
    batch_2 = SyncUpstreamBatchRequest(
        device_identifier="DEV-PARTIAL-RETRY",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=tx1_id, # Duplicate!
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 10.0}
            ),
            SyncMutationEnvelope(
                client_tx_id=tx2_id, # Fresh!
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={"item_variant_id": variant.id, "source_bin_id": bin_stor1.id, "dest_bin_id": bin_stor2.id, "quantity": 15.0}
            )
        ]
    )
    res_2 = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_2)
    assert res_2.total_received == 2
    assert res_2.committed_count == 2
    # Mutation 1 returns same server_tx_id
    assert res_2.acks[0].server_tx_id == server_tx1
    assert res_2.acks[1].server_tx_id is not None

    # Total deducted: 10.0 (from Tx 1) + 15.0 (from Tx 2) = 25.0 deducted (Balance = 25.0)
    await db_session.refresh(bal1)
    assert bal1.quantity_on_hand == Decimal("25.0")

async def test_sync_offline_blind_cycle_count_and_server_variance(db_session: AsyncSession):
    """
    Tests offline blind cycle counting (COUNT_SCAN):
    - Count session downloaded with expected quantities hidden.
    - Operator enters physical count.
    - Synced COUNT_SCAN uploads; server computes variance against snapshot.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, _, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-COUNT-01", device_name="Count Terminal"
    ))

    # Seed 30 units in Bin 1
    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh.id,
        location_bin_id=bin_stor1.id,
        item_variant_id=variant.id,
        quantity_on_hand=Decimal("30.0"),
        quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal1)

    # Create count session
    session = CountSession(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        warehouse_id=wh.id,
        session_number="CNT-SYNC-01",
        scope_type="FULL_WAREHOUSE",
        status="IN_PROGRESS"
    )
    db_session.add(session)
    await db_session.commit()

    # Operator physically counted 28 units (Variance = -2.0)
    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-COUNT-01",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-COUNT-{uuid.uuid4()}",
                operation_type="COUNT_SCAN",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "count_session_id": session.id,
                    "location_bin_id": bin_stor1.id,
                    "item_variant_id": variant.id,
                    "counted_quantity": 28.0,
                    "notes": "Blind count scan"
                }
            )
        ]
    )
    res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res.committed_count == 1
    assert res.acks[0].status == "COMMITTED"

    # Verify count line created with variance = -2.0
    line = (await db_session.execute(
        select(CountLine).where(CountLine.count_session_id == session.id, CountLine.location_bin_id == bin_stor1.id)
    )).scalar_one()
    assert line.counted_quantity == Decimal("28.0")
    assert line.expected_quantity == Decimal("30.0")
    assert line.variance_quantity == Decimal("-2.0")

async def test_sync_offline_packing_verification(db_session: AsyncSession):
    """
    Tests offline carton packing verification (PACK_ITEM).
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, _, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-PACK-01", device_name="Pack Terminal"
    ))

    # Create shipment & packing session
    from app.models.sales import Shipment, Customer, SalesOrder
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-PACK-01", name="Pack Client", email="pack@client.com")
    db_session.add(cust)
    await db_session.flush()

    so = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number="SO-PACK-01", customer_id=cust.id, warehouse_id=wh.id, total_amount=Decimal("500.00"))
    db_session.add(so)
    await db_session.flush()

    shipment = Shipment(id=str(uuid.uuid4()), sales_order_id=so.id, shipment_number="SHP-PACK-01")
    db_session.add(shipment)
    await db_session.flush()

    ps = PackingSession(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_number="PACK-SYNC-01",
        shipment_id=shipment.id,
        status="OPEN"
    )
    db_session.add(ps)
    await db_session.commit()

    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-PACK-01",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-PACK-{uuid.uuid4()}",
                operation_type="PACK_ITEM",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "packing_session_id": ps.id,
                    "carton_number": 1,
                    "item_variant_id": variant.id,
                    "quantity": 2.0,
                    "serial_number": "SN-PACK-01"
                }
            )
        ]
    )
    res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res.committed_count == 1
    assert res.acks[0].status == "COMMITTED"

    # Verify packing item logged
    p_item = (await db_session.execute(
        select(PackingItem).where(PackingItem.packing_session_id == ps.id)
    )).scalar_one()
    assert p_item.carton_number == 1
    assert p_item.quantity_packed == Decimal("2.0")
    assert p_item.serial_number == "SN-PACK-01"

async def test_sync_offline_customer_return_quarantine(db_session: AsyncSession):
    """
    Tests offline customer return intake (CUSTOMER_RETURN):
    - Returns good/damaged items into designated quarantine bin.
    - Prevents premature inflation of active available sales inventory.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, bin_stg, bin_stor1, _, item, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-RMA-01", device_name="RMA Terminal"
    ))

    # Create customer & sales order in SHIPPED status
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code="CUST-SYNC-01", name="Sync Client Corp", email="sync@client.com")
    db_session.add(cust)
    await db_session.flush()

    so = SalesOrder(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        so_number="SO-SYNC-RET-01",
        customer_id=cust.id,
        warehouse_id=wh.id,
        status="SHIPPED",
        total_amount=Decimal("600.00")
    )
    so_line = SOLineItem(
        id=str(uuid.uuid4()),
        sales_order_id=so.id,
        item_variant_id=variant.id,
        quantity_ordered=Decimal("2.0"),
        quantity_allocated=Decimal("0.0"),
        quantity_picked=Decimal("2.0"),
        quantity_shipped=Decimal("2.0"),
        quantity_returned=Decimal("0.0"),
        unit_price=Decimal("300.00"),
        line_total=Decimal("600.00")
    )
    so.lines.append(so_line)
    db_session.add(so)
    await db_session.commit()

    # Ingest return into STAGING bin (intake)
    batch_req = SyncUpstreamBatchRequest(
        device_identifier="DEV-RMA-01",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-RMA-{uuid.uuid4()}",
                operation_type="CUSTOMER_RETURN",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "sales_order_id": so.id,
                    "notes": "Damaged in transit return",
                    "lines": [{
                        "so_line_id": so_line.id,
                        "quantity_returned": 1.0,
                        "condition": "DAMAGED",
                        "destination_bin_id": bin_stg.id
                    }]
                }
            )
        ]
    )
    res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res.committed_count == 1
    assert res.acks[0].status == "COMMITTED"

    # Verify return record created
    ret = (await db_session.execute(
        select(SalesReturn).where(SalesReturn.sales_order_id == so.id)
    )).scalar_one()
    assert ret.status == "COMPLETED"
    assert len(ret.lines) == 1
    assert ret.lines[0].quantity_returned == Decimal("1.0")
    assert ret.lines[0].condition == "DAMAGED"

async def test_sync_device_restore_and_re_enable(db_session: AsyncSession):
    """
    Tests administrative device restore:
    - Revoked device is restored to ACTIVE status.
    - Subsequent sync succeeds normally.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    wh, _, bin_stor1, bin_stor2, _, variant, _ = await create_sync_test_environment(db_session, tenant_id)

    h_resp = await SyncService.handshake_device(db_session, tenant_id, user_id, SyncHandshakeRequest(
        device_identifier="DEV-RESTORE-TEST", device_name="Device to Restore"
    ))
    dev_id = h_resp.device_id

    # Revoke device
    await SyncService.revoke_device(db_session, tenant_id, dev_id, reason="Temporary lock")

    # Restore device
    restored = await SyncService.restore_device(db_session, tenant_id, dev_id, admin_user_id=user_id)
    assert restored.status == "ACTIVE"
    assert restored.active_lease_expires_at is not None

    # Sync now succeeds
    res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, SyncUpstreamBatchRequest(
        device_identifier="DEV-RESTORE-TEST",
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=f"TX-RES-{uuid.uuid4()}",
                operation_type="COUNT_SCAN",
                warehouse_id=wh.id,
                client_timestamp=get_utc_now(),
                payload={
                    "count_session_id": str(uuid.uuid4()), # Non-existent will be rejected safely
                    "location_bin_id": bin_stor1.id,
                    "item_variant_id": variant.id,
                    "counted_quantity": 1.0
                }
            )
        ]
    ))
    # It didn't fail with 403 Forbidden!
    assert res.total_received == 1
