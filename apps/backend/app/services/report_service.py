import io
import csv
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from app.models.item import Item, ItemVariant, Barcode
from app.models.warehouse import Warehouse, LocationBin
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, Supplier
from app.models.sales import SalesOrder, SOLineItem, Customer, Shipment, SalesReturn
from app.models.ledger import StockBalanceCache, StockLedgerEntry, StockLedgerTransaction
from app.models.audit import AuditLog
from app.schemas.reports import (
    DashboardMetricsResponse, DashboardOperationalAlert, RecentGoodsReceiptSummary, RecentSalesOrderSummary,
    ValuationReportResponse, ValuationReportItem,
    InventoryReportResponse, InventoryReportItem,
    PurchasingReportResponse, PurchasingReportItem,
    SalesReportResponse, SalesReportItem,
    GlobalSearchResponse, GlobalSearchResultItem
)
from app.schemas.ledger import StockLedgerEntryResponse
from app.schemas.audit import AuditLogResponse

class ReportService:
    @staticmethod
    async def get_dashboard_metrics(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None
    ) -> DashboardMetricsResponse:
        # 1. Total Active Products
        item_count_stmt = select(func.count(Item.id)).where(Item.tenant_id == tenant_id, Item.is_deleted == False)
        item_count_res = await db.execute(item_count_stmt)
        total_items = item_count_res.scalar() or 0

        # 2. Total Warehouses
        wh_count_stmt = select(func.count(Warehouse.id)).where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        wh_count_res = await db.execute(wh_count_stmt)
        total_warehouses = wh_count_res.scalar() or 0

        # 3. Stock Aggregates from Balance Cache
        bal_base = (
            select(
                func.coalesce(func.sum(StockBalanceCache.quantity_on_hand), 0),
                func.coalesce(func.sum(StockBalanceCache.quantity_allocated), 0),
                func.coalesce(func.sum(StockBalanceCache.quantity_on_hand - StockBalanceCache.quantity_allocated), 0),
            )
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .where(Warehouse.tenant_id == tenant_id)
        )
        if warehouse_id:
            bal_base = bal_base.where(StockBalanceCache.warehouse_id == warehouse_id)

        bal_agg_res = await db.execute(bal_base)
        on_hand_sum, alloc_sum, avail_sum = bal_agg_res.first() or (0, 0, 0)

        # 4. Low-Stock & Out-of-Stock Counts & Valuation
        val_stmt = (
            select(
                Item.id,
                Item.sku,
                Item.name,
                Item.reorder_point,
                func.coalesce(func.sum(StockBalanceCache.quantity_on_hand), 0).label("tot_on_hand"),
                func.coalesce(func.avg(ItemVariant.cost_price), 0).label("avg_cost")
            )
            .join(ItemVariant, Item.id == ItemVariant.item_id)
            .outerjoin(StockBalanceCache, ItemVariant.id == StockBalanceCache.item_variant_id)
            .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
            .group_by(Item.id, Item.sku, Item.name, Item.reorder_point)
        )
        val_res = await db.execute(val_stmt)
        low_stock_count = 0
        out_of_stock_count = 0
        total_valuation = 0.0
        alerts = []

        for row in val_res.fetchall():
            tot_qty = float(row.tot_on_hand)
            cost = float(row.avg_cost)
            reorder = float(row.reorder_point or 0.0)
            total_valuation += tot_qty * cost

            if tot_qty == 0:
                out_of_stock_count += 1
            elif reorder > 0 and tot_qty <= reorder:
                low_stock_count += 1

        if out_of_stock_count > 0:
            alerts.append(DashboardOperationalAlert(
                level="CRITICAL",
                title=f"{out_of_stock_count} Product(s) Completely Out of Stock",
                message="Critical items require immediate replenishment purchase orders.",
                count=out_of_stock_count,
                link_tab="purchasing"
            ))

        if low_stock_count > 0:
            alerts.append(DashboardOperationalAlert(
                level="WARNING",
                title=f"{low_stock_count} Product(s) Below Reorder Point",
                message="Inventory levels have breached defined safety thresholds.",
                count=low_stock_count,
                link_tab="inventory"
            ))

        # 5. Purchasing Metrics
        po_pending_stmt = select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.status.in_(["DRAFT", "PENDING_APPROVAL"]),
            PurchaseOrder.is_deleted == False
        )
        if warehouse_id:
            po_pending_stmt = po_pending_stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)
        pending_pos = (await db.execute(po_pending_stmt)).scalar() or 0

        # 6. Sales Fulfillment Funnel Queues
        so_base = select(SalesOrder.status, func.count(SalesOrder.id)).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.is_deleted == False
        )
        if warehouse_id:
            so_base = so_base.where(SalesOrder.warehouse_id == warehouse_id)
        so_status_res = await db.execute(so_base.group_by(SalesOrder.status))
        so_map = {row[0]: row[1] for row in so_status_res.fetchall()}

        pending_sos = sum(so_map.get(s, 0) for s in ["DRAFT", "CONFIRMED", "ALLOCATED", "PICKING", "PACKED"])
        orders_awaiting_picking = so_map.get("ALLOCATED", 0)
        orders_awaiting_packing = so_map.get("PICKING", 0)
        orders_awaiting_dispatch = so_map.get("PACKED", 0)

        # 7. Recent Transactions
        tx_stmt = (
            select(StockLedgerEntry, StockLedgerTransaction, ItemVariant, Item)
            .join(StockLedgerTransaction, StockLedgerEntry.transaction_id == StockLedgerTransaction.id)
            .join(ItemVariant, StockLedgerEntry.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(StockLedgerTransaction.tenant_id == tenant_id)
            .order_by(desc(StockLedgerEntry.entry_timestamp))
            .limit(8)
        )
        tx_res = await db.execute(tx_stmt)
        recent_txs = [
            StockLedgerEntryResponse(
                id=entry.id,
                transaction_id=tx.id,
                transaction_number=tx.transaction_number,
                transaction_type=tx.transaction_type,
                item_variant_id=variant.id,
                item_sku=item.sku,
                item_name=item.name,
                variant_name=variant.variant_name,
                source_location_bin_id=entry.source_location_bin_id,
                destination_location_bin_id=entry.destination_location_bin_id,
                quantity=float(entry.quantity),
                uom=entry.uom,
                unit_cost=float(entry.unit_cost),
                total_cost=float(entry.total_cost),
                posted_by_user_id=tx.posted_by_user_id,
                posted_at=entry.entry_timestamp,
                notes=tx.notes
            )
            for entry, tx, variant, item in tx_res.fetchall()
        ]

        # 8. Recent Goods Receipts (GRN)
        grn_stmt = (
            select(GoodsReceipt, PurchaseOrder, Warehouse)
            .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
            .join(Warehouse, GoodsReceipt.warehouse_id == Warehouse.id)
            .where(PurchaseOrder.tenant_id == tenant_id)
            .order_by(desc(GoodsReceipt.received_at))
            .limit(5)
        )
        grn_res = await db.execute(grn_stmt)
        recent_receipts = [
            RecentGoodsReceiptSummary(
                id=grn.id,
                grn_number=grn.grn_number,
                po_number=po.po_number,
                warehouse_name=wh.name,
                received_at=grn.received_at,
                lines_count=len(grn.lines) if grn.lines else 1
            )
            for grn, po, wh in grn_res.fetchall()
        ]

        # 9. Recent Sales Orders
        so_stmt = (
            select(SalesOrder, Customer)
            .join(Customer, SalesOrder.customer_id == Customer.id)
            .where(SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
            .order_by(desc(SalesOrder.ordered_at))
            .limit(5)
        )
        so_res = await db.execute(so_stmt)
        recent_sales = [
            RecentSalesOrderSummary(
                id=so.id,
                so_number=so.so_number,
                customer_name=cust.name,
                status=so.status,
                total_amount=float(so.total_amount),
                ordered_at=so.ordered_at
            )
            for so, cust in so_res.fetchall()
        ]

        # 10. Audit Logs
        audit_stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(desc(AuditLog.timestamp))
            .limit(8)
        )
        audit_res = await db.execute(audit_stmt)
        recent_audits = [
            AuditLogResponse(
                id=a.id,
                tenant_id=a.tenant_id,
                user_id=a.user_id,
                action=a.action,
                entity_type=a.entity_type,
                entity_id=a.entity_id,
                ip_address=a.ip_address,
                client_type=a.client_type,
                changes=a.changes or {},
                timestamp=a.timestamp
            )
            for a in audit_res.scalars().all()
        ]

        return DashboardMetricsResponse(
            total_items=total_items,
            total_warehouses=total_warehouses,
            total_on_hand_units=float(on_hand_sum),
            total_allocated_units=float(alloc_sum),
            total_available_units=float(avail_sum),
            low_stock_count=low_stock_count,
            out_of_stock_count=out_of_stock_count,
            pending_pos=pending_pos,
            pending_sos=pending_sos,
            orders_awaiting_picking=orders_awaiting_picking,
            orders_awaiting_packing=orders_awaiting_packing,
            orders_awaiting_dispatch=orders_awaiting_dispatch,
            total_valuation=round(total_valuation, 2),
            recent_transactions=recent_txs,
            recent_audit_logs=recent_audits,
            recent_receipts=recent_receipts,
            recent_sales_orders=recent_sales,
            operational_alerts=alerts
        )

    @staticmethod
    async def get_inventory_report(
        db: AsyncSession,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        stock_status: Optional[str] = None
    ) -> InventoryReportResponse:
        stmt = (
            select(
                Item.id.label("item_id"),
                ItemVariant.id.label("variant_id"),
                Item.sku,
                Item.name.label("item_name"),
                ItemVariant.variant_name,
                Warehouse.code.label("warehouse_code"),
                Warehouse.name.label("warehouse_name"),
                LocationBin.code.label("bin_code"),
                StockBalanceCache.quantity_on_hand,
                StockBalanceCache.quantity_allocated,
                Item.reorder_point
            )
            .join(ItemVariant, Item.id == ItemVariant.item_id)
            .join(StockBalanceCache, ItemVariant.id == StockBalanceCache.item_variant_id)
            .join(Warehouse, StockBalanceCache.warehouse_id == Warehouse.id)
            .join(LocationBin, StockBalanceCache.location_bin_id == LocationBin.id)
            .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
            .order_by(Item.sku.asc(), Warehouse.code.asc())
        )
        if warehouse_id:
            stmt = stmt.where(Warehouse.id == warehouse_id)

        res = await db.execute(stmt)
        items_out = []
        tot_on_hand = 0.0
        tot_alloc = 0.0
        tot_avail = 0.0

        for r in res.fetchall():
            on_hand = float(r.quantity_on_hand)
            alloc = float(r.quantity_allocated)
            avail = max(0.0, on_hand - alloc)
            reorder = float(r.reorder_point or 0.0)

            status_tag = "IN_STOCK"
            if on_hand == 0:
                status_tag = "OUT_OF_STOCK"
            elif reorder > 0 and on_hand <= reorder:
                status_tag = "LOW_STOCK"

            if stock_status and stock_status.upper() != "ALL":
                if stock_status.upper() != status_tag:
                    continue

            tot_on_hand += on_hand
            tot_alloc += alloc
            tot_avail += avail

            items_out.append(InventoryReportItem(
                item_id=r.item_id,
                variant_id=r.variant_id,
                sku=r.sku,
                item_name=r.item_name,
                variant_name=r.variant_name or "",
                warehouse_code=r.warehouse_code,
                warehouse_name=r.warehouse_name,
                bin_code=r.bin_code,
                quantity_on_hand=on_hand,
                quantity_allocated=alloc,
                quantity_available=avail,
                reorder_point=reorder,
                status=status_tag
            ))

        return InventoryReportResponse(
            total_items_reported=len(items_out),
            total_on_hand=round(tot_on_hand, 2),
            total_allocated=round(tot_alloc, 2),
            total_available=round(tot_avail, 2),
            items=items_out
        )

    @staticmethod
    async def get_purchasing_report(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: Optional[str] = None,
        warehouse_id: Optional[str] = None
    ) -> PurchasingReportResponse:
        stmt = (
            select(PurchaseOrder, Supplier, Warehouse)
            .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
            .join(Warehouse, PurchaseOrder.target_warehouse_id == Warehouse.id)
            .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
            .order_by(desc(PurchaseOrder.ordered_at))
        )
        if supplier_id:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        if warehouse_id:
            stmt = stmt.where(PurchaseOrder.target_warehouse_id == warehouse_id)

        res = await db.execute(stmt)
        items_out = []
        tot_spend = 0.0
        pending_app = 0
        part_recv = 0

        for po, sup, wh in res.fetchall():
            tot_ord = sum(float(l.quantity_ordered) for l in po.lines)
            tot_rec = sum(float(l.quantity_received) for l in po.lines)
            outst = max(0.0, tot_ord - tot_rec)
            spend = float(po.total_amount)
            tot_spend += spend

            if po.status in ["DRAFT", "PENDING_APPROVAL"]:
                pending_app += 1
            if po.status == "PARTIALLY_RECEIVED":
                part_recv += 1

            items_out.append(PurchasingReportItem(
                po_id=po.id,
                po_number=po.po_number,
                supplier_code=sup.code,
                supplier_name=sup.name,
                warehouse_code=wh.code,
                status=po.status,
                ordered_at=po.ordered_at,
                expected_delivery_at=po.expected_delivery_at,
                total_amount=spend,
                total_ordered_qty=tot_ord,
                total_received_qty=tot_rec,
                outstanding_qty=outst
            ))

        return PurchasingReportResponse(
            total_pos=len(items_out),
            total_spend=round(tot_spend, 2),
            pending_approval_count=pending_app,
            partial_receipt_count=part_recv,
            items=items_out
        )

    @staticmethod
    async def get_sales_report(
        db: AsyncSession,
        tenant_id: str,
        customer_id: Optional[str] = None,
        warehouse_id: Optional[str] = None
    ) -> SalesReportResponse:
        stmt = (
            select(SalesOrder, Customer, Warehouse)
            .join(Customer, SalesOrder.customer_id == Customer.id)
            .join(Warehouse, SalesOrder.warehouse_id == Warehouse.id)
            .where(SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
            .order_by(desc(SalesOrder.ordered_at))
        )
        if customer_id:
            stmt = stmt.where(SalesOrder.customer_id == customer_id)
        if warehouse_id:
            stmt = stmt.where(SalesOrder.warehouse_id == warehouse_id)

        res = await db.execute(stmt)
        items_out = []
        tot_sales = 0.0
        alloc_q = 0
        pick_q = 0
        pack_q = 0
        disp_q = 0

        for so, cust, wh in res.fetchall():
            tot_ord = sum(float(l.quantity_ordered) for l in so.lines)
            tot_alc = sum(float(l.quantity_allocated) for l in so.lines)
            tot_shp = sum(float(l.quantity_shipped) for l in so.lines)
            tot_ret = sum(float(l.quantity_returned) for l in so.lines)
            val = float(so.total_amount)
            tot_sales += val

            if so.status == "CONFIRMED":
                alloc_q += 1
            elif so.status == "ALLOCATED":
                pick_q += 1
            elif so.status == "PICKING":
                pack_q += 1
            elif so.status == "PACKED":
                disp_q += 1

            items_out.append(SalesReportItem(
                so_id=so.id,
                so_number=so.so_number,
                customer_code=cust.code,
                customer_name=cust.name,
                warehouse_code=wh.code,
                status=so.status,
                ordered_at=so.ordered_at,
                total_amount=val,
                total_ordered_qty=tot_ord,
                total_allocated_qty=tot_alc,
                total_shipped_qty=tot_shp,
                total_returned_qty=tot_ret
            ))

        return SalesReportResponse(
            total_orders=len(items_out),
            total_sales_value=round(tot_sales, 2),
            allocation_queue_count=alloc_q,
            picking_queue_count=pick_q,
            packing_queue_count=pack_q,
            dispatch_queue_count=disp_q,
            items=items_out
        )

    @staticmethod
    async def global_search(db: AsyncSession, tenant_id: str, query: str) -> GlobalSearchResponse:
        q_clean = query.strip()
        if not q_clean:
            return GlobalSearchResponse(query=query, total_matches=0, results=[])

        search_pat = f"%{q_clean}%"
        results = []

        # 1. Products & Variants
        itm_stmt = (
            select(Item, ItemVariant)
            .join(ItemVariant, Item.id == ItemVariant.item_id)
            .where(
                Item.tenant_id == tenant_id,
                Item.is_deleted == False,
                or_(Item.sku.ilike(search_pat), Item.name.ilike(search_pat), ItemVariant.variant_sku.ilike(search_pat))
            )
            .limit(5)
        )
        itm_res = await db.execute(itm_stmt)
        for itm, var in itm_res.fetchall():
            results.append(GlobalSearchResultItem(
                category="PRODUCT",
                title=f"{itm.sku} - {itm.name}",
                subtitle=f"Variant: {var.variant_name} ({var.variant_sku})",
                identifier=itm.id,
                link_page="/catalog",
                metadata={"sku": itm.sku, "cost": float(var.cost_price or 0)}
            ))

        # 2. Barcodes
        bc_stmt = (
            select(Barcode, ItemVariant, Item)
            .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(Item.tenant_id == tenant_id, Barcode.barcode_value.ilike(search_pat))
            .limit(3)
        )
        bc_res = await db.execute(bc_stmt)
        for bc, var, itm in bc_res.fetchall():
            results.append(GlobalSearchResultItem(
                category="BARCODE",
                title=f"Barcode: {bc.barcode_value}",
                subtitle=f"Mapped to {itm.sku} - {var.variant_name}",
                identifier=bc.id,
                link_page="/catalog",
                metadata={"barcode": bc.barcode_value, "item_id": itm.id}
            ))

        # 3. Customers
        cust_stmt = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.is_deleted == False,
            or_(Customer.code.ilike(search_pat), Customer.name.ilike(search_pat))
        ).limit(4)
        cust_res = await db.execute(cust_stmt)
        for c in cust_res.scalars().all():
            results.append(GlobalSearchResultItem(
                category="CUSTOMER",
                title=f"{c.code} - {c.name}",
                subtitle=f"Contact: {c.email or c.phone or 'N/A'}",
                identifier=c.id,
                link_page="/sales",
                metadata={"code": c.code}
            ))

        # 4. Suppliers
        sup_stmt = select(Supplier).where(
            Supplier.tenant_id == tenant_id,
            Supplier.is_deleted == False,
            or_(Supplier.code.ilike(search_pat), Supplier.name.ilike(search_pat))
        ).limit(4)
        sup_res = await db.execute(sup_stmt)
        for s in sup_res.scalars().all():
            results.append(GlobalSearchResultItem(
                category="SUPPLIER",
                title=f"{s.code} - {s.name}",
                subtitle=f"Terms: {s.payment_terms} &bull; Currency: {s.currency}",
                identifier=s.id,
                link_page="/purchasing",
                metadata={"code": s.code}
            ))

        # 5. Purchase Orders
        po_stmt = select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id,
            PurchaseOrder.is_deleted == False,
            PurchaseOrder.po_number.ilike(search_pat)
        ).limit(4)
        po_res = await db.execute(po_stmt)
        for po in po_res.scalars().all():
            results.append(GlobalSearchResultItem(
                category="PURCHASE_ORDER",
                title=f"PO: {po.po_number}",
                subtitle=f"Status: {po.status} &bull; Amount: ${float(po.total_amount):.2f}",
                identifier=po.id,
                link_page="/purchasing",
                metadata={"status": po.status}
            ))

        # 6. Sales Orders
        so_stmt = select(SalesOrder).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.is_deleted == False,
            SalesOrder.so_number.ilike(search_pat)
        ).limit(4)
        so_res = await db.execute(so_stmt)
        for so in so_res.scalars().all():
            results.append(GlobalSearchResultItem(
                category="SALES_ORDER",
                title=f"SO: {so.so_number}",
                subtitle=f"Status: {so.status} &bull; Total: ${float(so.total_amount):.2f}",
                identifier=so.id,
                link_page="/sales",
                metadata={"status": so.status}
            ))

        # 7. Warehouses
        wh_stmt = select(Warehouse).where(
            Warehouse.tenant_id == tenant_id,
            Warehouse.is_deleted == False,
            or_(Warehouse.code.ilike(search_pat), Warehouse.name.ilike(search_pat))
        ).limit(3)
        wh_res = await db.execute(wh_stmt)
        for wh in wh_res.scalars().all():
            results.append(GlobalSearchResultItem(
                category="WAREHOUSE",
                title=f"Facility: {wh.code} - {wh.name}",
                subtitle=f"Active Status: {'Active' if wh.is_active else 'Inactive'}",
                identifier=wh.id,
                link_page="/warehouses",
                metadata={"code": wh.code}
            ))

        return GlobalSearchResponse(
            query=query,
            total_matches=len(results),
            results=results
        )

    @staticmethod
    async def get_valuation_report(db: AsyncSession, tenant_id: str) -> ValuationReportResponse:
        """
        Calculates an operational inventory valuation estimate based on current on-hand quantities
        multiplied by the configured item/variant cost basis (unit cost).

        Architectural Note:
        Dynamic FIFO cost-layer depletion and moving weighted-average recalculation are deferred
        to future phases. This valuation represents an operational inventory estimate rather than
        a formalized statutory accounting ledger.
        """
        stmt = (
            select(Item, ItemVariant, func.sum(StockBalanceCache.quantity_on_hand))
            .join(ItemVariant, Item.id == ItemVariant.item_id)
            .outerjoin(StockBalanceCache, ItemVariant.id == StockBalanceCache.item_variant_id)
            .where(Item.tenant_id == tenant_id, Item.is_deleted == False)
            .group_by(Item.id, ItemVariant.id)
        )
        res = await db.execute(stmt)
        items = []
        total_val = 0.0

        for item, variant, qty in res.fetchall():
            quantity = float(qty or 0.0)
            unit_cost = float(variant.cost_price or 0.0)
            item_val = quantity * unit_cost
            total_val += item_val
            items.append(ValuationReportItem(
                item_id=item.id,
                sku=item.sku,
                name=f"{item.name} ({variant.variant_name})",
                valuation_method=item.valuation_method,
                total_quantity=quantity,
                unit_cost=unit_cost,
                total_valuation=round(item_val, 2)
            ))

        return ValuationReportResponse(
            total_inventory_value=round(total_val, 2),
            currency="USD",
            items=items
        )

    @staticmethod
    def generate_csv_export(headers: List[str], rows: List[List[Any]]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(r)
        return output.getvalue()
