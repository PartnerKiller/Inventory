import React, { useEffect, useState } from 'react';
import {
  Users, Shield, Plus, Key, CheckCircle, Lock, UserX, UserCheck,
  Smartphone, Monitor, Laptop, Trash2, LogOut, RefreshCw, Warehouse,
  Search, Filter, ShieldAlert, Edit2, AlertTriangle, Eye
} from 'lucide-react';
import { api } from '../api/client';
import { UserProfile, RoleItem, PermissionItem, UserSessionItem, Warehouse as WarehouseType } from '@inventory/shared-types';
import { Modal } from '../components/Modal';

export const UsersRolesPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'users' | 'roles' | 'matrix' | 'my_sessions'>('users');
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([]);
  const [mySessions, setMySessions] = useState<UserSessionItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedRoleFilter, setSelectedRoleFilter] = useState<string>('');
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<string>('ALL');

  // New / Edit User Modal
  const [isUserModalOpen, setIsUserModalOpen] = useState<boolean>(false);
  const [editingUser, setEditingUser] = useState<UserProfile | null>(null);
  const [userEmail, setUserEmail] = useState<string>('');
  const [userFullName, setUserFullName] = useState<string>('');
  const [userPassword, setUserPassword] = useState<string>('Pass123!');
  const [userRoleIds, setUserRoleIds] = useState<string[]>([]);
  const [userWarehouseIds, setUserWarehouseIds] = useState<string[]>([]);

  // Password Reset Modal
  const [isResetModalOpen, setIsResetModalOpen] = useState<boolean>(false);
  const [resetTargetUser, setResetTargetUser] = useState<UserProfile | null>(null);
  const [newPasswordValue, setNewPasswordValue] = useState<string>('');

  // User Sessions Modal (Admin view)
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState<boolean>(false);
  const [sessionsTargetUser, setSessionsTargetUser] = useState<UserProfile | null>(null);
  const [targetUserSessions, setTargetUserSessions] = useState<UserSessionItem[]>([]);

  // Create / Edit Role Modal
  const [isRoleModalOpen, setIsRoleModalOpen] = useState<boolean>(false);
  const [editingRole, setEditingRole] = useState<RoleItem | null>(null);
  const [roleName, setRoleName] = useState<string>('');
  const [roleDesc, setRoleDesc] = useState<string>('');
  const [rolePermCodes, setRolePermCodes] = useState<string[]>([]);

  // Notification / Error
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadData = async () => {
    try {
      setIsLoading(true);
      const isAct = selectedStatusFilter === 'ACTIVE' ? true : selectedStatusFilter === 'INACTIVE' ? false : undefined;
      const [uList, rList, pList, whList, mySess] = await Promise.all([
        api.getUsers({ q: searchQuery || undefined, role_id: selectedRoleFilter || undefined, is_active: isAct }),
        api.getRoles(),
        api.getPermissions(),
        api.getWarehouses(),
        api.getMySessions(),
      ]);
      setUsers(uList);
      setRoles(rList);
      setPermissions(pList);
      setWarehouses(whList);
      setMySessions(mySess);
    } catch (err: any) {
      console.error('Failed to load user administration data:', err);
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to load user administration data' });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedRoleFilter, selectedStatusFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  // Open Create User
  const handleOpenCreateUser = () => {
    setEditingUser(null);
    setUserEmail('');
    setUserFullName('');
    setUserPassword('Pass123!');
    setUserRoleIds(roles.length > 0 ? [roles[0].id] : []);
    setUserWarehouseIds([]);
    setIsUserModalOpen(true);
  };

  // Open Edit User
  const handleOpenEditUser = (u: UserProfile) => {
    setEditingUser(u);
    setUserEmail(u.email);
    setUserFullName(u.fullName || u.full_name || '');
    setUserRoleIds((u as any).role_ids || []);
    setUserWarehouseIds(u.warehouseScopes || u.warehouse_scopes || []);
    setIsUserModalOpen(true);
  };

  // Submit User Create / Edit
  const handleSaveUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingUser) {
        await api.updateUser(editingUser.id, {
          full_name: userFullName,
          role_ids: userRoleIds,
          warehouse_ids: userWarehouseIds,
        });
        setFeedbackMsg({ type: 'success', text: `User account '${userEmail}' updated successfully.` });
      } else {
        await api.createUser({
          email: userEmail,
          full_name: userFullName,
          password: userPassword,
          role_ids: userRoleIds,
          warehouse_ids: userWarehouseIds,
        });
        setFeedbackMsg({ type: 'success', text: `User '${userEmail}' successfully provisioned.` });
      }
      setIsUserModalOpen(false);
      loadData();
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to save user' });
    }
  };

  // Toggle User Activation
  const handleToggleActivate = async (u: UserProfile) => {
    const isActive = u.isActive ?? u.is_active ?? true;
    try {
      if (isActive) {
        await api.deactivateUser(u.id);
        setFeedbackMsg({ type: 'success', text: `User '${u.email}' deactivated and all active sessions revoked.` });
      } else {
        await api.activateUser(u.id);
        setFeedbackMsg({ type: 'success', text: `User '${u.email}' activated successfully.` });
      }
      loadData();
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to change activation status' });
    }
  };

  // Password Reset
  const handleOpenResetPassword = (u: UserProfile) => {
    setResetTargetUser(u);
    setNewPasswordValue('');
    setIsResetModalOpen(true);
  };

  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTargetUser) return;
    try {
      await api.resetUserPassword(resetTargetUser.id, newPasswordValue);
      setFeedbackMsg({ type: 'success', text: `Password reset for user '${resetTargetUser.email}'. All active sessions invalidated.` });
      setIsResetModalOpen(false);
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Password reset failed' });
    }
  };

  // Inspect User Sessions
  const handleInspectSessions = async (u: UserProfile) => {
    setSessionsTargetUser(u);
    try {
      const sessList = await api.getUserSessions(u.id);
      setTargetUserSessions(sessList);
      setIsSessionsModalOpen(true);
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to load user sessions' });
    }
  };

  const handleRevokeUserSession = async (sessId: string) => {
    if (!sessionsTargetUser) return;
    try {
      await api.revokeUserSession(sessionsTargetUser.id, sessId);
      setTargetUserSessions((prev) => prev.filter((s) => s.id !== sessId));
      setFeedbackMsg({ type: 'success', text: 'Session successfully revoked.' });
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to revoke session' });
    }
  };

  // My Sessions Management
  const handleRevokeMySession = async (sessId: string) => {
    try {
      await api.revokeMySession(sessId);
      setMySessions((prev) => prev.filter((s) => s.id !== sessId));
      setFeedbackMsg({ type: 'success', text: 'Session revoked successfully.' });
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to revoke session' });
    }
  };

  const handleRevokeAllOtherSessions = async () => {
    try {
      await api.revokeOtherSessions();
      const fresh = await api.getMySessions();
      setMySessions(fresh);
      setFeedbackMsg({ type: 'success', text: 'All other active sessions revoked successfully.' });
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to revoke sessions' });
    }
  };

  // Role Creation / Edit
  const handleOpenCreateRole = () => {
    setEditingRole(null);
    setRoleName('');
    setRoleDesc('');
    setRolePermCodes([]);
    setIsRoleModalOpen(true);
  };

  const handleOpenEditRole = (r: RoleItem) => {
    if (r.is_system) return;
    setEditingRole(r);
    setRoleName(r.name);
    setRoleDesc(r.description || '');
    setRolePermCodes(r.permissions || []);
    setIsRoleModalOpen(true);
  };

  const handleSaveRole = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingRole) {
        await api.updateRole(editingRole.id, {
          name: roleName,
          description: roleDesc,
          permission_codes: rolePermCodes,
        });
        setFeedbackMsg({ type: 'success', text: `Custom role '${roleName}' updated successfully.` });
      } else {
        await api.createRole({
          name: roleName,
          description: roleDesc,
          permission_codes: rolePermCodes,
        });
        setFeedbackMsg({ type: 'success', text: `Role '${roleName}' created successfully.` });
      }
      setIsRoleModalOpen(false);
      loadData();
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err.message || 'Failed to save role' });
    }
  };

  // Permission modules grouped
  const permissionModules = Array.from(new Set(permissions.map((p) => p.module)));

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            User Administration & Security Governance (RBAC)
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Granular role delegation, warehouse scoping, session lifecycle, and credential security
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={loadData}>
            <RefreshCw size={14} className={isLoading ? 'spin' : ''} /> Refresh
          </button>
          {activeTab === 'users' && (
            <button className="btn btn-primary" onClick={handleOpenCreateUser}>
              <Plus size={15} /> Provision Team Member
            </button>
          )}
          {activeTab === 'roles' && (
            <button className="btn btn-primary" onClick={handleOpenCreateRole}>
              <Plus size={15} /> Create Custom Role
            </button>
          )}
        </div>
      </div>

      {feedbackMsg && (
        <div style={{
          padding: '12px 16px',
          backgroundColor: feedbackMsg.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
          border: `1px solid ${feedbackMsg.type === 'success' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          borderRadius: 'var(--radius-sm)',
          color: feedbackMsg.type === 'success' ? '#34d399' : '#f87171',
          fontSize: '13px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          {feedbackMsg.type === 'success' ? <CheckCircle size={16} /> : <AlertTriangle size={16} />}
          {feedbackMsg.text}
        </div>
      )}

      {/* Navigation Tabs */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '16px' }}>
        <button
          className={`btn ${activeTab === 'users' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('users')}
        >
          <Users size={15} /> Team Members & Warehouse Scopes
        </button>
        <button
          className={`btn ${activeTab === 'roles' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('roles')}
        >
          <Shield size={15} /> Roles Directory
        </button>
        <button
          className={`btn ${activeTab === 'matrix' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('matrix')}
        >
          <Key size={15} /> Permission Matrix
        </button>
        <button
          className={`btn ${activeTab === 'my_sessions' ? 'btn-primary' : 'btn-outline'}`}
          style={{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}
          onClick={() => setActiveTab('my_sessions')}
        >
          <Monitor size={15} /> Active Sessions & Devices
        </button>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: USERS */}
      {/* ========================================================================= */}
      {activeTab === 'users' && (
        <div>
          {/* Filters Bar */}
          <div className="card" style={{ marginBottom: '16px', padding: '14px' }}>
            <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
                <Search size={15} style={{ position: 'absolute', left: '10px', top: '11px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-control"
                  style={{ paddingLeft: '32px' }}
                  placeholder="Search user name or email..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              <select
                className="form-control"
                style={{ width: '180px' }}
                value={selectedRoleFilter}
                onChange={(e) => setSelectedRoleFilter(e.target.value)}
              >
                <option value="">All Security Roles</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>

              <select
                className="form-control"
                style={{ width: '150px' }}
                value={selectedStatusFilter}
                onChange={(e) => setSelectedStatusFilter(e.target.value)}
              >
                <option value="ALL">All Statuses</option>
                <option value="ACTIVE">Active Only</option>
                <option value="INACTIVE">Deactivated Only</option>
              </select>

              <button type="submit" className="btn btn-secondary">
                <Filter size={14} /> Filter
              </button>
            </form>
          </div>

          {/* Users Table */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Tenant User Accounts ({users.length})</div>
              <span className="badge badge-info">Authoritative RBAC Enforced</span>
            </div>

            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Full Name</th>
                    <th>Email Address</th>
                    <th>Assigned Roles</th>
                    <th>Warehouse Scopes</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const isActive = u.isActive ?? u.is_active ?? true;
                    const scopes = u.warehouseScopes || u.warehouse_scopes || [];
                    return (
                      <tr key={u.id}>
                        <td>
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                            {u.fullName || u.full_name}
                          </div>
                          {u.isSuperuser && (
                            <span className="badge badge-warning" style={{ fontSize: '9.5px', marginTop: '2px' }}>
                              Root SuperAdmin
                            </span>
                          )}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)' }}>
                          {u.email}
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                            {u.roles.map((r) => (
                              <span key={r} className="badge badge-info" style={{ fontSize: '10.5px' }}>
                                {r}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td>
                          {scopes.length === 0 ? (
                            <span className="badge badge-default" style={{ fontSize: '10.5px' }}>Global (All Facilities)</span>
                          ) : (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                              {scopes.map((wid) => {
                                const wh = warehouses.find((w) => w.id === wid);
                                return (
                                  <span key={wid} className="badge badge-default" style={{ fontSize: '10px' }}>
                                    <Warehouse size={10} style={{ marginRight: '3px' }} />
                                    {wh ? wh.code : wid.slice(0, 6)}
                                  </span>
                                );
                              })}
                            </div>
                          )}
                        </td>
                        <td>
                          {isActive ? (
                            <span className="badge badge-success">
                              <CheckCircle size={12} /> Active
                            </span>
                          ) : (
                            <span className="badge badge-danger">
                              <UserX size={12} /> Deactivated
                            </span>
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: '6px' }}>
                            <button
                              className="btn btn-outline btn-sm"
                              title="Edit User & Permissions"
                              onClick={() => handleOpenEditUser(u)}
                            >
                              <Edit2 size={13} />
                            </button>
                            <button
                              className="btn btn-outline btn-sm"
                              title="Reset Password"
                              onClick={() => handleOpenResetPassword(u)}
                            >
                              <Key size={13} />
                            </button>
                            <button
                              className="btn btn-outline btn-sm"
                              title="View Active Sessions"
                              onClick={() => handleInspectSessions(u)}
                            >
                              <Monitor size={13} />
                            </button>
                            <button
                              className={`btn btn-sm ${isActive ? 'btn-outline' : 'btn-secondary'}`}
                              title={isActive ? 'Deactivate User' : 'Activate User'}
                              onClick={() => handleToggleActivate(u)}
                            >
                              {isActive ? <UserX size={13} color="#f87171" /> : <UserCheck size={13} color="#34d399" />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: ROLES */}
      {/* ========================================================================= */}
      {activeTab === 'roles' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
          {roles.map((role) => (
            <div key={role.id} className="card">
              <div className="card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Shield size={18} color="#60a5fa" />
                  <div className="card-title">{role.name}</div>
                </div>
                {role.is_system ? (
                  <span className="badge badge-warning">System Built-In</span>
                ) : (
                  <span className="badge badge-info">Custom Role</span>
                )}
              </div>

              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginBottom: '12px', minHeight: '36px' }}>
                {role.description || 'No description configured.'}
              </p>

              <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '10px', marginTop: 'auto' }}>
                <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Assigned Permissions ({role.permissions?.length || 0}):
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', maxHeight: '100px', overflowY: 'auto' }}>
                  {role.permissions?.map((p) => (
                    <span key={p} className="badge badge-default" style={{ fontSize: '10px' }}>
                      {p}
                    </span>
                  ))}
                </div>

                {!role.is_system && (
                  <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'flex-end' }}>
                    <button className="btn btn-outline btn-sm" onClick={() => handleOpenEditRole(role)}>
                      <Edit2 size={13} /> Edit Role Capabilities
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: PERMISSION MATRIX */}
      {/* ========================================================================= */}
      {activeTab === 'matrix' && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Enterprise Role-Permission Capability Matrix</div>
            <span className="badge badge-info">Multi-Module Governance</span>
          </div>

          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ minWidth: '180px' }}>Permission / Module</th>
                  <th style={{ minWidth: '220px' }}>Capability Description</th>
                  {roles.map((r) => (
                    <th key={r.id} style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: '12px' }}>{r.name}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {permissions.map((perm) => (
                  <tr key={perm.id}>
                    <td>
                      <div style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#60a5fa' }}>
                        {perm.code}
                      </div>
                      <span className="badge badge-default" style={{ fontSize: '9.5px', marginTop: '2px' }}>
                        {perm.module}
                      </span>
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {perm.description || perm.code}
                    </td>
                    {roles.map((r) => {
                      const hasPerm = r.permissions?.includes(perm.code) || r.name === 'SUPER_ADMIN';
                      return (
                        <td key={r.id} style={{ textAlign: 'center' }}>
                          {hasPerm ? (
                            <CheckCircle size={16} color="#34d399" style={{ display: 'inline' }} />
                          ) : (
                            <span style={{ color: 'var(--text-muted)' }}>&mdash;</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: MY SESSIONS */}
      {/* ========================================================================= */}
      {activeTab === 'my_sessions' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: '16px', color: 'var(--text-primary)' }}>
                Active Cryptographic Sessions
              </div>
              <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Refresh-token rotation sessions authenticated to your profile across desktop and web clients
              </div>
            </div>

            <button className="btn btn-outline" onClick={handleRevokeAllOtherSessions} style={{ color: '#f87171' }}>
              <LogOut size={14} /> Revoke All Other Sessions
            </button>
          </div>

          <div className="card">
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Device & Client</th>
                    <th>Created At</th>
                    <th>Session Expiration</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {mySessions.map((sess) => (
                    <tr key={sess.id}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Laptop size={16} color="#60a5fa" />
                          <span style={{ fontWeight: 500 }}>{sess.device_info || 'Web Client'}</span>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                          Session ID: {sess.id}
                        </div>
                      </td>
                      <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {new Date(sess.created_at).toLocaleString()}
                      </td>
                      <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {new Date(sess.expires_at).toLocaleString()}
                      </td>
                      <td>
                        <button
                          className="btn btn-outline btn-sm"
                          style={{ color: '#f87171' }}
                          onClick={() => handleRevokeMySession(sess.id)}
                        >
                          <Trash2 size={13} /> Revoke Session
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: PROVISION / EDIT USER */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isUserModalOpen}
        onClose={() => setIsUserModalOpen(false)}
        title={editingUser ? `Edit Team Member: ${editingUser.email}` : 'Provision New Team Member'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsUserModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveUser}>
              {editingUser ? 'Update Account' : 'Provision User'}
            </button>
          </>
        }
      >
        <form onSubmit={handleSaveUser}>
          <div className="form-group">
            <label className="form-label">Full Name *</label>
            <input
              type="text"
              required
              className="form-control"
              placeholder="e.g. Rachel Adams"
              value={userFullName}
              onChange={(e) => setUserFullName(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Email Address *</label>
            <input
              type="email"
              required
              disabled={!!editingUser}
              className="form-control"
              placeholder="rachel@inventory.local"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
            />
          </div>

          {!editingUser && (
            <div className="form-group">
              <label className="form-label">Initial Password *</label>
              <input
                type="password"
                required
                className="form-control"
                value={userPassword}
                onChange={(e) => setUserPassword(e.target.value)}
              />
            </div>
          )}

          {/* Role Checkboxes */}
          <div className="form-group">
            <label className="form-label">Assign Security Roles *</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', maxHeight: '160px', overflowY: 'auto' }}>
              {roles.map((r) => {
                const checked = userRoleIds.includes(r.id);
                return (
                  <label
                    key={r.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '8px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: checked ? 'rgba(59, 130, 246, 0.1)' : 'var(--bg-app)',
                      border: `1px solid ${checked ? 'rgba(59, 130, 246, 0.3)' : 'var(--border-subtle)'}`,
                      cursor: 'pointer',
                      fontSize: '12px'
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setUserRoleIds((prev) => [...prev, r.id]);
                        } else {
                          setUserRoleIds((prev) => prev.filter((id) => id !== r.id));
                        }
                      }}
                    />
                    <div>
                      <div style={{ fontWeight: 600 }}>{r.name}</div>
                      <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{r.description}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Warehouse Scopes */}
          <div className="form-group">
            <label className="form-label">Assigned Facility Scopes (Leave empty for Global Access)</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', maxHeight: '140px', overflowY: 'auto' }}>
              {warehouses.map((wh) => {
                const checked = userWarehouseIds.includes(wh.id);
                return (
                  <label
                    key={wh.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '8px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: checked ? 'rgba(16, 185, 129, 0.1)' : 'var(--bg-app)',
                      border: `1px solid ${checked ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-subtle)'}`,
                      cursor: 'pointer',
                      fontSize: '12px'
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setUserWarehouseIds((prev) => [...prev, wh.id]);
                        } else {
                          setUserWarehouseIds((prev) => prev.filter((id) => id !== wh.id));
                        }
                      }}
                    />
                    <div>
                      <div style={{ fontWeight: 600 }}>{wh.code}</div>
                      <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{wh.name}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: RESET PASSWORD */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isResetModalOpen}
        onClose={() => setIsResetModalOpen(false)}
        title={`Reset Password for: ${resetTargetUser?.email}`}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsResetModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleResetPasswordSubmit}>Confirm Reset</button>
          </>
        }
      >
        <form onSubmit={handleResetPasswordSubmit}>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
            Setting a new password will immediately invalidate all active sessions across all devices for this user.
          </p>

          <div className="form-group">
            <label className="form-label">New Password *</label>
            <input
              type="password"
              required
              className="form-control"
              placeholder="Enter secure new password..."
              value={newPasswordValue}
              onChange={(e) => setNewPasswordValue(e.target.value)}
            />
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: USER ACTIVE SESSIONS (ADMIN INSPECTION) */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isSessionsModalOpen}
        onClose={() => setIsSessionsModalOpen(false)}
        title={`Active Sessions: ${sessionsTargetUser?.email}`}
        footer={<button className="btn btn-primary" onClick={() => setIsSessionsModalOpen(false)}>Close</button>}
      >
        <div>
          {targetUserSessions.length === 0 ? (
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center', padding: '20px 0' }}>
              No active sessions currently recorded for this user.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {targetUserSessions.map((sess) => (
                <div
                  key={sess.id}
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: 'var(--bg-app)',
                    border: '1px solid var(--border-subtle)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px' }}>{sess.device_info || 'Web Client'}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Created: {new Date(sess.created_at).toLocaleString()} &bull; Expires: {new Date(sess.expires_at).toLocaleString()}
                    </div>
                  </div>

                  <button
                    className="btn btn-outline btn-sm"
                    style={{ color: '#f87171' }}
                    onClick={() => handleRevokeUserSession(sess.id)}
                  >
                    <Trash2 size={12} /> Revoke
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>

      {/* ========================================================================= */}
      {/* MODAL: CREATE / EDIT CUSTOM ROLE */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isRoleModalOpen}
        onClose={() => setIsRoleModalOpen(false)}
        title={editingRole ? `Edit Role: ${editingRole.name}` : 'Create Custom Security Role'}
        footer={
          <>
            <button className="btn btn-outline" onClick={() => setIsRoleModalOpen(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveRole}>
              {editingRole ? 'Save Changes' : 'Create Role'}
            </button>
          </>
        }
      >
        <form onSubmit={handleSaveRole}>
          <div className="form-group">
            <label className="form-label">Role Identifier Name *</label>
            <input
              type="text"
              required
              className="form-control"
              placeholder="e.g. LOGISTICS_LEAD"
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <input
              type="text"
              className="form-control"
              placeholder="e.g. Supervises multi-facility shipments and goods receipt"
              value={roleDesc}
              onChange={(e) => setRoleDesc(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Grant Permissions</label>
            <div style={{ maxHeight: '240px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {permissionModules.map((mod) => {
                const modPerms = permissions.filter((p) => p.module === mod);
                return (
                  <div key={mod} style={{ padding: '8px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontWeight: 700, fontSize: '12px', color: '#60a5fa', marginBottom: '6px' }}>
                      {mod} Module
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                      {modPerms.map((perm) => {
                        const checked = rolePermCodes.includes(perm.code);
                        return (
                          <label key={perm.id} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', cursor: 'pointer' }}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setRolePermCodes((prev) => [...prev, perm.code]);
                                } else {
                                  setRolePermCodes((prev) => prev.filter((c) => c !== perm.code));
                                }
                              }}
                            />
                            <span style={{ fontFamily: 'var(--font-mono)' }}>{perm.code}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </form>
      </Modal>
    </div>
  );
};
