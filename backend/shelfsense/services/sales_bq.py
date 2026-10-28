"""BigQuery-backed sales history (table ``<dataset>.sales_daily``: sku STRING, day DATE, units INT64, in_stock BOOL).

Load real POS data into that table (or the synthetic set via ``scripts/load_bigquery.py``) and set
``SALES_BACKEND=bigquery``. Results are cached briefly so a dashboard refresh doesn't re-query per SKU.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from typing import Any

_IDENT = re.compile(r"^[A-Za-z0-9_\-.]+$")


class BigQuerySales:
    def __init__(self, project: str | None, dataset: str, client: Any = None, ttl_s: float = 300.0) -> None:
        if not _IDENT.match(dataset) or (project and not _IDENT.match(project)):
            raise ValueError("invalid BigQuery project/dataset name")
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self.client = client
        self.table = f"{project or client.project}.{dataset}.sales_daily"
        self.ttl = ttl_s
        self._cache: dict[str, tuple[float, list[tuple[date, int, bool]]]] = {}
        self._lock = threading.Lock()

    def daily(self, sku: str) -> list[tuple[date, int, bool]]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(sku)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        from google.cloud import bigquery

        job = self.client.query(
            f"SELECT day, units, in_stock FROM `{self.table}` WHERE sku = @sku ORDER BY day",  # noqa: S608 - table validated in __init__
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("sku", "STRING", sku)]
            ),
        )
        rows = [(r["day"], int(r["units"]), bool(r["in_stock"])) for r in job.result()]
        with self._lock:
            self._cache[sku] = (now, rows)
        return rows
