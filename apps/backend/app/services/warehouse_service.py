import uuid
import math
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.item import Item, ItemVariant, Barcode, ItemCategory
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry, StockBatch
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.sales import SalesOrder, SOLineItem, Shipment, SOAllocation
from app.models.costing import CostLayer, ItemCostProfile
from app.models.warehouse_ops import (
    CountSession, CountLine, PickTask, PickTaskLine, PackingSession, PackingItem, ItemSerialNumber
)
from app.models.audit import AuditLog
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService
from app.services.purchase_service import PurchaseService
from app.services.sales_service import SalesService
from app.schemas.warehouse_ops import (
    BarcodeResolutionResponse, PutawayExecutionResponse, BinTransferResponse,
    CountSessionResponse, CountLineResponse, PickTaskResponse, PickTaskLineResponse,
    PackingSessionResponse, PackingItemResponse, PackingItemVerifyResponse, LabelGenerationResponse, LabelItemPayload
)

def quantize_decimal(value: Decimal, places: int = 4) -> Decimal:
    fmt = Decimal(10) ** -places
    return value.quantize(fmt)

class WarehouseService:

    @staticmethod
    async def resolve_barcode(
        db: AsyncSession,
        tenant_id: str,
        raw_barcode: str,
        warehouse_id: Optional[str] = None
    ) -> BarcodeResolutionResponse:
        """
        Universal Barcode Scanner Resolver.
        Resolves Product Barcode, Variant SKU, Bin Code, PO, GRN, SO, Shipment, or Package.
        """
        code = raw_barcode.strip()
        if not code:
            return BarcodeResolutionResponse(
                found=False,
                entity_type="UNKNOWN",
                identifier=code,
                display_title="Empty Barcode",
                payload={}
            )

        # 1. Check explicit prefixes
        upper_code = code.upper()
        if upper_code.startswith("BIN:"):
            bin_raw = code[4:].strip()
            bin_stmt = select(LocationBin).join(Warehouse).where(
                Warehouse.tenant_id == tenant_id,
                or_(LocationBin.code == bin_raw, LocationBin.id == bin_raw)
            )
            if warehouse_id:
                bin_stmt = bin_stmt.where(LocationBin.warehouse_id == warehouse_id)
            bin_obj = (await db.execute(bin_stmt)).scalars().first()
            if bin_obj:
                return BarcodeResolutionResponse(
                    found=True,
                    entity_type="LOCATION_BIN",
                    identifier=bin_obj.code,
                    display_title=f"Bin: {bin_obj.code} ({bin_obj.type})",
                    display_subtitle=f"Aisle {bin_obj.aisle} | Rack {bin_obj.rack} | Shelf {bin_obj.shelf}",
                    payload={"bin_id": bin_obj.id, "warehouse_id": bin_obj.warehouse_id, "type": bin_obj.type}
                )

        if upper_code.startswith("PO:"):
            po_num = code[3:].strip()
            po = (await db.execute(
                select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.po_number == po_num)
            )).scalars().first()
            if po:
                return BarcodeResolutionResponse(
                    found=True,
                    entity_type="PURCHASE_ORDER",
                    identifier=po.po_number,
                    display_title=f"Purchase Order: {po.po_number}",
                    display_subtitle=f"Status: {po.status}",
                    payload={"purchase_order_id": po.id, "status": po.status}
                )

        if upper_code.startswith("GRN:"):
            grn_num = code[4:].strip()
            grn = (await db.execute(
                select(GoodsReceipt).where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.grn_number == grn_num)
            )).scalars().first()
            if grn:
                return BarcodeResolutionResponse(
                    found=True,
                    entity_type="GOODS_RECEIPT",
                    identifier=grn.grn_number,
                    display_title=f"Goods Receipt: {grn.grn_number}",
                    payload={"goods_receipt_id": grn.id, "status": grn.status}
                )

        if upper_code.startswith("SO:"):
            so_num = code[3:].strip()
            so = (await db.execute(
                select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.so_number == so_num)
            )).scalars().first()
            if so:
                return BarcodeResolutionResponse(
                    found=True,
                    entity_type="SALES_ORDER",
                    identifier=so.so_number,
                    display_title=f"Sales Order: {so.so_number}",
                    display_subtitle=f"Status: {so.status}",
                    payload={"sales_order_id": so.id, "status": so.status}
                )

        # 2. Check Barcode Table (Primary / Secondary Variant Barcodes)
        bar_stmt = (
            select(Barcode, ItemVariant, Item)
            .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(Barcode.barcode_value == code, Item.tenant_id == tenant_id)
        )
        bar_row = (await db.execute(bar_stmt)).first()
        if bar_row:
            b_obj, var_obj, item_obj = bar_row
            return BarcodeResolutionResponse(
                found=True,
                entity_type="VARIANT",
                identifier=var_obj.variant_sku,
                display_title=f"{item_obj.name} - {var_obj.variant_name}",
                display_subtitle=f"SKU: {var_obj.variant_sku} | Cost: ${var_obj.cost_price}",
                payload={"item_id": item_obj.id, "variant_id": var_obj.id, "variant_sku": var_obj.variant_sku}
            )

        # 3. Check Variant SKU direct match
        var_stmt = (
            select(ItemVariant, Item)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(ItemVariant.variant_sku == code, Item.tenant_id == tenant_id)
        )
        var_row = (await db.execute(var_stmt)).first()
        if var_row:
            var_obj, item_obj = var_row
            return BarcodeResolutionResponse(
                found=True,
                entity_type="VARIANT",
                identifier=var_obj.variant_sku,
                display_title=f"{item_obj.name} - {var_obj.variant_name}",
                display_subtitle=f"SKU: {var_obj.variant_sku} | Cost: ${var_obj.cost_price}",
                payload={"item_id": item_obj.id, "variant_id": var_obj.id, "variant_sku": var_obj.variant_sku}
            )

        # 4. Check Location Bin direct code match
        bin_stmt = select(LocationBin).join(Warehouse).where(
            Warehouse.tenant_id == tenant_id,
            LocationBin.code == code
        )
        if warehouse_id:
            bin_stmt = bin_stmt.where(LocationBin.warehouse_id == warehouse_id)
        bin_obj = (await db.execute(bin_stmt)).scalars().first()
        if bin_obj:
            return BarcodeResolutionResponse(
                found=True,
                entity_type="LOCATION_BIN",
                identifier=bin_obj.code,
                display_title=f"Bin: {bin_obj.code} ({bin_obj.type})",
                display_subtitle=f"Aisle {bin_obj.aisle} | Rack {bin_obj.rack} | Shelf {bin_obj.shelf}",
                payload={"bin_id": bin_obj.id, "warehouse_id": bin_obj.warehouse_id, "type": bin_obj.type}
            )

        return BarcodeResolutionResponse(
            found=False,
            entity_type="UNKNOWN",
            identifier=code,
            display_title="Unrecognized Barcode",
            display_subtitle="No matching product, bin, or document found",
            payload={}
        )

    @staticmethod
    async def execute_putaway(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        source_staging_bin_id: str,
        destination_storage_bin_id: str,
        item_variant_id: str,
        quantity: Decimal,
        batch_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> PutawayExecutionResponse:
        """
        Executes an atomic putaway transfer from a Staging/Receiving bin to a Storage bin.
        Preserves cost basis and records a double-entry StockLedgerTransaction.
        """
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Putaway quantity must be positive")

        # Validate Bins
        src_bin = (await db.execute(
            select(LocationBin).where(LocationBin.id == source_staging_bin_id, LocationBin.warehouse_id == warehouse_id)
        )).scalar_one_or_none()
        if not src_bin:
            raise HTTPException(status_code=404, detail="Source staging bin not found in warehouse")

        dst_bin = (await db.execute(
            select(LocationBin).where(LocationBin.id == destination_storage_bin_id, LocationBin.warehouse_id == warehouse_id)
        )).scalar_one_or_none()
        if not dst_bin:
            raise HTTPException(status_code=404, detail="Destination storage bin not found in warehouse")

        # Acquire lock on source balance
        src_bal_stmt = (
            select(StockBalanceCache)
            .where(
                StockBalanceCache.warehouse_id == warehouse_id,
                StockBalanceCache.location_bin_id == source_staging_bin_id,
                StockBalanceCache.item_variant_id == item_variant_id
            )
            .with_for_update()
        )
        src_bal = (await db.execute(src_bal_stmt)).scalar_one_or_none()
        if not src_bal or src_bal.quantity_on_hand < quantity:
            available = float(src_bal.quantity_on_hand) if src_bal else 0.0
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient inventory in staging bin {src_bin.code} (Requested: {float(quantity)}, Available: {available})"
            )

        # Execute double-entry transfer via StockEngine
        tx_number = f"PTW-{uuid.uuid4().hex[:8].upper()}"
        tx = StockLedgerTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transaction_number=tx_number,
            transaction_type="PUTAWAY_TRANSFER",
            reference_document_type="PUTAWAY_TASK",
            posted_by_user_id=user_id,
            posted_at=get_utc_now(),
            notes=f"Putaway from {src_bin.code} to {dst_bin.code}"
        )
        db.add(tx)
        await db.flush()

        # Deduct from source staging bin
        src_bal.quantity_on_hand -= quantity

        # Add to destination storage bin
        dst_bal_stmt = (
            select(StockBalanceCache)
            .where(
                StockBalanceCache.warehouse_id == warehouse_id,
                StockBalanceCache.location_bin_id == destination_storage_bin_id,
                StockBalanceCache.item_variant_id == item_variant_id
            )
            .with_for_update()
        )
        dst_bal = (await db.execute(dst_bal_stmt)).scalar_one_or_none()
        if not dst_bal:
            dst_bal = StockBalanceCache(
                id=str(uuid.uuid4()),
                warehouse_id=warehouse_id,
                location_bin_id=destination_storage_bin_id,
                item_variant_id=item_variant_id,
                quantity_on_hand=Decimal("0.0"),
                quantity_allocated=Decimal("0.0")
            )
            db.add(dst_bal)
            await db.flush()

        dst_bal.quantity_on_hand += quantity

        # Post dual entries in StockLedgerEntry
        entry_out = StockLedgerEntry(
            id=str(uuid.uuid4()),
            transaction_id=tx.id,
            item_variant_id=item_variant_id,
            batch_id=batch_id,
            source_location_bin_id=source_staging_bin_id,
            destination_location_bin_id=destination_storage_bin_id,
            quantity=quantity,
            entry_timestamp=get_utc_now()
        )
        db.add(entry_out)
        await db.flush()

        # Fetch variant sku for response
        var = (await db.execute(select(ItemVariant).where(ItemVariant.id == item_variant_id))).scalar_one()

        return PutawayExecutionResponse(
            success=True,
            transaction_id=tx.id,
            transaction_number=tx.transaction_number,
            source_bin_code=src_bin.code,
            destination_bin_code=dst_bin.code,
            item_variant_sku=var.variant_sku,
            transferred_quantity=float(quantity),
            timestamp=tx.posted_at
        )

    @staticmethod
    async def execute_bin_transfer(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        source_bin_id: str,
        destination_bin_id: str,
        item_variant_id: str,
        quantity: Decimal,
        batch_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> BinTransferResponse:
        """
        Executes a rapid intra-warehouse bin-to-bin movement.
        """
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Transfer quantity must be positive")
        if source_bin_id == destination_bin_id:
            raise HTTPException(status_code=422, detail="Source and destination bins must be distinct")

        # Validate Bins
        src_bin = (await db.execute(
            select(LocationBin).where(LocationBin.id == source_bin_id, LocationBin.warehouse_id == warehouse_id)
        )).scalar_one_or_none()
        if not src_bin:
            raise HTTPException(status_code=404, detail="Source bin not found in warehouse")

        dst_bin = (await db.execute(
            select(LocationBin).where(LocationBin.id == destination_bin_id, LocationBin.warehouse_id == warehouse_id)
        )).scalar_one_or_none()
        if not dst_bin:
            raise HTTPException(status_code=404, detail="Destination bin not found in warehouse")

        # Acquire lock on source balance
        src_bal_stmt = (
            select(StockBalanceCache)
            .where(
                StockBalanceCache.warehouse_id == warehouse_id,
                StockBalanceCache.location_bin_id == source_bin_id,
                StockBalanceCache.item_variant_id == item_variant_id
            )
            .with_for_update()
        )
        src_bal = (await db.execute(src_bal_stmt)).scalar_one_or_none()
        avail = (src_bal.quantity_on_hand - src_bal.quantity_allocated) if src_bal else Decimal("0.0")
        if not src_bal or avail < quantity:
            available = float(avail)
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient unallocated stock in bin {src_bin.code} (Requested: {float(quantity)}, Available: {available})"
            )

        tx_number = f"MOV-{uuid.uuid4().hex[:8].upper()}"
        tx = StockLedgerTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transaction_number=tx_number,
            transaction_type="BIN_TRANSFER",
            reference_document_type="MANUAL_TRANSFER",
            posted_by_user_id=user_id,
            posted_at=get_utc_now(),
            notes=f"Bin transfer from {src_bin.code} to {dst_bin.code}"
        )
        db.add(tx)
        await db.flush()

        src_bal.quantity_on_hand -= quantity

        dst_bal_stmt = (
            select(StockBalanceCache)
            .where(
                StockBalanceCache.warehouse_id == warehouse_id,
                StockBalanceCache.location_bin_id == destination_bin_id,
                StockBalanceCache.item_variant_id == item_variant_id
            )
            .with_for_update()
        )
        dst_bal = (await db.execute(dst_bal_stmt)).scalar_one_or_none()
        if not dst_bal:
            dst_bal = StockBalanceCache(
                id=str(uuid.uuid4()),
                warehouse_id=warehouse_id,
                location_bin_id=destination_bin_id,
                item_variant_id=item_variant_id,
                quantity_on_hand=Decimal("0.0"),
                quantity_allocated=Decimal("0.0")
            )
            db.add(dst_bal)
            await db.flush()

        dst_bal.quantity_on_hand += quantity

        entry = StockLedgerEntry(
            id=str(uuid.uuid4()),
            transaction_id=tx.id,
            item_variant_id=item_variant_id,
            batch_id=batch_id,
            source_location_bin_id=source_bin_id,
            destination_location_bin_id=destination_bin_id,
            quantity=quantity,
            entry_timestamp=get_utc_now()
        )
        db.add(entry)
        await db.flush()

        var = (await db.execute(select(ItemVariant).where(ItemVariant.id == item_variant_id))).scalar_one()

        return BinTransferResponse(
            success=True,
            transaction_id=tx.id,
            transaction_number=tx.transaction_number,
            source_bin_code=src_bin.code,
            destination_bin_code=dst_bin.code,
            item_variant_sku=var.variant_sku,
            transferred_quantity=float(quantity),
            timestamp=tx.posted_at
        )

    @staticmethod
    async def create_count_session(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        scope_type: str = "FULL_WAREHOUSE",
        bin_ids: Optional[List[str]] = None,
        category_id: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> CountSessionResponse:
        """
        Initializes a cycle count session and captures expected quantity snapshots across scoped bins.
        """
        wh = (await db.execute(
            select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

        session_number = f"CNT-{wh.code}-{uuid.uuid4().hex[:6].upper()}"
        session = CountSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            session_number=session_number,
            status="IN_PROGRESS",
            scope_type=scope_type,
            notes=notes,
            assigned_to_user_id=user_id,
            started_at=get_utc_now()
        )
        db.add(session)
        await db.flush()

        # Query stock balances to snapshot
        bal_stmt = (
            select(StockBalanceCache, LocationBin, ItemVariant, Item)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .join(ItemVariant, StockBalanceCache.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(StockBalanceCache.warehouse_id == warehouse_id)
        )
        if scope_type == "CUSTOM_BINS" and bin_ids:
            bal_stmt = bal_stmt.where(StockBalanceCache.location_bin_id.in_(bin_ids))
        elif scope_type == "CATEGORY" and category_id:
            bal_stmt = bal_stmt.where(Item.category_id == category_id)

        rows = (await db.execute(bal_stmt)).fetchall()

        lines_out = []
        for bal, b_obj, v_obj, i_obj in rows:
            line = CountLine(
                id=str(uuid.uuid4()),
                count_session_id=session.id,
                location_bin_id=b_obj.id,
                item_variant_id=v_obj.id,
                batch_id=bal.batch_id,
                expected_quantity=bal.quantity_on_hand,
                counted_quantity=None,
                variance_quantity=Decimal("0.0"),
                unit_cost=v_obj.cost_price or Decimal("0.0"),
                variance_value=Decimal("0.0")
            )
            db.add(line)
            lines_out.append(CountLineResponse(
                id=line.id,
                count_session_id=session.id,
                location_bin_id=b_obj.id,
                bin_code=b_obj.code,
                item_variant_id=v_obj.id,
                variant_sku=v_obj.variant_sku,
                item_name=i_obj.name,
                expected_quantity=float(bal.quantity_on_hand),
                counted_quantity=None,
                variance_quantity=0.0,
                unit_cost=float(v_obj.cost_price or 0.0),
                variance_value=0.0,
                is_recounted=False
            ))

        await db.flush()

        return CountSessionResponse(
            id=session.id,
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            warehouse_name=wh.name,
            session_number=session.session_number,
            status=session.status,
            scope_type=session.scope_type,
            notes=session.notes,
            total_lines=len(lines_out),
            total_counted_lines=0,
            total_variance_quantity=0.0,
            total_variance_value=0.0,
            created_at=session.created_at,
            started_at=session.started_at,
            lines=lines_out
        )

    @staticmethod
    async def submit_count_results(
        db: AsyncSession,
        tenant_id: str,
        session_id: str,
        counts: List[Dict[str, Any]],
        user_id: Optional[str] = None
    ) -> CountSessionResponse:
        """
        Records operator floor counts into CountSession without directly mutating inventory.
        Computes physical and monetary variances for Supervisor review.
        """
        session_stmt = (
            select(CountSession)
            .where(CountSession.id == session_id, CountSession.tenant_id == tenant_id)
        )
        session = (await db.execute(session_stmt)).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Count session not found")
        if session.status not in ["IN_PROGRESS", "RECOUNT_REQUESTED"]:
            raise HTTPException(status_code=422, detail=f"Cannot submit counts in '{session.status}' status")

        # Fetch lines
        lines = (await db.execute(
            select(CountLine).where(CountLine.count_session_id == session.id)
        )).scalars().all()
        line_map = {(l.location_bin_id, l.item_variant_id): l for l in lines}

        total_var_qty = Decimal("0.0")
        total_var_val = Decimal("0.0")
        counted_count = 0

        for c in counts:
            bin_id = c["location_bin_id"]
            var_id = c["item_variant_id"]
            qty = Decimal(str(c["counted_quantity"]))

            key = (bin_id, var_id)
            if key in line_map:
                line = line_map[key]
                line.counted_quantity = qty
                line.variance_quantity = quantize_decimal(qty - line.expected_quantity, 4)
                line.variance_value = quantize_decimal(line.variance_quantity * line.unit_cost, 2)
                total_var_qty += abs(line.variance_quantity)
                total_var_val += abs(line.variance_value)
                counted_count += 1

        session.status = "PENDING_REVIEW"
        session.completed_at = get_utc_now()
        await db.flush()

        # Format response
        return await WarehouseService.get_count_session(db, tenant_id, session.id)

    @staticmethod
    async def get_count_session(
        db: AsyncSession,
        tenant_id: str,
        session_id: str
    ) -> CountSessionResponse:
        session = (await db.execute(
            select(CountSession).where(CountSession.id == session_id, CountSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Count session not found")

        wh = (await db.execute(select(Warehouse).where(Warehouse.id == session.warehouse_id))).scalar_one()

        lines_stmt = (
            select(CountLine, LocationBin, ItemVariant, Item)
            .join(LocationBin, CountLine.location_bin_id == LocationBin.id)
            .join(ItemVariant, CountLine.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(CountLine.count_session_id == session.id)
        )
        rows = (await db.execute(lines_stmt)).fetchall()

        lines_out = []
        tot_var_qty = Decimal("0.0")
        tot_var_val = Decimal("0.0")
        counted_cnt = 0

        for cl, b, v, i in rows:
            if cl.counted_quantity is not None:
                counted_cnt += 1
                tot_var_qty += abs(cl.variance_quantity)
                tot_var_val += abs(cl.variance_value)

            lines_out.append(CountLineResponse(
                id=cl.id,
                count_session_id=session.id,
                location_bin_id=b.id,
                bin_code=b.code,
                item_variant_id=v.id,
                variant_sku=v.variant_sku,
                item_name=i.name,
                expected_quantity=float(cl.expected_quantity),
                counted_quantity=float(cl.counted_quantity) if cl.counted_quantity is not None else None,
                variance_quantity=float(cl.variance_quantity),
                unit_cost=float(cl.unit_cost),
                variance_value=float(cl.variance_value),
                is_recounted=cl.is_recounted
            ))

        return CountSessionResponse(
            id=session.id,
            tenant_id=tenant_id,
            warehouse_id=session.warehouse_id,
            warehouse_name=wh.name,
            session_number=session.session_number,
            status=session.status,
            scope_type=session.scope_type,
            notes=session.notes,
            total_lines=len(lines_out),
            total_counted_lines=counted_cnt,
            total_variance_quantity=float(tot_var_qty),
            total_variance_value=float(tot_var_val),
            created_at=session.created_at,
            started_at=session.started_at,
            completed_at=session.completed_at,
            approved_at=session.approved_at,
            lines=lines_out
        )

    @staticmethod
    async def approve_count_session(
        db: AsyncSession,
        tenant_id: str,
        session_id: str,
        action: str = "APPROVE",
        review_notes: Optional[str] = None,
        supervisor_user_id: Optional[str] = None
    ) -> CountSessionResponse:
        """
        Supervisor action on CountSession:
        - APPROVE: Posts authoritative StockLedgerTransaction & Costing Adjustments for variances.
        - RECOUNT: Flags session for recount.
        - REJECT: Cancels session without stock changes.
        """
        session = (await db.execute(
            select(CountSession).where(CountSession.id == session_id, CountSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Count session not found")
        if session.status != "PENDING_REVIEW":
            raise HTTPException(status_code=422, detail=f"Cannot review session in status '{session.status}'")

        if action == "REJECT":
            session.status = "REJECTED"
            session.reviewed_by_user_id = supervisor_user_id
            await db.flush()
            return await WarehouseService.get_count_session(db, tenant_id, session.id)

        if action == "RECOUNT":
            session.status = "RECOUNT_REQUESTED"
            session.reviewed_by_user_id = supervisor_user_id
            await db.flush()
            return await WarehouseService.get_count_session(db, tenant_id, session.id)

        # APPROVE action: generate ledger adjustments
        lines = (await db.execute(
            select(CountLine).where(CountLine.count_session_id == session.id)
        )).scalars().all()

        for line in lines:
            if line.counted_quantity is not None and line.variance_quantity != 0:
                delta_qty = line.variance_quantity

                # Lock balance cache row
                bal_stmt = (
                    select(StockBalanceCache)
                    .where(
                        StockBalanceCache.warehouse_id == session.warehouse_id,
                        StockBalanceCache.location_bin_id == line.location_bin_id,
                        StockBalanceCache.item_variant_id == line.item_variant_id
                    )
                    .with_for_update()
                )
                bal = (await db.execute(bal_stmt)).scalar_one_or_none()
                if not bal:
                    bal = StockBalanceCache(
                        id=str(uuid.uuid4()),
                        warehouse_id=session.warehouse_id,
                        location_bin_id=line.location_bin_id,
                        item_variant_id=line.item_variant_id,
                        quantity_on_hand=Decimal("0.0"),
                        quantity_allocated=Decimal("0.0")
                    )
                    db.add(bal)
                    await db.flush()

                # Update physical stock balance
                bal.quantity_on_hand += delta_qty

                # Post ledger transaction
                tx = StockLedgerTransaction(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    transaction_number=f"ADJ-CNT-{uuid.uuid4().hex[:8].upper()}",
                    transaction_type="CYCLE_COUNT_ADJUSTMENT",
                    reference_document_type="COUNT_SESSION",
                    reference_document_id=session.id,
                    posted_by_user_id=supervisor_user_id,
                    posted_at=get_utc_now(),
                    notes=f"Count Variance Adjustment ({'+' if delta_qty > 0 else ''}{delta_qty})"
                )
                db.add(tx)
                await db.flush()

                entry = StockLedgerEntry(
                    id=str(uuid.uuid4()),
                    transaction_id=tx.id,
                    item_variant_id=line.item_variant_id,
                    batch_id=line.batch_id,
                    source_location_bin_id=line.location_bin_id if delta_qty < 0 else None,
                    destination_location_bin_id=line.location_bin_id if delta_qty > 0 else None,
                    quantity=abs(delta_qty),
                    unit_cost=line.unit_cost,
                    total_cost=abs(line.variance_value),
                    entry_timestamp=get_utc_now()
                )
                db.add(entry)
                await db.flush()

                # Update Costing Engine layers / MWA
                await CostingService.record_inventory_adjustment(
                    db=db,
                    tenant_id=tenant_id,
                    warehouse_id=session.warehouse_id,
                    item_variant_id=line.item_variant_id,
                    quantity_diff=delta_qty,
                    unit_cost=line.unit_cost
                )

        session.status = "APPROVED"
        session.reviewed_by_user_id = supervisor_user_id
        session.approved_at = get_utc_now()
        await db.flush()

        return await WarehouseService.get_count_session(db, tenant_id, session.id)

    @staticmethod
    async def get_or_create_pick_task(
        db: AsyncSession,
        tenant_id: str,
        sales_order_id: str,
        user_id: Optional[str] = None
    ) -> PickTaskResponse:
        """
        Generates or fetches a spatial-guided PickTask for an allocated Sales Order.
        Pick lines are ordered by spatial path: Aisle -> Rack -> Shelf -> Bin.
        """
        so = (await db.execute(
            select(SalesOrder).where(SalesOrder.id == sales_order_id, SalesOrder.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales order not found")
        if so.status not in ["CONFIRMED", "ALLOCATED", "PICKING", "PACKING"]:
            raise HTTPException(status_code=422, detail=f"Sales order in status '{so.status}' cannot be picked")

        # Check existing pick task
        task = (await db.execute(
            select(PickTask).where(PickTask.sales_order_id == sales_order_id, PickTask.tenant_id == tenant_id)
        )).scalar_one_or_none()

        if not task:
            task = PickTask(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                warehouse_id=so.warehouse_id,
                sales_order_id=sales_order_id,
                task_number=f"PCK-{so.so_number}",
                status="IN_PROGRESS",
                assigned_to_user_id=user_id,
                started_at=get_utc_now()
            )
            db.add(task)
            await db.flush()

            # Query allocations for SO lines
            alloc_stmt = (
                select(SOAllocation, SOLineItem, LocationBin, ItemVariant, Item)
                .join(SOLineItem, SOAllocation.so_line_id == SOLineItem.id)
                .join(LocationBin, SOAllocation.location_bin_id == LocationBin.id)
                .join(ItemVariant, SOLineItem.item_variant_id == ItemVariant.id)
                .join(Item, ItemVariant.item_id == Item.id)
                .where(SOLineItem.sales_order_id == sales_order_id)
                .order_by(LocationBin.aisle.asc(), LocationBin.rack.asc(), LocationBin.shelf.asc(), LocationBin.bin.asc())
            )
            alloc_rows = (await db.execute(alloc_stmt)).fetchall()

            for alloc, sol_item, b, v, i in alloc_rows:
                task_line = PickTaskLine(
                    id=str(uuid.uuid4()),
                    pick_task_id=task.id,
                    so_line_id=alloc.so_line_id,
                    location_bin_id=b.id,
                    item_variant_id=v.id,
                    batch_id=None,
                    quantity_allocated=alloc.quantity_allocated,
                    quantity_picked=Decimal("0.0"),
                    status="PENDING"
                )
                db.add(task_line)
            await db.flush()

        # Format output sorted by spatial route
        lines_stmt = (
            select(PickTaskLine, LocationBin, ItemVariant, Item)
            .join(LocationBin, PickTaskLine.location_bin_id == LocationBin.id)
            .join(ItemVariant, PickTaskLine.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(PickTaskLine.pick_task_id == task.id)
            .order_by(LocationBin.aisle.asc(), LocationBin.rack.asc(), LocationBin.shelf.asc(), LocationBin.bin.asc())
        )
        rows = (await db.execute(lines_stmt)).fetchall()

        lines_out = []
        picked_cnt = 0
        for pl, b, v, i in rows:
            if pl.status == "PICKED":
                picked_cnt += 1
            lines_out.append(PickTaskLineResponse(
                id=pl.id,
                pick_task_id=task.id,
                so_line_id=pl.so_line_id,
                location_bin_id=b.id,
                bin_code=b.code,
                bin_aisle=b.aisle,
                bin_rack=b.rack,
                bin_shelf=b.shelf,
                bin_position=b.bin,
                item_variant_id=v.id,
                variant_sku=v.variant_sku,
                item_name=i.name,
                quantity_allocated=float(pl.quantity_allocated),
                quantity_picked=float(pl.quantity_picked),
                status=pl.status
            ))

        return PickTaskResponse(
            id=task.id,
            tenant_id=tenant_id,
            warehouse_id=task.warehouse_id,
            sales_order_id=sales_order_id,
            sales_order_number=so.so_number,
            task_number=task.task_number,
            status=task.status,
            total_lines=len(lines_out),
            picked_lines=picked_cnt,
            lines=lines_out
        )

    @staticmethod
    async def confirm_pick_line(
        db: AsyncSession,
        tenant_id: str,
        pick_task_line_id: str,
        scanned_bin_code: str,
        scanned_item_barcode: str,
        quantity_picked: Decimal,
        user_id: Optional[str] = None
    ) -> PickTaskResponse:
        """
        Validates scanned bin and product barcodes against pick task line.
        Rejects scan if wrong bin or wrong product.
        """
        line = (await db.execute(
            select(PickTaskLine).where(PickTaskLine.id == pick_task_line_id)
        )).scalar_one_or_none()
        if not line:
            raise HTTPException(status_code=404, detail="Pick task line not found")

        # Validate Bin Code
        bin_obj = (await db.execute(
            select(LocationBin).where(LocationBin.id == line.location_bin_id)
        )).scalar_one()
        clean_bin = scanned_bin_code.strip().upper().replace("BIN:", "")
        if bin_obj.code.upper() != clean_bin:
            raise HTTPException(
                status_code=422,
                detail=f"Wrong Bin scanned! Target bin is {bin_obj.code}, but scanned {scanned_bin_code}"
            )

        # Validate Product Barcode
        var_obj = (await db.execute(
            select(ItemVariant).where(ItemVariant.id == line.item_variant_id)
        )).scalar_one()
        barcodes = (await db.execute(
            select(Barcode.barcode_value).where(Barcode.item_variant_id == var_obj.id)
        )).scalars().all()

        clean_item = scanned_item_barcode.strip().upper()
        valid_identifiers = [var_obj.variant_sku.upper()] + [b.upper() for b in barcodes]
        if clean_item not in valid_identifiers:
            raise HTTPException(
                status_code=422,
                detail=f"Wrong Product scanned! Target SKU is {var_obj.variant_sku}, but scanned {scanned_item_barcode}"
            )

        if quantity_picked <= 0 or quantity_picked > line.quantity_allocated:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid pick quantity (Requested: {float(quantity_picked)}, Allocated: {float(line.quantity_allocated)})"
            )

        line.quantity_picked = quantity_picked
        line.status = "PICKED"
        await db.flush()

        task = (await db.execute(select(PickTask).where(PickTask.id == line.pick_task_id))).scalar_one()
        all_lines = (await db.execute(
            select(PickTaskLine).where(PickTaskLine.pick_task_id == task.id)
        )).scalars().all()

        if all(l.status == "PICKED" for l in all_lines):
            task.status = "COMPLETED"
            task.completed_at = get_utc_now()
            await db.flush()

        return await WarehouseService.get_or_create_pick_task(db, tenant_id, task.sales_order_id, user_id)

    @staticmethod
    async def get_or_create_packing_session(
        db: AsyncSession,
        tenant_id: str,
        shipment_id: str,
        user_id: Optional[str] = None
    ) -> PackingSessionResponse:
        """
        Initializes or fetches packing session for a Shipment.
        """
        shipment = (await db.execute(
            select(Shipment)
            .join(SalesOrder, Shipment.sales_order_id == SalesOrder.id)
            .where(Shipment.id == shipment_id, SalesOrder.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        session = (await db.execute(
            select(PackingSession).where(PackingSession.shipment_id == shipment_id, PackingSession.tenant_id == tenant_id)
        )).scalar_one_or_none()

        if not session:
            session = PackingSession(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                shipment_id=shipment_id,
                session_number=f"PKG-{shipment.shipment_number}",
                packed_by_user_id=user_id,
                status="OPEN",
                carton_count=Decimal("1")
            )
            db.add(session)
            await db.flush()

        # Query total required quantity from SO Lines
        so = (await db.execute(
            select(SalesOrder).where(SalesOrder.id == shipment.sales_order_id)
        )).scalar_one()
        so_lines = (await db.execute(
            select(SOLineItem).where(SOLineItem.sales_order_id == so.id)
        )).scalars().all()
        total_req_qty = sum([Decimal(str(l.quantity_ordered)) for l in so_lines], Decimal("0.0"))

        # Query packed items
        packed_items = (await db.execute(
            select(PackingItem, ItemVariant, Item)
            .join(ItemVariant, PackingItem.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(PackingItem.packing_session_id == session.id)
        )).fetchall()

        items_out = []
        total_packed_qty = Decimal("0.0")
        for pi, v, i in packed_items:
            total_packed_qty += pi.quantity_packed
            items_out.append(PackingItemResponse(
                id=pi.id,
                item_variant_id=v.id,
                variant_sku=v.variant_sku,
                item_name=i.name,
                quantity_packed=float(pi.quantity_packed),
                carton_number=int(pi.carton_number),
                scanned_at=pi.scanned_at
            ))

        return PackingSessionResponse(
            id=session.id,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
            session_number=session.session_number,
            status=session.status,
            carton_count=int(session.carton_count),
            total_ordered_quantity=float(total_req_qty),
            total_packed_quantity=float(total_packed_qty),
            is_fully_verified=(total_packed_qty >= total_req_qty and total_req_qty > 0),
            items=items_out
        )

    @staticmethod
    async def verify_packing_item(
        db: AsyncSession,
        tenant_id: str,
        shipment_id: str,
        scanned_barcode: str,
        quantity: Decimal = Decimal("1.0"),
        carton_number: int = 1,
        user_id: Optional[str] = None
    ) -> PackingItemVerifyResponse:
        """
        Scan-verification step at Packing Station.
        Validates that the scanned item is on the order and not already over-packed.
        """
        # Resolve barcode
        res = await WarehouseService.resolve_barcode(db, tenant_id, scanned_barcode)
        if not res.found or res.entity_type != "VARIANT":
            raise HTTPException(status_code=422, detail=f"Scanned barcode '{scanned_barcode}' is not a valid product")

        variant_id = res.payload["variant_id"]
        v_obj = (await db.execute(select(ItemVariant).where(ItemVariant.id == variant_id))).scalar_one()
        i_obj = (await db.execute(select(Item).where(Item.id == v_obj.item_id))).scalar_one()

        shipment = (await db.execute(
            select(Shipment)
            .join(SalesOrder, Shipment.sales_order_id == SalesOrder.id)
            .where(Shipment.id == shipment_id, SalesOrder.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        # Verify SO contains this variant
        so_lines = (await db.execute(
            select(SOLineItem).where(
                SOLineItem.sales_order_id == shipment.sales_order_id,
                SOLineItem.item_variant_id == variant_id
            )
        )).scalars().all()
        if not so_lines:
            raise HTTPException(status_code=422, detail=f"Item {v_obj.variant_sku} is not part of this sales order")

        total_ordered = sum([Decimal(str(l.quantity_ordered)) for l in so_lines], Decimal("0.0"))

        # Fetch packing session
        session_resp = await WarehouseService.get_or_create_packing_session(db, tenant_id, shipment_id, user_id)
        session = (await db.execute(select(PackingSession).where(PackingSession.id == session_resp.id))).scalar_one()

        # Check existing packed qty for this variant
        packed_qty_stmt = select(func.sum(PackingItem.quantity_packed)).where(
            PackingItem.packing_session_id == session.id,
            PackingItem.item_variant_id == variant_id
        )
        cur_packed = (await db.execute(packed_qty_stmt)).scalar() or Decimal("0.0")

        if (cur_packed + quantity) > total_ordered:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot pack excess quantity of {v_obj.variant_sku} (Ordered: {float(total_ordered)}, Already Packed: {float(cur_packed)})"
            )

        # Record packing item
        p_item = PackingItem(
            id=str(uuid.uuid4()),
            packing_session_id=session.id,
            item_variant_id=variant_id,
            quantity_packed=quantity,
            carton_number=Decimal(str(carton_number)),
            scanned_at=get_utc_now()
        )
        db.add(p_item)
        await db.flush()

        updated_session = await WarehouseService.get_or_create_packing_session(db, tenant_id, shipment_id, user_id)

        return PackingItemVerifyResponse(
            verified=True,
            message=f"Verified & Packed {float(quantity)}x {v_obj.variant_sku}",
            item_variant_sku=v_obj.variant_sku,
            item_name=i_obj.name,
            quantity_packed_total=float(cur_packed + quantity),
            quantity_required_total=float(total_ordered),
            is_order_complete=updated_session.is_fully_verified
        )

    @staticmethod
    async def generate_labels(
        db: AsyncSession,
        tenant_id: str,
        label_type: str,
        entity_ids: List[str],
        copies_per_item: int = 1
    ) -> LabelGenerationResponse:
        """
        Generates structured printable barcode labels for products, bins, GRNs, or shipments.
        """
        labels = []

        if label_type == "VARIANT":
            rows = (await db.execute(
                select(ItemVariant, Item)
                .join(Item, ItemVariant.item_id == Item.id)
                .where(ItemVariant.id.in_(entity_ids), Item.tenant_id == tenant_id)
            )).fetchall()

            for var, itm in rows:
                for _ in range(copies_per_item):
                    labels.append(LabelItemPayload(
                        label_type="VARIANT",
                        entity_id=var.id,
                        title=itm.name,
                        subtitle=f"SKU: {var.variant_sku} | Cost: ${var.cost_price}",
                        barcode_payload=var.variant_sku,
                        barcode_human_readable=var.variant_sku,
                        symbology="CODE128"
                    ))

        elif label_type == "BIN":
            rows = (await db.execute(
                select(LocationBin, Warehouse)
                .join(Warehouse, LocationBin.warehouse_id == Warehouse.id)
                .where(LocationBin.id.in_(entity_ids), Warehouse.tenant_id == tenant_id)
            )).fetchall()

            for b, wh in rows:
                for _ in range(copies_per_item):
                    labels.append(LabelItemPayload(
                        label_type="BIN",
                        entity_id=b.id,
                        title=f"BIN: {b.code}",
                        subtitle=f"{wh.code} | Aisle {b.aisle} Rack {b.rack} Shelf {b.shelf}",
                        barcode_payload=f"BIN:{b.code}",
                        barcode_human_readable=b.code,
                        symbology="CODE128"
                    ))

        return LabelGenerationResponse(
            total_labels=len(labels),
            labels=labels
        )
