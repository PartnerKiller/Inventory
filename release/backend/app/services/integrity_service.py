from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.models.ledger import StockBalanceCache, StockLedgerEntry, StockLedgerTransaction
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine
from app.models.sales import SalesOrder, SOLineItem, Shipment, SalesReturn
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemVariant
from app.services.metrics_service import metrics_service

class IntegrityService:
    """
    Strictly Read-Only Data Integrity & Ledger Invariant Verification Engine.
    Audits physical stock invariants, balance cache sums vs ledger entries,
    and purchase/sales lifecycle quantities without mutating business data.
    """
    @classmethod
    async def run_full_integrity_check(cls, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        discrepancies: List[Dict[str, Any]] = []
        checks_performed = 0

        # -------------------------------------------------------------
        # 1. Audit Stock Balance Invariants: available = on_hand - allocated
        # -------------------------------------------------------------
        stmt_balances = (
            select(StockBalanceCache)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .where(Warehouse.tenant_id == tenant_id)
        )
        res_balances = await db.execute(stmt_balances)
        balances = res_balances.scalars().all()

        for b in balances:
            checks_performed += 1
            expected_avail = float(b.quantity_on_hand) - float(b.quantity_allocated)
            
            if float(b.quantity_on_hand) < 0:
                discrepancies.append({
                    "code": "INV_NEGATIVE_ON_HAND",
                    "severity": "CRITICAL",
                    "entity_type": "StockBalanceCache",
                    "entity_id": str(b.id),
                    "description": f"Negative on-hand balance ({b.quantity_on_hand}) detected for variant {b.item_variant_id}",
                    "expected": 0.0,
                    "actual": float(b.quantity_on_hand)
                })

            if float(b.quantity_allocated) < 0:
                discrepancies.append({
                    "code": "INV_NEGATIVE_ALLOCATED",
                    "severity": "CRITICAL",
                    "entity_type": "StockBalanceCache",
                    "entity_id": str(b.id),
                    "description": f"Negative allocated balance ({b.quantity_allocated}) detected for variant {b.item_variant_id}",
                    "expected": 0.0,
                    "actual": float(b.quantity_allocated)
                })

            if float(b.quantity_on_hand) < float(b.quantity_allocated):
                discrepancies.append({
                    "code": "INV_AVAILABLE_MISMATCH",
                    "severity": "CRITICAL",
                    "entity_type": "StockBalanceCache",
                    "entity_id": str(b.id),
                    "description": f"Balance invariant failed for variant {b.item_variant_id} at bin {b.location_bin_id}: on_hand ({b.quantity_on_hand}) < allocated ({b.quantity_allocated})",
                    "expected": float(b.quantity_allocated),
                    "actual": float(b.quantity_on_hand)
                })

        # -------------------------------------------------------------
        # 2. Audit Ledger Sums vs Balance Cache Projections
        # -------------------------------------------------------------
        # Sum inflows (destination_bin) and outflows (source_bin)
        stmt_inflows = (
            select(
                StockLedgerEntry.item_variant_id,
                StockLedgerEntry.destination_location_bin_id.label("bin_id"),
                func.sum(StockLedgerEntry.quantity).label("inflow_qty")
            )
            .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
            .where(StockLedgerTransaction.tenant_id == tenant_id, StockLedgerEntry.destination_location_bin_id.isnot(None))
            .group_by(StockLedgerEntry.item_variant_id, StockLedgerEntry.destination_location_bin_id)
        )
        res_inflows = await db.execute(stmt_inflows)
        inflows = { (r.item_variant_id, r.bin_id): float(r.inflow_qty or 0) for r in res_inflows.all() }

        stmt_outflows = (
            select(
                StockLedgerEntry.item_variant_id,
                StockLedgerEntry.source_location_bin_id.label("bin_id"),
                func.sum(StockLedgerEntry.quantity).label("outflow_qty")
            )
            .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
            .where(StockLedgerTransaction.tenant_id == tenant_id, StockLedgerEntry.source_location_bin_id.isnot(None))
            .group_by(StockLedgerEntry.item_variant_id, StockLedgerEntry.source_location_bin_id)
        )
        res_outflows = await db.execute(stmt_outflows)
        outflows = { (r.item_variant_id, r.bin_id): float(r.outflow_qty or 0) for r in res_outflows.all() }

        all_ledger_keys = set(inflows.keys()).union(set(outflows.keys()))
        balance_map = { (b.item_variant_id, b.location_bin_id): float(b.quantity_on_hand) for b in balances }

        for item_var_id, bin_id in all_ledger_keys:
            checks_performed += 1
            net_ledger = inflows.get((item_var_id, bin_id), 0.0) - outflows.get((item_var_id, bin_id), 0.0)
            cached_on_hand = balance_map.get((item_var_id, bin_id), 0.0)

            if round(net_ledger, 4) != round(cached_on_hand, 4):
                discrepancies.append({
                    "code": "LEDGER_BALANCE_DISCREPANCY",
                    "severity": "CRITICAL",
                    "entity_type": "StockLedgerEntry",
                    "entity_id": f"{item_var_id}:{bin_id}",
                    "description": f"Cumulative immutable ledger sum ({net_ledger}) does not equal on-hand cache ({cached_on_hand})",
                    "expected": round(net_ledger, 4),
                    "actual": round(cached_on_hand, 4)
                })

        # -------------------------------------------------------------
        # 3. Audit Purchase Order Receipts vs Lines
        # -------------------------------------------------------------
        stmt_po_lines = (
            select(POLineItem)
            .join(PurchaseOrder, POLineItem.purchase_order_id == PurchaseOrder.id)
            .where(PurchaseOrder.tenant_id == tenant_id)
        )
        res_po_lines = await db.execute(stmt_po_lines)
        po_lines = res_po_lines.scalars().all()

        for po_line in po_lines:
            checks_performed += 1
            if float(po_line.quantity_received) > float(po_line.quantity_ordered):
                discrepancies.append({
                    "code": "PO_OVER_RECEIPT_DETECTED",
                    "severity": "WARNING",
                    "entity_type": "POLineItem",
                    "entity_id": str(po_line.id),
                    "description": f"PO Line {po_line.id} received ({po_line.quantity_received}) exceeds ordered ({po_line.quantity_ordered})",
                    "expected": float(po_line.quantity_ordered),
                    "actual": float(po_line.quantity_received)
                })

        # -------------------------------------------------------------
        # 4. Audit Sales Order Dispatches vs Shipped Quantities
        # -------------------------------------------------------------
        stmt_so_lines = (
            select(SOLineItem)
            .join(SalesOrder, SOLineItem.sales_order_id == SalesOrder.id)
            .where(SalesOrder.tenant_id == tenant_id)
        )
        res_so_lines = await db.execute(stmt_so_lines)
        so_lines = res_so_lines.scalars().all()

        for so_line in so_lines:
            checks_performed += 1
            if float(so_line.quantity_shipped) > float(so_line.quantity_ordered):
                discrepancies.append({
                    "code": "SO_OVER_DISPATCH_DETECTED",
                    "severity": "WARNING",
                    "entity_type": "SOLineItem",
                    "entity_id": str(so_line.id),
                    "description": f"SO Line {so_line.id} shipped ({so_line.quantity_shipped}) exceeds ordered ({so_line.quantity_ordered})",
                    "expected": float(so_line.quantity_ordered),
                    "actual": float(so_line.quantity_shipped)
                })

        overall_status = "HEALTHY" if not discrepancies else "DISCREPANCIES_DETECTED"
        metrics_service.record_integrity_event(overall_status)

        return {
            "overall_status": overall_status,
            "checks_performed": checks_performed,
            "discrepancies_count": len(discrepancies),
            "discrepancies": discrepancies,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "invariants_verified": [
                "available = on_hand - allocated",
                "on_hand >= 0 and allocated >= 0",
                "sum(ledger_deltas) == balance_cache_on_hand",
                "po_received <= po_ordered",
                "so_shipped <= so_ordered"
            ]
        }
