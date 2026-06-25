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

from delivery_trace import build_customer_email_delivery_fields, sanitize_email_diagnostic

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
UNSUPPORTED_REISSUE_SCOPES = frozenset()

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
APPROVABLE_MODES = frozenset({"today_genie", "tomorrow_genie", "keysuri_global_tech", "keysuri_korea_tech"})
# keysuri_korea_tech delivery accepts the fixed baseline or generated-v6 anchor contract.
_KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES: frozenset = frozenset()  # retired: all modes now use per-mode gates

# Korea Bottom QA baseline lock (041559, commit bc78424)
_KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID = "keysuri_korea_bottom_20260605_105936"
_KEYSURI_KOREA_BOTTOM_APPROVED_SOURCES = frozenset({
    "fixed_105936_fallback",
    "fixed_105936_fallback_variation_not_implemented",
})
_KEYSURI_KOREA_BOTTOM_GENERATED_SOURCE = "generated_v6_multi_ref"

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
    "blocked": "정책 차단",
}

_CUSTOMER_DELIVERY_PANEL_GRADE: Dict[str, tuple[str, str]] = {
    "smtp_accepted": ("PASS", "발송 접수 완료"),
    "delivery_confirmed": ("PASS", "발송 접수 완료"),
    "customer_sent_after_approval": ("PASS", "발송 접수 완료"),
    "sent_after_owner_approval": ("PASS", "발송 접수 완료"),
    "failed": ("FAIL", "발송 실패"),
    "bounced": ("FAIL", "발송 실패"),
    "rejected": ("FAIL", "발송 실패"),
    "blocked": ("BLOCKED", "정책 차단"),
    "not_sent": ("대기", "미발송"),
    "send_attempted": ("대기", "발송 시도 중"),
    "unknown": ("대기", "확인 불가"),
}

_ADMIN_MISSING = "미기록"
_ADMIN_NONE = "없음"


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
    cleaned = sanitize_email_diagnostic(str(raw or "").strip())
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", cleaned)
    if not cleaned:
        return "Customer email send failed."
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def customer_delivery_status_label_ko(status: str) -> str:
    key = str(status or "not_sent").strip() or "not_sent"
    return _CUSTOMER_DELIVERY_STATUS_LABELS_KO.get(key, key)


def mask_customer_email(address: str) -> str:
    """Mask customer email for admin display: tera9003@daum.net -> t***3@daum.net."""
    raw = str(address or "").strip()
    if not raw or "@" not in raw:
        return raw or _ADMIN_NONE
    local, domain = raw.split("@", 1)
    local = local.strip()
    domain = domain.strip()
    if not local or not domain:
        return raw
    if len(local) == 1:
        masked_local = f"{local[0]}***"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def _panel_value(meta: Dict[str, Any], *keys: str, default: str = _ADMIN_MISSING) -> str:
    for key in keys:
        value = meta.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            return "예" if value else "아니오"
        return str(value).strip()
    return default


def _panel_recipients(meta: Dict[str, Any]) -> List[str]:
    masked = meta.get("customer_email_recipients_masked") or meta.get("customer_recipients_masked")
    if isinstance(masked, list):
        out = [str(item).strip() for item in masked if str(item).strip()]
        if out:
            return out
    for key in ("customer_recipients", "customer_recipient_list", "envelope_to"):
        raw = meta.get(key)
        if isinstance(raw, list):
            out = [str(item).strip() for item in raw if str(item).strip()]
            if out:
                return out
        if isinstance(raw, str) and raw.strip():
            parts = [part.strip() for part in re.split(r"[,;]", raw) if part.strip()]
            if parts:
                return parts
    trace = meta.get("customer_delivery_send_trace")
    if isinstance(trace, dict):
        envelope = trace.get("envelope_to")
        if isinstance(envelope, list):
            out = [str(item).strip() for item in envelope if str(item).strip()]
            if out:
                return out
    return []


