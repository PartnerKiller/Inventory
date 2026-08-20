import React, { useEffect, useState, useRef } from 'react';
import {
  Package, Plus, Search, Filter, SlidersHorizontal, Eye, Edit3, Trash2,
  Barcode, Layers, AlertTriangle, CheckCircle, RefreshCw, FolderPlus,
  ArrowUpDown, Printer, ChevronLeft, ChevronRight, X, Sparkles
} from 'lucide-react';
import { api, GetItemsParams } from '../api/client';
import { Item, ItemDetail, ItemCategory, ItemVariant } from '@inventory/shared-types';
import { Modal } from '../components/Modal';
import { nativeBridge } from '@inventory/native-bridge';
import { useWarehouse } from '../context/WarehouseContext';

export const InventoryCatalogPage: React.FC = () => {
  const { activeWarehouseId, activeWarehouse } = useWarehouse();
  // Main Data States
  const [items, setItems] = useState<Item[]>([]);
  const [categories, setCategories] = useState<ItemCategory[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [totalItems, setTotalItems] = useState<number>(0);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Search & Filter States
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [stockStatus, setStockStatus] = useState<'all' | 'in_stock' | 'low_stock' | 'out_of_stock'>('all');
  const [activeFilter, setActiveFilter] = useState<string>('all'); // all, active, inactive
  const [sortBy, setSortBy] = useState<'created_at' | 'sku' | 'name'>('created_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isCategoryModalOpen, setIsCategoryModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  // Selected Records for Modals
  const [selectedItemDetail, setSelectedItemDetail] = useState<ItemDetail | null>(null);
  const [itemToEdit, setItemToEdit] = useState<Item | null>(null);
  const [itemToDelete, setItemToDelete] = useState<Item | null>(null);

  // Create Form State
  const [newSku, setNewSku] = useState('');
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newCategoryId, setNewCategoryId] = useState('');
  const [newBaseUom, setNewBaseUom] = useState('PCS');
  const [newValuationMethod, setNewValuationMethod] = useState('FIFO');
  const [newReorderPoint, setNewReorderPoint] = useState('10');
  const [newReorderQuantity, setNewReorderQuantity] = useState('50');
  const [newIsBatchTracked, setNewIsBatchTracked] = useState(false);
  const [newIsSerialTracked, setNewIsSerialTracked] = useState(false);
  const [newVariantSku, setNewVariantSku] = useState('');
  const [newVariantName, setNewVariantName] = useState('Standard');
  const [newCostPrice, setNewCostPrice] = useState('0.00');
  const [newSellingPrice, setNewSellingPrice] = useState('0.00');
  const [newBarcode, setNewBarcode] = useState('');

  // Category Management Form State
  const [newCatName, setNewCatName] = useState('');
  const [newCatCode, setNewCatCode] = useState('');
  const [newCatDesc, setNewCatDesc] = useState('');

  const searchInputRef = useRef<HTMLInputElement>(null);

  // Load Categories
  const loadCategories = async () => {
    try {
      const data = await api.getCategories();
      setCategories(data);
    } catch (err: any) {
      console.error('Failed to load categories:', err);
    }
  };

  // Load Products
  const loadItems = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);

      const params: GetItemsParams = {
        q: searchTerm.trim() || undefined,
        category_id: selectedCategory || undefined,
        warehouse_id: activeWarehouseId || undefined,
        is_active: activeFilter === 'active' ? true : activeFilter === 'inactive' ? false : undefined,
        stock_status: stockStatus,
        sort_by: sortBy,
        sort_dir: sortDir,
        page: page,
        page_size: pageSize,
      };

      const res = await api.getItems(params);
      setItems(res.items);
      setTotalItems(res.pagination.total_items ?? res.pagination.totalItems ?? 0);
      setTotalPages(res.pagination.total_pages ?? res.pagination.totalPages ?? 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to fetch inventory catalog');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadCategories();
  }, []);

  useEffect(() => {
    loadItems();
  }, [page, pageSize, selectedCategory, stockStatus, activeFilter, sortBy, sortDir, activeWarehouseId]);

  // Keyboard shortcut listener (/ to focus search)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement !== searchInputRef.current) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Search submission
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadItems();
  };

  // Open Create Modal
  const openCreateModal = () => {
    setNewSku('');
    setNewName('');
    setNewDescription('');
    setNewCategoryId(categories[0]?.id || '');
    setNewBaseUom('PCS');
    setNewValuationMethod('FIFO');
    setNewReorderPoint('10');
    setNewReorderQuantity('50');
    setNewIsBatchTracked(false);
    setNewIsSerialTracked(false);
    setNewVariantSku('');
    setNewVariantName('Standard');
    setNewCostPrice('0.00');
    setNewSellingPrice('0.00');
    setNewBarcode('');
    setIsCreateModalOpen(true);
  };

  // SKU auto-fill variant SKU & Barcode
  const handleSkuChange = (val: string) => {
    const upper = val.toUpperCase().replace(/\s+/g, '-');
    setNewSku(upper);
    if (!newVariantSku || newVariantSku.startsWith(newSku)) {
      setNewVariantSku(`${upper}-STD`);
    }
    if (!newBarcode || newBarcode.startsWith(newSku)) {
      setNewBarcode(`${upper}001`);
    }
  };

  // Submit Create Product
  const handleCreateProduct = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSku || !newName) {
      alert('SKU and Product Name are required');
      return;
    }

    try {
      await api.createItem({
        sku: newSku,
        name: newName,
        description: newDescription || undefined,
        category_id: newCategoryId || undefined,
        base_uom: newBaseUom,
        valuation_method: newValuationMethod,
        reorder_point: parseFloat(newReorderPoint) || 0,
        reorder_quantity: parseFloat(newReorderQuantity) || 0,
        is_batch_tracked: newIsBatchTracked,
        is_serial_tracked: newIsSerialTracked,
        variants: [
          {
            variant_sku: newVariantSku || `${newSku}-STD`,
            variant_name: newVariantName || 'Standard',
            cost_price: parseFloat(newCostPrice) || 0,
            selling_price: parseFloat(newSellingPrice) || 0,
            barcodes: newBarcode ? [{ barcode_value: newBarcode, symbology: 'CODE128', is_primary: true }] : []
          }
        ]
      });

      setIsCreateModalOpen(false);
      loadItems();
      loadCategories();
    } catch (err: any) {
      alert(`Product creation failed: ${err.message}`);
    }
  };

  // View Detail
  const handleViewDetail = async (item: Item) => {
    try {
      const detail = await api.getItemDetail(item.id);
      setSelectedItemDetail(detail);
      setIsDetailModalOpen(true);
    } catch (err: any) {
      alert(`Failed to load product detail: ${err.message}`);
    }
  };

  // Open Edit Modal
  const handleOpenEdit = async (item: Item) => {
    try {
      const detail = await api.getItemDetail(item.id);
      setItemToEdit(detail);
      setIsEditModalOpen(true);
    } catch (err: any) {
      alert(`Failed to prepare edit form: ${err.message}`);
    }
  };

  // Save Item Updates
  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!itemToEdit) return;

    try {
      await api.updateItem(itemToEdit.id, {
        name: itemToEdit.name,
        description: itemToEdit.description,
        category_id: itemToEdit.categoryId || itemToEdit.category_id,
        base_uom: itemToEdit.baseUom || itemToEdit.base_uom,
        valuation_method: itemToEdit.valuationMethod || itemToEdit.valuation_method,
        reorder_point: itemToEdit.reorderPoint ?? itemToEdit.reorder_point,
        reorder_quantity: itemToEdit.reorderQuantity ?? itemToEdit.reorder_quantity,
        is_active: itemToEdit.isActive ?? itemToEdit.is_active,
      });
      setIsEditModalOpen(false);
      loadItems();
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  // Open Delete Confirmation
  const handleConfirmDelete = (item: Item) => {
    setItemToDelete(item);
    setIsDeleteModalOpen(true);
  };

  const executeDelete = async () => {
    if (!itemToDelete) return;
    try {
      await api.deleteItem(itemToDelete.id);
      setIsDeleteModalOpen(false);
      setItemToDelete(null);
      loadItems();
    } catch (err: any) {
      alert(`Archive rejected: ${err.message}`);
    }
  };

  // Category Actions
  const handleCreateCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCatName || !newCatCode) return;
    try {
      await api.createCategory({
        name: newCatName,
        code: newCatCode,
        description: newCatDesc
      });
      setNewCatName('');
      setNewCatCode('');
      setNewCatDesc('');
      loadCategories();
    } catch (err: any) {
      alert(`Category creation failed: ${err.message}`);
    }
  };

  const handleDeleteCategory = async (catId: string) => {
    if (!confirm('Are you sure you want to delete this category?')) return;
    try {
      await api.deleteCategory(catId);
      loadCategories();
    } catch (err: any) {
      alert(`Failed to delete category: ${err.message}`);
    }
  };

  return (
    <div>
      {/* Header & Main Actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Product Master & Item Registry
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            SKU governance, variant matrices, dynamic barcode symbologies, and multi-bin stock tracking
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={() => setIsCategoryModalOpen(true)}>
            <FolderPlus size={15} /> Categories ({categories.length})
          </button>
          <button className="btn btn-primary" onClick={openCreateModal}>
            <Plus size={16} /> New Product
          </button>
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="card" style={{ marginBottom: '18px', padding: '16px 20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: '14px', alignItems: 'center' }}>
          {/* Search Bar with Scanner Focus */}
          <form onSubmit={handleSearchSubmit} style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              ref={searchInputRef}
              type="text"
              className="form-control"
              placeholder="Search SKU, name, or scan barcode (Press '/' to focus)..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ paddingLeft: '36px', height: '38px', fontSize: '13px' }}
            />
          </form>

          {/* Category Filter */}
          <div>
            <select
              className="form-control"
              style={{ height: '38px', fontSize: '13px' }}
              value={selectedCategory}
              onChange={(e) => { setSelectedCategory(e.target.value); setPage(1); }}
            >
              <option value="">All Categories ({categories.length})</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.itemCount ?? c.item_count ?? 0})</option>
              ))}
            </select>
          </div>

          {/* Stock Status Filter */}
          <div>
            <select
              className="form-control"
              style={{ height: '38px', fontSize: '13px' }}
              value={stockStatus}
              onChange={(e: any) => { setStockStatus(e.target.value); setPage(1); }}
            >
              <option value="all">All Inventory Levels</option>
              <option value="in_stock">In Stock (&gt; 0)</option>
              <option value="low_stock">Low Stock (≤ Reorder)</option>
              <option value="out_of_stock">Out of Stock (= 0)</option>
            </select>
          </div>

          {/* Status Filter */}
          <div>
            <select
              className="form-control"
              style={{ height: '38px', fontSize: '13px' }}
              value={activeFilter}
              onChange={(e) => { setActiveFilter(e.target.value); setPage(1); }}
            >
              <option value="all">All Lifecycle Statuses</option>
              <option value="active">Active Products Only</option>
              <option value="inactive">Archived / Inactive</option>
            </select>
          </div>

          {/* Sort Controls */}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              className="btn btn-secondary btn-sm"
              style={{ height: '38px', padding: '0 12px' }}
              onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')}
              title={`Toggle Sort Order: Currently ${sortDir.toUpperCase()}`}
            >
              <ArrowUpDown size={14} /> {sortDir.toUpperCase()}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              style={{ height: '38px', padding: '0 12px' }}
              onClick={loadItems}
              title="Refresh Products"
            >
              <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
            </button>
          </div>
        </div>
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

      {/* Product List Table */}
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>SKU / Code</th>
              <th>Product Name & Description</th>
              <th>Category</th>
              <th>UOM & Method</th>
              <th>Total Stock</th>
              <th>Reorder Trigger</th>
              <th>Status</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                  <RefreshCw size={24} className="spin" style={{ margin: '0 auto 8px' }} />
                  <div>Loading master catalog data...</div>
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                  <Package size={32} style={{ opacity: 0.4, margin: '0 auto 8px' }} />
                  <div style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-primary)' }}>No products found</div>
                  <div style={{ fontSize: '12.5px', marginTop: '4px' }}>Try adjusting your search filters or click 'New Product' to register one.</div>
                </td>
              </tr>
            ) : (
              items.map((item) => {
                const isLowStock = (item.totalStock ?? item.total_stock ?? 0) <= (item.reorderPoint ?? item.reorder_point ?? 0);
                const stockQty = item.totalStock ?? item.total_stock ?? 0;
                const active = item.isActive ?? item.is_active;

                return (
                  <tr key={item.id}>
                    <td>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd', fontSize: '13.5px' }}>
                        {item.sku}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                        {item.variants.length} {item.variants.length === 1 ? 'Variant' : 'Variants'}
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '13.5px' }}>{item.name}</div>
                      {item.description && (
                        <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', maxWidth: '300px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.description}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="badge badge-default">
                        {item.categoryName || item.category_name || 'Uncategorized'}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontSize: '12.5px', fontWeight: 600 }}>{item.baseUom || item.base_uom}</div>
                      <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{item.valuationMethod || item.valuation_method}</div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontWeight: 800, fontSize: '14px', color: stockQty > 0 ? '#34d399' : '#f87171' }}>
                          {stockQty}
                        </span>
                        {isLowStock && stockQty > 0 && (
                          <span className="badge badge-warning" style={{ fontSize: '10px', padding: '2px 6px' }}>
                            Low
                          </span>
                        )}
                        {stockQty === 0 && (
                          <span className="badge badge-danger" style={{ fontSize: '10px', padding: '2px 6px' }}>
                            Out
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                        Point: <strong>{item.reorderPoint ?? item.reorder_point}</strong>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        Qty: {item.reorderQuantity ?? item.reorder_quantity}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${active ? 'badge-success' : 'badge-default'}`}>
                        {active ? 'Active' : 'Archived'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '6px' }}>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => handleViewDetail(item)}
                          title="View Product Detail & Bin Stock"
                        >
                          <Eye size={13} />
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleOpenEdit(item)}
                          title="Edit Product Master & Variants"
                        >
                          <Edit3 size={13} />
                        </button>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => handleConfirmDelete(item)}
                          title="Archive Product"
                          style={{ color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)' }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '16px', padding: '0 4px' }}>
        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
          Showing <strong>{items.length}</strong> of <strong>{totalItems}</strong> total products (Page {page} of {totalPages || 1})
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
            <span>Per page:</span>
            <select
              className="form-control"
              style={{ width: '70px', padding: '4px 8px', height: '32px' }}
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            >
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </div>

          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              className="btn btn-secondary btn-sm"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* MODAL: CREATE PRODUCT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Create New Master Product"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsCreateModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleCreateProduct}>Create Master Product</button>
          </>
        }
      >
        <form onSubmit={handleCreateProduct}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '14px' }}>
            <div className="form-group">
              <label className="form-label">SKU / Code *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. SKU-SEN-100"
                value={newSku}
                onChange={(e) => handleSkuChange(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Product Name *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. High-Precision Optical Sensor"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea
              className="form-control"
              rows={2}
              placeholder="Product specifications, notes, packaging details..."
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Category</label>
              <select
                className="form-control"
                value={newCategoryId}
                onChange={(e) => setNewCategoryId(e.target.value)}
              >
                <option value="">-- No Category --</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Base UOM</label>
              <select className="form-control" value={newBaseUom} onChange={(e) => setNewBaseUom(e.target.value)}>
                <option value="PCS">PCS (Pieces)</option>
                <option value="BOX">BOX (Boxes)</option>
                <option value="KG">KG (Kilograms)</option>
                <option value="MTR">MTR (Meters)</option>
                <option value="LTR">LTR (Liters)</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Valuation Method</label>
              <select className="form-control" value={newValuationMethod} onChange={(e) => setNewValuationMethod(e.target.value)}>
                <option value="FIFO">FIFO (First-In, First-Out)</option>
                <option value="WEIGHTED_AVERAGE">Moving Weighted Average</option>
                <option value="STANDARD_COST">Standard Cost</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Reorder Point</label>
              <input
                type="number"
                step="1"
                className="form-control"
                value={newReorderPoint}
                onChange={(e) => setNewReorderPoint(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Reorder Quantity</label>
              <input
                type="number"
                step="1"
                className="form-control"
                value={newReorderQuantity}
                onChange={(e) => setNewReorderQuantity(e.target.value)}
              />
            </div>
          </div>

          {/* Initial Variant & Barcode Section */}
          <div style={{
            marginTop: '10px',
            padding: '14px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)'
          }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--accent-primary)', marginBottom: '10px' }}>
              Initial Standard Variant & Primary Barcode
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div className="form-group">
                <label className="form-label">Variant Name</label>
                <input
                  type="text"
                  className="form-control"
                  value={newVariantName}
                  onChange={(e) => setNewVariantName(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Variant SKU</label>
                <input
                  type="text"
                  className="form-control"
                  value={newVariantSku}
                  onChange={(e) => setNewVariantSku(e.target.value.toUpperCase())}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1.5fr', gap: '12px' }}>
              <div className="form-group">
                <label className="form-label">Cost Price ($)</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  value={newCostPrice}
                  onChange={(e) => setNewCostPrice(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Selling Price ($)</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  value={newSellingPrice}
                  onChange={(e) => setNewSellingPrice(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Primary Barcode Code128</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="e.g. 890123456789"
                  value={newBarcode}
                  onChange={(e) => setNewBarcode(e.target.value)}
                />
              </div>
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: PRODUCT DETAIL & BIN STOCK BREAKDOWN */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        title={`Product Inspection: ${selectedItemDetail?.sku}`}
        footer={<button className="btn btn-primary" onClick={() => setIsDetailModalOpen(false)}>Close</button>}
      >
        {selectedItemDetail && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px', marginBottom: '16px' }}>
              <div>
                <h3 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)' }}>
                  {selectedItemDetail.name}
                </h3>
                <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {selectedItemDetail.description || 'No description provided'}
                </p>
                <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                  <span className="badge badge-info">{selectedItemDetail.categoryName || 'Uncategorized'}</span>
                  <span className="badge badge-default">UOM: {selectedItemDetail.baseUom}</span>
                  <span className="badge badge-default">Method: {selectedItemDetail.valuationMethod}</span>
                </div>
              </div>

              <div style={{
                backgroundColor: 'var(--bg-app)',
                padding: '12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Total In-Stock Balance
                </div>
                <div style={{ fontSize: '26px', fontWeight: 800, color: (selectedItemDetail.totalStock ?? 0) > 0 ? '#34d399' : '#f87171', margin: '4px 0' }}>
                  {selectedItemDetail.totalStock ?? 0} {selectedItemDetail.baseUom}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                  Reorder Threshold: {selectedItemDetail.reorderPoint} units
                </div>
              </div>
            </div>

            {/* Variants & Barcode details */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
                Variants & Pricing Structure
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {selectedItemDetail.variants.map((v) => (
                  <div
                    key={v.id}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--bg-app)',
                      border: '1px solid var(--border-subtle)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between'
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '13px' }}>{v.variantName} ({v.variantSku})</div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                        Cost: <strong>${v.costPrice.toFixed(2)}</strong> &bull; Price: <strong>${v.sellingPrice.toFixed(2)}</strong> (Margin: {v.sellingPrice > 0 ? `${Math.round(((v.sellingPrice - v.costPrice) / v.sellingPrice) * 100)}%` : '0%'})
                      </div>
                    </div>
                    <div>
                      {v.barcodes.map((b) => (
                        <span key={b.id} className="scan-code-pill" style={{ marginLeft: '6px' }}>
                          <Barcode size={12} /> {b.barcodeValue}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Warehouse / Bin Breakdown Table */}
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
                Bin-Level Physical Stock Breakdown
              </div>
              {selectedItemDetail.bin_stock_breakdown && selectedItemDetail.bin_stock_breakdown.length > 0 ? (
                <table className="data-table" style={{ fontSize: '12px' }}>
                  <thead>
                    <tr>
                      <th>Facility</th>
                      <th>Bin Location</th>
                      <th>Batch #</th>
                      <th>On Hand</th>
                      <th>Allocated</th>
                      <th>Available</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedItemDetail.bin_stock_breakdown.map((b, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: 600 }}>{b.warehouse_name}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>{b.bin_code}</td>
                        <td>{b.batch_number || 'Default'}</td>
                        <td style={{ fontWeight: 700 }}>{b.quantity_on_hand}</td>
                        <td style={{ color: '#f59e0b' }}>{b.quantity_allocated}</td>
                        <td style={{ fontWeight: 800, color: '#34d399' }}>{b.quantity_available}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ padding: '14px', textAlign: 'center', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)', fontSize: '12.5px' }}>
                  No physical inventory currently allocated across warehouse storage bins.
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: EDIT PRODUCT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title={`Edit Product: ${itemToEdit?.sku}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsEditModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveEdit}>Save Changes</button>
          </>
        }
      >
        {itemToEdit && (
          <form onSubmit={handleSaveEdit}>
            <div className="form-group">
              <label className="form-label">Product Name *</label>
              <input
                type="text"
                required
                className="form-control"
                value={itemToEdit.name}
                onChange={(e) => setItemToEdit({ ...itemToEdit, name: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Description</label>
              <textarea
                className="form-control"
                rows={2}
                value={itemToEdit.description || ''}
                onChange={(e) => setItemToEdit({ ...itemToEdit, description: e.target.value })}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
              <div className="form-group">
                <label className="form-label">Category</label>
                <select
                  className="form-control"
                  value={itemToEdit.categoryId || itemToEdit.category_id || ''}
                  onChange={(e) => setItemToEdit({ ...itemToEdit, categoryId: e.target.value })}
                >
                  <option value="">-- No Category --</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Reorder Point</label>
                <input
                  type="number"
                  className="form-control"
                  value={itemToEdit.reorderPoint ?? itemToEdit.reorder_point ?? 0}
                  onChange={(e) => setItemToEdit({ ...itemToEdit, reorderPoint: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Reorder Quantity</label>
                <input
                  type="number"
                  className="form-control"
                  value={itemToEdit.reorderQuantity ?? itemToEdit.reorder_quantity ?? 0}
                  onChange={(e) => setItemToEdit({ ...itemToEdit, reorderQuantity: parseFloat(e.target.value) || 0 })}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Status</label>
              <select
                className="form-control"
                value={String(itemToEdit.isActive ?? itemToEdit.is_active)}
                onChange={(e) => setItemToEdit({ ...itemToEdit, isActive: e.target.value === 'true' })}
              >
                <option value="true">Active</option>
                <option value="false">Archived / Inactive</option>
              </select>
            </div>
          </form>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: CATEGORY MANAGEMENT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCategoryModalOpen}
        onClose={() => setIsCategoryModalOpen(false)}
        title="Product Categories & Classification"
        footer={<button className="btn btn-primary" onClick={() => setIsCategoryModalOpen(false)}>Done</button>}
      >
        <div>
          {/* Add Category Form */}
          <form onSubmit={handleCreateCategory} style={{
            padding: '12px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '16px',
            border: '1px solid var(--border-subtle)'
          }}>
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '8px' }}>Create New Category</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 2fr auto', gap: '8px', alignItems: 'flex-end' }}>
              <div>
                <label className="form-label" style={{ fontSize: '11px' }}>Name *</label>
                <input
                  type="text"
                  required
                  className="form-control"
                  placeholder="e.g. Sensors"
                  value={newCatName}
                  onChange={(e) => setNewCatName(e.target.value)}
                />
              </div>
              <div>
                <label className="form-label" style={{ fontSize: '11px' }}>Code *</label>
                <input
                  type="text"
                  required
                  className="form-control"
                  placeholder="e.g. SEN"
                  value={newCatCode}
                  onChange={(e) => setNewCatCode(e.target.value.toUpperCase())}
                />
              </div>
              <div>
                <label className="form-label" style={{ fontSize: '11px' }}>Description</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Optional details..."
                  value={newCatDesc}
                  onChange={(e) => setNewCatDesc(e.target.value)}
                />
              </div>
              <button type="submit" className="btn btn-primary" style={{ height: '36px' }}>
                <Plus size={14} /> Add
              </button>
            </div>
          </form>

          {/* Categories List */}
          <div style={{ maxHeight: '280px', overflowY: 'auto' }}>
            <table className="data-table" style={{ fontSize: '12.5px' }}>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Category Name</th>
                  <th>Description</th>
                  <th>Products</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>{c.code}</td>
                    <td style={{ fontWeight: 600 }}>{c.name}</td>
                    <td style={{ color: 'var(--text-secondary)', fontSize: '11.5px' }}>{c.description || '—'}</td>
                    <td>
                      <span className="badge badge-info">{c.itemCount ?? c.item_count ?? 0}</span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-outline btn-sm"
                        style={{ color: '#f87171', padding: '2px 6px' }}
                        onClick={() => handleDeleteCategory(c.id)}
                        title="Delete Category"
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
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: DELETE CONFIRMATION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        title="Confirm Product Archive"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDeleteModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#ef4444', borderColor: '#ef4444' }} onClick={executeDelete}>
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
              Archive Product '{itemToDelete?.sku}'?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              This will mark <strong>{itemToDelete?.name}</strong> as archived. Products with positive physical stock in warehouse bins cannot be archived until their balances are adjusted to zero.
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
};
