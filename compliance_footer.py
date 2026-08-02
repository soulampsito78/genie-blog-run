"""Technical contract for approved policy links; contains no invented legal copy."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
from typing import Any, Dict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

URL_ENV_KEYS = (
    "GENIE_PRIVACY_POLICY_URL",
    "GENIE_TERMS_URL",
    "GENIE_UNSUBSCRIBE_URL",
)
UNSUBSCRIBE_HANDLER_CONTRACT = "v1_run_token_identity_confirmation"


def _valid_https_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def compliance_readiness() -> Dict[str, Any]:
    urls = {key: os.getenv(key, "").strip() for key in URL_ENV_KEYS}
    missing = [key for key, value in urls.items() if not value]
    invalid = [key for key, value in urls.items() if value and not _valid_https_url(value)]
    secret_ready = bool(os.getenv("GENIE_UNSUBSCRIBE_SIGNING_SECRET", "").strip())
    if not secret_ready:
        missing.append("GENIE_UNSUBSCRIBE_SIGNING_SECRET")
    handler_contract = os.getenv("GENIE_UNSUBSCRIBE_HANDLER_CONTRACT", "").strip()
    if not handler_contract:
        missing.append("GENIE_UNSUBSCRIBE_HANDLER_CONTRACT")
    elif handler_contract != UNSUBSCRIBE_HANDLER_CONTRACT:
        invalid.append("GENIE_UNSUBSCRIBE_HANDLER_CONTRACT")
    ready = not missing and not invalid
    return {
        "ready": ready,
        "status": "READY" if ready else "BLOCKED",
        "missing": sorted(set(missing)),
        "invalid": sorted(set(invalid)),
        "external_dependency": None if ready else "EXTERNAL_LEGAL_DEPENDENCY",
    }


def compliance_enforcement_required() -> bool:
    """Customer delivery is always gated; storage selection is irrelevant."""
    return True


def compliance_configuration_present() -> bool:
    return any(
        os.getenv(key, "").strip()
        for key in (
            *URL_ENV_KEYS,
            "GENIE_UNSUBSCRIBE_SIGNING_SECRET",
            "GENIE_UNSUBSCRIBE_HANDLER_CONTRACT",
        )
    )


def _opaque_unsubscribe_token(*, run_id: str, program_id: str) -> str:
    secret = os.getenv("GENIE_UNSUBSCRIBE_SIGNING_SECRET", "").encode("utf-8")
    if not secret:
        raise RuntimeError("unsubscribe_signing_secret_missing")
    payload = f"v1:{program_id}:{run_id}".encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    # Only the MAC is the token; the signed non-PII run/program fields travel
    # separately so the token itself cannot be decoded into application data.
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def append_compliance_footer(html_body: str, *, run_id: str, program_id: str) -> str:
    readiness = compliance_readiness()
    if not readiness["ready"]:
        raise RuntimeError("compliance_not_ready")
    privacy = os.environ["GENIE_PRIVACY_POLICY_URL"].strip()
    terms = os.environ["GENIE_TERMS_URL"].strip()
    unsubscribe = os.environ["GENIE_UNSUBSCRIBE_URL"].strip()
    parsed = urlparse(unsubscribe)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["run_id"] = run_id
    query["program_id"] = program_id
    query["token"] = _opaque_unsubscribe_token(run_id=run_id, program_id=program_id)
    unsubscribe_signed = urlunparse(parsed._replace(query=urlencode(query)))
    # Labels only identify destinations; approved legal prose remains external.
    footer = (
        '<div id="genie-compliance-links" style="margin-top:24px;font-size:12px;color:#667085">'
        f'<a href="{html.escape(privacy, quote=True)}">Privacy</a> · '
        f'<a href="{html.escape(terms, quote=True)}">Terms</a> · '
        f'<a href="{html.escape(unsubscribe_signed, quote=True)}">Unsubscribe</a>'
        "</div>"
    )
    marker = "</body>"
    if marker in html_body.lower():
        index = html_body.lower().rfind(marker)
        return f"{html_body[:index]}{footer}{html_body[index:]}"
    return f"{html_body}{footer}"
