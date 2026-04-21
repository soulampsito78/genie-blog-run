"""
Thin email delivery: sends Genie briefing email via SMTP when invoked by
the orchestrator. Uses stdlib only (smtplib + email.mime).

SMTP host, user, password, and port are read at **send time** (not at import)
so test harnesses and workers can set env after process start and so
SMTP_PASSWORD_FILE mounts are re-read when the file appears.

MIME rich path: multipart/mixed with multipart/related
(HTML + inline JPEG via Content-ID) plus separate attachment JPEG parts.

Modes:
- test-rich: GENIE_EMAIL_SEND_TEST=1 (+ GENIE_EMAIL_TEST_TO or explicit test_to_addrs)
- orchestrator-rich: GENIE_EMAIL_RICH_MODE=1 (+ EMAIL_TO)
"""
from __future__ import annotations

import logging
import os
import smtplib
import hashlib
from email import message_from_string
from email.message import Message
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Set on each send attempt (success clears); for test harness diagnostics only.
_LAST_SEND_DIAGNOSTIC: str = ""
_LAST_PASSWORD_SOURCE: str = ""
_LAST_PASSWORD_PATH: str = ""
_LAST_PASSWORD_FILE_EXISTS: bool = False
_LAST_PASSWORD_FILE_READ_OK: bool = False
_LAST_SEND_TRACE: dict = {}


def last_send_diagnostic() -> str:
    """Non-empty if the last send_genie_email call failed inside SMTP (or prep)."""
    return _LAST_SEND_DIAGNOSTIC


def last_password_resolution() -> dict:
    """Diagnostics for which SMTP password source was used on the last send call."""
    return {
        "source": _LAST_PASSWORD_SOURCE,
        "path": _LAST_PASSWORD_PATH,
        "file_exists": _LAST_PASSWORD_FILE_EXISTS,
        "file_read_ok": _LAST_PASSWORD_FILE_READ_OK,
    }


def last_send_trace() -> dict:
    """Structured facts from the most recent send attempt."""
    return dict(_LAST_SEND_TRACE)


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


def _resolve_password_with_meta() -> str:
    """
    Resolve SMTP password with explicit source metadata:
    SMTP_PASSWORD > SMTP_PASSWORD_FILE > SMTP_APP_PASSWORD > SMTP_APP_PASSWORD_FILE.
    """
    global _LAST_PASSWORD_SOURCE, _LAST_PASSWORD_PATH, _LAST_PASSWORD_FILE_EXISTS, _LAST_PASSWORD_FILE_READ_OK
    _LAST_PASSWORD_SOURCE = ""
    _LAST_PASSWORD_PATH = ""
    _LAST_PASSWORD_FILE_EXISTS = False
    _LAST_PASSWORD_FILE_READ_OK = False

    direct = os.getenv("SMTP_PASSWORD", "").strip()
    if direct:
        _LAST_PASSWORD_SOURCE = "SMTP_PASSWORD"
        return direct

    p1 = os.getenv("SMTP_PASSWORD_FILE", "").strip()
    if p1:
        _LAST_PASSWORD_SOURCE = "SMTP_PASSWORD_FILE"
        _LAST_PASSWORD_PATH = p1
        _LAST_PASSWORD_FILE_EXISTS = os.path.isfile(p1)
        if _LAST_PASSWORD_FILE_EXISTS:
            try:
                with open(p1, encoding="utf-8") as f:
                    val = f.read().strip()
                _LAST_PASSWORD_FILE_READ_OK = True
                if val:
                    return val
            except OSError:
                _LAST_PASSWORD_FILE_READ_OK = False
        return ""

    app = os.getenv("SMTP_APP_PASSWORD", "").strip()
    if app:
        _LAST_PASSWORD_SOURCE = "SMTP_APP_PASSWORD"
        return app

    p2 = os.getenv("SMTP_APP_PASSWORD_FILE", "").strip()
    if p2:
        _LAST_PASSWORD_SOURCE = "SMTP_APP_PASSWORD_FILE"
        _LAST_PASSWORD_PATH = p2
        _LAST_PASSWORD_FILE_EXISTS = os.path.isfile(p2)
        if _LAST_PASSWORD_FILE_EXISTS:
            try:
                with open(p2, encoding="utf-8") as f:
                    val = f.read().strip()
                _LAST_PASSWORD_FILE_READ_OK = True
                if val:
                    return val
            except OSError:
                _LAST_PASSWORD_FILE_READ_OK = False
        return ""

    return ""


def _smtp_password_live() -> str:
    return _resolve_password_with_meta()


def _smtp_host_live() -> str:
    return os.getenv("SMTP_HOST", "").strip()


def _smtp_user_live() -> str:
    return os.getenv("SMTP_USER", "").strip()


def _smtp_port_live() -> int:
    raw = os.getenv("SMTP_PORT", "587").strip()
    try:
        return int(raw) if raw else 587
    except ValueError:
        return 587


def _email_from_live() -> str:
    return os.getenv("EMAIL_FROM", "").strip()


