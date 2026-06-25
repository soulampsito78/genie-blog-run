"""Persistent sent-news log for customer-final briefing sends."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sent_news_dedup_gate import canonicalize_url, normalize_candidate, normalize_title

LOG_FILENAME = "sent_news_log.json"


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


def _sent_date_kst(sent_at: Any) -> str:
    dt = _parse_dt(sent_at) or _now_kst()
    return dt.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()


def _override_path() -> Optional[Path]:
    raw = os.getenv("GENIE_SENT_NEWS_LOG_PATH", "").strip()
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


def _read_text() -> Optional[str]:
    if _uses_gcs():
        from admin_store import _gcs_download_text

        return _gcs_download_text(_gcs_log_key())
    path = _local_log_path()
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _write_text(text: str) -> None:
    if _uses_gcs():
        from admin_store import _gcs_upload_text

        _gcs_upload_text(_gcs_log_key(), text, content_type="application/json")
        return
    _local_log_path().write_text(text, encoding="utf-8")


def load_sent_news_log() -> List[Dict[str, Any]]:
    raw = _read_text()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        rows = data.get("items")
    else:
        rows = data
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def save_sent_news_log(rows: List[Dict[str, Any]]) -> None:
    payload = {
        "schema": "sent_news_log_v1",
        "updated_at": _now_kst().isoformat(),
        "items": rows,
    }
    _write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def recent_sent_news_log(
    briefing_type: str,
    *,
    days: int = 5,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    cutoff = (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")) - timedelta(days=days)
    out: List[Dict[str, Any]] = []
    for row in load_sent_news_log():
        if str(row.get("briefing_type") or "") != briefing_type:
            continue
        sent_at = _parse_dt(row.get("sent_at"))
        if sent_at is None or sent_at >= cutoff:
            out.append(row)
    return out


def _row_from_item(
    item: Dict[str, Any],
    *,
    run_id: str,
    briefing_type: str,
    sent_at: str,
) -> Dict[str, Any]:
    normalized = normalize_candidate(item)
    title = str(normalized.get("title") or "").strip()
    return {
        "run_id": run_id,
        "briefing_type": briefing_type,
        "sent_at": sent_at,
        "sent_date_kst": _sent_date_kst(sent_at),
        "title": title,
        "normalized_title": normalized.get("normalized_title") or normalize_title(title),
        "url": normalized.get("url") or "",
        "canonical_url": normalized.get("canonical_url") or canonicalize_url(normalized.get("url")),
        "source": normalized.get("source") or "",
        "topic_key": normalized.get("topic_key") or "",
        "summary_hash": normalized.get("summary_hash") or "",
        "short_summary": str(normalized.get("short_summary") or normalized.get("summary") or "")[:500],
    }


def prune_sent_news_log(
    rows: List[Dict[str, Any]],
    *,
    days: int = 5,
    now: Optional[datetime] = None,
) -> tuple[List[Dict[str, Any]], int]:
    cutoff = (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")) - timedelta(days=days)
    kept: List[Dict[str, Any]] = []
    pruned = 0
    for row in rows:
        sent_at = _parse_dt(row.get("sent_at"))
        if sent_at is not None and sent_at < cutoff:
            pruned += 1
            continue
        kept.append(row)
    return kept, pruned


def append_or_upsert_sent_news(
    *,
    run_id: str,
    briefing_type: str,
    selected_items: List[Dict[str, Any]],
    sent_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    timestamp = sent_at or (now or _now_kst()).astimezone(ZoneInfo("Asia/Seoul")).isoformat()
    rows = load_sent_news_log()
    before_count = len(rows)
    new_rows = [
        _row_from_item(item, run_id=run_id, briefing_type=briefing_type, sent_at=timestamp)
        for item in selected_items
        if isinstance(item, dict)
    ]

    by_run_url: Dict[tuple[str, str], int] = {}
    by_day_url: Dict[tuple[str, str, str], int] = {}
    for idx, row in enumerate(rows):
        run_key = (str(row.get("run_id") or ""), str(row.get("canonical_url") or ""))
        day_key = (
            str(row.get("briefing_type") or ""),
            str(row.get("sent_date_kst") or _sent_date_kst(row.get("sent_at"))),
            str(row.get("canonical_url") or ""),
        )
        by_run_url[run_key] = idx
        by_day_url[day_key] = idx

    appended = 0
    updated = 0
    for row in new_rows:
        canonical_url = str(row.get("canonical_url") or "")
        run_key = (run_id, canonical_url)
        day_key = (briefing_type, str(row.get("sent_date_kst") or ""), canonical_url)
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

    rows, pruned = prune_sent_news_log(rows, now=now)
    save_sent_news_log(rows)
    return {
        "ok": True,
        "before_count": before_count,
        "after_count": len(rows),
        "appended_count": appended,
        "updated_count": updated,
        "pruned_count": pruned,
    }
