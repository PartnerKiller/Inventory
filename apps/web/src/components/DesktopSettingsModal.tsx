import React, { useState, useEffect } from 'react';
import { Server, Printer, Monitor, CheckCircle, XCircle, RefreshCw, X, HardDrive, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { nativeBridge, PrinterInfo } from '@inventory/native-bridge';
import { PrintLayout, AppMetadata } from '@inventory/shared-types';

interface DesktopSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onShowToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const DesktopSettingsModal: React.FC<DesktopSettingsModalProps> = ({ isOpen, onClose, onShowToast }) => {
  const [apiUrl, setApiUrl] = useState<string>(api.getBaseUrl());
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [connectionResult, setConnectionResult] = useState<{ ok: boolean; status: string; latencyMs: number; message?: string } | null>(null);
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [preferredPrinter, setPreferredPrinter] = useState<string>(localStorage.getItem('aurastock_pref_printer') || '');
  const [defaultLayout, setDefaultLayout] = useState<PrintLayout>((localStorage.getItem('aurastock_pref_layout') as PrintLayout) || 'A4');
  const [scannerThreshold, setScannerThreshold] = useState<number>(nativeBridge.getScannerThreshold());
  const [appInfo, setAppInfo] = useState<AppMetadata>(nativeBridge.getAppInfo());
  const [savedSuccess, setSavedSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      setApiUrl(api.getBaseUrl());
      setScannerThreshold(nativeBridge.getScannerThreshold());
      setAppInfo(nativeBridge.getAppInfo());
      loadPrinters();
      setSavedSuccess(false);
      setConnectionResult(null);
    }
  }, [isOpen]);

  const loadPrinters = async () => {
    try {
      const list = await nativeBridge.getAvailablePrinters();
      setPrinters(list);
      if (!preferredPrinter && list.length > 0) {
        const def = list.find(p => p.isDefault) || list[0];
        setPreferredPrinter(def.name);
      }
    } catch (e) {
      console.warn('Failed to enumerate printers:', e);
    }
  };

  const testCurrentConnection = async (targetUrl?: string) => {
    setIsTesting(true);
    setConnectionResult(null);
    try {
      const res = await api.checkHealth(targetUrl || apiUrl);
      setConnectionResult(res);
    } catch (e: any) {
      setConnectionResult({
        ok: false,
        status: 'OFFLINE',
        latencyMs: 0,
        message: e.message || 'Server check failed'
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSaveSettings = () => {
    api.setBaseUrl(apiUrl);
    nativeBridge.setScannerThreshold(scannerThreshold);
    localStorage.setItem('aurastock_pref_printer', preferredPrinter);
    localStorage.setItem('aurastock_pref_layout', defaultLayout);
    localStorage.setItem('aurastock_scanner_threshold', String(scannerThreshold));
    setSavedSuccess(true);
    if (onShowToast) {
      onShowToast('✓ Desktop settings saved and applied', 'success');
    }
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 600);
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        style={{
          maxWidth: '620px',
          width: '100%',
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.85)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Monitor size={20} color="#3b82f6" />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Windows Desktop & Connectivity Settings
            </h3>
          </div>
          <button className="btn btn-outline btn-sm" onClick={onClose} style={{ padding: '4px', borderRadius: '50%' }}>
            <X size={15} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '18px', padding: '20px 24px' }}>
          {/* Runtime & System Metadata */}
          <div style={{
            padding: '12px 16px',
            backgroundColor: '#131d36',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid #283550',
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '12px',
            fontSize: '12px'
          }}>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Application</span>
              <strong style={{ color: 'var(--text-primary)' }}>{appInfo.name}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Version</span>
              <strong style={{ color: 'var(--text-primary)' }}>v{appInfo.version}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Platform</span>
              <strong style={{ color: '#10b981' }}>{appInfo.platform}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Vault</span>
              <strong style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ShieldCheck size={13} /> Active
              </strong>
            </div>
          </div>

          {/* Backend API Server Connectivity */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <label style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Server size={15} color="#3b82f6" /> Central AuraStock Backend API Server URL
            </label>
            <div style={{ display: 'flex', gap: '10px' }}>
              <input
                type="text"
                className="form-control"
                value={apiUrl}
                onChange={e => setApiUrl(e.target.value)}
                placeholder="http://localhost:8000/api/v1"
                style={{ flex: 1, fontFamily: 'monospace', fontSize: '13px' }}
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => testCurrentConnection(apiUrl)}
                disabled={isTesting}
                style={{ minWidth: '130px' }}
              >
                {isTesting ? (
                  <>
                    <RefreshCw size={13} className="spin" /> Checking...
                  </>
                ) : (
                  <>
                    <RefreshCw size={13} /> Test Connection
                  </>
                )}
              </button>
            </div>

            {/* Connection feedback pill */}
            {connectionResult && (
              <div style={{
                padding: '8px 12px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: connectionResult.ok ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                border: `1px solid ${connectionResult.ok ? '#10b981' : '#ef4444'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '12px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {connectionResult.ok ? <CheckCircle size={15} color="#10b981" /> : <XCircle size={15} color="#ef4444" />}
                  <span style={{ color: connectionResult.ok ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                    {connectionResult.ok ? `Backend Operational (${connectionResult.latencyMs}ms)` : `Connection Failed: ${connectionResult.message}`}
                  </span>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Probe: /health</span>
              </div>
            )}
          </div>

          {/* Document & Printer Preferences */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Printer size={15} color="#3b82f6" /> System Printer
              </label>
              <select
                className="form-control"
                value={preferredPrinter}
                onChange={e => setPreferredPrinter(e.target.value)}
                style={{ fontSize: '13px' }}
              >
                {printers.map((p, idx) => (
                  <option key={idx} value={p.name}>
                    {p.name} {p.isDefault ? '(Default)' : ''}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <HardDrive size={15} color="#3b82f6" /> Default Document Format
              </label>
              <select
                className="form-control"
                value={defaultLayout}
                onChange={e => setDefaultLayout(e.target.value as PrintLayout)}
                style={{ fontSize: '13px' }}
              >
                <option value="A4">A4 Full Sheet</option>
                <option value="THERMAL">80mm Thermal Receipt</option>
                <option value="LABEL">Multi-Column Sticker Labels</option>
              </select>
            </div>
          </div>
          {/* USB HID Keyboard Wedge Scanner */}
          <div style={{
            padding: '14px 16px',
            backgroundColor: '#131d36',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid #283550',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
                <Monitor size={15} color="#3b82f6" /> USB HID Keyboard Wedge Scanner
              </label>
              <span style={{ fontSize: '11.5px', color: '#34d399', fontWeight: 600 }}>● Ready for Scans</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <label style={{ fontSize: '12px', color: 'var(--text-secondary)', minWidth: '160px' }}>
                Inter-keystroke Threshold:
              </label>
              <input
                type="number"
                min={10}
                max={250}
                step={5}
                className="form-control"
                style={{ width: '90px', fontSize: '12.5px', padding: '4px 8px' }}
                value={scannerThreshold}
                onChange={e => setScannerThreshold(Number(e.target.value))}
              />
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>ms</span>
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleSaveSettings}
            style={{ minWidth: '110px' }}
          >
            {savedSuccess ? (
              <>
                <CheckCircle size={15} /> Saved!
              </>
            ) : (
              'Save & Apply'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
