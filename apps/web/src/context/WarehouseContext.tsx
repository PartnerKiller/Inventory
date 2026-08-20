import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { Warehouse } from '@inventory/shared-types';
import { api } from '../api/client';
import { useAuth } from './AuthContext';

export interface WarehouseContextType {
  warehouses: Warehouse[];
  activeWarehouseId: string;
  activeWarehouse: Warehouse | null;
  isLoadingWarehouses: boolean;
  setActiveWarehouseId: (id: string) => void;
  refreshWarehouses: () => Promise<void>;
}

const defaultWarehouseContext: WarehouseContextType = {
  warehouses: [],
  activeWarehouseId: '',
  activeWarehouse: null,
  isLoadingWarehouses: false,
  setActiveWarehouseId: () => {},
  refreshWarehouses: async () => {},
};

const WarehouseContext = createContext<WarehouseContextType>(defaultWarehouseContext);

export const WarehouseProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [activeWarehouseId, setActiveWarehouseIdState] = useState<string>(() => {
    return localStorage.getItem('aurastock_active_warehouse') || '';
  });
  const [isLoadingWarehouses, setIsLoadingWarehouses] = useState<boolean>(false);

  const loadWarehouses = useCallback(async () => {
    if (!isAuthenticated) {
      setWarehouses([]);
      return;
    }
    try {
      setIsLoadingWarehouses(true);
      const data = await api.getWarehouses();
      setWarehouses(data);
    } catch (e) {
      console.error('WarehouseContext: Failed to fetch facilities:', e);
    } finally {
      setIsLoadingWarehouses(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    loadWarehouses();
  }, [loadWarehouses]);

  const setActiveWarehouseId = useCallback((id: string) => {
    const cleanId = (id || '').trim();
    setActiveWarehouseIdState(cleanId);
    if (cleanId) {
      localStorage.setItem('aurastock_active_warehouse', cleanId);
    } else {
      localStorage.removeItem('aurastock_active_warehouse');
    }
  }, []);

  const activeWarehouse = useMemo(() => {
    if (!activeWarehouseId) return null;
    return warehouses.find(w => w.id === activeWarehouseId) || null;
  }, [warehouses, activeWarehouseId]);

  const contextValue = useMemo(() => ({
    warehouses,
    activeWarehouseId,
    activeWarehouse,
    isLoadingWarehouses,
    setActiveWarehouseId,
    refreshWarehouses: loadWarehouses,
  }), [warehouses, activeWarehouseId, activeWarehouse, isLoadingWarehouses, setActiveWarehouseId, loadWarehouses]);

  return (
    <WarehouseContext.Provider value={contextValue}>
      {children}
    </WarehouseContext.Provider>
  );
};

export const useWarehouse = (): WarehouseContextType => {
  const context = useContext(WarehouseContext);
  return context || defaultWarehouseContext;
};
