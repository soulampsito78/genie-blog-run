"""Cloud Scheduler OIDC authentication with a temporary header-token fallback."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class InternalAuthResult:
    ok: bool
    method: str
    status_code: int
    error: str = ""
    principal: str = ""


def _csv_env(name: str) -> set[str]:
    return {part.strip().lower() for part in os.getenv(name, "").split(",") if part.strip()}


def _verify_google_oidc(token: str, audience: str) -> Dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)


def _oidc_provider_unavailable(exc: BaseException) -> bool:
    infrastructure_errors: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)
    try:
        from google.auth.exceptions import TransportError

        infrastructure_errors += (TransportError,)
    except ImportError:
        pass
    try:
        from requests.exceptions import RequestException

        infrastructure_errors += (RequestException,)
    except ImportError:
        pass
    return isinstance(exc, infrastructure_errors)


def verify_internal_request(
    *,
    authorization: str,
    header_token: Optional[str],
    oidc_verifier: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> InternalAuthResult:
    audience = os.getenv("GENIE_INTERNAL_OIDC_AUDIENCE", "").strip()
    allowed_emails = _csv_env("GENIE_INTERNAL_OIDC_SERVICE_ACCOUNTS")
    authz = str(authorization or "").strip()
    if authz.lower().startswith("bearer "):
        if not audience or not allowed_emails:
            return InternalAuthResult(False, "oidc", 503, "internal_oidc_not_configured")
        token = authz.split(None, 1)[1].strip()
        if not token:
            return InternalAuthResult(False, "oidc", 403, "forbidden")
        try:
            claims = (oidc_verifier or _verify_google_oidc)(token, audience)
        except Exception as exc:
            if _oidc_provider_unavailable(exc):
                return InternalAuthResult(False, "oidc", 503, "oidc_verification_unavailable")
            return InternalAuthResult(False, "oidc", 403, "forbidden")
        issuer = str(claims.get("iss") or "")
        email = str(claims.get("email") or "").strip().lower()
        if issuer not in {"https://accounts.google.com", "accounts.google.com"}:
            return InternalAuthResult(False, "oidc", 403, "forbidden")
        if claims.get("aud") != audience or email not in allowed_emails:
            return InternalAuthResult(False, "oidc", 403, "forbidden")
        if claims.get("email_verified") is not True:
            return InternalAuthResult(False, "oidc", 403, "forbidden")
        return InternalAuthResult(True, "oidc", 200, principal=email)

    expected = os.getenv("GENIE_INTERNAL_JOB_TOKEN", "").strip()
    if not expected:
        return InternalAuthResult(False, "none", 503, "internal_job_token_not_configured")
    provided = str(header_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        return InternalAuthResult(False, "token_fallback", 403, "forbidden")
    return InternalAuthResult(True, "token_fallback", 200)
