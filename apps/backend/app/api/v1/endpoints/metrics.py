from fastapi import APIRouter, Response
from app.core.telemetry import TelemetryCollector

router = APIRouter()

@router.get("", response_class=Response)
@router.get("/", response_class=Response)
async def get_prometheus_metrics():
    metrics_text = TelemetryCollector.generate_prometheus_metrics()
    return Response(
        content=metrics_text,
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )
