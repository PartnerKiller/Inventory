import { DocumentType, PrintLayout } from '@inventory/shared-types';
import { nativeBridge } from '@inventory/native-bridge';
import { api } from '../api/client';

export interface DocumentPrinterInterface {
  printHtml: (htmlContent: string, layout: PrintLayout) => Promise<void>;
  downloadPdf: (docType: DocumentType, docId: string, filename: string) => Promise<void>;
}

export class BrowserDocumentPrinter implements DocumentPrinterInterface {
  async printHtml(htmlContent: string, layout: PrintLayout): Promise<void> {
    await nativeBridge.printDocument(htmlContent, layout);
  }

  async downloadPdf(docType: DocumentType, docId: string, filename: string): Promise<void> {
    const token = api.getToken() || localStorage.getItem('aurastock_access_token');
    const baseUrl = api.getBaseUrl();
    const response = await fetch(`${baseUrl}/documents/${docType}/${docId}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });

    if (!response.ok) {
      throw new Error(`Failed to download PDF: ${response.statusText}`);
    }

    const blob = await response.blob();
    const finalFilename = filename.endsWith('.pdf') ? filename : `${filename}.pdf`;
    await nativeBridge.saveFile({
      data: blob,
      filename: finalFilename,
      mimeType: 'application/pdf',
      filterName: 'PDF Documents',
      extensions: ['pdf']
    });
  }
}

export class TauriDocumentPrinter implements DocumentPrinterInterface {
  async printHtml(htmlContent: string, layout: PrintLayout): Promise<void> {
    const success = await nativeBridge.printDocument(htmlContent, layout);
    if (!success) {
      console.warn('Tauri printDocument returned false, fallback invoked');
    }
  }

  async downloadPdf(docType: DocumentType, docId: string, filename: string): Promise<void> {
    const token = api.getToken() || localStorage.getItem('aurastock_access_token');
    const baseUrl = api.getBaseUrl();
    const response = await fetch(`${baseUrl}/documents/${docType}/${docId}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });

    if (!response.ok) {
      throw new Error(`Failed to download PDF: ${response.statusText}`);
    }

    const blob = await response.blob();
    const finalFilename = filename.endsWith('.pdf') ? filename : `${filename}.pdf`;
    
    // Invoke native Windows Save-As dialog via NativeCapabilities
    await nativeBridge.saveFile({
      data: blob,
      filename: finalFilename,
      defaultPath: finalFilename,
      mimeType: 'application/pdf',
      filterName: 'PDF Documents (*.pdf)',
      extensions: ['pdf']
    });
  }
}

export class UnifiedDocumentPrinter implements DocumentPrinterInterface {
  private browserPrinter = new BrowserDocumentPrinter();
  private tauriPrinter = new TauriDocumentPrinter();

  public getActivePrinter(): DocumentPrinterInterface {
    return nativeBridge.isDesktop() ? this.tauriPrinter : this.browserPrinter;
  }

  async printHtml(htmlContent: string, layout: PrintLayout): Promise<void> {
    return this.getActivePrinter().printHtml(htmlContent, layout);
  }

  async downloadPdf(docType: DocumentType, docId: string, filename: string): Promise<void> {
    return this.getActivePrinter().downloadPdf(docType, docId, filename);
  }
}

export const DocumentPrinter = new UnifiedDocumentPrinter();
