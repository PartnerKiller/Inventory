import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant, Barcode
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.sales import SalesOrder, SOLineItem, SalesReturn, SalesReturnLine
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.change_feed import EntityChangeFeed
from app.models.warehouse_ops import CountSession, CountLine, PackingSession, PackingItem
from app.schemas.sales import SalesReturnCreate, SalesReturnLineCreate, SalesOrderCreate, SOLineCreate
from app.schemas.maintenance import MaintenanceWorkOrderComplete
from app.services.maintenance_service import MaintenanceService
from app.schemas.sync import (
    SyncHandshakeRequest,
    SyncHandshakeResponse,
    SyncUpstreamBatchRequest,
    SyncMutationAck,
    SyncUpstreamBatchResponse,
    SyncDownstreamResponse,
    DeltaItemResponse,
    DeltaBinResponse,
    DeltaBalanceResponse,
    DeltaLotResponse,
    DeltaSerialResponse,
    ChangeFeedItem,
    ChangeFeedResponse
)
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService
from app.services.purchase_service import PurchaseService
from app.services.sales_service import SalesService
from app.services.warehouse_service import WarehouseService
from app.services.traceability_service import TraceabilityService
from app.services.audit_service import AuditService

LEASE_DURATION_SECONDS = 28800 # 8 Hours (1 Warehouse Shift)