def smtp_configured() -> bool:
    """True when env currently provides host, user, and a resolvable SMTP password."""
    return bool(_smtp_host_live() and _smtp_user_live() and _smtp_password_live())


def _parse_to_addrs() -> list[str]:
    raw = os.getenv("EMAIL_TO", "")
    if not raw or not raw.strip():
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _rich_send_gate_ok() -> bool:
    return os.getenv("GENIE_EMAIL_SEND_TEST", "").strip() in ("1", "true", "True", "yes", "YES")


def _rich_non_test_gate_ok() -> bool:
    return os.getenv("GENIE_EMAIL_RICH_MODE", "").strip() in ("1", "true", "True", "yes", "YES")


def _parse_test_recipients() -> list[str]:
    """CSV address list from GENIE_EMAIL_TEST_TO for explicit test sends."""
    raw = os.getenv("GENIE_EMAIL_TEST_TO", "").strip()
    if not raw:
        return []
    if ";" in raw or "\n" in raw:
        logger.warning("GENIE_EMAIL_TEST_TO must be comma-separated addresses only")
        return []
    out: list[str] = []
    for a in raw.split(","):
        addr = a.strip()
        if not addr:
            continue
        if "@" not in addr:
            return []
        out.append(addr)
    # de-duplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for a in out:
        low = a.lower()
        if low in seen:
            continue
        seen.add(low)
        uniq.append(a)
    return uniq


def _read_jpeg_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _build_mime_multipart_inline_and_attach(
    html_body: str,
    from_addr: str,
    to_addrs: Sequence[str],
    subject: str,
    inline_jpeg_parts: Sequence[Tuple[str, str, str]],
    attachment_jpeg_parts: Sequence[Tuple[str, str]],
) -> MIMEMultipart:
    """
    multipart/mixed
      multipart/related
        text/html
        image/jpeg (inline, Content-ID)
        ...
      image/jpeg (attachment)
      ...
    """
    root = MIMEMultipart("mixed")
    root["Subject"] = subject or "(Genie briefing)"
    root["From"] = from_addr
    root["To"] = ", ".join(to_addrs)

    related = MIMEMultipart("related")
    related.attach(MIMEText(html_body, "html", "utf-8"))

    seen_cids: set[str] = set()
    for fs_path, cid_token, inline_fname in inline_jpeg_parts:
        cid_token = cid_token.strip()
        if not cid_token or cid_token in seen_cids:
            continue
        seen_cids.add(cid_token)
        if not os.path.isfile(fs_path):
            raise FileNotFoundError(f"inline image missing: {fs_path}")
        img = MIMEImage(_read_jpeg_bytes(fs_path), _subtype="jpeg")
        img.add_header("Content-ID", f"<{cid_token}>")
        img.add_header("Content-Disposition", "inline", filename=inline_fname)
        related.attach(img)

    root.attach(related)

    seen_attach: set[str] = set()
    for fs_path, attach_fname in attachment_jpeg_parts:
        key = f"{fs_path}\0{attach_fname}"
        if key in seen_attach:
            continue
        seen_attach.add(key)
        if not os.path.isfile(fs_path):
            raise FileNotFoundError(f"attachment image missing: {fs_path}")
        att = MIMEImage(_read_jpeg_bytes(fs_path), _subtype="jpeg")
        att.add_header("Content-Disposition", "attachment", filename=attach_fname)
        root.attach(att)

    return root


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_html_bytes(msg: Message) -> bytes:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    return payload
                raw = part.get_payload()
                if isinstance(raw, str):
                    return raw.encode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        if (msg.get_content_type() or "").lower() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload is not None:
                return payload
            raw = msg.get_payload()
            if isinstance(raw, str):
                return raw.encode(msg.get_content_charset() or "utf-8", errors="replace")
    return b""


