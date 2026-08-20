# Phase 19 Design: Authentication Hardening, MFA/TOTP & SSO

## Executive Summary

Phase 19 designs a unified, enterprise-grade **Authentication Hardening, Multi-Factor Authentication (MFA/TOTP), and Single Sign-On (SSO)** architecture for the AuraStock ERP platform. It unifies identity primitives while strictly maintaining authorization boundaries between **Internal ERP Staff**, **B2B Customer Portal Users**, and **B2B Supplier Portal Users**.

### Core Guarantees:
1. **RFC 6238 TOTP Standard**: Cryptographically secure 160-bit Base32 secret generation, $\pm 1$ step clock skew tolerance, and single-use replay protection.
2. **Refresh Token Rotation & Reuse Detection**: Token families with automatic session destruction upon detection of replayed/compromised refresh tokens.
3. **Enterprise OIDC/SSO with PKCE**: Federated authentication with Okta, Azure AD, and Google Workspace, featuring CSRF state/nonce validation, domain matching, and account takeover prevention.
4. **Zero-Trust Session Invalidation**: Immediate session termination on password reset, MFA state change, role modification, or account deactivation.

---

## 1. Current Authentication & Identity Audit

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Current Identity Audit (Phases 1–18)                      │
├──────────────────────────┬──────────────────────────┬──────────────────────────────────┤
│ Internal ERP Users       │ B2B Portal Users         │ Client & API Sessions            │
├──────────────────────────┼──────────────────────────┼──────────────────────────────────┤
│ • Model: `User`          │ • Model: `PortalUser`    │ • `RefreshTokenSession` table    │
│ • Password: Argon2id     │ • `PortalUserMembership` │ • JWT Access Token (60 mins)     │
│ • RBAC: `Role`, `Perm`   │ • `PortalInvitation`     │ • Static refresh token           │
│ • Tenant Scoped          │ • Scaffolded MFA columns │ • Web & Tauri Desktop storage    │
│ • AuditLog on mutations  │ • Failed attempt counter │ • Rate limiter on `/login`       │
└──────────────────────────┴──────────────────────────┴──────────────────────────────────┘
```

### Identified Security Gaps in Current System:
1. **MFA/TOTP Incomplete**: Columns `mfa_secret` and `is_mfa_enabled` exist on `PortalUser`, but enrollment, QR generation, verification challenges, recovery codes, and internal user MFA are missing.
2. **Refresh Token Replay Vulnerability**: Current refresh tokens do not implement cryptographic family rotation with automatic reuse detection.
3. **Single Sign-On (SSO) Absent**: No federated identity provider integration (OIDC/SAML) for enterprise tenants.
4. **Session Invalidation Gaps**: Changing passwords or deactivating accounts does not immediately cascade to revoke all distributed tokens.

---

## 2. Phase 19 Target Architecture

```
                                  ┌──────────────────────────────┐
                                  │      Client Applications     │
                                  │ (Web App, Tauri Desktop, API)│
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │   Unified Security Gateway   │
                                  │ (Rate Limiting, WAF, Cors)   │
                                  └──────────────┬───────────────┘
                                                 │
         ┌───────────────────────────────────────┼───────────────────────────────────────┐
         ▼                                       ▼                                       ▼
┌──────────────────┐                   ┌──────────────────┐                    ┌──────────────────┐
│  Internal Auth   │                   │ Customer Portal  │                    │ Supplier Portal  │
│  (Staff/Admin)   │                   │ (B2B Customers)  │                    │ (B2B Suppliers)  │
└────────┬─────────┘                   └────────┬─────────┘                    └────────┬─────────┘
         │                                      │                                       │
         └──────────────────────────────────────┼───────────────────────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │       Core Identity & Security Engine        │
                         ├──────────────────────────────────────────────┤
                         │ • RFC 6238 TOTP Engine & QR Generator        │
                         │ • Single-Use Hashed Recovery Code Vault      │
                         │ • OIDC / SAML 2.0 Identity Broker with PKCE  │
                         │ • Token Family Rotation & Reuse Detection    │
                         │ • Progressive Lockout & Brute-Force Guard    │
                         │ • Distributed Session Revocation Engine      │
                         │ • Security Event Auditing Bus                │
                         └──────────────────────────────────────────────┘
