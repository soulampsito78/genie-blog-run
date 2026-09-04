"""Run artifacts for owner admin review and reissue tracking (local or GCS)."""
from __future__ import annotations

import json
import hashlib
import heapq
import itertools
import os
import re
import secrets
import threading
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from delivery_trace import build_customer_email_delivery_fields, sanitize_email_diagnostic
from product_surface_contract import PRODUCT_REVIEW_REQUIRED
from sent_news_log_store import append_or_upsert_sent_news

_RUN_ID_MODES = (
    "today_genie",
    "tomorrow_genie",
    "keysuri_global_tech",
    "keysuri_korea_tech",
)
_RUN_ID_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_(today_genie|tomorrow_genie|keysuri_global_tech|keysuri_korea_tech)_[a-f0-9]{8}$"
)

# Owner Admin collection reads must stay small even when the durable bucket has
# accumulated years of run artifacts.  GCS has no reverse-order listing, so we
# inspect bounded recent date partitions (refined to hour/minute on overflow)
# and select run ids before downloading any JSON body. The per-run
# ``.summary.json`` object contains only
# fields needed by list/status projections; full artifacts remain detail-only.
ADMIN_RUN_LIST_MAX_LIMIT = 200
ADMIN_RUN_LIST_GCS_SCAN_MAX = 5_000
ADMIN_RUN_LIST_MONTH_LOOKBACK = 24
ADMIN_RUN_LIST_PREFIX_SCAN_MAX = 1_000
ADMIN_RUN_LIST_SUMMARY_SUFFIX = ".summary.json"
ADMIN_RUN_MEMORY_SUFFIX = ".memory.json"
ADMIN_EMAIL_HTML_MAX_BYTES = 6 * 1024 * 1024
ADMIN_RUN_MEMORY_MAX_BYTES = 64 * 1024
MAX_CUSTOMER_DELIVERY_EVENTS_PER_RUN = 32

_RUN_MEMORY_STAGE_NAMES = frozenset(
    {
        "request_start",
        "after_source_selection",
        "after_model_generation",
        "after_render",
        "after_image_generation",
        "before_owner_smtp",
        "request_end",
    }
)
_RUN_MEMORY_SOURCES = frozenset(
    {
        "unavailable",
        "proc_status",
        "resource_getrusage",
        "upstream:proc_status",
        "upstream:resource_getrusage",
    }
)
_RUN_MEMORY_NOT_REACHED_REASONS = frozenset(
    {
        "not_reached_due_to_validation_block",
        "not_reached_before_image_generation",
        "not_reached_due_to_prior_failure",
        "not_reached_due_to_exception",
        "not_reached_due_to_missing_image",
        "owner_review_send_gate_off",
        "send_not_requested",
    }
)
_RUN_MEMORY_IMAGE_STATUSES = frozenset(
    {"generated", "failed", "not_implemented", "not_attempted", "unknown"}
)

_RUN_LIST_SUMMARY_KEYS = (
    "run_id",
    "mode",
    "program_id",
    "created_at",
    "created_at_kst",
    "completed_at",
    "owner_reviewed_at",
    "trigger_source",
    "execution_class",
    "scheduled_slot",
    "kst_schedule_date",
    "target_date",
    "artifact_status",
    "workflow_status",
    "validation_result",
    "quality_adjudicator",
    "safety_verdict",
    "editorial_verdict",
    "terminal_issue_codes",
    "review_issue_codes",
    "repaired_issue_codes",
    "owner_delivery_behavior",
    "customer_approval_policy",
    "customer_approval_available",
    "warning_confirmation_required",
    "issue_codes",
    "validation_issue_codes",
    "email_sent",
    "smtp_attempted",
    "owner_email_delivery_status",
    "smtp_status",
    "customer_delivery_status",
    "customer_email_delivery_status",
    "customer_email_recipient_count",
    "customer_recipient_count",
    "smtp_accepted_recipient_count",
    "smtp_refused_recipient_count",
    "smtp_refused_recipients_masked",
    "customer_delivery_unknown_count",
    "customer_email_sent_at_kst",
    "customer_sent_at",
    "customer_delivery_completed_at",
    "owner_review_status",
    "customer_email_subject",
    "email_subject",
    "subject",
    "owner_email_subject",
    "briefing_subject",
    "recovery_run",
    "original_incident_id",
    "recovery_for_incident_id",
    "incident_id",
    "admin_reissue",
    "parent_run_id",
    "reissue_scope",
    "verification_mode",
    "safe_fail",
    "generated_image_path",
    "generated_image_path_watermarked",
    "customer_top_image_path",
    "run_specific_images",
    "top_image_cid",
    "deployed_revision",
    "revision",
    "runtime_revision",
    "called_gemini",
    "artifact_saved",
    "error",
    "error_code",
    "first_failed_stage",
    "final_selected_count",
    "data_collected",
)

OWNER_REVIEW_STATUSES = frozenset(
    {"pending_review", "held", "approved", "reopened", "approval_expired_manual_required"}
)
LEGACY_OWNER_REVIEW_STATUSES = frozenset({"auto_sent_after_timeout"})
REISSUE_SCOPES = frozenset({"body_only", "image_only", "body_and_image"})
EXECUTABLE_REISSUE_SCOPE = "body_and_image"
UNSUPPORTED_REISSUE_SCOPES = frozenset()
# Backward-compatibility aliases for the pre-rename scope vocabulary
# (text_only/text_and_image). Past artifacts may still carry these legacy
# values; new requests/artifacts must use body_only/image_only/body_and_image.
LEGACY_REISSUE_SCOPE_ALIASES = {
    "text_only": "body_only",
    "text_and_image": "body_and_image",
}


def normalize_reissue_scope(raw_scope: str) -> Optional[str]:
    """Map a raw scope string to the canonical contract, accepting legacy aliases.

    Returns None if the value is empty or not recognized as either a current
    canonical scope or a known legacy alias.
    """
    value = str(raw_scope or "").strip()
    if not value:
        return None
    if value in REISSUE_SCOPES:
        return value
    return LEGACY_REISSUE_SCOPE_ALIASES.get(value)


