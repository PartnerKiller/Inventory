import React, { useEffect, useState } from 'react';
import {
  BarChart3, Download, DollarSign, TrendingUp, ShieldAlert,
  PieChart, RefreshCw, Boxes, ShoppingCart, Send, Layers,
  Search, AlertTriangle, CheckCircle, Package, ArrowRight
} from 'lucide-react';
import { api } from '../api/client';
import {
  InventoryReportResponse, PurchasingReportResponse, SalesReportResponse,
  ValuationReportResponse, Warehouse as WarehouseType, Supplier, Customer
} from '@inventory/shared-types';

export const ReportsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'inventory' | 'purchasing' | 'sales' | 'valuation'>('inventory');

  // Master lookup data
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);

  // Report States
  const [invReport, setInvReport] = useState<InventoryReportResponse | null>(null);
  const [poReport, setPoReport] = useState<PurchasingReportResponse | null>(null);
  const [soReport, setSoReport] = useState<SalesReportResponse | null>(null);
  const [valReport, setValReport] = useState<ValuationReportResponse | null>(null);

  // Filters
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<string>('');
  const [selectedSupplierId, setSelectedSupplierId] = useState<string>('');
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>('');
  const [stockStatusFilter, setStockStatusFilter] = useState<string>('ALL');

  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Master Data Loader
  const loadMasterData = async () => {
    try {
      const [whs, sups, custs] = await Promise.all([
        api.getWarehouses(),
        api.getSuppliers(),
        api.getCustomers(),
      ]);
      setWarehouses(whs);
      setSuppliers(sups);
      setCustomers(custs);
    } catch (err) {
      console.error('Failed to load master lookup data for reports:', err);
    }
  };

  // Report Loaders
  const loadCurrentTabReport = async () => {
    try {
      setIsLoading(true);
      if (activeTab === 'inventory') {
        const data = await api.getInventoryReport({
          warehouse_id: selectedWarehouseId || undefined,
          stock_status: stockStatusFilter !== 'ALL' ? stockStatusFilter : undefined,
        });
        setInvReport(data);
      } else if (activeTab === 'purchasing') {
        const data = await api.getPurchasingReport({
          supplier_id: selectedSupplierId || undefined,
          warehouse_id: selectedWarehouseId || undefined,
        });
        setPoReport(data);
      } else if (activeTab === 'sales') {
        const data = await api.getSalesReport({
          customer_id: selectedCustomerId || undefined,
          warehouse_id: selectedWarehouseId || undefined,
        });
        setSoReport(data);
      } else if (activeTab === 'valuation') {
        const data = await api.getValuationReport();
        setValReport(data);
      }
    } catch (err) {
      console.error(`Failed to load ${activeTab} report:`, err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadMasterData();
  }, []);

  useEffect(() => {
    loadCurrentTabReport();
  }, [activeTab, selectedWarehouseId, selectedSupplierId, selectedCustomerId, stockStatusFilter]);

  const handleExportCsv = () => {
    window.open('/api/v1/reports/valuation/export-csv', '_blank');
  };

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Operational Reporting & Intelligence
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Cross-functional inventory, purchasing, sales fulfillment, and financial valuation analytics
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={loadCurrentTabReport}>
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh
          </button>
          {activeTab === 'valuation' && (
            <button className="btn btn-primary" onClick={handleExportCsv}>
              <Download size={15} /> Export Valuation CSV
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '16px' }}>
        <button
          className={`btn ${activeTab === 'inventory' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('inventory')}
        >
          <Boxes size={15} /> Inventory Reports
        </button>
        <button
          className={`btn ${activeTab === 'purchasing' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('purchasing')}
        >
          <ShoppingCart size={15} /> Purchasing Reports
        </button>
        <button
          className={`btn ${activeTab === 'sales' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('sales')}
        >
          <Send size={15} /> Sales & Fulfillment Reports
        </button>
        <button
          className={`btn ${activeTab === 'valuation' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('valuation')}
        >
          <DollarSign size={15} /> Operational Valuation
        </button>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: INVENTORY REPORTS */}
      {/* ========================================================================= */}
      {activeTab === 'inventory' && (
        <div>
          {/* Summary KPIs */}
          <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '16px' }}>
            <div className="metric-card">
              <div>
                <div className="metric-label">Reported Bins & SKUs</div>
                <div className="metric-value">{invReport?.total_items_reported ?? 0} Positions</div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
                <Boxes size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Total On Hand</div>
                <div className="metric-value">{invReport?.total_on_hand?.toLocaleString() ?? 0}</div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(14, 165, 233, 0.15)', color: '#0ea5e9' }}>
                <Layers size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Allocated to Sales</div>
                <div className="metric-value" style={{ color: '#818cf8' }}>
                  {invReport?.total_allocated?.toLocaleString() ?? 0}
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)', color: '#818cf8' }}>
                <Package size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Available to Promise</div>
                <div className="metric-value" style={{ color: '#34d399' }}>
                  {invReport?.total_available?.toLocaleString() ?? 0}
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <CheckCircle size={20} />
              </div>
            </div>
          </div>

          {/* Filter Bar */}
          <div className="card" style={{ marginBottom: '16px', padding: '12px 16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1.5fr auto', gap: '12px', alignItems: 'center' }}>
              <div>
                <select
                  className="form-control"
                  style={{ height: '34px', fontSize: '13px' }}
                  value={selectedWarehouseId}
                  onChange={(e) => setSelectedWarehouseId(e.target.value)}
                >
                  <option value="">All Warehouse Facilities</option>
                  {warehouses.map(w => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '34px', fontSize: '13px' }}
                  value={stockStatusFilter}
                  onChange={(e) => setStockStatusFilter(e.target.value)}
                >
                  <option value="ALL">All Stock Statuses</option>
                  <option value="IN_STOCK">In Stock</option>
                  <option value="LOW_STOCK">Low Stock (At or Below Reorder Point)</option>
                  <option value="OUT_OF_STOCK">Out of Stock (Zero Units)</option>
                </select>
              </div>

              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Live double-entry balances
              </div>
            </div>
          </div>

          {/* Inventory Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Product & Variant</th>
                  <th>Facility</th>
                  <th>Bin Code</th>
                  <th style={{ textAlign: 'right' }}>On Hand</th>
                  <th style={{ textAlign: 'right' }}>Allocated</th>
                  <th style={{ textAlign: 'right' }}>Available</th>
                  <th style={{ textAlign: 'right' }}>Reorder Pt</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                      <RefreshCw size={20} className="spin" style={{ margin: '0 auto 6px' }} />
                      <div>Generating inventory report...</div>
                    </td>
                  </tr>
                ) : invReport?.items?.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                      No inventory balances found matching selected filters.
                    </td>
                  </tr>
                ) : (
                  invReport?.items?.map((item, idx) => (
                    <tr key={idx}>
                      <td>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>
                          {item.sku}
                        </div>
                        <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                          {item.item_name} ({item.variant_name})
                        </div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{item.warehouse_code}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.warehouse_name}</div>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{item.bin_code}</span>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{item.quantity_on_hand}</td>
                      <td style={{ textAlign: 'right', color: '#818cf8', fontWeight: 600 }}>{item.quantity_allocated}</td>
                      <td style={{ textAlign: 'right', color: '#34d399', fontWeight: 700 }}>{item.quantity_available}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{item.reorder_point}</td>
                      <td>
                        <span className={`badge ${
                          item.status === 'OUT_OF_STOCK' ? 'badge-danger' :
                          item.status === 'LOW_STOCK' ? 'badge-warning' : 'badge-success'
                        }`}>
                          {item.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: PURCHASING REPORTS */}
      {/* ========================================================================= */}
      {activeTab === 'purchasing' && (
        <div>
          {/* KPIs */}
          <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '16px' }}>
            <div className="metric-card">
              <div>
                <div className="metric-label">Total Purchasing Spend</div>
                <div className="metric-value" style={{ color: '#93c5fd' }}>
                  ${poReport?.total_spend?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '0.00'}
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
                <DollarSign size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Purchase Orders</div>
                <div className="metric-value">{poReport?.total_pos ?? 0} POs</div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(14, 165, 233, 0.15)', color: '#0ea5e9' }}>
                <ShoppingCart size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Pending Approval</div>
                <div className="metric-value" style={{ color: '#f59e0b' }}>
                  {poReport?.pending_approval_count ?? 0} Orders
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b' }}>
                <AlertTriangle size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">In-Flight Partial Receipts</div>
                <div className="metric-value" style={{ color: '#38bdf8' }}>
                  {poReport?.partial_receipt_count ?? 0} Orders
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                <Layers size={20} />
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="card" style={{ marginBottom: '16px', padding: '12px 16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1.5fr', gap: '12px' }}>
              <select
                className="form-control"
                style={{ height: '34px', fontSize: '13px' }}
                value={selectedSupplierId}
                onChange={(e) => setSelectedSupplierId(e.target.value)}
              >
                <option value="">All Suppliers</option>
                {suppliers.map(s => (
                  <option key={s.id} value={s.id}>{s.name} ({s.code})</option>
                ))}
              </select>

              <select
                className="form-control"
                style={{ height: '34px', fontSize: '13px' }}
                value={selectedWarehouseId}
                onChange={(e) => setSelectedWarehouseId(e.target.value)}
              >
                <option value="">All Destination Warehouses</option>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Purchasing Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>PO Number</th>
                  <th>Supplier</th>
                  <th>Target Facility</th>
                  <th>Status</th>
                  <th>Ordered Date</th>
                  <th style={{ textAlign: 'right' }}>Total Spend</th>
                  <th style={{ textAlign: 'right' }}>Ordered</th>
                  <th style={{ textAlign: 'right' }}>Received</th>
                  <th style={{ textAlign: 'right' }}>Outstanding</th>
                </tr>
              </thead>
              <tbody>
                {poReport?.items?.map((item) => (
                  <tr key={item.po_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>
                      {item.po_number}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{item.supplier_name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.supplier_code}</div>
                    </td>
                    <td>{item.warehouse_code}</td>
                    <td>
                      <span className={`badge ${
                        item.status === 'COMPLETED' ? 'badge-success' :
                        item.status === 'PARTIALLY_RECEIVED' ? 'badge-info' :
                        item.status === 'APPROVED' ? 'badge-warning' : 'badge-default'
                      }`}>
                        {item.status}
                      </span>
                    </td>
                    <td style={{ fontSize: '12px' }}>{new Date(item.ordered_at).toLocaleDateString()}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>${item.total_amount.toFixed(2)}</td>
                    <td style={{ textAlign: 'right' }}>{item.total_ordered_qty}</td>
                    <td style={{ textAlign: 'right', color: '#34d399', fontWeight: 600 }}>{item.total_received_qty}</td>
                    <td style={{ textAlign: 'right', color: item.outstanding_qty > 0 ? '#f59e0b' : 'var(--text-muted)' }}>
                      {item.outstanding_qty}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: SALES REPORTS */}
      {/* ========================================================================= */}
      {activeTab === 'sales' && (
        <div>
          {/* KPIs */}
          <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '16px' }}>
            <div className="metric-card">
              <div>
                <div className="metric-label">Total Gross Sales Value</div>
                <div className="metric-value" style={{ color: '#34d399' }}>
                  ${soReport?.total_sales_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '0.00'}
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <DollarSign size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Allocation Queue</div>
                <div className="metric-value" style={{ color: '#818cf8' }}>
                  {soReport?.allocation_queue_count ?? 0} Orders
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(99, 102, 241, 0.15)', color: '#818cf8' }}>
                <Boxes size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Picking Queue</div>
                <div className="metric-value" style={{ color: '#38bdf8' }}>
                  {soReport?.picking_queue_count ?? 0} Orders
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                <Package size={20} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Dispatch Queue</div>
                <div className="metric-value" style={{ color: '#fbbf24' }}>
                  {soReport?.dispatch_queue_count ?? 0} Orders
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(251, 191, 36, 0.15)', color: '#fbbf24' }}>
                <Send size={20} />
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="card" style={{ marginBottom: '16px', padding: '12px 16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1.5fr', gap: '12px' }}>
              <select
                className="form-control"
                style={{ height: '34px', fontSize: '13px' }}
                value={selectedCustomerId}
                onChange={(e) => setSelectedCustomerId(e.target.value)}
              >
                <option value="">All Customers</option>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                ))}
              </select>

              <select
                className="form-control"
                style={{ height: '34px', fontSize: '13px' }}
                value={selectedWarehouseId}
                onChange={(e) => setSelectedWarehouseId(e.target.value)}
              >
                <option value="">All Fulfillment Warehouses</option>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Sales Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>SO Number</th>
                  <th>Customer</th>
                  <th>Origin Facility</th>
                  <th>Status</th>
                  <th>Ordered Date</th>
                  <th style={{ textAlign: 'right' }}>Total Value</th>
                  <th style={{ textAlign: 'right' }}>Ordered</th>
                  <th style={{ textAlign: 'right' }}>Allocated</th>
                  <th style={{ textAlign: 'right' }}>Shipped</th>
                  <th style={{ textAlign: 'right' }}>Returned</th>
                </tr>
              </thead>
              <tbody>
                {soReport?.items?.map((item) => (
                  <tr key={item.so_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>
                      {item.so_number}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{item.customer_name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.customer_code}</div>
                    </td>
                    <td>{item.warehouse_code}</td>
                    <td>
                      <span className={`badge ${
                        item.status === 'SHIPPED' ? 'badge-success' :
                        item.status === 'PACKED' ? 'badge-info' :
                        item.status === 'ALLOCATED' ? 'badge-warning' : 'badge-default'
                      }`}>
                        {item.status}
                      </span>
                    </td>
                    <td style={{ fontSize: '12px' }}>{new Date(item.ordered_at).toLocaleDateString()}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: '#34d399' }}>${item.total_amount.toFixed(2)}</td>
                    <td style={{ textAlign: 'right' }}>{item.total_ordered_qty}</td>
                    <td style={{ textAlign: 'right', color: '#818cf8' }}>{item.total_allocated_qty}</td>
                    <td style={{ textAlign: 'right', color: '#34d399', fontWeight: 700 }}>{item.total_shipped_qty}</td>
                    <td style={{ textAlign: 'right', color: item.total_returned_qty > 0 ? '#f87171' : 'var(--text-muted)' }}>
                      {item.total_returned_qty}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: VALUATION */}
      {/* ========================================================================= */}
      {activeTab === 'valuation' && (
        <div>
          <div className="metrics-grid" style={{ gridTemplateColumns: '1fr 1fr 1fr', marginBottom: '16px' }}>
            <div className="metric-card">
              <div>
                <div className="metric-label">Total Asset Valuation</div>
                <div className="metric-value" style={{ color: '#34d399' }}>
                  ${valReport?.total_inventory_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '0.00'}
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Base Currency: {valReport?.currency || 'USD'}
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
                <DollarSign size={24} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Valued SKUs</div>
                <div className="metric-value">{valReport?.items?.length || 0} Products</div>
                <div style={{ fontSize: '11.5px', color: '#60a5fa', marginTop: '4px' }}>
                  Double-Entry Reconciled
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(37, 99, 235, 0.15)', color: '#3b82f6' }}>
                <PieChart size={24} />
              </div>
            </div>

            <div className="metric-card">
              <div>
                <div className="metric-label">Valuation Basis</div>
                <div className="metric-value">Operational Estimate</div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  On-Hand &times; Configured Cost Basis
                </div>
              </div>
              <div className="metric-icon-box" style={{ backgroundColor: 'rgba(14, 165, 233, 0.15)', color: '#0ea5e9' }}>
                <TrendingUp size={24} />
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">Detailed Product Valuation Breakdown</div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Operational inventory valuation estimate based on current on-hand units and configured cost basis. Dynamic FIFO layer depletion is deferred to Phase 3.
                </div>
              </div>
              <span className="badge badge-info">Operational Estimate</span>
            </div>

            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>SKU Code</th>
                    <th>Item & Variant Title</th>
                    <th>Method</th>
                    <th>Total In-Stock Qty</th>
                    <th>Unit Cost ($)</th>
                    <th>Extended Asset Valuation ($)</th>
                  </tr>
                </thead>
                <tbody>
                  {valReport?.items?.map((item: any) => (
                    <tr key={item.item_id + item.name}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>
                        {item.sku}
                      </td>
                      <td style={{ fontWeight: 600 }}>{item.name}</td>
                      <td>
                        <span className="badge badge-info" style={{ fontSize: '10.5px' }}>
                          {item.valuation_method}
                        </span>
                      </td>
                      <td style={{ fontWeight: 700, fontSize: '14px' }}>{item.total_quantity}</td>
                      <td>${item.unit_cost.toFixed(2)}</td>
                      <td style={{ fontWeight: 800, color: '#34d399', fontSize: '14.5px' }}>
                        ${item.total_valuation.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
