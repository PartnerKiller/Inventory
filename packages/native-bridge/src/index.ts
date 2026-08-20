/**
 * Unified Native Platform Adapter
 * Transparently bridges Web Browser and Tauri Windows Desktop runtimes
 */

import { AppMetadata, PrintLayout } from '@inventory/shared-types';

export interface BarcodeScanEvent {
  barcode: string;
  symbology?: string;
  source: 'KEYBOARD_WEDGE' | 'SERIAL_PORT' | 'CAMERA' | 'MANUAL';
  timestamp: number;
}

export interface PrinterInfo {
  name: string;
  isDefault: boolean;
  type: 'LOCAL' | 'NETWORK' | 'RAW_ESC_POS' | 'ZPL';
}

export interface SaveFileOptions {
  defaultPath?: string;
  filterName?: string;
  extensions?: string[];
  data: Blob | Uint8Array | string;
  mimeType?: string;
  filename?: string;
}

export interface OfflineMutation {
  operation_id: string;
  tenant_id: string;
  user_id: string;
  warehouse_id: string;
  entity_type: string;
  entity_id?: string;
  operation_type: string;
  payload: Record<string, any>;
  created_at_utc: string;
  client_version: string;
  sync_status: 'LOCAL_ONLY' | 'PENDING_SYNC' | 'SYNCING' | 'SYNCED' | 'RETRY_PENDING' | 'CONFLICT' | 'USER_REVIEW';
  retry_count: number;
  last_error?: string;
  server_ack_id?: string;
}

export interface NativeCapabilities {
  isDesktop(): boolean;
  getPlatformName(): string;
  getAppInfo(): AppMetadata;
  getAvailablePrinters(): Promise<PrinterInfo[]>;
  printDocument(htmlContent: string, layout: PrintLayout, rawData?: string): Promise<boolean>;
  saveFile(options: SaveFileOptions): Promise<string | null>;
  onBarcode(callback: (event: BarcodeScanEvent) => void): () => void;
  emitBarcode(event: BarcodeScanEvent): void;
  setScannerThreshold(ms: number): void;
  getScannerThreshold(): number;
  showNotification(title: string, body: string): Promise<void>;
  getSecureItem(key: string): Promise<string | null>;
  setSecureItem(key: string, value: string): Promise<void>;
  removeSecureItem(key: string): Promise<void>;
  queueOfflineMutation(mutation: OfflineMutation): Promise<void>;
  getPendingMutations(): Promise<OfflineMutation[]>;
  updateMutationStatus(operation_id: string, status: OfflineMutation['sync_status'], server_ack_id?: string, error?: string): Promise<void>;
  clearSyncedMutations(): Promise<void>;
}

export class NativeBridge implements NativeCapabilities {
  private static instance: NativeBridge;
  private isTauriRuntime: boolean = false;
  private scannerListeners: Array<(event: BarcodeScanEvent) => void> = [];
  private keyStrokeBuffer: string = '';
  private lastKeyStrokeTime: number = 0;
  private keyStrokeThresholdMs: number = 50; // Barcode scanners type with < 50ms interval
  private bufferResetTimer: any = null;

  private constructor() {
    this.checkRuntime();
    this.initializeScannerListeners();
  }

  public static getInstance(): NativeBridge {
    if (!NativeBridge.instance) {
      NativeBridge.instance = new NativeBridge();
    }
    return NativeBridge.instance;
  }

  private checkRuntime(): void {
    if (typeof window !== 'undefined') {
      this.isTauriRuntime = Boolean((window as any).__TAURI_INTERNALS__ || (window as any).__TAURI__);
    }
  }

  public isDesktop(): boolean {
    this.checkRuntime();
    return this.isTauriRuntime;
  }

  public getPlatformName(): string {
    return this.isDesktop() ? 'Tauri Windows Desktop' : 'Web Browser';
  }

  public getAppInfo(): AppMetadata {
    const isDev = typeof (globalThis as any).process !== 'undefined' && (globalThis as any).process?.env?.NODE_ENV === 'development';
    return {
      name: 'AuraStock Enterprise',
      version: '1.0.0',
      isDesktop: this.isDesktop(),
      platform: this.getPlatformName(),
      environment: isDev ? 'development' : 'production'
    };
  }

  public async printThermalLabel(labelHtml: string, rawZplOrEscPos?: string): Promise<boolean> {
    return this.printDocument(labelHtml, 'LABEL', rawZplOrEscPos);
  }

  public setScannerThreshold(ms: number): void {
    this.keyStrokeThresholdMs = Math.max(10, Math.min(250, ms));
  }

  public getScannerThreshold(): number {
    return this.keyStrokeThresholdMs;
  }

