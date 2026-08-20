import uuid
import hashlib
import hmac
import base64
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, update
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.edms import DocumentAttachment, DocumentSignOff
from app.schemas.edms import (
    DocumentAttachmentCreate,
    DocumentAttachmentResponse,
    DocumentIntegrityCheckResponse,
    DocumentSignOffRequest,
    DocumentSignOffExecute,
    DocumentSignOffResponse
)

class EDMSService:

    # ========================================================================
    # 1. ATTACHMENT UPLOAD, HASHING & VERSIONING
    # ========================================================================

    @staticmethod
    async def upload_attachment(
        db: AsyncSession,
        tenant_id: str,
        doc_in: DocumentAttachmentCreate,
        user_id: Optional[str] = None
    ) -> DocumentAttachmentResponse:
        # Validate and decode base64
        try:
            raw_bytes = base64.b64decode(doc_in.file_content_base64.encode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 document content")

        file_size = len(raw_bytes)
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Document cannot be empty")

        # Compute Cryptographic SHA-256 Checksum
        sha256_checksum = hashlib.sha256(raw_bytes).hexdigest()

        # Determine version
        existing_docs = (await db.execute(
            select(DocumentAttachment).where(
                DocumentAttachment.tenant_id == tenant_id,
                DocumentAttachment.entity_type == doc_in.entity_type.upper(),
                DocumentAttachment.entity_id == doc_in.entity_id,
                DocumentAttachment.file_name == doc_in.file_name
            )
        )).scalars().all()

        version = 1
        if existing_docs:
            version = max(d.version for d in existing_docs) + 1
            # Mark previous versions as not latest
            await db.execute(
                update(DocumentAttachment).where(
                    DocumentAttachment.tenant_id == tenant_id,
                    DocumentAttachment.entity_type == doc_in.entity_type.upper(),
                    DocumentAttachment.entity_id == doc_in.entity_id,
                    DocumentAttachment.file_name == doc_in.file_name
                ).values(is_latest=False)
            )

        attachment = DocumentAttachment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            entity_type=doc_in.entity_type.upper(),
            entity_id=doc_in.entity_id,
            file_name=doc_in.file_name,
            file_size=file_size,
            mime_type=doc_in.mime_type,
            sha256_hash=sha256_checksum,
            file_content_base64=doc_in.file_content_base64,
            version=version,
            is_latest=True,
            uploaded_by_user_id=user_id
        )
        db.add(attachment)
        await db.commit()
        await db.refresh(attachment)

        return DocumentAttachmentResponse(
            id=attachment.id,
            tenant_id=attachment.tenant_id,
            entity_type=attachment.entity_type,
            entity_id=attachment.entity_id,
            file_name=attachment.file_name,
            file_size=attachment.file_size,
            mime_type=attachment.mime_type,
            sha256_hash=attachment.sha256_hash,
            version=attachment.version,
            is_latest=attachment.is_latest,
            uploaded_by_user_id=attachment.uploaded_by_user_id,
            created_at=attachment.created_at
        )

    # ========================================================================
    # 2. CRYPTOGRAPHIC TAMPER VERIFICATION
    # ========================================================================

    @staticmethod
    async def verify_attachment_integrity(
        db: AsyncSession,
        tenant_id: str,
        attachment_id: str
    ) -> DocumentIntegrityCheckResponse:
        attachment = (await db.execute(
            select(DocumentAttachment).where(
                DocumentAttachment.id == attachment_id,
                DocumentAttachment.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Document attachment not found")

        try:
            raw_bytes = base64.b64decode(attachment.file_content_base64.encode("utf-8"))
            recomputed_hash = hashlib.sha256(raw_bytes).hexdigest()
            is_authentic = (recomputed_hash == attachment.sha256_hash)
        except Exception:
            is_authentic = False
            recomputed_hash = "CORRUPTED"

        return DocumentIntegrityCheckResponse(
            attachment_id=attachment.id,
            file_name=attachment.file_name,
            sha256_hash=attachment.sha256_hash,
            is_authentic=is_authentic,
            status="VERIFIED_AUTHENTIC" if is_authentic else "TAMPERED_OR_CORRUPT"
        )

    # ========================================================================
    # 3. COMPLIANCE AUDIT SIGN-OFF WORKFLOW
    # ========================================================================

    @staticmethod
    async def request_sign_off(
        db: AsyncSession,
        tenant_id: str,
        req: DocumentSignOffRequest
    ) -> DocumentSignOffResponse:
        attachment = (await db.execute(
            select(DocumentAttachment).where(
                DocumentAttachment.id == req.attachment_id,
                DocumentAttachment.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not attachment:
            raise HTTPException(status_code=404, detail="Document attachment not found")

        sign_off = DocumentSignOff(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            attachment_id=attachment.id,
            sign_off_role=req.sign_off_role.upper(),
            status="PENDING",
            notes=req.notes
        )
        db.add(sign_off)
        await db.commit()
        await db.refresh(sign_off)

        return DocumentSignOffResponse(
            id=sign_off.id,
            tenant_id=sign_off.tenant_id,
            attachment_id=sign_off.attachment_id,
            sign_off_role=sign_off.sign_off_role,
            signer_user_id=sign_off.signer_user_id,
            status=sign_off.status,
            digital_signature=sign_off.digital_signature,
            notes=sign_off.notes,
            signed_at=sign_off.signed_at,
            created_at=sign_off.created_at
        )

    @staticmethod
    async def execute_sign_off(
        db: AsyncSession,
        tenant_id: str,
        req: DocumentSignOffExecute,
        signer_user_id: str
    ) -> DocumentSignOffResponse:
        sign_off = (await db.execute(
            select(DocumentSignOff).where(
                DocumentSignOff.id == req.sign_off_id,
                DocumentSignOff.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not sign_off:
            raise HTTPException(status_code=404, detail="Sign-off request not found")

        if sign_off.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Sign-off already finalized with status {sign_off.status}")

        signed_at = get_utc_now()
        signature_data = f"{sign_off.attachment_id}:{signer_user_id}:{signed_at.isoformat()}"
        secret_key = settings.SECRET_KEY.encode("utf-8")
        digital_sig = hmac.new(secret_key, signature_data.encode("utf-8"), hashlib.sha256).hexdigest()

        sign_off.status = req.status.upper()
        sign_off.signer_user_id = signer_user_id
        sign_off.digital_signature = digital_sig if sign_off.status == "SIGNED" else None
        sign_off.notes = req.notes or sign_off.notes
        sign_off.signed_at = signed_at

        await db.commit()
        await db.refresh(sign_off)

        return DocumentSignOffResponse(
            id=sign_off.id,
            tenant_id=sign_off.tenant_id,
            attachment_id=sign_off.attachment_id,
            sign_off_role=sign_off.sign_off_role,
            signer_user_id=sign_off.signer_user_id,
            status=sign_off.status,
            digital_signature=sign_off.digital_signature,
            notes=sign_off.notes,
            signed_at=sign_off.signed_at,
            created_at=sign_off.created_at
        )
