import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status

from app.models.purchasing import (
    PurchaseOrder,
    POLineItem,
    GoodsReceipt,
    GoodsReceiptLine,
    Supplier,
    SupplierContact,
    SupplierAddress,
    SupplierProduct,
    SupplierPriceHistory,
    SupplierReturn,
    SupplierReturnLine,
    SupplierDebitMemo
)
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemVariant, Item
from app.models.ledger import StockBalanceCache
from app.models.base import get_utc_now
from app.schemas.purchasing import (
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
    GoodsReceiptCreate,
    POLineCreate,
    SupplierCreate,
    SupplierUpdate,
    SupplierProductCreate,
    SupplierProductUpdate,
    SupplierReturnCreate
)
from app.services.stock_engine import StockEngine
from app.services.audit_service import AuditService
from app.services.sequence_service import SequenceService
from app.services.costing_service import CostingService

class PurchaseService:
    @staticmethod
    def _compute_line_totals(lines: List[POLineCreate]) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
        """Calculates subtotal, discount, tax, and grand total."""
        subtotal = Decimal("0.0")
        disc_total = Decimal("0.0")
        tax_total = Decimal("0.0")

        for line in lines:
            qty = Decimal(str(line.quantity_ordered))
            price = Decimal(str(line.unit_price))
            disc_pct = Decimal(str(line.discount_pct or 0.0))
            tax_pct = Decimal(str(line.tax_pct or 0.0))

            base_amt = qty * price
            disc_amt = base_amt * (disc_pct / Decimal("100.0"))
            after_disc = base_amt - disc_amt
            tax_amt = after_disc * (tax_pct / Decimal("100.0"))

            subtotal += base_amt
            disc_total += disc_amt
            tax_total += tax_amt

        grand_total = subtotal - disc_total + tax_total
        return subtotal, disc_total, tax_total, grand_total

    # ============================================================================
    # SUPPLIER MASTER & RELATIONSHIPS
    # ============================================================================

    @staticmethod
    async def create_supplier(
        db: AsyncSession,
        tenant_id: str,
        sup_in: SupplierCreate,
        user_id: Optional[str] = None
    ) -> Supplier:
        # Check code uniqueness in tenant
        existing = (await db.execute(
            select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.code == sup_in.code, Supplier.is_deleted == False)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail=f"Supplier with code '{sup_in.code}' already exists in tenant")

        supplier = Supplier(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            code=sup_in.code,
            name=sup_in.name,
            email=sup_in.email,
            phone=sup_in.phone,
            address=sup_in.address,
            tax_identifier=sup_in.tax_identifier,
            payment_terms=sup_in.payment_terms,
            credit_limit=sup_in.credit_limit or Decimal("0.0"),
            currency=sup_in.currency,
            status=sup_in.status,
            is_active=sup_in.is_active
        )
        db.add(supplier)

        # Add contacts
        if sup_in.contacts:
            for c in sup_in.contacts:
                contact = SupplierContact(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    supplier_id=supplier.id,
                    contact_name=c.contact_name,
                    email=c.email,
                    phone=c.phone,
                    designation=c.designation,
                    is_primary=c.is_primary
                )
                db.add(contact)

        # Add addresses
        if sup_in.addresses:
            for a in sup_in.addresses:
                addr = SupplierAddress(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    supplier_id=supplier.id,
                    address_type=a.address_type,
                    address_line1=a.address_line1,
                    address_line2=a.address_line2,
                    city=a.city,
                    state=a.state,
                    postal_code=a.postal_code,
                    country=a.country,
                    is_default=a.is_default
                )
                db.add(addr)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE",
            entity_type="Supplier",
            entity_id=supplier.id,
            user_id=user_id,
            changes={"code": supplier.code, "name": supplier.name}
        )

        await db.commit()
        await db.refresh(supplier)
        return supplier

    @staticmethod
    async def update_supplier(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        sup_in: SupplierUpdate,
        user_id: Optional[str] = None
    ) -> Supplier:
        supplier = (await db.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False).with_for_update()
        )).scalar_one_or_none()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found")

        if sup_in.name is not None:
            supplier.name = sup_in.name
        if sup_in.email is not None:
            supplier.email = sup_in.email
        if sup_in.phone is not None:
            supplier.phone = sup_in.phone
        if sup_in.address is not None:
            supplier.address = sup_in.address
        if sup_in.tax_identifier is not None:
            supplier.tax_identifier = sup_in.tax_identifier
        if sup_in.payment_terms is not None:
            supplier.payment_terms = sup_in.payment_terms
        if sup_in.credit_limit is not None:
            supplier.credit_limit = sup_in.credit_limit
        if sup_in.currency is not None:
            supplier.currency = sup_in.currency
        if sup_in.status is not None:
            supplier.status = sup_in.status
        if sup_in.is_active is not None:
            supplier.is_active = sup_in.is_active

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="UPDATE",
            entity_type="Supplier",
            entity_id=supplier.id,
            user_id=user_id,
            changes={"status": supplier.status}
        )

        await db.commit()
        await db.refresh(supplier)
        return supplier

    @staticmethod
    async def create_or_update_supplier_product(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        sp_in: SupplierProductCreate,
        user_id: Optional[str] = None
    ) -> SupplierProduct:
        # Validate supplier
        sup = (await db.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
        )).scalar_one_or_none()
        if not sup:
            raise HTTPException(status_code=404, detail="Supplier not found")

        # Validate variant
        var = (await db.execute(
            select(ItemVariant).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == sp_in.item_variant_id, Item.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not var:
            raise HTTPException(status_code=404, detail="Item variant not found")

        sp = (await db.execute(
            select(SupplierProduct).where(
                SupplierProduct.tenant_id == tenant_id,
                SupplierProduct.supplier_id == supplier_id,
                SupplierProduct.item_variant_id == sp_in.item_variant_id
            ).with_for_update()
        )).scalar_one_or_none()

        old_price = None
        if sp:
            old_price = sp.unit_cost
            sp.supplier_sku = sp_in.supplier_sku or sp.supplier_sku
            sp.supplier_product_name = sp_in.supplier_product_name or sp.supplier_product_name
            sp.unit_cost = sp_in.unit_cost
            sp.currency = sp_in.currency
            sp.minimum_order_quantity = sp_in.minimum_order_quantity
            sp.pack_size = sp_in.pack_size
            sp.lead_time_days = sp_in.lead_time_days
            sp.is_preferred = sp_in.is_preferred
            sp.is_active = sp_in.is_active
        else:
            sp = SupplierProduct(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                item_variant_id=sp_in.item_variant_id,
                supplier_sku=sp_in.supplier_sku,
                supplier_product_name=sp_in.supplier_product_name,
                unit_cost=sp_in.unit_cost,
                currency=sp_in.currency,
                minimum_order_quantity=sp_in.minimum_order_quantity,
                pack_size=sp_in.pack_size,
                lead_time_days=sp_in.lead_time_days,
                is_preferred=sp_in.is_preferred,
                is_active=sp_in.is_active
            )
            db.add(sp)
            await db.flush()

        # If preferred, demote other suppliers for this variant
        if sp_in.is_preferred:
            other_sps = (await db.execute(
                select(SupplierProduct).where(
                    SupplierProduct.tenant_id == tenant_id,
                    SupplierProduct.item_variant_id == sp_in.item_variant_id,
                    SupplierProduct.id != sp.id
                )
            )).scalars().all()
            for osp in other_sps:
                osp.is_preferred = False

        # Record price history if new or price changed
        if old_price is None or old_price != sp_in.unit_cost:
            ph = SupplierPriceHistory(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                supplier_product_id=sp.id,
                unit_price=sp_in.unit_cost,
                currency=sp_in.currency,
                effective_date=get_utc_now(),
                source_document_type="CONTRACT_UPDATE",
                change_reason=f"Catalog price updated from {old_price} to {sp_in.unit_cost}" if old_price else "Initial Catalog Price",
                recorded_by_user_id=user_id
            )
            db.add(ph)

        await db.commit()
        await db.refresh(sp)
        return sp

    # ============================================================================
    # PURCHASE ORDER LIFECYCLE
    # ============================================================================

    @staticmethod
    async def create_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        po_in: PurchaseOrderCreate,
        user_id: Optional[str] = None
    ) -> PurchaseOrder:
        po_num = await SequenceService.generate_next_number(db, tenant_id, "PURCHASE_ORDER")

        # Validate supplier belongs to tenant
        sup_stmt = select(Supplier).where(Supplier.id == po_in.supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
        sup_res = await db.execute(sup_stmt)
        if not sup_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Supplier not found in tenant")

        # Validate warehouse belongs to tenant
        wh_stmt = select(Warehouse).where(Warehouse.id == po_in.target_warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        wh_res = await db.execute(wh_stmt)
        if not wh_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Warehouse not found in tenant")

        subtotal, disc_total, tax_total, grand_total = PurchaseService._compute_line_totals(po_in.lines)

        po = PurchaseOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            po_number=po_num,
            supplier_id=po_in.supplier_id,
            target_warehouse_id=po_in.target_warehouse_id,
            status="DRAFT",
            subtotal_amount=subtotal,
            discount_amount=disc_total,
            tax_amount=tax_total,
            total_amount=grand_total,
            currency=po_in.currency,
            ordered_at=get_utc_now(),
            expected_delivery_at=po_in.expected_delivery_at,
            notes=po_in.notes,
            created_by_user_id=user_id,
        )
        db.add(po)

        for line in po_in.lines:
            qty = Decimal(str(line.quantity_ordered))
            price = Decimal(str(line.unit_price))
            disc_pct = Decimal(str(line.discount_pct or 0.0))
            tax_pct = Decimal(str(line.tax_pct or 0.0))

            base_amt = qty * price
            disc_amt = base_amt * (disc_pct / Decimal("100.0"))
            after_disc = base_amt - disc_amt
            tax_amt = after_disc * (tax_pct / Decimal("100.0"))
            line_tot = after_disc + tax_amt

            po_line = POLineItem(
                id=str(uuid.uuid4()),
                purchase_order_id=po.id,
                item_variant_id=line.item_variant_id,
                quantity_ordered=qty,
                quantity_received=Decimal("0.0"),
                quantity_cancelled=Decimal("0.0"),
                unit_price=price,
                discount_pct=disc_pct,
                tax_pct=tax_pct,
                line_total=line_tot
            )
            db.add(po_line)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=user_id,
            changes={"po_number": po_num, "total": float(grand_total)}
        )

        await db.commit()
        await db.refresh(po)
        return po

    @staticmethod
    async def update_draft_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        po_id: str,
        po_in: PurchaseOrderUpdate,
        user_id: Optional[str] = None
    ) -> PurchaseOrder:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status != "DRAFT":
            raise HTTPException(status_code=400, detail=f"Only DRAFT purchase orders can be edited (current status: '{po.status}')")

        if po_in.supplier_id:
            sup_stmt = select(Supplier).where(Supplier.id == po_in.supplier_id, Supplier.tenant_id == tenant_id)
            sup_res = await db.execute(sup_stmt)
            if not sup_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Supplier not found")
            po.supplier_id = po_in.supplier_id

        if po_in.target_warehouse_id:
            wh_stmt = select(Warehouse).where(Warehouse.id == po_in.target_warehouse_id, Warehouse.tenant_id == tenant_id)
            wh_res = await db.execute(wh_stmt)
            if not wh_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Warehouse not found")
            po.target_warehouse_id = po_in.target_warehouse_id

        if po_in.expected_delivery_at is not None:
            po.expected_delivery_at = po_in.expected_delivery_at
        if po_in.notes is not None:
            po.notes = po_in.notes

        if po_in.lines is not None:
            del_stmt = select(POLineItem).where(POLineItem.purchase_order_id == po.id)
            del_res = await db.execute(del_stmt)
            for old_line in del_res.scalars().all():
                await db.delete(old_line)

            subtotal, disc_total, tax_total, grand_total = PurchaseService._compute_line_totals(po_in.lines)
            po.subtotal_amount = subtotal
            po.discount_amount = disc_total
            po.tax_amount = tax_total
            po.total_amount = grand_total

            for line in po_in.lines:
                qty = Decimal(str(line.quantity_ordered))
                price = Decimal(str(line.unit_price))
                disc_pct = Decimal(str(line.discount_pct or 0.0))
                tax_pct = Decimal(str(line.tax_pct or 0.0))

                base_amt = qty * price
                disc_amt = base_amt * (disc_pct / Decimal("100.0"))
                after_disc = base_amt - disc_amt
                tax_amt = after_disc * (tax_pct / Decimal("100.0"))
                line_tot = after_disc + tax_amt

                po_line = POLineItem(
                    id=str(uuid.uuid4()),
                    purchase_order_id=po.id,
                    item_variant_id=line.item_variant_id,
                    quantity_ordered=qty,
                    quantity_received=Decimal("0.0"),
                    quantity_cancelled=Decimal("0.0"),
                    unit_price=price,
                    discount_pct=disc_pct,
                    tax_pct=tax_pct,
                    line_total=line_tot
                )
                db.add(po_line)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="UPDATE",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=user_id,
            changes={"status": po.status, "total": float(po.total_amount)}
        )

        await db.commit()
        await db.refresh(po)
        return po

    @staticmethod
    async def submit_for_approval(
        db: AsyncSession,
        tenant_id: str,
        po_id: str,
        user_id: Optional[str] = None
    ) -> PurchaseOrder:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status != "DRAFT":
            raise HTTPException(status_code=400, detail=f"Only DRAFT purchase orders can be submitted for approval (current status: '{po.status}')")

        po.status = "PENDING_APPROVAL"
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SUBMIT_APPROVAL",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=user_id,
            changes={"status": "PENDING_APPROVAL"}
        )
        await db.commit()
        await db.refresh(po)
        return po

    @staticmethod
    async def approve_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        po_id: str,
        user_id: Optional[str] = None,
        max_self_approval_limit: Decimal = Decimal("5000.00")
    ) -> PurchaseOrder:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status not in ["DRAFT", "PENDING_APPROVAL"]:
            raise HTTPException(status_code=400, detail=f"Cannot approve PO in '{po.status}' status")

        # Self-approval threshold guard
        if user_id and po.created_by_user_id == user_id and po.total_amount > max_self_approval_limit:
            raise HTTPException(
                status_code=403,
                detail=f"Self-approval exceeded: PO total ${float(po.total_amount)} exceeds limit ${float(max_self_approval_limit)}. Independent manager approval required."
            )

        po.status = "APPROVED"
        po.approved_by_user_id = user_id
        po.approved_at = get_utc_now()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="APPROVE",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=user_id,
            changes={"status": "APPROVED", "approved_by": user_id}
        )
        await db.commit()
        await db.refresh(po)
        return po

    @staticmethod
    async def cancel_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        po_id: str,
        cancellation_reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> PurchaseOrder:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status not in ["DRAFT", "PENDING_APPROVAL", "APPROVED"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel PO in '{po.status}' status")

        # Guard against cancelling if any line has already been received
        lines_stmt = select(POLineItem).where(POLineItem.purchase_order_id == po.id)
        lines_res = await db.execute(lines_stmt)
        all_lines = lines_res.scalars().all()
        if any(l.quantity_received > 0 for l in all_lines):
            raise HTTPException(status_code=400, detail="Cannot cancel purchase order with partial receipts already posted")
        for line in lines_res.scalars().all():
            rem = line.quantity_ordered - line.quantity_received
            if rem > 0:
                line.quantity_cancelled += rem

        po.status = "CANCELLED"
        po.cancellation_reason = cancellation_reason

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CANCEL",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=user_id,
            changes={"status": "CANCELLED", "reason": cancellation_reason}
        )
        await db.commit()
        await db.refresh(po)
        return po

    # ============================================================================
    # GOODS RECEIPT (GRN)
    # ============================================================================

    @staticmethod
    async def receive_goods(
        db: AsyncSession,
        tenant_id: str,
        gr_in: GoodsReceiptCreate,
        user_id: Optional[str] = None,
        client_type: str = "WEB"
    ) -> GoodsReceipt:
        """
        Atomic Goods Receipt Workflow:
        1. Lock PO row with SELECT FOR UPDATE
        2. Validate PO status is APPROVED or PARTIALLY_RECEIVED
        3. Validate receiving warehouse and destination bins
        4. Validate per-line remaining quantities BEFORE mutating database state
        5. Create GoodsReceipt and GoodsReceiptLines
        6. Post inbound transaction into immutable stock ledger via StockEngine
        7. Update PO lines received quantities and PO status (PARTIALLY_RECEIVED or COMPLETED)
        8. Audit log entry
        9. Commit atomic transaction
        """
        # 1. Lock PO row
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == gr_in.purchase_order_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

        if po.status not in ["APPROVED", "PARTIALLY_RECEIVED"]:
            raise HTTPException(status_code=400, detail=f"Cannot receive goods against PO in '{po.status}' status (must be APPROVED or PARTIALLY_RECEIVED)")

        # Verify warehouse
        wh_stmt = select(Warehouse).where(Warehouse.id == gr_in.warehouse_id, Warehouse.tenant_id == tenant_id)
        wh_res = await db.execute(wh_stmt)
        if not wh_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Receiving warehouse not found in tenant")

        # 2. Pre-validate all line items and over-receipt rules BEFORE creating any records
        validated_lines_data = []
        for line_in in gr_in.lines:
            line_stmt = select(POLineItem).where(POLineItem.id == line_in.po_line_id, POLineItem.purchase_order_id == po.id).with_for_update()
            line_res = await db.execute(line_stmt)
            po_line = line_res.scalar_one_or_none()
            if not po_line:
                raise HTTPException(status_code=404, detail=f"PO line {line_in.po_line_id} not found on this PO")

            rem_qty = po_line.quantity_ordered - po_line.quantity_received - po_line.quantity_cancelled
            if line_in.quantity_received > rem_qty:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Cannot receive {line_in.quantity_received} units for line {po_line.id}; remaining order quantity is {rem_qty}"
                )

            # Validate destination bin belongs to receiving warehouse
            bin_stmt = select(LocationBin).where(LocationBin.id == line_in.destination_bin_id, LocationBin.warehouse_id == gr_in.warehouse_id)
            bin_res = await db.execute(bin_stmt)
            if not bin_res.scalar_one_or_none():
                raise HTTPException(status_code=404, detail=f"Destination bin {line_in.destination_bin_id} not found in receiving warehouse")

            # Lookup variant and parent item base UOM
            var_stmt = select(ItemVariant, Item).join(Item, ItemVariant.item_id == Item.id).where(ItemVariant.id == line_in.item_variant_id)
            var_res = await db.execute(var_stmt)
            var_row = var_res.first()
            if not var_row:
                raise HTTPException(status_code=404, detail=f"Item variant {line_in.item_variant_id} not found")
            variant, item = var_row

            validated_lines_data.append({
                "po_line": po_line,
                "line_in": line_in,
                "unit_cost": po_line.unit_price,
                "base_uom": item.base_uom or "PCS"
            })

        # 3. Validation passed - create GoodsReceipt
        grn_num = await SequenceService.generate_next_number(db, tenant_id, "GOODS_RECEIPT")
        goods_receipt = GoodsReceipt(
            id=str(uuid.uuid4()),
            purchase_order_id=po.id,
            grn_number=grn_num,
            warehouse_id=gr_in.warehouse_id,
            received_at=get_utc_now(),
            received_by_user_id=user_id,
            notes=gr_in.notes
        )
        db.add(goods_receipt)
        await db.flush()

        ledger_entries_data = []

        for item_data in validated_lines_data:
            po_line = item_data["po_line"]
            line_in = item_data["line_in"]

            po_line.quantity_received = Decimal(str(po_line.quantity_received)) + line_in.quantity_received

            gr_line = GoodsReceiptLine(
                id=str(uuid.uuid4()),
                goods_receipt_id=goods_receipt.id,
                po_line_id=po_line.id,
                item_variant_id=line_in.item_variant_id,
                quantity_received=line_in.quantity_received,
                destination_bin_id=line_in.destination_bin_id,
                batch_number=line_in.batch_number,
                expiry_date=line_in.expiry_date
            )
            db.add(gr_line)

            ledger_entries_data.append({
                "item_variant_id": line_in.item_variant_id,
                "quantity": line_in.quantity_received,
                "unit_cost": item_data["unit_cost"],
                "destination_location_bin_id": line_in.destination_bin_id,
                "batch_number": line_in.batch_number,
                "uom": item_data["base_uom"]
            })

        # Check total fulfillment status
        all_lines_stmt = select(POLineItem).where(POLineItem.purchase_order_id == po.id)
        all_lines_res = await db.execute(all_lines_stmt)
        all_lines = all_lines_res.scalars().all()

        all_completed = all((l.quantity_received + l.quantity_cancelled) >= l.quantity_ordered for l in all_lines)
        po.status = "COMPLETED" if all_completed else "PARTIALLY_RECEIVED"

        # 4. Post inbound transaction into immutable stock ledger via StockEngine
        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="PURCHASE_RECEIPT",
            entries_data=ledger_entries_data,
            reference_doc_type="PURCHASE_ORDER",
            reference_doc_id=po.id,
            user_id=user_id,
            notes=f"Goods Receipt {grn_num} against {po.po_number}",
            client_type=client_type
        )

        # 5. Record Inbound Acquisition Cost Layers in Costing Subsystem
        for item_data in validated_lines_data:
            line_in = item_data["line_in"]
            await CostingService.record_inbound_receipt(
                db=db,
                tenant_id=tenant_id,
                warehouse_id=gr_in.warehouse_id,
                item_variant_id=line_in.item_variant_id,
                quantity=Decimal(str(line_in.quantity_received)),
                unit_cost=Decimal(str(item_data["unit_cost"])),
                stock_transaction_id=tx.id,
                notes=f"PO {po.po_number} / GRN {grn_num}",
                user_id=user_id
            )

        # 6. Audit log entry
        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="GOODS_RECEIPT",
            entity_type="GoodsReceipt",
            entity_id=goods_receipt.id,
            user_id=user_id,
            changes={"grn_number": grn_num, "po_status": po.status}
        )

        # 7. Single atomic commit for entire GRN workflow
        await db.commit()
        await db.refresh(goods_receipt)
        return goods_receipt

    # ============================================================================
    # SUPPLIER RETURNS (RTV)
    # ============================================================================

    @staticmethod
    async def process_supplier_return(
        db: AsyncSession,
        tenant_id: str,
        ret_in: SupplierReturnCreate,
        user_id: Optional[str] = None
    ) -> SupplierReturn:
        """
        Executes a Return to Vendor (RTV):
        1. Validates supplier and warehouse.
        2. Deducts physical stock from source bins with row locking.
        3. Generates StockLedgerTransaction (SUPPLIER_RETURN).
        4. Depletes Cost Layers via CostingService.
        5. Issues SupplierDebitMemo.
        6. Audit logs the return.
        """
        sup = (await db.execute(
            select(Supplier).where(Supplier.id == ret_in.supplier_id, Supplier.tenant_id == tenant_id, Supplier.is_deleted == False)
        )).scalar_one_or_none()
        if not sup:
            raise HTTPException(status_code=404, detail="Supplier not found")

        wh = (await db.execute(
            select(Warehouse).where(Warehouse.id == ret_in.warehouse_id, Warehouse.tenant_id == tenant_id, Warehouse.is_deleted == False)
        )).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Warehouse not found")

        ret_num = await SequenceService.generate_next_number(db, tenant_id, "SUPPLIER_RETURN", custom_prefix="RTV")
        
        tot_refund = Decimal("0.0")
        supplier_return = SupplierReturn(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            return_number=ret_num,
            supplier_id=ret_in.supplier_id,
            purchase_order_id=ret_in.purchase_order_id,
            warehouse_id=ret_in.warehouse_id,
            status="COMPLETED",
            return_reason=ret_in.return_reason,
            total_refund_amount=Decimal("0.0"),
            returned_at=get_utc_now(),
            returned_by_user_id=user_id,
            notes=ret_in.notes
        )
        db.add(supplier_return)
        await db.flush()

        ledger_entries_data = []

        for line_in in ret_in.lines:
            qty = Decimal(str(line_in.quantity_returned))
            unit_cost = Decimal(str(line_in.unit_cost))
            line_tot = qty * unit_cost
            tot_refund += line_tot

            # Lock stock balance
            bal_stmt = (
                select(StockBalanceCache)
                .where(
                    StockBalanceCache.warehouse_id == ret_in.warehouse_id,
                    StockBalanceCache.location_bin_id == line_in.source_location_bin_id,
                    StockBalanceCache.item_variant_id == line_in.item_variant_id
                )
                .with_for_update()
            )
            bal = (await db.execute(bal_stmt)).scalar_one_or_none()
            avail = (bal.quantity_on_hand - bal.quantity_allocated) if bal else Decimal("0.0")
            if not bal or avail < qty:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Insufficient unallocated stock in bin to process return of {qty} units (Available: {avail})"
                )

            ret_line = SupplierReturnLine(
                id=str(uuid.uuid4()),
                supplier_return_id=supplier_return.id,
                item_variant_id=line_in.item_variant_id,
                source_location_bin_id=line_in.source_location_bin_id,
                quantity_returned=qty,
                unit_cost=unit_cost,
                total_cost=line_tot,
                batch_number=line_in.batch_number
            )
            db.add(ret_line)

            ledger_entries_data.append({
                "item_variant_id": line_in.item_variant_id,
                "quantity": qty,
                "unit_cost": unit_cost,
                "source_location_bin_id": line_in.source_location_bin_id,
                "batch_number": line_in.batch_number,
                "uom": "PCS"
            })

        supplier_return.total_refund_amount = tot_refund

        # 1. Post Stock Ledger Transaction
        tx = await StockEngine.post_transaction(
            db=db,
            tenant_id=tenant_id,
            transaction_type="SUPPLIER_RETURN",
            entries_data=ledger_entries_data,
            reference_doc_type="SUPPLIER_RETURN",
            reference_doc_id=supplier_return.id,
            user_id=user_id,
            notes=f"Supplier Return {ret_num}"
        )

        # 2. Deplete Cost Layers via negative adjustment
        for line_in in ret_in.lines:
            qty = Decimal(str(line_in.quantity_returned))
            unit_cost = Decimal(str(line_in.unit_cost))
            await CostingService.record_inventory_adjustment(
                db=db,
                tenant_id=tenant_id,
                warehouse_id=ret_in.warehouse_id,
                item_variant_id=line_in.item_variant_id,
                quantity_diff=-qty,
                unit_cost=unit_cost,
                stock_transaction_id=tx.id,
                reason=f"Supplier Return {ret_num} to {sup.name}",
                user_id=user_id
            )

        # 3. Issue Debit Memo
        memo_num = await SequenceService.generate_next_number(db, tenant_id, "DEBIT_MEMO", custom_prefix="DBM")
        debit_memo = SupplierDebitMemo(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            memo_number=memo_num,
            supplier_id=ret_in.supplier_id,
            supplier_return_id=supplier_return.id,
            amount=tot_refund,
            currency=sup.currency,
            status="OPEN",
            issued_at=get_utc_now(),
            notes=f"Debit Memo for Supplier Return {ret_num}"
        )
        db.add(debit_memo)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SUPPLIER_RETURN",
            entity_type="SupplierReturn",
            entity_id=supplier_return.id,
            user_id=user_id,
            changes={"return_number": ret_num, "total_refund": float(tot_refund)}
        )

        await db.commit()
        await db.refresh(supplier_return)
        return supplier_return
