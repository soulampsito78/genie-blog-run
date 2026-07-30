"""CONTROL D — recurrence counters for KeeSuri Global generation.

Aggregates the diagnostics that generation, parsing and post-render QA already
persist, so recurrence of the 2026-07-30 incidents is countable without a new
monitoring platform. Read-only over artifact/diagnostic dicts; never mutates a
run and never reads secrets.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Mapping

logger = logging.getLogger("keysuri.recurrence")

RECURRENCE_COUNTER_NAMES = (
    "generation_attempts",
    "bounded_retry_count",
    "retry_success",
    "retry_exhausted",
    "json_extraction_failure",
    "contentless_response_failure",
    "program_id_repair_count",
    "conflicting_program_id_block_count",
    "schema_validation_failure",
    "post_render_truncation_block",
    "global_run_success",
    "global_run_safe_fail",
)


def _codes(record: Mapping[str, Any]) -> List[str]:
    out: List[str] = [str(c) for c in (record.get("issue_codes") or []) if c]
    fc = record.get("failure_classification")
    if isinstance(fc, Mapping):
        primary = fc.get("primary_failure_code")
        if primary:
            out.append(str(primary))
        out.extend(str(c) for c in (fc.get("secondary_failure_codes") or []) if c)
    diag = record.get("post_render_qa_diagnostics")
    if isinstance(diag, Mapping):
        out.extend(str(c) for c in (diag.get("issue_codes") or []) if c)
    return out


def recurrence_counters_for_run(record: Mapping[str, Any]) -> Dict[str, int]:
    """Counters for a single run artifact or generation-diagnostics dict."""
    counters = {name: 0 for name in RECURRENCE_COUNTER_NAMES}
    if not isinstance(record, Mapping):
        return counters

    attempts = record.get("generation_attempt_count")
    if isinstance(attempts, int) and not isinstance(attempts, bool):
        counters["generation_attempts"] = attempts
    elif record.get("called_gemini"):
        counters["generation_attempts"] = 1

    if record.get("global_recovery_attempted") or record.get("generation_recovery_attempted"):
        counters["bounded_retry_count"] = 1
    result = str(record.get("global_recovery_result") or record.get("generation_recovery_result") or "")
    if result == "succeeded":
        counters["retry_success"] = 1
    if record.get("global_generation_budget_exhausted") or result.startswith("not_attempted_budget"):
        counters["retry_exhausted"] = 1

    codes = _codes(record)
    if "json_extract_failed" in codes:
        counters["json_extraction_failure"] = 1
    if any(c in codes for c in (
        "gemini_json_missing_required_keys", "top_5_news_missing", "deep_dive_missing",
        "top_5_news_missing_or_invalid",
    )):
        counters["contentless_response_failure"] = 1
    if "program_id_mismatch" in codes:
        counters["conflicting_program_id_block_count"] = 1
    if "gemini_json_schema_validation_failed" in codes:
        counters["schema_validation_failure"] = 1
    if "global_visible_text_truncated_deep_dive" in codes:
        counters["post_render_truncation_block"] = 1

    meta = record.get("parse_meta")
    repaired = meta.get("repaired_fields") if isinstance(meta, Mapping) else None
    if isinstance(repaired, Iterable) and "program_id" in list(repaired):
        counters["program_id_repair_count"] = 1
    elif record.get("program_id_repair_applied"):
        counters["program_id_repair_count"] = 1

    if str(record.get("validation_result") or "") == "pass" and record.get("email_sent"):
        counters["global_run_success"] = 1
    elif str(record.get("validation_result") or "") in ("block", "hold") or record.get("error"):
        counters["global_run_safe_fail"] = 1
    return counters


def aggregate_recurrence_counters(records: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Sum per-run counters across runs — the harness inspection path."""
    total = {name: 0 for name in RECURRENCE_COUNTER_NAMES}
    for record in records or []:
        for name, value in recurrence_counters_for_run(record).items():
            total[name] += value
    return total


def log_recurrence_counters(record: Mapping[str, Any], *, run_id: str = "") -> Dict[str, int]:
    """Emit one structured counter event, matching repo logging conventions."""
    counters = recurrence_counters_for_run(record)
    logger.info(
        "keysuri_recurrence_counters %s",
        json.dumps({"event": "keysuri_recurrence_counters", "run_id": run_id, **counters},
                   ensure_ascii=False, sort_keys=True),
    )
    return counters
