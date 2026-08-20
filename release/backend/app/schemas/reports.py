from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.schemas.ledger import StockLedgerEntryResponse
from app.schemas.audit import AuditLogResponse

class DashboardOperationalAlert(BaseModel):
    level: str # CRITICAL, WARNING, INFO
    title: str
    message: str
    count: int = 0
    link_tab: Optional[str] = None

class RecentGoodsReceiptSummary(BaseModel):
    id: str
    grn_number: str
    po_number: str
    warehouse_name: str
    received_at: datetime
    lines_count: int

class RecentSalesOrderSummary(BaseModel):
    id: str
    so_number: str
    customer_name: str
    status: str
    total_amount: float
    ordered_at: datetime

class ValuationReportItem(BaseModel):
    item_id: str
    sku: str
    name: str
    valuation_method: str
    total_quantity: float
    unit_cost: float
    total_valuation: float

class ValuationReportResponse(BaseModel):
    total_inventory_value: float
    currency: str = "USD"
    items: List[ValuationReportItem]

class DashboardMetricsResponse(BaseModel):
    total_items: int
    total_warehouses: int
    total_on_hand_units: float = 0.0
    total_allocated_units: float = 0.0
    total_available_units: float = 0.0
    low_stock_count: int = 0
    out_of_stock_count: int = 0
    pending_pos: int = 0
    pending_sos: int = 0
    orders_awaiting_picking: int = 0
    orders_awaiting_packing: int = 0
    orders_awaiting_dispatch: int = 0
    total_valuation: float = 0.0
    recent_transactions: List[StockLedgerEntryResponse] = []
    recent_audit_logs: List[AuditLogResponse] = []
    recent_receipts: List[RecentGoodsReceiptSummary] = []
    recent_sales_orders: List[RecentSalesOrderSummary] = []
    operational_alerts: List[DashboardOperationalAlert] = []

# ============================================================================
# CONSOLIDATED REPORTS SCHEMAS
# ============================================================================

class InventoryReportItem(BaseModel):
    item_id: str
    variant_id: str
    sku: str
    item_name: str
    variant_name: str
    warehouse_code: str
    warehouse_name: str
    bin_code: str
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float
    reorder_point: float
    status: str # IN_STOCK, LOW_STOCK, OUT_OF_STOCK

class InventoryReportResponse(BaseModel):
    total_items_reported: int
    total_on_hand: float
    total_allocated: float
    total_available: float
    items: List[InventoryReportItem]

class PurchasingReportItem(BaseModel):
    po_id: str
    po_number: str
    supplier_code: str
    supplier_name: str
    warehouse_code: str
    status: str
    ordered_at: datetime
    expected_delivery_at: Optional[datetime] = None
    total_amount: float
    total_ordered_qty: float
    total_received_qty: float
    outstanding_qty: float

class PurchasingReportResponse(BaseModel):
    total_pos: int
    total_spend: float
    pending_approval_count: int
    partial_receipt_count: int
    items: List[PurchasingReportItem]

class SalesReportItem(BaseModel):
    so_id: str
    so_number: str
    customer_code: str
    customer_name: str
    warehouse_code: str
    status: str
    ordered_at: datetime
    total_amount: float
    total_ordered_qty: float
    total_allocated_qty: float
    total_shipped_qty: float
    total_returned_qty: float

class SalesReportResponse(BaseModel):
    total_orders: int
    total_sales_value: float
    allocation_queue_count: int
    picking_queue_count: int
    packing_queue_count: int
    dispatch_queue_count: int
    items: List[SalesReportItem]

# ============================================================================
# GLOBAL SEARCH
# ============================================================================

class GlobalSearchResultItem(BaseModel):
    category: str # PRODUCT, BARCODE, CUSTOMER, SUPPLIER, PURCHASE_ORDER, SALES_ORDER, WAREHOUSE
    title: str
    subtitle: str
    identifier: str
    link_page: str
    metadata: Dict[str, Any] = {}

class GlobalSearchResponse(BaseModel):
    query: str
    total_matches: int
    results: List[GlobalSearchResultItem]
