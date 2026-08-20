import uuid
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.traceability import StockLot, ItemSerialNumber
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant
from app.models.ledger import StockBalanceCache, StockLedgerTransaction, StockLedgerEntry
from app.models.purchasing import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, POLineItem, Supplier
from app.models.sales import Shipment, SalesOrder, SOLineItem, Customer
from app.models.costing import CostLayer
from app.schemas.traceability import (
    StockLotCreate,
    StockLotUpdate,
    StockLotResponse,
    ItemSerialNumberCreate,
    ItemSerialNumberResponse,
    SerialBatchRegistrationRequest,
    ForwardTraceResponse,
    ForwardTraceShipmentItem,
    BackwardTraceResponse,
    RecallExecutionRequest,
    RecallExecutionResponse,
    ExpiryHorizonItem,
    ExpiryHorizonResponse,
    FEFOPickRecommendationItem,
    FEFOPickRecommendationResponse
)
from app.services.audit_service import AuditService

class TraceabilityService:
    # ============================================================================
    # STOCK LOTS
    # ============================================================================

    @staticmethod
    async def create_or_get_lot(
        db: AsyncSession,
        tenant_id: str,
        lot_in: StockLotCreate,
        user_id: Optional[str] = None
    ) -> StockLot:
        """
        Retrieves existing lot or creates a new authoritative StockLot.
        """
        stmt = (
            select(StockLot)
            .where(
                StockLot.tenant_id == tenant_id,
                StockLot.item_variant_id == lot_in.item_variant_id,
                StockLot.lot_number == lot_in.lot_number.strip()
            )
            .with_for_update()
        )
        res = await db.execute(stmt)
        lot = res.scalar_one_or_none()

        if lot:
            if lot_in.initial_quantity > 0:
                lot.current_quantity = Decimal(str(lot.current_quantity)) + lot_in.initial_quantity
                lot.initial_quantity = Decimal(str(lot.initial_quantity)) + lot_in.initial_quantity
            return lot

        lot = StockLot(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            item_variant_id=lot_in.item_variant_id,
            lot_number=lot_in.lot_number.strip(),
            supplier_id=lot_in.supplier_id,
            supplier_lot_number=lot_in.supplier_lot_number,
            origin_grn_id=lot_in.origin_grn_id,
            manufacturing_date=lot_in.manufacturing_date,
            expiry_date=lot_in.expiry_date,
            best_before_date=lot_in.best_before_date,
            initial_quantity=lot_in.initial_quantity,
            current_quantity=lot_in.initial_quantity,
            status="ACTIVE",
            notes=lot_in.notes
        )
        db.add(lot)
        await db.flush()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_LOT",
            entity_type="StockLot",
            entity_id=lot.id,
            user_id=user_id,
            changes={"lot_number": lot.lot_number, "variant_id": lot.item_variant_id}
        )
        return lot

    # ============================================================================
    # SERIAL NUMBERS
    # ============================================================================

    @staticmethod
    async def register_serial_numbers(
        db: AsyncSession,
        tenant_id: str,
        req: SerialBatchRegistrationRequest,
        user_id: Optional[str] = None
    ) -> List[ItemSerialNumber]:
        """
        Batch registers unit serial numbers during receiving or assembly.
        Validates uniqueness across the tenant and item variant.
        """
        created_serials = []
        for s_num in req.serial_numbers:
            s_clean = s_num.strip()
            # Check duplicate active serial
            stmt = select(ItemSerialNumber).where(
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.item_variant_id == req.item_variant_id,
                ItemSerialNumber.serial_number == s_clean
            ).with_for_update()
            existing = (await db.execute(stmt)).scalar_one_or_none()

            if existing and existing.status not in ["RETIRED", "RETURNED_TO_SUPPLIER"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Serial number '{s_clean}' already exists in status '{existing.status}' in warehouse {existing.warehouse_id}"
                )

            if existing:
                # Re-activate retired serial
                existing.warehouse_id = req.warehouse_id
                existing.lot_id = req.lot_id
                existing.status = "RECEIVED"
                existing.location_bin_id = req.location_bin_id
                existing.origin_grn_id = req.origin_grn_id
                existing.dispatched_shipment_id = None
                created_serials.append(existing)
            else:
                serial = ItemSerialNumber(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    warehouse_id=req.warehouse_id,
                    item_variant_id=req.item_variant_id,
                    lot_id=req.lot_id,
                    serial_number=s_clean,
                    status="RECEIVED",
                    location_bin_id=req.location_bin_id,
                    origin_grn_id=req.origin_grn_id
                )
                db.add(serial)
                created_serials.append(serial)

        await db.flush()
        return created_serials

    @staticmethod
    async def update_serial_bin_locations(
        db: AsyncSession,
        tenant_id: str,
        item_variant_id: str,
        source_bin_id: str,
        dest_bin_id: str,
        quantity: int,
        serial_numbers: Optional[List[str]] = None,
        target_status: str = "IN_STOCK"
    ):
        """
        Updates serial location bins during putaway or bin-to-bin transfers.
        """
        if serial_numbers:
            stmt = (
                select(ItemSerialNumber)
                .where(
                    ItemSerialNumber.tenant_id == tenant_id,
                    ItemSerialNumber.item_variant_id == item_variant_id,
                    ItemSerialNumber.location_bin_id == source_bin_id,
                    ItemSerialNumber.serial_number.in_(serial_numbers)
                )
                .with_for_update()
            )
        else:
            stmt = (
                select(ItemSerialNumber)
                .where(
                    ItemSerialNumber.tenant_id == tenant_id,
                    ItemSerialNumber.item_variant_id == item_variant_id,
                    ItemSerialNumber.location_bin_id == source_bin_id
                )
                .limit(quantity)
                .with_for_update()
            )
        serials = (await db.execute(stmt)).scalars().all()
        for s in serials:
            s.location_bin_id = dest_bin_id
            s.status = target_status
        await db.flush()

    VALID_SERIAL_TRANSITIONS = {
        "RECEIVED": {"IN_STOCK", "QUARANTINED"},
        "IN_STOCK": {"ALLOCATED", "PICKED", "QUARANTINED", "RETURNED_TO_SUPPLIER", "RETIRED"},
        "ALLOCATED": {"IN_STOCK", "PICKED", "QUARANTINED"},
        "PICKED": {"IN_STOCK", "ALLOCATED", "DISPATCHED", "QUARANTINED"},
        "DISPATCHED": {"RETURNED"},
        "RETURNED": {"IN_STOCK", "QUARANTINED"},
        "QUARANTINED": {"IN_STOCK", "RETURNED_TO_SUPPLIER", "RETIRED"},
        "RETURNED_TO_SUPPLIER": set(),
        "RETIRED": set(),
    }

    @classmethod
    def validate_lifecycle_transition(cls, current_status: str, target_status: str, serial_number: str):
        allowed = cls.VALID_SERIAL_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid serial lifecycle transition for '{serial_number}': '{current_status}' -> '{target_status}'. Allowed transitions: {sorted(list(allowed)) or 'None'}"
            )

    @classmethod
    async def transition_serial_status(
        cls,
        db: AsyncSession,
        tenant_id: str,
        serial_number: str,
        target_status: str,
        location_bin_id: Optional[str] = None,
        dispatched_shipment_id: Optional[str] = None,
        quarantine_reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> ItemSerialNumber:
        """
        Atomically validates and transitions serial status under row-level lock.
        """
        stmt = (
            select(ItemSerialNumber)
            .where(
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.serial_number == serial_number.strip()
            )
            .with_for_update()
        )
        serial = (await db.execute(stmt)).scalar_one_or_none()
        if not serial:
            raise HTTPException(status_code=404, detail=f"Serial number '{serial_number}' not found")

        cls.validate_lifecycle_transition(serial.status, target_status, serial.serial_number)

        old_status = serial.status
        serial.status = target_status
        if location_bin_id is not None:
            serial.location_bin_id = location_bin_id
        if dispatched_shipment_id is not None:
            serial.dispatched_shipment_id = dispatched_shipment_id
        if quarantine_reason is not None:
            serial.quarantine_reason = quarantine_reason
        if target_status == "DISPATCHED":
            serial.location_bin_id = None

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SERIAL_STATUS_CHANGE",
            entity_type="ItemSerialNumber",
            entity_id=serial.id,
            user_id=user_id,
            changes={"serial_number": serial.serial_number, "from_status": old_status, "to_status": target_status}
        )
        await db.flush()
        return serial

    @classmethod
    async def acquire_serial_for_pick(
        cls,
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        serial_number: str,
        user_id: Optional[str] = None
    ) -> ItemSerialNumber:
        """
        Atomically acquires a serial for picking under pessimistic row lock.
        Validates that the serial is in IN_STOCK or ALLOCATED status.
        Transitions to PICKED.
        """
        stmt = (
            select(ItemSerialNumber)
            .where(
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.warehouse_id == warehouse_id,
                ItemSerialNumber.item_variant_id == item_variant_id,
                ItemSerialNumber.serial_number == serial_number.strip()
            )
            .with_for_update()
        )
        serial = (await db.execute(stmt)).scalar_one_or_none()
        if not serial:
            raise HTTPException(status_code=404, detail=f"Serial '{serial_number}' not found in warehouse")

        if serial.status not in ["IN_STOCK", "ALLOCATED"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Serial '{serial_number}' cannot be picked: currently in status '{serial.status}'"
            )

        serial.status = "PICKED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PICK_SERIAL",
            entity_type="ItemSerialNumber",
            entity_id=serial.id,
            user_id=user_id,
            changes={"serial_number": serial.serial_number, "status": "PICKED"}
        )
        await db.flush()
        return serial

    @classmethod
    async def dispatch_serials(
        cls,
        db: AsyncSession,
        tenant_id: str,
        shipment_id: str,
        serial_numbers: List[str],
        user_id: Optional[str] = None
    ):
        """
        Transitions picked serials to DISPATCHED and binds to shipment.
        """
        stmt = (
            select(ItemSerialNumber)
            .where(
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.serial_number.in_(serial_numbers)
            )
            .with_for_update()
        )
        serials = (await db.execute(stmt)).scalars().all()
        if len(serials) != len(serial_numbers):
            found = set(s.serial_number for s in serials)
            missing = set(serial_numbers) - found
            raise HTTPException(status_code=404, detail=f"Serial numbers not found: {missing}")

        for s in serials:
            cls.validate_lifecycle_transition(s.status, "DISPATCHED", s.serial_number)
            s.status = "DISPATCHED"
            s.location_bin_id = None
            s.dispatched_shipment_id = shipment_id

            await AuditService.log_action(
                db=db,
                tenant_id=tenant_id,
                action="DISPATCH_SERIAL",
                entity_type="ItemSerialNumber",
                entity_id=s.id,
                user_id=user_id,
                changes={"serial_number": s.serial_number, "shipment_id": shipment_id}
            )
        await db.flush()

    # ============================================================================
    # QUARANTINE & RECALL
    # ============================================================================

    @staticmethod
    async def quarantine_lot(
        db: AsyncSession,
        tenant_id: str,
        lot_id: str,
        reason: str,
        user_id: Optional[str] = None
    ) -> StockLot:
        """
        Puts an entire lot and its serial numbers into QUARANTINED status.
        """
        lot = (await db.execute(
            select(StockLot).where(StockLot.id == lot_id, StockLot.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not lot:
            raise HTTPException(status_code=404, detail="Stock Lot not found")

        lot.status = "QUARANTINED"
        lot.quarantine_reason = reason

        # Quarantine all associated serials currently in warehouse
        serials = (await db.execute(
            select(ItemSerialNumber).where(
                ItemSerialNumber.lot_id == lot.id,
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.status.in_(["RECEIVED", "IN_STOCK", "ALLOCATED", "RETURNED"])
            ).with_for_update()
        )).scalars().all()

        for s in serials:
            s.status = "QUARANTINED"
            s.quarantine_reason = reason

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="QUARANTINE_LOT",
            entity_type="StockLot",
            entity_id=lot.id,
            user_id=user_id,
            changes={"status": "QUARANTINED", "reason": reason}
        )
        await db.commit()
        await db.refresh(lot)
        return lot

    @staticmethod
    async def execute_lot_recall(
        db: AsyncSession,
        tenant_id: str,
        req: RecallExecutionRequest,
        user_id: Optional[str] = None
    ) -> RecallExecutionResponse:
        """
        Executes a 1-Click recall containment for a defective lot:
        1. Transitions lot status to RECALLED
        2. Quarantines all in-warehouse serials
        3. Identifies all affected customer shipments
        4. Compiles containment summary
        """
        lot = (await db.execute(
            select(StockLot).where(StockLot.id == req.lot_id, StockLot.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not lot:
            raise HTTPException(status_code=404, detail="Stock Lot not found")

        lot.status = "RECALLED"
        lot.quarantine_reason = req.recall_reason

        # Quarantine in-warehouse serials
        serials = (await db.execute(
            select(ItemSerialNumber).where(
                ItemSerialNumber.lot_id == lot.id,
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.status.in_(["RECEIVED", "IN_STOCK", "ALLOCATED", "RETURNED"])
            ).with_for_update()
        )).scalars().all()

        for s in serials:
            s.status = "QUARANTINED"
            s.quarantine_reason = f"RECALL: {req.recall_reason}"
            if req.target_quarantine_bin_id:
                s.location_bin_id = req.target_quarantine_bin_id

        # Count affected customer shipments
        dispatched_serials = (await db.execute(
            select(ItemSerialNumber).where(
                ItemSerialNumber.lot_id == lot.id,
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.status == "DISPATCHED"
            )
        )).scalars().all()

        shipment_ids = list(set([s.dispatched_shipment_id for s in dispatched_serials if s.dispatched_shipment_id]))
        cust_cnt = 0
        if shipment_ids:
            cust_stmt = select(func.count(func.distinct(SalesOrder.customer_id))).join(Shipment, Shipment.sales_order_id == SalesOrder.id).where(Shipment.id.in_(shipment_ids))
            cust_cnt = (await db.execute(cust_stmt)).scalar() or 0

        var = (await db.execute(select(ItemVariant).where(ItemVariant.id == lot.item_variant_id))).scalar_one()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="RECALL_LOT",
            entity_type="StockLot",
            entity_id=lot.id,
            user_id=user_id,
            changes={"status": "RECALLED", "reason": req.recall_reason}
        )

        await db.commit()
        await db.refresh(lot)

        return RecallExecutionResponse(
            lot_id=lot.id,
            lot_number=lot.lot_number,
            variant_sku=var.variant_sku,
            status=lot.status,
            recalled_at=get_utc_now(),
            quarantined_units_count=float(lot.current_quantity),
            quarantined_serials_count=len(serials),
            affected_customers_count=cust_cnt,
            downloadable_containment_manifest_url=f"/api/v1/traceability/recalls/{lot.id}/manifest"
        )

    # ============================================================================
    # FORWARD & BACKWARD TRACEABILITY
    # ============================================================================

    @staticmethod
    async def get_forward_trace(
        db: AsyncSession,
        tenant_id: str,
        lot_id: str
    ) -> ForwardTraceResponse:
        """
        Forward trace: Supplier / Lot -> Warehouse Bins -> Outbound Shipments -> End Customers.
        """
        lot = (await db.execute(
            select(StockLot).where(StockLot.id == lot_id, StockLot.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not lot:
            raise HTTPException(status_code=404, detail="Stock Lot not found")

        var = (await db.execute(select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == lot.item_variant_id))).first()
        variant, item = var

        supp_name = lot.supplier.name if lot.supplier else "N/A"

        # Query bins holding this lot
        bal_stmt = (
            select(StockBalanceCache, Warehouse, LocationBin)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .where(StockBalanceCache.lot_id == lot.id, StockBalanceCache.quantity_on_hand > 0)
        )
        bal_rows = (await db.execute(bal_stmt)).fetchall()
        wh_locs = [
            {
                "warehouse_name": wh.name,
                "bin_code": bin_obj.code,
                "bin_type": bin_obj.type,
                "quantity_on_hand": float(b.quantity_on_hand)
            }
            for b, wh, bin_obj in bal_rows
        ]

        # Query dispatched shipments
        serials_dispatched = (await db.execute(
            select(ItemSerialNumber).where(
                ItemSerialNumber.lot_id == lot.id,
                ItemSerialNumber.status == "DISPATCHED",
                ItemSerialNumber.tenant_id == tenant_id
            )
        )).scalars().all()

        shipment_map: Dict[str, List[str]] = {}
        for s in serials_dispatched:
            if s.dispatched_shipment_id:
                if s.dispatched_shipment_id not in shipment_map:
                    shipment_map[s.dispatched_shipment_id] = []
                shipment_map[s.dispatched_shipment_id].append(s.serial_number)

        shipments_out = []
        tot_dispatched = Decimal("0.0")

        if shipment_map:
            ship_stmt = (
                select(Shipment, SalesOrder, Customer)
                .join(SalesOrder, Shipment.sales_order_id == SalesOrder.id)
                .join(Customer, SalesOrder.customer_id == Customer.id)
                .where(Shipment.id.in_(list(shipment_map.keys())))
            )
            ship_rows = (await db.execute(ship_stmt)).fetchall()

            for shp, so, cust in ship_rows:
                s_list = shipment_map.get(shp.id, [])
                qty = Decimal(str(len(s_list))) if s_list else Decimal("1.0")
                tot_dispatched += qty
                shipments_out.append(ForwardTraceShipmentItem(
                    shipment_id=shp.id,
                    shipment_number=shp.shipment_number,
                    sales_order_id=so.id,
                    so_number=so.so_number,
                    customer_id=cust.id,
                    customer_name=cust.name,
                    dispatched_at=shp.shipped_at or shp.created_at,
                    quantity_shipped=float(qty),
                    serials_dispatched=s_list
                ))

        return ForwardTraceResponse(
            lot_id=lot.id,
            lot_number=lot.lot_number,
            variant_sku=variant.variant_sku,
            item_name=item.name,
            supplier_name=supp_name,
            total_received_quantity=float(lot.initial_quantity),
            current_warehouse_quantity=float(lot.current_quantity),
            total_dispatched_quantity=float(tot_dispatched),
            warehouse_locations=wh_locs,
            affected_shipments=shipments_out,
            generated_at=get_utc_now()
        )

    @staticmethod
    async def get_backward_trace(
        db: AsyncSession,
        tenant_id: str,
        identifier: str
    ) -> BackwardTraceResponse:
        """
        Backward trace: Shipment / Serial -> Sales Order -> Stock Lot -> GRN -> PO -> Supplier.
        """
        # Try serial lookup first
        serial_stmt = (
            select(ItemSerialNumber, ItemVariant, Item)
            .join(ItemVariant, ItemSerialNumber.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(
                ItemSerialNumber.tenant_id == tenant_id,
                ItemSerialNumber.serial_number == identifier.strip()
            )
        )
        serial_res = await db.execute(serial_stmt)
        serial_row = serial_res.first()

        if serial_row:
            s, var, it = serial_row
            lot_num = s.lot.lot_number if s.lot else None
            grn_num = s.origin_grn.grn_number if s.origin_grn else None
            rec_at = s.origin_grn.received_at if s.origin_grn else None
            po_num = s.origin_grn.purchase_order.po_number if s.origin_grn and s.origin_grn.purchase_order else None
            sup_code = s.origin_grn.purchase_order.supplier.code if s.origin_grn and s.origin_grn.purchase_order and s.origin_grn.purchase_order.supplier else None
            sup_name = s.origin_grn.purchase_order.supplier.name if s.origin_grn and s.origin_grn.purchase_order and s.origin_grn.purchase_order.supplier else None

            shp_num = s.shipment.shipment_number if s.shipment else None
            so_num = s.shipment.sales_order.so_number if s.shipment and s.shipment.sales_order else None
            cust_name = s.shipment.sales_order.customer.name if s.shipment and s.shipment.sales_order and s.shipment.sales_order.customer else None

            return BackwardTraceResponse(
                searched_identifier=identifier,
                variant_sku=var.variant_sku,
                item_name=it.name,
                serial_number=s.serial_number,
                lot_number=lot_num,
                shipment_number=shp_num,
                so_number=so_num,
                customer_name=cust_name,
                grn_number=grn_num,
                received_at=rec_at,
                po_number=po_num,
                supplier_code=sup_code,
                supplier_name=sup_name,
                generated_at=get_utc_now()
            )

        raise HTTPException(status_code=404, detail=f"No traceability records found matching identifier '{identifier}'")

    # ============================================================================
    # EXPIRY & FEFO RECOMMENDATIONS
    # ============================================================================

    @staticmethod
    async def get_expiry_horizon(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> ExpiryHorizonResponse:
        """
        Evaluates active lots and classifies into expiry buckets (EXPIRED, CRITICAL_30D, WARNING_60D, NORMAL_90D).
        """
        now = get_utc_now().date()
        
        stmt = (
            select(StockLot, ItemVariant, Item, StockBalanceCache, Warehouse, LocationBin)
            .join(ItemVariant, StockLot.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .join(StockBalanceCache, StockLot.id == StockBalanceCache.lot_id)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .where(
                StockLot.tenant_id == tenant_id,
                StockLot.expiry_date != None,
                StockBalanceCache.quantity_on_hand > 0
            )
        )
        if warehouse_id:
            stmt = stmt.where(StockBalanceCache.warehouse_id == warehouse_id)

        rows = (await db.execute(stmt)).fetchall()

        items_out = []
        exp_cnt = 0
        crit_cnt = 0
        warn_cnt = 0

        for lot, var, it, bal, wh, bin_obj in rows:
            days_left = (lot.expiry_date - now).days
            if days_left < 0:
                cls = "EXPIRED"
                exp_cnt += 1
            elif days_left <= 30:
                cls = "CRITICAL_30D"
                crit_cnt += 1
            elif days_left <= 60:
                cls = "WARNING_60D"
                warn_cnt += 1
            else:
                cls = "NORMAL_90D"

            items_out.append(ExpiryHorizonItem(
                lot_id=lot.id,
                lot_number=lot.lot_number,
                variant_sku=var.variant_sku,
                item_name=it.name,
                warehouse_id=wh.id,
                warehouse_name=wh.name,
                location_bin_code=bin_obj.code,
                quantity_on_hand=float(bal.quantity_on_hand),
                expiry_date=lot.expiry_date,
                days_until_expiry=days_left,
                expiry_classification=cls
            ))

        items_out.sort(key=lambda x: x.days_until_expiry)

        return ExpiryHorizonResponse(
            total_lots_evaluated=len(items_out),
            expired_lots_count=exp_cnt,
            critical_30d_count=crit_cnt,
            warning_60d_count=warn_cnt,
            lots=items_out,
            generated_at=get_utc_now()
        )

    @staticmethod
    async def get_fefo_pick_recommendations(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        required_quantity: Decimal
    ) -> FEFOPickRecommendationResponse:
        """
        Recommends physical picking sequence based on First-Expired, First-Out (FEFO).
        """
        stmt = (
            select(StockLot, StockBalanceCache, LocationBin)
            .join(StockBalanceCache, StockLot.id == StockBalanceCache.lot_id)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .where(
                StockLot.tenant_id == tenant_id,
                StockBalanceCache.warehouse_id == warehouse_id,
                StockBalanceCache.item_variant_id == item_variant_id,
                StockLot.status == "ACTIVE",
                LocationBin.type.notin_(["QUARANTINE", "DAMAGE"]),
                StockBalanceCache.quantity_on_hand > StockBalanceCache.quantity_allocated
            )
            .order_by(
                StockLot.expiry_date.asc().nulls_last(),
                StockLot.created_at.asc(),
                LocationBin.code.asc()
            )
        )
        rows = (await db.execute(stmt)).fetchall()

        recs = []
        rem_needed = required_quantity
        seq = 1

        for lot, bal, bin_obj in rows:
            avail = bal.quantity_on_hand - bal.quantity_allocated
            if avail <= 0:
                continue

            pick_qty = min(rem_needed, avail)
            recs.append(FEFOPickRecommendationItem(
                lot_id=lot.id,
                lot_number=lot.lot_number,
                location_bin_id=bin_obj.id,
                location_bin_code=bin_obj.code,
                available_quantity=float(avail),
                expiry_date=lot.expiry_date,
                recommended_pick_quantity=float(pick_qty),
                pick_priority_sequence=seq
            ))
            seq += 1
            rem_needed -= pick_qty
            if rem_needed <= 0:
                break

        var = (await db.execute(select(ItemVariant).where(ItemVariant.id == item_variant_id))).scalar_one()

        return FEFOPickRecommendationResponse(
            item_variant_id=item_variant_id,
            variant_sku=var.variant_sku,
            required_quantity=float(required_quantity),
            recommendations=recs,
            generated_at=get_utc_now()
        )
