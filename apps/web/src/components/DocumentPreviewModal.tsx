import React, { useState, useEffect, useRef } from 'react';
import {
  Printer,
  Download,
  X,
  FileText,
  Building2,
  MapPin,
  Calendar,
  Layers,
  AlertCircle,
  Loader2,
  Maximize2
} from 'lucide-react';
import { DocumentType, DocumentPayload, PrintLayout } from '@inventory/shared-types';
import { api } from '../api/client';
import { DocumentPrinter } from '../services/DocumentPrinter';

interface DocumentPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  documentType: DocumentType;
  documentId: string;
}

export const DocumentPreviewModal: React.FC<DocumentPreviewModalProps> = ({
  isOpen,
  onClose,
  documentType,
  documentId
}) => {
  const [payload, setPayload] = useState<DocumentPayload | null>(null);
  const [layout, setLayout] = useState<PrintLayout>('A4');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isPrinting, setIsPrinting] = useState<boolean>(false);
  const [isDownloading, setIsDownloading] = useState<boolean>(false);
  const previewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen || !documentId) return;

    const loadDocument = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getDocumentPayload(documentType, documentId);
        setPayload(data);
      } catch (err: any) {
        setError(err.message || 'Failed to load document preview payload');
      } finally {
        setLoading(false);
      }
    };

    loadDocument();
  }, [isOpen, documentType, documentId]);

  if (!isOpen) return null;

  const handlePrint = async () => {
    if (!previewRef.current) return;
    setIsPrinting(true);
    try {
      await DocumentPrinter.printHtml(previewRef.current.innerHTML, layout);
    } catch (e) {
      console.error('Print failed:', e);
    } finally {
      setIsPrinting(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (!payload) return;
    setIsDownloading(true);
    try {
      await DocumentPrinter.downloadPdf(
        documentType,
        documentId,
        `${payload.header.document_number}.pdf`
      );
    } catch (e: any) {
      alert(`PDF download failed: ${e.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div
        className="modal-content"
        style={{
          maxWidth: layout === 'THERMAL' ? '480px' : '900px',
          width: '95%',
          maxHeight: '94vh',
          display: 'flex',
          flexDirection: 'column',
          padding: 0,
          overflow: 'hidden',
          backgroundColor: '#0f172a',
          borderColor: 'var(--border-subtle)'
        }}
      >
        {/* Header Toolbar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 20px',
            borderBottom: '1px solid var(--border-subtle)',
            backgroundColor: '#1e293b'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileText size={18} color="#3b82f6" />
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0, color: 'var(--text-primary)' }}>
                {payload ? payload.header.document_title : 'Document Preview'}
              </h3>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                {payload ? `#${payload.header.document_number}` : 'Loading details...'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* Layout switch */}
            <div style={{ display: 'flex', background: '#0f172a', borderRadius: '6px', padding: '2px', border: '1px solid var(--border-subtle)' }}>
              <button
                type="button"
                className={`btn btn-sm ${layout === 'A4' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '3px 10px', fontSize: '12px' }}
                onClick={() => setLayout('A4')}
              >
                A4 Standard
              </button>
              <button
                type="button"
                className={`btn btn-sm ${layout === 'THERMAL' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '3px 10px', fontSize: '12px' }}
                onClick={() => setLayout('THERMAL')}
              >
                Thermal (80mm)
              </button>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleDownloadPdf}
              disabled={loading || isDownloading}
              title="Download Server-Generated PDF"
            >
              {isDownloading ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
              <span>Download PDF</span>
            </button>

            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handlePrint}
              disabled={loading || isPrinting}
              title="Send to Printer"
            >
              {isPrinting ? <Loader2 size={14} className="spin" /> : <Printer size={14} />}
              <span>Print</span>
            </button>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onClose}
              style={{ padding: '6px' }}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Document Render Body */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px',
            backgroundColor: '#090d16',
            display: 'flex',
            justifyContent: 'center'
          }}
        >
          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px', color: 'var(--text-muted)' }}>
              <Loader2 size={32} className="spin" style={{ color: '#3b82f6', marginBottom: '12px' }} />
              <div>Assembling authoritative document preview...</div>
            </div>
          )}

          {error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '20px', backgroundColor: '#450a0a', border: '1px solid #7f1d1d', borderRadius: '8px', color: '#fca5a5' }}>
              <AlertCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && payload && (
            <div
              ref={previewRef}
              style={{
                width: layout === 'THERMAL' ? '320px' : '780px',
                minHeight: layout === 'THERMAL' ? 'auto' : '980px',
                backgroundColor: '#ffffff',
                color: '#0f172a',
                padding: layout === 'THERMAL' ? '16px' : '36px',
                boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
                borderRadius: '4px',
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                fontSize: layout === 'THERMAL' ? '11px' : '13px',
                lineHeight: 1.4
              }}
            >
              {/* Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '2px solid #0f172a', paddingBottom: '16px', marginBottom: '16px' }}>
                <div>
                  <div style={{ fontSize: layout === 'THERMAL' ? '16px' : '22px', fontWeight: 800, color: '#1e3a8a', letterSpacing: '-0.5px' }}>
                    {payload.header.company_name}
                  </div>
                  {payload.header.company_address && (
                    <div style={{ color: '#475569', fontSize: layout === 'THERMAL' ? '10px' : '12px', marginTop: '2px' }}>
                      {payload.header.company_address}
                    </div>
                  )}
                  <div style={{ color: '#64748b', fontSize: layout === 'THERMAL' ? '10px' : '11px', marginTop: '2px' }}>
                    {payload.header.company_email} {payload.header.company_phone ? `| ${payload.header.company_phone}` : ''}
                  </div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: layout === 'THERMAL' ? '13px' : '18px', fontWeight: 800, color: '#0f172a' }}>
                    {payload.header.document_title}
                  </div>
                  <div style={{ fontSize: layout === 'THERMAL' ? '11px' : '13px', fontWeight: 700, color: '#2563eb', marginTop: '2px' }}>
                    {payload.header.document_number}
                  </div>
                  <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                    Date: {payload.header.date_formatted}
                  </div>
                  <div style={{ marginTop: '4px' }}>
                    <span
                      style={{
                        display: 'inline-block',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: 700,
                        backgroundColor: '#f1f5f9',
                        color: '#334155',
                        border: '1px solid #cbd5e1'
                      }}
                    >
                      {payload.header.status}
                    </span>
                  </div>
                </div>
              </div>

              {/* Barcode Visual Representation */}
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '16px', padding: '6px', backgroundColor: '#f8fafc', borderRadius: '4px', border: '1px dashed #cbd5e1' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ letterSpacing: '4px', fontFamily: 'monospace', fontSize: '18px', fontWeight: 900 }}>
                    ||| | |||| || | |||| |||
                  </div>
                  <div style={{ fontSize: '10px', color: '#64748b', fontFamily: 'monospace', marginTop: '2px' }}>
                    *{payload.header.barcode_value}*
                  </div>
                </div>
              </div>

              {/* Parties & Facilities Grid */}
              {(payload.party || payload.facility || Object.keys(payload.metadata).length > 0) && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: layout === 'THERMAL' ? '1fr' : '1fr 1fr',
                    gap: '12px',
                    padding: '12px',
                    backgroundColor: '#f8fafc',
                    borderRadius: '6px',
                    border: '1px solid #e2e8f0',
                    marginBottom: '16px'
                  }}
                >
                  {payload.party && (
                    <div>
                      <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '4px' }}>
                        {payload.party.party_type}
                      </div>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>
                        {payload.party.name} {payload.party.code ? `(${payload.party.code})` : ''}
                      </div>
                      {payload.party.billing_address && (
                        <div style={{ fontSize: '11px', color: '#475569', marginTop: '2px' }}>
                          <b>Address:</b> {payload.party.billing_address}
                        </div>
                      )}
                      {payload.party.contact_person && (
                        <div style={{ fontSize: '11px', color: '#475569' }}>
                          <b>Contact:</b> {payload.party.contact_person}
                        </div>
                      )}
                      {payload.party.email && (
                        <div style={{ fontSize: '11px', color: '#475569' }}>
                          <b>Email:</b> {payload.party.email}
                        </div>
                      )}
                    </div>
                  )}

                  {payload.facility && (
                    <div>
                      <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '4px' }}>
                        Warehouse / Fulfillment Facility
                      </div>
                      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>
                        {payload.facility.warehouse_name} ({payload.facility.warehouse_code})
                      </div>
                      {payload.facility.address && (
                        <div style={{ fontSize: '11px', color: '#475569', marginTop: '2px' }}>
                          {payload.facility.address}
                        </div>
                      )}
                    </div>
                  )}

                  {!payload.facility && payload.metadata && Object.keys(payload.metadata).length > 0 && (
                    <div>
                      <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '4px' }}>
                        Logistics Details
                      </div>
                      {Object.entries(payload.metadata).map(([k, v]) => (
                        <div key={k} style={{ fontSize: '11px', color: '#475569' }}>
                          <b>{k.replace('_', ' ').toUpperCase()}:</b> {String(v)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Items Table */}
              <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '16px' }}>
                <thead>
                  <tr style={{ backgroundColor: '#0f172a', color: '#ffffff', textAlign: 'left' }}>
                    <th style={{ padding: '6px 8px', fontSize: '11px', width: '30px' }}>#</th>
                    <th style={{ padding: '6px 8px', fontSize: '11px' }}>SKU / Item Description</th>
                    {payload.lines.some(l => l.bin_location) && (
                      <th style={{ padding: '6px 8px', fontSize: '11px' }}>Location</th>
                    )}
                    <th style={{ padding: '6px 8px', fontSize: '11px', textAlign: 'right' }}>Qty</th>
                    {payload.summary && (
                      <>
                        <th style={{ padding: '6px 8px', fontSize: '11px', textAlign: 'right' }}>Price</th>
                        <th style={{ padding: '6px 8px', fontSize: '11px', textAlign: 'right' }}>Subtotal</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {payload.lines.map((line, idx) => (
                    <tr
                      key={idx}
                      style={{
                        borderBottom: '1px solid #e2e8f0',
                        backgroundColor: idx % 2 === 0 ? '#ffffff' : '#f8fafc'
                      }}
                    >
                      <td style={{ padding: '6px 8px', fontSize: '11px', color: '#64748b' }}>{line.line_number}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <div style={{ fontWeight: 600, color: '#0f172a' }}>{line.item_name}</div>
                        <div style={{ fontSize: '10px', color: '#64748b' }}>
                          SKU: {line.item_sku} {line.variant_name ? `• ${line.variant_name}` : ''}
                        </div>
                      </td>
                      {payload.lines.some(l => l.bin_location) && (
                        <td style={{ padding: '6px 8px', fontSize: '11px', color: '#475569' }}>
                          {line.bin_location || '-'}
                        </td>
                      )}
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>
                        {line.quantity} {line.uom}
                      </td>
                      {payload.summary && (
                        <>
                          <td style={{ padding: '6px 8px', textAlign: 'right', color: '#475569' }}>
                            ${line.unit_price?.toFixed(2) ?? '-'}
                          </td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: '#0f172a' }}>
                            ${line.subtotal?.toFixed(2) ?? '-'}
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Summary Block */}
              {payload.summary && (
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '20px' }}>
                  <div style={{ width: layout === 'THERMAL' ? '100%' : '260px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: '#475569', fontSize: '12px' }}>
                      <span>Subtotal:</span>
                      <span>${payload.summary.subtotal.toFixed(2)}</span>
                    </div>
                    {payload.summary.discount_total > 0 && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: '#16a34a', fontSize: '12px' }}>
                        <span>Discount:</span>
                        <span>-${payload.summary.discount_total.toFixed(2)}</span>
                      </div>
                    )}
                    {payload.summary.tax_total > 0 && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: '#475569', fontSize: '12px' }}>
                        <span>Estimated Tax:</span>
                        <span>+${payload.summary.tax_total.toFixed(2)}</span>
                      </div>
                    )}
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '8px 0',
                        borderTop: '2px solid #0f172a',
                        fontWeight: 800,
                        fontSize: '14px',
                        color: '#0f172a'
                      }}
                    >
                      <span>Grand Total:</span>
                      <span>${payload.summary.grand_total.toFixed(2)} {payload.summary.currency}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Notes & Terms */}
              {payload.summary?.notes && (
                <div style={{ fontSize: '11px', color: '#64748b', borderTop: '1px solid #e2e8f0', paddingTop: '10px', marginTop: '10px' }}>
                  <b>Instructions / Notes:</b> {payload.summary.notes}
                </div>
              )}

              {/* Footer */}
              <div
                style={{
                  marginTop: '24px',
                  borderTop: '1px solid #e2e8f0',
                  paddingTop: '10px',
                  fontSize: '9px',
                  color: '#94a3b8',
                  textAlign: 'center'
                }}
              >
                {payload.footer_text || 'Generated by AuraStock Enterprise. Immutable Transaction Record.'}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
