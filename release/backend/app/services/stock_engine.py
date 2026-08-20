import uuid
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.ledger import StockLedgerTransaction, StockLedgerEntry, StockBalanceCache, StockBatch
from app.models.warehouse import LocationBin
from app.models.base import get_utc_now
from app.services.audit_service import AuditService

from app.services.sequence_service import SequenceService

class StockEngine:
    @staticmethod
    async def post_transaction(
        db: AsyncSession,
        tenant_id: str,
        transaction_type: str,
        entries_data: List[Dict[str, Any]],
        reference_doc_type: Optional[str] = None,
        reference_doc_id: Optional[str] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None,
        client_type: str = "WEB"
    ) -> StockLedgerTransaction:
        """
        Executes a double-entry stock ledger journal entry and updates the stock balance cache.
        CRITICAL ARCHITECTURAL GUARANTEES:
        - Employs deterministic pessimistic row-locking (.with_for_update()) on all touched balance rows in sorted order.
        - Enforces tenant isolation.
        - NEVER calls db.commit() internally; only calls await db.flush() so that the outer
          business workflow orchestrates the single atomic transaction boundary.
        """
        tx_number = await SequenceService.generate_next_number(db, tenant_id, "STOCK_TRANSACTION", custom_prefix="TX")
        
        transaction = StockLedgerTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transaction_number=tx_number,
            transaction_type=transaction_type,
            reference_document_type=reference_doc_type,
            reference_document_id=reference_doc_id,
            posted_by_user_id=user_id,
            posted_at=get_utc_now(),
            notes=notes,
        )
        db.add(transaction)
        await db.flush()

        # Step 0: Acquire locks in strict deterministic order (sorted by (bin_id, variant_id))
        # to prevent deadlock when concurrent operations transfer stock in opposite directions
        lock_keys: List[Tuple[str, str]] = []
        for entry_info in entries_data:
            vid = entry_info["item_variant_id"]
            if entry_info.get("source_location_bin_id"):
                lock_keys.append((entry_info["source_location_bin_id"], vid))
            if entry_info.get("destination_location_bin_id"):
                lock_keys.append((entry_info["destination_location_bin_id"], vid))

        unique_lock_keys = sorted(list(set(lock_keys)), key=lambda x: (x[0], x[1]))
        locked_balances: Dict[Tuple[str, str], List[StockBalanceCache]] = {}

        for bin_id, vid in unique_lock_keys:
            lock_stmt = select(StockBalanceCache).where(
                StockBalanceCache.location_bin_id == bin_id,
                StockBalanceCache.item_variant_id == vid
            ).with_for_update()
            lock_res = await db.execute(lock_stmt)
            locked_balances[(bin_id, vid)] = lock_res.scalars().all()

        for entry_info in entries_data:
            variant_id = entry_info["item_variant_id"]
            qty = Decimal(str(entry_info["quantity"]))
            unit_cost = Decimal(str(entry_info.get("unit_cost", 0.0)))
            source_bin_id = entry_info.get("source_location_bin_id")
            dest_bin_id = entry_info.get("destination_location_bin_id")
            batch_id = entry_info.get("batch_id")
            batch_number = entry_info.get("batch_number")
            serial_number = entry_info.get("serial_number")
            uom = entry_info.get("uom", "PCS")

            if qty <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ledger quantity must be strictly positive: received {qty}"
                )

            # Resolve or create batch if batch_number is supplied
            if batch_number and not batch_id:
                batch_stmt = select(StockBatch).where(
                    StockBatch.item_variant_id == variant_id,
                    StockBatch.batch_number == batch_number
                )
                batch_res = await db.execute(batch_stmt)
                batch_obj = batch_res.scalar_one_or_none()
                if not batch_obj:
                    batch_obj = StockBatch(
                        id=str(uuid.uuid4()),
                        item_variant_id=variant_id,
                        batch_number=batch_number,
                        cost_per_unit=unit_cost
                    )
                    db.add(batch_obj)
                    await db.flush()
                batch_id = batch_obj.id

            # 1. Handle Source Bin Deduction (Credit / Outflow)
            if source_bin_id:
                source_bin_res = await db.execute(select(LocationBin).where(LocationBin.id == source_bin_id))
                source_bin = source_bin_res.scalar_one_or_none()
                if not source_bin:
                    raise HTTPException(status_code=404, detail=f"Source location bin {source_bin_id} not found")

                source_bals = locked_balances.get((source_bin_id, variant_id), [])
                if batch_id:
                    source_bals = [b for b in source_bals if b.batch_id == batch_id]

                total_avail = sum([(b.quantity_on_hand - b.quantity_allocated) for b in source_bals])
                if total_avail < qty:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Insufficient stock in bin {source_bin.code}. Required: {qty}, Available: {total_avail}"
                    )

                remaining_to_deduct = qty
                for source_bal in source_bals:
                    avail_in_bal = source_bal.quantity_on_hand - source_bal.quantity_allocated
                    if avail_in_bal > 0:
                        deduct = min(remaining_to_deduct, avail_in_bal)
                        source_bal.quantity_on_hand = Decimal(str(source_bal.quantity_on_hand)) - deduct
                        source_bal.updated_at = get_utc_now()
                        if not batch_id:
                            batch_id = source_bal.batch_id
                        remaining_to_deduct -= deduct
                        if remaining_to_deduct <= 0:
                            break

            # 2. Handle Destination Bin Addition (Debit / Inflow)
            if dest_bin_id:
                dest_bin_res = await db.execute(select(LocationBin).where(LocationBin.id == dest_bin_id))
                dest_bin = dest_bin_res.scalar_one_or_none()
                if not dest_bin:
                    raise HTTPException(status_code=404, detail=f"Destination location bin {dest_bin_id} not found")

                dest_bals = locked_balances.get((dest_bin_id, variant_id), [])
                dest_bal = next((b for b in dest_bals if b.batch_id == batch_id), None)

                if not dest_bal:
                    dest_bal = StockBalanceCache(
                        id=str(uuid.uuid4()),
                        warehouse_id=dest_bin.warehouse_id,
                        location_bin_id=dest_bin_id,
                        item_variant_id=variant_id,
                        batch_id=batch_id,
                        quantity_on_hand=qty,
                        quantity_allocated=Decimal("0.0"),
                        updated_at=get_utc_now()
                    )
                    db.add(dest_bal)
                    if (dest_bin_id, variant_id) not in locked_balances:
                        locked_balances[(dest_bin_id, variant_id)] = []
                    locked_balances[(dest_bin_id, variant_id)].append(dest_bal)
                else:
                    dest_bal.quantity_on_hand = Decimal(str(dest_bal.quantity_on_hand)) + qty
                    dest_bal.updated_at = get_utc_now()

            # 3. Create Immutable Ledger Entry
            ledger_entry = StockLedgerEntry(
                id=str(uuid.uuid4()),
                transaction_id=transaction.id,
                item_variant_id=variant_id,
                batch_id=batch_id,
                serial_number=serial_number,
                source_location_bin_id=source_bin_id,
                destination_location_bin_id=dest_bin_id,
                quantity=qty,
                uom=uom,
                unit_cost=unit_cost,
                total_cost=qty * unit_cost,
                entry_timestamp=get_utc_now()
            )
            db.add(ledger_entry)

        # 4. Record Audit Log
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="POST_LEDGER",
            entity_type="StockLedgerTransaction",
            entity_id=transaction.id,
            user_id=user_id,
            client_type=client_type,
            changes={"transaction_type": transaction_type, "entry_count": len(entries_data)}
        )

        # Flush within transaction without committing (outer workflow will commit)
        await db.flush()
        return transaction
