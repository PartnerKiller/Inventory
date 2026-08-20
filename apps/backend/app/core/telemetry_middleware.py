import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.telemetry import TelemetryCollector

class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract or generate distributed trace ID & span ID
        trace_id = request.headers.get("X-Trace-ID") or f"trace-{uuid.uuid4().hex}"
        span_id = f"span-{uuid.uuid4().hex[:16]}"

        request.state.trace_id = trace_id
        request.state.span_id = span_id

        start_time = time.perf_counter()
        try:
            response: Response = await call_next(request)
            duration = time.perf_counter() - start_time
            status_code = response.status_code
        except Exception as exc:
            duration = time.perf_counter() - start_time
            status_code = 500
            TelemetryCollector.record_http_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_seconds=duration
            )
            raise exc

        # Record HTTP metrics
        TelemetryCollector.record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_seconds=duration
        )

        # Inject distributed tracing headers
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Span-ID"] = span_id
        response.headers["X-Response-Time"] = f"{duration * 1000:.2f}ms"

        return response
