from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.permissions import get_current_user_claims
from app.schemas.documents import DocumentType, DocumentPayload, BarcodeLabelRequest
from app.services.document_service import DocumentService

router = APIRouter()

def _check_doc_permission(doc_type: DocumentType, claims: dict) -> None:
    perms = set(claims.get("permissions", []))
    if "*" in perms:
        return

    perm_map = {
        DocumentType.PURCHASE_ORDER: "purchasing:read",
        DocumentType.GOODS_RECEIPT: "purchasing:read",
        DocumentType.SALES_ORDER: "sales:read",
        DocumentType.SALES_INVOICE: "sales:read",
        DocumentType.PACKING_SLIP: "sales:read",
        DocumentType.DELIVERY_NOTE: "sales:read",
        DocumentType.STOCK_TRANSFER: "ledger:read",
        DocumentType.STOCK_ADJUSTMENT: "ledger:read",
        DocumentType.SALES_RETURN: "sales:read",
    }
    required = perm_map.get(doc_type)
    if required and required not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Missing required permission '{required}' to view this document"
        )

@router.get("/{document_type}/{document_id}", response_model=DocumentPayload)
async def get_document_payload(
    document_type: DocumentType,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    _check_doc_permission(document_type, claims)
    return await DocumentService.get_document_payload(
        db=db,
        tenant_id=tenant_id,
        document_type=document_type,
        document_id=document_id,
        claims=claims
    )

@router.get("/{document_type}/{document_id}/pdf")
async def get_document_pdf(
    document_type: DocumentType,
    document_id: str,
    layout: str = Query("A4"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    _check_doc_permission(document_type, claims)
    payload = await DocumentService.get_document_payload(
        db=db,
        tenant_id=tenant_id,
        document_type=document_type,
        document_id=document_id,
        claims=claims
    )
    pdf_bytes = DocumentService.generate_pdf(payload, layout=layout)
    filename = f"{payload.header.document_number.replace('/', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{filename}\"",
            "Cache-Control": "no-cache"
        }
    )

@router.post("/barcodes/labels/pdf")
async def generate_barcode_labels_pdf(
    request: BarcodeLabelRequest,
    claims: dict = Depends(get_current_user_claims)
):
    perms = set(claims.get("permissions", []))
    if "*" not in perms and "inventory:read" not in perms:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: Missing 'inventory:read'")

    pdf_bytes = DocumentService.generate_barcode_labels_pdf(request)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=\"barcode_labels.pdf\"",
            "Cache-Control": "no-cache"
        }
    )
