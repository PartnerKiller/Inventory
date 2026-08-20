import React, { useState, useEffect } from 'react';
import {
  ArrowLeftRight, Sliders, History, Search, Filter, RefreshCw,
  Plus, CheckCircle, AlertTriangle, ChevronLeft, ChevronRight,
  Warehouse as WarehouseIcon, Box, ArrowUpRight, ArrowDownLeft, FileText, X, Printer
} from 'lucide-react';
import { api, GetStockBalancesParams, GetLedgerEntriesParams } from '../api/client';
import { StockLedgerEntry, StockBalanceCache, Warehouse, Item, LocationBin, DocumentType } from '@inventory/shared-types';
import { Modal } from '../components/Modal';
import { DocumentPreviewModal } from '../components/DocumentPreviewModal';
import { useWarehouse } from '../context/WarehouseContext';

export const StockLedgerPage: React.FC = () => {
  const { activeWarehouseId, warehouses: contextWarehouses } = useWarehouse();
  const [activeTab, setActiveTab] = useState<'balances' | 'journal'>('balances');

  // Balances State
  const [balances, setBalances] = useState<StockBalanceCache[]>([]);
  const [totalBalances, setTotalBalances] = useState<number>(0);
  const [totalBalPages, setTotalBalPages] = useState<number>(1);
  const [balPage, setBalPage] = useState<number>(1);
  const [balPageSize, setBalPageSize] = useState<number>(15);
  const [selectedWarehouseFilter, setSelectedWarehouseFilter] = useState<string>(activeWarehouseId);
  const [selectedBinFilter, setSelectedBinFilter] = useState<string>('');
  const [stockStatusFilter, setStockStatusFilter] = useState<'all' | 'in_stock' | 'out_of_stock'>('in_stock');
  const [balanceSearch, setBalanceSearch] = useState<string>('');

  // Journal State
  const [entries, setEntries] = useState<StockLedgerEntry[]>([]);
  const [totalEntries, setTotalEntries] = useState<number>(0);
  const [totalEntryPages, setTotalEntryPages] = useState<number>(1);
  const [entryPage, setEntryPage] = useState<number>(1);
  const [entryPageSize, setEntryPageSize] = useState<number>(15);
  const [txTypeFilter, setTxTypeFilter] = useState<string>('');
  const [journalSearch, setJournalSearch] = useState<string>('');

  // Supporting Master Data
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewDoc, setPreviewDoc] = useState<{ type: DocumentType; id: string } | null>(null);

  // Modals
  const [isTransferModalOpen, setIsTransferModalOpen] = useState<boolean>(false);
  const [isAdjustmentModalOpen, setIsAdjustmentModalOpen] = useState(false);

  // Transfer Form State
  const [transferSrcWhId, setTransferSrcWhId] = useState('');
  const [transferSrcBinId, setTransferSrcBinId] = useState('');
  const [transferDstWhId, setTransferDstWhId] = useState('');
  const [transferDstBinId, setTransferDstBinId] = useState('');
  const [transferVariantId, setTransferVariantId] = useState('');
  const [transferQty, setTransferQty] = useState('1');
  const [transferNotes, setTransferNotes] = useState('');
  const [transferAvailStock, setTransferAvailStock] = useState<number | null>(null);

  // Adjustment Form State
  const [adjWhId, setAdjWhId] = useState('');
  const [adjBinId, setAdjBinId] = useState('');
  const [adjVariantId, setAdjVariantId] = useState('');
  const [adjCurrentStock, setAdjCurrentStock] = useState<number>(0);
  const [adjCountedQty, setAdjCountedQty] = useState('');
  const [adjReason, setAdjReason] = useState('CYCLE_COUNT_DISCREPANCY');
  const [adjType, setAdjType] = useState('INVENTORY_ADJUSTMENT');
  const [adjNotes, setAdjNotes] = useState('');

  // Load Master Options
  const loadMasterData = async () => {
    try {
      const [whs, itmsRes] = await Promise.all([
        api.getWarehouses(),
        api.getItems({ page_size: 300 }),
      ]);
      setWarehouses(whs);
      setItems(itmsRes.items);
    } catch (err: any) {
      console.error('Failed to load master lookup data:', err);
    }
  };

  // Load Balances
  const loadBalances = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);
      const params: GetStockBalancesParams = {
        warehouse_id: selectedWarehouseFilter || undefined,
        location_bin_id: selectedBinFilter || undefined,
        stock_status: stockStatusFilter,
        q: balanceSearch.trim() || undefined,
        page: balPage,
        page_size: balPageSize,
      };
      const res = await api.getStockBalances(params);
      setBalances(res.items);
      setTotalBalances(res.pagination.total_items ?? res.pagination.totalItems ?? 0);
      setTotalBalPages(res.pagination.total_pages ?? res.pagination.totalPages ?? 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load stock balances');
    } finally {
      setIsLoading(false);
    }
  };

  // Load Journal
  const loadJournal = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);
      const params: GetLedgerEntriesParams = {
        warehouse_id: selectedWarehouseFilter || undefined,
        transaction_type: txTypeFilter || undefined,
        q: journalSearch.trim() || undefined,
        page: entryPage,
        page_size: entryPageSize,
      };
      const res = await api.getLedgerEntries(params);
      setEntries(res.items);
      setTotalEntries(res.pagination.total_items ?? res.pagination.totalItems ?? 0);
      setTotalEntryPages(res.pagination.total_pages ?? res.pagination.totalPages ?? 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load ledger journal');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadMasterData();
  }, []);

  useEffect(() => {
    setSelectedWarehouseFilter(activeWarehouseId);
    setSelectedBinFilter('');
    setBalPage(1);
    setEntryPage(1);
  }, [activeWarehouseId]);

  useEffect(() => {
    if (activeTab === 'balances') {
      loadBalances();
    } else {
      loadJournal();
    }
  }, [activeTab, balPage, balPageSize, entryPage, entryPageSize, selectedWarehouseFilter, selectedBinFilter, stockStatusFilter, txTypeFilter]);

  // Handle Transfer Trigger for Specific Item & Bin
  const handleOpenTransfer = (bal?: StockBalanceCache) => {
    if (bal) {
      setTransferSrcWhId(bal.warehouse_id || '');
      setTransferSrcBinId(bal.location_bin_id || '');
      setTransferDstWhId(bal.warehouse_id || '');
      setTransferVariantId(bal.item_variant_id || '');
      setTransferAvailStock(bal.quantity_available ?? (bal.quantity_on_hand - bal.quantity_allocated));
    } else {
      setTransferSrcWhId(warehouses[0]?.id || '');
      setTransferSrcBinId(warehouses[0]?.bins?.[0]?.id || '');
      setTransferDstWhId(warehouses[0]?.id || '');
      setTransferVariantId(items[0]?.variants?.[0]?.id || '');
      setTransferAvailStock(null);
    }
    setTransferDstBinId('');
    setTransferQty('1');
    setTransferNotes('');
    setIsTransferModalOpen(true);
  };

  // Handle Adjustment Trigger for Specific Item & Bin
  const handleOpenAdjustment = (bal?: StockBalanceCache) => {
    if (bal) {
      setAdjWhId(bal.warehouse_id || '');
      setAdjBinId(bal.location_bin_id || '');
      setAdjVariantId(bal.item_variant_id || '');
      setAdjCurrentStock(bal.quantity_on_hand);
      setAdjCountedQty(String(bal.quantity_on_hand));
    } else {
      setAdjWhId(warehouses[0]?.id || '');
      setAdjBinId(warehouses[0]?.bins?.[0]?.id || '');
      setAdjVariantId(items[0]?.variants?.[0]?.id || '');
      setAdjCurrentStock(0);
      setAdjCountedQty('0');
    }
    setAdjReason('CYCLE_COUNT_DISCREPANCY');
    setAdjType('INVENTORY_ADJUSTMENT');
    setAdjNotes('');
    setIsAdjustmentModalOpen(true);
  };

  // Execute Transfer
  const handleExecuteTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transferSrcBinId || !transferDstBinId || !transferVariantId) {
      alert('Source bin, destination bin, and product variant are required');
      return;
    }
    if (transferSrcBinId === transferDstBinId) {
      alert('Source and destination bins cannot be identical');
      return;
    }

    try {
      await api.transferStock({
        item_variant_id: transferVariantId,
        source_bin_id: transferSrcBinId,
        destination_bin_id: transferDstBinId,
        quantity: parseFloat(transferQty) || 1,
        notes: transferNotes || undefined,
      });
      setIsTransferModalOpen(false);
      loadBalances();
      if (activeTab === 'journal') loadJournal();
    } catch (err: any) {
      alert(`Transfer failed: ${err.message}`);
    }
  };

  // Execute Adjustment
  const handleExecuteAdjustment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adjBinId || !adjVariantId) {
      alert('Bin and product variant are required');
      return;
    }
    if (!adjReason) {
      alert('Adjustment reason is required');
      return;
    }

    try {
      await api.adjustStock({
        item_variant_id: adjVariantId,
        location_bin_id: adjBinId,
        counted_quantity: parseFloat(adjCountedQty) || 0,
        reason: adjReason,
        adjustment_type: adjType,
      });
      setIsAdjustmentModalOpen(false);
      loadBalances();
      if (activeTab === 'journal') loadJournal();
    } catch (err: any) {
      alert(`Adjustment failed: ${err.message}`);
    }
  };

  // Helper: selected warehouse bins for modals
  const srcWhBins = warehouses.find(w => w.id === transferSrcWhId)?.bins || [];
  const dstWhBins = warehouses.find(w => w.id === transferDstWhId)?.bins || [];
  const adjWhBins = warehouses.find(w => w.id === adjWhId)?.bins || [];

  const countedVal = parseFloat(adjCountedQty) || 0;
  const varianceDelta = countedVal - adjCurrentStock;

  return (
    <div>
      {/* Header & Main Actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Inventory Overview & Stock Ledger
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Multi-bin physical stock balances, atomic transfers, physical count adjustments, and immutable double-entry journal
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={() => handleOpenAdjustment()}>
            <Sliders size={15} /> Stock Adjustment
          </button>
          <button className="btn btn-primary" onClick={() => handleOpenTransfer()}>
            <ArrowLeftRight size={16} /> Stock Transfer
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '16px' }}>
        <button
          className={`btn ${activeTab === 'balances' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('balances')}
        >
          <Box size={15} /> Physical Balances (Overview)
        </button>
        <button
          className={`btn ${activeTab === 'journal' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('journal')}
        >
          <History size={15} /> Immutable Movement Journal
        </button>
      </div>

      {/* Error Alert */}
      {errorMessage && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid #ef4444',
          borderRadius: 'var(--radius-sm)',
          color: '#f87171',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <AlertTriangle size={18} />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 1: PHYSICAL BALANCES OVERVIEW */}
      {/* ========================================================================= */}
      {activeTab === 'balances' && (
        <div>
          {/* Filter Toolbar */}
          <div className="card" style={{ marginBottom: '16px', padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: '12px', alignItems: 'center' }}>
              <div style={{ position: 'relative' }}>
                <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  placeholder="Search SKU, product name, or bin code..."
                  value={balanceSearch}
                  onChange={(e) => setBalanceSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { setBalPage(1); loadBalances(); } }}
                  style={{ paddingLeft: '34px', height: '36px', fontSize: '13px' }}
                />
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={selectedWarehouseFilter}
                  onChange={(e) => { setSelectedWarehouseFilter(e.target.value); setBalPage(1); }}
                >
                  <option value="">All Warehouses</option>
                  {warehouses.map((w) => (
                    <option key={w.id} value={w.id}>{w.code} ({w.name})</option>
                  ))}
                </select>
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={stockStatusFilter}
                  onChange={(e: any) => { setStockStatusFilter(e.target.value); setBalPage(1); }}
                >
                  <option value="in_stock">In Stock (&gt; 0)</option>
                  <option value="out_of_stock">Out of Stock (= 0)</option>
                  <option value="all">All Records</option>
                </select>
              </div>

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadBalances}>
                <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Facility & Bin</th>
                  <th>SKU & Variant</th>
                  <th>Product Title</th>
                  <th>Batch #</th>
                  <th style={{ textAlign: 'right' }}>On Hand</th>
                  <th style={{ textAlign: 'right' }}>Allocated</th>
                  <th style={{ textAlign: 'right' }}>Available</th>
                  <th style={{ textAlign: 'right' }}>Quick Actions</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <RefreshCw size={24} className="spin" style={{ margin: '0 auto 8px' }} />
                      <div>Loading stock balances...</div>
                    </td>
                  </tr>
                ) : balances.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <Box size={32} style={{ opacity: 0.4, margin: '0 auto 8px' }} />
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>No stock balances found</div>
                      <div style={{ fontSize: '12.5px', marginTop: '4px' }}>Try adjusting your warehouse or stock status filters.</div>
                    </td>
                  </tr>
                ) : (
                  balances.map((b) => (
                    <tr key={b.id}>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: '13px' }}>{b.warehouse_name || b.warehouse_code}</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd', fontSize: '12px' }}>
                          {b.bin_code}
                        </div>
                      </td>
                      <td>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd', fontSize: '13px' }}>
                          {b.item_sku}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{b.variant_name}</div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>{b.item_name}</div>
                      </td>
                      <td>
                        <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                          {b.batch_number || 'Standard'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700, color: b.quantity_on_hand > 0 ? '#34d399' : 'var(--text-muted)' }}>
                        {b.quantity_on_hand}
                      </td>
                      <td style={{ textAlign: 'right', color: b.quantity_allocated > 0 ? '#f59e0b' : 'var(--text-muted)' }}>
                        {b.quantity_allocated}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: (b.quantity_available ?? 0) > 0 ? '#34d399' : '#f87171' }}>
                        {b.quantity_available ?? (b.quantity_on_hand - b.quantity_allocated)}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '6px' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '2px 8px', fontSize: '11px' }}
                            onClick={() => handleOpenTransfer(b)}
                            title="Transfer from this bin"
                          >
                            <ArrowLeftRight size={11} /> Transfer
                          </button>
                          <button
                            className="btn btn-outline btn-sm"
                            style={{ padding: '2px 8px', fontSize: '11px' }}
                            onClick={() => handleOpenAdjustment(b)}
                            title="Adjust physical count"
                          >
                            <Sliders size={11} /> Count
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Balances Pagination */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '16px' }}>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Showing <strong>{balances.length}</strong> of <strong>{totalBalances}</strong> balance entries (Page {balPage} of {totalBalPages || 1})
            </div>

            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-secondary btn-sm" disabled={balPage <= 1} onClick={() => setBalPage(balPage - 1)}>
                <ChevronLeft size={14} /> Previous
              </button>
              <button className="btn btn-secondary btn-sm" disabled={balPage >= totalBalPages} onClick={() => setBalPage(balPage + 1)}>
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: IMMUTABLE MOVEMENT JOURNAL */}
      {/* ========================================================================= */}
      {activeTab === 'journal' && (
        <div>
          {/* Filter Toolbar */}
          <div className="card" style={{ marginBottom: '16px', padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: '12px', alignItems: 'center' }}>
              <div style={{ position: 'relative' }}>
                <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  placeholder="Search TX number, SKU, or user..."
                  value={journalSearch}
                  onChange={(e) => setJournalSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { setEntryPage(1); loadJournal(); } }}
                  style={{ paddingLeft: '34px', height: '36px', fontSize: '13px' }}
                />
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={txTypeFilter}
                  onChange={(e) => { setTxTypeFilter(e.target.value); setEntryPage(1); }}
                >
                  <option value="">All Movement Types</option>
                  <option value="TRANSFER_OUT">Transfers (Inter-bin & Facility)</option>
                  <option value="INVENTORY_ADJUSTMENT">Physical Adjustments</option>
                  <option value="PURCHASE_RECEIPT">Purchase Receipts</option>
                  <option value="SALES_SHIPMENT">Sales Shipments</option>
                  <option value="SCRAP">Scrap / Write-off</option>
                </select>
              </div>

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadJournal}>
                <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>TX Number & Time</th>
                  <th>Type</th>
                  <th>SKU & Item</th>
                  <th>Source Bin</th>
                  <th>Destination Bin</th>
                  <th style={{ textAlign: 'right' }}>Qty</th>
                  <th style={{ textAlign: 'right' }}>Unit Cost</th>
                  <th style={{ textAlign: 'right' }}>Total Cost</th>
                  <th>Posted By</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={10} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <RefreshCw size={24} className="spin" style={{ margin: '0 auto 8px' }} />
                      <div>Loading movement journal...</div>
                    </td>
                  </tr>
                ) : entries.length === 0 ? (
                  <tr>
                    <td colSpan={10} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <History size={32} style={{ opacity: 0.4, margin: '0 auto 8px' }} />
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>No journal entries found</div>
                    </td>
                  </tr>
                ) : (
                  entries.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '12.5px', color: '#93c5fd' }}>
                          {e.transaction_number || e.transactionNumber}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {new Date(e.posted_at || e.postedAt).toLocaleString()}
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${
                          e.transaction_type === 'PURCHASE_RECEIPT' ? 'badge-success' :
                          e.transaction_type === 'SALES_SHIPMENT' ? 'badge-danger' :
                          e.transaction_type === 'TRANSFER_OUT' ? 'badge-info' : 'badge-default'
                        }`}>
                          {e.transaction_type || e.transactionType}
                        </span>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: '13px' }}>{e.item_sku || e.itemSku}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{e.item_name || e.itemName}</div>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                          {e.source_bin_code || e.sourceBinCode || '—'}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                          {e.destination_bin_code || e.destinationBinCode || '—'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 800 }}>
                        {e.quantity} {e.uom}
                      </td>
                      <td style={{ textAlign: 'right', fontSize: '12px' }}>
                        ${e.unit_cost?.toFixed(2) || '0.00'}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700, fontSize: '12.5px' }}>
                        ${e.total_cost?.toFixed(2) || '0.00'}
                      </td>
                      <td>
                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                          {e.posted_by_user_name || e.postedByUserName || 'System'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '2px 8px', fontSize: '11px' }}
                          onClick={() => setPreviewDoc({
                            type: (e.transaction_type || '').includes('TRANSFER') ? 'STOCK_TRANSFER' : 'STOCK_ADJUSTMENT',
                            id: (e as any).transaction_id || e.id
                          })}
                          title="Print Document Slip"
                        >
                          <Printer size={11} /> Print
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Journal Pagination */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '16px' }}>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Showing <strong>{entries.length}</strong> of <strong>{totalEntries}</strong> journal movements (Page {entryPage} of {totalEntryPages || 1})
            </div>

            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-secondary btn-sm" disabled={entryPage <= 1} onClick={() => setEntryPage(entryPage - 1)}>
                <ChevronLeft size={14} /> Previous
              </button>
              <button className="btn btn-secondary btn-sm" disabled={entryPage >= totalEntryPages} onClick={() => setEntryPage(entryPage + 1)}>
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: STOCK TRANSFER */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isTransferModalOpen}
        onClose={() => setIsTransferModalOpen(false)}
        title="Execute Physical Stock Transfer"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsTransferModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleExecuteTransfer}>Post Transfer Journal</button>
          </>
        }
      >
        <form onSubmit={handleExecuteTransfer}>
          <div style={{
            padding: '12px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            marginBottom: '14px'
          }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Select Product & Variant *</label>
              <select
                className="form-control"
                value={transferVariantId}
                onChange={(e) => setTransferVariantId(e.target.value)}
              >
                {items.map(itm =>
                  itm.variants.map(v => (
                    <option key={v.id} value={v.id}>
                      {itm.sku} &bull; {itm.name} — {v.variantName} ({v.variantSku})
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '12px' }}>
            {/* Source Facility & Bin */}
            <div style={{ padding: '12px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#f87171', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ArrowUpRight size={14} /> Source Location (Credit)
              </div>
              <div className="form-group">
                <label className="form-label">Warehouse</label>
                <select className="form-control" value={transferSrcWhId} onChange={(e) => setTransferSrcWhId(e.target.value)}>
                  {warehouses.map(w => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Source Bin *</label>
                <select className="form-control" value={transferSrcBinId} onChange={(e) => setTransferSrcBinId(e.target.value)}>
                  <option value="">-- Select Source Bin --</option>
                  {srcWhBins.map(b => (
                    <option key={b.id} value={b.id}>{b.code} ({b.type})</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Destination Facility & Bin */}
            <div style={{ padding: '12px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: '12px', fontWeight: 700, color: '#34d399', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ArrowDownLeft size={14} /> Destination Location (Debit)
              </div>
              <div className="form-group">
                <label className="form-label">Warehouse</label>
                <select className="form-control" value={transferDstWhId} onChange={(e) => setTransferDstWhId(e.target.value)}>
                  {warehouses.map(w => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Destination Bin *</label>
                <select className="form-control" value={transferDstBinId} onChange={(e) => setTransferDstBinId(e.target.value)}>
                  <option value="">-- Select Destination Bin --</option>
                  {dstWhBins.map(b => (
                    <option key={b.id} value={b.id}>{b.code} ({b.type})</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Transfer Quantity *</label>
              <input
                type="number"
                min="0.0001"
                step="any"
                required
                className="form-control"
                value={transferQty}
                onChange={(e) => setTransferQty(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Notes & Reason</label>
              <input
                type="text"
                className="form-control"
                placeholder="e.g. Replenishment to primary picking bin"
                value={transferNotes}
                onChange={(e) => setTransferNotes(e.target.value)}
              />
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: STOCK ADJUSTMENT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isAdjustmentModalOpen}
        onClose={() => setIsAdjustmentModalOpen(false)}
        title="Record Physical Stock Adjustment"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsAdjustmentModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleExecuteAdjustment}>Post Adjustment Entry</button>
          </>
        }
      >
        <form onSubmit={handleExecuteAdjustment}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Facility *</label>
              <select className="form-control" value={adjWhId} onChange={(e) => setAdjWhId(e.target.value)}>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Location Bin *</label>
              <select className="form-control" value={adjBinId} onChange={(e) => setAdjBinId(e.target.value)}>
                <option value="">-- Select Bin --</option>
                {adjWhBins.map(b => (
                  <option key={b.id} value={b.id}>{b.code} ({b.type})</option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Product / Variant *</label>
            <select className="form-control" value={adjVariantId} onChange={(e) => setAdjVariantId(e.target.value)}>
              {items.map(itm =>
                itm.variants.map(v => (
                  <option key={v.id} value={v.id}>
                    {itm.sku} &bull; {itm.name} — {v.variantName} ({v.variantSku})
                  </option>
                ))
              )}
            </select>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: '12px',
            padding: '12px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            marginBottom: '14px',
            alignItems: 'center'
          }}>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Recorded On Hand</div>
              <div style={{ fontSize: '18px', fontWeight: 800 }}>{adjCurrentStock}</div>
            </div>
            <div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label" style={{ fontSize: '11px' }}>New Physical Count *</label>
                <input
                  type="number"
                  min="0"
                  step="any"
                  required
                  className="form-control"
                  value={adjCountedQty}
                  onChange={(e) => setAdjCountedQty(e.target.value)}
                />
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Variance Delta</div>
              <div style={{
                fontSize: '18px',
                fontWeight: 800,
                color: varianceDelta > 0 ? '#34d399' : varianceDelta < 0 ? '#f87171' : 'var(--text-muted)'
              }}>
                {varianceDelta > 0 ? `+${varianceDelta}` : varianceDelta}
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Adjustment Reason *</label>
              <select className="form-control" value={adjReason} onChange={(e) => setAdjReason(e.target.value)}>
                <option value="CYCLE_COUNT_DISCREPANCY">Physical Cycle Count Discrepancy</option>
                <option value="DAMAGED_GOODS">Damaged Goods Discarded</option>
                <option value="WRITE_OFF">Write-off / Obsolescence</option>
                <option value="FOUND_STOCK">Found Stock / Inventory Discovery</option>
                <option value="INVENTORY_AUDIT">Periodic Compliance Audit</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Movement Journal Type</label>
              <select className="form-control" value={adjType} onChange={(e) => setAdjType(e.target.value)}>
                <option value="INVENTORY_ADJUSTMENT">INVENTORY_ADJUSTMENT</option>
                <option value="SCRAP">SCRAP</option>
                <option value="CYCLE_COUNT">CYCLE_COUNT</option>
              </select>
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* BUSINESS DOCUMENT PRINT PREVIEW */}
      {/* ========================================================================= */}
      {previewDoc && (
        <DocumentPreviewModal
          isOpen={!!previewDoc}
          onClose={() => setPreviewDoc(null)}
          documentType={previewDoc.type}
          documentId={previewDoc.id}
        />
      )}
    </div>
  );
};
