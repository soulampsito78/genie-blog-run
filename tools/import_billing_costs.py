#!/usr/bin/env python3
"""Read Cloud Billing export safely and publish a monthly billing summary."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from admin_store import _get_gcs_bucket, admin_artifact_bucket_name  # noqa: E402
from genie_billing_export import (  # noqa: E402
    DATASET_ID, PROJECT_ID, aggregate_monthly_rows, billing_summary_object_key,
)
from tools.backfill_cost_ledger import GCSLedgerStore, _sha256  # noqa: E402
from tools.backfill_infra_cost_ledger import execute as execute_ledger_backfill  # noqa: E402

_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
DEFAULT_MAX_BYTES = 100_000_000


def month_utc_bounds(month: str) -> Tuple[str, str]:
    start_kst = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Seoul"))
    if start_kst.month == 12:
        end_kst = start_kst.replace(year=start_kst.year + 1, month=1)
    else:
        end_kst = start_kst.replace(month=start_kst.month + 1)
    return start_kst.astimezone(timezone.utc).isoformat(), end_kst.astimezone(timezone.utc).isoformat()


def build_query(source_table: str, month: str) -> str:
    start, end = month_utc_bounds(month)
    return f"""
SELECT service.id AS service_id, service.description AS service_description,
       sku.id AS sku_id, sku.description AS sku_description,
       invoice.month AS invoice_month, currency, currency_conversion_rate,
       SUM(CAST(cost AS NUMERIC)) AS gross_cost,
       SUM(IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits) c), 0)) AS credits,
       MIN(usage_start_time) AS usage_start_time, MAX(usage_end_time) AS usage_end_time,
       MAX(_PARTITIONTIME) AS exported_at, COUNT(*) AS billing_row_count
FROM `{source_table}`
WHERE project.id = '{PROJECT_ID}'
  AND usage_start_time >= TIMESTAMP('{start}')
  AND usage_start_time < TIMESTAMP('{end}')
GROUP BY service_id, service_description, sku_id, sku_description,
         invoice_month, currency, currency_conversion_rate
