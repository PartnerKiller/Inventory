import uuid
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert
from app.models.auth import User, Role, Permission, user_roles_table, role_permissions_table
from app.models.warehouse import Warehouse, LocationBin
from app.models.item import ItemCategory, Item, ItemVariant, Barcode
from app.models.purchasing import Supplier, PurchaseOrder, POLineItem
from app.models.sales import Customer, SalesOrder, SOLineItem
from app.models.ledger import StockLedgerTransaction, StockLedgerEntry, StockBalanceCache, StockBatch
from app.core.security import get_password_hash
from app.core.config import settings
from app.models.base import get_utc_now
from app.services.costing_service import CostingService

DEFAULT_PERMISSIONS = [
    ("users:read", "Users", "Read user accounts and profiles"),
    ("users:write", "Users", "Create, edit, and deactivate user accounts"),
    ("roles:read", "Roles", "Read roles and permissions"),
    ("roles:write", "Roles", "Create and modify roles and permissions"),
    ("settings:read", "Settings", "Read system and tenant settings"),
    ("settings:write", "Settings", "Update system and tenant settings"),
    ("warehouses:read", "Warehouses", "Read warehouse and bin layouts"),
    ("warehouses:write", "Warehouses", "Create and modify warehouses and bins"),
    ("inventory:read", "Inventory", "View items, variants, barcodes and catalog"),
    ("inventory:write", "Inventory", "Create and update items, variants and barcodes"),
    ("inventory:adjust", "Inventory", "Perform physical stock count adjustments"),
    ("ledger:read", "Stock Ledger", "View immutable stock ledger transactions and entries"),
    ("ledger:transfer", "Stock Ledger", "Perform inter-bin and inter-warehouse stock transfers"),
    ("purchasing:read", "Purchasing", "View suppliers and purchase orders"),
    ("purchasing:write", "Purchasing", "Create and edit purchase orders"),
    ("purchasing:approve", "Purchasing", "Approve purchase orders for fulfillment"),
    ("purchasing:receive", "Purchasing", "Receive goods against purchase orders"),
    ("sales:read", "Sales", "View customers and sales orders"),
    ("sales:write", "Sales", "Create and edit sales orders"),
    ("sales:allocate", "Sales", "Allocate and reserve inventory for sales orders"),
    ("sales:fulfill", "Sales", "Pick, pack, and dispatch sales orders"),
    ("costing:read", "Costing", "View inventory cost layers, COGS, and valuation profiles"),
    ("costing:write", "Costing", "Update costing methods and seed opening layers"),
    ("reports:view", "Reports", "Access valuation, velocity, and analytics dashboards"),
    ("audit:read", "Audit", "View compliance and change audit trails"),
]

