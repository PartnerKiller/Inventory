from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from app.services.carriers.base import PackageDimensionInput, RateQuoteItem, TrackingEventItem

class CarrierAccountCreate(BaseModel):
    carrier_code: str
    account_name: str
    account_number: Optional[str] = None
    api_key: str
    api_secret: Optional[str] = None
    is_sandbox: Optional[bool] = True
    default_service_level: Optional[str] = "GROUND"
    webhook_secret: Optional[str] = None

class CarrierAccountResponse(BaseModel):
    id: str
    tenant_id: str
    carrier_code: str
    account_name: str
    account_number: Optional[str] = None
    is_sandbox: bool
    is_active: bool
    default_service_level: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RateShoppingRequest(BaseModel):
    shipment_id: Optional[str] = None
    origin_warehouse_id: str
    destination_postal_code: str
    destination_country: Optional[str] = "US"
    packages: List[PackageDimensionInput]

class RateShoppingResponse(BaseModel):
    quotes: List[RateQuoteItem]
    lowest_cost_quote: Optional[RateQuoteItem] = None
    fastest_quote: Optional[RateQuoteItem] = None

class GenerateLabelPackageItemInput(BaseModel):
    item_variant_id: str
    quantity: Decimal
    serial_number: Optional[str] = None
    batch_number: Optional[str] = None

class GenerateLabelPackageInput(BaseModel):
    package_number: int = 1
    package_type: str = "CUSTOM_BOX"
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    items: List[GenerateLabelPackageItemInput] = []

class GenerateShippingLabelRequest(BaseModel):
    shipment_id: str
    carrier_account_id: str
    service_code: str
    label_format: Optional[str] = "PDF"
    packages: List[GenerateLabelPackageInput]

class PackageLabelResponse(BaseModel):
    package_number: int
    tracking_number: str
    carrier_package_id: str
    label_url: str
    label_base64: Optional[str] = None
    weight_kg: float
    dimensional_weight_kg: float

class ShippingLabelResponse(BaseModel):
    shipment_id: str
    master_tracking_number: str
    carrier_code: str
    service_code: str
    service_name: str
    total_shipping_cost: float
    currency: str
    label_format: str
    packages: List[PackageLabelResponse]

class VoidShippingLabelRequest(BaseModel):
    shipment_id: str
    reason: Optional[str] = "Shipment cancelled or repacked"

class IngestTrackingEventRequest(BaseModel):
    tracking_number: str
    carrier_code: str
    event_timestamp: datetime
    carrier_status: str
    normalized_status: str # LABEL_CREATED, PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, EXCEPTION, RETURNED
    location: Optional[str] = None
    description: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None

class ShipmentTrackingTimelineResponse(BaseModel):
    shipment_id: str
    tracking_number: str
    carrier_code: Optional[str] = None
    current_status: str
    events: List[TrackingEventItem] = []

class CreateCarrierManifestRequest(BaseModel):
    carrier_account_id: str
    warehouse_id: str
    shipment_ids: List[str]

class CarrierManifestResponse(BaseModel):
    id: str
    tenant_id: str
    manifest_number: str
    carrier_account_id: str
    warehouse_id: str
    manifest_url: Optional[str] = None
    total_packages: int
    total_weight_kg: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
