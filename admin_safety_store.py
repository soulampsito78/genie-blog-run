"""Durable owner-admin safety records (local tests or production GCS).

The records in this module are deliberately small and append/identity based:
approval snapshots are immutable, operator audit events are append-only, and a
delivery command is created once before an SMTP submission.  GCS object-create
preconditions (or local ``O_EXCL``) provide the application-side duplicate
submission boundary.  This does not claim provider-side exactly-once delivery.
"""
from __future__ import annotations

import json
import os
import re
import secrets
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
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY_RE.search(key):
                continue
            out[key[:80]] = sanitize_audit_metadata(raw_value, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_metadata(item, _depth=_depth + 1) for item in list(value)[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:500] if isinstance(value, str) else value
    return str(value)[:500]


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


def list_operator_audit(limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    if _uses_gcs_backend():
        prefix = f"{SAFETY_PREFIX}/operator_audit/"
        blobs = list(_get_gcs_bucket().list_blobs(prefix=prefix))
        names = sorted((b.name for b in blobs if b.name.endswith(".json")), reverse=True)[:limit]
        rows: List[Dict[str, Any]] = []
        for name in names:
            raw = _gcs_download_text(name)
            try:
                row = json.loads(raw or "")
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    paths = sorted((_local_root() / "operator_audit").glob("evt_*.json"), reverse=True)[:limit]
    rows = []
    for path in paths:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
