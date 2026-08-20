import uuid
from decimal import Decimal
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, update
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.maintenance import MaintenanceSchedule, MaintenanceWorkOrder, MWOSparePart
from app.models.fixed_asset import FixedAsset
from app.models.advanced_manufacturing import WorkCenter
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.maintenance import (
    MaintenanceScheduleCreate,
    MaintenanceScheduleResponse,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderComplete,
    MaintenanceWorkOrderResponse,
    MWOSparePartResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService
from app.services.stock_engine import StockEngine

class MaintenanceService:

    # ========================================================================
    # 1. PREVENTIVE MAINTENANCE SCHEDULES
    # ========================================================================

    @staticmethod
    async def create_maintenance_schedule(
        db: AsyncSession,
        tenant_id: str,
        sched_in: MaintenanceScheduleCreate
    ) -> MaintenanceScheduleResponse:
        now = get_utc_now()
        next_due = now + timedelta(days=sched_in.frequency_days)

        schedule = MaintenanceSchedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            schedule_name=sched_in.schedule_name,
            asset_id=sched_in.asset_id,
            work_center_id=sched_in.work_center_id,
            schedule_type=sched_in.schedule_type.upper(),
            frequency_days=sched_in.frequency_days,
            next_due_at=next_due,
            is_active=True
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)

        return MaintenanceScheduleResponse(
            id=schedule.id,
            tenant_id=schedule.tenant_id,
            schedule_name=schedule.schedule_name,
            asset_id=schedule.asset_id,
            work_center_id=schedule.work_center_id,
            schedule_type=schedule.schedule_type,
            frequency_days=schedule.frequency_days,
            last_performed_at=schedule.last_performed_at,
            next_due_at=schedule.next_due_at,
            is_active=schedule.is_active,
            created_at=schedule.created_at
        )

    # ========================================================================
    # 2. MAINTENANCE WORK ORDER LIFECYCLE
    # ========================================================================

    @staticmethod
    async def create_maintenance_work_order(
        db: AsyncSession,
        tenant_id: str,
        mwo_in: MaintenanceWorkOrderCreate
    ) -> MaintenanceWorkOrderResponse:
        mwo_num = f"MWO-{uuid.uuid4().hex[:6].upper()}"

        mwo = MaintenanceWorkOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            mwo_number=mwo_num,
            schedule_id=mwo_in.schedule_id,
            asset_id=mwo_in.asset_id,
            work_center_id=mwo_in.work_center_id,
            assigned_technician_id=mwo_in.assigned_technician_id,
            priority=mwo_in.priority.upper(),
            expenditure_type=mwo_in.expenditure_type.upper(),
            useful_life_extension_months=mwo_in.useful_life_extension_months,
            status="DRAFT",
            scheduled_start_date=mwo_in.scheduled_start_date or get_utc_now(),
            notes=mwo_in.notes
        )
        db.add(mwo)

        if mwo_in.spare_parts:
            for sp in mwo_in.spare_parts:
                total_c = (sp.quantity_required * sp.unit_cost).quantize(Decimal("0.0001"))
                part = MWOSparePart(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    mwo_id=mwo.id,
                    item_variant_id=sp.item_variant_id,
                    warehouse_id=sp.warehouse_id,
                    location_bin_id=sp.location_bin_id,
                    quantity_required=sp.quantity_required,
                    quantity_consumed=Decimal("0.0"),
                    unit_cost=sp.unit_cost,
                    total_cost=total_c
                )
                db.add(part)

        await db.commit()
        await db.refresh(mwo)

        return await MaintenanceService._format_mwo_response(mwo)

    @staticmethod
    async def update_work_order_status(
        db: AsyncSession,
        tenant_id: str,
        mwo_id: str,
        new_status: str
    ) -> MaintenanceWorkOrderResponse:
        mwo = (await db.execute(
            select(MaintenanceWorkOrder).where(
                MaintenanceWorkOrder.id == mwo_id,
                MaintenanceWorkOrder.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not mwo:
            raise HTTPException(status_code=404, detail="Maintenance work order not found")

        valid_transitions = {
            "DRAFT": ["SCHEDULED", "CANCELLED"],
            "SCHEDULED": ["IN_PROGRESS", "CANCELLED"],
            "IN_PROGRESS": ["CANCELLED"] # COMPLETED handled by complete_maintenance_work_order
        }

        target = new_status.upper()
        if target not in valid_transitions.get(mwo.status, []):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid MWO state transition from {mwo.status} to {target}"
            )

        mwo.status = target
        await db.commit()
        await db.refresh(mwo)
        return await MaintenanceService._format_mwo_response(mwo)

    # ========================================================================
    # 3. COMPLETION, STOCK MUTATION & GL EXPENSE POSTING
    # ========================================================================

    @staticmethod
    async def complete_maintenance_work_order(
        db: AsyncSession,
        tenant_id: str,
        mwo_id: str,
        comp_in: MaintenanceWorkOrderComplete,
        user_id: Optional[str] = None
    ) -> MaintenanceWorkOrderResponse:
        mwo = (await db.execute(
            select(MaintenanceWorkOrder).where(
                MaintenanceWorkOrder.id == mwo_id,
                MaintenanceWorkOrder.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not mwo:
            raise HTTPException(status_code=404, detail="Maintenance work order not found")

        if mwo.status != "IN_PROGRESS":
            raise HTTPException(
                status_code=400,
                detail=f"Only IN_PROGRESS work orders can be completed (current: {mwo.status})"
            )

        completion_time = comp_in.actual_completion_date or get_utc_now()
        comp_date = completion_time.date() if isinstance(completion_time, datetime) else completion_time

        # Phase 22 Closed Accounting Period Guard
        from app.models.accounting_period import AccountingPeriod
        closed_period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.start_date <= comp_date,
                AccountingPeriod.end_date >= comp_date,
                AccountingPeriod.status.in_(["CLOSED", "FINALIZED"])
            )
        )).scalar_one_or_none()
        if closed_period:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot post maintenance completion in a {closed_period.status} accounting period ({closed_period.period_code})"
            )

        total_parts_cost = Decimal("0.0")

        # 1. Consume Spare Parts & Mutate Stock Ledger
        entries_data = []
        for sp in mwo.spare_parts:
            sp.quantity_consumed = sp.quantity_required
            line_cost = (sp.quantity_consumed * sp.unit_cost).quantize(Decimal("0.0001"))
            sp.total_cost = line_cost
            total_parts_cost += line_cost

            entries_data.append({
                "item_variant_id": sp.item_variant_id,
                "source_location_bin_id": sp.location_bin_id,
                "destination_location_bin_id": None,
                "quantity": sp.quantity_consumed,
                "unit_cost": sp.unit_cost
            })

        if entries_data:
            await StockEngine.post_transaction(
                db=db,
                tenant_id=tenant_id,
                transaction_type="STOCK_ADJUSTMENT",
                entries_data=entries_data,
                reference_doc_type="MAINTENANCE_WORK_ORDER",
                reference_doc_id=mwo.mwo_number,
                user_id=user_id,
                notes=f"Spare parts consumed for {mwo.mwo_number}"
            )

        # 2. Financial GL Posting & Capitalization
        jv_id = None
        if total_parts_cost > Decimal("0.0"):
            await GLService.seed_standard_chart_of_accounts(db, tenant_id)
            acc_1200 = (await db.execute(
                select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1200")
            )).scalar_one()

            if mwo.expenditure_type == "CAPITAL_IMPROVEMENT" and mwo.asset_id:
                # Capital Improvement: Dr 1500 Fixed Asset / Cr 1200 Inventory Asset
                acc_1500 = (await db.execute(
                    select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1500")
                )).scalar_one()

                jv_res = await GLService.post_journal_voucher(
                    db=db,
                    tenant_id=tenant_id,
                    voucher_in=JournalVoucherCreate(
                        voucher_date=completion_time,
                        source_document_type="ASSET_CAPITAL_IMPROVEMENT",
                        source_document_id=mwo.mwo_number,
                        notes=f"Capital improvement for asset on {mwo.mwo_number}",
                        lines=[
                            JournalEntryLineCreate(account_id=acc_1500.id, debit_amount=total_parts_cost, credit_amount=Decimal("0.0"), memo=f"Capitalized improvement on {mwo.mwo_number}"),
                            JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("0.0"), credit_amount=total_parts_cost, memo=f"Inventory capitalized into asset for {mwo.mwo_number}")
                        ]
                    ),
                    user_id=user_id
                )
                jv_id = jv_res.id

                # Recalculate Fixed Asset Carrying Cost and Depreciation
                from app.services.fixed_asset_service import FixedAssetService
                from app.schemas.fixed_asset import AssetImprovementCreate
                await FixedAssetService.apply_capital_improvement_and_recalculate_depreciation(
                    db=db,
                    tenant_id=tenant_id,
                    asset_id=mwo.asset_id,
                    improvement_in=AssetImprovementCreate(
                        improvement_name=f"Capital Improvement from {mwo.mwo_number}",
                        capitalized_amount=total_parts_cost,
                        useful_life_extension_months=mwo.useful_life_extension_months,
                        mwo_id=mwo.id
                    ),
                    user_id=user_id
                )

            else:
                # Ordinary Maintenance: Dr 6150 Maintenance Expense / Cr 1200 Inventory Asset
                acc_6150 = (await db.execute(
                    select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6150")
                )).scalar_one_or_none()
                if not acc_6150:
                    acc_6150 = GLAccount(
                        id=str(uuid.uuid4()), tenant_id=tenant_id, account_code="6150",
                        account_name="Equipment Maintenance & Repairs Expense", account_class="EXPENSE",
                        account_type="OPERATING_EXPENSE", currency="USD", normal_balance="DEBIT",
                        is_active=True, is_system=True
                    )
                    db.add(acc_6150)
                    await db.flush()

                jv_res = await GLService.post_journal_voucher(
                    db=db,
                    tenant_id=tenant_id,
                    voucher_in=JournalVoucherCreate(
                        voucher_date=completion_time,
                        source_document_type="MAINTENANCE_WORK_ORDER",
                        source_document_id=mwo.mwo_number,
                        notes=f"Maintenance spare parts consumption for {mwo.mwo_number}",
                        lines=[
                            JournalEntryLineCreate(account_id=acc_6150.id, debit_amount=total_parts_cost, credit_amount=Decimal("0.0"), memo=f"Spare parts for {mwo.mwo_number}"),
                            JournalEntryLineCreate(account_id=acc_1200.id, debit_amount=Decimal("0.0"), credit_amount=total_parts_cost, memo=f"Inventory consumed for {mwo.mwo_number}")
                        ]
                    ),
                    user_id=user_id
                )
                jv_id = jv_res.id

        # 3. Recalculate Preventive Schedule Due Date
        if mwo.schedule_id:
            sched = (await db.execute(
                select(MaintenanceSchedule).where(MaintenanceSchedule.id == mwo.schedule_id)
            )).scalar_one_or_none()
            if sched:
                sched.last_performed_at = completion_time
                sched.next_due_at = completion_time + timedelta(days=sched.frequency_days)

        # 4. Finalize MWO Record
        mwo.status = "COMPLETED"
        mwo.actual_completion_date = completion_time
        mwo.downtime_hours = comp_in.downtime_hours
        mwo.labor_hours = comp_in.labor_hours
        mwo.journal_voucher_id = jv_id
        mwo.notes = comp_in.notes or mwo.notes

        await db.commit()
        await db.refresh(mwo)

        return await MaintenanceService._format_mwo_response(mwo)

    @staticmethod
    async def _format_mwo_response(mwo: MaintenanceWorkOrder) -> MaintenanceWorkOrderResponse:
        parts_resp = [
            MWOSparePartResponse(
                id=p.id,
                mwo_id=p.mwo_id,
                item_variant_id=p.item_variant_id,
                warehouse_id=p.warehouse_id,
                location_bin_id=p.location_bin_id,
                quantity_required=p.quantity_required,
                quantity_consumed=p.quantity_consumed,
                unit_cost=p.unit_cost,
                total_cost=p.total_cost
            ) for p in mwo.spare_parts
        ]
        return MaintenanceWorkOrderResponse(
            id=mwo.id,
            tenant_id=mwo.tenant_id,
            mwo_number=mwo.mwo_number,
            schedule_id=mwo.schedule_id,
            asset_id=mwo.asset_id,
            work_center_id=mwo.work_center_id,
            assigned_technician_id=mwo.assigned_technician_id,
            priority=mwo.priority,
            status=mwo.status,
            expenditure_type=mwo.expenditure_type,
            useful_life_extension_months=mwo.useful_life_extension_months,
            scheduled_start_date=mwo.scheduled_start_date,
            actual_completion_date=mwo.actual_completion_date,
            downtime_hours=mwo.downtime_hours,
            labor_hours=mwo.labor_hours,
            journal_voucher_id=mwo.journal_voucher_id,
            notes=mwo.notes,
            spare_parts=parts_resp,
            created_at=mwo.created_at
        )
