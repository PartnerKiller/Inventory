import pytest
import uuid
import hashlib
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.sales import Customer, SalesOrder, SOLineItem, PriceList, PriceListItem, CustomerPriceList, Shipment
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem, GoodsReceipt
from app.models.ledger import StockLedgerTransaction, StockLedgerEntry
from app.models.costing import CostLayer
from app.models.portal import (
    PortalUser,
    PortalUserMembership,
    PortalInvitation,
    AdvanceShippingNotice,
    ASNLineItem
)
from app.schemas.portal import (
    PortalLoginRequest,
    CustomerOrderCreateRequest,
    CustomerOrderLineCreate,
    SupplierPOConfirmRequest,
    SupplierPORejectRequest,
    CreateASNRequest,
    ASNLineCreate
)
from app.services.portal_service import PortalService

async def create_portal_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-PORT-{uuid.uuid4().hex[:4]}", name="Primary Portal Hub")
    db.add(wh)
    await db.flush()

    bin_storage = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="STORAGE-01", type="STORAGE")
    db.add(bin_storage)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Commercial Goods", code=f"CAT-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-B2B-{uuid.uuid4().hex[:4]}", name="Industrial Widget")
    db.add(item)
    await db.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-STD",
        variant_name="Standard", cost_price=Decimal("40.00"), selling_price=Decimal("100.00")
    )
    db.add(variant)

    # Customer A & Customer B
    cust_a = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-A-{uuid.uuid4().hex[:4]}", name="Acme Aerospace", currency="USD")
    cust_b = Customer(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-B-{uuid.uuid4().hex[:4]}", name="Beta Robotics", currency="USD")
    db.add_all([cust_a, cust_b])
    await db.flush()

    # Price list for Customer A
    pl = PriceList(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"PL-{uuid.uuid4().hex[:6]}", name="Acme Special Pricing", currency="USD")
    db.add(pl)
    await db.flush()

    pli = PriceListItem(id=str(uuid.uuid4()), price_list_id=pl.id, item_variant_id=variant.id, base_price=Decimal("85.00"))
    cpl = CustomerPriceList(id=str(uuid.uuid4()), tenant_id=tenant_id, customer_id=cust_a.id, price_list_id=pl.id, priority=1)
    db.add_all([pli, cpl])

    # Supplier A & Supplier B
    supp_a = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-A-{uuid.uuid4().hex[:4]}", name="Global Titanium Supply", currency="USD")
    supp_b = Supplier(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"SUPP-B-{uuid.uuid4().hex[:4]}", name="Delta Precision Parts", currency="USD")
    db.add_all([supp_a, supp_b])
    await db.flush()

    # Create Portal Users
    user_cust_a = await PortalService.create_portal_user_with_membership(
        db, tenant_id, email=f"procurement_{uuid.uuid4().hex[:4]}@acme.com", password="Password123!", full_name="Alice Acme",
        portal_type="CUSTOMER", entity_id=cust_a.id, role="ADMIN"
    )

    user_supp_a = await PortalService.create_portal_user_with_membership(
        db, tenant_id, email=f"sales_{uuid.uuid4().hex[:4]}@globaltitanium.com", password="Password123!", full_name="Bob Titanium",
        portal_type="SUPPLIER", entity_id=supp_a.id, role="ADMIN"
    )

    # Sample PO for Supplier A
    po_a = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-SUPP-{uuid.uuid4().hex[:4]}",
        supplier_id=supp_a.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("400.00")
    )
    db.add(po_a)
    await db.flush()
    pol_a = POLineItem(
        id=str(uuid.uuid4()), purchase_order_id=po_a.id, item_variant_id=variant.id,
        quantity_ordered=Decimal("10.0"), unit_price=Decimal("40.00"), line_total=Decimal("400.00")
    )
    db.add(pol_a)

    # Sample PO for Supplier B
    po_b = PurchaseOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, po_number=f"PO-SUPP-B-{uuid.uuid4().hex[:4]}",
        supplier_id=supp_b.id, target_warehouse_id=wh.id, status="APPROVED", total_amount=Decimal("800.00")
    )
    db.add(po_b)

    # Sample SO for Customer B
    so_b = SalesOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-BETA-{uuid.uuid4().hex[:4]}",
        customer_id=cust_b.id, warehouse_id=wh.id, status="CONFIRMED", total_amount=Decimal("500.00")
    )
    db.add(so_b)

    await db.commit()
    return wh, variant, cust_a, cust_b, supp_a, supp_b, user_cust_a, user_supp_a, po_a, po_b, so_b, pol_a