ORDER BY service_description, sku_description
""".strip()


def rows_for_aggregation(query_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in query_rows:
        result.append({
            "project": {"id": PROJECT_ID, "name": PROJECT_ID},
            "service": {"id": row.get("service_id"), "description": row.get("service_description")},
            "sku": {"id": row.get("sku_id"), "description": row.get("sku_description")},
            "invoice": {"month": row.get("invoice_month")},
            "cost": row.get("gross_cost"),
            "credits": [{"amount": row.get("credits")}],
            "currency": row.get("currency"),
            "currency_conversion_rate": row.get("currency_conversion_rate"),
            "usage_start_time": row.get("usage_start_time"),
            "usage_end_time": row.get("usage_end_time"),
            "exported_at": row.get("exported_at"),
        })
    return result


def _run_json(args: Sequence[str]) -> Any:
    completed = subprocess.run(list(args), check=True, capture_output=True, text=True)
    return json.loads(completed.stdout or "[]")


def discover_source_table() -> Optional[str]:
    tables = _run_json(["bq", "ls", "--format=prettyjson", f"{PROJECT_ID}:{DATASET_ID}"])
    ids = [str((item.get("tableReference") or {}).get("tableId") or "") for item in tables]
    detailed = next((table for table in ids if table.startswith("gcp_billing_export_resource_v1_")), None)
    standard = next((table for table in ids if table.startswith("gcp_billing_export_v1_")), None)
    selected = detailed or standard
    return f"{PROJECT_ID}.{DATASET_ID}.{selected}" if selected else None


def export_service_account_status() -> Dict[str, bool]:
    dataset = _run_json(["bq", "show", "--format=prettyjson", f"{PROJECT_ID}:{DATASET_ID}"])
    members = {
        str(item.get("userByEmail") or "")
        for item in (dataset.get("access") or [])
        if isinstance(item, Mapping)
    }
    return {
        "usage_export_writer": "billing-export-bigquery@system.gserviceaccount.com" in members,
        "pricing_export_writer": "cloud-account-pricing@cloud-account-pricing.iam.gserviceaccount.com" in members,
    }


def dry_run_query(query: str, maximum_bytes: int) -> int:
    completed = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--dry_run", "--format=prettyjson",
         f"--maximum_bytes_billed={maximum_bytes}", query],
        check=True, capture_output=True, text=True,
    )
    match = re.search(r"(\d+)\s+bytes", completed.stdout + completed.stderr)
    return int(match.group(1)) if match else 0


def execute_query(query: str, maximum_bytes: int) -> List[Dict[str, Any]]:
    data = _run_json([
        "bq", "query", "--use_legacy_sql=false", "--format=prettyjson",
        f"--maximum_bytes_billed={maximum_bytes}", query,
    ])
    return [dict(row) for row in data]


def build_summary(
    month: str, source_table: str, query: str, query_bytes: int,
    query_rows: Sequence[Mapping[str, Any]], maximum_bytes: int,
) -> Dict[str, Any]:
    summary = aggregate_monthly_rows(rows_for_aggregation(query_rows))
    summary.update({
        "month": month,
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "source_table": source_table,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "query_bytes": query_bytes,
        "maximum_bytes_billed": maximum_bytes,
        "imported_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "service_sku_group_count": len(query_rows),
    })
    return summary


def atomic_write_summary(bucket: Any, key: str, payload: str) -> Dict[str, Any]:
    source = bucket.get_blob(key)
    digest = _sha256(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parent, filename = key.rsplit("/", 1)
    temp_key = f"{parent}/tmp/{filename}.{stamp}.{digest[:16]}.json"
    temp = bucket.blob(temp_key)
    temp.upload_from_string(payload, content_type="application/json", if_generation_match=0)
    if source is None:
        created = bucket.copy_blob(temp, bucket, new_name=key, if_generation_match=0)
        return {"summary_generation": int(created.generation), "backup_generation": None}
    generation = int(source.generation)
    backup_key = f"{parent}/backups/{filename}.{stamp}.{generation}.json"
    backup = bucket.copy_blob(source, bucket, new_name=backup_key, source_generation=generation, if_generation_match=0)
    final = bucket.copy_blob(
        temp, bucket, new_name=key, source_generation=int(temp.generation),
        if_generation_match=generation, if_source_generation_match=int(temp.generation),
    )
    return {"summary_generation": int(final.generation), "backup_generation": int(backup.generation)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--maximum-bytes-billed", type=int, default=DEFAULT_MAX_BYTES)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not _MONTH_RE.match(args.month):
        parser.error("--month must be YYYY-MM")
    source = discover_source_table()
    if source is None:
        export_writers = export_service_account_status()
        configured = all(export_writers.values())
        print(json.dumps({
            "month": args.month,
            "billing_data_status": "billing_export_pending" if configured else "billing_export_not_enabled",
            "export_service_accounts": export_writers,
            "state": (
                "COST_INFRA_BILLING_EXPORT_FOUNDATION_PASS_DATA_BACKFILL_PENDING"
                if configured else "COST_INFRA_BILLING_EXPORT_SETUP_FAIL"
            ),
            "mutation": False,
        }, indent=2))
        return 0
    query = build_query(source, args.month)
    query_bytes = dry_run_query(query, args.maximum_bytes_billed)
    rows = execute_query(query, args.maximum_bytes_billed)
    summary = build_summary(args.month, source, query, query_bytes, rows, args.maximum_bytes_billed)
    if not rows:
        summary.update({"state": "COST_INFRA_BILLING_DATA_PARTIAL_WAITING_EXPORT_CATCHUP", "mutation": False})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if summary.get("billing_data_freshness") == "billing_data_stale":
        summary.update({"state": "COST_INFRA_BILLING_DATA_PARTIAL_WAITING_EXPORT_CATCHUP", "mutation": False})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.dry_run:
        summary["mutation"] = False
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        raise RuntimeError("GENIE_ADMIN_ARTIFACT_BUCKET is required")
    bucket = _get_gcs_bucket()
    ledger_report = execute_ledger_backfill(
        GCSLedgerStore(bucket), bucket_name, args.month, summary, "apply"
    )
    write_report = atomic_write_summary(
        bucket, billing_summary_object_key(args.month),
        json.dumps(summary, ensure_ascii=False, indent=2),
    )
    summary.update({"mutation": True, "ledger_backfill": ledger_report, **write_report})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
