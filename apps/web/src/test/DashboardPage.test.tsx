import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DashboardPage } from '../pages/DashboardPage';
import { ReportsPage } from '../pages/ReportsPage';
import { api } from '../api/client';
import { DashboardMetrics, InventoryReportResponse, Warehouse } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getDashboardMetrics: vi.fn(),
    getWarehouses: vi.fn(),
    getSuppliers: vi.fn(),
    getCustomers: vi.fn(),
    getInventoryReport: vi.fn(),
    getPurchasingReport: vi.fn(),
    getSalesReport: vi.fn(),
    getValuationReport: vi.fn(),
    globalSearch: vi.fn(),
  },
}));

const mockMetrics: DashboardMetrics = {
  total_items: 24,
  total_warehouses: 2,
  total_on_hand_units: 500,
  total_allocated_units: 120,
  total_available_units: 380,
  low_stock_count: 2,
  out_of_stock_count: 0,
  pending_pos: 3,
  pending_sos: 5,
  orders_awaiting_picking: 2,
  orders_awaiting_packing: 1,
  orders_awaiting_dispatch: 2,
  total_valuation: 45200.0,
  recent_transactions: [],
  recent_audit_logs: [],
  recent_sales_orders: [
    { id: 'so-1', so_number: 'SO-2026-0001', customer_name: 'Acme Corp', status: 'CONFIRMED', total_amount: 1500.0, ordered_at: '2026-08-18T10:00:00Z' }
  ],
  operational_alerts: [
    { level: 'WARNING', title: '2 Product(s) Below Reorder Point', message: 'Reorder safety threshold breached', count: 2, link_tab: 'inventory' }
  ]
};

const mockWarehouses: Warehouse[] = [
  { id: 'wh-1', code: 'WH-ATX-01', name: 'Austin Central Hub', isActive: true, bins: [] }
];

describe('Operational Dashboard & Reporting Components', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getDashboardMetrics as any).mockResolvedValue(mockMetrics);
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
    (api.getSuppliers as any).mockResolvedValue([]);
    (api.getCustomers as any).mockResolvedValue([]);
    (api.getInventoryReport as any).mockResolvedValue({
      total_items_reported: 1,
      total_on_hand: 500,
      total_allocated: 120,
      total_available: 380,
      items: [
        {
          item_id: 'itm-1',
          variant_id: 'var-1',
          sku: 'SKU-MCU-800',
          item_name: 'ARM Cortex M4 MCU',
          variant_name: 'SMD',
          warehouse_code: 'WH-ATX-01',
          warehouse_name: 'Austin Central Hub',
          bin_code: 'WH-ATX-A01-01',
          quantity_on_hand: 500,
          quantity_allocated: 120,
          quantity_available: 380,
          reorder_point: 100,
          status: 'IN_STOCK'
        }
      ]
    });
    (api.getValuationReport as any).mockResolvedValue({
      total_inventory_value: 45200.0,
      currency: 'USD',
      items: []
    });
  });

  it('renders Dashboard with operational KPIs and alerts', async () => {
    const onNavigate = vi.fn();
    render(<DashboardPage onNavigate={onNavigate} />);

    await waitFor(() => {
      expect(screen.getByText(/Operational Command Center/i)).toBeInTheDocument();
      expect(screen.getByText('500')).toBeInTheDocument(); // On-Hand Units
      expect(screen.getByText('120')).toBeInTheDocument(); // Allocated Units
      expect(screen.getByText('380')).toBeInTheDocument(); // Available Units
      expect(screen.getByText(/2 Product\(s\) Below Reorder Point/i)).toBeInTheDocument();
      expect(screen.getByText('SO-2026-0001')).toBeInTheDocument();
    });
  });

  it('renders ReportsPage and switches between inventory and valuation tabs', async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Operational Reporting & Intelligence/i)).toBeInTheDocument();
      expect(screen.getByText('SKU-MCU-800')).toBeInTheDocument();
      expect(screen.getByText('ARM Cortex M4 MCU (SMD)')).toBeInTheDocument();
      expect(screen.getByText('WH-ATX-A01-01')).toBeInTheDocument();
    });

    const valuationTabBtn = screen.getByRole('button', { name: /Operational Valuation/i });
    fireEvent.click(valuationTabBtn);

    await waitFor(() => {
      expect(api.getValuationReport).toHaveBeenCalled();
    });
  });
});