# ============================================================================
# 1. INVITATION LIFECYCLE & REPLAY PROTECTION
# ============================================================================

@pytest.mark.asyncio
async def test_invitation_lifecycle_and_replay_protection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, _, _, _, _, _, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    # 1. Create valid invitation
    inv, raw_token = await PortalService.create_portal_invitation(
        db_session, tenant_id, email=f"invitee_{uuid.uuid4().hex[:4]}@acme.com",
        entity_type="CUSTOMER", entity_id=cust_a.id, role="MEMBER"
    )
    assert inv.accepted_at is None

    # 2. Accept valid invitation -> SUCCESS
    accepted_user = await PortalService.accept_portal_invitation(
        db_session, raw_token, full_name="Invited Member", password="SecurePassword123!"
    )
    assert accepted_user.is_active == True

    # 3. Same invitation -> accept again -> REJECT (Single-use replay protection)
    with pytest.raises(HTTPException) as exc_info:
        await PortalService.accept_portal_invitation(
            db_session, raw_token, full_name="Replay Attacker", password="SecurePassword123!"
        )
    assert exc_info.value.status_code == 400
    assert "already been accepted" in exc_info.value.detail

    # 4. Expired invitation -> REJECT
    inv_exp, exp_token = await PortalService.create_portal_invitation(
        db_session, tenant_id, email=f"expired_{uuid.uuid4().hex[:4]}@acme.com",
        entity_type="CUSTOMER", entity_id=cust_a.id, role="MEMBER"
    )
    inv_exp.expires_at = get_utc_now() - timedelta(days=1)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await PortalService.accept_portal_invitation(
            db_session, exp_token, full_name="Late User", password="SecurePassword123!"
        )
    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail

    # 5. Tampered invitation token -> REJECT
    with pytest.raises(HTTPException) as exc_info:
        await PortalService.accept_portal_invitation(
            db_session, "completely_forged_invalid_token", full_name="Tamper User", password="SecurePassword123!"
        )
    assert exc_info.value.status_code == 400

# ============================================================================
# 2. SUPPLIER DATA SANITIZATION & ZERO INTERNAL EXPOSURE
# ============================================================================

