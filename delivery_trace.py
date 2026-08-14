"""Email delivery trace normalization for persisted run artifacts."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SENSITIVE_DIAGNOSTIC_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|authorization)\b(\s*[=:]\s*)([^\s,;]+)"
)


def dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def mask_email_address(address: str) -> str:
    raw = str(address or "").strip()
    if "@" not in raw:
        return ""
    local, domain = raw.rsplit("@", 1)
    local = local.strip()
    domain = domain.strip().lower()
    if not local or not domain:
        return ""
    if len(local) <= 4:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:2]}***{local[-2:]}"
    return f"{masked_local}@{domain}"


def mask_email_addresses(addresses: List[str]) -> List[str]:
    return [masked for masked in (mask_email_address(a) for a in dedupe_preserve_order(addresses)) if masked]


def recipient_domains(addresses: List[str]) -> List[str]:
    domains: List[str] = []
    for address in dedupe_preserve_order(addresses):
        if "@" not in address:
            continue
        domain = address.rsplit("@", 1)[1].strip().lower()
        if domain:
            domains.append(domain)
    return dedupe_preserve_order(domains)


def sanitize_email_diagnostic(diagnostic: str) -> str:
    clean = str(diagnostic or "")
    if not clean:
        return ""
    clean = _EMAIL_RE.sub(lambda match: mask_email_address(match.group(0)), clean)
    clean = _SENSITIVE_DIAGNOSTIC_RE.sub(r"\1\2[redacted]", clean)
    for env_key in ("SMTP_PASSWORD", "SMTP_APP_PASSWORD", "GENIE_INTERNAL_JOB_TOKEN"):
        secret_value = os.getenv(env_key, "").strip()
        if secret_value:
            clean = clean.replace(secret_value, "[redacted]")
    return clean[:500]


def _safe_path(path_value: Any, *, repo_root: Path | None = None) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if repo_root is not None:
        try:
            return path.resolve().relative_to(repo_root.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return path.name


def _inline_image_hashes(trace: Dict[str, Any], *, repo_root: Path | None = None) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for row in trace.get("inline_input_hashes") or []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "path": _safe_path(row.get("path"), repo_root=repo_root),
                "cid": str(row.get("cid") or ""),
                "filename": Path(str(row.get("filename") or "")).name,
                "sha256": str(row.get("sha256") or ""),
            }
        )
    return out


def build_customer_email_delivery_fields(
    *,
    attempted: bool,
    send_ok: bool,
    subject: str,
    trace: Dict[str, Any] | None,
    diagnostic: str,
    preheader: str = "",
    sent_at_kst: str | None = None,
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    trace = dict(trace or {}) if attempted else {}
    recipients = dedupe_preserve_order(
        [str(addr or "").strip() for addr in trace.get("envelope_to") or [] if str(addr or "").strip()]
    )
    refused = dedupe_preserve_order(
        [
            str(addr or "").strip()
            for addr in trace.get("smtp_refused_recipients") or []
            if str(addr or "").strip()
        ]
    )
    accepted_count = int(trace.get("smtp_accepted_recipient_count") or 0)
    if send_ok and not accepted_count:
        accepted_count = max(0, len(recipients) - len(refused))
    target_count = len(recipients)
    refused_count = len(refused)
    outcome_unknown = bool(trace.get("smtp_outcome_unknown"))
    submission_started = bool(trace.get("smtp_submission_started"))
    if not attempted:
        status = "NOT_SENT"
    elif outcome_unknown:
        status = "OUTCOME_UNKNOWN"
    elif refused_count and accepted_count:
        status = "PARTIAL_REFUSAL"
    elif refused_count and target_count and refused_count >= target_count:
        status = "REFUSED_ALL"
    elif send_ok and target_count and accepted_count >= target_count:
        status = "ACCEPTED_ALL"
    elif submission_started:
        status = "SUBMITTED"
    else:
        status = "NOT_SENT"
    unknown_count = max(0, target_count - accepted_count - refused_count)

    fields = {
        "customer_email_delivery_status": status,
        "customer_email_smtp_attempted": bool(attempted),
        "customer_email_sent_at_kst": sent_at_kst if status == "ACCEPTED_ALL" else None,
        "customer_email_recipient_count": target_count,
        "customer_email_recipient_domains": recipient_domains(recipients),
        "customer_email_recipients_masked": mask_email_addresses(recipients),
        "customer_email_subject": str(subject or ""),
        "customer_email_mime_html_sha256": str(trace.get("mime_html_sha256") or ""),
        "customer_email_mime_html_bytes_len": int(trace.get("mime_html_bytes_len") or 0),
        "customer_email_inline_image_hashes": _inline_image_hashes(trace, repo_root=repo_root),
        "customer_email_send_trace_available": bool(trace),
        "customer_email_send_diagnostic": sanitize_email_diagnostic(diagnostic),
        # SMTP immediate refusal only. Delayed bounces require mailbox/bounce monitoring.
        "smtp_refused_recipient_count": len(refused),
        "smtp_refused_recipients_masked": mask_email_addresses(refused),
        "smtp_partial_refusal": bool(refused),
        "smtp_accepted_recipient_count": accepted_count,
        "customer_delivery_target_count": target_count,
        "customer_delivery_accepted_count": accepted_count,
        "customer_delivery_refused_count": refused_count,
        "customer_delivery_unknown_count": unknown_count,
        "customer_delivery_attempted_at": str(trace.get("attempted_at") or ""),
        "customer_delivery_completed_at": sent_at_kst if status in {"ACCEPTED_ALL", "PARTIAL_REFUSAL", "REFUSED_ALL"} else None,
        "smtp_outcome_unknown": outcome_unknown,
        "provider_submission_identifier": str(trace.get("provider_submission_identifier") or ""),
    }
    clean_preheader = sanitize_email_diagnostic(str(preheader or "").strip())
    if clean_preheader:
        fields["customer_email_preheader"] = clean_preheader
    fields["customer_recipient_count"] = fields["customer_email_recipient_count"]
    fields["customer_recipients_masked"] = fields["customer_email_recipients_masked"]
    fields.setdefault("customer_delivery_message_id", "")
    return fields


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
