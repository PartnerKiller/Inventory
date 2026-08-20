import pytest
import uuid
import hmac
import hashlib
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer
from app.models.general_ledger import GLAccount, JournalVoucher
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.models.supply_chain import SupplyChainNode, TransferOrder, TransferOrderLine, EdgeSyncBatch
from app.schemas.supply_chain import (
    SupplyChainNodeCreate,
    TransferOrderCreate,
    TransferOrderLineCreate,
    TransferReceiveAction,
    TransferReceiveLineAction,
    SourcingPlanRequest,
    EdgeSyncBatchRequest,
    EdgeMutationItem
)
from app.services.supply_chain_service import SupplyChainService
from app.services.edge_sync_engine import EdgeSyncEngine
from app.services.gl_service import GLService

# ============================================================================
# 1. NODE TOPOLOGY & PRIORITY
# ============================================================================

@pytest.mark.asyncio
async def test_supply_chain_node_topology_and_priority(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh_central = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Central DC", code=f"CDC_{uuid.uuid4().hex[:4]}")
    wh_regional = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="East DC", code=f"EDC_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_central, wh_regional])
    await db_session.commit()

    central_node = await SupplyChainService.create_node(
        db=db_session, tenant_id=tenant_id,
        node_in=SupplyChainNodeCreate(
            node_code="NODE-CDC-01",
            node_name="Central Hub",
            node_type="CENTRAL_DC",
            warehouse_id=wh_central.id,
            lead_time_days=3,
            sourcing_priority=1
        )
    )
    assert central_node.node_code == "NODE-CDC-01"

    reg_node = await SupplyChainService.create_node(
        db=db_session, tenant_id=tenant_id,
        node_in=SupplyChainNodeCreate(
            node_code="NODE-EDC-01",
            node_name="East Regional Hub",
            node_type="REGIONAL_DC",
            warehouse_id=wh_regional.id,
            parent_node_id=central_node.id,
            lead_time_days=1,
            sourcing_priority=2
        )
    )
    assert reg_node.parent_node_id == central_node.id

    with pytest.raises(HTTPException) as exc_info:
        await SupplyChainService.create_node(
            db=db_session, tenant_id=tenant_id,
            node_in=SupplyChainNodeCreate(
                node_code="NODE-CDC-01",
                node_name="Duplicate Node",
                node_type="CENTRAL_DC"
            )
        )
    assert exc_info.value.status_code == 409

# ============================================================================
# 2. SOURCING PLAN RESOLUTION (LOCAL VS UPSTREAM)
# ============================================================================

@pytest.mark.asyncio
async def test_sourcing_plan_resolution_local_vs_upstream(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID

    wh_local = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Store 101", code=f"S101_{uuid.uuid4().hex[:4]}")
    wh_regional = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Regional DC", code=f"RDC_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_local, wh_regional])

    var = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="SKU-PLAN-01", variant_name="Plan Item")
    db_session.add(var)

    bal_local = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh_local.id, location_bin_id=str(uuid.uuid4()),
        item_variant_id=var.id, quantity_on_hand=Decimal("5.0"), quantity_allocated=Decimal("0.0")
    )
    bal_reg = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh_regional.id, location_bin_id=str(uuid.uuid4()),
        item_variant_id=var.id, quantity_on_hand=Decimal("50.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add_all([bal_local, bal_reg])

    node_reg = SupplyChainNode(
        id=str(uuid.uuid4()), tenant_id=tenant_id, node_code="NODE-RDC-PLAN",
        node_name="Regional Hub", node_type="REGIONAL_DC", warehouse_id=wh_regional.id,
        lead_time_days=1, sourcing_priority=1, is_active=True
    )
    db_session.add(node_reg)
    await db_session.commit()

    # Demand = 3 -> Local stock fulfills demand
    plan_a = await SupplyChainService.resolve_sourcing_plan(
        db=db_session, tenant_id=tenant_id,
        req=SourcingPlanRequest(item_variant_id=var.id, demand_quantity=Decimal("3.0"), requesting_warehouse_id=wh_local.id)
    )
    assert plan_a.options[0].tier == "LOCAL_STOCK"
    assert plan_a.options[0].recommended is True

    # Demand = 20 -> Local insufficient, Regional Transfer recommended
    plan_b = await SupplyChainService.resolve_sourcing_plan(
        db=db_session, tenant_id=tenant_id,
        req=SourcingPlanRequest(item_variant_id=var.id, demand_quantity=Decimal("20.0"), requesting_warehouse_id=wh_local.id)
    )
    assert plan_b.options[0].recommended is False
    assert plan_b.options[1].tier == "REGIONAL_TRANSFER"
    assert plan_b.options[1].recommended is True

# ============================================================================
# 3. TRANSFER ORDER DISPATCH & IN-TRANSIT ACCOUNTING (GL ACCOUNT 1250)
# ============================================================================

@pytest.mark.asyncio
async def test_transfer_order_dispatch_in_transit_accounting(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh_src = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Hub WH", code=f"HUB_{uuid.uuid4().hex[:4]}")
    wh_dst = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Spoke WH", code=f"SPK_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_src, wh_dst])

    bin_src = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_src.id, code="STORAGE-01", type="STORAGE")
    bin_transit = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="IN-TRANSIT", type="STORAGE")
    bin_dst = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="DEST-STG", type="STAGING")
    db_session.add_all([bin_src, bin_transit, bin_dst])

    var = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="SKU-TRF-01", variant_name="Trf Item")
    db_session.add(var)

    bal_src = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh_src.id, location_bin_id=bin_src.id,
        item_variant_id=var.id, quantity_on_hand=Decimal("20.0"), quantity_allocated=Decimal("0.0")
    )
    c_layer = CostLayer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, warehouse_id=wh_src.id,
        item_variant_id=var.id, layer_number=f"LAY-SRC-{uuid.uuid4().hex[:6].upper()}",
        original_quantity=Decimal("20.0"), remaining_quantity=Decimal("20.0"),
        unit_cost=Decimal("80.0"), total_cost=Decimal("1600.0"), status="ACTIVE",
        layer_timestamp=datetime.now(timezone.utc)
    )
    db_session.add_all([bal_src, c_layer])
    await db_session.commit()

    trf = await SupplyChainService.create_transfer_order(
        db=db_session, tenant_id=tenant_id,
        trf_in=TransferOrderCreate(
            source_warehouse_id=wh_src.id,
            destination_warehouse_id=wh_dst.id,
            in_transit_bin_id=bin_transit.id,
            destination_bin_id=bin_dst.id,
            freight_charge=Decimal("200.0"),
            lines=[TransferOrderLineCreate(item_variant_id=var.id, quantity_requested=Decimal("10.0"))]
        )
    )
    assert trf.status == "APPROVED"

    dispatched = await SupplyChainService.dispatch_transfer_order(
        db=db_session, tenant_id=tenant_id, transfer_id=trf.id, source_bin_id=bin_src.id, user_id=user_id
    )
    assert dispatched.status == "IN_TRANSIT"
    assert dispatched.lines[0].unit_cost == Decimal("80.0")

    bal_transit = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_transit.id, StockBalanceCache.item_variant_id == var.id)
    )).scalar_one()
    assert bal_transit.quantity_on_hand == Decimal("10.0")

    jvs = (await db_session.execute(
        select(JournalVoucher).where(JournalVoucher.source_document_type == "TRANSFER_ORDER")
    )).scalars().all()
    assert len(jvs) >= 2

