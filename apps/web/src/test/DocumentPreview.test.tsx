import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DocumentPreviewModal } from '../components/DocumentPreviewModal';
import { BarcodeLabelModal } from '../components/BarcodeLabelModal';
import { api } from '../api/client';
import { DocumentPrinter } from '../services/DocumentPrinter';

vi.mock('../api/client', () => ({
  api: {
    getDocumentPayload: vi.fn(),
  },
}));

describe('Phase 3B: Document Preview, PDF & Barcode Labels', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    (api.getDocumentPayload as any).mockResolvedValue({
      header: {
        company_name: 'AuraStock Enterprise',
        company_email: 'ops@aurastock.local',
        company_phone: '+1 800 555-AURA',
        company_address: '100 Logistics Blvd, Austin, TX',
        document_type: 'PURCHASE_ORDER',
        document_title: 'PURCHASE ORDER',
        document_number: 'PO-20260818-0001',
        date_formatted: 'August 18, 2026',
        status: 'APPROVED',
        barcode_value: 'PO-20260818-0001'
      },
      party: {
        party_type: 'Vendor / Supplier',
        name: 'Acme Components Corp',
        code: 'SUP-ACME-01',
        contact_person: 'John Buyer',
        email: 'john@acme.com',
        billing_address: '500 Supplier Way, Chicago, IL'
      },
      facility: {
        warehouse_name: 'Austin Fulfillment Center',
        warehouse_code: 'WH-ATX-01',
        address: 'Austin, TX'
      },
      lines: [
        {
          line_number: 1,
          item_sku: 'SKU-IOT-001',
          item_name: 'Industrial IoT Sensor Pro',
          variant_name: 'Standard',
          quantity: 10,
          uom: 'unit',
          unit_price: 50.0,
          discount: 0.0,
          tax: 0.0,
          subtotal: 500.0
        }
      ],
      summary: {
        currency: 'USD',
        subtotal: 500.0,
        discount_total: 0.0,
        tax_total: 0.0,
        grand_total: 500.0,
        payment_terms: 'Net 30 Days'
      },
      metadata: {},
      footer_text: 'Authorized System Document'
    });

    vi.spyOn(DocumentPrinter, 'printHtml').mockResolvedValue();
    vi.spyOn(DocumentPrinter, 'downloadPdf').mockResolvedValue();
  });

  it('renders DocumentPreviewModal with authoritative data and switches layout', async () => {
    render(
      <DocumentPreviewModal
        isOpen={true}
        onClose={vi.fn()}
        documentType="PURCHASE_ORDER"
        documentId="po-123"
      />
    );

    await waitFor(() => {
      expect(screen.getAllByText('PURCHASE ORDER').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/PO-20260818-0001/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Acme Components Corp/i)).toBeInTheDocument();
      expect(screen.getByText('Industrial IoT Sensor Pro')).toBeInTheDocument();
      expect(screen.getAllByText(/500\.00/i).length).toBeGreaterThanOrEqual(1);
    });

    // Switch to Thermal layout
    const thermalBtn = screen.getByRole('button', { name: /Thermal \(80mm\)/i });
    fireEvent.click(thermalBtn);

    expect(screen.getByRole('button', { name: /Thermal \(80mm\)/i })).toHaveClass('btn-primary');
  });

  it('triggers browser print and PDF download from preview modal', async () => {
    render(
      <DocumentPreviewModal
        isOpen={true}
        onClose={vi.fn()}
        documentType="PURCHASE_ORDER"
        documentId="po-123"
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Industrial IoT Sensor Pro')).toBeInTheDocument();
    });

    // Print button
    const printBtn = screen.getByRole('button', { name: /^Print$/i });
    fireEvent.click(printBtn);

    await waitFor(() => {
      expect(DocumentPrinter.printHtml).toHaveBeenCalled();
    });

    // Download PDF button
    const downloadBtn = screen.getByRole('button', { name: /Download PDF/i });
    fireEvent.click(downloadBtn);

    await waitFor(() => {
      expect(DocumentPrinter.downloadPdf).toHaveBeenCalledWith(
        'PURCHASE_ORDER',
        'po-123',
        'PO-20260818-0001.pdf'
      );
    });
  });

  it('renders BarcodeLabelModal and executes sticker sheet print', async () => {
    const sampleItems = [
      {
        title: 'Thermal Sensor Pro',
        sku: 'SKU-THM-100',
        variant: 'Pro',
        barcode: '890123456789',
        bin_code: 'BIN-01',
        price_formatted: '$49.99'
      }
    ];

    render(
      <BarcodeLabelModal
        isOpen={true}
        onClose={vi.fn()}
        items={sampleItems}
      />
    );

    expect(screen.getByText(/Print Barcode Labels \(1 item\)/i)).toBeInTheDocument();
    expect(screen.getByText('Thermal Sensor Pro')).toBeInTheDocument();
    expect(screen.getByText(/BIN: BIN-01/i)).toBeInTheDocument();

    // Increase copies
    const copiesInput = screen.getByRole('spinbutton');
    fireEvent.change(copiesInput, { target: { value: '3' } });

    const printStickersBtn = screen.getByRole('button', { name: /Print Stickers \(3\)/i });
    fireEvent.click(printStickersBtn);

    await waitFor(() => {
      expect(DocumentPrinter.printHtml).toHaveBeenCalled();
    });
  });
});
