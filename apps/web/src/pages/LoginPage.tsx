import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { ShieldCheck, LogIn, KeyRound, UserCheck } from 'lucide-react';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err.message || 'Login failed. Please check credentials.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickLogin = (demoEmail: string, demoPass: string) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    login(demoEmail, demoPass).catch((err) => setError(err.message));
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'var(--bg-app)',
      padding: '20px'
    }}>
      <div style={{
        maxWidth: '460px',
        width: '100%',
        backgroundColor: 'var(--bg-sidebar)',
        border: '1px solid var(--border-card)',
        borderRadius: 'var(--radius-lg)',
        padding: '36px',
        boxShadow: 'var(--shadow-lg)'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div style={{
            width: '48px',
            height: '48px',
            background: 'linear-gradient(135deg, #2563eb, #0ea5e9)',
            borderRadius: 'var(--radius-md)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 800,
            fontSize: '22px',
            boxShadow: '0 4px 14px rgba(37, 99, 235, 0.4)',
            marginBottom: '12px'
          }}>
            A
          </div>
          <h2 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
            AuraStock Enterprise
          </h2>
          <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Sign in to access multi-warehouse stock management
          </p>
        </div>

        {error && (
          <div style={{
            backgroundColor: 'var(--danger-bg)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#f87171',
            padding: '10px 14px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '13px',
            marginBottom: '20px'
          }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Work Email</label>
            <input
              type="text"
              required
              className="form-control"
              placeholder="user@inventory.local"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              type="password"
              required
              className="form-control"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="btn btn-primary"
            style={{ width: '100%', padding: '11px', marginTop: '8px' }}
          >
            <LogIn size={16} /> {isSubmitting ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>

        <div style={{ marginTop: '28px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '10px', textAlign: 'center' }}>
            Quick Demo Profiles
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              className="btn btn-secondary btn-sm"
              style={{ justifyContent: 'space-between', padding: '8px 12px' }}
              onClick={() => handleQuickLogin('admin@inventory.local', 'Admin123!')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ShieldCheck size={15} color="#3b82f6" />
                <span style={{ fontSize: '12.5px', fontWeight: 600 }}>Super Admin (All Modules)</span>
              </div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Admin123!</span>
            </button>

            <button
              className="btn btn-secondary btn-sm"
              style={{ justifyContent: 'space-between', padding: '8px 12px' }}
              onClick={() => handleQuickLogin('manager@inventory.local', 'Manager123!')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <UserCheck size={15} color="#10b981" />
                <span style={{ fontSize: '12.5px', fontWeight: 600 }}>Austin Warehouse Manager</span>
              </div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Manager123!</span>
            </button>

            <button
              className="btn btn-secondary btn-sm"
              style={{ justifyContent: 'space-between', padding: '8px 12px' }}
              onClick={() => handleQuickLogin('clerk@inventory.local', 'Clerk123!')}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <KeyRound size={15} color="#f59e0b" />
                <span style={{ fontSize: '12.5px', fontWeight: 600 }}>Inventory Clerk</span>
              </div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Clerk123!</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
