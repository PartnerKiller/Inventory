import {
  AuthTokens,
  UserProfile,
  Warehouse,
  LocationBin,
  Item,
  ItemDetail,
  ItemCategory,
  ItemCategoryCreate,
  ItemCategoryUpdate,
  ItemCreate,
  ItemUpdate,
  ItemVariant,
  ItemVariantCreate,
  ItemVariantUpdate,
  Barcode,
  BarcodeCreate,
  BarcodeLookupResponse,
  StockLedgerEntry,
  StockBalanceCache,
  PurchaseOrder,
  PurchaseOrderDetail,
  PurchaseOrderCreate,
  PurchaseOrderUpdate,
  GoodsReceipt,
  GoodsReceiptCreate,
  Supplier,
  SupplierCreate,
  SupplierUpdate,
  SalesOrder,
  SalesOrderDetail,
  SalesOrderCreate,
  SalesOrderUpdate,
  SOPickRequest,
  SOPackRequest,
  SODispatchRequest,
  Shipment,
  SalesReturn,
  SalesReturnCreate,
  Customer,
  CustomerCreate,
  CustomerUpdate,
  AuditLog,
  AuditLogItem,
  UserCreateInput,
  UserUpdateInput,
  UserSessionItem,
  RoleItem,
  RoleCreateInput,
  RoleUpdateInput,
  PermissionItem,
  SystemSettings,
  SystemSettingsUpdate,
  DocumentType,
  DocumentPayload,
  DashboardMetrics,
  InventoryReportResponse,
  PurchasingReportResponse,
  SalesReportResponse,
  GlobalSearchResponse,
  PaginatedResponse,
  SystemOperationsStatus,
  BackupItem,
  IntegrityCheckResult,
  OperationalMetrics
} from '@inventory/shared-types';

const API_BASE = '/api/v1';

export interface GetItemsParams {
  q?: string;
  category_id?: string;
  warehouse_id?: string;
  is_active?: boolean;
  stock_status?: 'all' | 'in_stock' | 'low_stock' | 'out_of_stock';
  sort_by?: 'sku' | 'name' | 'created_at';
  sort_dir?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

export interface GetStockBalancesParams {
  warehouse_id?: string;
  location_bin_id?: string;
  item_variant_id?: string;
  stock_status?: 'all' | 'in_stock' | 'out_of_stock';
  q?: string;
  page?: number;
  page_size?: number;
}

export interface GetLedgerEntriesParams {
  warehouse_id?: string;
  item_variant_id?: string;
  transaction_type?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

class ApiClient {
  private token: string | null = null;
  private refreshToken: string | null = null;
  private baseUrl: string = '/api/v1';

