"""Identity verification, account binding, and phone change.

Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 1, 2, 9, 11

Three rules drive everything here:

  1. The service is absolutely 19+ (sec. 1). An under-19 result creates no
     account, no trial, no payment method - and is recorded as
     `age_not_eligible`, not as a generic failure.
  2. The stable person key (DI or equivalent) is the identity (sec. 2). Phone
     numbers and email addresses are contact channels that change; they never
     identify a person and never merge two people.
  3. One verified person owns at most one active account (sec. 2). A duplicate
     signup is routed to recovery, never to a second account.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock
from customer.domain.enums import (
    AccountStatus,
    IdentityVerificationPurpose,
    IdentityVerificationStatus,
)
from customer.domain.errors import (
    AgeNotEligible,
    IdentityAlreadyRegistered,
    IdentityMismatch,
    IdentityVerificationFailed,
)
from customer.persistence.models import (
    CustomerAccount,
    IdentityVerification,
    PersonIdentity,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.providers import IdentityVerificationResult


@dataclass(frozen=True)
class VerifiedIdentity:
    """A stored, adult-verified identity ready to be bound to an account."""

    verification_id: uuid.UUID
    person_id: uuid.UUID
    stable_key: str
    mobile_e164: Optional[str]


class IdentityService:
    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)

    # -- recording a provider result ----------------------------------------

    def record_verification_result(
        self,
        result: IdentityVerificationResult,
        *,
        purpose: str,
        account_id: Optional[uuid.UUID] = None,
    ) -> IdentityVerification:
        """Persist a normalised provider outcome.

        Always stored, including failures and under-19 outcomes, because the
        adult gate has to be auditable after the fact. Never stores a raw
        provider payload.
        """
        now = self._clock.now()

        if result.failed:
            status = IdentityVerificationStatus.FAILED.value
        elif result.adult_verified is False:
            status = IdentityVerificationStatus.AGE_NOT_ELIGIBLE.value
        elif result.adult_verified is True and result.stable_key:
            status = IdentityVerificationStatus.VERIFIED.value
        else:
            status = IdentityVerificationStatus.PENDING.value

        verification = IdentityVerification(
            purpose=purpose,
            status=status,
            provider=result.provider,
            provider_reference=result.provider_reference,
            idv_stable_key=result.stable_key
            if status == IdentityVerificationStatus.VERIFIED.value
            else None,
            adult_verified=result.adult_verified,
            mobile_e164=result.mobile_e164,
            account_id=account_id,
            created_at=now,
            updated_at=now,
            completed_at=None
            if status == IdentityVerificationStatus.PENDING.value
            else (result.completed_at or now),
        )
        self._session.add(verification)
        self._session.flush()

        self._record(
            event_type="{0}{1}".format(audit_events.IDENTITY_VERIFICATION_PREFIX, status),
            account_id=account_id,
            payload={"purpose": purpose, "provider": result.provider},
        )
        return verification

    def assert_eligible(self, verification: IdentityVerification) -> None:
        """Fail closed on anything that is not an adult-verified success."""
        if verification.status == IdentityVerificationStatus.AGE_NOT_ELIGIBLE.value:
            raise AgeNotEligible("verified age is below the 19+ minimum")
        if verification.status != IdentityVerificationStatus.VERIFIED.value:
            raise IdentityVerificationFailed(
                "identity verification is {0}".format(verification.status)
            )

    # -- signup -------------------------------------------------------------

    def resolve_person_for_signup(
        self, verification: IdentityVerification
    ) -> VerifiedIdentity:
        """Turn a verified signup into a person, enforcing one-active-account.

        Reuses the existing `person_identity` row when the same human returns
        after withdrawal - the person is the same person, only the account
        ended.
        """
        self.assert_eligible(verification)
        now = self._clock.now()
        stable_key = verification.idv_stable_key

        person = self._session.scalar(
            sa.select(PersonIdentity).where(
                PersonIdentity.idv_stable_key == stable_key
            )
        )
        if person is None:
            person = PersonIdentity(
                idv_stable_key=stable_key,
                idv_provider=verification.provider,
                idv_reference=verification.provider_reference,
                adult_verified=True,
                adult_verified_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(person)
            self._session.flush()

        existing_active = self._session.scalar(
            sa.select(CustomerAccount).where(
                CustomerAccount.person_id == person.id,
                CustomerAccount.status == AccountStatus.ACTIVE.value,
            )
        )
        if existing_active is not None:
            self._record(
                event_type=audit_events.IDENTITY_DUPLICATE_SIGNUP_BLOCKED,
                account_id=existing_active.id,
                payload={"outcome": "routed_to_recovery"},
            )
            raise IdentityAlreadyRegistered(
                "this verified person already has an active account; "
                "use account recovery"
            )

        verification.person_id = person.id
        verification.consumed_at = now
        self._session.flush()

        return VerifiedIdentity(
            verification_id=verification.id,
            person_id=person.id,
            stable_key=stable_key,
            mobile_e164=verification.mobile_e164,
        )

    # -- phone change -------------------------------------------------------

    def apply_phone_change(
        self,
        *,
        account_id: uuid.UUID,
        verification: IdentityVerification,
    ) -> CustomerAccount:
        """Replace the registered mobile after fresh full IDV.

        The comparison is on the stable person key, never on the phone number
        itself. If the new verification resolves to a different person, this is
        an attempted account takeover, not a phone update - reject with
        IDENTITY_MISMATCH and leave ownership untouched (sec. 2, sec. 9).
        """
        self.assert_eligible(verification)
        now = self._clock.now()

        account = self._session.get(CustomerAccount, account_id)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise IdentityVerificationFailed("account is not active")

        if verification.purpose != IdentityVerificationPurpose.PHONE_CHANGE.value:
            raise IdentityVerificationFailed(
                "verification was not issued for a phone change"
            )
        if verification.consumed_at is not None:
            raise IdentityVerificationFailed("verification already consumed")

        person = self._session.get(PersonIdentity, account.person_id)
        if person is None or person.idv_stable_key != verification.idv_stable_key:
            self._record(
                event_type=audit_events.IDENTITY_PHONE_CHANGE_MISMATCH,
                account_id=account_id,
                payload={"outcome": "rejected"},
            )
            raise IdentityMismatch(
                "verification resolved to a different person than the account owner"
            )

        account.mobile_e164 = verification.mobile_e164
        account.updated_at = now
        verification.account_id = account_id
        verification.person_id = person.id
        verification.consumed_at = now
        self._session.flush()

        self._record(
            event_type=audit_events.IDENTITY_PHONE_CHANGED,
            account_id=account_id,
            payload={"outcome": "applied"},
        )
        return account

    # -- audit --------------------------------------------------------------

    def _record(self, *, event_type: str, account_id, payload) -> None:
        """Append a security event through the shared audit choke point."""
        self._audit.record(
            event_type, account_id=account_id, entity_type="identity", payload=payload
        )