def send_genie_email(
    html_body: str,
    subject: str,
    *,
    inline_jpeg_parts: Optional[List[Tuple[str, str, str]]] = None,
    attachment_jpeg_parts: Optional[List[Tuple[str, str]]] = None,
    test_to_addrs: Optional[List[str]] = None,
) -> bool:
    """
    Send HTML email via SMTP.

    Default: single-part HTML to addresses in EMAIL_TO (orchestrator path).

    Rich MIME:
      - Pass inline_jpeg_parts as [(path, content_id, inline_filename), ...]
        and attachment_jpeg_parts as [(path, attachment_filename), ...].
      - test-rich: GENIE_EMAIL_SEND_TEST=1 and GENIE_EMAIL_TEST_TO (or explicit test_to_addrs).
      - orchestrator-rich: GENIE_EMAIL_RICH_MODE=1 and EMAIL_TO.
      - HTML must reference images with cid:<content_id> (no relative URLs).
    """
    global _LAST_SEND_DIAGNOSTIC, _LAST_SEND_TRACE
    _LAST_SEND_DIAGNOSTIC = ""
    _LAST_SEND_TRACE = {}

    host = _smtp_host_live()
    port = _smtp_port_live()
    user = _smtp_user_live()
    password = _smtp_password_live()

    if not (host and user and password):
        _LAST_SEND_DIAGNOSTIC = (
            "missing_smtp_credentials: need SMTP_HOST, SMTP_USER, and "
            "SMTP_PASSWORD or readable SMTP_PASSWORD_FILE (or SMTP_APP_PASSWORD*)"
        )
        logger.warning(
            "send_genie_email: skipped (SMTP_HOST, SMTP_USER, and a resolvable SMTP password required)"
        )
        return False

    use_rich = bool(inline_jpeg_parts) or bool(attachment_jpeg_parts)
    if use_rich:
        if _rich_send_gate_ok():
            if test_to_addrs is not None:
                to_addrs = [x.strip() for x in test_to_addrs if isinstance(x, str) and x.strip()]
            else:
                to_addrs = _parse_test_recipients()
            if not to_addrs:
                _LAST_SEND_DIAGNOSTIC = (
                    "rich_send_blocked: set GENIE_EMAIL_TEST_TO to one or more valid test addresses"
                )
                logger.warning(
                    "send_genie_email: test-rich MIME send requires valid GENIE_EMAIL_TEST_TO addresses"
                )
                return False
        elif _rich_non_test_gate_ok():
            to_addrs = _parse_to_addrs()
            if not to_addrs:
                _LAST_SEND_DIAGNOSTIC = "rich_send_blocked: EMAIL_TO not set or empty"
                logger.warning(
                    "send_genie_email: orchestrator-rich MIME send requires EMAIL_TO"
                )
                return False
        else:
            _LAST_SEND_DIAGNOSTIC = (
                "rich_send_blocked: set GENIE_EMAIL_SEND_TEST=1 (test-rich) "
                "or GENIE_EMAIL_RICH_MODE=1 (orchestrator-rich)"
            )
            logger.warning(
                "send_genie_email: MIME/attachment kwargs require rich send gate"
            )
            return False
        if not inline_jpeg_parts:
            _LAST_SEND_DIAGNOSTIC = "rich_send_blocked: inline_jpeg_parts required"
            logger.warning("send_genie_email: MIME send requires inline_jpeg_parts")
            return False
    else:
        to_addrs = _parse_to_addrs()
        if not to_addrs:
            _LAST_SEND_DIAGNOSTIC = "skipped: EMAIL_TO not set or empty"
            logger.warning("send_genie_email: skipped (EMAIL_TO not set or empty)")
            return False

    from_addr = _email_from_live() or user

    if not html_body.strip():
        _LAST_SEND_DIAGNOSTIC = "skipped: empty html_body"
        logger.warning("send_genie_email: skipped (empty html_body)")
        return False

    try:
        if use_rich:
            att_parts = attachment_jpeg_parts or []
            inline_input_hashes = [
                {
                    "path": fs_path,
                    "cid": cid_token,
                    "filename": inline_fname,
                    "sha256": _sha256_file(fs_path) if os.path.isfile(fs_path) else "",
                }
                for fs_path, cid_token, inline_fname in (inline_jpeg_parts or [])
            ]
            attachment_input_hashes = [
                {
                    "path": fs_path,
                    "filename": attach_fname,
                    "sha256": _sha256_file(fs_path) if os.path.isfile(fs_path) else "",
                }
                for fs_path, attach_fname in att_parts
            ]
            msg = _build_mime_multipart_inline_and_attach(
                html_body,
                from_addr,
                to_addrs,
                subject,
                inline_jpeg_parts or [],
                att_parts,
            )
            payload = msg.as_string()
        else:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject or "(Genie briefing)"
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            payload = msg.as_string()
            inline_input_hashes = []
            attachment_input_hashes = []

        parsed = message_from_string(payload)
        sent_html_bytes = _extract_html_bytes(parsed)
        intended_html_bytes = html_body.encode("utf-8")
        _LAST_SEND_TRACE = {
            "to_header": str(msg.get("To", "")),
            "cc_header": str(msg.get("Cc", "")),
            "bcc_header": str(msg.get("Bcc", "")),
            "envelope_to": list(to_addrs),
            "mime_html_present": bool(sent_html_bytes),
            "mime_html_text": sent_html_bytes.decode("utf-8", errors="replace") if sent_html_bytes else "",
            "mime_html_sha256": hashlib.sha256(sent_html_bytes).hexdigest() if sent_html_bytes else "",
            "intended_html_sha256": hashlib.sha256(intended_html_bytes).hexdigest(),
            "mime_html_byte_identical": sent_html_bytes == intended_html_bytes,
            "mime_html_bytes_len": len(sent_html_bytes),
            "intended_html_bytes_len": len(intended_html_bytes),
            "inline_input_hashes": inline_input_hashes,
            "attachment_input_hashes": attachment_input_hashes,
        }

        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, list(to_addrs), payload)
        logger.info(
            "send_genie_email: sent (recipients=%d mime_rich=%s)",
            len(to_addrs),
            use_rich,
        )
        return True
    except (smtplib.SMTPException, OSError) as e:
        _LAST_SEND_DIAGNOSTIC = f"{type(e).__name__}: {e}"
        logger.exception("send_genie_email: send failed: %s", e)
        return False
