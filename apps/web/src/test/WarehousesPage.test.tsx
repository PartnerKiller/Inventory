import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WarehousesPage } from '../pages/WarehousesPage';
import { api } from '../api/client';
import { Warehouse, LocationBin } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getWarehouses: vi.fn(),
    createWarehouse: vi.fn(),
    updateWarehouse: vi.fn(),
    deleteWarehouse: vi.fn(),
    getWarehouseBins: vi.fn(),
    createBin: vi.fn(),
    updateBin: vi.fn(),
    deleteBin: vi.fn(),
  },
}));

const mockWarehouses: Warehouse[] = [
  {
    id: 'wh-1',
    code: 'WH-ATX-01',
    name: 'Austin Central Distribution Hub',
    address: { street: '4200 Logistics Pkwy', city: 'Austin', state: 'TX', postalCode: '78744' },
    isActive: true,
    totalBins: 3,
    total_stock_on_hand: 120,
    bins: [
      { id: 'bin-1', warehouse_id: 'wh-1', code: 'WH-ATX-RCV-01', aisle: 'R', rack: '01', shelf: '01', bin: '01', type: 'RECEIVING', is_active: true, created_at: '' },
      { id: 'bin-2', warehouse_id: 'wh-1', code: 'WH-ATX-A01-01', aisle: 'A', rack: '01', shelf: '01', bin: '01', type: 'STORAGE', is_active: true, created_at: '' },
    ]
  },
  {
    id: 'wh-2',
    code: 'WH-DFW-02',
    name: 'Dallas Regional Fulfillment',
    address: { street: '100 Airport Rd', city: 'Dallas', state: 'TX', postalCode: '75261' },
    isActive: true,
    totalBins: 2,
    total_stock_on_hand: 45,
    bins: []
  }
];

describe('WarehousesPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
    (api.getWarehouseBins as any).mockResolvedValue(mockWarehouses[0].bins || []);
  });

  it('renders warehouses list with facility cards and total stock', async () => {
    render(<WarehousesPage />);

    expect(screen.getByText(/Warehouses & Location Bins/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('WH-ATX-01')).toBeInTheDocument();
      expect(screen.getByText('Austin Central Distribution Hub')).toBeInTheDocument();
      expect(screen.getByText('Dallas Regional Fulfillment')).toBeInTheDocument();
      expect(screen.getByText('120 units')).toBeInTheDocument();
    });
  });

  it('opens and closes the Register New Warehouse modal', async () => {
    render(<WarehousesPage />);

    const newBtn = screen.getByRole('button', { name: /New Warehouse/i });
    fireEvent.click(newBtn);

    expect(screen.getByText('Register New Warehouse Facility')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. WH-CHI-01')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Register New Warehouse Facility')).not.toBeInTheDocument();
    });
  });

  it('opens the location bins drawer for a warehouse', async () => {
    render(<WarehousesPage />);

    await waitFor(() => {
      expect(screen.getByText('WH-ATX-01')).toBeInTheDocument();
    });

    const manageBinsBtns = screen.getAllByRole('button', { name: /Manage Bins/i });
    fireEvent.click(manageBinsBtns[0]);

    await waitFor(() => {
      expect(screen.getByText(/Location Bins: Austin Central Distribution Hub/i)).toBeInTheDocument();
      expect(screen.getByText('WH-ATX-RCV-01')).toBeInTheDocument();
    });
  });
});
