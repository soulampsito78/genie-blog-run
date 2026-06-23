"""Kee-Suri customer-final email: premium briefing HTML + inline CID only.

Global (keysuri_global_tech) customer delivery is enabled via admin approve_run.
Korea remains blocked in admin_store until Gmail-safe customer rendering is ready.
"""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from admin_store import resolve_customer_recipients
from email_sender import parse_customer_to_addrs, send_genie_email
from keysuri_contract_preview_renderer import (
    REVIEW_CONFIRMATION_TEXT,
    REVIEW_STATE_PREVIEW_PENDING,
    REVIEW_STATE_REVIEW_PASSED,
    REVIEW_STATE_SENT_ARCHIVED,
)
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA
from keysuri_service_full_run import (
    inline_jpeg_parts_for_global_service_email,
    inline_jpeg_parts_for_korea_service_email,
    keysuri_global_service_email_cid_token,
)

logger = logging.getLogger(__name__)

_KEYSURI_MODES = frozenset({PROGRAM_GLOBAL, PROGRAM_KOREA})
_KOREA_CID_PREFIX = "keysuri_topshot_korea"
_KOREA_BOTTOM_MISSING_REASON = "korea_bottom_image_missing_for_customer_email"
_GENERATED_V6_MULTI_REF_SOURCE = "generated_v6_multi_ref"

# Reason codes for generated provenance failures.
KOREA_GENERATED_TOP_PATH_MISSING = "korea_generated_top_path_missing"
KOREA_GENERATED_BOTTOM_PATH_MISSING = "korea_generated_bottom_path_missing"
KOREA_GENERATED_STATUS_INVALID = "korea_generated_status_invalid"
KOREA_GENERATED_SOURCE_INVALID = "korea_generated_source_invalid"
KOREA_GENERATED_FILES_UNAVAILABLE = "korea_generated_files_unavailable"
KOREA_GENERATED_ARTIFACT_RESTORE_FAILED = "korea_generated_artifact_restore_failed"
KOREA_GENERATED_PERSISTENCE_MISSING = "korea_generated_persistence_missing"
KOREA_GENERATED_FALLBACK_CONFLICT = "korea_generated_fallback_conflict"

_last_korea_inline_resolve_reason: str = ""

