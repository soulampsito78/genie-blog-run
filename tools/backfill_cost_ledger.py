#!/usr/bin/env python3
"""Safely backfill verified Vertex Standard text costs in a monthly ledger."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from admin_cost_ledger import cost_ledger_object_key  # noqa: E402
from admin_store import _get_gcs_bucket, admin_artifact_bucket_name  # noqa: E402
from genie_cost_estimate import (  # noqa: E402
    normalize_model_env_key,
    standard_text_pricing_for_model,
)

_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_TEXT_COST_COLUMNS = (
    "text_input_cost_usd",
    "text_output_cost_usd",
    "text_thoughts_cost_usd",
    "text_total_cost_usd",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_decimal(value: Decimal) -> str:
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _parse_nonnegative_int(raw: Any, field: str) -> int:
    value = str(raw if raw is not None else "").strip()
    if not value or not re.match(r"^[0-9]+$", value):
        raise ValueError(f"{field} must be a non-negative integer")
    return int(value)


def _decimal_or_none(raw: Any, field: str) -> Optional[Decimal]:
    value = str(raw if raw is not None else "").strip()
    if not value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return parsed


def _insert_text_total_column(fieldnames: Sequence[str]) -> List[str]:
    names = list(fieldnames)
    if "text_total_cost_usd" in names:
        return names
    anchor = "text_thoughts_cost_usd"
    if anchor in names:
        names.insert(names.index(anchor) + 1, "text_total_cost_usd")
    else:
        names.append("text_total_cost_usd")
    return names


def _render_csv(rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str], raw: str) -> str:
    line_ending = "\r\n" if "\r\n" in raw else "\n"
    out = io.StringIO(newline="")
    writer = csv.DictWriter(
        out,
        fieldnames=list(fieldnames),
        extrasaction="ignore",
        lineterminator=line_ending,
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _missing_image_price(row: Mapping[str, Any]) -> str:
    image_model = str(row.get("image_model") or "").strip()
    model_key = normalize_model_env_key(image_model)
    if not model_key:
        return "unknown_image_pricing"
    return f"GENIE_COST_{model_key}_USD_PER_IMAGE"


@dataclass
class BackfillPlan:
    source_text: str
    final_text: str
    source_sha256: str
    final_sha256: str
    row_count: int
    target_row_count: int
    changed_row_count: int
    model_counts: Dict[str, int]
    model_totals: Dict[str, Decimal]
    unknown_models: List[str]
    duplicate_run_ids: List[str]
    invalid_rows: List[str]
    changed_fields: List[str]
    text_total_nonempty_rows: int
    status_counts: Dict[str, int]

    @property
    def total_text_cost(self) -> Decimal:
        return sum(self.model_totals.values(), Decimal("0"))

    @property
    def can_apply(self) -> bool:
        return not self.duplicate_run_ids and not self.invalid_rows

    def as_report(self) -> Dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "final_sha256": self.final_sha256,
            "rows": self.row_count,
            "target_rows": self.target_row_count,
            "changed_rows": self.changed_row_count,
            "model_counts": dict(self.model_counts),
            "model_text_totals_usd": {
                key: _format_decimal(value) for key, value in self.model_totals.items()
            },
            "text_total_usd": _format_decimal(self.total_text_cost),
            "unknown_models": list(self.unknown_models),
            "unknown_model_count": len(self.unknown_models),
            "duplicate_run_ids": list(self.duplicate_run_ids),
            "duplicate_run_id_count": len(self.duplicate_run_ids),
            "invalid_rows": list(self.invalid_rows),
            "invalid_row_count": len(self.invalid_rows),
            "changed_fields": list(self.changed_fields),
            "text_total_nonempty_rows": self.text_total_nonempty_rows,
            "status_counts": dict(self.status_counts),
            "can_apply": self.can_apply,
        }


def build_backfill_plan(raw: str) -> BackfillPlan:
    reader = csv.DictReader(io.StringIO(raw, newline=""))
    original_fields = list(reader.fieldnames or [])
    if not original_fields:
        raise ValueError("ledger CSV has no header")
    required = {
        "run_id",
        "text_model",
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "total_token_count",
    }
    missing_columns = sorted(required.difference(original_fields))
    if missing_columns:
        raise ValueError("ledger CSV missing columns: " + ",".join(missing_columns))

    rows = [dict(row) for row in reader]
    run_ids = [str(row.get("run_id") or "").strip() for row in rows]
    duplicates = sorted(run_id for run_id, count in Counter(run_ids).items() if run_id and count > 1)
    fields = _insert_text_total_column(original_fields)
    model_counts: Counter[str] = Counter()
    model_totals: Counter[str] = Counter()
    unknown_models: List[str] = []
    invalid_rows: List[str] = []
    changed_fields = set()
    changed_rows = 0

    for index, row in enumerate(rows, start=2):
        before = dict(row)
        model = str(row.get("text_model") or "").strip()
        pricing = standard_text_pricing_for_model(model)
        if not pricing:
            unknown_models.append(model or f"<blank@row{index}>")
            continue
        canonical_model = str(pricing["model"])
        model_counts[canonical_model] += 1
        try:
            prompt = _parse_nonnegative_int(row.get("prompt_token_count"), "prompt_token_count")
            response = _parse_nonnegative_int(row.get("candidates_token_count"), "candidates_token_count")
            reasoning = _parse_nonnegative_int(row.get("thoughts_token_count"), "thoughts_token_count")
            total = _parse_nonnegative_int(row.get("total_token_count"), "total_token_count")
            if prompt + response + reasoning != total:
                raise ValueError("total_token_count does not equal prompt+response+reasoning")
            image_count_raw = str(row.get("generated_image_count") or "").strip()
            image_count = (
                _parse_nonnegative_int(image_count_raw, "generated_image_count")
                if image_count_raw
                else None
            )
            for cost_field in (*_TEXT_COST_COLUMNS, "image_cost_usd", "total_cost_usd", "total_cost_krw"):
                _decimal_or_none(row.get(cost_field), cost_field)
        except ValueError as exc:
            invalid_rows.append(f"row={index} run_id={row.get('run_id')}: {exc}")
            continue

        input_rate = Decimal(str(pricing["input_usd_per_1m_tokens"]))
        output_rate = Decimal(str(pricing["output_and_reasoning_usd_per_1m_tokens"]))
        denominator = Decimal("1000000")
        canonical_costs = {
            "text_input_cost_usd": Decimal(prompt) * input_rate / denominator,
            "text_output_cost_usd": Decimal(response) * output_rate / denominator,
            "text_thoughts_cost_usd": Decimal(reasoning) * output_rate / denominator,
        }
        canonical_total = sum(canonical_costs.values(), Decimal("0"))
        model_totals[canonical_model] += canonical_total

        for field, value in canonical_costs.items():
            if not str(row.get(field) or "").strip():
                row[field] = _format_decimal(value)
        if not str(row.get("text_total_cost_usd") or "").strip():
            component_total = sum(
                (_decimal_or_none(row.get(field), field) or Decimal("0"))
                for field in canonical_costs
            )
            row["text_total_cost_usd"] = _format_decimal(component_total)

        text_total = _decimal_or_none(row.get("text_total_cost_usd"), "text_total_cost_usd")
        image_cost = _decimal_or_none(row.get("image_cost_usd"), "image_cost_usd")
        if image_cost is not None or image_count == 0:
            if not str(row.get("total_cost_usd") or "").strip() and text_total is not None:
                row["total_cost_usd"] = _format_decimal(text_total + (image_cost or Decimal("0")))
            row["cost_estimate_status"] = "estimated"
            row["missing_price_env"] = ""
        else:
            # Blank image count is unknown, never zero. Keep the complete
            # production total blank and expose the verified text subtotal.
            row["cost_estimate_status"] = "partial_text_only"
            row["missing_price_env"] = _missing_image_price(row)
        row["pricing_source"] = "google_cloud_vertex_ai_standard"
        row["price_env_configured"] = "true"

        if row != before:
            changed_rows += 1
            changed_fields.update(key for key in fields if str(before.get(key, "")) != str(row.get(key, "")))

    final_text = _render_csv(rows, fields, raw)
    status_counts = Counter(str(row.get("cost_estimate_status") or "") for row in rows)
    nonempty_text_totals = sum(bool(str(row.get("text_total_cost_usd") or "").strip()) for row in rows)
    return BackfillPlan(
        source_text=raw,
        final_text=final_text,
        source_sha256=_sha256(raw),
        final_sha256=_sha256(final_text),
        row_count=len(rows),
        target_row_count=sum(model_counts.values()),
        changed_row_count=changed_rows,
        model_counts=dict(model_counts),
        model_totals=dict(model_totals),
        unknown_models=unknown_models,
        duplicate_run_ids=duplicates,
        invalid_rows=invalid_rows,
        changed_fields=sorted(changed_fields),
        text_total_nonempty_rows=nonempty_text_totals,
        status_counts=dict(status_counts),
    )


@dataclass
class LedgerDocument:
    text: str
    generation: int


class GCSLedgerStore:
    def __init__(self, bucket: Any) -> None:
        self.bucket = bucket

    def read(self, key: str) -> LedgerDocument:
        blob = self.bucket.get_blob(key)
        if blob is None:
            raise FileNotFoundError(key)
        generation = int(blob.generation)
        data = blob.download_as_bytes(if_generation_match=generation)
        return LedgerDocument(data.decode("utf-8"), generation)

    def create(self, key: str, text: str) -> LedgerDocument:
        blob = self.bucket.blob(key)
        blob.upload_from_string(
            text,
            content_type="text/csv; charset=utf-8",
            if_generation_match=0,
        )
        return self.read(key)

    def replace_from_object(self, source_key: str, destination_key: str, expected_generation: int) -> LedgerDocument:
        source = self.bucket.get_blob(source_key)
        if source is None:
            raise FileNotFoundError(source_key)
        source_generation = int(source.generation)
        self.bucket.copy_blob(
            source,
            self.bucket,
            new_name=destination_key,
            source_generation=source_generation,
            if_generation_match=expected_generation,
            if_source_generation_match=source_generation,
        )
        return self.read(destination_key)


def _object_targets(key: str, source_sha: str) -> Tuple[str, str]:
    parent, filename = key.rsplit("/", 1)
    stem = filename[:-4] if filename.endswith(".csv") else filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"{timestamp}.{source_sha[:16]}.csv"
    return (
        f"{parent}/backups/{stem}.{suffix}",
        f"{parent}/tmp/{stem}.{suffix}",
    )


def execute(store: Any, bucket_name: str, month: str, mode: str) -> Dict[str, Any]:
    key = cost_ledger_object_key(month)
    source = store.read(key)
    plan = build_backfill_plan(source.text)
    backup_key, temp_key = _object_targets(key, plan.source_sha256)
    report = plan.as_report()
    report.update(
        {
            "mode": mode,
            "source": f"gs://{bucket_name}/{key}",
            "destination": f"gs://{bucket_name}/{key}",
            "source_generation": source.generation,
            "backup_destination": f"gs://{bucket_name}/{backup_key}",
            "temporary_destination": f"gs://{bucket_name}/{temp_key}",
            "mutation": False,
        }
    )
    if mode in ("dry-run", "verify"):
        report["verification_pass"] = plan.can_apply and (
            mode == "dry-run" or plan.changed_row_count == 0
        )
        return report
    if mode != "apply":
        raise ValueError(f"unsupported mode: {mode}")
    if not plan.can_apply:
        raise RuntimeError("backfill plan has duplicate or invalid rows")
    if plan.changed_row_count == 0:
        report["idempotent_noop"] = True
        report["verification_pass"] = True
        return report

    backup = store.create(backup_key, source.text)
    if _sha256(backup.text) != plan.source_sha256:
        raise RuntimeError("backup verification failed before replacement")
    temporary = store.create(temp_key, plan.final_text)
    if _sha256(temporary.text) != plan.final_sha256:
        raise RuntimeError("temporary object verification failed before replacement")

    try:
        final = store.replace_from_object(temp_key, key, source.generation)
        if _sha256(final.text) != plan.final_sha256:
            raise RuntimeError("final object hash mismatch")
        verified = build_backfill_plan(final.text)
        if verified.row_count != plan.row_count or verified.changed_row_count != 0:
            raise RuntimeError("final object row/idempotency verification failed")
    except Exception as exc:
        current = store.read(key)
        original_preserved = _sha256(current.text) == plan.source_sha256
        if not original_preserved:
            restored = store.replace_from_object(backup_key, key, current.generation)
            original_preserved = _sha256(restored.text) == plan.source_sha256
        raise RuntimeError(
            f"atomic replacement failed; original_preserved={str(original_preserved).lower()}: {exc}"
        ) from exc

    report.update(
        {
            "backup_sha256": _sha256(backup.text),
            "backup_generation": backup.generation,
            "temporary_sha256": _sha256(temporary.text),
            "final_sha256": _sha256(final.text),
            "final_generation": final.generation,
            "atomic_replacement": True,
            "mutation": True,
            "verification_pass": True,
        }
    )
    return report


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if not _MONTH_RE.match(args.month):
        parser.error("--month must be YYYY-MM")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    mode = "apply" if args.apply else ("verify" if args.verify else "dry-run")
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        print(json.dumps({"error": "GENIE_ARTIFACT_BUCKET is required", "mutation": False}))
        return 2
    try:
        report = execute(GCSLedgerStore(_get_gcs_bucket()), bucket_name, args.month, mode)
    except Exception as exc:
        print(json.dumps({"error": str(exc), "mode": mode}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
