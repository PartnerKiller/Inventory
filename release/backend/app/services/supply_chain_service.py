import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.warehouse import Warehouse, LocationBin
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer
from app.models.general_ledger import GLAccount
from app.models.supply_chain import SupplyChainNode, TransferOrder, TransferOrderLine
from app.schemas.supply_chain import (
    SupplyChainNodeCreate,
    SupplyChainNodeResponse,
    TransferOrderCreate,
    TransferOrderResponse,
    TransferOrderLineResponse,
    TransferReceiveAction,
    SourcingPlanRequest,
    SourcingPlanResponse,
    SourcingOption
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.stock_engine import StockEngine
from app.services.gl_service import GLService
from app.services.sequence_service import SequenceService

class SupplyChainService:

    # ========================================================================
    # 1. NODE TOPOLOGY MANAGEMENT
    # ========================================================================

    @staticmethod
    async def create_node(
        db: AsyncSession,
        tenant_id: str,
        node_in: SupplyChainNodeCreate
    ) -> SupplyChainNodeResponse:
        existing = (await db.execute(
            select(SupplyChainNode).where(
                SupplyChainNode.tenant_id == tenant_id,
                SupplyChainNode.node_code == node_in.node_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Supply Chain Node '{node_in.node_code}' already exists")

        node = SupplyChainNode(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            node_code=node_in.node_code,
            node_name=node_in.node_name,
            node_type=node_in.node_type,
            warehouse_id=node_in.warehouse_id,
            parent_node_id=node_in.parent_node_id,
            lead_time_days=node_in.lead_time_days,
            sourcing_priority=node_in.sourcing_priority
        )
        db.add(node)
        await db.commit()
        await db.refresh(node)

        return SupplyChainNodeResponse(
            id=node.id,
            tenant_id=node.tenant_id,
            node_code=node.node_code,
            node_name=node.node_name,
            node_type=node.node_type,
            warehouse_id=node.warehouse_id,
            parent_node_id=node.parent_node_id,
            lead_time_days=node.lead_time_days,
            sourcing_priority=node.sourcing_priority,
            is_active=node.is_active,
            created_at=node.created_at
        )

    # ========================================================================
    # 2. MULTI-ECHELON SOURCING PLAN RESOLVER
    # ========================================================================

    @staticmethod
    async def resolve_sourcing_plan(
        db: AsyncSession,
        tenant_id: str,
        req: SourcingPlanRequest
    ) -> SourcingPlanResponse:
        options: List[SourcingOption] = []

        # 1. Evaluate Local Warehouse Stock
        local_bal = (await db.execute(
            select(func.coalesce(func.sum(StockBalanceCache.quantity_on_hand - StockBalanceCache.quantity_allocated), Decimal("0.0"))).where(
                StockBalanceCache.warehouse_id == req.requesting_warehouse_id,
                StockBalanceCache.item_variant_id == req.item_variant_id
            )
        )).scalar() or Decimal("0.0")

        wh = (await db.execute(select(Warehouse).where(Warehouse.id == req.requesting_warehouse_id))).scalar_one_or_none()
        wh_name = wh.name if wh else "Local WH"

        local_avail = max(Decimal("0.0"), Decimal(str(local_bal)))
        is_local_recommended = local_avail >= req.demand_quantity

        options.append(SourcingOption(
            tier="LOCAL_STOCK",
            source_id=req.requesting_warehouse_id,
            source_name=wh_name,
            available_quantity=local_avail,
            lead_time_days=0,
            estimated_unit_cost=Decimal("100.0"),
            recommended=is_local_recommended
        ))

        # 2. Evaluate Regional / Central Nodes
        nodes = (await db.execute(
            select(SupplyChainNode).where(
                SupplyChainNode.tenant_id == tenant_id,
                SupplyChainNode.is_active == True
            ).order_by(SupplyChainNode.sourcing_priority.asc())
        )).scalars().all()

        found_rec = is_local_recommended
        for node in nodes:
            if node.warehouse_id and node.warehouse_id != req.requesting_warehouse_id:
                node_bal = (await db.execute(
                    select(func.coalesce(func.sum(StockBalanceCache.quantity_on_hand - StockBalanceCache.quantity_allocated), Decimal("0.0"))).where(
                        StockBalanceCache.warehouse_id == node.warehouse_id,
                        StockBalanceCache.item_variant_id == req.item_variant_id
                    )
                )).scalar() or Decimal("0.0")
                n_avail = max(Decimal("0.0"), Decimal(str(node_bal)))
                rec = (not found_rec) and (n_avail >= req.demand_quantity)
                if rec:
                    found_rec = True

                options.append(SourcingOption(
                    tier="REGIONAL_TRANSFER" if node.node_type == "REGIONAL_DC" else "CENTRAL_TRANSFER",
                    source_id=node.warehouse_id,
                    source_name=node.node_name,
                    available_quantity=n_avail,
                    lead_time_days=node.lead_time_days,
                    estimated_unit_cost=Decimal("110.0"),
                    recommended=rec
                ))

        # 3. Fallback: External Supplier Purchase Order
        if not found_rec:
            options.append(SourcingOption(
                tier="SUPPLIER_BUY",
                source_id="SUPPLIER-DEFAULT",
                source_name="Primary Approved Supplier",
                available_quantity=Decimal("99999.0"),
                lead_time_days=7,
                estimated_unit_cost=Decimal("120.0"),
                recommended=True
            ))

        return SourcingPlanResponse(
            item_variant_id=req.item_variant_id,
            demand_quantity=req.demand_quantity,
            requesting_warehouse_id=req.requesting_warehouse_id,
            options=options
        )

    # ========================================================================
    # 3. TRANSFER ORDER LIFECYCLE & IN-TRANSIT ACCOUNTING
    # ========================================================================

    @staticmethod
    async def create_transfer_order(
        db: AsyncSession,
        tenant_id: str,
        trf_in: TransferOrderCreate
    ) -> TransferOrderResponse:
        trf_num = await SequenceService.generate_next_number(db, tenant_id, "TRANSFER_ORDER", custom_prefix="TRF")

        trf = TransferOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transfer_number=trf_num,
            source_warehouse_id=trf_in.source_warehouse_id,
            destination_warehouse_id=trf_in.destination_warehouse_id,
            in_transit_bin_id=trf_in.in_transit_bin_id,
            destination_bin_id=trf_in.destination_bin_id,
            status="APPROVED",
            freight_charge=trf_in.freight_charge,
            carrier_tracking_number=trf_in.carrier_tracking_number,
            notes=trf_in.notes
        )
        db.add(trf)

        lines = []
        for line_in in trf_in.lines:
            line = TransferOrderLine(
                id=str(uuid.uuid4()),
                transfer_order_id=trf.id,
                item_variant_id=line_in.item_variant_id,
                quantity_requested=line_in.quantity_requested,
                quantity_shipped=Decimal("0.0"),
                quantity_received=Decimal("0.0"),
                quantity_damaged=Decimal("0.0")
            )
            db.add(line)
            lines.append(line)

        await db.commit()
        await db.refresh(trf)

        return TransferOrderResponse(
            id=trf.id,
            tenant_id=trf.tenant_id,
            transfer_number=trf.transfer_number,
            source_warehouse_id=trf.source_warehouse_id,
            destination_warehouse_id=trf.destination_warehouse_id,
            in_transit_bin_id=trf.in_transit_bin_id,
            destination_bin_id=trf.destination_bin_id,
            status=trf.status,
            freight_charge=trf.freight_charge,
            dispatched_at=trf.dispatched_at,
            received_at=trf.received_at,
            carrier_tracking_number=trf.carrier_tracking_number,
            notes=trf.notes,
            lines=[
                TransferOrderLineResponse(
                    id=l.id,
                    item_variant_id=l.item_variant_id,
                    quantity_requested=l.quantity_requested,
                    quantity_shipped=l.quantity_shipped,
                    quantity_received=l.quantity_received,
                    quantity_damaged=l.quantity_damaged,
                    unit_cost=l.unit_cost
                ) for l in lines
            ],
            created_at=trf.created_at
        )

    @staticmethod
    async def dispatch_transfer_order(
        db: AsyncSession,
        tenant_id: str,
        transfer_id: str,
        source_bin_id: str,
        user_id: Optional[str] = None
    ) -> TransferOrderResponse:
        trf = (await db.execute(
            select(TransferOrder).where(TransferOrder.id == transfer_id, TransferOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not trf:
            raise HTTPException(status_code=404, detail="Transfer Order not found")

        if trf.status != "APPROVED":
            raise HTTPException(status_code=400, detail=f"Cannot dispatch transfer in '{trf.status}' status")

        total_val = Decimal("0.0")
        for line in trf.lines:
            # 1. Consume from source bin to in-transit bin
            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="STOCK_TRANSFER",
                entries_data=[{
                    "item_variant_id": line.item_variant_id,
                    "source_location_bin_id": source_bin_id,
                    "destination_location_bin_id": trf.in_transit_bin_id,
                    "quantity": line.quantity_requested
                }],
                reference_doc_type="TRANSFER_ORDER",
                reference_doc_id=trf.id,
                notes=f"Transfer {trf.transfer_number} dispatch to In-Transit",
                user_id=user_id
            )

            # Consume Cost Layers at source
            layers = (await db.execute(
                select(CostLayer).where(
                    CostLayer.tenant_id == tenant_id,
                    CostLayer.warehouse_id == trf.source_warehouse_id,
                    CostLayer.item_variant_id == line.item_variant_id,
                    CostLayer.status == "ACTIVE"
                ).order_by(CostLayer.layer_timestamp.asc()).with_for_update()
            )).scalars().all()

            rem_needed = line.quantity_requested
            cost_accum = Decimal("0.0")
            for l in layers:
                if rem_needed <= 0:
                    break
                rem = Decimal(str(l.remaining_quantity))
                take = min(rem_needed, rem)
                cost_accum += take * Decimal(str(l.unit_cost))
                l.remaining_quantity = rem - take
                if l.remaining_quantity <= 0:
                    l.status = "CONSUMED"
                rem_needed -= take

            if rem_needed > 0:
                cost_accum += rem_needed * Decimal("100.0") # default standard fallback

            line.quantity_shipped = line.quantity_requested
            line.unit_cost = (cost_accum / line.quantity_shipped).quantize(Decimal("0.0001"))
            total_val += cost_accum

        trf.status = "IN_TRANSIT"
        trf.dispatched_at = get_utc_now()

        # GL Journal Vouchers:
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200"))).scalar_one_or_none()
        acc_1250 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1250"))).scalar_one_or_none()
        acc_2000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2000"))).scalar_one_or_none()

        # 1. Dispatch JV (Dr 1250 In-Transit Asset / Cr 1200 Source Inventory Asset)
        if total_val > 0 and acc_1200 and acc_1250:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="TRANSFER_ORDER",
                    source_document_id=f"{trf.id}_DISPATCH",
                    notes=f"Transfer Order {trf.transfer_number} In-Transit Dispatch",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_1250.id, debit_amount=total_val, credit_amount=Decimal("0.0"), memo="In-Transit Asset debit"),
                        JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("0.0"), credit_amount=total_val, memo="Source Warehouse inventory credit")
                    ]
                ),
                user_id=user_id
            )

        # 2. Freight Surcharge JV (Dr 1250 In-Transit / Cr 2000 AP)
        if trf.freight_charge > Decimal("0.0") and acc_1250 and acc_2000:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="TRANSFER_ORDER",
                    source_document_id=f"{trf.id}_FREIGHT",
                    notes=f"Transfer Order {trf.transfer_number} Freight Surcharge",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_1250.id, debit_amount=trf.freight_charge, credit_amount=Decimal("0.0"), memo="Capitalize freight to in-transit"),
                        JournalEntryLineCreate(account_id=acc_2000.id, debit_amount=Decimal("0.0"), credit_amount=trf.freight_charge, memo="Carrier AP liability")
                    ]
                ),
                user_id=user_id
            )

        await db.commit()
        await db.refresh(trf)

        return TransferOrderResponse(
            id=trf.id,
            tenant_id=trf.tenant_id,
            transfer_number=trf.transfer_number,
            source_warehouse_id=trf.source_warehouse_id,
            destination_warehouse_id=trf.destination_warehouse_id,
            in_transit_bin_id=trf.in_transit_bin_id,
            destination_bin_id=trf.destination_bin_id,
            status=trf.status,
            freight_charge=trf.freight_charge,
            dispatched_at=trf.dispatched_at,
            received_at=trf.received_at,
            carrier_tracking_number=trf.carrier_tracking_number,
            notes=trf.notes,
            lines=[
                TransferOrderLineResponse(
                    id=l.id,
                    item_variant_id=l.item_variant_id,
                    quantity_requested=l.quantity_requested,
                    quantity_shipped=l.quantity_shipped,
                    quantity_received=l.quantity_received,
                    quantity_damaged=l.quantity_damaged,
                    unit_cost=l.unit_cost
                ) for l in trf.lines
            ],
            created_at=trf.created_at
        )

    @staticmethod
    async def receive_transfer_order(
        db: AsyncSession,
        tenant_id: str,
        transfer_id: str,
        receive_act: TransferReceiveAction,
        user_id: Optional[str] = None
    ) -> TransferOrderResponse:
        trf = (await db.execute(
            select(TransferOrder).where(TransferOrder.id == transfer_id, TransferOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not trf:
            raise HTTPException(status_code=404, detail="Transfer Order not found")

        if trf.status != "IN_TRANSIT":
            raise HTTPException(status_code=400, detail=f"Cannot receive transfer in '{trf.status}' status")

        total_received_cost = Decimal("0.0")
        total_damage_cost = Decimal("0.0")

        # Map lines
        line_map = {l.item_variant_id: l for l in trf.lines}
        total_shipped_qty = sum(l.quantity_shipped for l in trf.lines)
        freight_per_unit = (trf.freight_charge / total_shipped_qty).quantize(Decimal("0.0001")) if total_shipped_qty > 0 else Decimal("0.0")

        for r_line in receive_act.received_lines:
            line = line_map.get(r_line.item_variant_id)
            if not line:
                continue

            qty_good = r_line.quantity_received
            qty_dmg = r_line.quantity_damaged
            tot_rec = qty_good + qty_dmg

            # Move from in-transit bin to destination bin
            if qty_good > 0:
                await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="STOCK_TRANSFER",
                    entries_data=[{
                        "item_variant_id": line.item_variant_id,
                        "source_location_bin_id": trf.in_transit_bin_id,
                        "destination_location_bin_id": trf.destination_bin_id,
                        "quantity": qty_good
                    }],
                    reference_doc_type="TRANSFER_ORDER",
                    reference_doc_id=trf.id,
                    notes=f"Transfer {trf.transfer_number} destination stocking",
                    user_id=user_id
                )

                # Capitalize unit cost + freight into Destination CostLayer
                landed_unit_cost = line.unit_cost + freight_per_unit
                good_cost = (qty_good * landed_unit_cost).quantize(Decimal("0.0001"))
                total_received_cost += good_cost

                c_layer = CostLayer(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    warehouse_id=trf.destination_warehouse_id,
                    item_variant_id=line.item_variant_id,
                    layer_number=f"LAY-TRF-{uuid.uuid4().hex[:8].upper()}",
                    original_quantity=qty_good,
                    remaining_quantity=qty_good,
                    unit_cost=landed_unit_cost,
                    total_cost=good_cost,
                    status="ACTIVE",
                    layer_timestamp=get_utc_now()
                )
                db.add(c_layer)

            # Damaged items write-off
            if qty_dmg > 0:
                dmg_bin = r_line.damage_bin_id or trf.destination_bin_id
                await StockEngine.post_transaction(
                    db=db,
                    tenant_id=tenant_id,
                    transaction_type="STOCK_TRANSFER",
                    entries_data=[{
                        "item_variant_id": line.item_variant_id,
                        "source_location_bin_id": trf.in_transit_bin_id,
                        "destination_location_bin_id": dmg_bin,
                        "quantity": qty_dmg
                    }],
                    reference_doc_type="TRANSFER_ORDER",
                    reference_doc_id=trf.id,
                    notes=f"Transfer {trf.transfer_number} damaged goods quarantine",
                    user_id=user_id
                )
                dmg_cost = (qty_dmg * line.unit_cost).quantize(Decimal("0.0001"))
                total_damage_cost += dmg_cost

            line.quantity_received = qty_good
            line.quantity_damaged = qty_dmg

        trf.status = "COMPLETED"
        trf.received_at = get_utc_now()

        # GL Journal Vouchers:
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1200 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200"))).scalar_one_or_none()
        acc_1250 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1250"))).scalar_one_or_none()
        acc_6000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6000"))).scalar_one_or_none()

        # 1. Destination Inventory Receipt (Dr 1200 Dest Inventory / Cr 1250 In-Transit Asset)
        if total_received_cost > 0 and acc_1200 and acc_1250:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="TRANSFER_ORDER",
                    source_document_id=f"{trf.id}_RECEIPT",
                    notes=f"Transfer Order {trf.transfer_number} Destination Receipt",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=total_received_cost, credit_amount=Decimal("0.0"), memo="Destination inventory asset debit"),
                        JournalEntryLineCreate(account_id=acc_1250.id, debit_amount=Decimal("0.0"), credit_amount=total_received_cost, memo="Clear in-transit inventory asset")
                    ]
                ),
                user_id=user_id
            )

        # 2. Damaged Goods Write-Off JV (Dr 6000 Operating Loss / Cr 1250 In-Transit)
        if total_damage_cost > 0 and acc_6000 and acc_1250:
            await GLService.post_journal_voucher(
                db=db, tenant_id=tenant_id,
                voucher_in=JournalVoucherCreate(
                    voucher_date=get_utc_now(),
                    source_document_type="TRANSFER_ORDER",
                    source_document_id=f"{trf.id}_DAMAGE",
                    notes=f"Transfer Order {trf.transfer_number} In-Transit Damage Write-Off",
                    lines=[
                        JournalEntryLineCreate(account_id=acc_6000.id, debit_amount=total_damage_cost, credit_amount=Decimal("0.0"), memo="Transit damage operating loss"),
                        JournalEntryLineCreate(account_id=acc_1250.id, debit_amount=Decimal("0.0"), credit_amount=total_damage_cost, memo="Clear damaged in-transit asset")
                    ]
                ),
                user_id=user_id
            )

        await db.commit()
        await db.refresh(trf)

        return TransferOrderResponse(
            id=trf.id,
            tenant_id=trf.tenant_id,
            transfer_number=trf.transfer_number,
            source_warehouse_id=trf.source_warehouse_id,
            destination_warehouse_id=trf.destination_warehouse_id,
            in_transit_bin_id=trf.in_transit_bin_id,
            destination_bin_id=trf.destination_bin_id,
            status=trf.status,
            freight_charge=trf.freight_charge,
            dispatched_at=trf.dispatched_at,
            received_at=trf.received_at,
            carrier_tracking_number=trf.carrier_tracking_number,
            notes=trf.notes,
            lines=[
                TransferOrderLineResponse(
                    id=l.id,
                    item_variant_id=l.item_variant_id,
                    quantity_requested=l.quantity_requested,
                    quantity_shipped=l.quantity_shipped,
                    quantity_received=l.quantity_received,
                    quantity_damaged=l.quantity_damaged,
                    unit_cost=l.unit_cost
                ) for l in trf.lines
            ],
            created_at=trf.created_at
        )
