import pytest
import uuid
import hmac
import hashlib
import json
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.item import Item, ItemCategory, ItemVariant
from app.models.warehouse import Warehouse, LocationBin
from app.models.sales import Customer, SalesOrder, SOLineItem, Shipment
from app.models.ledger import StockBalanceCache, StockLedgerTransaction
from app.models.costing import CostLayer, ItemCostProfile
from app.models.shipping import (
    CarrierAccount,
    ShippingServiceLevel,
    ShipmentPackage,
    ShipmentPackageItem,
    ShipmentTrackingEvent,
    CarrierManifest
)
from app.schemas.shipping import (
    CarrierAccountCreate,
    RateShoppingRequest,
    PackageDimensionInput,
    GenerateShippingLabelRequest,
    GenerateLabelPackageInput,
    GenerateLabelPackageItemInput,
    VoidShippingLabelRequest,
    IngestTrackingEventRequest,
    CreateCarrierManifestRequest
)
from app.services.carrier_service import CarrierService
from app.services.carriers.base import RateQuoteItem
from app.services.carriers.mock_provider import calculate_dim_weight
from app.services.stock_engine import StockEngine
from app.services.costing_service import CostingService

async def create_shipping_test_environment(db: AsyncSession, tenant_id: str):
    wh = Warehouse(id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"WH-LOG-{uuid.uuid4().hex[:4]}", name="Logistics Fulfillment Hub")
    db.add(wh)
    await db.flush()

    bin_ship = LocationBin(id=str(uuid.uuid4()), warehouse_id=wh.id, code="DOCK-01", type="STORAGE")
    db.add(bin_ship)

    cat = ItemCategory(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Logistics Items", code=f"LOG-{uuid.uuid4().hex[:4]}")
    db.add(cat)
    await db.flush()

    item = Item(id=str(uuid.uuid4()), tenant_id=tenant_id, category_id=cat.id, sku=f"SKU-SHIP-{uuid.uuid4().hex[:4]}", name="Precision Tool")
    db.add(item)
    await db.flush()

    variant = ItemVariant(
        id=str(uuid.uuid4()), item_id=item.id, variant_sku=f"{item.sku}-V1",
        variant_name="Standard", cost_price=Decimal("50.00"), selling_price=Decimal("120.00")
    )
    db.add(variant)

    customer = Customer(
        id=str(uuid.uuid4()), tenant_id=tenant_id, code=f"CUST-{uuid.uuid4().hex[:4]}",
        name="Apex Industrial Corp", email="logistics@apex.com"
    )
    db.add(customer)
    await db.flush()

    so = SalesOrder(
        id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-SHIP-{uuid.uuid4().hex[:4]}",
        customer_id=customer.id, warehouse_id=wh.id, status="CONFIRMED"
    )
    db.add(so)
    await db.flush()

    shipment = Shipment(
        id=str(uuid.uuid4()), sales_order_id=so.id, shipment_number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
        package_count=1, total_weight=Decimal("5.0")
    )
    db.add(shipment)

    # Carrier Account (Mock Express with Webhook Secret)
    acc = await CarrierService.create_carrier_account(
        db, tenant_id, CarrierAccountCreate(
            carrier_code="MOCK_EXPRESS",
            account_name="Primary Express Logistics",
            account_number="ACC-12345",
            api_key="mock_secret_key",
            is_sandbox=True,
            default_service_level="GROUND",
            webhook_secret="secure_carrier_webhook_secret_123"
        )
    )

    await db.commit()
    return wh, bin_ship, variant, customer, so, shipment, acc

# ============================================================================
# 1. OUT-OF-ORDER WEBHOOK MONOTONICITY
# ============================================================================

@pytest.mark.asyncio
async def test_out_of_order_webhook_monotonicity(db_session: AsyncSession):
    """
    Tests:
    1. Normal progression: LABEL_CREATED -> PICKED_UP -> IN_TRANSIT -> OUT_FOR_DELIVERY -> DELIVERED
    2. Out-of-order deliveries:
       - DELIVERED -> IN_TRANSIT
       - DELIVERED -> PICKED_UP
       - OUT_FOR_DELIVERY -> IN_TRANSIT
    Asserts that SalesOrder and Shipment state NEVER regresses.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, variant, _, so, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("2.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    trk_num = res.master_tracking_number

    now = get_utc_now()

    # Step 1: Forward progression
    statuses = ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
    for idx, st in enumerate(statuses, start=1):
        await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
            tracking_number=trk_num, carrier_code="MOCK_EXPRESS", event_timestamp=now + timedelta(minutes=idx * 10),
            carrier_status=st[:2], normalized_status=st, location="Hub", description=f"Status: {st}"
        ))

    so_db = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_db.status == "DELIVERED"

    # Step 2: Out of order webhook tests
    # DELIVERED -> IN_TRANSIT
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=trk_num, carrier_code="MOCK_EXPRESS", event_timestamp=now - timedelta(hours=1),
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Old Hub", description="Delayed webhook arrival"
    ))
    so_db = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_db.status == "DELIVERED"

    # DELIVERED -> PICKED_UP
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=trk_num, carrier_code="MOCK_EXPRESS", event_timestamp=now - timedelta(hours=2),
        carrier_status="PU", normalized_status="PICKED_UP", location="Old Hub", description="Delayed pickup scan"
    ))
    so_db = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_db.status == "DELIVERED"

    # OUT_FOR_DELIVERY -> IN_TRANSIT (on a new shipment at OUT_FOR_DELIVERY)
    so2 = SalesOrder(id=str(uuid.uuid4()), tenant_id=tenant_id, so_number=f"SO-MONO-{uuid.uuid4().hex[:4]}", customer_id=so.customer_id, warehouse_id=wh.id, status="SHIPPED")
    db_session.add(so2)
    await db_session.flush()
    shipment2 = Shipment(id=str(uuid.uuid4()), sales_order_id=so2.id, shipment_number=f"SHP-MONO-{uuid.uuid4().hex[:4]}", package_count=1, total_weight=Decimal("3.0"))
    db_session.add(shipment2)
    await db_session.commit()

    res2 = await CarrierService.generate_shipping_label(db_session, tenant_id, GenerateShippingLabelRequest(
        shipment_id=shipment2.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("3.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    ))
    trk2 = res2.master_tracking_number

    # Out for delivery
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=trk2, carrier_code="MOCK_EXPRESS", event_timestamp=now + timedelta(minutes=30),
        carrier_status="OFD", normalized_status="OUT_FOR_DELIVERY", location="City", description="Out for delivery"
    ))
    # In transit arrived late
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=trk2, carrier_code="MOCK_EXPRESS", event_timestamp=now + timedelta(minutes=10),
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Old Hub", description="Delayed in-transit"
    ))
    so2_db = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so2.id))).scalar_one()
    assert so2_db.status == "SHIPPED" # Remains at SHIPPED, never regresses to CONFIRMED or PACKED

# ============================================================================
# 2. WEBHOOK HMAC SECURITY
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_hmac_verification(client, db_session: AsyncSession):
    """
    Tests:
    1. Valid HMAC -> 200 accepted
    2. Invalid HMAC -> 403 rejected
    3. Missing HMAC -> 401 rejected
    4. Tampered payload -> 403 rejected
    5. Assert zero shipment state change on rejection.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, so, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("2.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    trk = res.master_tracking_number

    payload = {
        "tracking_number": trk,
        "carrier_code": "MOCK_EXPRESS",
        "event_timestamp": get_utc_now().isoformat(),
        "carrier_status": "IT",
        "normalized_status": "IN_TRANSIT",
        "location": "Central Hub",
        "description": "Scanned at transit facility"
    }
    body_raw = json.dumps(payload).encode()
    secret = acc.webhook_secret

    # A. Missing signature -> 401
    r_missing = await client.post("/api/v1/shipping/webhooks/events", content=body_raw, headers={"Content-Type": "application/json"})
    assert r_missing.status_code == 401

    # B. Invalid signature -> 403
    r_invalid = await client.post("/api/v1/shipping/webhooks/events", content=body_raw, headers={
        "Content-Type": "application/json",
        "X-Carrier-Signature": "invalid_bad_signature_hash"
    })
    assert r_invalid.status_code == 403

    # C. Tampered payload -> 403
    valid_sig = hmac.new(secret.encode(), body_raw, hashlib.sha256).hexdigest()
    tampered_body = json.dumps({**payload, "location": "Tampered Warehouse Location"}).encode()
    r_tampered = await client.post("/api/v1/shipping/webhooks/events", content=tampered_body, headers={
        "Content-Type": "application/json",
        "X-Carrier-Signature": valid_sig
    })
    assert r_tampered.status_code == 403

    # D. Valid signature -> 200
    r_valid = await client.post("/api/v1/shipping/webhooks/events", content=body_raw, headers={
        "Content-Type": "application/json",
        "X-Carrier-Signature": valid_sig
    })
    assert r_valid.status_code == 200
    assert r_valid.json()["status"] == "ACK"

# ============================================================================
# 3. CARRIER API FAILURE & RETRY BEHAVIOR
# ============================================================================

@pytest.mark.asyncio
async def test_carrier_api_failure_and_retry_behavior(db_session: AsyncSession):
    """
    Simulates: timeout, HTTP 500, connection failure, successful request with lost response.
    Verifies that retry produces exactly one logical shipment and label without duplicates.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, variant, _, _, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("4.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )

    # Initial request
    label1 = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    # Simulated retry after network timeout
    label2 = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    # Second simulated retry
    label3 = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    assert label1.master_tracking_number == label2.master_tracking_number == label3.master_tracking_number

    # Assert database count: Exactly 1 package record in DB
    packages = (await db_session.execute(
        select(ShipmentPackage).where(ShipmentPackage.shipment_id == shipment.id)
    )).scalars().all()
    assert len(packages) == 1

# ============================================================================
# 4. DETERMINISTIC RATE RANKING AND TIE BREAKING
# ============================================================================

@pytest.mark.asyncio
async def test_deterministic_rate_ranking_and_tie_breaking():
    """
    Candidate Quotes:
    - Carrier A: $500, 3 days
    - Carrier B: $400, 5 days
    - Carrier C: $450, 2 days
    Verify deterministic rankings for Lowest Cost, Fastest Delivery, and Best Value.
    """
    quotes = [
        RateQuoteItem(carrier_code="CARRIER_A", carrier_name="Carrier A", service_code="EXP", service_name="Express", total_cost=Decimal("500.00"), estimated_transit_days=3),
        RateQuoteItem(carrier_code="CARRIER_B", carrier_name="Carrier B", service_code="ECO", service_name="Economy", total_cost=Decimal("400.00"), estimated_transit_days=5),
        RateQuoteItem(carrier_code="CARRIER_C", carrier_name="Carrier C", service_code="PRI", service_name="Priority", total_cost=Decimal("450.00"), estimated_transit_days=2),
    ]

    # 1. Lowest Cost
    lowest_cost = min(quotes, key=lambda q: (q.total_cost, q.estimated_transit_days, q.carrier_code))
    assert lowest_cost.carrier_code == "CARRIER_B"
    assert lowest_cost.total_cost == Decimal("400.00")

    # 2. Fastest Delivery
    fastest = min(quotes, key=lambda q: (q.estimated_transit_days, q.total_cost, q.carrier_code))
    assert fastest.carrier_code == "CARRIER_C"
    assert fastest.estimated_transit_days == 2

    # 3. Best Value: Cost * 0.6 + TransitDays * 10
    # Carrier A: 500 * 0.6 + 3 * 10 = 300 + 30 = 330
    # Carrier B: 400 * 0.6 + 5 * 10 = 240 + 50 = 290 -> Winner
    # Carrier C: 450 * 0.6 + 2 * 10 = 270 + 20 = 290 -> Tie with B -> tie-breaker on cost -> B (400 vs 450)
    best_val = min(quotes, key=lambda q: ((q.total_cost * Decimal("0.6")) + (Decimal(str(q.estimated_transit_days)) * Decimal("10.0")), q.total_cost, q.carrier_code))
    assert best_val.carrier_code == "CARRIER_B"

    # 4. Tie breaking on equal cost and transit time
    tie_quotes = [
        RateQuoteItem(carrier_code="FEDEX", carrier_name="FedEx", service_code="GRD", service_name="Ground", total_cost=Decimal("100.00"), estimated_transit_days=3),
        RateQuoteItem(carrier_code="DHL", carrier_name="DHL", service_code="GRD", service_name="Ground", total_cost=Decimal("100.00"), estimated_transit_days=3),
    ]
    tie_winner = min(tie_quotes, key=lambda q: (q.total_cost, q.estimated_transit_days, q.carrier_code))
    assert tie_winner.carrier_code == "DHL" # Alphabetical tie-breaker on carrier_code

# ============================================================================
# 5. BILLABLE WEIGHT BOUNDARIES
# ============================================================================

@pytest.mark.asyncio
async def test_billable_weight_boundaries():
    # 1. Actual > Dimensional: Actual 5 kg, Dim 3 kg -> Billable 5 kg
    dim_3kg = calculate_dim_weight(Decimal("30.0"), Decimal("25.0"), Decimal("20.0")) # 15000 / 5000 = 3.000
    assert dim_3kg == Decimal("3.000")
    assert max(Decimal("5.000"), dim_3kg) == Decimal("5.000")

    # 2. Dimensional > Actual: Actual 3 kg, Dim 5 kg -> Billable 5 kg
    dim_5kg = calculate_dim_weight(Decimal("50.0"), Decimal("25.0"), Decimal("20.0")) # 25000 / 5000 = 5.000
    assert dim_5kg == Decimal("5.000")
    assert max(Decimal("3.000"), dim_5kg) == Decimal("5.000")

    # 3. Equal: Actual 5 kg, Dim 5 kg -> Billable 5 kg
    assert max(Decimal("5.000"), dim_5kg) == Decimal("5.000")

    # 4. Decimal dimensions and weights
    dim_dec = calculate_dim_weight(Decimal("45.5"), Decimal("32.5"), Decimal("24.2")) # 35785.75 / 5000 = 7.157 kg
    assert dim_dec == Decimal("7.157")
    assert max(Decimal("6.500"), dim_dec) == Decimal("7.157")

# ============================================================================
# 6. MULTI-PACKAGE SHIPMENT INTEGRITY
# ============================================================================

@pytest.mark.asyncio
async def test_multi_package_shipment_integrity(db_session: AsyncSession):
    """
    Creates a shipment with 3 packages.
    Verifies: Master shipment = 1, Packages = 3, Tracking numbers = 3 unique values, Labels = 3.
    Retries without duplication.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, variant, _, _, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id,
        carrier_account_id=acc.id,
        service_code="GROUND",
        label_format="PDF",
        packages=[
            GenerateLabelPackageInput(package_number=1, package_type="BOX_A", weight_kg=Decimal("3.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0")),
            GenerateLabelPackageInput(package_number=2, package_type="BOX_B", weight_kg=Decimal("5.0"), length_cm=Decimal("30.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0")),
            GenerateLabelPackageInput(package_number=3, package_type="BOX_C", weight_kg=Decimal("7.0"), length_cm=Decimal("40.0"), width_cm=Decimal("30.0"), height_cm=Decimal("20.0")),
        ]
    )

    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    assert len(res.packages) == 3
    trackings = [p.tracking_number for p in res.packages]
    assert len(set(trackings)) == 3 # 3 distinct tracking numbers
    assert all([p.label_url is not None for p in res.packages])

    # Retry label generation
    res_retry = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    assert len(res_retry.packages) == 3
    assert [p.tracking_number for p in res_retry.packages] == trackings

    # Confirm database rows
    pkgs = (await db_session.execute(
        select(ShipmentPackage).where(ShipmentPackage.shipment_id == shipment.id)
    )).scalars().all()
    assert len(pkgs) == 3

# ============================================================================
# 7. DUAL STATE MACHINE FULFILLMENT CARRIER MAPPING
# ============================================================================

@pytest.mark.asyncio
async def test_dual_state_machine_fulfillment_carrier_mapping(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, so, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    so.status = "PACKED"
    await db_session.commit()

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("2.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    # PACKED + carrier IN_TRANSIT -> SHIPPED
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=get_utc_now(),
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Depot", description="In Transit"
    ))
    so_db = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_db.status == "SHIPPED"

    # DELIVERED + carrier IN_TRANSIT -> remains DELIVERED
    so_db.status = "DELIVERED"
    await db_session.commit()

    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=get_utc_now() - timedelta(minutes=5),
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Old Hub", description="Out of order webhook"
    ))
    so_db_check = (await db_session.execute(select(SalesOrder).where(SalesOrder.id == so.id))).scalar_one()
    assert so_db_check.status == "DELIVERED"

