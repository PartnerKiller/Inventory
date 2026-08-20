import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Barcode, CheckCircle, X, RefreshCw } from 'lucide-react';
import { nativeBridge } from '@inventory/native-bridge';

interface ScannerSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ScannerSettingsModal: React.FC<ScannerSettingsModalProps> = ({ isOpen, onClose }) => {
  const [scannerThreshold, setScannerThreshold] = useState<number>(nativeBridge.getScannerThreshold());
  const [scannedTestLog, setScannedTestLog] = useState<string[]>([]);
  const [testInputValue, setTestInputValue] = useState<string>('');
  const [savedSuccess, setSavedSuccess] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      setScannerThreshold(nativeBridge.getScannerThreshold());
      setScannedTestLog([]);
      setTestInputValue('');
      setSavedSuccess(false);
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

  const handleSave = () => {
    nativeBridge.setScannerThreshold(scannerThreshold);
    localStorage.setItem('aurastock_scanner_threshold', String(scannerThreshold));
    setSavedSuccess(true);
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 800);
  };

  if (!isOpen) return null;

  const modalElement = (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        style={{
          maxWidth: '520px',
          width: '100%',
          backgroundColor: '#0f172a',
          border: '1px solid #334155',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.85)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Barcode size={20} color="#3b82f6" />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              USB HID Keyboard Wedge Scanner
            </h3>
          </div>
          <button className="btn btn-outline btn-sm" onClick={onClose} style={{ padding: '4px', borderRadius: '50%' }}>
            <X size={15} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '18px', padding: '20px 24px' }}>
          {/* Status */}
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label" style={{ marginBottom: '8px' }}>
              Status
            </label>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'rgba(16, 185, 129, 0.12)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              color: '#34d399',
              fontSize: '13px',
              fontWeight: 600
            }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#10b981',
                boxShadow: '0 0 6px #10b981'
              }} />
              Ready for Scans
            </div>
          </div>

          {/* Inter-keystroke Threshold */}
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label" style={{ marginBottom: '6px' }}>
              Inter-keystroke Threshold
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <input
                type="number"
                min={10}
                max={250}
                step={5}
                className="form-control"
                style={{ width: '100px', fontSize: '13.5px', fontFamily: 'monospace' }}
                value={scannerThreshold}
                onChange={(e) => setScannerThreshold(Number(e.target.value))}
              />
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                ms (Hardware scanners emit characters &lt;50ms apart)
              </span>
            </div>
          </div>

          {/* Scanner test / input area */}
          <div className="form-group" style={{ margin: 0 }}>
            <label className="form-label" style={{ marginBottom: '6px' }}>
              Scanner Verification & Live Input Area
            </label>
            <input
              type="text"
              className="form-control"
              placeholder="Scan any barcode or type quickly to test..."
              value={testInputValue}
              onChange={(e) => setTestInputValue(e.target.value)}
              style={{ fontSize: '13px' }}
            />

            {scannedTestLog.length > 0 && (
              <div style={{
                marginTop: '10px',
                padding: '10px 12px',
                backgroundColor: '#0b1120',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid #1e293b',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Recent Scan Detections:
                </div>
                {scannedTestLog.map((log, i) => (
                  <div key={i} style={{ fontSize: '11.5px', fontFamily: 'monospace', color: '#38bdf8' }}>
                    {log}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleSave}
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

  if (typeof document !== 'undefined') {
    return createPortal(modalElement, document.body);
  }

  return modalElement;
};
