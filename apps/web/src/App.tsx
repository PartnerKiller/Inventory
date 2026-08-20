import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from './context/AuthContext';
import { Sidebar, NavPage } from './components/Sidebar';
import { Navbar } from './components/Navbar';
import { ScannerHUD } from './components/ScannerHUD';
import { GlobalSearchModal } from './components/GlobalSearchModal';
import { DesktopSettingsModal } from './components/DesktopSettingsModal';
import { SyncCenterModal } from './components/SyncCenterModal';
import { ScannerSettingsModal } from './components/ScannerSettingsModal';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { InventoryCatalogPage } from './pages/InventoryCatalogPage';
import { StockLedgerPage } from './pages/StockLedgerPage';
import { WarehousesPage } from './pages/WarehousesPage';
import { PurchasingPage } from './pages/PurchasingPage';
import { SalesOrdersPage } from './pages/SalesOrdersPage';
import { BarcodeStationPage } from './pages/BarcodeStationPage';
import { ReportsPage } from './pages/ReportsPage';
import { AuditLogPage } from './pages/AuditLogPage';
import { UsersRolesPage } from './pages/UsersRolesPage';
import { SettingsPage } from './pages/SettingsPage';
import { OperationsMonitoringPage } from './pages/OperationsMonitoringPage';
import { api } from './api/client';
import { Warehouse } from '@inventory/shared-types';
import { CheckCircle2, AlertCircle, Info } from 'lucide-react';

interface ToastMessage {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

export const App: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const [currentPage, setCurrentPage] = useState<NavPage>('dashboard');
  const [activeWarehouse, setActiveWarehouse] = useState<string>('');
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);
  const [isDesktopSettingsOpen, setIsDesktopSettingsOpen] = useState<boolean>(false);
  const [isSyncCenterOpen, setIsSyncCenterOpen] = useState<boolean>(false);
  const [isScannerSettingsOpen, setIsScannerSettingsOpen] = useState<boolean>(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'success') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 3200);
  }, []);

  const loadWarehouses = async () => {
    if (!isAuthenticated) return;
    try {
      const data = await api.getWarehouses();
      setWarehouses(data);
    } catch (e) {
      console.error('Failed to fetch warehouses:', e);
    }
  };

  useEffect(() => {
    loadWarehouses();
  }, [isAuthenticated]);

  // Global Ctrl+K / Cmd+K listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsSearchOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-app)', color: 'var(--text-secondary)' }}>
        Initializing AuraStock Enterprise Engine...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  const renderContent = () => {
    switch (currentPage) {
      case 'dashboard':
        return <DashboardPage onNavigate={setCurrentPage} activeWarehouse={activeWarehouse} />;
      case 'items':
        return <InventoryCatalogPage />;
      case 'ledger':
        return <StockLedgerPage />;
      case 'warehouses':
        return <WarehousesPage />;
      case 'purchasing':
        return <PurchasingPage />;
      case 'sales':
        return <SalesOrdersPage />;
      case 'barcodes':
        return <BarcodeStationPage />;
      case 'reports':
        return <ReportsPage />;
      case 'audit':
        return <AuditLogPage />;
      case 'users':
        return <UsersRolesPage />;
      case 'settings':
        return <SettingsPage />;
      case 'operations':
        return <OperationsMonitoringPage />;
      default:
        return <DashboardPage onNavigate={setCurrentPage} activeWarehouse={activeWarehouse} />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} />
      <div className="main-content">
        <Navbar
          activeWarehouse={activeWarehouse}
          onWarehouseChange={setActiveWarehouse}
          warehouses={warehouses}
          onRefresh={loadWarehouses}
          onOpenSearch={() => setIsSearchOpen(true)}
          onOpenDesktopSettings={() => setIsDesktopSettingsOpen(true)}
          onOpenSyncCenter={() => setIsSyncCenterOpen(true)}
          onOpenScannerSettings={() => setIsScannerSettingsOpen(true)}
        />
        <main className="page-body">
          <ScannerHUD />
          {renderContent()}
        </main>
      </div>

      {/* Global Modals rendered at Root with createPortal */}
      <GlobalSearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onNavigate={setCurrentPage}
      />

      <DesktopSettingsModal
        isOpen={isDesktopSettingsOpen}
        onClose={() => setIsDesktopSettingsOpen(false)}
        onShowToast={showToast}
      />

      <SyncCenterModal
        isOpen={isSyncCenterOpen}
        onClose={() => setIsSyncCenterOpen(false)}
        onShowToast={showToast}
      />

      <ScannerSettingsModal
        isOpen={isScannerSettingsOpen}
        onClose={() => setIsScannerSettingsOpen(false)}
      />

      {/* Non-blocking Toast Container */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map(t => (
            <div key={t.id} className={`toast-notification ${t.type}`}>
              {t.type === 'success' && <CheckCircle2 size={16} color="#34d399" />}
              {t.type === 'error' && <AlertCircle size={16} color="#f87171" />}
              {t.type === 'info' && <Info size={16} color="#38bdf8" />}
              <span>{t.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
