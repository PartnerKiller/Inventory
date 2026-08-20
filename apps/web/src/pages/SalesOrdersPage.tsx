import React, { useEffect, useState } from 'react';
import {
  Send, Plus, Search, RefreshCw, CheckCircle, AlertTriangle,
  ArrowRight, Truck, Eye, Trash2, Edit3, Check, Slash,
  Package, RotateCcw, Building2, User, ChevronLeft, ChevronRight,
  Boxes, ShieldCheck, FileText, Barcode as BarcodeIcon, Layers, Printer
} from 'lucide-react';
import { api } from '../api/client';
import {
  SalesOrder, SalesOrderDetail, Customer, Warehouse, Item,
  SalesOrderCreate, CustomerCreate, SOPickRequest, SOPackRequest,
  SODispatchRequest, SalesReturnCreate, DocumentType
} from '@inventory/shared-types';
import { Modal } from '../components/Modal';
import { DocumentPreviewModal } from '../components/DocumentPreviewModal';

export const SalesOrdersPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'orders' | 'customers'>('orders');

  // Sales Orders State
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [totalOrders, setTotalOrders] = useState<number>(0);
  const [totalOrderPages, setTotalOrderPages] = useState<number>(1);
  const [orderPage, setOrderPage] = useState<number>(1);
  const [orderPageSize, setOrderPageSize] = useState<number>(15);
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [customerFilter, setCustomerFilter] = useState<string>('');
  const [warehouseFilter, setWarehouseFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Customers State
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerSearch, setCustomerSearch] = useState<string>('');

  // Master Lookup Data
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Modals
  const [isCreateSoModalOpen, setIsCreateSoModalOpen] = useState<boolean>(false);
  const [isEditSoModalOpen, setIsEditSoModalOpen] = useState<boolean>(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);
  const [isPickModalOpen, setIsPickModalOpen] = useState<boolean>(false);
  const [isPackModalOpen, setIsPackModalOpen] = useState<boolean>(false);
  const [isDispatchModalOpen, setIsDispatchModalOpen] = useState<boolean>(false);
  const [isReturnModalOpen, setIsReturnModalOpen] = useState<boolean>(false);
  const [isCustomerModalOpen, setIsCustomerModalOpen] = useState<boolean>(false);
  const [isDeleteCustomerModalOpen, setIsDeleteCustomerModalOpen] = useState<boolean>(false);
  const [previewDoc, setPreviewDoc] = useState<{ type: DocumentType; id: string } | null>(null);

  // Selected Records
  const [selectedSoDetail, setSelectedSoDetail] = useState<SalesOrderDetail | null>(null);
  const [editingSo, setEditingSo] = useState<SalesOrder | null>(null);
  const [activeSo, setActiveSo] = useState<SalesOrder | null>(null);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);
  const [deletingCustomer, setDeletingCustomer] = useState<Customer | null>(null);

  // SO Form State
  const [formCustomerId, setFormCustomerId] = useState<string>('');
  const [formWarehouseId, setFormWarehouseId] = useState<string>('');
  const [formNotes, setFormNotes] = useState<string>('');
  const [formLines, setFormLines] = useState<Array<{
    item_variant_id: string;
    quantity_ordered: number;
    unit_price: number;
    discount_pct: number;
    tax_pct: number;
  }>>([]);

  // Picking State
  const [pickLines, setPickLines] = useState<Array<{
    so_line_id: string;
    item_sku: string;
    item_name: string;
    allocated: number;
    already_picked: number;
    quantity_picked: number;
  }>>([]);

  // Packing State
  const [packCount, setPackCount] = useState<number>(1);
  const [packWeight, setPackWeight] = useState<number>(5.0);
  const [packNotes, setPackNotes] = useState<string>('');

  // Dispatch State
  const [dispatchCarrier, setDispatchCarrier] = useState<string>('FedEx Freight');
  const [dispatchTracking, setDispatchTracking] = useState<string>('');
  const [dispatchPackages, setDispatchPackages] = useState<number>(1);
  const [dispatchWeight, setDispatchWeight] = useState<number>(5.0);
  const [dispatchNotes, setDispatchNotes] = useState<string>('');

  // Return (RMA) State
  const [returnDestinationBinId, setReturnDestinationBinId] = useState<string>('');
  const [returnNotes, setReturnNotes] = useState<string>('');
  const [returnLines, setReturnLines] = useState<Array<{
    so_line_id: string;
    item_sku: string;
    item_name: string;
    shipped: number;
    returned: number;
    max_returnable: number;
    quantity_returned: number;
    condition: string;
  }>>([]);

  // Customer Form State
  const [custCode, setCustCode] = useState<string>('');
  const [custName, setCustName] = useState<string>('');
  const [custEmail, setCustEmail] = useState<string>('');
  const [custPhone, setCustPhone] = useState<string>('');
  const [custBillStreet, setCustBillStreet] = useState<string>('');
  const [custBillCity, setCustBillCity] = useState<string>('');
  const [custBillState, setCustBillState] = useState<string>('');
  const [custShipStreet, setCustShipStreet] = useState<string>('');
  const [custShipCity, setCustShipCity] = useState<string>('');
  const [custShipState, setCustShipState] = useState<string>('');

  // Load Lookup Data
  const loadMasterData = async () => {
    try {
      const [whs, itmsRes, custs] = await Promise.all([
        api.getWarehouses(),
        api.getItems({ page_size: 300 }),
        api.getCustomers(),
      ]);
      setWarehouses(whs);
      setItems(itmsRes.items);
      setCustomers(custs);
    } catch (err: any) {
      console.error('Failed to load lookup data:', err);
    }
  };

  // Load Sales Orders
  const loadSalesOrders = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);
      const res = await api.getSalesOrders({
        status: statusFilter !== 'ALL' ? statusFilter : undefined,
        customer_id: customerFilter || undefined,
        warehouse_id: warehouseFilter || undefined,
        q: searchQuery.trim() || undefined,
        page: orderPage,
        page_size: orderPageSize,
      });
      setOrders(res.items);
      setTotalOrders(res.pagination.total_items ?? res.pagination.totalItems ?? 0);
      setTotalOrderPages(res.pagination.total_pages ?? res.pagination.totalPages ?? 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load sales orders');
    } finally {
      setIsLoading(false);
    }
  };

  // Load Customers
  const loadCustomers = async () => {
    try {
      const data = await api.getCustomers({ q: customerSearch.trim() || undefined });
      setCustomers(data);
    } catch (err: any) {
      console.error('Failed to load customers:', err);
    }
  };

  useEffect(() => {
    loadMasterData();
  }, []);

  useEffect(() => {
    if (activeTab === 'orders') {
      loadSalesOrders();
    } else {
      loadCustomers();
    }
  }, [activeTab, orderPage, orderPageSize, statusFilter, customerFilter, warehouseFilter]);

  // =========================================================================
  // ACTIONS: DETAIL, CONFIRM, ALLOCATE, CANCEL, DELETE
  // =========================================================================
  const handleOpenDetail = async (soId: string) => {
    try {
      const detail = await api.getSalesOrderDetail(soId);
      setSelectedSoDetail(detail);
      setIsDetailModalOpen(true);
    } catch (err: any) {
      alert(`Failed to load SO detail: ${err.message}`);
    }
  };

  const handleConfirmOrder = async (soId: string) => {
    try {
      await api.confirmSalesOrder(soId);
      loadSalesOrders();
    } catch (err: any) {
      alert(`Confirmation failed: ${err.message}`);
    }
  };

  const handleAllocateOrder = async (soId: string) => {
    try {
      await api.allocateSalesOrder(soId);
      loadSalesOrders();
      alert('Stock successfully allocated and reserved from facility inventory!');
    } catch (err: any) {
      alert(`Allocation failed: ${err.message}`);
    }
  };

  const handleCancelOrder = async (soId: string) => {
    if (!confirm('Cancel this sales order? Any allocated stock will be released back to available inventory.')) return;
    try {
      await api.cancelSalesOrder(soId);
      loadSalesOrders();
    } catch (err: any) {
      alert(`Cancellation failed: ${err.message}`);
    }
  };

  const handleDeleteDraft = async (soId: string) => {
    if (!confirm('Delete this draft sales order?')) return;
    try {
      await api.deleteSalesOrder(soId);
      loadSalesOrders();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  // =========================================================================
  // CREATE / EDIT SO MODAL
  // =========================================================================
  const openCreateSoModal = () => {
    setEditingSo(null);
    setFormCustomerId(customers[0]?.id || '');
    setFormWarehouseId(warehouses[0]?.id || '');
    setFormNotes('');

    const firstVariant = items[0]?.variants?.[0];
    setFormLines([{
      item_variant_id: firstVariant?.id || '',
      quantity_ordered: 5,
      unit_price: firstVariant?.sellingPrice || firstVariant?.selling_price || 0,
      discount_pct: 0,
      tax_pct: 0,
    }]);
    setIsCreateSoModalOpen(true);
  };

  const openEditSoModal = (so: SalesOrder) => {
    setEditingSo(so);
    setFormCustomerId(so.customer_id || so.customerId || '');
    setFormWarehouseId(so.warehouse_id || so.warehouseId || '');
    setFormNotes(so.notes || '');
    setFormLines(so.lines.map(l => ({
      item_variant_id: l.item_variant_id || l.itemVariantId || '',
      quantity_ordered: l.quantity_ordered ?? l.quantityOrdered ?? 1,
      unit_price: l.unit_price ?? l.unitPrice ?? 0,
      discount_pct: l.discount_pct ?? l.discountPct ?? 0,
      tax_pct: l.tax_pct ?? l.taxPct ?? 0,
    })));
    setIsEditSoModalOpen(true);
  };

  const handleAddLine = () => {
    const firstVariant = items[0]?.variants?.[0];
    setFormLines([
      ...formLines,
      {
        item_variant_id: firstVariant?.id || '',
        quantity_ordered: 5,
        unit_price: firstVariant?.sellingPrice || firstVariant?.selling_price || 0,
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
      for (const itm of items) {
        const found = itm.variants.find(v => v.id === value);
        if (found) {
          line.unit_price = found.sellingPrice || found.selling_price || 0;
          break;
        }
      }
    }
    updated[idx] = line;
    setFormLines(updated);
  };

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

  const handleSaveSo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formCustomerId || !formWarehouseId || formLines.length === 0) {
      alert('Customer, warehouse facility, and at least one order line are required');
      return;
    }

    try {
      const payload: SalesOrderCreate = {
        customer_id: formCustomerId,
        warehouse_id: formWarehouseId,
        notes: formNotes || undefined,
        lines: formLines.map(l => ({
          item_variant_id: l.item_variant_id,
          quantity_ordered: Number(l.quantity_ordered),
          unit_price: Number(l.unit_price),
          discount_pct: Number(l.discount_pct || 0),
          tax_pct: Number(l.tax_pct || 0),
        }))
      };

      if (editingSo) {
        await api.updateSalesOrder(editingSo.id, payload);
        setIsEditSoModalOpen(false);
      } else {
        await api.createSalesOrder(payload);
        setIsCreateSoModalOpen(false);
      }
      loadSalesOrders();
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    }
  };

  // =========================================================================
  // FULFILLMENT: PICKING
  // =========================================================================
  const openPickModal = (so: SalesOrder) => {
    setActiveSo(so);
    setPickLines(so.lines.map(l => {
      const alloc = l.quantity_allocated ?? l.quantityAllocated ?? 0;
      const picked = l.quantity_picked ?? l.quantityPicked ?? 0;
      const rem = Math.max(0, alloc - picked);
      return {
        so_line_id: l.id,
        item_sku: l.item_sku || l.itemSku || '',
        item_name: l.item_name || l.itemName || '',
        allocated: alloc,
        already_picked: picked,
        quantity_picked: rem,
      };
    }));
    setIsPickModalOpen(true);
  };

  const handlePickLineChange = (idx: number, qty: number) => {
    const updated = [...pickLines];
    updated[idx].quantity_picked = qty;
    setPickLines(updated);
  };

  const handleSavePicks = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSo) return;

    const activePicks = pickLines.filter(p => p.quantity_picked > 0);
    if (activePicks.length === 0) {
      alert('Please enter pick quantities greater than 0');
      return;
    }

    try {
      const payload: SOPickRequest = {
        picks: activePicks.map(p => ({
          so_line_id: p.so_line_id,
          quantity_picked: Number(p.quantity_picked),
        }))
      };
      await api.pickSalesOrderItems(activeSo.id, payload);
      setIsPickModalOpen(false);
      loadSalesOrders();
    } catch (err: any) {
      alert(`Picking failed: ${err.message}`);
    }
  };

  // =========================================================================
  // FULFILLMENT: PACKING
  // =========================================================================
  const openPackModal = (so: SalesOrder) => {
    setActiveSo(so);
    setPackCount(1);
    setPackWeight(5.0);
    setPackNotes('');
    setIsPackModalOpen(true);
  };

  const handleSavePacking = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSo) return;
    try {
      const payload: SOPackRequest = {
        package_count: Number(packCount),
        total_weight: Number(packWeight),
        packing_notes: packNotes || undefined,
      };
      await api.packSalesOrder(activeSo.id, payload);
      setIsPackModalOpen(false);
      loadSalesOrders();
    } catch (err: any) {
      alert(`Packing failed: ${err.message}`);
    }
  };

  // =========================================================================
  // FULFILLMENT: DISPATCH / SHIPMENT
  // =========================================================================
  const openDispatchModal = (so: SalesOrder) => {
    setActiveSo(so);
    setDispatchCarrier('FedEx Freight');
    setDispatchTracking(`TRK-${Math.floor(10000000 + Math.random() * 90000000)}`);
    setDispatchPackages(1);
    setDispatchWeight(10.0);
    setDispatchNotes('');
    setIsDispatchModalOpen(true);
  };

  const handleExecuteDispatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSo) return;
    try {
      const payload: SODispatchRequest = {
        carrier: dispatchCarrier,
        tracking_number: dispatchTracking || undefined,
        package_count: Number(dispatchPackages),
        total_weight: Number(dispatchWeight),
        notes: dispatchNotes || undefined,
      };
      await api.dispatchSalesOrder(activeSo.id, payload);
      setIsDispatchModalOpen(false);
      loadSalesOrders();
      alert('Shipment dispatched! Outbound stock ledger transaction posted and inventory deducted.');
    } catch (err: any) {
      alert(`Dispatch failed: ${err.message}`);
    }
  };

  // =========================================================================
  // FULFILLMENT: SALES RETURNS (RMA)
  // =========================================================================
  const openReturnModal = (so: SalesOrder) => {
    setActiveSo(so);
    const wh = warehouses.find(w => w.id === (so.warehouse_id || so.warehouseId));
    const defaultBin = wh?.bins?.find(b => b.type === 'RECEIVING') || wh?.bins?.[0];
    setReturnDestinationBinId(defaultBin?.id || '');
    setReturnNotes('');

    setReturnLines(so.lines.map(l => {
      const shp = l.quantity_shipped ?? l.quantityShipped ?? 0;
      const ret = l.quantity_returned ?? l.quantityReturned ?? 0;
      const maxRet = Math.max(0, shp - ret);
      return {
        so_line_id: l.id,
        item_sku: l.item_sku || l.itemSku || '',
        item_name: l.item_name || l.itemName || '',
        shipped: shp,
        returned: ret,
        max_returnable: maxRet,
        quantity_returned: maxRet > 0 ? maxRet : 0,
        condition: 'GOOD',
      };
    }));
    setIsReturnModalOpen(true);
  };

  const handleReturnLineChange = (idx: number, field: string, value: any) => {
    const updated = [...returnLines];
    updated[idx] = { ...updated[idx], [field]: value };
    setReturnLines(updated);
  };

  const handlePostReturn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSo || !returnDestinationBinId) {
      alert('Destination bin is required');
      return;
    }

    const activeReturns = returnLines.filter(r => r.quantity_returned > 0);
    if (activeReturns.length === 0) {
      alert('Please enter return quantity for at least one item');
      return;
    }

    try {
      const payload: SalesReturnCreate = {
        notes: returnNotes || undefined,
        lines: activeReturns.map(r => ({
          so_line_id: r.so_line_id,
          quantity_returned: Number(r.quantity_returned),
          condition: r.condition,
          destination_bin_id: returnDestinationBinId,
        }))
      };
      await api.processSalesReturn(activeSo.id, payload);
      setIsReturnModalOpen(false);
      loadSalesOrders();
      alert('Sales Return (RMA) intake posted to inventory stock ledger!');
    } catch (err: any) {
      alert(`Return rejected: ${err.message}`);
    }
  };

  // =========================================================================
  // CUSTOMER CRUD
  // =========================================================================
  const openCreateCustomerModal = () => {
    setEditingCustomer(null);
    setCustCode('');
    setCustName('');
    setCustEmail('');
    setCustPhone('');
    setCustBillStreet('');
    setCustBillCity('');
    setCustBillState('');
    setCustShipStreet('');
    setCustShipCity('');
    setCustShipState('');
    setIsCustomerModalOpen(true);
  };

  const openEditCustomerModal = (cust: Customer) => {
    setEditingCustomer(cust);
    setCustCode(cust.code);
    setCustName(cust.name);
    setCustEmail(cust.email || '');
    setCustPhone(cust.phone || '');
    setCustBillStreet(cust.billing_address?.street || '');
    setCustBillCity(cust.billing_address?.city || '');
    setCustBillState(cust.billing_address?.state || '');
    setCustShipStreet(cust.shipping_address?.street || '');
    setCustShipCity(cust.shipping_address?.city || '');
    setCustShipState(cust.shipping_address?.state || '');
    setIsCustomerModalOpen(true);
  };

  const handleSaveCustomer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!custCode || !custName) {
      alert('Customer code and name are required');
      return;
    }

    try {
      const payload: CustomerCreate = {
        code: custCode.toUpperCase().trim(),
        name: custName.trim(),
        email: custEmail.trim() || undefined,
        phone: custPhone.trim() || undefined,
        billing_address: { street: custBillStreet, city: custBillCity, state: custBillState },
        shipping_address: { street: custShipStreet, city: custShipCity, state: custShipState },
      };

      if (editingCustomer) {
        await api.updateCustomer(editingCustomer.id, payload);
      } else {
        await api.createCustomer(payload);
      }
      setIsCustomerModalOpen(false);
      loadCustomers();
      loadMasterData();
    } catch (err: any) {
      alert(`Customer save failed: ${err.message}`);
    }
  };

  const executeDeleteCustomer = async () => {
    if (!deletingCustomer) return;
    try {
      await api.deleteCustomer(deletingCustomer.id);
      setIsDeleteCustomerModalOpen(false);
      setDeletingCustomer(null);
      loadCustomers();
    } catch (err: any) {
      alert(`Archive failed: ${err.message}`);
    }
  };

  const activeWhBins = warehouses.find(w => w.id === (activeSo?.warehouse_id || activeSo?.warehouseId))?.bins || [];

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Sales & Order Fulfillment
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Customer demand, stock reservation, picking/packing workflows, and atomic outbound dispatch
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={openCreateCustomerModal}>
            <User size={15} /> Add Customer
          </button>
          <button className="btn btn-primary" onClick={openCreateSoModal}>
            <Plus size={16} /> New Sales Order
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
          <Send size={15} /> Sales Orders ({totalOrders})
        </button>
        <button
          className={`btn ${activeTab === 'customers' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('customers')}
        >
          <User size={15} /> Customer Directory ({customers.length})
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
      {/* TAB 1: SALES ORDERS */}
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
                  placeholder="Search SO number or customer..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { setOrderPage(1); loadSalesOrders(); } }}
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
                  <option value="DRAFT">DRAFT</option>
                  <option value="CONFIRMED">CONFIRMED (Ready to Allocate)</option>
                  <option value="ALLOCATED">ALLOCATED (Stock Reserved)</option>
                  <option value="PICKING">PICKING</option>
                  <option value="PACKED">PACKED (Ready to Ship)</option>
                  <option value="SHIPPED">SHIPPED</option>
                  <option value="CANCELLED">CANCELLED</option>
                </select>
              </div>

              <div>
                <select
                  className="form-control"
                  style={{ height: '36px', fontSize: '13px' }}
                  value={customerFilter}
                  onChange={(e) => { setCustomerFilter(e.target.value); setOrderPage(1); }}
                >
                  <option value="">All Customers</option>
                  {customers.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
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

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadSalesOrders}>
                <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
              </button>
            </div>
          </div>

          {/* Orders Table */}
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>SO Number & Date</th>
                  <th>Customer</th>
                  <th>Origin Facility</th>
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
                      <div>Loading sales orders...</div>
                    </td>
                  </tr>
                ) : orders.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      <Send size={32} style={{ opacity: 0.4, margin: '0 auto 8px' }} />
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>No sales orders found</div>
                      <div style={{ fontSize: '12.5px', marginTop: '4px' }}>Click 'New Sales Order' to register customer demand.</div>
                    </td>
                  </tr>
                ) : (
                  orders.map(so => {
                    const status = so.status;
                    const totOrd = so.lines.reduce((sum, l) => sum + (l.quantity_ordered ?? l.quantityOrdered ?? 0), 0);
                    const totShp = so.lines.reduce((sum, l) => sum + (l.quantity_shipped ?? l.quantityShipped ?? 0), 0);
                    const totAlc = so.lines.reduce((sum, l) => sum + (l.quantity_allocated ?? l.quantityAllocated ?? 0), 0);
                    const pct = totOrd > 0 ? Math.min(100, Math.round((totShp / totOrd) * 100)) : 0;

                    return (
                      <tr key={so.id}>
                        <td>
                          <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, color: '#93c5fd', fontSize: '13px' }}>
                            {so.so_number || so.soNumber}
                          </div>
                          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                            {new Date(so.ordered_at || so.orderedAt).toLocaleDateString()}
                          </div>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                            {so.customer_name || so.customerName}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {so.customer_code || so.customerCode}
                          </div>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: '12.5px' }}>
                            {so.warehouse_code || so.warehouseCode || so.warehouse_name}
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${
                            status === 'SHIPPED' ? 'badge-success' :
                            status === 'PACKED' ? 'badge-info' :
                            status === 'ALLOCATED' ? 'badge-warning' :
                            status === 'CANCELLED' ? 'badge-danger' : 'badge-default'
                          }`}>
                            {status}
                          </span>
                        </td>
                        <td>
                          <div style={{ width: '120px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                              <span>{totShp > 0 ? `${totShp}/${totOrd} Shipped` : `${totAlc}/${totOrd} Allocated`}</span>
                              <span style={{ fontWeight: 700 }}>{pct}%</span>
                            </div>
                            <div style={{ height: '5px', backgroundColor: 'var(--bg-app)', borderRadius: '3px', overflow: 'hidden' }}>
                              <div style={{
                                width: `${status === 'SHIPPED' ? 100 : (totAlc / (totOrd || 1)) * 100}%`,
                                height: '100%',
                                backgroundColor: status === 'SHIPPED' ? '#34d399' : '#38bdf8',
                                transition: 'width 0.3s ease'
                              }} />
                            </div>
                          </div>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 800, fontSize: '13.5px' }}>
                          ${(so.total_amount ?? so.totalAmount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <div style={{ display: 'inline-flex', gap: '4px' }}>
                            <button
                              className="btn btn-outline btn-sm"
                              style={{ padding: '3px 7px' }}
                              onClick={() => handleOpenDetail(so.id)}
                              title="View Order Details"
                            >
                              <Eye size={13} />
                            </button>

                            {/* DRAFT */}
                            {status === 'DRAFT' && (
                              <>
                                <button
                                  className="btn btn-outline btn-sm"
                                  style={{ padding: '3px 7px' }}
                                  onClick={() => openEditSoModal(so)}
                                  title="Edit Draft Order"
                                >
                                  <Edit3 size={13} />
                                </button>
                                <button
                                  className="btn btn-secondary btn-sm"
                                  style={{ padding: '3px 8px', fontSize: '11.5px' }}
                                  onClick={() => handleConfirmOrder(so.id)}
                                >
                                  <Check size={12} /> Confirm
                                </button>
                                <button
                                  className="btn btn-outline btn-sm"
                                  style={{ padding: '3px 7px', color: '#f87171' }}
                                  onClick={() => handleDeleteDraft(so.id)}
                                  title="Delete Draft"
                                >
                                  <Trash2 size={13} />
                                </button>
                              </>
                            )}

                            {/* CONFIRMED */}
                            {status === 'CONFIRMED' && (
                              <button
                                className="btn btn-primary btn-sm"
                                style={{ padding: '3px 9px', fontSize: '11.5px', backgroundColor: '#6366f1', borderColor: '#6366f1' }}
                                onClick={() => handleAllocateOrder(so.id)}
                              >
                                <Boxes size={13} /> Allocate
                              </button>
                            )}

                            {/* ALLOCATED / PICKING */}
                            {(status === 'ALLOCATED' || status === 'PICKING') && (
                              <button
                                className="btn btn-primary btn-sm"
                                style={{ padding: '3px 9px', fontSize: '11.5px', backgroundColor: '#3b82f6', borderColor: '#3b82f6' }}
                                onClick={() => openPickModal(so)}
                              >
                                <BarcodeIcon size={13} /> Pick
                              </button>
                            )}

                            {/* PACKED (or ready to pack) */}
                            {status === 'PACKED' && (
                              <button
                                className="btn btn-primary btn-sm"
                                style={{ padding: '3px 9px', fontSize: '11.5px', backgroundColor: '#10b981', borderColor: '#10b981' }}
                                onClick={() => openDispatchModal(so)}
                              >
                                <Truck size={13} /> Dispatch
                              </button>
                            )}

                            {/* SHIPPED -> Sales Return */}
                            {status === 'SHIPPED' && (
                              <button
                                className="btn btn-outline btn-sm"
                                style={{ padding: '3px 8px', fontSize: '11px', color: '#fbbf24', borderColor: '#fbbf24' }}
                                onClick={() => openReturnModal(so)}
                                title="Process Sales Return (RMA)"
                              >
                                <RotateCcw size={12} /> Return
                              </button>
                            )}

                            {/* Cancel for active un-shipped orders */}
                            {['DRAFT', 'CONFIRMED', 'ALLOCATED', 'PICKING'].includes(status) && (
                              <button
                                className="btn btn-outline btn-sm"
                                style={{ padding: '3px 7px', color: '#f87171' }}
                                onClick={() => handleCancelOrder(so.id)}
                                title="Cancel Order"
                              >
                                <Slash size={12} />
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
              Showing <strong>{orders.length}</strong> of <strong>{totalOrders}</strong> orders (Page {orderPage} of {totalOrderPages || 1})
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
      {/* TAB 2: CUSTOMER DIRECTORY */}
      {/* ========================================================================= */}
      {activeTab === 'customers' && (
        <div>
          <div className="card" style={{ marginBottom: '16px', padding: '14px 18px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr auto', gap: '12px', alignItems: 'center' }}>
              <div style={{ position: 'relative' }}>
                <Search size={15} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  placeholder="Search customer name or code..."
                  value={customerSearch}
                  onChange={(e) => setCustomerSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') loadCustomers(); }}
                  style={{ paddingLeft: '34px', height: '36px', fontSize: '13px' }}
                />
              </div>

              <button className="btn btn-secondary" style={{ height: '36px' }} onClick={loadCustomers}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '14px' }}>
            {customers.map(c => (
              <div key={c.id} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '12px', color: '#93c5fd' }}>
                        {c.code}
                      </span>
                      <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
                        {c.name}
                      </h3>
                    </div>
                    <span className={`badge ${c.is_active ?? c.isActive ? 'badge-success' : 'badge-default'}`}>
                      {c.is_active ?? c.isActive ? 'Active' : 'Archived'}
                    </span>
                  </div>

                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                    {c.email && <div>Email: {c.email}</div>}
                    {c.phone && <div>Phone: {c.phone}</div>}
                    {c.billing_address?.city && <div>Location: {c.billing_address.city}, {c.billing_address.state}</div>}
                  </div>

                  <div style={{
                    padding: '8px 12px',
                    backgroundColor: 'var(--bg-app)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '12px',
                    color: 'var(--text-secondary)'
                  }}>
                    Active Demand Orders: <strong>{c.active_orders_count ?? c.activeOrdersCount ?? 0}</strong>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px', marginTop: '12px' }}>
                  <button className="btn btn-outline btn-sm" onClick={() => openEditCustomerModal(c)}>
                    <Edit3 size={13} /> Edit
                  </button>
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ color: '#f87171' }}
                    onClick={() => { setDeletingCustomer(c); setIsDeleteCustomerModalOpen(true); }}
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
      {/* MODAL: CREATE / EDIT SALES ORDER */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreateSoModalOpen || isEditSoModalOpen}
        onClose={() => { setIsCreateSoModalOpen(false); setIsEditSoModalOpen(false); }}
        title={editingSo ? `Edit Draft SO: ${editingSo.so_number || editingSo.soNumber}` : 'Create New Sales Order'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => { setIsCreateSoModalOpen(false); setIsEditSoModalOpen(false); }}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveSo}>
              {editingSo ? 'Save Changes' : 'Create Draft SO'}
            </button>
          </>
        }
      >
        <form onSubmit={handleSaveSo}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div className="form-group">
              <label className="form-label">Customer / Client *</label>
              <select className="form-control" value={formCustomerId} onChange={(e) => setFormCustomerId(e.target.value)}>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Fulfillment Facility *</label>
              <select className="form-control" value={formWarehouseId} onChange={(e) => setFormWarehouseId(e.target.value)}>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Line Items */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: 700 }}>Sales Line Items</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleAddLine}>
                <Plus size={13} /> Add Line
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

          {/* Financial Totals */}
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
              <label className="form-label">Special Delivery / Customer Notes</label>
              <textarea
                rows={2}
                className="form-control"
                placeholder="e.g. Expedited ground delivery requested, dock appointment required..."
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
      {/* MODAL: PICKING */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isPickModalOpen}
        onClose={() => setIsPickModalOpen(false)}
        title={`Pick Stock: ${activeSo?.so_number || activeSo?.soNumber}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsPickModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSavePicks}>
              <CheckCircle size={15} /> Confirm Picking & Stage for Packing
            </button>
          </>
        }
      >
        <form onSubmit={handleSavePicks}>
          <div style={{ maxHeight: '250px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', marginBottom: '12px' }}>
            <table className="data-table" style={{ fontSize: '12px', margin: 0 }}>
              <thead>
                <tr>
                  <th>Product / SKU</th>
                  <th>Allocated</th>
                  <th>Picked</th>
                  <th style={{ width: '120px' }}>Pick Now *</th>
                </tr>
              </thead>
              <tbody>
                {pickLines.map((p, idx) => (
                  <tr key={p.so_line_id}>
                    <td>
                      <div style={{ fontWeight: 700, color: '#93c5fd' }}>{p.item_sku}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{p.item_name}</div>
                    </td>
                    <td>{p.allocated}</td>
                    <td style={{ color: '#34d399' }}>{p.already_picked}</td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        max={p.allocated - p.already_picked}
                        step="any"
                        className="form-control"
                        style={{ height: '28px', fontSize: '12px' }}
                        value={p.quantity_picked}
                        onChange={(e) => handlePickLineChange(idx, parseFloat(e.target.value) || 0)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: DISPATCH / SHIPMENT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDispatchModalOpen}
        onClose={() => setIsDispatchModalOpen(false)}
        title={`Dispatch Shipment: ${activeSo?.so_number || activeSo?.soNumber}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDispatchModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#10b981', borderColor: '#10b981' }} onClick={handleExecuteDispatch}>
              <Truck size={15} /> Confirm & Dispatch Outbound Stock
            </button>
          </>
        }
      >
        <form onSubmit={handleExecuteDispatch}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1.5fr', gap: '12px', marginBottom: '12px' }}>
            <div className="form-group">
              <label className="form-label">Freight / Shipping Carrier *</label>
              <select className="form-control" value={dispatchCarrier} onChange={(e) => setDispatchCarrier(e.target.value)}>
                <option value="FedEx Freight">FedEx Freight</option>
                <option value="UPS Ground">UPS Ground</option>
                <option value="DHL Express">DHL Express</option>
                <option value="Dedicated Fleet">Dedicated Fleet</option>
                <option value="Customer Pickup">Customer Pickup / Will Call</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Tracking / BOL Number</label>
              <input type="text" className="form-control" value={dispatchTracking} onChange={(e) => setDispatchTracking(e.target.value)} />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div className="form-group">
              <label className="form-label">Package Count</label>
              <input type="number" min="1" className="form-control" value={dispatchPackages} onChange={(e) => setDispatchPackages(parseInt(e.target.value) || 1)} />
            </div>

            <div className="form-group">
              <label className="form-label">Total Weight (kg)</label>
              <input type="number" min="0" step="0.1" className="form-control" value={dispatchWeight} onChange={(e) => setDispatchWeight(parseFloat(e.target.value) || 0)} />
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Dispatch Notes</label>
            <input type="text" className="form-control" placeholder="e.g. Dock door 4 hand-off" value={dispatchNotes} onChange={(e) => setDispatchNotes(e.target.value)} />
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: SALES RETURN (RMA) */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isReturnModalOpen}
        onClose={() => setIsReturnModalOpen(false)}
        title={`Process Sales Return: ${activeSo?.so_number || activeSo?.soNumber}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsReturnModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#fbbf24', borderColor: '#fbbf24', color: '#000' }} onClick={handlePostReturn}>
              <RotateCcw size={15} /> Intake Returned Stock
            </button>
          </>
        }
      >
        <form onSubmit={handlePostReturn}>
          <div className="form-group" style={{ marginBottom: '14px' }}>
            <label className="form-label">Intake Destination Bin *</label>
            <select
              className="form-control"
              value={returnDestinationBinId}
              onChange={(e) => setReturnDestinationBinId(e.target.value)}
            >
              {activeWhBins.map(b => (
                <option key={b.id} value={b.id}>{b.code} ({b.type})</option>
              ))}
            </select>
          </div>

          <div style={{ maxHeight: '240px', overflowY: 'auto', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', marginBottom: '12px' }}>
            <table className="data-table" style={{ fontSize: '12px', margin: 0 }}>
              <thead>
                <tr>
                  <th>Product / SKU</th>
                  <th>Shipped</th>
                  <th>Returned</th>
                  <th style={{ width: '100px' }}>Return Qty *</th>
                  <th style={{ width: '120px' }}>Condition</th>
                </tr>
              </thead>
              <tbody>
                {returnLines.map((r, idx) => (
                  <tr key={r.so_line_id}>
                    <td>
                      <div style={{ fontWeight: 700, color: '#93c5fd' }}>{r.item_sku}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{r.item_name}</div>
                    </td>
                    <td>{r.shipped}</td>
                    <td>{r.returned}</td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        max={r.max_returnable}
                        step="any"
                        className="form-control"
                        style={{ height: '28px', fontSize: '12px' }}
                        value={r.quantity_returned}
                        onChange={(e) => handleReturnLineChange(idx, 'quantity_returned', parseFloat(e.target.value) || 0)}
                      />
                    </td>
                    <td>
                      <select
                        className="form-control"
                        style={{ height: '28px', fontSize: '12px' }}
                        value={r.condition}
                        onChange={(e) => handleReturnLineChange(idx, 'condition', e.target.value)}
                      >
                        <option value="GOOD">Good Stock</option>
                        <option value="DAMAGED">Damaged</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Return Reason / Notes</label>
            <input type="text" className="form-control" placeholder="e.g. Unopened items returned by customer" value={returnNotes} onChange={(e) => setReturnNotes(e.target.value)} />
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: SO DETAIL INSPECTION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        title={`Sales Order: ${selectedSoDetail?.so_number || selectedSoDetail?.soNumber}`}
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {selectedSoDetail && (
                <>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setPreviewDoc({ type: 'SALES_ORDER', id: selectedSoDetail.id })}
                  >
                    <Printer size={13} />
                    <span>Order</span>
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setPreviewDoc({ type: 'SALES_INVOICE', id: selectedSoDetail.id })}
                  >
                    <FileText size={13} />
                    <span>Invoice</span>
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setPreviewDoc({ type: 'PACKING_SLIP', id: selectedSoDetail.id })}
                  >
                    <Package size={13} />
                    <span>Packing Slip</span>
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setPreviewDoc({ type: 'DELIVERY_NOTE', id: selectedSoDetail.id })}
                  >
                    <Truck size={13} />
                    <span>Delivery Note</span>
                  </button>
                </>
              )}
            </div>
            <button className="btn btn-primary" onClick={() => setIsDetailModalOpen(false)}>Close</button>
          </div>
        }
      >
        {selectedSoDetail && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', marginBottom: '14px' }}>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Customer</div>
                <div style={{ fontWeight: 700 }}>{selectedSoDetail.customer_name}</div>
              </div>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Fulfillment Facility</div>
                <div style={{ fontWeight: 700 }}>{selectedSoDetail.warehouse_name}</div>
              </div>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Status</div>
                <span className="badge badge-info">{selectedSoDetail.status}</span>
              </div>
            </div>

            <div style={{ marginBottom: '14px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>Ordered Items Breakdown</div>
              <table className="data-table" style={{ fontSize: '12px' }}>
                <thead>
                  <tr>
                    <th>SKU & Item</th>
                    <th>Ordered</th>
                    <th>Allocated</th>
                    <th>Picked</th>
                    <th>Shipped</th>
                    <th style={{ textAlign: 'right' }}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedSoDetail.lines.map(l => (
                    <tr key={l.id}>
                      <td>
                        <div style={{ fontWeight: 700, color: '#93c5fd' }}>{l.item_sku}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{l.item_name}</div>
                      </td>
                      <td>{l.quantity_ordered}</td>
                      <td style={{ color: '#818cf8', fontWeight: 600 }}>{l.quantity_allocated}</td>
                      <td style={{ color: '#38bdf8' }}>{l.quantity_picked}</td>
                      <td style={{ color: '#34d399', fontWeight: 700 }}>{l.quantity_shipped}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>${l.line_total.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selectedSoDetail.shipments && selectedSoDetail.shipments.length > 0 && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>Shipments & Tracking</div>
                <table className="data-table" style={{ fontSize: '11.5px' }}>
                  <thead>
                    <tr>
                      <th>Shipment #</th>
                      <th>Carrier</th>
                      <th>Tracking #</th>
                      <th>Dispatched At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedSoDetail.shipments.map(s => (
                      <tr key={s.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#34d399' }}>{s.shipment_number}</td>
                        <td>{s.carrier}</td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{s.tracking_number || 'N/A'}</td>
                        <td>{new Date(s.shipped_at).toLocaleString()}</td>
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
      {/* MODAL: CUSTOMER CREATE / EDIT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCustomerModalOpen}
        onClose={() => setIsCustomerModalOpen(false)}
        title={editingCustomer ? `Edit Customer: ${editingCustomer.name}` : 'Register New Customer'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsCustomerModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveCustomer}>Save Customer</button>
          </>
        }
      >
        <form onSubmit={handleSaveCustomer}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Customer Code *</label>
              <input
                type="text"
                required
                disabled={!!editingCustomer}
                className="form-control"
                placeholder="e.g. CUST-ACME-01"
                value={custCode}
                onChange={(e) => setCustCode(e.target.value.toUpperCase())}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Customer Name *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. Acme Industrial Automation"
                value={custName}
                onChange={(e) => setCustName(e.target.value)}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input type="email" className="form-control" value={custEmail} onChange={(e) => setCustEmail(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Phone</label>
              <input type="text" className="form-control" value={custPhone} onChange={(e) => setCustPhone(e.target.value)} />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Billing Street Address</label>
            <input type="text" className="form-control" value={custBillStreet} onChange={(e) => setCustBillStreet(e.target.value)} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">City</label>
              <input type="text" className="form-control" value={custBillCity} onChange={(e) => setCustBillCity(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">State</label>
              <input type="text" className="form-control" value={custBillState} onChange={(e) => setCustBillState(e.target.value)} />
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: CUSTOMER ARCHIVE CONFIRMATION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDeleteCustomerModalOpen}
        onClose={() => setIsDeleteCustomerModalOpen(false)}
        title="Confirm Customer Archival"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDeleteCustomerModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#ef4444', borderColor: '#ef4444' }} onClick={executeDeleteCustomer}>
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
              Archive Customer '{deletingCustomer?.name}'?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Customers with active demand or open orders cannot be archived until all associated orders are fulfilled or cancelled.
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