```

---

## 3. MFA / TOTP Subsystem (RFC 6238)

### 3.1 Enrollment & Activation Flow
```
User (Client)                     Auth API / Security Engine                   Database / Vault
     │                                        │                                        │
     │ 1. POST /auth/mfa/enroll               │                                        │
     ├───────────────────────────────────────►│                                        │
     │                                        │ 2. Generate 160-bit Secret             │
     │                                        │ 3. Generate 10 Backup Codes            │
     │                                        │ 4. Hash Backup Codes (Argon2)          │
     │                                        │ 5. Save pending state                  │
     │                                        ├───────────────────────────────────────►│
     │ 6. Return QR URI + Raw Backup Codes    │                                        │
     │◄───────────────────────────────────────┤                                        │
     │                                        │                                        │
     │ 7. POST /auth/mfa/verify-activate      │                                        │
     │    { "totp_code": "123456" }           │                                        │
     ├───────────────────────────────────────►│                                        │
     │                                        │ 8. Validate code (±1 timestep)         │
     │                                        │ 9. Set is_mfa_enabled = True           │
     │                                        ├───────────────────────────────────────►│
     │ 10. MFA Activated + Security Logged    │                                        │
     │◄───────────────────────────────────────┤                                        │
```

### 3.2 Authentication Challenge Flow
1. **Step 1 (Primary Auth)**: User submits email + password (or completes SSO).
2. **Step 2 (MFA Check)**: If `is_mfa_enabled == True`:
   - System returns `HTTP 200` with `{"mfa_required": true, "mfa_token": "<ephemeral_jwt>"}`.
   - Ephemeral token is signed with `scope: "mfa:challenge"`, expires in 5 minutes, and cannot access business APIs.
3. **Step 3 (MFA Verification)**:
   - User submits `POST /auth/mfa/challenge` with `mfa_token` and `totp_code` (or `recovery_code`).
   - If TOTP code is valid (and not in replay cache): issues full access & refresh token pair.
   - If recovery code is valid: marks recovery code as consumed, logs security event, and issues token pair.

---

## 4. Session Security & Refresh Token Rotation

### 4.1 Cryptographic Token Families & Reuse Detection
```
                    ┌─────────────────────────┐
                    │ Login: Issues Refresh T1│
                    └────────────┬────────────┘
                                 │
                     (Client requests refresh with T1)
                                 ▼
                    ┌─────────────────────────┐
                    │ T1 marked USED          │
                    │ Issues Refresh T2       │
                    └────────────┬────────────┘
                                 │
       ┌─────────────────────────┴─────────────────────────┐
       │ (Normal Refresh: Presents T2)                     │ (Theft/Replay: Attacker presents T1)
       ▼                                                   ▼
┌─────────────────────────┐                         ┌───────────────────────────────────────┐
│ T2 marked USED          │                         │ REUSE DETECTED!                       │
│ Issues Refresh T3       │                         │ • Entire Token Family Revoked         │
│ Session continues       │                         │ • Security Alert Dispatched           │
└─────────────────────────┘                         │ • User Forced to Re-Authenticate      │
                                                    └───────────────────────────────────────┘
```

### 4.2 Invalidation Matrix

| Trigger Event | Current Session | Other Active Sessions of User | Refresh Tokens |
| :--- | :---: | :---: | :---: |
| **Normal Logout** | Revoked | Preserved | Current Revoked |
| **Global Logout ("Logout all devices")** | Revoked | Revoked | All Revoked |
| **Password Changed / Reset** | Revoked | Revoked | All Revoked |
| **MFA Enabled / Disabled / Reset** | Revoked | Revoked | All Revoked |
| **User Deactivated / Role Modified** | Revoked | Revoked | All Revoked |
| **Refresh Token Reuse Detected** | Revoked | Revoked | All Revoked |

---

## 5. Enterprise OIDC / SAML Single Sign-On (SSO)

### 5.1 OIDC Authorization Code Flow with PKCE
- **PKCE**: Client generates `code_verifier` (cryptographic random string) and `code_challenge = BASE64URL(SHA256(code_verifier))`.
- **State & Nonce**: High-entropy random strings preventing CSRF and ID token replay.
- **SSO Broker**:
  - `GET /auth/sso/initiate?tenant_domain=acme.com`: Looks up tenant SSO config, redirects to IdP with client ID, scope (`openid profile email`), state, nonce, and PKCE challenge.
  - `POST /auth/sso/callback`: Exchanges authorization code with PKCE verifier, verifies ID token signature & claims (Issuer, Audience, Nonce), and maps claims.
- **Account Takeover Prevention**:
  - Automatic account linking is permitted **only** if the email domain matches the tenant's verified SSO domain and the IdP asserts `email_verified: true`.

---

## 6. Proposed Data Models (`apps/backend/app/models/auth_security.py`)

```python
class UserMFASecurity(Base, BaseModelMixin):
    __tablename__ = "user_mfa_security"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_type = Column(String(30), nullable=False) # INTERNAL, PORTAL_CUSTOMER, PORTAL_SUPPLIER
    user_id = Column(String(36), nullable=False, index=True)
    is_mfa_enabled = Column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted = Column(Text, nullable=True)
    last_totp_timestep = Column(Integer, default=0, nullable=False) # Replay protection
    enrolled_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_type", "user_id", name="uq_user_mfa"),
    )

