import logging
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|secret|token|access_token|refresh_token|authorization|private_key|api_key|pgpassword)",
    re.IGNORECASE
)

class SensitiveDataFilter(logging.Filter):
    """
    Redacts passwords, tokens, secret keys, and authorization headers from all logs.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redact_string(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = self.redact_dict(record.msg)
        
        if record.args:
            if isinstance(record.args, dict):
                record.args = self.redact_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.redact_string(str(arg)) if isinstance(arg, str) else arg 
                    for arg in record.args
                )
        return True

    def redact_string(self, text: str) -> str:
        # Mask Bearer tokens
        text = re.sub(r"(Bearer\s+)[A-Za-z0-9\-_.]+", r"\1***REDACTED_TOKEN***", text, flags=re.IGNORECASE)
        # Mask key=value or "key": "value" patterns
        text = re.sub(
            r'("(?:password|secret|token|refresh_token|access_token|private_key)"\s*:\s*)"[^"]*"',
            r'\1"***REDACTED***"',
            text,
            flags=re.IGNORECASE
        )
        text = re.sub(
            r'((?:password|secret|token|refresh_token|access_token|private_key)\s*=\s*)[^\s&,]+',
            r'\1***REDACTED***',
            text,
            flags=re.IGNORECASE
        )
        return text

    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        redacted = {}
        for k, v in data.items():
            if SENSITIVE_KEY_PATTERNS.search(str(k)):
                redacted[k] = "***REDACTED***"
            elif isinstance(v, dict):
                redacted[k] = self.redact_dict(v)
            elif isinstance(v, list):
                redacted[k] = [self.redact_dict(item) if isinstance(item, dict) else item for item in v]
            elif isinstance(v, str):
                redacted[k] = self.redact_string(v)
            else:
                redacted[k] = v
        return redacted


class StructuredJsonFormatter(logging.Formatter):
    """
    Standard JSON structured logging formatter for production monitoring and log aggregation.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        # Include contextual correlation metadata if available
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = record.tenant_id
        if hasattr(record, "path"):
            log_obj["path"] = record.path
        if hasattr(record, "method"):
            log_obj["method"] = record.method
        if hasattr(record, "status_code"):
            log_obj["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_structured_logging():
    """
    Initializes root logging with the SensitiveDataFilter and standard formatting.
    """
    root_logger = logging.getLogger()
    
    # Avoid duplicate handlers on re-initialization
    if not any(isinstance(f, SensitiveDataFilter) for f in root_logger.filters):
        root_logger.addFilter(SensitiveDataFilter())

    for handler in root_logger.handlers:
        if not any(isinstance(f, SensitiveDataFilter) for f in handler.filters):
            handler.addFilter(SensitiveDataFilter())
