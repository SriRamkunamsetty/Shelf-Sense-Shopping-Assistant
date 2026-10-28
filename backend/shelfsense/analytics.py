"""Optional analytics sink: stream demand events to BigQuery for BI (Looker Studio) and BQML.

Disabled unless ``BIGQUERY_DATASET`` is set. The table is created on first use. Failures never
propagate to the shopper path (see ``DemandService.log``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .config import Settings
from .domain import DemandEvent

log = logging.getLogger("shelfsense.analytics")

SCHEMA = [
    ("id", "STRING"),
    ("ts", "TIMESTAMP"),
    ("customer_id", "STRING"),
    ("need_text", "STRING"),
    ("need_key", "STRING"),
    ("language", "STRING"),
    ("outcome", "STRING"),
    ("coverage", "FLOAT"),
    ("budget", "FLOAT"),
    ("est_value", "FLOAT"),
    ("channel", "STRING"),
    ("matched_skus", "STRING"),
]


def build_sink(s: Settings) -> Callable[[DemandEvent], None] | None:
    if not s.bigquery_dataset:
        return None
    from google.cloud import bigquery

    client = bigquery.Client(project=s.google_cloud_project)
    table_id = f"{client.project}.{s.bigquery_dataset}.demand_events"
    try:
        client.get_table(table_id)
    except Exception:
        client.create_dataset(s.bigquery_dataset, exists_ok=True)
        client.create_table(bigquery.Table(table_id, schema=[bigquery.SchemaField(n, t) for n, t in SCHEMA]))
        log.info("created BigQuery table %s", table_id)

    def sink(ev: DemandEvent) -> None:
        row = {
            "id": ev.id,
            "ts": ev.ts.isoformat(),
            "customer_id": ev.customer_id,
            "need_text": ev.need_text,
            "need_key": ev.need_key,
            "language": ev.language,
            "outcome": ev.outcome.value,
            "coverage": ev.coverage,
            "budget": ev.budget,
            "est_value": ev.est_value,
            "channel": ev.channel,
            "matched_skus": ",".join(ev.matched_skus),
        }
        errors = client.insert_rows_json(table_id, [row])
        if errors:
            log.warning("BigQuery insert errors: %s", errors)

    return sink