async def seed_database(db: AsyncSession):
    # 1. Check if already seeded
    admin_check = await db.execute(select(User).where(User.email == "admin@inventory.local"))
    if admin_check.scalar_one_or_none():
        return

    tenant_id = settings.TENANT_DEFAULT_ID

    # 2. Seed Permissions
    perm_map = {}
    for code, mod, desc in DEFAULT_PERMISSIONS:
        perm = Permission(
            id=str(uuid.uuid4()),
            code=code,
            module=mod,
            description=desc
        )
        db.add(perm)
        perm_map[code] = perm
    await db.flush()

    # 3. Seed Roles
    super_admin_role = Role(id=str(uuid.uuid4()), tenant_id=tenant_id, name="SUPER_ADMIN", description="Unrestricted platform access", is_system=True)
    manager_role = Role(id=str(uuid.uuid4()), tenant_id=tenant_id, name="WAREHOUSE_MANAGER", description="Manages warehouses, approvals and ledger", is_system=True)
    clerk_role = Role(id=str(uuid.uuid4()), tenant_id=tenant_id, name="INVENTORY_CLERK", description="Receives, transfers, picks and counts stock", is_system=True)
    purchaser_role = Role(id=str(uuid.uuid4()), tenant_id=tenant_id, name="PURCHASING_AGENT", description="Creates POs and manages suppliers", is_system=True)
    auditor_role = Role(id=str(uuid.uuid4()), tenant_id=tenant_id, name="AUDITOR", description="Read-only compliance access", is_system=True)

    db.add_all([super_admin_role, manager_role, clerk_role, purchaser_role, auditor_role])
    await db.flush()

    # Associate permissions via table inserts
    role_perm_rows = []
    # Super Admin -> All
    for p in perm_map.values():
        role_perm_rows.append({"role_id": super_admin_role.id, "permission_id": p.id})

    # Manager
    for c, p in perm_map.items():
        if not c.startswith("users:write"):
            role_perm_rows.append({"role_id": manager_role.id, "permission_id": p.id})

    # Clerk
    for c, p in perm_map.items():
        if c in ["inventory:read", "inventory:adjust", "ledger:read", "ledger:transfer", "purchasing:read", "purchasing:receive", "sales:read", "sales:fulfill"]:
            role_perm_rows.append({"role_id": clerk_role.id, "permission_id": p.id})

    # Purchaser
    for c, p in perm_map.items():
        if c.startswith("purchasing:") or c in ["inventory:read", "reports:view"]:
            role_perm_rows.append({"role_id": purchaser_role.id, "permission_id": p.id})

    # Auditor
    for c, p in perm_map.items():
        if c.endswith(":read") or c in ["reports:view", "audit:read"]:
            role_perm_rows.append({"role_id": auditor_role.id, "permission_id": p.id})

    for row in role_perm_rows:
        await db.execute(insert(role_permissions_table).values(row))
    await db.flush()

    # 4. Seed Users
    admin_user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email="admin@inventory.local",
        password_hash=get_password_hash("Admin123!"),
        full_name="Sarah Jenkins (Super Admin)",
        is_active=True,
        is_superuser=True
    )

    manager_user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email="manager@inventory.local",
        password_hash=get_password_hash("Manager123!"),
        full_name="Marcus Vance (Austin WH Manager)",
        is_active=True,
        is_superuser=False
    )

    clerk_user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email="clerk@inventory.local",
        password_hash=get_password_hash("Clerk123!"),
        full_name="Alex Rivera (Inventory Clerk)",
        is_active=True,
        is_superuser=False
    )

    db.add_all([admin_user, manager_user, clerk_user])
    await db.flush()

    # Associate user roles
    await db.execute(insert(user_roles_table).values({"user_id": admin_user.id, "role_id": super_admin_role.id}))
    await db.execute(insert(user_roles_table).values({"user_id": manager_user.id, "role_id": manager_role.id}))
    await db.execute(insert(user_roles_table).values({"user_id": clerk_user.id, "role_id": clerk_role.id}))
    await db.flush()

    # 5. Seed Warehouses & Bins
    wh1 = Warehouse(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="WH-ATX-01",
        name="Austin Central Distribution Hub",
        address={"street": "4200 Logistics Pkwy", "city": "Austin", "state": "TX", "postalCode": "78744", "country": "USA"},
        is_active=True
    )
    wh2 = Warehouse(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="WH-DAL-02",
        name="Dallas Regional Fulfillment Center",
        address={"street": "1000 Airport Freeway", "city": "Dallas", "state": "TX", "postalCode": "75261", "country": "USA"},
        is_active=True
    )
    db.add_all([wh1, wh2])
    await db.flush()

    # Bins for WH1
    wh1_rcv = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="ATX-RCV-01", aisle="R", rack="01", shelf="01", bin="01", type="RECEIVING")
    wh1_stg = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="ATX-STG-01", aisle="S", rack="01", shelf="01", bin="01", type="STAGING")
    wh1_a01 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="ATX-A01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")
    wh1_a02 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="ATX-A01-02", aisle="A", rack="01", shelf="01", bin="02", type="STORAGE")
    wh1_b01 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh1.id, code="ATX-B01-01", aisle="B", rack="01", shelf="01", bin="01", type="STORAGE")

    # Bins for WH2
    wh2_rcv = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh2.id, code="DAL-RCV-01", aisle="R", rack="01", shelf="01", bin="01", type="RECEIVING")
    wh2_a01 = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh2.id, code="DAL-A01-01", aisle="A", rack="01", shelf="01", bin="01", type="STORAGE")

    db.add_all([wh1_rcv, wh1_stg, wh1_a01, wh1_a02, wh1_b01, wh2_rcv, wh2_a01])
    await db.flush()

    # 6. Seed Categories
    cat1 = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Industrial Electronics", code="ELEC", description="Sensors, PCBs, and controllers")
    cat2 = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Precision Fasteners", code="FAST", description="Titanium and stainless screws, bolts and rivets")
    cat3 = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Packaging Supplies", code="PACK", description="Corrugated boxes, protective wrap, labels")
    db.add_all([cat1, cat2, cat3])
    await db.flush()

    # 7. Seed Items, Variants, Barcodes
    item1 = Item(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=cat1.id,
        sku="SKU-THM-100",
        name="Industrial IoT Thermal Sensor Pro",
        description="High precision wireless temperature and humidity telemetry sensor with Modbus support.",
        base_uom="PCS",
        valuation_method="FIFO",
        reorder_point=Decimal("20.0"),
        reorder_quantity=Decimal("100.0"),
        is_batch_tracked=True,
        is_serial_tracked=False,
        is_active=True
    )
    db.add(item1)
    await db.flush()

    var1_1 = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item1.id,
        variant_sku="SKU-THM-100-IP67",
        variant_name="IP67 Waterproof Casing",
        attributes={"casing": "IP67", "wireless": "LoRaWAN"},
        cost_price=Decimal("42.50"),
        selling_price=Decimal("89.99")
    )
    var1_2 = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item1.id,
        variant_sku="SKU-THM-100-STD",
        variant_name="Standard Indoor Mount",
        attributes={"casing": "Standard", "wireless": "BLE / Zigbee"},
        cost_price=Decimal("28.00"),
        selling_price=Decimal("59.99")
    )
    db.add_all([var1_1, var1_2])
    await db.flush()

    bc1_1 = Barcode(id=str(uuid.uuid4()), item_variant_id=var1_1.id, barcode_value="890123456789", symbology="CODE128", is_primary=True)
    bc1_2 = Barcode(id=str(uuid.uuid4()), item_variant_id=var1_2.id, barcode_value="890123456790", symbology="CODE128", is_primary=True)
    db.add_all([bc1_1, bc1_2])

    item2 = Item(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=cat2.id,
        sku="SKU-BLT-M8-40",
        name="Stainless Steel Hex Flange Bolt (M8 x 40mm)",
        description="Grade 316 A4 Marine Stainless Steel heavy duty industrial fasteners.",
        base_uom="BOX",
        valuation_method="WEIGHTED_AVERAGE",
        reorder_point=Decimal("50.0"),
        reorder_quantity=Decimal("200.0"),
        is_batch_tracked=False,
        is_serial_tracked=False,
        is_active=True
    )
    db.add(item2)
    await db.flush()

    var2_1 = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item2.id,
        variant_sku="SKU-BLT-M8-40-100PK",
        variant_name="Box of 100 Pcs",
        attributes={"packSize": "100"},
        cost_price=Decimal("14.20"),
        selling_price=Decimal("24.50")
    )
    db.add(var2_1)
    await db.flush()

    bc2_1 = Barcode(id=str(uuid.uuid4()), item_variant_id=var2_1.id, barcode_value="789012345671", symbology="CODE128", is_primary=True)
    db.add(bc2_1)

    item3 = Item(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        category_id=cat3.id,
        sku="SKU-BOX-4040",
        name="Double-Wall Corrugated Heavy Shipping Box 40x40x40cm",
        description="ECT-48 heavy-duty cardboard boxes for sensitive component shipping.",
        base_uom="PCS",
        valuation_method="FIFO",
        reorder_point=Decimal("100.0"),
        reorder_quantity=Decimal("500.0"),
        is_batch_tracked=False,
        is_serial_tracked=False,
        is_active=True
    )
    db.add(item3)
    await db.flush()

    var3_1 = ItemVariant(
        id=str(uuid.uuid4()),
        item_id=item3.id,
        variant_sku="SKU-BOX-4040-KRAFT",
        variant_name="Standard Kraft Brown",
        attributes={"color": "Kraft"},
        cost_price=Decimal("2.40"),
        selling_price=Decimal("4.80")
    )
    db.add(var3_1)
    await db.flush()

    bc3_1 = Barcode(id=str(uuid.uuid4()), item_variant_id=var3_1.id, barcode_value="654321098765", symbology="CODE128", is_primary=True)
    db.add(bc3_1)

    # 8. Seed Suppliers & Customers
    sup1 = Supplier(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="SUP-VERTEX",
        name="Vertex Microelectronics Corp",
        email="orders@vertex-micro.com",
        phone="+1 (512) 555-0198",
        payment_terms="Net 30",
        currency="USD",
        is_active=True
    )
    sup2 = Supplier(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="SUP-TITAN",
        name="Titan Fasteners & Hardware Supply",
        email="sales@titan-hardware.com",
        phone="+1 (214) 555-0144",
        payment_terms="Net 45",
        currency="USD",
        is_active=True
    )
    db.add_all([sup1, sup2])

    cust1 = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="CUST-APEX",
        name="Apex Industrial Automation LLC",
        email="procurement@apex-automation.io",
        phone="+1 (512) 555-0322",
        shipping_addresses=[{"address": "8800 Technology Dr, Austin, TX 78759"}],
        is_active=True
    )
    cust2 = Customer(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code="CUST-NEXUS",
        name="Nexus Robotics Labs",
        email="inventory@nexus-robotics.org",
        phone="+1 (972) 555-0811",
        shipping_addresses=[{"address": "1200 Innovation Blvd, Plano, TX 75024"}],
        is_active=True
    )
    db.add_all([cust1, cust2])
    await db.flush()

    # 9. Seed Initial Stock Balances & Double-Entry Ledger Transactions
    batch1 = StockBatch(
        id=str(uuid.uuid4()),
        item_variant_id=var1_1.id,
        batch_number="BCH-2026-08A",
        cost_per_unit=var1_1.cost_price
    )
    db.add(batch1)
    await db.flush()

    init_tx = StockLedgerTransaction(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        transaction_number="TX-INIT-000001",
        transaction_type="PURCHASE_RECEIPT",
        reference_document_type="INITIAL_BALANCE",
        posted_by_user_id=admin_user.id,
        posted_at=get_utc_now(),
        notes="Opening inventory balance initialization"
    )
    db.add(init_tx)
    await db.flush()

    bal1 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh1.id,
        location_bin_id=wh1_a01.id,
        item_variant_id=var1_1.id,
        batch_id=batch1.id,
        quantity_on_hand=Decimal("120.0"),
        quantity_allocated=Decimal("0.0"),
        updated_at=get_utc_now()
    )
    bal2 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh1.id,
        location_bin_id=wh1_a02.id,
        item_variant_id=var1_2.id,
        quantity_on_hand=Decimal("85.0"),
        quantity_allocated=Decimal("0.0"),
        updated_at=get_utc_now()
    )
    bal3 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh1.id,
        location_bin_id=wh1_b01.id,
        item_variant_id=var2_1.id,
        quantity_on_hand=Decimal("250.0"),
        quantity_allocated=Decimal("0.0"),
        updated_at=get_utc_now()
    )
    bal4 = StockBalanceCache(
        id=str(uuid.uuid4()),
        warehouse_id=wh2.id,
        location_bin_id=wh2_a01.id,
        item_variant_id=var3_1.id,
        quantity_on_hand=Decimal("450.0"),
        quantity_allocated=Decimal("0.0"),
        updated_at=get_utc_now()
    )
    db.add_all([bal1, bal2, bal3, bal4])

    e1 = StockLedgerEntry(
        id=str(uuid.uuid4()),
        transaction_id=init_tx.id,
        item_variant_id=var1_1.id,
        batch_id=batch1.id,
        destination_location_bin_id=wh1_a01.id,
        quantity=Decimal("120.0"),
        uom="PCS",
        unit_cost=var1_1.cost_price,
        total_cost=Decimal("120.0") * var1_1.cost_price,
        entry_timestamp=get_utc_now()
    )
    e2 = StockLedgerEntry(
        id=str(uuid.uuid4()),
        transaction_id=init_tx.id,
        item_variant_id=var1_2.id,
        destination_location_bin_id=wh1_a02.id,
        quantity=Decimal("85.0"),
        uom="PCS",
        unit_cost=var1_2.cost_price,
        total_cost=Decimal("85.0") * var1_2.cost_price,
        entry_timestamp=get_utc_now()
    )
    e3 = StockLedgerEntry(
        id=str(uuid.uuid4()),
        transaction_id=init_tx.id,
        item_variant_id=var2_1.id,
        destination_location_bin_id=wh1_b01.id,
        quantity=Decimal("250.0"),
        uom="BOX",
        unit_cost=var2_1.cost_price,
        total_cost=Decimal("250.0") * var2_1.cost_price,
        entry_timestamp=get_utc_now()
    )
    e4 = StockLedgerEntry(
        id=str(uuid.uuid4()),
        transaction_id=init_tx.id,
        item_variant_id=var3_1.id,
        destination_location_bin_id=wh2_a01.id,
        quantity=Decimal("450.0"),
        uom="PCS",
        unit_cost=var3_1.cost_price,
        total_cost=Decimal("450.0") * var3_1.cost_price,
        entry_timestamp=get_utc_now()
    )
    db.add_all([e1, e2, e3, e4])
    await db.flush()

    # Initialize opening CostLayers and ItemCostProfiles for seeded stock
    await CostingService.initialize_opening_cost_layers(db, tenant_id)

    await db.commit()
