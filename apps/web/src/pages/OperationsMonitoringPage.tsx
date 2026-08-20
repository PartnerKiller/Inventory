import React, { useEffect, useState } from 'react';
import { 
  Activity, Database, HardDrive, ShieldCheck, RefreshCw, 
  CheckCircle, AlertTriangle, XCircle, Download, Play, 
  Clock, Server, FileText, CheckCircle2
} from 'lucide-react';
import { api } from '../api/client';
import { 
  SystemOperationsStatus, BackupItem, IntegrityCheckResult, 
  OperationalMetrics 
} from '@inventory/shared-types';

export const OperationsMonitoringPage: React.FC = () => {
  const [statusData, setStatusData] = useState<SystemOperationsStatus | null>(null);
  const [metrics, setMetrics] = useState<OperationalMetrics | null>(null);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [integrityResult, setIntegrityResult] = useState<IntegrityCheckResult | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isBackingUp, setIsBackingUp] = useState<boolean>(false);
  const [isCheckingIntegrity, setIsCheckingIntegrity] = useState<boolean>(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setIsLoading(true);
      const [stat, met, bks] = await Promise.all([
        api.getOperationsStatus(),
        api.getOperationalMetrics(),
        api.getBackups(),
      ]);
      setStatusData(stat);
      setMetrics(met);
      setBackups(bks);
    } catch (err: any) {
      console.error('Failed to load operations status:', err);
      setActionError(err.message || 'Failed to retrieve operational monitoring status');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleTriggerBackup = async () => {
    try {
      setIsBackingUp(true);
      setActionError(null);
      setActionSuccess(null);
      const res = await api.triggerBackup();
      setActionSuccess(`Backup created successfully: ${res.filename} (${res.size_formatted}) with SHA-256 integrity verification.`);
      // Reload backups & status
      await loadData();
    } catch (err: any) {
      console.error('Backup trigger failed:', err);
      setActionError(err.message || 'Database backup generation failed');
    } finally {
      setIsBackingUp(false);
    }
  };

  const handleRunIntegrityCheck = async () => {
    try {
      setIsCheckingIntegrity(true);
      setActionError(null);
      setActionSuccess(null);
      const res = await api.runIntegrityCheck();
      setIntegrityResult(res);
      if (res.overall_status === 'HEALTHY') {
        setActionSuccess(`Data integrity verified: All ${res.checks_performed} stock invariant checks passed without discrepancies.`);
      } else {
        setActionError(`Data integrity warning: ${res.discrepancies_count} discrepancies detected across audited records.`);
      }
    } catch (err: any) {
      console.error('Integrity check failed:', err);
      setActionError(err.message || 'Data integrity verification failed');
    } finally {
      setIsCheckingIntegrity(false);
    }
  };

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / (3600 * 24));
    const h = Math.floor((seconds % (3600 * 24)) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    return `${m}m ${s}s`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            System Operations & Reliability Monitoring
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            PostgreSQL backup automation, database latency metrics, and read-only ledger invariant reconciliation
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={loadData} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh Status
          </button>
        </div>
      </div>

      {/* Notifications */}
      {actionSuccess && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: 'var(--radius-sm)',
          color: '#34d399',
          fontSize: '13px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <CheckCircle size={16} /> {actionSuccess}
        </div>
      )}

      {actionError && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-sm)',
          color: '#f87171',
          fontSize: '13px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <AlertTriangle size={16} /> {actionError}
        </div>
      )}

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
        {/* System Health */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600 }}>API System Status</span>
            <Activity size={18} color="var(--primary)" />
          </div>
          <div style={{ marginTop: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              width: '10px', height: '10px', borderRadius: '50%',
              backgroundColor: statusData?.status === 'OPERATIONAL' ? '#10b981' : '#ef4444'
            }} />
            <span style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)' }}>
              {statusData?.status || 'CHECKING...'}
            </span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Uptime: {statusData ? formatUptime(statusData.metrics_summary.uptime_seconds) : '-'}
          </div>
        </div>

        {/* Database Connectivity */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600 }}>Database Latency</span>
            <Database size={18} color="#38bdf8" />
          </div>
          <div style={{ marginTop: '10px', display: 'flex', alignItems: 'baseline', gap: '4px' }}>
            <span style={{ fontSize: '24px', fontWeight: 800, color: '#38bdf8' }}>
              {statusData?.database.latency_ms !== undefined ? `${statusData.database.latency_ms}` : '-'}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>ms</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Engine: {statusData?.database.engine || 'PostgreSQL 16'}
          </div>
        </div>

        {/* Operational Requests */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600 }}>Total Handled Requests</span>
            <Server size={18} color="#a78bfa" />
          </div>
          <div style={{ marginTop: '10px', fontSize: '24px', fontWeight: 800, color: '#a78bfa' }}>
            {statusData?.metrics_summary.total_requests.toLocaleString() || '0'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Avg Latency: {statusData?.metrics_summary.avg_latency_ms || 0}ms (p95: {statusData?.metrics_summary.p95_latency_ms || 0}ms)
          </div>
        </div>

        {/* Backup Status */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 600 }}>Backup Verification</span>
            <ShieldCheck size={18} color="#10b981" />
          </div>
          <div style={{ marginTop: '10px', fontSize: '24px', fontWeight: 800, color: '#10b981' }}>
            {backups.length} <span style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text-muted)' }}>Snapshots</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Retention: 7 historical snapshots with SHA-256
          </div>
        </div>
      </div>

      {/* Main Operations Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        {/* SECTION 1: DATABASE BACKUP MANAGEMENT */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div className="card-title">PostgreSQL Database Backups</div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0 }}>
                Automated gzip compressed backups with SHA-256 integrity verification
              </p>
            </div>
            <button 
              className="btn btn-primary btn-sm" 
              onClick={handleTriggerBackup} 
              disabled={isBackingUp}
            >
              {isBackingUp ? (
                <>
                  <RefreshCw size={14} className="spin" /> Generating...
                </>
              ) : (
                <>
                  <Play size={14} /> Trigger Backup
                </>
              )}
            </button>
          </div>

          <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
            {backups.length === 0 ? (
              <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                No backups recorded yet. Click "Trigger Backup" to generate an on-demand snapshot.
              </div>
            ) : (
              <table className="table" style={{ width: '100%', fontSize: '12px' }}>
                <thead>
                  <tr>
                    <th>Archive File</th>
                    <th>Size</th>
                    <th>SHA-256 Checksum</th>
                    <th>Created At</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {backups.map((b, idx) => (
                    <tr key={idx}>
                      <td style={{ fontWeight: 600, fontFamily: 'monospace' }}>{b.filename}</td>
                      <td>{b.size_formatted}</td>
                      <td style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }} title={b.checksum_sha256}>
                        {b.checksum_sha256.substring(0, 10)}...
                      </td>
                      <td>{new Date(b.created_at).toLocaleString()}</td>
                      <td>
                        <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <CheckCircle2 size={12} /> Verified
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* SECTION 2: READ-ONLY DATA INTEGRITY AUDIT */}
        <div className="card">
          <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div className="card-title">Data Integrity & Ledger Invariant Audit</div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0 }}>
                Verifies available = on_hand - allocated & immutable ledger sums
              </p>
            </div>
            <button 
              className="btn btn-secondary btn-sm" 
              onClick={handleRunIntegrityCheck} 
              disabled={isCheckingIntegrity}
            >
              {isCheckingIntegrity ? (
                <>
                  <RefreshCw size={14} className="spin" /> Auditing...
                </>
              ) : (
                <>
                  <ShieldCheck size={14} /> Run Invariant Audit
                </>
              )}
            </button>
          </div>

          <div>
            {integrityResult ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{
                  padding: '12px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: integrityResult.overall_status === 'HEALTHY' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                  border: `1px solid ${integrityResult.overall_status === 'HEALTHY' ? '#10b981' : '#ef4444'}`,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {integrityResult.overall_status === 'HEALTHY' ? <CheckCircle size={18} color="#10b981" /> : <XCircle size={18} color="#ef4444" />}
                    <div>
                      <strong style={{ color: integrityResult.overall_status === 'HEALTHY' ? '#10b981' : '#ef4444', fontSize: '13px' }}>
                        {integrityResult.overall_status === 'HEALTHY' ? 'All Invariants Fully Verified' : 'Discrepancies Detected'}
                      </strong>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {integrityResult.checks_performed} database records audited across 5 structural invariant rules
                      </div>
                    </div>
                  </div>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {new Date(integrityResult.audited_at).toLocaleTimeString()}
                  </span>
                </div>

                {integrityResult.discrepancies.length > 0 && (
                  <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
                    <table className="table" style={{ width: '100%', fontSize: '11px' }}>
                      <thead>
                        <tr>
                          <th>Severity</th>
                          <th>Entity</th>
                          <th>Description</th>
                          <th>Expected</th>
                          <th>Actual</th>
                        </tr>
                      </thead>
                      <tbody>
                        {integrityResult.discrepancies.map((d, i) => (
                          <tr key={i}>
                            <td>
                              <span className={`badge ${d.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'}`}>
                                {d.severity}
                              </span>
                            </td>
                            <td>{d.entity_type} ({d.entity_id.substring(0, 8)})</td>
                            <td>{d.description}</td>
                            <td>{d.expected}</td>
                            <td>{d.actual}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                Click "Run Invariant Audit" to scan the stock ledger, balance projections, purchase receipts, and sales dispatches for consistency.
              </div>
            )}

            {/* Invariants specification checklist */}
            <div style={{ marginTop: '16px', padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '11.5px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                Authoritative Invariants Verified:
              </span>
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11.5px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                <li><code>available_quantity = on_hand_quantity - allocated_quantity</code></li>
                <li><code>on_hand_quantity &gt;= 0</code> and <code>allocated_quantity &gt;= 0</code></li>
                <li><code>sum(StockLedgerEntry.quantity_delta) == StockBalanceCache.on_hand_quantity</code></li>
                <li><code>POLineItem.quantity_received &lt;= POLineItem.quantity_ordered</code></li>
                <li><code>SOLineItem.quantity_shipped &lt;= SOLineItem.quantity_ordered</code></li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
