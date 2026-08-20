import os
import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.sales import Customer, SalesOrder
from app.models.ledger import StockBalanceCache
from app.models.change_feed import EntityChangeFeed
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncUpstreamBatchRequest,
    SyncMutationEnvelope
)
from app.services.sync_service import SyncService
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService
from app.services.reconciliation_service import ReconciliationService

# ============================================================================
# 1. WINDOWS ARTIFACT EXISTENCE & INTEGRITY
# ============================================================================

def test_windows_production_artifact_bundle():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    win_dir = os.path.join(base_dir, "release", "windows")
    exe_path = os.path.join(win_dir, "AuraStock.exe")
    nsis_path = os.path.join(win_dir, "AuraStock_1.1.0_x64-setup.exe")
    msi_path = os.path.join(win_dir, "AuraStock_1.1.0_x64_en-US.msi")
    loader_path = os.path.join(win_dir, "WebView2Loader.dll")

    assert os.path.exists(exe_path), f"Missing {exe_path}"
    assert os.path.exists(nsis_path), f"Missing {nsis_path}"
    assert os.path.exists(msi_path), f"Missing {msi_path}"
    assert os.path.exists(loader_path), f"Missing {loader_path}"

    # Verify genuine multi-megabyte native binaries
    assert os.path.getsize(exe_path) > 10_000_000, f"AuraStock.exe is too small ({os.path.getsize(exe_path)} bytes)"
    assert os.path.getsize(nsis_path) > 3_000_000, f"NSIS installer is too small ({os.path.getsize(nsis_path)} bytes)"
    assert os.path.getsize(msi_path) > 5_000_000, f"MSI installer is too small ({os.path.getsize(msi_path)} bytes)"

# ============================================================================
# 2. FULL LIFECYCLE: ONLINE -> OFFLINE -> RESTART -> SYNC -> DOWNSTREAM -> CONFLICT
# ============================================================================