  private initializeScannerListeners(): void {
    if (typeof window === 'undefined') return;

    window.addEventListener('keydown', (e: KeyboardEvent) => {
      const now = Date.now();
      const timeDiff = now - this.lastKeyStrokeTime;

      const target = e.target as HTMLElement | null;
      const isInput = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

      if (e.key === 'Enter' || e.key === 'Tab') {
        if (this.keyStrokeBuffer.length >= 3) {
          const scannedCode = this.keyStrokeBuffer.trim();
          this.emitBarcode({
            barcode: scannedCode,
            source: 'KEYBOARD_WEDGE',
            timestamp: now,
          });
          this.keyStrokeBuffer = '';
          if (isInput) {
            e.preventDefault();
            e.stopPropagation();
          }
        } else {
          this.keyStrokeBuffer = '';
        }
        return;
      }

      if (timeDiff < this.keyStrokeThresholdMs || this.keyStrokeBuffer.length === 0) {
        if (e.key && e.key.length === 1) {
          this.keyStrokeBuffer += e.key;
        }
      } else {
        if (e.key && e.key.length === 1) {
          this.keyStrokeBuffer = e.key;
        } else {
          this.keyStrokeBuffer = '';
        }
      }

      this.lastKeyStrokeTime = now;

      // Auto-clear buffer if no keystrokes follow within threshold * 4
      if (this.bufferResetTimer) {
        clearTimeout(this.bufferResetTimer);
      }
      this.bufferResetTimer = setTimeout(() => {
        if (this.keyStrokeBuffer.length > 0 && this.keyStrokeBuffer.length < 3) {
          this.keyStrokeBuffer = '';
        }
      }, this.keyStrokeThresholdMs * 4);
    });

    if (this.isDesktop()) {
      try {
        const tauriEvent = (window as any).__TAURI__?.event;
        if (tauriEvent?.listen) {
          tauriEvent.listen('tauri://serial-barcode-scanned', (event: { payload: { barcode: string; symbology?: string } }) => {
            this.emitBarcode({
              barcode: event.payload.barcode,
              symbology: event.payload.symbology,
              source: 'SERIAL_PORT',
              timestamp: Date.now(),
            });
          }).catch((err: any) => {
            console.warn('Tauri serial barcode event listener unavailable:', err);
          });
        }
      } catch (err) {
        console.warn('Could not initialize Tauri native serial scanner listener:', err);
      }
    }
  }

  public onBarcode(callback: (event: BarcodeScanEvent) => void): () => void {
    this.scannerListeners.push(callback);
    return () => {
      this.scannerListeners = this.scannerListeners.filter(cb => cb !== callback);
    };
  }

