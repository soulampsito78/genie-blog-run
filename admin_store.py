"""Run artifacts for owner admin review and reissue tracking (local or GCS)."""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

_RUN_ID_MODES = (
    "today_genie",
    "tomorrow_genie",
    "keysuri_global_tech",
    "keysuri_korea_tech",
)
_RUN_ID_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_(today_genie|tomorrow_genie|keysuri_global_tech|keysuri_korea_tech)_[a-f0-9]{8}$"
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
_KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES = frozenset(
    {"keysuri_global_tech", "keysuri_korea_tech"}
)

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


def admin_artifact_bucket_name() -> Optional[str]:
    """GCS bucket for durable admin artifacts.

    Primary: ``GENIE_ADMIN_ARTIFACT_BUCKET``. Legacy Cloud Run alias: ``GENIE_ARTIFACT_BUCKET``.
    """
    for key in ("GENIE_ADMIN_ARTIFACT_BUCKET", "GENIE_ARTIFACT_BUCKET"):
        name = os.environ.get(key, "").strip()
        if name:
            return name
    return None


def admin_artifact_gcs_prefix() -> str:
    for key in ("GENIE_ADMIN_ARTIFACT_GCS_PREFIX", "GENIE_ARTIFACT_PREFIX"):
        raw = os.environ.get(key, "").strip().strip("/")
        if raw:
            return raw
    return "admin_runs"


def artifact_storage_backend_name() -> str:
    return "gcs" if admin_artifact_bucket_name() else "local"


def is_artifact_storage_durable() -> bool:
    return artifact_storage_backend_name() == "gcs"


def artifact_store_display_path() -> str:
    bucket = admin_artifact_bucket_name()
    if bucket:
        return f"gs://{bucket}/{admin_artifact_gcs_prefix()}"
    return str(admin_runs_dir())


def gcs_artifact_object_key(run_id: str, suffix: str) -> str:
    """Build a GCS object key under the configured prefix (suffix includes leading dot)."""
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return f"{admin_artifact_gcs_prefix()}/{run_id}{suffix}"


def gcs_json_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ".json")


def gcs_email_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ".email.html")


def gcs_contract_preview_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ".contract_preview.html")


_gcs_client: Any = None


def _uses_gcs_backend() -> bool:
    return admin_artifact_bucket_name() is not None


def _get_gcs_client() -> Any:
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage

        _gcs_client = storage.Client()
    return _gcs_client


def _get_gcs_bucket() -> Any:
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        raise RuntimeError("GCS backend requested without GENIE_ADMIN_ARTIFACT_BUCKET")
    return _get_gcs_client().bucket(bucket_name)


def _gcs_upload_text(key: str, text: str, *, content_type: str) -> None:
    blob = _get_gcs_bucket().blob(key)
    blob.upload_from_string(text, content_type=content_type)


def _gcs_download_text(key: str) -> Optional[str]:
    blob = _get_gcs_bucket().blob(key)
    if not blob.exists():
        return None
    return blob.download_as_text(encoding="utf-8")


def _gcs_delete_object(key: str) -> None:
    blob = _get_gcs_bucket().blob(key)
    if blob.exists():
        blob.delete()


def _write_json_blob(run_id: str, meta: Dict[str, Any]) -> None:
    payload = json.dumps(meta, ensure_ascii=False, indent=2)
    if _uses_gcs_backend():
        _gcs_upload_text(gcs_json_object_key(run_id), payload, content_type="application/json")
        return
    artifact_json_path(run_id).write_text(payload, encoding="utf-8")


