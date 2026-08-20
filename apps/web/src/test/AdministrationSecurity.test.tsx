import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { UsersRolesPage } from '../pages/UsersRolesPage';
import { SettingsPage } from '../pages/SettingsPage';
import { AuditLogPage } from '../pages/AuditLogPage';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getUsers: vi.fn(),
    getRoles: vi.fn(),
    getPermissions: vi.fn(),
    getWarehouses: vi.fn(),
    getMySessions: vi.fn(),
    getUserSessions: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    activateUser: vi.fn(),
    deactivateUser: vi.fn(),
    resetUserPassword: vi.fn(),
    revokeMySession: vi.fn(),
    revokeOtherSessions: vi.fn(),
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    getAuditLogs: vi.fn(),
    getAuditLogDetail: vi.fn(),
    getBaseUrl: vi.fn(() => '/api/v1'),
    setBaseUrl: vi.fn(),
    checkHealth: vi.fn().mockResolvedValue({ ok: true, status: 'ONLINE', latencyMs: 5 }),
  },
}));

describe('Phase 3A: Administration, Security & System Configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    (api.getUsers as any).mockResolvedValue([
      {
        id: 'usr-1',
        email: 'sarah.admin@inventory.local',
        fullName: 'Sarah Admin',
        isActive: true,
        isSuperuser: true,
        roles: ['SUPER_ADMIN'],
        warehouseScopes: [],
        createdAt: '2026-01-01T00:00:00Z',
      },
      {
        id: 'usr-2',
        email: 'john.clerk@inventory.local',
        fullName: 'John Clerk',
        isActive: true,
        isSuperuser: false,
        roles: ['INVENTORY_CLERK'],
        warehouseScopes: ['wh-1'],
        createdAt: '2026-01-02T00:00:00Z',
      }
    ]);

    (api.getRoles as any).mockResolvedValue([
      {
        id: 'role-1',
        name: 'SUPER_ADMIN',
        description: 'Full platform access',
        is_system: true,
        permissions: ['*']
      },
      {
        id: 'role-2',
        name: 'INVENTORY_CLERK',
        description: 'Performs stock movements',
        is_system: true,
        permissions: ['inventory:read', 'inventory:adjust', 'ledger:read']
      }
    ]);

    (api.getPermissions as any).mockResolvedValue([
      { id: 'p1', code: 'users:read', module: 'Users', description: 'Read user accounts' },
      { id: 'p2', code: 'users:write', module: 'Users', description: 'Modify user accounts' },
      { id: 'p3', code: 'inventory:read', module: 'Inventory', description: 'View items' },
      { id: 'p4', code: 'settings:write', module: 'Settings', description: 'Change settings' },
    ]);

    (api.getWarehouses as any).mockResolvedValue([
      {
        id: 'wh-1',
        code: 'WH-ATX-01',
        name: 'Austin Fulfillment Center',
        bins: [
          { id: 'bin-1', code: 'RCV-01', name: 'Receiving Dock', type: 'RECEIVING' },
          { id: 'bin-2', code: 'DMG-01', name: 'Quarantine Area', type: 'DAMAGE' }
        ]
      }
    ]);

    (api.getMySessions as any).mockResolvedValue([
      {
        id: 'sess-1',
        user_id: 'usr-1',
        device_info: 'Chrome 120 (Desktop)',
        created_at: '2026-08-18T10:00:00Z',
        expires_at: '2026-08-25T10:00:00Z'
      }
    ]);

    (api.getSettings as any).mockResolvedValue({
      company_name: 'AuraStock Enterprise',
      company_email: 'admin@aurastock.local',
      currency: 'USD',
      timezone: 'UTC',
      date_format: 'YYYY-MM-DD',
      default_warehouse_id: 'wh-1',
      allow_negative_stock: false,
      auto_allocate_on_confirm: false,
      require_grn_inspection: false,
      default_payment_terms: 'NET_30',
      default_tax_pct: 0.0,
      require_po_approval: true,
      po_approval_threshold: 1000.0,
    });

    (api.getAuditLogs as any).mockResolvedValue({
      items: [
        {
          id: 'log-1',
          tenant_id: 'ten-1',
          user_name: 'Sarah Admin',
          user_email: 'sarah.admin@inventory.local',
          action: 'POST_LEDGER',
          entity_type: 'StockLedgerTransaction',
          entity_id: 'tx-001',
          client_type: 'WEB',
          changes: { transaction_type: 'PURCHASE_RECEIPT' },
          timestamp: '2026-08-18T12:00:00Z'
        }
      ],
      pagination: { page: 1, pageSize: 25, totalPages: 1, totalItems: 1 }
    });
  });

  it('renders UsersRolesPage and lists team members and security roles', async () => {
    render(<UsersRolesPage />);

    await waitFor(() => {
      expect(screen.getByText(/User Administration & Security Governance/i)).toBeInTheDocument();
      expect(screen.getByText('sarah.admin@inventory.local')).toBeInTheDocument();
      expect(screen.getByText('john.clerk@inventory.local')).toBeInTheDocument();
    });

    // Switch to Permission Matrix tab
    const matrixTab = screen.getByRole('button', { name: /Permission Matrix/i });
    fireEvent.click(matrixTab);

    await waitFor(() => {
      expect(screen.getByText(/Enterprise Role-Permission Capability Matrix/i)).toBeInTheDocument();
      expect(screen.getByText('users:read')).toBeInTheDocument();
      expect(screen.getByText('settings:write')).toBeInTheDocument();
    });
  });

  it('opens Provision Team Member modal and calls createUser API', async () => {
    (api.createUser as any).mockResolvedValue({
      id: 'usr-3',
      email: 'new.member@inventory.local',
      fullName: 'New Member',
      roles: ['INVENTORY_CLERK'],
      warehouseScopes: [],
      createdAt: '2026-08-18T14:00:00Z'
    });

    render(<UsersRolesPage />);

    await waitFor(() => {
      expect(screen.getByText('sarah.admin@inventory.local')).toBeInTheDocument();
    });

    const provisionBtn = screen.getByRole('button', { name: /Provision Team Member/i });
    fireEvent.click(provisionBtn);

    expect(screen.getByText('Provision New Team Member')).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText(/e\.g\. Rachel Adams/i);
    const emailInput = screen.getByPlaceholderText(/rachel@inventory\.local/i);

    fireEvent.change(nameInput, { target: { value: 'New Member' } });
    fireEvent.change(emailInput, { target: { value: 'new.member@inventory.local' } });

    const submitBtn = screen.getByRole('button', { name: 'Provision User' });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.createUser).toHaveBeenCalledWith(expect.objectContaining({
        email: 'new.member@inventory.local',
        full_name: 'New Member',
      }));
    });
  });

  it('renders SettingsPage and saves updated company configuration', async () => {
    (api.updateSettings as any).mockResolvedValue({
      company_name: 'AuraStock Global Logistics',
      company_email: 'ops@aurastock-global.com',
      currency: 'USD',
      timezone: 'America/New_York',
      date_format: 'YYYY-MM-DD',
      allow_negative_stock: false,
      auto_allocate_on_confirm: true,
      require_grn_inspection: false,
      default_payment_terms: 'NET_60',
      default_tax_pct: 5.0,
      require_po_approval: true,
      po_approval_threshold: 2000.0,
    });

    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText(/System Settings & Enterprise Configuration/i)).toBeInTheDocument();
      expect(screen.getByDisplayValue('AuraStock Enterprise')).toBeInTheDocument();
    });

    const nameInput = screen.getByDisplayValue('AuraStock Enterprise');
    fireEvent.change(nameInput, { target: { value: 'AuraStock Global Logistics' } });

    const saveBtn = screen.getByRole('button', { name: /Save Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.updateSettings).toHaveBeenCalledWith(expect.objectContaining({
        company_name: 'AuraStock Global Logistics',
      }));
    });
  });

  it('renders AuditLogPage with cryptographic log records and filters', async () => {
    render(<AuditLogPage />);

    await waitFor(() => {
      expect(screen.getByText(/Enterprise Compliance & System Audit Trail/i)).toBeInTheDocument();
      expect(screen.getByText('StockLedgerTransaction')).toBeInTheDocument();
      expect(screen.getByText('sarah.admin@inventory.local')).toBeInTheDocument();
    });

    const diffBtn = screen.getByRole('button', { name: /View Changes Diff/i });
    fireEvent.click(diffBtn);

    await waitFor(() => {
      expect(screen.getByText(/Audit Mutation Payload & State Diff/i)).toBeInTheDocument();
    });
  });
});
