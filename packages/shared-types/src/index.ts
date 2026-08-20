/**
 * Production Inventory Management System - Shared Types Contract
 */

export type RoleType = 'SUPER_ADMIN' | 'WAREHOUSE_MANAGER' | 'INVENTORY_CLERK' | 'PURCHASING_AGENT' | 'SALES_REP' | 'AUDITOR';

export type ValuationMethod = 'FIFO' | 'WEIGHTED_AVERAGE' | 'STANDARD_COST';

export type BinType = 'STORAGE' | 'RECEIVING' | 'SHIPPING' | 'STAGING' | 'DAMAGE' | 'VIRTUAL_ADJUSTMENT';

export type TransactionType =
  | 'PURCHASE_RECEIPT'
  | 'SALES_SHIPMENT'
  | 'TRANSFER_IN'
  | 'TRANSFER_OUT'
  | 'INVENTORY_ADJUSTMENT'
  | 'SCRAP'
  | 'CYCLE_COUNT';

export type POStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'PARTIALLY_RECEIVED' | 'COMPLETED' | 'CANCELLED';

export type SOStatus = 'DRAFT' | 'CONFIRMED' | 'ALLOCATED' | 'PICKING' | 'PACKED' | 'SHIPPED' | 'DELIVERED' | 'CANCELLED';

export interface PaginationMeta {
  page: number;
  pageSize?: number;
  page_size?: number;
  totalItems?: number;
  total_items?: number;
  totalPages?: number;
  total_pages?: number;
  hasNext?: boolean;
  has_next?: boolean;
  hasPrev?: boolean;
  has_prev?: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  pagination: PaginationMeta;
}

export interface UserProfile {
  id: string;
  tenant_id?: string;
  tenantId?: string;
  email: string;
  fullName: string;
  full_name?: string;
  isActive?: boolean;
  is_active?: boolean;
  isSuperuser?: boolean;
  is_superuser?: boolean;
  roles: string[];
  permissions: string[];
  warehouseScopes?: string[];
  warehouse_scopes?: string[];
  lastLoginAt?: string;
  last_login_at?: string;
  createdAt?: string;
  created_at?: string;
}

export interface AuthTokens {
  accessToken: string;
  access_token?: string;
  refreshToken?: string;
  refresh_token?: string;
  tokenType?: string;
  token_type?: string;
  expiresIn?: number;
  expires_in?: number;
  user: UserProfile;
}

export interface LocationBin {
  id: string;
  warehouseId?: string;
  warehouse_id?: string;
  warehouseCode?: string;
  code: string;
  aisle: string;
  rack: string;
  shelf: string;
  bin: string;
  type: BinType | string;
  isActive?: boolean;
  is_active?: boolean;
  occupiedItemsCount?: number;
  occupied_items_count?: number;
  createdAt?: string;
  created_at?: string;
}

export interface Warehouse {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  code: string;
  name: string;
  address?: {
    street?: string;
    city?: string;
    state?: string;
    postalCode?: string;
    country?: string;
  };
  isActive?: boolean;
  is_active?: boolean;
  totalBins?: number;
  total_bins?: number;
  totalStockOnHand?: number;
  total_stock_on_hand?: number;
  bins?: LocationBin[];
  createdAt?: string;
  created_at?: string;
  updatedAt?: string;
  updated_at?: string;
}

export interface ItemCategory {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  parentId?: string;
  parent_id?: string;
  name: string;
  code: string;
  description?: string;
  itemCount?: number;
  item_count?: number;
  createdAt?: string;
  created_at?: string;
}

export interface ItemCategoryCreate {
  name: string;
  code: string;
  description?: string;
  parent_id?: string;
}

export interface ItemCategoryUpdate {
  name?: string;
  code?: string;
  description?: string;
  parent_id?: string;
}

export interface Barcode {
  id: string;
  itemVariantId?: string;
  item_variant_id?: string;
  barcodeValue: string;
  barcode_value?: string;
  symbology: 'CODE128' | 'EAN13' | 'UPCA' | 'QR' | 'DATAMATRIX' | string;
  isPrimary?: boolean;
  is_primary?: boolean;
}

