import React, { useEffect, useState } from 'react';
import { Settings, Building2, Globe, Warehouse, ShieldAlert, CheckCircle, Save, RefreshCw, AlertTriangle, ShieldCheck, Monitor, Server, Printer, Barcode, Wifi, WifiOff } from 'lucide-react';
import { api } from '../api/client';
import { nativeBridge, PrinterInfo } from '@inventory/native-bridge';
import { SystemSettings, Warehouse as WarehouseType, PrintLayout, AppMetadata } from '@inventory/shared-types';

export const SettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([]);
  const [activeTab, setActiveTab] = useState<'general' | 'facilities' | 'policies' | 'security' | 'desktop'>('general');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [desktopApiUrl, setDesktopApiUrl] = useState<string>(api.getBaseUrl());
  const [connectionCheck, setConnectionCheck] = useState<{ ok: boolean; status: string; latencyMs: number; message?: string } | null>(null);
  const [isCheckingConn, setIsCheckingConn] = useState<boolean>(false);
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [selectedPrinter, setSelectedPrinter] = useState<string>(localStorage.getItem('aurastock_pref_printer') || '');
  const [appInfo, setAppInfo] = useState<AppMetadata>(nativeBridge.getAppInfo());

  // Form state
  const [formData, setFormData] = useState<Partial<SystemSettings>>({});

  const loadData = async () => {
    try {
      setIsLoading(true);
      const [sets, whs] = await Promise.all([
        api.getSettings(),
        api.getWarehouses(),
      ]);
      setSettings(sets);
      setFormData(sets);
      setWarehouses(whs);
    } catch (err: any) {
      console.error('Failed to load settings:', err);
      setSaveError(err.message || 'Failed to load system settings');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleChange = (field: keyof SystemSettings, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setSaveSuccess(null);
    setSaveError(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsSaving(true);
      setSaveError(null);
      setSaveSuccess(null);

      const updated = await api.updateSettings({
        company_name: formData.company_name,
        company_email: formData.company_email,
        company_phone: formData.company_phone,
        logo_url: formData.logo_url,
        currency: formData.currency,
        timezone: formData.timezone,
        date_format: formData.date_format,
        default_warehouse_id: formData.default_warehouse_id || undefined,
        default_receiving_bin_id: formData.default_receiving_bin_id || undefined,
        default_damage_bin_id: formData.default_damage_bin_id || undefined,
        auto_allocate_on_confirm: formData.auto_allocate_on_confirm,
        require_grn_inspection: formData.require_grn_inspection,
        default_payment_terms: formData.default_payment_terms,
        default_tax_pct: Number(formData.default_tax_pct || 0),
        require_po_approval: formData.require_po_approval,
        po_approval_threshold: Number(formData.po_approval_threshold || 1000),
      });

      setSettings(updated);
      setFormData(updated);
      setSaveSuccess('System settings updated successfully and audit logged.');
    } catch (err: any) {
      console.error('Failed to save settings:', err);
      setSaveError(err.message || 'Failed to save settings');
    } finally {
      setIsSaving(false);
    }
  };

  const selectedWarehouse = warehouses.find((w) => w.id === formData.default_warehouse_id);
  const availableBins = selectedWarehouse?.bins || [];

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            System Settings & Enterprise Configuration
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Tenant parameters, facility defaults, automated fulfillment policies, and security governance
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={loadData} disabled={isLoading}>
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={isSaving || isLoading}>
            <Save size={15} /> {isSaving ? 'Saving Changes...' : 'Save Settings'}
          </button>
        </div>
      </div>

      {saveSuccess && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: 'var(--radius-sm)',
          color: '#34d399',
          fontSize: '13px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <CheckCircle size={16} /> {saveSuccess}
        </div>
      )}

      {saveError && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-sm)',
          color: '#f87171',
          fontSize: '13px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <AlertTriangle size={16} /> {saveError}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '16px' }}>
        <button
          className={`btn ${activeTab === 'general' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('general')}
        >
          <Building2 size={15} /> Company & Localization
        </button>
        <button
          className={`btn ${activeTab === 'facilities' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('facilities')}
        >
          <Warehouse size={15} /> Facility Defaults
        </button>
        <button
          className={`btn ${activeTab === 'policies' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('policies')}
        >
          <Globe size={15} /> Business Policies
        </button>
        <button
          className={`btn ${activeTab === 'security' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('security')}
        >
          <ShieldCheck size={15} /> Security & Invariants
        </button>
        <button
          className={`btn ${activeTab === 'desktop' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('desktop')}
        >
          <Monitor size={15} /> Desktop & Connectivity
        </button>
      </div>

      <form onSubmit={handleSave}>
        {/* TAB 1: GENERAL */}
        {activeTab === 'general' && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Tenant Organization & Locale</div>
              <span className="badge badge-info">Profile & Formatting</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group">
                <label className="form-label">Company / Organization Name *</label>
                <input
                  type="text"
                  required
                  className="form-control"
                  value={formData.company_name || ''}
                  onChange={(e) => handleChange('company_name', e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Official Contact Email</label>
                <input
                  type="email"
                  className="form-control"
                  placeholder="contact@enterprise.com"
                  value={formData.company_email || ''}
                  onChange={(e) => handleChange('company_email', e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Contact Phone</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="+1 (555) 019-2834"
                  value={formData.company_phone || ''}
                  onChange={(e) => handleChange('company_phone', e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Brand Logo URL</label>
                <input
                  type="url"
                  className="form-control"
                  placeholder="https://assets.enterprise.com/logo.png"
                  value={formData.logo_url || ''}
                  onChange={(e) => handleChange('logo_url', e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Base Operating Currency *</label>
                <select
                  className="form-control"
                  value={formData.currency || 'USD'}
                  onChange={(e) => handleChange('currency', e.target.value)}
                >
                  <option value="USD">USD ($) - US Dollar</option>
                  <option value="EUR">EUR (€) - Euro</option>
                  <option value="GBP">GBP (£) - British Pound</option>
                  <option value="JPY">JPY (¥) - Japanese Yen</option>
                  <option value="CAD">CAD ($) - Canadian Dollar</option>
                  <option value="AUD">AUD ($) - Australian Dollar</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">System Timezone *</label>
                <select
                  className="form-control"
                  value={formData.timezone || 'UTC'}
                  onChange={(e) => handleChange('timezone', e.target.value)}
                >
                  <option value="UTC">UTC (Universal Time Coordinated)</option>
                  <option value="America/New_York">America/New_York (EST/EDT)</option>
                  <option value="America/Chicago">America/Chicago (CST/CDT)</option>
                  <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                  <option value="Europe/London">Europe/London (GMT/BST)</option>
                  <option value="Europe/Berlin">Europe/Berlin (CET/CEST)</option>
                  <option value="Asia/Tokyo">Asia/Tokyo (JST)</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Date Presentation Format *</label>
                <select
                  className="form-control"
                  value={formData.date_format || 'YYYY-MM-DD'}
                  onChange={(e) => handleChange('date_format', e.target.value)}
                >
                  <option value="YYYY-MM-DD">YYYY-MM-DD (ISO 8601 Standard)</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY (US Standard)</option>
                  <option value="DD/MM/YYYY">DD/MM/YYYY (European Standard)</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: FACILITIES */}
        {activeTab === 'facilities' && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Default Facilities & Logistics Routing</div>
              <span className="badge badge-info">Warehouse Topology</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group" style={{ gridColumn: 'span 2' }}>
                <label className="form-label">Default Fulfillment Warehouse</label>
                <select
                  className="form-control"
                  value={formData.default_warehouse_id || ''}
                  onChange={(e) => handleChange('default_warehouse_id', e.target.value)}
                >
                  <option value="">-- No Default Facility Selected --</option>
                  {warehouses.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.code} - {w.name} ({w.address?.city || 'Facility'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Default Receiving Staging Bin</label>
                <select
                  className="form-control"
                  value={formData.default_receiving_bin_id || ''}
                  onChange={(e) => handleChange('default_receiving_bin_id', e.target.value)}
                >
                  <option value="">-- Select Receiving Bin --</option>
                  {availableBins.map((b) => (
                    <option key={b.id} value={b.id}>
                      [{b.type}] {b.code} ({b.aisle}-{b.rack})
                    </option>
                  ))}
                </select>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Auto-populated on incoming PO Goods Receipts (GRN)
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Default Damaged / Quarantine Bin</label>
                <select
                  className="form-control"
                  value={formData.default_damage_bin_id || ''}
                  onChange={(e) => handleChange('default_damage_bin_id', e.target.value)}
                >
                  <option value="">-- Select Damage Bin --</option>
                  {availableBins.map((b) => (
                    <option key={b.id} value={b.id}>
                      [{b.type}] {b.code} ({b.aisle}-{b.rack})
                    </option>
                  ))}
                </select>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Targeted automatically during RMA returns for damaged stock
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: POLICIES */}
        {activeTab === 'policies' && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Commercial & Operational Fulfillment Policies</div>
              <span className="badge badge-info">Workflow Automation</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group">
                <label className="form-label">Default Commercial Payment Terms</label>
                <select
                  className="form-control"
                  value={formData.default_payment_terms || 'NET_30'}
                  onChange={(e) => handleChange('default_payment_terms', e.target.value)}
                >
                  <option value="IMMEDIATE">Immediate / Due on Receipt</option>
                  <option value="NET_15">Net 15 Days</option>
                  <option value="NET_30">Net 30 Days</option>
                  <option value="NET_60">Net 60 Days</option>
                  <option value="NET_90">Net 90 Days</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Default Commercial Tax Rate (%)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="100"
                  className="form-control"
                  value={formData.default_tax_pct ?? 0}
                  onChange={(e) => handleChange('default_tax_pct', parseFloat(e.target.value) || 0)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Purchase Order Approval Threshold ($)</label>
                <input
                  type="number"
                  step="100"
                  min="0"
                  className="form-control"
                  value={formData.po_approval_threshold ?? 1000}
                  onChange={(e) => handleChange('po_approval_threshold', parseFloat(e.target.value) || 0)}
                />
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Orders exceeding this monetary value require formal manager approval
                </div>
              </div>

              <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '8px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={formData.require_po_approval ?? true}
                    onChange={(e) => handleChange('require_po_approval', e.target.checked)}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                      Enforce Purchase Order Approval Gate
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Draft POs must transition through PENDING_APPROVAL and APPROVED before goods receipt is permitted
                    </div>
                  </div>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={formData.auto_allocate_on_confirm ?? false}
                    onChange={(e) => handleChange('auto_allocate_on_confirm', e.target.checked)}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                      Auto-Allocate Stock on Order Confirmation
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Automatically reserve available physical stock when a Sales Order is confirmed
                    </div>
                  </div>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={formData.require_grn_inspection ?? false}
                    onChange={(e) => handleChange('require_grn_inspection', e.target.checked)}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>
                      Require Quality Inspection for Inbound Receipts
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Force incoming goods into QA inspection bin before moving to primary storage
                    </div>
                  </div>
                </label>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: SECURITY */}
        {activeTab === 'security' && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Security Governance & Architectural Invariants</div>
              <span className="badge badge-success">Hardware & Enclave Protected</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{
                padding: '16px',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px'
              }}>
                <ShieldCheck size={24} style={{ color: '#60a5fa', flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <div style={{ fontWeight: 700, fontSize: '14px', color: '#60a5fa' }}>
                    Infrastructure Secrets & Token Enclave Isolation
                  </div>
                  <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.5 }}>
                    In accordance with enterprise security standards, database passwords, JWT signing keys, Redis credentials, and cryptographic salts are injected via environment variables and are inaccessible via the application API.
                  </div>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div style={{ padding: '14px', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Negative Stock Prevention
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '15px', color: '#34d399', marginTop: '4px' }}>
                    Enforced (Zero Negative Stock)
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    PostgreSQL CHECK constraint: <code>quantity_on_hand &gt;= 0</code>
                  </div>
                </div>

                <div style={{ padding: '14px', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Concurrency Protection
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '15px', color: '#60a5fa', marginTop: '4px' }}>
                    Deterministic Row Locking
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Pessimistic <code>SELECT FOR UPDATE</code> with sorted resource keys
                  </div>
                </div>

                <div style={{ padding: '14px', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Stock Ledger Integrity
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '15px', color: '#a78bfa', marginTop: '4px' }}>
                    Append-Only Immutable Ledger
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Double-entry balance projections with cryptographic audit hashes
                  </div>
                </div>

                <div style={{ padding: '14px', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Session Security
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '15px', color: '#f59e0b', marginTop: '4px' }}>
                    Refresh Token Rotation
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Single-use token rotation with multi-session individual & global revocation
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: DESKTOP & CONNECTIVITY */}
        {activeTab === 'desktop' && (
          <div className="card">
            <div className="card-header">
              <div className="card-title">Windows Desktop & Hardware Connectivity</div>
              <span className="badge badge-success">{appInfo.platform}</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Client Metadata Banner */}
              <div style={{
                padding: '14px 18px',
                backgroundColor: 'var(--bg-app)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '16px',
                fontSize: '12.5px'
              }}>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block' }}>Application Client</span>
                  <strong style={{ color: 'var(--text-primary)' }}>{appInfo.name}</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block' }}>Version</span>
                  <strong style={{ color: 'var(--text-primary)' }}>v{appInfo.version}</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block' }}>Runtime Engine</span>
                  <strong style={{ color: appInfo.isDesktop ? '#10b981' : '#38bdf8' }}>
                    {appInfo.platform}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', display: 'block' }}>Security Vault</span>
                  <strong style={{ color: '#10b981' }}>OS Credential Store</strong>
                </div>
              </div>

              {/* API Server Endpoint Configuration */}
              <div className="form-group">
                <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Server size={15} color="var(--primary)" /> FastAPI Authoritative Backend Endpoint URL
                </label>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <input
                    type="text"
                    className="form-control"
                    value={desktopApiUrl}
                    onChange={e => setDesktopApiUrl(e.target.value)}
                    placeholder="http://localhost:8000/api/v1"
                    style={{ fontFamily: 'monospace', flex: 1 }}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={async () => {
                      setIsCheckingConn(true);
                      const res = await api.checkHealth(desktopApiUrl);
                      setConnectionCheck(res);
                      setIsCheckingConn(false);
                    }}
                    disabled={isCheckingConn}
                  >
                    <RefreshCw size={14} className={isCheckingConn ? 'spin' : ''} /> Test Endpoint
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      api.setBaseUrl(desktopApiUrl);
                      setSaveSuccess('API endpoint URL saved and updated dynamically.');
                    }}
                  >
                    Apply URL
                  </button>
                </div>

                {connectionCheck && (
                  <div style={{
                    marginTop: '10px',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    backgroundColor: connectionCheck.ok ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    border: `1px solid ${connectionCheck.ok ? '#10b981' : '#ef4444'}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    fontSize: '12px'
                  }}>
                    <span style={{ color: connectionCheck.ok ? '#10b981' : '#ef4444', fontWeight: 600 }}>
                      {connectionCheck.ok ? `● Backend Connected (${connectionCheck.latencyMs}ms latency)` : `✕ Connection Failed: ${connectionCheck.message}`}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>Target: {desktopApiUrl}</span>
                  </div>
                )}
              </div>

              {/* Hardware Information & Invariants */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <Barcode size={18} color="var(--primary)" />
                    <strong style={{ fontSize: '14px' }}>USB HID Barcode Scanner</strong>
                  </div>
                  <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
                    Standard USB HID keyboard wedge barcode scanners are automatically captured globally via high-speed keystroke burst buffering (&lt;50ms) without requiring vendor-specific drivers.
                  </p>
                </div>

                <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <Printer size={18} color="var(--primary)" />
                    <strong style={{ fontSize: '14px' }}>Windows Native Spooler & PDF</strong>
                  </div>
                  <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
                    Documents and labels are rendered directly through the unified ReportLab vector PDF engine and dispatched to native Windows print spoolers or browser print previews.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </form>
    </div>
  );
};
