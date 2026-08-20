import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { RefreshCw, CheckCircle2, AlertTriangle, Clock, X, CloudUpload, Trash2, Wifi, WifiOff, Check } from 'lucide-react';
import { nativeBridge, OfflineMutation } from '@inventory/native-bridge';
import { api } from '../api/client';

interface SyncCenterModalProps {
  isOpen: boolean;
  onClose: () => void;
  onShowToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const SyncCenterModal: React.FC<SyncCenterModalProps> = ({ isOpen, onClose, onShowToast }) => {
  const [mutations, setMutations] = useState<OfflineMutation[]>([]);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [backendStatus, setBackendStatus] = useState<string>('Checking...');
  const [lastSyncTime, setLastSyncTime] = useState<string>(localStorage.getItem('aurastock_last_sync') || 'Never');

  const loadQueue = async () => {
    const items = await nativeBridge.getPendingMutations();
    setMutations(items);
  };

  const checkHealth = async () => {
    try {
      const res = await api.checkHealth();
      setBackendStatus(res.ok ? 'Online' : 'Offline');
    } catch {
      setBackendStatus('Offline');
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadQueue();
      checkHealth();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const pendingCount = mutations.filter(m => m.sync_status === 'PENDING_SYNC' || m.sync_status === 'RETRY_PENDING').length;
  const failedCount = mutations.filter(m => m.sync_status === 'CONFLICT' || m.sync_status === 'RETRY_PENDING').length;

  const handleSyncNow = async () => {
    setIsSyncing(true);
    try {
      const pending = mutations.filter(m => m.sync_status === 'PENDING_SYNC' || m.sync_status === 'RETRY_PENDING');
      let committedCount = 0;
      let conflictCount = 0;

      if (pending.length > 0) {
        for (const m of pending) {
          await nativeBridge.updateMutationStatus(m.operation_id, 'SYNCING');
        }
        await loadQueue();

        const batchPayload = {
          device_identifier: 'DESKTOP-CLIENT-001',
          mutations: pending.map(p => ({
            client_tx_id: p.operation_id,
            operation_type: p.operation_type,
            warehouse_id: p.warehouse_id,
            client_timestamp: p.created_at_utc || new Date().toISOString(),
            payload: p.payload
          }))
        };

        const res = await api.syncUpstreamBatch(batchPayload);
        if (res && res.acks) {
          for (const ack of res.acks) {
            if (ack.status === 'COMMITTED') {
              await nativeBridge.updateMutationStatus(ack.client_tx_id, 'SYNCED', ack.server_tx_id);
            } else if (ack.status === 'CONFLICT') {
              await nativeBridge.updateMutationStatus(ack.client_tx_id, 'CONFLICT', undefined, ack.error_message);
            } else {
              await nativeBridge.updateMutationStatus(ack.client_tx_id, 'RETRY_PENDING', undefined, ack.error_message);
            }
          }
        }
        committedCount = res?.committed_count || 0;
        conflictCount = res?.conflict_count || 0;
      }

      // Pull Downstream Changes
      await api.syncDownstreamFeed(0, 50);

      const nowStr = new Date().toLocaleTimeString();
      setLastSyncTime(nowStr);
      localStorage.setItem('aurastock_last_sync', nowStr);
      await loadQueue();

      if (onShowToast) {
        onShowToast('✓ All offline operations synchronized', 'success');
      }
    } catch (err: any) {
      if (onShowToast) {
        onShowToast(`Sync failed: ${err.message || 'Server unreachable'}`, 'error');
      }
    } finally {
      setIsSyncing(false);
    }
  };

  const handleClearSynced = async () => {
    await nativeBridge.clearSyncedMutations();
    await loadQueue();
  };

  const modalElement = (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        style={{
          maxWidth: '580px',
          width: '100%',
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.85)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CloudUpload size={18} color="#3b82f6" />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Offline Sync Center
            </h3>
          </div>
          <button className="btn btn-outline btn-sm" onClick={onClose} style={{ padding: '4px', borderRadius: '50%' }}>
            <X size={15} />
          </button>
        </div>

        <div className="modal-body" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Sync Status Grid Box */}
          <div style={{
            padding: '14px 18px',
            backgroundColor: '#131d36',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid #283550'
          }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span>Sync Status</span>
              <span style={{
                fontSize: '11.5px',
                fontWeight: 600,
                color: backendStatus === 'Online' ? '#34d399' : '#f87171',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}>
                {backendStatus === 'Online' ? <Wifi size={12} /> : <WifiOff size={12} />}
                {backendStatus}
              </span>
            </div>
            <div style={{
              height: '1px',
              backgroundColor: '#1e293b',
              marginBottom: '12px'
            }} />
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '10px',
              fontSize: '12px'
            }}>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Backend</span>
                <strong style={{ color: backendStatus === 'Online' ? '#34d399' : '#f87171' }}>{backendStatus}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Pending</span>
                <strong style={{ color: pendingCount > 0 ? '#fbbf24' : 'var(--text-primary)' }}>{pendingCount}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Last Sync</span>
                <strong style={{ color: 'var(--text-primary)' }}>{lastSyncTime}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Failed</span>
                <strong style={{ color: failedCount > 0 ? '#f87171' : 'var(--text-primary)' }}>{failedCount}</strong>
              </div>
            </div>
          </div>

          {/* Action Row */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
              Local Operation Queue (Durable SQLite/FS)
            </span>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleClearSynced}
                disabled={isSyncing || mutations.filter(m => m.sync_status === 'SYNCED').length === 0}
              >
                <Trash2 size={13} /> Clear Synced
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleSyncNow}
                disabled={isSyncing || mutations.length === 0}
              >
                <RefreshCw size={13} className={isSyncing ? 'spin' : ''} /> {isSyncing ? 'Syncing...' : 'Sync Now'}
              </button>
            </div>
          </div>

          {/* Queue Listing */}
          {mutations.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-muted)' }}>
              <CheckCircle2 size={32} color="#10b981" style={{ margin: '0 auto 8px' }} />
              <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                All local offline operations are synchronized with the central server.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
              {mutations.map(m => (
                <div key={m.operation_id} style={{
                  padding: '10px 12px',
                  backgroundColor: '#131d36',
                  border: '1px solid #283550',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <div>
                    <div style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {m.operation_type}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      ID: {m.operation_id.slice(0, 12)}... | {new Date(m.created_at_utc).toLocaleTimeString()}
                    </div>
                  </div>
                  <div>
                    <span className={`badge badge-${
                      m.sync_status === 'SYNCED' ? 'success' :
                      m.sync_status === 'CONFLICT' ? 'danger' :
                      m.sync_status === 'SYNCING' ? 'info' : 'warning'
                    }`} style={{ fontSize: '10.5px' }}>
                      {m.sync_status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );

  if (typeof document !== 'undefined') {
    return createPortal(modalElement, document.body);
  }

  return modalElement;
};
