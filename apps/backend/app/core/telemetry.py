import time
import threading
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import uuid

class TelemetryCollector:
    _lock = threading.Lock()
    
    # Counters: (metric_name, tuple(sorted(labels.items()))) -> count
    _counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
    
    # Gauges: (metric_name, tuple(sorted(labels.items()))) -> value
    _gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
    
    # Histograms: (metric_name, tuple(sorted(labels.items()))) -> {sum: float, count: int, buckets: Dict[float, int]}
    _histogram_buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    _histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Dict] = {}

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._counters.clear()
            cls._gauges.clear()
            cls._histograms.clear()

    @classmethod
    def inc_counter(cls, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        lbl_tuple = tuple(sorted(labels.items())) if labels else ()
        with cls._lock:
            cls._counters[(name, lbl_tuple)] += value

    @classmethod
    def set_gauge(cls, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        lbl_tuple = tuple(sorted(labels.items())) if labels else ()
        with cls._lock:
            cls._gauges[(name, lbl_tuple)] = value

    @classmethod
    def observe_histogram(cls, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        lbl_tuple = tuple(sorted(labels.items())) if labels else ()
        with cls._lock:
            key = (name, lbl_tuple)
            if key not in cls._histograms:
                cls._histograms[key] = {
                    "count": 0,
                    "sum": 0.0,
                    "buckets": {b: 0 for b in cls._histogram_buckets}
                }
            entry = cls._histograms[key]
            entry["count"] += 1
            entry["sum"] += value
            for b in cls._histogram_buckets:
                if value <= b:
                    entry["buckets"][b] += 1

    @classmethod
    def record_http_request(cls, method: str, path: str, status_code: int, duration_seconds: float):
        # Normalize path
        norm_path = path if path.startswith("/api") or path.startswith("/health") else "other"
        labels = {"method": method, "path": norm_path, "status": str(status_code)}
        cls.inc_counter("aurastock_http_requests_total", 1.0, labels)
        cls.observe_histogram("aurastock_http_request_duration_seconds", duration_seconds, {"method": method, "path": norm_path})

    @classmethod
    def record_stock_transaction(cls, tx_type: str):
        cls.inc_counter("aurastock_stock_ledger_transactions_total", 1.0, {"type": tx_type})

    @classmethod
    def record_gl_voucher(cls, source_type: str):
        cls.inc_counter("aurastock_gl_vouchers_posted_total", 1.0, {"source_type": source_type})

    @classmethod
    def record_approval(cls, status: str, entity_type: str):
        cls.inc_counter("aurastock_approval_requests_total", 1.0, {"status": status, "entity_type": entity_type})

    @classmethod
    def record_edge_sync(cls, status: str):
        cls.inc_counter("aurastock_edge_sync_mutations_total", 1.0, {"status": status})

    @classmethod
    def generate_prometheus_metrics(cls) -> str:
        lines: List[str] = []
        with cls._lock:
            # Document standard metrics
            lines.append("# HELP aurastock_http_requests_total Total number of HTTP requests processed")
            lines.append("# TYPE aurastock_http_requests_total counter")
            for (name, labels), count in sorted(cls._counters.items()):
                if name == "aurastock_http_requests_total":
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl_str}}} {count}")

            lines.append("\n# HELP aurastock_http_request_duration_seconds HTTP request execution latency in seconds")
            lines.append("# TYPE aurastock_http_request_duration_seconds histogram")
            for (name, labels), data in sorted(cls._histograms.items()):
                if name == "aurastock_http_request_duration_seconds":
                    base_lbl = ",".join(f'{k}="{v}"' for k, v in labels)
                    prefix = f"{base_lbl}," if base_lbl else ""
                    for b in cls._histogram_buckets:
                        lines.append(f'{name}_bucket{{{prefix}le="{b}"}} {data["buckets"][b]}')
                    lines.append(f'{name}_bucket{{{prefix}le="+Inf"}} {data["count"]}')
                    lines.append(f"{name}_sum{{{base_lbl}}} {data['sum']:.6f}")
                    lines.append(f"{name}_count{{{base_lbl}}} {data['count']}")

            lines.append("\n# HELP aurastock_stock_ledger_transactions_total Total stock ledger transactions posted")
            lines.append("# TYPE aurastock_stock_ledger_transactions_total counter")
            for (name, labels), count in sorted(cls._counters.items()):
                if name == "aurastock_stock_ledger_transactions_total":
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl_str}}} {count}")

            lines.append("\n# HELP aurastock_gl_vouchers_posted_total Total General Ledger Journal Vouchers posted")
            lines.append("# TYPE aurastock_gl_vouchers_posted_total counter")
            for (name, labels), count in sorted(cls._counters.items()):
                if name == "aurastock_gl_vouchers_posted_total":
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl_str}}} {count}")

            lines.append("\n# HELP aurastock_approval_requests_total Total approval workflow requests")
            lines.append("# TYPE aurastock_approval_requests_total counter")
            for (name, labels), count in sorted(cls._counters.items()):
                if name == "aurastock_approval_requests_total":
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl_str}}} {count}")

            lines.append("\n# HELP aurastock_edge_sync_mutations_total Total edge synchronization mutations processed")
            lines.append("# TYPE aurastock_edge_sync_mutations_total counter")
            for (name, labels), count in sorted(cls._counters.items()):
                if name == "aurastock_edge_sync_mutations_total":
                    lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl_str}}} {count}")

            # Gauges
            lines.append("\n# HELP aurastock_active_gauges Active system gauges")
            lines.append("# TYPE aurastock_active_gauges gauge")
            for (name, labels), val in sorted(cls._gauges.items()):
                lbl_str = ",".join(f'{k}="{v}"' for k, v in labels)
                if lbl_str:
                    lines.append(f"{name}{{{lbl_str}}} {val}")
                else:
                    lines.append(f"{name} {val}")

        lines.append("") # Trailing newline
        return "\n".join(lines)
