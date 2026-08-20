import React, { useState, useEffect } from 'react';
import { RefreshCw, CheckCircle2, AlertTriangle, Clock, X, CloudUpload, Trash2 } from 'lucide-react';
import { nativeBridge, OfflineMutation } from '@inventory/native-bridge';
import { api } from '../api/client';

interface SyncCenterModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SyncCenterModal: React.FC<SyncCenterModalProps> = ({ isOpen, onClose }) => {
  const [mutations, setMutations] = useState<OfflineMutation[]>([]);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);

  const loadQueue = async () => {
    const items = await nativeBridge.getPendingMutations();
    setMutations(items);
  };

  useEffect(() => {
    if (isOpen) {
      loadQueue();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSyncNow = async () => {
    setIsSyncing(true);
    setSyncResult(null);
    try {
      const pending = mutations.filter(m => m.sync_status === 'PENDING_SYNC' || m.sync_status === 'RETRY_PENDING');
      let committedCount = 0;
      let conflictCount = 0;
      let rejectedCount = 0;

      if (pending.length > 0) {
        // Mark SYNCING
        for (const m of pending) {
          await nativeBridge.updateMutationStatus(m.operation_id, 'SYNCING');
        }
        await loadQueue();

        // Dispatch upstream batch
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
        rejectedCount = res?.rejected_count || 0;
      }

      // Downstream Delta Feed Pull
      const feedRes = await api.syncDownstreamFeed(0, 50);
      const downstreamChanges = feedRes?.count || 0;

      setSyncResult(`Bidirectional sync complete: ↑ ${committedCount} uploaded (${conflictCount} conflicts), ↓ ${downstreamChanges} downloaded from server.`);
      await loadQueue();
    } catch (err: any) {
      setSyncResult(`Sync failed: ${err.message || 'Network error'}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleClearSynced = async () => {
    await nativeBridge.clearSyncedMutations();
    await loadQueue();
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-container" style={{ maxWidth: '640px', width: '100%' }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CloudUpload size={18} color="#3b82f6" />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>Offline Sync Center</h3>
          </div>
          <button className="btn-icon" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Total Queued Mutations: <strong>{mutations.length}</strong>
              </span>
            </div>
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

          {syncResult && (
            <div style={{
              padding: '10px 14px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '12.5px',
              marginBottom: '16px',
              backgroundColor: syncResult.includes('failed') ? 'var(--danger-bg)' : 'var(--success-bg)',
              color: syncResult.includes('failed') ? '#f87171' : '#34d399',
              border: `1px solid ${syncResult.includes('failed') ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)'}`
            }}>
              {syncResult}
            </div>
          )}

          {mutations.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '36px', color: 'var(--text-muted)' }}>
              <CheckCircle2 size={36} color="#10b981" style={{ margin: '0 auto 10px' }} />
              <p style={{ margin: 0, fontSize: '13.5px' }}>All local offline operations are synchronized with the server.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '320px', overflowY: 'auto' }}>
              {mutations.map(m => (
                <div key={m.operation_id} style={{
                  padding: '12px',
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-card)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {m.operation_type}
                    </div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      ID: {m.operation_id.slice(0, 8)}... | Created: {new Date(m.created_at_utc).toLocaleTimeString()}
                    </div>
                    {m.last_error && (
                      <div style={{ fontSize: '11px', color: '#f87171', marginTop: '4px' }}>
                        Error: {m.last_error}
                      </div>
                    )}
                  </div>
                  <div>
                    <span className={`badge badge-${
                      m.sync_status === 'SYNCED' ? 'success' :
                      m.sync_status === 'CONFLICT' ? 'danger' :
                      m.sync_status === 'SYNCING' ? 'info' : 'warning'
                    }`} style={{ fontSize: '11px' }}>
                      {m.sync_status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', padding: '14px 20px', borderTop: '1px solid var(--border-card)' }}>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
