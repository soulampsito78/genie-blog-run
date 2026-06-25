"""Admin operational notice delivery.

Reuses email_sender.send_genie_email() exclusively — no new MIME/SMTP logic.
Never reads or writes briefing run artifacts, never calls approve_run, never
touches sent_news_log. Recipient addresses are resolved at send time only
and are never written into the notice JSON (admin_notice_store.py).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from admin_store import resolve_customer_recipients
from email_sender import send_genie_email

logger = logging.getLogger(__name__)


def notice_recipient_source_label() -> str:
    """Human-readable provenance label only — never the address list itself."""
    return "beta_recipients_config_merged"


def send_admin_notice_email(notice: Dict[str, Any]) -> bool:
    """Send an operational customer notice using the shared low-level sender.

    Does not touch any briefing run artifact, approve_run(), or sent_news_log.
    """
    subject = str(notice.get("subject") or "").strip()
    body_text = str(notice.get("body_text") or "")
    html_body = str(notice.get("body_html") or "") or render_notice_body_html(body_text)

    final_recipients = resolve_customer_recipients()["final_recipients"]
    if not final_recipients:
        logger.warning("send_admin_notice_email: blocked (no resolved recipients)")
        return False

    sent = send_genie_email(
        html_body,
        subject,
        to_addrs_override=final_recipients,
    )
    return bool(sent)


def render_notice_body_html(body_text: str) -> str:
    import html as _html

    paragraphs = [
        f"<p>{_html.escape(line)}</p>"
        for line in body_text.splitlines()
        if line.strip()
    ]
    return "\n".join(paragraphs) or "<p></p>"
