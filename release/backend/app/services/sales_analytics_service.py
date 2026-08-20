from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case

from app.models.sales import SalesOrder, SOLineItem, Shipment, SalesReturn, SalesReturnLine, Customer
from app.models.costing import COGSRecord
from app.models.warehouse import Warehouse
from app.models.item import ItemVariant, Item
from app.schemas.analytics import (
    SalesSummaryKPIs,
    ProductSalesAnalyticsItem,
    CustomerSalesAnalyticsItem,
    WarehouseSalesAnalyticsItem
)

class SalesAnalyticsService:
    @staticmethod
    async def get_executive_sales_summary(
        db: AsyncSession,
        tenant_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> SalesSummaryKPIs:
        # Base filter
        so_stmt = select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
        if from_date:
            so_stmt = so_stmt.where(SalesOrder.ordered_at >= from_date)
        if to_date:
            so_stmt = so_stmt.where(SalesOrder.ordered_at <= to_date)

        sos = (await db.execute(so_stmt)).scalars().all()

        total_orders = len(sos)
        delivered_orders = sum(1 for so in sos if so.status == "DELIVERED")
        cancelled_orders = sum(1 for so in sos if so.status == "CANCELLED")

        gross_rev = sum(Decimal(str(so.subtotal_amount or 0.0)) for so in sos if so.status != "CANCELLED")
        disc_tot = sum(Decimal(str(so.discount_amount or 0.0)) for so in sos if so.status != "CANCELLED")
        tax_tot = sum(Decimal(str(so.tax_amount or 0.0)) for so in sos if so.status != "CANCELLED")
        net_rev = gross_rev - disc_tot

        # Query Authoritative COGS from COGSRecord
        cogs_stmt = select(func.coalesce(func.sum(COGSRecord.total_cogs_amount), 0.0)).where(
            COGSRecord.tenant_id == tenant_id
        )
        if from_date:
            cogs_stmt = cogs_stmt.where(COGSRecord.recognized_at >= from_date)
        if to_date:
            cogs_stmt = cogs_stmt.where(COGSRecord.recognized_at <= to_date)

        auth_cogs = Decimal(str((await db.execute(cogs_stmt)).scalar() or 0.0))

        gross_profit = net_rev - auth_cogs
        gross_margin_pct = (gross_profit / net_rev * Decimal("100.0")) if net_rev > Decimal("0.0") else Decimal("0.0")

        # Fill rate & OTIF
        total_ordered_qty = sum(sum(Decimal(str(l.quantity_ordered)) for l in so.lines) for so in sos if so.status != "CANCELLED")
        total_shipped_qty = sum(sum(Decimal(str(l.quantity_shipped)) for l in so.lines) for so in sos if so.status != "CANCELLED")
        total_returned_qty = sum(sum(Decimal(str(l.quantity_returned)) for l in so.lines) for so in sos if so.status != "CANCELLED")

        fill_rate = (total_shipped_qty / total_ordered_qty * Decimal("100.0")) if total_ordered_qty > Decimal("0.0") else Decimal("100.0")
        otif = (Decimal(str(delivered_orders)) / Decimal(str(total_orders)) * Decimal("100.0")) if total_orders > 0 else Decimal("100.0")
        cancel_rate = (Decimal(str(cancelled_orders)) / Decimal(str(total_orders)) * Decimal("100.0")) if total_orders > 0 else Decimal("0.0")
        return_rate = (total_returned_qty / total_shipped_qty * Decimal("100.0")) if total_shipped_qty > Decimal("0.0") else Decimal("0.0")
        aov = (net_rev / Decimal(str(total_orders - cancelled_orders))) if (total_orders - cancelled_orders) > 0 else Decimal("0.0")

        return SalesSummaryKPIs(
            total_orders_placed=total_orders,
            total_orders_delivered=delivered_orders,
            total_orders_cancelled=cancelled_orders,
            gross_sales_revenue=float(gross_rev),
            discount_total=float(disc_tot),
            tax_total=float(tax_tot),
            net_sales_revenue=float(net_rev),
            authoritative_cogs=float(auth_cogs),
            gross_profit_amount=float(gross_profit),
            gross_profit_margin_pct=round(float(gross_margin_pct), 2),
            average_order_value=round(float(aov), 2),
            fill_rate_pct=round(float(fill_rate), 2),
            on_time_in_full_pct=round(float(otif), 2),
            cancellation_rate_pct=round(float(cancel_rate), 2),
            return_rate_pct=round(float(return_rate), 2)
        )

    @staticmethod
    async def get_sales_by_product(
        db: AsyncSession,
        tenant_id: str
    ) -> List[ProductSalesAnalyticsItem]:
        stmt = (
            select(
                ItemVariant.id,
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                ItemVariant.variant_sku,
                ItemVariant.variant_name,
                func.coalesce(func.sum(SOLineItem.quantity_ordered), 0.0).label("units_ordered"),
                func.coalesce(func.sum(SOLineItem.quantity_shipped), 0.0).label("units_shipped"),
                func.coalesce(func.sum(SOLineItem.line_total), 0.0).label("net_revenue")
            )
            .join(Item, ItemVariant.item_id == Item.id)
            .outerjoin(SOLineItem, SOLineItem.item_variant_id == ItemVariant.id)
            .where(Item.tenant_id == tenant_id)
            .group_by(ItemVariant.id, Item.sku, Item.name, ItemVariant.variant_sku, ItemVariant.variant_name)
        )
        rows = (await db.execute(stmt)).all()

        results = []
        for r in rows:
            var_id = r[0]
            units_ord = float(r[5])
            units_shp = float(r[6])
            rev = float(r[7])

            # Get authoritative COGS for this variant
            cogs_stmt = select(func.coalesce(func.sum(COGSRecord.total_cogs_amount), 0.0)).where(
                COGSRecord.tenant_id == tenant_id,
                COGSRecord.item_variant_id == var_id
            )
            cogs_val = float((await db.execute(cogs_stmt)).scalar() or 0.0)
            margin_amt = rev - cogs_val
            margin_pct = (margin_amt / rev * 100.0) if rev > 0 else 0.0

            results.append(ProductSalesAnalyticsItem(
                item_variant_id=var_id,
                item_sku=r[1],
                item_name=r[2],
                variant_sku=r[3],
                variant_name=r[4],
                units_ordered=units_ord,
                units_shipped=units_shp,
                net_revenue=rev,
                authoritative_cogs=cogs_val,
                gross_margin_amount=round(margin_amt, 2),
                gross_margin_pct=round(margin_pct, 2)
            ))
        return results

    @staticmethod
    async def get_sales_by_customer(
        db: AsyncSession,
        tenant_id: str
    ) -> List[CustomerSalesAnalyticsItem]:
        stmt = (
            select(
                Customer.id,
                Customer.code,
                Customer.name,
                func.count(SalesOrder.id).label("order_count"),
                func.coalesce(func.sum(SalesOrder.total_amount), 0.0).label("total_spend")
            )
            .outerjoin(SalesOrder, and_(SalesOrder.customer_id == Customer.id, SalesOrder.status != "CANCELLED"))
            .where(Customer.tenant_id == tenant_id, Customer.is_deleted == False)
            .group_by(Customer.id, Customer.code, Customer.name)
        )
        rows = (await db.execute(stmt)).all()

        results = []
        for r in rows:
            cust_id = r[0]
            spend = float(r[4])

            # Authoritative COGS for customer
            cogs_stmt = (
                select(func.coalesce(func.sum(COGSRecord.total_cogs_amount), 0.0))
                .join(SalesOrder, COGSRecord.sales_order_id == SalesOrder.id)
                .where(SalesOrder.customer_id == cust_id)
            )
            cogs_val = float((await db.execute(cogs_stmt)).scalar() or 0.0)
            margin_amt = spend - cogs_val
            margin_pct = (margin_amt / spend * 100.0) if spend > 0 else 0.0

            results.append(CustomerSalesAnalyticsItem(
                customer_id=cust_id,
                customer_code=r[1],
                customer_name=r[2],
                order_count=int(r[3]),
                total_spend=spend,
                authoritative_cogs=cogs_val,
                gross_margin_amount=round(margin_amt, 2),
                gross_margin_pct=round(margin_pct, 2)
            ))
        return results

    @staticmethod
    async def get_sales_by_warehouse(
        db: AsyncSession,
        tenant_id: str
    ) -> List[WarehouseSalesAnalyticsItem]:
        stmt = (
            select(
                Warehouse.id,
                Warehouse.code,
                Warehouse.name,
                func.count(Shipment.id).label("shipment_count"),
                func.coalesce(func.sum(SalesOrder.total_amount), 0.0).label("net_revenue")
            )
            .outerjoin(SalesOrder, and_(SalesOrder.warehouse_id == Warehouse.id, SalesOrder.status != "CANCELLED"))
            .outerjoin(Shipment, Shipment.sales_order_id == SalesOrder.id)
            .where(Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
            .group_by(Warehouse.id, Warehouse.code, Warehouse.name)
        )
        rows = (await db.execute(stmt)).all()

        results = []
        for r in rows:
            wh_id = r[0]
            rev = float(r[4])

            cogs_stmt = (
                select(func.coalesce(func.sum(COGSRecord.total_cogs_amount), 0.0))
                .join(SalesOrder, COGSRecord.sales_order_id == SalesOrder.id)
                .where(SalesOrder.warehouse_id == wh_id)
            )
            cogs_val = float((await db.execute(cogs_stmt)).scalar() or 0.0)

            results.append(WarehouseSalesAnalyticsItem(
                warehouse_id=wh_id,
                warehouse_code=r[1],
                warehouse_name=r[2],
                shipment_count=int(r[3]),
                units_dispatched=0.0,
                net_revenue=rev,
                authoritative_cogs=cogs_val,
                fill_rate_pct=100.0
            ))
        return results
