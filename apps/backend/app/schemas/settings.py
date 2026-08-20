from typing import Optional
from pydantic import BaseModel, EmailStr

class SystemSettingResponse(BaseModel):
    company_name: str
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    logo_url: Optional[str] = None
    currency: str = "USD"
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    default_warehouse_id: Optional[str] = None
    default_receiving_bin_id: Optional[str] = None
    default_damage_bin_id: Optional[str] = None
    allow_negative_stock: bool = False
    auto_allocate_on_confirm: bool = False
    require_grn_inspection: bool = False
    default_payment_terms: str = "NET_30"
    default_tax_pct: float = 0.0
    require_po_approval: bool = True
    po_approval_threshold: float = 1000.0

class SystemSettingUpdate(BaseModel):
    company_name: Optional[str] = None
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    logo_url: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    date_format: Optional[str] = None
    default_warehouse_id: Optional[str] = None
    default_receiving_bin_id: Optional[str] = None
    default_damage_bin_id: Optional[str] = None
    auto_allocate_on_confirm: Optional[bool] = None
    require_grn_inspection: Optional[bool] = None
    default_payment_terms: Optional[str] = None
    default_tax_pct: Optional[float] = None
    require_po_approval: Optional[bool] = None
    po_approval_threshold: Optional[float] = None
