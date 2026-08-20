import os
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.seed import seed_database
from app.core.logging import setup_structured_logging
from app.core.middleware import RequestCorrelationMiddleware
from app.core.telemetry_middleware import TelemetryMiddleware
from app.api.v1.api import api_router

# Initialize structured logging and sensitive data filters
setup_structured_logging()

APP_START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB Schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Auto-seed initial demo dataset
    async with AsyncSessionLocal() as session:
        await seed_database(session)
    
    yield
    # Teardown
    await engine.dispose()

from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from app.core.rate_limiter import limiter

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Correlation & Metrics Middleware
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(TelemetryMiddleware)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permissive for multi-client desktop / web testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RFC 7807 Error Handlers with Request Correlation IDs
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    req_id = getattr(request.state, "request_id", None)
    headers = {"Content-Type": "application/problem+json"}
    if req_id:
        headers["X-Request-ID"] = req_id

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "https://api.inventory.domain/errors/http-error",
            "title": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": str(request.url.path),
            "request_id": req_id
        },
        headers=headers
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", None)
    headers = {"Content-Type": "application/problem+json"}
    if req_id:
        headers["X-Request-ID"] = req_id

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "type": "https://api.inventory.domain/errors/validation-error",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Input validation failed for request payload",
            "instance": str(request.url.path),
            "invalid_params": exc.errors(),
            "request_id": req_id
        },
        headers=headers
    )

# -------------------------------------------------------------
# Health & Readiness Endpoints
# -------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    """
    Lightweight process liveness probe. Indicates the web application server process is running.
    """
    uptime_seconds = int(time.time() - APP_START_TIME)
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "mode": "production-ready",
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/ready", tags=["System"])
async def readiness_check():
    """
    Deep dependency readiness probe. Executes an active database ping to verify PostgreSQL connectivity.
    Returns HTTP 200 when ready to accept transactional traffic, or HTTP 503 if dependencies are unavailable.
    """
    start_time = time.time()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "status": "ready",
            "ready": True,
            "checks": {
                "database": "connected",
                "latency_ms": latency_ms
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "ready": False,
                "checks": {
                    "database": "unavailable",
                    "latency_ms": latency_ms
                },
                "error": "Database dependency check failed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

from fastapi.responses import PlainTextResponse
from app.services.metrics_service import metrics_service

@app.get("/metrics", tags=["System"], response_class=PlainTextResponse)
async def prometheus_metrics():
    """
    Prometheus text exposition format metrics endpoint.
    Exposes request counters, latency percentiles, error rates, and system uptime.
    """
    return PlainTextResponse(
        content=metrics_service.get_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )

# Mount REST API router
app.include_router(api_router, prefix=settings.API_V1_STR)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
