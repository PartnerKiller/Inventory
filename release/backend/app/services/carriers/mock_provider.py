import uuid
from decimal import Decimal
from typing import List, Dict, Any
from datetime import datetime, timedelta
from app.models.base import get_utc_now
from app.services.carriers.base import (
    CarrierProvider,
    RateQuoteRequest,
    RateQuoteItem,
    CreateCarrierShipmentRequest,
    CarrierShipmentResult,
    GeneratedPackageLabel,
    TrackingDetailsResponse,
    TrackingEventItem,
    ManifestResult
)

def calculate_dim_weight(length_cm: Decimal, width_cm: Decimal, height_cm: Decimal) -> Decimal:
    """Standard IATA dimensional weight divisor: L x W x H / 5000"""
    vol = length_cm * width_cm * height_cm
    return (vol / Decimal("5000.0")).quantize(Decimal("0.001"))

class MockCarrierProvider(CarrierProvider):
    def __init__(self, carrier_code: str = "MOCK_EXPRESS", carrier_name: str = "Mock Express Logistics"):
        self.carrier_code = carrier_code
        self.carrier_name = carrier_name

    async def get_rates(self, account_config: Dict[str, Any], request: RateQuoteRequest) -> List[RateQuoteItem]:
        total_billable_weight = Decimal("0.0")
        for pkg in request.packages:
            dim_w = calculate_dim_weight(pkg.length_cm, pkg.width_cm, pkg.height_cm)
            billable = max(pkg.weight_kg, dim_w)
            total_billable_weight += billable

        base_rate = total_billable_weight * Decimal("5.00")

        return [
            RateQuoteItem(
                carrier_code=self.carrier_code,
                carrier_name=self.carrier_name,
                service_code="GROUND",
                service_name="Standard Ground",
                total_cost=max(Decimal("15.00"), base_rate).quantize(Decimal("0.01")),
                currency="USD",
                estimated_transit_days=4,
                is_guaranteed=False
            ),
            RateQuoteItem(
                carrier_code=self.carrier_code,
                carrier_name=self.carrier_name,
                service_code="EXPRESS_2DAY",
                service_name="2-Day Air",
                total_cost=max(Decimal("28.00"), base_rate * Decimal("1.80")).quantize(Decimal("0.01")),
                currency="USD",
                estimated_transit_days=2,
                is_guaranteed=True
            ),
            RateQuoteItem(
                carrier_code=self.carrier_code,
                carrier_name=self.carrier_name,
                service_code="OVERNIGHT",
                service_name="Priority Overnight",
                total_cost=max(Decimal("45.00"), base_rate * Decimal("2.80")).quantize(Decimal("0.01")),
                currency="USD",
                estimated_transit_days=1,
                is_guaranteed=True
            )
        ]

    async def create_shipment(self, account_config: Dict[str, Any], request: CreateCarrierShipmentRequest) -> CarrierShipmentResult:
        master_tracking = f"{self.carrier_code[:4]}-{uuid.uuid4().hex[:10].upper()}"
        generated_pkgs: List[GeneratedPackageLabel] = []
        total_cost = Decimal("0.0")

        for idx, pkg in enumerate(request.packages, start=1):
            dim_w = calculate_dim_weight(pkg.length_cm, pkg.width_cm, pkg.height_cm)
            pkg_tracking = f"{master_tracking}-{idx}" if len(request.packages) > 1 else master_tracking
            pkg_cost = max(pkg.weight_kg, dim_w) * Decimal("5.00")
            total_cost += pkg_cost

            # Mock printable label URL
            label_url = f"https://labels.mockcarrier.com/v1/{pkg_tracking}.{request.label_format.lower()}"
            label_base64 = f"JVBERi0xLjQKJ_MOCK_LABEL_CONTENT_{pkg_tracking}"

            generated_pkgs.append(GeneratedPackageLabel(
                package_number=pkg.package_number,
                tracking_number=pkg_tracking,
                carrier_package_id=f"PKG-{uuid.uuid4().hex[:8]}",
                label_url=label_url,
                label_base64=label_base64,
                dimensional_weight_kg=dim_w
            ))

        service_name = "Standard Ground"
        if request.service_code == "EXPRESS_2DAY":
            service_name = "2-Day Air"
            total_cost = total_cost * Decimal("1.80")
        elif request.service_code == "OVERNIGHT":
            service_name = "Priority Overnight"
            total_cost = total_cost * Decimal("2.80")

        return CarrierShipmentResult(
            master_tracking_number=master_tracking,
            carrier_shipment_id=f"CSHIP-{uuid.uuid4().hex[:8]}",
            service_code=request.service_code,
            service_name=service_name,
            total_shipping_cost=max(Decimal("15.00"), total_cost).quantize(Decimal("0.01")),
            currency="USD",
            label_format=request.label_format,
            packages=generated_pkgs
        )

    async def cancel_shipment(self, account_config: Dict[str, Any], tracking_number: str) -> bool:
        # Mock cancel always succeeds
        return True

    async def track_shipment(self, account_config: Dict[str, Any], tracking_number: str) -> TrackingDetailsResponse:
        now = get_utc_now()
        return TrackingDetailsResponse(
            tracking_number=tracking_number,
            carrier_code=self.carrier_code,
            current_status="IN_TRANSIT",
            estimated_delivery_at=now + timedelta(days=2),
            events=[
                TrackingEventItem(
                    event_timestamp=now - timedelta(hours=12),
                    carrier_status="OC",
                    normalized_status="LABEL_CREATED",
                    location="Origin Hub",
                    description="Shipping label created, awaiting package pickup."
                ),
                TrackingEventItem(
                    event_timestamp=now - timedelta(hours=6),
                    carrier_status="PU",
                    normalized_status="PICKED_UP",
                    location="Origin Hub",
                    description="Package picked up by carrier driver."
                ),
                TrackingEventItem(
                    event_timestamp=now - timedelta(hours=2),
                    carrier_status="IT",
                    normalized_status="IN_TRANSIT",
                    location="Sort Facility",
                    description="Package scanned at sorting center."
                )
            ]
        )

    async def create_manifest(self, account_config: Dict[str, Any], tracking_numbers: List[str]) -> ManifestResult:
        mnf_num = f"MNF-{get_utc_now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        return ManifestResult(
            manifest_id=str(uuid.uuid4()),
            manifest_number=mnf_num,
            manifest_url=f"https://manifests.mockcarrier.com/v1/{mnf_num}.pdf",
            total_packages=len(tracking_numbers),
            total_weight_kg=Decimal(str(len(tracking_numbers) * 2.5))
        )
