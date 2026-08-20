import pytest
import uuid
import base64
import hashlib
from typing import Tuple, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.edms import DocumentAttachment, DocumentSignOff
from app.schemas.edms import (
    DocumentAttachmentCreate,
    DocumentSignOffRequest,
    DocumentSignOffExecute
)
from app.services.edms_service import EDMSService

# ============================================================================
# 1. ATTACHMENT UPLOAD, SHA-256 & VERSIONING
# ============================================================================

@pytest.mark.asyncio
async def test_document_upload_sha256_and_versioning(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    raw_pdf_v1 = b"%PDF-1.4 Authoritative Vendor Contract Revision 1"
    b64_v1 = base64.b64encode(raw_pdf_v1).decode("utf-8")
    expected_hash_v1 = hashlib.sha256(raw_pdf_v1).hexdigest()

    # 1. Upload Version 1
    doc_v1 = await EDMSService.upload_attachment(
        db=db_session,
        tenant_id=tenant_id,
        doc_in=DocumentAttachmentCreate(
            entity_type="PURCHASE_ORDER",
            entity_id=entity_id,
            file_name="Signed_Contract.pdf",
            mime_type="application/pdf",
            file_content_base64=b64_v1
        ),
        user_id=user_id
    )

    assert doc_v1.version == 1
    assert doc_v1.is_latest is True
    assert doc_v1.sha256_hash == expected_hash_v1
    assert doc_v1.file_size == len(raw_pdf_v1)

    # 2. Upload Version 2 with modified content
    raw_pdf_v2 = b"%PDF-1.4 Authoritative Vendor Contract Revision 2 with Addendum"
    b64_v2 = base64.b64encode(raw_pdf_v2).decode("utf-8")
    expected_hash_v2 = hashlib.sha256(raw_pdf_v2).hexdigest()

    doc_v2 = await EDMSService.upload_attachment(
        db=db_session,
        tenant_id=tenant_id,
        doc_in=DocumentAttachmentCreate(
            entity_type="PURCHASE_ORDER",
            entity_id=entity_id,
            file_name="Signed_Contract.pdf",
            mime_type="application/pdf",
            file_content_base64=b64_v2
        ),
        user_id=user_id
    )

    assert doc_v2.version == 2
    assert doc_v2.is_latest is True
    assert doc_v2.sha256_hash == expected_hash_v2

    # 3. Verify Version 1 is marked is_latest = False
    v1_reloaded = (await db_session.execute(select(DocumentAttachment).where(DocumentAttachment.id == doc_v1.id))).scalar_one()
    assert v1_reloaded.is_latest is False

# ============================================================================
# 2. CRYPTOGRAPHIC TAMPER VERIFICATION PROBE
# ============================================================================

@pytest.mark.asyncio
async def test_document_tamper_verification_probe(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    raw_pdf = b"%PDF-1.4 Customs Clearance Bill of Lading"
    b64_content = base64.b64encode(raw_pdf).decode("utf-8")

    doc = await EDMSService.upload_attachment(
        db=db_session,
        tenant_id=tenant_id,
        doc_in=DocumentAttachmentCreate(
            entity_type="GOODS_RECEIPT",
            entity_id=entity_id,
            file_name="Bill_of_Lading.pdf",
            mime_type="application/pdf",
            file_content_base64=b64_content
        ),
        user_id=user_id
    )

    # 1. Authentic file verification
    check1 = await EDMSService.verify_attachment_integrity(
        db=db_session, tenant_id=tenant_id, attachment_id=doc.id
    )
    assert check1.is_authentic is True
    assert check1.status == "VERIFIED_AUTHENTIC"

    # 2. Simulate byte tampering directly in the database
    tampered_bytes = b"%PDF-1.4 TAMPERED_FORGED_BILL_OF_LADING"
    tampered_b64 = base64.b64encode(tampered_bytes).decode("utf-8")
    
    doc_record = (await db_session.execute(select(DocumentAttachment).where(DocumentAttachment.id == doc.id))).scalar_one()
    doc_record.file_content_base64 = tampered_b64
    await db_session.commit()

    # 3. Check tamper detection
    check2 = await EDMSService.verify_attachment_integrity(
        db=db_session, tenant_id=tenant_id, attachment_id=doc.id
    )
    assert check2.is_authentic is False
    assert check2.status == "TAMPERED_OR_CORRUPT"

# ============================================================================
# 3. AUDIT COMPLIANCE SIGN-OFF WORKFLOWS
# ============================================================================

@pytest.mark.asyncio
async def test_audit_compliance_signoff_workflows(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())
    auditor_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    raw_pdf = b"%PDF-1.4 Annual SOX Audit Workpaper"
    b64_content = base64.b64encode(raw_pdf).decode("utf-8")

    doc = await EDMSService.upload_attachment(
        db=db_session,
        tenant_id=tenant_id,
        doc_in=DocumentAttachmentCreate(
            entity_type="JOURNAL_VOUCHER",
            entity_id=entity_id,
            file_name="SOX_Workpaper.pdf",
            mime_type="application/pdf",
            file_content_base64=b64_content
        ),
        user_id=user_id
    )

    # 1. Request Sign-Off
    sign_req = await EDMSService.request_sign_off(
        db=db_session,
        tenant_id=tenant_id,
        req=DocumentSignOffRequest(
            attachment_id=doc.id,
            sign_off_role="INTERNAL_AUDITOR",
            notes="Requires internal audit review and signature"
        )
    )
    assert sign_req.status == "PENDING"
    assert sign_req.sign_off_role == "INTERNAL_AUDITOR"

    # 2. Execute Sign-Off (Approval with Digital Signature)
    sign_exec = await EDMSService.execute_sign_off(
        db=db_session,
        tenant_id=tenant_id,
        req=DocumentSignOffExecute(
            sign_off_id=sign_req.id,
            status="SIGNED",
            notes="Reviewed and approved by internal auditor"
        ),
        signer_user_id=auditor_id
    )
    assert sign_exec.status == "SIGNED"
    assert sign_exec.digital_signature is not None
    assert sign_exec.signer_user_id == auditor_id
    assert sign_exec.signed_at is not None

    # 3. Idempotency / Double Sign-off guard -> Re-executing raises HTTP 400
    with pytest.raises(HTTPException) as exc_info:
        await EDMSService.execute_sign_off(
            db=db_session,
            tenant_id=tenant_id,
            req=DocumentSignOffExecute(
                sign_off_id=sign_req.id,
                status="SIGNED"
            ),
            signer_user_id=auditor_id
        )
    assert exc_info.value.status_code == 400
    assert "already finalized" in exc_info.value.detail
