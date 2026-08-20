import React, { useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Tag, Printer, X, Download, Copy, Layers, Check } from 'lucide-react';
import { BarcodeLabelItem } from '@inventory/shared-types';
import { DocumentPrinter } from '../services/DocumentPrinter';

interface BarcodeLabelModalProps {
  isOpen: boolean;
  onClose: () => void;
  items: BarcodeLabelItem[];
}

export const BarcodeLabelModal: React.FC<BarcodeLabelModalProps> = ({
  isOpen,
  onClose,
  items
}) => {
  const [copies, setCopies] = useState<number>(1);
  const [isPrinting, setIsPrinting] = useState<boolean>(false);
  const sheetRef = useRef<HTMLDivElement>(null);

  if (!isOpen || items.length === 0) return null;

  const handlePrint = async () => {
    if (!sheetRef.current) return;
    setIsPrinting(true);
    try {
      await DocumentPrinter.printHtml(sheetRef.current.innerHTML, 'LABEL');
    } catch (e) {
      console.error('Label print failed:', e);
    } finally {
      setIsPrinting(false);
    }
  };

  const modalElement = (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-content"
        style={{
          maxWidth: '750px',
          width: '90%',
          backgroundColor: '#0f172a',
          borderColor: 'var(--border-subtle)',
          padding: 0,
          overflow: 'hidden'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
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
            <Tag size={18} color="#3b82f6" />
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0, color: 'var(--text-primary)' }}>
                Print Barcode Labels ({items.length} item{items.length > 1 ? 's' : ''})
              </h3>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Standard 2" × 1" (50mm × 25mm) thermal & sticker sheets
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Copies:</span>
              <input
                type="number"
                min="1"
                max="50"
                value={copies}
                onChange={(e) => setCopies(Math.max(1, parseInt(e.target.value) || 1))}
                style={{
                  width: '55px',
                  padding: '3px 6px',
                  backgroundColor: '#0f172a',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '4px',
                  color: 'var(--text-primary)',
                  fontSize: '12px',
                  textAlign: 'center'
                }}
              />
            </div>

            <button
              className="btn btn-primary btn-sm"
              onClick={handlePrint}
              disabled={isPrinting}
            >
              <Printer size={14} />
              {isPrinting ? 'Printing...' : `Print Stickers (${items.length * copies})`}
            </button>
            <button className="btn btn-outline btn-sm" onClick={onClose} style={{ padding: '4px', borderRadius: '50%' }}>
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body Container */}
        <div style={{ padding: '20px', overflowY: 'auto', maxHeight: '75vh', backgroundColor: '#0f172a' }}>
          <div
            ref={sheetRef}
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
              gap: '12px'
            }}
          >
            {items.map((item, idx) =>
              Array.from({ length: copies }).map((_, cIdx) => (
                <div
                  key={`${idx}-${cIdx}`}
                  style={{
                    border: '1px dashed #334155',
                    borderRadius: '6px',
                    padding: '10px',
                    backgroundColor: '#1e293b',
                    textAlign: 'center'
                  }}
                >
                  <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.title}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                    SKU: {item.sku}
                  </div>

                  <div style={{ fontSize: '20px', fontFamily: 'monospace', letterSpacing: '4px', margin: '6px 0 2px', color: '#f8fafc' }}>
                    ||||| ||| |||| || |||||
                  </div>

                  <div style={{ fontSize: '9px', fontFamily: 'monospace', color: '#64748b', marginTop: '2px' }}>
                    *{item.barcode}*
                  </div>

                  {item.bin_code && (
                    <div style={{ fontSize: '9px', fontWeight: 700, color: '#2563eb', marginTop: '4px' }}>
                      BIN: {item.bin_code}
                    </div>
                  )}

                  {item.price_formatted && (
                    <div style={{ fontSize: '10px', fontWeight: 800, color: '#16a34a', marginTop: '2px' }}>
                      {item.price_formatted}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalElement, document.body);
};
