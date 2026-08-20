import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PurchasingPage } from '../pages/PurchasingPage';
import { api } from '../api/client';
import { PurchaseOrder, Supplier, Warehouse, Item } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getPurchaseOrders: vi.fn(),
    getPurchaseOrderDetail: vi.fn(),
    createPurchaseOrder: vi.fn(),
    updatePurchaseOrder: vi.fn(),
    submitPurchaseOrder: vi.fn(),
    approvePurchaseOrder: vi.fn(),
    cancelPurchaseOrder: vi.fn(),
    deletePurchaseOrder: vi.fn(),
    receiveGoods: vi.fn(),
    getSuppliers: vi.fn(),
    createSupplier: vi.fn(),
    updateSupplier: vi.fn(),
    deleteSupplier: vi.fn(),
    getWarehouses: vi.fn(),
    getItems: vi.fn(),
  },
}));

const mockSuppliers: Supplier[] = [
  {
    id: 'sup-1',
    code: 'SUP-APEX-01',
    name: 'Apex Micro Electronics Ltd',
    email: 'sales@apexmicro.com',
    phone: '+1-555-0199',
    payment_terms: 'Net 30',
    currency: 'USD',
    is_active: true,
    active_orders_count: 1
  }
];

const mockWarehouses: Warehouse[] = [
  {
    id: 'wh-1',
    code: 'WH-ATX-01',
    name: 'Austin Central Hub',
    isActive: true,
    bins: [
      { id: 'bin-rcv', code: 'WH-ATX-RCV-01', aisle: 'R', rack: '01', shelf: '01', bin: '01', type: 'RECEIVING', is_active: true },
      { id: 'bin-stg', code: 'WH-ATX-A01-01', aisle: 'A', rack: '01', shelf: '01', bin: '01', type: 'STORAGE', is_active: true }
    ]
  }
];

const mockItems: Item[] = [
  {
    id: 'itm-1',
    sku: 'SKU-MCU-800',
    name: 'ARM Cortex M4 MCU',
    baseUom: 'PCS',
    valuationMethod: 'FIFO',
    reorderPoint: 100,
    reorderQuantity: 500,
    variants: [
      { id: 'var-1', variantSku: 'SKU-MCU-800-SMD', variantName: 'SMD Package', costPrice: 4.5, sellingPrice: 12.0, attributes: {}, barcodes: [] }
    ]
  }
];

const mockOrders: PurchaseOrder[] = [
  {
    id: 'po-1',
    po_number: 'PO-20260818-0001',
    supplier_id: 'sup-1',
    supplier_name: 'Apex Micro Electronics Ltd',
    target_warehouse_id: 'wh-1',
    target_warehouse_name: 'Austin Central Hub',
    target_warehouse_code: 'WH-ATX-01',
    status: 'APPROVED',
    subtotal_amount: 450.0,
    discount_amount: 0.0,
    tax_amount: 0.0,
    total_amount: 450.0,
    ordered_at: '2026-08-18T10:00:00Z',
    lines: [
      {
        id: 'line-1',
        purchase_order_id: 'po-1',
        item_variant_id: 'var-1',
        item_sku: 'SKU-MCU-800',
        item_name: 'ARM Cortex M4 MCU',
        variant_sku: 'SKU-MCU-800-SMD',
        quantity_ordered: 100,
        quantity_received: 40,
        quantity_remaining: 60,
        unit_price: 4.5,
        discount_pct: 0,
        tax_pct: 0,
        line_total: 450.0
      }
    ]
  }
];

describe('PurchasingPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getPurchaseOrders as any).mockResolvedValue({
      items: mockOrders,
      pagination: { page: 1, page_size: 15, total_items: 1, total_pages: 1, has_next: false, has_prev: false }
    });
    (api.getSuppliers as any).mockResolvedValue(mockSuppliers);
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
    (api.getItems as any).mockResolvedValue({ items: mockItems, pagination: {} });
  });

  it('renders purchase orders list with status badge and progress', async () => {
    render(<PurchasingPage />);

    expect(screen.getByText(/Purchasing & Goods Receipt/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('PO-20260818-0001')).toBeInTheDocument();
      expect(screen.getAllByText('Apex Micro Electronics Ltd').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('WH-ATX-01').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('APPROVED')).toBeInTheDocument();
    });
  });

  it('opens and closes the Initiate New Purchase Order modal', async () => {
    render(<PurchasingPage />);

    const newPoBtn = screen.getByRole('button', { name: /New Purchase Order/i });
    fireEvent.click(newPoBtn);

    expect(screen.getByText('Initiate New Purchase Order')).toBeInTheDocument();
    expect(screen.getByText('Vendor / Supplier *')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Initiate New Purchase Order')).not.toBeInTheDocument();
    });
  });

  it('opens Goods Receipt (GRN) modal for approved PO', async () => {
    render(<PurchasingPage />);

    await waitFor(() => {
      expect(screen.getByText('PO-20260818-0001')).toBeInTheDocument();
    });

    const grnBtn = screen.getByRole('button', { name: /GRN/i });
    fireEvent.click(grnBtn);

    expect(screen.getByText(/Receive Goods against PO: PO-20260818-0001/i)).toBeInTheDocument();
    expect(screen.getByText('Receiving Destination Bin *')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Receive All Remaining/i })).toBeInTheDocument();
  });

  it('switches to Supplier Directory tab and displays supplier cards', async () => {
    render(<PurchasingPage />);

    const supplierTabBtn = screen.getByRole('button', { name: /Supplier Directory/i });
    fireEvent.click(supplierTabBtn);

    await waitFor(() => {
      expect(screen.getByText('SUP-APEX-01')).toBeInTheDocument();
      expect(screen.getAllByText('Apex Micro Electronics Ltd').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/sales@apexmicro.com/i)).toBeInTheDocument();
    });
  });
});
