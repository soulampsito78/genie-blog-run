"""Internal first paid-charge command for an explicitly confirmed conversion.

The command has two database transactions with the provider call between them:

1. lock and validate conversion authority, create one pending BillingAttempt,
   commit it;
2. call the provider with the attempt's stable idempotency key;
3. lock the same attempt and atomically apply the authoritative outcome.

This prevents a database transaction from spanning a network charge.  A crash
after step 1 is fail-closed: the pending attempt is treated as unknown and is
never blindly resubmitted.
"""

import calendar
import datetime as dt
import re
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, Tuple
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    BillingAttemptPurpose,
    BillingAttemptStatus,
    ConversionSnapshotStatus,
    DeliveryEmailStatus,
    EntitlementSource,
    PaymentMethodStatus,
    SubscriptionState,
)
from customer.domain.errors import FirstChargeConflict
from customer.persistence.models import (
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    ConversionSnapshot,
    ConversionSnapshotProduct,
    DeliveryEmail,
    Entitlement,
    PaymentMethod,
    Subscription,
    SubscriptionProduct,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.charge_providers import (
    ChargeOutcome,
    FirstChargeProvider,
    FirstChargeProviderResult,
    FirstChargeRequest,
)


KST = ZoneInfo("Asia/Seoul")
FIRST_CHARGE_PURPOSE = BillingAttemptPurpose.FIRST_CONVERSION_CHARGE.value


@dataclass(frozen=True)
class FirstChargeExecutionResult:
    status: str
    subscription_id: Optional[uuid.UUID]
    conversion_snapshot_id: Optional[uuid.UUID]
    billing_attempt_id: Optional[uuid.UUID] = None
    replayed: bool = False
    retry_required: bool = False
    reconciliation_required: bool = False


@dataclass(frozen=True)
class PreparedFirstCharge:
    result: FirstChargeExecutionResult
    request: Optional[FirstChargeRequest] = None


class FirstChargeService:
    """Transactional half of the internal first-charge executor."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)

    def prepare(
        self,
        *,
        conversion_snapshot_id: uuid.UUID,
        provider_name: str,
        explicit_retry: bool = False,
    ) -> PreparedFirstCharge:
        provider = _safe_provider_name(provider_name)
        snapshot = self._session.scalar(
            sa.select(ConversionSnapshot)
            .where(ConversionSnapshot.id == conversion_snapshot_id)
            .with_for_update()
        )
        if snapshot is None:
            return PreparedFirstCharge(
                FirstChargeExecutionResult("not_eligible", None, None)
            )
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.id == snapshot.subscription_id)
            .with_for_update()
        )
        if subscription is None or snapshot.status != ConversionSnapshotStatus.PENDING.value:
            return self._terminal_or_ineligible(snapshot, subscription)
        if (
            snapshot.account_id != subscription.account_id
            or subscription.trial_end_at is None
            or ensure_utc(snapshot.first_charge_at)
            != ensure_utc(subscription.trial_end_at)
        ):
            raise FirstChargeConflict("conversion charge authority is inconsistent")

        now = ensure_utc(self._clock.now())
        if now < ensure_utc(snapshot.first_charge_at):
            return PreparedFirstCharge(
                self._result("not_due", snapshot, subscription)
            )
        if subscription.state not in {
            SubscriptionState.CONVERSION_SCHEDULED.value,
            SubscriptionState.TRIAL_EXPIRED.value,
        }:
            return PreparedFirstCharge(
                self._result("not_eligible", snapshot, subscription)
            )

        attempts = list(
            self._session.scalars(
                sa.select(BillingAttempt)
                .where(
                    BillingAttempt.conversion_snapshot_id == snapshot.id,
                    BillingAttempt.purpose == FIRST_CHARGE_PURPOSE,
                )
                .order_by(BillingAttempt.attempt_no.asc())
                .with_for_update()
            ).all()
        )
        existing = self._existing_result(snapshot, subscription, attempts)
        if existing is not None:
            latest = attempts[-1]
            if latest.status in {
                BillingAttemptStatus.PENDING.value,
                BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
                BillingAttemptStatus.SUCCEEDED.value,
            }:
                return PreparedFirstCharge(existing)
            if latest.status == BillingAttemptStatus.FAILED.value and not explicit_retry:
                return PreparedFirstCharge(existing)

        if subscription.state == SubscriptionState.TRIAL_EXPIRED.value and not explicit_retry:
            return PreparedFirstCharge(
                self._result(
                    "retry_required",
                    snapshot,
                    subscription,
                    replayed=True,
                    retry_required=True,
                )
            )

        delivery_email = self._valid_delivery_email(snapshot.account_id)
        if delivery_email is None:
            self._expire_without_paid_delivery(subscription, now)
            self._record_block_once(snapshot, subscription, "delivery_email")
            return PreparedFirstCharge(
                self._result(
                    "blocked_delivery_email",
                    snapshot,
                    subscription,
                    retry_required=True,
                )
            )

        payment_method = self._usable_default_payment_method(snapshot.account_id)
        if payment_method is None:
            self._expire_without_paid_delivery(subscription, now)
            self._record_block_once(snapshot, subscription, "payment_method")
            return PreparedFirstCharge(
                self._result(
                    "blocked_payment_method",
                    snapshot,
                    subscription,
                    retry_required=True,
                )
            )
        if attempts and attempts[-1].status == BillingAttemptStatus.FAILED.value:
            if payment_method.id == attempts[-1].payment_method_id:
                self._record_block_once(snapshot, subscription, "payment_method_update")
                return PreparedFirstCharge(
                    self._result(
                        "payment_method_update_required",
                        snapshot,
                        subscription,
                        attempts[-1],
                        replayed=True,
                        retry_required=True,
                    )
                )

        products = self._snapshot_products(snapshot)
        if not products:
            raise FirstChargeConflict("confirmed product snapshot is empty")
        self._close_trial_entitlements(subscription, now)

        attempt_no = len(attempts) + 1
        period_start, period_end, _ = _billing_period(snapshot.first_charge_at)
        idempotency_key = "first-conversion:{0}:{1}".format(snapshot.id, attempt_no)
        attempt = BillingAttempt(
            account_id=snapshot.account_id,
            subscription_id=subscription.id,
            conversion_snapshot_id=snapshot.id,
            payment_method_id=payment_method.id,
            purpose=FIRST_CHARGE_PURPOSE,
            status=BillingAttemptStatus.PENDING.value,
            attempt_no=attempt_no,
            retry_offset_day=None,
            billing_period_start=period_start,
            billing_period_end=period_end,
            amount_krw=snapshot.price_krw,
            currency=snapshot.currency,
            plan_code=snapshot.plan_code,
            price_version=snapshot.price_version,
            idempotency_key=idempotency_key,
            provider=provider,
            scheduled_at=ensure_utc(snapshot.first_charge_at),
            created_at=now,
            updated_at=now,
        )
        self._session.add(attempt)
        self._session.flush()
        self._session.add(
            BillingEvent(
                billing_attempt_id=attempt.id,
                event_type="first_charge_prepared",
                occurred_at=now,
                detail={"attempt_no": attempt_no, "explicit_retry": explicit_retry},
                created_at=now,
            )
        )
        self._session.flush()
        request = FirstChargeRequest(
            attempt_id=str(attempt.id),
            conversion_snapshot_id=str(snapshot.id),
            account_id=str(snapshot.account_id),
            subscription_id=str(subscription.id),
            amount_krw=snapshot.price_krw,
            currency=snapshot.currency,
            plan_code=snapshot.plan_code,
            price_version=snapshot.price_version,
            idempotency_key=idempotency_key,
            billing_key_reference=payment_method.billing_key_reference,
        )
        return PreparedFirstCharge(
            self._result("prepared", snapshot, subscription, attempt), request
        )

    def apply_provider_result(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeProviderResult,
    ) -> FirstChargeExecutionResult:
        attempt_reference = self._session.get(BillingAttempt, billing_attempt_id)
        if (
            attempt_reference is None
            or attempt_reference.purpose != FIRST_CHARGE_PURPOSE
            or attempt_reference.conversion_snapshot_id is None
        ):
            raise FirstChargeConflict("first-charge attempt is unavailable")
        snapshot = self._session.scalar(
            sa.select(ConversionSnapshot)
            .where(
                ConversionSnapshot.id
                == attempt_reference.conversion_snapshot_id
            )
            .with_for_update()
        )
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.id == attempt_reference.subscription_id)
            .with_for_update()
        )
        attempt = self._session.scalar(
            sa.select(BillingAttempt)
            .where(BillingAttempt.id == billing_attempt_id)
            .with_for_update()
        )
        if snapshot is None or subscription is None:
            raise FirstChargeConflict("first-charge evidence is unavailable")

        if attempt.status != BillingAttemptStatus.PENDING.value:
            return self._replayed_provider_result(
                attempt, snapshot, subscription, provider_result
            )
        now = ensure_utc(self._clock.now())
        attempt.attempted_at = now
        attempt.updated_at = now

        if provider_result.outcome == ChargeOutcome.SUCCEEDED:
            transaction_reference = _safe_reference(
                provider_result.transaction_reference, required=True
            )
            attempt.status = BillingAttemptStatus.SUCCEEDED.value
            attempt.provider_transaction_reference = transaction_reference
            attempt.settled_at = now
            self._record_billing_event(
                attempt,
                "first_charge_succeeded",
                now,
                provider_result.provider_event_reference or transaction_reference,
                {"authoritative": True},
            )
            self._activate_paid_contract(subscription, snapshot, now)
            self._audit.record(
                audit_events.FIRST_CHARGE_SUCCEEDED,
                account_id=snapshot.account_id,
                subscription_id=subscription.id,
                entity_type="billing_attempt",
                entity_id=attempt.id,
                payload={
                    "plan_code": snapshot.plan_code,
                    "amount_krw": snapshot.price_krw,
                    "currency": snapshot.currency,
                    "product_count": len(self._snapshot_products(snapshot)),
                    "attempt_no": attempt.attempt_no,
                },
            )
            return self._result("succeeded", snapshot, subscription, attempt)

        if provider_result.outcome == ChargeOutcome.FAILED:
            failure_code = _safe_failure_code(provider_result.failure_code)
            attempt.status = BillingAttemptStatus.FAILED.value
            attempt.failure_code = failure_code
            attempt.failure_message = "payment provider definitively rejected first charge"
            self._record_billing_event(
                attempt,
                "first_charge_failed",
                now,
                provider_result.provider_event_reference,
                {"failure_code": failure_code, "retry_requires_customer_action": True},
            )
            self._expire_without_paid_delivery(subscription, now)
            self._audit.record(
                audit_events.FIRST_CHARGE_FAILED,
                account_id=snapshot.account_id,
                subscription_id=subscription.id,
                entity_type="billing_attempt",
                entity_id=attempt.id,
                payload={
                    "failure_code": failure_code,
                    "attempt_no": attempt.attempt_no,
                    "retry_required": True,
                    "grace_days": 0,
                    "delivery_enabled": False,
                },
            )
            return self._result(
                "failed", snapshot, subscription, attempt, retry_required=True
            )

        attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
        attempt.failure_code = "PROVIDER_STATE_UNKNOWN"
        attempt.failure_message = "provider outcome requires reconciliation"
        self._record_billing_event(
            attempt,
            "first_charge_provider_state_unknown",
            now,
            provider_result.provider_event_reference,
            {"reconciliation_required": True, "blind_retry_allowed": False},
        )
        self._close_trial_entitlements(subscription, now)
        self._audit.record(
            audit_events.FIRST_CHARGE_UNKNOWN,
            account_id=snapshot.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "reconciliation_required": True,
                "blind_retry_allowed": False,
                "delivery_enabled": False,
            },
        )
        return self._result(
            "provider_state_unknown",
            snapshot,
            subscription,
            attempt,
            reconciliation_required=True,
        )

    def _terminal_or_ineligible(self, snapshot, subscription) -> PreparedFirstCharge:
        if subscription is not None and snapshot.status == ConversionSnapshotStatus.APPLIED.value:
            attempt = self._session.scalar(
                sa.select(BillingAttempt).where(
                    BillingAttempt.conversion_snapshot_id == snapshot.id,
                    BillingAttempt.status == BillingAttemptStatus.SUCCEEDED.value,
                )
            )
            if attempt is not None:
                return PreparedFirstCharge(
                    self._result(
                        "succeeded", snapshot, subscription, attempt, replayed=True
                    )
                )
        return PreparedFirstCharge(
            FirstChargeExecutionResult(
                "not_eligible",
                subscription.id if subscription is not None else None,
                snapshot.id,
            )
        )

    def _existing_result(self, snapshot, subscription, attempts):
        if not attempts:
            return None
        latest = attempts[-1]
        if latest.status == BillingAttemptStatus.SUCCEEDED.value:
            return self._result("succeeded", snapshot, subscription, latest, replayed=True)
        if latest.status == BillingAttemptStatus.FAILED.value:
            return self._result(
                "failed",
                snapshot,
                subscription,
                latest,
                replayed=True,
                retry_required=True,
            )
        return self._result(
            "provider_state_unknown",
            snapshot,
            subscription,
            latest,
            replayed=True,
            reconciliation_required=True,
        )

    def _replayed_provider_result(self, attempt, snapshot, subscription, result):
        expected = {
            BillingAttemptStatus.SUCCEEDED.value: ChargeOutcome.SUCCEEDED,
            BillingAttemptStatus.FAILED.value: ChargeOutcome.FAILED,
            BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value:
                ChargeOutcome.PROVIDER_STATE_UNKNOWN,
        }.get(attempt.status)
        if expected != result.outcome:
            raise FirstChargeConflict("provider outcome conflicts with stored authority")
        if expected == ChargeOutcome.SUCCEEDED:
            reference = _safe_reference(result.transaction_reference, required=True)
            if reference != attempt.provider_transaction_reference:
                raise FirstChargeConflict("provider transaction replay differs")
        return self._result(
            attempt.status,
            snapshot,
            subscription,
            attempt,
            replayed=True,
            retry_required=attempt.status == BillingAttemptStatus.FAILED.value,
            reconciliation_required=(
                attempt.status == BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
            ),
        )

    def _activate_paid_contract(self, subscription, snapshot, now) -> None:
        if snapshot.status != ConversionSnapshotStatus.PENDING.value:
            raise FirstChargeConflict("conversion snapshot is not pending")
        products = self._snapshot_products(snapshot)
        self._close_trial_entitlements(subscription, now)
        for existing in list(
            self._session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == subscription.id
                )
            ).all()
        ):
            self._session.delete(existing)
        for product_code in products:
            self._session.add(
                SubscriptionProduct(
                    subscription_id=subscription.id,
                    product_code=product_code,
                    created_at=now,
                )
            )
            self._session.add(
                Entitlement(
                    account_id=snapshot.account_id,
                    subscription_id=subscription.id,
                    product_code=product_code,
                    source=EntitlementSource.PAID.value,
                    plan_code=snapshot.plan_code,
                    price_version=snapshot.price_version,
                    effective_from=ensure_utc(snapshot.first_charge_at).astimezone(KST).date(),
                    effective_to=None,
                    revoked_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        period_start, period_end, next_billing_at = _billing_period(
            snapshot.first_charge_at
        )
        subscription.state = SubscriptionState.ACTIVE.value
        subscription.contracted_plan_code = snapshot.plan_code
        subscription.contracted_price_krw = snapshot.price_krw
        subscription.contracted_price_version = snapshot.price_version
        subscription.contracted_currency = snapshot.currency
        subscription.contracted_at = now
        subscription.billing_anchor_day = ensure_utc(snapshot.first_charge_at).astimezone(KST).day
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        subscription.next_billing_at = next_billing_at
        subscription.ended_at = None
        subscription.updated_at = now
        snapshot.status = ConversionSnapshotStatus.APPLIED.value
        snapshot.applied_at = now
        snapshot.updated_at = now
        self._session.flush()

    def _close_trial_entitlements(self, subscription, now) -> None:
        cutoff = ensure_utc(subscription.trial_end_at).astimezone(KST).date()
        for entitlement in self._session.scalars(
            sa.select(Entitlement)
            .where(
                Entitlement.subscription_id == subscription.id,
                Entitlement.source == EntitlementSource.TRIAL.value,
                Entitlement.revoked_at.is_(None),
            )
            .with_for_update()
        ).all():
            entitlement.effective_to = max(
                entitlement.effective_from, cutoff - dt.timedelta(days=1)
            )
            entitlement.revoked_at = now
            entitlement.updated_at = now
        self._session.flush()

    def _expire_without_paid_delivery(self, subscription, now) -> None:
        self._close_trial_entitlements(subscription, now)
        subscription.state = SubscriptionState.TRIAL_EXPIRED.value
        subscription.ended_at = now
        subscription.updated_at = now
        self._session.flush()

    def _snapshot_products(self, snapshot) -> Tuple[str, ...]:
        return tuple(
            sorted(
                self._session.scalars(
                    sa.select(ConversionSnapshotProduct.product_code).where(
                        ConversionSnapshotProduct.conversion_snapshot_id == snapshot.id
                    )
                ).all()
            )
        )

    def _valid_delivery_email(self, account_id) -> Optional[DeliveryEmail]:
        rows = list(
            self._session.scalars(
                sa.select(DeliveryEmail)
                .where(DeliveryEmail.account_id == account_id)
                .with_for_update()
            ).all()
        )
        active = [
            row
            for row in rows
            if row.status == DeliveryEmailStatus.ACTIVE.value
            and row.verified_at is not None
            and row.deactivated_at is None
        ]
        return active[0] if len(active) == 1 else None

    def _usable_default_payment_method(self, account_id) -> Optional[PaymentMethod]:
        return self._session.scalar(
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

    def _record_block_once(self, snapshot, subscription, reason: str) -> None:
        event_type = "billing.first_charge_blocked_{0}".format(reason)
        exists = self._session.scalar(
            sa.select(AuditEvent.id).where(
                AuditEvent.event_type == event_type,
                AuditEvent.entity_type == "conversion_snapshot",
                AuditEvent.entity_id == str(snapshot.id),
            )
        )
        if exists is None:
            self._audit.record(
                event_type,
                account_id=snapshot.account_id,
                subscription_id=subscription.id,
                entity_type="conversion_snapshot",
                entity_id=snapshot.id,
                payload={"reason": reason, "retry_required": True, "charged": False},
            )

    def _record_billing_event(self, attempt, event_type, now, reference, detail):
        self._session.add(
            BillingEvent(
                billing_attempt_id=attempt.id,
                event_type=event_type,
                occurred_at=now,
                provider_event_reference=_safe_reference(reference, required=False),
                detail=detail,
                created_at=now,
            )
        )
        self._session.flush()

    @staticmethod
    def _result(
        status,
        snapshot,
        subscription,
        attempt=None,
        *,
        replayed=False,
        retry_required=False,
        reconciliation_required=False,
    ):
        return FirstChargeExecutionResult(
            status=status,
            subscription_id=subscription.id,
            conversion_snapshot_id=snapshot.id,
            billing_attempt_id=attempt.id if attempt is not None else None,
            replayed=replayed,
            retry_required=retry_required,
            reconciliation_required=reconciliation_required,
        )


class FirstChargeExecutor:
    """Future internal-worker boundary; deliberately not exposed as an API."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        provider: FirstChargeProvider,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider = provider

    def execute(
        self, conversion_snapshot_id: uuid.UUID, *, explicit_retry: bool = False
    ) -> FirstChargeExecutionResult:
        session = self._session_factory()
        try:
            with session.begin():
                prepared = FirstChargeService(session, self._clock).prepare(
                    conversion_snapshot_id=conversion_snapshot_id,
                    provider_name=self._provider.name,
                    explicit_retry=explicit_retry,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result

        try:
            provider_result = self._provider.charge(prepared.request)
            if not isinstance(provider_result, FirstChargeProviderResult):
                provider_result = FirstChargeProviderResult.unknown()
        except Exception:
            # Provider exceptions are sanitized into an unknown outcome.  No
            # exception text or raw response crosses the persistence boundary.
            provider_result = FirstChargeProviderResult.unknown()

        session = self._session_factory()
        try:
            with session.begin():
                return FirstChargeService(
                    session, self._clock
                ).apply_provider_result(
                    billing_attempt_id=uuid.UUID(prepared.request.attempt_id),
                    provider_result=provider_result,
                )
        finally:
            session.close()


def _billing_period(first_charge_at: dt.datetime):
    anchor = ensure_utc(first_charge_at).astimezone(KST)
    next_month = 1 if anchor.month == 12 else anchor.month + 1
    next_year = anchor.year + 1 if anchor.month == 12 else anchor.year
    next_day = min(anchor.day, calendar.monthrange(next_year, next_month)[1])
    next_anchor = anchor.replace(year=next_year, month=next_month, day=next_day)
    return anchor.date(), next_anchor.date(), next_anchor.astimezone(dt.timezone.utc)


def _safe_provider_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 64 or not re.fullmatch(r"[A-Za-z0-9_.-]+", normalized):
        raise FirstChargeConflict("invalid provider identity")
    return normalized


def _safe_reference(value: Optional[str], *, required: bool) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        if required:
            raise FirstChargeConflict("authoritative provider reference is required")
        return None
    if len(normalized) > 255 or any(ord(char) < 32 for char in normalized):
        raise FirstChargeConflict("provider reference is invalid")
    return normalized


def _safe_failure_code(value: Optional[str]) -> str:
    normalized = str(value or "PROVIDER_DECLINED").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{1,80}", normalized):
        return "PROVIDER_DECLINED"
    return normalized