  constructor() {
    this.token = localStorage.getItem('aurastock_access_token');
    this.refreshToken = localStorage.getItem('aurastock_refresh_token');
    const customUrl = localStorage.getItem('aurastock_api_url');
    const envApiUrl = typeof import.meta !== 'undefined' && (import.meta as any).env ? (import.meta as any).env.VITE_API_URL : null;
    if (customUrl && customUrl.trim()) {
      this.baseUrl = customUrl.trim().replace(/\/+$/, '');
    } else if (envApiUrl && String(envApiUrl).trim()) {
      this.baseUrl = String(envApiUrl).trim().replace(/\/+$/, '');
    } else {
      const isDesktop = typeof window !== 'undefined' && (
        Boolean((window as any).__TAURI_INTERNALS__ || (window as any).__TAURI__) ||
        window.location.protocol === 'tauri:' ||
        window.location.hostname === 'tauri.localhost' ||
        window.location.origin.includes('tauri') ||
        window.location.protocol === 'file:'
      );
      this.baseUrl = isDesktop ? 'http://192.168.0.11:8000/api/v1' : '/api/v1';
    }
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public setBaseUrl(url: string) {
    const cleaned = (url || '/api/v1').trim().replace(/\/+$/, '');
    this.baseUrl = cleaned;
    localStorage.setItem('aurastock_api_url', cleaned);
    window.dispatchEvent(new CustomEvent('connection:base_url_changed', { detail: { url: cleaned } }));
  }

  public async checkHealth(targetUrl?: string): Promise<{ ok: boolean; status: string; latencyMs: number; message?: string }> {
    const base = (targetUrl || this.baseUrl).trim().replace(/\/+$/, '');
    const healthUrl = base.endsWith('/api/v1') ? `${base.replace(/\/api\/v1$/, '')}/health` : `${base}/health`;
    const start = Date.now();
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3500);
      const res = await fetch(healthUrl, { signal: controller.signal });
      clearTimeout(timeoutId);
      const latencyMs = Date.now() - start;
      if (res.ok) {
        window.dispatchEvent(new CustomEvent('connection:status', { detail: { status: 'CONNECTED', url: base, latencyMs } }));
        return { ok: true, status: 'ONLINE', latencyMs };
      }
      const text = await res.text().catch(() => '');
      window.dispatchEvent(new CustomEvent('connection:status', { detail: { status: 'ERROR', url: base, message: text } }));
      return { ok: false, status: 'ERROR', latencyMs, message: `Server returned HTTP ${res.status}` };
    } catch (err: any) {
      const latencyMs = Date.now() - start;
      const msg = err.name === 'AbortError' ? 'Connection timed out (3.5s)' : (err.message || 'Server unreachable');
      window.dispatchEvent(new CustomEvent('connection:status', { detail: { status: 'DISCONNECTED', url: base, message: msg } }));
      return { ok: false, status: 'OFFLINE', latencyMs, message: msg };
    }
  }

  public setTokens(accessToken: string | null, refreshToken?: string | null) {
    this.token = accessToken;
    if (accessToken) {
      localStorage.setItem('aurastock_access_token', accessToken);
    } else {
      localStorage.removeItem('aurastock_access_token');
    }

    if (refreshToken !== undefined) {
      this.refreshToken = refreshToken;
      if (refreshToken) {
        localStorage.setItem('aurastock_refresh_token', refreshToken);
      } else {
        localStorage.removeItem('aurastock_refresh_token');
      }
    }
  }

  public getToken(): string | null {
    return this.token;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3500);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${endpoint}`, {
        ...options,
        headers,
        signal: options.signal || controller.signal,
      });
      clearTimeout(timeoutId);
      window.dispatchEvent(new CustomEvent('connection:status', { detail: { status: 'CONNECTED', url: this.baseUrl } }));
    } catch (networkErr: any) {
      clearTimeout(timeoutId);
      const errorMsg = `Server unreachable at ${this.baseUrl}. Working in offline mode.`;
      window.dispatchEvent(new CustomEvent('connection:status', { detail: { status: 'DISCONNECTED', url: this.baseUrl, message: errorMsg } }));
      throw new Error(errorMsg);
    }

    if (response.status === 401 && this.refreshToken && endpoint !== '/auth/refresh' && endpoint !== '/auth/login') {
      try {
        const refreshRes = await fetch(`${this.baseUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        });

