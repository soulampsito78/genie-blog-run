"""Durable store for natural-run SLA incidents (diagnose → report → wait).

Never triggers recovery or customer send. Watchdog and Admin share this store.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

INCIDENT_PREFIX = "admin_incidents"

STATUS_OPEN = "open"
STATUS_REPORTED = "reported"
STATUS_RECOVERY_APPROVED = "recovery_approved"
STATUS_RECOVERY_SUCCEEDED = "recovery_succeeded"
STATUS_RECOVERY_FAILED = "recovery_failed"
STATUS_DISMISSED = "dismissed"

RETRY_SAFE_TO_RETRY = "SAFE_TO_RETRY"
RETRY_REQUIRES_PATCH = "RETRY_REQUIRES_PATCH"
RETRY_BLOCKED = "RETRY_BLOCKED"
RETRY_STATUS_UNKNOWN = "RETRY_STATUS_UNKNOWN"

PROGRAM_DISPLAY = {
    "today_genie": "Today_Geenee",
    "keysuri_global_tech": "KeeSuri_Global_Tech",
    "keysuri_korea_tech": "KeeSuri_Korea_Tech",
}

NATURAL_SLOTS = {
    "today_genie": "06:30",
    "keysuri_global_tech": "12:30",
    "keysuri_korea_tech": "18:30",
}

_INCIDENT_ID_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_(today_genie|keysuri_global_tech|keysuri_korea_tech)_\d{2}-\d{2}$"
)
_VERIFICATION_ID_RE = re.compile(r"^verification_\d{4}-\d{2}-\d{2}_watchdog_test$")

ACTIVATION_META_ID = "_watchdog_activation"
ACTIVATION_ENV = "NATURAL_RUN_WATCHDOG_ACTIVATED_AT"

_LOCK = threading.RLock()  # reentrant: lease helpers call save_incident under lock


def now_kst_iso() -> str:
    return datetime.now(KST).isoformat()


def kst_date_str(now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    return now.date().isoformat()


def normalize_slot(slot: str) -> str:
    text = str(slot or "").strip().upper().replace("KST", "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 3:
        digits = f"0{digits}"
    if len(digits) == 4:
        return f"{digits[:2]}:{digits[2:]}"
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip()[:2].isdigit():
            return f"{int(parts[0]):02d}:{int(parts[1][:2]):02d}"
    return text


def make_incident_id(program_id: str, kst_date: str, scheduled_slot: str) -> str:
    slot = normalize_slot(scheduled_slot).replace(":", "-")
    return f"{kst_date}_{program_id}_{slot}"


def validate_incident_id(incident_id: str) -> bool:
    text = str(incident_id or "").strip()
    return bool(_INCIDENT_ID_RE.match(text) or _VERIFICATION_ID_RE.match(text))


def is_verification_incident_id(incident_id: str) -> bool:
    return bool(_VERIFICATION_ID_RE.match(str(incident_id or "").strip()))


def make_verification_incident_id(kst_date: str) -> str:
    return f"verification_{kst_date}_watchdog_test"


def program_display_name(program_id: str) -> str:
    return PROGRAM_DISPLAY.get(str(program_id or "").strip(), str(program_id or ""))


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def incidents_local_dir() -> Path:
    d = _repo_root() / "output" / INCIDENT_PREFIX
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bucket_name() -> Optional[str]:
    for key in ("GENIE_ADMIN_ARTIFACT_BUCKET", "GENIE_ARTIFACT_BUCKET"):
        name = os.environ.get(key, "").strip()
        if name:
            return name
    return None


def _uses_gcs() -> bool:
    return _bucket_name() is not None


def _object_key(incident_id: str) -> str:
    text = str(incident_id or "").strip()
    if text == ACTIVATION_META_ID:
        return f"{INCIDENT_PREFIX}/{ACTIVATION_META_ID}.json"
    if not validate_incident_id(text):
        raise ValueError("invalid incident_id")
    return f"{INCIDENT_PREFIX}/{text}.json"


def _read_raw_object(key: str) -> Optional[str]:
    try:
        if _uses_gcs():
            return _gcs_download(key)
        path = incidents_local_dir() / key.split("/", 1)[-1]
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _write_raw_object(key: str, text: str) -> None:
    with _LOCK:
        if _uses_gcs():
            _gcs_upload(key, text)
        else:
            path = incidents_local_dir() / key.split("/", 1)[-1]
            path.write_text(text, encoding="utf-8")


def load_activation_watermark() -> Optional[datetime]:
    """Return durable activation time (KST-aware) if present."""
    env = os.environ.get(ACTIVATION_ENV, "").strip()
    if env:
        try:
            dt = datetime.fromisoformat(env.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST)
        except ValueError:
            pass
    raw = _read_raw_object(_object_key(ACTIVATION_META_ID))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        text = str(data.get("activated_at") or "").strip()
        if not text:
            return None
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except Exception:
        return None


def ensure_activation_watermark(now: Optional[datetime] = None) -> datetime:
    """Persist first activation timestamp; never moves backwards."""
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    existing = load_activation_watermark()
    if existing is not None:
        return existing
    payload = {
        "activated_at": now.isoformat(),
        "purpose": "natural_run_watchdog_startup_watermark",
        "note": "Slots whose SLA threshold is before activated_at are not alerted on startup.",
    }
    _write_raw_object(
        _object_key(ACTIVATION_META_ID),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
    )
    return now


def _gcs_upload(key: str, text: str) -> None:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    bucket.blob(key).upload_from_string(text, content_type="application/json; charset=utf-8")


def _gcs_download(key: str) -> Optional[str]:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    blob = bucket.blob(key)
    if not blob.exists():
        return None
    return blob.download_as_text(encoding="utf-8")


def _gcs_list_ids(limit: int = 100) -> List[str]:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    prefix = f"{INCIDENT_PREFIX}/"
    blobs = list(bucket.list_blobs(prefix=prefix))
    blobs.sort(key=lambda b: getattr(b, "updated", None) or getattr(b, "time_created", None), reverse=True)
    out: List[str] = []
    for blob in blobs:
        name = blob.name
        if not name.endswith(".json"):
            continue
        stem = name[len(prefix) : -len(".json")]
        if validate_incident_id(stem):
            out.append(stem)
        if len(out) >= max(1, limit):
            break
    return out


def empty_stage_map() -> Dict[str, str]:
    return {
        "Scheduler": "확인불가",
        "Cloud Run": "확인불가",
        "실행 게이트": "확인불가",
        "데이터 수집": "확인불가",
        "콘텐츠 생성": "확인불가",
        "검증": "확인불가",
        "이미지": "확인불가",
        "Artifact": "확인불가",
        "운영자 메일": "확인불가",
    }


def new_incident(
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: Optional[str] = None,
    facts: Optional[List[str]] = None,
    confirmed_cause: Optional[str] = None,
    hypotheses: Optional[List[str]] = None,
    unknowns: Optional[List[str]] = None,
    stage_map: Optional[Dict[str, str]] = None,
    retry_verdict: str = RETRY_STATUS_UNKNOWN,
    retry_verdict_ko: str = "",
    recommendation_ko: str = "추가 조사 필요",
    original_run_id: Optional[str] = None,
    first_failed_stage: Optional[str] = None,
    error_code: Optional[str] = None,
    issue_codes: Optional[List[str]] = None,
    failure_event: Optional[Dict[str, Any]] = None,
    system_status: Optional[Dict[str, str]] = None,
    outcomes: Optional[Dict[str, str]] = None,
    summary_ko: str = "",
) -> Dict[str, Any]:
    slot = normalize_slot(scheduled_slot or NATURAL_SLOTS.get(program_id, ""))
    incident_id = make_incident_id(program_id, kst_date, slot)
    return {
        "incident_id": incident_id,
        "program_id": program_id,
        "program_display": program_display_name(program_id),
        "kst_date": kst_date,
        "scheduled_slot": slot,
        "status": STATUS_OPEN,
        "created_at": now_kst_iso(),
        "updated_at": now_kst_iso(),
        "detected_at": now_kst_iso(),
        "facts": list(facts or []),
        "confirmed_cause": confirmed_cause,  # None => 원인 미확정
        "hypotheses": list(hypotheses or []),
        "unknowns": list(unknowns or []),
        "stage_map": dict(stage_map or empty_stage_map()),
        "retry_verdict": retry_verdict,
        "retry_verdict_ko": retry_verdict_ko,
        "recommendation_ko": recommendation_ko,
        "original_run_id": original_run_id,
        "recovery_run_id": None,
        "first_failed_stage": first_failed_stage,
        "error_code": error_code,
        "issue_codes": list(issue_codes or []),
        "failure_event": dict(failure_event or {}),
        "system_status": dict(
            system_status
            or {
                "서비스 상태": "확인불가",
                "Cloud Run": "확인불가",
                "Scheduler": "확인불가",
                "장애 실행": "종료",
                "다음 정규 실행": "영향 없음",
            }
        ),
        "outcomes": dict(
            outcomes
            or {
                "자연실행 artifact": "확인불가",
                "운영자 검수 메일": "확인불가",
                "이미지 생성": "확인불가",
                "SMTP 시도": "확인불가",
                "고객 메일": "발송되지 않음",
                "데이터/Artifact 손상": "확인되지 않음",
                "중복 발송": "없음",
            }
        ),
        "summary_ko": summary_ko,
        "report_sent_at": None,
        "report_send_count": 0,
        "recovery_report_sent_at": None,
        "recovery_lease_token": None,
        "recovery_approved_at": None,
        "recovery_customer_send_count": 0,
        "watchdog_auto_retry_count": 0,
        "revision": os.getenv("K_REVISION", "").strip() or "",
    }


def save_incident(incident: Dict[str, Any]) -> str:
    incident_id = str(incident.get("incident_id") or "").strip()
    if not validate_incident_id(incident_id):
        raise ValueError("invalid incident_id")
    payload = dict(incident)
    payload["updated_at"] = now_kst_iso()
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with _LOCK:
        if _uses_gcs():
            _gcs_upload(_object_key(incident_id), text)
        else:
            path = incidents_local_dir() / f"{incident_id}.json"
            path.write_text(text, encoding="utf-8")
    return incident_id


def load_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    if not validate_incident_id(incident_id):
        return None
    try:
        if _uses_gcs():
            raw = _gcs_download(_object_key(incident_id))
        else:
            path = incidents_local_dir() / f"{incident_id}.json"
            if not path.exists():
                return None
            raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_incidents(limit: int = 50) -> List[Dict[str, Any]]:
    ids: List[str]
    if _uses_gcs():
        ids = _gcs_list_ids(limit)
    else:
        root = incidents_local_dir()
        files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        ids = [p.stem for p in files if validate_incident_id(p.stem)][: max(1, limit)]
    out: List[Dict[str, Any]] = []
    for iid in ids:
        meta = load_incident(iid)
        if meta:
            out.append(meta)
    return out


def upsert_incident(incident: Dict[str, Any]) -> Dict[str, Any]:
    """Create or merge; preserves report_sent_at / lease / recovery fields."""
    incident_id = str(incident.get("incident_id") or "").strip()
    existing = load_incident(incident_id) if incident_id else None
    if existing is None:
        save_incident(incident)
        return dict(incident)
    merged = dict(existing)
    for key, value in incident.items():
        if key in (
            "report_sent_at",
            "report_send_count",
            "recovery_lease_token",
            "recovery_approved_at",
            "recovery_run_id",
            "recovery_report_sent_at",
            "status",
        ) and existing.get(key) not in (None, "", 0, STATUS_OPEN):
            # Do not clobber terminal/reported state from a weaker upsert.
            if key == "status":
                # Allow enrichment while open; once reported+, keep unless explicit transition helpers used.
                continue
            continue
        if value is not None:
            merged[key] = value
    # Preserve critical counters
    for key in (
        "report_sent_at",
        "report_send_count",
        "recovery_lease_token",
        "recovery_approved_at",
        "recovery_run_id",
        "recovery_report_sent_at",
        "recovery_customer_send_count",
        "watchdog_auto_retry_count",
    ):
        if existing.get(key) is not None:
            merged[key] = existing.get(key)
    if existing.get("status") in {
        STATUS_REPORTED,
        STATUS_RECOVERY_APPROVED,
        STATUS_RECOVERY_SUCCEEDED,
        STATUS_RECOVERY_FAILED,
        STATUS_DISMISSED,
    }:
        merged["status"] = existing["status"]
    save_incident(merged)
    return merged


def mark_report_sent(incident_id: str) -> Optional[Dict[str, Any]]:
    meta = load_incident(incident_id)
    if not meta:
        return None
    if meta.get("report_sent_at"):
        return meta  # idempotent — no second send marker bump needed by callers
    meta["report_sent_at"] = now_kst_iso()
    meta["report_send_count"] = int(meta.get("report_send_count") or 0) + 1
    meta["status"] = STATUS_REPORTED
    meta["report_lease_token"] = None
    save_incident(meta)
    return meta


def acquire_report_lease(incident_id: str) -> Optional[str]:
    """Exactly-once send lease across instances. None if already sent/leased."""
    with _LOCK:
        meta = load_incident(incident_id)
        if not meta:
            return None
        if meta.get("report_sent_at"):
            return None
        if meta.get("report_lease_token"):
            return None
        token = secrets.token_hex(16)
        meta["report_lease_token"] = token
        meta["report_lease_acquired_at"] = now_kst_iso()
        save_incident(meta)
        return token


def release_report_lease(incident_id: str, lease_token: str) -> None:
    """Clear lease after failed send so a later poll may retry once."""
    with _LOCK:
        meta = load_incident(incident_id)
        if not meta:
            return
        if str(meta.get("report_lease_token") or "") != str(lease_token or ""):
            return
        meta["report_lease_token"] = None
        save_incident(meta)


def dismiss_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    meta = load_incident(incident_id)
    if not meta:
        return None
    meta["status"] = STATUS_DISMISSED
    meta["dismissed_at"] = now_kst_iso()
    save_incident(meta)
    return meta


def acquire_recovery_lease(incident_id: str) -> Optional[str]:
    """Return lease token on success; None if not acquirable."""
    with _LOCK:
        meta = load_incident(incident_id)
        if not meta:
            return None
        status = str(meta.get("status") or "")
        if status in {STATUS_RECOVERY_APPROVED, STATUS_RECOVERY_SUCCEEDED, STATUS_DISMISSED}:
            return None
        if status == STATUS_RECOVERY_FAILED:
            # Explicit re-approve after failure is allowed only if lease cleared.
            if meta.get("recovery_lease_token"):
                return None
        if status not in {STATUS_REPORTED, STATUS_OPEN, STATUS_RECOVERY_FAILED}:
            return None
        if meta.get("recovery_lease_token") and status == STATUS_RECOVERY_APPROVED:
            return None
        token = secrets.token_hex(16)
        meta["recovery_lease_token"] = token
        meta["recovery_approved_at"] = now_kst_iso()
        meta["status"] = STATUS_RECOVERY_APPROVED
        save_incident(meta)
        return token


def complete_recovery(
    incident_id: str,
    *,
    lease_token: str,
    success: bool,
    recovery_run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    meta = load_incident(incident_id)
    if not meta:
        return None
    if str(meta.get("recovery_lease_token") or "") != str(lease_token or ""):
        return None
    meta["recovery_run_id"] = recovery_run_id
    meta["status"] = STATUS_RECOVERY_SUCCEEDED if success else STATUS_RECOVERY_FAILED
    meta["recovery_completed_at"] = now_kst_iso()
    if not success:
        # Clear lease so owner may approve again after failure (no auto retry).
        meta["recovery_lease_token"] = None
    save_incident(meta)
    return meta


def mark_recovery_report_sent(incident_id: str) -> Optional[Dict[str, Any]]:
    meta = load_incident(incident_id)
    if not meta:
        return None
    meta["recovery_report_sent_at"] = now_kst_iso()
    save_incident(meta)
    return meta
