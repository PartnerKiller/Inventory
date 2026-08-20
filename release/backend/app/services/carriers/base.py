from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime

class PackageDimensionInput(BaseModel):
    package_number: int = 1
    package_type: str = "CUSTOM_BOX"
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal

class RateQuoteRequest(BaseModel):
    origin_warehouse_id: str
    origin_postal_code: str
    origin_country: str = "US"
    destination_postal_code: str
    destination_country: str = "US"
    packages: List[PackageDimensionInput]

class RateQuoteItem(BaseModel):
    carrier_code: str
    carrier_name: str
    service_code: str
    service_name: str
    total_cost: Decimal
    currency: str = "USD"
    estimated_transit_days: int
    is_guaranteed: bool = False

class CreateCarrierShipmentRequest(BaseModel):
    shipment_id: str
    shipment_number: str
    service_code: str
    origin_address: Dict[str, Any]
    destination_address: Dict[str, Any]
    packages: List[PackageDimensionInput]
    label_format: str = "PDF" # PDF, ZPL, PNG

class GeneratedPackageLabel(BaseModel):
    package_number: int
    tracking_number: str
    carrier_package_id: str
    label_url: str
    label_base64: Optional[str] = None
    dimensional_weight_kg: Decimal

class CarrierShipmentResult(BaseModel):
    master_tracking_number: str
    carrier_shipment_id: str
    service_code: str
    service_name: str
    total_shipping_cost: Decimal
    currency: str = "USD"
    label_format: str
    packages: List[GeneratedPackageLabel]

class TrackingEventItem(BaseModel):
    event_timestamp: datetime
    carrier_status: str
    normalized_status: str # LABEL_CREATED, PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, EXCEPTION, RETURNED
    location: Optional[str] = None
    description: Optional[str] = None

class TrackingDetailsResponse(BaseModel):
    tracking_number: str
    carrier_code: str
    current_status: str
    estimated_delivery_at: Optional[datetime] = None
    events: List[TrackingEventItem] = []

class ManifestResult(BaseModel):
    manifest_id: str
    manifest_number: str
    manifest_url: str
    total_packages: int
    total_weight_kg: Decimal

class CarrierProvider(ABC):
    @abstractmethod
    async def get_rates(self, account_config: Dict[str, Any], request: RateQuoteRequest) -> List[RateQuoteItem]:
        pass

    @abstractmethod
    async def create_shipment(self, account_config: Dict[str, Any], request: CreateCarrierShipmentRequest) -> CarrierShipmentResult:
        pass

    @abstractmethod
    async def cancel_shipment(self, account_config: Dict[str, Any], tracking_number: str) -> bool:
        pass

    @abstractmethod
    async def track_shipment(self, account_config: Dict[str, Any], tracking_number: str) -> TrackingDetailsResponse:
        pass

    @abstractmethod
    async def create_manifest(self, account_config: Dict[str, Any], tracking_numbers: List[str]) -> ManifestResult:
        pass
