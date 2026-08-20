import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List

class MetricsService:
    """
    In-memory thread-safe operational metrics collector for request counters,
    HTTP status distributions, latency tracking, and system health stats.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MetricsService, cls).__new__(cls)
                cls._instance._init_metrics()
            return cls._instance

    def _init_metrics(self):
        self.start_time = time.time()
        self.total_requests = 0
        self.status_2xx = 0
        self.status_3xx = 0
        self.status_4xx = 0
        self.status_5xx = 0
        self.error_count = 0
        self.latencies: List[float] = []  # sliding window of last 1000 requests
        self.max_latencies_retained = 1000
        self.active_requests = 0
        self.last_backup_time: str | None = None
        self.last_backup_status: str | None = "NONE"
        self.last_integrity_check_time: str | None = None
        self.last_integrity_check_status: str | None = "NONE"

    def record_request(self, status_code: int, duration_ms: float):
        with self._lock:
            self.total_requests += 1
            if 200 <= status_code < 300:
                self.status_2xx += 1
            elif 300 <= status_code < 400:
                self.status_3xx += 1
            elif 400 <= status_code < 500:
                self.status_4xx += 1
            elif status_code >= 500:
                self.status_5xx += 1
                self.error_count += 1

            self.latencies.append(duration_ms)
            if len(self.latencies) > self.max_latencies_retained:
                self.latencies.pop(0)

    def record_backup_event(self, status: str):
        with self._lock:
            self.last_backup_time = datetime.now(timezone.utc).isoformat()
            self.last_backup_status = status

    def record_integrity_event(self, status: str):
        with self._lock:
            self.last_integrity_check_time = datetime.now(timezone.utc).isoformat()
            self.last_integrity_check_status = status

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            uptime_seconds = int(time.time() - self.start_time)
            avg_latency = round(sum(self.latencies) / len(self.latencies), 2) if self.latencies else 0.0
            sorted_lat = sorted(self.latencies) if self.latencies else [0.0]
            p95_index = int(len(sorted_lat) * 0.95)
            p95_latency = round(sorted_lat[min(p95_index, len(sorted_lat) - 1)], 2)
            max_latency = round(max(sorted_lat), 2)

            return {
                "uptime_seconds": uptime_seconds,
                "total_requests": self.total_requests,
                "status_breakdown": {
                    "2xx": self.status_2xx,
                    "3xx": self.status_3xx,
                    "4xx": self.status_4xx,
                    "5xx": self.status_5xx,
                },
                "error_count": self.error_count,
                "latency_ms": {
                    "avg": avg_latency,
                    "p95": p95_latency,
                    "max": max_latency,
                },
                "last_backup": {
                    "timestamp": self.last_backup_time,
                    "status": self.last_backup_status,
                },
                "last_integrity_check": {
                    "timestamp": self.last_integrity_check_time,
                    "status": self.last_integrity_check_status,
                }
            }

    def get_prometheus_metrics(self) -> str:
        with self._lock:
            uptime_seconds = int(time.time() - self.start_time)
            avg_sec = (sum(self.latencies) / len(self.latencies) / 1000.0) if self.latencies else 0.0
            sorted_lat = sorted(self.latencies) if self.latencies else [0.0]
            p95_index = int(len(sorted_lat) * 0.95)
            p95_sec = (sorted_lat[min(p95_index, len(sorted_lat) - 1)] / 1000.0)
            max_sec = (max(sorted_lat) / 1000.0)

            lines = [
                "# HELP http_requests_total Total number of HTTP requests processed",
                "# TYPE http_requests_total counter",
                f'http_requests_total{{status="2xx"}} {self.status_2xx}',
                f'http_requests_total{{status="3xx"}} {self.status_3xx}',
                f'http_requests_total{{status="4xx"}} {self.status_4xx}',
                f'http_requests_total{{status="5xx"}} {self.status_5xx}',
                "",
                "# HELP http_request_duration_seconds HTTP request latency summary in seconds",
                "# TYPE http_request_duration_seconds gauge",
                f'http_request_duration_seconds{{quantile="avg"}} {avg_sec:.6f}',
                f'http_request_duration_seconds{{quantile="0.95"}} {p95_sec:.6f}',
                f'http_request_duration_seconds{{quantile="max"}} {max_sec:.6f}',
                "",
                "# HELP aurastock_uptime_seconds Application uptime in seconds",
                "# TYPE aurastock_uptime_seconds counter",
                f'aurastock_uptime_seconds {uptime_seconds}',
                "",
                "# HELP aurastock_error_total Total count of HTTP 5xx errors",
                "# TYPE aurastock_error_total counter",
                f'aurastock_error_total {self.error_count}',
                ""
            ]
            return "\n".join(lines)

metrics_service = MetricsService()
