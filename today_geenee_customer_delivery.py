"""Today_Geenee customer-final email: HTML body + inline CID only (no Naver package)."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from email_sender import parse_customer_to_addrs, send_genie_email
from renderers import today_genie_email_inline_cid_pair

logger = logging.getLogger(__name__)

REVIEW_CONFIRMATION_STATE_REVIEW_PASSED = "review_passed"

REVIEW_PASSED_CONFIRMATION_TEXT = (
    "본 브리핑은 운영책임자의 직접 검수를 통과했습니다."
)

_GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES = frozenset({REVIEW_CONFIRMATION_STATE_REVIEW_PASSED})

_OPERATIONAL_HANDOFF_RE = re.compile(
    r'<section[^>]*\bid=["\']genie-operational-handoff["\'][^>]*>.*?</section>',
    re.IGNORECASE | re.DOTALL,
)

_NAVER_MARKER_FRAGMENTS = (
    "[네이버 블로그 복사용 본문 시작]",
    "[네이버 블로그 복사용 본문 끝]",
    "[본문 크기 안내]",
    "[사용 안내]",
    "naver_ready_article.html",
    "genie-customer-naver-paste-body",
)


def strip_owner_operational_handoff(html_body: str) -> str:
    """Remove owner-review operational handoff block from customer-facing HTML."""
    if not html_body:
        return ""
    return _OPERATIONAL_HANDOFF_RE.sub("", html_body).strip()


def customer_html_contains_naver_markers(html_body: str) -> bool:
    blob = html_body or ""
    lower = blob.lower()
    return any(frag.lower() in lower for frag in _NAVER_MARKER_FRAGMENTS)


def customer_delivery_config_ready() -> tuple[bool, str]:
    if not parse_customer_to_addrs():
        return False, "missing_customer_to"
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    if not (host and user):
        return False, "missing_smtp"
    return True, "ok"


def _resolve_today_genie_inline_jpeg_parts() -> Optional[List[Tuple[str, str, str]]]:
    repo = Path(__file__).resolve().parent
    top_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
    bottom_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
    if not top_latest.is_file() or not bottom_latest.is_file():
        return None
    cid_top, cid_bottom = today_genie_email_inline_cid_pair()
    return [
        (str(top_latest), cid_top, "GENIE_EMAIL_today_genie_top.jpg"),
        (str(bottom_latest), cid_bottom, "GENIE_EMAIL_today_genie_bottom.jpg"),
    ]


def build_customer_final_subject(meta: Dict[str, Any], saved_html: str) -> str:
    drafts_subj = ""
    if isinstance(meta.get("email_subject"), str):
        drafts_subj = meta["email_subject"].strip()
    if not drafts_subj:
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", saved_html or "", re.IGNORECASE)
        if m:
            drafts_subj = m.group(1).strip()
    if not drafts_subj:
        drafts_subj = "오늘의 지니 장전 브리핑"
    for prefix in ("[GENIE owner reissue]", "[GENIE render test]", "[운영자 검토]"):
        if drafts_subj.startswith(prefix):
            drafts_subj = drafts_subj.split("]", 1)[-1].strip(" -")
    return drafts_subj


def render_genie_review_confirmation_box(review_state: str) -> str:
    """Customer-safe review confirmation box for approved outbound email only."""
    if review_state not in _GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES:
        raise ValueError(
            "unsupported review_confirmation_state for Genie customer outbound email: "
            f"{review_state!r}"
        )
    return (
        f'<section id="review-confirmation-box" '
        f'data-review-state="{review_state}" '
        'style="margin-top:24px;padding:16px 18px;border:1px solid #d9d9d9;'
        'border-radius:8px;background:#fafafa;">'
        f'<p class="review-confirmation-text" style="margin:0;font-size:14px;'
        f'line-height:1.65;color:#1a1a1a;">{REVIEW_PASSED_CONFIRMATION_TEXT}</p>'
        "</section>"
    )


def prepare_customer_final_html(
    saved_html: str,
    *,
    review_confirmation_state: str | None = None,
) -> str:
    html_body = strip_owner_operational_handoff(saved_html)
    if customer_html_contains_naver_markers(html_body):
        raise ValueError("customer final HTML contains forbidden Naver markers")
    if not html_body.strip():
        raise ValueError("customer final HTML is empty after stripping operational handoff")
    if review_confirmation_state is None:
        return html_body
    if review_confirmation_state not in _GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES:
        raise ValueError(
            "unsupported review_confirmation_state for Genie customer outbound email: "
            f"{review_confirmation_state!r}"
        )
    review_box = render_genie_review_confirmation_box(review_confirmation_state)
    return f"{html_body}\n{review_box}"


def send_today_geenee_customer_final_email(
    saved_html: str,
    meta: Dict[str, Any],
) -> bool:
    """
    Send approved customer email: text/html body with inline CID JPEG parts only.
    No HTML attachment, no image attachments, no Naver paste body.
    """
    ready, err = customer_delivery_config_ready()
    if not ready:
        logger.warning("send_today_geenee_customer_final_email: blocked (%s)", err)
        return False

    try:
        html_body = prepare_customer_final_html(
            saved_html,
            review_confirmation_state=REVIEW_CONFIRMATION_STATE_REVIEW_PASSED,
        )
    except ValueError as exc:
        logger.warning("send_today_geenee_customer_final_email: %s", exc)
        return False

    inline_parts = _resolve_today_genie_inline_jpeg_parts()
    if inline_parts is None:
        logger.warning("send_today_geenee_customer_final_email: missing latest inline JPEG assets")
        return False

    subject = build_customer_final_subject(meta, saved_html)
    customer_to = parse_customer_to_addrs()
    os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
    return send_genie_email(
        html_body,
        subject,
        inline_jpeg_parts=inline_parts,
        attachment_jpeg_parts=[],
        to_addrs_override=customer_to,
    )


def send_customer_timeout_draft_email(*_args: Any, **_kwargs: Any) -> bool:
    """Retired: timeout-based customer auto-send is not active policy."""
    logger.info("send_customer_timeout_draft_email: retired no-op (timeout auto-send removed)")
    return False
