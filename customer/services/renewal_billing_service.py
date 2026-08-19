"""Provider-neutral paid-renewal command and query-only reconciliation.

Each provider call is bounded by two database transactions: the first creates
one durable renewal attempt slot, the provider call happens without an open
transaction, and the second applies only an authoritative outcome.  A durable
PENDING/UNKNOWN attempt blocks every later retry until it is reconciled.
"""

import calendar
import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.catalog import (
    CURRENCY_KRW,
    PLAN_FIXED_PRODUCTS,
    PLAN_PRODUCT_COUNT,
    RENEWAL_RETRY_OFFSET_DAYS,
    TRIAL_PRODUCTS,
)
from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    BillingAttemptPurpose,
    BillingAttemptStatus,
    EntitlementSource,
    SubscriptionState,
)
from customer.domain.errors import RenewalBillingConflict
from customer.persistence.models import (
    BillingAttempt,
    BillingEvent,
    Entitlement,
    PaymentMethod,
    Subscription,
    SubscriptionProduct,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.charge_providers import (
    ChargeOutcome,
    FirstChargeProviderResult,
    FirstChargeReconciliationCapabilities,
    FirstChargeReconciliationResult,
    ReconciliationLookupBasis,
    ReconciliationOutcome,
    RenewalChargeProvider,
    RenewalChargeReconciliationProvider,
    RenewalChargeReconciliationRequest,
    RenewalChargeRequest,
)
from customer.services.first_charge_service import (
    FirstChargeService,
    KST,
    _safe_failure_code,
    _safe_provider_name,
    _safe_reference,
)


RENEWAL_PURPOSE = BillingAttemptPurpose.RENEWAL_CHARGE.value
RENEWAL_OFFSETS = tuple(RENEWAL_RETRY_OFFSET_DAYS)


@dataclass(frozen=True)
class RenewalExecutionResult:
    status: str
    subscription_id: Optional[uuid.UUID]
    billing_attempt_id: Optional[uuid.UUID] = None
    attempt_no: Optional[int] = None
    retry_offset_day: Optional[int] = None
    replayed: bool = False
    reconciliation_required: bool = False
    grace_active: bool = False
    delivery_available: bool = False


@dataclass(frozen=True)
class PreparedRenewal:
    result: RenewalExecutionResult
    request: Optional[RenewalChargeRequest] = None


@dataclass(frozen=True)
class PreparedRenewalReconciliation:
    result: RenewalExecutionResult
    request: Optional[RenewalChargeReconciliationRequest] = None


class RenewalBillingService:
    """Transactional state machine for one paid monthly renewal obligation."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)
        self._first_charge = FirstChargeService(session, clock, audit=self._audit)

    def prepare(
        self, *, subscription_id: uuid.UUID, provider_name: str
    ) -> PreparedRenewal:
        provider = _safe_provider_name(provider_name)
        subscription = self._locked_subscription(subscription_id)
        if subscription is None:
            return PreparedRenewal(RenewalExecutionResult("not_eligible", None))
        if subscription.state == SubscriptionState.SUSPENDED.value:
            return PreparedRenewal(
                self._result("final_failed", subscription, replayed=True)
            )
        if subscription.state not in {
            SubscriptionState.ACTIVE.value,
            SubscriptionState.PAST_DUE.value,
        }:
            return PreparedRenewal(self._result("not_eligible", subscription))

        products = self._assert_contract_authority(subscription)
        now = ensure_utc(self._clock.now())
        due_at = ensure_utc(subscription.next_billing_at)
        period_start = subscription.current_period_end
        next_due_at = _next_monthly_anchor(due_at, subscription.billing_anchor_day)
        period_end = next_due_at.astimezone(KST).date()

        unresolved = self._session.scalar(
            sa.select(BillingAttempt)
            .where(
                BillingAttempt.subscription_id == subscription.id,
                BillingAttempt.status.in_(
                    (
                        BillingAttemptStatus.PENDING.value,
                        BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
                    )
                ),
            )
            .order_by(BillingAttempt.created_at.asc(), BillingAttempt.id.asc())
            .with_for_update()
        )
        if unresolved is not None:
            return PreparedRenewal(
                self._result(
                    "provider_state_unknown",
                    subscription,
                    unresolved,
                    replayed=True,
                    reconciliation_required=True,
                    now=now,
                )
            )

        attempts = list(
            self._session.scalars(
                sa.select(BillingAttempt)
                .where(
                    BillingAttempt.subscription_id == subscription.id,
                    BillingAttempt.purpose == RENEWAL_PURPOSE,
                    BillingAttempt.billing_period_start == period_start,
                )
                .order_by(BillingAttempt.attempt_no.asc())
                .with_for_update()
            ).all()
        )
        self._assert_attempt_sequence(
            subscription, attempts, provider, period_start, period_end
        )
        if any(
            attempt.status == BillingAttemptStatus.SUCCEEDED.value
            for attempt in attempts
        ):
            raise RenewalBillingConflict(
                "settled renewal did not advance the billing period"
            )

        if attempts:
            latest = attempts[-1]
            if latest.status != BillingAttemptStatus.FAILED.value:
                raise RenewalBillingConflict("renewal attempt state is inconsistent")
            if subscription.state != SubscriptionState.PAST_DUE.value:
                raise RenewalBillingConflict("failed renewal is not past due")
            if latest.attempt_no >= len(RENEWAL_OFFSETS):
                raise RenewalBillingConflict("final renewal failure is not suspended")
            attempt_no = latest.attempt_no + 1
        else:
            if subscription.state != SubscriptionState.ACTIVE.value:
                raise RenewalBillingConflict("past-due renewal has no failed attempt")
            attempt_no = 1

        retry_offset = RENEWAL_OFFSETS[attempt_no - 1]
        scheduled_at = _retry_at(due_at, retry_offset)
        if now < scheduled_at:
            return PreparedRenewal(
                self._result(
                    "not_due" if attempt_no == 1 else "retry_not_due",
                    subscription,
                    attempts[-1] if attempts else None,
                    replayed=bool(attempts),
                    now=now,
                )
            )

        if self._first_charge._valid_delivery_email(subscription.account_id) is None:
            return PreparedRenewal(
                self._result("blocked_delivery_email", subscription, now=now)
            )
        payment_method = self._first_charge._usable_default_payment_method(
            subscription.account_id
        )
        if payment_method is None:
            return PreparedRenewal(
                self._result("blocked_payment_method", subscription, now=now)
            )

        idempotency_key = "renewal:{0}:{1}:{2}".format(
            subscription.id, period_start.isoformat(), attempt_no
        )
        attempt = BillingAttempt(
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            conversion_snapshot_id=None,
            payment_method_id=payment_method.id,
            purpose=RENEWAL_PURPOSE,
            status=BillingAttemptStatus.PENDING.value,
            attempt_no=attempt_no,
            retry_offset_day=retry_offset,
            billing_period_start=period_start,
            billing_period_end=period_end,
            amount_krw=subscription.contracted_price_krw,
            currency=subscription.contracted_currency,
            plan_code=subscription.contracted_plan_code,
            price_version=subscription.contracted_price_version,
            idempotency_key=idempotency_key,
            provider=provider,
            scheduled_at=scheduled_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(attempt)
        self._session.flush()
        self._record_event(
            attempt,
            "renewal_prepared",
            now,
            None,
            {
                "attempt_no": attempt_no,
                "retry_offset_day": retry_offset,
                "product_count": len(products),
                "charge_command_created": True,
            },
        )
        self._audit.record(
            audit_events.RENEWAL_PREPARED,
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt_no,
                "retry_offset_day": retry_offset,
                "amount_krw": attempt.amount_krw,
                "currency": attempt.currency,
                "product_count": len(products),
            },
        )
        request = RenewalChargeRequest(
            attempt_id=str(attempt.id),
            account_id=str(subscription.account_id),
            subscription_id=str(subscription.id),
            billing_period_start=period_start,
            billing_period_end=period_end,
            amount_krw=attempt.amount_krw,
            currency=attempt.currency,
            plan_code=attempt.plan_code,
            price_version=attempt.price_version,
            attempt_no=attempt_no,
            retry_offset_day=retry_offset,
            idempotency_key=idempotency_key,
            billing_key_reference=payment_method.billing_key_reference,
        )
        return PreparedRenewal(
            self._result("prepared", subscription, attempt, now=now), request
        )

    def apply_provider_result(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeProviderResult,
    ) -> RenewalExecutionResult:
        attempt, subscription = self._locked_attempt_authority(billing_attempt_id)
        if attempt.status != BillingAttemptStatus.PENDING.value:
            return self._terminal_result(attempt, subscription, provider_result)
        self._assert_attempt_matches_contract(attempt, subscription)
        if provider_result.outcome == ChargeOutcome.SUCCEEDED:
            return self._apply_success(
                attempt, subscription, provider_result, reconciled=False
            )
        if provider_result.outcome == ChargeOutcome.FAILED:
            return self._apply_failure(
                attempt, subscription, provider_result, reconciled=False
            )
        return self._apply_unknown(attempt, subscription, provider_result)

    def _apply_success(
        self, attempt, subscription, provider_result, *, reconciled
    ) -> RenewalExecutionResult:
        now = ensure_utc(self._clock.now())
        transaction_reference = _safe_reference(
            provider_result.transaction_reference, required=True
        )
        competing_success = self._session.scalar(
            sa.select(BillingAttempt.id).where(
                BillingAttempt.subscription_id == attempt.subscription_id,
                BillingAttempt.billing_period_start == attempt.billing_period_start,
                BillingAttempt.status == BillingAttemptStatus.SUCCEEDED.value,
                BillingAttempt.id != attempt.id,
            )
        )
        if competing_success is not None:
            raise RenewalBillingConflict("renewal obligation is already settled")
        if subscription.current_period_end != attempt.billing_period_start:
            raise RenewalBillingConflict("renewal period changed before settlement")

        attempt.status = BillingAttemptStatus.SUCCEEDED.value
        attempt.provider_transaction_reference = transaction_reference
        attempt.failure_code = None
        attempt.failure_message = None
        attempt.attempted_at = attempt.attempted_at or now
        attempt.settled_at = now
        attempt.updated_at = now
        self._record_event(
            attempt,
            "renewal_reconciled_success" if reconciled else "renewal_succeeded",
            now,
            provider_result.provider_event_reference or transaction_reference,
            {
                "authoritative": True,
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "charge_command_created": False,
            },
        )
        next_due_at = _next_monthly_anchor(
            ensure_utc(subscription.next_billing_at), subscription.billing_anchor_day
        )
        if next_due_at.astimezone(KST).date() != attempt.billing_period_end:
            raise RenewalBillingConflict("renewal period end differs from anchor")
        subscription.state = SubscriptionState.ACTIVE.value
        subscription.current_period_start = attempt.billing_period_start
        subscription.current_period_end = attempt.billing_period_end
        subscription.next_billing_at = next_due_at
        subscription.ended_at = None
        subscription.updated_at = now
        self._audit.record(
            (
                audit_events.RENEWAL_RECONCILIATION_SUCCEEDED
                if reconciled
                else audit_events.RENEWAL_SUCCEEDED
            ),
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "amount_krw": attempt.amount_krw,
                "currency": attempt.currency,
                "billing_anchor_day": subscription.billing_anchor_day,
            },
        )
        self._session.flush()
        return self._result("succeeded", subscription, attempt, now=now)

    def _apply_failure(
        self, attempt, subscription, provider_result, *, reconciled
    ) -> RenewalExecutionResult:
        now = ensure_utc(self._clock.now())
        failure_code = _safe_failure_code(provider_result.failure_code)
        attempt.status = BillingAttemptStatus.FAILED.value
        attempt.failure_code = failure_code
        attempt.failure_message = "payment provider definitively rejected renewal"
        attempt.attempted_at = attempt.attempted_at or now
        attempt.settled_at = now
        attempt.updated_at = now
        final_failure = attempt.attempt_no == len(RENEWAL_OFFSETS)
        subscription.state = (
            SubscriptionState.SUSPENDED.value
            if final_failure
            else SubscriptionState.PAST_DUE.value
        )
        subscription.updated_at = now
        delivery_available = self._delivery_available(subscription, now)
        self._record_event(
            attempt,
            "renewal_reconciled_failure" if reconciled else "renewal_failed",
            now,
            provider_result.provider_event_reference,
            {
                "authoritative": True,
                "failure_code": failure_code,
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "final_failure": final_failure,
                "automatic_retry": not final_failure,
            },
        )
        self._audit.record(
            (
                audit_events.RENEWAL_RECONCILIATION_FAILED
                if reconciled
                else audit_events.RENEWAL_FAILED
            ),
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "failure_code": failure_code,
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "final_failure": final_failure,
                "grace_days": 0 if final_failure else 3,
                "delivery_enabled": delivery_available,
            },
        )
        self._session.flush()
        return self._result(
            "suspended" if final_failure else "past_due",
            subscription,
            attempt,
            now=now,
            delivery_available=delivery_available,
        )

    def _apply_unknown(
        self, attempt, subscription, provider_result
    ) -> RenewalExecutionResult:
        now = ensure_utc(self._clock.now())
        attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
        attempt.failure_code = "PROVIDER_STATE_UNKNOWN"
        attempt.failure_message = "provider outcome requires reconciliation"
        attempt.attempted_at = attempt.attempted_at or now
        attempt.updated_at = now
        subscription.state = SubscriptionState.PAST_DUE.value
        subscription.updated_at = now
        self._record_event(
            attempt,
            "renewal_provider_state_unknown",
            now,
            provider_result.provider_event_reference,
            {
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "reconciliation_required": True,
                "blind_retry_allowed": False,
            },
        )
        self._audit.record(
            audit_events.RENEWAL_UNKNOWN,
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "reconciliation_required": True,
                "blind_retry_allowed": False,
            },
        )
        self._session.flush()
        return self._result(
            "provider_state_unknown",
            subscription,
            attempt,
            reconciliation_required=True,
            now=now,
        )

    def _terminal_result(self, attempt, subscription, provider_result):
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            if provider_result.outcome == ChargeOutcome.SUCCEEDED:
                reference = _safe_reference(
                    provider_result.transaction_reference, required=True
                )
                if reference != attempt.provider_transaction_reference:
                    raise RenewalBillingConflict("provider transaction replay differs")
            return self._result(
                "succeeded", subscription, attempt, replayed=True, now=self._clock.now()
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            if provider_result.outcome != ChargeOutcome.FAILED:
                raise RenewalBillingConflict("provider outcome contradicts failed renewal")
            return self._result(
                "suspended" if attempt.attempt_no == 3 else "past_due",
                subscription,
                attempt,
                replayed=True,
                now=self._clock.now(),
            )
        if attempt.status == BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value:
            return self._result(
                "provider_state_unknown",
                subscription,
                attempt,
                replayed=True,
                reconciliation_required=True,
                now=self._clock.now(),
            )
        raise RenewalBillingConflict("renewal attempt state changed unexpectedly")

    def _locked_subscription(self, subscription_id):
        return self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.id == subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _locked_attempt_authority(self, attempt_id):
        reference = self._session.get(BillingAttempt, attempt_id)
        if reference is None or reference.purpose != RENEWAL_PURPOSE:
            raise RenewalBillingConflict("renewal attempt is unavailable")
        subscription = self._locked_subscription(reference.subscription_id)
        attempt = self._session.scalar(
            sa.select(BillingAttempt)
            .where(BillingAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subscription is None or attempt is None:
            raise RenewalBillingConflict("renewal authority is incomplete")
        return attempt, subscription

    def _assert_contract_authority(self, subscription):
        if (
            subscription.contracted_plan_code not in PLAN_PRODUCT_COUNT
            or not subscription.contracted_price_krw
            or subscription.contracted_price_version is None
            or subscription.contracted_currency != CURRENCY_KRW
            or subscription.billing_anchor_day is None
            or subscription.current_period_start is None
            or subscription.current_period_end is None
            or subscription.next_billing_at is None
        ):
            raise RenewalBillingConflict("paid renewal contract is incomplete")
        due_local = ensure_utc(subscription.next_billing_at).astimezone(KST)
        expected_day = min(
            subscription.billing_anchor_day,
            calendar.monthrange(due_local.year, due_local.month)[1],
        )
        if (
            due_local.day != expected_day
            or due_local.date() != subscription.current_period_end
            or subscription.current_period_start >= subscription.current_period_end
        ):
            raise RenewalBillingConflict("billing period does not match its anchor")

        products = tuple(
            sorted(
                self._session.scalars(
                    sa.select(SubscriptionProduct.product_code).where(
                        SubscriptionProduct.subscription_id == subscription.id
                    )
                ).all()
            )
        )
        if (
            len(products)
            != PLAN_PRODUCT_COUNT[subscription.contracted_plan_code]
            or not set(products).issubset(TRIAL_PRODUCTS)
        ):
            raise RenewalBillingConflict("contracted product set is invalid")
        fixed = PLAN_FIXED_PRODUCTS.get(subscription.contracted_plan_code)
        if fixed is not None and set(products) != set(fixed):
            raise RenewalBillingConflict("fixed-plan product set is invalid")
        open_entitlements = list(
            self._session.scalars(
                sa.select(Entitlement).where(
                    Entitlement.subscription_id == subscription.id,
                    Entitlement.revoked_at.is_(None),
                    Entitlement.effective_to.is_(None),
                )
            ).all()
        )
        entitlement_products = tuple(
            sorted(entitlement.product_code for entitlement in open_entitlements)
        )
        if entitlement_products != products or any(
            entitlement.account_id != subscription.account_id
            or entitlement.source != EntitlementSource.PAID.value
            or entitlement.plan_code != subscription.contracted_plan_code
            or entitlement.price_version != subscription.contracted_price_version
            for entitlement in open_entitlements
        ):
            raise RenewalBillingConflict("paid entitlement differs from contract")
        return products

    def _assert_attempt_sequence(
        self, subscription, attempts, provider, period_start, period_end
    ):
        for index, attempt in enumerate(attempts):
            attempt_no = index + 1
            payment_owner = self._session.scalar(
                sa.select(PaymentMethod.account_id)
                .where(PaymentMethod.id == attempt.payment_method_id)
                .with_for_update()
            )
            if (
                attempt.attempt_no != attempt_no
                or attempt_no > len(RENEWAL_OFFSETS)
                or attempt.retry_offset_day != RENEWAL_OFFSETS[index]
                or attempt.account_id != subscription.account_id
                or payment_owner != subscription.account_id
                or attempt.provider != provider
                or attempt.billing_period_start != period_start
                or attempt.billing_period_end != period_end
                or attempt.amount_krw != subscription.contracted_price_krw
                or attempt.currency != subscription.contracted_currency
                or attempt.plan_code != subscription.contracted_plan_code
                or attempt.price_version != subscription.contracted_price_version
            ):
                raise RenewalBillingConflict("renewal attempt authority is inconsistent")

    def _assert_attempt_matches_contract(self, attempt, subscription):
        self._assert_contract_authority(subscription)
        payment_owner = self._session.scalar(
            sa.select(PaymentMethod.account_id)
            .where(PaymentMethod.id == attempt.payment_method_id)
            .with_for_update()
        )
        expected_end = _next_monthly_anchor(
            ensure_utc(subscription.next_billing_at), subscription.billing_anchor_day
        ).astimezone(KST).date()
        if (
            subscription.state
            not in {
                SubscriptionState.ACTIVE.value,
                SubscriptionState.PAST_DUE.value,
            }
            or attempt.account_id != subscription.account_id
            or payment_owner != subscription.account_id
            or attempt.billing_period_start != subscription.current_period_end
            or attempt.billing_period_end != expected_end
            or attempt.amount_krw != subscription.contracted_price_krw
            or attempt.currency != subscription.contracted_currency
            or attempt.plan_code != subscription.contracted_plan_code
            or attempt.price_version != subscription.contracted_price_version
            or attempt.retry_offset_day != RENEWAL_OFFSETS[attempt.attempt_no - 1]
        ):
            raise RenewalBillingConflict("renewal attempt differs from paid contract")

    def _delivery_available(self, subscription, now):
        if subscription.state == SubscriptionState.SUSPENDED.value:
            return False
        if subscription.state == SubscriptionState.PAST_DUE.value:
            final_retry_at = _retry_at(
                ensure_utc(subscription.next_billing_at), RENEWAL_OFFSETS[-1]
            )
            if ensure_utc(now) > final_retry_at:
                return False
        if subscription.state not in {
            SubscriptionState.ACTIVE.value,
            SubscriptionState.PAST_DUE.value,
        }:
            return False
        return (
            self._first_charge._valid_delivery_email(subscription.account_id)
            is not None
        )

    def _record_event(self, attempt, event_type, now, reference, detail):
        provider_reference = _safe_reference(reference, required=False)
        if provider_reference is not None:
            existing = self._session.scalar(
                sa.select(BillingEvent).where(
                    BillingEvent.provider_event_reference == provider_reference
                )
            )
            if existing is not None:
                if existing.billing_attempt_id != attempt.id:
                    raise RenewalBillingConflict(
                        "provider evidence belongs to another attempt"
                    )
                provider_reference = None
        self._session.add(
            BillingEvent(
                billing_attempt_id=attempt.id,
                event_type=event_type,
                occurred_at=ensure_utc(now),
                provider_event_reference=provider_reference,
                detail=dict(detail),
                created_at=ensure_utc(now),
            )
        )
        self._session.flush()

    def _result(
        self,
        status,
        subscription,
        attempt=None,
        *,
        replayed=False,
        reconciliation_required=False,
        now=None,
        delivery_available=None,
    ):
        effective_now = ensure_utc(now or self._clock.now())
        if delivery_available is None:
            delivery_available = self._delivery_available(subscription, effective_now)
        return RenewalExecutionResult(
            status=status,
            subscription_id=subscription.id,
            billing_attempt_id=attempt.id if attempt is not None else None,
            attempt_no=attempt.attempt_no if attempt is not None else None,
            retry_offset_day=(
                attempt.retry_offset_day if attempt is not None else None
            ),
            replayed=replayed,
            reconciliation_required=reconciliation_required,
            grace_active=(
                subscription.state == SubscriptionState.PAST_DUE.value
                and effective_now
                <= _retry_at(
                    ensure_utc(subscription.next_billing_at),
                    RENEWAL_OFFSETS[-1],
                )
            ),
            delivery_available=bool(delivery_available),
        )


class RenewalBillingExecutor:
    """Future-worker boundary that executes one due renewal attempt."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        provider: RenewalChargeProvider,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider = provider

    def execute(self, subscription_id: uuid.UUID) -> RenewalExecutionResult:
        session = self._session_factory()
        try:
            with session.begin():
                prepared = RenewalBillingService(session, self._clock).prepare(
                    subscription_id=subscription_id,
                    provider_name=self._provider.name,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result
        try:
            provider_result = self._provider.charge_renewal(prepared.request)
            if (
                not isinstance(provider_result, FirstChargeProviderResult)
                or not isinstance(provider_result.outcome, ChargeOutcome)
            ):
                provider_result = FirstChargeProviderResult.unknown()
        except Exception:
            provider_result = FirstChargeProviderResult.unknown()
        session = self._session_factory()
        try:
            with session.begin():
                return RenewalBillingService(
                    session, self._clock
                ).apply_provider_result(
                    billing_attempt_id=uuid.UUID(prepared.request.attempt_id),
                    provider_result=provider_result,
                )
        finally:
            session.close()


class RenewalBillingReconciliationService:
    """Query-only resolution of one original renewal attempt."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._renewal = RenewalBillingService(session, clock, audit=audit)

    def prepare(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_name: str,
        capabilities: FirstChargeReconciliationCapabilities,
    ) -> PreparedRenewalReconciliation:
        provider = _safe_provider_name(provider_name)
        attempt, subscription = self._renewal._locked_attempt_authority(
            billing_attempt_id
        )
        if attempt.provider != provider:
            raise RenewalBillingConflict("reconciliation provider differs")
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            return PreparedRenewalReconciliation(
                self._renewal._result(
                    "succeeded", subscription, attempt, replayed=True
                )
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            return PreparedRenewalReconciliation(
                self._renewal._result(
                    "suspended" if attempt.attempt_no == 3 else "past_due",
                    subscription,
                    attempt,
                    replayed=True,
                )
            )
        if attempt.status not in {
            BillingAttemptStatus.PENDING.value,
            BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
        }:
            raise RenewalBillingConflict("renewal cannot be reconciled")
        self._renewal._assert_attempt_matches_contract(attempt, subscription)
        operation_reference = self._original_operation_reference(attempt.id)
        if operation_reference:
            lookup_basis = ReconciliationLookupBasis.OPERATION_REFERENCE
        elif capabilities.authoritative_idempotency_lookup:
            lookup_basis = ReconciliationLookupBasis.IDEMPOTENCY_KEY
        else:
            return PreparedRenewalReconciliation(
                self._renewal._result(
                    "query_authority_unavailable",
                    subscription,
                    attempt,
                    replayed=True,
                    reconciliation_required=True,
                )
            )
        return PreparedRenewalReconciliation(
            self._renewal._result(
                "prepared_reconciliation",
                subscription,
                attempt,
                reconciliation_required=True,
            ),
            RenewalChargeReconciliationRequest(
                attempt_id=str(attempt.id),
                provider=provider,
                lookup_basis=lookup_basis,
                original_idempotency_key=attempt.idempotency_key,
                original_operation_reference=operation_reference,
            ),
        )

    def apply_provider_result(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeReconciliationResult,
        lookup_basis: ReconciliationLookupBasis,
        idempotency_lookup_authoritative: bool,
    ) -> RenewalExecutionResult:
        attempt, subscription = self._renewal._locked_attempt_authority(
            billing_attempt_id
        )
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            return self._terminal_conflict_or_replay(
                attempt, subscription, provider_result
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            return self._terminal_conflict_or_replay(
                attempt, subscription, provider_result
            )
        self._renewal._assert_attempt_matches_contract(attempt, subscription)
        if attempt.status == BillingAttemptStatus.PENDING.value:
            operation_authority = (
                lookup_basis == ReconciliationLookupBasis.OPERATION_REFERENCE
                and self._original_operation_reference(attempt.id) is not None
            )
            idempotency_authority = (
                lookup_basis == ReconciliationLookupBasis.IDEMPOTENCY_KEY
                and idempotency_lookup_authoritative
            )
            if not (operation_authority or idempotency_authority):
                raise RenewalBillingConflict(
                    "pending renewal lacks authoritative lookup evidence"
                )
        if provider_result.outcome == ReconciliationOutcome.CONFIRMED_SUCCESS:
            return self._renewal._apply_success(
                attempt,
                subscription,
                FirstChargeProviderResult.succeeded(
                    provider_result.transaction_reference,
                    event_reference=provider_result.provider_event_reference,
                ),
                reconciled=True,
            )
        if provider_result.outcome == ReconciliationOutcome.CONFIRMED_FAILURE:
            return self._renewal._apply_failure(
                attempt,
                subscription,
                FirstChargeProviderResult.failed(
                    provider_result.failure_code,
                    event_reference=provider_result.provider_event_reference,
                ),
                reconciled=True,
            )
        return self._apply_still_unknown(attempt, subscription, provider_result)

    def _apply_still_unknown(self, attempt, subscription, provider_result):
        now = ensure_utc(self._clock.now())
        attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
        attempt.failure_code = "PROVIDER_STATE_UNKNOWN"
        attempt.failure_message = "provider outcome requires reconciliation"
        attempt.updated_at = now
        subscription.state = SubscriptionState.PAST_DUE.value
        subscription.updated_at = now
        self._renewal._record_event(
            attempt,
            "renewal_reconciliation_still_unknown",
            now,
            provider_result.provider_event_reference,
            {
                "reconciliation_required": True,
                "automatic_retry": False,
                "charge_command_created": False,
            },
        )
        self._renewal._audit.record(
            audit_events.RENEWAL_RECONCILIATION_UNKNOWN,
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "retry_offset_day": attempt.retry_offset_day,
                "reconciliation_required": True,
                "charged_again": False,
            },
        )
        self._session.flush()
        return self._renewal._result(
            "still_unknown",
            subscription,
            attempt,
            reconciliation_required=True,
            now=now,
        )

    def _terminal_conflict_or_replay(
        self, attempt, subscription, provider_result
    ):
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            if provider_result.outcome == ReconciliationOutcome.CONFIRMED_SUCCESS:
                reference = _safe_reference(
                    provider_result.transaction_reference, required=True
                )
                if reference == attempt.provider_transaction_reference:
                    return self._renewal._result(
                        "succeeded", subscription, attempt, replayed=True
                    )
            return self._record_conflict(
                attempt, subscription, provider_result, "succeeded"
            )
        if provider_result.outcome != ReconciliationOutcome.CONFIRMED_SUCCESS:
            return self._renewal._result(
                "suspended" if attempt.attempt_no == 3 else "past_due",
                subscription,
                attempt,
                replayed=True,
            )
        later_success = self._session.scalar(
            sa.select(BillingAttempt.id).where(
                BillingAttempt.subscription_id == attempt.subscription_id,
                BillingAttempt.billing_period_start == attempt.billing_period_start,
                BillingAttempt.status == BillingAttemptStatus.SUCCEEDED.value,
            )
        )
        if later_success is None:
            attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
            attempt.failure_code = "PROVIDER_OBSERVATION_CONFLICT"
            attempt.failure_message = "provider observations conflict"
            attempt.updated_at = ensure_utc(self._clock.now())
        return self._record_conflict(
            attempt, subscription, provider_result, "contradictory_observation"
        )

    def _record_conflict(self, attempt, subscription, observed, status):
        now = ensure_utc(self._clock.now())
        self._renewal._record_event(
            attempt,
            "renewal_reconciliation_contradictory_observation",
            now,
            observed.provider_event_reference,
            {
                "observed_outcome": observed.outcome.value,
                "stored_status": attempt.status,
                "economic_state_changed": False,
            },
        )
        self._renewal._audit.record(
            audit_events.RENEWAL_RECONCILIATION_CONFLICT,
            account_id=subscription.account_id,
            subscription_id=subscription.id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "observed_outcome": observed.outcome.value,
                "stored_status": attempt.status,
                "economic_state_changed": False,
            },
        )
        self._session.flush()
        return self._renewal._result(
            status,
            subscription,
            attempt,
            replayed=True,
            reconciliation_required=(
                attempt.status
                == BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
            ),
            now=now,
        )

    def _original_operation_reference(self, attempt_id):
        return self._session.scalar(
            sa.select(BillingEvent.provider_event_reference)
            .where(
                BillingEvent.billing_attempt_id == attempt_id,
                BillingEvent.event_type == "renewal_provider_state_unknown",
                BillingEvent.provider_event_reference.is_not(None),
            )
            .order_by(BillingEvent.occurred_at.asc(), BillingEvent.id.asc())
            .limit(1)
        )


class RenewalBillingReconciliationExecutor:
    """Future-worker boundary that queries but never creates a charge."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        provider: RenewalChargeReconciliationProvider,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider = provider

    def execute(self, attempt_id: uuid.UUID) -> RenewalExecutionResult:
        capabilities = getattr(
            self._provider,
            "reconciliation_capabilities",
            FirstChargeReconciliationCapabilities(),
        )
        if not isinstance(capabilities, FirstChargeReconciliationCapabilities):
            capabilities = FirstChargeReconciliationCapabilities()
        session = self._session_factory()
        try:
            with session.begin():
                prepared = RenewalBillingReconciliationService(
                    session, self._clock
                ).prepare(
                    billing_attempt_id=attempt_id,
                    provider_name=self._provider.name,
                    capabilities=capabilities,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result
        try:
            provider_result = self._provider.reconcile_renewal(prepared.request)
            if (
                not isinstance(provider_result, FirstChargeReconciliationResult)
                or not isinstance(provider_result.outcome, ReconciliationOutcome)
            ):
                provider_result = FirstChargeReconciliationResult.still_unknown()
        except Exception:
            provider_result = FirstChargeReconciliationResult.still_unknown()
        if provider_result.outcome == ReconciliationOutcome.NOT_FOUND:
            if capabilities.definitive_not_found_means_no_charge:
                provider_result = FirstChargeReconciliationResult.confirmed_failure(
                    "PROVIDER_TRANSACTION_NOT_FOUND",
                    event_reference=provider_result.provider_event_reference,
                )
            else:
                provider_result = FirstChargeReconciliationResult.still_unknown(
                    event_reference=provider_result.provider_event_reference
                )
        session = self._session_factory()
        try:
            with session.begin():
                return RenewalBillingReconciliationService(
                    session, self._clock
                ).apply_provider_result(
                    billing_attempt_id=uuid.UUID(prepared.request.attempt_id),
                    provider_result=provider_result,
                    lookup_basis=prepared.request.lookup_basis,
                    idempotency_lookup_authoritative=(
                        capabilities.authoritative_idempotency_lookup
                    ),
                )
        finally:
            session.close()


def _next_monthly_anchor(current_due_at: dt.datetime, anchor_day: int) -> dt.datetime:
    local = ensure_utc(current_due_at).astimezone(KST)
    month = 1 if local.month == 12 else local.month + 1
    year = local.year + 1 if local.month == 12 else local.year
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day).astimezone(dt.timezone.utc)


def _retry_at(due_at: dt.datetime, offset_days: int) -> dt.datetime:
    return (
        ensure_utc(due_at).astimezone(KST) + dt.timedelta(days=offset_days)
    ).astimezone(dt.timezone.utc)
