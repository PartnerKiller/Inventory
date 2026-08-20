import React, { useState, useEffect } from 'react';
import { Barcode, Printer, QrCode, Scan, Copy, Check, Download, Tag } from 'lucide-react';
import { api } from '../api/client';
import { Item, BarcodeLabelItem } from '@inventory/shared-types';
import { nativeBridge } from '@inventory/native-bridge';
import { BarcodeLabelModal } from '../components/BarcodeLabelModal';
import { DocumentPrinter } from '../services/DocumentPrinter';

export const BarcodeStationPage: React.FC = () => {
  const [items, setItems] = useState<Item[]>([]);
  const [selectedBarcode, setSelectedBarcode] = useState('890123456789');
  const [selectedSymbology, setSelectedSymbology] = useState<'code128' | 'qr'>('code128');
  const [labelTitle, setLabelTitle] = useState('Industrial IoT Thermal Sensor Pro');
  const [labelSku, setLabelSku] = useState('SKU-THM-100');
  const [copied, setCopied] = useState(false);
  const [isLabelModalOpen, setIsLabelModalOpen] = useState(false);

  useEffect(() => {
    const fetchItems = async () => {
      try {
        const res = await api.getItems({ page_size: 100 });
        setItems(res.items);
      } catch (err) {
        console.error('Failed to load items:', err);
      }
    };
    fetchItems();
  }, []);

  const handleSelectVariant = (barcodeVal: string, itemTitle: string, sku: string) => {
    setSelectedBarcode(barcodeVal);
    setLabelTitle(itemTitle);
    setLabelSku(sku);
  };

  const handlePrint = async () => {
    const labelHtml = `
      <div style="width: 320px; border: 2px solid #000; padding: 12px; font-family: sans-serif; text-align: center; border-radius: 8px;">
        <div style="font-size: 16px; font-weight: bold; margin-bottom: 4px;">AuraStock Enterprise</div>
        <div style="font-size: 14px; font-weight: 600; color: #333;">${labelTitle}</div>
        <div style="font-size: 13px; font-family: monospace; font-weight: bold; margin: 4px 0;">SKU: ${labelSku}</div>
        <img src="/api/v1/barcodes/image/${selectedBarcode}?symbology=${selectedSymbology}" style="max-width: 260px; height: 75px; margin: 8px 0;" />
        <div style="font-size: 14px; font-family: monospace; letter-spacing: 2px; font-weight: bold;">${selectedBarcode}</div>
      </div>
    `;

    // ZPL payload for direct thermal printers in Tauri
    const zplData = `
      ^XA
      ^FO50,40^A0N,28,28^FDAuraStock Enterprise^FS
      ^FO50,75^A0N,22,22^FD${labelTitle.slice(0, 24)}^FS
      ^FO50,105^A0N,20,20^FDSKU: ${labelSku}^FS
      ^FO50,135^BCN,70,Y,N,N^FD${selectedBarcode}^FS
      ^XZ
    `;

    await nativeBridge.printThermalLabel(labelHtml, zplData);
  };

  const handleCopyBarcode = () => {
    navigator.clipboard.writeText(selectedBarcode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const imageUrl = `/api/v1/barcodes/image/${encodeURIComponent(selectedBarcode)}?symbology=${selectedSymbology}`;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Barcode Station & Label Generator
          </h1>
          <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Linear Code128, 2D QR Code generator, ESC/POS and Zebra (ZPL) direct thermal label dispatch
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-secondary" onClick={() => setIsLabelModalOpen(true)}>
            <Tag size={16} /> Print Sheet of Labels
          </button>
          <button className="btn btn-primary" onClick={handlePrint}>
            <Printer size={16} /> Print Thermal Label
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
        {/* Label Preview & Settings */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Live Printable Label Preview</div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className={`btn btn-sm ${selectedSymbology === 'code128' ? 'btn-primary' : 'btn-outline'}`}
                onClick={() => setSelectedSymbology('code128')}
              >
                <Barcode size={14} /> Code128 Linear
              </button>
              <button
                className={`btn btn-sm ${selectedSymbology === 'qr' ? 'btn-primary' : 'btn-outline'}`}
                onClick={() => setSelectedSymbology('qr')}
              >
                <QrCode size={14} /> 2D QR Matrix
              </button>
            </div>
          </div>

          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '30px',
            backgroundColor: '#ffffff',
            borderRadius: 'var(--radius-md)',
            border: '2px dashed #94a3b8',
            color: '#0f172a',
            margin: '10px 0 20px',
            boxShadow: 'var(--shadow-md)',
            maxWidth: '420px',
            marginLeft: 'auto',
            marginRight: 'auto'
          }}>
            <div style={{ fontSize: '12px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '1px', color: '#64748b' }}>
              AuraStock Enterprise
            </div>
            <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '4px', textAlign: 'center' }}>
              {labelTitle}
            </div>
            <div style={{ fontSize: '13px', fontFamily: 'monospace', fontWeight: 600, color: '#475569', margin: '4px 0' }}>
              SKU: {labelSku}
            </div>

            <img
              src={imageUrl}
              alt="Barcode"
              style={{
                height: selectedSymbology === 'code128' ? '80px' : '120px',
                maxWidth: '300px',
                margin: '12px 0',
                objectFit: 'contain'
              }}
            />

            <div style={{ fontSize: '15px', fontFamily: 'monospace', fontWeight: 800, letterSpacing: '3px' }}>
              {selectedBarcode}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <div className="form-group">
              <label className="form-label">Barcode Value / Data</label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  type="text"
                  className="form-control"
                  value={selectedBarcode}
                  onChange={(e) => setSelectedBarcode(e.target.value)}
                />
                <button className="btn btn-secondary btn-sm" onClick={handleCopyBarcode} title="Copy code">
                  {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
                </button>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Item SKU</label>
              <input
                type="text"
                className="form-control"
                value={labelSku}
                onChange={(e) => setLabelSku(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Item Catalog Barcode Selector */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Registered Item Barcodes</div>
            <span className="badge badge-info">{items.length} SKUs</span>
          </div>

          <div style={{ maxHeight: '420px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {items.map((item) =>
              item.variants.map((v) => {
                const bc = v.barcodes[0]?.barcodeValue || `${item.sku}001`;
                return (
                  <div
                    key={v.id}
                    onClick={() => handleSelectVariant(bc, item.name, item.sku)}
                    style={{
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: selectedBarcode === bc ? 'rgba(37, 99, 235, 0.15)' : 'var(--bg-app)',
                      border: `1px solid ${selectedBarcode === bc ? '#3b82f6' : 'var(--border-subtle)'}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                        {item.name}
                      </div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                        SKU: {item.sku} &bull; {v.variantName}
                      </div>
                    </div>

                    <span className="scan-code-pill" style={{ fontSize: '12px' }}>
                      {bc}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      <BarcodeLabelModal
        isOpen={isLabelModalOpen}
        onClose={() => setIsLabelModalOpen(false)}
        items={
          items.flatMap(item =>
            item.variants.map(v => ({
              title: item.name,
              sku: item.sku,
              variant: v.variantName,
              barcode: v.barcodes[0]?.barcodeValue || `${item.sku}001`,
              price_formatted: `$${v.sellingPrice?.toFixed(2) || '0.00'}`
            }))
          )
        }
      />
    </div>
  );
};