def _panel_delivery_grade(meta: Dict[str, Any]) -> tuple[str, str, str]:
    delivery_status = str(meta.get("customer_delivery_status") or "not_sent").strip() or "not_sent"
    if delivery_status in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED:
        return delivery_status, "PASS", "발송 접수 완료"
    if delivery_status == "failed":
        return delivery_status, "FAIL", "발송 실패"
    if delivery_status == "blocked":
        return delivery_status, "BLOCKED", "정책 차단"
    grade = _CUSTOMER_DELIVERY_PANEL_GRADE.get(
        delivery_status,
        ("대기", customer_delivery_status_label_ko(delivery_status)),
    )
    return delivery_status, grade[0], grade[1]


def _panel_double_send_blocked(meta: Dict[str, Any]) -> str:
    delivery_status = str(meta.get("customer_delivery_status") or "not_sent").strip()
    owner_status = str(meta.get("owner_review_status") or "").strip()
    if delivery_status in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED or owner_status == "approved":
        return "예 — 이미 발송됨 / 재발송 차단"
    return "아니오"


def _panel_smtp_accepted(meta: Dict[str, Any]) -> str:
    if meta.get("smtp_accepted") is True:
        return "예"
    if meta.get("smtp_accepted") is False:
        return "아니오"
    delivery_status = str(meta.get("customer_delivery_status") or "not_sent").strip()
    if delivery_status in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED:
        return "예"
    if delivery_status in {"failed", "bounced", "rejected"}:
        return "아니오"
    return _ADMIN_MISSING


def _panel_image_evidence(meta: Dict[str, Any]) -> Dict[str, str]:
    top_cid = _panel_value(meta, "top_image_cid", default=_ADMIN_NONE)
    bottom_cid = _panel_value(
        meta,
        "bottom_image_cid",
        "korea_bottom_shot_cid",
        default=_ADMIN_NONE,
    )
    cids = meta.get("customer_email_image_cids") or meta.get("owner_email_image_cids") or []
    mime_count = str(len(cids)) if isinstance(cids, list) and cids else _ADMIN_MISSING
    image_source = str(meta.get("customer_image_source") or meta.get("image_source") or "").strip()
    bottom_source = str(meta.get("korea_bottom_shot_source") or meta.get("bottom_shot_source") or "").strip()
    static_latest = _ADMIN_MISSING
    if image_source:
        static_latest = "예" if "static" in image_source.lower() or "fallback" in image_source.lower() else "아니오"
    elif bottom_source:
        static_latest = "예" if "fixed_105936" in bottom_source or "fallback" in bottom_source else "아니오"
    generated_used = _ADMIN_MISSING
    if meta.get("run_specific_images") is True or meta.get("generated_image_path") or meta.get("customer_top_image_path"):
        generated_used = "예"
    elif meta.get("run_specific_images") is False:
        generated_used = "아니오"
    return {
        "top_image_source": _panel_value(
            meta,
            "customer_image_source",
            "image_source",
            "top_shot_image_source",
            default=_ADMIN_NONE,
        ),
        "bottom_image_source": _panel_value(
            meta,
            "korea_bottom_shot_source",
            "bottom_shot_source",
            default=_ADMIN_NONE,
        ),
        "top_image_path": _panel_value(
            meta,
            "generated_image_path_watermarked",
            "generated_image_path",
            "customer_top_image_path",
            default=_ADMIN_NONE,
        ),
        "bottom_image_path": _panel_value(
            meta,
            "korea_bottom_shot_path",
            "bottom_shot_image_path",
            "customer_bottom_image_path",
            default=_ADMIN_NONE,
        ),
        "top_cid_present": "예" if top_cid not in (_ADMIN_NONE, _ADMIN_MISSING, "") else "아니오",
        "bottom_cid_present": "예" if bottom_cid not in (_ADMIN_NONE, _ADMIN_MISSING, "") else "아니오",
        "top_cid": top_cid,
        "bottom_cid": bottom_cid,
        "mime_inline_part_count": mime_count,
        "static_latest_used": static_latest,
        "generated_image_path_used": generated_used,
    }


