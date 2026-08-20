import React from 'react';
import {
  LayoutDashboard,
  Boxes,
  Layers,
  Warehouse,
  ShoppingCart,
  TrendingUp,
  Barcode,
  BarChart3,
  History,
  Users,
  Settings,
  LogOut,
  ShieldCheck,
  Activity
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export type NavPage =
  | 'dashboard'
  | 'items'
  | 'ledger'
  | 'warehouses'
  | 'purchasing'
  | 'sales'
  | 'barcodes'
  | 'reports'
  | 'audit'
  | 'users'
  | 'settings'
  | 'operations';

interface SidebarProps {
  currentPage: NavPage;
  onNavigate: (page: NavPage) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentPage, onNavigate }) => {
  const { user, logout, hasPermission } = useAuth();

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, perm: 'reports:view' },
    { id: 'items', label: 'Item Catalog & Stock', icon: Boxes, perm: 'inventory:read' },
    { id: 'ledger', label: 'Stock Ledger Journal', icon: Layers, perm: 'ledger:read' },
    { id: 'warehouses', label: 'Warehouses & Bins', icon: Warehouse, perm: 'warehouses:read' },
    { id: 'purchasing', label: 'Procurement (POs)', icon: ShoppingCart, perm: 'purchasing:read' },
    { id: 'sales', label: 'Sales & Fulfillment', icon: TrendingUp, perm: 'sales:read' },
    { id: 'barcodes', label: 'Barcode Station', icon: Barcode, perm: 'inventory:read' },
    { id: 'reports', label: 'Valuation & Analytics', icon: BarChart3, perm: 'reports:view' },
    { id: 'audit', label: 'Compliance Audit Log', icon: History, perm: 'audit:read' },
    { id: 'users', label: 'Users & RBAC Roles', icon: Users, perm: 'users:read' },
    { id: 'settings', label: 'System Settings', icon: Settings, perm: 'settings:read' },
    { id: 'operations', label: 'Operations & Reliability', icon: Activity, perm: 'system:read' },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo-icon">A</div>
        <div>
          <div className="sidebar-brand-name">AuraStock</div>
          <div className="sidebar-brand-sub">Enterprise Inventory</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section-title">Core Operations</div>
        {navItems.slice(0, 6).map((item) => (
          <div
            key={item.id}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id as NavPage)}
          >
            <item.icon size={18} />
            <span className="nav-text">{item.label}</span>
          </div>
        ))}

        <div className="nav-section-title">Intelligence & Tools</div>
        {navItems.slice(6).map((item) => (
          <div
            key={item.id}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id as NavPage)}
          >
            <item.icon size={18} />
            <span className="nav-text">{item.label}</span>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            backgroundColor: '#1e293b',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '13px',
            fontWeight: 700,
            color: '#60a5fa'
          }}>
            {(user?.fullName || (user as any)?.full_name || user?.email || 'U').charAt(0).toUpperCase()}
          </div>
          <div style={{ overflow: 'hidden' }}>
            <div style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {user?.fullName || (user as any)?.full_name || user?.email || 'User'}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {user?.roles?.[0] || (user as any)?.role || 'Member'}
            </div>
          </div>
        </div>

        <button
          className="btn btn-outline btn-sm"
          title="Sign out"
          onClick={logout}
          style={{ padding: '6px' }}
        >
          <LogOut size={15} />
        </button>
      </div>
    </aside>
  );
};
