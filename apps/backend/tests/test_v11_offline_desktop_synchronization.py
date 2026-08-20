import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.sales import Customer, SalesOrder
from app.models.maintenance import MaintenanceSchedule, MaintenanceWorkOrder, MWOSparePart
from app.models.fixed_asset import FixedAssetClass, FixedAsset
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncUpstreamBatchRequest,
    SyncMutationEnvelope
)
from app.services.sync_service import SyncService
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService

# ============================================================================
# 1. OFFLINE HANDSHAKE & LEASE ISSUANCE
# ============================================================================

@pytest.mark.asyncio
async def test_offline_handshake_lease_issuance(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    device_id = f"WIN-DESK-{uuid.uuid4().hex[:8]}"

    handshake_res = await SyncService.handshake_device(
        db=db_session,
        tenant_id=tenant_id,
        user_id=user_id,
        req=SyncHandshakeRequest(
            device_identifier=device_id,
            device_name="Warehouse Surface Pro 11",
            platform="WINDOWS_DESKTOP",
            app_version="1.1.0"
        )
    )

    assert handshake_res.status == "ACTIVE"
    assert handshake_res.lease_duration_seconds == 28800 # 8 hours
    assert handshake_res.lease_expires_at > datetime.now(timezone.utc)
    assert handshake_res.sync_session_token.startswith("SYNC-LEASE-")

# ============================================================================
# 2. OFFLINE SALES ORDER CREATION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_offline_sales_order_and_idempotent_retransmission(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    device_id = f"WIN-DESK-{uuid.uuid4().hex[:8]}"

    # Setup device
    await SyncService.handshake_device(
        db=db_session, tenant_id=tenant_id, user_id=user_id,
        req=SyncHandshakeRequest(device_identifier=device_id, device_name="Desk 1", platform="WINDOWS_DESKTOP", app_version="1.1.0")
    )

    # Setup master data
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-OFF-{uuid.uuid4().hex[:4]}", name="Offline WH", is_active=True)
    db_session.add(wh)
    cust = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-OFF-{uuid.uuid4().hex[:4]}", name="Offline Client", is_active=True)
    db_session.add(cust)
    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-OFF-{uuid.uuid4().hex[:4]}", name="Offline Widget", base_uom="PCS", is_active=True)
    db_session.add(item)
    await db_session.flush()

    var = ItemVariant(id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD", variant_name="Std", cost_price=Decimal("15.0"), selling_price=Decimal("25.0"))
    db_session.add(var)
    await db_session.flush()

    client_tx_id = f"OFF-SO-{uuid.uuid4()}"

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
                    "notes": "Created while warehouse tablet was offline",
                    "lines": [
                        {"item_variant_id": var.id, "quantity_ordered": 5.0, "unit_price": 25.0}
                    ]
                }
            )
        ]
    )

    # 1. First sync attempt
    res1 = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res1.committed_count == 1
    assert res1.acks[0].status == "COMMITTED"
    so_id = res1.acks[0].server_tx_id

    # Verify Sales Order created
    so = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so_id))).scalar_one()
    assert so.total_amount == Decimal("125.0")
    assert so.status == "DRAFT"

    # 2. Idempotent Retry: Exactly same client_tx_id
    res2 = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res2.committed_count == 1
    assert res2.acks[0].status == "COMMITTED"
    assert res2.acks[0].server_tx_id == so_id

    # Verify no duplicate Sales Orders created
    all_sos = (await db_session.execute(select(SalesOrder).where(SalesOrder.customer_id == cust.id))).scalars().all()
    assert len(all_sos) == 1

# ============================================================================
# 3. OFFLINE MAINTENANCE CONSUMPTION & GL JOURNAL VOUCHER
# ============================================================================