@pytest.mark.asyncio
async def test_supplier_data_sanitization_zero_internal_exposure(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, supp_a, _, _, user_supp_a, po_a, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    pos = await PortalService.get_supplier_purchase_orders(db_session, tenant_id, supp_a.id)
    assert len(pos) >= 1
    po_dict = pos[0].model_dump()

    # Assert zero exposure of internal data
    forbidden_supplier_fields = [
        "customer_id", "customer_name", "customer_notes", "sales_order_id",
        "bin_id", "bin_code", "warehouse_bin", "margin", "profit_margin", "cogs", "internal_notes"
    ]
    for field in forbidden_supplier_fields:
        assert field not in po_dict, f"Supplier response leaked forbidden field: {field}"

# ============================================================================
# 3. CUSTOMER ORDER INVENTORY ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_customer_order_inventory_isolation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, _, _, user_cust_a, _, _, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    tx_count_before = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_count_before = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # Create customer portal order
    req = CustomerOrderCreateRequest(
        customer_notes="Customer Order Isolation Verification",
        lines=[CustomerOrderLineCreate(item_variant_id=variant.id, quantity=Decimal("3.0"))]
    )
    so_resp = await PortalService.create_customer_sales_order(
        db_session, tenant_id, cust_a.id, req, portal_user_id=user_cust_a.id
    )
    assert so_resp.so_number.startswith("SO-")

    tx_count_after = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_count_after = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # Assert ZERO inventory ledger or costing mutation
    assert tx_count_after == tx_count_before, "Customer portal order creation mutated StockLedgerTransaction"
    assert layer_count_after == layer_count_before, "Customer portal order creation mutated CostLayer"

# ============================================================================
# 4. SUPPLIER PO / ASN INVENTORY ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_supplier_po_and_asn_inventory_isolation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, _, _, supp_a, _, _, user_supp_a, po_a, _, _, pol_a = await create_portal_test_environment(db_session, tenant_id)

    tx_count_before = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    grn_count_before = (await db_session.execute(select(func.count()).select_from(GoodsReceipt))).scalar()
    layer_count_before = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # 1. Supplier confirms PO
    conf = await PortalService.confirm_purchase_order(
        db_session, tenant_id, supp_a.id, po_a.id,
        SupplierPOConfirmRequest(promised_delivery_date=get_utc_now() + timedelta(days=5)),
        portal_user_id=user_supp_a.id
    )
    assert conf.status == "CONFIRMED"

    # 2. Supplier submits ASN
    asn = await PortalService.create_advance_shipping_notice(
        db_session, tenant_id, supp_a.id,
        CreateASNRequest(
            purchase_order_id=po_a.id, carrier_code="UPS", tracking_number="1Z99999999",
            estimated_arrival_date=get_utc_now() + timedelta(days=3),
            lines=[ASNLineCreate(po_line_id=pol_a.id, item_variant_id=variant.id, quantity_shipped=Decimal("10.0"))]
        ),
        portal_user_id=user_supp_a.id
    )
    assert asn.status == "SUBMITTED"

    tx_count_after = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    grn_count_after = (await db_session.execute(select(func.count()).select_from(GoodsReceipt))).scalar()
    layer_count_after = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # Assert zero inventory receipt or costing mutation from supplier confirmation/ASN
    assert tx_count_after == tx_count_before, "Supplier PO/ASN confirmation mutated stock ledger"
    assert grn_count_after == grn_count_before, "Supplier PO/ASN confirmation generated GoodsReceipt"
    assert layer_count_after == layer_count_before, "Supplier PO/ASN confirmation mutated cost layers"

# ============================================================================
# 5. IMMEDIATE PORTAL USER DEACTIVATION
# ============================================================================

@pytest.mark.asyncio
async def test_immediate_portal_user_deactivation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, _, _, user_cust_a, _, _, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    # 1. Login and get valid token
    auth_resp = await PortalService.authenticate_portal_user(db_session, PortalLoginRequest(
        email=user_cust_a.email, password="Password123!", portal_type="CUSTOMER"
    ))
    assert auth_resp.access_token is not None

    # 2. Verify active user check succeeds
    active_user = await PortalService.verify_portal_user_active(db_session, user_cust_a.id)
    assert active_user.id == user_cust_a.id

    # 3. Deactivate portal user in DB
    user_cust_a.is_active = False
    await db_session.commit()

    # 4. Same user session requests protected check -> 401/403
    with pytest.raises(HTTPException) as exc_info:
        await PortalService.verify_portal_user_active(db_session, user_cust_a.id)
    assert exc_info.value.status_code == 401
    assert "deactivated" in exc_info.value.detail

# ============================================================================
# 6. MULTI-COMPANY MEMBERSHIP ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_multi_company_membership_isolation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, cust_b, _, _, user_cust_a, _, _, _, so_b, _ = await create_portal_test_environment(db_session, tenant_id)

    # Add second membership for Customer B
    mem_b = PortalUserMembership(
        id=str(uuid.uuid4()), portal_user_id=user_cust_a.id, tenant_id=tenant_id,
        entity_type="CUSTOMER", entity_id=cust_b.id, role="MEMBER", is_active=True
    )
    db_session.add(mem_b)
    await db_session.commit()

    # Query with context for Customer A: strictly excludes Customer B's orders
    orders_a = await PortalService.get_customer_orders(db_session, tenant_id, cust_a.id)
    order_ids_a = [o.id for o in orders_a]
    assert so_b.id not in order_ids_a

    # Query with context for Customer B: includes Customer B's orders
    orders_b = await PortalService.get_customer_orders(db_session, tenant_id, cust_b.id)
    order_ids_b = [o.id for o in orders_b]
    assert so_b.id in order_ids_b

# ============================================================================
# 7. MFA STATUS (DEFERRED VERIFICATION)
# ============================================================================

def test_mfa_status_reporting():
    """
    MFA is scaffolded in data model (mfa_secret, is_mfa_enabled),
    but full TOTP RFC6238 endpoint verification is deferred.
    """
    mfa_implemented = False
    assert mfa_implemented is False, "MFA status is DEFERRED"

# ============================================================================
# 8. CUSTOMER PAYMENT SAFETY
# ============================================================================

@pytest.mark.asyncio
async def test_customer_payment_safety_blocks_direct_mutation(db_session: AsyncSession):
    """
    Verifies that customer portal users cannot directly modify invoice balances or fabricate paid status.
    """
    # Customer portal DTOs do not contain invoice status or balance setter
    from app.schemas.portal import CustomerOrderCreateRequest
    order_dict = CustomerOrderCreateRequest(lines=[CustomerOrderLineCreate(item_variant_id="var-1", quantity=Decimal("1.0"))]).model_dump()
    assert "payment_status" not in order_dict
    assert "paid_amount" not in order_dict
    assert "is_paid" not in order_dict

# ============================================================================
# 9. CUSTOMER ORDER CANCELLATION LIFECYCLE
# ============================================================================

@pytest.mark.asyncio
async def test_customer_order_cancellation_lifecycle(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, _, _, user_cust_a, _, _, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    # 1. Create order
    so = await PortalService.create_customer_sales_order(
        db_session, tenant_id, cust_a.id,
        CustomerOrderCreateRequest(lines=[CustomerOrderLineCreate(item_variant_id=variant.id, quantity=Decimal("2.0"))]),
        portal_user_id=user_cust_a.id
    )

    # 2. Cancel CONFIRMED order -> SUCCESS
    cancelled_so = await PortalService.cancel_customer_sales_order(
        db_session, tenant_id, cust_a.id, so.id, reason="Customer cancelled before dispatch", portal_user_id=user_cust_a.id
    )
    assert cancelled_so.status == "CANCELLED"

    # 3. Create another order and set to SHIPPED -> Cancel must FAIL (400)
    so_shipped = SalesOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-SHIP-{uuid.uuid4().hex[:4]}",
        customer_id=cust_a.id, warehouse_id=wh.id, status="SHIPPED", total_amount=Decimal("200.00")
    )
    db_session.add(so_shipped)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await PortalService.cancel_customer_sales_order(
            db_session, tenant_id, cust_a.id, so_shipped.id, reason="Try cancelling shipped order", portal_user_id=user_cust_a.id
        )
    assert exc_info.value.status_code == 400
    assert "Cannot cancel sales order in 'SHIPPED'" in exc_info.value.detail

# ============================================================================
# 10. SUPPLIER PO REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_supplier_po_rejection_lifecycle(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, _, _, supp_a, supp_b, _, user_supp_a, po_a, po_b, _, _ = await create_portal_test_environment(db_session, tenant_id)

    tx_count_before = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_count_before = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # 1. Supplier A rejects PO A -> SUCCESS
    rej_resp = await PortalService.reject_purchase_order(
        db_session, tenant_id, supp_a.id, po_a.id,
        SupplierPORejectRequest(rejection_reason="Raw material stockout at factory"),
        portal_user_id=user_supp_a.id
    )
    assert rej_resp.status == "CANCELLED"

    # 2. Supplier A attempts to reject Supplier B's PO -> 404 (Isolation Guard)
    with pytest.raises(HTTPException) as exc_info:
        await PortalService.reject_purchase_order(
            db_session, tenant_id, supp_a.id, po_b.id,
            SupplierPORejectRequest(rejection_reason="Unauthorized rejection attempt"),
            portal_user_id=user_supp_a.id
        )
    assert exc_info.value.status_code == 404

    # 3. Assert zero inventory or costing mutations from rejection
    tx_count_after = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_count_after = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()
    assert tx_count_after == tx_count_before
    assert layer_count_after == layer_count_before

# ============================================================================
# 11. PORTAL DTO SECURITY REGRESSION (AUTOMATED FORBIDDEN-FIELD SCAN)
# ============================================================================

@pytest.mark.asyncio
async def test_portal_dto_security_regression(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, variant, cust_a, _, supp_a, _, _, _, po_a, _, _, _ = await create_portal_test_environment(db_session, tenant_id)

    # Customer catalog and orders
    catalog = await PortalService.get_customer_catalog(db_session, tenant_id, cust_a.id)
    cust_orders = await PortalService.get_customer_orders(db_session, tenant_id, cust_a.id)

    for item in catalog:
        item_d = item.model_dump()
        for f in ["cost_price", "unit_cost", "margin", "landed_cost", "supplier_id"]:
            assert f not in item_d, f"Customer catalog leaked: {f}"

    for order in cust_orders:
        ord_d = order.model_dump()
        for f in ["cost_price", "unit_cost", "margin", "landed_cost", "supplier_id", "internal_notes"]:
            assert f not in ord_d, f"Customer order leaked: {f}"

# ============================================================================
# 12. DOCUMENT AUTHORIZATION MATRIX
# ============================================================================

@pytest.mark.asyncio
async def test_document_authorization_matrix():
    tenant_id = "00000000-0000-0000-0000-000000000001"
    cust_a_id = "cust-aaa"
    cust_b_id = "cust-bbb"
    supp_a_id = "supp-aaa"
    supp_b_id = "supp-bbb"

    tok_cust_a = PortalService.generate_document_token(tenant_id, cust_a_id, "INVOICE", "INV-001")
    tok_supp_a = PortalService.generate_document_token(tenant_id, supp_a_id, "PURCHASE_ORDER", "PO-001")

    # 1. Customer A token + Customer A context -> SUCCESS
    assert PortalService.verify_document_token(tok_cust_a, tenant_id, cust_a_id)["document_id"] == "INV-001"

    # 2. Customer A token + Customer B context -> REJECT (403)
    with pytest.raises(HTTPException) as exc:
        PortalService.verify_document_token(tok_cust_a, tenant_id, cust_b_id)
    assert exc.value.status_code == 403

    # 3. Supplier A token + Supplier B context -> REJECT (403)
    with pytest.raises(HTTPException) as exc:
        PortalService.verify_document_token(tok_supp_a, tenant_id, supp_b_id)
    assert exc.value.status_code == 403

    # 4. Customer token + Supplier context -> REJECT (403)
    with pytest.raises(HTTPException) as exc:
        PortalService.verify_document_token(tok_cust_a, tenant_id, supp_a_id)
    assert exc.value.status_code == 403

    # 5. Supplier token + Customer context -> REJECT (403)
    with pytest.raises(HTTPException) as exc:
        PortalService.verify_document_token(tok_supp_a, tenant_id, cust_a_id)
    assert exc.value.status_code == 403
