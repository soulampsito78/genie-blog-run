"""Admin operational customer notices: storage and state machine.

Fully separate from briefing run artifacts (admin_store.py / output/admin_runs).
Notices never reference sent_news_log and never read or write briefing run
fields (customer_sent/email_sent/smtp_accepted on a run artifact).

Notice JSON never stores the actual recipient email address list — only a
count and a human-readable source label, to keep PII out of disk artifacts.
"""
from __future__ import annotations

import json
import heapq
import itertools
import os
import re
import secrets
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from admin_store import (
    _get_gcs_bucket,
    _gcs_download_text,
    _gcs_upload_text,
    _uses_gcs_backend,
    admin_artifact_bucket_name,
)

NOTICE_SCHEMA_VERSION = 1
NOTICE_GCS_PREFIX = "admin_notices"
NOTICE_LIST_INDEX_PREFIX = f"{NOTICE_GCS_PREFIX}/list_index"
NOTICE_LIST_SUMMARY_SUFFIX = ".summary.json"
ADMIN_NOTICE_LIST_MAX_LIMIT = 200
ADMIN_NOTICE_GCS_SCAN_MAX = 5_000
ADMIN_NOTICE_PREFIX_SCAN_MAX = 1_000
ADMIN_NOTICE_MONTH_LOOKBACK = 24

_NOTICE_LIST_SUMMARY_KEYS = (
    "notice_id",
    "notice_type",
    "program_id",
    "related_run_id",
    "status",
    "recipients_count",
    "recipient_source",
    "created_at",
    "previewed_at",
    "sent_at",
    "smtp_accepted",
    "send_error",
    "visible_recipient_policy",
    "storage_backend",
)

NOTICE_TYPES = (
    "delay_notice",
    "quality_check_notice",
    "resolved_notice",
    "incident_notice",
    "custom_notice",
)

NOTICE_STATUSES = frozenset({"draft", "previewed", "sent", "failed"})

VISIBLE_RECIPIENT_POLICY = "undisclosed_recipients_bcc_envelope_only"

_NOTICE_ID_RE = re.compile(
    r"^notice_(?:delay_notice|quality_check_notice|resolved_notice|incident_notice|custom_notice)"
    r"_[0-9]{8}_[a-f0-9]{8}$"
)

# Customer-facing program names. A notice names the program it is about; the
# templates below carried "키수리 글로벌테크" in every string, so a Today or Korea
# notice would have told customers the wrong service was affected.
NOTICE_PROGRAM_NAMES: Dict[str, str] = {
    "today_genie": "투데이 지니",
    "keysuri_global_tech": "키수리 글로벌테크",
    "keysuri_korea_tech": "키수리 코리아테크",
    "all": "지니 구독",
}
DEFAULT_NOTICE_PROGRAM = "all"


def notice_program_name(program_id: str) -> str:
    key = str(program_id or "").strip() or DEFAULT_NOTICE_PROGRAM
    return NOTICE_PROGRAM_NAMES.get(key, NOTICE_PROGRAM_NAMES[DEFAULT_NOTICE_PROGRAM])


# Default subject/body templates, parameterized by program. custom_notice has no
# default body (free text).
_NOTICE_TEMPLATE_SPECS: Dict[str, Dict[str, str]] = {
    "quality_check_notice": {
        "subject": "[{program}] 오늘 브리핑 품질 점검 안내",
        "body_text": (
            "오늘 {program} 브리핑은 품질 점검으로 인해 평소보다 발송이 지연되고 있습니다.\n"
            "검수 완료 후 발송하겠습니다.\n"
            "기다려 주셔서 감사합니다."
        ),
    },
    "delay_notice": {
        "subject": "[{program}] 오늘 브리핑 발송 지연 안내",
        "body_text": (
            "오늘 {program} 브리핑은 품질 확인 과정으로 인해 발송이 지연되었습니다.\n"
            "정확한 내용을 보내드리기 위해 검수 후 발송하겠습니다."
        ),
    },
    "resolved_notice": {
        "subject": "[{program}] 지연된 브리핑 발송 완료 안내",
        "body_text": (
            "품질 점검으로 지연되었던 오늘 {program} 브리핑 발송이 완료되었습니다.\n"
            "기다려 주셔서 감사합니다."
        ),
    },
    "incident_notice": {
        "subject": "[{program}] 서비스 장애 안내",
        "body_text": "",
    },
    "custom_notice": {
        "subject": "",
        "body_text": "",
    },
}


