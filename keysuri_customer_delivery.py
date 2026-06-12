"""Kee-Suri customer-final email: premium briefing HTML + inline CID only.

Production-blocked: admin_store.approve_run does not call this module until durable
artifact storage, Gmail-safe rendering, and owner/customer surface separation exist.
"""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from email_sender import parse_customer_to_addrs, send_genie_email
from keysuri_contract_preview_renderer import (
    REVIEW_CONFIRMATION_TEXT,
    REVIEW_STATE_SENT_ARCHIVED,
)
from keysuri_live_source_smoke import PROGRAM_GLOBAL, PROGRAM_KOREA
from keysuri_service_full_run import (
    inline_jpeg_parts_for_global_service_email,
    keysuri_global_service_email_cid_token,
)

logger = logging.getLogger(__name__)

_KEYSURI_MODES = frozenset({PROGRAM_GLOBAL, PROGRAM_KOREA})
_KOREA_CID_PREFIX = "keysuri_topshot_korea"

_OWNER_ADMIN_ENTRY_RE = re.compile(
    r'<div[^>]*\bid=["\']owner-review-admin-entry["\'][^>]*>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
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
    if not parse_customer_to_addrs():
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


def render_keysuri_customer_review_confirmation_box() -> str:
    text = REVIEW_CONFIRMATION_TEXT[REVIEW_STATE_SENT_ARCHIVED]
    state = REVIEW_STATE_SENT_ARCHIVED
    return (
        f'<section id="review-confirmation-box" class="review-box" '
        f'data-review-state="{state}">'
        f'<p class="review-confirmation-text">{html.escape(text)}</p>'
        "</section>"
    )


def strip_keysuri_owner_review_controls(html_body: str) -> str:
    if not html_body:
        return ""
    out = html_body
    out = _OWNER_ADMIN_ENTRY_RE.sub("", out)
    out = _OWNER_REVIEW_BADGE_RE.sub("", out)
    out = _INTERNAL_BLOCK_RE.sub("", out)
    out = _REVIEW_BOX_RE.sub("", out)
    for fragment in (
        "운영자 검수용 미리보기 · 아직 발송 전",
        "운영자 검수용",
        "아직 발송 전",
        "운영자 검수 화면 열기",
    ):
        out = out.replace(fragment, "")
    return out.strip()


def prepare_keysuri_customer_final_html(
    saved_html: str,
    *,
    meta: Dict[str, Any],
) -> str:
    html_body = strip_keysuri_owner_review_controls(saved_html)
    if not html_body.strip():
        raise ValueError("Kee-Suri customer final HTML is empty after stripping owner controls")
    review_box = render_keysuri_customer_review_confirmation_box()
    return f"{html_body}\n{review_box}"


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


def _resolve_generated_image_path(meta: Dict[str, Any]) -> Optional[Path]:
    repo = _repo_root()
    rel = str(meta.get("generated_image_path") or "").strip()
    if not rel:
        return None
    path = (repo / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    return path if path.is_file() else None


def _cid_tokens_from_html(saved_html: str) -> List[str]:
    return [m.group(1).strip() for m in _CID_SRC_RE.finditer(saved_html or "") if m.group(1).strip()]


def resolve_keysuri_inline_jpeg_parts(
    saved_html: str,
    meta: Dict[str, Any],
) -> Optional[List[Tuple[str, str, str]]]:
    """Resolve inline JPEG parts from generated service_full_run artifact metadata."""
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode not in _KEYSURI_MODES:
        return None
    if not meta.get("service_full_run"):
        return None
    image_path = _resolve_generated_image_path(meta)
    if image_path is None:
        return None
    run_id = str(meta.get("run_id") or "").strip()
    if mode == PROGRAM_GLOBAL:
        return inline_jpeg_parts_for_global_service_email(image_path, run_id)
    cid_token = keysuri_korea_service_email_cid_token(run_id)
    fname = image_path.name if image_path.name else "keysuri_korea_service.jpg"
    return [(str(image_path), cid_token, fname)]


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
        _last_delivery_result = KeysuriCustomerDeliveryResult(
            sent=False,
            reason="missing_generated_inline_image",
            customer_delivery_status="not_sent",
            customer_email_subject=subject,
        )
        logger.warning("send_keysuri_customer_final_email: missing generated inline JPEG")
        return False

    cid_tokens = [row[1] for row in inline_parts] or _cid_tokens_from_html(saved_html)
    customer_to = parse_customer_to_addrs()
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
