import io
from typing import List, Optional, Dict, Any
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.schemas.documents import (
    DocumentType, DocumentPayload, DocumentHeader, DocumentParty,
    DocumentFacility, DocumentLine, DocumentSummary, BarcodeLabelItem, BarcodeLabelRequest
)
from app.models.purchasing import PurchaseOrder, POLineItem, GoodsReceipt, GoodsReceiptLine, Supplier
from app.models.sales import SalesOrder, SOLineItem, Shipment, SalesReturn, SalesReturnLine, Customer
from app.models.ledger import StockLedgerTransaction, StockLedgerEntry
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import Item, ItemVariant
from app.models.settings import SystemSetting
from app.core.permissions import check_warehouse_scope

# ReportLab imports
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib import colors
from reportlab.lib.units import mm, inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.graphics.barcode import createBarcodeDrawing

class NumberedCanvas:
    """Helper for page numbering on canvas."""
    pass

class DocumentService:
    @staticmethod
    async def get_system_settings(db: AsyncSession, tenant_id: str) -> SystemSetting:
        stmt = select(SystemSetting).where(SystemSetting.tenant_id == tenant_id)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if not setting:
            setting = SystemSetting(
                tenant_id=tenant_id,
                company_name="AuraStock Enterprise",
                company_email="operations@aurastock.local",
                company_phone="+1 (800) 555-AURA",
                currency="USD"
            )
        return setting

    @staticmethod
    async def get_document_payload(
        db: AsyncSession,
        tenant_id: str,
        document_type: DocumentType,
        document_id: str,
        claims: dict
    ) -> DocumentPayload:
        """
        Assembles authoritative DocumentPayload without recalculating any figures.
        Enforces tenant isolation and warehouse scoping checks.
        """
        settings = await DocumentService.get_system_settings(db, tenant_id)
        comp_name = settings.company_name or "AuraStock Enterprise"
        comp_email = settings.company_email
        comp_phone = settings.company_phone
        comp_addr = getattr(settings, "company_address", None) or "100 Logistics Blvd, Austin, TX"
        currency = settings.currency or "USD"

        if document_type == DocumentType.PURCHASE_ORDER:
            stmt = (
                select(PurchaseOrder)
                .options(
                    selectinload(PurchaseOrder.lines).selectinload(POLineItem.variant).selectinload(ItemVariant.item),
                    selectinload(PurchaseOrder.supplier),
                    selectinload(PurchaseOrder.target_warehouse)
                )
                .where(PurchaseOrder.id == document_id, PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.is_deleted == False)
            )
            res = await db.execute(stmt)
            po = res.scalar_one_or_none()
            if not po:
                raise HTTPException(status_code=404, detail="Purchase Order not found")

            check_warehouse_scope(claims, po.target_warehouse_id)

            lines = []
            for idx, line in enumerate(po.lines, start=1):
                item_name = line.variant.item.name if line.variant and line.variant.item else "Product"
                sku = line.variant.variant_sku if line.variant and hasattr(line.variant, "variant_sku") else (line.variant.item.sku if line.variant and line.variant.item else "SKU")
                var_name = line.variant.variant_name if line.variant and hasattr(line.variant, "variant_name") else ""
                uom = line.variant.item.base_uom if line.variant and line.variant.item and hasattr(line.variant.item, "base_uom") else "PCS"
                lines.append(DocumentLine(
                    line_number=idx,
                    item_sku=sku,
                    item_name=item_name,
                    variant_name=var_name,
                    quantity=float(line.quantity_ordered),
                    uom=uom,
                    unit_price=float(line.unit_price or 0.0),
                    discount=float(line.discount_pct if hasattr(line, "discount_pct") else 0.0),
                    tax=float(line.tax_pct if hasattr(line, "tax_pct") else 0.0),
                    subtotal=float(line.line_total or 0.0)
                ))

            header = DocumentHeader(
                company_name=comp_name,
                company_email=comp_email,
                company_phone=comp_phone,
                company_address=comp_addr,
                document_type=DocumentType.PURCHASE_ORDER,
                document_title="PURCHASE ORDER",
                document_number=po.po_number,
                date_formatted=po.created_at.strftime("%B %d, %Y") if po.created_at else "",
                status=po.status,
                barcode_value=po.po_number
            )

            party = None
            if po.supplier:
                addr_str = f"{po.supplier.address.get('street', '')}, {po.supplier.address.get('city', '')}, {po.supplier.address.get('state', '')} {po.supplier.address.get('postalCode', '')}" if po.supplier.address else ""
                party = DocumentParty(
                    party_type="Vendor / Supplier",
                    name=po.supplier.name,
                    code=po.supplier.code,
                    contact_person=getattr(po.supplier, "contact_name", None) or po.supplier.name,
                    email=po.supplier.email,
                    phone=po.supplier.phone,
                    billing_address=addr_str
                )

            facility = None
            if po.target_warehouse:
                facility = DocumentFacility(
                    warehouse_name=po.target_warehouse.name,
                    warehouse_code=po.target_warehouse.code,
                    address=po.target_warehouse.address.get("city", "") if po.target_warehouse.address else ""
                )

            summary = DocumentSummary(
                currency=currency,
                subtotal=float(po.subtotal_amount or 0.0),
                discount_total=float(po.discount_amount or 0.0),
                tax_total=float(po.tax_amount or 0.0),
                grand_total=float(po.total_amount or 0.0),
                payment_terms=po.supplier.payment_terms if po.supplier and po.supplier.payment_terms else "NET 30",
                notes=po.notes
            )

            return DocumentPayload(
                header=header,
                party=party,
                facility=facility,
                lines=lines,
                summary=summary,
                metadata={"approval_status": po.status, "expected_date": str(po.expected_delivery_at or "")}
            )

        elif document_type == DocumentType.GOODS_RECEIPT:
            stmt = (
                select(GoodsReceipt)
                .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
                .options(
                    selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.variant).selectinload(ItemVariant.item),
                    selectinload(GoodsReceipt.lines).selectinload(GoodsReceiptLine.destination_bin),
                    selectinload(GoodsReceipt.purchase_order).selectinload(PurchaseOrder.supplier),
                    selectinload(GoodsReceipt.warehouse)
                )
                .where(GoodsReceipt.id == document_id, PurchaseOrder.tenant_id == tenant_id, GoodsReceipt.is_deleted == False)
            )
            res = await db.execute(stmt)
            grn = res.scalar_one_or_none()
            if not grn:
                raise HTTPException(status_code=404, detail="Goods Receipt not found")

            check_warehouse_scope(claims, grn.warehouse_id)

            lines = []
            for idx, line in enumerate(grn.lines, start=1):
                item_name = line.variant.item.name if line.variant and line.variant.item else "Product"
                sku = line.variant.variant_sku if line.variant and hasattr(line.variant, "variant_sku") else (line.variant.item.sku if line.variant and line.variant.item else "SKU")
                var_name = line.variant.variant_name if line.variant and hasattr(line.variant, "variant_name") else ""
                lines.append(DocumentLine(
                    line_number=idx,
                    item_sku=sku,
                    item_name=item_name,
                    variant_name=var_name,
                    bin_location=line.destination_bin.code if line.destination_bin else None,
                    quantity=float(line.quantity_received),
                    uom="PCS",
                    notes=f"Batch: {line.batch_number}" if line.batch_number else None
                ))

            header = DocumentHeader(
                company_name=comp_name,
                company_email=comp_email,
                company_phone=comp_phone,
                company_address=comp_addr,
                document_type=DocumentType.GOODS_RECEIPT,
                document_title="GOODS RECEIPT NOTE (GRN)",
                document_number=grn.grn_number,
                date_formatted=grn.received_at.strftime("%B %d, %Y %H:%M") if grn.received_at else "",
                status="RECEIVED",
                barcode_value=grn.grn_number
            )

            party = None
            if grn.purchase_order and grn.purchase_order.supplier:
                sup = grn.purchase_order.supplier
                party = DocumentParty(
                    party_type="Vendor / Supplier",
                    name=sup.name,
                    code=sup.code,
                    contact_person=getattr(sup, "contact_name", None) or sup.name,
                    email=sup.email,
                    phone=sup.phone
                )

            facility = None
            if grn.warehouse:
                facility = DocumentFacility(
                    warehouse_name=grn.warehouse.name,
                    warehouse_code=grn.warehouse.code
                )

            return DocumentPayload(
                header=header,
                party=party,
                facility=facility,
                lines=lines,
                summary=None,
                metadata={"po_number": grn.purchase_order.po_number if grn.purchase_order else "", "notes": grn.notes}
            )

        elif document_type in [DocumentType.SALES_ORDER, DocumentType.SALES_INVOICE, DocumentType.PACKING_SLIP, DocumentType.DELIVERY_NOTE]:
            stmt = (
                select(SalesOrder)
                .options(
                    selectinload(SalesOrder.lines).selectinload(SOLineItem.variant).selectinload(ItemVariant.item),
                    selectinload(SalesOrder.customer),
                    selectinload(SalesOrder.warehouse),
                    selectinload(SalesOrder.shipments)
                )
                .where(SalesOrder.id == document_id, SalesOrder.tenant_id == tenant_id, SalesOrder.is_deleted == False)
            )
            res = await db.execute(stmt)
            so = res.scalar_one_or_none()
            if not so:
                raise HTTPException(status_code=404, detail="Sales Order not found")

            check_warehouse_scope(claims, so.warehouse_id)

            title_map = {
                DocumentType.SALES_ORDER: "SALES ORDER CONFIRMATION",
                DocumentType.SALES_INVOICE: "COMMERCIAL SALES INVOICE",
                DocumentType.PACKING_SLIP: "WAREHOUSE PACKING SLIP",
                DocumentType.DELIVERY_NOTE: "DISPATCH & DELIVERY NOTE",
            }

            header = DocumentHeader(
                company_name=comp_name,
                company_email=comp_email,
                company_phone=comp_phone,
                company_address=comp_addr,
                document_type=document_type,
                document_title=title_map[document_type],
                document_number=so.so_number if document_type != DocumentType.SALES_INVOICE else f"INV-{so.so_number.replace('SO-', '')}",
                date_formatted=so.created_at.strftime("%B %d, %Y") if so.created_at else "",
                status=so.status,
                barcode_value=so.so_number
            )

            party = None
            if so.customer:
                bill_str = f"{so.customer.billing_address.get('street', '')}, {so.customer.billing_address.get('city', '')} {so.customer.billing_address.get('state', '')}" if so.customer.billing_address else ""
                ship_str = f"{so.customer.shipping_address.get('street', '')}, {so.customer.shipping_address.get('city', '')} {so.customer.shipping_address.get('state', '')}" if so.customer.shipping_address else bill_str
                party = DocumentParty(
                    party_type="Customer / Buyer",
                    name=so.customer.name,
                    code=so.customer.code,
                    contact_person=getattr(so.customer, "contact_name", None) or so.customer.name,
                    email=so.customer.email,
                    phone=so.customer.phone,
                    billing_address=bill_str,
                    shipping_address=ship_str
                )

            facility = None
            if so.warehouse:
                facility = DocumentFacility(
                    warehouse_name=so.warehouse.name,
                    warehouse_code=so.warehouse.code,
                    address=so.warehouse.address.get("city", "") if so.warehouse.address else ""
                )

            lines = []
            for idx, line in enumerate(so.lines, start=1):
                item_name = line.variant.item.name if line.variant and line.variant.item else "Product"
                sku = line.variant.variant_sku if line.variant and hasattr(line.variant, "variant_sku") else (line.variant.item.sku if line.variant and line.variant.item else "SKU")
                var_name = line.variant.variant_name if line.variant and hasattr(line.variant, "variant_name") else ""
                uom = line.variant.item.base_uom if line.variant and line.variant.item and hasattr(line.variant.item, "base_uom") else "PCS"

                # If Packing slip or delivery note, hide prices for logistics focus
                is_financial = document_type in [DocumentType.SALES_ORDER, DocumentType.SALES_INVOICE]

                lines.append(DocumentLine(
                    line_number=idx,
                    item_sku=sku,
                    item_name=item_name,
                    variant_name=var_name,
                    quantity=float(line.quantity_ordered if document_type != DocumentType.DELIVERY_NOTE else line.quantity_shipped),
                    uom=uom,
                    unit_price=float(line.unit_price or 0.0) if is_financial else None,
                    discount=float(line.discount_pct if hasattr(line, "discount_pct") else 0.0) if is_financial else 0.0,
                    tax=float(line.tax_pct if hasattr(line, "tax_pct") else 0.0) if is_financial else 0.0,
                    subtotal=float(line.line_total or 0.0) if is_financial else None,
                    notes=f"Allocated: {float(line.quantity_allocated)}" if document_type == DocumentType.PACKING_SLIP else None
                ))

            summary = None
            if document_type in [DocumentType.SALES_ORDER, DocumentType.SALES_INVOICE]:
                summary = DocumentSummary(
                    currency=currency,
                    subtotal=float(so.subtotal_amount or 0.0),
                    discount_total=float(so.discount_amount or 0.0),
                    tax_total=float(so.tax_amount or 0.0),
                    grand_total=float(so.total_amount or 0.0),
                    payment_terms="Net 30 Days",
                    notes=so.notes
                )

            latest_shipment = so.shipments[-1] if hasattr(so, "shipments") and so.shipments else None
            carrier = latest_shipment.carrier if latest_shipment and latest_shipment.carrier else "Standard Ground"
            tracking = latest_shipment.tracking_number if latest_shipment and latest_shipment.tracking_number else "N/A"

            return DocumentPayload(
                header=header,
                party=party,
                facility=facility,
                lines=lines,
                summary=summary,
                metadata={"carrier": carrier, "tracking_number": tracking}
            )

        elif document_type in [DocumentType.STOCK_TRANSFER, DocumentType.STOCK_ADJUSTMENT]:
            stmt = (
                select(StockLedgerTransaction)
                .options(
                    selectinload(StockLedgerTransaction.entries).selectinload(StockLedgerEntry.variant).selectinload(ItemVariant.item),
                    selectinload(StockLedgerTransaction.entries).selectinload(StockLedgerEntry.source_bin).selectinload(LocationBin.warehouse),
                    selectinload(StockLedgerTransaction.entries).selectinload(StockLedgerEntry.destination_bin).selectinload(LocationBin.warehouse)
                )
                .where(StockLedgerTransaction.id == document_id, StockLedgerTransaction.tenant_id == tenant_id, StockLedgerTransaction.is_deleted == False)
            )
            res = await db.execute(stmt)
            tx = res.scalar_one_or_none()
            if not tx:
                raise HTTPException(status_code=404, detail="Stock Transaction not found")

            # Check warehouse access on touched warehouses
            touched_whs = set()
            for e in tx.entries:
                if e.source_bin and e.source_bin.warehouse_id:
                    touched_whs.add(e.source_bin.warehouse_id)
                if e.destination_bin and e.destination_bin.warehouse_id:
                    touched_whs.add(e.destination_bin.warehouse_id)
            for wh_id in touched_whs:
                check_warehouse_scope(claims, wh_id)

            title = "INTERNAL STOCK TRANSFER DOCKET" if document_type == DocumentType.STOCK_TRANSFER else "INVENTORY ADJUSTMENT VOUCHER"

            header = DocumentHeader(
                company_name=comp_name,
                company_email=comp_email,
                company_phone=comp_phone,
                company_address=comp_addr,
                document_type=document_type,
                document_title=title,
                document_number=tx.transaction_number,
                date_formatted=tx.posted_at.strftime("%B %d, %Y %H:%M") if tx.posted_at else "",
                status="POSTED",
                barcode_value=tx.transaction_number
            )

            lines = []
            for idx, entry in enumerate(tx.entries, start=1):
                item_name = entry.variant.item.name if entry.variant and entry.variant.item else "Item"
                sku = entry.variant.variant_sku if entry.variant and hasattr(entry.variant, "variant_sku") else (entry.variant.item.sku if entry.variant and entry.variant.item else "SKU")
                var_name = entry.variant.variant_name if entry.variant and hasattr(entry.variant, "variant_name") else ""
                
                src_code = f"{entry.source_bin.warehouse.code}:{entry.source_bin.code}" if entry.source_bin and entry.source_bin.warehouse else (entry.source_bin.code if entry.source_bin else "")
                dst_code = f"{entry.destination_bin.warehouse.code}:{entry.destination_bin.code}" if entry.destination_bin and entry.destination_bin.warehouse else (entry.destination_bin.code if entry.destination_bin else "")
                
                if src_code and dst_code:
                    loc_display = f"{src_code} -> {dst_code}"
                elif dst_code:
                    loc_display = f"+ {dst_code}"
                elif src_code:
                    loc_display = f"- {src_code}"
                else:
                    loc_display = "Warehouse Bin"

                lines.append(DocumentLine(
                    line_number=idx,
                    item_sku=sku,
                    item_name=item_name,
                    variant_name=var_name,
                    bin_location=loc_display,
                    quantity=float(entry.quantity),
                    uom=entry.uom or "PCS",
                    notes=f"Unit Cost: ${float(entry.unit_cost):.2f}"
                ))

            return DocumentPayload(
                header=header,
                party=None,
                facility=None,
                lines=lines,
                summary=None,
                metadata={"transaction_type": tx.transaction_type, "notes": tx.notes or "Operational ledger post"}
            )

        elif document_type == DocumentType.SALES_RETURN:
            stmt = (
                select(SalesReturn)
                .join(SalesOrder, SalesReturn.sales_order_id == SalesOrder.id)
                .options(
                    selectinload(SalesReturn.lines).selectinload(SalesReturnLine.variant).selectinload(ItemVariant.item),
                    selectinload(SalesReturn.lines).selectinload(SalesReturnLine.destination_bin),
                    selectinload(SalesReturn.sales_order).selectinload(SalesOrder.customer),
                    selectinload(SalesReturn.sales_order).selectinload(SalesOrder.warehouse)
                )
                .where(SalesReturn.id == document_id, SalesOrder.tenant_id == tenant_id, SalesReturn.is_deleted == False)
            )
            res = await db.execute(stmt)
            rma = res.scalar_one_or_none()
            if not rma:
                raise HTTPException(status_code=404, detail="Sales Return not found")

            check_warehouse_scope(claims, rma.sales_order.warehouse_id)

            header = DocumentHeader(
                company_name=comp_name,
                company_email=comp_email,
                company_phone=comp_phone,
                company_address=comp_addr,
                document_type=DocumentType.SALES_RETURN,
                document_title="RETURN MERCHANDISE AUTHORIZATION (RMA)",
                document_number=rma.return_number,
                date_formatted=rma.returned_at.strftime("%B %d, %Y") if rma.returned_at else "",
                status=rma.status,
                barcode_value=rma.return_number
            )

            party = None
            if rma.sales_order and rma.sales_order.customer:
                cust = rma.sales_order.customer
                party = DocumentParty(
                    party_type="Customer / Buyer",
                    name=cust.name,
                    code=cust.code,
                    email=cust.email,
                    phone=cust.phone
                )

            facility = None
            if rma.sales_order and rma.sales_order.warehouse:
                wh = rma.sales_order.warehouse
                facility = DocumentFacility(
                    warehouse_name=wh.name,
                    warehouse_code=wh.code
                )

            lines = []
            for idx, line in enumerate(rma.lines, start=1):
                item_name = line.variant.item.name if line.variant and line.variant.item else "Product"
                sku = line.variant.variant_sku if line.variant and hasattr(line.variant, "variant_sku") else (line.variant.item.sku if line.variant and line.variant.item else "SKU")
                var_name = line.variant.variant_name if line.variant and hasattr(line.variant, "variant_name") else ""
                lines.append(DocumentLine(
                    line_number=idx,
                    item_sku=sku,
                    item_name=item_name,
                    variant_name=var_name,
                    quantity=float(line.quantity_returned),
                    uom="PCS",
                    notes=f"Condition: {line.condition}" + (f" | {rma.notes}" if rma.notes else "")
                ))

            return DocumentPayload(
                header=header,
                party=party,
                facility=facility,
                lines=lines,
                summary=None,
                metadata={"notes": rma.notes or "Sales Return RMA", "status": rma.status}
            )

        raise HTTPException(status_code=400, detail=f"Unsupported document type {document_type}")

    # =========================================================================
    # PDF GENERATION ENGINE
    # =========================================================================

    @staticmethod
    def generate_pdf(payload: DocumentPayload, layout: str = "A4") -> bytes:
        """
        Generates a clean vector PDF using ReportLab Platypus.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm
        )

        styles = getSampleStyleSheet()
        primary_color = colors.HexColor("#0f172a")
        accent_color = colors.HexColor("#2563eb")
        text_dark = colors.HexColor("#1e293b")
        text_muted = colors.HexColor("#64748b")
        bg_light = colors.HexColor("#f8fafc")
        border_color = colors.HexColor("#e2e8f0")

        header_title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=primary_color
        )
        company_name_style = ParagraphStyle(
            "CompName",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=accent_color
        )
        body_style = ParagraphStyle(
            "DocBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=text_dark
        )
        body_bold_style = ParagraphStyle(
            "DocBodyBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            textColor=text_dark
        )
        muted_style = ParagraphStyle(
            "DocMuted",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=text_muted
        )
        table_header_style = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white
        )

        elements = []

        # 1. Header Bar Table (Company Info & Document Meta)
        comp_info = [
            Paragraph(payload.header.company_name, company_name_style),
            Paragraph(payload.header.company_address or "", body_style),
            Paragraph(f"Email: {payload.header.company_email or 'support@aurastock.local'} | Phone: {payload.header.company_phone or 'N/A'}", muted_style)
        ]

        doc_meta = [
            Paragraph(f"<b>{payload.header.document_title}</b>", header_title_style),
            Paragraph(f"<b>Document #:</b> {payload.header.document_number}", body_bold_style),
            Paragraph(f"<b>Date:</b> {payload.header.date_formatted}", body_style),
            Paragraph(f"<b>Status:</b> {payload.header.status}", body_bold_style)
        ]

        header_table = Table([[comp_info, doc_meta]], colWidths=[100 * mm, 80 * mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 8 * mm))

        # 2. Barcode Graphic
        try:
            barcode = createBarcodeDrawing('Code128', value=payload.header.barcode_value, barWidth=1.2, barHeight=25, humanReadable=True)
            elements.append(barcode)
            elements.append(Spacer(1, 6 * mm))
        except Exception:
            pass

        # 3. Addresses Table (Party & Facility)
        party_col = []
        if payload.party:
            party_col.append(Paragraph(f"<b>{payload.party.party_type}</b>", body_bold_style))
            party_col.append(Paragraph(f"<b>{payload.party.name}</b>", body_style))
            if payload.party.code:
                party_col.append(Paragraph(f"Account Code: {payload.party.code}", muted_style))
            if payload.party.billing_address:
                party_col.append(Paragraph(f"Billing Address: {payload.party.billing_address}", muted_style))
            if payload.party.shipping_address:
                party_col.append(Paragraph(f"Ship To: {payload.party.shipping_address}", muted_style))
            if payload.party.email:
                party_col.append(Paragraph(f"Contact: {payload.party.email} | {payload.party.phone or ''}", muted_style))

        facility_col = []
        if payload.facility:
            facility_col.append(Paragraph("<b>Fulfillment / Target Facility</b>", body_bold_style))
            facility_col.append(Paragraph(f"<b>{payload.facility.warehouse_name}</b> ({payload.facility.warehouse_code})", body_style))
            if payload.facility.address:
                facility_col.append(Paragraph(f"Location: {payload.facility.address}", muted_style))
        elif payload.metadata:
            facility_col.append(Paragraph("<b>Logistics & Metadata</b>", body_bold_style))
            for k, v in payload.metadata.items():
                facility_col.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", muted_style))

        if party_col or facility_col:
            addr_table = Table([[party_col or "", facility_col or ""]], colWidths=[90 * mm, 90 * mm])
            addr_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, -1), bg_light),
                ('BOX', (0, 0), (-1, -1), 0.5, border_color),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(addr_table)
            elements.append(Spacer(1, 8 * mm))

        # 4. Line Items Table
        is_financial = payload.summary is not None

        if is_financial:
            headers = [
                Paragraph("#", table_header_style),
                Paragraph("SKU / Description", table_header_style),
                Paragraph("Qty", table_header_style),
                Paragraph("Unit Price", table_header_style),
                Paragraph("Discount", table_header_style),
                Paragraph("Tax", table_header_style),
                Paragraph("Subtotal", table_header_style),
            ]
            col_widths = [10 * mm, 65 * mm, 20 * mm, 22 * mm, 20 * mm, 20 * mm, 23 * mm]
        else:
            headers = [
                Paragraph("#", table_header_style),
                Paragraph("SKU / Item Description", table_header_style),
                Paragraph("Location / Details", table_header_style),
                Paragraph("Quantity", table_header_style),
                Paragraph("Notes", table_header_style),
            ]
            col_widths = [10 * mm, 70 * mm, 40 * mm, 25 * mm, 35 * mm]

        table_data = [headers]

        for line in payload.lines:
            desc = f"<b>{line.item_name}</b><br/><font color='#64748b'>SKU: {line.item_sku} {f'({line.variant_name})' if line.variant_name else ''}</font>"
            if is_financial:
                row = [
                    Paragraph(str(line.line_number), body_style),
                    Paragraph(desc, body_style),
                    Paragraph(f"{line.quantity:g} {line.uom}", body_style),
                    Paragraph(f"${line.unit_price:.2f}" if line.unit_price is not None else "-", body_style),
                    Paragraph(f"${line.discount:.2f}" if line.discount else "-", muted_style),
                    Paragraph(f"${line.tax:.2f}" if line.tax else "-", muted_style),
                    Paragraph(f"${line.subtotal:.2f}" if line.subtotal is not None else "-", body_bold_style),
                ]
            else:
                row = [
                    Paragraph(str(line.line_number), body_style),
                    Paragraph(desc, body_style),
                    Paragraph(line.bin_location or "-", muted_style),
                    Paragraph(f"{line.quantity:g} {line.uom}", body_bold_style),
                    Paragraph(line.notes or "-", muted_style),
                ]
            table_data.append(row)

        lines_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        lines_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, border_color),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(lines_table)
        elements.append(Spacer(1, 6 * mm))

        # 5. Financial Summary Block
        if payload.summary:
            sum_rows = [
                [Paragraph("<b>Subtotal:</b>", body_style), Paragraph(f"${payload.summary.subtotal:.2f}", body_style)],
                [Paragraph("<b>Discount:</b>", body_style), Paragraph(f"-${payload.summary.discount_total:.2f}", muted_style)],
                [Paragraph("<b>Estimated Tax:</b>", body_style), Paragraph(f"+${payload.summary.tax_total:.2f}", muted_style)],
                [Paragraph("<b>Grand Total:</b>", header_title_style), Paragraph(f"<b>${payload.summary.grand_total:.2f} {payload.summary.currency}</b>", header_title_style)],
            ]
            sum_table = Table(sum_rows, colWidths=[40 * mm, 35 * mm])
            sum_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEABOVE', (0, 3), (-1, 3), 1, primary_color),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))

            terms_box = [
                Paragraph(f"<b>Payment Terms:</b> {payload.summary.payment_terms or 'Net 30'}", body_style),
                Paragraph(f"<b>Notes / Instructions:</b> {payload.summary.notes or 'None'}", muted_style)
            ]
            terms_table = Table([[terms_box, sum_table]], colWidths=[105 * mm, 75 * mm])
            terms_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(KeepTogether(terms_table))
            elements.append(Spacer(1, 8 * mm))

        # 6. Footer Text
        elements.append(Paragraph(payload.footer_text or "Authorized System Document", muted_style))

        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()

    # =========================================================================
    # BARCODE LABELS PDF GENERATION
    # =========================================================================

    @staticmethod
    def generate_barcode_labels_pdf(request: BarcodeLabelRequest) -> bytes:
        """
        Generates printable 2x1 sticker labels arranged in multi-column sheet.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=10 * mm,
            rightMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "LabelTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.black
        )
        sku_style = ParagraphStyle(
            "LabelSKU",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#334155")
        )
        loc_style = ParagraphStyle(
            "LabelLoc",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#64748b")
        )

        label_cards = []
        for item in request.labels:
            for _ in range(request.copies_per_label):
                card_elements = [
                    Paragraph(f"<b>{item.title[:26]}</b>", title_style),
                    Paragraph(f"SKU: {item.sku} {f'| {item.variant}' if item.variant else ''}", sku_style)
                ]
                try:
                    bc = createBarcodeDrawing('Code128', value=item.barcode, barWidth=1.0, barHeight=18, humanReadable=True)
                    card_elements.append(bc)
                except Exception:
                    card_elements.append(Paragraph(f"[{item.barcode}]", sku_style))

                if item.bin_code:
                    card_elements.append(Paragraph(f"BIN: <b>{item.bin_code}</b>", loc_style))

                label_cards.append(card_elements)

        # Arrange in 3-column table
        cols = 3
        rows = []
        current_row = []
        for card in label_cards:
            current_row.append(card)
            if len(current_row) == cols:
                rows.append(current_row)
                current_row = []
        if current_row:
            while len(current_row) < cols:
                current_row.append([])
            rows.append(current_row)

        if not rows:
            rows = [[[]]]

        sheet_table = Table(rows, colWidths=[60 * mm] * cols)
        sheet_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))

        doc.build([sheet_table])
        buffer.seek(0)
        return buffer.getvalue()
