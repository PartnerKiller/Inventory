import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SalesOrdersPage } from '../pages/SalesOrdersPage';
import { api } from '../api/client';
import { SalesOrder, Customer, Warehouse, Item } from '@inventory/shared-types';

vi.mock('../api/client', () => ({
  api: {
    getSalesOrders: vi.fn(),
    getSalesOrderDetail: vi.fn(),
    createSalesOrder: vi.fn(),
    updateSalesOrder: vi.fn(),
    confirmSalesOrder: vi.fn(),
    allocateSalesOrder: vi.fn(),
    pickSalesOrderItems: vi.fn(),
    packSalesOrder: vi.fn(),
    dispatchSalesOrder: vi.fn(),
    cancelSalesOrder: vi.fn(),
    deleteSalesOrder: vi.fn(),
    processSalesReturn: vi.fn(),
    getCustomers: vi.fn(),
    createCustomer: vi.fn(),
    updateCustomer: vi.fn(),
    deleteCustomer: vi.fn(),
    getWarehouses: vi.fn(),
    getItems: vi.fn(),
  },
}));

const mockCustomers: Customer[] = [
  {
    id: 'cust-1',
    code: 'CUST-ACME-01',
    name: 'Acme Industrial Automation',
    email: 'procurement@acme.com',
    phone: '+1-555-8822',
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

const mockOrders: SalesOrder[] = [
  {
    id: 'so-1',
    so_number: 'SO-20260818-0001',
    customer_id: 'cust-1',
    customer_name: 'Acme Industrial Automation',
    customer_code: 'CUST-ACME-01',
    warehouse_id: 'wh-1',
    warehouse_name: 'Austin Central Hub',
    warehouse_code: 'WH-ATX-01',
    status: 'CONFIRMED',
    subtotal_amount: 600.0,
    discount_amount: 0.0,
    tax_amount: 0.0,
    total_amount: 600.0,
    ordered_at: '2026-08-18T10:00:00Z',
    lines: [
      {
        id: 'line-1',
        sales_order_id: 'so-1',
        item_variant_id: 'var-1',
        item_sku: 'SKU-MCU-800',
        item_name: 'ARM Cortex M4 MCU',
        variant_sku: 'SKU-MCU-800-SMD',
        quantity_ordered: 50,
        quantity_allocated: 0,
        quantity_picked: 0,
        quantity_shipped: 0,
        unit_price: 12.0,
        discount_pct: 0,
        tax_pct: 0,
        line_total: 600.0
      }
    ]
  }
];

describe('SalesOrdersPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getSalesOrders as any).mockResolvedValue({
      items: mockOrders,
      pagination: { page: 1, page_size: 15, total_items: 1, total_pages: 1, has_next: false, has_prev: false }
    });
    (api.getCustomers as any).mockResolvedValue(mockCustomers);
    (api.getWarehouses as any).mockResolvedValue(mockWarehouses);
    (api.getItems as any).mockResolvedValue({ items: mockItems, pagination: {} });
  });

  it('renders sales orders list with status badge and table rows', async () => {
    render(<SalesOrdersPage />);

    expect(screen.getByText(/Sales & Order Fulfillment/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('SO-20260818-0001')).toBeInTheDocument();
      expect(screen.getAllByText('Acme Industrial Automation').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('WH-ATX-01').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('CONFIRMED')).toBeInTheDocument();
    });
  });

  it('opens and closes the Create New Sales Order modal', async () => {
    render(<SalesOrdersPage />);

    const newSoBtn = screen.getByRole('button', { name: /New Sales Order/i });
    fireEvent.click(newSoBtn);

    expect(screen.getByText('Create New Sales Order')).toBeInTheDocument();
    expect(screen.getByText('Customer / Client *')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText('Create New Sales Order')).not.toBeInTheDocument();
    });
  });

  it('allocates confirmed sales order', async () => {
    (api.allocateSalesOrder as any).mockResolvedValue({
      ...mockOrders[0],
      status: 'ALLOCATED',
      lines: [{ ...mockOrders[0].lines[0], quantity_allocated: 50 }]
    });

    render(<SalesOrdersPage />);

    await waitFor(() => {
      expect(screen.getByText('SO-20260818-0001')).toBeInTheDocument();
    });

    const allocateBtn = screen.getByRole('button', { name: /Allocate/i });
    fireEvent.click(allocateBtn);

    await waitFor(() => {
      expect(api.allocateSalesOrder).toHaveBeenCalledWith('so-1');
    });
  });

  it('switches to Customer Directory tab and renders customer cards', async () => {
    render(<SalesOrdersPage />);

    const customerTabBtn = screen.getByRole('button', { name: /Customer Directory/i });
    fireEvent.click(customerTabBtn);

    await waitFor(() => {
      expect(screen.getByText('CUST-ACME-01')).toBeInTheDocument();
      expect(screen.getAllByText('Acme Industrial Automation').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/procurement@acme.com/i)).toBeInTheDocument();
    });
  });
});
