"""Owner-review exposure log — cross-day dedup memory for owner-review-only briefings.

Separate from sent_news_log_store.py (customer final send log). keysuri_global_tech
and keysuri_korea_tech are frequently owner-review-only, so sent_news_log stays
empty for them and cross-day duplicate news can recur unnoticed. This store records
news that was actually emailed to the owner for review, independent of whether a
customer send ever happens.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sent_news_dedup_gate import (
    canonicalize_url,
    editorial_cluster_key as _compute_editorial_cluster_key,
    extract_company_entities,
    normalize_candidate,
    normalize_title,
)

LOG_FILENAME = "owner_review_exposure_log.json"

EXPOSURE_KIND_EMAIL = "owner_review_email"
EXPOSURE_KIND_REISSUE_BODY = "owner_review_reissue_body"
EXPOSURE_KIND_REISSUE_BODY_AND_IMAGE = "owner_review_reissue_body_and_image"
ALLOWED_EXPOSURE_KINDS = frozenset(
    {EXPOSURE_KIND_EMAIL, EXPOSURE_KIND_REISSUE_BODY, EXPOSURE_KIND_REISSUE_BODY_AND_IMAGE}
)


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _parse_dt(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return dt.astimezone(ZoneInfo("Asia/Seoul"))


def _exposed_date_kst(exposed_at: Any) -> str:
    dt = _parse_dt(exposed_at) or _now_kst()
    return dt.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()


def _override_path() -> Optional[Path]:
    raw = os.getenv("GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH", "").strip()
    return Path(raw) if raw else None


def _local_log_path() -> Path:
    override = _override_path()
    if override is not None:
        override.parent.mkdir(parents=True, exist_ok=True)
        return override
    from admin_store import admin_runs_dir

    return admin_runs_dir() / LOG_FILENAME


def _gcs_log_key() -> str:
    from admin_store import admin_artifact_gcs_prefix

    return f"{admin_artifact_gcs_prefix()}/{LOG_FILENAME}"


def _uses_gcs() -> bool:
    if _override_path() is not None:
        return False
    from admin_store import admin_artifact_bucket_name

    return admin_artifact_bucket_name() is not None


def logical_log_path() -> str:
    """Human-readable path for artifact/meta surfacing (not used for I/O)."""
    if _uses_gcs():
        from admin_store import admin_artifact_bucket_name

        return f"gs://{admin_artifact_bucket_name()}/{_gcs_log_key()}"
    return str(_local_log_path())


def _read_text_with_status() -> Tuple[Optional[str], bool, Optional[str]]:
    """Read raw log text. Never raises — read failures fail open.

    Returns (text_or_none, read_ok, error_code). ``read_ok`` is False only when
    an actual read error occurred (missing file/blob is not an error: read_ok
    stays True with text=None).
    """
    try:
        if _uses_gcs():
            from admin_store import _gcs_download_text

            return _gcs_download_text(_gcs_log_key()), True, None
        path = _local_log_path()
        if not path.is_file():
            return None, True, None
        return path.read_text(encoding="utf-8"), True, None
    except Exception as exc:  # noqa: BLE001 - read failure must fail open, never crash the run
        return None, False, f"{type(exc).__name__}"


def _write_text(text: str) -> None:
    if _uses_gcs():
        from admin_store import _gcs_upload_text

        _gcs_upload_text(_gcs_log_key(), text, content_type="application/json")
        return
    _local_log_path().write_text(text, encoding="utf-8")


def load_owner_review_exposure_log_with_status() -> Dict[str, Any]:
    raw, read_ok, error_code = _read_text_with_status()
    if not raw:
        return {"items": [], "read_ok": read_ok, "error_code": error_code}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"items": [], "read_ok": False, "error_code": "JSONDecodeError"}
    if isinstance(data, dict):
        rows = data.get("items")
    else:
        rows = data
    if not isinstance(rows, list):
        return {"items": [], "read_ok": False, "error_code": "malformed_log_payload"}
    return {
        "items": [dict(row) for row in rows if isinstance(row, dict)],
        "read_ok": read_ok,
        "error_code": error_code,
    }


def load_owner_review_exposure_log() -> List[Dict[str, Any]]:
    """Fail-open convenience wrapper: always returns a list, swallowing errors."""
    return load_owner_review_exposure_log_with_status()["items"]


def save_owner_review_exposure_log(rows: List[Dict[str, Any]]) -> None:
    payload = {
        "schema": "owner_review_exposure_log_v1",
        "updated_at": _now_kst().isoformat(),
        "items": rows,
    }
    _write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def recent_owner_review_exposure_log_with_status(
    program_id: str,
    *,
    days: int = 5,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    loaded = load_owner_review_exposure_log_with_status()
    cutoff = (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")) - timedelta(days=days)
    out: List[Dict[str, Any]] = []
    for row in loaded["items"]:
        if str(row.get("program_id") or "") != program_id:
            continue
        exposed_at = _parse_dt(row.get("exposed_at"))
        if exposed_at is None or exposed_at >= cutoff:
            out.append(row)
    return {"items": out, "read_ok": loaded["read_ok"], "error_code": loaded["error_code"]}


def recent_owner_review_exposure_log(
    program_id: str,
    *,
    days: int = 5,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Fail-open convenience wrapper used by simple call sites/tests."""
    return recent_owner_review_exposure_log_with_status(program_id, days=days, now=now)["items"]


