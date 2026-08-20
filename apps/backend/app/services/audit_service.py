import uuid
from typing import Optional, Dict, Any
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog
from app.models.base import get_utc_now

class AuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        tenant_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        client_type: str = "WEB",
        changes: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        safe_changes = jsonable_encoder(changes) if changes else {}
        audit_entry = AuditLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            client_type=client_type,
            changes=safe_changes,
            timestamp=get_utc_now(),
        )
        db.add(audit_entry)
        return audit_entry
