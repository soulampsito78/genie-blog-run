"""Durable owner-admin safety records (local tests or production GCS).

The records in this module are deliberately small and append/identity based:
approval snapshots are immutable, operator audit events are append-only, and a
delivery command is created once before an SMTP submission.  GCS object-create
preconditions (or local ``O_EXCL``) provide the application-side duplicate
submission boundary.  This does not claim provider-side exactly-once delivery.
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
    _uses_gcs_backend,
    admin_artifact_bucket_name,
)

SCHEMA_VERSION = 1
SAFETY_PREFIX = "admin_safety"
APPROVAL_SNAPSHOT_TTL_SECONDS = 15 * 60
MAX_AUDIT_METADATA_DICT_ITEMS = 50
MAX_AUDIT_METADATA_LIST_ITEMS = 50
ADMIN_AUDIT_LIST_MAX_LIMIT = 500
ADMIN_AUDIT_GCS_SCAN_MAX = 2_000
ADMIN_AUDIT_MONTH_LOOKBACK = 24
ADMIN_AUDIT_PREFIX_SCAN_MAX = 500

_SNAPSHOT_ID_RE = re.compile(r"^aps_[0-9]{8}_[a-f0-9]{16}$")
_COMMAND_ID_RE = re.compile(r"^delivery_[a-f0-9]{40}$")
_EVENT_ID_RE = re.compile(r"^evt_[0-9]{8}T[0-9]{6}_[a-f0-9]{12}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|cookie|otp|credential|session_raw)"
)


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def safety_storage_backend_name() -> str:
    return "gcs" if _uses_gcs_backend() else "local_test_dev"


def safety_storage_display_path() -> str:
    bucket = admin_artifact_bucket_name()
    if bucket:
        return f"gs://{bucket}/{SAFETY_PREFIX}"
    return str(_local_root())


def _local_root() -> Path:
    allow_local = os.getenv("GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE", "").strip().lower()
    if os.getenv("K_SERVICE", "").strip() and allow_local not in {"1", "true", "yes", "on"}:
        raise RuntimeError("durable_admin_safety_store_required")
    configured = os.getenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", "").strip()
    root = Path(configured) if configured else Path(__file__).resolve().parent / "output" / SAFETY_PREFIX
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(key: str) -> Path:
    path = _local_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json_text(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _create_json_once(key: str, payload: Dict[str, Any]) -> bool:
    text = _json_text(payload)
    if _uses_gcs_backend():
        blob = _get_gcs_bucket().blob(f"{SAFETY_PREFIX}/{key}")
        try:
            blob.upload_from_string(
                text,
                content_type="application/json",
                if_generation_match=0,
            )
            return True
        except Exception as exc:  # google exception is optional at import time
            if getattr(exc, "code", None) in (409, 412):
                return False
            if exc.__class__.__name__ in {"Conflict", "PreconditionFailed"}:
                return False
            raise
    path = _local_path(key)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def _write_json(key: str, payload: Dict[str, Any]) -> None:
    text = _json_text(payload)
    if _uses_gcs_backend():
        _get_gcs_bucket().blob(f"{SAFETY_PREFIX}/{key}").upload_from_string(
            text, content_type="application/json"
        )
        return
    path = _local_path(key)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _read_json(key: str) -> Optional[Dict[str, Any]]:
    if _uses_gcs_backend():
        raw = _gcs_download_text(f"{SAFETY_PREFIX}/{key}")
    else:
        path = _local_path(key)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def generate_approval_snapshot_id() -> str:
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    return f"aps_{stamp}_{secrets.token_hex(8)}"


def save_approval_snapshot(snapshot: Dict[str, Any]) -> bool:
    snapshot_id = str(snapshot.get("approval_snapshot_id") or "")
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError("invalid approval_snapshot_id")
    payload = dict(snapshot)
    payload["schema_version"] = SCHEMA_VERSION
    return _create_json_once(f"approval_snapshots/{snapshot_id}.json", payload)


def load_approval_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    if not _SNAPSHOT_ID_RE.fullmatch(str(snapshot_id or "")):
        return None
    return _read_json(f"approval_snapshots/{snapshot_id}.json")


def delivery_command_id_for_snapshot(snapshot_id: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"customer_delivery|{snapshot_id}".encode("utf-8")).hexdigest()[:40]
    return f"delivery_{digest}"


def reserve_delivery_command(
    *,
    command_id: str,
    snapshot_id: str,
    run_id: str,
    operator_id: str,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    if not _COMMAND_ID_RE.fullmatch(str(command_id or "")):
        raise ValueError("invalid delivery command id")
    record = {
        "schema_version": SCHEMA_VERSION,
        "delivery_command_id": command_id,
        "approval_snapshot_id": snapshot_id,
        "run_id": run_id,
        "operator_id": operator_id,
        "status": "SUBMITTED",
        "guarantee": "application_side_duplicate_submission_block",
        "provider_exactly_once": False,
        "attempted_at": now_kst_iso(),
        "completed_at": None,
        "result_code": None,
    }
    created = _create_json_once(f"delivery_commands/{command_id}.json", record)
    return created, record if created else load_delivery_command(command_id)


def load_delivery_command(command_id: str) -> Optional[Dict[str, Any]]:
    if not _COMMAND_ID_RE.fullmatch(str(command_id or "")):
        return None
    return _read_json(f"delivery_commands/{command_id}.json")


def complete_delivery_command(
    command_id: str,
    *,
    result_code: str,
    safe_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    record = load_delivery_command(command_id)
    if not record:
        return None
    record["status"] = str(result_code or "OUTCOME_UNKNOWN")
    record["result_code"] = str(result_code or "OUTCOME_UNKNOWN")
    record["completed_at"] = now_kst_iso()
    if safe_metadata:
        record["result_metadata"] = sanitize_audit_metadata(safe_metadata)
    _write_json(f"delivery_commands/{command_id}.json", record)
    return record


def sanitize_audit_metadata(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for raw_key, raw_value in itertools.islice(
            value.items(), MAX_AUDIT_METADATA_DICT_ITEMS
        ):
            key = str(raw_key)
            if _SENSITIVE_KEY_RE.search(key):
                continue
            out[key[:80]] = sanitize_audit_metadata(raw_value, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [
            sanitize_audit_metadata(item, _depth=_depth + 1)
            for item in itertools.islice(value, MAX_AUDIT_METADATA_LIST_ITEMS)
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:500] if isinstance(value, str) else value
    return str(value)[:500]


_QA_MANUAL_COMMAND_RE = re.compile(r"^qam_[0-9]{8}T[0-9]{6}_[a-f0-9]{12}$")


def reserve_qa_manual_run(command_id: str, *, operator_id: str, program_id: str) -> bool:
    """Claim a qa_manual run slot exactly once.

    A manual verification run costs a Gemini generation and an owner email, so a
    double-submit — a refreshed confirmation page, an impatient second click —
    must not produce a second live run. Backed by the same create-once primitive
    the delivery commands use, so the guard is atomic rather than advisory.
    """
    token = str(command_id or "").strip()
    if not _QA_MANUAL_COMMAND_RE.fullmatch(token):
        raise ValueError("invalid qa_manual command id")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "command_id": token,
        "program_id": str(program_id or "")[:80],
        "operator_id": str(operator_id or "unknown")[:120],
        "reserved_at": now_kst_iso(),
    }
    return _create_json_once(f"qa_manual_runs/{token}.json", payload)


def append_operator_audit(
    action: str,
    *,
    operator_id: str,
    run_id: str = "",
    incident_id: str = "",
    result: str = "",
    reason_code: str = "",
    related_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    event_id = f"evt_{now.strftime('%Y%m%dT%H%M%S')}_{secrets.token_hex(6)}"
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "timestamp": now.isoformat(),
        "operator_id": str(operator_id or "unknown")[:120],
        "action": str(action or "")[:120],
        "run_id": str(run_id or "")[:160] or None,
        "incident_id": str(incident_id or "")[:160] or None,
        "result": str(result or "")[:120] or None,
        "reason_code": str(reason_code or "")[:160] or None,
        "related_id": str(related_id or "")[:200] or None,
        "metadata": sanitize_audit_metadata(metadata or {}),
    }
    if not _EVENT_ID_RE.fullmatch(event_id):
        raise RuntimeError("invalid generated audit event id")
    if not _create_json_once(f"operator_audit/{event_id}.json", record):
        raise RuntimeError("operator audit event collision")
    return record


def _bounded_audit_blobs(bucket: Any, *, prefix: str, max_results: int):
    try:
        iterator = bucket.list_blobs(prefix=prefix, max_results=max_results)
    except TypeError:
        iterator = bucket.list_blobs(prefix=prefix)
    return itertools.islice(iterator, max_results)


def _collect_recent_audit_names(limit: int, *, cursor: str = "") -> tuple[List[str], int]:
    base_prefix = f"{SAFETY_PREFIX}/operator_audit/evt_"
    bucket = _get_gcs_bucket()
    names: set[str] = set()
    state = {"scanned": 0}
    valid_cursor = cursor if _EVENT_ID_RE.fullmatch(cursor) else ""
    cursor_dt: Optional[datetime] = None
    if valid_cursor:
        try:
            cursor_dt = datetime.strptime(valid_cursor[4:19], "%Y%m%dT%H%M%S")
        except ValueError:
            cursor_dt = None

    def add_blobs(blobs: List[Any]) -> None:
        for blob in blobs:
            name = str(blob.name)
            event_id = name.rsplit("/", 1)[-1][:-5] if name.endswith(".json") else ""
            if not _EVENT_ID_RE.fullmatch(event_id):
                continue
            if valid_cursor and event_id >= valid_cursor:
                continue
            names.add(name)

    def scan_partition(
        partition_prefix: str,
        levels: tuple[int, ...],
        *,
        upper_values: tuple[int, ...] = (),
    ) -> None:
        remaining = ADMIN_AUDIT_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            return
        cap = min(ADMIN_AUDIT_PREFIX_SCAN_MAX, remaining)
        blobs = list(
            _bounded_audit_blobs(bucket, prefix=partition_prefix, max_results=cap)
        )
        state["scanned"] += len(blobs)
        saturated = len(blobs) >= cap
        if not saturated or not levels or state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
            add_blobs(blobs)
            return
        before_count = len(names)
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
            if len(names) >= limit or state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
                break
        if len(names) == before_count and state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
            add_blobs(blobs)

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    start_day = now.date()
    if cursor_dt is not None:
        start_day = min(start_day, cursor_dt.date())
    year, month = start_day.year, start_day.month
    for month_offset in range(ADMIN_AUDIT_MONTH_LOOKBACK):
        month_token = f"{year:04d}{month:02d}"
        remaining = ADMIN_AUDIT_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            break
        cap = min(ADMIN_AUDIT_PREFIX_SCAN_MAX, remaining)
        month_blobs = list(
            _bounded_audit_blobs(
                bucket, prefix=f"{base_prefix}{month_token}", max_results=cap
            )
        )
        state["scanned"] += len(month_blobs)
        saturated = len(month_blobs) >= cap
        if not saturated or state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
            add_blobs(month_blobs)
        else:
            day_upper = monthrange(year, month)[1]
            if month_offset == 0:
                day_upper = min(day_upper, start_day.day)
            before_count = len(names)
            for day in range(day_upper, 0, -1):
                cursor_time_upper = (
                    (cursor_dt.hour, cursor_dt.minute, cursor_dt.second)
                    if cursor_dt is not None
                    and cursor_dt.year == year
                    and cursor_dt.month == month
                    and cursor_dt.day == day
                    else ()
                )
                scan_partition(
                    f"{base_prefix}{month_token}{day:02d}T",
                    (24, 60, 60),
                    upper_values=cursor_time_upper,
                )
                if len(names) >= limit or state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
                    break
            if len(names) == before_count and state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
                add_blobs(month_blobs)
        if len(names) >= limit or state["scanned"] >= ADMIN_AUDIT_GCS_SCAN_MAX:
            break
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return heapq.nlargest(limit, names), state["scanned"]


def list_operator_audit_page(limit: int = 100, *, cursor: str = "") -> Dict[str, Any]:
    """Return a bounded newest-first audit page and stable event-id cursor."""
    bounded_limit = max(1, min(int(limit), ADMIN_AUDIT_LIST_MAX_LIMIT))
    fetch_limit = bounded_limit + 1
    if _uses_gcs_backend():
        names, _scanned = _collect_recent_audit_names(fetch_limit, cursor=cursor)
        rows: List[Dict[str, Any]] = []
        for name in names:
            raw = _gcs_download_text(name)
            try:
                row = json.loads(raw or "")
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    else:
        valid_cursor = cursor if _EVENT_ID_RE.fullmatch(cursor) else ""
        paths = heapq.nlargest(
            fetch_limit,
            (
                path
                for path in (_local_root() / "operator_audit").glob("evt_*.json")
                if not valid_cursor or path.stem < valid_cursor
            ),
            key=lambda path: path.name,
        )
        rows = []
        for path in paths:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
    has_more = len(rows) > bounded_limit
    items = rows[:bounded_limit]
    return {
        "items": items,
        "limit": bounded_limit,
        "cursor": cursor if _EVENT_ID_RE.fullmatch(cursor) else "",
        "next_cursor": (
            str(items[-1].get("event_id") or "") if has_more and items else ""
        ),
        "has_more": has_more,
    }


def list_operator_audit(limit: int = 100, *, cursor: str = "") -> List[Dict[str, Any]]:
    return list_operator_audit_page(limit=limit, cursor=cursor)["items"]
