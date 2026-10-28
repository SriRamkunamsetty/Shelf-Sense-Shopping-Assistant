"""Load the synthetic sales history into BigQuery (table: <dataset>.sales_daily) for BQML / Looker Studio.

Usage: python scripts/load_bigquery.py --project my-proj --dataset shelfsense
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from google.cloud import bigquery  # noqa: E402

from shelfsense.seed import build_sales  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--project", required=True)
ap.add_argument("--dataset", default="shelfsense")
a = ap.parse_args()

client = bigquery.Client(project=a.project)
client.create_dataset(a.dataset, exists_ok=True)
rows = [
    {"sku": sku, "day": r.day.isoformat(), "units": r.units, "in_stock": r.in_stock}
    for sku, series in build_sales().items()
    for r in series
]
job = client.load_table_from_json(
    rows,
    f"{a.project}.{a.dataset}.sales_daily",
    job_config=bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        schema=[
            bigquery.SchemaField("sku", "STRING"), bigquery.SchemaField("day", "DATE"),
            bigquery.SchemaField("units", "INT64"), bigquery.SchemaField("in_stock", "BOOL"),
        ],
    ),
)
job.result()
print(f"loaded {len(rows)} rows into {a.dataset}.sales_daily")
