from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

# ============================================================================
# FIXED ASSET CLASS SCHEMAS
# ============================================================================

class FixedAssetClassCreate(BaseModel):
    class_code: str # BUILDINGS, PLANT_MACHINERY, VEHICLES, COMPUTERS_IT, FURNITURE_FIXTURES
    class_name: str
    depreciation_method: str = "STRAIGHT_LINE" # STRAIGHT_LINE, WRITTEN_DOWN_VALUE
    useful_life_months: int = 60
    depreciation_rate_annual: Decimal = Decimal("0.0")
    description: Optional[str] = None

class FixedAssetClassResponse(BaseModel):
    id: str
    tenant_id: str
    class_code: str
    class_name: str
    depreciation_method: str
    useful_life_months: int
    depreciation_rate_annual: Decimal
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

# ============================================================================
# FIXED ASSET & SCHEDULE SCHEMAS
# ============================================================================

class FixedAssetCreate(BaseModel):
    asset_code: str # AST-001
    asset_name: str
    asset_class_id: str
    warehouse_id: Optional[str] = None
    serial_number: Optional[str] = None
    source_po_id: Optional[str] = None
    source_grn_id: Optional[str] = None
    purchase_cost: Decimal
    salvage_value: Decimal = Decimal("0.0")
    acquisition_date: date
    depreciation_start_date: date
    depreciation_method: Optional[str] = None
    useful_life_months: Optional[int] = None
    depreciation_rate_annual: Optional[Decimal] = None
    notes: Optional[str] = None

class DepreciationScheduleEntryResponse(BaseModel):
    id: str
    fixed_asset_id: str
    period_code: str
    scheduled_date: date
    depreciation_amount: Decimal
    accumulated_depreciation_after: Decimal
    remaining_book_value_after: Decimal
    status: str
    posted_at: Optional[datetime] = None
    journal_voucher_id: Optional[str] = None

class FixedAssetResponse(BaseModel):
    id: str
    tenant_id: str
    asset_code: str
    asset_name: str
    asset_class_id: str
    warehouse_id: Optional[str] = None
    serial_number: Optional[str] = None
    source_po_id: Optional[str] = None
    source_grn_id: Optional[str] = None
    purchase_cost: Decimal
    salvage_value: Decimal
    acquisition_date: date
    depreciation_start_date: date
    depreciation_method: str
    useful_life_months: int
    depreciation_rate_annual: Decimal
    current_book_value: Decimal
    accumulated_depreciation: Decimal
    status: str
    disposal_date: Optional[date] = None
    disposal_amount: Optional[Decimal] = None
    notes: Optional[str] = None
    schedule_entries: List[DepreciationScheduleEntryResponse] = []
    created_at: datetime

# ============================================================================
# BATCH DEPRECIATION & DISPOSAL SCHEMAS
# ============================================================================

class DepreciationBatchRunRequest(BaseModel):
    period_code: str # e.g. 2026-01
    run_date: Optional[date] = None
    notes: Optional[str] = None

class DepreciationBatchRunResponse(BaseModel):
    period_code: str
    processed_assets_count: int
    total_depreciation_amount: Decimal
    journal_voucher_id: Optional[str] = None
    journal_voucher_number: Optional[str] = None

class AssetDisposalRequest(BaseModel):
    disposal_date: date
    disposal_amount: Decimal # Cash/proceeds received
    notes: Optional[str] = None

class AssetDisposalResponse(BaseModel):
    asset_id: str
    asset_code: str
    purchase_cost: Decimal
    accumulated_depreciation: Decimal
    book_value_at_disposal: Decimal
    disposal_amount: Decimal
    gain_or_loss: Decimal
    journal_voucher_id: str
    status: str

# ============================================================================
# ASSET CAPITAL IMPROVEMENT SCHEMAS (PHASE 34)
# ============================================================================

class AssetImprovementCreate(BaseModel):
    improvement_name: str
    capitalized_amount: Decimal
    useful_life_extension_months: int = 0
    mwo_id: Optional[str] = None

class AssetImprovementResponse(BaseModel):
    id: str
    tenant_id: str
    asset_id: str
    mwo_id: Optional[str] = None
    improvement_name: str
    capitalized_amount: Decimal
    useful_life_extension_months: int
    capitalization_date: datetime
    status: str
    journal_voucher_id: Optional[str] = None
    created_at: datetime
