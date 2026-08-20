"""Initial enterprise schema with constraints and indexes

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-08-18 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('email', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('is_superuser', sa.Boolean(), default=False, nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Roles
    op.create_table(
        'roles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('is_system', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Permissions
    op.create_table(
        'permissions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('module', sa.String(50), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Warehouses
    op.create_table(
        'warehouses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('address', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_warehouse_code')
    )

    # Location Bins
    op.create_table(
        'location_bins',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('aisle', sa.String(20), nullable=False),
        sa.Column('rack', sa.String(20), nullable=False),
        sa.Column('shelf', sa.String(20), nullable=False),
        sa.Column('bin', sa.String(20), nullable=False),
        sa.Column('type', sa.String(30), default='STORAGE', nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('warehouse_id', 'code', name='uq_warehouse_bin_code')
    )

    # User Roles Association
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role_id', sa.String(36), sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=True)
    )

    # Role Permissions Association
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.String(36), sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission_id', sa.String(36), sa.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
    )

    # Refresh Token Sessions
    op.create_table(
        'refresh_token_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('token_hash', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('device_info', sa.String(255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('is_revoked', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Item Categories
    op.create_table(
        'item_categories',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('item_categories.id'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_category_code')
    )

    # Items
    op.create_table(
        'items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('category_id', sa.String(36), sa.ForeignKey('item_categories.id'), nullable=True, index=True),
        sa.Column('sku', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('base_uom', sa.String(20), default='PCS', nullable=False),
        sa.Column('valuation_method', sa.String(30), default='FIFO', nullable=False),
        sa.Column('reorder_point', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('reorder_quantity', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('is_batch_tracked', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_serial_tracked', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('tenant_id', 'sku', name='uq_tenant_item_sku')
    )

    # Item Variants
    op.create_table(
        'item_variants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), sa.ForeignKey('items.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('variant_sku', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('variant_name', sa.String(100), nullable=False),
        sa.Column('attributes', sa.JSON(), nullable=True),
        sa.Column('cost_price', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('selling_price', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Barcodes
    op.create_table(
        'barcodes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('barcode_value', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('symbology', sa.String(30), default='CODE128', nullable=False),
        sa.Column('is_primary', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Stock Batches
    op.create_table(
        'stock_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('batch_number', sa.String(100), index=True, nullable=False),
        sa.Column('manufacturing_date', sa.Date(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('cost_per_unit', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('item_variant_id', 'batch_number', name='uq_variant_batch'),
        sa.CheckConstraint('cost_per_unit >= 0', name='chk_batch_cost_non_negative')
    )

    # Stock Ledger Transactions
    op.create_table(
        'stock_ledger_transactions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('transaction_number', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('transaction_type', sa.String(50), nullable=False),
        sa.Column('reference_document_type', sa.String(50), nullable=True),
        sa.Column('reference_document_id', sa.String(36), nullable=True, index=True),
        sa.Column('posted_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )
    op.create_index('idx_tx_tenant_posted_at', 'stock_ledger_transactions', ['tenant_id', 'posted_at'])

    # Stock Ledger Entries
    op.create_table(
        'stock_ledger_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('transaction_id', sa.String(36), sa.ForeignKey('stock_ledger_transactions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id'), nullable=False, index=True),
        sa.Column('batch_id', sa.String(36), sa.ForeignKey('stock_batches.id'), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('source_location_bin_id', sa.String(36), sa.ForeignKey('location_bins.id'), nullable=True, index=True),
        sa.Column('destination_location_bin_id', sa.String(36), sa.ForeignKey('location_bins.id'), nullable=True, index=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=False),
        sa.Column('uom', sa.String(20), default='PCS', nullable=False),
        sa.Column('unit_cost', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('total_cost', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('entry_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.CheckConstraint('quantity > 0', name='chk_ledger_quantity_positive'),
        sa.CheckConstraint('unit_cost >= 0', name='chk_ledger_unit_cost_non_negative')
    )
    op.create_index('idx_ledger_variant_time', 'stock_ledger_entries', ['item_variant_id', 'entry_timestamp'])
    op.create_index('idx_ledger_tx_id', 'stock_ledger_entries', ['transaction_id'])

    # Stock Balance Cache
    op.create_table(
        'stock_balance_cache',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('location_bin_id', sa.String(36), sa.ForeignKey('location_bins.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('batch_id', sa.String(36), sa.ForeignKey('stock_batches.id'), nullable=True),
        sa.Column('quantity_on_hand', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('quantity_allocated', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('location_bin_id', 'item_variant_id', 'batch_id', name='uq_bin_variant_batch'),
        sa.CheckConstraint('quantity_on_hand >= 0', name='chk_stock_on_hand_non_negative'),
        sa.CheckConstraint('quantity_allocated >= 0', name='chk_stock_allocated_non_negative'),
        sa.CheckConstraint('quantity_on_hand >= quantity_allocated', name='chk_stock_available_non_negative')
    )
    op.create_index('idx_stock_balance_lookup', 'stock_balance_cache', ['warehouse_id', 'item_variant_id'])

    # Suppliers
    op.create_table(
        'suppliers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address', sa.JSON(), nullable=True),
        sa.Column('payment_terms', sa.String(50), default='NET30', nullable=True),
        sa.Column('currency', sa.String(10), default='USD', nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_supplier_code')
    )

    # Purchase Orders
    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('po_number', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('supplier_id', sa.String(36), sa.ForeignKey('suppliers.id'), nullable=False, index=True),
        sa.Column('target_warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('status', sa.String(30), default='DRAFT', nullable=False),
        sa.Column('total_amount', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('ordered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expected_delivery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # PO Line Items
    op.create_table(
        'po_line_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('purchase_order_id', sa.String(36), sa.ForeignKey('purchase_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id'), nullable=False, index=True),
        sa.Column('quantity_ordered', sa.Numeric(18, 4), nullable=False),
        sa.Column('quantity_received', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 4), nullable=False),
        sa.Column('line_total', sa.Numeric(18, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Goods Receipts
    op.create_table(
        'goods_receipts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('purchase_order_id', sa.String(36), sa.ForeignKey('purchase_orders.id'), nullable=False, index=True),
        sa.Column('grn_number', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Goods Receipt Lines
    op.create_table(
        'goods_receipt_lines',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('goods_receipt_id', sa.String(36), sa.ForeignKey('goods_receipts.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('po_line_id', sa.String(36), sa.ForeignKey('po_line_items.id'), nullable=False),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id'), nullable=False),
        sa.Column('quantity_received', sa.Numeric(18, 4), nullable=False),
        sa.Column('destination_bin_id', sa.String(36), sa.ForeignKey('location_bins.id'), nullable=False),
        sa.Column('batch_number', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Customers
    op.create_table(
        'customers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('shipping_addresses', sa.JSON(), nullable=True),
        sa.Column('billing_address', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_customer_code')
    )

    # Sales Orders
    op.create_table(
        'sales_orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('so_number', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('customers.id'), nullable=False, index=True),
        sa.Column('warehouse_id', sa.String(36), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('status', sa.String(30), default='CONFIRMED', nullable=False),
        sa.Column('total_amount', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('ordered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # SO Line Items
    op.create_table(
        'so_line_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sales_order_id', sa.String(36), sa.ForeignKey('sales_orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('item_variant_id', sa.String(36), sa.ForeignKey('item_variants.id'), nullable=False, index=True),
        sa.Column('quantity_ordered', sa.Numeric(18, 4), nullable=False),
        sa.Column('quantity_allocated', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('quantity_picked', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('quantity_shipped', sa.Numeric(18, 4), default=0.0, nullable=False),
        sa.Column('unit_price', sa.Numeric(18, 4), nullable=False),
        sa.Column('line_total', sa.Numeric(18, 4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Shipments
    op.create_table(
        'shipments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sales_order_id', sa.String(36), sa.ForeignKey('sales_orders.id'), nullable=False, index=True),
        sa.Column('shipment_number', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('carrier', sa.String(100), nullable=True),
        sa.Column('tracking_number', sa.String(100), nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dispatched_by_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), default=False, nullable=False),
    )

    # Append-only Audit Logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(50), nullable=False, index=True),
        sa.Column('entity_type', sa.String(100), nullable=False, index=True),
        sa.Column('entity_id', sa.String(36), nullable=False, index=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('client_type', sa.String(20), default='WEB', nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index('idx_audit_tenant_time', 'audit_logs', ['tenant_id', 'timestamp'])
    op.create_index('idx_audit_entity', 'audit_logs', ['entity_type', 'entity_id'])

    # Event Outbox
    op.create_table(
        'event_outbox',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('event_type', sa.String(100), nullable=False, index=True),
        sa.Column('aggregate_type', sa.String(50), nullable=False),
        sa.Column('aggregate_id', sa.String(36), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_outbox_status', 'event_outbox', ['status', 'created_at'])


def downgrade() -> None:
    op.drop_table('event_outbox')
    op.drop_table('audit_logs')
    op.drop_table('shipments')
    op.drop_table('so_line_items')
    op.drop_table('sales_orders')
    op.drop_table('customers')
    op.drop_table('goods_receipt_lines')
    op.drop_table('goods_receipts')
    op.drop_table('po_line_items')
    op.drop_table('purchase_orders')
    op.drop_table('suppliers')
    op.drop_table('stock_balance_cache')
    op.drop_table('stock_ledger_entries')
    op.drop_table('stock_ledger_transactions')
    op.drop_table('stock_batches')
    op.drop_table('barcodes')
    op.drop_table('item_variants')
    op.drop_table('items')
    op.drop_table('item_categories')
    op.drop_table('refresh_token_sessions')
    op.drop_table('role_permissions')
    op.drop_table('user_roles')
    op.drop_table('location_bins')
    op.drop_table('warehouses')
    op.drop_table('permissions')
    op.drop_table('roles')
    op.drop_table('users')
