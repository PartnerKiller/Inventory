import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.sync import SyncDevice, SyncIdempotencyLog
from app.models.supply_chain import EdgeSyncBatch
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.schemas.supply_chain import (
    EdgeSyncBatchRequest,
    EdgeSyncBatchResponse,
    EdgeMutationItem,
    EdgeMutationResult
)
from app.services.stock_engine import StockEngine

import hmac
import hashlib

# Operations strictly prohibited from offline execution
REQUIRES_ONLINE_OPERATIONS = {"BOM_EDIT", "PO_APPROVE", "GL_CLOSE", "CREDIT_LIMIT_OVERRIDE"}

class EdgeSyncEngine:

    @staticmethod
    async def process_sync_batch(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        batch_req: EdgeSyncBatchRequest
    ) -> EdgeSyncBatchResponse:
        # 1. Validate HMAC signature if provided
        if batch_req.hmac_signature:
            expected_hmac = hmac.new(
                batch_req.device_id.encode("utf-8"),
                f"{batch_req.batch_id}:{batch_req.device_id}:{len(batch_req.mutations)}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(batch_req.hmac_signature, expected_hmac):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid HMAC signature. Sync batch has been tampered with or unauthorized key used."
                )

        # 2. Validate device registration
        device = (await db.execute(
            select(SyncDevice).where(
                SyncDevice.tenant_id == tenant_id,
                SyncDevice.device_identifier == batch_req.device_id
            )
        )).scalar_one_or_none()

        if not device:
            # Auto-register active device for edge sync
            device = SyncDevice(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                device_identifier=batch_req.device_id,
                device_name=f"Edge Node {batch_req.device_id[:8]}",
                platform="WINDOWS_DESKTOP",
                app_version="1.0.0",
                status="ACTIVE",
                registered_by_user_id=user_id,
                last_sync_at=get_utc_now()
            )
            db.add(device)
            await db.flush()

        if device.status == "REVOKED":
            raise HTTPException(status_code=403, detail="Edge device access has been revoked by system administrator")

        results: List[EdgeMutationResult] = []

        for mutation in batch_req.mutations:
            # 2. Check Idempotency Log
            existing_log = (await db.execute(
                select(SyncIdempotencyLog).where(
                    SyncIdempotencyLog.tenant_id == tenant_id,
                    SyncIdempotencyLog.client_transaction_id == mutation.client_transaction_id
                )
            )).scalar_one_or_none()

            if existing_log:
                results.append(EdgeMutationResult(
                    client_transaction_id=mutation.client_transaction_id,
                    status=existing_log.status,
                    server_transaction_id=existing_log.server_transaction_id,
                    error_detail=existing_log.error_detail
                ))
                continue

            # 3. Transaction Classification Guard
            if mutation.operation_type in REQUIRES_ONLINE_OPERATIONS:
                res = EdgeMutationResult(
                    client_transaction_id=mutation.client_transaction_id,
                    status="REJECTED",
                    error_detail=f"Operation '{mutation.operation_type}' strictly requires online central server connectivity"
                )
                log = SyncIdempotencyLog(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    client_transaction_id=mutation.client_transaction_id,
                    device_id=batch_req.device_id,
                    user_id=user_id,
                    operation_type=mutation.operation_type,
                    status="REJECTED",
                    response_payload={"error": res.error_detail},
                    error_detail=res.error_detail
                )
                db.add(log)
                results.append(res)
                continue

            # 4. Process Offline POS Sales with Stock Check & Compensating Backorder
            if mutation.operation_type == "POS_SALE":
                qty = mutation.quantity or Decimal("1.0")
                bal = (await db.execute(
                    select(StockBalanceCache).where(
                        StockBalanceCache.warehouse_id == mutation.warehouse_id,
                        StockBalanceCache.location_bin_id == mutation.source_bin_id,
                        StockBalanceCache.item_variant_id == mutation.item_variant_id
                    ).with_for_update()
                )).scalar_one_or_none()

                avail = (bal.quantity_on_hand - bal.quantity_allocated) if bal else Decimal("0.0")

                if avail < qty:
                    # Depleted Stock Conflict -> Trigger compensating backorder
                    res = EdgeMutationResult(
                        client_transaction_id=mutation.client_transaction_id,
                        status="CONFLICT",
                        error_detail=f"Insufficient stock (Available: {avail}, Requested: {qty}). Intervening sale depleted inventory.",
                        compensating_action="CREATE_BACKORDER_AND_ALERT_STORE_MANAGER"
                    )
                    log = SyncIdempotencyLog(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        client_transaction_id=mutation.client_transaction_id,
                        device_id=batch_req.device_id,
                        user_id=user_id,
                        operation_type=mutation.operation_type,
                        status="CONFLICT",
                        response_payload={"conflict": res.error_detail, "action": res.compensating_action},
                        error_detail=res.error_detail
                    )
                    db.add(log)
                    results.append(res)
                    continue

                # Stock Available -> Post Transaction
                tx = await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="STOCK_ISSUE",
                    entries_data=[{
                        "item_variant_id": mutation.item_variant_id,
                        "source_location_bin_id": mutation.source_bin_id,
                        "quantity": qty
                    }],
                    reference_doc_type="POS_SALE",
                    reference_doc_id=mutation.client_transaction_id,
                    notes="Edge POS offline sale sync",
                    user_id=user_id
                )
                res = EdgeMutationResult(
                    client_transaction_id=mutation.client_transaction_id,
                    status="COMMITTED",
                    server_transaction_id=tx.id
                )
                log = SyncIdempotencyLog(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    client_transaction_id=mutation.client_transaction_id,
                    device_id=batch_req.device_id,
                    user_id=user_id,
                    operation_type=mutation.operation_type,
                    server_transaction_id=tx.id,
                    status="COMMITTED",
                    response_payload={"tx_number": tx.transaction_number}
                )
                db.add(log)
                results.append(res)
                continue

            # 5. Bin-to-Bin rapid movement / Pick item
            if mutation.operation_type in {"BIN_TRANSFER", "PICK_ITEM"}:
                qty = mutation.quantity or Decimal("1.0")
                tx = await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="STOCK_TRANSFER",
                    entries_data=[{
                        "item_variant_id": mutation.item_variant_id,
                        "source_location_bin_id": mutation.source_bin_id,
                        "destination_location_bin_id": mutation.destination_bin_id,
                        "quantity": qty
                    }],
                    reference_doc_type="EDGE_SYNC",
                    reference_doc_id=mutation.client_transaction_id,
                    notes=f"Edge {mutation.operation_type} sync",
                    user_id=user_id
                )
                res = EdgeMutationResult(
                    client_transaction_id=mutation.client_transaction_id,
                    status="COMMITTED",
                    server_transaction_id=tx.id
                )
                log = SyncIdempotencyLog(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    client_transaction_id=mutation.client_transaction_id,
                    device_id=batch_req.device_id,
                    user_id=user_id,
                    operation_type=mutation.operation_type,
                    server_transaction_id=tx.id,
                    status="COMMITTED",
                    response_payload={"tx_number": tx.transaction_number}
                )
                db.add(log)
                results.append(res)
                continue

            # Default fallback for count scan and other safe offline tasks
            res = EdgeMutationResult(
                client_transaction_id=mutation.client_transaction_id,
                status="COMMITTED"
            )
            log = SyncIdempotencyLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                client_transaction_id=mutation.client_transaction_id,
                device_id=batch_req.device_id,
                user_id=user_id,
                operation_type=mutation.operation_type,
                status="COMMITTED",
                response_payload={"message": "Logged successfully"}
            )
            db.add(log)
            results.append(res)

        # Record Edge Sync Batch
        sync_batch = EdgeSyncBatch(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            batch_id=batch_req.batch_id,
            device_id=batch_req.device_id,
            user_id=user_id,
            mutation_count=len(batch_req.mutations),
            hmac_signature=batch_req.hmac_signature,
            status="PROCESSED"
        )
        db.add(sync_batch)
        device.last_sync_at = get_utc_now()

        await db.commit()

        return EdgeSyncBatchResponse(
            batch_id=batch_req.batch_id,
            device_id=batch_req.device_id,
            processed_count=len(results),
            results=results
        )
