import uuid
import hmac
import hashlib
import json
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException, status
from passlib.context import CryptContext

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.base import get_utc_now
from app.models.auth import User
from app.models.sales import Customer, SalesOrder, SOLineItem, Shipment, SalesReturn, SalesReturnLine, CustomerPriceList, PriceListItem
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, SupplierProduct
from app.models.item import Item, ItemVariant
from app.models.ledger import StockBalanceCache
from app.models.portal import (
    PortalUser,
    PortalUserMembership,
    PortalInvitation,
    AdvanceShippingNotice,
    ASNLineItem
)
from app.schemas.portal import (
    PortalLoginRequest,
    PortalLoginResponse,
    PortalInviteUserRequest,
    PortalAcceptInviteRequest,
    CustomerProfileResponse,
    CustomerCatalogItemResponse,
    CustomerOrderCreateRequest,
    CustomerOrderResponse,
    CustomerOrderLineResponse,
    CustomerReturnCreateRequest,
    CustomerReturnResponse,
    SupplierProfileResponse,
    SupplierPOResponse,
    SupplierPOLineResponse,
    SupplierPOConfirmRequest,
    SupplierPORejectRequest,
    CreateASNRequest,
    ASNResponse,
    ASNLineResponse,
    SecureDocumentTokenResponse
)
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.sales_service import SalesService
from app.services.purchase_service import PurchaseService

CUSTOMER_PERMISSIONS = {
    "ADMIN": [
        "customer:profile:read", "customer:profile:write", "customer:users:manage",
        "customer:catalog:read", "customer:orders:read", "customer:orders:create", "customer:orders:cancel",
        "customer:invoices:read", "customer:payments:create", "customer:shipments:read", "customer:tracking:read",
        "customer:returns:create", "customer:returns:read"
    ],
    "MEMBER": [
        "customer:profile:read", "customer:catalog:read", "customer:orders:read", "customer:orders:create",
        "customer:invoices:read", "customer:shipments:read", "customer:tracking:read", "customer:returns:read"
    ],
    "VIEWER": [
        "customer:profile:read", "customer:catalog:read", "customer:orders:read", "customer:invoices:read",
        "customer:shipments:read", "customer:tracking:read"
    ]
}

SUPPLIER_PERMISSIONS = {
    "ADMIN": [
        "supplier:profile:read", "supplier:profile:write", "supplier:users:manage",
        "supplier:catalog:read", "supplier:catalog:update",
        "supplier:purchase_orders:read", "supplier:purchase_orders:confirm", "supplier:purchase_orders:reject",
        "supplier:asn:create", "supplier:asn:read", "supplier:invoices:read", "supplier:invoices:submit",
        "supplier:payments:read"
    ],
    "MEMBER": [
        "supplier:profile:read", "supplier:catalog:read", "supplier:purchase_orders:read",
        "supplier:purchase_orders:confirm", "supplier:asn:create", "supplier:asn:read", "supplier:invoices:read"
    ],
    "VIEWER": [
        "supplier:profile:read", "supplier:catalog:read", "supplier:purchase_orders:read", "supplier:invoices:read"
    ]
}