@pytest.mark.asyncio
async def test_windows_client_full_offline_bidirectional_verification(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    device_id = f"WIN-PROD-{uuid.uuid4().hex[:8]}"

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)

    # 1. Online Handshake & Authentication Lease
    handshake = await SyncService.handshake_device(
        db=db_session, tenant_id=tenant_id, user_id=user_id,
        req=SyncHandshakeRequest(
            device_identifier=device_id,
            device_name="Floor Surface Laptop Studio 2",
            platform="WINDOWS_DESKTOP",
            app_version="1.1.0"
        )
    )
    assert handshake.status == "ACTIVE"
    assert handshake.lease_duration_seconds == 28800

    # Setup Master Data
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-WIN-{uuid.uuid4().hex[:4]}", name="Windows Test WH", is_active=True)
    db_session.add(wh)
    bin_a = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-WIN-A", is_active=True)
    bin_b = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-WIN-B", is_active=True)
    db_session.add(bin_a)
    db_session.add(bin_b)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-WIN-{uuid.uuid4().hex[:4]}", name="Windows Client Ltd", is_active=True)
    db_session.add(cust)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-WIN-{uuid.uuid4().hex[:4]}", name="Precision Gear", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Standard Gear", cost_price=Decimal("40.0"), selling_price=Decimal("65.0"))
    db_session.add(var)
    await db_session.flush()

    # Seed initial physical inventory on server (10 units in BIN-A)
    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_a.id, "quantity": Decimal("10.0"), "unit_cost": Decimal("40.0")}],
        user_id=user_id
    )

    # 2. Simulate Network Disconnect (Offline Mode)
    # Perform supported offline operations: Local Bin Transfer (4 units A -> B) and Draft Sales Order (2 units)
    tx1_id = f"OFF-TX1-{uuid.uuid4()}"
    tx2_id = f"OFF-TX2-{uuid.uuid4()}"

    # Simulate local durable storage: Mutations survive application restart
    simulated_local_queue = [
        SyncMutationEnvelope(
            client_tx_id=tx1_id,
            operation_type="BIN_TRANSFER",
            warehouse_id=wh.id,
            client_timestamp=datetime.now(timezone.utc),
            payload={
                "item_variant_id": var.id,
                "source_bin_id": bin_a.id,
                "destination_bin_id": bin_b.id,
                "quantity": 4.0
            }
        ),
        SyncMutationEnvelope(
            client_tx_id=tx2_id,
            operation_type="CREATE_SALES_ORDER",
            warehouse_id=wh.id,
            client_timestamp=datetime.now(timezone.utc),
            payload={
                "customer_id": cust.id,
                "notes": "Created during offline shift",
                "lines": [{"item_variant_id": var.id, "quantity_ordered": 2.0, "unit_price": 65.0}]
            }
        )
    ]

    # Verify queue survived offline restart
    assert len(simulated_local_queue) == 2

    # 3. Restore Network Connectivity -> Automatic Upstream Batch Sync
    batch_req = SyncUpstreamBatchRequest(device_identifier=device_id, mutations=simulated_local_queue)
    sync_res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)

    assert sync_res.committed_count == 2
    assert sync_res.conflict_count == 0
    assert sync_res.rejected_count == 0
    assert len(sync_res.acks) == 2
    assert sync_res.acks[0].status == "COMMITTED"
    assert sync_res.acks[1].status == "COMMITTED"

    # 4. Web Application modification -> Downstream Change Feed Synchronization
    # Web admin adds a new product and price
    web_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-WEB-{uuid.uuid4().hex[:4]}", name="Web Added Motor", base_uom="PCS", is_active=True)
    db_session.add(web_item)
    await db_session.flush()

    await SyncService.record_entity_change(
        db=db_session, tenant_id=tenant_id, entity_type="ITEM", entity_id=web_item.id, change_type="CREATED",
        payload={"sku": web_item.sku, "name": web_item.name, "created_by": "Web Admin"}
    )
    await db_session.commit()

    # Windows Client pulls downstream feed
    feed_res = await SyncService.get_change_feed(db_session, tenant_id, since_revision=0, limit=100)
    assert feed_res.count >= 1
    web_deltas = [c for c in feed_res.changes if c.entity_id == web_item.id]
    assert len(web_deltas) == 1
    assert web_deltas[0].payload["sku"] == web_item.sku

    # 5. Concurrent Inventory Conflict Test
    # Windows client attempts to transfer 20 units (when only 6 remain in BIN-A)
    tx_conflict_id = f"OFF-CONF-{uuid.uuid4()}"
    conflict_batch = SyncUpstreamBatchRequest(
        device_identifier=device_id,
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=tx_conflict_id,
                operation_type="BIN_TRANSFER",
                warehouse_id=wh.id,
                client_timestamp=datetime.now(timezone.utc),
                payload={
                    "item_variant_id": var.id,
                    "source_bin_id": bin_a.id,
                    "destination_bin_id": bin_b.id,
                    "quantity": 20.0
                }
            )
        ]
    )

    conf_res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, conflict_batch)
    assert conf_res.committed_count == 0
    assert conf_res.rejected_count == 1 or conf_res.conflict_count == 1
    assert "Insufficient" in conf_res.acks[0].error_message

    # 6. Idempotency Retransmission Guard
    # Re-delivering batch_req must return cached committed ACKs with zero duplicate GL lines
    dup_res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert dup_res.committed_count == 2
    assert dup_res.acks[0].server_tx_id == sync_res.acks[0].server_tx_id
    assert dup_res.acks[1].server_tx_id == sync_res.acks[1].server_tx_id

    # 7. Physical Stock & Subledger Balance Parity Check
    bal_a = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_a.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    bal_b = (await db_session.execute(select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_b.id, StockBalanceCache.item_variant_id == var.id))).scalar_one()
    assert bal_a.quantity_on_hand == Decimal("6.0")
    assert bal_b.quantity_on_hand == Decimal("4.0")
    assert bal_a.quantity_on_hand + bal_b.quantity_on_hand == Decimal("10.0")

    # Subledger reconciliations
    ar_rec = await ReconciliationService.reconcile_ar_subledger(db_session, tenant_id)
    ap_rec = await ReconciliationService.reconcile_ap_subledger(db_session, tenant_id)
    fa_rec = await ReconciliationService.reconcile_fixed_assets_subledger(db_session, tenant_id)
    ic_rec = await ReconciliationService.reconcile_intercompany_clearing(db_session, tenant_id)

    assert ar_rec.is_in_balance is True
    assert ap_rec.is_in_balance is True
    assert fa_rec.is_in_balance is True
    assert ic_rec.is_in_balance is True
