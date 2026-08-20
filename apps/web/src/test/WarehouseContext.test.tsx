import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WarehouseProvider, useWarehouse } from '../context/WarehouseContext';
import { api } from '../api/client';
import { Warehouse } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getWarehouses: vi.fn(),
  },
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: 'u-1', email: 'test@aurastock.local' },
  }),
}));

const mockWarehouses: Warehouse[] = [
  { id: 'wh-main', code: 'WH-MAIN', name: 'Main Distribution Center', isActive: true },
  { id: 'wh-east', code: 'WH-EAST', name: 'East Coast Hub', isActive: true },
];

const TestConsumer: React.FC = () => {
  const { warehouses, activeWarehouseId, activeWarehouse, setActiveWarehouseId, refreshWarehouses } = useWarehouse();
  return (
    <div>
      <div data-testid="active-id">{activeWarehouseId || 'ALL'}</div>
      <div data-testid="active-name">{activeWarehouse?.name || 'All Warehouses'}</div>
      <div data-testid="warehouse-count">{warehouses.length}</div>
      <button onClick={() => setActiveWarehouseId('wh-east')}>Select East</button>
      <button onClick={() => setActiveWarehouseId('')}>Select All</button>
      <button onClick={() => refreshWarehouses()}>Refresh</button>
    </div>
  );
};

describe('Phase 1: Canonical WarehouseContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
  });

  it('loads warehouses on mount and provides active warehouse state', async () => {
    render(
      <WarehouseProvider>
        <TestConsumer />
      </WarehouseProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('warehouse-count')).toHaveTextContent('2');
    });

    expect(screen.getByTestId('active-id')).toHaveTextContent('ALL');
    expect(screen.getByTestId('active-name')).toHaveTextContent('All Warehouses');
  });

  it('updates active warehouse and synchronizes with localStorage', async () => {
    render(
      <WarehouseProvider>
        <TestConsumer />
      </WarehouseProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('warehouse-count')).toHaveTextContent('2');
    });

    const selectEastBtn = screen.getByText('Select East');
    fireEvent.click(selectEastBtn);

    expect(screen.getByTestId('active-id')).toHaveTextContent('wh-east');
    expect(screen.getByTestId('active-name')).toHaveTextContent('East Coast Hub');
    expect(localStorage.getItem('aurastock_active_warehouse')).toBe('wh-east');

    const selectAllBtn = screen.getByText('Select All');
    fireEvent.click(selectAllBtn);

    expect(screen.getByTestId('active-id')).toHaveTextContent('ALL');
    expect(screen.getByTestId('active-name')).toHaveTextContent('All Warehouses');
    expect(localStorage.getItem('aurastock_active_warehouse')).toBeNull();
  });

  it('provides safe fallback defaults when rendered outside of WarehouseProvider', () => {
    render(<TestConsumer />);
    expect(screen.getByTestId('active-id')).toHaveTextContent('ALL');
    expect(screen.getByTestId('warehouse-count')).toHaveTextContent('0');
  });
});
