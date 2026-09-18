"""Kee-Suri customer-final email: premium briefing HTML + inline CID only.

Global (keysuri_global_tech) customer delivery is enabled via admin approve_run.
Korea remains blocked in admin_store until Gmail-safe customer rendering is ready.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from admin_store import (
    _get_gcs_client,
    admin_artifact_bucket_name,
    resolve_customer_recipients,
)
from customer_review_confirmation import (
    HUMAN_OWNER,
    PRE_SEND_REVIEWED,
    customer_review_confirmation,
)
from email_sender import parse_customer_to_addrs, send_genie_email
from keysuri_email_identity import build_keysuri_customer_subject, sanitize_preheader_text
from keysuri_contract_preview_renderer import (
    PREHEADER_STYLE,
    REVIEW_CONFIRMATION_TEXT,
    REVIEW_STATE_PREVIEW_PENDING,
    REVIEW_STATE_REVIEW_PASSED,
    REVIEW_STATE_SENT_ARCHIVED,
)
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA
from keysuri_service_full_run import (
    _global_top_image_gcs_object,
    _writable_keysuri_service_assets_dir,
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

# Reason codes for the Global top image when the local generated file is gone
# (the Cloud Run instance that generated it no longer exists) and the only
# remaining source is this run's durably persisted GCS object.
GLOBAL_TOP_PERSISTENCE_MISSING = "global_top_image_persistence_missing"
GLOBAL_TOP_REFERENCE_NOT_RUN_BOUND = "global_top_image_reference_not_run_bound"
GLOBAL_TOP_EXPECTED_HASH_MISSING = "global_top_image_expected_hash_missing"
GLOBAL_TOP_RESTORE_FAILED = "global_top_image_gcs_restore_failed"
GLOBAL_TOP_RESTORE_HASH_MISMATCH = "global_top_image_restored_hash_mismatch"
GLOBAL_TOP_RESTORED_FROM_GCS = "global_top_image_restored_from_gcs"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_last_korea_inline_resolve_reason: str = ""
_last_global_inline_resolve_reason: str = ""

_OWNER_ADMIN_ENTRY_RE = re.compile(
    r'<div[^>]*\bid=["\']owner-review-admin-entry["\'][^>]*>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
_RUN_ID_ADMIN_LINE_RE = re.compile(
    r'<p[^>]*>\s*run_id:\s*[^<]+</p>',
    re.IGNORECASE,
)
from auto_remediation import strip_auto_remediation_notice

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
# Owner-only "이미지 재발행" banner injected on image_only reissue. It is delimited
# by HTML comment sentinels so it can be removed cleanly before customer send.
_IMAGE_ONLY_REISSUE_MARKER_RE = re.compile(
    r'<!--image-only-reissue-marker-start-->.*?<!--image-only-reissue-marker-end-->',
    re.IGNORECASE | re.DOTALL,
)
# This REVIEW warning belongs to the owner email and approval UI, never the
# prepared customer-final payload. The producer emits no nested <div> here.
_REVIEW_WARNING_PANEL_RE = re.compile(
    r'<div[^>]*\bdata-keysuri-review-warning=["\']true["\'][^>]*>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
_CID_SRC_RE = re.compile(r'src=["\']cid:([^"\']+)["\']', re.IGNORECASE)

_last_delivery_result: Optional["KeysuriCustomerDeliveryResult"] = None


def last_korea_inline_resolve_reason() -> str:
    return _last_korea_inline_resolve_reason


def last_global_inline_resolve_reason() -> str:
    return _last_global_inline_resolve_reason


@dataclass
class KeysuriCustomerDeliveryResult:
    sent: bool
    reason: str
    customer_delivery_status: str
    customer_email_subject: str
    customer_email_preheader: str = ""
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


def render_keysuri_customer_review_confirmation_box(
    *,
    gmail_safe: bool = False,
    approval_source: str = HUMAN_OWNER,
) -> str:
    """Render source-specific pre-submit copy for a customer payload.

    The archival state is retained for historical owner surfaces, but an email
    being prepared for provider handoff must not state that it was sent already.
    """
    state, text = customer_review_confirmation(
        approval_source=approval_source,
        display_state=PRE_SEND_REVIEWED,
    )
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
        f'data-review-state="{state}" data-review-source="{approval_source}">'
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


def _finalize_gmail_global_customer_review_state(
    html_body: str,
    *,
    approval_source: str = HUMAN_OWNER,
) -> str:
    out = html_body
    _, confirmation_text = customer_review_confirmation(
        approval_source=approval_source,
        display_state=PRE_SEND_REVIEWED,
    )
    # Existing owner-preview artifacts can contain any historical review state.
    # A newly prepared payload is pre-submit and is rebuilt with the selected
    # source rather than inheriting a human or "already sent" attestation.
    for state in (
        REVIEW_STATE_PREVIEW_PENDING,
        REVIEW_STATE_REVIEW_PASSED,
        REVIEW_STATE_SENT_ARCHIVED,
    ):
        old_text = REVIEW_CONFIRMATION_TEXT[state]
        if old_text in out:
            out = out.replace(old_text, confirmation_text)
    if confirmation_text not in out:
        box = render_keysuri_customer_review_confirmation_box(
            gmail_safe=True,
            approval_source=approval_source,
        )
        marker = "Copyright Ⓒ MirAI:ON"
        if marker in out:
            out = out.replace(marker, f"{box}\n{marker}", 1)
        else:
            out = f"{out}\n{box}"
    return out


def prepare_gmail_global_customer_final_html(
    saved_html: str,
    *,
    approval_source: str = HUMAN_OWNER,
) -> str:
    out = strip_keysuri_owner_review_controls(saved_html)
    out = _RUN_ID_ADMIN_LINE_RE.sub("", out)
    out = _ADMIN_RUN_URL_RE.sub("", out)
    out = out.replace("[운영자 검토]", "")
    out = _finalize_gmail_global_customer_review_state(out, approval_source=approval_source)
    return out.strip()


def strip_keysuri_owner_review_controls(html_body: str) -> str:
    if not html_body:
        return ""
    out = html_body
    out = _OWNER_ADMIN_ENTRY_RE.sub("", out)
    out = _IMAGE_ONLY_REISSUE_MARKER_RE.sub("", out)
    out = _REVIEW_WARNING_PANEL_RE.sub("", out)
    # Owner-only 자동 교정본 header: never part of a customer surface.
    out = strip_auto_remediation_notice(out)
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
    approval_source: str = HUMAN_OWNER,
) -> str:
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode == PROGRAM_GLOBAL and _is_gmail_safe_keysuri_html(saved_html):
        html_body = prepare_gmail_global_customer_final_html(
            saved_html,
            approval_source=approval_source,
        )
    else:
        html_body = strip_keysuri_owner_review_controls(saved_html)
        if not html_body.strip():
            raise ValueError("Kee-Suri customer final HTML is empty after stripping owner controls")
        review_box = render_keysuri_customer_review_confirmation_box(
            approval_source=approval_source,
        )
        html_body = f"{html_body}\n{review_box}"
    if not html_body.strip():
        raise ValueError("Kee-Suri customer final HTML is empty after stripping owner controls")
    return html_body


def build_keysuri_customer_final_subject(meta: Dict[str, Any], saved_html: str) -> str:
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if meta.get("editorial_subject") or meta.get("email_subject"):
        editorial = build_keysuri_customer_subject(mode, meta=meta)
        if editorial:
            return editorial
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


def build_keysuri_customer_final_preheader(meta: Dict[str, Any], saved_html: str) -> str:
    explicit = str(meta.get("customer_email_preheader") or "").strip()
    if explicit:
        return sanitize_preheader_text(explicit)
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    scope = "국내" if mode == PROGRAM_KOREA else "글로벌"
    top_headline = str(meta.get("subject_top_headline") or "").strip()
    if top_headline:
        return sanitize_preheader_text(f"{scope} AI·테크 신호 브리핑 · 주요 신호: {top_headline}")
    for key in ("email_preheader", "owner_email_preheader"):
        value = str(meta.get(key) or "").strip()
        if value:
            return sanitize_preheader_text(
                value.replace("수동 검증 run · ", "").replace("검수 대기", "브리핑")
            )
    subject = build_keysuri_customer_final_subject(meta, saved_html)
    return sanitize_preheader_text(f"{scope} AI·테크 신호 브리핑 · 주요 신호: {subject}")


def _insert_hidden_preheader(html_body: str, preheader: str) -> str:
    clean = sanitize_preheader_text(preheader)
    if not clean:
        return html_body
    hidden = f'<span style="{PREHEADER_STYLE}">{html.escape(clean)}</span>'
    body_open = re.search(r"<body\b[^>]*>", html_body or "", flags=re.IGNORECASE)
    if body_open:
        idx = body_open.end()
        return f"{html_body[:idx]}{hidden}{html_body[idx:]}"
    return f"{hidden}{html_body}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _download_keysuri_gcs_image(bucket_name: str, object_name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _get_gcs_client().bucket(bucket_name).blob(object_name).download_to_filename(str(dest))


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_global_top_sha256(meta: Dict[str, Any], run_id: str) -> str:
    """The SHA256 the owner-reviewed Global top image had when it was sent.

    Persisted by ``_owner_email_inline_image_hashes``. Global carries exactly one
    inline image, so an entry is accepted only when its CID is this run's Global
    top CID (or is absent in an older artifact), and the accepted hashes must
    agree — an ambiguous set is treated as "no expected hash" and fails closed.
    """
    token = keysuri_global_service_email_cid_token(run_id) if run_id else ""
    hashes: set[str] = set()
    for row in meta.get("owner_email_inline_image_hashes") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("cid") or "").strip()
        if cid and cid != token:
            continue
        sha = str(row.get("sha256") or "").strip().lower()
        if _SHA256_HEX_RE.fullmatch(sha):
            hashes.add(sha)
    return next(iter(hashes)) if len(hashes) == 1 else ""


def _restore_global_top_image_from_gcs(
    meta: Dict[str, Any],
    run_id: str,
    *,
    download_fn=None,
) -> Tuple[Optional[Path], str]:
    """Restore this run's Global top image from its persisted GCS object.

    Used only when the local generated file is missing. Accepts bytes only from
    the exact run-bound object in the configured artifact bucket and only when
    they hash to the persisted owner-reviewed SHA256. There is no alternate
    object, no fixed image, and no unverified fallback: every other outcome
    returns a reason code and no path.
    """
    if not run_id:
        return None, GLOBAL_TOP_PERSISTENCE_MISSING
    bucket = str(meta.get("generated_image_gcs_bucket") or "").strip()
    gcs_object = str(meta.get("top_image_gcs_object") or "").strip()
    if not bucket or not gcs_object:
        return None, GLOBAL_TOP_PERSISTENCE_MISSING
    configured_bucket = str(admin_artifact_bucket_name() or "").strip()
    if gcs_object != _global_top_image_gcs_object(run_id) or (
        configured_bucket and bucket != configured_bucket
    ):
        return None, GLOBAL_TOP_REFERENCE_NOT_RUN_BOUND

    expected_sha = _expected_global_top_sha256(meta, run_id)
    if not expected_sha:
        return None, GLOBAL_TOP_EXPECTED_HASH_MISSING

    token = re.sub(r"[^A-Za-z0-9_]", "", run_id)
    dest = _writable_keysuri_service_assets_dir() / f"{token}_restored_global_top.jpg"
    if not _try_restore_keysuri_from_gcs(bucket, gcs_object, dest, download_fn=download_fn):
        return None, GLOBAL_TOP_RESTORE_FAILED
    try:
        actual_sha = _sha256_file(dest)
    except OSError:
        logger.exception("keysuri Global top image restore hash read failed: %s", dest.name)
        return None, GLOBAL_TOP_RESTORE_FAILED
    if actual_sha != expected_sha:
        # Restored bytes are not the reviewed image: discard them so no later
        # caller can pick the file up, and block.
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            logger.warning("keysuri Global top image mismatch cleanup failed: %s", dest.name)
        logger.warning(
            "keysuri Global top image restore hash mismatch: gs://%s/%s", bucket, gcs_object
        )
        return None, GLOBAL_TOP_RESTORE_HASH_MISMATCH
    return dest, ""


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
    For Global, a locally present generated image is used unchanged; only when that
    file is gone is this run's persisted, hash-verified GCS object restored.
    """
    global _last_global_inline_resolve_reason

    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode not in _KEYSURI_MODES:
        return None
    _last_global_inline_resolve_reason = ""
    if not meta.get("service_full_run"):
        return None
    run_id = str(meta.get("run_id") or "").strip()

    if mode == PROGRAM_KOREA and _is_korea_generated_v6(meta):
        parts, _ = _resolve_korea_generated_inline_parts(meta, run_id, download_fn=download_fn)
        return parts

    image_path = _resolve_generated_image_path(meta)
    if mode == PROGRAM_GLOBAL:
        if image_path is None:
            restored, reason = _restore_global_top_image_from_gcs(
                meta, run_id, download_fn=download_fn
            )
            if restored is None:
                _last_global_inline_resolve_reason = reason
                return None
            _last_global_inline_resolve_reason = GLOBAL_TOP_RESTORED_FROM_GCS
            return inline_jpeg_parts_for_global_service_email(restored, run_id)
        return inline_jpeg_parts_for_global_service_email(image_path, run_id)
    if image_path is None:
        return None
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
    *,
    prepared_delivery: Optional[Dict[str, Any]] = None,
) -> bool:
    global _last_delivery_result
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    prepared = dict(prepared_delivery or prepare_keysuri_customer_delivery(saved_html, meta))
    subject = str(prepared.get("subject") or build_keysuri_customer_final_subject(meta, saved_html))
    preheader = str(prepared.get("preheader") or build_keysuri_customer_final_preheader(meta, saved_html))
    if not prepared.get("ok"):
        err = str(prepared.get("error") or "keysuri_delivery_preparation_failed")
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason=err,
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
            customer_email_preheader=preheader,
        )
        logger.warning("send_keysuri_customer_final_email: blocked (%s)", err)
        return False

    html_body = str(prepared["html_body"])
    inline_parts = list(prepared["inline_jpeg_parts"])
    cid_tokens = [row[1] for row in inline_parts] or _cid_tokens_from_html(saved_html)
    customer_to = list(prepared["recipients"])
    sent = send_genie_email(
        html_body,
        subject,
        inline_jpeg_parts=inline_parts,
        attachment_jpeg_parts=[],
        to_addrs_override=customer_to,
        allow_rich_delivery=True,
    )
    _last_delivery_result = KeysuriCustomerDeliveryResult(
        sent=bool(sent),
        reason="ok" if sent else "smtp_send_failed",
        customer_delivery_status="smtp_accepted" if sent else "not_sent",
        customer_email_subject=subject,
        customer_email_preheader=preheader,
        cid_tokens_used=list(cid_tokens),
    )
    return bool(sent)


