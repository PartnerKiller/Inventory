import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { nativeBridge, NativeBridge, BarcodeScanEvent } from '@inventory/native-bridge';
import { api } from '../api/client';
import { DocumentPrinter, BrowserDocumentPrinter, TauriDocumentPrinter, UnifiedDocumentPrinter } from '../services/DocumentPrinter';
import { DesktopSettingsModal } from '../components/DesktopSettingsModal';

describe('Phase 3C: Tauri Windows Desktop & Native Capabilities Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    api.setBaseUrl('/api/v1');
  });

  afterEach(() => {
    delete (window as any).__TAURI__;
    delete (window as any).__TAURI_INTERNALS__;
  });

  it('correctly reports platform metadata and capability abstraction', () => {
    const bridge = NativeBridge.getInstance();
    expect(bridge.getPlatformName()).toBe('Web Browser');
    expect(bridge.isDesktop()).toBe(false);

    const appInfo = bridge.getAppInfo();
    expect(appInfo.name).toBe('AuraStock Enterprise');
    expect(appInfo.version).toBe('1.0.0');
    expect(appInfo.isDesktop).toBe(false);

    bridge.setScannerThreshold(60);
    expect(bridge.getScannerThreshold()).toBe(60);
  });

  it('detects Tauri desktop runtime when internal hooks are present', () => {
    (window as any).__TAURI_INTERNALS__ = {};
    const bridge = NativeBridge.getInstance();
    expect(bridge.isDesktop()).toBe(true);
    expect(bridge.getPlatformName()).toBe('Tauri Windows Desktop');
  });

  it('buffers and emits USB HID keyboard wedge scanner input on rapid keystrokes with Enter', async () => {
    const bridge = NativeBridge.getInstance();
    const mockCallback = vi.fn();
    const unsubscribe = bridge.onBarcode(mockCallback);

    bridge.setScannerThreshold(100);

    // Simulate rapid USB HID barcode scanner key events (<100ms apart)
    fireEvent.keyDown(window, { key: 'S' });
    fireEvent.keyDown(window, { key: 'K' });
    fireEvent.keyDown(window, { key: 'U' });
    fireEvent.keyDown(window, { key: '-' });
    fireEvent.keyDown(window, { key: '8' });
    fireEvent.keyDown(window, { key: '8' });
    fireEvent.keyDown(window, { key: '8' });
    fireEvent.keyDown(window, { key: 'Enter' });

    expect(mockCallback).toHaveBeenCalledTimes(1);
    expect(mockCallback).toHaveBeenCalledWith(
      expect.objectContaining({
        barcode: 'SKU-888',
        source: 'KEYBOARD_WEDGE'
      })
    );

    unsubscribe();
  });

  it('ignores slow typing when inter-keystroke threshold is exceeded', async () => {
    const bridge = NativeBridge.getInstance();
    const mockCallback = vi.fn();
    const unsubscribe = bridge.onBarcode(mockCallback);

    bridge.setScannerThreshold(10); // Very low threshold to simulate slow manual typing

    // Manual slow typing
    fireEvent.keyDown(window, { key: 'A' });
    
    // Wait slightly to exceed threshold
    await new Promise(r => setTimeout(r, 20));
    fireEvent.keyDown(window, { key: 'B' });
    await new Promise(r => setTimeout(r, 20));
    fireEvent.keyDown(window, { key: 'C' });
    fireEvent.keyDown(window, { key: 'Enter' });

    // Since each key was typed slowly, the buffer only had 'C' when Enter was pressed (< 3 chars)
    expect(mockCallback).not.toHaveBeenCalled();

    unsubscribe();
  });

  it('routes UnifiedDocumentPrinter to Browser or Tauri implementations based on runtime', async () => {
    const unifiedPrinter = new UnifiedDocumentPrinter();
    
    // In Browser mode
    delete (window as any).__TAURI__;
    delete (window as any).__TAURI_INTERNALS__;
    expect(unifiedPrinter.getActivePrinter()).toBeInstanceOf(BrowserDocumentPrinter);

    // In Tauri desktop mode
    (window as any).__TAURI_INTERNALS__ = {};
    expect(unifiedPrinter.getActivePrinter()).toBeInstanceOf(TauriDocumentPrinter);
  });

  it('supports dynamic ApiClient base URL configuration and health check', async () => {
    expect(api.getBaseUrl()).toBe('/api/v1');

    api.setBaseUrl('http://192.168.1.100:8000/api/v1');
    expect(api.getBaseUrl()).toBe('http://192.168.1.100:8000/api/v1');
    expect(localStorage.getItem('aurastock_api_url')).toBe('http://192.168.1.100:8000/api/v1');

    // Mock globalThis.fetch for health check
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'healthy', database: 'connected' })
    } as any);

    const health = await api.checkHealth();
    expect(health.ok).toBe(true);
    expect(health.status).toBe('ONLINE');
    expect(health.latencyMs).toBeGreaterThanOrEqual(0);

    globalThis.fetch = originalFetch;
  });

  it('renders DesktopSettingsModal, allows testing endpoint, and saves desktop preferences', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'healthy' })
    } as any);

    const mockClose = vi.fn();
    render(<DesktopSettingsModal isOpen={true} onClose={mockClose} />);

    expect(screen.getByText('Windows Desktop & Connectivity Settings')).toBeInTheDocument();
    expect(screen.getByText('USB HID Keyboard Wedge Scanner')).toBeInTheDocument();

    const input = screen.getByPlaceholderText('http://localhost:8000/api/v1');
    fireEvent.change(input, { target: { value: 'http://custom-server:8000/api/v1' } });

    const testBtn = screen.getByText('Test Connection');
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(screen.getByText(/Backend Operational/i)).toBeInTheDocument();
    });

    const saveBtn = screen.getByText('Save & Apply');
    fireEvent.click(saveBtn);

    expect(api.getBaseUrl()).toBe('http://custom-server:8000/api/v1');

    globalThis.fetch = originalFetch;
  });
});
