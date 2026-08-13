"""Browser sessions, access contexts, and fresh-auth evaluation.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 4, 5, 6, 9

The two-layer model required by sec. 4.2:

    BrowserSession  - server-managed, revocable, long-lived (up to 30 days).
                      Authenticated by an opaque token whose hash is stored.
    AccessContext   - short-lived (~15 min), derived per request window,
                      never persisted, never a bearer credential on its own.

"Keep me signed in" extends the *session*, never the freshness. A 29-day-old
remembered session is authenticated and simultaneously not fresh, which is
what makes sec. 5's step-up requirement meaningful.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import List, Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain import auth_policy
from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    AccountStatus,
    AuthAssuranceLevel,
    SessionRevokeReason,
    assurance_at_least,
)
from customer.domain.errors import (
    AccountNotActive,
    SessionExpired,
    SessionInvalid,
    SessionRevoked,
    StepUpRequired,
)
from customer.domain.security import generate_session_token, hash_session_token
from customer.persistence.models import BrowserSession, CustomerAccount
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService


@dataclass(frozen=True)
class CreatedSession:
    """A new browser session plus its one-time bearer token."""

    session_id: uuid.UUID
    #: Plaintext token. Returned once, stored nowhere, set as an HttpOnly
    #: cookie by the transport layer.
    token: str
    absolute_expires_at: dt.datetime
    inactivity_expires_at: dt.datetime
    remember_login: bool


@dataclass(frozen=True)
class AccessContext:
    """Short-lived authorization context derived from a valid session.

    Not persisted and not a credential: it is the in-process answer to "who is
    this request, how strong is their auth, and until when may I reuse that
    answer without re-reading the session".
    """

    account_id: uuid.UUID
    session_id: uuid.UUID
    issued_at: dt.datetime
    expires_at: dt.datetime
    assurance: str
    fresh_until: Optional[dt.datetime]

    def is_expired(self, now: dt.datetime) -> bool:
        return now >= self.expires_at

    def is_fresh(self, now: dt.datetime) -> bool:
        return self.fresh_until is not None and now < self.fresh_until


class SessionService:
    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)

    # -- creation -----------------------------------------------------------

    def create_browser_session(
        self,
        *,
        account_id: uuid.UUID,
        remember_login: bool = auth_policy.REMEMBER_LOGIN_DEFAULT,
        assurance: str = AuthAssuranceLevel.RECENT_VERIFICATION.value,
        user_agent_summary: Optional[str] = None,
        created_ip: Optional[str] = None,
    ) -> CreatedSession:
        """Create a session after a successful login verification.

        Login just happened, so the session starts fresh; the 10-minute window
        then runs from now regardless of `remember_login`.
        """
        now = self._clock.now()
        account = self._session.get(CustomerAccount, account_id)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise AccountNotActive("account is not active")

        absolute_ttl, inactivity_ttl = auth_policy.session_ttls(remember_login)
        token = generate_session_token()

        browser_session = BrowserSession(
            account_id=account_id,
            session_token_hash=hash_session_token(token),
            remember_login=remember_login,
            absolute_expires_at=now + absolute_ttl,
            inactivity_expires_at=now + inactivity_ttl,
            last_seen_at=now,
            created_at=now,
            last_fresh_auth_at=now,
            fresh_auth_assurance=assurance,
            user_agent_summary=user_agent_summary,
            created_ip=created_ip,
            last_seen_ip=created_ip,
        )
        self._session.add(browser_session)
        self._session.flush()

        # session_id is an identifier, safe to record. The token and its hash
        # are credentials and are not.
        self._audit.record(
            audit_events.SESSION_CREATED,
            account_id=account_id,
            actor_type="customer",
            entity_type="browser_session",
            entity_id=browser_session.id,
            payload={"remember_login": remember_login, "assurance": assurance},
        )

        return CreatedSession(
            session_id=browser_session.id,
            token=token,
            absolute_expires_at=browser_session.absolute_expires_at,
            inactivity_expires_at=browser_session.inactivity_expires_at,
            remember_login=remember_login,
        )

    # -- authentication -----------------------------------------------------

    def authenticate_session(
        self, *, token: str, touch: bool = True, seen_ip: Optional[str] = None
    ) -> BrowserSession:
        """Resolve a bearer token to a live session, or fail closed.

        Lookup is by token hash, so a stolen database row cannot be replayed as
        a token. An IP change never invalidates a session (sec. 6); the IP is
        recorded for the customer's own session list only.
        """
        now = self._clock.now()
        browser_session = self._session.scalar(
            sa.select(BrowserSession).where(
                BrowserSession.session_token_hash == hash_session_token(token)
            )
        )
        if browser_session is None:
            raise SessionInvalid("no session matches the presented token")

        if browser_session.revoked_at is not None:
            raise SessionRevoked("session was revoked")

        if now >= ensure_utc(browser_session.absolute_expires_at):
            raise SessionExpired("absolute session lifetime elapsed")

        if now >= ensure_utc(browser_session.inactivity_expires_at):
            raise SessionExpired("session inactivity timeout elapsed")

        account = self._session.get(CustomerAccount, browser_session.account_id)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise AccountNotActive("account is not active")

        if touch:
            self.record_session_activity(browser_session, seen_ip=seen_ip, now=now)
        return browser_session

    def record_session_activity(
        self,
        browser_session: BrowserSession,
        *,
        seen_ip: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> BrowserSession:
        """Slide the inactivity window forward, never past the absolute limit.

        Clamping matters: without it, a continuously active remembered session
        would drift beyond its 30-day absolute lifetime.
        """
        now = now or self._clock.now()
        _, inactivity_ttl = auth_policy.session_ttls(browser_session.remember_login)
        slid = now + inactivity_ttl
        absolute = ensure_utc(browser_session.absolute_expires_at)

        browser_session.last_seen_at = now
        browser_session.inactivity_expires_at = min(slid, absolute)
        if seen_ip is not None:
            browser_session.last_seen_ip = seen_ip
        self._session.flush()
        return browser_session

    def refresh_access_context(self, browser_session: BrowserSession) -> AccessContext:
        """Mint a short-lived access context from a still-valid session."""
        now = self._clock.now()
        fresh_until = None
        if browser_session.last_fresh_auth_at is not None:
            fresh_until = (
                ensure_utc(browser_session.last_fresh_auth_at)
                + auth_policy.FRESH_AUTH_WINDOW
            )
        return AccessContext(
            account_id=browser_session.account_id,
            session_id=browser_session.id,
            issued_at=now,
            expires_at=now + auth_policy.ACCESS_CONTEXT_TTL,
            assurance=browser_session.fresh_auth_assurance
            or AuthAssuranceLevel.SESSION.value,
            fresh_until=fresh_until,
        )

    # -- fresh auth ---------------------------------------------------------

    def record_fresh_auth(
        self, browser_session: BrowserSession, *, assurance: str
    ) -> BrowserSession:
        """Record a successful step-up on this session."""
        now = self._clock.now()
        browser_session.last_fresh_auth_at = now
        browser_session.fresh_auth_assurance = assurance
        self._session.flush()
        self._audit.record(
            audit_events.AUTH_FRESH_AUTH_RECORDED,
            account_id=browser_session.account_id,
            actor_type="customer",
            entity_type="browser_session",
            entity_id=browser_session.id,
            payload={"assurance": assurance},
        )
        return browser_session

    def is_fresh(
        self,
        browser_session: BrowserSession,
        *,
        required_assurance: str = AuthAssuranceLevel.STRONG_OTP.value,
    ) -> bool:
        """True when the session is inside the fresh-auth window AND strong enough.

        Both halves are required. A recent email verification is fresh but not
        strong enough for a financial action; an old mobile OTP is strong but
        no longer fresh.
        """
        now = self._clock.now()
        if browser_session.last_fresh_auth_at is None:
            return False
        if browser_session.fresh_auth_assurance is None:
            return False
        elapsed_ok = (
            now
            < ensure_utc(browser_session.last_fresh_auth_at)
            + auth_policy.FRESH_AUTH_WINDOW
        )
        strong_enough = assurance_at_least(
            browser_session.fresh_auth_assurance, required_assurance
        )
        return elapsed_ok and strong_enough

    def require_fresh_auth(
        self,
        browser_session: BrowserSession,
        *,
        required_assurance: str = AuthAssuranceLevel.STRONG_OTP.value,
    ) -> None:
        """Raise STEP_UP_REQUIRED unless the session is fresh and strong enough."""
        if not self.is_fresh(
            browser_session, required_assurance=required_assurance
        ):
            raise StepUpRequired(
                "action requires reauthentication at assurance "
                "'{0}' within the fresh-auth window".format(required_assurance)
            )

    # -- listing and revocation ---------------------------------------------

    def list_active_sessions(self, account_id: uuid.UUID) -> List[BrowserSession]:
        """Sessions the customer can see and revoke on My Page."""
        now = self._clock.now()
        rows: Sequence[BrowserSession] = self._session.scalars(
            sa.select(BrowserSession)
            .where(
                BrowserSession.account_id == account_id,
                BrowserSession.revoked_at.is_(None),
                BrowserSession.absolute_expires_at > now,
                BrowserSession.inactivity_expires_at > now,
            )
            .order_by(BrowserSession.created_at)
        ).all()
        return list(rows)

    def revoke_session(
        self,
        session_id: uuid.UUID,
        *,
        reason: str = SessionRevokeReason.USER_LOGOUT.value,
    ) -> bool:
        """Revoke one session server-side. Idempotent."""
        now = self._clock.now()
        browser_session = self._session.get(BrowserSession, session_id)
        if browser_session is None or browser_session.revoked_at is not None:
            return False
        browser_session.revoked_at = now
        browser_session.revoke_reason = reason
        self._session.flush()
        self._audit.record(
            audit_events.SESSION_REVOKED,
            account_id=browser_session.account_id,
            actor_type="customer",
            entity_type="browser_session",
            entity_id=browser_session.id,
            payload={"revoke_reason": reason},
        )
        return True

    def revoke_all_sessions(
        self,
        account_id: uuid.UUID,
        *,
        reason: str = SessionRevokeReason.USER_LOGOUT_ALL.value,
        except_session_id: Optional[uuid.UUID] = None,
    ) -> int:
        """Revoke every live session for an account, server-side.

        Deleting the caller's cookie is not logout-all: the other devices still
        hold valid tokens. Revocation must happen in the database, which is why
        this issues an UPDATE rather than touching any cookie.
        """
        now = self._clock.now()
        statement = (
            sa.update(BrowserSession)
            .where(
                BrowserSession.account_id == account_id,
                BrowserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
        if except_session_id is not None:
            statement = statement.where(BrowserSession.id != except_session_id)
        result = self._session.execute(statement)
        self._session.flush()
        revoked = int(result.rowcount or 0)
        self._audit.record(
            audit_events.SESSION_LOGOUT_ALL,
            account_id=account_id,
            actor_type="customer",
            entity_type="customer_account",
            entity_id=account_id,
            payload={"revoke_reason": reason, "revoked_count": revoked},
        )
        return revoked