  public emitBarcode(event: BarcodeScanEvent): void {
    for (const listener of this.scannerListeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in barcode listener callback:', err);
      }
    }
  }

  public async getAvailablePrinters(): Promise<PrinterInfo[]> {
    if (this.isDesktop()) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          return await tauriCore.invoke('get_printers');
        }
      } catch (err) {
        console.warn('Failed to fetch native printers via Tauri:', err);
      }
    }

    return [
      { name: 'System Default Printer (Browser Dialog)', isDefault: true, type: 'LOCAL' }
    ];
  }

  public async printDocument(htmlContent: string, layout: PrintLayout, rawData?: string): Promise<boolean> {
    if (this.isDesktop() && rawData) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          await tauriCore.invoke('print_raw', { data: rawData });
          return true;
        }
      } catch (err) {
        console.warn('Native raw print failed, falling back to browser print:', err);
      }
    }

    const isThermal = layout === 'THERMAL';
    const isLabel = layout === 'LABEL';

    const pageRule = isThermal
      ? '@page { size: 80mm auto; margin: 2mm; }'
      : isLabel
      ? '@page { size: auto; margin: 3mm; }'
      : '@page { size: A4 portrait; margin: 12mm 15mm; }';

    const fullHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8" />
          <title>Print Document</title>
          <style>
            ${pageRule}
            * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
              color: #0f172a;
              margin: 0;
              padding: ${isThermal ? '2px' : '0'};
              background: #fff;
              font-size: ${isThermal ? '11px' : '13px'};
              line-height: 1.4;
            }
            @media print {
              body { width: 100%; }
              .no-print { display: none !important; }
            }
          </style>
        </head>
        <body>
          ${htmlContent}
        </body>
      </html>
    `;

    const iframe = document.createElement('iframe');
    iframe.style.position = 'fixed';
    iframe.style.right = '0';
    iframe.style.bottom = '0';
    iframe.style.width = '0';
    iframe.style.height = '0';
    iframe.style.border = '0';
    document.body.appendChild(iframe);

    const doc = iframe.contentWindow?.document;
    if (doc) {
      doc.open();
      doc.write(fullHtml);
      doc.close();

      return new Promise<boolean>((resolve) => {
        setTimeout(() => {
          try {
            iframe.contentWindow?.focus();
            iframe.contentWindow?.print();
            setTimeout(() => {
              if (iframe.parentNode) {
                document.body.removeChild(iframe);
              }
              resolve(true);
            }, 1000);
          } catch (e) {
            console.error('Printing execution error:', e);
            if (iframe.parentNode) {
              document.body.removeChild(iframe);
            }
            resolve(false);
          }
        }, 250);
      });
    }

    return false;
  }

  public async saveFile(options: SaveFileOptions): Promise<string | null> {
    const filename = options.filename || options.defaultPath || 'document.pdf';

    // Tauri Native File Dialog if available
    if (this.isDesktop()) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          const res = await tauriCore.invoke('save_file_dialog', {
            defaultPath: filename,
            filterName: options.filterName || 'Documents',
            extensions: options.extensions || ['pdf']
          });
          if (res) {
            return String(res);
          }
        }
      } catch (err) {
        console.warn('Tauri native save dialog failed, falling back to browser download:', err);
      }
    }

    // Web Browser fallback: Blob Anchor download
    let blob: Blob;
    if (options.data instanceof Blob) {
      blob = options.data;
    } else if (typeof options.data === 'string') {
      blob = new Blob([options.data], { type: options.mimeType || 'text/plain;charset=utf-8' });
    } else {
      blob = new Blob([options.data as any], { type: options.mimeType || 'application/octet-stream' });
    }

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
    return filename;
  }

  public async showNotification(title: string, body: string): Promise<void> {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'granted') {
        new Notification(title, { body });
      } else if (Notification.permission !== 'denied') {
        const perm = await Notification.requestPermission();
        if (perm === 'granted') {
          new Notification(title, { body });
        }
      }
    }
  }

  public async getSecureItem(key: string): Promise<string | null> {
    if (this.isDesktop()) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          return await tauriCore.invoke('get_secure_key', { key });
        }
      } catch (err) {
        console.warn('Failed to retrieve secure item from Tauri vault:', err);
      }
    }
    return localStorage.getItem(`secure_${key}`);
  }

  public async setSecureItem(key: string, value: string): Promise<void> {
    if (this.isDesktop()) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          await tauriCore.invoke('set_secure_key', { key, value });
          return;
        }
      } catch (err) {
        console.warn('Failed to set secure item in Tauri vault:', err);
      }
    }
    localStorage.setItem(`secure_${key}`, value);
  }

  public async removeSecureItem(key: string): Promise<void> {
    if (this.isDesktop()) {
      try {
        const tauriCore = (window as any).__TAURI__?.core;
        if (tauriCore?.invoke) {
          await tauriCore.invoke('delete_secure_key', { key });
          return;
        }
      } catch (err) {
        console.warn('Failed to delete secure item in Tauri vault:', err);
      }
    }
    localStorage.removeItem(`secure_${key}`);
  }

  public async queueOfflineMutation(mutation: OfflineMutation): Promise<void> {
    const queue = await this.getPendingMutations();
    queue.push(mutation);
    localStorage.setItem('aurastock_offline_queue', JSON.stringify(queue));
    window.dispatchEvent(new CustomEvent('offline:mutation_queued', { detail: mutation }));
  }

  public async getPendingMutations(): Promise<OfflineMutation[]> {
    try {
      const raw = localStorage.getItem('aurastock_offline_queue');
      if (!raw) return [];
      return JSON.parse(raw) as OfflineMutation[];
    } catch {
      return [];
    }
  }

  public async updateMutationStatus(
    operation_id: string,
    status: OfflineMutation['sync_status'],
    server_ack_id?: string,
    error?: string
  ): Promise<void> {
    const queue = await this.getPendingMutations();
    const item = queue.find(q => q.operation_id === operation_id);
    if (item) {
      item.sync_status = status;
      if (server_ack_id) item.server_ack_id = server_ack_id;
      if (error) item.last_error = error;
      if (status === 'RETRY_PENDING') item.retry_count = (item.retry_count || 0) + 1;
      localStorage.setItem('aurastock_offline_queue', JSON.stringify(queue));
      window.dispatchEvent(new CustomEvent('offline:mutation_updated', { detail: item }));
    }
  }

  public async clearSyncedMutations(): Promise<void> {
    const queue = await this.getPendingMutations();
    const remaining = queue.filter(q => q.sync_status !== 'SYNCED');
    localStorage.setItem('aurastock_offline_queue', JSON.stringify(remaining));
    window.dispatchEvent(new CustomEvent('offline:queue_cleared', { detail: { remaining: remaining.length } }));
  }
}

export const nativeBridge = NativeBridge.getInstance();
