import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone
from calendar import monthrange
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.fixed_asset import FixedAssetClass, FixedAsset, DepreciationScheduleEntry, AssetImprovement
from app.models.general_ledger import GLAccount, JournalVoucher, JournalEntryLine
from app.schemas.fixed_asset import (
    FixedAssetClassCreate,
    FixedAssetClassResponse,
    FixedAssetCreate,
    FixedAssetResponse,
    DepreciationScheduleEntryResponse,
    DepreciationBatchRunRequest,
    DepreciationBatchRunResponse,
    AssetDisposalRequest,
    AssetDisposalResponse,
    AssetImprovementCreate,
    AssetImprovementResponse
)
from app.schemas.general_ledger import JournalVoucherCreate, JournalEntryLineCreate
from app.services.gl_service import GLService

class FixedAssetService:

    # ========================================================================
    # 1. FIXED ASSET CLASS MANAGEMENT
    # ========================================================================

    @staticmethod
    async def create_asset_class(
        db: AsyncSession,
        tenant_id: str,
        class_in: FixedAssetClassCreate
    ) -> FixedAssetClassResponse:
        existing = (await db.execute(
            select(FixedAssetClass).where(
                FixedAssetClass.tenant_id == tenant_id,
                FixedAssetClass.class_code == class_in.class_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Asset Class '{class_in.class_code}' already exists")

        ac = FixedAssetClass(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            class_code=class_in.class_code.upper(),
            class_name=class_in.class_name,
            depreciation_method=class_in.depreciation_method,
            useful_life_months=class_in.useful_life_months,
            depreciation_rate_annual=class_in.depreciation_rate_annual,
            description=class_in.description,
            is_active=True
        )
        db.add(ac)
        await db.commit()
        await db.refresh(ac)

        return FixedAssetClassResponse(
            id=ac.id,
            tenant_id=ac.tenant_id,
            class_code=ac.class_code,
            class_name=ac.class_name,
            depreciation_method=ac.depreciation_method,
            useful_life_months=ac.useful_life_months,
            depreciation_rate_annual=ac.depreciation_rate_annual,
            description=ac.description,
            is_active=ac.is_active,
            created_at=ac.created_at
        )

    # ========================================================================
    # 2. FIXED ASSET CAPITALIZATION & SCHEDULE GENERATION
    # ========================================================================

    @staticmethod
    async def create_and_capitalize_fixed_asset(
        db: AsyncSession,
        tenant_id: str,
        asset_in: FixedAssetCreate,
        user_id: Optional[str] = None
    ) -> FixedAssetResponse:
        existing = (await db.execute(
            select(FixedAsset).where(
                FixedAsset.tenant_id == tenant_id,
                FixedAsset.asset_code == asset_in.asset_code
            )
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Fixed Asset '{asset_in.asset_code}' already exists")

        ac = (await db.execute(
            select(FixedAssetClass).where(
                FixedAssetClass.id == asset_in.asset_class_id,
                FixedAssetClass.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not ac:
            raise HTTPException(status_code=404, detail="Asset Class not found")

        method = asset_in.depreciation_method or ac.depreciation_method
        useful_months = asset_in.useful_life_months or ac.useful_life_months
        dep_rate = asset_in.depreciation_rate_annual if asset_in.depreciation_rate_annual is not None else ac.depreciation_rate_annual

        if asset_in.source_grn_id:
            existing_grn_asset = (await db.execute(
                select(FixedAsset).where(
                    FixedAsset.tenant_id == tenant_id,
                    FixedAsset.source_grn_id == asset_in.source_grn_id
                )
            )).scalar_one_or_none()
            if existing_grn_asset:
                raise HTTPException(status_code=409, detail=f"Fixed Asset already capitalized against GRN '{asset_in.source_grn_id}'")

        asset = FixedAsset(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            asset_code=asset_in.asset_code.upper(),
            asset_name=asset_in.asset_name,
            asset_class_id=ac.id,
            warehouse_id=asset_in.warehouse_id,
            serial_number=asset_in.serial_number,
            source_po_id=asset_in.source_po_id,
            source_grn_id=asset_in.source_grn_id,
            purchase_cost=asset_in.purchase_cost,
            salvage_value=asset_in.salvage_value,
            acquisition_date=asset_in.acquisition_date,
            depreciation_start_date=asset_in.depreciation_start_date,
            depreciation_method=method,
            useful_life_months=useful_months,
            depreciation_rate_annual=dep_rate,
            current_book_value=asset_in.purchase_cost,
            accumulated_depreciation=Decimal("0.0"),
            status="ACTIVE",
            notes=asset_in.notes
        )
        db.add(asset)

        # Generate Depreciation Schedule Entries
        depreciable_base = asset_in.purchase_cost - asset_in.salvage_value
        monthly_slm_dep = (depreciable_base / Decimal(str(useful_months))).quantize(Decimal("0.0001"))

        sched_entries: List[DepreciationScheduleEntry] = []
        running_acc_dep = Decimal("0.0")
        running_book_val = asset_in.purchase_cost

        cur_year = asset_in.depreciation_start_date.year
        cur_month = asset_in.depreciation_start_date.month

        for m_idx in range(useful_months):
            if method == "STRAIGHT_LINE":
                m_dep = monthly_slm_dep
                if m_idx == (useful_months - 1): # Last month adjustment
                    m_dep = depreciable_base - running_acc_dep
            else: # WRITTEN_DOWN_VALUE
                # Monthly rate = annual_rate / 12 / 100
                m_rate = (dep_rate / Decimal("100.0")) / Decimal("12.0")
                m_dep = (running_book_val * m_rate).quantize(Decimal("0.0001"))

            running_acc_dep += m_dep
            running_book_val = max(Decimal("0.0"), asset_in.purchase_cost - running_acc_dep)

            _, last_day = monthrange(cur_year, cur_month)
            p_date = date(cur_year, cur_month, last_day)
            p_code = f"{cur_year}-{cur_month:02d}"

            entry = DepreciationScheduleEntry(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                fixed_asset_id=asset.id,
                period_code=p_code,
                scheduled_date=p_date,
                depreciation_amount=m_dep,
                accumulated_depreciation_after=running_acc_dep,
                remaining_book_value_after=running_book_val,
                status="SCHEDULED"
            )
            db.add(entry)
            sched_entries.append(entry)

            # Advance month
            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        # Post Capitalization Journal Voucher: Dr 1500 Fixed Asset / Cr 2000 AP
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1500 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1500"))).scalar_one()
        acc_2000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "2000"))).scalar_one()

        await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=datetime.combine(asset_in.acquisition_date, datetime.min.time(), tzinfo=timezone.utc),
                source_document_type="FIXED_ASSET_CAPITALIZATION",
                source_document_id=asset.id,
                notes=f"Capitalization for Fixed Asset {asset.asset_code}",
                lines=[
                    JournalEntryLineCreate(account_id=acc_1500.id, debit_amount=asset_in.purchase_cost, credit_amount=Decimal("0.0"), memo=f"Acquire {asset.asset_name}"),
                    JournalEntryLineCreate(account_id=acc_2000.id, debit_amount=Decimal("0.0"), credit_amount=asset_in.purchase_cost, memo="Vendor AP liability")
                ]
            ),
            user_id=user_id
        )

        await db.commit()
        await db.refresh(asset)

        return FixedAssetResponse(
            id=asset.id,
            tenant_id=asset.tenant_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_class_id=asset.asset_class_id,
            warehouse_id=asset.warehouse_id,
            serial_number=asset.serial_number,
            source_po_id=asset.source_po_id,
            source_grn_id=asset.source_grn_id,
            purchase_cost=asset.purchase_cost,
            salvage_value=asset.salvage_value,
            acquisition_date=asset.acquisition_date,
            depreciation_start_date=asset.depreciation_start_date,
            depreciation_method=asset.depreciation_method,
            useful_life_months=asset.useful_life_months,
            depreciation_rate_annual=asset.depreciation_rate_annual,
            current_book_value=asset.current_book_value,
            accumulated_depreciation=asset.accumulated_depreciation,
            status=asset.status,
            notes=asset.notes,
            schedule_entries=[
                DepreciationScheduleEntryResponse(
                    id=e.id,
                    fixed_asset_id=e.fixed_asset_id,
                    period_code=e.period_code,
                    scheduled_date=e.scheduled_date,
                    depreciation_amount=e.depreciation_amount,
                    accumulated_depreciation_after=e.accumulated_depreciation_after,
                    remaining_book_value_after=e.remaining_book_value_after,
                    status=e.status,
                    posted_at=e.posted_at,
                    journal_voucher_id=e.journal_voucher_id
                ) for e in sched_entries
            ],
            created_at=asset.created_at
        )

    # ========================================================================
    # 3. MONTHLY DEPRECIATION BATCH RUNNER
    # ========================================================================

    @staticmethod
    async def run_monthly_depreciation_batch(
        db: AsyncSession,
        tenant_id: str,
        batch_req: DepreciationBatchRunRequest,
        user_id: Optional[str] = None
    ) -> DepreciationBatchRunResponse:
        batch_key = f"DEP-BATCH-{batch_req.period_code}"

        # Upfront Accounting Period validation
        from app.models.accounting_period import AccountingPeriod
        period = (await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.period_code == batch_req.period_code
            )
        )).scalar_one_or_none()
        if period and period.status in {"CLOSED", "FINALIZED"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Accounting Period '{period.period_code}' is {period.status}. Depreciation posting is strictly prohibited."
            )

        # Idempotency check: Return existing posted batch
        existing_jv = (await db.execute(
            select(JournalVoucher).where(
                JournalVoucher.tenant_id == tenant_id,
                JournalVoucher.source_document_type == "DEPRECIATION_BATCH",
                JournalVoucher.source_document_id == batch_key,
                JournalVoucher.status == "POSTED"
            )
        )).scalar_one_or_none()

        if existing_jv:
            tot_d = sum(l.debit_amount for l in existing_jv.lines)
            return DepreciationBatchRunResponse(
                period_code=batch_req.period_code,
                processed_assets_count=len(existing_jv.lines) // 2,
                total_depreciation_amount=tot_d,
                journal_voucher_id=existing_jv.id,
                journal_voucher_number=existing_jv.voucher_number
            )

        # Query all scheduled depreciation entries for this period
        entries = (await db.execute(
            select(DepreciationScheduleEntry).join(FixedAsset).where(
                DepreciationScheduleEntry.tenant_id == tenant_id,
                DepreciationScheduleEntry.period_code == batch_req.period_code,
                DepreciationScheduleEntry.status == "SCHEDULED",
                FixedAsset.status.in_(["ACTIVE", "DEPRECIATING"])
            ).with_for_update()
        )).scalars().all()

        if not entries:
            return DepreciationBatchRunResponse(
                period_code=batch_req.period_code,
                processed_assets_count=0,
                total_depreciation_amount=Decimal("0.0"),
                journal_voucher_id=None,
                journal_voucher_number=None
            )

        total_dep = sum(e.depreciation_amount for e in entries).quantize(Decimal("0.0001"))

        # GL Accounts
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_6400 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6400"))).scalar_one()
        acc_1550 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1550"))).scalar_one()

        run_dt = datetime.combine(batch_req.run_date or entries[0].scheduled_date, datetime.min.time(), tzinfo=timezone.utc)

        jv = await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=run_dt,
                source_document_type="DEPRECIATION_BATCH",
                source_document_id=batch_key,
                notes=f"Monthly Depreciation Batch for Period {batch_req.period_code}",
                lines=[
                    JournalEntryLineCreate(account_id=acc_6400.id, debit_amount=total_dep, credit_amount=Decimal("0.0"), memo=f"Depreciation Expense for {batch_req.period_code}"),
                    JournalEntryLineCreate(account_id=acc_1550.id, debit_amount=Decimal("0.0"), credit_amount=total_dep, memo=f"Accumulated Depreciation for {batch_req.period_code}")
                ]
            ),
            user_id=user_id
        )

        for e in entries:
            e.status = "POSTED"
            e.posted_at = get_utc_now()
            e.journal_voucher_id = jv.id

            asset = (await db.execute(select(FixedAsset).where(FixedAsset.id == e.fixed_asset_id))).scalar_one()
            asset.accumulated_depreciation = e.accumulated_depreciation_after
            asset.current_book_value = e.remaining_book_value_after
            asset.status = "FULLY_DEPRECIATED" if asset.current_book_value <= asset.salvage_value else "DEPRECIATING"

        await db.commit()

        return DepreciationBatchRunResponse(
            period_code=batch_req.period_code,
            processed_assets_count=len(entries),
            total_depreciation_amount=total_dep,
            journal_voucher_id=jv.id,
            journal_voucher_number=jv.voucher_number
        )

    # ========================================================================
    # 4. ASSET DISPOSAL & GAIN/LOSS ACCOUNTING
    # ========================================================================

    @staticmethod
    async def dispose_fixed_asset(
        db: AsyncSession,
        tenant_id: str,
        asset_id: str,
        disp_req: AssetDisposalRequest,
        user_id: Optional[str] = None
    ) -> AssetDisposalResponse:
        asset = (await db.execute(
            select(FixedAsset).where(FixedAsset.id == asset_id, FixedAsset.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Fixed Asset not found")

        if asset.status in {"DISPOSED", "SCRAPPED"}:
            raise HTTPException(status_code=400, detail="Fixed Asset has already been disposed or scrapped")

        book_val = (asset.purchase_cost - asset.accumulated_depreciation).quantize(Decimal("0.0001"))
        gain_loss = (disp_req.disposal_amount - book_val).quantize(Decimal("0.0001"))

        # GL Accounts
        await GLService.seed_standard_chart_of_accounts(db, tenant_id)
        acc_1000 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1000"))).scalar_one()
        acc_1500 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1500"))).scalar_one()
        acc_1550 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "1550"))).scalar_one()
        acc_6450 = (await db.execute(select(GLAccount).where(GLAccount.tenant_id == tenant_id, GLAccount.account_code == "6450"))).scalar_one()

        lines: List[JournalEntryLineCreate] = []

        # 1. Dr Cash (Proceeds)
        if disp_req.disposal_amount > Decimal("0.0"):
            lines.append(JournalEntryLineCreate(account_id=acc_1000.id, debit_amount=disp_req.disposal_amount, credit_amount=Decimal("0.0"), memo="Disposal proceeds received"))

        # 2. Dr Accumulated Depreciation (Clear Contra Asset)
        if asset.accumulated_depreciation > Decimal("0.0"):
            lines.append(JournalEntryLineCreate(account_id=acc_1550.id, debit_amount=asset.accumulated_depreciation, credit_amount=Decimal("0.0"), memo="Clear accumulated depreciation"))

        # 3. Cr Fixed Asset (Clear Historical Cost)
        lines.append(JournalEntryLineCreate(account_id=acc_1500.id, debit_amount=Decimal("0.0"), credit_amount=asset.purchase_cost, memo="Clear historical asset cost"))

        # 4. Gain / Loss Balancing Line (Account 6450)
        if gain_loss > Decimal("0.0"): # Gain on Sale -> Credit
            lines.append(JournalEntryLineCreate(account_id=acc_6450.id, debit_amount=Decimal("0.0"), credit_amount=gain_loss, memo="Gain on disposal of fixed asset"))
        elif gain_loss < Decimal("0.0"): # Loss on Sale -> Debit
            lines.append(JournalEntryLineCreate(account_id=acc_6450.id, debit_amount=abs(gain_loss), credit_amount=Decimal("0.0"), memo="Loss on disposal of fixed asset"))

        jv = await GLService.post_journal_voucher(
            db=db, tenant_id=tenant_id,
            voucher_in=JournalVoucherCreate(
                voucher_date=datetime.combine(disp_req.disposal_date, datetime.min.time(), tzinfo=timezone.utc),
                source_document_type="FIXED_ASSET_DISPOSAL",
                source_document_id=asset.id,
                notes=f"Disposal of Asset {asset.asset_code}",
                lines=lines
            ),
            user_id=user_id
        )

        asset.status = "DISPOSED" if disp_req.disposal_amount > 0 else "SCRAPPED"
        asset.disposal_date = disp_req.disposal_date
        asset.disposal_amount = disp_req.disposal_amount
        asset.current_book_value = Decimal("0.0")

        # Skip all future scheduled entries
        future_entries = (await db.execute(
            select(DepreciationScheduleEntry).where(
                DepreciationScheduleEntry.fixed_asset_id == asset.id,
                DepreciationScheduleEntry.status == "SCHEDULED"
            )
        )).scalars().all()
        for fe in future_entries:
            fe.status = "SKIPPED"

        await db.commit()

        return AssetDisposalResponse(
            asset_id=asset.id,
            asset_code=asset.asset_code,
            purchase_cost=asset.purchase_cost,
            accumulated_depreciation=asset.accumulated_depreciation,
            book_value_at_disposal=book_val,
            disposal_amount=disp_req.disposal_amount,
            gain_or_loss=gain_loss,
            journal_voucher_id=jv.id,
            status=asset.status
        )

    VALID_TRANSITIONS = {
        "DRAFT": {"ACTIVE"},
        "ACTIVE": {"DEPRECIATING", "DISPOSED", "SCRAPPED"},
        "DEPRECIATING": {"FULLY_DEPRECIATED", "DISPOSED", "SCRAPPED"},
        "FULLY_DEPRECIATED": {"DISPOSED", "SCRAPPED"},
        "DISPOSED": set(),
        "SCRAPPED": set()
    }

    @staticmethod
    async def update_asset_status(
        db: AsyncSession,
        tenant_id: str,
        asset_id: str,
        new_status: str
    ) -> FixedAssetResponse:
        asset = (await db.execute(
            select(FixedAsset).where(FixedAsset.id == asset_id, FixedAsset.tenant_id == tenant_id).with_for_update()
        )).scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Fixed Asset not found")

        allowed = FixedAssetService.VALID_TRANSITIONS.get(asset.status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal asset lifecycle transition from {asset.status} to {new_status}"
            )

        asset.status = new_status
        await db.commit()
        await db.refresh(asset)

        return FixedAssetResponse(
            id=asset.id,
            tenant_id=asset.tenant_id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_class_id=asset.asset_class_id,
            warehouse_id=asset.warehouse_id,
            serial_number=asset.serial_number,
            source_po_id=asset.source_po_id,
            source_grn_id=asset.source_grn_id,
            purchase_cost=asset.purchase_cost,
            salvage_value=asset.salvage_value,
            acquisition_date=asset.acquisition_date,
            depreciation_start_date=asset.depreciation_start_date,
            depreciation_method=asset.depreciation_method,
            useful_life_months=asset.useful_life_months,
            depreciation_rate_annual=asset.depreciation_rate_annual,
            current_book_value=asset.current_book_value,
            accumulated_depreciation=asset.accumulated_depreciation,
            status=asset.status,
            notes=asset.notes,
            schedule_entries=[],
            created_at=asset.created_at
        )

    # ========================================================================
    # 5. ASSET CAPITAL IMPROVEMENTS & DEPRECIATION RECALCULATION (PHASE 34)
    # ========================================================================

    @staticmethod
    async def apply_capital_improvement_and_recalculate_depreciation(
        db: AsyncSession,
        tenant_id: str,
        asset_id: str,
        improvement_in: AssetImprovementCreate,
        user_id: Optional[str] = None
    ) -> AssetImprovementResponse:
        asset = (await db.execute(
            select(FixedAsset).where(
                FixedAsset.id == asset_id,
                FixedAsset.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Fixed Asset not found")

        if asset.status in ["DISPOSED", "SCRAPPED", "FULLY_DEPRECIATED"]:
            raise HTTPException(status_code=400, detail=f"Cannot improve asset in {asset.status} state")

        # 1. Update Asset Cost & Useful Life
        asset.purchase_cost = asset.purchase_cost + improvement_in.capitalized_amount
        asset.current_book_value = asset.current_book_value + improvement_in.capitalized_amount
        asset.useful_life_months = asset.useful_life_months + improvement_in.useful_life_extension_months

        # 2. Delete all remaining SCHEDULED depreciation entries
        scheduled_entries = (await db.execute(
            select(DepreciationScheduleEntry).where(
                DepreciationScheduleEntry.fixed_asset_id == asset.id,
                DepreciationScheduleEntry.status == "SCHEDULED"
            )
        )).scalars().all()
        for ent in scheduled_entries:
            await db.delete(ent)
        await db.flush()

        # 3. Recalculate remaining schedules
        posted_count = (await db.execute(
            select(func.count(DepreciationScheduleEntry.id)).where(
                DepreciationScheduleEntry.fixed_asset_id == asset.id,
                DepreciationScheduleEntry.status == "POSTED"
            )
        )).scalar() or 0

        remaining_months = max(1, asset.useful_life_months - posted_count)
        remaining_depreciable_base = asset.current_book_value - asset.salvage_value
        monthly_slm_dep = (remaining_depreciable_base / Decimal(str(remaining_months))).quantize(Decimal("0.0001"))

        now_utc = get_utc_now()
        cur_year = now_utc.year
        cur_month = now_utc.month
        running_acc_dep = asset.accumulated_depreciation
        running_book_val = asset.current_book_value

        for m_idx in range(remaining_months):
            if m_idx == (remaining_months - 1):
                m_dep = max(Decimal("0.0"), remaining_depreciable_base - (running_acc_dep - asset.accumulated_depreciation))
            else:
                m_dep = monthly_slm_dep

            running_acc_dep += m_dep
            running_book_val = max(Decimal("0.0"), asset.current_book_value - running_acc_dep)

            _, last_day = monthrange(cur_year, cur_month)
            p_date = date(cur_year, cur_month, last_day)
            p_code = f"{cur_year}-{cur_month:02d}"

            entry = DepreciationScheduleEntry(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                fixed_asset_id=asset.id,
                period_code=p_code,
                scheduled_date=p_date,
                depreciation_amount=m_dep,
                accumulated_depreciation_after=running_acc_dep,
                remaining_book_value_after=running_book_val,
                status="SCHEDULED"
            )
            db.add(entry)

            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        # 4. Create AssetImprovement Record
        improvement = AssetImprovement(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            asset_id=asset.id,
            mwo_id=improvement_in.mwo_id,
            improvement_name=improvement_in.improvement_name,
            capitalized_amount=improvement_in.capitalized_amount,
            useful_life_extension_months=improvement_in.useful_life_extension_months,
            capitalization_date=now_utc,
            status="CAPITALIZED"
        )
        db.add(improvement)
        await db.commit()
        await db.refresh(improvement)

        return AssetImprovementResponse(
            id=improvement.id,
            tenant_id=improvement.tenant_id,
            asset_id=improvement.asset_id,
            mwo_id=improvement.mwo_id,
            improvement_name=improvement.improvement_name,
            capitalized_amount=improvement.capitalized_amount,
            useful_life_extension_months=improvement.useful_life_extension_months,
            capitalization_date=improvement.capitalization_date,
            status=improvement.status,
            journal_voucher_id=improvement.journal_voucher_id,
            created_at=improvement.created_at
        )
