import React, { useEffect, useState } from 'react';
import {
  Boxes, Warehouse, AlertTriangle, DollarSign, ShoppingCart,
  TrendingUp, ArrowRightLeft, Send, Truck, Package, RotateCcw,
  CheckCircle, ArrowRight, RefreshCw, Layers, ShieldAlert, BarChart3
} from 'lucide-react';
import { api } from '../api/client';
import { DashboardMetrics, Warehouse as WarehouseType } from '@inventory/shared-types';
import { NavPage } from '../components/Sidebar';

interface DashboardPageProps {
  onNavigate: (page: NavPage) => void;
  activeWarehouse?: string;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ onNavigate, activeWarehouse }) => {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadData = async (whId?: string) => {
    try {
      setIsLoading(true);
      const data = await api.getDashboardMetrics(whId || undefined);
      setMetrics(data);
    } catch (err) {
      console.error('Failed to load dashboard metrics:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData(activeWarehouse);
  }, [activeWarehouse]);

  if (isLoading && !metrics) {
    return (
      <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <RefreshCw size={28} className="spin" style={{ margin: '0 auto 12px' }} />
        <div>Loading real-time enterprise inventory telemetry...</div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Operational Command Center
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Real-time stock ledger synchronization, fulfillment queues, and multi-facility intelligence
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button className="btn btn-primary btn-sm" onClick={() => onNavigate('sales')}>
            <Send size={14} /> Fulfill Orders
          </button>
        </div>
      </div>

      {/* Operational Alerts */}
      {metrics?.operational_alerts && metrics.operational_alerts.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '18px' }}>
          {metrics.operational_alerts.map((alert, idx) => (
            <div
              key={idx}
              style={{
                padding: '12px 16px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: alert.level === 'CRITICAL' ? 'rgba(239, 68, 68, 0.12)' : 'rgba(245, 158, 11, 0.12)',
                border: `1px solid ${alert.level === 'CRITICAL' ? '#ef4444' : '#f59e0b'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <AlertTriangle size={18} color={alert.level === 'CRITICAL' ? '#f87171' : '#fbbf24'} />
                <div>
                  <div style={{ fontWeight: 700, fontSize: '13.5px', color: alert.level === 'CRITICAL' ? '#fca5a5' : '#fde68a' }}>
                    {alert.title}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '1px' }}>
                    {alert.message}
                  </div>
                </div>
              </div>

              {alert.link_tab && (
                <button
                  className="btn btn-outline btn-sm"
                  style={{ fontSize: '11.5px', borderColor: 'currentColor', color: alert.level === 'CRITICAL' ? '#f87171' : '#fbbf24' }}
                  onClick={() => onNavigate(alert.link_tab === 'purchasing' ? 'purchasing' : 'items')}
                >
                  Resolve Now <ArrowRight size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* KPI Cards Row 1: Stock Quantities & Master Data */}
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: '16px' }}>
        <div className="metric-card">
          <div>
            <div className="metric-label">Total On-Hand Units</div>
            <div className="metric-value">
              {metrics?.total_on_hand_units?.toLocaleString() ?? '0'}
            </div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
              Physical units in bins
            </div>
          </div>
          <div className="metric-icon-box" style={{ backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
            <Boxes size={20} />
          </div>
        </div>

        <div className="metric-card">
          <div>
            <div className="metric-label">Total Allocated Units</div>
            <div className="metric-value" style={{ color: '#818cf8' }}>
              {metrics?.total_allocated_units?.toLocaleString() ?? '0'}
            </div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
              Reserved for open SOs
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
              {metrics?.total_available_units?.toLocaleString() ?? '0'}
            </div>
            <div style={{ fontSize: '11.5px', color: '#10b981', marginTop: '4px', fontWeight: 600 }}>
              On Hand &minus; Allocated
            </div>
          </div>
          <div className="metric-icon-box" style={{ backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#10b981' }}>
            <CheckCircle size={20} />
          </div>
        </div>

        <div className="metric-card">
          <div>
            <div className="metric-label">Inventory Valuation</div>
            <div className="metric-value" style={{ color: '#93c5fd' }}>
              ${metrics?.total_valuation?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '0.00'}
            </div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
              Standard/FIFO basis
            </div>
          </div>
          <div className="metric-icon-box" style={{ backgroundColor: 'rgba(14, 165, 233, 0.15)', color: '#0ea5e9' }}>
            <DollarSign size={20} />
          </div>
        </div>
      </div>

      {/* Row 2: Fulfillment Funnel & Queues */}
      <div className="card" style={{ marginBottom: '18px', padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <div>
            <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Fulfillment Pipeline Queues
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '8px' }}>
              Active customer orders by operational stage
            </span>
          </div>
          <button className="btn btn-outline btn-sm" onClick={() => onNavigate('sales')}>
            Open Fulfillment Workspace
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '14px' }}>
          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Pending PO Approvals</div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: '#f59e0b', marginTop: '2px' }}>
              {metrics?.pending_pos ?? 0} Inbound
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>Awaiting Purchasing Review</div>
          </div>

          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Awaiting Stock Picking</div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: '#38bdf8', marginTop: '2px' }}>
              {metrics?.orders_awaiting_picking ?? 0} Orders
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>Allocated & Ready to Pick</div>
          </div>

          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Awaiting Packaging</div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: '#a78bfa', marginTop: '2px' }}>
              {metrics?.orders_awaiting_packing ?? 0} Orders
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>Picked & Staged</div>
          </div>

          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Ready for Dispatch</div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: '#34d399', marginTop: '2px' }}>
              {metrics?.orders_awaiting_dispatch ?? 0} Orders
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>Packed & Staged at Dock</div>
          </div>
        </div>
      </div>

      {/* Row 3: Recent Activity Feeds */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '18px' }}>
        {/* Recent Stock Movements */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Live Stock Ledger Movements</div>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Immutable double-entry inventory journal
              </div>
            </div>
            <button className="btn btn-outline btn-sm" onClick={() => onNavigate('ledger')}>
              Full Journal
            </button>
          </div>

          <div className="table-wrapper">
            <table className="data-table" style={{ fontSize: '12px' }}>
              <thead>
                <tr>
                  <th>Tx #</th>
                  <th>Type</th>
                  <th>SKU & Variant</th>
                  <th>Qty</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {metrics?.recent_transactions?.map((tx) => (
                  <tr key={tx.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>
                      {tx.transaction_number}
                    </td>
                    <td>
                      <span className={`badge ${
                        tx.transaction_type === 'PURCHASE_RECEIPT' ? 'badge-success' :
                        tx.transaction_type === 'SALES_SHIPMENT' ? 'badge-danger' :
                        tx.transaction_type === 'TRANSFER_OUT' || tx.transaction_type === 'TRANSFER_IN' ? 'badge-info' : 'badge-warning'
                      }`} style={{ fontSize: '10.5px' }}>
                        {tx.transaction_type}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{tx.item_sku}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{tx.variant_name}</div>
                    </td>
                    <td style={{ fontWeight: 700 }}>
                      {tx.quantity} {tx.uom}
                    </td>
                    <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {new Date(tx.posted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Sales Orders & Receipts Feed */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Recent Order Activity</div>
              <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Inbound receipts & outbound sales
              </div>
            </div>
            <button className="btn btn-outline btn-sm" onClick={() => onNavigate('reports')}>
              All Reports
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {metrics?.recent_sales_orders?.map((so) => (
              <div
                key={so.id}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--bg-app)',
                  border: '1px solid var(--border-subtle)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd', fontSize: '12px' }}>
                      {so.so_number}
                    </span>
                    <span className="badge badge-info" style={{ fontSize: '10px' }}>{so.status}</span>
                  </div>
                  <div style={{ fontSize: '12px', fontWeight: 600, marginTop: '2px' }}>{so.customer_name}</div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: 800, fontSize: '13px', color: '#34d399' }}>
                    ${so.total_amount.toFixed(2)}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {new Date(so.ordered_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