_OWNER_ADMIN_ENTRY_RE = re.compile(
    r'<div[^>]*\bid=["\']owner-review-admin-entry["\'][^>]*>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
_RUN_ID_ADMIN_LINE_RE = re.compile(
    r'<p[^>]*>\s*run_id:\s*[^<]+</p>',
    re.IGNORECASE,
)
_ADMIN_RUN_URL_RE = re.compile(r"/admin/runs/[^\s\"'<>]+", re.IGNORECASE)
_REVIEW_BOX_RE = re.compile(
    r'<section[^>]*\bid=["\']review-confirmation-box["\'][^>]*>.*?</section>',
    re.IGNORECASE | re.DOTALL,
)
_OWNER_REVIEW_BADGE_RE = re.compile(
    r'<[^>]*\bclass=["\'][^"\']*owner-review-badge[^"\']*["\'][^>]*>.*?</[^>]+>',
    re.IGNORECASE | re.DOTALL,
)
_INTERNAL_BLOCK_RE = re.compile(
    r'<(?:div|section)[^>]*\bid=["\'](?:operation-metadata|preview-metadata|validation-result-box|compliance-checklist)["\'][^>]*>.*?</(?:div|section)>',
    re.IGNORECASE | re.DOTALL,
)
_CID_SRC_RE = re.compile(r'src=["\']cid:([^"\']+)["\']', re.IGNORECASE)

_last_delivery_result: Optional["KeysuriCustomerDeliveryResult"] = None


def last_korea_inline_resolve_reason() -> str:
    return _last_korea_inline_resolve_reason


@dataclass
class KeysuriCustomerDeliveryResult:
    sent: bool
    reason: str
    customer_delivery_status: str
    customer_email_subject: str
    cid_tokens_used: List[str] = field(default_factory=list)


def last_keysuri_delivery_result() -> Optional[KeysuriCustomerDeliveryResult]:
    return _last_delivery_result


def customer_delivery_config_ready() -> tuple[bool, str]:
    if not resolve_customer_recipients()["final_recipients"]:
        return False, "missing_customer_to"
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    if not (host and user):
        return False, "missing_smtp"
    return True, "ok"


def _kst_date_from_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if len(rid) >= 8 and rid[:8].isdigit():
        return rid[:8]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


def keysuri_korea_service_email_cid_token(run_id: str) -> str:
    return f"{_KOREA_CID_PREFIX}_{_kst_date_from_run_id(run_id)}"


def keysuri_service_email_cid_token(program_id: str, run_id: str) -> str:
    if program_id == PROGRAM_GLOBAL:
        return keysuri_global_service_email_cid_token(run_id)
    return keysuri_korea_service_email_cid_token(run_id)


def render_keysuri_customer_review_confirmation_box(*, gmail_safe: bool = False) -> str:
    text = REVIEW_CONFIRMATION_TEXT[REVIEW_STATE_SENT_ARCHIVED]
    state = REVIEW_STATE_SENT_ARCHIVED
    if gmail_safe:
        return (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="background:#eef3f8;border:1px solid #dce4ef;border-radius:12px;">'
            '<tr><td style="padding:14px 16px;text-align:center;">'
            f'<p style="margin:0;font-size:13px;line-height:1.6;color:#536274;">{html.escape(text)}</p>'
            "</td></tr></table>"
        )
    return (
        f'<section id="review-confirmation-box" class="review-box" '
        f'data-review-state="{state}">'
        f'<p class="review-confirmation-text">{html.escape(text)}</p>'
        "</section>"
    )


def _is_gmail_safe_keysuri_html(html_body: str) -> bool:
    raw = str(html_body or "")
    if not raw.strip():
        return False
    lowered = raw.lower()
    if "<style" in lowered:
        return False
    return 'role="presentation"' in lowered and "cid:keysuri_topshot_global_" in lowered


def _finalize_gmail_global_customer_review_state(html_body: str) -> str:
    out = html_body
    sent_text = REVIEW_CONFIRMATION_TEXT[REVIEW_STATE_SENT_ARCHIVED]
    for state in (REVIEW_STATE_PREVIEW_PENDING, REVIEW_STATE_REVIEW_PASSED):
        pending_text = REVIEW_CONFIRMATION_TEXT[state]
        if pending_text in out:
            out = out.replace(pending_text, sent_text)
    if sent_text not in out:
        box = render_keysuri_customer_review_confirmation_box(gmail_safe=True)
        marker = "Copyright Ⓒ MirAI:ON"
        if marker in out:
            out = out.replace(marker, f"{box}\n{marker}", 1)
        else:
            out = f"{out}\n{box}"
    return out


def prepare_gmail_global_customer_final_html(saved_html: str) -> str:
    out = strip_keysuri_owner_review_controls(saved_html)
    out = _RUN_ID_ADMIN_LINE_RE.sub("", out)
    out = _ADMIN_RUN_URL_RE.sub("", out)
    out = out.replace("[운영자 검토]", "")
    out = _finalize_gmail_global_customer_review_state(out)
    return out.strip()


def strip_keysuri_owner_review_controls(html_body: str) -> str:
    if not html_body:
        return ""
    out = html_body
    out = _OWNER_ADMIN_ENTRY_RE.sub("", out)
    out = _RUN_ID_ADMIN_LINE_RE.sub("", out)
    out = _ADMIN_RUN_URL_RE.sub("", out)
    out = _OWNER_REVIEW_BADGE_RE.sub("", out)
    out = _INTERNAL_BLOCK_RE.sub("", out)
    out = _REVIEW_BOX_RE.sub("", out)
    for fragment in (
        "운영자 검수용 미리보기 · 아직 발송 전",
        "운영자 검수용",
        "아직 발송 전",
        "운영자 검수 화면 열기",
        "[운영자 검토]",
    ):
        out = out.replace(fragment, "")
    return out.strip()


def prepare_keysuri_customer_final_html(
    saved_html: str,
    *,
    meta: Dict[str, Any],
) -> str:
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode == PROGRAM_GLOBAL and _is_gmail_safe_keysuri_html(saved_html):
        html_body = prepare_gmail_global_customer_final_html(saved_html)
    else:
        html_body = strip_keysuri_owner_review_controls(saved_html)
        if not html_body.strip():
            raise ValueError("Kee-Suri customer final HTML is empty after stripping owner controls")
        review_box = render_keysuri_customer_review_confirmation_box()
        html_body = f"{html_body}\n{review_box}"
    if not html_body.strip():
        raise ValueError("Kee-Suri customer final HTML is empty after stripping owner controls")
    return html_body


def build_keysuri_customer_final_subject(meta: Dict[str, Any], saved_html: str) -> str:
    drafts_subj = ""
    if isinstance(meta.get("email_subject"), str):
        drafts_subj = meta["email_subject"].strip()
    if not drafts_subj:
        m = re.search(
            r'<h1[^>]*class=["\'][^"\']*hero-title[^"\']*["\'][^>]*>([^<]+)</h1>',
            saved_html or "",
            re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r"<h1[^>]*>([^<]+)</h1>",
                saved_html or "",
                re.IGNORECASE,
            )
        if m:
            drafts_subj = m.group(1).strip()
    if not drafts_subj:
        mode = str(meta.get("mode") or meta.get("program_id") or "")
        drafts_subj = "키수리 글로벌 테크 브리핑" if mode == PROGRAM_GLOBAL else "키수리 코리아 테크 브리핑"
    for prefix in ("[운영자 검토]", "[KEYSURI test]", "[키수리 브리핑]"):
        if drafts_subj.startswith(prefix):
            drafts_subj = drafts_subj.split("]", 1)[-1].strip(" -")
    return drafts_subj


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _download_keysuri_gcs_image(bucket_name: str, object_name: str, dest: Path) -> None:
    from google.cloud import storage

    dest.parent.mkdir(parents=True, exist_ok=True)
    storage.Client().bucket(bucket_name).blob(object_name).download_to_filename(str(dest))


def _is_korea_generated_v6(meta: Dict[str, Any]) -> bool:
    return str(meta.get("bottom_shot_source") or "") == _GENERATED_V6_MULTI_REF_SOURCE


def _validate_korea_generated_provenance(meta: Dict[str, Any]) -> Optional[str]:
    """Return reason code if generated provenance fields are inconsistent, else None."""
    source = str(meta.get("bottom_shot_source") or "")
    generated = meta.get("bottom_shot_generated")
    gen_status = str(meta.get("bottom_shot_generation_status") or "")
    is_generated_source = source == _GENERATED_V6_MULTI_REF_SOURCE

    if is_generated_source and generated is not True:
        return KOREA_GENERATED_FALLBACK_CONFLICT
    if is_generated_source and gen_status and gen_status != "generated":
        return KOREA_GENERATED_STATUS_INVALID
    if generated is True and not is_generated_source:
        return KOREA_GENERATED_SOURCE_INVALID
    return None


def _try_restore_keysuri_from_gcs(
    bucket: str,
    gcs_object: str,
    dest: Path,
    *,
    download_fn=None,
) -> bool:
    """Try to download a single image from GCS. Returns True on success."""
    downloader = download_fn or _download_keysuri_gcs_image
    try:
        downloader(bucket, gcs_object, dest)
    except Exception:
        logger.exception("keysuri GCS image restore failed: gs://%s/%s", bucket, gcs_object)
        return False
    return dest.is_file()


def _resolve_korea_generated_inline_parts(
    meta: Dict[str, Any],
    run_id: str,
    *,
    download_fn=None,
) -> Tuple[Optional[List[Tuple[str, str, str]]], str]:
    """Resolve Korea generated Top+Bottom inline parts with GCS restore fallback.

    Never falls back to fixed_105936. Returns (parts, reason_code) where
    reason_code is empty string on success.
    """
    global _last_korea_inline_resolve_reason

    conflict = _validate_korea_generated_provenance(meta)
    if conflict:
        _last_korea_inline_resolve_reason = conflict
        return None, conflict

    bucket = str(meta.get("korea_generated_image_gcs_bucket") or "").strip()
    repo = _repo_root()
    safe_run_id = run_id or "unknown_run"

    top_path = _resolve_generated_image_path(meta)
    if top_path is None:
        top_gcs = str(meta.get("korea_generated_top_gcs_object") or "").strip()
        if not bucket or not top_gcs:
            reason = KOREA_GENERATED_PERSISTENCE_MISSING
            _last_korea_inline_resolve_reason = reason
            return None, reason
        restore_top = (
            repo / "output" / "admin_runs" / "keysuri_service_assets"
            / f"{safe_run_id}_restored_korea_top.jpg"
        )
        if not _try_restore_keysuri_from_gcs(bucket, top_gcs, restore_top, download_fn=download_fn):
            reason = KOREA_GENERATED_ARTIFACT_RESTORE_FAILED
            _last_korea_inline_resolve_reason = reason
            return None, reason
        top_path = restore_top

    bottom_path = _resolve_korea_bottom_image_path(meta)
    if bottom_path is None:
        bottom_gcs = str(meta.get("korea_generated_bottom_gcs_object") or "").strip()
        if not bucket or not bottom_gcs:
            reason = KOREA_GENERATED_PERSISTENCE_MISSING
            _last_korea_inline_resolve_reason = reason
            return None, reason
        restore_bottom = (
            repo / "output" / "admin_runs" / "keysuri_service_assets"
            / f"{safe_run_id}_restored_korea_bottom.jpg"
        )
        if not _try_restore_keysuri_from_gcs(
            bucket, bottom_gcs, restore_bottom, download_fn=download_fn
        ):
            reason = KOREA_GENERATED_ARTIFACT_RESTORE_FAILED
            _last_korea_inline_resolve_reason = reason
            return None, reason
        bottom_path = restore_bottom

    parts = inline_jpeg_parts_for_korea_service_email(
        top_path, run_id, bottom_image_path=bottom_path
    )
    _last_korea_inline_resolve_reason = "korea_generated_images_resolved"
    return parts, ""


def _resolve_generated_image_path(meta: Dict[str, Any]) -> Optional[Path]:
    repo = _repo_root()
    rel = str(meta.get("generated_image_path") or "").strip()
    if not rel:
        return None
    path = (repo / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    return path if path.is_file() else None


def _resolve_korea_bottom_image_path(meta: Dict[str, Any]) -> Optional[Path]:
    """Resolve Korea bottom shot path from artifact metadata."""
    repo = _repo_root()
    for key in ("korea_bottom_shot_path", "bottom_shot_image_path"):
        rel = str(meta.get(key) or "").strip()
        if rel:
            path = (repo / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
            if path.is_file():
                return path
    return None


def _cid_tokens_from_html(saved_html: str) -> List[str]:
    return [m.group(1).strip() for m in _CID_SRC_RE.finditer(saved_html or "") if m.group(1).strip()]


def resolve_keysuri_inline_jpeg_parts(
    saved_html: str,
    meta: Dict[str, Any],
    *,
    download_fn=None,
) -> Optional[List[Tuple[str, str, str]]]:
    """Resolve inline JPEG parts from generated service_full_run artifact metadata.

    For Korea generated_v6_multi_ref artifacts, uses strict provenance validation and
    GCS restore fallback. Never silently falls back to fixed_105936 for generated artifacts.
    """
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode not in _KEYSURI_MODES:
        return None
    if not meta.get("service_full_run"):
        return None
    run_id = str(meta.get("run_id") or "").strip()

    if mode == PROGRAM_KOREA and _is_korea_generated_v6(meta):
        parts, _ = _resolve_korea_generated_inline_parts(meta, run_id, download_fn=download_fn)
        return parts

    image_path = _resolve_generated_image_path(meta)
    if image_path is None:
        return None
    if mode == PROGRAM_GLOBAL:
        return inline_jpeg_parts_for_global_service_email(image_path, run_id)
    # Korea fixed_105936_fallback: both Top and Bottom must be present locally.
    # If Bottom is missing the HTML will have a broken cid:keysuri_bottomshot_korea_*
    # reference, so we block rather than silently omit.
    bottom_path = _resolve_korea_bottom_image_path(meta)
    if bottom_path is None:
        return None
    return inline_jpeg_parts_for_korea_service_email(image_path, run_id, bottom_image_path=bottom_path)


def send_keysuri_customer_final_email(
    saved_html: str,
    meta: Dict[str, Any],
) -> bool:
    global _last_delivery_result
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    subject = build_keysuri_customer_final_subject(meta, saved_html)

    ready, err = customer_delivery_config_ready()
    if not ready:
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason=err,
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
        )
        logger.warning("send_keysuri_customer_final_email: blocked (%s)", err)
        return False

    if mode not in _KEYSURI_MODES:
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason="unsupported_mode",
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
        )
        return False

    try:
        html_body = prepare_keysuri_customer_final_html(saved_html, meta=meta)
    except ValueError as exc:
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason=str(exc),
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
        )
        logger.warning("send_keysuri_customer_final_email: %s", exc)
        return False

    inline_parts = resolve_keysuri_inline_jpeg_parts(saved_html, meta)
    if not inline_parts:
        if mode == PROGRAM_KOREA and _is_korea_generated_v6(meta):
            # generated_v6_multi_ref: use the specific reason set during resolution.
            reason = _last_korea_inline_resolve_reason or KOREA_GENERATED_FILES_UNAVAILABLE
        elif mode == PROGRAM_KOREA and _resolve_generated_image_path(meta) is not None:
            reason = _KOREA_BOTTOM_MISSING_REASON
        else:
            reason = "missing_generated_inline_image"
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason=reason,
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
        )
        logger.warning("send_keysuri_customer_final_email: %s", reason)
        return False

    cid_tokens = [row[1] for row in inline_parts] or _cid_tokens_from_html(saved_html)
    customer_to = resolve_customer_recipients()["final_recipients"]
    os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
    sent = send_genie_email(
        html_body,
        subject,
        inline_jpeg_parts=inline_parts,
        attachment_jpeg_parts=[],
        to_addrs_override=customer_to,
    )
    _last_delivery_result = KeysuriCustomerDeliveryResult(
        sent=bool(sent),
        reason="ok" if sent else "smtp_send_failed",
        customer_delivery_status="smtp_accepted" if sent else "not_sent",
        customer_email_subject=subject,
        cid_tokens_used=list(cid_tokens),
    )
    return bool(sent)
