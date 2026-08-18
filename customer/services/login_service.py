"""Passwordless routine-login orchestration.

The public transport returns the same accepted shape for known and unknown
contacts.  Unknown contacts receive an opaque, non-persisted challenge id and
cannot be verified; the internal audit still records that classification.
"""

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock
from customer.domain.enums import AccountStatus, AuthChallengeChannel, AuthChallengePurpose
from customer.domain.errors import LoginChallengeInvalid
from customer.persistence.models import CustomerAccount
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.challenge_service import ChallengeService


AUTH_LOGIN_CHALLENGE_UNKNOWN_CONTACT = "auth.login_challenge_unknown_contact"


@dataclass(frozen=True)
class LoginChallengeRequest:
    challenge_id: uuid.UUID
    known_account: bool


class LoginService:
    def __init__(self, session: Session, clock: Clock, challenges: ChallengeService) -> None:
        self._session = session
        self._clock = clock
        self._challenges = challenges
        self._audit = AuditService(session, clock)

    def issue_login_challenge(self, *, channel: str, target: str) -> LoginChallengeRequest:
        account = self._find_active_account(channel=channel, target=target)
        if account is None:
            self._audit.record(
                AUTH_LOGIN_CHALLENGE_UNKNOWN_CONTACT,
                entity_type="auth_challenge",
                payload={"channel": channel, "outcome": "unknown_or_ambiguous"},
            )
            return LoginChallengeRequest(challenge_id=uuid.uuid4(), known_account=False)

        issued = self._challenges.issue_challenge(
            purpose=AuthChallengePurpose.LOGIN.value,
            channel=channel,
            target=target,
            account_id=account.id,
        )
        return LoginChallengeRequest(challenge_id=issued.challenge_id, known_account=True)

    def verify_login_challenge(
        self, *, channel: str, target: str, challenge_id: uuid.UUID, code: str
    ) -> CustomerAccount:
        account = self._find_active_account(channel=channel, target=target)
        if account is None:
            raise LoginChallengeInvalid("login contact is not uniquely registered")
        self._challenges.verify_and_consume(
            challenge_id=challenge_id,
            code=code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )
        return account

    def _find_active_account(self, *, channel: str, target: str):
        target = target.strip().lower()
        if channel == AuthChallengeChannel.EMAIL.value:
            rows = self._session.scalars(
                sa.select(CustomerAccount).where(
                    CustomerAccount.account_email == target,
                    CustomerAccount.status == AccountStatus.ACTIVE.value,
                )
            ).all()
        elif channel == AuthChallengeChannel.SMS.value:
            rows = self._session.scalars(
                sa.select(CustomerAccount).where(
                    CustomerAccount.mobile_e164 == target,
                    CustomerAccount.status == AccountStatus.ACTIVE.value,
                )
            ).all()
        else:
            raise LoginChallengeInvalid("unknown login channel")
        return rows[0] if len(rows) == 1 else None