def build_customer_delivery_admin_panel(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only customer delivery evidence for admin UI (no SMTP / no env reads)."""
    status_code, grade_label, grade_detail = _panel_delivery_grade(meta)
    recipients = _panel_recipients(meta)
    recipient_count_raw = meta.get("customer_email_recipient_count")
    if recipient_count_raw in (None, ""):
        recipient_count_raw = meta.get("customer_recipient_count")
    if recipient_count_raw in (None, ""):
        recipient_count = str(len(recipients)) if recipients else _ADMIN_MISSING
    else:
        recipient_count = str(recipient_count_raw)
    sent_at = _panel_value(
        meta,
        "customer_sent_at",
        "customer_delivery_completed_at",
        default=_ADMIN_MISSING,
    )
    return {
        "status_code": status_code,
        "status_grade": grade_label,
        "status_detail": grade_detail,
        "status_label_ko": customer_delivery_status_label_ko(status_code),
        "sent_at_kst": sent_at,
        "recipient_count": recipient_count,
        "recipients_masked": (
            recipients
            if meta.get("customer_email_recipients_masked") or meta.get("customer_recipients_masked")
            else [mask_customer_email(addr) for addr in recipients]
        ),
        "smtp_accepted": _panel_smtp_accepted(meta),
        "smtp_message_id": _panel_value(
            meta,
            "smtp_message_id",
            "customer_delivery_message_id",
            "message_id",
            default=_ADMIN_MISSING,
        ),
        "failure_reason_code": (
            _ADMIN_NONE
            if status_code in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED
            else _panel_value(
                meta,
                "customer_delivery_error_code",
                default=_ADMIN_NONE,
            )
        ),
        "failure_message": (
            _ADMIN_NONE
            if status_code in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED
            else _panel_value(meta, "customer_delivery_error_summary", default=_ADMIN_NONE)
        ),
        "double_send_blocked": _panel_double_send_blocked(meta),
        "mode": _panel_value(meta, "mode", "program_id", default=_ADMIN_MISSING),
        "run_id": _panel_value(meta, "run_id", default=_ADMIN_MISSING),
        "subject": _panel_value(meta, "customer_email_subject", "email_subject", default=_ADMIN_MISSING),
        "mime_html_sha256": _panel_value(meta, "customer_email_mime_html_sha256", default=_ADMIN_MISSING),
        "mime_html_bytes_len": _panel_value(meta, "customer_email_mime_html_bytes_len", default=_ADMIN_MISSING),
        "inline_image_count": str(len(meta.get("customer_email_inline_image_hashes") or []))
        if meta.get("customer_email_inline_image_hashes")
        else _ADMIN_MISSING,
        "image": _panel_image_evidence(meta),
    }


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


def _keysuri_korea_bottom_baseline_confirmed(meta: Dict[str, Any]) -> tuple[bool, str]:
    """Check fixed baseline or generated-v6 anchor metadata for Korea Bottom.

    Fixed fallback requires the legacy asset/source pair. Generated v6 requires
    the 105936 slot-0 anchor and Asset01 slot-1 continuity contract.
    """
    source = str(meta.get("bottom_shot_source") or "")
    if source == _KEYSURI_KOREA_BOTTOM_GENERATED_SOURCE:
        anchor_id = str(
            meta.get("bottom_anchor_asset_id")
            or meta.get("korea_bottom_anchor_asset_id")
            or ""
        )
        if anchor_id != _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID:
            return False, "korea_bottom_generated_anchor_id_invalid"
        if meta.get("bottom_anchor_slot") != 0:
            return False, "korea_bottom_generated_anchor_slot_invalid"
        if str(meta.get("secondary_reference_asset_id") or "") != "Asset01":
            return False, "korea_bottom_generated_secondary_reference_invalid"
        if meta.get("secondary_reference_slot") != 1:
            return False, "korea_bottom_generated_secondary_slot_invalid"
        if not bool(meta.get("bottom_shot_generated")):
            return False, "korea_bottom_generated_status_unconfirmed"
        return True, "ok"

    asset_id = str(
        meta.get("bottom_shot_asset_id") or meta.get("korea_bottom_shot_asset_id") or ""
    )
    if asset_id != _KEYSURI_KOREA_BOTTOM_BASELINE_ASSET_ID:
        return False, "korea_bottom_baseline_asset_id_missing"
    if source not in _KEYSURI_KOREA_BOTTOM_APPROVED_SOURCES:
        return False, "korea_bottom_baseline_source_unconfirmed"
    return True, "ok"


def can_approve_customer_send(meta: Dict[str, Any], *, has_email_html: bool) -> tuple[bool, str]:
    mode = str(meta.get("mode") or "")
    if mode not in APPROVABLE_MODES:
        return False, "unsupported_mode"
    if mode == "keysuri_korea_tech":
        # Korea delivery requires 041559 bottom QA baseline metadata confirmed.
        # If bottom image metadata is absent or wrong, delivery is blocked.
        baseline_ok, baseline_err = _keysuri_korea_bottom_baseline_confirmed(meta)
        if not baseline_ok:
            return False, baseline_err
        from keysuri_customer_delivery import customer_delivery_config_ready

        ready, err = customer_delivery_config_ready()
        if not ready:
            return False, err
    if mode == "keysuri_global_tech":
        from keysuri_customer_delivery import customer_delivery_config_ready

        ready, err = customer_delivery_config_ready()
        if not ready:
            return False, err
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


def approve_run(
    run_id: str,
    note: str = "",
    *,
    approval_audit: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[Dict[str, Any]], str]:
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
    from email_sender import last_send_diagnostic, last_send_trace, reset_last_send_state

    reset_last_send_state()

    mode = str(meta.get("mode") or "")
    keysuri_delivery_result = None
    if mode == "today_genie":
        from today_geenee_customer_delivery import send_today_geenee_customer_final_email

        send_ok = send_today_geenee_customer_final_email(saved_html, meta)
    elif mode in ("keysuri_global_tech", "keysuri_korea_tech"):
        from keysuri_customer_delivery import (
            last_keysuri_delivery_result,
            send_keysuri_customer_final_email,
        )

        send_ok = send_keysuri_customer_final_email(saved_html, meta)
        keysuri_delivery_result = last_keysuri_delivery_result()
    else:
        return None, "unsupported_mode"

    send_trace = last_send_trace()
    send_diagnostic = last_send_diagnostic()
    customer_subject = str(send_trace.get("subject") or "")
    customer_preheader = ""
    if keysuri_delivery_result is not None:
        result_subject = str(getattr(keysuri_delivery_result, "customer_email_subject", "") or "").strip()
        if result_subject:
            customer_subject = result_subject
        customer_preheader = str(
            getattr(keysuri_delivery_result, "customer_email_preheader", "") or ""
        ).strip()

    if not send_ok:
        diag = sanitize_delivery_error_summary(send_diagnostic or "Customer email send failed.")
        delivery_fields = build_customer_email_delivery_fields(
            attempted=True,
            send_ok=False,
            subject=customer_subject,
            trace=send_trace,
            diagnostic=diag,
            preheader=customer_preheader,
            repo_root=repo_root(),
        )

        def _fail(m: Dict[str, Any]) -> None:
            _record_customer_delivery_failure(
                m,
                attempted_at=attempted_at,
                error_summary=diag,
                error_code="send_failed",
            )
            m.update(delivery_fields)

        update_run_artifact(run_id, _fail)
        return None, "send_failed"

    cleaned_note = note.strip()
    sent_ts = now_kst_iso()
    delivery_fields = build_customer_email_delivery_fields(
        attempted=True,
        send_ok=True,
        subject=customer_subject,
        trace=send_trace,
        diagnostic=send_diagnostic,
        preheader=customer_preheader,
        sent_at_kst=sent_ts,
        repo_root=repo_root(),
    )

    def _mut(m: Dict[str, Any]) -> None:
        m["owner_review_status"] = "approved"
        m["owner_reviewed_at"] = sent_ts
        m["approved_at"] = sent_ts
        m["owner_review_note"] = cleaned_note or None
        m["approved_by"] = "owner_admin"
        m["customer_delivery_reason"] = "owner_approved"
        m["customer_sent_at"] = sent_ts
        _record_customer_delivery_smtp_accepted(m, completed_at=sent_ts)
        m.update(delivery_fields)
        if approval_audit:
            for key, value in approval_audit.items():
                m[key] = value

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


# ---------------------------------------------------------------------------
# Beta customer recipient config (GCS-backed, admin-managed)
# ---------------------------------------------------------------------------

_BETA_RECIPIENTS_GCS_KEY = "admin_config/customer_recipients.json"
_BETA_RECIPIENTS_LOCAL_PATH = "output/admin_config/customer_recipients.json"

# Intentionally permissive but injection-safe: local@domain pattern.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _is_valid_email(addr: str) -> bool:
    """Return True if *addr* passes basic RFC-5321-inspired validation.

    Rejects blank, newlines, commas, angle brackets, and anything that would
    allow header injection.
    """
    if not addr or not isinstance(addr, str):
        return False
    stripped = addr.strip()
    if not stripped:
        return False
    # Newline/header-injection guard
    if "\n" in stripped or "\r" in stripped:
        return False
    # Comma-packed or angle-bracket forms blocked
    if "," in stripped or "<" in stripped or ">" in stripped:
        return False
    return bool(_EMAIL_RE.match(stripped))


def _beta_recipients_local_path() -> Path:
    p = repo_root() / _BETA_RECIPIENTS_LOCAL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_beta_recipient_config() -> Dict[str, Any]:
    """Load admin-managed beta recipient config.

    GCS backend is used when GENIE_ADMIN_ARTIFACT_BUCKET / GENIE_ARTIFACT_BUCKET
    is configured.  On missing config (key not found or parse error) returns an
    empty-recipients dict — callers treat this as "no admin recipients".
    On GCS read *error* (network, auth) also returns empty — fails closed to
    env-only baseline.

    The returned dict carries ``load_ok``: True for a genuinely missing config
    (first-time use) or a clean read, False when the backing store could not be
    read or parsed. Mutation helpers must refuse to write when ``load_ok`` is
    False so a transient read failure cannot silently overwrite existing
    recipients with a partial list.
    """
    empty: Dict[str, Any] = {
        "recipients": [],
        "disabled_recipients": [],
        "updated_at": "",
        "updated_by": "admin",
        "version": 1,
        "load_ok": True,
    }

    def _error_empty() -> Dict[str, Any]:
        err = dict(empty)
        err["load_ok"] = False
        return err

    try:
        if _uses_gcs_backend():
            raw = _gcs_download_text(_BETA_RECIPIENTS_GCS_KEY)
        else:
            p = _beta_recipients_local_path()
            raw = p.read_text(encoding="utf-8") if p.is_file() else None
    except Exception:
        return _error_empty()
    if raw is None:
        return dict(empty)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _error_empty()
    if not isinstance(data, dict):
        return _error_empty()
    # Normalise fields
    recipients = [str(r).strip().lower() for r in data.get("recipients", []) if str(r).strip()]
    disabled = [str(r).strip().lower() for r in data.get("disabled_recipients", []) if str(r).strip()]
    return {
        "recipients": recipients,
        "disabled_recipients": disabled,
        "updated_at": str(data.get("updated_at") or ""),
        "updated_by": str(data.get("updated_by") or "admin"),
        "version": int(data.get("version") or 1),
        "load_ok": True,
    }


def save_beta_recipient_config(
    recipients: List[str],
    *,
    disabled_recipients: Optional[List[str]] = None,
    updated_by: str = "admin",
) -> None:
    """Persist admin-managed beta recipient config to GCS (or local fallback)."""
    payload = {
        "recipients": [str(r).strip().lower() for r in recipients],
        "disabled_recipients": [str(r).strip().lower() for r in (disabled_recipients or [])],
        "updated_at": now_kst_iso(),
        "updated_by": updated_by,
        "version": 1,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if _uses_gcs_backend():
        _gcs_upload_text(_BETA_RECIPIENTS_GCS_KEY, text, content_type="application/json")
    else:
        p = _beta_recipients_local_path()
        p.write_text(text, encoding="utf-8")


def resolve_customer_recipients() -> Dict[str, Any]:
    """Return merged customer recipient list from env baseline + admin config.

    Result keys:
      final_recipients  – ordered, deduped, validated list to use for sending
      env_recipients    – addresses from GENIE_CUSTOMER_EMAIL_TO
      admin_recipients  – validated addresses from admin config (non-disabled)
      invalid_entries   – rejected addresses with reason
      source_summary    – human-readable provenance string
      admin_config_ok   – True if config loaded without error
    """
    from email_sender import parse_customer_to_addrs

    env_list: List[str] = [a.strip().lower() for a in parse_customer_to_addrs() if a.strip()]

    cfg = load_beta_recipient_config()
    admin_list_raw: List[str] = cfg.get("recipients", [])
    disabled_set = {a.strip().lower() for a in cfg.get("disabled_recipients", []) if a.strip()}

    admin_valid: List[str] = []
    invalid: List[Dict[str, str]] = []
    for addr in admin_list_raw:
        norm = addr.strip().lower()
        if norm in disabled_set:
            continue
        if not _is_valid_email(norm):
            invalid.append({"email": norm, "reason": "invalid_format"})
            continue
        admin_valid.append(norm)

    # Validate env entries too (warn but keep — env is operator-controlled)
    env_valid: List[str] = []
    for addr in env_list:
        if _is_valid_email(addr):
            env_valid.append(addr)
        else:
            invalid.append({"email": addr, "reason": "invalid_format_env"})

    # Deduplicate: env first, then admin additions
    seen: set = set()
    final: List[str] = []
    for addr in env_valid + admin_valid:
        if addr not in seen:
            seen.add(addr)
            final.append(addr)

    env_count = len(env_valid)
    admin_count = len(admin_valid)
    parts = []
    if env_count:
        parts.append(f"env({env_count})")
    if admin_count:
        parts.append(f"admin_config({admin_count})")
    source_summary = "+".join(parts) if parts else "empty"

    return {
        "final_recipients": final,
        "env_recipients": env_valid,
        "admin_recipients": admin_valid,
        "invalid_entries": invalid,
        "source_summary": source_summary,
        "admin_config_ok": True,
    }


def add_beta_recipient(email: str) -> tuple[bool, str]:
    """Add *email* to the admin-managed beta recipient list.

    Returns (ok, error_message).  Does not send email.
    """
    norm = str(email or "").strip().lower()
    if not norm:
        return False, "empty_email"
    if not _is_valid_email(norm):
        return False, "invalid_format"
    cfg = load_beta_recipient_config()
    if not cfg.get("load_ok", True):
        # Read failed/corrupt: refuse to write so we never clobber existing data.
        return False, "config_unavailable"
    current = [str(r).strip().lower() for r in cfg.get("recipients", [])]
    if norm in current:
        return False, "already_exists"
    current.append(norm)
    save_beta_recipient_config(current, disabled_recipients=cfg.get("disabled_recipients", []))
    return True, ""


def remove_beta_recipient(email: str) -> tuple[bool, str]:
    """Remove *email* from the admin-managed beta recipient list.

    Returns (ok, error_message).  Does not send email.
    """
    norm = str(email or "").strip().lower()
    if not norm:
        return False, "empty_email"
    cfg = load_beta_recipient_config()
    if not cfg.get("load_ok", True):
        # Read failed/corrupt: refuse to write so we never clobber existing data.
        return False, "config_unavailable"
    current = [str(r).strip().lower() for r in cfg.get("recipients", [])]
    if norm not in current:
        return False, "not_found"
    updated = [r for r in current if r != norm]
    save_beta_recipient_config(updated, disabled_recipients=cfg.get("disabled_recipients", []))
    return True, ""
