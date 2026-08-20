from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict
from decimal import Decimal

# ============================================================================
# INVENTORY ANALYTICS SCHEMAS (Phase 4D)
# ============================================================================

class AgingBucketDetail(BaseModel):
    bucket_name: str
    min_days: Optional[int] = None
    max_days: Optional[int] = None
    total_quantity: float
    total_value: float
    item_count: int
    percentage_of_total_value: float

class InventoryAgingReportResponse(BaseModel):
    total_inventory_quantity: float
    total_inventory_value: float
    buckets: List[AgingBucketDetail]
    generated_at: datetime

class TurnoverMetricItem(BaseModel):
    item_id: str
    item_sku: str
    item_name: str
    variant_id: str
    variant_sku: str
    category_name: Optional[str] = None
    cogs_period: float
    average_inventory_value: float
    current_quantity_on_hand: float
    turnover_ratio: float
    days_inventory_outstanding: Optional[float] = None
    velocity_status: str

class InventoryTurnoverReportResponse(BaseModel):
    period_days: int
    period_start: datetime
    period_end: datetime
    enterprise_cogs: float
    enterprise_average_inventory: float
    enterprise_turnover_ratio: float
    enterprise_dio: Optional[float] = None
    items: List[TurnoverMetricItem]
    generated_at: datetime

class StockMovementClassificationItem(BaseModel):
    variant_id: str
    variant_sku: str
    item_name: str
    category_name: Optional[str] = None
    classification: str
    quantity_on_hand: float
    current_valuation: float
    days_since_last_dispatch: Optional[int] = None
    last_dispatch_date: Optional[datetime] = None
    turnover_ratio: float
    days_inventory_outstanding: Optional[float] = None

class StockClassificationReportResponse(BaseModel):
    total_slow_moving_value: float
    total_dead_stock_value: float
    fast_moving_count: int
    normal_count: int
    slow_moving_count: int
    dead_stock_count: int
    items: List[StockMovementClassificationItem]
    generated_at: datetime

class UsageTimeBucket(BaseModel):
    period_label: str
    start_date: datetime
    end_date: datetime
    consumed_quantity: float
    consumed_cost: float
    dispatch_count: int

class DemandAndUsageResponse(BaseModel):
    variant_id: str
    variant_sku: str
    item_name: str
    measurement_period_days: int
    total_consumed_quantity: float
    average_daily_usage_30d: float
    average_daily_usage_90d: float
    average_daily_usage_180d: float
    usage_trend_percentage: float
    trend_direction: str
    time_buckets: List[UsageTimeBucket]
    generated_at: datetime

class ReplenishmentRecommendationItem(BaseModel):
    variant_id: str
    variant_sku: str
    item_name: str
    warehouse_id: str
    warehouse_name: str
    quantity_on_hand: float
    quantity_allocated: float
    quantity_available: float
    incoming_on_po: float
    average_daily_usage: float
    lead_time_days: int
    safety_stock: float
    reorder_point: float
    target_stock: float
    raw_recommended_quantity: float
    recommended_order_quantity: float
    minimum_order_quantity: float
    pack_size: float
    estimated_reorder_cost: float
    urgency: str

class ReplenishmentRecommendationsResponse(BaseModel):
    total_skus_evaluated: int
    skus_requiring_reorder: int
    critical_stockout_skus: int
    total_recommended_spend: float
    recommendations: List[ReplenishmentRecommendationItem]
    generated_at: datetime

class SupplierPerformanceItem(BaseModel):
    supplier_id: str
    supplier_name: str
    supplier_code: str
    total_orders_placed: int
    total_orders_completed: int
    average_lead_time_days: Optional[float] = None
    fulfillment_fill_rate_percentage: float
    total_spend: float
    open_po_count: int
    open_po_value: float

class SupplierAnalyticsResponse(BaseModel):
    total_suppliers_evaluated: int
    suppliers: List[SupplierPerformanceItem]
    generated_at: datetime

class ExecutiveInventoryDashboardResponse(BaseModel):
    total_inventory_valuation: float
    total_units_on_hand: float
    active_sku_count: int
    annualized_turnover_ratio: float
    days_inventory_outstanding: Optional[float] = None
    low_stock_sku_count: int
    slow_moving_valuation: float
    dead_stock_valuation: float
    reorder_required_sku_count: int
    aging_summary: Dict[str, float]
    top_fast_moving_items: List[StockMovementClassificationItem]
    generated_at: datetime

# ============================================================================
# SALES ANALYTICS SCHEMAS (Phase 8B.3)
# ============================================================================

class SalesSummaryKPIs(BaseModel):
    total_orders_placed: int
    total_orders_delivered: int
    total_orders_cancelled: int
    gross_sales_revenue: float
    discount_total: float
    tax_total: float
    net_sales_revenue: float
    authoritative_cogs: float
    gross_profit_amount: float
    gross_profit_margin_pct: float
    average_order_value: float
    fill_rate_pct: float
    on_time_in_full_pct: float
    cancellation_rate_pct: float
    return_rate_pct: float

class ProductSalesAnalyticsItem(BaseModel):
    item_variant_id: str
    item_sku: str
    item_name: str
    variant_sku: str
    variant_name: Optional[str] = None
    units_ordered: float
    units_shipped: float
    net_revenue: float
    authoritative_cogs: float
    gross_margin_amount: float
    gross_margin_pct: float

class CustomerSalesAnalyticsItem(BaseModel):
    customer_id: str
    customer_code: str
    customer_name: str
    order_count: int
    total_spend: float
    authoritative_cogs: float
    gross_margin_amount: float
    gross_margin_pct: float

class WarehouseSalesAnalyticsItem(BaseModel):
    warehouse_id: str
    warehouse_code: str
    warehouse_name: str
    shipment_count: int
    units_dispatched: float
    net_revenue: float
    authoritative_cogs: float
    fill_rate_pct: float
