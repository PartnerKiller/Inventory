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
from app.models.change_feed import EntityChangeFeed
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncUpstreamBatchRequest,
    SyncMutationEnvelope
)
from app.services.sync_service import SyncService

# ============================================================================
# 1. CHANGE-FEED RECORDING & STREAMING
# ============================================================================

@pytest.mark.asyncio
async def test_record_entity_change_and_feed_stream(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    item_id = str(uuid.uuid4())

    # 1. Record entity change
    change_entry = await SyncService.record_entity_change(
        db=db_session,
        tenant_id=tenant_id,
        entity_type="ITEM",
        entity_id=item_id,
        change_type="CREATED",
        payload={"sku": "SKU-FEED-001", "name": "Sync Feed Widget", "base_price": 45.0}
    )
    await db_session.commit()

    assert change_entry.revision_id is not None
    assert change_entry.revision_id > 0

    # 2. Query change feed
    feed_res = await SyncService.get_change_feed(
        db=db_session,
        tenant_id=tenant_id,
        since_revision=0,
        limit=50
    )

    assert feed_res.count >= 1
    assert feed_res.current_server_revision >= change_entry.revision_id
    matching_changes = [c for c in feed_res.changes if c.entity_id == item_id]
    assert len(matching_changes) == 1
    assert matching_changes[0].change_type == "CREATED"
    assert matching_changes[0].payload["sku"] == "SKU-FEED-001"

# ============================================================================
# 2. INCREMENTAL CHECKPOINT FILTERING
# ============================================================================

@pytest.mark.asyncio
async def test_bidirectional_incremental_checkpoint(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    # Record 3 changes
    e1 = await SyncService.record_entity_change(db_session, tenant_id, "ITEM", str(uuid.uuid4()), "CREATED", {"v": 1})
    e2 = await SyncService.record_entity_change(db_session, tenant_id, "PRICE", str(uuid.uuid4()), "UPDATED", {"v": 2})
    e3 = await SyncService.record_entity_change(db_session, tenant_id, "CUSTOMER", str(uuid.uuid4()), "CREATED", {"v": 3})
    await db_session.commit()

    # Query with since_revision = e1.revision_id
    feed = await SyncService.get_change_feed(db_session, tenant_id, since_revision=e1.revision_id, limit=50)

    # Must contain e2 and e3, but NOT e1
    rev_ids = [c.revision_id for c in feed.changes]
    assert e1.revision_id not in rev_ids
    assert e2.revision_id in rev_ids
    assert e3.revision_id in rev_ids

# ============================================================================
# 3. END-TO-END BIDIRECTIONAL SYNC LOOP
# ============================================================================

@pytest.mark.asyncio
async def test_end_to_end_bidirectional_sync_loop(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    device_id = f"WIN-DESK-{uuid.uuid4().hex[:8]}"

    # Handshake
    await SyncService.handshake_device(
        db=db_session, tenant_id=tenant_id, user_id=user_id,
        req=SyncHandshakeRequest(device_identifier=device_id, device_name="Desk Sync", platform="WINDOWS_DESKTOP", app_version="1.1.0")
    )

    # Master Data
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-BIDI-{uuid.uuid4().hex[:4]}", name="Bidi WH", is_active=True)
    db_session.add(wh)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-BIDI-{uuid.uuid4().hex[:4]}", name="Bidi Client", is_active=True)
    db_session.add(cust)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-BIDI-{uuid.uuid4().hex[:4]}", name="Bidi Widget", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Std", cost_price=Decimal("20.0"), selling_price=Decimal("35.0"))
    db_session.add(var)
    await db_session.commit()

    # 1. Upstream Offline Upload
    client_tx_id = f"OFF-BIDI-{uuid.uuid4()}"
    batch_req = SyncUpstreamBatchRequest(
        device_identifier=device_id,
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=client_tx_id,
                operation_type="CREATE_SALES_ORDER",
                warehouse_id=wh.id,
                client_timestamp=datetime.now(timezone.utc),
                payload={
                    "customer_id": cust.id,
                    "notes": "Created on offline tablet",
                    "lines": [{"item_variant_id": var.id, "quantity_ordered": 2.0, "unit_price": 35.0}]
                }
            )
        ]
    )

    upstream_res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert upstream_res.committed_count == 1
    assert upstream_res.acks[0].status == "COMMITTED"
    so_id = upstream_res.acks[0].server_tx_id

    # 2. Server records downstream change for other clients
    change = await SyncService.record_entity_change(
        db=db_session,
        tenant_id=tenant_id,
        entity_type="SALES_ORDER",
        entity_id=so_id,
        change_type="CREATED",
        payload={"so_id": so_id, "customer_id": cust.id, "total": 70.0}
    )
    await db_session.commit()

    # 3. Downstream Pull
    downstream_feed = await SyncService.get_change_feed(db_session, tenant_id, since_revision=0, limit=50)
    assert downstream_feed.count >= 1
    so_changes = [c for c in downstream_feed.changes if c.entity_id == so_id]
    assert len(so_changes) == 1
    assert so_changes[0].payload["total"] == 70.0