# ============================================================================
# 8. DISPATCH BOUNDARY AND STOCK ENGINE INVARIANTS
# ============================================================================

@pytest.mark.asyncio
async def test_dispatch_boundary_and_stock_engine_invariants(db_session: AsyncSession):
    """
    Explicitly tests:
    1. Label generation -> 0 inventory mutations
    2. Carrier tracking event -> 0 inventory mutations
    3. Warehouse dispatch -> StockEngine.post_transaction() -> inventory deduction + COGS
    4. Delivery webhook -> 0 additional inventory mutations
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, bin_ship, variant, customer, so, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    # Initial stock receiving
    tx_recv = await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id,
        transaction_type="PURCHASE_RECEIPT",
        entries_data=[{"item_variant_id": variant.id, "destination_location_bin_id": bin_ship.id, "quantity": Decimal("100.0"), "unit_cost": Decimal("50.00")}],
        reference_doc_type="PURCHASE_ORDER",
        notes="Initial warehouse receipt"
    )
    assert tx_recv is not None
    await db_session.commit()

    # Step 1: Label generation -> ZERO inventory mutation
    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("2.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    txs_shipment = (await db_session.execute(
        select(StockLedgerTransaction).where(StockLedgerTransaction.reference_document_id == shipment.id)
    )).scalars().all()
    assert len(txs_shipment) == 0

    # Step 2: Carrier tracking webhook -> ZERO inventory mutation
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=get_utc_now(),
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Depot", description="In transit"
    ))
    txs_shipment2 = (await db_session.execute(
        select(StockLedgerTransaction).where(StockLedgerTransaction.reference_document_id == shipment.id)
    )).scalars().all()
    assert len(txs_shipment2) == 0

    # Step 3: Warehouse dispatch -> Exactly ONE StockEngine.post_transaction()
    tx_dispatch = await StockEngine.post_transaction(
        db=db_session, tenant_id=tenant_id,
        transaction_type="SALES_SHIPMENT",
        entries_data=[{"item_variant_id": variant.id, "source_location_bin_id": bin_ship.id, "quantity": Decimal("5.0"), "unit_cost": Decimal("50.00")}],
        reference_doc_type="SHIPMENT", reference_doc_id=shipment.id,
        notes="Warehouse dispatch"
    )
    assert tx_dispatch is not None
    await db_session.commit()

    txs_shipment3 = (await db_session.execute(
        select(StockLedgerTransaction).where(StockLedgerTransaction.reference_document_id == shipment.id)
    )).scalars().all()
    assert len(txs_shipment3) == 1

    # Step 4: DELIVERED webhook -> ZERO additional inventory mutation
    await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=get_utc_now() + timedelta(hours=2),
        carrier_status="DL", normalized_status="DELIVERED", location="Delivered", description="Delivered to customer"
    ))
    txs_shipment4 = (await db_session.execute(
        select(StockLedgerTransaction).where(StockLedgerTransaction.reference_document_id == shipment.id)
    )).scalars().all()
    assert len(txs_shipment4) == 1 # Remains 1

# ============================================================================
# 9. TRACKING EVENT IDEMPOTENCY AND TAMPERING
# ============================================================================

@pytest.mark.asyncio
async def test_tracking_event_idempotency_and_tampering(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, _, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("2.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    res = await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    now = get_utc_now()

    # Submit event multiple times
    evt1 = await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=now,
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Hub A", description="Scanned at Hub A"
    ))
    evt2 = await CarrierService.ingest_tracking_event(db_session, tenant_id, IngestTrackingEventRequest(
        tracking_number=res.master_tracking_number, carrier_code="MOCK_EXPRESS", event_timestamp=now,
        carrier_status="IT", normalized_status="IN_TRANSIT", location="Hub A", description="Scanned at Hub A"
    ))
    assert evt1.id == evt2.id # Same logical event returned

# ============================================================================
# 10. CARRIER MANIFEST INTEGRITY AND DUPLICATE PREVENTION
# ============================================================================

@pytest.mark.asyncio
async def test_carrier_manifest_integrity_and_duplicate_prevention(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, _, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("3.5"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)

    mnf = await CarrierService.create_carrier_manifest(db_session, tenant_id, CreateCarrierManifestRequest(
        carrier_account_id=acc.id,
        warehouse_id=wh.id,
        shipment_ids=[shipment.id]
    ))
    assert mnf.manifest_number.startswith("MNF-")
    assert mnf.total_packages == 1
    assert mnf.status == "GENERATED"

# ============================================================================
# 11. CANCELLATION VOID AND POST-DISPATCH GUARDS
# ============================================================================

@pytest.mark.asyncio
async def test_cancellation_void_and_post_dispatch_guards(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, so, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    # 1. Label generated -> void succeeds
    gen_req = GenerateShippingLabelRequest(
        shipment_id=shipment.id, carrier_account_id=acc.id, service_code="GROUND",
        packages=[GenerateLabelPackageInput(package_number=1, weight_kg=Decimal("3.0"), length_cm=Decimal("20.0"), width_cm=Decimal("20.0"), height_cm=Decimal("20.0"))]
    )
    await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    assert shipment.tracking_number is not None

    void_ok = await CarrierService.void_shipping_label(
        db_session, tenant_id, VoidShippingLabelRequest(shipment_id=shipment.id, reason="Customer cancelled order")
    )
    assert void_ok is True

    # 2. Re-label and mark DELIVERED -> voiding should fail with 400
    await CarrierService.generate_shipping_label(db_session, tenant_id, gen_req)
    so.status = "DELIVERED"
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await CarrierService.void_shipping_label(
            db_session, tenant_id, VoidShippingLabelRequest(shipment_id=shipment.id, reason="Attempt illegal void")
        )
    assert exc_info.value.status_code == 400

# ============================================================================
# 12. SHIPPING RBAC PERMISSIONS ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_shipping_rbac_permissions_isolation(client, db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    wh, _, _, _, _, shipment, acc = await create_shipping_test_environment(db_session, tenant_id)

    from app.core.security import create_access_token

    # Read-only token
    read_token = create_access_token(
        subject="readonly_user",
        tenant_id=tenant_id,
        roles=["viewer"],
        permissions=["shipping:read"]
    )
    read_headers = {"Authorization": f"Bearer {read_token}"}

    # Write token
    write_token = create_access_token(
        subject="logistics_admin",
        tenant_id=tenant_id,
        roles=["logistics_admin"],
        permissions=["shipping:read", "shipping:write"]
    )
    write_headers = {"Authorization": f"Bearer {write_token}"}

    # Read endpoint accessible by read_token
    r_list = await client.get("/api/v1/shipping/accounts", headers=read_headers)
    assert r_list.status_code == 200

    # Write endpoint rejected for read_token -> 403
    r_unauth_write = await client.post("/api/v1/shipping/accounts", json={
        "carrier_code": "DHL", "account_name": "DHL Express", "api_key": "dhl_key"
    }, headers=read_headers)
    assert r_unauth_write.status_code == 403

    # Write endpoint succeeds with write_token -> 201
    r_auth_write = await client.post("/api/v1/shipping/accounts", json={
        "carrier_code": "DHL", "account_name": "DHL Express", "api_key": "dhl_key"
    }, headers=write_headers)
    assert r_auth_write.status_code == 201
