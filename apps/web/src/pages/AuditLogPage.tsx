import React, { useEffect, useState } from 'react';
import { History, Shield, RefreshCw, Filter, Eye, ChevronLeft, ChevronRight, Search, Calendar, AlertCircle } from 'lucide-react';
import { api } from '../api/client';
import { AuditLogItem, PaginationMeta } from '@inventory/shared-types';
import { Modal } from '../components/Modal';

export const AuditLogPage: React.FC = () => {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta>({ page: 1, pageSize: 25, totalPages: 1, totalItems: 0 });
  const [selectedLog, setSelectedLog] = useState<AuditLogItem | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Filters
  const [entityType, setEntityType] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<string>('');
  const [entityIdFilter, setEntityIdFilter] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);

  const loadAuditLogs = async (page: number = currentPage) => {
    try {
      setIsLoading(true);
      const res = await api.getAuditLogs({
        entity_type: entityType || undefined,
        action: actionFilter || undefined,
        entity_id: entityIdFilter || undefined,
        start_date: startDate ? new Date(startDate).toISOString() : undefined,
        end_date: endDate ? new Date(endDate).toISOString() : undefined,
        page,
        page_size: 25,
      });
      setLogs(res.items || []);
      if (res.pagination) {
        setPagination(res.pagination);
        setCurrentPage(res.pagination.page);
      }
    } catch (err) {
      console.error('Failed to load audit logs:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAuditLogs(1);
  }, [entityType, actionFilter]);

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadAuditLogs(1);
  };

  const handleResetFilters = () => {
    setEntityType('');
    setActionFilter('');
    setEntityIdFilter('');
    setStartDate('');
    setEndDate('');
    loadAuditLogs(1);
  };

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Enterprise Compliance & System Audit Trail
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Cryptographically timestamped, append-only ledger of state mutations, security events, and user workflows
          </p>
        </div>

        <button className="btn btn-secondary" onClick={() => loadAuditLogs(currentPage)}>
          <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh Trail
        </button>
      </div>

      {/* Filters Bar */}
      <div className="card" style={{ marginBottom: '16px', padding: '14px' }}>
        <form onSubmit={handleFilterSubmit} style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            className="form-control"
            style={{ width: '160px' }}
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
          >
            <option value="">All Entities</option>
            <option value="Item">Item Master</option>
            <option value="PurchaseOrder">Purchase Order</option>
            <option value="GoodsReceipt">Goods Receipt (GRN)</option>
            <option value="SalesOrder">Sales Order</option>
            <option value="StockLedgerTransaction">Stock Ledger</option>
            <option value="User">User Account</option>
            <option value="SystemSetting">System Settings</option>
            <option value="Warehouse">Warehouse</option>
          </select>

          <select
            className="form-control"
            style={{ width: '160px' }}
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          >
            <option value="">All Actions</option>
            <option value="CREATE">CREATE</option>
            <option value="UPDATE">UPDATE</option>
            <option value="DELETE">DELETE</option>
            <option value="APPROVE">APPROVE</option>
            <option value="POST_LEDGER">POST_LEDGER</option>
            <option value="ALLOCATE">ALLOCATE</option>
            <option value="PICK">PICK</option>
            <option value="PACK">PACK</option>
            <option value="DISPATCH">DISPATCH</option>
            <option value="RESET_PASSWORD">RESET_PASSWORD</option>
          </select>

          <input
            type="text"
            className="form-control"
            style={{ width: '180px' }}
            placeholder="Filter by Entity ID..."
            value={entityIdFilter}
            onChange={(e) => setEntityIdFilter(e.target.value)}
          />

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>From:</span>
            <input
              type="date"
              className="form-control"
              style={{ width: '135px' }}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>To:</span>
            <input
              type="date"
              className="form-control"
              style={{ width: '135px' }}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>

          <button type="submit" className="btn btn-secondary">
            <Filter size={14} /> Filter
          </button>
          <button type="button" className="btn btn-outline" onClick={handleResetFilters}>
            Reset
          </button>
        </form>
      </div>

      {/* Table */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Immutable Audit Trail Records</div>
          <span className="badge badge-success">Cryptographically Sealed</span>
        </div>

        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Action</th>
                <th>Entity Type</th>
                <th>Entity Target ID</th>
                <th>Operator</th>
                <th>Client Source</th>
                <th>State Mutation Diff</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-muted)' }}>
                    No audit records matching the specified criteria.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id}>
                    <td style={{ fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {new Date(log.timestamp).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' })}
                    </td>
                    <td>
                      <span className={`badge ${
                        log.action === 'CREATE' ? 'badge-success' :
                        log.action === 'POST_LEDGER' ? 'badge-info' :
                        log.action === 'APPROVE' ? 'badge-warning' :
                        log.action === 'DISPATCH' ? 'badge-info' :
                        log.action === 'RESET_PASSWORD' ? 'badge-danger' : 'badge-default'
                      }`}>
                        {log.action}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{log.entity_type}</div>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11.5px', color: '#93c5fd' }}>
                      {log.entity_id ? `${log.entity_id.slice(0, 8)}...` : 'N/A'}
                    </td>
                    <td>
                      <div style={{ fontWeight: 500, fontSize: '12px' }}>{log.user_name || 'System Daemon'}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{log.user_email || 'daemon@system'}</div>
                    </td>
                    <td>
                      <span className="badge badge-default" style={{ fontSize: '10px' }}>
                        {log.client_type || 'WEB'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => setSelectedLog(log)}
                        style={{ padding: '4px 8px', fontSize: '11.5px' }}
                      >
                        <Eye size={13} /> View Changes Diff
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
            Showing Page {pagination.page} of {pagination.totalPages || pagination.total_pages || 1} ({pagination.totalItems || pagination.total_items || 0} Total Records)
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              className="btn btn-outline btn-sm"
              disabled={pagination.page <= 1}
              onClick={() => loadAuditLogs(pagination.page - 1)}
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <button
              className="btn btn-outline btn-sm"
              disabled={pagination.page >= (pagination.totalPages || pagination.total_pages || 1)}
              onClick={() => loadAuditLogs(pagination.page + 1)}
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* Modal: View Audit Changes */}
      <Modal
        isOpen={!!selectedLog}
        onClose={() => setSelectedLog(null)}
        title="Audit Mutation Payload & State Diff"
        footer={<button className="btn btn-primary" onClick={() => setSelectedLog(null)}>Close</button>}
      >
        {selectedLog && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
              <div>
                <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Action & Entity:</span>
                <div style={{ fontWeight: 700, fontSize: '13px' }}>{selectedLog.action} &bull; {selectedLog.entity_type}</div>
              </div>
              <div>
                <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Execution Timestamp:</span>
                <div style={{ fontWeight: 600, fontSize: '13px' }}>{new Date(selectedLog.timestamp).toLocaleString()}</div>
              </div>
              <div>
                <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Target Entity ID:</span>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#93c5fd' }}>{selectedLog.entity_id}</div>
              </div>
              <div>
                <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Operator / IP:</span>
                <div style={{ fontSize: '12px' }}>{selectedLog.user_email || 'System'} ({selectedLog.ip_address || '127.0.0.1'})</div>
              </div>
            </div>

            <label className="form-label">Captured JSON Mutation Diff</label>
            <pre style={{
              backgroundColor: '#0b1120',
              padding: '14px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-card)',
              color: '#38bdf8',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              overflowX: 'auto',
              maxHeight: '300px'
            }}>
              {JSON.stringify(selectedLog.changes, null, 2)}
            </pre>
          </div>
        )}
      </Modal>
    </div>
  );
};
