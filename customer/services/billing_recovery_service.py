"""Explicit, provider-neutral recovery for failed Customer billing obligations.

Recovery never invents a new financial truth.  First-charge recovery delegates
to the frozen conversion snapshot and the existing first-charge state machine.
Suspended-renewal recovery settles the same missed billing-period tuple that
the Day 0/+1/+3 attempts exhausted.  Provider calls remain outside database
transactions and every PENDING/UNKNOWN state fails closed into reconciliation.
"""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    AccountStatus,
    BillingAttemptPurpose,
    BillingAttemptStatus,
    CommandIdempotencyStatus,
    SubscriptionState,
)
from customer.domain.errors import (
    FirstChargeConflict,
    IdempotencyKeyConflict,
    RenewalBillingConflict,
)
from customer.persistence.models import (
    BillingAttempt,
    BillingEvent,
    CommandIdempotency,
    ConversionSnapshot,
    CustomerAccount,
    PaymentMethod,
    Subscription,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.charge_providers import (
    ChargeOutcome,
    FirstChargeProvider,
    FirstChargeProviderResult,
    FirstChargeReconciliationCapabilities,
    FirstChargeReconciliationResult,
    FirstChargeRequest,
    ReconciliationLookupBasis,
    ReconciliationOutcome,
    RenewalChargeProvider,
    RenewalChargeReconciliationProvider,
    RenewalChargeReconciliationRequest,
    RenewalChargeRequest,
)
from customer.services.first_charge_service import (
    FIRST_CHARGE_PURPOSE,
    FirstChargeService,
    _safe_failure_code,
    _safe_provider_name,
    _safe_reference,
)
from customer.services.renewal_billing_service import (
    RENEWAL_OFFSETS,
    RENEWAL_PURPOSE,
    RenewalBillingService,
    _next_monthly_anchor,
)


FIRST_CHARGE_RECOVERY = "first_charge"
SUSPENDED_RENEWAL_RECOVERY = "suspended_renewal"
FIRST_CHARGE_RECOVERY_COMMAND = "billing_recovery.first_charge"
RENEWAL_RECOVERY_COMMAND = "billing_recovery.suspended_renewal"
RECOVERY_PURPOSE = BillingAttemptPurpose.RECOVERY_CHARGE.value
_UNRESOLVED = (
    BillingAttemptStatus.PENDING.value,
    BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
)


@dataclass(frozen=True)
class RecoveryEligibility:
    kind: str
    eligible: bool
    status: str
    subscription_id: Optional[uuid.UUID] = None
    billing_attempt_id: Optional[uuid.UUID] = None
    reconciliation_required: bool = False
    explicit_action_required: bool = True


@dataclass(frozen=True)
class BillingRecoveryProjection:
    first_charge: RecoveryEligibility
    suspended_renewal: RecoveryEligibility


@dataclass(frozen=True)
class BillingRecoveryResult:
    kind: str
    status: str
    account_id: uuid.UUID
    subscription_id: Optional[uuid.UUID]
    billing_attempt_id: Optional[uuid.UUID] = None
    replayed: bool = False
    reconciliation_required: bool = False
    delivery_available: bool = False


RecoveryRequest = Union[FirstChargeRequest, RenewalChargeRequest]


@dataclass(frozen=True)
class PreparedBillingRecovery:
    result: BillingRecoveryResult
    request: Optional[RecoveryRequest] = None


@dataclass(frozen=True)
class PreparedRecoveryReconciliation:
    result: BillingRecoveryResult
    request: Optional[RenewalChargeReconciliationRequest] = None


class BillingRecoveryService:
    """Transactional authority for explicit Customer billing recovery."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)
        self._first_charge = FirstChargeService(session, clock, audit=self._audit)
        self._renewal = RenewalBillingService(session, clock, audit=self._audit)

    def projection(self, account_id: uuid.UUID) -> BillingRecoveryProjection:
        account = self._session.get(CustomerAccount, account_id)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            return BillingRecoveryProjection(
                self._eligibility(FIRST_CHARGE_RECOVERY, "not_eligible"),
                self._eligibility(SUSPENDED_RENEWAL_RECOVERY, "not_eligible"),
            )
        return BillingRecoveryProjection(
            self._first_charge_eligibility(account_id),
            self._renewal_eligibility(account_id),
        )

    def prepare_first_charge(
        self,
        *,
        account_id: uuid.UUID,
        idempotency_key: str,
        provider_name: str,
    ) -> PreparedBillingRecovery:
        self._active_account(account_id)
        key = _idempotency_key(idempotency_key)
        provider = _safe_provider_name(provider_name)
        command = self._command(FIRST_CHARGE_RECOVERY_COMMAND, key)
        if command is not None:
            return PreparedBillingRecovery(
                self._replay_command(command, account_id, FIRST_CHARGE_RECOVERY)
            )

        snapshot = self._latest_snapshot(account_id, lock=True)
        if snapshot is None:
            return PreparedBillingRecovery(
                self._result(FIRST_CHARGE_RECOVERY, "not_eligible", account_id, None)
            )
        prepared = self._first_charge.prepare(
            conversion_snapshot_id=snapshot.id,
            provider_name=provider,
            explicit_retry=True,
        )
        result = self._from_first_charge(account_id, prepared.result)
        if prepared.request is None:
            return PreparedBillingRecovery(result)

        self._record_command(
            command_name=FIRST_CHARGE_RECOVERY_COMMAND,
            key=key,
            account_id=account_id,
            attempt_id=uuid.UUID(prepared.request.attempt_id),
            fingerprint=_fingerprint(
                FIRST_CHARGE_RECOVERY,
                account_id,
                result.subscription_id,
                prepared.request.amount_krw,
                prepared.request.idempotency_key,
            ),
        )
        self._record_requested(
            result,
            amount_krw=prepared.request.amount_krw,
            attempt_no=self._attempt(prepared.request.attempt_id).attempt_no,
        )
        return PreparedBillingRecovery(result, prepared.request)

    def apply_first_charge_result(
        self,
        *,
        account_id: uuid.UUID,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeProviderResult,
    ) -> BillingRecoveryResult:
        attempt = self._attempt(billing_attempt_id)
        if attempt.account_id != account_id or attempt.purpose != FIRST_CHARGE_PURPOSE:
            raise FirstChargeConflict("first-charge recovery authority is unavailable")
        result = self._first_charge.apply_provider_result(
            billing_attempt_id=billing_attempt_id,
            provider_result=provider_result,
        )
        recovery = self._from_first_charge(account_id, result)
        self._complete_command(FIRST_CHARGE_RECOVERY_COMMAND, billing_attempt_id)
        self._record_outcome(recovery, attempt, reconciled=False)
        return recovery

    def prepare_suspended_renewal(
        self,
        *,
        account_id: uuid.UUID,
        idempotency_key: str,
        provider_name: str,
    ) -> PreparedBillingRecovery:
        self._active_account(account_id)
        key = _idempotency_key(idempotency_key)
        provider = _safe_provider_name(provider_name)
        command = self._command(RENEWAL_RECOVERY_COMMAND, key)
        if command is not None:
            return PreparedBillingRecovery(
                self._replay_command(command, account_id, SUSPENDED_RENEWAL_RECOVERY)
            )

        subscription = self._suspended_subscription(account_id, lock=True)
        if subscription is None:
            return PreparedBillingRecovery(
                self._result(
                    SUSPENDED_RENEWAL_RECOVERY, "not_eligible", account_id, None
                )
            )
        self._renewal._assert_contract_authority(subscription)
        unresolved = self._unresolved_attempt(subscription.id, lock=True)
        if unresolved is not None:
            return PreparedBillingRecovery(
                self._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "reconciliation_required",
                    account_id,
                    subscription.id,
                    unresolved,
                    replayed=True,
                    reconciliation_required=True,
                )
            )

        original_attempts, period_start, period_end = (
            self._assert_suspended_renewal_obligation(subscription, lock=True)
        )
        recovery_attempts = self._recovery_attempts(
            subscription.id, period_start, lock=True
        )
        self._assert_recovery_history(subscription, recovery_attempts, period_end)
        if recovery_attempts and recovery_attempts[-1].status in _UNRESOLVED:
            return PreparedBillingRecovery(
                self._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "reconciliation_required",
                    account_id,
                    subscription.id,
                    recovery_attempts[-1],
                    replayed=True,
                    reconciliation_required=True,
                )
            )

        if self._first_charge._valid_delivery_email(account_id) is None:
            return PreparedBillingRecovery(
                self._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "blocked_delivery_email",
                    account_id,
                    subscription.id,
                )
            )
        payment_method = self._first_charge._usable_default_payment_method(account_id)
        if payment_method is None or not payment_method.billing_key_reference.strip():
            return PreparedBillingRecovery(
                self._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "blocked_payment_method",
                    account_id,
                    subscription.id,
                )
            )

        now = ensure_utc(self._clock.now())
        attempt_no = len(recovery_attempts) + 1
        provider_key = "renewal-recovery:{0}:{1}:{2}".format(
            subscription.id, period_start.isoformat(), attempt_no
        )
        attempt = BillingAttempt(
            account_id=account_id,
            subscription_id=subscription.id,
            conversion_snapshot_id=None,
            payment_method_id=payment_method.id,
            purpose=RECOVERY_PURPOSE,
            status=BillingAttemptStatus.PENDING.value,
            attempt_no=attempt_no,
            retry_offset_day=None,
            billing_period_start=period_start,
            billing_period_end=period_end,
            amount_krw=subscription.contracted_price_krw,
            currency=subscription.contracted_currency,
            plan_code=subscription.contracted_plan_code,
            price_version=subscription.contracted_price_version,
            idempotency_key=provider_key,
            provider=provider,
            scheduled_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(attempt)
        self._session.flush()
        self._record_event(
            attempt,
            "billing_recovery_prepared",
            None,
            {
                "recovery_kind": SUSPENDED_RENEWAL_RECOVERY,
                "original_final_attempt_id": str(original_attempts[-1].id),
                "explicit_customer_action": True,
                "automatic_retry": False,
            },
        )
        fingerprint = _fingerprint(
            SUSPENDED_RENEWAL_RECOVERY,
            account_id,
            subscription.id,
            attempt.amount_krw,
            provider_key,
        )
        self._record_command(
            command_name=RENEWAL_RECOVERY_COMMAND,
            key=key,
            account_id=account_id,
            attempt_id=attempt.id,
            fingerprint=fingerprint,
        )
        result = self._result(
            SUSPENDED_RENEWAL_RECOVERY,
            "prepared",
            account_id,
            subscription.id,
            attempt,
        )
        self._record_requested(result, amount_krw=attempt.amount_krw, attempt_no=attempt_no)
        request = RenewalChargeRequest(
            attempt_id=str(attempt.id),
            account_id=str(account_id),
            subscription_id=str(subscription.id),
            billing_period_start=period_start,
            billing_period_end=period_end,
            amount_krw=attempt.amount_krw,
            currency=attempt.currency,
            plan_code=attempt.plan_code,
            price_version=attempt.price_version,
            attempt_no=attempt.attempt_no,
            retry_offset_day=None,
            idempotency_key=provider_key,
            billing_key_reference=payment_method.billing_key_reference,
            purpose=RECOVERY_PURPOSE,
        )
        return PreparedBillingRecovery(result, request)

    def apply_suspended_renewal_result(
        self,
        *,
        account_id: uuid.UUID,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeProviderResult,
        reconciled: bool = False,
    ) -> BillingRecoveryResult:
        attempt, subscription = self._locked_recovery_attempt(billing_attempt_id)
        if attempt.account_id != account_id:
            raise RenewalBillingConflict("renewal recovery belongs to another account")
        if attempt.status != BillingAttemptStatus.PENDING.value:
            if not (
                reconciled
                and attempt.status == BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
            ):
                return self._terminal_recovery_result(
                    attempt, subscription, provider_result
                )
        self._assert_recovery_attempt_authority(attempt, subscription)
        if provider_result.outcome == ChargeOutcome.SUCCEEDED:
            result = self._apply_recovery_success(
                attempt, subscription, provider_result, reconciled=reconciled
            )
        elif provider_result.outcome == ChargeOutcome.FAILED:
            result = self._apply_recovery_failure(
                attempt, subscription, provider_result, reconciled=reconciled
            )
        else:
            result = self._apply_recovery_unknown(
                attempt, subscription, provider_result, reconciled=reconciled
            )
        self._complete_command(RENEWAL_RECOVERY_COMMAND, attempt.id)
        return result

    def _apply_recovery_success(
        self, attempt, subscription, provider_result, *, reconciled
    ):
        transaction_reference = _safe_reference(
            provider_result.transaction_reference, required=True
        )
        competing = self._session.scalar(
            sa.select(BillingAttempt.id).where(
                BillingAttempt.subscription_id == attempt.subscription_id,
                BillingAttempt.billing_period_start == attempt.billing_period_start,
                BillingAttempt.status == BillingAttemptStatus.SUCCEEDED.value,
                BillingAttempt.id != attempt.id,
            )
        )
        if competing is not None:
            raise RenewalBillingConflict("missed renewal obligation is already settled")
        now = ensure_utc(self._clock.now())
        next_due = _next_monthly_anchor(
            ensure_utc(subscription.next_billing_at), subscription.billing_anchor_day
        )
        if (
            subscription.state != SubscriptionState.SUSPENDED.value
            or subscription.current_period_end != attempt.billing_period_start
            or next_due.astimezone(self._kst()).date() != attempt.billing_period_end
        ):
            raise RenewalBillingConflict("renewal recovery anchor changed before settlement")
        attempt.status = BillingAttemptStatus.SUCCEEDED.value
        attempt.provider_transaction_reference = transaction_reference
        attempt.failure_code = None
        attempt.failure_message = None
        attempt.attempted_at = attempt.attempted_at or now
        attempt.settled_at = now
        attempt.updated_at = now
        subscription.state = SubscriptionState.ACTIVE.value
        subscription.current_period_start = attempt.billing_period_start
        subscription.current_period_end = attempt.billing_period_end
        subscription.next_billing_at = next_due
        subscription.ended_at = None
        subscription.updated_at = now
        self._record_event(
            attempt,
            "billing_recovery_reconciled_success"
            if reconciled
            else "billing_recovery_succeeded",
            provider_result.provider_event_reference or transaction_reference,
            {
                "authoritative": True,
                "billing_anchor_day": subscription.billing_anchor_day,
                "period_advanced_once": True,
            },
        )
        result = self._result(
            SUSPENDED_RENEWAL_RECOVERY,
            "succeeded",
            attempt.account_id,
            subscription.id,
            attempt,
            delivery_available=True,
        )
        self._record_outcome(result, attempt, reconciled=reconciled)
        self._session.flush()
        return result

    def _apply_recovery_failure(
        self, attempt, subscription, provider_result, *, reconciled
    ):
        now = ensure_utc(self._clock.now())
        failure_code = _safe_failure_code(provider_result.failure_code)
        attempt.status = BillingAttemptStatus.FAILED.value
        attempt.failure_code = failure_code
        attempt.failure_message = "payment provider definitively rejected recovery"
        attempt.attempted_at = attempt.attempted_at or now
        attempt.settled_at = now
        attempt.updated_at = now
        subscription.state = SubscriptionState.SUSPENDED.value
        subscription.updated_at = now
        self._record_event(
            attempt,
            "billing_recovery_reconciled_failure"
            if reconciled
            else "billing_recovery_failed",
            provider_result.provider_event_reference,
            {
                "authoritative": True,
                "failure_code": failure_code,
                "automatic_retry": False,
                "entitlement_restored": False,
            },
        )
        result = self._result(
            SUSPENDED_RENEWAL_RECOVERY,
            "failed",
            attempt.account_id,
            subscription.id,
            attempt,
        )
        self._record_outcome(result, attempt, reconciled=reconciled)
        self._session.flush()
        return result

    def _apply_recovery_unknown(
        self, attempt, subscription, provider_result, *, reconciled
    ):
        now = ensure_utc(self._clock.now())
        attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
        attempt.failure_code = "PROVIDER_STATE_UNKNOWN"
        attempt.failure_message = "provider outcome requires reconciliation"
        attempt.attempted_at = attempt.attempted_at or now
        attempt.updated_at = now
        subscription.state = SubscriptionState.SUSPENDED.value
        subscription.updated_at = now
        self._record_event(
            attempt,
            "billing_recovery_reconciliation_still_unknown"
            if reconciled
            else "billing_recovery_provider_state_unknown",
            provider_result.provider_event_reference,
            {
                "reconciliation_required": True,
                "automatic_retry": False,
                "charge_command_created": False,
            },
        )
        result = self._result(
            SUSPENDED_RENEWAL_RECOVERY,
            "provider_state_unknown",
            attempt.account_id,
            subscription.id,
            attempt,
            reconciliation_required=True,
        )
        self._record_outcome(result, attempt, reconciled=reconciled)
        self._session.flush()
        return result

    def _terminal_recovery_result(self, attempt, subscription, observed):
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            if observed.outcome == ChargeOutcome.SUCCEEDED:
                reference = _safe_reference(
                    observed.transaction_reference, required=True
                )
                if reference != attempt.provider_transaction_reference:
                    raise RenewalBillingConflict(
                        "recovery provider transaction replay differs"
                    )
            return self._result(
                SUSPENDED_RENEWAL_RECOVERY,
                "succeeded",
                attempt.account_id,
                subscription.id,
                attempt,
                replayed=True,
                delivery_available=True,
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            if observed.outcome == ChargeOutcome.SUCCEEDED:
                now = ensure_utc(self._clock.now())
                attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
                attempt.failure_code = "PROVIDER_OBSERVATION_CONFLICT"
                attempt.failure_message = "provider observations conflict"
                attempt.updated_at = now
                self._record_event(
                    attempt,
                    "billing_recovery_contradictory_observation",
                    observed.provider_event_reference,
                    {"stored_status": "failed", "economic_state_changed": False},
                )
                self._audit.record(
                    audit_events.BILLING_RECOVERY_RECONCILIATION_CONFLICT,
                    account_id=attempt.account_id,
                    subscription_id=subscription.id,
                    entity_type="billing_attempt",
                    entity_id=attempt.id,
                    payload={
                        "recovery_kind": SUSPENDED_RENEWAL_RECOVERY,
                        "stored_status": attempt.status,
                        "economic_state_changed": False,
                    },
                )
                return self._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "financial_conflict",
                    attempt.account_id,
                    subscription.id,
                    attempt,
                    replayed=True,
                    reconciliation_required=True,
                )
            return self._result(
                SUSPENDED_RENEWAL_RECOVERY,
                "failed",
                attempt.account_id,
                subscription.id,
                attempt,
                replayed=True,
            )
        return self._result(
            SUSPENDED_RENEWAL_RECOVERY,
            "provider_state_unknown",
            attempt.account_id,
            subscription.id,
            attempt,
            replayed=True,
            reconciliation_required=True,
        )

    def _first_charge_eligibility(self, account_id):
        snapshot = self._latest_snapshot(account_id, lock=False)
        if snapshot is None:
            return self._eligibility(FIRST_CHARGE_RECOVERY, "not_eligible")
        subscription = self._session.get(Subscription, snapshot.subscription_id)
        attempts = self._first_charge_attempts(snapshot.id, lock=False)
        latest = attempts[-1] if attempts else None
        if latest is not None and latest.status in _UNRESOLVED:
            return self._eligibility(
                FIRST_CHARGE_RECOVERY,
                "reconciliation_required",
                subscription,
                latest,
                reconciliation_required=True,
            )
        if (
            subscription is None
            or subscription.account_id != account_id
            or subscription.state != SubscriptionState.TRIAL_EXPIRED.value
            or latest is None
            or latest.status != BillingAttemptStatus.FAILED.value
        ):
            return self._eligibility(
                FIRST_CHARGE_RECOVERY, "not_eligible", subscription, latest
            )
        method = self._first_charge._usable_default_payment_method(account_id)
        if method is None or method.id == latest.payment_method_id:
            return self._eligibility(
                FIRST_CHARGE_RECOVERY,
                "payment_method_update_required",
                subscription,
                latest,
            )
        if self._first_charge._valid_delivery_email(account_id) is None:
            return self._eligibility(
                FIRST_CHARGE_RECOVERY,
                "blocked_delivery_email",
                subscription,
                latest,
            )
        return self._eligibility(
            FIRST_CHARGE_RECOVERY, "eligible", subscription, latest, eligible=True
        )

    def _renewal_eligibility(self, account_id):
        subscription = self._suspended_subscription(account_id, lock=False)
        if subscription is None:
            return self._eligibility(SUSPENDED_RENEWAL_RECOVERY, "not_eligible")
        unresolved = self._unresolved_attempt(subscription.id, lock=False)
        if unresolved is not None:
            return self._eligibility(
                SUSPENDED_RENEWAL_RECOVERY,
                "reconciliation_required",
                subscription,
                unresolved,
                reconciliation_required=True,
            )
        try:
            original, period_start, period_end = self._assert_suspended_renewal_obligation(
                subscription, lock=False
            )
            recovery = self._recovery_attempts(
                subscription.id, period_start, lock=False
            )
            self._assert_recovery_history(subscription, recovery, period_end)
        except RenewalBillingConflict:
            return self._eligibility(
                SUSPENDED_RENEWAL_RECOVERY, "financial_conflict", subscription
            )
        latest = recovery[-1] if recovery else original[-1]
        if self._first_charge._usable_default_payment_method(account_id) is None:
            return self._eligibility(
                SUSPENDED_RENEWAL_RECOVERY,
                "blocked_payment_method",
                subscription,
                latest,
            )
        if self._first_charge._valid_delivery_email(account_id) is None:
            return self._eligibility(
                SUSPENDED_RENEWAL_RECOVERY,
                "blocked_delivery_email",
                subscription,
                latest,
            )
        return self._eligibility(
            SUSPENDED_RENEWAL_RECOVERY,
            "eligible",
            subscription,
            latest,
            eligible=True,
        )

    def _assert_suspended_renewal_obligation(self, subscription, *, lock):
        if subscription.state != SubscriptionState.SUSPENDED.value:
            raise RenewalBillingConflict("subscription is not suspended")
        period_start = subscription.current_period_end
        if period_start is None or subscription.next_billing_at is None:
            raise RenewalBillingConflict("missed renewal period is unavailable")
        period_end = _next_monthly_anchor(
            ensure_utc(subscription.next_billing_at), subscription.billing_anchor_day
        ).astimezone(self._kst()).date()
        query = (
            sa.select(BillingAttempt)
            .where(
                BillingAttempt.subscription_id == subscription.id,
                BillingAttempt.purpose == RENEWAL_PURPOSE,
                BillingAttempt.billing_period_start == period_start,
            )
            .order_by(BillingAttempt.attempt_no.asc())
        )
        if lock:
            query = query.with_for_update()
        attempts = list(self._session.scalars(query).all())
        if len(attempts) != len(RENEWAL_OFFSETS):
            raise RenewalBillingConflict("suspended renewal cadence is incomplete")
        for index, attempt in enumerate(attempts):
            payment_owner = self._session.scalar(
                sa.select(PaymentMethod.account_id).where(
                    PaymentMethod.id == attempt.payment_method_id
                )
            )
            if (
                attempt.attempt_no != index + 1
                or attempt.retry_offset_day != RENEWAL_OFFSETS[index]
                or attempt.status != BillingAttemptStatus.FAILED.value
                or attempt.account_id != subscription.account_id
                or payment_owner != subscription.account_id
                or attempt.billing_period_end != period_end
                or attempt.amount_krw != subscription.contracted_price_krw
                or attempt.currency != subscription.contracted_currency
                or attempt.plan_code != subscription.contracted_plan_code
                or attempt.price_version != subscription.contracted_price_version
            ):
                raise RenewalBillingConflict("suspended renewal authority conflicts")
        conflict = self._session.scalar(
            sa.select(BillingEvent.id)
            .where(
                BillingEvent.billing_attempt_id.in_([item.id for item in attempts]),
                BillingEvent.event_type.like("%contradictory_observation%"),
            )
            .limit(1)
        )
        if conflict is not None:
            raise RenewalBillingConflict("renewal obligation has a financial conflict")
        return attempts, period_start, period_end

    def _assert_recovery_history(self, subscription, attempts, period_end):
        for index, attempt in enumerate(attempts):
            payment_owner = self._session.scalar(
                sa.select(PaymentMethod.account_id).where(
                    PaymentMethod.id == attempt.payment_method_id
                )
            )
            if (
                attempt.attempt_no != index + 1
                or attempt.retry_offset_day is not None
                or attempt.conversion_snapshot_id is not None
                or attempt.account_id != subscription.account_id
                or payment_owner != subscription.account_id
                or attempt.billing_period_start != subscription.current_period_end
                or attempt.billing_period_end != period_end
                or attempt.amount_krw != subscription.contracted_price_krw
                or attempt.currency != subscription.contracted_currency
                or attempt.plan_code != subscription.contracted_plan_code
                or attempt.price_version != subscription.contracted_price_version
            ):
                raise RenewalBillingConflict("renewal recovery history conflicts")
        if any(item.status == BillingAttemptStatus.SUCCEEDED.value for item in attempts):
            raise RenewalBillingConflict("suspended obligation was already recovered")
        if attempts and attempts[-1].status not in {
            BillingAttemptStatus.FAILED.value,
            BillingAttemptStatus.PENDING.value,
            BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
        }:
            raise RenewalBillingConflict("renewal recovery state is invalid")

    def _assert_recovery_attempt_authority(self, attempt, subscription):
        if subscription.state != SubscriptionState.SUSPENDED.value:
            raise RenewalBillingConflict("subscription is no longer suspended")
        self._renewal._assert_contract_authority(subscription)
        self._assert_suspended_renewal_obligation(subscription, lock=True)
        payment_owner = self._session.scalar(
            sa.select(PaymentMethod.account_id)
            .where(PaymentMethod.id == attempt.payment_method_id)
            .with_for_update()
        )
        expected_end = _next_monthly_anchor(
            ensure_utc(subscription.next_billing_at), subscription.billing_anchor_day
        ).astimezone(self._kst()).date()
        if (
            attempt.purpose != RECOVERY_PURPOSE
            or attempt.conversion_snapshot_id is not None
            or attempt.retry_offset_day is not None
            or attempt.account_id != subscription.account_id
            or payment_owner != subscription.account_id
            or attempt.billing_period_start != subscription.current_period_end
            or attempt.billing_period_end != expected_end
            or attempt.amount_krw != subscription.contracted_price_krw
            or attempt.currency != subscription.contracted_currency
            or attempt.plan_code != subscription.contracted_plan_code
            or attempt.price_version != subscription.contracted_price_version
        ):
            raise RenewalBillingConflict("renewal recovery attempt differs from obligation")

    def _replay_command(self, command, account_id, kind):
        if command.account_id != account_id or not command.result_reference:
            raise IdempotencyKeyConflict("recovery key belongs to another command")
        attempt = self._attempt(command.result_reference)
        expected_purpose = (
            FIRST_CHARGE_PURPOSE if kind == FIRST_CHARGE_RECOVERY else RECOVERY_PURPOSE
        )
        if attempt.account_id != account_id or attempt.purpose != expected_purpose:
            raise IdempotencyKeyConflict("recovery result authority is invalid")
        expected = _fingerprint(
            kind,
            account_id,
            attempt.subscription_id,
            attempt.amount_krw,
            attempt.idempotency_key,
        )
        if command.request_fingerprint != expected:
            raise IdempotencyKeyConflict("recovery key parameters differ")
        subscription = self._session.get(Subscription, attempt.subscription_id)
        if subscription is None:
            raise IdempotencyKeyConflict("recovery result is unavailable")
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            status = "succeeded"
        elif attempt.status == BillingAttemptStatus.FAILED.value:
            status = "failed"
        else:
            status = "provider_state_unknown"
        return self._result(
            kind,
            status,
            account_id,
            subscription.id,
            attempt,
            replayed=True,
            reconciliation_required=attempt.status in _UNRESOLVED,
            delivery_available=(
                kind == SUSPENDED_RENEWAL_RECOVERY
                and attempt.status == BillingAttemptStatus.SUCCEEDED.value
            ),
        )

    def _record_command(
        self, *, command_name, key, account_id, attempt_id, fingerprint
    ):
        now = ensure_utc(self._clock.now())
        self._session.add(
            CommandIdempotency(
                account_id=account_id,
                command=command_name,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                status=CommandIdempotencyStatus.IN_PROGRESS.value,
                result_reference=str(attempt_id),
                created_at=now,
                updated_at=now,
            )
        )
        self._session.flush()

    def _complete_command(self, command_name, attempt_id):
        command = self._session.scalar(
            sa.select(CommandIdempotency)
            .where(
                CommandIdempotency.command == command_name,
                CommandIdempotency.result_reference == str(attempt_id),
            )
            .with_for_update()
        )
        if command is None:
            raise IdempotencyKeyConflict("recovery command evidence is unavailable")
        now = ensure_utc(self._clock.now())
        command.status = CommandIdempotencyStatus.COMPLETED.value
        command.completed_at = command.completed_at or now
        command.updated_at = now
        self._session.flush()

    def _record_requested(self, result, *, amount_krw, attempt_no):
        self._audit.record(
            audit_events.BILLING_RECOVERY_REQUESTED,
            account_id=result.account_id,
            subscription_id=result.subscription_id,
            actor_type="customer",
            entity_type="billing_attempt",
            entity_id=result.billing_attempt_id,
            payload={
                "recovery_kind": result.kind,
                "amount_krw": amount_krw,
                "attempt_no": attempt_no,
                "explicit_customer_action": True,
                "automatic_retry": False,
            },
        )

    def _record_outcome(self, result, attempt, *, reconciled):
        if result.status == "succeeded":
            event = (
                audit_events.BILLING_RECOVERY_RECONCILIATION_SUCCEEDED
                if reconciled
                else audit_events.BILLING_RECOVERY_SUCCEEDED
            )
        elif result.status == "failed":
            event = (
                audit_events.BILLING_RECOVERY_RECONCILIATION_FAILED
                if reconciled
                else audit_events.BILLING_RECOVERY_FAILED
            )
        else:
            event = (
                audit_events.BILLING_RECOVERY_RECONCILIATION_UNKNOWN
                if reconciled
                else audit_events.BILLING_RECOVERY_UNKNOWN
            )
        self._audit.record(
            event,
            account_id=result.account_id,
            subscription_id=result.subscription_id,
            actor_type="customer" if not reconciled else "system",
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "recovery_kind": result.kind,
                "attempt_no": attempt.attempt_no,
                "amount_krw": attempt.amount_krw,
                "reconciliation_required": result.reconciliation_required,
            },
        )

    def _record_event(self, attempt, event_type, reference, detail):
        self._session.add(
            BillingEvent(
                billing_attempt_id=attempt.id,
                event_type=event_type,
                occurred_at=ensure_utc(self._clock.now()),
                provider_event_reference=_safe_reference(reference, required=False),
                detail=dict(detail),
                created_at=ensure_utc(self._clock.now()),
            )
        )
        self._session.flush()

    def _active_account(self, account_id):
        account = self._session.scalar(
            sa.select(CustomerAccount)
            .where(CustomerAccount.id == account_id)
            .with_for_update()
        )
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise FirstChargeConflict("active Customer account is required")
        return account

    def _latest_snapshot(self, account_id, *, lock):
        query = (
            sa.select(ConversionSnapshot)
            .where(ConversionSnapshot.account_id == account_id)
            .order_by(ConversionSnapshot.created_at.desc(), ConversionSnapshot.id.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def _suspended_subscription(self, account_id, *, lock):
        query = sa.select(Subscription).where(
            Subscription.account_id == account_id,
            Subscription.state == SubscriptionState.SUSPENDED.value,
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def _first_charge_attempts(self, snapshot_id, *, lock):
        query = (
            sa.select(BillingAttempt)
            .where(
                BillingAttempt.conversion_snapshot_id == snapshot_id,
                BillingAttempt.purpose == FIRST_CHARGE_PURPOSE,
            )
            .order_by(BillingAttempt.attempt_no.asc())
        )
        if lock:
            query = query.with_for_update()
        return list(self._session.scalars(query).all())

    def _recovery_attempts(self, subscription_id, period_start, *, lock):
        query = (
            sa.select(BillingAttempt)
            .where(
                BillingAttempt.subscription_id == subscription_id,
                BillingAttempt.purpose == RECOVERY_PURPOSE,
                BillingAttempt.billing_period_start == period_start,
            )
            .order_by(BillingAttempt.attempt_no.asc())
        )
        if lock:
            query = query.with_for_update()
        return list(self._session.scalars(query).all())

    def _unresolved_attempt(self, subscription_id, *, lock):
        query = (
            sa.select(BillingAttempt)
            .where(
                BillingAttempt.subscription_id == subscription_id,
                BillingAttempt.status.in_(_UNRESOLVED),
            )
            .order_by(BillingAttempt.created_at.asc(), BillingAttempt.id.asc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        return self._session.scalar(query)

    def _locked_recovery_attempt(self, attempt_id):
        reference = self._session.get(BillingAttempt, attempt_id)
        if reference is None or reference.purpose != RECOVERY_PURPOSE:
            raise RenewalBillingConflict("renewal recovery attempt is unavailable")
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.id == reference.subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = self._session.scalar(
            sa.select(BillingAttempt)
            .where(BillingAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subscription is None or attempt is None:
            raise RenewalBillingConflict("renewal recovery authority is incomplete")
        return attempt, subscription

    def _attempt(self, attempt_id):
        try:
            identifier = uuid.UUID(str(attempt_id))
        except (TypeError, ValueError):
            raise IdempotencyKeyConflict("recovery attempt reference is invalid")
        attempt = self._session.get(BillingAttempt, identifier)
        if attempt is None:
            raise IdempotencyKeyConflict("recovery attempt is unavailable")
        return attempt

    def _command(self, name, key):
        return self._session.scalar(
            sa.select(CommandIdempotency)
            .where(
                CommandIdempotency.command == name,
                CommandIdempotency.idempotency_key == key,
            )
            .with_for_update()
        )

    @staticmethod
    def _from_first_charge(account_id, result):
        return BillingRecoveryResult(
            kind=FIRST_CHARGE_RECOVERY,
            status=result.status,
            account_id=account_id,
            subscription_id=result.subscription_id,
            billing_attempt_id=result.billing_attempt_id,
            replayed=result.replayed,
            reconciliation_required=result.reconciliation_required,
            delivery_available=result.status == "succeeded",
        )

    @staticmethod
    def _result(
        kind,
        status,
        account_id,
        subscription_id,
        attempt=None,
        *,
        replayed=False,
        reconciliation_required=False,
        delivery_available=False,
    ):
        return BillingRecoveryResult(
            kind=kind,
            status=status,
            account_id=account_id,
            subscription_id=subscription_id,
            billing_attempt_id=attempt.id if attempt is not None else None,
            replayed=replayed,
            reconciliation_required=reconciliation_required,
            delivery_available=delivery_available,
        )

    @staticmethod
    def _eligibility(
        kind,
        status,
        subscription=None,
        attempt=None,
        *,
        eligible=False,
        reconciliation_required=False,
    ):
        return RecoveryEligibility(
            kind=kind,
            eligible=eligible,
            status=status,
            subscription_id=subscription.id if subscription is not None else None,
            billing_attempt_id=attempt.id if attempt is not None else None,
            reconciliation_required=reconciliation_required,
        )

    @staticmethod
    def _kst():
        from customer.services.first_charge_service import KST

        return KST


class BillingRecoveryExecutor:
    """Two-transaction explicit recovery executor; never an automatic worker."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        first_charge_provider: FirstChargeProvider,
        renewal_provider: Optional[RenewalChargeProvider] = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._first_provider = first_charge_provider
        self._renewal_provider = renewal_provider or first_charge_provider

    def recover_first_charge(self, account_id, *, idempotency_key):
        session = self._session_factory()
        try:
            with session.begin():
                prepared = BillingRecoveryService(session, self._clock).prepare_first_charge(
                    account_id=account_id,
                    idempotency_key=idempotency_key,
                    provider_name=self._first_provider.name,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result
        try:
            provider_result = self._first_provider.charge(prepared.request)
            if not isinstance(provider_result, FirstChargeProviderResult):
                provider_result = FirstChargeProviderResult.unknown()
        except Exception:
            provider_result = FirstChargeProviderResult.unknown()
        session = self._session_factory()
        try:
            with session.begin():
                return BillingRecoveryService(
                    session, self._clock
                ).apply_first_charge_result(
                    account_id=account_id,
                    billing_attempt_id=uuid.UUID(prepared.request.attempt_id),
                    provider_result=provider_result,
                )
        finally:
            session.close()

    def recover_suspended_renewal(self, account_id, *, idempotency_key):
        session = self._session_factory()
        try:
            with session.begin():
                prepared = BillingRecoveryService(
                    session, self._clock
                ).prepare_suspended_renewal(
                    account_id=account_id,
                    idempotency_key=idempotency_key,
                    provider_name=self._renewal_provider.name,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result
        try:
            provider_result = self._renewal_provider.charge_renewal(prepared.request)
            if not isinstance(provider_result, FirstChargeProviderResult):
                provider_result = FirstChargeProviderResult.unknown()
        except Exception:
            provider_result = FirstChargeProviderResult.unknown()
        session = self._session_factory()
        try:
            with session.begin():
                return BillingRecoveryService(
                    session, self._clock
                ).apply_suspended_renewal_result(
                    account_id=account_id,
                    billing_attempt_id=uuid.UUID(prepared.request.attempt_id),
                    provider_result=provider_result,
                )
        finally:
            session.close()


class BillingRecoveryReconciliationService:
    """Query-only resolution for an UNKNOWN suspended-renewal recovery."""

    def __init__(self, session: Session, clock: Clock) -> None:
        self._service = BillingRecoveryService(session, clock)
        self._session = session

    def prepare(self, *, billing_attempt_id, provider_name, capabilities):
        provider = _safe_provider_name(provider_name)
        attempt, subscription = self._service._locked_recovery_attempt(
            billing_attempt_id
        )
        if attempt.provider != provider:
            raise RenewalBillingConflict("recovery reconciliation provider differs")
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            return PreparedRecoveryReconciliation(
                self._service._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "succeeded",
                    attempt.account_id,
                    subscription.id,
                    attempt,
                    replayed=True,
                    delivery_available=True,
                )
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            return PreparedRecoveryReconciliation(
                self._service._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "failed",
                    attempt.account_id,
                    subscription.id,
                    attempt,
                    replayed=True,
                )
            )
        self._service._assert_recovery_attempt_authority(attempt, subscription)
        operation_reference = self._operation_reference(attempt.id)
        if operation_reference:
            basis = ReconciliationLookupBasis.OPERATION_REFERENCE
        elif capabilities.authoritative_idempotency_lookup:
            basis = ReconciliationLookupBasis.IDEMPOTENCY_KEY
        else:
            return PreparedRecoveryReconciliation(
                self._service._result(
                    SUSPENDED_RENEWAL_RECOVERY,
                    "query_authority_unavailable",
                    attempt.account_id,
                    subscription.id,
                    attempt,
                    replayed=True,
                    reconciliation_required=True,
                )
            )
        return PreparedRecoveryReconciliation(
            self._service._result(
                SUSPENDED_RENEWAL_RECOVERY,
                "prepared_reconciliation",
                attempt.account_id,
                subscription.id,
                attempt,
                reconciliation_required=True,
            ),
            RenewalChargeReconciliationRequest(
                attempt_id=str(attempt.id),
                provider=provider,
                lookup_basis=basis,
                original_idempotency_key=attempt.idempotency_key,
                original_operation_reference=operation_reference,
            ),
        )

    def apply(
        self,
        *,
        billing_attempt_id,
        provider_result,
        lookup_basis,
        idempotency_lookup_authoritative,
    ):
        attempt, subscription = self._service._locked_recovery_attempt(
            billing_attempt_id
        )
        if attempt.status == BillingAttemptStatus.PENDING.value:
            operation_authority = (
                lookup_basis == ReconciliationLookupBasis.OPERATION_REFERENCE
                and self._operation_reference(attempt.id) is not None
            )
            idempotency_authority = (
                lookup_basis == ReconciliationLookupBasis.IDEMPOTENCY_KEY
                and idempotency_lookup_authoritative
            )
            if not (operation_authority or idempotency_authority):
                raise RenewalBillingConflict(
                    "pending recovery lacks authoritative lookup evidence"
                )
        if provider_result.outcome == ReconciliationOutcome.CONFIRMED_SUCCESS:
            outcome = FirstChargeProviderResult.succeeded(
                provider_result.transaction_reference,
                event_reference=provider_result.provider_event_reference,
            )
        elif provider_result.outcome == ReconciliationOutcome.CONFIRMED_FAILURE:
            outcome = FirstChargeProviderResult.failed(
                provider_result.failure_code,
                event_reference=provider_result.provider_event_reference,
            )
        else:
            outcome = FirstChargeProviderResult.unknown(
                operation_reference=provider_result.provider_event_reference
            )
        return self._service.apply_suspended_renewal_result(
            account_id=attempt.account_id,
            billing_attempt_id=attempt.id,
            provider_result=outcome,
            reconciled=True,
        )

    def _operation_reference(self, attempt_id):
        return self._session.scalar(
            sa.select(BillingEvent.provider_event_reference)
            .where(
                BillingEvent.billing_attempt_id == attempt_id,
                BillingEvent.event_type == "billing_recovery_provider_state_unknown",
                BillingEvent.provider_event_reference.is_not(None),
            )
            .order_by(BillingEvent.occurred_at.asc(), BillingEvent.id.asc())
            .limit(1)
        )


class BillingRecoveryReconciliationExecutor:
    """Provider query boundary; cannot issue any recovery charge."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        provider: RenewalChargeReconciliationProvider,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider = provider

    def execute(self, billing_attempt_id):
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
                prepared = BillingRecoveryReconciliationService(
                    session, self._clock
                ).prepare(
                    billing_attempt_id=billing_attempt_id,
                    provider_name=self._provider.name,
                    capabilities=capabilities,
                )
        finally:
            session.close()
        if prepared.request is None:
            return prepared.result
        try:
            result = self._provider.reconcile_renewal(prepared.request)
            if not isinstance(result, FirstChargeReconciliationResult):
                result = FirstChargeReconciliationResult.still_unknown()
        except Exception:
            result = FirstChargeReconciliationResult.still_unknown()
        if result.outcome == ReconciliationOutcome.NOT_FOUND:
            if capabilities.definitive_not_found_means_no_charge:
                result = FirstChargeReconciliationResult.confirmed_failure(
                    "PROVIDER_TRANSACTION_NOT_FOUND",
                    event_reference=result.provider_event_reference,
                )
            else:
                result = FirstChargeReconciliationResult.still_unknown(
                    event_reference=result.provider_event_reference
                )
        session = self._session_factory()
        try:
            with session.begin():
                return BillingRecoveryReconciliationService(
                    session, self._clock
                ).apply(
                    billing_attempt_id=billing_attempt_id,
                    provider_result=result,
                    lookup_basis=prepared.request.lookup_basis,
                    idempotency_lookup_authoritative=(
                        capabilities.authoritative_idempotency_lookup
                    ),
                )
        finally:
            session.close()


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 200:
        raise IdempotencyKeyConflict("invalid recovery idempotency key")
    return normalized


def _fingerprint(kind, account_id, subscription_id, amount_krw, provider_key):
    raw = "billing-recovery-v1:{0}:{1}:{2}:{3}:{4}".format(
        kind, account_id, subscription_id, amount_krw, provider_key
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
