from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, EmailStr

class LoginRequest(BaseModel):
    email: str
    password: str

class UserProfileResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    roles: List[str] = []
    role_ids: List[str] = []
    permissions: List[str] = []
    warehouse_scopes: List[str] = []
    last_login_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: UserProfileResponse

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role_ids: List[str] = []
    warehouse_ids: List[str] = []

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[List[str]] = None
    warehouse_ids: Optional[List[str]] = None

class UserPasswordReset(BaseModel):
    new_password: str

class UserSessionResponse(BaseModel):
    id: str
    user_id: str
    device_info: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False

class PermissionResponse(BaseModel):
    id: str
    code: str
    module: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permission_codes: List[str] = []

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_codes: Optional[List[str]] = None

class RoleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_system: bool
    permissions: List[str] = []

    model_config = ConfigDict(from_attributes=True)