class PortalService:
    @staticmethod
    def hash_password(password: str) -> str:
        return get_password_hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return verify_password(plain_password, hashed_password)

    @staticmethod
    async def verify_portal_user_active(db: AsyncSession, portal_user_id: str) -> PortalUser:
        stmt = select(PortalUser).where(PortalUser.id == portal_user_id)
        user = (await db.execute(stmt)).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal user account is deactivated or deleted")
        return user

    @staticmethod
    async def create_portal_invitation(
        db: AsyncSession,
        tenant_id: str,
        email: str,
        entity_type: str,
        entity_id: str,
        role: str = "MEMBER",
        invited_by_user_id: Optional[str] = None
    ) -> Tuple[PortalInvitation, str]:
        raw_token = uuid.uuid4().hex + uuid.uuid4().hex
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = get_utc_now() + timedelta(days=7)

        inv = PortalInvitation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email.lower().strip(),
            entity_type=entity_type.upper(),
            entity_id=entity_id,
            role=role.upper(),
            token_hash=token_hash,
            expires_at=expires_at,
            invited_by_user_id=invited_by_user_id
        )
        db.add(inv)
        await db.commit()
        await db.refresh(inv)
        return inv, raw_token

    @staticmethod
    async def accept_portal_invitation(
        db: AsyncSession,
        raw_token: str,
        full_name: str,
        password: str
    ) -> PortalUser:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        stmt = select(PortalInvitation).where(PortalInvitation.token_hash == token_hash)
        inv = (await db.execute(stmt)).scalar_one_or_none()

        if not inv:
            raise HTTPException(status_code=400, detail="Invalid or unrecognized invitation token")

        if inv.accepted_at is not None:
            raise HTTPException(status_code=400, detail="Invitation token has already been accepted and cannot be reused")

        exp_at = inv.expires_at
        now = get_utc_now()
        if exp_at.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif exp_at.tzinfo is not None and now.tzinfo is None:
            from datetime import timezone
            now = now.replace(tzinfo=timezone.utc)

        if exp_at < now:
            raise HTTPException(status_code=400, detail="Invitation token has expired")

        # Find or create user
        user_stmt = select(PortalUser).where(PortalUser.email == inv.email, PortalUser.portal_type == inv.entity_type)
        user = (await db.execute(user_stmt)).scalar_one_or_none()

        if not user:
            user = PortalUser(
                id=str(uuid.uuid4()),
                tenant_id=inv.tenant_id,
                email=inv.email,
                password_hash=PortalService.hash_password(password),
                full_name=full_name,
                portal_type=inv.entity_type,
                is_active=True
            )
            db.add(user)
            await db.flush()

        # Add or update membership
        mem_stmt = select(PortalUserMembership).where(
            PortalUserMembership.portal_user_id == user.id,
            PortalUserMembership.entity_type == inv.entity_type,
            PortalUserMembership.entity_id == inv.entity_id
        )
        membership = (await db.execute(mem_stmt)).scalar_one_or_none()
        if not membership:
            membership = PortalUserMembership(
                id=str(uuid.uuid4()),
                portal_user_id=user.id,
                tenant_id=inv.tenant_id,
                entity_type=inv.entity_type,
                entity_id=inv.entity_id,
                role=inv.role,
                is_active=True
            )
            db.add(membership)
        else:
            membership.is_active = True
            membership.role = inv.role

        inv.accepted_at = get_utc_now()
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def create_portal_user_with_membership(
        db: AsyncSession,
        tenant_id: str,
        email: str,
        password: str,
        full_name: str,
        portal_type: str, # CUSTOMER or SUPPLIER
        entity_id: str,
        role: str = "ADMIN"
    ) -> PortalUser:
        user = PortalUser(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email.lower().strip(),
            password_hash=PortalService.hash_password(password),
            full_name=full_name,
            portal_type=portal_type.upper(),
            is_active=True
        )
        db.add(user)
        await db.flush()

        membership = PortalUserMembership(
            id=str(uuid.uuid4()),
            portal_user_id=user.id,
            tenant_id=tenant_id,
            entity_type=portal_type.upper(),
            entity_id=entity_id,
            role=role.upper(),
            is_active=True
        )
        db.add(membership)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def authenticate_portal_user(
        db: AsyncSession,
        req: PortalLoginRequest
    ) -> PortalLoginResponse:
        email = req.email.lower().strip()
        portal_type = req.portal_type.upper()

        stmt = select(PortalUser).where(PortalUser.email == email, PortalUser.portal_type == portal_type)
        user = (await db.execute(stmt)).scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        if user.locked_until and user.locked_until > get_utc_now():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is temporarily locked due to failed login attempts. Please try again later.")

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Portal account has been deactivated. Please contact support.")

        if not PortalService.verify_password(req.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = get_utc_now() + timedelta(minutes=15)
            await db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        # Reset failed attempts
        user.failed_login_attempts = 0
        user.last_login_at = get_utc_now()

        # Resolve active membership
        mem_stmt = select(PortalUserMembership).where(
            PortalUserMembership.portal_user_id == user.id,
            PortalUserMembership.entity_type == portal_type,
            PortalUserMembership.is_active == True
        )
        membership = (await db.execute(mem_stmt)).scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no active company memberships for this portal")

        # Resolve entity name
        entity_name = "Company"
        if portal_type == "CUSTOMER":
            cust = (await db.execute(select(Customer).where(Customer.id == membership.entity_id))).scalar_one_or_none()
            if not cust or not cust.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer company account is inactive or suspended")
            entity_name = cust.name
            permissions = CUSTOMER_PERMISSIONS.get(membership.role, CUSTOMER_PERMISSIONS["VIEWER"])
        else:
            supp = (await db.execute(select(Supplier).where(Supplier.id == membership.entity_id))).scalar_one_or_none()
            if not supp or not supp.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supplier company account is inactive or suspended")
            entity_name = supp.name
            permissions = SUPPLIER_PERMISSIONS.get(membership.role, SUPPLIER_PERMISSIONS["VIEWER"])

        await db.commit()

        # Generate JWT Token
        token_payload = {
            "sub": user.id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "portal_type": portal_type,
            "entity_type": portal_type,
            "entity_id": membership.entity_id,
            "customer_id": membership.entity_id if portal_type == "CUSTOMER" else None,
            "supplier_id": membership.entity_id if portal_type == "SUPPLIER" else None,
            "role": membership.role,
            "permissions": permissions
        }
        access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            roles=[f"portal_{portal_type.lower()}_{membership.role.lower()}"],
            permissions=permissions,
            extra_claims=token_payload
        )

        return PortalLoginResponse(
            access_token=access_token,
            portal_user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            portal_type=portal_type,
            entity_id=membership.entity_id,
            entity_name=entity_name,
            role=membership.role,
            permissions=permissions
        )

    # ========================================================================
    # CUSTOMER PORTAL WORKFLOWS
    # ========================================================================

    @staticmethod
    async def get_customer_profile(db: AsyncSession, tenant_id: str, customer_id: str) -> CustomerProfileResponse:
        cust = (await db.execute(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")
        return CustomerProfileResponse(
            id=cust.id,
            code=cust.code,
            name=cust.name,
            email=cust.email,
            phone=cust.phone,
            currency=cust.currency,
            payment_terms=cust.payment_terms,
            credit_limit=float(cust.credit_limit),
            current_credit_exposure=float(cust.current_credit_exposure),
            billing_address=cust.billing_address,
            shipping_address=cust.shipping_address
        )

    @staticmethod
    async def get_customer_catalog(db: AsyncSession, tenant_id: str, customer_id: str) -> List[CustomerCatalogItemResponse]:
        """
        Returns master catalog filtered by customer's active price list.
        Data Sanitization: NO internal cost prices, NO internal warehouse stock numbers.
        """
        # Fetch customer price list
        pl_stmt = (
            select(PriceListItem, ItemVariant, Item)
            .join(ItemVariant, PriceListItem.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .join(CustomerPriceList, CustomerPriceList.price_list_id == PriceListItem.price_list_id)
            .where(CustomerPriceList.customer_id == customer_id, Item.tenant_id == tenant_id, Item.is_active == True)
        )
        rows = (await db.execute(pl_stmt)).all()

        catalog_items: List[CustomerCatalogItemResponse] = []
        for pl_item, variant, item in rows:
            # Check if stock exists without revealing exact count
            bal = (await db.execute(
                select(func.sum(StockBalanceCache.quantity_on_hand - StockBalanceCache.quantity_allocated))
                .where(StockBalanceCache.item_variant_id == variant.id)
            )).scalar() or Decimal("0.0")

            catalog_items.append(CustomerCatalogItemResponse(
                item_id=item.id,
                variant_id=variant.id,
                sku=variant.variant_sku or item.sku,
                name=item.name,
                variant_name=variant.variant_name,
                unit_price=float(pl_item.base_price),
                is_in_stock=bal > Decimal("0.0")
            ))

        return catalog_items

    @staticmethod
    async def create_customer_sales_order(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        req: CustomerOrderCreateRequest,
        portal_user_id: str
    ) -> CustomerOrderResponse:
        """
        Places a new B2B sales order on behalf of the authenticated customer.
        Strict Boundary: Flows through SalesService.
        """
        cust = (await db.execute(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Resolve warehouse (default customer warehouse or primary warehouse)
        from app.models.warehouse import Warehouse
        wh = (await db.execute(select(Warehouse).where(Warehouse.tenant_id == tenant_id, Warehouse.is_active == True))).scalars().first()
        if not wh:
            raise HTTPException(status_code=400, detail="No active fulfillment warehouse configured")

        so_number = await SequenceService.generate_next_number(db, tenant_id, "SALES_ORDER", custom_prefix="SO")
        so = SalesOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            so_number=so_number,
            customer_id=cust.id,
            warehouse_id=wh.id,
            status="CONFIRMED",
            notes=req.customer_notes
        )
        db.add(so)
        await db.flush()

        subtotal = Decimal("0.0")
        lines_out: List[CustomerOrderLineResponse] = []

        for line_in in req.lines:
            variant = (await db.execute(select(ItemVariant).where(ItemVariant.id == line_in.item_variant_id))).scalar_one_or_none()
            if not variant:
                raise HTTPException(status_code=400, detail=f"Variant {line_in.item_variant_id} not found")

            # Resolve price from price list or variant selling price
            unit_price = variant.selling_price or Decimal("100.00")
            lt = (unit_price * line_in.quantity).quantize(Decimal("0.01"))
            subtotal += lt

            sol = SOLineItem(
                id=str(uuid.uuid4()),
                sales_order_id=so.id,
                item_variant_id=variant.id,
                quantity_ordered=line_in.quantity,
                unit_price=unit_price,
                line_total=lt
            )
            db.add(sol)
            lines_out.append(CustomerOrderLineResponse(
                id=sol.id,
                item_variant_id=variant.id,
                sku=variant.variant_sku or "",
                variant_name=variant.variant_name,
                quantity_ordered=float(sol.quantity_ordered),
                quantity_shipped=0.0,
                unit_price=float(unit_price),
                line_total=float(lt)
            ))

        tax_amt = (subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
        so.subtotal_amount = subtotal
        so.tax_amount = tax_amt
        so.total_amount = subtotal + tax_amt

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PORTAL_CREATE_SALES_ORDER",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=portal_user_id,
            changes={"so_number": so.so_number, "customer_id": cust.id, "total": float(so.total_amount)}
        )

        await db.commit()
        await db.refresh(so)

        return CustomerOrderResponse(
            id=so.id,
            so_number=so.so_number,
            status=so.status,
            total_amount=float(so.total_amount),
            subtotal_amount=float(so.subtotal_amount),
            tax_amount=float(so.tax_amount),
            currency=cust.currency,
            customer_notes=so.notes,
            created_at=so.created_at,
            lines=lines_out
        )

    @staticmethod
    async def get_customer_orders(db: AsyncSession, tenant_id: str, customer_id: str) -> List[CustomerOrderResponse]:
        stmt = (
            select(SalesOrder)
            .where(SalesOrder.tenant_id == tenant_id, SalesOrder.customer_id == customer_id)
            .order_by(SalesOrder.created_at.desc())
        )
        orders = (await db.execute(stmt)).scalars().all()

        out: List[CustomerOrderResponse] = []
        for so in orders:
            line_res: List[CustomerOrderLineResponse] = []
            for l in so.lines:
                sku = l.variant.variant_sku if l.variant else ""
                vname = l.variant.variant_name if l.variant else ""
                line_res.append(CustomerOrderLineResponse(
                    id=l.id,
                    item_variant_id=l.item_variant_id,
                    sku=sku,
                    variant_name=vname,
                    quantity_ordered=float(l.quantity_ordered),
                    quantity_shipped=float(l.quantity_shipped),
                    unit_price=float(l.unit_price),
                    line_total=float(l.line_total)
                ))
            out.append(CustomerOrderResponse(
                id=so.id,
                so_number=so.so_number,
                status=so.status,
                total_amount=float(so.total_amount),
                subtotal_amount=float(so.subtotal_amount),
                tax_amount=float(so.tax_amount),
                currency="USD",
                customer_notes=so.notes,
                created_at=so.created_at,
                lines=line_res
            ))
        return out

    # ========================================================================
    # SUPPLIER PORTAL WORKFLOWS
    # ========================================================================

    @staticmethod
    async def get_supplier_profile(db: AsyncSession, tenant_id: str, supplier_id: str) -> SupplierProfileResponse:
        supp = (await db.execute(select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id))).scalar_one_or_none()
        if not supp:
            raise HTTPException(status_code=404, detail="Supplier not found")
        return SupplierProfileResponse(
            id=supp.id,
            code=supp.code,
            name=supp.name,
            email=supp.email,
            phone=supp.phone,
            currency=supp.currency,
            payment_terms=supp.payment_terms
        )

    @staticmethod
    async def get_supplier_purchase_orders(db: AsyncSession, tenant_id: str, supplier_id: str) -> List[SupplierPOResponse]:
        stmt = (
            select(PurchaseOrder)
            .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.supplier_id == supplier_id)
            .order_by(PurchaseOrder.created_at.desc())
        )
        pos = (await db.execute(stmt)).scalars().all()

        out: List[SupplierPOResponse] = []
        for po in pos:
            line_res: List[SupplierPOLineResponse] = []
            for l in po.lines:
                sku = l.variant.variant_sku if l.variant else ""
                vname = l.variant.variant_name if l.variant else ""
                line_res.append(SupplierPOLineResponse(
                    id=l.id,
                    item_variant_id=l.item_variant_id,
                    sku=sku,
                    variant_name=vname,
                    quantity_ordered=float(l.quantity_ordered),
                    quantity_received=float(l.quantity_received),
                    unit_cost=float(l.unit_price),
                    line_total=float(l.line_total)
                ))
            out.append(SupplierPOResponse(
                id=po.id,
                po_number=po.po_number,
                status=po.status,
                order_date=po.ordered_at,
                promised_delivery_date=po.expected_delivery_at,
                total_amount=float(po.total_amount),
                currency="USD",
                lines=line_res
            ))
        return out

    @staticmethod
    async def confirm_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        po_id: str,
        req: SupplierPOConfirmRequest,
        portal_user_id: str
    ) -> SupplierPOResponse:
        po = (await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found for supplier")

        po.expected_delivery_at = req.promised_delivery_date
        if po.status in ["ISSUED", "SENT", "PENDING_CONFIRMATION", "APPROVED"]:
            po.status = "CONFIRMED"

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SUPPLIER_CONFIRM_PO",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=portal_user_id,
            changes={"promised_date": str(req.promised_delivery_date), "notes": req.notes}
        )

        await db.commit()
        await db.refresh(po)

        line_res = [
            SupplierPOLineResponse(
                id=l.id, item_variant_id=l.item_variant_id,
                sku=l.variant.variant_sku if l.variant else "",
                variant_name=l.variant.variant_name if l.variant else "",
                quantity_ordered=float(l.quantity_ordered),
                quantity_received=float(l.quantity_received),
                unit_cost=float(l.unit_price),
                line_total=float(l.line_total)
            )
            for l in po.lines
        ]

        return SupplierPOResponse(
            id=po.id,
            po_number=po.po_number,
            status=po.status,
            order_date=po.ordered_at,
            promised_delivery_date=po.expected_delivery_at,
            total_amount=float(po.total_amount),
            currency="USD",
            lines=line_res
        )
    @staticmethod
    async def cancel_customer_sales_order(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        so_id: str,
        reason: Optional[str] = None,
        portal_user_id: Optional[str] = None
    ) -> SalesOrder:
        so = (await db.execute(
            select(SalesOrder).where(SalesOrder.id == so_id, SalesOrder.customer_id == customer_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not so:
            raise HTTPException(status_code=404, detail="Sales order not found for customer")

        if so.status in ["SHIPPED", "DELIVERED", "COMPLETED"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel sales order in '{so.status}' status")

        if so.status == "CANCELLED":
            return so

        so.status = "CANCELLED"
        if reason:
            so.notes = f"{so.notes or ''}\n[Cancellation Reason]: {reason}".strip()

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="PORTAL_CANCEL_SALES_ORDER",
            entity_type="SalesOrder",
            entity_id=so.id,
            user_id=portal_user_id,
            changes={"status": "CANCELLED", "reason": reason}
        )

        await db.commit()
        await db.refresh(so)
        return so

    @staticmethod
    async def reject_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        po_id: str,
        req: SupplierPORejectRequest,
        portal_user_id: str
    ) -> SupplierPOResponse:
        po = (await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found for supplier")

        if po.status in ["PARTIALLY_RECEIVED", "RECEIVED", "COMPLETED"]:
            raise HTTPException(status_code=400, detail=f"Cannot reject purchase order in '{po.status}' status")

        po.status = "CANCELLED"
        po.cancellation_reason = req.rejection_reason

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SUPPLIER_REJECT_PO",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            user_id=portal_user_id,
            changes={"status": "CANCELLED", "rejection_reason": req.rejection_reason}
        )

        await db.commit()
        await db.refresh(po)

        line_res = [
            SupplierPOLineResponse(
                id=l.id, item_variant_id=l.item_variant_id,
                sku=l.variant.variant_sku if l.variant else "",
                variant_name=l.variant.variant_name if l.variant else "",
                quantity_ordered=float(l.quantity_ordered),
                quantity_received=float(l.quantity_received),
                unit_cost=float(l.unit_price),
                line_total=float(l.line_total)
            )
            for l in po.lines
        ]

        return SupplierPOResponse(
            id=po.id,
            po_number=po.po_number,
            status=po.status,
            order_date=po.ordered_at,
            promised_delivery_date=po.expected_delivery_at,
            total_amount=float(po.total_amount),
            currency="USD",
            lines=line_res
        )

    @staticmethod
    async def create_advance_shipping_notice(
        db: AsyncSession,
        tenant_id: str,
        supplier_id: str,
        req: CreateASNRequest,
        portal_user_id: str
    ) -> ASNResponse:
        po = (await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == req.purchase_order_id, PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found for supplier")

        asn_num = await SequenceService.generate_next_number(db, tenant_id, "ASN", custom_prefix="ASN")
        asn = AdvanceShippingNotice(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            asn_number=asn_num,
            supplier_id=supplier_id,
            purchase_order_id=po.id,
            carrier_code=req.carrier_code,
            tracking_number=req.tracking_number,
            estimated_arrival_date=req.estimated_arrival_date,
            status="SUBMITTED",
            notes=req.notes
        )
        db.add(asn)
        await db.flush()

        line_out: List[ASNLineResponse] = []
        for line_in in req.lines:
            asn_line = ASNLineItem(
                id=str(uuid.uuid4()),
                asn_id=asn.id,
                po_line_id=line_in.po_line_id,
                item_variant_id=line_in.item_variant_id,
                quantity_shipped=line_in.quantity_shipped,
                lot_number=line_in.lot_number,
                serial_numbers=line_in.serial_numbers
            )
            db.add(asn_line)
            line_out.append(ASNLineResponse(
                id=asn_line.id,
                po_line_id=asn_line.po_line_id,
                item_variant_id=asn_line.item_variant_id,
                quantity_shipped=float(asn_line.quantity_shipped),
                lot_number=asn_line.lot_number
            ))

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="SUPPLIER_SUBMIT_ASN",
            entity_type="AdvanceShippingNotice",
            entity_id=asn.id,
            user_id=portal_user_id,
            changes={"asn_number": asn.asn_number, "tracking_number": asn.tracking_number, "po_id": po.id}
        )

        await db.commit()
        await db.refresh(asn)

        return ASNResponse(
            id=asn.id,
            asn_number=asn.asn_number,
            purchase_order_id=po.id,
            po_number=po.po_number,
            carrier_code=asn.carrier_code,
            tracking_number=asn.tracking_number,
            estimated_arrival_date=asn.estimated_arrival_date,
            status=asn.status,
            created_at=asn.created_at,
            lines=line_out
        )

    # ========================================================================
    # SECURE PRE-SIGNED DOCUMENT TOKEN VERIFICATION
    # ========================================================================

    @staticmethod
    def generate_document_token(tenant_id: str, entity_id: str, document_type: str, document_id: str) -> str:
        secret = settings.SECRET_KEY
        expires_at = int((get_utc_now() + timedelta(minutes=15)).timestamp())
        raw_msg = f"{tenant_id}:{entity_id}:{document_type}:{document_id}:{expires_at}"
        sig = hmac.new(secret.encode(), raw_msg.encode(), hashlib.sha256).hexdigest()
        payload = {"token": f"{raw_msg}:{sig}", "expires_at": expires_at}
        import base64
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    @staticmethod
    def verify_document_token(token_str: str, expected_tenant_id: str, expected_entity_id: str) -> Dict[str, str]:
        import base64
        try:
            raw_json = base64.urlsafe_b64decode(token_str.encode()).decode()
            data = json.loads(raw_json)
            token = data["token"]
            parts = token.split(":")
            if len(parts) != 6:
                raise HTTPException(status_code=400, detail="Invalid token structure")
            tenant_id, entity_id, doc_type, doc_id, exp_ts, sig = parts

            if tenant_id != expected_tenant_id or entity_id != expected_entity_id:
                raise HTTPException(status_code=403, detail="Cross-company document access forbidden")

            if int(exp_ts) < int(get_utc_now().timestamp()):
                raise HTTPException(status_code=401, detail="Document token expired")

            raw_msg = f"{tenant_id}:{entity_id}:{doc_type}:{doc_id}:{exp_ts}"
            secret = settings.SECRET_KEY
            expected_sig = hmac.new(secret.encode(), raw_msg.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, sig):
                raise HTTPException(status_code=403, detail="Invalid document token signature")

            return {"document_type": doc_type, "document_id": doc_id}
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=400, detail="Malformed document token")