class MFARecoveryCode(Base, BaseModelMixin):
    __tablename__ = "mfa_recovery_codes"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

class UserSessionRecord(Base, BaseModelMixin):
    __tablename__ = "user_sessions"

    tenant_id = Column(String(36), nullable=False, index=True)
    user_type = Column(String(30), nullable=False)
    user_id = Column(String(36), nullable=False, index=True)
    family_id = Column(String(36), nullable=False, index=True) # Cryptographic token family
    refresh_token_hash = Column(String(255), unique=True, nullable=False, index=True)
    device_name = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    status = Column(String(20), default="ACTIVE", nullable=False) # ACTIVE, USED, REVOKED
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_active_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

class SSOConfiguration(Base, BaseModelMixin):
    __tablename__ = "sso_configurations"

    tenant_id = Column(String(36), nullable=False, unique=True, index=True)
    domain = Column(String(100), nullable=False, unique=True, index=True) # e.g. acme.com
    provider_type = Column(String(30), default="OIDC", nullable=False) # OIDC, SAML2
    issuer_url = Column(String(2048), nullable=False)
    client_id = Column(String(255), nullable=False)
    client_secret_encrypted = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    allow_password_fallback = Column(Boolean, default=True, nullable=False)
```

---

## 7. Threat Model & Security Mitigations

| Threat Vector | Severity | Mitigation Strategy |
| :--- | :---: | :--- |
| **Credential Stuffing / Brute Force** | Critical | Progressive exponential delay after 3 failed logins; strict 15-minute account lockout after 5 consecutive failures. |
| **Token Theft & Replay** | Critical | Refresh token family rotation with automatic revocation of all descendant sessions if an already-used token is replayed. |
| **MFA Bypass** | Critical | Primary authentication returns an ephemeral, non-authoritative token with scope `mfa:challenge`. Business APIs strictly verify `mfa:complete` claim. |
| **TOTP Code Replay** | High | Tracks `last_totp_timestep` per user; rejects duplicate submissions of the same 6-digit code within the 30-second window. |
| **SSO Account Takeover** | Critical | Strict domain validation against tenant whitelist; rejects account linking if email is unverified or domain mismatch occurs. |
| **Password Reset Replay** | High | Single-use cryptographically random token hashed in DB with 15-minute TTL; marks token consumed upon reset and revokes all active sessions. |

---

## 8. Verification & Test Strategy

1. **RFC 6238 TOTP Lifecycle**: Enroll $\to$ verify code $\to$ activate $\to$ challenge during login $\to$ verify clock skew ($\pm 30\text{s}$) $\to$ reject replay of same code.
2. **Recovery Codes**: Test single-use consumption of recovery code; verify consumed code cannot be reused.
3. **Token Family Rotation & Reuse Detection**: Refresh session normally (T1 $\to$ T2); then submit consumed T1 $\implies$ verify entire session family is revoked.
4. **Global Invalidation Cascades**:
   - Password change $\implies$ all active sessions revoked.
   - MFA state change $\implies$ all active sessions revoked.
   - User deactivation $\implies$ all active sessions revoked.
5. **SSO PKCE & State/Nonce Integrity**: Test OIDC callback with valid state/nonce; test rejection of tampered state or expired nonce.
6. **Progressive Account Lockout**: 5 failed login attempts $\implies$ account locked; 6th attempt rejected even with valid password until lockout expires.
7. **Zero Physical Inventory / Costing Mutation**: Assert auth security mutations cause 0 changes to `StockLedgerTransaction` or `CostLayer`.