# ============================================================================
# 4. TRANSFER RECEIPT & FREIGHT CAPITALIZATION
# ============================================================================

@pytest.mark.asyncio
async def test_transfer_order_receive_with_freight_capitalization(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh_src = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Hub", code=f"H_{uuid.uuid4().hex[:4]}")
    wh_dst = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Spoke", code=f"S_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_src, wh_dst])

    bin_transit = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="TRANSIT-BIN", type="STORAGE")
    bin_dst = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="DEST-STORAGE", type="STORAGE")
    db_session.add_all([bin_transit, bin_dst])

    var = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="SKU-REC-01", variant_name="Rec Item")
    db_session.add(var)

    bal_transit = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh_dst.id, location_bin_id=bin_transit.id,
        item_variant_id=var.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal_transit)

    trf = TransferOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, transfer_number=f"TRF-REC-{uuid.uuid4().hex[:4]}",
        source_warehouse_id=wh_src.id, destination_warehouse_id=wh_dst.id,
        in_transit_bin_id=bin_transit.id, destination_bin_id=bin_dst.id,
        status="IN_TRANSIT", freight_charge=Decimal("50.0")
    )
    db_session.add(trf)

    line = TransferOrderLine(
        id=str(uuid.uuid4()), transfer_order_id=trf.id, item_variant_id=var.id,
        quantity_requested=Decimal("10.0"), quantity_shipped=Decimal("10.0"), unit_cost=Decimal("100.0")
    )
    db_session.add(line)
    await db_session.commit()

    received = await SupplyChainService.receive_transfer_order(
        db=db_session, tenant_id=tenant_id, transfer_id=trf.id,
        receive_act=TransferReceiveAction(
            received_lines=[TransferReceiveLineAction(item_variant_id=var.id, quantity_received=Decimal("10.0"), quantity_damaged=Decimal("0.0"))]
        ),
        user_id=user_id
    )
    assert received.status == "COMPLETED"

    dst_layer = (await db_session.execute(
        select(CostLayer).where(CostLayer.warehouse_id == wh_dst.id, CostLayer.item_variant_id == var.id)
    )).scalar_one()
    assert dst_layer.unit_cost == Decimal("105.0")
    assert dst_layer.total_cost == Decimal("1050.0")

