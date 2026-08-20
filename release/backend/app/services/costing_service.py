import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.costing import CostLayer, CostLayerConsumption, ItemCostProfile, CostTransaction, COGSRecord
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockLedgerTransaction, StockBalanceCache
from app.models.sales import SalesOrder, Shipment
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService

def quantize_decimal(value: Decimal, places: int = 4) -> Decimal:
    """Quantizes decimal to specified places using standard financial ROUND_HALF_UP."""
    exp = Decimal(10) ** -places
    return Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_UP)

class CostingService:
    @staticmethod
    async def get_or_create_cost_profile(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str
    ) -> ItemCostProfile:
        """
        Retrieves or initializes the ItemCostProfile for a given warehouse and item variant.
        Locks with SELECT FOR UPDATE.
        """
        stmt = (
            select(ItemCostProfile)
            .where(
                ItemCostProfile.tenant_id == tenant_id,
                ItemCostProfile.warehouse_id == warehouse_id,
                ItemCostProfile.item_variant_id == item_variant_id
            )
            .with_for_update()
        )
        res = await db.execute(stmt)
        profile = res.scalar_one_or_none()

        if not profile:
            var_stmt = (
                select(ItemVariant, Item)
                .join(Item, ItemVariant.item_id == Item.id)
                .where(ItemVariant.id == item_variant_id, Item.tenant_id == tenant_id)
            )
            var_res = await db.execute(var_stmt)
            row = var_res.first()
            if not row:
                raise HTTPException(status_code=404, detail=f"Item variant {item_variant_id} not found in tenant")
            variant, item = row

            method = item.valuation_method if item.valuation_method in ["FIFO", "WEIGHTED_AVERAGE", "STANDARD_COST"] else "FIFO"
            std_cost = Decimal(str(variant.cost_price or 0.0))

            profile = ItemCostProfile(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                item_variant_id=item_variant_id,
                costing_method=method,
                current_quantity=Decimal("0.0"),
                current_total_value=Decimal("0.0"),
                moving_average_cost=std_cost,
                standard_cost=std_cost,
                last_cost_recalculated_at=get_utc_now()
            )
            db.add(profile)
            await db.flush()

        return profile

    @staticmethod
    async def record_inbound_receipt(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        quantity: Decimal,
        unit_cost: Decimal,
        stock_transaction_id: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> CostTransaction:
        """
        Records an inbound inventory acquisition cost transaction:
        - Creates a new CostLayer for FIFO tracking.
        - Updates the running ItemCostProfile (quantity, total value, moving average cost).
        """
        qty = quantize_decimal(Decimal(str(quantity)))
        cost = quantize_decimal(Decimal(str(unit_cost)))
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Inbound costing quantity must be strictly positive: {qty}")
        if cost < 0:
            raise HTTPException(status_code=400, detail=f"Unit cost cannot be negative: {cost}")

        profile = await CostingService.get_or_create_cost_profile(db, tenant_id, warehouse_id, item_variant_id)
        total_inbound_cost = quantize_decimal(qty * cost)

        tx_number = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
        cost_tx = CostTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            stock_transaction_id=stock_transaction_id,
            cost_transaction_number=tx_number,
            transaction_type="RECEIPT_COST",
            warehouse_id=warehouse_id,
            item_variant_id=item_variant_id,
            quantity=qty,
            unit_cost=cost,
            total_cost_impact=total_inbound_cost,
            costing_method=profile.costing_method,
            posted_at=get_utc_now(),
            posted_by_user_id=user_id,
            notes=notes
        )
        db.add(cost_tx)

        # 1. Create active FIFO CostLayer
        layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER")
        layer = CostLayer(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            item_variant_id=item_variant_id,
            origin_transaction_id=stock_transaction_id,
            layer_number=layer_num,
            original_quantity=qty,
            remaining_quantity=qty,
            unit_cost=cost,
            total_cost=total_inbound_cost,
            status="ACTIVE",
            layer_timestamp=get_utc_now(),
            notes=notes
        )
        db.add(layer)

        # 2. Update Moving Weighted Average & Running Totals in Profile
        curr_qty = Decimal(str(profile.current_quantity))
        curr_val = Decimal(str(profile.current_total_value))

        new_qty = curr_qty + qty
        new_val = quantize_decimal(curr_val + total_inbound_cost)
        new_avg = quantize_decimal(new_val / new_qty) if new_qty > 0 else cost

        profile.current_quantity = new_qty
        profile.current_total_value = new_val
        profile.moving_average_cost = new_avg
        profile.last_cost_recalculated_at = get_utc_now()

        await db.flush()
        return cost_tx

    @staticmethod
    async def record_outbound_dispatch(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        quantity: Decimal,
        sales_order_id: str,
        shipment_id: str,
        stock_transaction_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Tuple[CostTransaction, COGSRecord]:
        """
        Executes outbound consumption and creates an immutable COGS record:
        - Depletes FIFO layers ordered by (layer_timestamp ASC, id ASC) or consumes at Moving Average.
        - Persists immutable CostLayerConsumption records.
        - Persists immutable COGSRecord.
        """
        qty = quantize_decimal(Decimal(str(quantity)))
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Outbound dispatch quantity must be strictly positive: {qty}")

        profile = await CostingService.get_or_create_cost_profile(db, tenant_id, warehouse_id, item_variant_id)

        tx_number = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
        cost_tx = CostTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            stock_transaction_id=stock_transaction_id,
            cost_transaction_number=tx_number,
            transaction_type="DISPATCH_COGS",
            warehouse_id=warehouse_id,
            item_variant_id=item_variant_id,
            quantity=qty,
            costing_method=profile.costing_method,
            posted_at=get_utc_now(),
            posted_by_user_id=user_id,
            notes=f"Sales Dispatch COGS for SO {sales_order_id}"
        )
        db.add(cost_tx)
        await db.flush()

        total_cogs = Decimal("0.0")

        # 1. Fetch active FIFO layers for this variant in this warehouse
        layer_stmt = (
            select(CostLayer)
            .where(
                CostLayer.tenant_id == tenant_id,
                CostLayer.warehouse_id == warehouse_id,
                CostLayer.item_variant_id == item_variant_id,
                CostLayer.status == "ACTIVE"
            )
            .order_by(CostLayer.layer_timestamp.asc(), CostLayer.id.asc())
            .with_for_update()
        )
        layer_res = await db.execute(layer_stmt)
        active_layers = layer_res.scalars().all()

        total_available_layer_qty = sum([Decimal(str(l.remaining_quantity)) for l in active_layers])

        # If FIFO costing method
        if profile.costing_method == "FIFO":
            if total_available_layer_qty < qty:
                # If uncosted stock exists (e.g. legacy opening stock without layers), fallback to profile moving average/std cost
                shortfall = qty - total_available_layer_qty
                fallback_cost = Decimal(str(profile.moving_average_cost or profile.standard_cost or 0.0))
                if shortfall > 0 and total_available_layer_qty == 0:
                    total_cogs = quantize_decimal(qty * fallback_cost)
                else:
                    # Deplete available layers, and fulfill shortfall at fallback
                    remaining_to_deplete = qty
                    for layer in active_layers:
                        rem = Decimal(str(layer.remaining_quantity))
                        if rem <= 0:
                            continue
                        consume = min(remaining_to_deplete, rem)
                        layer_unit_cost = Decimal(str(layer.unit_cost))
                        layer_cogs = quantize_decimal(consume * layer_unit_cost)
                        total_cogs += layer_cogs

                        layer.remaining_quantity = quantize_decimal(rem - consume)
                        if layer.remaining_quantity == 0:
                            layer.status = "DEPLETED"

                        db.add(CostLayerConsumption(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            cost_layer_id=layer.id,
                            cost_transaction_id=cost_tx.id,
                            quantity_consumed=consume,
                            unit_cost=layer_unit_cost,
                            total_cost=layer_cogs,
                            consumed_at=get_utc_now()
                        ))
                        remaining_to_deplete -= consume
                        if remaining_to_deplete <= 0:
                            break
                    if remaining_to_deplete > 0:
                        shortfall_cogs = quantize_decimal(remaining_to_deplete * fallback_cost)
                        total_cogs += shortfall_cogs
            else:
                remaining_to_deplete = qty
                for layer in active_layers:
                    rem = Decimal(str(layer.remaining_quantity))
                    if rem <= 0:
                        continue
                    consume = min(remaining_to_deplete, rem)
                    layer_unit_cost = Decimal(str(layer.unit_cost))
                    layer_cogs = quantize_decimal(consume * layer_unit_cost)
                    total_cogs += layer_cogs

                    layer.remaining_quantity = quantize_decimal(rem - consume)
                    if layer.remaining_quantity == 0:
                        layer.status = "DEPLETED"

                    db.add(CostLayerConsumption(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        cost_layer_id=layer.id,
                        cost_transaction_id=cost_tx.id,
                        quantity_consumed=consume,
                        unit_cost=layer_unit_cost,
                        total_cost=layer_cogs,
                        consumed_at=get_utc_now()
                    ))
                    remaining_to_deplete -= consume
                    if remaining_to_deplete <= 0:
                        break
        elif profile.costing_method == "WEIGHTED_AVERAGE":
            # Moving Weighted Average consumption at running average
            avg_unit_cost = Decimal(str(profile.moving_average_cost))
            total_cogs = quantize_decimal(qty * avg_unit_cost)

            # Deplete FIFO layers in parallel to maintain synchronization
            remaining_to_deplete = qty
            for layer in active_layers:
                rem = Decimal(str(layer.remaining_quantity))
                if rem <= 0:
                    continue
                consume = min(remaining_to_deplete, rem)
                layer.remaining_quantity = quantize_decimal(rem - consume)
                if layer.remaining_quantity == 0:
                    layer.status = "DEPLETED"

                db.add(CostLayerConsumption(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    cost_layer_id=layer.id,
                    cost_transaction_id=cost_tx.id,
                    quantity_consumed=consume,
                    unit_cost=avg_unit_cost,
                    total_cost=quantize_decimal(consume * avg_unit_cost),
                    consumed_at=get_utc_now()
                ))
                remaining_to_deplete -= consume
                if remaining_to_deplete <= 0:
                    break
        else:
            # STANDARD_COST
            std_cost = Decimal(str(profile.standard_cost))
            total_cogs = quantize_decimal(qty * std_cost)

        total_cogs = quantize_decimal(total_cogs)
        unit_cogs = quantize_decimal(total_cogs / qty) if qty > 0 else Decimal("0.0")

        cost_tx.unit_cost = unit_cogs
        cost_tx.total_cost_impact = total_cogs

        # Update profile running quantity and valuation
        profile.current_quantity = max(Decimal("0.0"), Decimal(str(profile.current_quantity)) - qty)
        profile.current_total_value = max(Decimal("0.0"), Decimal(str(profile.current_total_value)) - total_cogs)
        profile.last_cost_recalculated_at = get_utc_now()

        # Create immutable COGS Record
        cogs_record = COGSRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            sales_order_id=sales_order_id,
            shipment_id=shipment_id,
            cost_transaction_id=cost_tx.id,
            item_variant_id=item_variant_id,
            quantity_shipped=qty,
            unit_cogs=unit_cogs,
            total_cogs_amount=total_cogs,
            recognized_at=get_utc_now()
        )
        db.add(cogs_record)
        await db.flush()

        return cost_tx, cogs_record

    @staticmethod
    async def record_warehouse_transfer(
        db: AsyncSession,
        tenant_id: str,
        source_warehouse_id: str,
        dest_warehouse_id: str,
        item_variant_id: str,
        quantity: Decimal,
        stock_transaction_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Tuple[CostTransaction, CostTransaction]:
        """
        Executes cost transfer between warehouses preserving exact cost basis with zero artificial P&L:
        - FIFO: Depletes oldest layers in Source and clones matching CostLayers in Destination with provenance.
        - MWA: Transfers at source moving average and blends into destination profile.
        - Locks source and destination profiles in deterministic alphabetical order to prevent deadlocks.
        """
        qty = quantize_decimal(Decimal(str(quantity)))
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Transfer quantity must be strictly positive: {qty}")

        # Deterministic locking order
        wh_ids = sorted([source_warehouse_id, dest_warehouse_id])
        for wid in wh_ids:
            await CostingService.get_or_create_cost_profile(db, tenant_id, wid, item_variant_id)

        source_profile = await CostingService.get_or_create_cost_profile(db, tenant_id, source_warehouse_id, item_variant_id)
        dest_profile = await CostingService.get_or_create_cost_profile(db, tenant_id, dest_warehouse_id, item_variant_id)

        # Source Outbound Cost Transaction
        tx_num_out = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
        tx_out = CostTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            stock_transaction_id=stock_transaction_id,
            cost_transaction_number=tx_num_out,
            transaction_type="TRANSFER_COST_OUT",
            warehouse_id=source_warehouse_id,
            item_variant_id=item_variant_id,
            quantity=qty,
            costing_method=source_profile.costing_method,
            posted_at=get_utc_now(),
            posted_by_user_id=user_id,
            notes=f"Stock Transfer Out to warehouse {dest_warehouse_id}"
        )
        db.add(tx_out)

        # Destination Inbound Cost Transaction
        tx_num_in = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
        tx_in = CostTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            stock_transaction_id=stock_transaction_id,
            cost_transaction_number=tx_num_in,
            transaction_type="TRANSFER_COST_IN",
            warehouse_id=dest_warehouse_id,
            item_variant_id=item_variant_id,
            quantity=qty,
            costing_method=dest_profile.costing_method,
            posted_at=get_utc_now(),
            posted_by_user_id=user_id,
            notes=f"Stock Transfer In from warehouse {source_warehouse_id}"
        )
        db.add(tx_in)
        await db.flush()

        total_transfer_cost = Decimal("0.0")

        # Fetch active source layers
        src_layers_stmt = (
            select(CostLayer)
            .where(
                CostLayer.tenant_id == tenant_id,
                CostLayer.warehouse_id == source_warehouse_id,
                CostLayer.item_variant_id == item_variant_id,
                CostLayer.status == "ACTIVE"
            )
            .order_by(CostLayer.layer_timestamp.asc(), CostLayer.id.asc())
            .with_for_update()
        )
        src_layers_res = await db.execute(src_layers_stmt)
        src_layers = src_layers_res.scalars().all()

        rem_to_transfer = qty
        for s_layer in src_layers:
            rem = Decimal(str(s_layer.remaining_quantity))
            if rem <= 0:
                continue
            consume = min(rem_to_transfer, rem)
            unit_c = Decimal(str(s_layer.unit_cost))
            layer_val = quantize_decimal(consume * unit_c)
            total_transfer_cost += layer_val

            # Deplete from source layer
            s_layer.remaining_quantity = quantize_decimal(rem - consume)
            if s_layer.remaining_quantity == 0:
                s_layer.status = "DEPLETED"

            # Record source consumption
            db.add(CostLayerConsumption(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                cost_layer_id=s_layer.id,
                cost_transaction_id=tx_out.id,
                quantity_consumed=consume,
                unit_cost=unit_c,
                total_cost=layer_val,
                consumed_at=get_utc_now()
            ))

            # Inbound Clone into Destination (FIFO provenance preservation)
            dest_layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER")
            dest_layer = CostLayer(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                warehouse_id=dest_warehouse_id,
                item_variant_id=item_variant_id,
                origin_transaction_id=stock_transaction_id,
                source_layer_id=s_layer.id, # Provenance reference!
                layer_number=dest_layer_num,
                original_quantity=consume,
                remaining_quantity=consume,
                unit_cost=unit_c,
                total_cost=layer_val,
                status="ACTIVE",
                layer_timestamp=get_utc_now(),
                notes=f"Transferred from layer {s_layer.layer_number} (WH {source_warehouse_id})"
            )
            db.add(dest_layer)

            rem_to_transfer -= consume
            if rem_to_transfer <= 0:
                break

        # If source had no active layers (fallback)
        if rem_to_transfer > 0:
            fallback_unit_cost = Decimal(str(source_profile.moving_average_cost or source_profile.standard_cost or 0.0))
            fallback_val = quantize_decimal(rem_to_transfer * fallback_unit_cost)
            total_transfer_cost += fallback_val

            dest_layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER")
            dest_layer = CostLayer(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                warehouse_id=dest_warehouse_id,
                item_variant_id=item_variant_id,
                origin_transaction_id=stock_transaction_id,
                layer_number=dest_layer_num,
                original_quantity=rem_to_transfer,
                remaining_quantity=rem_to_transfer,
                unit_cost=fallback_unit_cost,
                total_cost=fallback_val,
                status="ACTIVE",
                layer_timestamp=get_utc_now(),
                notes=f"Transferred from WH {source_warehouse_id} (fallback average cost)"
            )
            db.add(dest_layer)

        total_transfer_cost = quantize_decimal(total_transfer_cost)
        avg_transfer_unit_cost = quantize_decimal(total_transfer_cost / qty)

        tx_out.unit_cost = avg_transfer_unit_cost
        tx_out.total_cost_impact = total_transfer_cost
        tx_in.unit_cost = avg_transfer_unit_cost
        tx_in.total_cost_impact = total_transfer_cost

        # Update Source Profile
        source_profile.current_quantity = max(Decimal("0.0"), Decimal(str(source_profile.current_quantity)) - qty)
        source_profile.current_total_value = max(Decimal("0.0"), Decimal(str(source_profile.current_total_value)) - total_transfer_cost)
        source_profile.last_cost_recalculated_at = get_utc_now()

        # Update Destination Profile
        dest_curr_qty = Decimal(str(dest_profile.current_quantity))
        dest_curr_val = Decimal(str(dest_profile.current_total_value))
        new_dest_qty = dest_curr_qty + qty
        new_dest_val = quantize_decimal(dest_curr_val + total_transfer_cost)
        new_dest_avg = quantize_decimal(new_dest_val / new_dest_qty) if new_dest_qty > 0 else avg_transfer_unit_cost

        dest_profile.current_quantity = new_dest_qty
        dest_profile.current_total_value = new_dest_val
        dest_profile.moving_average_cost = new_dest_avg
        dest_profile.last_cost_recalculated_at = get_utc_now()

        await db.flush()
        return tx_out, tx_in

    @staticmethod
    async def record_inventory_adjustment(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        quantity_diff: Decimal,
        unit_cost: Optional[Decimal] = None,
        stock_transaction_id: Optional[str] = None,
        reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> CostTransaction:
        """
        Records cost adjustments for physical cycle counts or shrinkage:
        - Positive diff (+): Requires validated cost basis, creates new cost layer and updates running average.
        - Negative diff (-): Depletes oldest active layers or consumes at current running average.
        """
        diff = quantize_decimal(Decimal(str(quantity_diff)))
        if diff == 0:
            raise HTTPException(status_code=400, detail="Adjustment quantity difference cannot be zero")

        profile = await CostingService.get_or_create_cost_profile(db, tenant_id, warehouse_id, item_variant_id)

        if diff > 0:
            # Positive count adjustment
            resolved_cost = unit_cost if (unit_cost is not None and unit_cost >= 0) else profile.moving_average_cost
            if resolved_cost is None or resolved_cost <= 0:
                resolved_cost = profile.standard_cost if profile.standard_cost > 0 else Decimal("0.0")

            cost = quantize_decimal(Decimal(str(resolved_cost)))
            total_cost = quantize_decimal(diff * cost)

            tx_number = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
            cost_tx = CostTransaction(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                stock_transaction_id=stock_transaction_id,
                cost_transaction_number=tx_number,
                transaction_type="ADJUSTMENT_COST_IN",
                warehouse_id=warehouse_id,
                item_variant_id=item_variant_id,
                quantity=diff,
                unit_cost=cost,
                total_cost_impact=total_cost,
                costing_method=profile.costing_method,
                posted_at=get_utc_now(),
                posted_by_user_id=user_id,
                notes=f"Positive Adjustment (+{diff}): {reason or ''}"
            )
            db.add(cost_tx)

            layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER")
            layer = CostLayer(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                item_variant_id=item_variant_id,
                origin_transaction_id=stock_transaction_id,
                layer_number=layer_num,
                original_quantity=diff,
                remaining_quantity=diff,
                unit_cost=cost,
                total_cost=total_cost,
                status="ACTIVE",
                layer_timestamp=get_utc_now(),
                notes=f"Adjustment surplus: {reason or ''}"
            )
            db.add(layer)

            # Update profile MWA
            curr_qty = Decimal(str(profile.current_quantity))
            curr_val = Decimal(str(profile.current_total_value))
            new_qty = curr_qty + diff
            new_val = quantize_decimal(curr_val + total_cost)
            new_avg = quantize_decimal(new_val / new_qty) if new_qty > 0 else cost

            profile.current_quantity = new_qty
            profile.current_total_value = new_val
            profile.moving_average_cost = new_avg
            profile.last_cost_recalculated_at = get_utc_now()

            await db.flush()
            return cost_tx
        else:
            # Negative count adjustment (shrinkage/damage)
            abs_diff = abs(diff)
            tx_number = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
            cost_tx = CostTransaction(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                stock_transaction_id=stock_transaction_id,
                cost_transaction_number=tx_number,
                transaction_type="ADJUSTMENT_COST_OUT",
                warehouse_id=warehouse_id,
                item_variant_id=item_variant_id,
                quantity=abs_diff,
                costing_method=profile.costing_method,
                posted_at=get_utc_now(),
                posted_by_user_id=user_id,
                notes=f"Negative Adjustment (-{abs_diff}): {reason or ''}"
            )
            db.add(cost_tx)
            await db.flush()

            # Deplete oldest active layers
            layer_stmt = (
                select(CostLayer)
                .where(
                    CostLayer.tenant_id == tenant_id,
                    CostLayer.warehouse_id == warehouse_id,
                    CostLayer.item_variant_id == item_variant_id,
                    CostLayer.status == "ACTIVE"
                )
                .order_by(CostLayer.layer_timestamp.asc(), CostLayer.id.asc())
                .with_for_update()
            )
            layer_res = await db.execute(layer_stmt)
            active_layers = layer_res.scalars().all()

            total_loss = Decimal("0.0")
            rem_to_deplete = abs_diff
            for layer in active_layers:
                rem = Decimal(str(layer.remaining_quantity))
                if rem <= 0:
                    continue
                consume = min(rem_to_deplete, rem)
                unit_c = Decimal(str(layer.unit_cost))
                loss_val = quantize_decimal(consume * unit_c)
                total_loss += loss_val

                layer.remaining_quantity = quantize_decimal(rem - consume)
                if layer.remaining_quantity == 0:
                    layer.status = "DEPLETED"

                db.add(CostLayerConsumption(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    cost_layer_id=layer.id,
                    cost_transaction_id=cost_tx.id,
                    quantity_consumed=consume,
                    unit_cost=unit_c,
                    total_cost=loss_val,
                    consumed_at=get_utc_now()
                ))
                rem_to_deplete -= consume
                if rem_to_deplete <= 0:
                    break

            if rem_to_deplete > 0:
                fallback_unit_cost = Decimal(str(profile.moving_average_cost or profile.standard_cost or 0.0))
                total_loss += quantize_decimal(rem_to_deplete * fallback_unit_cost)

            total_loss = quantize_decimal(total_loss)
            avg_unit_loss = quantize_decimal(total_loss / abs_diff)

            cost_tx.unit_cost = avg_unit_loss
            cost_tx.total_cost_impact = total_loss

            profile.current_quantity = max(Decimal("0.0"), Decimal(str(profile.current_quantity)) - abs_diff)
            profile.current_total_value = max(Decimal("0.0"), Decimal(str(profile.current_total_value)) - total_loss)
            profile.last_cost_recalculated_at = get_utc_now()

            await db.flush()
            return cost_tx

    @staticmethod
    async def record_customer_return(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: str,
        item_variant_id: str,
        quantity: Decimal,
        sales_order_id: str,
        condition: str = "GOOD",
        stock_transaction_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> CostTransaction:
        """
        Restores cost basis for returned items:
        - GOOD condition: Restores cost layer with original acquisition unit cost from the original COGSRecord.
        - DAMAGED condition: Quarantined at 0 or scrap unit cost.
        """
        qty = quantize_decimal(Decimal(str(quantity)))
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Return quantity must be strictly positive: {qty}")

        profile = await CostingService.get_or_create_cost_profile(db, tenant_id, warehouse_id, item_variant_id)

        # Lookup original COGS record for this Sales Order and variant
        cogs_stmt = (
            select(COGSRecord)
            .where(
                COGSRecord.tenant_id == tenant_id,
                COGSRecord.sales_order_id == sales_order_id,
                COGSRecord.item_variant_id == item_variant_id
            )
            .order_by(COGSRecord.recognized_at.desc())
        )
        cogs_res = await db.execute(cogs_stmt)
        cogs = cogs_res.scalars().first()

        unit_cost_to_restore = Decimal(str(cogs.unit_cogs)) if (cogs and condition.upper() == "GOOD") else Decimal("0.0")
        if condition.upper() != "GOOD":
            unit_cost_to_restore = Decimal("0.0")

        total_restored_cost = quantize_decimal(qty * unit_cost_to_restore)

        tx_number = await SequenceService.generate_next_number(db, tenant_id, "COST_TRANSACTION", custom_prefix="CTX")
        cost_tx = CostTransaction(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            stock_transaction_id=stock_transaction_id,
            cost_transaction_number=tx_number,
            transaction_type="RETURN_COST",
            warehouse_id=warehouse_id,
            item_variant_id=item_variant_id,
            quantity=qty,
            unit_cost=unit_cost_to_restore,
            total_cost_impact=total_restored_cost,
            costing_method=profile.costing_method,
            posted_at=get_utc_now(),
            posted_by_user_id=user_id,
            notes=f"Sales Return ({condition}): Restored cost basis from SO {sales_order_id}"
        )
        db.add(cost_tx)

        # Inbound Restored Layer
        layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER")
        restored_layer = CostLayer(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            item_variant_id=item_variant_id,
            origin_transaction_id=stock_transaction_id,
            layer_number=layer_num,
            original_quantity=qty,
            remaining_quantity=qty,
            unit_cost=unit_cost_to_restore,
            total_cost=total_restored_cost,
            status="ACTIVE",
            layer_timestamp=get_utc_now(),
            notes=f"Restored layer from RMA ({condition}) for SO {sales_order_id}"
        )
        db.add(restored_layer)

        # Update profile totals
        curr_qty = Decimal(str(profile.current_quantity))
        curr_val = Decimal(str(profile.current_total_value))
        new_qty = curr_qty + qty
        new_val = quantize_decimal(curr_val + total_restored_cost)
        new_avg = quantize_decimal(new_val / new_qty) if new_qty > 0 else unit_cost_to_restore

        profile.current_quantity = new_qty
        profile.current_total_value = new_val
        profile.moving_average_cost = new_avg
        profile.last_cost_recalculated_at = get_utc_now()

        await db.flush()
        return cost_tx

    @staticmethod
    async def initialize_opening_cost_layers(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        default_cost_if_missing: Decimal = Decimal("0.0")
    ) -> Dict[str, Any]:
        """
        Seeds initial opening CostLayer and ItemCostProfile records from existing StockBalanceCache on-hand quantities.
        Uses configured ItemVariant.cost_price as opening acquisition cost basis.
        """
        bal_stmt = (
            select(StockBalanceCache, ItemVariant, Item, Warehouse)
            .join(ItemVariant, StockBalanceCache.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .where(Warehouse.tenant_id == tenant_id, StockBalanceCache.quantity_on_hand > 0)
        )
        if warehouse_id:
            bal_stmt = bal_stmt.where(StockBalanceCache.warehouse_id == warehouse_id)

        bal_res = await db.execute(bal_stmt)
        rows = bal_res.fetchall()

        migrated_count = 0
        total_qty = Decimal("0.0")
        total_val = Decimal("0.0")

        # Group by (warehouse_id, item_variant_id)
        grouped_stock: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for bal, variant, item, wh in rows:
            key = (bal.warehouse_id, bal.item_variant_id)
            qty = Decimal(str(bal.quantity_on_hand))
            if key not in grouped_stock:
                grouped_stock[key] = {
                    "warehouse": wh,
                    "variant": variant,
                    "item": item,
                    "total_quantity": Decimal("0.0"),
                }
            grouped_stock[key]["total_quantity"] += qty

        for (wh_id, vid), data in grouped_stock.items():
            wh = data["warehouse"]
            variant = data["variant"]
            item = data["item"]
            qty = data["total_quantity"]

            cost = Decimal(str(variant.cost_price or default_cost_if_missing or 0.0))
            val = quantize_decimal(qty * cost)

            profile = await CostingService.get_or_create_cost_profile(db, tenant_id, wh_id, vid)

            # Check if active layers already exist
            check_stmt = select(func.count(CostLayer.id)).where(
                CostLayer.tenant_id == tenant_id,
                CostLayer.warehouse_id == wh_id,
                CostLayer.item_variant_id == vid,
                CostLayer.status == "ACTIVE"
            )
            existing_layers_count = (await db.execute(check_stmt)).scalar() or 0

            if existing_layers_count == 0:
                layer_num = await SequenceService.generate_next_number(db, tenant_id, "COST_LAYER", custom_prefix="LAYER-OPENING")
                layer = CostLayer(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    warehouse_id=wh_id,
                    item_variant_id=vid,
                    layer_number=layer_num,
                    original_quantity=qty,
                    remaining_quantity=qty,
                    unit_cost=cost,
                    total_cost=val,
                    status="ACTIVE",
                    layer_timestamp=get_utc_now(),
                    notes="Opening stock migration cutover"
                )
                db.add(layer)

                profile.current_quantity = qty
                profile.current_total_value = val
                profile.moving_average_cost = cost
                profile.standard_cost = cost
                profile.last_cost_recalculated_at = get_utc_now()

                migrated_count += 1
                total_qty += qty
                total_val += val

        await db.flush()
        return {
            "migrated_layers_count": migrated_count,
            "total_quantity_migrated": float(total_qty),
            "total_valuation_migrated": float(total_val),
            "message": f"Successfully initialized {migrated_count} opening cost profiles and FIFO layers."
        }
