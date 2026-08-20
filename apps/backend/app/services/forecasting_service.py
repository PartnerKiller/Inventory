import uuid
import math
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.base import get_utc_now
from app.models.item import Item, ItemVariant
from app.models.warehouse import Warehouse
from app.models.ledger import StockLedgerEntry
from app.models.purchasing import PurchaseOrder
from app.models.forecasting import DemandForecastProfile, ForecastPeriodEntry, ReplenishmentProposal
from app.schemas.forecasting import (
    DemandForecastProfileCreate,
    DemandForecastProfileResponse,
    ForecastCalculationRequest,
    ForecastCalculationResponse,
    ReplenishmentProposalResponse,
    ConvertProposalToPORequest
)
from app.schemas.purchasing import PurchaseOrderCreate, POLineCreate
from app.services.purchase_service import PurchaseService

class ForecastingService:

    # ========================================================================
    # 1. FORECAST PROFILE MANAGEMENT
    # ========================================================================

    @staticmethod
    async def create_forecast_profile(
        db: AsyncSession,
        tenant_id: str,
        profile_in: DemandForecastProfileCreate
    ) -> DemandForecastProfileResponse:
        existing = (await db.execute(
            select(DemandForecastProfile).where(
                DemandForecastProfile.tenant_id == tenant_id,
                DemandForecastProfile.item_id == profile_in.item_id,
                DemandForecastProfile.warehouse_id == profile_in.warehouse_id
            )
        )).scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=409, detail="Forecast profile already exists for this item and warehouse")

        item = (await db.execute(select(Item).where(Item.id == profile_in.item_id, Item.tenant_id == tenant_id))).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        wh = (await db.execute(select(Warehouse).where(Warehouse.id == profile_in.warehouse_id, Warehouse.tenant_id == tenant_id))).scalar_one_or_none()
        if not wh:
            raise HTTPException(status_code=404, detail="Warehouse not found")

        profile = DemandForecastProfile(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            item_id=profile_in.item_id,
            warehouse_id=profile_in.warehouse_id,
            model_type=profile_in.model_type,
            seasonality_periods=profile_in.seasonality_periods,
            alpha=profile_in.alpha,
            beta=profile_in.beta,
            gamma=profile_in.gamma,
            service_level_target=profile_in.service_level_target,
            lead_time_days=profile_in.lead_time_days,
            lead_time_std_dev=profile_in.lead_time_std_dev,
            is_active=True
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

        return DemandForecastProfileResponse(
            id=profile.id,
            tenant_id=profile.tenant_id,
            item_id=profile.item_id,
            warehouse_id=profile.warehouse_id,
            model_type=profile.model_type,
            seasonality_periods=profile.seasonality_periods,
            alpha=profile.alpha,
            beta=profile.beta,
            gamma=profile.gamma,
            service_level_target=profile.service_level_target,
            lead_time_days=profile.lead_time_days,
            lead_time_std_dev=profile.lead_time_std_dev,
            is_active=profile.is_active,
            created_at=profile.created_at
        )

    # ========================================================================
    # 2. STATISTICAL FORECASTING & SAFETY STOCK ENGINE
    # ========================================================================

    @staticmethod
    def _calculate_holt_winters(
        series: List[float],
        m: int,
        alpha: float,
        beta: float,
        gamma: float,
        horizon: int
    ) -> Tuple[List[float], List[float]]:
        """Holt-Winters Additive Seasonality model."""
        n = len(series)
        if n < 2 * m: # Fallback if history < 2 cycles
            # Simple exponential smoothing fallback
            level = series[0]
            fitted = [level]
            for val in series[1:]:
                level = alpha * val + (1 - alpha) * level
                fitted.append(level)
            forecast = [level] * horizon
            return fitted, forecast

        # Initial Seasonality & Level
        seasonals = [0.0] * m
        season_averages = []
        n_seasons = n // m
        for i in range(n_seasons):
            season_averages.append(sum(series[i*m : (i+1)*m]) / float(m))

        for i in range(m):
            sum_over_seasons = 0.0
            for j in range(n_seasons):
                sum_over_seasons += series[j*m + i] - season_averages[j]
            seasonals[i] = sum_over_seasons / float(n_seasons)

        level = series[0] - seasonals[0]
        trend = (series[m] - series[0]) / float(m)

        fitted = []
        for i in range(n):
            val = series[i]
            prev_level = level
            prev_trend = trend
            s_idx = i % m

            level = alpha * (val - seasonals[s_idx]) + (1 - alpha) * (prev_level + prev_trend)
            trend = beta * (level - prev_level) + (1 - beta) * prev_trend
            seasonals[s_idx] = gamma * (val - level) + (1 - gamma) * seasonals[s_idx]

            fitted.append(level + trend + seasonals[s_idx])

        forecast = []
        for h in range(1, horizon + 1):
            s_idx = (n + h - 1) % m
            forecast.append(level + h * trend + seasonals[s_idx])

        return fitted, forecast

    @staticmethod
    async def calculate_forecast(
        db: AsyncSession,
        tenant_id: str,
        req: ForecastCalculationRequest
    ) -> ForecastCalculationResponse:
        profile = (await db.execute(
            select(DemandForecastProfile).where(
                DemandForecastProfile.id == req.profile_id,
                DemandForecastProfile.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="Forecast profile not found")

        series_f = [float(x) for x in req.historical_demand_series]
        if not series_f:
            raise HTTPException(status_code=400, detail="Historical demand series cannot be empty")

        m = max(2, profile.seasonality_periods)
        alpha = float(profile.alpha)
        beta = float(profile.beta)
        gamma = float(profile.gamma)

        fitted, forecast = ForecastingService._calculate_holt_winters(
            series_f, m, alpha, beta, gamma, req.horizon_periods
        )

        # Calculate MAPE
        ape_sum = 0.0
        count = 0
        for actual, fit in zip(series_f, fitted):
            if actual > 0:
                ape_sum += abs(actual - fit) / actual
                count += 1
        mape = (Decimal(str(ape_sum / count * 100.0))).quantize(Decimal("0.01")) if count > 0 else Decimal("0.0")

        # Dynamic Safety Stock: SS = Z * sqrt(L * sigma_D^2 + D^2 * sigma_L^2)
        mean_d = sum(series_f) / float(len(series_f))
        var_d = sum((x - mean_d) ** 2 for x in series_f) / float(max(1, len(series_f) - 1))
        sigma_d = math.sqrt(var_d)

        l_bar = float(profile.lead_time_days)
        sigma_l = float(profile.lead_time_std_dev)

        z = 1.645
        if float(profile.service_level_target) >= 0.99:
            z = 2.33
        elif float(profile.service_level_target) >= 0.975:
            z = 1.96

        # SS = Z * sqrt(L * sigma_D^2 + D^2 * sigma_L^2)
        ss_val = z * math.sqrt(max(0.0, l_bar * (sigma_d ** 2) + (mean_d ** 2) * (sigma_l ** 2)))
        ss = Decimal(str(ss_val)).quantize(Decimal("0.0001"))

        # ROP = (D * L) + SS
        rop_val = (mean_d * l_bar) + ss_val
        rop = Decimal(str(rop_val)).quantize(Decimal("0.0001"))

        return ForecastCalculationResponse(
            profile_id=profile.id,
            model_type=profile.model_type,
            fitted_values=[Decimal(str(round(x, 4))) for x in fitted],
            forecast_values=[Decimal(str(round(x, 4))) for x in forecast],
            safety_stock=ss,
            reorder_point=rop,
            mean_absolute_percentage_error=mape
        )

    # ========================================================================
    # 3. REPLENISHMENT PROPOSALS & PURCHASE ORDER CONVERSION
    # ========================================================================

    @staticmethod
    async def generate_replenishment_proposal(
        db: AsyncSession,
        tenant_id: str,
        item_id: str,
        warehouse_id: str,
        current_stock: Decimal,
        in_transit_stock: Decimal = Decimal("0.0"),
        service_level: Decimal = Decimal("0.95"),
        lead_time_days: Decimal = Decimal("7.0"),
        lead_time_std_dev: Decimal = Decimal("1.5"),
        demand_history: Optional[List[Decimal]] = None
    ) -> Optional[ReplenishmentProposalResponse]:
        # Calculate ROP and Safety Stock
        history = [float(x) for x in (demand_history or [Decimal("50.0"), Decimal("60.0"), Decimal("55.0"), Decimal("70.0")])]
        mean_d = sum(history) / float(len(history))
        var_d = sum((x - mean_d) ** 2 for x in history) / float(max(1, len(history) - 1))
        sigma_d = math.sqrt(var_d)

        z = 2.33 if float(service_level) >= 0.99 else (1.96 if float(service_level) >= 0.975 else 1.645)
        l_bar = float(lead_time_days)
        sigma_l = float(lead_time_std_dev)

        ss_val = z * math.sqrt(max(0.0, l_bar * (sigma_d ** 2) + (mean_d ** 2) * (sigma_l ** 2)))
        rop_val = (mean_d * l_bar) + ss_val

        ss = Decimal(str(ss_val)).quantize(Decimal("0.0001"))
        rop = Decimal(str(rop_val)).quantize(Decimal("0.0001"))

        available_stock = current_stock + in_transit_stock

        # Boundary Condition: If On Hand + In Transit >= ROP -> No replenishment proposal
        if available_stock >= rop:
            return None

        # Idempotency Check: Return existing active proposal
        existing = (await db.execute(
            select(ReplenishmentProposal).where(
                ReplenishmentProposal.tenant_id == tenant_id,
                ReplenishmentProposal.item_id == item_id,
                ReplenishmentProposal.warehouse_id == warehouse_id,
                ReplenishmentProposal.status == "DRAFT"
            )
        )).scalar_one_or_none()

        if existing:
            return ReplenishmentProposalResponse(
                id=existing.id,
                tenant_id=existing.tenant_id,
                item_id=existing.item_id,
                warehouse_id=existing.warehouse_id,
                suggested_order_qty=existing.suggested_order_qty,
                current_stock_on_hand=existing.current_stock_on_hand,
                in_transit_qty=existing.in_transit_qty,
                calculated_rop=existing.calculated_rop,
                calculated_safety_stock=existing.calculated_safety_stock,
                status=existing.status,
                purchase_order_id=existing.purchase_order_id,
                reason=existing.reason,
                created_at=existing.created_at
            )

        suggested_qty = max(Decimal("0.0"), (rop - available_stock)).quantize(Decimal("0.0001"))

        proposal = ReplenishmentProposal(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            suggested_order_qty=suggested_qty,
            current_stock_on_hand=current_stock,
            in_transit_qty=in_transit_stock,
            calculated_rop=rop,
            calculated_safety_stock=ss,
            status="DRAFT",
            reason=f"Stock + In-Transit ({available_stock}) < ROP ({rop}). Reorder suggested: {suggested_qty}"
        )
        db.add(proposal)
        await db.commit()
        await db.refresh(proposal)

        return ReplenishmentProposalResponse(
            id=proposal.id,
            tenant_id=proposal.tenant_id,
            item_id=proposal.item_id,
            warehouse_id=proposal.warehouse_id,
            suggested_order_qty=proposal.suggested_order_qty,
            current_stock_on_hand=proposal.current_stock_on_hand,
            in_transit_qty=proposal.in_transit_qty,
            calculated_rop=proposal.calculated_rop,
            calculated_safety_stock=proposal.calculated_safety_stock,
            status=proposal.status,
            purchase_order_id=proposal.purchase_order_id,
            reason=proposal.reason,
            created_at=proposal.created_at
        )

    @staticmethod
    async def convert_proposal_to_purchase_order(
        db: AsyncSession,
        tenant_id: str,
        proposal_id: str,
        conv_req: ConvertProposalToPORequest,
        user_id: Optional[str] = None
    ) -> ReplenishmentProposalResponse:
        proposal = (await db.execute(
            select(ReplenishmentProposal).where(
                ReplenishmentProposal.id == proposal_id,
                ReplenishmentProposal.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()

        if not proposal:
            raise HTTPException(status_code=404, detail="Replenishment proposal not found")

        if proposal.status == "CONVERTED_TO_PO":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Proposal already converted to Purchase Order"
            )

        # Find or create variant for item
        variant = (await db.execute(
            select(ItemVariant).where(ItemVariant.item_id == proposal.item_id)
        )).scalars().first()
        if not variant:
            variant = ItemVariant(
                id=str(uuid.uuid4()),
                item_id=proposal.item_id,
                variant_name="Standard",
                variant_sku=f"VAR-{uuid.uuid4().hex[:6]}",
                cost_price=conv_req.unit_price,
                selling_price=conv_req.unit_price
            )
            db.add(variant)
            await db.commit()
            await db.refresh(variant)

        # Create authoritative Purchase Order
        po = await PurchaseService.create_purchase_order(
            db=db,
            tenant_id=tenant_id,
            po_in=PurchaseOrderCreate(
                supplier_id=conv_req.supplier_id,
                target_warehouse_id=proposal.warehouse_id,
                currency="USD",
                lines=[
                    POLineCreate(
                        item_variant_id=variant.id,
                        quantity_ordered=proposal.suggested_order_qty,
                        unit_price=conv_req.unit_price
                    )
                ]
            ),
            user_id=user_id
        )

        proposal.status = "CONVERTED_TO_PO"
        proposal.purchase_order_id = po.id
        await db.commit()
        await db.refresh(proposal)

        return ReplenishmentProposalResponse(
            id=proposal.id,
            tenant_id=proposal.tenant_id,
            item_id=proposal.item_id,
            warehouse_id=proposal.warehouse_id,
            suggested_order_qty=proposal.suggested_order_qty,
            current_stock_on_hand=proposal.current_stock_on_hand,
            in_transit_qty=proposal.in_transit_qty,
            calculated_rop=proposal.calculated_rop,
            calculated_safety_stock=proposal.calculated_safety_stock,
            status=proposal.status,
            purchase_order_id=proposal.purchase_order_id,
            reason=proposal.reason,
            created_at=proposal.created_at
        )
