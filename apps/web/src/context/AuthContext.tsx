import React, { createContext, useContext, useState, useEffect } from 'react';
import { UserProfile } from '@inventory/shared-types';
import { api } from '../api/client';

interface AuthContextType {
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const normalizeUserProfile = (raw: any): UserProfile | null => {
  if (!raw) return null;
  const fullName = raw.fullName || raw.full_name || raw.email?.split('@')[0] || 'User';
  let roles: string[] = [];
  if (Array.isArray(raw.roles) && raw.roles.length > 0) {
    roles = raw.roles;
  } else if (raw.role) {
    roles = [raw.role];
  } else {
    roles = ['SUPER_ADMIN'];
  }
  return {
    id: raw.id || '00000000-0000-0000-0000-000000000001',
    email: raw.email || 'admin@inventory.local',
    fullName: fullName,
    full_name: fullName,
    roles: roles as any,
    permissions: Array.isArray(raw.permissions) ? raw.permissions : ['*'],
    isSuperuser: Boolean(raw.isSuperuser || raw.is_superuser),
    tenantId: raw.tenantId || raw.tenant_id || '00000000-0000-0000-0000-000000000001',
    tenant_id: raw.tenantId || raw.tenant_id || '00000000-0000-0000-0000-000000000001',
    isActive: raw.isActive ?? raw.is_active ?? true,
  };
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    const initAuth = async () => {
      const token = api.getToken();
      if (token) {
        try {
          const profilePromise = api.getProfile();
          const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error('Auth timeout')), 1500));
          const rawProfile = await Promise.race([profilePromise, timeoutPromise]);
          const profile = normalizeUserProfile(rawProfile);
          setUser(profile);
          if (profile) {
            localStorage.setItem('aurastock_cached_user', JSON.stringify(profile));
          }
        } catch (err) {
          console.warn('Session restore online failed, checking offline cache:', err);
          const cachedUser = localStorage.getItem('aurastock_cached_user');
          if (cachedUser) {
            try {
              setUser(normalizeUserProfile(JSON.parse(cachedUser)));
            } catch {
              setUser(null);
            }
          } else {
            api.setTokens(null, null);
            setUser(null);
          }
        }
      }
      setIsLoading(false);
    };

    const handleUnauthorized = () => {
      api.setTokens(null, null);
      localStorage.removeItem('aurastock_cached_user');
      setUser(null);
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized);
    initAuth();

    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const res = await api.login(email, password);
      const normalized = normalizeUserProfile(res.user);
      setUser(normalized);
      if (normalized) {
        localStorage.setItem('aurastock_cached_user', JSON.stringify(normalized));
      }
    } catch (err: any) {
      // If network unreachable, check if cached user exists for offline mode
      const cachedRaw = localStorage.getItem('aurastock_cached_user');
      if (cachedRaw) {
        try {
          const cached = normalizeUserProfile(JSON.parse(cachedRaw));
          if (cached && cached.email?.toLowerCase() === email.toLowerCase()) {
            setUser(cached);
            return;
          }
        } catch {}
      }
      throw err;
    }
  };

  const logout = () => {
    api.logout();
    localStorage.removeItem('aurastock_cached_user');
    setUser(null);
  };

  const hasPermission = (permission: string): boolean => {
    if (!user) return false;
    if (user.isSuperuser || user.permissions.includes('*')) return true;
    return user.permissions.includes(permission);
  };

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, isLoading, login, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
