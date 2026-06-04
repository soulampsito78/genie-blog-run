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
CUSTOMER_DELIVERY_STATUSES = frozenset(
    {
        "not_sent",
        "customer_sent_after_approval",
        "sent_after_owner_approval",
        "failed",
    }
)
LEGACY_CUSTOMER_DELIVERY_STATUSES = frozenset({"sent_after_timeout"})
APPROVABLE_MODES = frozenset({"today_genie", "tomorrow_genie"})


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
    if delivery not in ("not_sent", ""):
        if delivery in LEGACY_CUSTOMER_DELIVERY_STATUSES:
            return False, "legacy_timeout_sent"
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


def approve_run(run_id: str, note: str = "") -> tuple[Optional[Dict[str, Any]], str]:
    """Approve run and send customer final email immediately (today_genie HTML body only)."""
    meta = load_run_artifact(run_id)
    if not meta:
        return None, "not_found"

    saved_html = load_run_email_html(run_id) or ""
    ok, msg = can_approve_customer_send(meta, has_email_html=bool(saved_html.strip()))
    if not ok:
        return None, msg

    mode = str(meta.get("mode") or "")
    if mode == "today_genie":
        from today_geenee_customer_delivery import send_today_geenee_customer_final_email

        if not send_today_geenee_customer_final_email(saved_html, meta):
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
        m["customer_delivery_status"] = "customer_sent_after_approval"
        m["customer_delivery_reason"] = "owner_approved"
        m["customer_sent_at"] = sent_ts

    updated = update_run_artifact(run_id, _mut)
    return updated, "ok"
