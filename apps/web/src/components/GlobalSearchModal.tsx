import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Search, X, ArrowRight, Package, User, Building2, ShoppingCart, Send, Barcode, Warehouse, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import { GlobalSearchResultItem } from '@inventory/shared-types';
import { NavPage } from './Sidebar';

interface GlobalSearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (page: NavPage) => void;
}

export const GlobalSearchModal: React.FC<GlobalSearchModalProps> = ({ isOpen, onClose, onNavigate }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GlobalSearchResultItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        setIsLoading(true);
        const res = await api.globalSearch(query.trim());
        setResults(res.results);
        setSelectedIndex(0);
      } catch (err) {
        console.error('Global search error:', err);
      } finally {
        setIsLoading(false);
      }
    }, 200);

    return () => clearTimeout(timer);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev < results.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[selectedIndex]) {
        handleSelect(results[selectedIndex]);
      }
    }
  };

  const handleSelect = (item: GlobalSearchResultItem) => {
    const pageMap: Record<string, NavPage> = {
      '/catalog': 'items',
      '/purchasing': 'purchasing',
      '/sales': 'sales',
      '/warehouses': 'warehouses',
      '/ledger': 'ledger',
      '/reports': 'reports'
    };
    const targetPage = pageMap[item.link_page] || 'dashboard';
    onNavigate(targetPage);
    onClose();
  };

  if (!isOpen) return null;

  const renderCategoryIcon = (category: string) => {
    switch (category) {
      case 'PRODUCT': return <Package size={16} color="#38bdf8" />;
      case 'BARCODE': return <Barcode size={16} color="#fbbf24" />;
      case 'CUSTOMER': return <User size={16} color="#34d399" />;
      case 'SUPPLIER': return <Building2 size={16} color="#a78bfa" />;
      case 'PURCHASE_ORDER': return <ShoppingCart size={16} color="#60a5fa" />;
      case 'SALES_ORDER': return <Send size={16} color="#f472b6" />;
      case 'WAREHOUSE': return <Warehouse size={16} color="#fb923c" />;
      default: return <Search size={16} color="#94a3b8" />;
    }
  };

  const modalElement = (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(5, 10, 20, 0.78)',
      backdropFilter: 'blur(6px)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'center',
      paddingTop: '80px',
    }} onClick={onClose}>
      <div style={{
        width: '640px',
        maxWidth: '92vw',
        backgroundColor: '#0f172a',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
        overflow: 'hidden',
      }} onClick={(e) => e.stopPropagation()}>
        {/* Search Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle)',
          backgroundColor: '#131e36',
        }}>
          <Search size={20} color="#93c5fd" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search products, SKU, barcodes, customer orders, vendors..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '15px',
              outline: 'none',
            }}
          />
          {isLoading && <RefreshCw size={16} className="spin" color="#60a5fa" />}
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '4px',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Results Body */}
        <div style={{ maxHeight: '420px', overflowY: 'auto', padding: '8px' }}>
          {results.length === 0 && query.trim() && !isLoading ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              No matches found for "{query}" across tenant inventory.
            </div>
          ) : results.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12.5px' }}>
              Type product names, SKU codes, PO numbers, customer or supplier accounts...
            </div>
          ) : (
            results.map((item, index) => {
              const isSelected = index === selectedIndex;
              return (
                <div
                  key={item.identifier + item.category + index}
                  onClick={() => handleSelect(item)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: isSelected ? '#1e293b' : 'transparent',
                    cursor: 'pointer',
                    transition: 'background-color 0.1s',
                    border: isSelected ? '1px solid #3b82f6' : '1px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '6px',
                      backgroundColor: '#0f172a',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      {renderCategoryIcon(item.category)}
                    </div>
                    <div>
                      <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
                        {item.title}
                      </div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '2px' }}>
                        {item.subtitle}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      fontSize: '10.5px',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor: '#0f172a',
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                    }}>
                      {item.category.replace('_', ' ')}
                    </span>
                    <ArrowRight size={14} color="#64748b" />
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '10px 16px',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: '#090d16',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '11.5px',
          color: '#64748b',
        }}>
          <div>
            Use <kbd style={{ padding: '1px 5px', background: '#1e293b', borderRadius: '3px' }}>&uarr;</kbd> <kbd style={{ padding: '1px 5px', background: '#1e293b', borderRadius: '3px' }}>&darr;</kbd> to navigate, <kbd style={{ padding: '1px 5px', background: '#1e293b', borderRadius: '3px' }}>Enter</kbd> to select
          </div>
          <div>Global Tenant Isolated</div>
        </div>
      </div>
    </div>
  );

  if (typeof document !== 'undefined') {
    return createPortal(modalElement, document.body);
  }

  return modalElement;
};
