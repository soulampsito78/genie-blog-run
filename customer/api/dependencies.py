"""Injectable transport dependencies for the isolated customer API."""

from dataclasses import dataclass, field
from typing import FrozenSet, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from customer.domain.clock import Clock, SystemClock
from customer.domain.enums import AuthAssuranceLevel
from customer.domain.errors import AuthenticationRequired, StepUpRequired
from customer.persistence.models import BrowserSession
from customer.persistence.session import customer_session
from customer.services.challenge_service import ChallengeService
from customer.services.cookies import session_cookie_settings
from customer.services.providers import (
    IdentityVerificationProvider,
    NullVerificationCodeSender,
    VerificationCodeSender,
)
from customer.services.payment_providers import (
    PaymentMethodProvider,
    UnconfiguredPaymentMethodProvider,
)
from customer.services.session_service import AccessContext, SessionService


class IdentityProviderNotConfigured(RuntimeError):
    """The intentionally unavailable default IDV integration."""


class UnconfiguredIdentityProvider:
    name = "unconfigured"

    def start(self, purpose: str, reference_hint=None) -> str:
        raise IdentityProviderNotConfigured("identity provider is not configured")

    def result(self, provider_reference: str):
        raise IdentityProviderNotConfigured("identity provider is not configured")


@dataclass(frozen=True)
class CustomerApiSecurityConfig:
    """Cookie and same-site request policy, with CORS deliberately closed."""

    cookie_secure: bool = True
    allowed_state_changing_origins: FrozenSet[str] = field(default_factory=frozenset)


def get_customer_db_session() -> Iterator[Session]:
    """Lazy runtime dependency; no URL is read until a request needs it."""
    yield from customer_session()


def get_clock() -> Clock:
    return SystemClock()


def get_identity_provider() -> IdentityVerificationProvider:
    return UnconfiguredIdentityProvider()


def get_verification_code_sender() -> VerificationCodeSender:
    return NullVerificationCodeSender()


def get_payment_method_provider() -> PaymentMethodProvider:
    return UnconfiguredPaymentMethodProvider()


def get_customer_api_security_config() -> CustomerApiSecurityConfig:
    # Origins are not finalised, so a mounted deployment must explicitly
    # provide them before cookie-authenticated writes can proceed.
    return CustomerApiSecurityConfig()


def require_customer_session(
    request: Request,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
) -> AccessContext:
    settings = session_cookie_settings(remember_login=False, secure=config.cookie_secure)
    token = request.cookies.get(settings.name)
    if not token:
        raise AuthenticationRequired("customer session cookie is required")
    service = SessionService(session, clock)
    live_session = service.authenticate_session(
        token=token,
        seen_ip=_request_ip(request),
    )
    return service.refresh_access_context(live_session)


def require_fresh_auth(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
) -> AccessContext:
    """Require 10-minute recent verification for currently-sensitive APIs."""
    live_session = session.get(BrowserSession, access.session_id)
    if live_session is None:
        raise AuthenticationRequired("customer session is required")
    service = SessionService(session, clock)
    service.require_fresh_auth(
        live_session,
        required_assurance=AuthAssuranceLevel.RECENT_VERIFICATION.value,
    )
    return access


def require_fresh_financial_auth(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
) -> AccessContext:
    """Require fresh mobile-OTP-equivalent assurance for payment changes."""
    live_session = session.get(BrowserSession, access.session_id)
    if live_session is None:
        raise AuthenticationRequired("customer session is required")
    SessionService(session, clock).require_fresh_auth(
        live_session,
        required_assurance=AuthAssuranceLevel.STRONG_OTP.value,
    )
    return access


def require_same_site_origin(
    request: Request,
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
) -> None:
    """Origin validation for cookie-authenticated writes.

    SameSite=Lax prevents routine cross-site cookie attachment.  We also
    require an explicitly configured same-site Origin for browser writes,
    avoiding a decorative CSRF token and never opening credentialed wildcard
    CORS.  The test app injects only its HTTPS test origin.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in config.allowed_state_changing_origins:
        raise RequestOriginRejected("state-changing customer request origin is not allowed")


class RequestOriginRejected(AuthenticationRequired):
    code = "REQUEST_ORIGIN_REJECTED"


def _request_ip(request: Request):
    return request.client.host if request.client is not None else None
