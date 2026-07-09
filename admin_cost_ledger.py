"""Best-effort admin cost records and monthly CSV ledger export.

Cost records are operational observability only. They must never affect
generation, owner-review email, customer delivery, or approval decisions.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo

from admin_store import (
    admin_artifact_bucket_name,
    admin_artifact_gcs_prefix,
    admin_runs_dir,
    artifact_json_path,
    artifact_storage_backend_name,
    now_kst_iso,
    repo_root,
    validate_run_id,
    _gcs_download_text,
    _gcs_upload_text,
    _get_gcs_bucket,
    _uses_gcs_backend,
)

logger = logging.getLogger(__name__)

COST_LEDGER_COLUMNS = (
    "created_at_kst",
    "run_id",
    "service_family",
    "program_id",
    "mode",
    "trigger_source",
    "validation_result",
    "email_sent",
    "customer_delivery_status",
    "text_model",
    "image_model",
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "total_token_count",
    "generated_image_count",
    "text_input_cost_usd",
    "text_output_cost_usd",
    "text_thoughts_cost_usd",
    "image_cost_usd",
    "total_cost_usd",
    "total_cost_krw",
    "cost_estimate_status",
    "pricing_source",
    "price_env_configured",
    "missing_price_env",
    "revision",
    "commit_sha",
    "owner_review_url",
    "artifact_url",
)

_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")


def _safe_month(raw: Optional[str]) -> str:
    value = str(raw or "").strip()
    if _MONTH_RE.match(value):
        return value
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")


def month_from_run_meta(meta: Mapping[str, Any]) -> str:
    for key in ("created_at_kst", "created_at", "owner_email_sent_at_kst"):
        raw = str(meta.get(key) or "").strip()
        if len(raw) >= 7 and _MONTH_RE.match(raw[:7]):
            return raw[:7]
    run_id = str(meta.get("run_id") or "").strip()
    if len(run_id) >= 6 and run_id[:6].isdigit():
        return f"{run_id[:4]}-{run_id[4:6]}"
    return _safe_month(None)


def cost_record_object_key(run_id: str, month: str) -> str:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return f"{admin_artifact_gcs_prefix()}/cost_records/{_safe_month(month)}/{run_id}.cost.json"


def cost_ledger_object_key(month: str) -> str:
    return f"{admin_artifact_gcs_prefix()}/cost_reports/genie_cost_ledger_{_safe_month(month)}.csv"


def cost_record_path(run_id: str, month: str) -> Path:
    return admin_runs_dir() / "cost_records" / _safe_month(month) / f"{run_id}.cost.json"


def cost_ledger_path(month: str) -> Path:
    return admin_runs_dir() / "cost_reports" / f"genie_cost_ledger_{_safe_month(month)}.csv"


def cost_record_display_path(run_id: str, month: str) -> str:
    if _uses_gcs_backend():
        return f"gs://{admin_artifact_bucket_name()}/{cost_record_object_key(run_id, month)}"
    return str(cost_record_path(run_id, month))


def cost_ledger_display_path(month: str) -> str:
    if _uses_gcs_backend():
        return f"gs://{admin_artifact_bucket_name()}/{cost_ledger_object_key(month)}"
    return str(cost_ledger_path(month))


def _artifact_display_path(run_id: str) -> str:
    if _uses_gcs_backend():
        return f"gs://{admin_artifact_bucket_name()}/{admin_artifact_gcs_prefix()}/{run_id}.json"
    return str(artifact_json_path(run_id))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _join_missing_price_env(raw: Any) -> str:
    if isinstance(raw, (list, tuple)):
        return "|".join(str(v).strip() for v in raw if str(v).strip())
    return str(raw or "").strip()


def _model_text(cost_estimate: Mapping[str, Any], key: str) -> Optional[str]:
    model = cost_estimate.get("model")
    if isinstance(model, Mapping):
        return str(model.get(key) or "").strip() or None
    if key == "text_model":
        return str(model or "").strip() or None
    return None


def build_cost_record(meta: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    cost_estimate = meta.get("cost_estimate")
    if not isinstance(cost_estimate, Mapping):
        return None
    run_id = str(meta.get("run_id") or cost_estimate.get("run_id") or "").strip()
    if not validate_run_id(run_id):
        return None
    usage = cost_estimate.get("usage") if isinstance(cost_estimate.get("usage"), Mapping) else {}
    components = (
        cost_estimate.get("components") if isinstance(cost_estimate.get("components"), Mapping) else {}
    )
    created_at = str(meta.get("created_at_kst") or meta.get("created_at") or "").strip() or now_kst_iso()
    return {
        "created_at_kst": created_at,
        "run_id": run_id,
        "service_family": cost_estimate.get("service_family") or meta.get("service_family"),
        "program_id": meta.get("program_id") or cost_estimate.get("program_id"),
        "mode": meta.get("mode") or cost_estimate.get("mode"),
        "trigger_source": meta.get("trigger_source"),
        "validation_result": meta.get("validation_result"),
        "email_sent": _as_bool(meta.get("email_sent") or meta.get("owner_review_email_sent")),
        "customer_delivery_status": meta.get("customer_delivery_status"),
        "text_model": _model_text(cost_estimate, "text_model"),
        "image_model": _model_text(cost_estimate, "image_model"),
        "prompt_token_count": usage.get("prompt_token_count"),
        "candidates_token_count": usage.get("candidates_token_count"),
        "thoughts_token_count": usage.get("thoughts_token_count"),
        "total_token_count": usage.get("total_token_count"),
        "generated_image_count": usage.get("generated_image_count"),
        "text_input_cost_usd": components.get("text_input_cost_usd"),
        "text_output_cost_usd": components.get("text_output_cost_usd"),
        "text_thoughts_cost_usd": components.get("text_thoughts_cost_usd"),
        "image_cost_usd": components.get("image_cost_usd"),
        "total_cost_usd": cost_estimate.get("total_cost_usd"),
        "total_cost_krw": cost_estimate.get("total_cost_krw"),
        "cost_estimate_status": cost_estimate.get("cost_estimate_status"),
        "pricing_source": cost_estimate.get("pricing_source"),
        "price_env_configured": _as_bool(cost_estimate.get("price_env_configured")),
        "missing_price_env": _join_missing_price_env(cost_estimate.get("missing_price_env")),
        "revision": meta.get("revision") or meta.get("cloud_run_revision") or os.getenv("K_REVISION", ""),
        "commit_sha": meta.get("commit_sha")
        or meta.get("deployed_commit_sha")
        or os.getenv("COMMIT_SHA", "")
        or os.getenv("SOURCE_COMMIT", ""),
        "owner_review_url": meta.get("owner_review_url") or meta.get("admin_review_url"),
        "artifact_url": meta.get("artifact_url") or _artifact_display_path(run_id),
    }


def cost_record_to_csv_row(record: Mapping[str, Any]) -> Dict[str, str]:
    row: Dict[str, str] = {}
    for column in COST_LEDGER_COLUMNS:
        value = record.get(column)
        if value is None:
            row[column] = ""
        elif isinstance(value, bool):
            row[column] = "true" if value else "false"
        else:
            row[column] = str(value)
    return row


def _render_ledger_csv(rows: List[Mapping[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(COST_LEDGER_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(cost_record_to_csv_row(row))
    return out.getvalue()


def _parse_ledger_csv(raw: str) -> List[Dict[str, str]]:
    if not str(raw or "").strip():
        return []
    reader = csv.DictReader(io.StringIO(raw))
    return [dict(row) for row in reader]


def _write_cost_record(record: Mapping[str, Any], month: str) -> str:
    run_id = str(record.get("run_id") or "")
    payload = json.dumps(dict(record), ensure_ascii=False, indent=2)
    if _uses_gcs_backend():
        key = cost_record_object_key(run_id, month)
        _gcs_upload_text(key, payload, content_type="application/json")
        return f"gs://{admin_artifact_bucket_name()}/{key}"
    path = cost_record_path(run_id, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return str(path)


def _append_cost_ledger(record: Mapping[str, Any], month: str) -> str:
    if _uses_gcs_backend():
        key = cost_ledger_object_key(month)
        existing = _gcs_download_text(key) or ""
        rows = _parse_ledger_csv(existing)
        rows.append(cost_record_to_csv_row(record))
        _gcs_upload_text(key, _render_ledger_csv(rows), content_type="text/csv; charset=utf-8")
        return f"gs://{admin_artifact_bucket_name()}/{key}"
    path = cost_ledger_path(month)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _parse_ledger_csv(path.read_text(encoding="utf-8") if path.is_file() else "")
    rows.append(cost_record_to_csv_row(record))
    path.write_text(_render_ledger_csv(rows), encoding="utf-8")
    return str(path)


def save_cost_record_best_effort(meta: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist run cost JSON and monthly CSV ledger. Never raises."""
    result: Dict[str, Any] = {
        "cost_record_saved": False,
        "cost_ledger_saved": False,
        "cost_record_path": None,
        "cost_ledger_path": None,
        "cost_record_error": None,
        "cost_ledger_error": None,
    }
    record = build_cost_record(meta)
    if not record:
        result["cost_record_error"] = "missing_or_invalid_cost_estimate"
        return result
    month = month_from_run_meta(record)
    try:
        result["cost_record_path"] = _write_cost_record(record, month)
        result["cost_record_saved"] = True
    except Exception as exc:  # pragma: no cover - defensive best-effort
        result["cost_record_error"] = str(exc)
        logger.warning("cost_record_write_failed run_id=%s error=%s", record.get("run_id"), exc)
    try:
        result["cost_ledger_path"] = _append_cost_ledger(record, month)
        result["cost_ledger_saved"] = True
    except Exception as exc:  # pragma: no cover - defensive best-effort
        result["cost_ledger_error"] = str(exc)
        logger.warning("cost_ledger_append_failed run_id=%s error=%s", record.get("run_id"), exc)
    return result


def load_cost_ledger_csv(month: str) -> Optional[str]:
    month = _safe_month(month)
    if _uses_gcs_backend():
        return _gcs_download_text(cost_ledger_object_key(month))
    path = cost_ledger_path(month)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def list_cost_records(limit: int = 50) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if _uses_gcs_backend():
        prefix = f"{admin_artifact_gcs_prefix()}/cost_records/"
        blobs = list(_get_gcs_bucket().list_blobs(prefix=prefix))
        blobs.sort(key=lambda b: getattr(b, "updated", None) or getattr(b, "time_created", None), reverse=True)
        for blob in blobs[:limit]:
            try:
                data = json.loads(blob.download_as_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                records.append(data)
        return records
    root = admin_runs_dir() / "cost_records"
    if not root.is_dir():
        return []
    paths = sorted(root.glob("*/*.cost.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records

