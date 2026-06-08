"""File-based run artifacts for owner admin review and reissue tracking."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

_RUN_ID_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_(today_genie|tomorrow_genie)_[a-f0-9]{8}$"
)

OWNER_REVIEW_STATUSES = frozenset(
    {"pending_review", "approved", "reopened", "approval_expired_manual_required"}
)
LEGACY_OWNER_REVIEW_STATUSES = frozenset({"auto_sent_after_timeout"})
REISSUE_SCOPES = frozenset({"text_only", "image_only", "text_and_image"})
EXECUTABLE_REISSUE_SCOPE = "text_and_image"
UNSUPPORTED_REISSUE_SCOPES = frozenset({"text_only", "image_only"})

CUSTOMER_DELIVERY_STATUSES = frozenset(
    {
        "not_sent",
        "send_attempted",
        "smtp_accepted",
        "delivery_confirmed",
        "bounced",
        "rejected",
        "delayed",
        "failed",
        "unknown",
        "customer_sent_after_approval",
        "sent_after_owner_approval",
    }
)
_CUSTOMER_DELIVERY_SENT_OR_ACCEPTED = frozenset(
    {
        "customer_sent_after_approval",
        "sent_after_owner_approval",
        "smtp_accepted",
        "delivery_confirmed",
    }
)
LEGACY_CUSTOMER_DELIVERY_STATUSES = frozenset({"sent_after_timeout"})
APPROVABLE_MODES = frozenset({"today_genie", "tomorrow_genie"})

_CUSTOMER_DELIVERY_STATUS_LABELS_KO = {
    "not_sent": "미발송",
    "send_attempted": "발송 시도 중",
    "smtp_accepted": "SMTP 접수",
    "delivery_confirmed": "전달 확인",
    "bounced": "반송됨",
    "rejected": "거절됨",
    "delayed": "지연 중",
    "failed": "발송 실패",
    "unknown": "확인 불가",
    "customer_sent_after_approval": "SMTP 접수",
    "sent_after_owner_approval": "SMTP 접수",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def admin_runs_dir() -> Path:
    d = repo_root() / "output" / "admin_runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.match(str(run_id or "").strip()))


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def generate_run_id(mode: str) -> str:
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    stamp = kst.strftime("%Y%m%d_%H%M%S")
    short = secrets.token_hex(4)
    safe_mode = mode if mode in ("today_genie", "tomorrow_genie") else "unknown"
    return f"{stamp}_{safe_mode}_{short}"


def artifact_json_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}.json"


def artifact_email_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}.email.html"


def derive_artifact_status(meta: Dict[str, Any]) -> str:
    if meta.get("parent_run_id"):
        if meta.get("email_sent"):
            return "reissued"
        if meta.get("artifact_status") == "failed":
            return "failed"
        return "reissued"
    if meta.get("response_status") not in (200, "200", None) and meta.get("response_status") is not None:
        if int(meta.get("response_status") or 0) != 200:
            return "failed"
    if meta.get("reason_summary") in ("request_failed", "invalid_response_body", "validation_block", "api_error"):
        if meta.get("response_status") != 200:
            return "failed"
    if meta.get("email_sent"):
        return "emailed"
    wf = str(meta.get("workflow_status") or "")
    vr = str(meta.get("validation_result") or "")
    if wf == "review_required" or vr == "draft_only":
        return "review_required"
    if vr == "pass" or wf == "validated":
        return "validated"
    if meta.get("response_status") == 200:
        return "generated"
    return "failed"


def save_run_artifact(
    meta: Dict[str, Any],
    email_html: str = "",
) -> str:
    run_id = str(meta.get("run_id") or "").strip()
    if not run_id:
        run_id = generate_run_id(str(meta.get("mode") or "unknown"))
        meta["run_id"] = run_id
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id in metadata")

    meta = dict(meta)
    if "created_at" not in meta:
        meta["created_at"] = now_kst_iso()
    if meta.get("owner_review_status") is None:
        meta["owner_review_status"] = "pending_review"
    if meta.get("customer_delivery_status") is None:
        meta["customer_delivery_status"] = "not_sent"
    meta["artifact_status"] = derive_artifact_status(meta)

    artifact_json_path(run_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if email_html and email_html.strip():
        artifact_email_path(run_id).write_text(email_html, encoding="utf-8")

    parent_id = str(meta.get("parent_run_id") or "").strip()
    if parent_id and validate_run_id(parent_id):
        _increment_parent_reissue_count(parent_id)

    return run_id


def _increment_parent_reissue_count(parent_run_id: str) -> None:
    path = artifact_json_path(parent_run_id)
    if not path.is_file():
        return
    try:
        parent = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(parent, dict):
        return
    parent["reissue_count"] = int(parent.get("reissue_count") or 0) + 1
    parent["artifact_status"] = "reissue_requested"
    path.write_text(json.dumps(parent, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_delivery_error_summary(raw: str, *, max_len: int = 240) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", str(raw or "").strip())
    if not cleaned:
        return "Customer email send failed."
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def customer_delivery_status_label_ko(status: str) -> str:
    key = str(status or "not_sent").strip() or "not_sent"
    return _CUSTOMER_DELIVERY_STATUS_LABELS_KO.get(key, key)


def owner_review_email_label_ko(meta: Dict[str, Any]) -> str:
    if meta.get("email_sent"):
        return "운영자 검토용 이메일 발송됨"
    return "운영자 검토용 이메일 미발송"


def append_customer_delivery_event(meta: Dict[str, Any], event: Dict[str, Any]) -> None:
    events = meta.get("customer_delivery_events")
    if not isinstance(events, list):
        events = []
    events.append(event)
    meta["customer_delivery_events"] = events


def record_parent_reissue_audit(
    parent_run_id: str,
    *,
    child_run_id: str,
    reissue_scope: str,
) -> None:
    def _mut(parent: Dict[str, Any]) -> None:
        parent["last_reissue_scope_requested"] = reissue_scope
        parent["last_reissue_child_run_id"] = child_run_id

    update_run_artifact(parent_run_id, _mut)


def apply_reissue_child_metadata(
    child_run_id: str,
    *,
    reissue_scope: str,
    reissue_reason_code: str,
    reissue_reason_note: str,
    reissue_scope_status: str = "executed",
) -> Optional[Dict[str, Any]]:
    ts = now_kst_iso()

    def _mut(child: Dict[str, Any]) -> None:
        child["reissue_scope"] = reissue_scope
        child["reissue_scope_supported"] = reissue_scope == EXECUTABLE_REISSUE_SCOPE
        child["reissue_scope_status"] = reissue_scope_status
        child["reissue_reason_code"] = reissue_reason_code or None
        child["reissue_reason_note"] = reissue_reason_note or None
        child["reissue_requested_at"] = ts
        child["reissue_requested_by"] = "owner_admin"

    return update_run_artifact(child_run_id, _mut)


def load_run_artifact(run_id: str) -> Optional[Dict[str, Any]]:
    if not validate_run_id(run_id):
        return None
    path = artifact_json_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_run_email_html(run_id: str) -> Optional[str]:
    if not validate_run_id(run_id):
        return None
    path = artifact_email_path(run_id)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def list_run_artifacts(limit: int = 50) -> List[Dict[str, Any]]:
    root = admin_runs_dir()
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for path in files[: max(1, limit)]:
        run_id = path.stem
        if not validate_run_id(run_id):
            continue
        meta = load_run_artifact(run_id)
        if meta:
            out.append(meta)
    return out


def update_run_artifact(
    run_id: str,
    mutator: Callable[[Dict[str, Any]], None],
) -> Optional[Dict[str, Any]]:
    if not validate_run_id(run_id):
        return None
    path = artifact_json_path(run_id)
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    mutator(meta)
    meta["artifact_status"] = derive_artifact_status(meta)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _is_legacy_timeout_artifact(meta: Dict[str, Any]) -> bool:
    owner = str(meta.get("owner_review_status") or "")
    delivery = str(meta.get("customer_delivery_status") or "")
    return (
        owner in LEGACY_OWNER_REVIEW_STATUSES
        or delivery in LEGACY_CUSTOMER_DELIVERY_STATUSES
    )


def can_approve_customer_send(meta: Dict[str, Any], *, has_email_html: bool) -> tuple[bool, str]:
    mode = str(meta.get("mode") or "")
    if mode not in APPROVABLE_MODES:
        return False, "unsupported_mode"
    if _is_legacy_timeout_artifact(meta):
        return False, "legacy_timeout_sent"
    owner_status = str(meta.get("owner_review_status") or "pending_review")
    if owner_status == "approved":
        return False, "already_approved"
    delivery = str(meta.get("customer_delivery_status") or "not_sent")
    if delivery in LEGACY_CUSTOMER_DELIVERY_STATUSES:
        return False, "legacy_timeout_sent"
    if delivery in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED:
        return False, "customer_already_sent"
    if delivery not in ("not_sent", "", "failed"):
        return False, "customer_already_sent"
    if owner_status not in OWNER_REVIEW_STATUSES:
        return False, "invalid_owner_review_status"
    vr = str(meta.get("validation_result") or "")
    if vr == "block" or str(meta.get("artifact_status") or "") == "failed":
        return False, "not_approvable"
    if not has_email_html:
        return False, "missing_email_html"
    if mode == "today_genie":
        from today_geenee_customer_delivery import customer_delivery_config_ready

        ready, err = customer_delivery_config_ready()
        if not ready:
            return False, err
    return True, "ok"


def _record_customer_delivery_attempt(meta: Dict[str, Any], *, attempted_at: str) -> None:
    meta["customer_delivery_attempted_at"] = attempted_at
    meta["customer_delivery_attempt_count"] = int(meta.get("customer_delivery_attempt_count") or 0) + 1
    meta["customer_delivery_event_source"] = "approve_run"
    meta["customer_delivery_status"] = "send_attempted"
    meta["customer_delivery_last_event_at"] = attempted_at


def _record_customer_delivery_failure(
    meta: Dict[str, Any],
    *,
    attempted_at: str,
    error_summary: str,
    error_code: str = "smtp_send_failed",
) -> None:
    summary = sanitize_delivery_error_summary(error_summary)
    meta["customer_delivery_status"] = "failed"
    meta["customer_delivery_error_code"] = error_code
    meta["customer_delivery_error_summary"] = summary
    meta["customer_delivery_last_event_at"] = attempted_at
    append_customer_delivery_event(
        meta,
        {
            "status": "failed",
            "event_type": "smtp_send_failed",
            "source": "approve_run",
            "summary": summary,
            "at": attempted_at,
        },
    )


def _record_customer_delivery_smtp_accepted(meta: Dict[str, Any], *, completed_at: str) -> None:
    meta["customer_delivery_status"] = "smtp_accepted"
    meta["customer_delivery_legacy_status"] = "customer_sent_after_approval"
    meta["customer_delivery_completed_at"] = completed_at
    meta["customer_delivery_last_event_at"] = completed_at
    meta["customer_delivery_error_code"] = None
    meta["customer_delivery_error_summary"] = None
    append_customer_delivery_event(
        meta,
        {
            "status": "smtp_accepted",
            "event_type": "smtp_send",
            "source": "approve_run",
            "summary": "SMTP send accepted by configured mail server.",
            "at": completed_at,
        },
    )


def approve_run(run_id: str, note: str = "") -> tuple[Optional[Dict[str, Any]], str]:
    """Approve run and send customer final email immediately (today_genie HTML body only)."""
    meta = load_run_artifact(run_id)
    if not meta:
        return None, "not_found"

    saved_html = load_run_email_html(run_id) or ""
    ok, msg = can_approve_customer_send(meta, has_email_html=bool(saved_html.strip()))
    if not ok:
        return None, msg

    attempted_at = now_kst_iso()
    update_run_artifact(run_id, lambda m: _record_customer_delivery_attempt(m, attempted_at=attempted_at))

    mode = str(meta.get("mode") or "")
    if mode == "today_genie":
        from email_sender import last_send_diagnostic
        from today_geenee_customer_delivery import send_today_geenee_customer_final_email

        if not send_today_geenee_customer_final_email(saved_html, meta):
            diag = sanitize_delivery_error_summary(last_send_diagnostic() or "Customer email send failed.")

            def _fail(m: Dict[str, Any]) -> None:
                _record_customer_delivery_failure(
                    m,
                    attempted_at=attempted_at,
                    error_summary=diag,
                    error_code="send_failed",
                )

            update_run_artifact(run_id, _fail)
            return None, "send_failed"
    else:
        return None, "unsupported_mode"

    cleaned_note = note.strip()
    sent_ts = now_kst_iso()

    def _mut(m: Dict[str, Any]) -> None:
        m["owner_review_status"] = "approved"
        m["owner_reviewed_at"] = sent_ts
        m["approved_at"] = sent_ts
        m["owner_review_note"] = cleaned_note or None
        m["approved_by"] = "owner_admin"
        m["customer_delivery_reason"] = "owner_approved"
        m["customer_sent_at"] = sent_ts
        _record_customer_delivery_smtp_accepted(m, completed_at=sent_ts)

    updated = update_run_artifact(run_id, _mut)
    return updated, "ok"
