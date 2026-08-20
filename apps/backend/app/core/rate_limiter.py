import os
from starlette.requests import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

def get_rate_limit_key(request: Request) -> str:
    ip = get_remote_address(request) or "127.0.0.1"
    test_client_id = request.headers.get("X-Test-Client-ID")
    if test_client_id:
        return f"{ip}:{test_client_id}"
    return ip

limiter = Limiter(key_func=get_rate_limit_key, default_limits=["500/minute"])
