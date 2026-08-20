import React, { useEffect, useState } from 'react';
import {
  Warehouse as WarehouseIcon, Plus, Edit3, Trash2, Box, Layers, MapPin,
  CheckCircle, AlertTriangle, RefreshCw, Search, ShieldCheck, ChevronRight, X
} from 'lucide-react';
import { api } from '../api/client';
import { Warehouse, LocationBin } from '@inventory/shared-types';
import { Modal } from '../components/Modal';

export const WarehousesPage: React.FC = () => {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<string>('all'); // all, active, inactive
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isBinDrawerOpen, setIsBinDrawerOpen] = useState(false);

  // Selected Records
  const [selectedWarehouse, setSelectedWarehouse] = useState<Warehouse | null>(null);
  const [warehouseToEdit, setWarehouseToEdit] = useState<Warehouse | null>(null);
  const [warehouseToDelete, setWarehouseToDelete] = useState<Warehouse | null>(null);

  // Warehouse Form States
  const [whCode, setWhCode] = useState('');
  const [whName, setWhName] = useState('');
  const [whStreet, setWhStreet] = useState('');
  const [whCity, setWhCity] = useState('');
  const [whState, setWhState] = useState('');
  const [whPostal, setWhPostal] = useState('');

  // Bin Management States (inside drawer)
  const [warehouseBins, setWarehouseBins] = useState<LocationBin[]>([]);
  const [binSearch, setBinSearch] = useState('');
  const [binTypeFilter, setBinTypeFilter] = useState('');
  const [isCreateBinModalOpen, setIsCreateBinModalOpen] = useState(false);
  const [isEditBinModalOpen, setIsEditBinModalOpen] = useState(false);
  const [binToEdit, setBinToEdit] = useState<LocationBin | null>(null);
  const [binToDelete, setBinToDelete] = useState<LocationBin | null>(null);
  const [isDeleteBinModalOpen, setIsDeleteBinModalOpen] = useState(false);

  // New Bin Form States
  const [newBinCode, setNewBinCode] = useState('');
  const [newBinAisle, setNewBinAisle] = useState('A');
  const [newBinRack, setNewBinRack] = useState('01');
  const [newBinShelf, setNewBinShelf] = useState('01');
  const [newBinLevel, setNewBinLevel] = useState('01');
  const [newBinType, setNewBinType] = useState('STORAGE');

  // Load Warehouses
  const loadWarehouses = async () => {
    try {
      setIsLoading(true);
      setErrorMessage(null);
      const data = await api.getWarehouses({
        q: searchTerm.trim() || undefined,
        is_active: activeFilter === 'active' ? true : activeFilter === 'inactive' ? false : undefined,
      });
      setWarehouses(data);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load warehouses');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadWarehouses();
  }, [activeFilter]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadWarehouses();
  };

  // Open Create Warehouse
  const openCreateModal = () => {
    setWhCode('');
    setWhName('');
    setWhStreet('');
    setWhCity('');
    setWhState('');
    setWhPostal('');
    setIsCreateModalOpen(true);
  };

  const handleCreateWarehouse = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!whCode || !whName) {
      alert('Warehouse Code and Name are required');
      return;
    }

    try {
      await api.createWarehouse({
        code: whCode.toUpperCase().trim(),
        name: whName.trim(),
        address: {
          street: whStreet.trim(),
          city: whCity.trim(),
          state: whState.trim(),
          postalCode: whPostal.trim(),
        }
      });
      setIsCreateModalOpen(false);
      loadWarehouses();
    } catch (err: any) {
      alert(`Warehouse creation failed: ${err.message}`);
    }
  };

  // Open Edit Warehouse
  const handleOpenEdit = (wh: Warehouse) => {
    setWarehouseToEdit(wh);
    setWhName(wh.name);
    setWhStreet(wh.address?.street || '');
    setWhCity(wh.address?.city || '');
    setWhState(wh.address?.state || '');
    setWhPostal(wh.address?.postalCode || '');
    setIsEditModalOpen(true);
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!warehouseToEdit) return;

    try {
      await api.updateWarehouse(warehouseToEdit.id, {
        name: whName.trim(),
        address: {
          street: whStreet.trim(),
          city: whCity.trim(),
          state: whState.trim(),
          postalCode: whPostal.trim(),
        },
        is_active: warehouseToEdit.isActive ?? warehouseToEdit.is_active,
      });
      setIsEditModalOpen(false);
      loadWarehouses();
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  // Delete Warehouse
  const handleConfirmDelete = (wh: Warehouse) => {
    setWarehouseToDelete(wh);
    setIsDeleteModalOpen(true);
  };

  const executeDeleteWarehouse = async () => {
    if (!warehouseToDelete) return;
    try {
      await api.deleteWarehouse(warehouseToDelete.id);
      setIsDeleteModalOpen(false);
      setWarehouseToDelete(null);
      loadWarehouses();
    } catch (err: any) {
      alert(`Archive rejected: ${err.message}`);
    }
  };

  // =========================================================================
  // BIN MANAGEMENT DRAWER
  // =========================================================================
  const openBinDrawer = async (wh: Warehouse) => {
    setSelectedWarehouse(wh);
    await loadBins(wh.id);
    setIsBinDrawerOpen(true);
  };

  const loadBins = async (whId: string) => {
    try {
      const bins = await api.getWarehouseBins(whId, {
        q: binSearch.trim() || undefined,
        type: binTypeFilter || undefined,
      });
      setWarehouseBins(bins);
    } catch (err: any) {
      console.error('Failed to load bins:', err);
    }
  };

  const handleCreateBin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWarehouse || !newBinCode) return;

    try {
      await api.createBin(selectedWarehouse.id, {
        code: newBinCode.toUpperCase().trim(),
        aisle: newBinAisle.trim(),
        rack: newBinRack.trim(),
        shelf: newBinShelf.trim(),
        bin: newBinLevel.trim(),
        type: newBinType,
      });
      setIsCreateBinModalOpen(false);
      setNewBinCode('');
      loadBins(selectedWarehouse.id);
      loadWarehouses();
    } catch (err: any) {
      alert(`Bin creation failed: ${err.message}`);
    }
  };

  const handleOpenEditBin = (bin: LocationBin) => {
    setBinToEdit(bin);
    setIsEditBinModalOpen(true);
  };

  const handleSaveEditBin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWarehouse || !binToEdit) return;

    try {
      await api.updateBin(selectedWarehouse.id, binToEdit.id, {
        code: binToEdit.code,
        aisle: binToEdit.aisle,
        rack: binToEdit.rack,
        shelf: binToEdit.shelf,
        bin: binToEdit.bin,
        type: binToEdit.type,
        is_active: binToEdit.isActive ?? binToEdit.is_active,
      });
      setIsEditBinModalOpen(false);
      loadBins(selectedWarehouse.id);
    } catch (err: any) {
      alert(`Bin update failed: ${err.message}`);
    }
  };

  const handleConfirmDeleteBin = (bin: LocationBin) => {
    setBinToDelete(bin);
    setIsDeleteBinModalOpen(true);
  };

  const executeDeleteBin = async () => {
    if (!selectedWarehouse || !binToDelete) return;
    try {
      await api.deleteBin(selectedWarehouse.id, binToDelete.id);
      setIsDeleteBinModalOpen(false);
      setBinToDelete(null);
      loadBins(selectedWarehouse.id);
      loadWarehouses();
    } catch (err: any) {
      alert(`Bin deletion rejected: ${err.message}`);
    }
  };

  return (
    <div>
      {/* Page Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            Warehouses & Location Bins
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Multi-facility management, physical bin hierarchies, and storage zone topologies
          </p>
        </div>

        <button className="btn btn-primary" onClick={openCreateModal}>
          <Plus size={16} /> New Warehouse
        </button>
      </div>

      {/* Toolbar */}
      <div className="card" style={{ marginBottom: '18px', padding: '16px 20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: '14px', alignItems: 'center' }}>
          <form onSubmit={handleSearch} style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              className="form-control"
              placeholder="Search warehouse code or facility name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ paddingLeft: '36px', height: '38px', fontSize: '13px' }}
            />
          </form>

          <div>
            <select
              className="form-control"
              style={{ height: '38px', fontSize: '13px' }}
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value)}
            >
              <option value="all">All Facility Statuses</option>
              <option value="active">Active Warehouses Only</option>
              <option value="inactive">Archived / Inactive</option>
            </select>
          </div>

          <button className="btn btn-secondary" style={{ height: '38px' }} onClick={loadWarehouses}>
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh
          </button>
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

      {/* Warehouse Cards Grid */}
      {isLoading ? (
        <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
          <RefreshCw size={28} className="spin" style={{ margin: '0 auto 12px' }} />
          <div>Loading warehouse facilities...</div>
        </div>
      ) : warehouses.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          <WarehouseIcon size={36} style={{ opacity: 0.4, margin: '0 auto 10px' }} />
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '15px' }}>No warehouses found</div>
          <div style={{ fontSize: '13px', marginTop: '4px' }}>Click 'New Warehouse' to register your first storage facility.</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
          {warehouses.map((wh) => {
            const active = wh.isActive ?? wh.is_active;
            const stockQty = wh.total_stock_on_hand ?? 0;
            const binCount = wh.totalBins ?? wh.total_bins ?? (wh.bins ? wh.bins.length : 0);

            return (
              <div key={wh.id} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                    <div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '13px', color: '#93c5fd', letterSpacing: '0.5px' }}>
                        {wh.code}
                      </span>
                      <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
                        {wh.name}
                      </h3>
                    </div>
                    <span className={`badge ${active ? 'badge-success' : 'badge-default'}`}>
                      {active ? 'Active' : 'Archived'}
                    </span>
                  </div>

                  {wh.address?.city && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '14px' }}>
                      <MapPin size={13} style={{ color: 'var(--text-muted)' }} />
                      <span>{wh.address.street ? `${wh.address.street}, ` : ''}{wh.address.city}, {wh.address.state || ''} {wh.address.postalCode || ''}</span>
                    </div>
                  )}

                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '8px',
                    padding: '10px',
                    backgroundColor: 'var(--bg-app)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    marginBottom: '14px'
                  }}>
                    <div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Configured Bins</div>
                      <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)' }}>{binCount}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>On Hand Stock</div>
                      <div style={{ fontSize: '18px', fontWeight: 800, color: stockQty > 0 ? '#34d399' : 'var(--text-muted)' }}>
                        {stockQty} units
                      </div>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => openBinDrawer(wh)}
                    style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    <Layers size={13} /> Manage Bins ({binCount}) <ChevronRight size={13} />
                  </button>

                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button className="btn btn-outline btn-sm" onClick={() => handleOpenEdit(wh)} title="Edit Warehouse">
                      <Edit3 size={13} />
                    </button>
                    <button
                      className="btn btn-outline btn-sm"
                      style={{ color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)' }}
                      onClick={() => handleConfirmDelete(wh)}
                      title="Archive Warehouse"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: CREATE WAREHOUSE */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Register New Warehouse Facility"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsCreateModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleCreateWarehouse}>Register Facility</button>
          </>
        }
      >
        <form onSubmit={handleCreateWarehouse}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Facility Code *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. WH-CHI-01"
                value={whCode}
                onChange={(e) => setWhCode(e.target.value.toUpperCase())}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Warehouse Name *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. Chicago Central Hub"
                value={whName}
                onChange={(e) => setWhName(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Street Address</label>
            <input
              type="text"
              className="form-control"
              placeholder="e.g. 500 Logistics Parkway"
              value={whStreet}
              onChange={(e) => setWhStreet(e.target.value)}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">City</label>
              <input type="text" className="form-control" value={whCity} onChange={(e) => setWhCity(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">State / Region</label>
              <input type="text" className="form-control" value={whState} onChange={(e) => setWhState(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Postal Code</label>
              <input type="text" className="form-control" value={whPostal} onChange={(e) => setWhPostal(e.target.value)} />
            </div>
          </div>

          <div style={{
            padding: '10px 14px',
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            fontSize: '12px',
            color: 'var(--text-secondary)',
            marginTop: '8px'
          }}>
            <CheckCircle size={14} style={{ color: '#34d399', display: 'inline', marginRight: '6px' }} />
            Automatically configures default <strong>RECEIVING</strong>, <strong>STAGING</strong>, and <strong>STORAGE</strong> location bins.
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: EDIT WAREHOUSE */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title={`Edit Warehouse: ${warehouseToEdit?.code}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsEditModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveEdit}>Save Changes</button>
          </>
        }
      >
        {warehouseToEdit && (
          <form onSubmit={handleSaveEdit}>
            <div className="form-group">
              <label className="form-label">Warehouse Name *</label>
              <input
                type="text"
                required
                className="form-control"
                value={whName}
                onChange={(e) => setWhName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Street Address</label>
              <input type="text" className="form-control" value={whStreet} onChange={(e) => setWhStreet(e.target.value)} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px' }}>
              <div className="form-group">
                <label className="form-label">City</label>
                <input type="text" className="form-control" value={whCity} onChange={(e) => setWhCity(e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">State</label>
                <input type="text" className="form-control" value={whState} onChange={(e) => setWhState(e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Postal Code</label>
                <input type="text" className="form-control" value={whPostal} onChange={(e) => setWhPostal(e.target.value)} />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Status</label>
              <select
                className="form-control"
                value={String(warehouseToEdit.isActive ?? warehouseToEdit.is_active)}
                onChange={(e) => setWarehouseToEdit({ ...warehouseToEdit, isActive: e.target.value === 'true' })}
              >
                <option value="true">Active Facility</option>
                <option value="false">Archived / Inactive</option>
              </select>
            </div>
          </form>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: DELETE WAREHOUSE CONFIRMATION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        title="Confirm Warehouse Archival"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDeleteModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#ef4444', borderColor: '#ef4444' }} onClick={executeDeleteWarehouse}>
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
              Archive Warehouse '{warehouseToDelete?.code}'?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              This facility will be marked as archived. Facilities containing active stock across any bins cannot be archived until all inventory balances are transferred or adjusted to zero.
            </div>
          </div>
        </div>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: LOCATION BINS MANAGEMENT */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isBinDrawerOpen}
        onClose={() => setIsBinDrawerOpen(false)}
        title={`Location Bins: ${selectedWarehouse?.name} (${selectedWarehouse?.code})`}
        footer={<button className="btn btn-primary" onClick={() => setIsBinDrawerOpen(false)}>Done</button>}
      >
        {selectedWarehouse && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div style={{ display: 'flex', gap: '8px', flex: 1, marginRight: '10px' }}>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Filter bin code..."
                  value={binSearch}
                  onChange={(e) => { setBinSearch(e.target.value); loadBins(selectedWarehouse.id); }}
                  style={{ height: '34px', fontSize: '12.5px' }}
                />
                <select
                  className="form-control"
                  style={{ height: '34px', fontSize: '12.5px', width: '150px' }}
                  value={binTypeFilter}
                  onChange={(e) => { setBinTypeFilter(e.target.value); loadBins(selectedWarehouse.id); }}
                >
                  <option value="">All Types</option>
                  <option value="STORAGE">STORAGE</option>
                  <option value="RECEIVING">RECEIVING</option>
                  <option value="SHIPPING">SHIPPING</option>
                  <option value="STAGING">STAGING</option>
                  <option value="DAMAGE">DAMAGE</option>
                  <option value="VIRTUAL_ADJUSTMENT">VIRTUAL</option>
                </select>
              </div>

              <button className="btn btn-primary btn-sm" onClick={() => setIsCreateBinModalOpen(true)}>
                <Plus size={14} /> New Bin
              </button>
            </div>

            <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
              <table className="data-table" style={{ fontSize: '12px' }}>
                <thead>
                  <tr>
                    <th>Bin Code</th>
                    <th>Type</th>
                    <th>Aisle</th>
                    <th>Rack</th>
                    <th>Shelf</th>
                    <th>Level</th>
                    <th>Occupancy</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {warehouseBins.map((b) => (
                    <tr key={b.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#93c5fd' }}>{b.code}</td>
                      <td>
                        <span className={`badge ${
                          b.type === 'STORAGE' ? 'badge-info' :
                          b.type === 'RECEIVING' ? 'badge-success' :
                          b.type === 'DAMAGE' ? 'badge-danger' : 'badge-default'
                        }`}>
                          {b.type}
                        </span>
                      </td>
                      <td>{b.aisle}</td>
                      <td>{b.rack}</td>
                      <td>{b.shelf}</td>
                      <td>{b.bin}</td>
                      <td>
                        <span style={{ fontWeight: 600, color: (b.occupied_items_count ?? 0) > 0 ? '#34d399' : 'var(--text-muted)' }}>
                          {b.occupied_items_count ?? 0} SKUs
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '4px' }}>
                          <button className="btn btn-outline btn-sm" style={{ padding: '2px 6px' }} onClick={() => handleOpenEditBin(b)}>
                            <Edit3 size={12} />
                          </button>
                          <button
                            className="btn btn-outline btn-sm"
                            style={{ color: '#f87171', padding: '2px 6px' }}
                            onClick={() => handleConfirmDeleteBin(b)}
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: CREATE BIN */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreateBinModalOpen}
        onClose={() => setIsCreateBinModalOpen(false)}
        title={`Add Bin to ${selectedWarehouse?.code}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsCreateBinModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleCreateBin}>Add Location Bin</button>
          </>
        }
      >
        <form onSubmit={handleCreateBin}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '12px' }}>
            <div className="form-group">
              <label className="form-label">Bin Code *</label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. WH-ATX-B02-04"
                value={newBinCode}
                onChange={(e) => setNewBinCode(e.target.value.toUpperCase())}
              />
            </div>
            <div className="form-group">
              <label className="form-label">Bin Type *</label>
              <select className="form-control" value={newBinType} onChange={(e) => setNewBinType(e.target.value)}>
                <option value="STORAGE">STORAGE</option>
                <option value="RECEIVING">RECEIVING</option>
                <option value="SHIPPING">SHIPPING</option>
                <option value="STAGING">STAGING</option>
                <option value="DAMAGE">DAMAGE</option>
                <option value="VIRTUAL_ADJUSTMENT">VIRTUAL_ADJUSTMENT</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px' }}>
            <div className="form-group">
              <label className="form-label">Aisle</label>
              <input type="text" className="form-control" value={newBinAisle} onChange={(e) => setNewBinAisle(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Rack</label>
              <input type="text" className="form-control" value={newBinRack} onChange={(e) => setNewBinRack(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Shelf</label>
              <input type="text" className="form-control" value={newBinShelf} onChange={(e) => setNewBinShelf(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Bin / Level</label>
              <input type="text" className="form-control" value={newBinLevel} onChange={(e) => setNewBinLevel(e.target.value)} />
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: DELETE BIN CONFIRMATION */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDeleteBinModalOpen}
        onClose={() => setIsDeleteBinModalOpen(false)}
        title="Confirm Bin Deletion"
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsDeleteBinModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" style={{ backgroundColor: '#ef4444', borderColor: '#ef4444' }} onClick={executeDeleteBin}>
              Confirm Delete
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
              Delete Bin '{binToDelete?.code}'?
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
              Only completely empty bins with zero on-hand and allocated stock can be deleted.
            </div>
          </div>
        </div>
      </Modal>
    </div>
  );
};