        if (refreshRes.ok) {
          const freshTokens: AuthTokens = await refreshRes.json();
          this.setTokens(freshTokens.accessToken || freshTokens.access_token, freshTokens.refreshToken || freshTokens.refresh_token);
          headers['Authorization'] = `Bearer ${this.token}`;
          response = await fetch(`${this.baseUrl}${endpoint}`, {
            ...options,
            headers,
          });
        } else {
          this.setTokens(null, null);
          window.dispatchEvent(new Event('auth:unauthorized'));
        }
      } catch (e) {
        this.setTokens(null, null);
        window.dispatchEvent(new Event('auth:unauthorized'));
      }
    }

    if (response.status === 401) {
      this.setTokens(null, null);
      window.dispatchEvent(new Event('auth:unauthorized'));
    }

    if (!response.ok) {
      let errorDetail = 'API Request Failed';
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || errorJson.title || JSON.stringify(errorJson);
      } catch (e) {
        errorDetail = await response.text();
      }
      throw new Error(errorDetail);
    }

    const data = await response.json();
    return data;
  }

  // Auth
  public async login(email: string, password: string): Promise<AuthTokens> {
    const data = await this.request<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setTokens(data.accessToken || data.access_token, data.refreshToken || data.refresh_token);
    return data;
  }

  public async logout(): Promise<void> {
    if (this.refreshToken) {
      try {
        await this.request('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        });
      } catch (e) {
        console.warn('Logout server notification failed:', e);
      }
    }
    this.setTokens(null, null);
  }

  public async getProfile(): Promise<UserProfile> {
    return this.request<UserProfile>('/auth/me');
  }

  // ==========================================
  // Product Master & Categories
  // ==========================================

  public async getCategories(): Promise<ItemCategory[]> {
    return this.request<ItemCategory[]>('/items/categories');
  }

  public async createCategory(payload: ItemCategoryCreate): Promise<ItemCategory> {
    return this.request<ItemCategory>('/items/categories', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateCategory(categoryId: string, payload: ItemCategoryUpdate): Promise<ItemCategory> {
    return this.request<ItemCategory>(`/items/categories/${categoryId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteCategory(categoryId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/items/categories/${categoryId}`, {
      method: 'DELETE',
    });
  }

  public async getItems(params: GetItemsParams = {}): Promise<PaginatedResponse<Item>> {
    const query = new URLSearchParams();
    if (params.q) query.set('q', params.q);
    if (params.category_id) query.set('category_id', params.category_id);
    if (params.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params.is_active !== undefined) query.set('is_active', String(params.is_active));
    if (params.stock_status && params.stock_status !== 'all') query.set('stock_status', params.stock_status);
    if (params.sort_by) query.set('sort_by', params.sort_by);
    if (params.sort_dir) query.set('sort_dir', params.sort_dir);
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<Item>>(`/items${qs}`);
  }

  public async getItemDetail(itemId: string): Promise<ItemDetail> {
    return this.request<ItemDetail>(`/items/${itemId}`);
  }

  public async createItem(payload: ItemCreate): Promise<Item> {
    return this.request<Item>('/items', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateItem(itemId: string, payload: ItemUpdate): Promise<Item> {
    return this.request<Item>(`/items/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteItem(itemId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/items/${itemId}`, {
      method: 'DELETE',
    });
  }

  public async addVariant(itemId: string, payload: ItemVariantCreate): Promise<ItemVariant> {
    return this.request<ItemVariant>(`/items/${itemId}/variants`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateVariant(itemId: string, variantId: string, payload: ItemVariantUpdate): Promise<ItemVariant> {
    return this.request<ItemVariant>(`/items/${itemId}/variants/${variantId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteVariant(itemId: string, variantId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/items/${itemId}/variants/${variantId}`, {
      method: 'DELETE',
    });
  }

  public async addBarcode(itemId: string, variantId: string, payload: BarcodeCreate): Promise<Barcode> {
    return this.request<Barcode>(`/items/${itemId}/variants/${variantId}/barcodes`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async deleteBarcode(itemId: string, variantId: string, barcodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/items/${itemId}/variants/${variantId}/barcodes/${barcodeId}`, {
      method: 'DELETE',
    });
  }

  public async lookupBarcode(barcode: string): Promise<BarcodeLookupResponse> {
    return this.request<BarcodeLookupResponse>('/barcodes/lookup', {
      method: 'POST',
      body: JSON.stringify({ barcode }),
    });
  }

  // ==========================================
  // Warehouses & Bins
  // ==========================================
  public async getWarehouses(params?: { q?: string; is_active?: boolean }): Promise<Warehouse[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set('q', params.q);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<Warehouse[]>(`/warehouses${qs}`);
  }

  public async getWarehouseDetail(warehouseId: string): Promise<Warehouse> {
    return this.request<Warehouse>(`/warehouses/${warehouseId}`);
  }

  public async createWarehouse(payload: { code: string; name: string; address?: any }): Promise<Warehouse> {
    return this.request<Warehouse>('/warehouses', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateWarehouse(warehouseId: string, payload: { name?: string; address?: any; is_active?: boolean }): Promise<Warehouse> {
    return this.request<Warehouse>(`/warehouses/${warehouseId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteWarehouse(warehouseId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/warehouses/${warehouseId}`, {
      method: 'DELETE',
    });
  }

  public async getWarehouseBins(warehouseId: string, params?: { type?: string; is_active?: boolean; q?: string }): Promise<LocationBin[]> {
    const query = new URLSearchParams();
    if (params?.type) query.set('type', params.type);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    if (params?.q) query.set('q', params.q);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<LocationBin[]>(`/warehouses/${warehouseId}/bins${qs}`);
  }

  public async createBin(warehouseId: string, payload: { code: string; aisle?: string; rack?: string; shelf?: string; bin?: string; type: string }): Promise<LocationBin> {
    return this.request<LocationBin>(`/warehouses/${warehouseId}/bins`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateBin(warehouseId: string, binId: string, payload: { code?: string; aisle?: string; rack?: string; shelf?: string; bin?: string; type?: string; is_active?: boolean }): Promise<LocationBin> {
    return this.request<LocationBin>(`/warehouses/${warehouseId}/bins/${binId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteBin(warehouseId: string, binId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/warehouses/${warehouseId}/bins/${binId}`, {
      method: 'DELETE',
    });
  }

  // ==========================================
  // Stock Ledger & Balances
  // ==========================================
  public async getLedgerEntries(params: GetLedgerEntriesParams = {}): Promise<PaginatedResponse<StockLedgerEntry>> {
    const query = new URLSearchParams();
    if (params.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params.item_variant_id) query.set('item_variant_id', params.item_variant_id);
    if (params.transaction_type) query.set('transaction_type', params.transaction_type);
    if (params.q) query.set('q', params.q);
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<StockLedgerEntry>>(`/ledger/entries${qs}`);
  }

  public async getStockBalances(params: GetStockBalancesParams = {}): Promise<PaginatedResponse<StockBalanceCache>> {
    const query = new URLSearchParams();
    if (params.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params.location_bin_id) query.set('location_bin_id', params.location_bin_id);
    if (params.item_variant_id) query.set('item_variant_id', params.item_variant_id);
    if (params.stock_status && params.stock_status !== 'all') query.set('stock_status', params.stock_status);
    if (params.q) query.set('q', params.q);
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<StockBalanceCache>>(`/ledger/balances${qs}`);
  }

  public async transferStock(payload: { item_variant_id: string; source_bin_id: string; destination_bin_id: string; quantity: number; batch_number?: string; notes?: string }): Promise<any> {
    return this.request('/ledger/transfers', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async adjustStock(payload: { item_variant_id: string; location_bin_id: string; counted_quantity: number; reason: string; adjustment_type?: string; batch_number?: string }): Promise<any> {
    return this.request('/ledger/adjustments', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ==========================================
  // Purchasing & Goods Receipt
  // ==========================================
  public async getSuppliers(params?: { q?: string; is_active?: boolean }): Promise<Supplier[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set('q', params.q);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<Supplier[]>(`/purchase-orders/suppliers${qs}`);
  }

  public async createSupplier(payload: SupplierCreate): Promise<Supplier> {
    return this.request<Supplier>('/purchase-orders/suppliers', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateSupplier(supplierId: string, payload: SupplierUpdate): Promise<Supplier> {
    return this.request<Supplier>(`/purchase-orders/suppliers/${supplierId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteSupplier(supplierId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/purchase-orders/suppliers/${supplierId}`, {
      method: 'DELETE',
    });
  }

  public async getPurchaseOrders(params?: {
    status?: string;
    supplier_id?: string;
    warehouse_id?: string;
    q?: string;
    sort_by?: string;
    sort_dir?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<PurchaseOrder>> {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.supplier_id) query.set('supplier_id', params.supplier_id);
    if (params?.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params?.q) query.set('q', params.q);
    if (params?.sort_by) query.set('sort_by', params.sort_by);
    if (params?.sort_dir) query.set('sort_dir', params.sort_dir);
    if (params?.page) query.set('page', String(params.page));
    if (params?.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<PurchaseOrder>>(`/purchase-orders${qs}`);
  }

  public async getPurchaseOrderDetail(poId: string): Promise<PurchaseOrderDetail> {
    return this.request<PurchaseOrderDetail>(`/purchase-orders/${poId}`);
  }

  public async createPurchaseOrder(payload: PurchaseOrderCreate): Promise<PurchaseOrder> {
    return this.request<PurchaseOrder>('/purchase-orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updatePurchaseOrder(poId: string, payload: PurchaseOrderUpdate): Promise<PurchaseOrder> {
    return this.request<PurchaseOrder>(`/purchase-orders/${poId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async submitPurchaseOrder(poId: string): Promise<PurchaseOrder> {
    return this.request<PurchaseOrder>(`/purchase-orders/${poId}/submit`, {
      method: 'POST',
    });
  }

  public async approvePurchaseOrder(poId: string): Promise<PurchaseOrder> {
    return this.request<PurchaseOrder>(`/purchase-orders/${poId}/approve`, {
      method: 'POST',
    });
  }

  public async cancelPurchaseOrder(poId: string): Promise<PurchaseOrder> {
    return this.request<PurchaseOrder>(`/purchase-orders/${poId}/cancel`, {
      method: 'POST',
    });
  }

  public async deletePurchaseOrder(poId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/purchase-orders/${poId}`, {
      method: 'DELETE',
    });
  }

  public async receiveGoods(payload: GoodsReceiptCreate): Promise<GoodsReceipt> {
    return this.request<GoodsReceipt>('/purchase-orders/receive', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ==========================================
  // Sales & Order Fulfillment
  // ==========================================
  public async getCustomers(params?: { q?: string; is_active?: boolean }): Promise<Customer[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set('q', params.q);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<Customer[]>(`/sales-orders/customers${qs}`);
  }

  public async getCustomer(customerId: string): Promise<Customer> {
    return this.request<Customer>(`/sales-orders/customers/${customerId}`);
  }

  public async createCustomer(payload: CustomerCreate): Promise<Customer> {
    return this.request<Customer>('/sales-orders/customers', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateCustomer(customerId: string, payload: CustomerUpdate): Promise<Customer> {
    return this.request<Customer>(`/sales-orders/customers/${customerId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async deleteCustomer(customerId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/sales-orders/customers/${customerId}`, {
      method: 'DELETE',
    });
  }

  public async getSalesOrders(params?: {
    status?: string;
    customer_id?: string;
    warehouse_id?: string;
    q?: string;
    sort_by?: string;
    sort_dir?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<SalesOrder>> {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.customer_id) query.set('customer_id', params.customer_id);
    if (params?.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params?.q) query.set('q', params.q);
    if (params?.sort_by) query.set('sort_by', params.sort_by);
    if (params?.sort_dir) query.set('sort_dir', params.sort_dir);
    if (params?.page) query.set('page', String(params.page));
    if (params?.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<SalesOrder>>(`/sales-orders${qs}`);
  }

  public async getSalesOrderDetail(soId: string): Promise<SalesOrderDetail> {
    return this.request<SalesOrderDetail>(`/sales-orders/${soId}`);
  }

  public async createSalesOrder(payload: SalesOrderCreate): Promise<SalesOrder> {
    return this.request<SalesOrder>('/sales-orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateSalesOrder(soId: string, payload: SalesOrderUpdate): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async confirmSalesOrder(soId: string): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}/confirm`, {
      method: 'POST',
    });
  }

  public async allocateSalesOrder(soId: string, payload?: any): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}/allocate`, {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    });
  }

  public async pickSalesOrderItems(soId: string, payload: SOPickRequest): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}/pick`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async packSalesOrder(soId: string, payload: SOPackRequest): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}/pack`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async dispatchSalesOrder(soId: string, payload: SODispatchRequest): Promise<Shipment> {
    return this.request<Shipment>(`/sales-orders/${soId}/dispatch`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async cancelSalesOrder(soId: string): Promise<SalesOrder> {
    return this.request<SalesOrder>(`/sales-orders/${soId}/cancel`, {
      method: 'POST',
    });
  }

  public async deleteSalesOrder(soId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/sales-orders/${soId}`, {
      method: 'DELETE',
    });
  }

  public async processSalesReturn(soId: string, payload: SalesReturnCreate): Promise<SalesReturn> {
    return this.request<SalesReturn>(`/sales-orders/${soId}/returns`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ==========================================
  // Reports & Analytics
  // ==========================================
  public async getDashboardMetrics(warehouseId?: string): Promise<DashboardMetrics> {
    const qs = warehouseId ? `?warehouse_id=${encodeURIComponent(warehouseId)}` : '';
    return this.request<DashboardMetrics>(`/reports/dashboard${qs}`);
  }

  public async getInventoryReport(params?: { warehouse_id?: string; stock_status?: string }): Promise<InventoryReportResponse> {
    const query = new URLSearchParams();
    if (params?.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    if (params?.stock_status) query.set('stock_status', params.stock_status);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<InventoryReportResponse>(`/reports/inventory${qs}`);
  }

  public async getPurchasingReport(params?: { supplier_id?: string; warehouse_id?: string }): Promise<PurchasingReportResponse> {
    const query = new URLSearchParams();
    if (params?.supplier_id) query.set('supplier_id', params.supplier_id);
    if (params?.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PurchasingReportResponse>(`/reports/purchasing${qs}`);
  }

  public async getSalesReport(params?: { customer_id?: string; warehouse_id?: string }): Promise<SalesReportResponse> {
    const query = new URLSearchParams();
    if (params?.customer_id) query.set('customer_id', params.customer_id);
    if (params?.warehouse_id) query.set('warehouse_id', params.warehouse_id);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<SalesReportResponse>(`/reports/sales${qs}`);
  }

  public async getValuationReport(): Promise<any> {
    return this.request('/reports/valuation');
  }

  // ==========================================
  // Global Search
  // ==========================================
  public async globalSearch(query: string): Promise<GlobalSearchResponse> {
    return this.request<GlobalSearchResponse>(`/search?q=${encodeURIComponent(query)}`);
  }

  // ==========================================
  // Audit Logs (Searchable, Filterable, Paginated)
  // ==========================================
  public async getAuditLogs(params?: {
    entity_type?: string;
    action?: string;
    user_id?: string;
    entity_id?: string;
    start_date?: string;
    end_date?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<AuditLogItem>> {
    const query = new URLSearchParams();
    if (params?.entity_type) query.set('entity_type', params.entity_type);
    if (params?.action) query.set('action', params.action);
    if (params?.user_id) query.set('user_id', params.user_id);
    if (params?.entity_id) query.set('entity_id', params.entity_id);
    if (params?.start_date) query.set('start_date', params.start_date);
    if (params?.end_date) query.set('end_date', params.end_date);
    if (params?.page) query.set('page', String(params.page));
    if (params?.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<PaginatedResponse<AuditLogItem>>(`/audit${qs}`);
  }

  public async getAuditLogDetail(logId: string): Promise<AuditLogItem> {
    return this.request<AuditLogItem>(`/audit/${logId}`);
  }

  // ==========================================
  // Users & RBAC
  // ==========================================
  public async getUsers(params?: { q?: string; role_id?: string; is_active?: boolean }): Promise<UserProfile[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set('q', params.q);
    if (params?.role_id) query.set('role_id', params.role_id);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<UserProfile[]>(`/users${qs}`);
  }

  public async getUserDetail(userId: string): Promise<UserProfile> {
    return this.request<UserProfile>(`/users/${userId}`);
  }

  public async createUser(payload: UserCreateInput): Promise<UserProfile> {
    return this.request<UserProfile>('/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateUser(userId: string, payload: UserUpdateInput): Promise<UserProfile> {
    return this.request<UserProfile>(`/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async activateUser(userId: string): Promise<UserProfile> {
    return this.request<UserProfile>(`/users/${userId}/activate`, {
      method: 'POST',
    });
  }

  public async deactivateUser(userId: string): Promise<UserProfile> {
    return this.request<UserProfile>(`/users/${userId}/deactivate`, {
      method: 'POST',
    });
  }

  public async resetUserPassword(userId: string, newPassword: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    });
  }

  // ==========================================
  // Session Management
  // ==========================================
  public async getMySessions(): Promise<UserSessionItem[]> {
    return this.request<UserSessionItem[]>('/auth/sessions');
  }

  public async revokeMySession(sessionId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/auth/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  }

  public async revokeOtherSessions(): Promise<{ message: string }> {
    return this.request<{ message: string }>('/auth/sessions/revoke-others', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: this.refreshToken }),
    });
  }

  public async getUserSessions(userId: string): Promise<UserSessionItem[]> {
    return this.request<UserSessionItem[]>(`/users/${userId}/sessions`);
  }

  public async revokeUserSession(userId: string, sessionId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/users/${userId}/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  }

  // ==========================================
  // Roles & Permissions
  // ==========================================
  public async getRoles(): Promise<RoleItem[]> {
    return this.request<RoleItem[]>('/users/roles');
  }

  public async createRole(payload: RoleCreateInput): Promise<RoleItem> {
    return this.request<RoleItem>('/users/roles', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateRole(roleId: string, payload: RoleUpdateInput): Promise<RoleItem> {
    return this.request<RoleItem>(`/users/roles/${roleId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  public async getPermissions(): Promise<PermissionItem[]> {
    return this.request<PermissionItem[]>('/users/permissions');
  }

  // ==========================================
  // System Settings
  // ==========================================
  public async getSettings(): Promise<SystemSettings> {
    return this.request<SystemSettings>('/settings');
  }

  public async updateSettings(payload: SystemSettingsUpdate): Promise<SystemSettings> {
    return this.request<SystemSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  // ==========================================
  // Business Documents & Labels
  // ==========================================
  public async getDocumentPayload(docType: DocumentType, docId: string): Promise<DocumentPayload> {
    return this.request<DocumentPayload>(`/documents/${docType}/${docId}`);
  }

  public getDocumentPdfUrl(docType: DocumentType, docId: string, layout: string = 'A4'): string {
    return `${this.baseUrl}/documents/${docType}/${docId}/pdf?layout=${layout}`;
  }

  // ==========================================
  // Operations & Reliability
  // ==========================================
  public async getOperationsStatus(): Promise<SystemOperationsStatus> {
    return this.request<SystemOperationsStatus>('/operations/status');
  }

  public async getOperationalMetrics(): Promise<OperationalMetrics> {
    return this.request<OperationalMetrics>('/operations/metrics');
  }

  public async getBackups(): Promise<BackupItem[]> {
    return this.request<BackupItem[]>('/operations/backups');
  }

  public async triggerBackup(): Promise<any> {
    return this.request<any>('/operations/backups', {
      method: 'POST',
    });
  }

  public async runIntegrityCheck(): Promise<IntegrityCheckResult> {
    return this.request<IntegrityCheckResult>('/operations/integrity-check', {
      method: 'POST',
    });
  }

  public async syncUpstreamBatch(batchPayload: any): Promise<any> {
    return this.request<any>('/sync/upstream', {
      method: 'POST',
      body: JSON.stringify(batchPayload),
    });
  }

  public async syncDownstreamFeed(sinceRevision: number = 0, limit: number = 200): Promise<any> {
    return this.request<any>(`/sync/feed?since_revision=${sinceRevision}&limit=${limit}`);
  }
}

export const api = new ApiClient();