@pytest.mark.asyncio
async def test_offline_maintenance_consumption_and_gl_jv(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    device_id = f"WIN-DESK-{uuid.uuid4().hex[:8]}"

    await GLService.seed_standard_chart_of_accounts(db_session, tenant_id)

    # Setup device
    await SyncService.handshake_device(
        db=db_session, tenant_id=tenant_id, user_id=user_id,
        req=SyncHandshakeRequest(device_identifier=device_id, device_name="Desk 1", platform="WINDOWS_DESKTOP", app_version="1.1.0")
    )

    # Setup warehouse & bin
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-MWO-{uuid.uuid4().hex[:4]}", name="MWO WH", is_active=True)
    db_session.add(wh)
    await db_session.flush()

    bin_loc = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="BIN-SPARE-1", is_active=True)
    db_session.add(bin_loc)
    await db_session.flush()

    # Asset
    ac = FixedAssetClass(id=str(uuid.uuid4()), tenant_id=tenant_id, class_code=f"AC-{uuid.uuid4().hex[:4]}", class_name="Compressors", useful_life_months=60)
    db_session.add(ac)
    await db_session.flush()

    from datetime import date
    fa = FixedAsset(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        asset_code=f"AST-{uuid.uuid4().hex[:4]}",
        asset_name="Air Compressor 10HP",
        asset_class_id=ac.id,
        purchase_cost=Decimal("8000.0"),
        current_book_value=Decimal("8000.0"),
        acquisition_date=date(2026, 1, 1),
        depreciation_start_date=date(2026, 1, 1),
        status="ACTIVE"
    )
    db_session.add(fa)
    await db_session.flush()

    # Spare Part Item & Stock
    part_item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, sku=f"SKU-VALVE-{uuid.uuid4().hex[:4]}", name="Intake Valve", base_uom="PCS", is_active=True)
    db_session.add(part_item)
    await db_session.flush()

    part_var = ItemVariant(id=str(uuid.uuid4()), item_id=part_item.id, variant_sku=f"{part_item.sku}-STD", variant_name="Valve Std", cost_price=Decimal("150.0"), selling_price=Decimal("200.0"))
    db_session.add(part_var)
    await db_session.flush()

    await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id, transaction_type="OPENING_BALANCE",
        entries_data=[{"item_variant_id": part_var.id, "source_location_bin_id": None, "destination_location_bin_id": bin_loc.id, "quantity": Decimal("10.0"), "unit_cost": Decimal("150.0")}],
        user_id=user_id
    )

    # Create MWO in IN_PROGRESS state
    mwo = MaintenanceWorkOrder(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        mwo_number=f"MWO-{uuid.uuid4().hex[:6].upper()}",
        asset_id=fa.id,
        status="IN_PROGRESS",
        priority="HIGH",
        notes="Replace Valve Assembly",
        expenditure_type="REVENUE_EXPENSE",
        scheduled_start_date=datetime.now(timezone.utc)
    )
    db_session.add(mwo)
    await db_session.flush()

    sp_line = MWOSparePart(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        mwo_id=mwo.id,
        item_variant_id=part_var.id,
        warehouse_id=wh.id,
        location_bin_id=bin_loc.id,
        quantity_required=Decimal("2.0"),
        quantity_consumed=Decimal("0.0"),
        unit_cost=Decimal("150.0")
    )
    db_session.add(sp_line)
    await db_session.commit()

    # Sync offline completion
    client_tx_id = f"OFF-MWO-{uuid.uuid4()}"
    batch_req = SyncUpstreamBatchRequest(
        device_identifier=device_id,
        mutations=[
            SyncMutationEnvelope(
                client_tx_id=client_tx_id,
                operation_type="CONSUME_MAINTENANCE_PARTS",
                warehouse_id=wh.id,
                client_timestamp=datetime.now(timezone.utc),
                payload={
                    "work_order_id": mwo.id,
                    "actual_downtime_hours": 2.5,
                    "resolution_notes": "Valves replaced and tested offline"
                }
            )
        ]
    )

    res = await SyncService.process_upstream_batch(db_session, tenant_id, user_id, batch_req)
    assert res.committed_count == 1
    assert res.acks[0].status == "COMMITTED"

    # Verify MWO completed
    await db_session.refresh(mwo)
    assert mwo.status == "COMPLETED"
    assert mwo.downtime_hours == Decimal("2.5")