def _read_json_blob(run_id: str) -> Optional[Dict[str, Any]]:
    if _uses_gcs_backend():
        raw = _gcs_download_text(gcs_json_object_key(run_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    path = artifact_json_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_email_blob(run_id: str, email_html: str) -> None:
    if _uses_gcs_backend():
        _gcs_upload_text(
            gcs_email_object_key(run_id),
            email_html,
            content_type="text/html; charset=utf-8",
        )
        return
    artifact_email_path(run_id).write_text(email_html, encoding="utf-8")


def _read_email_blob(run_id: str) -> Optional[str]:
    if _uses_gcs_backend():
        return _gcs_download_text(gcs_email_object_key(run_id))
    path = artifact_email_path(run_id)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _sync_optional_preview_artifacts(run_id: str, meta: Dict[str, Any]) -> None:
    """Upload contract preview HTML to GCS when ``html_path`` is present in metadata."""
    if not _uses_gcs_backend():
        return
    preview_rel = str(meta.get("html_path") or "").strip()
    if not preview_rel:
        return
    path = Path(preview_rel)
    if not path.is_absolute():
        path = repo_root() / path
    if not path.is_file():
        return
    try:
        preview_html = path.read_text(encoding="utf-8")
    except OSError:
        return
    key = gcs_contract_preview_object_key(run_id)
    _gcs_upload_text(key, preview_html, content_type="text/html; charset=utf-8")
    meta["contract_preview_gcs_object"] = key


def _apply_artifact_storage_fields(meta: Dict[str, Any]) -> None:
    backend = artifact_storage_backend_name()
    meta["artifact_storage_backend"] = backend
    meta["artifact_storage_durable"] = backend == "gcs"


def validate_run_id(run_id: str) -> bool:
    return bool(_RUN_ID_RE.match(str(run_id or "").strip()))


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def generate_run_id(mode: str) -> str:
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    stamp = kst.strftime("%Y%m%d_%H%M%S")
    short = secrets.token_hex(4)
    safe_mode = mode if mode in _RUN_ID_MODES else "unknown"
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
    _apply_artifact_storage_fields(meta)
    _sync_optional_preview_artifacts(run_id, meta)
    _write_json_blob(run_id, meta)
    if email_html and email_html.strip():
        _write_email_blob(run_id, email_html)

    parent_id = str(meta.get("parent_run_id") or "").strip()
    if parent_id and validate_run_id(parent_id):
        _increment_parent_reissue_count(parent_id)

    return run_id


def _increment_parent_reissue_count(parent_run_id: str) -> None:
    parent = _read_json_blob(parent_run_id)
    if not parent:
        return
    parent["reissue_count"] = int(parent.get("reissue_count") or 0) + 1
    parent["artifact_status"] = "reissue_requested"
    _write_json_blob(parent_run_id, parent)


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


def load_run_artifact(run_id: str, *, normalize: bool = True) -> Optional[Dict[str, Any]]:
    if not validate_run_id(run_id):
        return None
    data = _read_json_blob(run_id)
    if not data:
        return None
    if normalize:
        return normalize_artifact_view(data, run_id)
    return data


def load_run_email_html(run_id: str) -> Optional[str]:
    if not validate_run_id(run_id):
        return None
    return _read_email_blob(run_id)


def _list_run_ids_from_gcs(limit: int) -> List[str]:
    prefix = f"{admin_artifact_gcs_prefix()}/"
    blobs = list(_get_gcs_bucket().list_blobs(prefix=prefix))
    json_blobs = [b for b in blobs if b.name.endswith(".json")]
    def _blob_sort_key(blob: Any) -> datetime:
        ts = getattr(blob, "updated", None) or getattr(blob, "time_created", None)
        if ts is None:
            return datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        return ts

    json_blobs.sort(key=_blob_sort_key, reverse=True)
    run_ids: List[str] = []
    for blob in json_blobs:
        name = blob.name
        if not name.startswith(prefix):
            continue
        stem = name[len(prefix) :]
        if not stem.endswith(".json"):
            continue
        run_id = stem[: -len(".json")]
        if validate_run_id(run_id):
            run_ids.append(run_id)
        if len(run_ids) >= max(1, limit):
            break
    return run_ids


def list_run_artifacts(limit: int = 50) -> List[Dict[str, Any]]:
    if _uses_gcs_backend():
        run_ids = _list_run_ids_from_gcs(limit)
    else:
        root = admin_runs_dir()
        files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        run_ids = []
        for path in files:
            if validate_run_id(path.stem):
                run_ids.append(path.stem)
            if len(run_ids) >= max(1, limit):
                break
    out: List[Dict[str, Any]] = []
    for run_id in run_ids[: max(1, limit)]:
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
    meta = _read_json_blob(run_id)
    if not meta:
        return None
    mutator(meta)
    meta["artifact_status"] = derive_artifact_status(meta)
    _write_json_blob(run_id, meta)
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
    if mode in _KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES:
        return False, "keysuri_customer_delivery_not_ready"
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

        send_ok = send_today_geenee_customer_final_email(saved_html, meta)
        diag_source = last_send_diagnostic
    else:
        return None, "unsupported_mode"

    if not send_ok:
        diag = sanitize_delivery_error_summary(diag_source() or "Customer email send failed.")

        def _fail(m: Dict[str, Any]) -> None:
            _record_customer_delivery_failure(
                m,
                attempted_at=attempted_at,
                error_summary=diag,
                error_code="send_failed",
            )

        update_run_artifact(run_id, _fail)
        return None, "send_failed"

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


APPROVABLE_ARTIFACT_STATUSES = frozenset({"emailed", "validated", "reissued", "review_required"})
_SCHEDULER_OWNER_REVIEW_STATUSES = frozenset({"pending_review", "approved", "reopened"})


def check_artifact_store_ready() -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return (error_message, store_desc). Exactly one side is populated on failure paths."""
    bucket_name = admin_artifact_bucket_name()
    if bucket_name:
        try:
            probe_key = f"{admin_artifact_gcs_prefix()}/.store_ready_probe"
            _gcs_upload_text(probe_key, "ok", content_type="text/plain")
            _gcs_delete_object(probe_key)
            return None, {
                "backend": "gcs",
                "bucket": bucket_name,
                "prefix": admin_artifact_gcs_prefix(),
                "durable": True,
            }
        except Exception as exc:
            return str(exc), None
    try:
        root = admin_runs_dir()
        probe = root / ".store_ready_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return None, {"backend": "local", "path": str(root), "durable": False}
    except OSError as exc:
        return str(exc), None


def normalize_artifact_view(meta: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Return artifact with safe defaults for admin display (does not persist)."""
    view = dict(meta)
    view.setdefault("run_id", run_id)
    view.setdefault("artifact_status", derive_artifact_status(view))
    view.setdefault("owner_review_status", "pending_review")
    view.setdefault("customer_delivery_status", "not_sent")
    return view


def find_scheduled_owner_review_for_kst_date(
    mode: str,
    *,
    kst_date: Optional[datetime] = None,
    limit: int = 100,
) -> Optional[str]:
    """
    Find an existing same-KST-calendar-day owner-review run for scheduler dedupe.
    Reissue children (parent_run_id set) are ignored. validation_result=block with
    email_sent=false does not count (scheduler may retry).
    """
    if mode != "today_genie":
        return None
    if kst_date is None:
        kst_date = datetime.now(ZoneInfo("Asia/Seoul"))
    elif kst_date.tzinfo is None:
        kst_date = kst_date.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    date_prefix = kst_date.strftime("%Y%m%d_")

    for raw in list_run_artifacts(limit=limit):
        run_id = str(raw.get("run_id") or "").strip()
        if not run_id or not validate_run_id(run_id):
            continue
        if str(raw.get("mode") or "") != mode:
            continue
        if not run_id.startswith(date_prefix):
            continue
        if raw.get("parent_run_id"):
            continue
        validation_result = str(raw.get("validation_result") or "")
        email_sent = bool(raw.get("email_sent"))
        if validation_result == "block" and not email_sent:
            continue
        owner_status = str(raw.get("owner_review_status") or "")
        if email_sent or owner_status in _SCHEDULER_OWNER_REVIEW_STATUSES:
            return run_id
    return None


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def classify_timeout_skip(
    meta: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    has_email_html: bool = False,
) -> Optional[str]:
    """Return skip reason code if run is not eligible for timeout send, else None."""
    view = normalize_artifact_view(meta, str(meta.get("run_id") or ""))
    owner_status = str(view.get("owner_review_status") or "")
    if owner_status == "approved":
        return "already_approved"
    if owner_status == "auto_sent_after_timeout":
        return "already_timeout_sent"
    if owner_status != "pending_review":
        return "not_pending_review"
    delivery = str(view.get("customer_delivery_status") or "not_sent")
    if delivery != "not_sent":
        return "customer_already_sent"
    vr = str(view.get("validation_result") or "")
    wf = str(view.get("workflow_status") or "")
    artifact_status = str(view.get("artifact_status") or derive_artifact_status(view))
    if vr == "block":
        return "validation_block"
    if artifact_status == "failed":
        return "artifact_failed"
    if not (
        vr == "pass"
        or wf == "validated"
        or artifact_status in APPROVABLE_ARTIFACT_STATUSES
    ):
        return "not_approvable"
    if not has_email_html:
        return "missing_email_html"
    deadline_raw = view.get("approval_deadline_at")
    deadline = _parse_iso_datetime(deadline_raw)
    if deadline is None:
        return "missing_deadline"
    if now is None:
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    if deadline > now:
        return "before_deadline"
    return None


def _timeout_customer_send_retired() -> bool:
    """Batch 8.3 policy: timeout auto-send is retired on main."""
    return True


def process_approval_timeouts(
    *,
    now: Optional[datetime] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """
    Scan artifacts for approval-timeout eligibility.
    On main, timeout customer auto-send is retired; scan results are returned without send.
    """
    from collections import Counter

    from today_geenee_customer_delivery import (
        customer_delivery_config_ready,
        send_customer_timeout_draft_email,
    )

    if now is None:
        now = datetime.now(ZoneInfo("Asia/Seoul"))

    ready, config_err = customer_delivery_config_ready()
    if not ready:
        return {
            "ok": False,
            "error": config_err,
            "scanned": 0,
            "eligible": 0,
            "sent": 0,
            "skipped": 0,
            "errors": 0,
            "run_ids_sent": [],
            "skip_reasons": {},
            "error_run_ids": [],
        }

    retired = _timeout_customer_send_retired()
    summary: Dict[str, Any] = {
        "ok": True,
        "error": None,
        "scanned": 0,
        "eligible": 0,
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "run_ids_sent": [],
        "skip_reasons": {},
        "error_run_ids": [],
    }
    skip_counter: Counter[str] = Counter()

    for raw in list_run_artifacts(limit=limit):
        run_id = str(raw.get("run_id") or "").strip()
        if not run_id or not validate_run_id(run_id):
            continue
        summary["scanned"] = int(summary["scanned"]) + 1
        view = normalize_artifact_view(raw, run_id)
        saved_html = load_run_email_html(run_id) or ""
        has_html = bool(saved_html.strip())
        skip = classify_timeout_skip(view, now=now, has_email_html=has_html)
        if skip:
            skip_counter[skip] += 1
            summary["skipped"] = int(summary["skipped"]) + 1
            continue

        summary["eligible"] = int(summary["eligible"]) + 1
        if retired:
            skip_counter["timeout_send_retired"] += 1
            summary["skipped"] = int(summary["skipped"]) + 1
            continue

        if not send_customer_timeout_draft_email(saved_html, view):
            summary["errors"] = int(summary["errors"]) + 1
            summary["error_run_ids"].append(run_id)
            continue

        summary["sent"] = int(summary["sent"]) + 1
        summary["run_ids_sent"].append(run_id)

    summary["skip_reasons"] = dict(skip_counter)
    if retired:
        summary["retired"] = True
        summary["note"] = "timeout customer send retired"
    return summary