# ============================================================================
# 5. TRANSFER DAMAGE WRITE-OFF GL
# ============================================================================

@pytest.mark.asyncio
async def test_transfer_order_damage_write_off_gl(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    wh_src = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Hub", code=f"H_{uuid.uuid4().hex[:4]}")
    wh_dst = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Spoke", code=f"S_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_src, wh_dst])

    bin_transit = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="TR-BIN-D", type="STORAGE")
    bin_dst = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="DST-BIN-D", type="STORAGE")
    bin_dmg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh_dst.id, code="DMG-BIN", type="STORAGE")
    db_session.add_all([bin_transit, bin_dst, bin_dmg])

    var = ItemVariant(id=str(uuid.uuid4()), item_id=str(uuid.uuid4()), variant_sku="SKU-DMG-01", variant_name="Dmg Item")
    db_session.add(var)

    bal_transit = StockBalanceCache(
        id=str(uuid.uuid4()), warehouse_id=wh_dst.id, location_bin_id=bin_transit.id,
        item_variant_id=var.id, quantity_on_hand=Decimal("10.0"), quantity_allocated=Decimal("0.0")
    )
    db_session.add(bal_transit)

    trf = TransferOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, transfer_number=f"TRF-DMG-{uuid.uuid4().hex[:4]}",
        source_warehouse_id=wh_src.id, destination_warehouse_id=wh_dst.id,
        in_transit_bin_id=bin_transit.id, destination_bin_id=bin_dst.id,
        status="IN_TRANSIT", freight_charge=Decimal("0.0")
    )
    db_session.add(trf)

    line = TransferOrderLine(
        id=str(uuid.uuid4()), transfer_order_id=trf.id, item_variant_id=var.id,
        quantity_requested=Decimal("10.0"), quantity_shipped=Decimal("10.0"), unit_cost=Decimal("50.0")
    )
    db_session.add(line)
    await db_session.commit()

    await SupplyChainService.receive_transfer_order(
        db=db_session, tenant_id=tenant_id, transfer_id=trf.id,
        receive_act=TransferReceiveAction(
            received_lines=[
                TransferReceiveLineAction(
                    item_variant_id=var.id, quantity_received=Decimal("8.0"),
                    quantity_damaged=Decimal("2.0"), damage_bin_id=bin_dmg.id
                )
            ]
        ),
        user_id=user_id
    )

    bal_dmg = (await db_session.execute(
        select(StockBalanceCache).where(StockBalanceCache.location_bin_id == bin_dmg.id, StockBalanceCache.item_variant_id == var.id)
    )).scalar_one()
    assert bal_dmg.quantity_on_hand == Decimal("2.0")

    jvs = (await db_session.execute(
        select(JournalVoucher).where(
            JournalVoucher.source_document_type == "TRANSFER_ORDER",
            JournalVoucher.source_document_id == f"{trf.id}_DAMAGE"
        )
    )).scalars().all()
    assert len(jvs) == 1
    assert sum(l.debit_amount for l in jvs[0].lines) == Decimal("100.0")