# A reissue copies the parent's grounding forward. Reissuing from a run that
# never reached a publishable state carries that run's defect into a fresh
# owner-review email, which is how the 2026-07-30 Global incident produced a
# second batch of placeholder cards.
REISSUE_PARENT_BLOCK_REASONS = frozenset(
    {
        "parent_validation_not_pass",
        "parent_run_errored",
        "parent_placeholder_content",
        "parent_not_reissuable_dry_run",
    }
)

# Fabricated "{source} 기반 AI·테크 신호 {rank}" cards — the incident signature.
_REISSUE_PARENT_PLACEHOLDER_TITLE_RE = re.compile(r"기반\s*AI[·\s]*테크\s*신호\s*\d+\s*$")


def _reissue_parent_top5_titles(parent: Dict[str, Any]) -> List[str]:
    """Every visible TOP5 title the parent would hand to a child run."""
    titles: List[str] = []
    buckets: List[Any] = [parent.get("selected_items")]
    snapshot = parent.get("regen_generated_briefing_snapshot")
    if isinstance(snapshot, dict):
        buckets.append((snapshot.get("top_5_news") or {}).get("items"))
    for bucket in buckets:
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("headline") or item.get("korean_title") or item.get("title") or ""
            ).strip()
            if title:
                titles.append(title)
    return titles