export interface BarcodeCreate {
  barcode_value: string;
  symbology?: string;
  is_primary?: boolean;
}

export interface ItemVariant {
  id: string;
  itemId?: string;
  item_id?: string;
  variantSku?: string;
  variant_sku?: string;
  variantName: string;
  variant_name?: string;
  attributes: Record<string, any>;
  costPrice: number;
  cost_price?: number;
  sellingPrice: number;
  selling_price?: number;
  barcodes: Barcode[];
  currentStock?: number;
  current_stock?: number;
  allocatedStock?: number;
  allocated_stock?: number;
  availableStock?: number;
  available_stock?: number;
}

export interface ItemVariantCreate {
  variant_sku: string;
  variant_name: string;
  attributes?: Record<string, any>;
  cost_price?: number;
  selling_price?: number;
  barcodes?: BarcodeCreate[];
}

export interface ItemVariantUpdate {
  variant_sku?: string;
  variant_name?: string;
  attributes?: Record<string, any>;
  cost_price?: number;
  selling_price?: number;
}

export interface VariantBinStock {
  warehouse_id: string;
  warehouse_name: string;
  warehouse_code: string;
  location_bin_id: string;
  bin_code: string;
  batch_number?: string;
  quantity_on_hand: number;
  quantity_allocated: number;
  quantity_available: number;
}