def prepare_keysuri_customer_delivery(
    saved_html: str,
    meta: Dict[str, Any],
    *,
    recipients_override: Optional[List[str]] = None,
    approval_source: str = HUMAN_OWNER,
) -> Dict[str, Any]:
    """Prepare the exact KeeSuri payload without submitting it to SMTP.

    ``approval_source`` selects display copy only.  Delivery authority remains
    with the guarded human/delegated caller and is never created here.
    """
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    subject = build_keysuri_customer_final_subject(meta, saved_html)
    preheader = build_keysuri_customer_final_preheader(meta, saved_html)
    if mode in _KEYSURI_MODES:
        if meta.get("reader_surface_enforced") is not True:
            return {
                "ok": False,
                "error": "KEYSURI_READER_SURFACE_UNVERIFIED",
                "subject": subject,
                "preheader": preheader,
            }
        if meta.get("reader_surface_complete") is not True:
            return {
                "ok": False,
                "error": "KEYSURI_READER_SURFACE_INCOMPLETE",
                "subject": subject,
                "preheader": preheader,
            }
        if str(meta.get("safety_verdict") or "") != "SAFE":
            return {
                "ok": False,
                "error": "KEYSURI_SAFETY_NOT_SAFE",
                "subject": subject,
                "preheader": preheader,
            }
        if str(meta.get("editorial_verdict") or "") == "POOR":
            return {
                "ok": False,
                "error": "KEYSURI_EDITORIAL_POOR",
                "subject": subject,
                "preheader": preheader,
            }
    if recipients_override is None:
        ready, err = customer_delivery_config_ready()
        if not ready:
            return {"ok": False, "error": err, "subject": subject, "preheader": preheader}
    if mode not in _KEYSURI_MODES:
        return {"ok": False, "error": "unsupported_mode", "subject": subject, "preheader": preheader}
    try:
        html_body = prepare_keysuri_customer_final_html(
            saved_html,
            meta=meta,
            approval_source=approval_source,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "subject": subject, "preheader": preheader}
    html_body = _insert_hidden_preheader(html_body, preheader)
    inline_parts = resolve_keysuri_inline_jpeg_parts(saved_html, meta)
    if not inline_parts:
        if mode == PROGRAM_KOREA and _is_korea_generated_v6(meta):
            reason = _last_korea_inline_resolve_reason or KOREA_GENERATED_FILES_UNAVAILABLE
        elif mode == PROGRAM_KOREA and _resolve_generated_image_path(meta) is not None:
            reason = _KOREA_BOTTOM_MISSING_REASON
        elif mode == PROGRAM_GLOBAL and _last_global_inline_resolve_reason:
            # Specific fail-closed cause of the Global top image restore, so the
            # operator surface does not report a generic "missing image".
            reason = _last_global_inline_resolve_reason
        else:
            reason = "missing_generated_inline_image"
        return {"ok": False, "error": reason, "subject": subject, "preheader": preheader}
    recipients = (
        list(recipients_override)
        if recipients_override is not None
        else list(resolve_customer_recipients()["final_recipients"])
    )
    if not recipients:
        return {"ok": False, "error": "missing_customer_to", "subject": subject, "preheader": preheader}
    return {
        "ok": True,
        "html_body": html_body,
        "subject": subject,
        "preheader": preheader,
        "inline_jpeg_parts": list(inline_parts),
        "recipients": recipients,
    }
