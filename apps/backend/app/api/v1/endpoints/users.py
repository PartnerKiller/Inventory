import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from app.core.database import get_db
from app.core.permissions import require_permission, get_current_user_claims
from app.models.auth import User, Role, Permission, RefreshTokenSession
from app.models.warehouse import Warehouse
from app.core.security import get_password_hash
from app.schemas.auth import (
    UserCreate, UserUpdate, UserPasswordReset, UserProfileResponse,
    RoleResponse, RoleCreate, RoleUpdate, PermissionResponse, UserSessionResponse
)
from app.services.audit_service import AuditService

from sqlalchemy.orm import selectinload

router = APIRouter()

def _check_privilege_delegation(caller_claims: dict, requested_permissions: set) -> None:
    caller_perms = set(caller_claims.get("permissions", []))
    if "*" in caller_perms:
        return
    unauthorized_perms = requested_permissions - caller_perms
    if unauthorized_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Privilege escalation prevented: cannot grant permissions you do not possess ({', '.join(sorted(unauthorized_perms))})"
        )

# ============================================================================
# ROLES & PERMISSIONS (Static subpaths declared first)
# ============================================================================

@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("roles:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(Role)
        .options(selectinload(Role.permissions))
        .where(or_(Role.tenant_id == tenant_id, Role.is_system == True), Role.is_deleted == False)
    )
    res = await db.execute(stmt)
    roles = res.scalars().all()

    return [
        RoleResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            permissions=[p.code for p in r.permissions]
        )
        for r in roles
    ]

@router.post("/roles", response_model=RoleResponse)
async def create_role(
    role_in: RoleCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("roles:write"))
):
    tenant_id = claims["tenant_id"]
    _check_privilege_delegation(claims, set(role_in.permission_codes))

    assigned_perms = []
    if role_in.permission_codes:
        perm_stmt = select(Permission).where(Permission.code.in_(role_in.permission_codes))
        perm_res = await db.execute(perm_stmt)
        assigned_perms = list(perm_res.scalars().all())

    role = Role(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=role_in.name.strip(),
        description=role_in.description,
        is_system=False,
        permissions=assigned_perms
    )
    db.add(role)

    await db.commit()
    await db.refresh(role)

    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=[p.code for p in role.permissions]
    )

@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    role_in: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("roles:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.id == role_id, Role.tenant_id == tenant_id)
        .with_for_update()
    )
    res = await db.execute(stmt)
    role = res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot modify built-in system role")

    if role_in.permission_codes is not None:
        _check_privilege_delegation(claims, set(role_in.permission_codes))
        perm_stmt = select(Permission).where(Permission.code.in_(role_in.permission_codes))
        perm_res = await db.execute(perm_stmt)
        role.permissions = list(perm_res.scalars().all())

    if role_in.name:
        role.name = role_in.name.strip()
    if role_in.description is not None:
        role.description = role_in.description

    await db.commit()
    await db.refresh(role)

    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=[p.code for p in role.permissions]
    )

@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("roles:read"))
):
    stmt = select(Permission).order_by(Permission.module.asc(), Permission.code.asc())
    res = await db.execute(stmt)
    perms = res.scalars().all()

    return [
        PermissionResponse(
            id=p.id,
            code=p.code,
            module=p.module,
            description=p.description
        )
        for p in perms
    ]

# ============================================================================
# USERS CRUD
# ============================================================================

@router.get("", response_model=List[UserProfileResponse])
async def list_users(
    q: Optional[str] = Query(None),
    role_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(User).where(User.tenant_id == tenant_id, User.is_deleted == False)

    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)

    if q:
        pat = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(pat), User.full_name.ilike(pat)))

    res = await db.execute(stmt)
    users = res.scalars().all()

    out = []
    for u in users:
        role_names = [r.name for r in u.roles]
        role_ids = [r.id for r in u.roles]
        perms = list({p.code for r in u.roles for p in r.permissions})
        wh_scopes = [w.id for w in u.warehouses]

        if role_id and role_id not in role_ids:
            continue

        out.append(UserProfileResponse(
            id=u.id,
            tenant_id=u.tenant_id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            roles=role_names,
            role_ids=role_ids,
            permissions=perms,
            warehouse_scopes=wh_scopes,
            last_login_at=u.last_login_at,
            created_at=u.created_at
        ))
    return out

@router.post("", response_model=UserProfileResponse)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    caller_id = claims.get("sub")

    # Check duplicate email
    stmt = select(User).where(User.email == user_in.email.strip().lower())
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate roles & delegation privileges
    assigned_roles = []
    requested_perms = set()
    if user_in.role_ids:
        roles_stmt = select(Role).where(Role.id.in_(user_in.role_ids))
        roles_res = await db.execute(roles_stmt)
        assigned_roles = roles_res.scalars().all()
        for r in assigned_roles:
            for p in r.permissions:
                requested_perms.add(p.code)

    _check_privilege_delegation(claims, requested_perms)

    # Validate warehouses
    assigned_warehouses = []
    if user_in.warehouse_ids:
        wh_stmt = select(Warehouse).where(Warehouse.id.in_(user_in.warehouse_ids), Warehouse.tenant_id == tenant_id)
        wh_res = await db.execute(wh_stmt)
        assigned_warehouses = wh_res.scalars().all()

    new_user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=user_in.email.strip().lower(),
        password_hash=get_password_hash(user_in.password),
        full_name=user_in.full_name.strip(),
        is_active=True,
        is_superuser=False,
        roles=list(assigned_roles),
        warehouses=list(assigned_warehouses)
    )
    db.add(new_user)

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="CREATE",
        entity_type="User",
        entity_id=new_user.id,
        user_id=caller_id,
        changes={"email": new_user.email, "roles": [r.name for r in assigned_roles]}
    )

    await db.commit()
    await db.refresh(new_user)

    return UserProfileResponse(
        id=new_user.id,
        tenant_id=new_user.tenant_id,
        email=new_user.email,
        full_name=new_user.full_name,
        is_active=new_user.is_active,
        is_superuser=new_user.is_superuser,
        roles=[r.name for r in new_user.roles],
        role_ids=[r.id for r in new_user.roles],
        permissions=list(requested_perms),
        warehouse_scopes=[w.id for w in new_user.warehouses],
        last_login_at=new_user.last_login_at,
        created_at=new_user.created_at
    )

