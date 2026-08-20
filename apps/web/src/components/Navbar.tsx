import React, { useState, useEffect } from 'react';
import { Search, Warehouse, RefreshCw, Monitor, Wifi, WifiOff, CloudUpload } from 'lucide-react';
import { api } from '../api/client';
import { nativeBridge } from '@inventory/native-bridge';
import { DesktopSettingsModal } from './DesktopSettingsModal';
import { SyncCenterModal } from './SyncCenterModal';

interface NavbarProps {
  activeWarehouse: string;
  onWarehouseChange: (whId: string) => void;
  warehouses: Array<{ id: string; code: string; name: string }>;
  onRefresh: () => void;
  onOpenSearch?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeWarehouse,
  onWarehouseChange,
  warehouses,
  onRefresh,
  onOpenSearch,
}) => {
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTED' | 'DISCONNECTED' | 'ERROR'>('CONNECTED');
  const [isDesktopSettingsOpen, setIsDesktopSettingsOpen] = useState<boolean>(false);
  const [isSyncCenterOpen, setIsSyncCenterOpen] = useState<boolean>(false);
  const [pendingCount, setPendingCount] = useState<number>(0);

  const checkPendingQueue = async () => {
    const queue = await nativeBridge.getPendingMutations();
    const pending = queue.filter(q => q.sync_status === 'PENDING_SYNC' || q.sync_status === 'RETRY_PENDING');
    setPendingCount(pending.length);
  };

  useEffect(() => {
    // Initial health check
    api.checkHealth().then(res => {
      setConnectionStatus(res.ok ? 'CONNECTED' : 'DISCONNECTED');
    });

    checkPendingQueue();

    const handleConnectionStatus = (e: any) => {
      if (e.detail?.status) {
        setConnectionStatus(e.detail.status === 'CONNECTED' ? 'CONNECTED' : 'DISCONNECTED');
      }
    };

    const handleQueueChange = () => {
      checkPendingQueue();
    };

    window.addEventListener('connection:status', handleConnectionStatus);
    window.addEventListener('offline:mutation_queued', handleQueueChange);
    window.addEventListener('offline:mutation_updated', handleQueueChange);
    window.addEventListener('offline:queue_cleared', handleQueueChange);

    return () => {
      window.removeEventListener('connection:status', handleConnectionStatus);
      window.removeEventListener('offline:mutation_queued', handleQueueChange);
      window.removeEventListener('offline:mutation_updated', handleQueueChange);
      window.removeEventListener('offline:queue_cleared', handleQueueChange);
    };
  }, []);

  return (
    <header className="navbar">
      <div
        className="navbar-search"
        onClick={onOpenSearch}
        style={{ cursor: 'pointer' }}
      >
        <Search size={16} color="#64748b" />
        <input
          type="text"
          readOnly
          placeholder="Search products, SKUs, barcodes, POs, SOs... (Ctrl+K)"
          style={{ cursor: 'pointer' }}
        />
        <span style={{ fontSize: '11px', color: '#64748b', border: '1px solid #334155', padding: '2px 5px', borderRadius: '4px', marginLeft: 'auto' }}>
          Ctrl+K
        </span>
      </div>

      <div className="navbar-actions">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Warehouse size={16} color="#94a3b8" />
          <select
            className="form-control"
            value={activeWarehouse}
            onChange={(e) => onWarehouseChange(e.target.value)}
            style={{ width: '220px', padding: '6px 12px', fontSize: '13px', backgroundColor: 'var(--bg-card)' }}
          >
            <option value="">All Warehouses</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} - {w.name}
              </option>
            ))}
          </select>
        </div>

        <button className="btn btn-secondary btn-sm" onClick={onRefresh} title="Sync data">
          <RefreshCw size={14} /> Refresh
        </button>

        {/* Sync Center Trigger */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsSyncCenterOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            borderColor: pendingCount > 0 ? '#f59e0b' : 'var(--border-card)',
            backgroundColor: pendingCount > 0 ? 'rgba(245, 158, 11, 0.1)' : 'transparent'
          }}
          title="Offline Sync Center"
        >
          <CloudUpload size={14} color={pendingCount > 0 ? '#f59e0b' : '#94a3b8'} />
          <span style={{ fontSize: '12px', fontWeight: 600, color: pendingCount > 0 ? '#f59e0b' : 'var(--text-secondary)' }}>
            {pendingCount > 0 ? `${pendingCount} Pending` : 'Sync Center'}
          </span>
        </button>

        {/* Connection status indicator */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsDesktopSettingsOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            borderColor: connectionStatus === 'CONNECTED' ? '#10b981' : '#ef4444',
            backgroundColor: connectionStatus === 'CONNECTED' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)'
          }}
          title="Desktop & Backend Connectivity Settings"
        >
          {connectionStatus === 'CONNECTED' ? (
            <Wifi size={14} color="#10b981" />
          ) : (
            <WifiOff size={14} color="#ef4444" />
          )}
          <span style={{ color: connectionStatus === 'CONNECTED' ? '#10b981' : '#ef4444', fontSize: '12px', fontWeight: 600 }}>
            {connectionStatus === 'CONNECTED' ? 'Backend Online' : 'Backend Offline'}
          </span>
          <Monitor size={13} color="var(--text-muted)" style={{ marginLeft: '4px' }} />
        </button>
      </div>

      <DesktopSettingsModal
        isOpen={isDesktopSettingsOpen}
        onClose={() => setIsDesktopSettingsOpen(false)}
      />

      <SyncCenterModal
        isOpen={isSyncCenterOpen}
        onClose={() => setIsSyncCenterOpen(false)}
      />
    </header>
  );
};
