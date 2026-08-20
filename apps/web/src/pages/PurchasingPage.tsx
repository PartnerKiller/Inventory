import React, { useEffect, useState } from 'react';
import {
  ShoppingBag, Plus, Search, Filter, RefreshCw, CheckCircle, AlertTriangle,
  Clock, ArrowRight, Truck, FileText, ChevronLeft, ChevronRight, X, Trash2,
  Edit3, ShieldCheck, Eye, Check, Slash, Layers, MapPin, Building2, Calendar, Printer
} from 'lucide-react';
import { api } from '../api/client';
import {
  PurchaseOrder, PurchaseOrderDetail, Supplier, Warehouse, Item,
  GoodsReceiptCreate, PurchaseOrderCreate, POLineCreate, SupplierCreate, DocumentType
} from '@inventory/shared-types';
import { Modal } from '../components/Modal';
import { DocumentPreviewModal } from '../components/DocumentPreviewModal';
import { useWarehouse } from '../context/WarehouseContext';

export const PurchasingPage: React.FC = () => {
  const { activeWarehouseId } = useWarehouse();
  const [activeTab, setActiveTab] = useState<'orders' | 'suppliers'>('orders');

  // Purchase Orders State
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [totalOrders, setTotalOrders] = useState<number>(0);
  const [totalOrderPages, setTotalOrderPages] = useState<number>(1);
  const [orderPage, setOrderPage] = useState<number>(1);
  const [orderPageSize, setOrderPageSize] = useState<number>(15);
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [supplierFilter, setSupplierFilter] = useState<string>('');
  const [warehouseFilter, setWarehouseFilter] = useState<string>(activeWarehouseId);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Suppliers State
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierSearch, setSupplierSearch] = useState<string>('');

  // Master lookup data
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Modals
  const [isCreatePoModalOpen, setIsCreatePoModalOpen] = useState<boolean>(false);
  const [isEditPoModalOpen, setIsEditPoModalOpen] = useState<boolean>(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);
  const [isGrnModalOpen, setIsGrnModalOpen] = useState<boolean>(false);
  const [isSupplierModalOpen, setIsSupplierModalOpen] = useState<boolean>(false);
  const [isDeleteSupplierModalOpen, setIsDeleteSupplierModalOpen] = useState<boolean>(false);
  const [previewDoc, setPreviewDoc] = useState<{ type: DocumentType; id: string } | null>(null);

  // Selected Records
  const [selectedPoDetail, setSelectedPoDetail] = useState<PurchaseOrderDetail | null>(null);
  const [editingPo, setEditingPo] = useState<PurchaseOrder | null>(null);
  const [grnPo, setGrnPo] = useState<PurchaseOrder | null>(null);
  const [editingSupplier, setEditingSupplier] = useState<Supplier | null>(null);
  const [deletingSupplier, setDeletingSupplier] = useState<Supplier | null>(null);

  // PO Form State
  const [formSupplierId, setFormSupplierId] = useState<string>('');
  const [formWarehouseId, setFormWarehouseId] = useState<string>('');
  const [formDeliveryDate, setFormDeliveryDate] = useState<string>('');
  const [formNotes, setFormNotes] = useState<string>('');
  const [formLines, setFormLines] = useState<Array<{
    item_variant_id: string;
    quantity_ordered: number;
    unit_price: number;
    discount_pct: number;
    tax_pct: number;
  }>>([]);

  // GRN Form State
  const [grnDestinationBinId, setGrnDestinationBinId] = useState<string>('');
  const [grnNotes, setGrnNotes] = useState<string>('');
  const [grnLines, setGrnLines] = useState<Array<{
    po_line_id: string;
    item_variant_id: string;
    quantity_received: number;
    batch_number?: string;
    expiry_date?: string;
  }>>([]);

  // Supplier Form State
  const [supCode, setSupCode] = useState<string>('');
  const [supName, setSupName] = useState<string>('');
  const [supEmail, setSupEmail] = useState<string>('');
  const [supPhone, setSupPhone] = useState<string>('');
  const [supTerms, setSupTerms] = useState<string>('Net 30');
  const [supCurrency, setSupCurrency] = useState<string>('USD');
  const [supStreet, setSupStreet] = useState<string>('');
  const [supCity, setSupCity] = useState<string>('');
  const [supState, setSupState] = useState<string>('');
  const [supPostal, setSupPostal] = useState<string>('');

  // Load Lookup Data
  const loadMasterData = async () => {
    try {
      const [whs, itmsRes, sups] = await Promise.all([
        api.getWarehouses(),
        api.getItems({ page_size: 300 }),
        api.getSuppliers(),
      ]);
      setWarehouses(whs);
      setItems(itmsRes.items);
      setSuppliers(sups);
    } catch (err: any) {
      console.error('Failed to load lookup data:', err);
    }
  };

  // Load Purchase Orders
  const loadPurchaseOrders = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);
      const res = await api.getPurchaseOrders({
        status: statusFilter !== 'ALL' ? statusFilter : undefined,
        supplier_id: supplierFilter || undefined,
        warehouse_id: warehouseFilter || undefined,
        q: searchQuery.trim() || undefined,
        page: orderPage,
        page_size: orderPageSize,
      });
      setOrders(res.items);
      setTotalOrders(res.pagination.total_items ?? res.pagination.totalItems ?? 0);
      setTotalOrderPages(res.pagination.total_pages ?? res.pagination.totalPages ?? 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load purchase orders');
    } finally {
      setIsLoading(false);
    }
  };

  // Load Suppliers
  const loadSuppliers = async () => {
    try {
      const data = await api.getSuppliers({ q: supplierSearch.trim() || undefined });
      setSuppliers(data);
    } catch (err: any) {
      console.error('Failed to load suppliers:', err);
    }
  };

  useEffect(() => {
    loadMasterData();
  }, []);

  useEffect(() => {
    setWarehouseFilter(activeWarehouseId);
    setOrderPage(1);
  }, [activeWarehouseId]);

  useEffect(() => {
    if (activeTab === 'orders') {
      loadPurchaseOrders();
    } else {
      loadSuppliers();
    }
  }, [activeTab, orderPage, orderPageSize, statusFilter, supplierFilter, warehouseFilter]);

  // =========================================================================
  // PO ACTIONS (Approve, Submit, Cancel, Delete, View)
  // =========================================================================
  const handleOpenDetail = async (poId: string) => {
    try {
      const detail = await api.getPurchaseOrderDetail(poId);
      setSelectedPoDetail(detail);
      setIsDetailModalOpen(true);
    } catch (err: any) {
      alert(`Failed to load PO detail: ${err.message}`);
    }
  };

  const handleSubmitForApproval = async (poId: string) => {
    try {
      await api.submitPurchaseOrder(poId);
      loadPurchaseOrders();
    } catch (err: any) {
      alert(`Failed to submit: ${err.message}`);
    }
  };

  const handleApprovePo = async (poId: string) => {
    try {
      await api.approvePurchaseOrder(poId);
      loadPurchaseOrders();
    } catch (err: any) {
      alert(`Approval failed: ${err.message}`);
    }
  };

  const handleCancelPo = async (poId: string) => {
    if (!confirm('Are you sure you want to cancel this purchase order?')) return;
    try {
      await api.cancelPurchaseOrder(poId);
      loadPurchaseOrders();
    } catch (err: any) {
      alert(`Cancellation failed: ${err.message}`);
    }
  };

  const handleDeletePo = async (poId: string) => {
    if (!confirm('Delete this draft purchase order?')) return;
    try {
      await api.deletePurchaseOrder(poId);
      loadPurchaseOrders();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  // =========================================================================
  // CREATE / EDIT PO MODAL
  // =========================================================================
  const openCreatePoModal = () => {
    setEditingPo(null);
    setFormSupplierId(suppliers[0]?.id || '');
    setFormWarehouseId(activeWarehouseId || warehouses[0]?.id || '');
    setFormDeliveryDate('');
    setFormNotes('');
    
    // Default 1 line
    const firstVariant = items[0]?.variants?.[0];
    setFormLines([{
      item_variant_id: firstVariant?.id || '',
      quantity_ordered: 10,
      unit_price: firstVariant?.costPrice || firstVariant?.cost_price || 0,
      discount_pct: 0,
      tax_pct: 0,
    }]);
    setIsCreatePoModalOpen(true);
  };

  const openEditPoModal = (po: PurchaseOrder) => {
    setEditingPo(po);
    setFormSupplierId(po.supplier_id || po.supplierId || '');
    setFormWarehouseId(po.target_warehouse_id || po.targetWarehouseId || '');
    setFormDeliveryDate(po.expected_delivery_at || po.expectedDeliveryAt ? new Date(po.expected_delivery_at || po.expectedDeliveryAt || '').toISOString().split('T')[0] : '');
    setFormNotes(po.notes || '');
    setFormLines(po.lines.map(l => ({
      item_variant_id: l.item_variant_id || l.itemVariantId || '',
      quantity_ordered: l.quantity_ordered ?? l.quantityOrdered ?? 1,
      unit_price: l.unit_price ?? l.unitPrice ?? 0,
      discount_pct: l.discount_pct ?? l.discountPct ?? 0,
      tax_pct: l.tax_pct ?? l.taxPct ?? 0,
    })));
    setIsEditPoModalOpen(true);
  };

  const handleAddLine = () => {
    const firstVariant = items[0]?.variants?.[0];
    setFormLines([
      ...formLines,
      {
        item_variant_id: firstVariant?.id || '',
        quantity_ordered: 10,
        unit_price: firstVariant?.costPrice || firstVariant?.cost_price || 0,
        discount_pct: 0,
        tax_pct: 0,
      }
    ]);
  };

  const handleRemoveLine = (idx: number) => {
    if (formLines.length <= 1) return;
    setFormLines(formLines.filter((_, i) => i !== idx));
  };

  const handleLineChange = (idx: number, field: string, value: any) => {
    const updated = [...formLines];
    const line = { ...updated[idx], [field]: value };

    if (field === 'item_variant_id') {
      // Auto-populate default cost price
      for (const itm of items) {
        const found = itm.variants.find(v => v.id === value);
        if (found) {
          line.unit_price = found.costPrice || found.cost_price || 0;
          break;
        }
      }
    }
    updated[idx] = line;
    setFormLines(updated);
  };

  // Financial calculations
  const calculateTotals = () => {
    let subtotal = 0;
    let totalDiscount = 0;
    let totalTax = 0;

    for (const l of formLines) {
      const base = l.quantity_ordered * l.unit_price;
      const disc = base * (l.discount_pct / 100);
      const afterDisc = base - disc;
      const tax = afterDisc * (l.tax_pct / 100);

      subtotal += base;
      totalDiscount += disc;
      totalTax += tax;
    }
    const grandTotal = subtotal - totalDiscount + totalTax;
    return { subtotal, totalDiscount, totalTax, grandTotal };
  };

  const { subtotal, totalDiscount, totalTax, grandTotal } = calculateTotals();

  const handleSavePo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formSupplierId || !formWarehouseId || formLines.length === 0) {
      alert('Supplier, target facility, and at least one order line are required');
      return;
    }

    try {
      const payload: PurchaseOrderCreate = {
        supplier_id: formSupplierId,
        target_warehouse_id: formWarehouseId,
        expected_delivery_at: formDeliveryDate ? new Date(formDeliveryDate).toISOString() : undefined,
        notes: formNotes || undefined,
        lines: formLines.map(l => ({
          item_variant_id: l.item_variant_id,
          quantity_ordered: Number(l.quantity_ordered),
          unit_price: Number(l.unit_price),
          discount_pct: Number(l.discount_pct || 0),
          tax_pct: Number(l.tax_pct || 0),
        }))
      };

      if (editingPo) {
        await api.updatePurchaseOrder(editingPo.id, payload);
        setIsEditPoModalOpen(false);
      } else {
        await api.createPurchaseOrder(payload);
        setIsCreatePoModalOpen(false);
      }
      loadPurchaseOrders();
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    }
  };

  // =========================================================================
  // GOODS RECEIPT (GRN) MODAL
  // =========================================================================
  const openGrnModal = (po: PurchaseOrder) => {
    setGrnPo(po);
    const wh = warehouses.find(w => w.id === (po.target_warehouse_id || po.targetWarehouseId));
    const defaultBin = wh?.bins?.find(b => b.type === 'RECEIVING') || wh?.bins?.[0];
    setGrnDestinationBinId(defaultBin?.id || '');
    setGrnNotes('');

    // Pre-populate remaining quantities
    setGrnLines(po.lines.map(l => {
      const ord = l.quantity_ordered ?? l.quantityOrdered ?? 0;
      const rec = l.quantity_received ?? l.quantityReceived ?? 0;
      const rem = Math.max(0, ord - rec);
      return {
        po_line_id: l.id,
        item_variant_id: l.item_variant_id || l.itemVariantId || '',
        quantity_received: rem,
        batch_number: '',
        expiry_date: '',
      };
    }));
    setIsGrnModalOpen(true);
  };

  const handleGrnLineChange = (idx: number, field: string, value: any) => {
    const updated = [...grnLines];
    updated[idx] = { ...updated[idx], [field]: value };
    setGrnLines(updated);
  };

  const handleReceiveAllShortcut = () => {
    if (!grnPo) return;
    setGrnLines(grnPo.lines.map(l => {
      const ord = l.quantity_ordered ?? l.quantityOrdered ?? 0;
      const rec = l.quantity_received ?? l.quantityReceived ?? 0;
      return {
        po_line_id: l.id,
        item_variant_id: l.item_variant_id || l.itemVariantId || '',
        quantity_received: Math.max(0, ord - rec),
        batch_number: '',
        expiry_date: '',
      };
    }));
  };

  const handlePostGrn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!grnPo || !grnDestinationBinId) {
      alert('Receiving bin is required');
      return;
    }

    const activeReceivingLines = grnLines.filter(l => l.quantity_received > 0);
    if (activeReceivingLines.length === 0) {
      alert('Please enter a quantity greater than 0 for at least one item');
      return;
    }

    try {
      const payload: GoodsReceiptCreate = {
        purchase_order_id: grnPo.id,
        warehouse_id: grnPo.target_warehouse_id || grnPo.targetWarehouseId || '',
        notes: grnNotes || undefined,
        lines: activeReceivingLines.map(l => ({
          po_line_id: l.po_line_id,
          item_variant_id: l.item_variant_id,
          quantity_received: Number(l.quantity_received),
          destination_bin_id: grnDestinationBinId,
          batch_number: l.batch_number?.trim() || undefined,
          expiry_date: l.expiry_date ? new Date(l.expiry_date).toISOString() : undefined,
        }))
      };

      await api.receiveGoods(payload);
      setIsGrnModalOpen(false);
      loadPurchaseOrders();
      alert('Goods Receipt Note (GRN) posted successfully and stock ledger updated!');
    } catch (err: any) {
      alert(`Receipt rejected: ${err.message}`);
    }
  };

  // =========================================================================
  // SUPPLIER CRUD
  // =========================================================================
  const openCreateSupplierModal = () => {
    setEditingSupplier(null);
    setSupCode('');
    setSupName('');
    setSupEmail('');
    setSupPhone('');
    setSupTerms('Net 30');
    setSupCurrency('USD');
    setSupStreet('');
    setSupCity('');
    setSupState('');
    setSupPostal('');
    setIsSupplierModalOpen(true);
  };

  const openEditSupplierModal = (sup: Supplier) => {
    setEditingSupplier(sup);
    setSupCode(sup.code);
    setSupName(sup.name);
    setSupEmail(sup.email || '');
    setSupPhone(sup.phone || '');
    setSupTerms(sup.payment_terms || sup.paymentTerms || 'Net 30');
    setSupCurrency(sup.currency || 'USD');
    setSupStreet(sup.address?.street || '');
    setSupCity(sup.address?.city || '');
    setSupState(sup.address?.state || '');
    setSupPostal(sup.address?.postalCode || '');
    setIsSupplierModalOpen(true);
  };

  const handleSaveSupplier = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supCode || !supName) {
      alert('Supplier code and name are required');
      return;
    }

    try {
      const payload: SupplierCreate = {
        code: supCode.toUpperCase().trim(),
        name: supName.trim(),
        email: supEmail.trim() || undefined,
        phone: supPhone.trim() || undefined,
        payment_terms: supTerms,
        currency: supCurrency,
        address: {
          street: supStreet.trim(),
          city: supCity.trim(),
          state: supState.trim(),
          postalCode: supPostal.trim(),
        }
      };

      if (editingSupplier) {
        await api.updateSupplier(editingSupplier.id, payload);
      } else {
        await api.createSupplier(payload);
      }
      setIsSupplierModalOpen(false);
      loadSuppliers();
      loadMasterData();
    } catch (err: any) {
      alert(`Supplier save failed: ${err.message}`);
    }
  };

  const executeDeleteSupplier = async () => {
    if (!deletingSupplier) return;
    try {
      await api.deleteSupplier(deletingSupplier.id);
      setIsDeleteSupplierModalOpen(false);
      setDeletingSupplier(null);
      loadSuppliers();
    } catch (err: any) {
      alert(`Archive failed: ${err.message}`);
    }
  };

  // Helper: target warehouse bins for GRN
  const grnWhBins = warehouses.find(w => w.id === (grnPo?.target_warehouse_id || grnPo?.targetWarehouseId))?.bins || [];

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Purchasing & Goods Receipt
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Procurement lifecycle, supplier contracts, approval workflows, and atomic Goods Receipt Note (GRN) intake
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={openCreateSupplierModal}>
            <Building2 size={15} /> Add Supplier
          </button>
          <button className="btn btn-primary" onClick={openCreatePoModal}>
            <Plus size={16} /> New Purchase Order
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '16px' }}>
        <button
          className={`btn ${activeTab === 'orders' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('orders')}
        >
          <ShoppingBag size={15} /> Purchase Orders ({totalOrders})
        </button>
        <button
          className={`btn ${activeTab === 'suppliers' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('suppliers')}
        >
          <Building2 size={15} /> Supplier Directory ({suppliers.length})
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
      {/* TAB 1: PURCHASE ORDERS */}
      {/* ========================================================================= */}
      {activeTab === 'orders' && (
        <div>
          {/* Toolbar */}
          <div className="card" style={{ marginBottom: '16px', padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1.2fr 1fr 1fr auto', gap: '12px', alignItems: 'center' }}>
              <div style={{ position: 'relative' }}>
                <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  placeholder="Search PO number or supplier..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { setOrderPage(1); loadPurchaseOrders(); } }}
                  style={{ paddingLeft: '34px', height: '36px', fontSize: '13px' }}
                />
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={statusFilter}
                  onChange={(e) => { setStatusFilter(e.target.value); setOrderPage(1); }}
                >
                  <option value="ALL">All Lifecycle Statuses</option>
                  <option value="DRAFT">DRAFT (Editable)</option>
                  <option value="PENDING_APPROVAL">PENDING APPROVAL</option>
                  <option value="APPROVED">APPROVED (Ready for GRN)</option>
                  <option value="PARTIALLY_RECEIVED">PARTIALLY RECEIVED</option>
                  <option value="COMPLETED">COMPLETED</option>
                  <option value="CANCELLED">CANCELLED</option>
                </select>
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={supplierFilter}
                  onChange={(e) => { setSupplierFilter(e.target.value); setOrderPage(1); }}
                >
                  <option value="">All Suppliers</option>
                  {suppliers.map(s => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={warehouseFilter}
                  onChange={(e) => { setWarehouseFilter(e.target.value); setOrderPage(1); }}
                >
                  <option value="">All Facilities</option>
                  {warehouses.map(w => (
                    <option key={w.id} value={w.id}>{w.code}</option>
                  ))}
                </select>
              </div>

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadPurchaseOrders}>
                <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
              </button>
            </div>
          </div>

          {/* PO Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>PO Number & Date</th>
                  <th>Supplier</th>
                  <th>Target Facility</th>
                  <th>Status</th>
                  <th>Fulfillment Progress</th>
                  <th style={{ textAlign: 'right' }}>Total Amount</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <RefreshCw size={24} className="spin" style={{ margin: '0 auto 8px' }} />
                      <div>Loading purchase orders...</div>
                    </td>
                  </tr>
                ) : orders.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <ShoppingBag size={32} style={{ opacity: 0.4, margin: '0 auto 8px' }} />
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>No purchase orders found</div>
                      <div style={{ fontSize: '12.5px', marginTop: '4px' }}>Click 'New Purchase Order' to initiate procurement.</div>
                    </td>
                  </tr>
                ) : (
                  orders.map(po => {
                    const status = po.status;
                    const totOrd = po.lines.reduce((sum, l) => sum + (l.quantity_ordered ?? l.quantityOrdered ?? 0), 0);
                    const totRec = po.lines.reduce((sum, l) => sum + (l.quantity_received ?? l.quantityReceived ?? 0), 0);
                    const pct = totOrd > 0 ? Math.min(100, Math.round((totRec / totOrd) * 100)) : 0;

                    return (
                      <tr key={po.id}>
                        <td>
                          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, color: '#93c5fd', fontSize: '13px' }}>
                            {po.po_number || po.poNumber}
                          </div>
                          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                            {new Date(po.ordered_at || po.orderedAt).toLocaleDateString()}
                          </div>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                            {po.supplier_name || po.supplierName}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {po.supplier_code || po.supplierCode}
                          </div>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: '12.5px' }}>
                            {po.target_warehouse_code || po.targetWarehouseCode || po.target_warehouse_name}
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${
                            status === 'COMPLETED' ? 'badge-success' :
                            status === 'APPROVED' ? 'badge-info' :
                            status === 'PARTIALLY_RECEIVED' ? 'badge-warning' :
                            status === 'CANCELLED' ? 'badge-danger' : 'badge-default'
                          }`}>
                            {status}
                          </span>
                        </td>
                        <td>
                          <div style={{ width: '120px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                              <span>{totRec} / {totOrd}</span>
                              <span style={{ fontWeight: 700 }}>{pct}%</span>
                            </div>
                            <div style={{ height: '5px', backgroundColor: 'var(--bg-app)', borderRadius: '3px', overflow: 'hidden' }}>
                              <div style={{
                                width: `${pct}%`,
                                height: '100%',
                                backgroundColor: pct === 100 ? '#34d399' : '#38bdf8',
                                transition: 'width 0.3s ease'
                              }} />
                            </div>
                          </div>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 800, fontSize: '13.5px' }}>
                          ${(po.total_amount ?? po.totalAmount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <div style={{ display: 'inline-flex', gap: '4px' }}>
                            <button
                              className="btn btn-outline btn-sm"
                              style={{ padding: '3px 7px' }}
                              onClick={() => handleOpenDetail(po.id)}
                              title="View PO Details"
                            >
                              <Eye size={13} />
                            </button>

                            {/* DRAFT Actions */}
                            {status === 'DRAFT' && (
                              <>
                                <button
                                  className="btn btn-outline btn-sm"
                                  style={{ padding: '3px 7px' }}
                                  onClick={() => openEditPoModal(po)}
                                  title="Edit Draft PO"
                                >
                                  <Edit3 size={13} />
                                </button>
                                <button
                                  className="btn btn-secondary btn-sm"
                                  style={{ padding: '3px 7px', fontSize: '11px' }}
                                  onClick={() => handleSubmitForApproval(po.id)}
                                  title="Submit for Approval"
                                >
                                  <ArrowRight size={12} /> Submit
                                </button>
                                <button
                                  className="btn btn-outline btn-sm"
                                  style={{ padding: '3px 7px', color: '#f87171' }}
                                  onClick={() => handleDeletePo(po.id)}
                                  title="Delete Draft"
                                >
                                  <Trash2 size={13} />
                                </button>
                              </>
                            )}

                            {/* PENDING_APPROVAL Actions */}
                            {status === 'PENDING_APPROVAL' && (
                              <>
                                <button
                                  className="btn btn-primary btn-sm"
                                  style={{ padding: '3px 8px', fontSize: '11px', backgroundColor: '#3b82f6', borderColor: '#3b82f6' }}
                                  onClick={() => handleApprovePo(po.id)}
                                >
                                  <Check size={12} /> Approve
                                </button>
                                <button
                                  className="btn btn-outline btn-sm"
                                  style={{ padding: '3px 7px', color: '#f87171' }}
                                  onClick={() => handleCancelPo(po.id)}
                                  title="Cancel PO"
                                >
                                  <Slash size={12} />
                                </button>
                              </>
                            )}

                            {/* APPROVED / PARTIALLY_RECEIVED Actions */}
                            {(status === 'APPROVED' || status === 'PARTIALLY_RECEIVED') && (
                              <button
                                className="btn btn-primary btn-sm"
                                style={{ padding: '3px 9px', fontSize: '11.5px', backgroundColor: '#10b981', borderColor: '#10b981' }}
                                onClick={() => openGrnModal(po)}
                              >
                                <Truck size={13} /> GRN
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '16px' }}>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Showing <strong>{orders.length}</strong> of <strong>{totalOrders}</strong> purchase orders (Page {orderPage} of {totalOrderPages || 1})
            </div>

            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="btn btn-secondary btn-sm" disabled={orderPage <= 1} onClick={() => setOrderPage(orderPage - 1)}>
                <ChevronLeft size={14} /> Previous
              </button>
              <button className="btn btn-secondary btn-sm" disabled={orderPage >= totalOrderPages} onClick={() => setOrderPage(orderPage + 1)}>
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: SUPPLIER DIRECTORY */}
      {/* ========================================================================= */}
      {activeTab === 'suppliers' && (
        <div>
          <div className="card" style={{ marginBottom: '16px', padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr auto', gap: '12px', alignItems: 'center' }}>
              <div style={{ position: 'relative' }}>
                <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  placeholder="Search supplier name or code..."
                  value={supplierSearch}
                  onChange={(e) => setSupplierSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') loadSuppliers(); }}
                  style={{ paddingLeft: '34px', height: '36px', fontSize: '13px' }}
                />
              </div>

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadSuppliers}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '14px' }}>
            {suppliers.map(s => (
              <div key={s.id} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '12px', color: '#93c5fd' }}>
                        {s.code}
                      </span>
                      <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
                        {s.name}
                      </h3>
                    </div>
                    <span className={`badge ${s.is_active ?? s.isActive ? 'badge-success' : 'badge-default'}`}>
                      {s.is_active ?? s.isActive ? 'Active' : 'Archived'}
                    </span>
                  </div>

                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                    {s.email && <div>Email: {s.email}</div>}
                    {s.phone && <div>Phone: {s.phone}</div>}
                    <div>Terms: <strong>{s.payment_terms || s.paymentTerms}</strong> &bull; Currency: <strong>{s.currency}</strong></div>
                  </div>

                  <div style={{
                    padding: '8px 12px',
                    backgroundColor: 'var(--bg-app)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '12px',
                    color: 'var(--text-secondary)'
                  }}>
                    Active Procurement Orders: <strong>{s.active_orders_count ?? s.activeOrdersCount ?? 0}</strong>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px', marginTop: '12px' }}>
                  <button className="btn btn-outline btn-sm" onClick={() => openEditSupplierModal(s)}>
                    <Edit3 size={13} /> Edit
                  </button>
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ color: '#f87171' }}
                    onClick={() => { setDeletingSupplier(s); setIsDeleteSupplierModalOpen(true); }}
                  >
                    <Trash2 size={13} /> Archive
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: CREATE / EDIT PURCHASE ORDER */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreatePoModalOpen || isEditPoModalOpen}
        onClose={() => { setIsCreatePoModalOpen(false); setIsEditPoModalOpen(false); }}
        title={editingPo ? `Edit Draft PO: ${editingPo.po_number || editingPo.poNumber}` : 'Initiate New Purchase Order'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => { setIsCreatePoModalOpen(false); setIsEditPoModalOpen(false); }}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSavePo}>
              {editingPo ? 'Save Changes' : 'Create Draft PO'}
            </button>
          </>
        }
      >
        <form onSubmit={handleSavePo}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div className="form-group">
              <label className="form-label">Vendor / Supplier *</label>
              <select className="form-control" value={formSupplierId} onChange={(e) => setFormSupplierId(e.target.value)}>
                {suppliers.map(s => (
                  <option key={s.id} value={s.id}>{s.name} ({s.code})</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Target Facility *</label>
              <select className="form-control" value={formWarehouseId} onChange={(e) => setFormWarehouseId(e.target.value)}>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Expected Delivery</label>
              <input
                type="date"
                className="form-control"
                value={formDeliveryDate}
                onChange={(e) => setFormDeliveryDate(e.target.value)}
              />
            </div>
          </div>

          {/* Line Items Table */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: 700 }}>Procurement Line Items</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleAddLine}>
                <Plus size={13} /> Add Item
              </button>
            </div>

            <div style={{ maxHeight: '240px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <table className="data-table" style={{ fontSize: '12px', margin: 0 }}>
                <thead>
                  <tr>
                    <th style={{ width: '40%' }}>Product & Variant</th>
                    <th style={{ width: '15%' }}>Qty</th>
                    <th style={{ width: '15%' }}>Unit Price ($)</th>
                    <th style={{ width: '12%' }}>Disc %</th>
                    <th style={{ width: '12%' }}>Tax %</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {formLines.map((l, idx) => (
                    <tr key={idx}>
                      <td>
                        <select
                          className="form-control"
                          style={{ height: '30px', fontSize: '12px' }}
                          value={l.item_variant_id}
                          onChange={(e) => handleLineChange(idx, 'item_variant_id', e.target.value)}
                        >
                          {items.map(itm =>
                            itm.variants.map(v => (
                              <option key={v.id} value={v.id}>
                                {itm.sku} - {itm.name} ({v.variantName || v.variant_name})
                              </option>
                            ))
                          )}
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="1"
                          step="any"
                          required
                          className="form-control"
                          style={{ height: '30px', fontSize: '12px' }}
                          value={l.quantity_ordered}
                          onChange={(e) => handleLineChange(idx, 'quantity_ordered', parseFloat(e.target.value) || 0)}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          required
                          className="form-control"
                          style={{ height: '30px', fontSize: '12px' }}
                          value={l.unit_price}
                          onChange={(e) => handleLineChange(idx, 'unit_price', parseFloat(e.target.value) || 0)}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="0.1"
                          className="form-control"
                          style={{ height: '30px', fontSize: '12px' }}
                          value={l.discount_pct}
                          onChange={(e) => handleLineChange(idx, 'discount_pct', parseFloat(e.target.value) || 0)}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="0.1"
                          className="form-control"
                          style={{ height: '30px', fontSize: '12px' }}
                          value={l.tax_pct}
                          onChange={(e) => handleLineChange(idx, 'tax_pct', parseFloat(e.target.value) || 0)}
                        />
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          style={{ padding: '2px 6px', color: '#f87171' }}
                          onClick={() => handleRemoveLine(idx)}
                          disabled={formLines.length <= 1}
                        >
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Financial Summary */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '2fr 1fr',
            gap: '14px',
            padding: '12px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            marginBottom: '10px'
          }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Procurement Notes / Instructions</label>
              <textarea
                rows={2}
                className="form-control"
                placeholder="e.g. Standard sea freight shipping, dock receipt instructions..."
                value={formNotes}
                onChange={(e) => setFormNotes(e.target.value)}
                style={{ fontSize: '12.5px' }}
              />
            </div>

            <div style={{ fontSize: '12.5px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>Subtotal:</span>
                <span>${subtotal.toFixed(2)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#34d399' }}>
                <span>Discount:</span>
                <span>-${totalDiscount.toFixed(2)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                <span>Estimated Tax:</span>
                <span>+${totalTax.toFixed(2)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 800, fontSize: '15px', borderTop: '1px solid var(--border-subtle)', paddingTop: '4px', marginTop: '2px' }}>
                <span>Grand Total:</span>
                <span style={{ color: '#93c5fd' }}>${grandTotal.toFixed(2)}</span>
              </div>
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: GOODS RECEIPT NOTE (GRN) */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isGrnModalOpen}
        onClose={() => setIsGrnModalOpen(false)}
        title={`Receive Goods against PO: ${grnPo?.po_number || grnPo?.poNumber}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsGrnModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#10b981', borderColor: '#10b981' }} onClick={handlePostGrn}>
              <CheckCircle size={15} /> Post Goods Receipt Note (GRN)
            </button>
          </>
        }
      >
        {grnPo && (
          <form onSubmit={handlePostGrn}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1.5fr 1fr',
              gap: '12px',
              padding: '12px',
              backgroundColor: 'var(--bg-app)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              marginBottom: '14px'
            }}>
              <div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Facility:</div>
                <div style={{ fontWeight: 700, fontSize: '13.5px' }}>{grnPo.target_warehouse_name || grnPo.targetWarehouseName}</div>
                <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  Vendor: <strong>{grnPo.supplier_name || grnPo.supplierName}</strong>
                </div>
              </div>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Receiving Destination Bin *</label>
                <select
                  className="form-control"
                  value={grnDestinationBinId}
                  onChange={(e) => setGrnDestinationBinId(e.target.value)}
                >
                  {grnWhBins.map(b => (
                    <option key={b.id} value={b.id}>{b.code} ({b.type})</option>
                  ))}
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: 700 }}>Line Items Receiving Intake</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleReceiveAllShortcut}>
                Receive All Remaining
              </button>
            </div>

            <div style={{ maxHeight: '250px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', marginBottom: '12px' }}>
              <table className="data-table" style={{ fontSize: '12px', margin: 0 }}>
                <thead>
                  <tr>
                    <th>Product / SKU</th>
                    <th>Ordered</th>
                    <th>Received</th>
                    <th>Remaining</th>
                    <th style={{ width: '110px' }}>Receive Now *</th>
                    <th style={{ width: '140px' }}>Batch / Lot #</th>
                  </tr>
                </thead>
                <tbody>
                  {grnPo.lines.map((l, idx) => {
                    const ord = l.quantity_ordered ?? l.quantityOrdered ?? 0;
                    const rec = l.quantity_received ?? l.quantityReceived ?? 0;
                    const rem = Math.max(0, ord - rec);
                    const currInput = grnLines[idx]?.quantity_received || 0;

                    return (
                      <tr key={l.id}>
                        <td>
                          <div style={{ fontWeight: 700, color: '#93c5fd' }}>{l.item_sku || l.itemSku}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{l.item_name || l.itemName}</div>
                        </td>
                        <td>{ord}</td>
                        <td style={{ color: '#34d399' }}>{rec}</td>
                        <td style={{ fontWeight: 700, color: rem > 0 ? '#38bdf8' : 'var(--text-muted)' }}>{rem}</td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            max={rem}
                            step="any"
                            className="form-control"
                            style={{
                              height: '28px',
                              fontSize: '12px',
                              borderColor: currInput > rem ? '#ef4444' : undefined
                            }}
                            value={currInput}
                            onChange={(e) => handleGrnLineChange(idx, 'quantity_received', parseFloat(e.target.value) || 0)}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            placeholder="Optional Batch #"
                            className="form-control"
                            style={{ height: '28px', fontSize: '12px' }}
                            value={grnLines[idx]?.batch_number || ''}
                            onChange={(e) => handleGrnLineChange(idx, 'batch_number', e.target.value)}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Goods Receipt Delivery / Carrier Notes</label>
              <input
                type="text"
                className="form-control"
                placeholder="e.g. Carrier BOL #88392 delivered intact"
                value={grnNotes}
                onChange={(e) => setGrnNotes(e.target.value)}
              />
            </div>
          </form>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: PO DETAIL INSPECTION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        title={`Purchase Order: ${selectedPoDetail?.po_number || selectedPoDetail?.poNumber}`}
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
            {selectedPoDetail && (
              <button
                className="btn btn-secondary"
                onClick={() => setPreviewDoc({ type: 'PURCHASE_ORDER', id: selectedPoDetail.id })}
              >
                <Printer size={15} />
                <span>Print Official PO</span>
              </button>
            )}
            <button className="btn btn-primary" onClick={() => setIsDetailModalOpen(false)}>Close</button>
          </div>
        }
      >
        {selectedPoDetail && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', marginBottom: '14px' }}>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Supplier</div>
                <div style={{ fontWeight: 700 }}>{selectedPoDetail.supplier_name}</div>
              </div>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Target Facility</div>
                <div style={{ fontWeight: 700 }}>{selectedPoDetail.target_warehouse_name}</div>
              </div>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Status</div>
                <span className="badge badge-info">{selectedPoDetail.status}</span>
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>Ordered Items</div>
              <table className="data-table" style={{ fontSize: '12px' }}>
                <thead>
                  <tr>
                    <th>SKU & Item</th>
                    <th>Ordered</th>
                    <th>Received</th>
                    <th>Remaining</th>
                    <th>Unit Price</th>
                    <th style={{ textAlign: 'right' }}>Line Total</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedPoDetail.lines.map(l => (
                    <tr key={l.id}>
                      <td>
                        <div style={{ fontWeight: 700, color: '#93c5fd' }}>{l.item_sku}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{l.item_name}</div>
                      </td>
                      <td>{l.quantity_ordered}</td>
                      <td style={{ color: '#34d399', fontWeight: 600 }}>{l.quantity_received}</td>
                      <td style={{ color: l.quantity_remaining > 0 ? '#38bdf8' : 'var(--text-muted)' }}>{l.quantity_remaining}</td>
                      <td>${l.unit_price.toFixed(2)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>${l.line_total.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selectedPoDetail.receipts && selectedPoDetail.receipts.length > 0 && (
              <div>
                <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>Goods Receipt History (GRNs)</div>
                <table className="data-table" style={{ fontSize: '11.5px' }}>
                  <thead>
                    <tr>
                      <th>GRN Number</th>
                      <th>Date</th>
                      <th>Items Received</th>
                      <th>Bin Location</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedPoDetail.receipts.map(r => (
                      <tr key={r.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#34d399' }}>{r.grn_number}</td>
                        <td>{new Date(r.received_at).toLocaleString()}</td>
                        <td>
                          {r.lines.map(gl => `${gl.item_sku}: ${gl.quantity_received}`).join(', ')}
                        </td>
                        <td>{r.lines[0]?.destination_bin_code || 'Standard Dock'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '3px 8px', fontSize: '11px' }}
                            onClick={() => setPreviewDoc({ type: 'GOODS_RECEIPT', id: r.id })}
                          >
                            <Printer size={12} />
                            <span>Print GRN</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: SUPPLIER CREATE / EDIT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isSupplierModalOpen}
        onClose={() => setIsSupplierModalOpen(false)}
        title={editingSupplier ? `Edit Supplier: ${editingSupplier.name}` : 'Register New Supplier'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsSupplierModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveSupplier}>Save Supplier</button>
          </>
        }
      >
        <form onSubmit={handleSaveSupplier}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Supplier Code *</label>
              <input
                type="text"
                required
                disabled={!!editingSupplier}
                className="form-control"
                placeholder="e.g. SUP-APEX-01"
                value={supCode}
                onChange={(e) => setSupCode(e.target.value.toUpperCase())}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Supplier Name *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. Apex Micro Electronics Ltd"
                value={supName}
                onChange={(e) => setSupName(e.target.value)}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input type="email" className="form-control" value={supEmail} onChange={(e) => setSupEmail(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Phone</label>
              <input type="text" className="form-control" value={supPhone} onChange={(e) => setSupPhone(e.target.value)} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Payment Terms</label>
              <select className="form-control" value={supTerms} onChange={(e) => setSupTerms(e.target.value)}>
                <option value="Net 15">Net 15</option>
                <option value="Net 30">Net 30</option>
                <option value="Net 45">Net 45</option>
                <option value="Net 60">Net 60</option>
                <option value="Due on Receipt">Due on Receipt</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Currency</label>
              <input type="text" className="form-control" value={supCurrency} onChange={(e) => setSupCurrency(e.target.value.toUpperCase())} />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Street Address</label>
            <input type="text" className="form-control" value={supStreet} onChange={(e) => setSupStreet(e.target.value)} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">City</label>
              <input type="text" className="form-control" value={supCity} onChange={(e) => setSupCity(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">State</label>
              <input type="text" className="form-control" value={supState} onChange={(e) => setSupState(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Postal Code</label>
              <input type="text" className="form-control" value={supPostal} onChange={(e) => setSupPostal(e.target.value)} />
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: SUPPLIER ARCHIVE CONFIRMATION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDeleteSupplierModalOpen}
        onClose={() => setIsDeleteSupplierModalOpen(false)}
        title="Confirm Supplier Archival"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDeleteSupplierModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#ef4444', borderColor: '#ef4444' }} onClick={executeDeleteSupplier}>
              Confirm Archive
            </button>
          </>
        }
      >
        <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
          <div style={{ padding: '10px', backgroundColor: 'rgba(239, 68, 68, 0.15)', borderRadius: '50%', color: '#ef4444' }}>
            <AlertTriangle size={24} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)', marginBottom: '4px' }}>
              Archive Supplier '{deletingSupplier?.name}'?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Suppliers with active open purchase orders cannot be archived until all associated procurement orders are fulfilled or cancelled.
            </div>
          </div>
        </div>
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
