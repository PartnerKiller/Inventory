import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InventoryCatalogPage } from '../pages/InventoryCatalogPage';
import { api } from '../api/client';
import { Item, ItemCategory } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getItems: vi.fn(),
    getCategories: vi.fn(),
    createItem: vi.fn(),
    updateItem: vi.fn(),
    deleteItem: vi.fn(),
    getItemDetail: vi.fn(),
    createCategory: vi.fn(),
    deleteCategory: vi.fn(),
  },
}));

const mockCategories: ItemCategory[] = [
  { id: 'cat-1', code: 'ELEC', name: 'Electronics', itemCount: 10 },
  { id: 'cat-2', code: 'MECH', name: 'Mechanical Parts', itemCount: 5 },
];

const mockItems: Item[] = [
  {
    id: 'item-1',
    sku: 'SKU-ELEC-001',
    name: 'Microcontroller Board V2',
    description: 'High-speed 32-bit MCU board',
    categoryId: 'cat-1',
    categoryName: 'Electronics',
    baseUom: 'PCS',
    valuationMethod: 'FIFO',
    reorderPoint: 10,
    reorderQuantity: 50,
    totalStock: 85,
    isActive: true,
    variants: [
      {
        id: 'var-1',
        variantSku: 'SKU-ELEC-001-STD',
        variantName: 'Standard',
        costPrice: 12.5,
        sellingPrice: 25.0,
        attributes: {},
        barcodes: [{ id: 'b-1', barcodeValue: '89012345001', symbology: 'CODE128', isPrimary: true }],
      },
    ],
  },
  {
    id: 'item-2',
    sku: 'SKU-MECH-002',
    name: 'Precision Ball Bearing',
    description: 'Stainless steel sealed bearing',
    categoryId: 'cat-2',
    categoryName: 'Mechanical Parts',
    baseUom: 'PCS',
    valuationMethod: 'FIFO',
    reorderPoint: 20,
    reorderQuantity: 100,
    totalStock: 5, // low stock
    isActive: true,
    variants: [
      {
        id: 'var-2',
        variantSku: 'SKU-MECH-002-STD',
        variantName: 'Standard',
        costPrice: 4.0,
        sellingPrice: 9.5,
        attributes: {},
        barcodes: [],
      },
    ],
  },
];

describe('InventoryCatalogPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getCategories as any).mockResolvedValue(mockCategories);
    (api.getItems as any).mockResolvedValue({
      items: mockItems,
      pagination: { page: 1, page_size: 10, total_items: 2, total_pages: 1, has_next: false, has_prev: false },
    });
  });

  it('renders product catalog list with products, categories, and low-stock indicators', async () => {
    render(<InventoryCatalogPage />);

    expect(screen.getByText(/Product Master & Item Registry/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('SKU-ELEC-001')).toBeInTheDocument();
      expect(screen.getByText('Microcontroller Board V2')).toBeInTheDocument();
      expect(screen.getByText('Precision Ball Bearing')).toBeInTheDocument();
      expect(screen.getByText('Low')).toBeInTheDocument(); // Low stock badge for item-2
    });
  });

  it('triggers search with query term on search input submit', async () => {
    render(<InventoryCatalogPage />);

    await waitFor(() => {
      expect(screen.getByText('SKU-ELEC-001')).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/Search SKU, name, or scan barcode/i);
    fireEvent.change(searchInput, { target: { value: 'Microcontroller' } });
    fireEvent.submit(searchInput.closest('form')!);

    await waitFor(() => {
      expect(api.getItems).toHaveBeenCalledWith(expect.objectContaining({ q: 'Microcontroller' }));
    });
  });

  it('opens and closes the Create New Master Product modal', async () => {
    render(<InventoryCatalogPage />);

    const newProductBtn = screen.getByRole('button', { name: /New Product/i });
    fireEvent.click(newProductBtn);

    expect(screen.getByText('Create New Master Product')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. SKU-SEN-100')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Create New Master Product')).not.toBeInTheDocument();
    });
  });

  it('displays error banner when fetching catalog fails', async () => {
    (api.getItems as any).mockRejectedValueOnce(new Error('Database network timeout'));
    render(<InventoryCatalogPage />);

    await waitFor(() => {
      expect(screen.getByText(/Database network timeout/i)).toBeInTheDocument();
    });
  });
});
