"""Customer account creation and deterministic onboarding projection.

This service deliberately stops after signup stages 1--2.  It never creates a
payment method, trial, paid-plan snapshot, or subscription; those are later
phase operations with their own evidence requirements.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock
from customer.domain.enums import AccountStatus, PaymentMethodStatus
from customer.domain.errors import IdentityAlreadyRegistered, IdentityVerificationFailed
from customer.persistence.models import (
    CustomerAccount,
    IdentityVerification,
    PaymentMethod,
    Subscription,
)
from customer.services.identity_service import IdentityService


@dataclass(frozen=True)
class SignupCompletion:
    account: Optional[CustomerAccount]
    existing_account_recovery_required: bool


class OnboardingService:
    """Coordinates the account-creation half of the four-stage signup."""

    def __init__(self, session: Session, clock: Clock, identity: IdentityService) -> None:
        self._session = session
        self._clock = clock
        self._identity = identity

    def complete_account_signup(
        self, *, verification: IdentityVerification, account_email: str
    ) -> SignupCompletion:
        """Create exactly one active account after IDV and email proof.

        The caller consumes the email-ownership challenge in the same request
        transaction before calling this method.  A duplicate DI is a normal
        recovery outcome rather than an exception that would roll back the
        duplicate-signup audit event.
        """
        normalized_email = account_email.strip().lower()
        if not _is_normalized_email(normalized_email):
            raise IdentityVerificationFailed("account email is invalid")

        try:
            verified = self._identity.resolve_person_for_signup(verification)
        except IdentityAlreadyRegistered:
            return SignupCompletion(account=None, existing_account_recovery_required=True)

        account = CustomerAccount(
            person_id=verified.person_id,
            account_email=normalized_email,
            mobile_e164=verified.mobile_e164,
            status=AccountStatus.ACTIVE.value,
            created_at=self._clock.now(),
            updated_at=self._clock.now(),
        )
        self._session.add(account)
        self._session.flush()
        return SignupCompletion(account=account, existing_account_recovery_required=False)

    def status_for_identity(self, verification: IdentityVerification) -> str:
        """Return the next real stage for a pre-account verification."""
        self._identity.assert_eligible(verification)
        return "account_email_verification_required"

    def status_for_account(self, account_id: uuid.UUID) -> str:
        """Project only states supported by persisted evidence."""
        active_payment = self._session.scalar(
            sa.select(PaymentMethod.id).where(
                PaymentMethod.account_id == account_id,
                PaymentMethod.status == PaymentMethodStatus.ACTIVE.value,
                PaymentMethod.own_name_verified.is_(True),
            )
        )
        if active_payment is None:
            return "payment_method_registration_required"

        subscription = self._session.scalar(
            sa.select(Subscription.id).where(Subscription.account_id == account_id)
        )
        if subscription is None:
            return "trial_start_confirmation_required"
        return "onboarding_complete"


def _is_normalized_email(value: str) -> bool:
    """Minimal transport-independent format gate; DB remains authoritative."""
    local, separator, domain = value.partition("@")
    return bool(separator and local and domain and "." in domain and " " not in value)