export interface Item {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  categoryId?: string;
  category_id?: string;
  categoryName?: string;
  category_name?: string;
  sku: string;
  name: string;
  description?: string;
  baseUom: string;
  base_uom?: string;
  valuationMethod: ValuationMethod | string;
  valuation_method?: string;
  reorderPoint: number;
  reorder_point?: number;
  reorderQuantity: number;
  reorder_quantity?: number;
  isBatchTracked?: boolean;
  is_batch_tracked?: boolean;
  isSerialTracked?: boolean;
  is_serial_tracked?: boolean;
  isActive?: boolean;
  is_active?: boolean;
  variants: ItemVariant[];
  totalStock?: number;
  total_stock?: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface ItemDetail extends Item {
  bin_stock_breakdown?: VariantBinStock[];
}

export interface ItemCreate {
  category_id?: string;
  sku: string;
  name: string;
  description?: string;
  base_uom?: string;
  valuation_method?: string;
  reorder_point?: number;
  reorder_quantity?: number;
  is_batch_tracked?: boolean;
  is_serial_tracked?: boolean;
  variants?: ItemVariantCreate[];
}

export interface ItemUpdate {
  category_id?: string;
  sku?: string;
  name?: string;
  description?: string;
  base_uom?: string;
  valuation_method?: string;
  reorder_point?: number;
  reorder_quantity?: number;
  is_batch_tracked?: boolean;
  is_serial_tracked?: boolean;
  is_active?: boolean;
}

export interface StockLedgerEntry {
  id: string;
  transactionId?: string;
  transaction_id?: string;
  transactionNumber?: string;
  transaction_number?: string;
  transactionType?: TransactionType | string;
  transaction_type?: string;
  itemVariantId?: string;
  item_variant_id?: string;
  itemSku?: string;
  item_sku?: string;
  itemName?: string;
  item_name?: string;
  variantName?: string;
  variant_name?: string;
  batchNumber?: string;
  batch_number?: string;
  serialNumber?: string;
  serial_number?: string;
  sourceLocationBinId?: string;
  source_location_bin_id?: string;
  sourceBinCode?: string;
  source_bin_code?: string;
  destinationLocationBinId?: string;
  destination_location_bin_id?: string;
  destinationBinCode?: string;
  destination_bin_code?: string;
  quantity: number;
  uom: string;
  unitCost?: number;
  unit_cost: number;
  totalCost?: number;
  total_cost: number;
  postedByUserId?: string;
  posted_by_user_id?: string;
  postedByUserName?: string;
  posted_by_user_name?: string;
  postedAt?: string;
  posted_at: string;
  notes?: string;
}

export interface StockBalanceCache {
  id: string;
  warehouseId?: string;
  warehouse_id?: string;
  warehouseCode?: string;
  warehouse_code?: string;
  warehouseName?: string;
  warehouse_name?: string;
  locationBinId?: string;
  location_bin_id?: string;
  binCode?: string;
  bin_code?: string;
  itemVariantId?: string;
  item_variant_id?: string;
  itemSku?: string;
  item_sku?: string;
  itemName?: string;
  item_name?: string;
  variantSku?: string;
  variant_sku?: string;
  variantName?: string;
  variant_name?: string;
  batchNumber?: string;
  batch_number?: string;
  quantityOnHand?: number;
  quantity_on_hand: number;
  quantityAllocated?: number;
  quantity_allocated: number;
  quantityAvailable?: number;
  quantity_available: number;
  updatedAt?: string;
  updated_at: string;
}

export interface Supplier {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  code: string;
  name: string;
  email?: string;
  phone?: string;
  address?: Record<string, any>;
  paymentTerms?: string;
  payment_terms?: string;
  currency: string;
  isActive?: boolean;
  is_active?: boolean;
  activeOrdersCount?: number;
  active_orders_count?: number;
  createdAt?: string;
  created_at?: string;
}

export interface SupplierCreate {
  code: string;
  name: string;
  email?: string;
  phone?: string;
  address?: Record<string, any>;
  payment_terms?: string;
  currency?: string;
  is_active?: boolean;
}

export interface SupplierUpdate {
  name?: string;
  email?: string;
  phone?: string;
  address?: Record<string, any>;
  payment_terms?: string;
  currency?: string;
  is_active?: boolean;
}

export interface POLineItem {
  id: string;
  purchaseOrderId?: string;
  purchase_order_id?: string;
  itemVariantId?: string;
  item_variant_id?: string;
  itemSku?: string;
  item_sku?: string;
  itemName?: string;
  item_name?: string;
  variantSku?: string;
  variant_sku?: string;
  variantName?: string;
  variant_name?: string;
  quantityOrdered?: number;
  quantity_ordered: number;
  quantityReceived?: number;
  quantity_received: number;
  quantityRemaining?: number;
  quantity_remaining?: number;
  unitPrice?: number;
  unit_price: number;
  discountPct?: number;
  discount_pct?: number;
  taxPct?: number;
  tax_pct?: number;
  lineTotal?: number;
  line_total: number;
}

export interface POLineCreate {
  item_variant_id: string;
  quantity_ordered: number;
  unit_price: number;
  discount_pct?: number;
  tax_pct?: number;
}

export interface GoodsReceiptLine {
  id: string;
  po_line_id: string;
  item_variant_id: string;
  item_sku: string;
  item_name: string;
  quantity_received: number;
  destination_bin_id: string;
  destination_bin_code?: string;
  batch_number?: string;
  expiry_date?: string;
}

export interface GoodsReceipt {
  id: string;
  grn_number: string;
  purchase_order_id: string;
  warehouse_id: string;
  warehouse_name?: string;
  received_at: string;
  notes?: string;
  lines: GoodsReceiptLine[];
}

export interface GoodsReceiptLineCreate {
  po_line_id: string;
  item_variant_id: string;
  quantity_received: number;
  destination_bin_id: string;
  batch_number?: string;
  expiry_date?: string;
}

export interface GoodsReceiptCreate {
  purchase_order_id: string;
  warehouse_id: string;
  notes?: string;
  lines: GoodsReceiptLineCreate[];
}

export interface PurchaseOrder {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  poNumber?: string;
  po_number?: string;
  supplierId?: string;
  supplier_id?: string;
  supplierName?: string;
  supplier_name?: string;
  supplierCode?: string;
  supplier_code?: string;
  targetWarehouseId?: string;
  target_warehouse_id?: string;
  targetWarehouseName?: string;
  target_warehouse_name?: string;
  targetWarehouseCode?: string;
  target_warehouse_code?: string;
  status: POStatus | string;
  subtotalAmount?: number;
  subtotal_amount?: number;
  discountAmount?: number;
  discount_amount?: number;
  taxAmount?: number;
  tax_amount?: number;
  totalAmount?: number;
  total_amount: number;
  orderedAt?: string;
  ordered_at: string;
  expectedDeliveryAt?: string;
  expected_delivery_at?: string;
  notes?: string;
  lines: POLineItem[];
  receipts?: GoodsReceipt[];
  createdAt?: string;
  created_at?: string;
}

export interface PurchaseOrderDetail extends PurchaseOrder {
  receipts: GoodsReceipt[];
}

export interface PurchaseOrderCreate {
  supplier_id: string;
  target_warehouse_id: string;
  expected_delivery_at?: string;
  notes?: string;
  lines: POLineCreate[];
}

export interface PurchaseOrderUpdate {
  supplier_id?: string;
  target_warehouse_id?: string;
  expected_delivery_at?: string;
  notes?: string;
  lines?: POLineCreate[];
}

export interface Customer {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  code: string;
  name: string;
  email?: string;
  phone?: string;
  shippingAddresses?: any[];
  shipping_address?: Record<string, any>;
  billingAddress?: Record<string, any>;
  billing_address?: Record<string, any>;
  isActive?: boolean;
  is_active?: boolean;
  activeOrdersCount?: number;
  active_orders_count?: number;
  createdAt?: string;
  created_at?: string;
}

export interface CustomerCreate {
  code: string;
  name: string;
  email?: string;
  phone?: string;
  billing_address?: Record<string, any>;
  shipping_address?: Record<string, any>;
  is_active?: boolean;
}

export interface CustomerUpdate {
  name?: string;
  email?: string;
  phone?: string;
  billing_address?: Record<string, any>;
  shipping_address?: Record<string, any>;
  is_active?: boolean;
}

export interface SOAllocationDetail {
  location_bin_id: string;
  bin_code: string;
  quantity_allocated: number;
}

export interface SOLineItem {
  id: string;
  salesOrderId?: string;
  sales_order_id?: string;
  itemVariantId?: string;
  item_variant_id?: string;
  itemSku?: string;
  item_sku?: string;
  itemName?: string;
  item_name?: string;
  variantSku?: string;
  variant_sku?: string;
  variantName?: string;
  variant_name?: string;
  quantityOrdered?: number;
  quantity_ordered: number;
  quantityAllocated?: number;
  quantity_allocated: number;
  quantityPicked?: number;
  quantity_picked: number;
  quantityShipped?: number;
  quantity_shipped: number;
  quantityReturned?: number;
  quantity_returned?: number;
  unitPrice?: number;
  unit_price: number;
  discountPct?: number;
  discount_pct?: number;
  taxPct?: number;
  tax_pct?: number;
  lineTotal?: number;
  line_total: number;
  allocations?: SOAllocationDetail[];
}

export interface SOLineCreate {
  item_variant_id: string;
  quantity_ordered: number;
  unit_price: number;
  discount_pct?: number;
  tax_pct?: number;
}

export interface Shipment {
  id: string;
  shipment_number: string;
  carrier?: string;
  tracking_number?: string;
  package_count: number;
  total_weight?: number;
  shipped_at: string;
  notes?: string;
}

export interface SalesReturnLine {
  id: string;
  so_line_id: string;
  item_variant_id: string;
  item_sku: string;
  item_name: string;
  quantity_returned: number;
  condition: string;
  destination_bin_id: string;
  destination_bin_code?: string;
}

export interface SalesReturn {
  id: string;
  return_number: string;
  sales_order_id: string;
  status: string;
  returned_at: string;
  notes?: string;
  lines: SalesReturnLine[];
}

export interface SalesReturnLineCreate {
  so_line_id: string;
  quantity_returned: number;
  condition: 'GOOD' | 'DAMAGED' | string;
  destination_bin_id: string;
}

export interface SalesReturnCreate {
  notes?: string;
  lines: SalesReturnLineCreate[];
}

export interface SalesOrder {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  soNumber?: string;
  so_number?: string;
  customerId?: string;
  customer_id?: string;
  customerName?: string;
  customer_name?: string;
  customerCode?: string;
  customer_code?: string;
  warehouseId?: string;
  warehouse_id?: string;
  warehouseName?: string;
  warehouse_name?: string;
  warehouseCode?: string;
  warehouse_code?: string;
  status: SOStatus | string;
  subtotalAmount?: number;
  subtotal_amount?: number;
  discountAmount?: number;
  discount_amount?: number;
  taxAmount?: number;
  tax_amount?: number;
  totalAmount?: number;
  total_amount: number;
  orderedAt?: string;
  ordered_at: string;
  notes?: string;
  lines: SOLineItem[];
  shipments?: Shipment[];
  returns?: SalesReturn[];
  createdAt?: string;
  created_at?: string;
}

export interface SalesOrderDetail extends SalesOrder {
  shipments: Shipment[];
  returns: SalesReturn[];
}

export interface SalesOrderCreate {
  customer_id: string;
  warehouse_id: string;
  notes?: string;
  lines: SOLineCreate[];
}

export interface SalesOrderUpdate {
  customer_id?: string;
  warehouse_id?: string;
  notes?: string;
  lines?: SOLineCreate[];
}

export interface SOPickItem {
  so_line_id: string;
  quantity_picked: number;
}

export interface SOPickRequest {
  picks: SOPickItem[];
}

export interface SOPackRequest {
  package_count: number;
  total_weight?: number;
  packing_notes?: string;
}

export interface SODispatchRequest {
  carrier?: string;
  tracking_number?: string;
  package_count?: number;
  total_weight?: number;
  notes?: string;
}

export interface AuditLog {
  id: string;
  tenantId?: string;
  tenant_id?: string;
  userId?: string;
  user_id?: string;
  userEmail?: string;
  user_email?: string;
  userName?: string;
  user_name?: string;
  action: string;
  entityType?: string;
  entity_type: string;
  entityId?: string;
  entity_id: string;
  ipAddress?: string;
  ip_address?: string;
  clientType?: string;
  client_type: string;
  changes: Record<string, any>;
  timestamp: string;
}

export interface BarcodeLookupResponse {
  found: boolean;
  barcode_value: string;
  item_id?: string;
  item_sku?: string;
  item_name?: string;
  variant_id?: string;
  variant_sku?: string;
  variant_name?: string;
  cost_price?: number;
  selling_price?: number;
  current_stock?: number;
}

export interface DashboardOperationalAlert {
  level: 'CRITICAL' | 'WARNING' | 'INFO' | string;
  title: string;
  message: string;
  count?: number;
  link_tab?: string;
}

export interface RecentGoodsReceiptSummary {
  id: string;
  grn_number: string;
  po_number: string;
  warehouse_name: string;
  received_at: string;
  lines_count: number;
}

export interface RecentSalesOrderSummary {
  id: string;
  so_number: string;
  customer_name: string;
  status: string;
  total_amount: number;
  ordered_at: string;
}

export interface DashboardMetrics {
  total_items: number;
  total_warehouses: number;
  total_on_hand_units?: number;
  total_allocated_units?: number;
  total_available_units?: number;
  low_stock_count: number;
  out_of_stock_count?: number;
  pending_pos: number;
  pending_sos: number;
  orders_awaiting_picking?: number;
  orders_awaiting_packing?: number;
  orders_awaiting_dispatch?: number;
  total_valuation: number;
  recent_transactions: StockLedgerEntry[];
  recent_audit_logs: AuditLog[];
  recent_receipts?: RecentGoodsReceiptSummary[];
  recent_sales_orders?: RecentSalesOrderSummary[];
  operational_alerts?: DashboardOperationalAlert[];
}

export interface InventoryReportItem {
  item_id: string;
  variant_id: string;
  sku: string;
  item_name: string;
  variant_name: string;
  warehouse_code: string;
  warehouse_name: string;
  bin_code: string;
  quantity_on_hand: number;
  quantity_allocated: number;
  quantity_available: number;
  reorder_point: number;
  status: 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK' | string;
}

export interface InventoryReportResponse {
  total_items_reported: number;
  total_on_hand: number;
  total_allocated: number;
  total_available: number;
  items: InventoryReportItem[];
}

export interface PurchasingReportItem {
  po_id: string;
  po_number: string;
  supplier_code: string;
  supplier_name: string;
  warehouse_code: string;
  status: string;
  ordered_at: string;
  expected_delivery_at?: string;
  total_amount: number;
  total_ordered_qty: number;
  total_received_qty: number;
  outstanding_qty: number;
}

export interface PurchasingReportResponse {
  total_pos: number;
  total_spend: number;
  pending_approval_count: number;
  partial_receipt_count: number;
  items: PurchasingReportItem[];
}

export interface SalesReportItem {
  so_id: string;
  so_number: string;
  customer_code: string;
  customer_name: string;
  warehouse_code: string;
  status: string;
  ordered_at: string;
  total_amount: number;
  total_ordered_qty: number;
  total_allocated_qty: number;
  total_shipped_qty: number;
  total_returned_qty: number;
}

export interface SalesReportResponse {
  total_orders: number;
  total_sales_value: number;
  allocation_queue_count: number;
  picking_queue_count: number;
  packing_queue_count: number;
  dispatch_queue_count: number;
  items: SalesReportItem[];
}

export interface GlobalSearchResultItem {
  category: 'PRODUCT' | 'BARCODE' | 'CUSTOMER' | 'SUPPLIER' | 'PURCHASE_ORDER' | 'SALES_ORDER' | 'WAREHOUSE' | string;
  title: string;
  subtitle: string;
  identifier: string;
  link_page: string;
  metadata?: Record<string, any>;
}

export interface GlobalSearchResponse {
  query: string;
  total_matches: number;
  results: GlobalSearchResultItem[];
}

export interface ValuationReportItem {
  item_id: string;
  sku: string;
  name: string;
  valuation_method: string;
  total_quantity: number;
  unit_cost: number;
  total_valuation: number;
}

export interface ValuationReportResponse {
  total_inventory_value: number;
  currency: string;
  items: ValuationReportItem[];
}

export interface UserCreateInput {
  email: string;
  password: string;
  full_name: string;
  role_ids: string[];
  warehouse_ids: string[];
}

export interface UserUpdateInput {
  full_name?: string;
  is_active?: boolean;
  role_ids?: string[];
  warehouse_ids?: string[];
}

export interface UserSessionItem {
  id: string;
  user_id: string;
  device_info?: string;
  created_at: string;
  expires_at: string;
  is_current?: boolean;
}

export interface PermissionItem {
  id: string;
  code: string;
  module: string;
  description?: string;
}

export interface RoleItem {
  id: string;
  name: string;
  description?: string;
  is_system: boolean;
  permissions: string[];
}

export interface RoleCreateInput {
  name: string;
  description?: string;
  permission_codes: string[];
}

export interface RoleUpdateInput {
  name?: string;
  description?: string;
  permission_codes?: string[];
}

export interface SystemSettings {
  company_name: string;
  company_email?: string;
  company_phone?: string;
  logo_url?: string;
  currency: string;
  timezone: string;
  date_format: string;
  default_warehouse_id?: string;
  default_receiving_bin_id?: string;
  default_damage_bin_id?: string;
  allow_negative_stock: boolean;
  auto_allocate_on_confirm: boolean;
  require_grn_inspection: boolean;
  default_payment_terms: string;
  default_tax_pct: number;
  require_po_approval: boolean;
  po_approval_threshold: number;
}

export interface SystemSettingsUpdate {
  company_name?: string;
  company_email?: string;
  company_phone?: string;
  logo_url?: string;
  currency?: string;
  timezone?: string;
  date_format?: string;
  default_warehouse_id?: string;
  default_receiving_bin_id?: string;
  default_damage_bin_id?: string;
  auto_allocate_on_confirm?: boolean;
  require_grn_inspection?: boolean;
  default_payment_terms?: string;
  default_tax_pct?: number;
  require_po_approval?: boolean;
  po_approval_threshold?: number;
}

export interface AuditLogItem {
  id: string;
  tenant_id: string;
  user_id?: string;
  user_name?: string;
  user_email?: string;
  action: string;
  entity_type: string;
  entity_id: string;
  ip_address?: string;
  client_type: string;
  changes: Record<string, any>;
  timestamp: string;
}

export type DocumentType =
  | 'PURCHASE_ORDER'
  | 'GOODS_RECEIPT'
  | 'SALES_ORDER'
  | 'SALES_INVOICE'
  | 'PACKING_SLIP'
  | 'DELIVERY_NOTE'
  | 'STOCK_TRANSFER'
  | 'STOCK_ADJUSTMENT'
  | 'SALES_RETURN';

export interface DocumentHeader {
  company_name: string;
  company_email?: string;
  company_phone?: string;
  company_address?: string;
  document_type: DocumentType;
  document_title: string;
  document_number: string;
  date_formatted: string;
  status: string;
  barcode_value: string;
}

export interface DocumentParty {
  party_type: string;
  name: string;
  code?: string;
  contact_person?: string;
  email?: string;
  phone?: string;
  tax_id?: string;
  billing_address?: string;
  shipping_address?: string;
}

export interface DocumentFacility {
  warehouse_name: string;
  warehouse_code: string;
  address?: string;
  bin_name?: string;
}

export interface DocumentLine {
  line_number: number;
  item_sku: string;
  item_name: string;
  variant_name?: string;
  bin_location?: string;
  quantity: number;
  uom: string;
  unit_price?: number;
  discount?: number;
  tax?: number;
  subtotal?: number;
  notes?: string;
}

export interface DocumentSummary {
  currency: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  grand_total: number;
  payment_terms?: string;
  notes?: string;
}

export interface DocumentPayload {
  header: DocumentHeader;
  party?: DocumentParty;
  facility?: DocumentFacility;
  destination_facility?: DocumentFacility;
  lines: DocumentLine[];
  summary?: DocumentSummary;
  metadata: Record<string, any>;
  footer_text?: string;
}

export interface BarcodeLabelItem {
  title: string;
  sku: string;
  variant?: string;
  barcode: string;
  bin_code?: string;
  price_formatted?: string;
}

export interface BarcodeLabelRequest {
  labels: BarcodeLabelItem[];
  copies_per_label?: number;
  layout?: 'sticker' | 'thermal_roll' | 'sheet_3x8';
}

export type PrintLayout = 'A4' | 'THERMAL' | 'LABEL';

export type ConnectionStatus = 'CONNECTED' | 'CONNECTING' | 'DISCONNECTED' | 'ERROR';

export interface DesktopConfig {
  apiUrl: string;
  defaultLayout: PrintLayout;
  preferredPrinter?: string;
  scannerThresholdMs: number;
}

export interface AppMetadata {
  name: string;
  version: string;
  isDesktop: boolean;
  platform: string;
  environment: 'development' | 'production' | 'test';
}

export interface BackupItem {
  filename: string;
  size_bytes: number;
  size_formatted: string;
  checksum_sha256: string;
  created_at: string;
  verified: boolean;
}

export interface IntegrityDiscrepancy {
  code: string;
  severity: 'CRITICAL' | 'WARNING' | 'INFO';
  entity_type: string;
  entity_id: string;
  description: string;
  expected: number;
  actual: number;
}

export interface IntegrityCheckResult {
  overall_status: 'HEALTHY' | 'DISCREPANCIES_DETECTED';
  checks_performed: number;
  discrepancies_count: number;
  discrepancies: IntegrityDiscrepancy[];
  audited_at: string;
  invariants_verified: string[];
}

export interface OperationalMetrics {
  uptime_seconds: number;
  total_requests: number;
  status_breakdown: {
    '2xx': number;
    '3xx': number;
    '4xx': number;
    '5xx': number;
  };
  error_count: number;
  latency_ms: {
    avg: number;
    p95: number;
    max: number;
  };
  last_backup: {
    timestamp: string | null;
    status: string;
  };
  last_integrity_check: {
    timestamp: string | null;
    status: string;
  };
}

export interface SystemOperationsStatus {
  status: 'OPERATIONAL' | 'DEGRADED';
  service: string;
  version: string;
  environment: string;
  database: {
    connected: boolean;
    latency_ms: number;
    engine: string;
  };
  storage: {
    total_bytes: number;
    free_bytes: number;
    free_percent: number;
  };
  metrics_summary: {
    uptime_seconds: number;
    total_requests: number;
    error_count: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
  };
  backup: {
    total_backups: number;
    latest_backup: BackupItem | null;
    retention_policy: string;
  };
}
