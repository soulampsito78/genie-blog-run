"""Verification-challenge issuance and consumption.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 3, 5, 8

Threat model this service is written against:

  replay              - a verified challenge is CONSUMED atomically; a second
                        use finds `status='consumed'` and fails closed.
  brute force         - wrong attempts increment under a row lock and the
                        challenge LOCKS permanently at `max_attempts`.
  cross-purpose reuse - `purpose` is bound into the row and re-checked, so a
                        `login` code cannot authorize a `withdrawal`.
  cross-account reuse - `account_id` and `target` are both re-checked.
  flooding            - a cooldown bounds re-issuance per target+purpose.

Plaintext codes exist only in memory, are handed to the sender port, and are
never persisted, logged, or returned in any error.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain import auth_policy
from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import AuthChallengeStatus
from customer.domain.errors import ChallengeRateLimited, LoginChallengeInvalid
from customer.domain.email import normalize_email
from customer.domain.security import issue_verification_code, verification_code_matches
from customer.persistence.models import AuthChallenge
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService


@dataclass(frozen=True)
class IssuedChallenge:
    """Result of issuing a challenge.

    `code` is the plaintext, present so the caller can hand it to a delivery
    provider. It is not stored and must not be logged or returned to a client.
    """

    challenge_id: uuid.UUID
    code: str
    expires_at: dt.datetime


class ChallengeService:
    def __init__(self, session: Session, clock: Clock, sender=None, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._sender = sender
        self._audit = audit or AuditService(session, clock)

    # -- issuance -----------------------------------------------------------

    def issue_challenge(
        self,
        *,
        purpose: str,
        channel: str,
        target: str,
        account_id: Optional[uuid.UUID] = None,
        max_attempts: int = auth_policy.CHALLENGE_MAX_ATTEMPTS,
        ttl: dt.timedelta = auth_policy.CHALLENGE_TTL,
    ) -> IssuedChallenge:
        """Issue a single-use verification code.

        Any still-pending challenge for the same target+purpose is expired
        first, which both enforces the partial unique index and guarantees an
        attacker cannot accumulate several live codes for one action.
        """
        now = self._clock.now()
        target = _normalize_target(channel, target)

        self._enforce_issue_cooldown(purpose=purpose, target=target, now=now)
        self._expire_pending(purpose=purpose, target=target, now=now)

        code, salt, code_hash = issue_verification_code()
        challenge = AuthChallenge(
            account_id=account_id,
            purpose=purpose,
            channel=channel,
            target=target,
            code_hash=code_hash,
            code_salt=salt,
            status=AuthChallengeStatus.PENDING.value,
            attempt_count=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
            expires_at=now + ttl,
        )
        self._session.add(challenge)
        self._session.flush()

        if self._sender is not None:
            self._sender.send(channel, target, code)

        # Purpose and channel only: the target is a contact address and the
        # code is a live credential, so neither is recorded.
        self._audit.record(
            audit_events.AUTH_CHALLENGE_ISSUED,
            account_id=account_id,
            entity_type="auth_challenge",
            entity_id=challenge.id,
            payload={"purpose": purpose, "channel": channel},
        )

        return IssuedChallenge(
            challenge_id=challenge.id, code=code, expires_at=challenge.expires_at
        )

    def _enforce_issue_cooldown(self, *, purpose: str, target: str, now) -> None:
        cutoff = now - auth_policy.CHALLENGE_ISSUE_COOLDOWN
        recent = self._session.scalar(
            sa.select(sa.func.count())
            .select_from(AuthChallenge)
            .where(
                AuthChallenge.target == target,
                AuthChallenge.purpose == purpose,
                AuthChallenge.created_at > cutoff,
            )
        )
        if recent:
            raise ChallengeRateLimited(
                "challenge for this target/purpose was issued within the cooldown"
            )

    def _expire_pending(self, *, purpose: str, target: str, now) -> None:
        self._session.execute(
            sa.update(AuthChallenge)
            .where(
                AuthChallenge.target == target,
                AuthChallenge.purpose == purpose,
                AuthChallenge.status == AuthChallengeStatus.PENDING.value,
            )
            .values(status=AuthChallengeStatus.EXPIRED.value, updated_at=now)
        )
        self._session.flush()

    # -- verification -------------------------------------------------------

    def verify_and_consume(
        self,
        *,
        challenge_id: uuid.UUID,
        code: str,
        purpose: str,
        account_id: Optional[uuid.UUID] = None,
        expected_target: Optional[str] = None,
    ) -> AuthChallenge:
        """Verify a code and consume the challenge in one atomic step.

        The row is locked with `SELECT ... FOR UPDATE` for the whole check, so
        two concurrent requests presenting the same correct code cannot both
        observe `pending` and both succeed. Verification and consumption are
        deliberately not separable by a caller: a "verified but unconsumed"
        window is exactly the replay gap this design removes.

        Every failure raises the same `LOGIN_CHALLENGE_INVALID` code, so the
        response cannot be used to distinguish a wrong code from an unknown
        challenge, an expired one, or someone else's.
        """
        now = self._clock.now()

        challenge = self._session.scalar(
            sa.select(AuthChallenge)
            .where(AuthChallenge.id == challenge_id)
            .with_for_update()
        )
        if challenge is None:
            raise LoginChallengeInvalid("no such challenge")

        # Purpose and account binding: a code is valid only for the exact
        # action and actor it was issued for.
        if challenge.purpose != purpose:
            raise LoginChallengeInvalid("challenge purpose mismatch")
        if account_id is not None and challenge.account_id != account_id:
            raise LoginChallengeInvalid("challenge account mismatch")
        if account_id is None and challenge.account_id is not None:
            raise LoginChallengeInvalid("challenge account mismatch")
        if (
            expected_target is not None
            and challenge.target
            != _normalize_target(challenge.channel, expected_target)
        ):
            # Compare before status/code mutation. A request for another
            # address must neither consume this proof nor reveal any address.
            raise LoginChallengeInvalid("challenge target mismatch")

        if challenge.status != AuthChallengeStatus.PENDING.value:
            raise LoginChallengeInvalid(
                "challenge is {0}".format(challenge.status)
            )

        if ensure_utc(challenge.expires_at) <= now:
            challenge.status = AuthChallengeStatus.EXPIRED.value
            challenge.updated_at = now
            self._session.flush()
            raise LoginChallengeInvalid("challenge expired")

        if not verification_code_matches(code, challenge.code_salt, challenge.code_hash):
            challenge.attempt_count += 1
            challenge.updated_at = now
            locked = challenge.attempt_count >= challenge.max_attempts
            if locked:
                challenge.status = AuthChallengeStatus.LOCKED.value
                challenge.locked_at = now
            self._session.flush()
            self._audit.record(
                audit_events.AUTH_CHALLENGE_LOCKED
                if locked
                else audit_events.AUTH_CHALLENGE_FAILED,
                account_id=challenge.account_id,
                entity_type="auth_challenge",
                entity_id=challenge.id,
                payload={
                    "purpose": challenge.purpose,
                    "attempt_count": challenge.attempt_count,
                },
            )
            raise LoginChallengeInvalid("verification code did not match")

        challenge.status = AuthChallengeStatus.CONSUMED.value
        challenge.verified_at = now
        challenge.consumed_at = now
        challenge.updated_at = now
        self._session.flush()
        self._audit.record(
            audit_events.AUTH_CHALLENGE_VERIFIED,
            account_id=challenge.account_id,
            entity_type="auth_challenge",
            entity_id=challenge.id,
            payload={"purpose": challenge.purpose, "channel": challenge.channel},
        )
        return challenge


def _normalize_target(channel: str, target: str) -> str:
    if channel == "email":
        return normalize_email(target)
    return str(target or "").strip().lower()
