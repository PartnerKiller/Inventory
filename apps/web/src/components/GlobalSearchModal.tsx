import React, { useState, useEffect, useRef } from 'react';
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

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(5, 10, 20, 0.75)',
      backdropFilter: 'blur(4px)',
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
            placeholder="Search products, SKUs, barcodes, customers, suppliers, POs, SOs... (ESC to close)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{
              flex: 1,
              backgroundColor: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#fff',
              fontSize: '15px',
              fontWeight: 500,
            }}
          />
          {isLoading ? (
            <RefreshCw size={16} className="spin" color="#94a3b8" />
          ) : query ? (
            <button
              onClick={() => setQuery('')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 0 }}
            >
              <X size={16} />
            </button>
          ) : (
            <span style={{ fontSize: '11px', color: '#64748b', border: '1px solid #334155', padding: '2px 6px', borderRadius: '4px' }}>
              ESC
            </span>
          )}
        </div>

        {/* Results List */}
        <div style={{ maxHeight: '380px', overflowY: 'auto', padding: '8px' }}>
          {!query.trim() ? (
            <div style={{ padding: '30px 20px', textAlign: 'center', color: '#64748b', fontSize: '13px' }}>
              Type a keyword, SKU, PO number, or customer name to search across the entire inventory system.
            </div>
          ) : results.length === 0 && !isLoading ? (
            <div style={{ padding: '30px 20px', textAlign: 'center', color: '#64748b', fontSize: '13px' }}>
              No matches found for <strong style={{ color: '#94a3b8' }}>"{query}"</strong>
            </div>
          ) : (
            results.map((r, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={r.identifier + r.category + idx}
                  onClick={() => handleSelect(r)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: isSelected ? '#1e293b' : 'transparent',
                    cursor: 'pointer',
                    transition: 'background 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      padding: '8px',
                      backgroundColor: 'rgba(255,255,255,0.04)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      {renderCategoryIcon(r.category)}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '13.5px', color: isSelected ? '#93c5fd' : '#f1f5f9' }}>
                        {r.title}
                      </div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                        {r.subtitle}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="badge badge-default" style={{ fontSize: '10px' }}>
                      {r.category}
                    </span>
                    <ArrowRight size={14} color={isSelected ? '#93c5fd' : '#475569'} />
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
};
