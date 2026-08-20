import React, { useState, useEffect } from 'react';
import { Settings, Server, Printer, Barcode, Monitor, CheckCircle, XCircle, RefreshCw, X, HardDrive, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { nativeBridge, PrinterInfo } from '@inventory/native-bridge';
import { PrintLayout, AppMetadata } from '@inventory/shared-types';

interface DesktopSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const DesktopSettingsModal: React.FC<DesktopSettingsModalProps> = ({ isOpen, onClose }) => {
  const [apiUrl, setApiUrl] = useState<string>(api.getBaseUrl());
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [connectionResult, setConnectionResult] = useState<{ ok: boolean; status: string; latencyMs: number; message?: string } | null>(null);
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [preferredPrinter, setPreferredPrinter] = useState<string>(localStorage.getItem('aurastock_pref_printer') || '');
  const [defaultLayout, setDefaultLayout] = useState<PrintLayout>((localStorage.getItem('aurastock_pref_layout') as PrintLayout) || 'A4');
  const [scannerThreshold, setScannerThreshold] = useState<number>(nativeBridge.getScannerThreshold());
  const [scannedTestLog, setScannedTestLog] = useState<string[]>([]);
  const [appInfo, setAppInfo] = useState<AppMetadata>(nativeBridge.getAppInfo());
  const [savedSuccess, setSavedSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      setApiUrl(api.getBaseUrl());
      setScannerThreshold(nativeBridge.getScannerThreshold());
      setAppInfo(nativeBridge.getAppInfo());
      loadPrinters();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const unsubscribe = nativeBridge.onBarcode((event) => {
      const entry = `[${new Date(event.timestamp).toLocaleTimeString()}] ${event.barcode} (${event.source}${event.symbology ? ` - ${event.symbology}` : ''})`;
      setScannedTestLog(prev => [entry, ...prev.slice(0, 4)]);
    });

    return () => unsubscribe();
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
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 1000);
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: '750px', maxHeight: '90vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Monitor size={22} color="var(--primary)" />
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Windows Desktop & Connectivity Settings</h3>
          </div>
          <button className="btn btn-icon" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Runtime & System Metadata */}
          <div style={{
            padding: '12px 16px',
            backgroundColor: 'var(--bg-card-alt)',
            borderRadius: '8px',
            border: '1px solid var(--border-card)',
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '12px',
            fontSize: '12px'
          }}>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Application</span>
              <strong style={{ color: 'var(--text-main)' }}>{appInfo.name}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Client Version</span>
              <strong style={{ color: 'var(--text-main)' }}>v{appInfo.version}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Runtime Host</span>
              <strong style={{ color: appInfo.isDesktop ? '#10b981' : '#38bdf8' }}>
                {appInfo.platform}
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)', display: 'block' }}>Security Vault</span>
              <strong style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ShieldCheck size={14} /> Active
              </strong>
            </div>
          </div>

          {/* Backend API Server Connectivity */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Server size={16} color="var(--primary)" /> FastAPI Backend API Server URL
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
                style={{ minWidth: '140px' }}
              >
                {isTesting ? (
                  <>
                    <RefreshCw size={14} className="spin" /> Checking...
                  </>
                ) : (
                  <>
                    <RefreshCw size={14} /> Test Connection
                  </>
                )}
              </button>
            </div>

            {/* Connection feedback pill */}
            {connectionResult && (
              <div style={{
                padding: '8px 12px',
                borderRadius: '6px',
                backgroundColor: connectionResult.ok ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${connectionResult.ok ? '#10b981' : '#ef4444'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '12px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {connectionResult.ok ? <CheckCircle size={16} color="#10b981" /> : <XCircle size={16} color="#ef4444" />}
                  <span style={{ color: connectionResult.ok ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                    {connectionResult.ok ? `Backend Operational (${connectionResult.latencyMs}ms latency)` : `Connection Failed: ${connectionResult.message}`}
                  </span>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Health Check: /health</span>
              </div>
            )}
          </div>

          {/* Document & Printer Preferences */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Printer size={16} color="var(--primary)" /> Preferred System Printer
              </label>
              <select
                className="form-control"
                value={preferredPrinter}
                onChange={e => setPreferredPrinter(e.target.value)}
              >
                {printers.map((p, idx) => (
                  <option key={idx} value={p.name}>
                    {p.name} {p.isDefault ? '(Default)' : ''} [{p.type}]
                  </option>
                ))}
              </select>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Enumerated via native Windows Spooler abstraction
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <HardDrive size={16} color="var(--primary)" /> Default Document Format
              </label>
              <select
                className="form-control"
                value={defaultLayout}
                onChange={e => setDefaultLayout(e.target.value as PrintLayout)}
              >
                <option value="A4">A4 Full Sheet (Commercial Forms)</option>
                <option value="THERMAL">80mm Thermal Receipt (POS / Logistics)</option>
                <option value="LABEL">Multi-Column Sticker Labels</option>
              </select>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Pre-selected layout when opening Document Preview
              </span>
            </div>
          </div>

          {/* Barcode Scanner (USB HID Keyboard Wedge) */}
          <div style={{
            padding: '14px',
            backgroundColor: 'var(--bg-card-alt)',
            borderRadius: '8px',
            border: '1px solid var(--border-card)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
                <Barcode size={16} color="var(--primary)" /> USB HID Keyboard Wedge Scanner
              </label>
              <span style={{ fontSize: '12px', color: '#10b981', fontWeight: 600 }}>● Ready for Scans</span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', minWidth: '150px' }}>
                Inter-keystroke Threshold:
              </label>
              <input
                type="number"
                min={10}
                max={250}
                step={5}
                className="form-control"
                style={{ width: '90px' }}
                value={scannerThreshold}
                onChange={e => setScannerThreshold(Number(e.target.value))}
              />
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>ms (Scanners fire characters &lt;50ms apart)</span>
            </div>

            {/* Live Scan Test Area */}
            <div style={{ marginTop: '4px' }}>
              <input
                type="text"
                className="form-control"
                placeholder="Scan any barcode here to verify USB HID scanner reception..."
                style={{ fontSize: '12px' }}
              />
              {scannedTestLog.length > 0 && (
                <div style={{
                  marginTop: '8px',
                  padding: '8px',
                  backgroundColor: 'var(--bg-app)',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontFamily: 'monospace',
                  color: '#38bdf8'
                }}>
                  {scannedTestLog.map((log, i) => (
                    <div key={i}>{log}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSaveSettings}
            style={{ minWidth: '130px' }}
          >
            {savedSuccess ? (
              <>
                <CheckCircle size={16} /> Saved!
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
