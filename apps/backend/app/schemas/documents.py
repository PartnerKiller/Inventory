from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime

class DocumentType(str, Enum):
    PURCHASE_ORDER = "PURCHASE_ORDER"
    GOODS_RECEIPT = "GOODS_RECEIPT"
    SALES_ORDER = "SALES_ORDER"
    SALES_INVOICE = "SALES_INVOICE"
    PACKING_SLIP = "PACKING_SLIP"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    STOCK_TRANSFER = "STOCK_TRANSFER"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    SALES_RETURN = "SALES_RETURN"

class DocumentHeader(BaseModel):
    company_name: str
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    company_address: Optional[str] = None
    document_type: DocumentType
    document_title: str
    document_number: str
    date_formatted: str
    status: str
    barcode_value: str

class DocumentParty(BaseModel):
    party_type: str  # "Supplier", "Customer", "Internal Facility"
    name: str
    code: Optional[str] = None
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None

class DocumentFacility(BaseModel):
    warehouse_name: str
    warehouse_code: str
    address: Optional[str] = None
    bin_name: Optional[str] = None

class DocumentLine(BaseModel):
    line_number: int
    item_sku: str
    item_name: str
    variant_name: Optional[str] = None
    bin_location: Optional[str] = None
    quantity: float
    uom: str
    unit_price: Optional[float] = None
    discount: Optional[float] = 0.0
    tax: Optional[float] = 0.0
    subtotal: Optional[float] = None
    notes: Optional[str] = None

class DocumentSummary(BaseModel):
    currency: str
    subtotal: float
    discount_total: float
    tax_total: float
    grand_total: float
    payment_terms: Optional[str] = None
    notes: Optional[str] = None

class DocumentPayload(BaseModel):
    header: DocumentHeader
    party: Optional[DocumentParty] = None
    facility: Optional[DocumentFacility] = None
    destination_facility: Optional[DocumentFacility] = None
    lines: List[DocumentLine] = []
    summary: Optional[DocumentSummary] = None
    metadata: Dict[str, Any] = {}
    footer_text: Optional[str] = "Generated automatically by AuraStock Enterprise Inventory. Authorized System Document."

class BarcodeLabelItem(BaseModel):
    title: str
    sku: str
    variant: Optional[str] = None
    barcode: str
    bin_code: Optional[str] = None
    price_formatted: Optional[str] = None

class BarcodeLabelRequest(BaseModel):
    labels: List[BarcodeLabelItem]
    copies_per_label: int = 1
    layout: str = "sticker"  # "sticker", "thermal_roll", "sheet_3x8"
