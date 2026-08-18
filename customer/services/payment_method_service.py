"""Own-name payment-method registration without charge or subscription work."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock
from customer.domain.enums import (
    AccountStatus,
    CommandIdempotencyStatus,
    PaymentMethodStatus,
)
from customer.domain.errors import (
    AccountNotActive,
    CustomerAuthError,
    IdempotencyKeyConflict,
    IdentityVerificationFailed,
    PaymentMethodNotFound,
    PaymentMethodVerificationFailed,
    PaymentProviderStateUnknown,
    PaymentProviderUnavailable,
)
from customer.persistence.models import (
    CommandIdempotency,
    CustomerAccount,
    PaymentMethod,
    PersonIdentity,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.payment_providers import (
    PaymentMethodProvider,
    PaymentRegistrationStatus,
)


PAYMENT_REGISTRATION_COMMAND = "payment_method.register"
_SAFE_PROVIDER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_BRAND = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


@dataclass(frozen=True)
class InitiatedPaymentRegistration:
    registration_reference: str
    replayed: bool
    completed: bool


@dataclass(frozen=True)
class RegisteredPaymentMethod:
    payment_method: PaymentMethod
    replayed: bool


class PaymentMethodService:
    """Provider-neutral Stage 3 coordinator.

    Provider success and own-name verification are both required before a
    usable PaymentMethod is inserted.  This service never creates a trial,
    subscription, billing attempt, conversion snapshot, or charge.
    """

    def __init__(
        self,
        session: Session,
        clock: Clock,
        provider: PaymentMethodProvider,
        audit=None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._provider = provider
        self._audit = audit or AuditService(session, clock)

    def initiate_registration(
        self,
        *,
        account_id: uuid.UUID,
        idempotency_key: str,
        replacement_payment_method_id: Optional[uuid.UUID] = None,
    ) -> InitiatedPaymentRegistration:
        account = self._verified_account(account_id)
        self._replacement_for_account(account.id, replacement_payment_method_id)
        key = _idempotency_key(idempotency_key)
        fingerprint = _fingerprint(
            account.id, replacement_payment_method_id, self._provider.name
        )

        existing = self._command(key)
        if existing is not None:
            self._assert_same_command(existing, account.id, fingerprint)
            if not existing.result_reference:
                raise PaymentProviderStateUnknown("registration has no provider reference")
            return InitiatedPaymentRegistration(
                registration_reference=existing.result_reference,
                replayed=True,
                completed=existing.status == CommandIdempotencyStatus.COMPLETED.value,
            )

        try:
            started = self._provider.start_registration(
                account_reference=str(account.id), idempotency_key=key
            )
        except CustomerAuthError:
            raise
        except Exception:
            raise PaymentProviderUnavailable("payment provider initiation failed")

        registration_reference = _bounded_reference(
            started.registration_reference, 120, "registration reference"
        )
        now = self._clock.now()
        command = CommandIdempotency(
            account_id=account.id,
            command=PAYMENT_REGISTRATION_COMMAND,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            status=CommandIdempotencyStatus.IN_PROGRESS.value,
            result_reference=registration_reference,
            created_at=now,
            updated_at=now,
        )
        self._session.add(command)
        self._session.flush()
        return InitiatedPaymentRegistration(
            registration_reference=registration_reference,
            replayed=False,
            completed=False,
        )

    def finalize_registration(
        self,
        *,
        account_id: uuid.UUID,
        idempotency_key: str,
        registration_reference: str,
        replacement_payment_method_id: Optional[uuid.UUID] = None,
    ) -> RegisteredPaymentMethod:
        account = self._verified_account(account_id)
        replacement = self._replacement_for_account(
            account.id, replacement_payment_method_id
        )
        key = _idempotency_key(idempotency_key)
        fingerprint = _fingerprint(
            account.id, replacement_payment_method_id, self._provider.name
        )
        command = self._command(key)
        if command is None:
            raise PaymentMethodNotFound("payment registration was not initiated")
        self._assert_same_command(command, account.id, fingerprint)

        reference = _bounded_reference(
            registration_reference, 120, "registration reference"
        )
        if command.result_reference != reference:
            raise IdempotencyKeyConflict("registration reference does not match command")

        try:
            result = self._provider.verify_registration(
                registration_reference=reference
            )
        except CustomerAuthError:
            raise
        except Exception:
            raise PaymentProviderUnavailable("payment provider verification failed")

        if result.provider != self._provider.name:
            raise PaymentProviderStateUnknown("provider identity mismatch")
        if result.registration_reference != reference:
            raise PaymentProviderStateUnknown("provider registration reference mismatch")

        provider = _provider_name(result.provider)
        state = getattr(result.status, "value", result.status)
        if state == PaymentRegistrationStatus.PENDING.value:
            raise PaymentProviderStateUnknown("provider registration is not final")
        if state != PaymentRegistrationStatus.SUCCEEDED.value:
            raise PaymentMethodVerificationFailed("provider rejected payment method")
        if not result.own_name_verified:
            raise PaymentMethodVerificationFailed("own-name verification failed")

        billing_key = _billing_key_reference(result.billing_key_reference)
        own_name_reference = _bounded_reference(
            result.own_name_verification_reference,
            255,
            "own-name verification reference",
        )
        brand = _safe_brand(result.card_brand)
        last4 = _safe_last4(result.card_last4)

        existing = self._session.scalar(
            sa.select(PaymentMethod).where(
                PaymentMethod.provider == provider,
                PaymentMethod.billing_key_reference == billing_key,
            )
        )
        if existing is not None:
            if existing.account_id != account.id:
                raise PaymentMethodVerificationFailed(
                    "provider credential is already bound to another account"
                )
            if (
                existing.status != PaymentMethodStatus.ACTIVE.value
                or not existing.own_name_verified
            ):
                raise PaymentMethodVerificationFailed(
                    "existing provider credential is not usable"
                )
            self._complete_command(command)
            return RegisteredPaymentMethod(payment_method=existing, replayed=True)

        defaults = list(
            self._session.scalars(
                sa.select(PaymentMethod)
                .where(
                    PaymentMethod.account_id == account.id,
                    PaymentMethod.is_default.is_(True),
                )
                .with_for_update()
            ).all()
        )
        for current in defaults:
            current.is_default = False
            current.updated_at = self._clock.now()
        if defaults:
            self._session.flush()

        now = self._clock.now()
        method = PaymentMethod(
            account_id=account.id,
            provider=provider,
            billing_key_reference=billing_key,
            card_brand=brand,
            card_last4=last4,
            display_label=_display_label(brand, last4),
            own_name_verified=True,
            own_name_verified_at=now,
            own_name_verification_reference=own_name_reference,
            status=PaymentMethodStatus.ACTIVE.value,
            is_default=True,
            created_at=now,
            updated_at=now,
        )
        self._session.add(method)
        self._session.flush()
        self._audit.record(
            audit_events.PAYMENT_METHOD_REGISTERED,
            account_id=account.id,
            actor_type="customer",
            entity_type="payment_method",
            entity_id=method.id,
            payload={
                "provider": provider,
                "replacement": replacement is not None,
            },
        )
        self._complete_command(command)
        return RegisteredPaymentMethod(payment_method=method, replayed=False)

    def default_payment_method(self, account_id: uuid.UUID) -> PaymentMethod:
        self._verified_account(account_id)
        method = self._session.scalar(
            sa.select(PaymentMethod).where(
                PaymentMethod.account_id == account_id,
                PaymentMethod.status == PaymentMethodStatus.ACTIVE.value,
                PaymentMethod.is_default.is_(True),
            )
        )
        if method is None:
            raise PaymentMethodNotFound("default payment method is unavailable")
        return method

    def _verified_account(self, account_id: uuid.UUID) -> CustomerAccount:
        account = self._session.get(CustomerAccount, account_id)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise AccountNotActive("account is not active")
        person = self._session.get(PersonIdentity, account.person_id)
        if (
            person is None
            or not person.adult_verified
            or person.adult_verified_at is None
        ):
            raise IdentityVerificationFailed("verified adult identity is required")
        return account

    def _replacement_for_account(
        self,
        account_id: uuid.UUID,
        payment_method_id: Optional[uuid.UUID],
    ) -> Optional[PaymentMethod]:
        if payment_method_id is None:
            return None
        method = self._session.get(PaymentMethod, payment_method_id)
        if (
            method is None
            or method.account_id != account_id
            or method.status != PaymentMethodStatus.ACTIVE.value
        ):
            raise PaymentMethodNotFound("replacement target is unavailable")
        return method

    def _command(self, key: str) -> Optional[CommandIdempotency]:
        return self._session.scalar(
            sa.select(CommandIdempotency).where(
                CommandIdempotency.command == PAYMENT_REGISTRATION_COMMAND,
                CommandIdempotency.idempotency_key == key,
            )
        )

    @staticmethod
    def _assert_same_command(
        command: CommandIdempotency,
        account_id: uuid.UUID,
        fingerprint: str,
    ) -> None:
        if command.account_id != account_id or command.request_fingerprint != fingerprint:
            raise IdempotencyKeyConflict(
                "idempotency key belongs to a different payment command"
            )

    def _complete_command(self, command: CommandIdempotency) -> None:
        now = self._clock.now()
        command.status = CommandIdempotencyStatus.COMPLETED.value
        command.completed_at = now
        command.updated_at = now
        self._session.flush()


def _fingerprint(
    account_id: uuid.UUID,
    replacement_payment_method_id: Optional[uuid.UUID],
    provider: str,
) -> str:
    value = "|".join(
        (
            str(account_id),
            str(replacement_payment_method_id or "none"),
            _provider_name(provider),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _idempotency_key(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 200:
        raise IdempotencyKeyConflict("a bounded Idempotency-Key is required")
    return normalized


def _provider_name(value: str) -> str:
    normalized = (value or "").strip()
    if not _SAFE_PROVIDER.fullmatch(normalized):
        raise PaymentProviderStateUnknown("provider identity is invalid")
    return normalized


def _bounded_reference(value: Optional[str], maximum: int, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise PaymentProviderStateUnknown("{0} is invalid".format(label))
    return normalized


def _safe_brand(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if (
        not normalized
        or not _SAFE_BRAND.fullmatch(normalized)
        or not any(character.isalpha() for character in normalized)
        or sum(character.isdigit() for character in normalized) > 4
    ):
        raise PaymentProviderStateUnknown("card brand metadata is invalid")
    return normalized


def _safe_last4(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) != 4 or not normalized.isdigit():
        raise PaymentProviderStateUnknown("card display digits are invalid")
    return normalized


def _billing_key_reference(value: Optional[str]) -> str:
    normalized = _bounded_reference(value, 255, "billing key reference")
    compact = normalized.replace(" ", "").replace("-", "")
    if compact.isdigit() and 12 <= len(compact) <= 19:
        raise PaymentProviderStateUnknown("billing key resembles prohibited card data")
    return normalized


def _display_label(brand: Optional[str], last4: Optional[str]) -> Optional[str]:
    if brand and last4:
        return "{0} •••• {1}".format(brand, last4)
    if brand:
        return brand
    if last4:
        return "•••• {0}".format(last4)
    return None
