#!/usr/bin/env python3
"""Atomically add GCP infra estimates and shared-overhead allocation to a ledger."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from admin_cost_ledger import COST_LEDGER_COLUMNS, cost_ledger_object_key  # noqa: E402
from admin_store import _get_gcs_bucket, admin_artifact_bucket_name  # noqa: E402
from genie_billing_export import decimal_or_none, decimal_text  # noqa: E402
from genie_cost_allocation import allocation_metrics  # noqa: E402
from tools.backfill_cost_ledger import (  # noqa: E402
    GCSLedgerStore,
    _object_targets,
    _render_csv,
    _sha256,
)

_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_AI_PROTECTED = (
    "text_input_cost_usd", "text_output_cost_usd", "text_thoughts_cost_usd",
    "text_total_cost_usd", "image_cost_usd", "image_list_price_cost_usd",
    "total_cost_usd", "cost_estimate_status",
)


@dataclass
class InfraBackfillPlan:
    source_text: str
    final_text: str
    source_sha256: str
    final_sha256: str
    row_count: int
    changed_row_count: int
    operational_run_count: int
    delivered_run_count: int
    allocation_per_run: Optional[str]
    invalid_rows: List[str]

    @property
    def can_apply(self) -> bool:
        return not self.invalid_rows

    def report(self) -> Dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "final_sha256": self.final_sha256,
            "rows": self.row_count,
            "changed_rows": self.changed_row_count,
            "operational_runs": self.operational_run_count,
            "delivered_runs": self.delivered_run_count,
            "shared_overhead_per_operational_run": self.allocation_per_run,
            "invalid_rows": self.invalid_rows,
            "can_apply": self.can_apply,
        }


def build_infra_backfill_plan(raw: str, summary: Mapping[str, Any]) -> InfraBackfillPlan:
    reader = csv.DictReader(io.StringIO(raw, newline=""))
    fields = list(reader.fieldnames or [])
    if not fields or "run_id" not in fields:
        raise ValueError("ledger CSV missing run_id")
    rows = [dict(row) for row in reader]
    for column in COST_LEDGER_COLUMNS:
        if column not in fields:
            fields.append(column)
    allocation = allocation_metrics(summary.get("shared_platform_net"), rows)
    per_run = decimal_or_none(allocation.get("shared_overhead_per_operational_run"))
    changed = 0
    invalid: List[str] = []
    for index, row in enumerate(rows, start=2):
        before = dict(row)
        protected = {key: row.get(key) for key in _AI_PROTECTED}
        ai = decimal_or_none(row.get("total_cost_usd"))
        direct = decimal_or_none(row.get("run_direct_infra_list_estimate_usd"))
        if ai is not None:
            row["ai_model_direct_cost_usd"] = decimal_text(ai)
        if per_run is not None:
            row["allocated_shared_overhead_usd"] = decimal_text(per_run)
            row["cogs_allocation_policy"] = allocation["cogs_allocation_policy"]
        if ai is not None and direct is not None and per_run is not None:
            row["run_modeled_cogs_usd"] = decimal_text(ai + direct + per_run)
            row["cogs_confidence"] = "modeled_list_infra_plus_actual_shared"
        else:
            row["run_modeled_cogs_usd"] = ""
            row["cogs_confidence"] = "partial"
        if any(row.get(key) != value for key, value in protected.items()):
            invalid.append(f"row={index}: AI cost field mutation")
            row.clear()
            row.update(before)
        if row != before:
            changed += 1
    final = _render_csv(rows, fields, raw)
    return InfraBackfillPlan(
        raw, final, _sha256(raw), _sha256(final), len(rows), changed,
        allocation["operational_run_count"], allocation["delivered_run_count"],
        allocation.get("shared_overhead_per_operational_run"), invalid,
    )


def execute(
    store: Any, bucket_name: str, month: str, summary: Mapping[str, Any], mode: str
) -> Dict[str, Any]:
    key = cost_ledger_object_key(month)
    source = store.read(key)
    plan = build_infra_backfill_plan(source.text, summary)
    backup_key, temp_key = _object_targets(key, plan.source_sha256)
    report = plan.report()
    report.update({"mode": mode, "source_generation": source.generation, "mutation": False})
    if mode in ("dry-run", "verify"):
        report["verification_pass"] = plan.can_apply and (mode == "dry-run" or plan.changed_row_count == 0)
        return report
    if mode != "apply" or not plan.can_apply:
        raise RuntimeError("infra backfill cannot apply")
    if plan.changed_row_count == 0:
        report.update({"idempotent_noop": True, "verification_pass": True})
        return report
    backup = store.create(backup_key, source.text)
    temporary = store.create(temp_key, plan.final_text)
    if _sha256(backup.text) != plan.source_sha256 or _sha256(temporary.text) != plan.final_sha256:
        raise RuntimeError("backup or temporary verification failed")
    try:
        final = store.replace_from_object(temp_key, key, source.generation)
        verified = build_infra_backfill_plan(final.text, summary)
        if _sha256(final.text) != plan.final_sha256 or verified.changed_row_count != 0:
            raise RuntimeError("final verification failed")
    except Exception as exc:
        current = store.read(key)
        preserved = _sha256(current.text) == plan.source_sha256
        if not preserved:
            restored = store.replace_from_object(backup_key, key, current.generation)
            preserved = _sha256(restored.text) == plan.source_sha256
        raise RuntimeError(f"atomic replacement failed; original_preserved={preserved}: {exc}") from exc
    report.update({
        "backup_generation": backup.generation,
        "final_generation": final.generation,
        "atomic_replacement": True,
        "mutation": True,
        "verification_pass": True,
    })
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--summary", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if not _MONTH_RE.match(args.month):
        parser.error("--month must be YYYY-MM")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    mode = "apply" if args.apply else "verify" if args.verify else "dry-run"
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        raise RuntimeError("GENIE_ADMIN_ARTIFACT_BUCKET is required")
    report = execute(GCSLedgerStore(_get_gcs_bucket()), bucket_name, args.month, summary, mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
