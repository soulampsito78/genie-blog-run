"""Explicit Stage 4 trial confirmation, with no billing or conversion work."""

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.catalog import (
    TRIAL_ELIGIBILITY_BLOCK_DAYS,
    TRIAL_PRODUCTS,
)
from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    AccountStatus,
    CommandIdempotencyStatus,
    DeliveryEmailStatus,
    EntitlementSource,
    PaymentMethodStatus,
    SubscriptionState,
)
from customer.domain.errors import (
    AccountNotActive,
    DeliveryEmailUnverified,
    IdempotencyKeyConflict,
    IdentityVerificationFailed,
    PaymentMethodRequired,
    TrialNotEligible,
    TrialNotFound,
)
from customer.domain.trial_calendar import first_delivery_date, trial_bounds
from customer.persistence.models import (
    CommandIdempotency,
    CustomerAccount,
    DeliveryEmail,
    Entitlement,
    PaymentMethod,
    PersonIdentity,
    Subscription,
    TrialEligibilityBlock,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService


TRIAL_START_COMMAND = "subscription.trial_start"


@dataclass(frozen=True)
class TrialResult:
    subscription: Subscription
    products: Tuple[str, ...]
    replayed: bool


class TrialService:
    """Create the one real free trial in one database transaction.

    No provider call is needed here: Stage 3 has already persisted the
    provider-authoritative own-name payment result.  This service creates no
    billing attempt, paid plan, subscription product, or conversion snapshot.
    """

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)

    def start_trial(
        self, *, account_id: uuid.UUID, idempotency_key: str
    ) -> TrialResult:
        account, person = self._verified_account_and_person(account_id)
        key = _idempotency_key(idempotency_key)
        fingerprint = _fingerprint(account.id)

        command = self._command(key)
        if command is not None:
            self._assert_same_command(command, account.id, fingerprint)
            if (
                command.status != CommandIdempotencyStatus.COMPLETED.value
                or not command.result_reference
            ):
                raise IdempotencyKeyConflict("trial confirmation is incomplete")
            subscription = self._subscription_reference(
                command.result_reference, account.id
            )
            return self._result(subscription, replayed=True)

        prior_trial = self._session.scalar(
            sa.select(Subscription)
            .where(
                Subscription.account_id == account.id,
                Subscription.trial_start_at.is_not(None),
            )
            .order_by(Subscription.created_at.asc())
            .with_for_update()
        )
        if prior_trial is not None:
            self._record_completed_command(key, fingerprint, account.id, prior_trial.id)
            return self._result(prior_trial, replayed=True)

        any_subscription = self._session.scalar(
            sa.select(Subscription.id)
            .where(Subscription.account_id == account.id)
            .limit(1)
        )
        if any_subscription is not None:
            raise TrialNotEligible("an existing subscription makes trial unavailable")

        now = ensure_utc(self._clock.now())
        block = self._session.scalar(
            sa.select(TrialEligibilityBlock)
            .where(TrialEligibilityBlock.idv_stable_key == person.idv_stable_key)
            .with_for_update()
        )
        if block is not None and ensure_utc(block.block_expires_at) > now:
            raise TrialNotEligible("verified person is inside the trial block window")

        self._usable_default_payment_method(account.id)
        self._verified_delivery_email(account.id)

        trial_start_at, trial_end_at = trial_bounds(now)
        delivery_start_date = first_delivery_date(trial_start_at)
        subscription = Subscription(
            account_id=account.id,
            state=SubscriptionState.TRIALING.value,
            trial_start_at=trial_start_at,
            trial_end_at=trial_end_at,
            delivery_start_date=delivery_start_date,
            created_at=now,
            updated_at=now,
        )
        self._session.add(subscription)
        self._session.flush()

        for product_code in sorted(TRIAL_PRODUCTS):
            self._session.add(
                Entitlement(
                    account_id=account.id,
                    subscription_id=subscription.id,
                    product_code=product_code,
                    source=EntitlementSource.TRIAL.value,
                    plan_code=None,
                    price_version=None,
                    effective_from=delivery_start_date,
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        block_expires_at = trial_end_at + dt.timedelta(
            days=TRIAL_ELIGIBILITY_BLOCK_DAYS
        )
        if block is None:
            block = TrialEligibilityBlock(
                idv_stable_key=person.idv_stable_key,
                trial_started_at=trial_start_at,
                trial_ended_at=trial_end_at,
                block_expires_at=block_expires_at,
                created_at=now,
            )
            self._session.add(block)
        else:
            # Expired evidence is outside its retention window and may become
            # the next eligibility window without creating parallel authority.
            block.trial_started_at = trial_start_at
            block.trial_ended_at = trial_end_at
            block.block_expires_at = block_expires_at

        self._session.flush()
        self._record_completed_command(key, fingerprint, account.id, subscription.id)
        self._audit.record(
            audit_events.TRIAL_STARTED,
            account_id=account.id,
            subscription_id=subscription.id,
            actor_type="customer",
            entity_type="subscription",
            entity_id=subscription.id,
            payload={
                "duration_days": 14,
                "product_count": len(TRIAL_PRODUCTS),
                "delivery_start_date": delivery_start_date.isoformat(),
                "automatic_paid_conversion": False,
            },
        )
        return self._result(subscription, replayed=False)

    def current_trial(self, account_id: uuid.UUID) -> TrialResult:
        self._verified_account_and_person(account_id, lock=False)
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(
                Subscription.account_id == account_id,
                Subscription.trial_start_at.is_not(None),
            )
            .order_by(Subscription.created_at.desc())
        )
        if subscription is None:
            raise TrialNotFound("trial is unavailable")
        return self._result(subscription, replayed=True)

    def _verified_account_and_person(
        self, account_id: uuid.UUID, *, lock: bool = True
    ) -> Tuple[CustomerAccount, PersonIdentity]:
        query = sa.select(CustomerAccount).where(CustomerAccount.id == account_id)
        if lock:
            query = query.with_for_update()
        account = self._session.scalar(query)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise AccountNotActive("account is not active")
        person_query = sa.select(PersonIdentity).where(
            PersonIdentity.id == account.person_id
        )
        if lock:
            person_query = person_query.with_for_update()
        person = self._session.scalar(person_query)
        if (
            person is None
            or not person.adult_verified
            or person.adult_verified_at is None
            or not person.idv_stable_key
        ):
            raise IdentityVerificationFailed("verified adult identity is required")
        return account, person

    def _usable_default_payment_method(self, account_id: uuid.UUID) -> PaymentMethod:
        method = self._session.scalar(
            sa.select(PaymentMethod)
            .where(
                PaymentMethod.account_id == account_id,
                PaymentMethod.status == PaymentMethodStatus.ACTIVE.value,
                PaymentMethod.is_default.is_(True),
                PaymentMethod.own_name_verified.is_(True),
                PaymentMethod.own_name_verified_at.is_not(None),
            )
            .with_for_update()
        )
        if method is None or not method.billing_key_reference.strip():
            raise PaymentMethodRequired("usable own-name default payment method required")
        return method

    def _verified_delivery_email(self, account_id: uuid.UUID) -> DeliveryEmail:
        rows = list(
            self._session.scalars(
                sa.select(DeliveryEmail)
                .where(DeliveryEmail.account_id == account_id)
                .with_for_update()
            ).all()
        )
        active = [row for row in rows if row.status == DeliveryEmailStatus.ACTIVE.value]
        if active:
            if len(active) != 1 or active[0].verified_at is None:
                raise DeliveryEmailUnverified("verified delivery email required")
            return active[0]
        # Signup owns initial materialization from the consumed ownership
        # challenge. Trial confirmation may use that evidence, never invent it.
        raise DeliveryEmailUnverified("verified delivery email required")

    def _command(self, key: str) -> Optional[CommandIdempotency]:
        return self._session.scalar(
            sa.select(CommandIdempotency).where(
                CommandIdempotency.command == TRIAL_START_COMMAND,
                CommandIdempotency.idempotency_key == key,
            )
        )

    @staticmethod
    def _assert_same_command(command, account_id, fingerprint) -> None:
        if command.account_id != account_id or command.request_fingerprint != fingerprint:
            raise IdempotencyKeyConflict(
                "idempotency key belongs to a different trial command"
            )

    def _record_completed_command(
        self, key: str, fingerprint: str, account_id: uuid.UUID, subscription_id: uuid.UUID
    ) -> None:
        now = ensure_utc(self._clock.now())
        self._session.add(
            CommandIdempotency(
                account_id=account_id,
                command=TRIAL_START_COMMAND,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                status=CommandIdempotencyStatus.COMPLETED.value,
                result_reference=str(subscription_id),
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )
        self._session.flush()

    def _subscription_reference(
        self, reference: str, account_id: uuid.UUID
    ) -> Subscription:
        try:
            subscription_id = uuid.UUID(reference)
        except (TypeError, ValueError):
            raise IdempotencyKeyConflict("trial result reference is invalid")
        subscription = self._session.get(Subscription, subscription_id)
        if subscription is None or subscription.account_id != account_id:
            raise IdempotencyKeyConflict("trial result reference is unavailable")
        return subscription

    def _result(self, subscription: Subscription, *, replayed: bool) -> TrialResult:
        products = tuple(
            sorted(
                self._session.scalars(
                    sa.select(Entitlement.product_code).where(
                        Entitlement.subscription_id == subscription.id,
                        Entitlement.source == EntitlementSource.TRIAL.value,
                    )
                ).all()
            )
        )
        if set(products) != set(TRIAL_PRODUCTS):
            raise TrialNotEligible("trial entitlement state is incomplete")
        return TrialResult(subscription=subscription, products=products, replayed=replayed)


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 200:
        raise IdempotencyKeyConflict("invalid idempotency key")
    return normalized


def _fingerprint(account_id: uuid.UUID) -> str:
    return hashlib.sha256(
        "trial-start-v1:{0}".format(account_id).encode("utf-8")
    ).hexdigest()