def notice_template(notice_type: str, program_id: str = DEFAULT_NOTICE_PROGRAM) -> Dict[str, str]:
    """Subject/body defaults for one notice type, named for one program."""
    spec = _NOTICE_TEMPLATE_SPECS.get(str(notice_type or "").strip())
    if spec is None:
        return {"subject": "", "body_text": ""}
    program = notice_program_name(program_id)
    return {
        "subject": spec["subject"].format(program=program),
        "body_text": spec["body_text"].format(program=program),
    }


#: Backwards-compatible default rendering (all-programs wording).
NOTICE_TEMPLATES: Dict[str, Dict[str, str]] = {
    notice_type: notice_template(notice_type)
    for notice_type in _NOTICE_TEMPLATE_SPECS
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def admin_notices_dir() -> Path:
    configured = os.getenv("GENIE_ADMIN_NOTICE_LOCAL_DIR", "").strip()
    d = Path(configured) if configured else repo_root() / "output" / "admin_notices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def validate_notice_id(notice_id: str) -> bool:
    return bool(_NOTICE_ID_RE.match(str(notice_id or "")))


def generate_notice_id(notice_type: str) -> str:
    if notice_type not in NOTICE_TYPES:
        raise ValueError(f"unknown notice_type: {notice_type!r}")
    date_part = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    return f"notice_{notice_type}_{date_part}_{secrets.token_hex(4)}"


def _notice_path(notice_id: str) -> Path:
    return admin_notices_dir() / f"{notice_id}.json"


def _notice_summary_path(notice_id: str) -> Path:
    return admin_notices_dir() / f"{notice_id}{NOTICE_LIST_SUMMARY_SUFFIX}"


def notice_storage_backend_name() -> str:
    return "gcs" if _uses_gcs_backend() else "local_test_dev"


def _ensure_notice_store_allowed() -> None:
    if _uses_gcs_backend():
        return
    allow_local = os.getenv("GENIE_ADMIN_ALLOW_LOCAL_NOTICE_STORE", "").strip().lower()
    if os.getenv("K_SERVICE", "").strip() and allow_local not in {"1", "true", "yes", "on"}:
        raise RuntimeError("durable_admin_notice_store_required")


def notice_storage_display_path() -> str:
    bucket = admin_artifact_bucket_name()
    return f"gs://{bucket}/{NOTICE_GCS_PREFIX}" if bucket else str(admin_notices_dir())


def _notice_gcs_key(notice_id: str) -> str:
    if not validate_notice_id(notice_id):
        raise ValueError("invalid notice_id")
    return f"{NOTICE_GCS_PREFIX}/{notice_id}.json"


def _notice_summary_gcs_key(notice_id: str) -> str:
    if not validate_notice_id(notice_id):
        raise ValueError("invalid notice_id")
    return f"{NOTICE_GCS_PREFIX}/{notice_id}{NOTICE_LIST_SUMMARY_SUFFIX}"


def _notice_index_gcs_key(notice: Dict[str, Any]) -> str:
    notice_id = str(notice.get("notice_id") or "")
    if not validate_notice_id(notice_id):
        raise ValueError("invalid notice_id")
    raw_created = str(notice.get("created_at") or "")
    try:
        created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        created = created.astimezone(ZoneInfo("Asia/Seoul"))
    except ValueError:
        created = datetime.now(ZoneInfo("Asia/Seoul"))
    order_key = created.strftime("%Y%m%dT%H%M%S%f")
    return f"{NOTICE_LIST_INDEX_PREFIX}/{order_key}_{notice_id}{NOTICE_LIST_SUMMARY_SUFFIX}"


def build_notice_list_summary(notice: Dict[str, Any]) -> Dict[str, Any]:
    """Projection for list rows; body_text/body_html are intentionally absent."""
    summary: Dict[str, Any] = {"notice_list_summary": True}
    for key in _NOTICE_LIST_SUMMARY_KEYS:
        if key not in notice:
            continue
        value = notice.get(key)
        if isinstance(value, str):
            summary[key] = value[:1_000]
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
    return summary


def _save_notice_summary(notice: Dict[str, Any]) -> None:
    notice_id = str(notice.get("notice_id") or "")
    summary = build_notice_list_summary(notice)
    text = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    if _uses_gcs_backend():
        _gcs_upload_text(
            _notice_index_gcs_key(notice), text, content_type="application/json"
        )
    else:
        _notice_summary_path(notice_id).write_text(text, encoding="utf-8")


def save_notice(notice: Dict[str, Any]) -> None:
    _ensure_notice_store_allowed()
    notice_id = str(notice.get("notice_id") or "")
    if not validate_notice_id(notice_id):
        raise ValueError(f"invalid notice_id: {notice_id!r}")
    payload = dict(notice)
    payload["schema_version"] = int(payload.get("schema_version") or NOTICE_SCHEMA_VERSION)
    payload["storage_backend"] = notice_storage_backend_name()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if _uses_gcs_backend():
        _gcs_upload_text(_notice_gcs_key(notice_id), text, content_type="application/json")
    else:
        _notice_path(notice_id).write_text(text, encoding="utf-8")
    _save_notice_summary(payload)


def load_notice(notice_id: str) -> Optional[Dict[str, Any]]:
    _ensure_notice_store_allowed()
    if not validate_notice_id(notice_id):
        return None
    try:
        if _uses_gcs_backend():
            raw = _gcs_download_text(_notice_gcs_key(notice_id))
            if raw is None:
                return None
        else:
            path = _notice_path(notice_id)
            if not path.is_file():
                return None
            raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _bounded_notice_blobs(bucket: Any):
    prefix = f"{NOTICE_GCS_PREFIX}/notice_"
    try:
        iterator = bucket.list_blobs(prefix=prefix, max_results=ADMIN_NOTICE_GCS_SCAN_MAX)
    except TypeError:
        iterator = bucket.list_blobs(prefix=prefix)
    return itertools.islice(iterator, ADMIN_NOTICE_GCS_SCAN_MAX)


def _notice_id_from_object_name(name: str) -> tuple[str, bool]:
    filename = name.rsplit("/", 1)[-1]
    if filename.endswith(NOTICE_LIST_SUMMARY_SUFFIX):
        notice_id = filename[: -len(NOTICE_LIST_SUMMARY_SUFFIX)]
        return (notice_id, True) if validate_notice_id(notice_id) else ("", False)
    if filename.endswith(".json"):
        notice_id = filename[:-5]
        return (notice_id, False) if validate_notice_id(notice_id) else ("", False)
    return "", False


def _notice_blob_order(blob: Any) -> tuple[float, str]:
    stamp = getattr(blob, "updated", None) or getattr(blob, "time_created", None)
    try:
        numeric = float(stamp.timestamp()) if stamp is not None else 0.0
    except (AttributeError, TypeError, ValueError):
        numeric = 0.0
    return numeric, str(getattr(blob, "name", ""))


def _read_notice_summary_blob(blob: Any) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(blob.download_as_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _skeletal_notice_summary(notice_id: str, blob: Any = None) -> Dict[str, Any]:
    notice_type = next(
        (
            value
            for value in NOTICE_TYPES
            if notice_id.startswith(f"notice_{value}_")
        ),
        "",
    )
    match = re.search(r"_([0-9]{8})_[a-f0-9]{8}$", notice_id)
    created_at = ""
    if match:
        try:
            created_at = datetime.strptime(match.group(1), "%Y%m%d").replace(
                tzinfo=ZoneInfo("Asia/Seoul")
            ).isoformat()
        except ValueError:
            pass
    return {
        "notice_list_summary": True,
        "summary_source": "legacy_object_metadata",
        "summary_available": False,
        "notice_id": notice_id,
        "notice_type": notice_type,
        "created_at": created_at,
        "status": "metadata_unavailable",
        "storage_updated_at": str(
            getattr(blob, "updated", None)
            or getattr(blob, "time_created", None)
            or ""
        )[:100],
    }


def _notice_index_parts(name: str) -> tuple[str, str]:
    prefix = f"{NOTICE_LIST_INDEX_PREFIX}/"
    if not name.startswith(prefix) or not name.endswith(NOTICE_LIST_SUMMARY_SUFFIX):
        return "", ""
    filename = name[len(prefix) : -len(NOTICE_LIST_SUMMARY_SUFFIX)]
    order_key, separator, notice_id = filename.partition("_notice_")
    if not separator or not re.fullmatch(r"[0-9]{8}T[0-9]{12}", order_key):
        return "", ""
    notice_id = f"notice_{notice_id}"
    return (order_key, notice_id) if validate_notice_id(notice_id) else ("", "")


def _collect_notice_index_blobs(
    limit: int,
    *,
    cursor: str = "",
) -> tuple[Dict[str, Any], int]:
    bucket = _get_gcs_bucket()
    candidates: Dict[str, Any] = {}
    state = {"scanned": 0}
    valid_cursor = cursor if re.fullmatch(r"[0-9]{8}T[0-9]{12}", cursor) else ""
    cursor_dt: Optional[datetime] = None
    if valid_cursor:
        try:
            cursor_dt = datetime.strptime(valid_cursor, "%Y%m%dT%H%M%S%f")
        except ValueError:
            cursor_dt = None

    def add_blobs(blobs: List[Any]) -> None:
        for blob in blobs:
            order_key, _notice_id = _notice_index_parts(str(blob.name))
            if not order_key or (valid_cursor and order_key >= valid_cursor):
                continue
            candidates[order_key] = blob

    def scan_partition(
        partition_prefix: str,
        levels: tuple[int, ...],
        *,
        upper_values: tuple[int, ...] = (),
    ) -> None:
        remaining = ADMIN_NOTICE_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            return
        cap = min(ADMIN_NOTICE_PREFIX_SCAN_MAX, remaining)
        try:
            iterator = bucket.list_blobs(prefix=partition_prefix, max_results=cap)
        except TypeError:
            iterator = bucket.list_blobs(prefix=partition_prefix)
        blobs = list(itertools.islice(iterator, cap))
        state["scanned"] += len(blobs)
        saturated = len(blobs) >= cap
        if not saturated or not levels or state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
            add_blobs(blobs)
            return
        before_count = len(candidates)
        upper = (
            min(levels[0] - 1, upper_values[0])
            if upper_values
            else levels[0] - 1
        )
        for value in range(upper, -1, -1):
            scan_partition(
                f"{partition_prefix}{value:02d}",
                levels[1:],
                upper_values=(
                    upper_values[1:]
                    if upper_values and value == upper
                    else ()
                ),
            )
            if len(candidates) >= limit:
                break
            if state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
                break
        if len(candidates) == before_count and state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
            add_blobs(blobs)

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    start_day = now.date()
    if cursor_dt is not None:
        start_day = min(start_day, cursor_dt.date())
    year, month = start_day.year, start_day.month
    for month_offset in range(ADMIN_NOTICE_MONTH_LOOKBACK):
        month_token = f"{year:04d}{month:02d}"
        remaining = ADMIN_NOTICE_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            break
        cap = min(ADMIN_NOTICE_PREFIX_SCAN_MAX, remaining)
        month_prefix = f"{NOTICE_LIST_INDEX_PREFIX}/{month_token}"
        try:
            iterator = bucket.list_blobs(prefix=month_prefix, max_results=cap)
        except TypeError:
            iterator = bucket.list_blobs(prefix=month_prefix)
        month_blobs = list(itertools.islice(iterator, cap))
        state["scanned"] += len(month_blobs)
        saturated = len(month_blobs) >= cap
        if not saturated or state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
            add_blobs(month_blobs)
        else:
            day_upper = monthrange(year, month)[1]
            if month_offset == 0:
                day_upper = min(day_upper, start_day.day)
            before_count = len(candidates)
            for day in range(day_upper, 0, -1):
                cursor_time_upper = ()
                if (
                    cursor_dt is not None
                    and cursor_dt.year == year
                    and cursor_dt.month == month
                    and cursor_dt.day == day
                ):
                    microsecond = cursor_dt.microsecond
                    cursor_time_upper = (
                        cursor_dt.hour,
                        cursor_dt.minute,
                        cursor_dt.second,
                        microsecond // 10_000,
                        (microsecond // 100) % 100,
                        microsecond % 100,
                    )
                scan_partition(
                    f"{NOTICE_LIST_INDEX_PREFIX}/{month_token}{day:02d}T",
                    (24, 60, 60, 100, 100, 100),
                    upper_values=cursor_time_upper,
                )
                if len(candidates) >= limit or state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
                    break
            if len(candidates) == before_count and state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
                add_blobs(month_blobs)
        if len(candidates) >= limit or state["scanned"] >= ADMIN_NOTICE_GCS_SCAN_MAX:
            break
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return candidates, state["scanned"]


def list_notice_page(limit: int = 50, *, cursor: str = "") -> Dict[str, Any]:
    """List one bounded metadata-only page; cursor is the last time index."""
    _ensure_notice_store_allowed()
    bounded_limit = max(1, min(int(limit), ADMIN_NOTICE_LIST_MAX_LIMIT))
    fetch_limit = bounded_limit + 1
    rows: List[Dict[str, Any]] = []
    row_cursors: List[str] = []
    if _uses_gcs_backend():
        candidates, _scanned = _collect_notice_index_blobs(
            fetch_limit, cursor=cursor
        )
        for order_key in sorted(candidates, reverse=True)[:fetch_limit]:
            blob = candidates[order_key]
            _index_key, notice_id = _notice_index_parts(str(blob.name))
            data = _read_notice_summary_blob(blob)
            rows.append(data or _skeletal_notice_summary(notice_id, blob))
            row_cursors.append(order_key)

        # Bounded compatibility window for legacy notices written before the
        # chronological index existed. Full notice JSON is never downloaded.
        if len(rows) < fetch_limit and not cursor:
            legacy: Dict[str, List[Any]] = {}
            for blob in _bounded_notice_blobs(_get_gcs_bucket()):
                notice_id, is_summary = _notice_id_from_object_name(str(blob.name))
                if not notice_id or any(
                    str(row.get("notice_id") or "") == notice_id for row in rows
                ):
                    continue
                pair = legacy.setdefault(notice_id, [None, None])
                pair[0 if is_summary else 1] = blob
            selected = heapq.nlargest(
                fetch_limit - len(rows),
                legacy.items(),
                key=lambda item: _notice_blob_order(item[1][0] or item[1][1]),
            )
            for notice_id, (summary_blob, full_blob) in selected:
                data = (
                    _read_notice_summary_blob(summary_blob)
                    if summary_blob is not None
                    else None
                )
                rows.append(data or _skeletal_notice_summary(notice_id, full_blob))
                row_cursors.append("")
    else:
        full_paths = (
            path
            for path in admin_notices_dir().glob("notice_*.json")
            if not path.name.endswith(NOTICE_LIST_SUMMARY_SUFFIX)
        )
        selected_paths = heapq.nlargest(
            fetch_limit,
            full_paths,
            key=lambda path: path.stat().st_mtime,
        )
        for path in selected_paths:
            notice_id = path.name[:-5]
            summary_path = _notice_summary_path(notice_id)
            data = None
            if summary_path.is_file():
                try:
                    parsed = json.loads(summary_path.read_text(encoding="utf-8"))
                    data = parsed if isinstance(parsed, dict) else None
                except (OSError, json.JSONDecodeError):
                    pass
            rows.append(data or _skeletal_notice_summary(notice_id))
            row_cursors.append("")
    ordered = sorted(
        zip(rows, row_cursors),
        key=lambda pair: str(pair[0].get("created_at") or ""),
        reverse=True,
    )
    has_more = len(ordered) > bounded_limit
    selected_rows = [row for row, _row_cursor in ordered[:bounded_limit]]
    selected_cursors = [value for _row, value in ordered[:bounded_limit]]
    return {
        "items": selected_rows,
        "limit": bounded_limit,
        "cursor": cursor,
        "next_cursor": (
            selected_cursors[-1] if has_more and selected_cursors else ""
        ),
        "has_more": has_more,
    }


def list_notices(limit: int = 50, *, cursor: str = "") -> List[Dict[str, Any]]:
    """List bounded metadata summaries without loading stored notice bodies."""
    return list_notice_page(limit=limit, cursor=cursor)["items"]


def create_notice_draft(
    *,
    notice_type: str,
    program_id: str,
    related_run_id: Optional[str],
    subject: str,
    body_text: str,
    body_html: str,
) -> Dict[str, Any]:
    """Build and persist a new draft notice. Never touches run artifacts."""
    if notice_type not in NOTICE_TYPES:
        raise ValueError(f"unknown notice_type: {notice_type!r}")
    notice_id = generate_notice_id(notice_type)
    notice: Dict[str, Any] = {
        "schema_version": NOTICE_SCHEMA_VERSION,
        "notice_id": notice_id,
        "notice_type": notice_type,
        "program_id": str(program_id or "").strip(),
        "related_run_id": str(related_run_id).strip() if related_run_id else None,
        "subject": str(subject or "").strip(),
        "body_text": str(body_text or "").strip(),
        "body_html": str(body_html or ""),
        "recipients_count": 0,
        "recipient_source": "",
        "created_at": now_kst_iso(),
        "previewed_at": None,
        "sent_at": None,
        "sent_by": None,
        "status": "draft",
        "smtp_accepted": None,
        "send_error": None,
        "visible_recipient_policy": VISIBLE_RECIPIENT_POLICY,
        "pii_safe_delivery": True,
        "storage_backend": notice_storage_backend_name(),
    }
    save_notice(notice)
    return notice


def mark_previewed(notice: Dict[str, Any], *, recipients_count: int, recipient_source: str) -> Dict[str, Any]:
    """Record a preview render. Never sends email."""
    notice = dict(notice)
    notice["recipients_count"] = int(recipients_count)
    notice["recipient_source"] = str(recipient_source or "")
    notice["previewed_at"] = now_kst_iso()
    notice["status"] = "previewed"
    save_notice(notice)
    return notice


def mark_sent(notice: Dict[str, Any], *, sent_by: str) -> Dict[str, Any]:
    notice = dict(notice)
    notice["status"] = "sent"
    notice["sent_at"] = now_kst_iso()
    notice["sent_by"] = str(sent_by or "admin")
    notice["smtp_accepted"] = True
    notice["send_error"] = None
    save_notice(notice)
    return notice


def mark_failed(notice: Dict[str, Any], *, send_error: str, sent_by: str) -> Dict[str, Any]:
    notice = dict(notice)
    notice["status"] = "failed"
    notice["sent_at"] = now_kst_iso()
    notice["sent_by"] = str(sent_by or "admin")
    notice["smtp_accepted"] = False
    notice["send_error"] = str(send_error or "send_failed")
    save_notice(notice)
    return notice
