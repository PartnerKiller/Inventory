import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.sales import PriceList, PriceListItem, PriceListTier, CustomerPriceList, Customer
from app.models.item import ItemVariant, Item
from app.schemas.pricing import (
    PriceListCreate,
    PriceListUpdate,
    PriceListItemCreate,
    PriceListTierCreate,
    PriceResolutionResponse
)
from app.services.audit_service import AuditService

class PricingService:
    @staticmethod
    async def create_price_list(
        db: AsyncSession,
        tenant_id: str,
        pl_in: PriceListCreate,
        user_id: Optional[str] = None
    ) -> PriceList:
        code_clean = pl_in.code.upper().strip()
        dup = (await db.execute(
            select(PriceList).where(PriceList.tenant_id == tenant_id, PriceList.code == code_clean, PriceList.is_deleted == False)
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=400, detail=f"Price list code '{code_clean}' already exists")

        if pl_in.is_default:
            # Unset existing default
            existing_defaults = (await db.execute(
                select(PriceList).where(PriceList.tenant_id == tenant_id, PriceList.is_default == True)
            )).scalars().all()
            for ed in existing_defaults:
                ed.is_default = False

        pl = PriceList(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            code=code_clean,
            name=pl_in.name.strip(),
            currency=pl_in.currency.upper(),
            valid_from=pl_in.valid_from or get_utc_now(),
            valid_to=pl_in.valid_to,
            is_active=pl_in.is_active,
            is_default=pl_in.is_default,
            notes=pl_in.notes
        )
        db.add(pl)

        await AuditService.log_action(
            db=db,
            tenant_id=tenant_id,
            action="CREATE",
            entity_type="PriceList",
            entity_id=pl.id,
            user_id=user_id,
            changes={"code": code_clean, "currency": pl.currency}
        )

        await db.commit()
        await db.refresh(pl)
        return pl

    @staticmethod
    async def add_or_update_price_list_item(
        db: AsyncSession,
        tenant_id: str,
        price_list_id: str,
        item_in: PriceListItemCreate,
        user_id: Optional[str] = None
    ) -> PriceListItem:
        pl = (await db.execute(
            select(PriceList).where(PriceList.id == price_list_id, PriceList.tenant_id == tenant_id, PriceList.is_deleted == False)
        )).scalar_one_or_none()
        if not pl:
            raise HTTPException(status_code=404, detail="Price list not found")

        # Verify variant exists
        variant = (await db.execute(
            select(ItemVariant).where(ItemVariant.id == item_in.item_variant_id)
        )).scalar_one_or_none()
        if not variant:
            raise HTTPException(status_code=404, detail="Item variant not found")

        # Check existing item
        item_stmt = select(PriceListItem).where(
            PriceListItem.price_list_id == pl.id,
            PriceListItem.item_variant_id == item_in.item_variant_id
        )
        item_obj = (await db.execute(item_stmt)).scalar_one_or_none()

        if not item_obj:
            item_obj = PriceListItem(
                id=str(uuid.uuid4()),
                price_list_id=pl.id,
                item_variant_id=item_in.item_variant_id,
                base_price=item_in.base_price,
                min_price=item_in.min_price
            )
            db.add(item_obj)
            await db.flush()
        else:
            item_obj.base_price = item_in.base_price
            item_obj.min_price = item_in.min_price

        # Add volume tiers if provided
        if item_in.tiers is not None:
            # Clear old tiers
            del_stmt = select(PriceListTier).where(PriceListTier.price_list_item_id == item_obj.id)
            old_tiers = (await db.execute(del_stmt)).scalars().all()
            for ot in old_tiers:
                await db.delete(ot)

            for tier_in in item_in.tiers:
                tier = PriceListTier(
                    id=str(uuid.uuid4()),
                    price_list_item_id=item_obj.id,
                    min_quantity=tier_in.min_quantity,
                    unit_price=tier_in.unit_price,
                    discount_pct=tier_in.discount_pct or Decimal("0.0")
                )
                db.add(tier)

        await db.commit()
        await db.refresh(item_obj)
        return item_obj

    @staticmethod
    async def assign_customer_price_list(
        db: AsyncSession,
        tenant_id: str,
        customer_id: str,
        price_list_id: str,
        priority: int = 1,
        user_id: Optional[str] = None
    ) -> CustomerPriceList:
        cust = (await db.execute(
            select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not cust:
            raise HTTPException(status_code=404, detail="Customer not found")

        pl = (await db.execute(
            select(PriceList).where(PriceList.id == price_list_id, PriceList.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not pl:
            raise HTTPException(status_code=404, detail="Price list not found")

        existing = (await db.execute(
            select(CustomerPriceList).where(
                CustomerPriceList.customer_id == customer_id,
                CustomerPriceList.price_list_id == price_list_id
            )
        )).scalar_one_or_none()

        if existing:
            existing.priority = priority
            cpl = existing
        else:
            cpl = CustomerPriceList(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                customer_id=customer_id,
                price_list_id=price_list_id,
                priority=priority,
                assigned_at=get_utc_now()
            )
            db.add(cpl)

        await db.commit()
        await db.refresh(cpl)
        return cpl

    @classmethod
    async def resolve_unit_price(
        cls,
        db: AsyncSession,
        tenant_id: str,
        customer_id: Optional[str],
        item_variant_id: str,
        quantity: Decimal = Decimal("1.0")
    ) -> PriceResolutionResponse:
        """
        Dynamic Price Resolution Hierarchy:
        1. Customer-specific price list + matching volume tier
        2. Customer-specific price list base price
        3. Default tenant price list + matching volume tier
        4. Default tenant price list base price
        5. Variant master catalog selling price
        """
        now = get_utc_now()
        qty = Decimal(str(quantity))

        # Variant lookup
        var_stmt = select(ItemVariant).where(ItemVariant.id == item_variant_id)
        variant = (await db.execute(var_stmt)).scalar_one_or_none()
        if not variant:
            raise HTTPException(status_code=404, detail="Item variant not found")

        # 1 & 2: Check Customer Price Lists (ordered by priority ASC)
        if customer_id:
            cpl_stmt = (
                select(PriceList)
                .join(CustomerPriceList, CustomerPriceList.price_list_id == PriceList.id)
                .where(
                    CustomerPriceList.customer_id == customer_id,
                    CustomerPriceList.tenant_id == tenant_id,
                    PriceList.is_active == True,
                    PriceList.is_deleted == False,
                    PriceList.valid_from <= now,
                    or_(PriceList.valid_to == None, PriceList.valid_to >= now)
                )
                .order_by(CustomerPriceList.priority.asc())
            )
            cpls = (await db.execute(cpl_stmt)).scalars().all()

            for pl in cpls:
                pli_stmt = select(PriceListItem).where(
                    PriceListItem.price_list_id == pl.id,
                    PriceListItem.item_variant_id == item_variant_id
                )
                pli = (await db.execute(pli_stmt)).scalar_one_or_none()
                if pli:
                    # Check volume tiers
                    tier_stmt = (
                        select(PriceListTier)
                        .where(PriceListTier.price_list_item_id == pli.id, PriceListTier.min_quantity <= qty)
                        .order_by(PriceListTier.min_quantity.desc())
                    )
                    tier = (await db.execute(tier_stmt)).scalars().first()
                    if tier:
                        unit_p = Decimal(str(tier.unit_price))
                        disc_p = Decimal(str(tier.discount_pct or 0.0))
                        eff_p = unit_p * (Decimal("1.0") - (disc_p / Decimal("100.0")))
                        return PriceResolutionResponse(
                            item_variant_id=variant.id,
                            unit_price=float(unit_p),
                            discount_pct=float(disc_p),
                            effective_unit_price=float(eff_p),
                            matched_rule="CUSTOMER_PRICE_LIST_TIER",
                            price_list_id=pl.id,
                            price_list_name=pl.name,
                            currency=pl.currency
                        )

                    unit_p = Decimal(str(pli.base_price))
                    return PriceResolutionResponse(
                        item_variant_id=variant.id,
                        unit_price=float(unit_p),
                        discount_pct=0.0,
                        effective_unit_price=float(unit_p),
                        matched_rule="CUSTOMER_PRICE_LIST",
                        price_list_id=pl.id,
                        price_list_name=pl.name,
                        currency=pl.currency
                    )

        # 3 & 4: Check Default Tenant Price List
        def_pl_stmt = select(PriceList).where(
            PriceList.tenant_id == tenant_id,
            PriceList.is_default == True,
            PriceList.is_active == True,
            PriceList.is_deleted == False,
            PriceList.valid_from <= now,
            or_(PriceList.valid_to == None, PriceList.valid_to >= now)
        )
        def_pl = (await db.execute(def_pl_stmt)).scalars().first()

        if def_pl:
            pli_stmt = select(PriceListItem).where(
                PriceListItem.price_list_id == def_pl.id,
                PriceListItem.item_variant_id == item_variant_id
            )
            pli = (await db.execute(pli_stmt)).scalar_one_or_none()
            if pli:
                tier_stmt = (
                    select(PriceListTier)
                    .where(PriceListTier.price_list_item_id == pli.id, PriceListTier.min_quantity <= qty)
                    .order_by(PriceListTier.min_quantity.desc())
                )
                tier = (await db.execute(tier_stmt)).scalars().first()
                if tier:
                    unit_p = Decimal(str(tier.unit_price))
                    disc_p = Decimal(str(tier.discount_pct or 0.0))
                    eff_p = unit_p * (Decimal("1.0") - (disc_p / Decimal("100.0")))
                    return PriceResolutionResponse(
                        item_variant_id=variant.id,
                        unit_price=float(unit_p),
                        discount_pct=float(disc_p),
                        effective_unit_price=float(eff_p),
                        matched_rule="DEFAULT_PRICE_LIST_TIER",
                        price_list_id=def_pl.id,
                        price_list_name=def_pl.name,
                        currency=def_pl.currency
                    )

                unit_p = Decimal(str(pli.base_price))
                return PriceResolutionResponse(
                    item_variant_id=variant.id,
                    unit_price=float(unit_p),
                    discount_pct=0.0,
                    effective_unit_price=float(unit_p),
                    matched_rule="DEFAULT_PRICE_LIST",
                    price_list_id=def_pl.id,
                    price_list_name=def_pl.name,
                    currency=def_pl.currency
                )

        # 5: Fallback to variant master selling_price
        base_p = Decimal(str(variant.selling_price or 0.0))
        return PriceResolutionResponse(
            item_variant_id=variant.id,
            unit_price=float(base_p),
            discount_pct=0.0,
            effective_unit_price=float(base_p),
            matched_rule="VARIANT_BASE_PRICE",
            price_list_id=None,
            price_list_name=None,
            currency="USD"
        )
