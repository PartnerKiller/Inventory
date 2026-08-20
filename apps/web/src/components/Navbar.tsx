import React, { useState, useEffect } from 'react';
import { Search, Warehouse, RefreshCw, Monitor, Wifi, WifiOff, CloudUpload, Barcode } from 'lucide-react';
import { api } from '../api/client';
import { nativeBridge } from '@inventory/native-bridge';
import { DesktopSettingsModal } from './DesktopSettingsModal';
import { SyncCenterModal } from './SyncCenterModal';
import { ScannerSettingsModal } from './ScannerSettingsModal';

interface NavbarProps {
  activeWarehouse: string;
  onWarehouseChange: (whId: string) => void;
  warehouses: Array<{ id: string; code: string; name: string }>;
  onRefresh: () => void;
  onOpenSearch?: () => void;
  onShowToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeWarehouse,
  onWarehouseChange,
  warehouses,
  onRefresh,
  onOpenSearch,
  onShowToast,
}) => {
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTED' | 'DISCONNECTED' | 'ERROR' | 'SYNCING'>('CONNECTED');
  const [isDesktopSettingsOpen, setIsDesktopSettingsOpen] = useState<boolean>(false);
  const [isSyncCenterOpen, setIsSyncCenterOpen] = useState<boolean>(false);
  const [isScannerSettingsOpen, setIsScannerSettingsOpen] = useState<boolean>(false);
  const [pendingCount, setPendingCount] = useState<number>(0);

  const checkPendingQueue = async () => {
    const queue = await nativeBridge.getPendingMutations();
    const pending = queue.filter(q => q.sync_status === 'PENDING_SYNC' || q.sync_status === 'RETRY_PENDING');
    setPendingCount(pending.length);
  };

  useEffect(() => {
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
        style={{ cursor: 'pointer', maxWidth: '340px' }}
      >
        <Search size={15} color="#64748b" />
        <input
          type="text"
          readOnly
          placeholder="Quick search products, SKUs, POs (Ctrl+K)"
          style={{ cursor: 'pointer', fontSize: '13px' }}
        />
        <span style={{ fontSize: '11px', color: '#64748b', border: '1px solid #334155', padding: '1px 5px', borderRadius: '4px', marginLeft: 'auto' }}>
          Ctrl+K
        </span>
      </div>

      <div className="navbar-actions" style={{ gap: '10px' }}>
        {/* Global Facility Selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Warehouse size={15} color="#94a3b8" />
          <select
            className="form-control"
            value={activeWarehouse}
            onChange={(e) => onWarehouseChange(e.target.value)}
            style={{ width: '190px', padding: '5px 10px', fontSize: '12.5px', backgroundColor: 'var(--bg-card)' }}
          >
            <option value="">All Warehouses</option>
            {warehouses.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} - {w.name}
              </option>
            ))}
          </select>
        </div>

        <button className="btn btn-secondary btn-sm" onClick={onRefresh} title="Refresh catalog data">
          <RefreshCw size={13} /> Refresh
        </button>

        {/* Dedicated Scanner Settings Trigger */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsScannerSettingsOpen(true)}
          style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          title="USB HID Barcode Scanner Settings"
        >
          <Barcode size={14} color="#3b82f6" />
          <span>Scanner</span>
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
            backgroundColor: pendingCount > 0 ? 'rgba(245, 158, 11, 0.12)' : 'transparent'
          }}
          title="Offline Sync Center"
        >
          <CloudUpload size={14} color={pendingCount > 0 ? '#f59e0b' : '#94a3b8'} />
          <span style={{ fontSize: '12px', fontWeight: 600, color: pendingCount > 0 ? '#fbbf24' : 'var(--text-secondary)' }}>
            {pendingCount > 0 ? `${pendingCount} Pending` : 'Sync Center'}
          </span>
        </button>

        {/* Compact Backend Status Control */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setIsDesktopSettingsOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            borderColor: connectionStatus === 'CONNECTED' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
            backgroundColor: connectionStatus === 'CONNECTED' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)'
          }}
          title="Server Settings & Connectivity"
        >
          <span style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            backgroundColor: connectionStatus === 'CONNECTED' ? '#10b981' : '#ef4444',
            boxShadow: connectionStatus === 'CONNECTED' ? '0 0 6px #10b981' : '0 0 6px #ef4444'
          }} />
          <span style={{ color: connectionStatus === 'CONNECTED' ? '#34d399' : '#f87171', fontSize: '12px', fontWeight: 600 }}>
            {connectionStatus === 'CONNECTED' ? 'Backend Online' : 'Offline'}
          </span>
        </button>
      </div>

      <DesktopSettingsModal
        isOpen={isDesktopSettingsOpen}
        onClose={() => setIsDesktopSettingsOpen(false)}
        onShowToast={onShowToast}
      />

      <SyncCenterModal
        isOpen={isSyncCenterOpen}
        onClose={() => setIsSyncCenterOpen(false)}
        onShowToast={onShowToast}
      />

      <ScannerSettingsModal
        isOpen={isScannerSettingsOpen}
        onClose={() => setIsScannerSettingsOpen(false)}
      />
    </header>
  );
};
