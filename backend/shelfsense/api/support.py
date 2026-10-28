"""Cross-cutting concerns: structured logging (Cloud Logging format), rate limiting, auth."""

from __future__ import annotations

import contextvars
import hmac
import json
import logging
import sys
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SEVERITY = {"DEBUG": "DEBUG", "INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "CRITICAL"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line with Cloud Logging's ``severity`` / ``message`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": _SEVERITY.get(record.levelname, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "google_adk", "google.adk", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RateLimiter:
    """Sliding-window limiter per client key. In-process: put Cloud Armor / API Gateway in front for fleet-wide limits."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory
                self._hits.clear()
            return True


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def make_ops_guard(api_key: str | None):
    """Dependency: when OPS_API_KEY is configured, owner endpoints require a matching X-API-Key header."""

    def guard(x_api_key: str | None = Header(default=None)) -> str:
        if api_key is None:
            return "owner"
        if not x_api_key or not hmac.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
        return "owner"

    return guard
