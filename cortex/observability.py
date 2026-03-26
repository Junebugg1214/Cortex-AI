from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RouteMetric:
    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0

    def add(self, duration_ms: float, *, error: bool) -> None:
        self.count += 1
        if error:
            self.errors += 1
        self.total_duration_ms += duration_ms
        self.max_duration_ms = max(self.max_duration_ms, duration_ms)

    def to_dict(self) -> dict[str, Any]:
        average = round(self.total_duration_ms / self.count, 4) if self.count else 0.0
        return {
            "count": self.count,
            "errors": self.errors,
            "avg_duration_ms": average,
            "max_duration_ms": round(self.max_duration_ms, 4),
        }


@dataclass(slots=True)
class CortexObservability:
    store_dir: Path
    log_path: Path = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _request_count: int = 0
    _error_count: int = 0
    _routes: dict[str, RouteMetric] = field(default_factory=dict)
    _last_event: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.store_dir = Path(self.store_dir)
        self.log_path = self.store_dir / "logs" / "cortexd.jsonl"

    def _append_event(self, payload: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def record_request(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        namespace: str,
        backend: str,
        index_lag_commits: int | None = None,
        error: str = "",
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        route = path.split("?", 1)[0]
        payload = {
            "type": "request",
            "timestamp": timestamp,
            "request_id": request_id,
            "method": method,
            "path": route,
            "status": status,
            "duration_ms": round(duration_ms, 4),
            "namespace": namespace,
            "backend": backend,
            "index_lag_commits": index_lag_commits,
            "error": error,
        }
        with self._lock:
            self._request_count += 1
            is_error = status >= 400
            if is_error:
                self._error_count += 1
            metric = self._routes.setdefault(route, RouteMetric())
            metric.add(duration_ms, error=is_error)
            self._last_event = payload
            self._append_event(payload)

    def metrics(
        self, *, index_status: dict[str, Any] | None = None, backend: str = "", current_branch: str = ""
    ) -> dict[str, Any]:
        with self._lock:
            routes = {route: metric.to_dict() for route, metric in sorted(self._routes.items())}
            last_event = dict(self._last_event) if self._last_event else None
            request_count = self._request_count
            error_count = self._error_count
        return {
            "status": "ok",
            "backend": backend,
            "current_branch": current_branch,
            "requests_total": request_count,
            "errors_total": error_count,
            "routes": routes,
            "log_path": str(self.log_path),
            "last_event": last_event,
            "index": index_status or {},
        }


__all__ = ["CortexObservability", "RouteMetric"]
