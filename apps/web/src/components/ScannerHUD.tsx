import React, { useEffect, useState } from 'react';
import { ScanBarcode, CheckCircle2, ShieldCheck, Laptop } from 'lucide-react';
import { nativeBridge, BarcodeScanEvent } from '@inventory/native-bridge';
import { api } from '../api/client';
import { BarcodeLookupResponse } from '@inventory/shared-types';

export const ScannerHUD: React.FC<{
  onItemScanned?: (item: BarcodeLookupResponse) => void;
}> = ({ onItemScanned }) => {
  const [lastScan, setLastScan] = useState<BarcodeScanEvent | null>(null);
  const [lookupResult, setLookupResult] = useState<BarcodeLookupResponse | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [manualCode, setManualCode] = useState('');

  // Audio Beep generator using Web Audio API
  const playBeep = (isSuccess: boolean = true) => {
    try {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = isSuccess ? 'sine' : 'sawtooth';
      osc.frequency.setValueAtTime(isSuccess ? 1800 : 300, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + (isSuccess ? 0.12 : 0.3));
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + (isSuccess ? 0.12 : 0.3));
    } catch (e) {
      // Audio not permitted or supported
    }
  };

  useEffect(() => {
    const unsubscribe = nativeBridge.onBarcode(async (event) => {
      setLastScan(event);
      setIsScanning(true);
      try {
        const res = await api.lookupBarcode(event.barcode);
        setLookupResult(res);
        playBeep(res.found);
        if (onItemScanned) {
          onItemScanned(res);
        }
      } catch (err) {
        console.error('Barcode lookup failed:', err);
        playBeep(false);
      } finally {
        setIsScanning(false);
      }
    });

    return () => unsubscribe();
  }, [onItemScanned]);

  const handleManualLookup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualCode.trim()) return;

    const event: BarcodeScanEvent = {
      barcode: manualCode.trim(),
      source: 'MANUAL',
      timestamp: Date.now(),
    };
    setLastScan(event);
    try {
      const res = await api.lookupBarcode(manualCode.trim());
      setLookupResult(res);
      playBeep(res.found);
      if (onItemScanned) onItemScanned(res);
    } catch (err) {
      playBeep(false);
    }
    setManualCode('');
  };

  return (
    <div className="scanner-hud">
      <div className="scanner-pulse" />
      <ScanBarcode size={20} color="#3b82f6" />
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          {nativeBridge.getPlatformName()}:
        </span>
        {lastScan ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="scan-code-pill">{lastScan.barcode}</span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              ({lastScan.source})
            </span>
            {lookupResult && lookupResult.found ? (
              <span className="badge badge-success" style={{ fontSize: '11px' }}>
                <CheckCircle2 size={12} /> {lookupResult.item_name} ({lookupResult.current_stock} in stock)
              </span>
            ) : lookupResult ? (
              <span className="badge badge-warning" style={{ fontSize: '11px' }}>
                Unregistered Barcode
              </span>
            ) : null}
          </div>
        ) : (
          <span style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
            Ready to scan. Use USB Scanner, Bluetooth Wedge, or enter manual code.
          </span>
        )}
      </div>

      <form onSubmit={handleManualLookup} style={{ display: 'flex', gap: '6px' }}>
        <input
          type="text"
          placeholder="Test scan barcode..."
          value={manualCode}
          onChange={(e) => setManualCode(e.target.value)}
          className="form-control"
          style={{ width: '180px', padding: '4px 10px', fontSize: '12px' }}
        />
        <button type="submit" className="btn btn-secondary btn-sm">
          Simulate Scan
        </button>
      </form>
    </div>
  );
};