def reissue_parent_block_reason(parent: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why this run must not be used as a reissue parent, or None if eligible.

    Scope-independent: a defective parent is defective for body_only,
    image_only and body_and_image alike, because every scope inherits the
    parent's article selection.
    """
    if not isinstance(parent, dict):
        return "parent_validation_not_pass"

    if str(parent.get("validation_result") or "").strip().lower() != "pass":
        return "parent_validation_not_pass"
    if str(parent.get("error") or "").strip():
        return "parent_run_errored"
    if parent.get("admin_reissue_dry_run") or str(
        parent.get("verification_mode") or ""
    ).strip() == "no_send_verification":
        return "parent_not_reissuable_dry_run"
    for title in _reissue_parent_top5_titles(parent):
        if _REISSUE_PARENT_PLACEHOLDER_TITLE_RE.search(title):
            return "parent_placeholder_content"
    return None


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
        "NOT_SENT",
        "SUBMITTED",
        "ACCEPTED_ALL",
        "PARTIAL_REFUSAL",
        "REFUSED_ALL",
        "OUTCOME_UNKNOWN",
    }
)
_CUSTOMER_DELIVERY_SENT_OR_ACCEPTED = frozenset(
    {
        "customer_sent_after_approval",
        "sent_after_owner_approval",
        "smtp_accepted",
        "delivery_confirmed",
        "ACCEPTED_ALL",
        "PARTIAL_REFUSAL",
        "REFUSED_ALL",
        "OUTCOME_UNKNOWN",
        "SUBMITTED",
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


def gcs_summary_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ADMIN_RUN_LIST_SUMMARY_SUFFIX)


def gcs_memory_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ADMIN_RUN_MEMORY_SUFFIX)


def gcs_email_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ".email.html")


def gcs_contract_preview_object_key(run_id: str) -> str:
    return gcs_artifact_object_key(run_id, ".contract_preview.html")


_gcs_client: Any = None
_gcs_client_lock = threading.Lock()


def _uses_gcs_backend() -> bool:
    return admin_artifact_bucket_name() is not None


def _get_gcs_client() -> Any:
    global _gcs_client
    if _gcs_client is None:
        with _gcs_client_lock:
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


def _bounded_summary_value(value: Any) -> Any:
    """Keep list projections scalar and bounded; never carry source documents."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:1_000] if isinstance(value, str) else value
    if isinstance(value, (list, tuple)):
        return [
            item[:240] if isinstance(item, str) else item
            for item in value[:50]
            if isinstance(item, (str, int, float, bool)) or item is None
        ]
    return None


def build_run_artifact_list_summary(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return only metadata required by Admin/natural-run list projections."""
    summary: Dict[str, Any] = {"artifact_list_summary": True}
    for key in _RUN_LIST_SUMMARY_KEYS:
        if key not in meta:
            continue
        value = meta.get(key)
        if key == "validation_result" and isinstance(value, dict):
            nested = {
                nested_key: _bounded_summary_value(value.get(nested_key))
                for nested_key in ("status", "result", "issue_codes")
                if nested_key in value
            }
            summary[key] = nested
            continue
        bounded = _bounded_summary_value(value)
        if bounded is not None or value is None:
            summary[key] = bounded
    policy = meta.get("policy")
    if isinstance(policy, dict) and "send_email" in policy:
        summary["policy"] = {"send_email": bool(policy.get("send_email"))}
    return summary


def _write_summary_blob(run_id: str, meta: Dict[str, Any]) -> None:
    summary = build_run_artifact_list_summary(meta)
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    if _uses_gcs_backend():
        _gcs_upload_text(gcs_summary_object_key(run_id), payload, content_type="application/json")
        return
    artifact_summary_path(run_id).write_text(payload, encoding="utf-8")


def _write_json_blob(run_id: str, meta: Dict[str, Any]) -> None:
    payload = json.dumps(meta, ensure_ascii=False, indent=2)
    if _uses_gcs_backend():
        _gcs_upload_text(gcs_json_object_key(run_id), payload, content_type="application/json")
        _write_summary_blob(run_id, meta)
        return
    artifact_json_path(run_id).write_text(payload, encoding="utf-8")
    _write_summary_blob(run_id, meta)


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


def _bounded_gcs_email_blob(run_id: str) -> Any:
    """Return an exact HTML blob only after authoritative size metadata passes."""
    blob = _get_gcs_bucket().blob(gcs_email_object_key(run_id))
    try:
        if not blob.exists():
            return None
        blob.reload()
        size = int(blob.size)
    except Exception:
        # Metadata uncertainty must not turn into an unbounded body download.
        return None
    if size < 0 or size > ADMIN_EMAIL_HTML_MAX_BYTES:
        return None
    return blob


def _read_email_blob(run_id: str) -> Optional[str]:
    if _uses_gcs_backend():
        blob = _bounded_gcs_email_blob(run_id)
        if blob is None:
            return None
        expected_size = int(blob.size)
        try:
            payload = blob.download_as_bytes(
                start=0,
                end=max(0, ADMIN_EMAIL_HTML_MAX_BYTES - 1),
            )
        except Exception:
            return None
        if len(payload) != expected_size or len(payload) > ADMIN_EMAIL_HTML_MAX_BYTES:
            return None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    path = artifact_email_path(run_id)
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < 0 or size > ADMIN_EMAIL_HTML_MAX_BYTES:
        return None
    try:
        with path.open("rb") as handle:
            payload = handle.read(ADMIN_EMAIL_HTML_MAX_BYTES + 1)
    except OSError:
        return None
    if len(payload) > ADMIN_EMAIL_HTML_MAX_BYTES:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
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


def artifact_summary_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}{ADMIN_RUN_LIST_SUMMARY_SUFFIX}"


def artifact_memory_path(run_id: str) -> Path:
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    return admin_runs_dir() / f"{run_id}{ADMIN_RUN_MEMORY_SUFFIX}"


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
    if delivery_status in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED or delivery_status.upper() in {
        "SUBMITTED", "ACCEPTED_ALL", "PARTIAL_REFUSAL", "REFUSED_ALL", "OUTCOME_UNKNOWN"
    } or owner_status == "approved":
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
    prior_total = int(meta.get("customer_delivery_event_count") or len(events))
    bounded = [*events[-(MAX_CUSTOMER_DELIVERY_EVENTS_PER_RUN - 1) :], dict(event)]
    meta["customer_delivery_events"] = bounded
    meta["customer_delivery_event_count"] = prior_total + 1
    meta["customer_delivery_events_truncated"] = (
        prior_total + 1 > len(bounded)
    )


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


def run_email_html_exists(run_id: str) -> bool:
    """Check exact HTML object metadata without downloading the HTML body."""
    if not validate_run_id(run_id):
        return False
    if _uses_gcs_backend():
        return _bounded_gcs_email_blob(run_id) is not None
    try:
        size = artifact_email_path(run_id).stat().st_size
    except OSError:
        return False
    return 0 <= size <= ADMIN_EMAIL_HTML_MAX_BYTES


def _bounded_nonnegative_int(value: Any) -> int:
    try:
        return min(max(0, int(value or 0)), (1 << 63) - 1)
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalize_run_memory_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Allowlist bounded numeric samples plus explicit stage reachability."""
    stages_in = evidence.get("stages")
    stages: Dict[str, Dict[str, Any]] = {}
    if isinstance(stages_in, dict):
        for stage in _RUN_MEMORY_STAGE_NAMES:
            sample = stages_in.get(stage)
            if not isinstance(sample, dict):
                continue
            if sample.get("reached") is False:
                reason = str(sample.get("reason") or "not_reached")
                if reason not in _RUN_MEMORY_NOT_REACHED_REASONS:
                    reason = "not_reached_due_to_prior_failure"
                stages[stage] = {"reached": False, "reason": reason}
                continue
            rss_kib = _bounded_nonnegative_int(sample.get("rss_kib"))
            hwm_kib = max(
                rss_kib, _bounded_nonnegative_int(sample.get("hwm_kib"))
            )
            row: Dict[str, Any] = {
                "rss_kib": rss_kib,
                "hwm_kib": hwm_kib,
            }
            if sample.get("reached") is True:
                row["reached"] = True
            if stage == "after_image_generation" and sample.get("reached") is True:
                image_status = str(sample.get("image_status") or "unknown")
                row["image_status"] = (
                    image_status
                    if image_status in _RUN_MEMORY_IMAGE_STATUSES
                    else "unknown"
                )
            stages[stage] = row
    source = str(evidence.get("source") or "unavailable")[:80]
    if source not in _RUN_MEMORY_SOURCES:
        source = "unavailable"
    peak_hwm_kib = max(
        (_bounded_nonnegative_int(sample.get("hwm_kib")) for sample in stages.values()),
        default=0,
    )
    configured_limit_kib = _bounded_nonnegative_int(
        evidence.get("configured_limit_kib")
    )
    return {
        "source": source,
        "unit": "KiB",
        "stage_count": len(stages),
        "peak_hwm_kib": peak_hwm_kib,
        "configured_limit_kib": configured_limit_kib,
        "headroom_kib": (
            max(0, configured_limit_kib - peak_hwm_kib)
            if configured_limit_kib
            else 0
        ),
        "stages": stages,
    }


def save_run_memory_evidence(run_id: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Write a small sidecar; never reads or rewrites the full run artifact."""
    if not validate_run_id(run_id):
        raise ValueError("invalid run_id")
    if not isinstance(evidence, dict):
        raise TypeError("memory evidence must be an object")
    normalized = _normalize_run_memory_evidence(evidence)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if _uses_gcs_backend():
        _gcs_upload_text(
            gcs_memory_object_key(run_id), payload, content_type="application/json"
        )
    else:
        artifact_memory_path(run_id).write_text(payload, encoding="utf-8")
    return normalized


def load_run_memory_evidence(run_id: str) -> Optional[Dict[str, Any]]:
    """Load only the bounded memory sidecar, never the full run artifact."""
    if not validate_run_id(run_id):
        return None
    if _uses_gcs_backend():
        blob = _get_gcs_bucket().blob(gcs_memory_object_key(run_id))
        try:
            if not blob.exists():
                return None
            blob.reload()
            expected_size = int(blob.size)
        except Exception:
            return None
        if expected_size < 0 or expected_size > ADMIN_RUN_MEMORY_MAX_BYTES:
            return None
        try:
            payload = blob.download_as_bytes(
                start=0,
                end=max(0, ADMIN_RUN_MEMORY_MAX_BYTES - 1),
            )
        except Exception:
            return None
        if len(payload) != expected_size or len(payload) > ADMIN_RUN_MEMORY_MAX_BYTES:
            return None
    else:
        path = artifact_memory_path(run_id)
        if not path.is_file():
            return None
        try:
            expected_size = path.stat().st_size
            if expected_size < 0 or expected_size > ADMIN_RUN_MEMORY_MAX_BYTES:
                return None
            with path.open("rb") as handle:
                payload = handle.read(ADMIN_RUN_MEMORY_MAX_BYTES + 1)
        except OSError:
            return None
        if len(payload) != expected_size or len(payload) > ADMIN_RUN_MEMORY_MAX_BYTES:
            return None
    try:
        raw = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return _normalize_run_memory_evidence(data) if isinstance(data, dict) else None


def _bounded_list_blobs(bucket: Any, *, prefix: str, max_results: int):
    """Compatibility wrapper that never consumes more than ``max_results`` blobs."""
    try:
        iterator = bucket.list_blobs(prefix=prefix, max_results=max_results)
    except TypeError:  # small local fakes / older compatible clients
        iterator = bucket.list_blobs(prefix=prefix)
    return itertools.islice(iterator, max_results)


def _summary_run_id_from_object_name(name: str, prefix: str) -> tuple[str, bool]:
    if not name.startswith(prefix):
        return "", False
    stem = name[len(prefix) :]
    if stem.endswith(ADMIN_RUN_MEMORY_SUFFIX):
        return "", False
    if stem.endswith(ADMIN_RUN_LIST_SUMMARY_SUFFIX):
        run_id = stem[: -len(ADMIN_RUN_LIST_SUMMARY_SUFFIX)]
        return (run_id, True) if validate_run_id(run_id) else ("", False)
    if stem.endswith(".json"):
        run_id = stem[: -len(".json")]
        return (run_id, False) if validate_run_id(run_id) else ("", False)
    return "", False


def _read_summary_blob(blob: Any) -> Optional[Dict[str, Any]]:
    try:
        raw = blob.download_as_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _skeletal_run_list_summary(run_id: str, blob: Any = None) -> Dict[str, Any]:
    """Build a tiny legacy row from object identity without reading its JSON."""
    match = _RUN_ID_RE.match(run_id)
    mode = match.group(1) if match is not None else ""
    created_at = ""
    try:
        created_at = datetime.strptime(
            run_id[:15], "%Y%m%d_%H%M%S"
        ).replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat()
    except ValueError:
        pass
    summary: Dict[str, Any] = {
        "artifact_list_summary": True,
        "summary_source": "legacy_object_metadata",
        "summary_available": False,
        "run_id": run_id,
        "mode": mode,
        "program_id": mode,
        "artifact_status": "metadata_only",
        "customer_delivery_status": "metadata_unavailable",
    }
    if created_at:
        summary["created_at"] = created_at
        summary["created_at_kst"] = created_at
    stamp = getattr(blob, "updated", None) or getattr(blob, "time_created", None)
    try:
        summary["storage_updated_at"] = stamp.isoformat() if stamp is not None else ""
    except (AttributeError, TypeError, ValueError):
        summary["storage_updated_at"] = ""
    return summary


def _collect_recent_run_candidates_from_gcs(
    limit: int,
    *,
    cursor: str = "",
) -> tuple[Dict[str, List[Any]], int]:
    prefix = f"{admin_artifact_gcs_prefix()}/"
    bucket = _get_gcs_bucket()
    # run_id -> [summary blob, legacy full-json blob]. Listing materializes only
    # lightweight Blob metadata. Callers decide whether full JSON may be read.
    candidates: Dict[str, List[Any]] = {}
    state = {"scanned": 0}
    before_run_id = cursor if validate_run_id(cursor) else ""
    cursor_dt: Optional[datetime] = None
    if before_run_id:
        try:
            cursor_dt = datetime.strptime(before_run_id[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            cursor_dt = None

    def add_blobs(blobs: List[Any]) -> None:
        for blob in blobs:
            run_id, is_summary = _summary_run_id_from_object_name(str(blob.name), prefix)
            if not run_id or (before_run_id and run_id >= before_run_id):
                continue
            row = candidates.setdefault(run_id, [None, None])
            if is_summary:
                row[0] = blob
            else:
                row[1] = blob

    def scan_partition(
        partition_prefix: str,
        levels: tuple[int, ...],
        *,
        upper_values: tuple[int, ...] = (),
    ) -> None:
        remaining = ADMIN_RUN_LIST_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            return
        cap = min(ADMIN_RUN_LIST_PREFIX_SCAN_MAX, remaining)
        blobs = list(
            _bounded_list_blobs(bucket, prefix=partition_prefix, max_results=cap)
        )
        state["scanned"] += len(blobs)
        saturated = len(blobs) >= cap
        if not saturated or not levels or state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
            add_blobs(blobs)
            return

        # A saturated ascending GCS window may contain only the oldest objects
        # in this date partition. Refine newest-first by hour/minute/second.
        # On a cursor's own day, start at that cursor's exact time instead of
        # repeatedly materializing all newer prefixes until the global cap is
        # exhausted. The final run-id comparison still excludes the cursor and
        # disambiguates multiple runs in the same second.
        before_count = len(candidates)
        width = levels[0]
        upper = min(width - 1, upper_values[0]) if upper_values else width - 1
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
            if state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
                break
        if len(candidates) == before_count and state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
            add_blobs(blobs)

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    start_day = now.date()
    if cursor_dt is not None:
        start_day = min(start_day, cursor_dt.date())
    year, month = start_day.year, start_day.month
    for month_offset in range(ADMIN_RUN_LIST_MONTH_LOOKBACK):
        month_token = f"{year:04d}{month:02d}"
        remaining = ADMIN_RUN_LIST_GCS_SCAN_MAX - state["scanned"]
        if remaining <= 0:
            break
        cap = min(ADMIN_RUN_LIST_PREFIX_SCAN_MAX, remaining)
        month_blobs = list(
            _bounded_list_blobs(
                bucket, prefix=f"{prefix}{month_token}", max_results=cap
            )
        )
        state["scanned"] += len(month_blobs)
        saturated = len(month_blobs) >= cap
        if not saturated or state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
            add_blobs(month_blobs)
        else:
            day_upper = monthrange(year, month)[1]
            if month_offset == 0:
                day_upper = min(day_upper, start_day.day)
            before_count = len(candidates)
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
                    f"{prefix}{month_token}{day:02d}_",
                    (24, 60, 60),
                    upper_values=cursor_time_upper,
                )
                if len(candidates) >= limit or state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
                    break
            if len(candidates) == before_count and state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
                add_blobs(month_blobs)
        if len(candidates) >= limit or state["scanned"] >= ADMIN_RUN_LIST_GCS_SCAN_MAX:
            break
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return candidates, state["scanned"]


def _list_run_summaries_from_gcs(limit: int, *, cursor: str = "") -> List[Dict[str, Any]]:
    candidates, _scanned = _collect_recent_run_candidates_from_gcs(
        limit, cursor=cursor
    )

    out: List[Dict[str, Any]] = []
    for run_id in sorted(candidates, reverse=True)[:limit]:
        summary_blob, full_blob = candidates[run_id]
        summary = _read_summary_blob(summary_blob) if summary_blob is not None else None
        # Normal list GETs are summary-only and read-only. Legacy/corrupt rows
        # remain visible from object identity, but their full JSON is never
        # downloaded here. Use the explicit bounded backfill helper separately.
        out.append(summary or _skeletal_run_list_summary(run_id, full_blob))
    return out


def _local_run_id_from_json_path(path: Path) -> str:
    name = path.name
    if name.endswith(ADMIN_RUN_MEMORY_SUFFIX):
        return ""
    if name.endswith(ADMIN_RUN_LIST_SUMMARY_SUFFIX):
        run_id = name[: -len(ADMIN_RUN_LIST_SUMMARY_SUFFIX)]
    elif name.endswith(".json"):
        run_id = name[: -len(".json")]
    else:
        return ""
    return run_id if validate_run_id(run_id) else ""


def _read_local_summary(run_id: str) -> Optional[Dict[str, Any]]:
    path = artifact_summary_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_run_artifact_page(limit: int = 50, *, cursor: str = "") -> Dict[str, Any]:
    """Return one newest-first metadata page with an opaque run-id cursor."""
    bounded_limit = max(1, min(int(limit), ADMIN_RUN_LIST_MAX_LIMIT))
    valid_cursor = cursor if validate_run_id(cursor) else ""
    fetch_limit = bounded_limit + 1
    if _uses_gcs_backend():
        rows = _list_run_summaries_from_gcs(fetch_limit, cursor=valid_cursor)
    else:
        root = admin_runs_dir()
        run_ids = heapq.nlargest(
            fetch_limit,
            (
                run_id
                for path in root.glob("*.json")
                if not path.name.endswith(ADMIN_RUN_LIST_SUMMARY_SUFFIX)
                and not path.name.endswith(ADMIN_RUN_MEMORY_SUFFIX)
                and (run_id := _local_run_id_from_json_path(path))
                and (not valid_cursor or run_id < valid_cursor)
            ),
        )
        rows = []
        for run_id in run_ids:
            summary = _read_local_summary(run_id)
            rows.append(summary or _skeletal_run_list_summary(run_id))

    has_more = len(rows) > bounded_limit
    items = rows[:bounded_limit]
    return {
        "items": items,
        "limit": bounded_limit,
        "cursor": valid_cursor,
        "next_cursor": (
            str(items[-1].get("run_id") or "") if has_more and items else ""
        ),
        "has_more": has_more,
    }


def list_run_artifacts(limit: int = 50, *, cursor: str = "") -> List[Dict[str, Any]]:
    """Return bounded metadata summaries; full JSON/HTML stays detail-only."""
    return list_run_artifact_page(limit=limit, cursor=cursor)["items"]


def backfill_recent_run_list_summaries(
    limit: int = ADMIN_RUN_LIST_MAX_LIMIT,
    *,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Explicit bounded migration for recent legacy run summary sidecars.

    This helper is never called by an Admin request. Its safe default performs
    only bounded object/path discovery; ``dry_run=False`` downloads and writes
    at most ``ADMIN_RUN_LIST_MAX_LIMIT`` recent full documents.
    """
    bounded_limit = max(1, min(int(limit), ADMIN_RUN_LIST_MAX_LIMIT))
    report: Dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "limit": bounded_limit,
        "scanned_objects": 0,
        "legacy_candidates": 0,
        "written": 0,
        "errors": 0,
        "candidate_run_ids": [],
    }

    if _uses_gcs_backend():
        candidates, scanned = _collect_recent_run_candidates_from_gcs(bounded_limit)
        report["scanned_objects"] = scanned
        selected = [
            (run_id, full_blob)
            for run_id, (summary_blob, full_blob) in sorted(
                candidates.items(), reverse=True
            )[:bounded_limit]
            if summary_blob is None and full_blob is not None
        ]
        report["legacy_candidates"] = len(selected)
        report["candidate_run_ids"] = [run_id for run_id, _blob in selected]
        if dry_run:
            return report
        for run_id, full_blob in selected:
            full = _read_summary_blob(full_blob)
            if full is None:
                report["errors"] = int(report["errors"]) + 1
                continue
            try:
                _write_summary_blob(run_id, full)
            except (OSError, KeyError, TypeError, ValueError):
                report["errors"] = int(report["errors"]) + 1
                continue
            report["written"] = int(report["written"]) + 1
        report["ok"] = report["errors"] == 0
        return report

    root = admin_runs_dir()
    run_paths = heapq.nlargest(
        bounded_limit,
        (
            (run_id, path)
            for path in root.glob("*.json")
            if not path.name.endswith(ADMIN_RUN_LIST_SUMMARY_SUFFIX)
            and (run_id := _local_run_id_from_json_path(path))
        ),
        key=lambda item: item[0],
    )
    selected_paths = [
        (run_id, path)
        for run_id, path in run_paths
        if not artifact_summary_path(run_id).is_file()
    ]
    report["scanned_objects"] = len(run_paths)
    report["legacy_candidates"] = len(selected_paths)
    report["candidate_run_ids"] = [run_id for run_id, _path in selected_paths]
    if dry_run:
        return report
    for run_id, path in selected_paths:
        try:
            full = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(full, dict):
                raise TypeError("run artifact must be an object")
            _write_summary_blob(run_id, full)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            report["errors"] = int(report["errors"]) + 1
            continue
        report["written"] = int(report["written"]) + 1
    report["ok"] = report["errors"] == 0
    return report


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
    if _is_legacy_timeout_artifact(meta):
        return False, "legacy_timeout_sent"
    owner_status = str(meta.get("owner_review_status") or "pending_review")
    if owner_status == "held":
        return False, "review_held"
    delivery = str(meta.get("customer_delivery_status") or "not_sent")
    if delivery in LEGACY_CUSTOMER_DELIVERY_STATUSES:
        return False, "legacy_timeout_sent"
    canonical_delivery_blocks = {
        "SUBMITTED": "delivery_submission_pending",
        "PARTIAL_REFUSAL": "delivery_partial_refusal",
        "REFUSED_ALL": "delivery_refused_all",
        "OUTCOME_UNKNOWN": "delivery_outcome_unknown",
    }
    if delivery.upper() in canonical_delivery_blocks:
        return False, canonical_delivery_blocks[delivery.upper()]
    if owner_status == "approved":
        return False, "already_approved"
    if delivery in _CUSTOMER_DELIVERY_SENT_OR_ACCEPTED or delivery.upper() in {
        "ACCEPTED_ALL"
    }:
        return False, "customer_already_sent"
    if delivery.lower() not in ("not_sent", "", "failed"):
        return False, "customer_already_sent"
    if owner_status not in OWNER_REVIEW_STATUSES:
        return False, "invalid_owner_review_status"
    vr = str(meta.get("validation_result") or "")
    if vr == "block" or str(meta.get("artifact_status") or "") == "failed":
        return False, "not_approvable"
    if str(meta.get("customer_surface_status") or "") == PRODUCT_REVIEW_REQUIRED:
        return False, "product_surface_remediation_needed"
    if mode == "today_genie" and vr != "pass":
        return False, "review_required_remediation_needed"
    if mode in {"keysuri_global_tech", "keysuri_korea_tech"}:
        if str(meta.get("safety_verdict") or "") != "SAFE":
            return False, "keysuri_safety_not_safe"
        editorial_verdict = str(meta.get("editorial_verdict") or "")
        if editorial_verdict == "POOR":
            return False, "keysuri_editorial_poor"
        if editorial_verdict not in {"READY", "REVIEW"}:
            return False, "keysuri_editorial_unclassified"
    if not has_email_html:
        return False, "missing_email_html"
    if mode == "keysuri_korea_tech":
        # Korea delivery requires 041559 bottom QA baseline metadata confirmed.
        # Check immutable run state first so an ambiguous/previous submission is
        # always explained and blocked as a duplicate-risk condition.
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
    meta["customer_delivery_status"] = "SUBMITTED"
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


def _update_sent_news_log_after_customer_success(meta: Dict[str, Any], *, sent_at: str) -> None:
    run_id = str(meta.get("run_id") or "").strip()
    briefing_type = str(meta.get("briefing_type") or meta.get("mode") or meta.get("program_id") or "").strip()
    selected_items = meta.get("selected_items")
    required_raw = meta.get("required_count")
    if not isinstance(selected_items, list) or not selected_items:
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = "selected_items_missing"
        return
    try:
        required_count = int(required_raw)
    except (TypeError, ValueError):
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = "required_count_missing"
        return
    if required_count <= 0:
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = "required_count_missing"
        return
    if len(selected_items) < required_count:
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = "selected_items_below_required_count"
        return
    if not run_id or not briefing_type:
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = "run_id_or_briefing_type_missing"
        return
    try:
        result = append_or_upsert_sent_news(
            run_id=run_id,
            briefing_type=briefing_type,
            selected_items=selected_items,
            sent_at=sent_at,
        )
    except Exception as exc:  # noqa: BLE001 - customer send success must stand
        meta["sent_log_updated"] = False
        meta["sent_log_update_error"] = f"{type(exc).__name__}"
        return
    meta["sent_log_updated"] = bool(result.get("ok"))
    meta["sent_log_pruned"] = int(result.get("pruned_count") or 0)
    meta["sent_log_appended_count"] = int(result.get("appended_count") or 0)
    meta["sent_log_updated_count"] = int(result.get("updated_count") or 0)
    meta["sent_log_update_error"] = None


def approve_run(
    run_id: str,
    note: str = "",
    *,
    approval_snapshot_id: str = "",
    operator_id: str = "",
    approval_audit: Optional[Dict[str, Any]] = None,
    review_warning_confirmed: bool = False,
) -> tuple[Optional[Dict[str, Any]], str]:
    """Verify a frozen target, reserve one command, then submit exactly that payload."""
    meta = load_run_artifact(run_id)
    if not meta:
        return None, "not_found"

    saved_html = load_run_email_html(run_id) or ""
    ok, msg = can_approve_customer_send(meta, has_email_html=bool(saved_html.strip()))
    if not ok:
        return None, msg
    if not approval_snapshot_id or not operator_id:
        return None, "INVALID_APPROVAL_SNAPSHOT"

    from admin_approval import ApprovalTargetError, verify_approval_snapshot
    from admin_safety_store import (
        append_operator_audit,
        complete_delivery_command,
        delivery_command_id_for_snapshot,
        reserve_delivery_command,
    )

    try:
        snapshot, prepared = verify_approval_snapshot(
            snapshot_id=approval_snapshot_id,
            run_id=run_id,
            meta=meta,
            saved_html=saved_html,
            operator_id=operator_id,
        )
    except ApprovalTargetError as exc:
        append_operator_audit(
            "customer_send_blocked",
            operator_id=operator_id,
            run_id=run_id,
            result="blocked",
            reason_code=exc.code,
            related_id=approval_snapshot_id,
        )
        return None, exc.code

    if bool(snapshot.get("warning_confirmation_required")) and not bool(
        review_warning_confirmed
    ):
        append_operator_audit(
            "customer_send_blocked",
            operator_id=operator_id,
            run_id=run_id,
            result="blocked",
            reason_code="REVIEW_WARNING_CONFIRMATION_REQUIRED",
            related_id=approval_snapshot_id,
        )
        return None, "REVIEW_WARNING_CONFIRMATION_REQUIRED"

    append_operator_audit(
        "approval_confirmed",
        operator_id=operator_id,
        run_id=run_id,
        result="confirmed",
        related_id=approval_snapshot_id,
    )

    command_id = delivery_command_id_for_snapshot(approval_snapshot_id)
    command_created, _ = reserve_delivery_command(
        command_id=command_id,
        snapshot_id=approval_snapshot_id,
        run_id=run_id,
        operator_id=operator_id,
    )
    if not command_created:
        append_operator_audit(
            "customer_send_blocked",
            operator_id=operator_id,
            run_id=run_id,
            result="blocked",
            reason_code="DUPLICATE_DELIVERY_COMMAND",
            related_id=command_id,
        )
        return None, "DUPLICATE_DELIVERY_COMMAND"

    append_operator_audit(
        "customer_send_attempted",
        operator_id=operator_id,
        run_id=run_id,
        result="submitted_to_application_boundary",
        related_id=command_id,
        metadata={"target_count": len(prepared.recipients)},
    )

    attempted_at = now_kst_iso()
    def _attempt(m: Dict[str, Any]) -> None:
        _record_customer_delivery_attempt(m, attempted_at=attempted_at)
        m["approval_snapshot_id"] = approval_snapshot_id
        m["delivery_command_id"] = command_id
        m["customer_delivery_target_count"] = len(prepared.recipients)

    update_run_artifact(run_id, _attempt)
    from email_sender import last_send_diagnostic, last_send_trace, reset_last_send_state

    reset_last_send_state()

    mode = str(meta.get("mode") or "")
    keysuri_delivery_result = None
    if mode == "today_genie":
        from today_geenee_customer_delivery import send_today_geenee_customer_final_email

        send_ok = send_today_geenee_customer_final_email(
            saved_html,
            meta,
            prepared_delivery={
                "ok": True,
                "html_body": prepared.customer_html,
                "subject": prepared.subject,
                "inline_jpeg_parts": prepared.inline_jpeg_parts,
                "recipients": prepared.recipients,
            },
        )
    elif mode in ("keysuri_global_tech", "keysuri_korea_tech"):
        from keysuri_customer_delivery import (
            last_keysuri_delivery_result,
            send_keysuri_customer_final_email,
        )

        send_ok = send_keysuri_customer_final_email(
            saved_html,
            meta,
            prepared_delivery={
                "ok": True,
                "html_body": prepared.customer_html,
                "subject": prepared.subject,
                "preheader": "",
                "inline_jpeg_parts": prepared.inline_jpeg_parts,
                "recipients": prepared.recipients,
            },
        )
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

    cleaned_note = note.strip()
    sent_ts = now_kst_iso()
    traced = dict(send_trace or {})
    traced["attempted_at"] = attempted_at
    traced.setdefault("envelope_to", list(prepared.recipients))
    if send_ok:
        traced.setdefault("smtp_submission_started", True)
        traced.setdefault("smtp_submission_completed", True)
    delivery_fields = build_customer_email_delivery_fields(
        attempted=True,
        send_ok=bool(send_ok),
        subject=customer_subject or prepared.subject,
        trace=traced,
        diagnostic=send_diagnostic,
        preheader=customer_preheader,
        sent_at_kst=sent_ts,
        repo_root=repo_root(),
    )
    result_code = str(delivery_fields.get("customer_email_delivery_status") or "OUTCOME_UNKNOWN")
    complete_delivery_command(
        command_id,
        result_code=result_code,
        safe_metadata={
            "target_count": delivery_fields.get("customer_delivery_target_count"),
            "accepted_count": delivery_fields.get("customer_delivery_accepted_count"),
            "refused_count": delivery_fields.get("customer_delivery_refused_count"),
            "unknown_count": delivery_fields.get("customer_delivery_unknown_count"),
        },
    )
    append_operator_audit(
        "customer_send_result",
        operator_id=operator_id,
        run_id=run_id,
        result=result_code,
        related_id=command_id,
        metadata={
            "target_count": delivery_fields.get("customer_delivery_target_count"),
            "accepted_count": delivery_fields.get("customer_delivery_accepted_count"),
            "refused_count": delivery_fields.get("customer_delivery_refused_count"),
            "unknown_count": delivery_fields.get("customer_delivery_unknown_count"),
            "provider_exactly_once": False,
        },
    )

    def _mut(m: Dict[str, Any]) -> None:
        m["owner_review_status"] = "approved" if result_code != "NOT_SENT" else "pending_review"
        m["owner_reviewed_at"] = sent_ts
        m["approved_at"] = sent_ts
        m["owner_review_note"] = cleaned_note or None
        m["approved_by"] = "owner_admin"
        m["customer_delivery_reason"] = "owner_approved"
        m["customer_sent_at"] = sent_ts if result_code in {"ACCEPTED_ALL", "PARTIAL_REFUSAL"} else None
        m.update(delivery_fields)
        m["customer_delivery_status"] = result_code
        if result_code == "ACCEPTED_ALL":
            m["customer_delivery_legacy_status"] = "customer_sent_after_approval"
        m["approval_snapshot_id"] = approval_snapshot_id
        m["delivery_command_id"] = command_id
        m["provider_exactly_once"] = False
        m["application_duplicate_submission_block"] = True
        append_customer_delivery_event(
            m,
            {
                "status": result_code,
                "event_type": "smtp_submission_result",
                "source": "approve_run",
                "summary": (
                    "Immediate SMTP evidence recorded; inbox receipt is not confirmed."
                ),
                "at": sent_ts,
                "target_count": delivery_fields.get("customer_delivery_target_count"),
                "accepted_count": delivery_fields.get("customer_delivery_accepted_count"),
                "refused_count": delivery_fields.get("customer_delivery_refused_count"),
                "unknown_count": delivery_fields.get("customer_delivery_unknown_count"),
            },
        )
        if result_code in {"ACCEPTED_ALL", "PARTIAL_REFUSAL"}:
            _update_sent_news_log_after_customer_success(m, sent_at=sent_ts)
        if result_code == "NOT_SENT":
            _record_customer_delivery_failure(
                m,
                attempted_at=attempted_at,
                error_summary=send_diagnostic or "Customer email was not submitted.",
                error_code="send_failed",
            )
            m["customer_delivery_status"] = "NOT_SENT"
        if approval_audit:
            for key, value in approval_audit.items():
                m[key] = value

    updated = update_run_artifact(run_id, _mut)
    if result_code == "NOT_SENT":
        return None, "send_failed"
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
    """Legacy same-KST-date lookup.

    Retained for older tests/callers. Production Today natural admission must use
    ``find_today_natural_slot_completer`` / execution-class gate instead — a
    same-date QA/manual emailed artifact must not satisfy the natural slot.
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


def find_today_natural_slot_completer(
    *,
    kst_date: Optional[datetime] = None,
    scheduled_slot: str = "06:30",
    limit: int = 100,
) -> Optional[Dict[str, Any]]:
    """Return metadata for a run that legitimately completes Today's natural slot.

    Only ``execution_class=natural_scheduled`` terminal successes for the same
    KST date + canonical slot qualify. Legacy artifacts without execution_class,
    QA/manual, reissue, preview, failed, and no-send verification runs do not.
    """
    from today_genie_execution_identity import (
        PROGRAM_TODAY,
        find_natural_slot_completer,
        kst_date_str,
        normalize_scheduled_slot,
    )

    date_text = kst_date_str(kst_date)
    slot = normalize_scheduled_slot(scheduled_slot) or "06:30"
    artifacts = list_run_artifacts(limit=limit)
    match = find_natural_slot_completer(
        artifacts,
        program_id=PROGRAM_TODAY,
        kst_date=date_text,
        scheduled_slot=slot,
    )
    if match is None:
        return None
    for raw in artifacts:
        if str(raw.get("run_id") or "").strip() == match.run_id:
            return dict(raw)
    return {
        "run_id": match.run_id,
        "execution_class": match.execution_class,
        "scheduled_slot": match.scheduled_slot,
        "email_sent": match.email_sent,
        "artifact_status": match.artifact_status,
        "owner_review_status": match.terminal_status,
        "trigger_source": match.trigger_source,
        "mode": PROGRAM_TODAY,
    }


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

    # Timeout customer delivery is permanently retired on main.  Return before
    # resolving SMTP/customer config, listing GCS, downloading run JSON, or
    # loading any stored email HTML.  Keeping the historical scanner below makes
    # the legacy behavior explicit without paying for it in production.
    retired = _timeout_customer_send_retired()
    if retired:
        return {
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
            "retired": True,
            "note": "timeout customer send retired",
        }

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
        if not send_customer_timeout_draft_email(saved_html, view):
            summary["errors"] = int(summary["errors"]) + 1
            summary["error_run_ids"].append(run_id)
            continue

        summary["sent"] = int(summary["sent"]) + 1
        summary["run_ids_sent"].append(run_id)

    summary["skip_reasons"] = dict(skip_counter)
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
    version: int = 1,
) -> None:
    """Persist admin-managed beta recipient config to GCS (or local fallback)."""
    payload = {
        "recipients": [str(r).strip().lower() for r in recipients],
        "disabled_recipients": [str(r).strip().lower() for r in (disabled_recipients or [])],
        "updated_at": now_kst_iso(),
        "updated_by": updated_by,
        "version": max(1, int(version)),
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

    config_version = int(cfg.get("version") or 1)
    config_identity = {
        "env_recipients": env_valid,
        "admin_recipients": admin_valid,
        "disabled_recipients": sorted(disabled_set),
        "final_recipients": final,
        "admin_version": config_version,
    }
    config_hash = hashlib.sha256(
        json.dumps(config_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "final_recipients": final,
        "env_recipients": env_valid,
        "admin_recipients": admin_valid,
        "invalid_entries": invalid,
        "source_summary": source_summary,
        "admin_config_ok": bool(cfg.get("load_ok", True)),
        "recipient_configuration_version": f"env+admin:v{config_version}",
        "recipient_configuration_hash": config_hash,
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
    save_beta_recipient_config(
        current,
        disabled_recipients=cfg.get("disabled_recipients", []),
        version=int(cfg.get("version") or 1) + 1,
    )
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
    save_beta_recipient_config(
        updated,
        disabled_recipients=cfg.get("disabled_recipients", []),
        version=int(cfg.get("version") or 1) + 1,
    )
    return True, ""


def hold_run(run_id: str, *, note: str = "", operator_id: str = "owner_admin") -> tuple[Optional[Dict[str, Any]], str]:
    """Durably record the owner's explicit do-not-send-yet decision."""
    meta = load_run_artifact(run_id)
    if not meta:
        return None, "not_found"
    owner_status = str(meta.get("owner_review_status") or "pending_review")
    if owner_status == "held":
        return None, "already_held"
    if owner_status not in {"pending_review", "reopened"}:
        return None, "invalid_owner_review_status"
    delivery = str(meta.get("customer_delivery_status") or "not_sent").upper()
    if delivery not in {"NOT_SENT", "FAILED", ""}:
        return None, "customer_already_sent"
    ts = now_kst_iso()

    def _mut(row: Dict[str, Any]) -> None:
        row["owner_review_status"] = "held"
        row["review_held_at"] = ts
        row["review_held_by"] = operator_id
        row["review_hold_note"] = str(note or "").strip()[:500] or None

    return update_run_artifact(run_id, _mut), "ok"


def reopen_held_run(run_id: str, *, operator_id: str = "owner_admin") -> tuple[Optional[Dict[str, Any]], str]:
    """Reopen a held review without generating or mutating briefing content."""
    meta = load_run_artifact(run_id)
    if not meta:
        return None, "not_found"
    if str(meta.get("owner_review_status") or "") != "held":
        return None, "not_held"
    ts = now_kst_iso()

    def _mut(row: Dict[str, Any]) -> None:
        row["owner_review_status"] = "reopened"
        row["review_reopened_at"] = ts
        row["review_reopened_by"] = operator_id

    return update_run_artifact(run_id, _mut), "ok"