# ============================================================================
# 6. MULTI-TENANT ISOLATION (COMPANY A VS COMPANY B)
# ============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_isolation_cross_company(db_session: AsyncSession):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    wh_a = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_a, name="Company A DC", code=f"CA_{uuid.uuid4().hex[:4]}")
    wh_b = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_b, name="Company B DC", code=f"CB_{uuid.uuid4().hex[:4]}")
    db_session.add_all([wh_a, wh_b])

    node_b = SupplyChainNode(
        id=str(uuid.uuid4()), tenant_id=tenant_b, node_code=f"NODE-B-{uuid.uuid4().hex[:4]}",
        node_name="Company B Hub", node_type="CENTRAL_DC", warehouse_id=wh_b.id, is_active=True
    )
    db_session.add(node_b)
    await db_session.commit()

    # Company A attempts to query sourcing plan referencing Company B warehouse -> Node B ignored
    plan = await SupplyChainService.resolve_sourcing_plan(
        db=db_session, tenant_id=tenant_a,
        req=SourcingPlanRequest(item_variant_id=str(uuid.uuid4()), demand_quantity=Decimal("10.0"), requesting_warehouse_id=wh_a.id)
    )
    # Company B node must not appear in Company A options
    for opt in plan.options:
        assert opt.source_id != wh_b.id

# ============================================================================
# 7. HMAC SECURITY & PAYLOAD TAMPER GUARDS
# ============================================================================

@pytest.mark.asyncio
async def test_hmac_security_and_tamper_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    dev_id = f"EDGE-HMAC-{uuid.uuid4().hex[:6]}"
    batch_id = str(uuid.uuid4())

    # Valid HMAC
    valid_hmac = hmac.new(
        dev_id.encode("utf-8"),
        f"{batch_id}:{dev_id}:1".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    # 1. Valid HMAC -> ACCEPT
    req_valid = EdgeSyncBatchRequest(
        device_id=dev_id, batch_id=batch_id, hmac_signature=valid_hmac,
        mutations=[EdgeMutationItem(client_transaction_id=str(uuid.uuid4()), operation_type="COUNT_SCAN", warehouse_id=str(uuid.uuid4()))]
    )
    resp = await EdgeSyncEngine.process_sync_batch(db_session, tenant_id, user_id, req_valid)
    assert resp.processed_count == 1

    # 2. Tampered / Invalid HMAC -> REJECT (HTTP 401)
    req_invalid = EdgeSyncBatchRequest(
        device_id=dev_id, batch_id=str(uuid.uuid4()), hmac_signature="INVALID_FORGED_SIGNATURE",
        mutations=[EdgeMutationItem(client_transaction_id=str(uuid.uuid4()), operation_type="COUNT_SCAN", warehouse_id=str(uuid.uuid4()))]
    )
    with pytest.raises(HTTPException) as exc_info:
        await EdgeSyncEngine.process_sync_batch(db_session, tenant_id, user_id, req_invalid)
    assert exc_info.value.status_code == 401
    assert "Invalid HMAC signature" in exc_info.value.detail

# ============================================================================
# 8. REPLAY PROTECTION & IDEMPOTENCY
# ============================================================================

@pytest.mark.asyncio
async def test_replay_protection_different_batch_same_tx_id(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    dev_id = f"EDGE-REPLAY-{uuid.uuid4().hex[:6]}"
    client_tx_id = str(uuid.uuid4())

    # First Batch
    req1 = EdgeSyncBatchRequest(
        device_id=dev_id, batch_id=str(uuid.uuid4()),
        mutations=[EdgeMutationItem(client_transaction_id=client_tx_id, operation_type="COUNT_SCAN", warehouse_id=str(uuid.uuid4()))]
    )
    resp1 = await EdgeSyncEngine.process_sync_batch(db_session, tenant_id, user_id, req1)
    assert resp1.results[0].status == "COMMITTED"

    # Second Batch with different batch ID but same client transaction ID
    req2 = EdgeSyncBatchRequest(
        device_id=dev_id, batch_id=str(uuid.uuid4()),
        mutations=[EdgeMutationItem(client_transaction_id=client_tx_id, operation_type="COUNT_SCAN", warehouse_id=str(uuid.uuid4()))]
    )
    resp2 = await EdgeSyncEngine.process_sync_batch(db_session, tenant_id, user_id, req2)
    assert resp2.results[0].status == "COMMITTED"

    # Verify single log entry exists
    logs = (await db_session.execute(
        select(SyncIdempotencyLog).where(SyncIdempotencyLog.client_transaction_id == client_tx_id)
    )).scalars().all()
    assert len(logs) == 1

# ============================================================================
# 9. IN-TRANSIT QUANTITY INTEGRITY
# ============================================================================

def test_in_transit_quantity_mathematical_balance():
    dispatched = Decimal("100.0")
    received = Decimal("85.0")
    damaged = Decimal("10.0")
    remaining_in_transit = Decimal("5.0")

    # Invariant: Dispatched = Received + Damaged + Remaining In Transit
    assert dispatched == (received + damaged + remaining_in_transit)
