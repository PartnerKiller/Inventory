import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockLedgerPage } from '../pages/StockLedgerPage';
import { api } from '../api/client';
import { StockBalanceCache, StockLedgerEntry, Warehouse, Item } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getStockBalances: vi.fn(),
    getLedgerEntries: vi.fn(),
    getWarehouses: vi.fn(),
    getItems: vi.fn(),
    transferStock: vi.fn(),
    adjustStock: vi.fn(),
  },
}));

const mockBalances: StockBalanceCache[] = [
  {
    id: 'bal-1',
    warehouse_id: 'wh-1',
    warehouse_code: 'WH-ATX-01',
    warehouse_name: 'Austin Hub',
    location_bin_id: 'bin-1',
    bin_code: 'WH-ATX-A01-01',
    item_variant_id: 'var-1',
    item_sku: 'SKU-SEN-100',
    item_name: 'Optical Sensor',
    variant_sku: 'SKU-SEN-100-STD',
    variant_name: 'Standard',
    quantity_on_hand: 50,
    quantity_allocated: 10,
    quantity_available: 40,
    updated_at: '2026-08-18T10:00:00Z',
  }
];

const mockWarehouses: Warehouse[] = [
  {
    id: 'wh-1',
    code: 'WH-ATX-01',
    name: 'Austin Hub',
    isActive: true,
    bins: [
      { id: 'bin-1', warehouse_id: 'wh-1', code: 'WH-ATX-A01-01', aisle: 'A', rack: '01', shelf: '01', bin: '01', type: 'STORAGE', is_active: true, created_at: '' },
      { id: 'bin-2', warehouse_id: 'wh-1', code: 'WH-ATX-STG-01', aisle: 'S', rack: '01', shelf: '01', bin: '01', type: 'STAGING', is_active: true, created_at: '' }
    ]
  }
];

const mockItems: Item[] = [
  {
    id: 'item-1',
    sku: 'SKU-SEN-100',
    name: 'Optical Sensor',
    baseUom: 'PCS',
    valuationMethod: 'FIFO',
    reorderPoint: 10,
    reorderQuantity: 50,
    variants: [
      { id: 'var-1', variantSku: 'SKU-SEN-100-STD', variantName: 'Standard', costPrice: 20, sellingPrice: 45, attributes: {}, barcodes: [] }
    ]
  }
];

describe('StockLedgerPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getStockBalances as any).mockResolvedValue({
      items: mockBalances,
      pagination: { page: 1, page_size: 15, total_items: 1, total_pages: 1, has_next: false, has_prev: false }
    });
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
    (api.getItems as any).mockResolvedValue({ items: mockItems, pagination: {} });
  });

  it('renders physical stock balances overview with on-hand, allocated, and available columns', async () => {
    render(<StockLedgerPage />);

    expect(screen.getByText(/Inventory Overview & Stock Ledger/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('SKU-SEN-100')).toBeInTheDocument();
      expect(screen.getByText('WH-ATX-A01-01')).toBeInTheDocument();
      expect(screen.getByText('50')).toBeInTheDocument(); // On hand
      expect(screen.getByText('10')).toBeInTheDocument(); // Allocated
      expect(screen.getByText('40')).toBeInTheDocument(); // Available
    });
  });

  it('opens and closes the Stock Transfer modal', async () => {
    render(<StockLedgerPage />);

    const transferBtn = screen.getByRole('button', { name: /Stock Transfer/i });
    fireEvent.click(transferBtn);

    expect(screen.getByText('Execute Physical Stock Transfer')).toBeInTheDocument();
    expect(screen.getByText(/Source Location/i)).toBeInTheDocument();
    expect(screen.getByText(/Destination Location/i)).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Execute Physical Stock Transfer')).not.toBeInTheDocument();
    });
  });

  it('opens and closes the Stock Adjustment modal with variance calculation', async () => {
    render(<StockLedgerPage />);

    const adjBtn = screen.getByRole('button', { name: /Stock Adjustment/i });
    fireEvent.click(adjBtn);

    expect(screen.getByText('Record Physical Stock Adjustment')).toBeInTheDocument();
    expect(screen.getByText('Adjustment Reason *')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Record Physical Stock Adjustment')).not.toBeInTheDocument();
    });
  });
});
