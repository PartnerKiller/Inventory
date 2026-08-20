import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.settings import SystemSetting
from app.schemas.settings import SystemSettingResponse, SystemSettingUpdate
from app.services.audit_service import AuditService

router = APIRouter()

@router.get("", response_model=SystemSettingResponse)
async def get_system_settings(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("settings:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(SystemSetting).where(SystemSetting.tenant_id == tenant_id)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()

    if not setting:
        # Create default tenant setting
        setting = SystemSetting(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            company_name="AuraStock Enterprise",
            currency="USD",
            timezone="UTC",
            date_format="YYYY-MM-DD",
            allow_negative_stock=False,
            auto_allocate_on_confirm=False,
            require_grn_inspection=False,
            default_payment_terms="NET_30",
            default_tax_pct=0.0,
            require_po_approval=True,
            po_approval_threshold=1000.0
        )
        db.add(setting)
        await db.commit()
        await db.refresh(setting)

    return SystemSettingResponse(
        company_name=setting.company_name,
        company_email=setting.company_email,
        company_phone=setting.company_phone,
        logo_url=setting.logo_url,
        currency=setting.currency,
        timezone=setting.timezone,
        date_format=setting.date_format,
        default_warehouse_id=setting.default_warehouse_id,
        default_receiving_bin_id=setting.default_receiving_bin_id,
        default_damage_bin_id=setting.default_damage_bin_id,
        allow_negative_stock=setting.allow_negative_stock,
        auto_allocate_on_confirm=setting.auto_allocate_on_confirm,
        require_grn_inspection=setting.require_grn_inspection,
        default_payment_terms=setting.default_payment_terms,
        default_tax_pct=setting.default_tax_pct,
        require_po_approval=setting.require_po_approval,
        po_approval_threshold=setting.po_approval_threshold
    )

@router.put("", response_model=SystemSettingResponse)
async def update_system_settings(
    update_data: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("settings:write"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims.get("sub")

    stmt = select(SystemSetting).where(SystemSetting.tenant_id == tenant_id).with_for_update()
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()

    if not setting:
        setting = SystemSetting(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            company_name="AuraStock Enterprise"
        )
        db.add(setting)

    old_state = {
        "company_name": setting.company_name,
        "currency": setting.currency,
        "timezone": setting.timezone,
        "default_warehouse_id": setting.default_warehouse_id
    }

    # Safe updates only (allow_negative_stock is strictly immutable / protected)
    for field, val in update_data.model_dump(exclude_unset=True).items():
        if field == "allow_negative_stock":
            continue # Negative stock is strictly disallowed in core invariant
        setattr(setting, field, val)

    await AuditService.log_action(
        db=db,
        tenant_id=tenant_id,
        action="UPDATE",
        entity_type="SystemSetting",
        entity_id=setting.id,
        user_id=user_id,
        changes={"old": old_state, "new": update_data.model_dump(exclude_unset=True)}
    )

    await db.commit()
    await db.refresh(setting)

    return SystemSettingResponse(
        company_name=setting.company_name,
        company_email=setting.company_email,
        company_phone=setting.company_phone,
        logo_url=setting.logo_url,
        currency=setting.currency,
        timezone=setting.timezone,
        date_format=setting.date_format,
        default_warehouse_id=setting.default_warehouse_id,
        default_receiving_bin_id=setting.default_receiving_bin_id,
        default_damage_bin_id=setting.default_damage_bin_id,
        allow_negative_stock=setting.allow_negative_stock,
        auto_allocate_on_confirm=setting.auto_allocate_on_confirm,
        require_grn_inspection=setting.require_grn_inspection,
        default_payment_terms=setting.default_payment_terms,
        default_tax_pct=setting.default_tax_pct,
        require_po_approval=setting.require_po_approval,
        po_approval_threshold=setting.po_approval_threshold
    )
