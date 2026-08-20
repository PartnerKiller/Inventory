from fastapi import APIRouter, Depends, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.permissions import require_permission
from app.schemas.item import BarcodeLookupResponse
from app.services.barcode_service import BarcodeService

router = APIRouter()

@router.post("/lookup", response_model=BarcodeLookupResponse)
async def lookup_barcode(
    barcode_payload: dict,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("inventory:read"))
):
    code = barcode_payload.get("barcode", "")
    tenant_id = claims["tenant_id"]
    return await BarcodeService.lookup_barcode(db, tenant_id, code)

@router.get("/image/{barcode_value}")
async def get_barcode_image(
    barcode_value: str,
    symbology: str = Query("code128", description="code128, qr, datamatrix"),
    claims: dict = Depends(require_permission("inventory:read"))
):
    img_bytes = BarcodeService.generate_barcode_image(barcode_value, symbology)
    return Response(content=img_bytes, media_type="image/png")
