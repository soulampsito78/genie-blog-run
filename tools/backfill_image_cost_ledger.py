#!/usr/bin/env python3
"""Evidence-gated, atomic image-cost backfill for a monthly Genie ledger."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from admin_cost_ledger import COST_LEDGER_COLUMNS, cost_ledger_object_key  # noqa: E402
from admin_store import _get_gcs_bucket, admin_artifact_bucket_name, admin_artifact_gcs_prefix  # noqa: E402
from tools.backfill_cost_ledger import (  # noqa: E402
    GCSLedgerStore,
    _format_decimal,
    _object_targets,
    _render_csv,
    _sha256,
)

_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_EVIDENCE_DIR = REPO_ROOT / "evidence"
_IMAGE_FIELDS = (
    "image_model",
    "generated_image_count",
    "generated_image_count_semantics",
    "image_api_provider",
    "image_model_raw",
    "image_model_normalized",
    "image_pricing_mode",
    "image_request_count",
    "image_successful_output_count",
    "image_failed_request_count",
    "image_retry_count",
    "image_discarded_output_count",
    "image_locally_derived_asset_count",
    "image_cache_reuse_count",
    "image_static_fallback_count",
    "image_output_tokens",
    "image_cost_usd",
    "image_list_price_cost_usd",
    "image_billed_cost_usd",
    "billing_reconciliation_status",
    "image_cost_estimate_status",
    "image_unit_price_usd",
    "image_pricing_source",
    "image_pricing_checked_at",
    "image_evidence_confidence",
    "image_evidence_source",
)


def load_evidence(month: str, path: Optional[Path] = None) -> Dict[str, Any]:
    source = path or (_EVIDENCE_DIR / f"genie_cost_image_evidence_{month}.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("month") != month or not isinstance(data.get("runs"), list):
        raise ValueError("evidence month/schema mismatch")
    contract = data.get("pricing_contract") or {}
    rate = Decimal(str(contract.get("output_image_usd_per_1m_tokens")))
    tokens = int(contract.get("output_tokens_per_image"))
    for item in data["runs"]:
        run_id = str(item.get("run_id") or "")
        count = int(item.get("successful_output_count") or 0)
        item.setdefault(
            "created_at_kst",
            f"{run_id[0:4]}-{run_id[4:6]}-{run_id[6:8]}T{run_id[9:11]}:{run_id[11:13]}:{run_id[13:15]}+09:00",
        )
        item.setdefault("image_api_provider", contract.get("provider"))
        item.setdefault("image_model_raw", contract.get("model"))
        item.setdefault("image_model_normalized", contract.get("model"))
        item.setdefault("generated_artifact_count", len(item.get("objects") or []))
        item.setdefault(
            "evidence_source",
            [
                "exact_cloud_run_revision_and_commit",
                "revision_model_default_and_no_override",
                "run_artifact_api_success_and_generated_source",
                "durable_nonempty_gcs_output_object",
                "one_request_one_output_no_retry_code_contract",
            ],
        )
        item.setdefault("pricing_unit", contract.get("pricing_mode"))
        item.setdefault("applicable_rate", str(rate))
        item.setdefault(
            "estimated_image_cost_usd",
            _format_decimal(Decimal(count * tokens) * rate / Decimal("1000000")),
        )
        item.setdefault("backfill_allowed", item.get("confidence") == "high")
        item.setdefault(
            "calculation",
            f"{count} outputs * {tokens} tokens/output * {rate} USD/1M tokens",
        )
    return data


def _decimal(raw: Any, field: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return value


def _int(raw: Any, field: str) -> int:
    value = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{field} must be a non-negative integer")
    return int(value)


def _set_verified(row: Dict[str, Any], field: str, value: Any) -> None:
    canonical = "" if value is None else str(value)
    existing = str(row.get(field) or "").strip()
    if existing and existing != canonical:
        raise ValueError(f"existing {field} conflicts with evidence")
    row[field] = canonical


@dataclass
class ImageBackfillPlan:
    source_text: str
    final_text: str
    source_sha256: str
    final_sha256: str
    row_count: int
    changed_row_count: int
    high_confidence_count: int
    insufficient_count: int
    paid_output_count: int
    locally_derived_count: int
    failed_request_count: int
    retry_count: int
    discarded_output_count: int
    cache_reuse_count: int
    static_fallback_count: int
    image_total: Decimal
    text_total: Decimal
    complete_total: Decimal
    invalid_rows: List[str]
    duplicate_run_ids: List[str]
    status_counts: Dict[str, int]
    model_counts: Dict[str, int]
    model_image_totals: Dict[str, Decimal]

    @property
    def can_apply(self) -> bool:
        return not self.invalid_rows and not self.duplicate_run_ids

    def report(self) -> Dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "final_sha256": self.final_sha256,
            "rows": self.row_count,
            "changed_rows": self.changed_row_count,
            "high_confidence_rows": self.high_confidence_count,
            "medium_confidence_rows": 0,
            "insufficient_evidence_rows": self.insufficient_count,
            "paid_successful_output_count": self.paid_output_count,
            "locally_derived_asset_count": self.locally_derived_count,
            "failed_request_count": self.failed_request_count,
            "retry_count": self.retry_count,
            "discarded_output_count": self.discarded_output_count,
            "cache_reuse_count": self.cache_reuse_count,
            "static_fallback_count": self.static_fallback_count,
            "image_list_price_total_usd": _format_decimal(self.image_total),
            "text_total_usd": _format_decimal(self.text_total),
            "complete_ai_model_total_usd": _format_decimal(self.complete_total),
            "invalid_rows": self.invalid_rows,
            "duplicate_run_ids": self.duplicate_run_ids,
            "status_counts": self.status_counts,
            "model_counts": self.model_counts,
            "model_image_totals_usd": {
                model: _format_decimal(value)
                for model, value in self.model_image_totals.items()
            },
            "can_apply": self.can_apply,
        }


def build_backfill_plan(raw: str, evidence: Mapping[str, Any]) -> ImageBackfillPlan:
    reader = csv.DictReader(io.StringIO(raw, newline=""))
    original_fields = list(reader.fieldnames or [])
    if not original_fields:
        raise ValueError("ledger CSV has no header")
    for required in ("run_id", "text_total_cost_usd"):
        if required not in original_fields:
            raise ValueError(f"ledger CSV missing column: {required}")
    rows = [dict(row) for row in reader]
    run_counts = Counter(str(row.get("run_id") or "").strip() for row in rows)
    duplicates = sorted(key for key, count in run_counts.items() if key and count > 1)
    evidence_by_run = {
        str(item.get("run_id") or ""): item for item in evidence.get("runs", [])
    }
    contract = evidence.get("pricing_contract") or {}
    rate = _decimal(contract.get("output_image_usd_per_1m_tokens"), "image rate")
    tokens_per_output = _int(contract.get("output_tokens_per_image"), "tokens per output")
    fields = list(original_fields)
    for field in COST_LEDGER_COLUMNS:
        if field not in fields:
            fields.append(field)

    invalid: List[str] = []
    changed = high = insufficient = outputs = local = failed = retries = discarded = cache = fallback = 0
    image_total = text_total = complete_total = Decimal("0")
    model_counts: Counter[str] = Counter()
    model_totals: Counter[str] = Counter()
    for index, row in enumerate(rows, start=2):
        before = dict(row)
        run_id = str(row.get("run_id") or "").strip()
        item = evidence_by_run.get(run_id)
        text_cost_raw = str(row.get("text_total_cost_usd") or "").strip()
        if text_cost_raw:
            try:
                text_total += _decimal(text_cost_raw, "text_total_cost_usd")
            except ValueError as exc:
                invalid.append(f"row={index} run_id={run_id}: {exc}")
        if not item or item.get("confidence") != "high":
            insufficient += 1
            continue
        high += 1
        try:
            count = _int(item.get("successful_output_count"), "successful_output_count")
            requests = _int(item.get("image_request_count"), "image_request_count")
            failed_count = _int(item.get("failed_request_count"), "failed_request_count")
            retry_count = _int(item.get("retry_count"), "retry_count")
            discarded_count = _int(item.get("discarded_output_count"), "discarded_output_count")
            local_count = _int(item.get("locally_derived_asset_count"), "locally_derived_asset_count")
            cache_count = _int(item.get("cache_reuse_count"), "cache_reuse_count")
            fallback_count = _int(item.get("static_fallback_count"), "static_fallback_count")
            if len(item.get("objects") or []) != count:
                raise ValueError("durable object count does not equal successful outputs")
            output_tokens = count * tokens_per_output
            image_cost = Decimal(output_tokens) * rate / Decimal("1000000")
            text_cost = _decimal(text_cost_raw, "text_total_cost_usd")
            canonical = {
                "image_model": contract.get("model"),
                "generated_image_count": count,
                "generated_image_count_semantics": "paid_successful_api_outputs",
                "image_api_provider": contract.get("provider"),
                "image_model_raw": contract.get("model"),
                "image_model_normalized": contract.get("model"),
                "image_pricing_mode": contract.get("pricing_tier"),
                "image_request_count": requests,
                "image_successful_output_count": count,
                "image_failed_request_count": failed_count,
                "image_retry_count": retry_count,
                "image_discarded_output_count": discarded_count,
                "image_locally_derived_asset_count": local_count,
                "image_cache_reuse_count": cache_count,
                "image_static_fallback_count": fallback_count,
                "image_output_tokens": output_tokens,
                "image_cost_usd": _format_decimal(image_cost),
                "image_list_price_cost_usd": _format_decimal(image_cost),
                "image_billed_cost_usd": None,
                "billing_reconciliation_status": evidence.get("billing_reconciliation_status"),
                "image_cost_estimate_status": "priced_from_output_image_tokens",
                "image_unit_price_usd": _format_decimal(rate),
                "image_pricing_source": "google_cloud_official_standard_paygo",
                "image_pricing_checked_at": evidence.get("checked_at_kst"),
                "image_evidence_confidence": "high",
                "image_evidence_source": "revision+commit+run_artifact+durable_gcs_object+code_contract",
            }
            for field, value in canonical.items():
                _set_verified(row, field, value)
            _set_verified(row, "total_cost_usd", _format_decimal(text_cost + image_cost))
            row["cost_estimate_status"] = "fully_priced_ai_model_cost"
            row["missing_price_env"] = ""
            outputs += count
            local += local_count
            failed += failed_count
            retries += retry_count
            discarded += discarded_count
            cache += cache_count
            fallback += fallback_count
            image_total += image_cost
            complete_total += text_cost + image_cost
            model = str(contract.get("model") or "unknown")
            model_counts[model] += 1
            model_totals[model] += image_cost
        except ValueError as exc:
            invalid.append(f"row={index} run_id={run_id}: {exc}")
            row.clear()
            row.update(before)
        if row != before:
            changed += 1

    final = _render_csv(rows, fields, raw)
    return ImageBackfillPlan(
        raw, final, _sha256(raw), _sha256(final), len(rows), changed, high,
        insufficient, outputs, local, failed, retries, discarded, cache, fallback,
        image_total, text_total, complete_total, invalid, duplicates,
        dict(Counter(str(row.get("cost_estimate_status") or "") for row in rows)),
        dict(model_counts), dict(model_totals),
    )


def _verify_objects(bucket: Any, evidence: Mapping[str, Any]) -> List[str]:
    missing: List[str] = []
    for item in evidence.get("runs", []):
        if item.get("confidence") != "high":
            continue
        for key in item.get("objects") or []:
            blob = bucket.get_blob(str(key))
            if blob is None or int(getattr(blob, "size", 0) or 0) <= 0:
                missing.append(str(key))
    return missing


def _ensure_evidence_object(bucket: Any, key: str, text: str) -> Dict[str, Any]:
    expected = _sha256(text)
    blob = bucket.get_blob(key)
    if blob is None:
        blob = bucket.blob(key)
        blob.upload_from_string(text, content_type="application/json", if_generation_match=0)
        blob = bucket.get_blob(key)
    actual = blob.download_as_text(encoding="utf-8")
    if _sha256(actual) != expected:
        raise RuntimeError("existing evidence object hash mismatch")
    return {"evidence_object": key, "evidence_sha256": expected, "evidence_generation": int(blob.generation)}


def execute(
    bucket: Any,
    bucket_name: str,
    month: str,
    mode: str,
    evidence: Mapping[str, Any],
    *,
    store: Optional[Any] = None,
) -> Dict[str, Any]:
    store = store or GCSLedgerStore(bucket)
    key = cost_ledger_object_key(month)
    source = store.read(key)
    plan = build_backfill_plan(source.text, evidence)
    report = plan.report()
    missing_objects = _verify_objects(bucket, evidence)
    report.update({
        "mode": mode,
        "source": f"gs://{bucket_name}/{key}",
        "source_generation": source.generation,
        "durable_object_verification_pass": not missing_objects,
        "missing_durable_objects": missing_objects,
        "mutation": False,
    })
    if mode in ("dry-run", "verify"):
        report["verification_pass"] = plan.can_apply and not missing_objects and (
            mode == "dry-run" or plan.changed_row_count == 0
        )
        return report
    if not plan.can_apply or missing_objects:
        raise RuntimeError("image backfill evidence validation failed")
    if plan.changed_row_count == 0:
        report.update({"idempotent_noop": True, "verification_pass": True})
        return report

    backup_key, temp_key = _object_targets(key, plan.source_sha256)
    backup = store.create(backup_key, source.text)
    if _sha256(backup.text) != plan.source_sha256:
        raise RuntimeError("backup verification failed")
    temporary = store.create(temp_key, plan.final_text)
    if _sha256(temporary.text) != plan.final_sha256:
        raise RuntimeError("temporary object verification failed")
    try:
        final = store.replace_from_object(temp_key, key, source.generation)
        if _sha256(final.text) != plan.final_sha256:
            raise RuntimeError("final object hash mismatch")
        verified = build_backfill_plan(final.text, evidence)
        if verified.changed_row_count != 0 or verified.row_count != plan.row_count:
            raise RuntimeError("final ledger idempotency verification failed")
        evidence_text = json.dumps(dict(evidence), ensure_ascii=False, indent=2) + "\n"
        evidence_key = f"{admin_artifact_gcs_prefix()}/cost_reports/evidence/genie_cost_image_evidence_{month}.json"
        evidence_report = _ensure_evidence_object(bucket, evidence_key, evidence_text)
    except Exception as exc:
        current = store.read(key)
        original_preserved = _sha256(current.text) == plan.source_sha256
        if not original_preserved:
            restored = store.replace_from_object(backup_key, key, current.generation)
            original_preserved = _sha256(restored.text) == plan.source_sha256
        raise RuntimeError(f"atomic replacement failed; original_preserved={original_preserved}: {exc}") from exc
    report.update({
        "backup_destination": f"gs://{bucket_name}/{backup_key}",
        "backup_sha256": _sha256(backup.text),
        "temporary_destination": f"gs://{bucket_name}/{temp_key}",
        "final_generation": final.generation,
        "atomic_replacement": True,
        "mutation": True,
        "verification_pass": True,
        **evidence_report,
    })
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--evidence", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if not _MONTH_RE.fullmatch(args.month):
        parser.error("--month must be YYYY-MM")
    mode = "apply" if args.apply else ("verify" if args.verify else "dry-run")
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        print(json.dumps({"error": "GENIE_ARTIFACT_BUCKET is required", "mutation": False}))
        return 2
    try:
        report = execute(_get_gcs_bucket(), bucket_name, args.month, mode, load_evidence(args.month, args.evidence))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "mode": mode}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
