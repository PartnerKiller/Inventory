import io
import barcode
from barcode.writer import ImageWriter
import qrcode
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.item import Barcode, ItemVariant, Item
from app.models.ledger import StockBalanceCache
from app.schemas.item import BarcodeLookupResponse

class BarcodeService:
    @staticmethod
    async def lookup_barcode(db: AsyncSession, tenant_id: str, barcode_val: str) -> BarcodeLookupResponse:
        clean_code = barcode_val.strip()
        
        # 1. Search Barcode entity within tenant
        stmt = (
            select(Barcode, ItemVariant, Item)
            .join(ItemVariant, Barcode.item_variant_id == ItemVariant.id)
            .join(Item, ItemVariant.item_id == Item.id)
            .where(
                Barcode.barcode_value == clean_code,
                Item.tenant_id == tenant_id,
                Item.is_deleted == False
            )
        )
        res = await db.execute(stmt)
        row = res.first()

        # 2. If not found by barcode value, fallback to SKU lookup within tenant
        if not row:
            sku_stmt = (
                select(ItemVariant, Item)
                .join(Item, ItemVariant.item_id == Item.id)
                .where(
                    Item.tenant_id == tenant_id,
                    Item.is_deleted == False,
                    (ItemVariant.variant_sku == clean_code) | (Item.sku == clean_code)
                )
            )
            sku_res = await db.execute(sku_stmt)
            sku_row = sku_res.first()
            if sku_row:
                variant, item = sku_row
                stock_stmt = select(StockBalanceCache.quantity_on_hand).where(
                    StockBalanceCache.item_variant_id == variant.id
                )
                stock_res = await db.execute(stock_stmt)
                stock_sum = sum([r[0] for r in stock_res.fetchall()])
                return BarcodeLookupResponse(
                    found=True,
                    barcode_value=clean_code,
                    item_id=item.id,
                    item_sku=item.sku,
                    item_name=item.name,
                    variant_id=variant.id,
                    variant_sku=variant.variant_sku,
                    variant_name=variant.variant_name,
                    cost_price=float(variant.cost_price),
                    selling_price=float(variant.selling_price),
                    current_stock=float(stock_sum)
                )
            return BarcodeLookupResponse(found=False, barcode_value=clean_code)

        barcode_obj, variant, item = row
        stock_stmt = select(StockBalanceCache.quantity_on_hand).where(
            StockBalanceCache.item_variant_id == variant.id
        )
        stock_res = await db.execute(stock_stmt)
        stock_sum = sum([r[0] for r in stock_res.fetchall()])

        return BarcodeLookupResponse(
            found=True,
            barcode_value=clean_code,
            item_id=item.id,
            item_sku=item.sku,
            item_name=item.name,
            variant_id=variant.id,
            variant_sku=variant.variant_sku,
            variant_name=variant.variant_name,
            cost_price=float(variant.cost_price),
            selling_price=float(variant.selling_price),
            current_stock=float(stock_sum)
        )

    @staticmethod
    def generate_barcode_image(value: str, symbology: str = "code128") -> bytes:
        sym = symbology.lower()
        if sym in ["qr", "qrcode"]:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=2,
            )
            qr.add_data(value)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        
        try:
            code_class = barcode.get_barcode_class('code128')
            writer = ImageWriter()
            bc = code_class(value, writer=writer)
            buf = io.BytesIO()
            bc.write(buf)
            return buf.getvalue()
        except Exception:
            qr = qrcode.make(value)
            buf = io.BytesIO()
            qr.save(buf, format="PNG")
            return buf.getvalue()