def _row_from_item(
    item: Dict[str, Any],
    *,
    run_id: str,
    program_id: str,
    exposed_at: str,
    exposure_kind: str,
) -> Dict[str, Any]:
    normalized = normalize_candidate(item)
    title = str(normalized.get("title") or "").strip()
    entity_keys = item.get("entity_keys")
    if not isinstance(entity_keys, list):
        entity_keys = extract_company_entities(item)
    cluster_key = str(item.get("editorial_cluster_key") or "").strip()
    if not cluster_key:
        cluster_key = _compute_editorial_cluster_key(item)
    return {
        "program_id": program_id,
        "run_id": run_id,
        "exposed_at": exposed_at,
        "exposed_date_kst": _exposed_date_kst(exposed_at),
        "title": title,
        "normalized_title": normalized.get("normalized_title") or normalize_title(title),
        "source": normalized.get("source") or "",
        "normalized_source": normalized.get("normalized_source") or "",
        "url": normalized.get("url") or "",
        "canonical_url": normalized.get("canonical_url") or canonicalize_url(normalized.get("url")),
        "entity_keys": list(entity_keys),
        "editorial_cluster_key": cluster_key,
        "topic_key": normalized.get("topic_key") or "",
        "story_key": str(item.get("story_key") or item.get("story_id") or "").strip(),
        "exposure_kind": exposure_kind,
    }


def rows_from_selected_items(
    selected_items: List[Dict[str, Any]],
    *,
    run_id: str,
    program_id: str,
    exposure_kind: str,
    exposed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    timestamp = exposed_at or (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")).isoformat()
    return [
        _row_from_item(item, run_id=run_id, program_id=program_id, exposed_at=timestamp, exposure_kind=exposure_kind)
        for item in selected_items
        if isinstance(item, dict)
    ]


def prune_owner_review_exposure_log(
    rows: List[Dict[str, Any]],
    *,
    days: int = 10,
    now: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    cutoff = (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")) - timedelta(days=days)
    kept: List[Dict[str, Any]] = []
    pruned = 0
    for row in rows:
        exposed_at = _parse_dt(row.get("exposed_at"))
        if exposed_at is not None and exposed_at < cutoff:
            pruned += 1
            continue
        kept.append(row)
    return kept, pruned


def append_owner_review_exposure(
    *,
    run_id: str,
    program_id: str,
    exposure_kind: str,
    selected_items: List[Dict[str, Any]],
    exposed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if exposure_kind not in ALLOWED_EXPOSURE_KINDS:
        raise ValueError(f"invalid exposure_kind: {exposure_kind!r}")

    timestamp = exposed_at or (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")).isoformat()
    rows = load_owner_review_exposure_log()
    before_count = len(rows)
    new_rows = rows_from_selected_items(
        selected_items,
        run_id=run_id,
        program_id=program_id,
        exposure_kind=exposure_kind,
        exposed_at=timestamp,
    )

    by_run_url: Dict[Tuple[str, str], int] = {}
    by_day_url: Dict[Tuple[str, str, str], int] = {}
    for idx, row in enumerate(rows):
        run_key = (str(row.get("run_id") or ""), str(row.get("canonical_url") or ""))
        day_key = (
            str(row.get("program_id") or ""),
            str(row.get("exposed_date_kst") or _exposed_date_kst(row.get("exposed_at"))),
            str(row.get("canonical_url") or ""),
        )
        by_run_url[run_key] = idx
        by_day_url[day_key] = idx

    appended = 0
    updated = 0
    for row in new_rows:
        canonical_url = str(row.get("canonical_url") or "")
        run_key = (run_id, canonical_url)
        day_key = (program_id, str(row.get("exposed_date_kst") or ""), canonical_url)
        target_idx = by_run_url.get(run_key)
        if target_idx is None:
            target_idx = by_day_url.get(day_key)
        if target_idx is None:
            rows.append(row)
            idx = len(rows) - 1
            by_run_url[run_key] = idx
            by_day_url[day_key] = idx
            appended += 1
        else:
            rows[target_idx] = {**rows[target_idx], **row}
            updated += 1

    rows, pruned = prune_owner_review_exposure_log(rows, now=now)
    save_owner_review_exposure_log(rows)
    return {
        "ok": True,
        "before_count": before_count,
        "after_count": len(rows),
        "appended_count": appended,
        "updated_count": updated,
        "pruned_count": pruned,
        "logical_path": logical_log_path(),
    }
