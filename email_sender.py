"""
Thin email delivery: sends Genie briefing email via SMTP when invoked by
the orchestrator. Uses stdlib only (smtplib + email.mime).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _read_secret(env_key: str, file_env_key: str) -> str:
    """Read from env or, if file_env_key is set, from that path (Secret Manager mount)."""
    val = os.getenv(env_key, "").strip()
    if val:
        return val
    path = os.getenv(file_env_key, "").strip()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = _read_secret("SMTP_PASSWORD", "SMTP_PASSWORD_FILE") or _read_secret("SMTP_APP_PASSWORD", "SMTP_APP_PASSWORD_FILE")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")


def _parse_to_addrs() -> list[str]:
    if not EMAIL_TO or not EMAIL_TO.strip():
        return []
    return [addr.strip() for addr in EMAIL_TO.split(",") if addr.strip()]


def send_genie_email(html_body: str, subject: str) -> bool:
    """
    Send a single HTML email via SMTP using env-configured credentials.

    Args:
        html_body: HTML body (e.g. from rendered_channels.email_body_html)
        subject: Subject line (e.g. from channel_drafts.email_subject)

    Returns:
        True if send succeeded, False on misconfiguration or send failure.
    """
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(
            "send_genie_email: skipped (SMTP_HOST, SMTP_USER, SMTP_PASSWORD required)"
        )
        return False

    to_addrs = _parse_to_addrs()
    if not to_addrs:
        logger.warning("send_genie_email: skipped (EMAIL_TO not set or empty)")
        return False

    from_addr = EMAIL_FROM or SMTP_USER
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or "(Genie briefing)"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        logger.info("send_genie_email: sent (recipients=%d)", len(to_addrs))
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.exception("send_genie_email: send failed: %s", e)
        return False
