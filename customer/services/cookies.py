"""Session cookie policy.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 4, 7

No FastAPI route is wired in this phase; this module exists so the cookie
attributes are decided once, here, rather than improvised at each future route.

What the cookie carries: the opaque session token and nothing else. It never
carries the stable person identity, a verification code, an IDV payload, a
payment token, or any operator authority (sec. 7 - the browser is untrusted).

Persistence mirrors the policy: with "Keep me signed in" OFF the cookie is a
non-persistent browser-session cookie (`max_age=None`), so closing the browser
discards it; with it ON the cookie persists for the session's absolute
lifetime. Server-side expiry remains authoritative either way - a cookie that
outlived its session still fails authentication.
"""

from dataclasses import dataclass
from typing import Optional

from customer.domain import auth_policy

#: Name of the customer session cookie. `__Host-` locks it to an exact origin
#: with no Domain attribute and requires Secure + Path=/, which is the
#: strongest browser-enforced binding available.
SESSION_COOKIE_NAME = "__Host-genie_customer_session"

#: Development name, used only when Secure cannot be set (plain-HTTP
#: localhost), because browsers reject `__Host-` cookies without Secure.
SESSION_COOKIE_NAME_INSECURE = "genie_customer_session"


@dataclass(frozen=True)
class CookieSettings:
    """Attributes for the customer session cookie."""

    name: str
    http_only: bool
    secure: bool
    same_site: str
    path: str
    #: None means a non-persistent browser-session cookie.
    max_age: Optional[int]
    domain: Optional[str] = None


def session_cookie_settings(
    *, remember_login: bool, secure: bool = True
) -> CookieSettings:
    """Cookie attributes for a newly created session.

    `secure=False` exists only for local plain-HTTP development and downgrades
    the cookie name accordingly; production defaults are safe with no argument.
    """
    if remember_login:
        max_age = int(auth_policy.SESSION_ABSOLUTE_TTL_REMEMBER_ON.total_seconds())
    else:
        # Non-persistent: discarded when the browser closes.
        max_age = None

    return CookieSettings(
        name=SESSION_COOKIE_NAME if secure else SESSION_COOKIE_NAME_INSECURE,
        http_only=True,
        secure=secure,
        # Lax, not None: the customer web is same-site, and SameSite=None would
        # attach the session to third-party requests for no benefit.
        same_site="Lax",
        path="/",
        max_age=max_age,
        # No Domain attribute: host-only, so no subdomain can claim the cookie.
        domain=None,
    )


def cleared_cookie_settings(*, secure: bool = True) -> CookieSettings:
    """Attributes for clearing the cookie on logout.

    Clearing the cookie is a client-side convenience only. Logout MUST also
    revoke the session server-side (see SessionService.revoke_session);
    otherwise the token remains valid for anyone who captured it.
    """
    return CookieSettings(
        name=SESSION_COOKIE_NAME if secure else SESSION_COOKIE_NAME_INSECURE,
        http_only=True,
        secure=secure,
        same_site="Lax",
        path="/",
        max_age=0,
        domain=None,
    )