@router.get("/{user_id}", response_model=UserProfileResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_deleted == False)
    res = await db.execute(stmt)
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    wh_scopes = [w.id for w in u.warehouses]

    return UserProfileResponse(
        id=u.id,
        tenant_id=u.tenant_id,
        email=u.email,
        full_name=u.full_name,
        is_active=u.is_active,
        is_superuser=u.is_superuser,
        roles=[r.name for r in u.roles],
        role_ids=[r.id for r in u.roles],
        permissions=list({p.code for r in u.roles for p in r.permissions}),
        warehouse_scopes=wh_scopes,
        last_login_at=u.last_login_at,
        created_at=u.created_at
    )

@router.put("/{user_id}", response_model=UserProfileResponse)
async def update_user(
    user_id: str,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    caller_id = claims.get("sub")

    stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_deleted == False).with_for_update()
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_in.full_name is not None:
        user.full_name = user_in.full_name.strip()

    if user_in.is_active is not None:
        user.is_active = user_in.is_active
        if not user.is_active:
            # Revoke all sessions on deactivation
            await db.execute(
                update(RefreshTokenSession)
                .where(RefreshTokenSession.user_id == user.id)
                .values(is_revoked=True)
            )

    if user_in.role_ids is not None:
        roles_stmt = select(Role).where(Role.id.in_(user_in.role_ids))
        roles_res = await db.execute(roles_stmt)
        assigned_roles = roles_res.scalars().all()

        requested_perms = {p.code for r in assigned_roles for p in r.permissions}
        _check_privilege_delegation(claims, requested_perms)

        user.roles = list(assigned_roles)

    if user_in.warehouse_ids is not None:
        wh_stmt = select(Warehouse).where(Warehouse.id.in_(user_in.warehouse_ids), Warehouse.tenant_id == tenant_id)
        wh_res = await db.execute(wh_stmt)
        user.warehouses = list(wh_res.scalars().all())

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="UPDATE",
        entity_type="User",
        entity_id=user.id,
        user_id=caller_id,
        changes={"full_name": user.full_name, "is_active": user.is_active, "roles": [r.name for r in user.roles]}
    )

    await db.commit()
    await db.refresh(user)

    return UserProfileResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[r.name for r in user.roles],
        role_ids=[r.id for r in user.roles],
        permissions=list({p.code for r in user.roles for p in r.permissions}),
        warehouse_scopes=[w.id for w in user.warehouses],
        last_login_at=user.last_login_at,
        created_at=user.created_at
    )

@router.post("/{user_id}/activate", response_model=UserProfileResponse)
async def activate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id).with_for_update()
    user_res = await db.execute(user_stmt)
    u = user_res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    u.is_active = True
    await db.commit()
    await db.refresh(u)
    return await get_user(user_id, db, claims)

@router.post("/{user_id}/deactivate", response_model=UserProfileResponse)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id).with_for_update()
    user_res = await db.execute(user_stmt)
    u = user_res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    u.is_active = False
    # Revoke all active sessions
    await db.execute(
        update(RefreshTokenSession)
        .where(RefreshTokenSession.user_id == u.id)
        .values(is_revoked=True)
    )
    await db.commit()
    await db.refresh(u)
    return await get_user(user_id, db, claims)

@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    reset_in: UserPasswordReset,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    caller_id = claims.get("sub")

    user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id).with_for_update()
    user_res = await db.execute(user_stmt)
    u = user_res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    u.password_hash = get_password_hash(reset_in.new_password)
    # Revoke existing sessions upon password reset for security
    await db.execute(
        update(RefreshTokenSession)
        .where(RefreshTokenSession.user_id == u.id)
        .values(is_revoked=True)
    )

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="RESET_PASSWORD",
        entity_type="User",
        entity_id=u.id,
        user_id=caller_id,
        changes={"status": "password_reset"}
    )
    await db.commit()
    return {"message": f"Password for user {u.email} successfully reset."}

# ============================================================================
# USER SESSIONS (ADMIN VIEW & REVOCATION)
# ============================================================================

@router.get("/{user_id}/sessions", response_model=List[UserSessionResponse])
async def list_user_sessions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        select(RefreshTokenSession)
        .where(
            RefreshTokenSession.user_id == user_id,
            RefreshTokenSession.tenant_id == tenant_id,
            RefreshTokenSession.is_revoked == False
        )
        .order_by(RefreshTokenSession.created_at.desc())
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    return [
        UserSessionResponse(
            id=s.id,
            user_id=s.user_id,
            device_info=s.device_info,
            created_at=s.created_at,
            expires_at=s.expires_at,
            is_current=False
        )
        for s in sessions
    ]

@router.delete("/{user_id}/sessions/{session_id}")
async def revoke_user_session(
    user_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("users:write"))
):
    tenant_id = claims["tenant_id"]
    stmt = (
        update(RefreshTokenSession)
        .where(
            RefreshTokenSession.id == session_id,
            RefreshTokenSession.user_id == user_id,
            RefreshTokenSession.tenant_id == tenant_id
        )
        .values(is_revoked=True)
    )
    res = await db.execute(stmt)
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return {"message": "Session revoked"}