class SyncService:
    # ============================================================================
    # HANDSHAKE & LEASE MANAGEMENT
    # ============================================================================

    @staticmethod
    async def handshake_device(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        req: SyncHandshakeRequest
    ) -> SyncHandshakeResponse:
        """
        Registers or authenticates a desktop device and issues an 8-hour cryptographic offline lease.
        """
        stmt = (
            select(SyncDevice)
            .where(
                SyncDevice.tenant_id == tenant_id,
                SyncDevice.device_identifier == req.device_identifier.strip()
            )
            .with_for_update()
        )
        device = (await db.execute(stmt)).scalar_one_or_none()

        now = get_utc_now()
        lease_expires = now + timedelta(seconds=LEASE_DURATION_SECONDS)

        if device:
            if device.status == "REVOKED":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This device has been revoked by system administrators. Offline sync denied."
                )
            device.device_name = req.device_name
            device.app_version = req.app_version
            device.last_sync_at = now
            device.active_lease_expires_at = lease_expires
        else:
            device = SyncDevice(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                device_identifier=req.device_identifier.strip(),
                device_name=req.device_name,
                platform=req.platform,
                app_version=req.app_version,
                status="ACTIVE",
                registered_by_user_id=user_id,
                last_sync_at=now,
                active_lease_expires_at=lease_expires
            )
            db.add(device)

        await db.commit()
        await db.refresh(device)

        return SyncHandshakeResponse(
            device_id=device.id,
            device_name=device.device_name,
            status=device.status,
            sync_session_token=f"SYNC-LEASE-{device.id}-{uuid.uuid4().hex[:16]}",
            lease_expires_at=lease_expires,
            lease_duration_seconds=LEASE_DURATION_SECONDS,
            server_time=now
        )

    # ============================================================================
    # UPSTREAM MUTATION RECONCILIATION
    # ============================================================================

    @classmethod
    async def process_upstream_batch(
        cls,
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        req: SyncUpstreamBatchRequest
    ) -> SyncUpstreamBatchResponse:
        """
        Sequentially ingests offline mutations with strict idempotency and conflict rejection.
        """
        # Validate device active status
        dev_stmt = select(SyncDevice).where(
            SyncDevice.tenant_id == tenant_id,
            SyncDevice.device_identifier == req.device_identifier.strip()
        )
        device = (await db.execute(dev_stmt)).scalar_one_or_none()
        if not device or device.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Device is not registered or has been revoked."
            )

        if device.active_lease_expires_at:
            lease_exp = device.active_lease_expires_at.replace(tzinfo=timezone.utc) if device.active_lease_expires_at.tzinfo is None else device.active_lease_expires_at
            now_utc = get_utc_now()
            if lease_exp < now_utc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Offline lease has expired. Device must perform online handshake to renew lease."
                )

        acks = []
        committed_cnt = 0
        rejected_cnt = 0
        conflict_cnt = 0

        for mutation in req.mutations:
            # 1. Idempotency Check: Return cached ACK if already processed
            idemp_stmt = select(SyncIdempotencyLog).where(
                SyncIdempotencyLog.tenant_id == tenant_id,
                SyncIdempotencyLog.client_transaction_id == mutation.client_tx_id
            )
            existing_log = (await db.execute(idemp_stmt)).scalar_one_or_none()
            if existing_log:
                acks.append(SyncMutationAck(
                    client_tx_id=mutation.client_tx_id,
                    operation_type=mutation.operation_type,
                    status=existing_log.status,
                    server_tx_id=existing_log.server_transaction_id,
                    error_message=existing_log.error_detail,
                    committed_at=existing_log.processed_at
                ))
                if existing_log.status == "COMMITTED":
                    committed_cnt += 1
                elif existing_log.status == "CONFLICT":
                    conflict_cnt += 1
                else:
                    rejected_cnt += 1
                continue

            # 2. Fresh Mutation Execution
            ack = await cls._execute_single_mutation(db, tenant_id, user_id, device.id, mutation)
            acks.append(ack)
            if ack.status == "COMMITTED":
                committed_cnt += 1
            elif ack.status == "CONFLICT":
                conflict_cnt += 1
            else:
                rejected_cnt += 1

        device.last_sync_at = get_utc_now()
        await db.commit()

        return SyncUpstreamBatchResponse(
            total_received=len(req.mutations),
            committed_count=committed_cnt,
            rejected_count=rejected_cnt,
            conflict_count=conflict_cnt,
            acks=acks,
            server_time=get_utc_now()
        )

    @classmethod
    async def _execute_single_mutation(
        cls,
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        device_id: str,
        mutation
    ) -> SyncMutationAck:
        now = get_utc_now()
        op_type = mutation.operation_type
        p = mutation.payload

        try:
            wh_stmt = select(Warehouse).where(Warehouse.id == mutation.warehouse_id, Warehouse.tenant_id == tenant_id)
            wh = (await db.execute(wh_stmt)).scalar_one_or_none()
            if not wh:
                raise HTTPException(status_code=404, detail=f"Target warehouse '{mutation.warehouse_id}' not found in current tenant")

            server_tx_id = None
            if op_type in ["BIN_TRANSFER", "PUTAWAY"]:
                item_variant_id = p["item_variant_id"]
                source_bin_id = p.get("source_bin_id") or p.get("source_location_bin_id")
                dest_bin_id = p.get("dest_bin_id") or p.get("destination_bin_id") or p.get("destination_location_bin_id")
                quantity = Decimal(str(p["quantity"]))
                lot_id = p.get("lot_id")
                serials = p.get("serial_numbers", [])

                # Verify source stock under lock
                bal_stmt = (
                    select(StockBalanceCache)
                    .where(
                        StockBalanceCache.warehouse_id == mutation.warehouse_id,
                        StockBalanceCache.location_bin_id == source_bin_id,
                        StockBalanceCache.item_variant_id == item_variant_id
                    )
                    .with_for_update()
                )
                bal = (await db.execute(bal_stmt)).scalar_one_or_none()
                if not bal or (bal.quantity_on_hand - bal.quantity_allocated) < quantity:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Insufficient available stock in source bin to execute transfer of {quantity} units"
                    )

                # Post stock ledger transfer
                tx = await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="PUTAWAY" if op_type == "PUTAWAY" else "TRANSFER_INTERNAL",
                    reference_doc_type="OFFLINE_DESKTOP",
                    reference_doc_id=mutation.client_tx_id,
                    user_id=user_id,
                    entries_data=[{
                        "item_variant_id": item_variant_id,
                        "source_location_bin_id": source_bin_id,
                        "destination_location_bin_id": dest_bin_id,
                        "quantity": quantity,
                        "uom": p.get("uom", "PCS"),
                        "unit_cost": Decimal("0.0")
                    }]
                )
                server_tx_id = tx.id

                # Update serial locations if any
                if serials:
                    await TraceabilityService.update_serial_bin_locations(
                        db=db,
                        tenant_id=tenant_id,
                        item_variant_id=item_variant_id,
                        source_bin_id=source_bin_id,
                        dest_bin_id=dest_bin_id,
                        quantity=int(quantity),
                        serial_numbers=serials,
                        target_status="IN_STOCK"
                    )

            elif op_type == "PICK_ITEM":
                # Acquire serial / stock for pick
                serial_number = p.get("serial_number")
                if serial_number:
                    acquired = await TraceabilityService.acquire_serial_for_pick(
                        db=db,
                        tenant_id=tenant_id,
                        warehouse_id=mutation.warehouse_id,
                        item_variant_id=p["item_variant_id"],
                        serial_number=serial_number,
                        user_id=user_id
                    )
                    server_tx_id = acquired.id

            elif op_type == "RECEIVE_GOODS":
                # Inbound goods receipt
                po_id = p.get("purchase_order_id")
                po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
                if not po:
                    raise HTTPException(status_code=404, detail="Purchase order not found")

                # Post goods receipt
                dest_bin_id = p["destination_bin_id"]
                item_variant_id = p["item_variant_id"]
                quantity = Decimal(str(p["quantity"]))
                unit_price = Decimal(str(p.get("unit_price", "0.0")))

                tx = await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="PURCHASE_RECEIPT",
                    reference_doc_type="PURCHASE_ORDER",
                    reference_doc_id=po.id,
                    user_id=user_id,
                    entries_data=[{
                        "item_variant_id": item_variant_id,
                        "source_location_bin_id": None,
                        "destination_location_bin_id": dest_bin_id,
                        "quantity": quantity,
                        "unit_cost": unit_price
                    }]
                )
                server_tx_id = tx.id

                # Server-authoritative costing layer recording
                await CostingService.record_inbound_receipt(
                    db=db,
                    tenant_id=tenant_id,
                    warehouse_id=mutation.warehouse_id,
                    item_variant_id=item_variant_id,
                    quantity=quantity,
                    unit_cost=unit_price
                )

                # Register lot & serials if present
                lot_number = p.get("lot_number")
                if lot_number:
                    await TraceabilityService.create_or_get_lot(
                        db=db,
                        tenant_id=tenant_id,
                        lot_in=type("LotIn", (), {
                            "item_variant_id": item_variant_id,
                            "lot_number": lot_number,
                            "supplier_id": po.supplier_id,
                            "supplier_lot_number": p.get("supplier_lot_number"),
                            "origin_grn_id": None,
                            "manufacturing_date": None,
                            "expiry_date": None,
                            "best_before_date": None,
                            "initial_quantity": quantity,
                            "notes": "Offline GRN Sync"
                        })(),
                        user_id=user_id
                    )

            elif op_type == "COUNT_SCAN":
                # Blind cycle counting observation record
                count_session_id = p.get("count_session_id")
                session = (await db.execute(
                    select(CountSession).where(CountSession.id == count_session_id, CountSession.warehouse_id == mutation.warehouse_id)
                )).scalar_one_or_none()
                if not session:
                    raise HTTPException(status_code=404, detail="Count session not found or does not match warehouse")
                if session.status not in ["DRAFT", "IN_PROGRESS"]:
                    raise HTTPException(status_code=400, detail=f"Cannot record count scan against session in '{session.status}' status")

                item_variant_id = p["item_variant_id"]
                location_bin_id = p["location_bin_id"]
                counted_qty = Decimal(str(p["counted_quantity"]))

                # Check if count line exists, else create
                line_stmt = select(CountLine).where(
                    CountLine.count_session_id == session.id,
                    CountLine.location_bin_id == location_bin_id,
                    CountLine.item_variant_id == item_variant_id
                )
                count_line = (await db.execute(line_stmt)).scalar_one_or_none()

                # Get current expected balance from DB snapshot
                bal_stmt = select(StockBalanceCache).where(
                    StockBalanceCache.warehouse_id == mutation.warehouse_id,
                    StockBalanceCache.location_bin_id == location_bin_id,
                    StockBalanceCache.item_variant_id == item_variant_id
                )
                bal = (await db.execute(bal_stmt)).scalar_one_or_none()
                expected_qty = bal.quantity_on_hand if bal else Decimal("0.0")

                if count_line:
                    count_line.counted_quantity = counted_qty
                    count_line.variance_quantity = counted_qty - count_line.expected_quantity
                    count_line.notes = p.get("notes", "Offline Count Scan")
                else:
                    count_line = CountLine(
                        id=str(uuid.uuid4()),
                        count_session_id=session.id,
                        location_bin_id=location_bin_id,
                        item_variant_id=item_variant_id,
                        expected_quantity=expected_qty,
                        counted_quantity=counted_qty,
                        variance_quantity=counted_qty - expected_qty,
                        notes=p.get("notes", "Offline Count Scan")
                    )
                    db.add(count_line)
                session.status = "IN_PROGRESS"
                server_tx_id = session.id

            elif op_type == "PACK_ITEM":
                # Packing verification scan
                item_variant_id = p["item_variant_id"]
                quantity = Decimal(str(p.get("quantity", "1.0")))
                serial_number = p.get("serial_number")
                carton_num = int(p.get("carton_number", 1))
                packing_session_id = p.get("packing_session_id")

                # If packing session provided, verify it is active
                if packing_session_id:
                    ps_stmt = select(PackingSession).where(PackingSession.id == packing_session_id)
                    ps = (await db.execute(ps_stmt)).scalar_one_or_none()
                    if not ps or ps.status != "OPEN":
                        raise HTTPException(status_code=400, detail="Packing session not open or not found")

                    pack_item = PackingItem(
                        id=str(uuid.uuid4()),
                        packing_session_id=ps.id,
                        item_variant_id=item_variant_id,
                        carton_number=carton_num,
                        quantity_packed=quantity,
                        serial_number=serial_number
                    )
                    db.add(pack_item)
                    server_tx_id = pack_item.id
                else:
                    server_tx_id = str(uuid.uuid4())

            elif op_type == "CUSTOMER_RETURN":
                # Customer Return intake into Quarantine / Receiving bin
                so_id = p["sales_order_id"]
                so = (await db.execute(select(SalesOrder).where(SalesOrder.id == so_id))).scalar_one_or_none()
                if not so:
                    raise HTTPException(status_code=404, detail="Sales order not found")

                lines_in = [
                    SalesReturnLineCreate(
                        so_line_id=l["so_line_id"],
                        quantity_returned=Decimal(str(l["quantity_returned"])),
                        condition=l.get("condition", "GOOD"),
                        destination_bin_id=l["destination_bin_id"]
                    )
                    for l in p.get("lines", [])
                ]
                return_create = SalesReturnCreate(
                    notes=p.get("notes", "Offline RMA Return Intake"),
                    lines=lines_in
                )
                sales_return = await SalesService.process_sales_return(
                    db=db,
                    tenant_id=tenant_id,
                    so_id=so_id,
                    return_in=return_create,
                    user_id=user_id,
                    client_type="OFFLINE_DESKTOP"
                )
                server_tx_id = sales_return.id

            elif op_type == "CREATE_SALES_ORDER":
                lines_in = [
                    SOLineCreate(
                        item_variant_id=l["item_variant_id"],
                        quantity_ordered=Decimal(str(l["quantity_ordered"])),
                        unit_price=Decimal(str(l["unit_price"])),
                        discount_pct=Decimal(str(l.get("discount_pct", 0.0))),
                        tax_pct=Decimal(str(l.get("tax_pct", 0.0)))
                    )
                    for l in p.get("lines", [])
                ]
                so_create = SalesOrderCreate(
                    customer_id=p["customer_id"],
                    warehouse_id=mutation.warehouse_id,
                    notes=p.get("notes", "Offline Sales Order Creation"),
                    lines=lines_in
                )
                so = await SalesService.create_sales_order(
                    db=db,
                    tenant_id=tenant_id,
                    so_in=so_create,
                    user_id=user_id
                )
                server_tx_id = so.id

            elif op_type == "CONSUME_MAINTENANCE_PARTS":
                mwo_id = p["work_order_id"]
                comp_req = MaintenanceWorkOrderComplete(
                    actual_completion_date=get_utc_now(),
                    downtime_hours=Decimal(str(p.get("actual_downtime_hours", "1.0"))),
                    labor_hours=Decimal(str(p.get("labor_hours", "1.0"))),
                    notes=p.get("resolution_notes", "Completed via offline sync")
                )
                mwo = await MaintenanceService.complete_maintenance_work_order(
                    db=db,
                    tenant_id=tenant_id,
                    mwo_id=mwo_id,
                    comp_in=comp_req,
                    user_id=user_id
                )
                server_tx_id = mwo.id

            # Record success in sync_idempotency_log
            log_entry = SyncIdempotencyLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                client_transaction_id=mutation.client_tx_id,
                device_id=device_id,
                user_id=user_id,
                operation_type=op_type,
                server_transaction_id=server_tx_id,
                status="COMMITTED",
                response_payload={"server_tx_id": server_tx_id, "status": "COMMITTED"},
                processed_at=now
            )
            db.add(log_entry)
            await db.flush()

            return SyncMutationAck(
                client_tx_id=mutation.client_tx_id,
                operation_type=op_type,
                status="COMMITTED",
                server_tx_id=server_tx_id,
                committed_at=now
            )

        except HTTPException as he:
            st = "CONFLICT" if he.status_code == 409 else "REJECTED"
            log_entry = SyncIdempotencyLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                client_transaction_id=mutation.client_tx_id,
                device_id=device_id,
                user_id=user_id,
                operation_type=op_type,
                server_transaction_id=None,
                status=st,
                response_payload={"status": st, "error": he.detail},
                error_detail=he.detail,
                processed_at=now
            )
            db.add(log_entry)
            await db.flush()

            return SyncMutationAck(
                client_tx_id=mutation.client_tx_id,
                operation_type=op_type,
                status=st,
                error_message=he.detail,
                committed_at=now
            )

    # ============================================================================
    # DOWNSTREAM DELTA SYNCHRONIZATION
    # ============================================================================

    @staticmethod
    async def get_downstream_delta(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str
    ) -> SyncDownstreamResponse:
        """
        Retrieves active master data, bins, lot masters, and serials for offline caching.
        """
        # Items & Variants
        items_stmt = select(Item).where(Item.tenant_id == tenant_id, Item.is_active == True)
        items_res = (await db.execute(items_stmt)).scalars().all()
        items_out = [
            DeltaItemResponse(
                id=it.id,
                sku=it.sku,
                name=it.name,
                base_uom=it.base_uom,
                valuation_method=it.valuation_method,
                is_batch_tracked=it.is_batch_tracked,
                is_serial_tracked=it.is_serial_tracked,
                variants=[{"id": v.id, "sku": v.variant_sku, "name": v.variant_name, "cost": float(v.cost_price)} for v in it.variants]
            )
            for it in items_res
        ]

        # Bins
        bins_stmt = select(LocationBin).where(LocationBin.warehouse_id == warehouse_id, LocationBin.is_active == True)
        bins_res = (await db.execute(bins_stmt)).scalars().all()
        bins_out = [
            DeltaBinResponse(
                id=b.id,
                warehouse_id=b.warehouse_id,
                code=b.code,
                aisle=b.aisle,
                rack=b.rack,
                shelf=b.shelf,
                bin=b.bin,
                type=b.type,
                is_active=b.is_active
            )
            for b in bins_res
        ]

        # Balances
        bal_stmt = select(StockBalanceCache).where(StockBalanceCache.warehouse_id == warehouse_id, StockBalanceCache.quantity_on_hand > 0)
        bal_res = (await db.execute(bal_stmt)).scalars().all()
        bal_out = [
            DeltaBalanceResponse(
                warehouse_id=b.warehouse_id,
                location_bin_id=b.location_bin_id,
                item_variant_id=b.item_variant_id,
                lot_id=b.lot_id,
                quantity_on_hand=float(b.quantity_on_hand),
                quantity_allocated=float(b.quantity_allocated)
            )
            for b in bal_res
        ]

        # Lots
        lots_stmt = select(StockLot).where(StockLot.tenant_id == tenant_id, StockLot.status == "ACTIVE")
        lots_res = (await db.execute(lots_stmt)).scalars().all()
        lots_out = [
            DeltaLotResponse(
                id=l.id,
                item_variant_id=l.item_variant_id,
                lot_number=l.lot_number,
                expiry_date=str(l.expiry_date) if l.expiry_date else None,
                status=l.status
            )
            for l in lots_res
        ]

        # Serials
        serials_stmt = select(ItemSerialNumber).where(ItemSerialNumber.warehouse_id == warehouse_id, ItemSerialNumber.status.in_(["IN_STOCK", "ALLOCATED"]))
        serials_res = (await db.execute(serials_stmt)).scalars().all()
        serials_out = [
            DeltaSerialResponse(
                id=s.id,
                item_variant_id=s.item_variant_id,
                serial_number=s.serial_number,
                status=s.status,
                location_bin_id=s.location_bin_id,
                lot_id=s.lot_id
            )
            for s in serials_res
        ]

        return SyncDownstreamResponse(
            warehouse_id=warehouse_id,
            server_time=get_utc_now(),
            items=items_out,
            bins=bins_out,
            balances=bal_out,
            lots=lots_out,
            serials=serials_out
        )

    # ============================================================================
    # DEVICE REVOCATION
    # ============================================================================

    @staticmethod
    async def revoke_device(
        db: AsyncSession,
        tenant_id: str,
        device_id: str,
        reason: str,
        admin_user_id: Optional[str] = None
    ) -> SyncDevice:
        """
        Immediately revokes an offline device, preventing further synchronization.
        """
        device = (await db.execute(
            select(SyncDevice).where(SyncDevice.id == device_id, SyncDevice.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        device.status = "REVOKED"
        device.active_lease_expires_at = None
        device.notes = f"REVOKED: {reason}"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="REVOKE_DEVICE",
            entity_type="SyncDevice",
            entity_id=device.id,
            user_id=admin_user_id,
            changes={"status": "REVOKED", "reason": reason}
        )
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def restore_device(
        db: AsyncSession,
        tenant_id: str,
        device_id: str,
        admin_user_id: Optional[str] = None
    ) -> SyncDevice:
        """
        Restores a previously revoked device to ACTIVE status and issues a fresh lease.
        """
        device = (await db.execute(
            select(SyncDevice).where(SyncDevice.id == device_id, SyncDevice.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        now = get_utc_now()
        device.status = "ACTIVE"
        device.active_lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)
        device.notes = f"RESTORED: Device reactivated by administrator on {now.isoformat()}"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="RESTORE_DEVICE",
            entity_type="SyncDevice",
            entity_id=device.id,
            user_id=admin_user_id,
            changes={"status": "ACTIVE"}
        )
        await db.commit()
        await db.refresh(device)
        return device

    # ============================================================================
    # BIDIRECTIONAL CHANGE-FEED (DOWNSTREAM INCREMENTAL SYNC)
    # ============================================================================

    @staticmethod
    async def record_entity_change(
        db: AsyncSession,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        change_type: str,
        payload: Dict[str, Any]
    ) -> EntityChangeFeed:
        """
        Appends an entity mutation to the monotonic change feed for client synchronization.
        """
        change_entry = EntityChangeFeed(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=change_type,
            payload_json=payload,
            created_at=get_utc_now()
        )
        db.add(change_entry)
        await db.flush()
        return change_entry

    @staticmethod
    async def get_change_feed(
        db: AsyncSession,
        tenant_id: str,
        since_revision: int = 0,
        limit: int = 200
    ) -> ChangeFeedResponse:
        """
        Streams incremental entity deltas recorded after since_revision.
        """
        # Get highest revision in tenant
        max_stmt = select(EntityChangeFeed.revision_id).where(
            EntityChangeFeed.tenant_id == tenant_id
        ).order_by(EntityChangeFeed.revision_id.desc()).limit(1)
        current_rev = (await db.execute(max_stmt)).scalar() or 0

        # Query changes since requested revision
        stmt = select(EntityChangeFeed).where(
            EntityChangeFeed.tenant_id == tenant_id,
            EntityChangeFeed.revision_id > since_revision
        ).order_by(EntityChangeFeed.revision_id.asc()).limit(limit + 1)
        results = (await db.execute(stmt)).scalars().all()

        has_more = len(results) > limit
        items = results[:limit]

        changes_out = [
            ChangeFeedItem(
                revision_id=c.revision_id,
                entity_type=c.entity_type,
                entity_id=c.entity_id,
                change_type=c.change_type,
                payload=c.payload_json,
                created_at=c.created_at
            )
            for c in items
        ]

        return ChangeFeedResponse(
            current_server_revision=current_rev,
            since_revision=since_revision,
            count=len(changes_out),
            has_more=has_more,
            changes=changes_out
        )

