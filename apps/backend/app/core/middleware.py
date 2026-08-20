import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.services.metrics_service import metrics_service

logger = logging.getLogger("app.middleware.correlation")

class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that captures or generates a unique correlation X-Request-ID,
    injects it into request state, logs structured request lifecycle details,
    and sets the X-Request-ID response header.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract existing correlation ID or generate fresh UUID4
        request_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # Record operational metrics
            metrics_service.record_request(response.status_code, duration_ms)
            
            # Set correlation and security headers on response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'self';"
            
            # Structured debug/info log
            logger.info(
                f"{request.method} {request.url.path} completed with {response.status_code} in {duration_ms}ms [ReqID: {request_id}]",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms
                }
            )
            return response
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            metrics_service.record_request(500, duration_ms)
            logger.error(
                f"Unhandled exception during {request.method} {request.url.path}: {exc} [ReqID: {request_id}]",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms
                }
            )
            raise exc
