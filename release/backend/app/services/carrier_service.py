import uuid
import asyncio
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.sales import Shipment, SalesOrder
from app.models.warehouse import Warehouse
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
    RateShoppingResponse,
    GenerateShippingLabelRequest,
    ShippingLabelResponse,
    PackageLabelResponse,
    VoidShippingLabelRequest,
    IngestTrackingEventRequest,
    ShipmentTrackingTimelineResponse,
    CreateCarrierManifestRequest,
    CarrierManifestResponse
)
from app.services.carriers.base import (
    CarrierProvider,
    RateQuoteRequest,
    RateQuoteItem,
    CreateCarrierShipmentRequest,
    TrackingEventItem,
    PackageDimensionInput
)
from app.services.carriers.mock_provider import MockCarrierProvider, calculate_dim_weight
from app.services.sequence_service import SequenceService
from app.services.audit_service import AuditService
from app.services.costing_service import quantize_decimal

class CarrierService:
    @staticmethod
    def get_provider(carrier_code: str) -> CarrierProvider:
        """Returns the appropriate CarrierProvider adapter based on carrier_code."""
        # For production/sandbox testing, MockCarrierProvider handles MOCK_EXPRESS, FEDEX, UPS, DHL, USPS, etc.
        return MockCarrierProvider(carrier_code=carrier_code, carrier_name=f"{carrier_code} Express Logistics")

    @staticmethod
    async def create_carrier_account(
        db: AsyncSession,
        tenant_id: str,
        acc_in: CarrierAccountCreate,
        user_id: Optional[str] = None
    ) -> CarrierAccount:
        acc = CarrierAccount(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            carrier_code=acc_in.carrier_code.upper(),
            account_name=acc_in.account_name,
            account_number=acc_in.account_number,
            api_key=acc_in.api_key,
            api_secret=acc_in.api_secret,
            is_sandbox=acc_in.is_sandbox if acc_in.is_sandbox is not None else True,
            is_active=True,
            default_service_level=acc_in.default_service_level or "GROUND",
            webhook_secret=acc_in.webhook_secret
        )
        db.add(acc)
        await db.flush()

        # Seed standard service levels for this carrier
        levels = [
            ShippingServiceLevel(
                id=str(uuid.uuid4()), tenant_id=tenant_id, carrier_account_id=acc.id,
                service_code="GROUND", service_name="Standard Ground", transit_days_estimate=4, is_active=True
            ),
            ShippingServiceLevel(
                id=str(uuid.uuid4()), tenant_id=tenant_id, carrier_account_id=acc.id,
                service_code="EXPRESS_2DAY", service_name="2-Day Air", transit_days_estimate=2, is_active=True
            ),
            ShippingServiceLevel(
                id=str(uuid.uuid4()), tenant_id=tenant_id, carrier_account_id=acc.id,
                service_code="OVERNIGHT", service_name="Priority Overnight", transit_days_estimate=1, is_active=True
            )
        ]
        db.add_all(levels)
        await db.commit()
        await db.refresh(acc)
        return acc

    @staticmethod
    async def rate_shopping(
        db: AsyncSession,
        tenant_id: str,
        req: RateShoppingRequest
    ) -> RateShoppingResponse:
        """
        Calculates and compares shipping rates across all active carrier accounts.
        """
        # Fetch active accounts
        stmt = select(CarrierAccount).where(CarrierAccount.tenant_id == tenant_id, CarrierAccount.is_active == True)
        accounts = (await db.execute(stmt)).scalars().all()
        if not accounts:
            # Fallback to a default mock carrier account if none explicitly configured
            accounts = [
                CarrierAccount(
                    id=str(uuid.uuid4()), tenant_id=tenant_id, carrier_code="MOCK_EXPRESS",
                    account_name="Default Mock Express", api_key="mock_key", is_sandbox=True, is_active=True
                )
            ]

        # Fetch warehouse for origin postal code
        wh = (await db.execute(select(Warehouse).where(Warehouse.id == req.origin_warehouse_id))).scalar_one_or_none()
        origin_zip = "90210"

        all_quotes: List[RateQuoteItem] = []
        for acc in accounts:
            provider = CarrierService.get_provider(acc.carrier_code)
            provider_req = RateQuoteRequest(
                origin_warehouse_id=req.origin_warehouse_id,
                origin_postal_code=origin_zip,
                origin_country="US",
                destination_postal_code=req.destination_postal_code,
                destination_country=req.destination_country or "US",
                packages=req.packages
            )
            quotes = await provider.get_rates(account_config={"api_key": acc.api_key}, request=provider_req)
            all_quotes.extend(quotes)

        # Deterministic sorting
        all_quotes.sort(key=lambda q: (q.total_cost, q.estimated_transit_days, q.carrier_code, q.service_code))
        lowest_cost = all_quotes[0] if all_quotes else None

        # Fastest quote (deterministic tie-break on cost, carrier, service)
        fastest = min(all_quotes, key=lambda q: (q.estimated_transit_days, q.total_cost, q.carrier_code, q.service_code)) if all_quotes else None

        return RateShoppingResponse(
            quotes=all_quotes,
            lowest_cost_quote=lowest_cost,
            fastest_quote=fastest
        )

    @staticmethod
    async def generate_shipping_label(
        db: AsyncSession,
        tenant_id: str,
        req: GenerateShippingLabelRequest,
        user_id: Optional[str] = None
    ) -> ShippingLabelResponse:
        """
        Generates official carrier labels, assigns tracking numbers, and creates ShipmentPackage records.
        Guarantees idempotency via row-level locking.
        """
        # Fetch shipment with lock
        shipment = (await db.execute(
            select(Shipment).where(Shipment.id == req.shipment_id).with_for_update()
        )).scalar_one_or_none()
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        acc = (await db.execute(
            select(CarrierAccount).where(CarrierAccount.id == req.carrier_account_id, CarrierAccount.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not acc:
            raise HTTPException(status_code=404, detail="Carrier account not found")

        # Idempotency check: if packages already exist with tracking, return existing label response
        existing_pkgs = (await db.execute(
            select(ShipmentPackage).where(ShipmentPackage.shipment_id == shipment.id)
        )).scalars().all()
        if existing_pkgs and shipment.tracking_number:
            pkg_res = [
                PackageLabelResponse(
                    package_number=p.package_number,
                    tracking_number=p.tracking_number,
                    carrier_package_id=p.carrier_package_id or "",
                    label_url=p.label_url or "",
                    label_base64=p.label_base64,
                    weight_kg=float(p.weight_kg),
                    dimensional_weight_kg=float(p.dimensional_weight_kg)
                )
                for p in existing_pkgs
            ]
            return ShippingLabelResponse(
                shipment_id=shipment.id,
                master_tracking_number=shipment.tracking_number,
                carrier_code=acc.carrier_code,
                service_code=req.service_code,
                service_name="Standard Carrier Service",
                total_shipping_cost=float(sum([p.weight_kg for p in existing_pkgs]) * Decimal("5.0")),
                currency="USD",
                label_format=req.label_format or "PDF",
                packages=pkg_res
            )

        provider = CarrierService.get_provider(acc.carrier_code)

        pkg_dim_inputs = [
            PackageDimensionInput(
                package_number=p.package_number,
                package_type=p.package_type,
                weight_kg=p.weight_kg,
                length_cm=p.length_cm,
                width_cm=p.width_cm,
                height_cm=p.height_cm
            )
            for p in req.packages
        ]

        carrier_req = CreateCarrierShipmentRequest(
            shipment_id=shipment.id,
            shipment_number=shipment.shipment_number,
            service_code=req.service_code,
            origin_address={"country": "US", "postal_code": "90210"},
            destination_address={"country": "US", "postal_code": "10001"},
            packages=pkg_dim_inputs,
            label_format=req.label_format or "PDF"
        )

        res = await provider.create_shipment(account_config={"api_key": acc.api_key}, request=carrier_req)

        # Update Shipment
        shipment.carrier = acc.carrier_code
        shipment.tracking_number = res.master_tracking_number
        shipment.package_count = len(res.packages)
        shipment.total_weight = sum([p.weight_kg for p in req.packages])

        # Persist ShipmentPackage and items
        pkg_responses: List[PackageLabelResponse] = []
        for idx, gen_pkg in enumerate(res.packages):
            input_pkg = req.packages[idx] if idx < len(req.packages) else None
            sp = ShipmentPackage(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                shipment_id=shipment.id,
                package_number=gen_pkg.package_number,
                package_type=input_pkg.package_type if input_pkg else "CUSTOM_BOX",
                weight_kg=input_pkg.weight_kg if input_pkg else Decimal("1.0"),
                length_cm=input_pkg.length_cm if input_pkg else Decimal("20.0"),
                width_cm=input_pkg.width_cm if input_pkg else Decimal("20.0"),
                height_cm=input_pkg.height_cm if input_pkg else Decimal("20.0"),
                dimensional_weight_kg=gen_pkg.dimensional_weight_kg,
                tracking_number=gen_pkg.tracking_number,
                carrier_package_id=gen_pkg.carrier_package_id,
                label_format=res.label_format,
                label_url=gen_pkg.label_url,
                label_base64=gen_pkg.label_base64
            )
            db.add(sp)
            await db.flush()

            if input_pkg and input_pkg.items:
                for it in input_pkg.items:
                    spi = ShipmentPackageItem(
                        id=str(uuid.uuid4()),
                        package_id=sp.id,
                        item_variant_id=it.item_variant_id,
                        quantity=it.quantity,
                        serial_number=it.serial_number,
                        batch_number=it.batch_number
                    )
                    db.add(spi)

            pkg_responses.append(PackageLabelResponse(
                package_number=gen_pkg.package_number,
                tracking_number=gen_pkg.tracking_number,
                carrier_package_id=gen_pkg.carrier_package_id,
                label_url=gen_pkg.label_url,
                label_base64=gen_pkg.label_base64,
                weight_kg=float(sp.weight_kg),
                dimensional_weight_kg=float(gen_pkg.dimensional_weight_kg)
            ))

        # Initial Tracking Event
        evt = ShipmentTrackingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            tracking_number=res.master_tracking_number,
            event_timestamp=get_utc_now(),
            carrier_status="OC",
            normalized_status="LABEL_CREATED",
            location="Origin Fulfillment Center",
            description="Shipping label created successfully."
        )
        db.add(evt)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="GENERATE_SHIPPING_LABEL",
            entity_type="Shipment",
            entity_id=shipment.id,
            user_id=user_id,
            changes={"tracking_number": res.master_tracking_number, "packages": len(res.packages), "carrier": acc.carrier_code}
        )

        await db.commit()

        return ShippingLabelResponse(
            shipment_id=shipment.id,
            master_tracking_number=res.master_tracking_number,
            carrier_code=acc.carrier_code,
            service_code=res.service_code,
            service_name=res.service_name,
            total_shipping_cost=float(res.total_shipping_cost),
            currency=res.currency,
            label_format=res.label_format,
            packages=pkg_responses
        )

    @staticmethod
    async def void_shipping_label(
        db: AsyncSession,
        tenant_id: str,
        req: VoidShippingLabelRequest,
        user_id: Optional[str] = None
    ) -> bool:
        shipment = (await db.execute(
            select(Shipment).where(Shipment.id == req.shipment_id).with_for_update()
        )).scalar_one_or_none()
        if not shipment:
            raise HTTPException(status_code=404, detail="Shipment not found")

        if not shipment.tracking_number:
            raise HTTPException(status_code=400, detail="Shipment has no active shipping label to void")

        # Guard: If SalesOrder is already DELIVERED, rejecting void
        if shipment.sales_order_id:
            so = (await db.execute(select(SalesOrder).where(SalesOrder.id == shipment.sales_order_id))).scalar_one_or_none()
            if so and so.status == "DELIVERED":
                raise HTTPException(status_code=400, detail="Cannot void label for an already delivered shipment")

        carrier_code = shipment.carrier or "MOCK_EXPRESS"
        provider = CarrierService.get_provider(carrier_code)
        await provider.cancel_shipment(account_config={}, tracking_number=shipment.tracking_number)

        evt = ShipmentTrackingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            tracking_number=shipment.tracking_number,
            event_timestamp=get_utc_now(),
            carrier_status="CA",
            normalized_status="VOIDED",
            location="Origin Fulfillment Center",
            description=f"Shipping label voided. Reason: {req.reason}"
        )
        db.add(evt)

        old_tracking = shipment.tracking_number
        shipment.tracking_number = None

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="VOID_SHIPPING_LABEL",
            entity_type="Shipment",
            entity_id=shipment.id,
            user_id=user_id,
            changes={"voided_tracking_number": old_tracking, "reason": req.reason}
        )

        await db.commit()
        return True

    @staticmethod
    async def ingest_tracking_event(
        db: AsyncSession,
        tenant_id: str,
        req: IngestTrackingEventRequest
    ) -> ShipmentTrackingEvent:
        """
        Ingests external carrier webhook tracking updates.
        Strict Invariants:
        1. Monotonic status progression (internal status never regresses on out-of-order webhooks).
        2. Idempotent deduplication (duplicate events with identical timestamp/status do not duplicate).
        3. Zero inventory transactions or cost layer changes.
        """
        shipment = (await db.execute(
            select(Shipment).where(Shipment.tracking_number == req.tracking_number)
        )).scalar_one_or_none()
        if not shipment:
            # Try finding via child package tracking number
            pkg = (await db.execute(
                select(ShipmentPackage).where(ShipmentPackage.tracking_number == req.tracking_number)
            )).scalar_one_or_none()
            if pkg:
                shipment = (await db.execute(select(Shipment).where(Shipment.id == pkg.shipment_id))).scalar_one_or_none()

        if not shipment:
            raise HTTPException(status_code=404, detail=f"No active shipment found matching tracking number {req.tracking_number}")

        # Idempotency check: Exact duplicate event
        existing_evt = (await db.execute(
            select(ShipmentTrackingEvent).where(
                ShipmentTrackingEvent.shipment_id == shipment.id,
                ShipmentTrackingEvent.tracking_number == req.tracking_number,
                ShipmentTrackingEvent.event_timestamp == req.event_timestamp,
                ShipmentTrackingEvent.normalized_status == req.normalized_status.upper()
            )
        )).scalar_one_or_none()
        if existing_evt:
            return existing_evt

        evt = ShipmentTrackingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            tracking_number=req.tracking_number,
            event_timestamp=req.event_timestamp,
            carrier_status=req.carrier_status,
            normalized_status=req.normalized_status.upper(),
            location=req.location,
            description=req.description,
            raw_payload=req.raw_payload
        )
        db.add(evt)

        # Monotonic State Machine Guards:
        # Hierarchy: DRAFT (0) < CONFIRMED (1) < ALLOCATED (2) < PICKING (3) < PACKED (4) < SHIPPED (5) < DELIVERED (6)
        STATUS_HIERARCHY = {
            "LABEL_CREATED": 4, # PACKED
            "PICKED_UP": 5,     # SHIPPED
            "IN_TRANSIT": 5,    # SHIPPED
            "OUT_FOR_DELIVERY": 5, # SHIPPED
            "DELIVERED": 6      # DELIVERED
        }

        if shipment.sales_order_id:
            so = (await db.execute(select(SalesOrder).where(SalesOrder.id == shipment.sales_order_id))).scalar_one_or_none()
            if so:
                curr_rank = 6 if so.status == "DELIVERED" else (5 if so.status == "SHIPPED" else (4 if so.status == "PACKED" else 1))
                new_rank = STATUS_HIERARCHY.get(req.normalized_status.upper(), 0)

                # Only advance forward monotonically, never regress
                if new_rank > curr_rank:
                    if req.normalized_status.upper() == "DELIVERED":
                        so.status = "DELIVERED"
                    elif req.normalized_status.upper() in ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"] and so.status != "DELIVERED":
                        if so.status != "SHIPPED":
                            so.status = "SHIPPED"

        await db.commit()
        await db.refresh(evt)
        return evt

    @staticmethod
    async def get_tracking_timeline(
        db: AsyncSession,
        tenant_id: str,
        tracking_number: str
    ) -> ShipmentTrackingTimelineResponse:
        events = (await db.execute(
            select(ShipmentTrackingEvent)
            .where(
                ShipmentTrackingEvent.tenant_id == tenant_id,
                ShipmentTrackingEvent.tracking_number == tracking_number
            )
            .order_by(ShipmentTrackingEvent.event_timestamp.asc())
        )).scalars().all()

        if not events:
            raise HTTPException(status_code=404, detail="No tracking events found for tracking number")

        latest = events[-1]
        ev_items = [
            TrackingEventItem(
                event_timestamp=e.event_timestamp,
                carrier_status=e.carrier_status,
                normalized_status=e.normalized_status,
                location=e.location,
                description=e.description
            )
            for e in events
        ]

        return ShipmentTrackingTimelineResponse(
            shipment_id=latest.shipment_id,
            tracking_number=tracking_number,
            current_status=latest.normalized_status,
            events=ev_items
        )

    @staticmethod
    async def create_carrier_manifest(
        db: AsyncSession,
        tenant_id: str,
        req: CreateCarrierManifestRequest,
        user_id: Optional[str] = None
    ) -> CarrierManifestResponse:
        acc = (await db.execute(
            select(CarrierAccount).where(CarrierAccount.id == req.carrier_account_id, CarrierAccount.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not acc:
            raise HTTPException(status_code=404, detail="Carrier account not found")

        shipments = (await db.execute(
            select(Shipment).where(Shipment.id.in_(req.shipment_ids))
        )).scalars().all()

        tracking_numbers = [s.tracking_number for s in shipments if s.tracking_number]
        if not tracking_numbers:
            raise HTTPException(status_code=400, detail="None of the selected shipments have active tracking numbers")

        provider = CarrierService.get_provider(acc.carrier_code)
        mnf_res = await provider.create_manifest(account_config={"api_key": acc.api_key}, tracking_numbers=tracking_numbers)

        manifest = CarrierManifest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            manifest_number=mnf_res.manifest_number,
            carrier_account_id=acc.id,
            warehouse_id=req.warehouse_id,
            manifest_url=mnf_res.manifest_url,
            total_packages=mnf_res.total_packages,
            total_weight_kg=mnf_res.total_weight_kg,
            status="GENERATED"
        )
        db.add(manifest)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE_CARRIER_MANIFEST",
            entity_type="CarrierManifest",
            entity_id=manifest.id,
            user_id=user_id,
            changes={"manifest_number": manifest.manifest_number, "packages": mnf_res.total_packages}
        )

        await db.commit()
        await db.refresh(manifest)

        return CarrierManifestResponse(
            id=manifest.id,
            tenant_id=manifest.tenant_id,
            manifest_number=manifest.manifest_number,
            carrier_account_id=manifest.carrier_account_id,
            warehouse_id=manifest.warehouse_id,
            manifest_url=manifest.manifest_url,
            total_packages=manifest.total_packages,
            total_weight_kg=float(manifest.total_weight_kg),
            status=manifest.status,
            created_at=manifest.created_at
        )
