"""Query-only reconciliation of an indeterminate first-charge attempt.

The original ``BillingAttempt`` remains the sole economic charge authority.
This service only asks the provider about that attempt's original idempotency
key/operation reference; it cannot construct or submit a charge request.
"""

import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    BillingAttemptStatus,
    ConversionSnapshotStatus,
    SubscriptionState,
)
from customer.domain.errors import FirstChargeConflict
from customer.persistence.models import (
    BillingAttempt,
    BillingEvent,
    ConversionSnapshot,
    Entitlement,
    PaymentMethod,
    Subscription,
    SubscriptionProduct,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService
from customer.services.charge_providers import (
    FirstChargeReconciliationCapabilities,
    FirstChargeReconciliationProvider,
    FirstChargeReconciliationRequest,
    FirstChargeReconciliationResult,
    ReconciliationLookupBasis,
    ReconciliationOutcome,
)
from customer.services.first_charge_service import (
    FIRST_CHARGE_PURPOSE,
    FirstChargeService,
    _safe_failure_code,
    _safe_provider_name,
    _safe_reference,
)


@dataclass(frozen=True)
class ReconciliationExecutionResult:
    status: str
    billing_attempt_id: Optional[uuid.UUID]
    subscription_id: Optional[uuid.UUID]
    conversion_snapshot_id: Optional[uuid.UUID]
    replayed: bool = False
    reconciliation_required: bool = False
    observation_count: int = 0
    delivery_authority_available: Optional[bool] = None


@dataclass(frozen=True)
class PreparedReconciliation:
    result: ReconciliationExecutionResult
    request: Optional[FirstChargeReconciliationRequest] = None


class FirstChargeReconciliationService:
    """Transactional reconciliation state machine for one original attempt."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)
        self._first_charge = FirstChargeService(session, clock, audit=self._audit)

    def prepare(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_name: str,
        capabilities: FirstChargeReconciliationCapabilities = (
            FirstChargeReconciliationCapabilities()
        ),
    ) -> PreparedReconciliation:
        provider = _safe_provider_name(provider_name)
        attempt, snapshot, subscription = self._locked_authority(billing_attempt_id)
        if attempt is None:
            return PreparedReconciliation(self._empty_result("not_eligible"))

        if attempt.provider != provider:
            raise FirstChargeConflict("reconciliation provider differs from original")
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            return PreparedReconciliation(
                self._result(
                    "confirmed_success", attempt, snapshot, subscription, replayed=True
                )
            )
        if attempt.status == BillingAttemptStatus.FAILED.value:
            return PreparedReconciliation(
                self._result(
                    "confirmed_failure", attempt, snapshot, subscription, replayed=True
                )
            )
        if attempt.status not in {
            BillingAttemptStatus.PENDING.value,
            BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
        }:
            return PreparedReconciliation(
                self._result("not_eligible", attempt, snapshot, subscription)
            )

        self._assert_indeterminate_authority(attempt, snapshot, subscription)
        operation_reference = self._original_operation_reference(attempt.id)
        if operation_reference:
            lookup_basis = ReconciliationLookupBasis.OPERATION_REFERENCE
        elif capabilities.authoritative_idempotency_lookup:
            lookup_basis = ReconciliationLookupBasis.IDEMPOTENCY_KEY
        else:
            return PreparedReconciliation(
                self._result(
                    "query_authority_unavailable",
                    attempt,
                    snapshot,
                    subscription,
                    reconciliation_required=True,
                )
            )
        request = FirstChargeReconciliationRequest(
            attempt_id=str(attempt.id),
            provider=provider,
            lookup_basis=lookup_basis,
            original_idempotency_key=attempt.idempotency_key,
            original_operation_reference=operation_reference,
        )
        return PreparedReconciliation(
            self._result(
                "prepared",
                attempt,
                snapshot,
                subscription,
                reconciliation_required=True,
            ),
            request,
        )

    def apply_provider_result(
        self,
        *,
        billing_attempt_id: uuid.UUID,
        provider_result: FirstChargeReconciliationResult,
        lookup_basis: Optional[ReconciliationLookupBasis] = None,
        idempotency_lookup_authoritative: bool = False,
    ) -> ReconciliationExecutionResult:
        attempt, snapshot, subscription = self._locked_authority(billing_attempt_id)
        if attempt is None:
            raise FirstChargeConflict("reconciliation attempt is unavailable")

        if attempt.status not in {
            BillingAttemptStatus.PENDING.value,
            BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value,
        }:
            return self._apply_to_terminal(
                attempt, snapshot, subscription, provider_result
            )

        self._assert_indeterminate_authority(attempt, snapshot, subscription)
        if attempt.status == BillingAttemptStatus.PENDING.value:
            operation_reference_is_durable = (
                lookup_basis == ReconciliationLookupBasis.OPERATION_REFERENCE
                and self._original_operation_reference(attempt.id) is not None
            )
            idempotency_lookup_is_authoritative = (
                lookup_basis == ReconciliationLookupBasis.IDEMPOTENCY_KEY
                and idempotency_lookup_authoritative
            )
            if not (
                operation_reference_is_durable
                or idempotency_lookup_is_authoritative
            ):
                raise FirstChargeConflict(
                    "pending first-charge command lacks authoritative lookup evidence"
                )
        now = ensure_utc(self._clock.now())
        attempt.updated_at = now

        if provider_result.outcome == ReconciliationOutcome.CONFIRMED_SUCCESS:
            transaction_reference = _safe_reference(
                provider_result.transaction_reference, required=True
            )
            attempt.status = BillingAttemptStatus.SUCCEEDED.value
            attempt.provider_transaction_reference = transaction_reference
            attempt.failure_code = None
            attempt.failure_message = None
            attempt.settled_at = now
            observation_count = self._record_observation(
                attempt,
                "first_charge_reconciliation_confirmed_success",
                now,
                provider_result.provider_event_reference or transaction_reference,
                {"authoritative": True, "charge_command_created": False},
            )
            self._first_charge._activate_paid_contract(subscription, snapshot, now)
            delivery_authority_available = (
                self._first_charge._valid_delivery_email(attempt.account_id) is not None
            )
            self._audit.record(
                audit_events.FIRST_CHARGE_RECONCILIATION_SUCCEEDED,
                account_id=attempt.account_id,
                subscription_id=attempt.subscription_id,
                entity_type="billing_attempt",
                entity_id=attempt.id,
                payload={
                    "attempt_no": attempt.attempt_no,
                    "observation_count": observation_count,
                    "amount_krw": attempt.amount_krw,
                    "currency": attempt.currency,
                    "charged_again": False,
                },
            )
            return self._result(
                "confirmed_success",
                attempt,
                snapshot,
                subscription,
                observation_count=observation_count,
                delivery_authority_available=delivery_authority_available,
            )

        if provider_result.outcome == ReconciliationOutcome.CONFIRMED_FAILURE:
            failure_code = _safe_failure_code(provider_result.failure_code)
            attempt.status = BillingAttemptStatus.FAILED.value
            attempt.failure_code = failure_code
            attempt.failure_message = (
                "provider reconciliation definitively rejected first charge"
            )
            observation_count = self._record_observation(
                attempt,
                "first_charge_reconciliation_confirmed_failure",
                now,
                provider_result.provider_event_reference,
                {
                    "authoritative": True,
                    "failure_code": failure_code,
                    "automatic_retry": False,
                },
            )
            self._first_charge._expire_without_paid_delivery(subscription, now)
            self._audit.record(
                audit_events.FIRST_CHARGE_RECONCILIATION_FAILED,
                account_id=attempt.account_id,
                subscription_id=attempt.subscription_id,
                entity_type="billing_attempt",
                entity_id=attempt.id,
                payload={
                    "attempt_no": attempt.attempt_no,
                    "observation_count": observation_count,
                    "failure_code": failure_code,
                    "retry_required": True,
                    "grace_days": 0,
                    "delivery_enabled": False,
                    "charged_again": False,
                },
            )
            return self._result(
                "confirmed_failure",
                attempt,
                snapshot,
                subscription,
                observation_count=observation_count,
            )

        attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
        attempt.failure_code = "PROVIDER_STATE_UNKNOWN"
        attempt.failure_message = "provider outcome requires reconciliation"
        observation_count = self._record_observation(
            attempt,
            "first_charge_reconciliation_still_unknown",
            now,
            provider_result.provider_event_reference,
            {
                "reconciliation_required": True,
                "automatic_retry": False,
                "charge_command_created": False,
            },
        )
        self._audit.record(
            audit_events.FIRST_CHARGE_RECONCILIATION_UNKNOWN,
            account_id=attempt.account_id,
            subscription_id=attempt.subscription_id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "observation_count": observation_count,
                "reconciliation_required": True,
                "delivery_enabled": False,
                "charged_again": False,
            },
        )
        return self._result(
            "still_unknown",
            attempt,
            snapshot,
            subscription,
            reconciliation_required=True,
            observation_count=observation_count,
        )

    def _apply_to_terminal(self, attempt, snapshot, subscription, observed):
        if attempt.status == BillingAttemptStatus.SUCCEEDED.value:
            if observed.outcome == ReconciliationOutcome.CONFIRMED_SUCCESS:
                reference = _safe_reference(
                    observed.transaction_reference, required=True
                )
                if reference == attempt.provider_transaction_reference:
                    return self._result(
                        "confirmed_success",
                        attempt,
                        snapshot,
                        subscription,
                        replayed=True,
                    )
                preserve_status = "contradictory_observation"
            else:
                preserve_status = "confirmed_success"
            return self._record_terminal_conflict(
                attempt,
                snapshot,
                subscription,
                observed,
                preserve_status=preserve_status,
            )

        if attempt.status == BillingAttemptStatus.FAILED.value:
            if observed.outcome != ReconciliationOutcome.CONFIRMED_SUCCESS:
                return self._result(
                    "confirmed_failure",
                    attempt,
                    snapshot,
                    subscription,
                    replayed=True,
                )
            # A late success after a definitive failure is financially
            # contradictory. Return the original attempt to UNKNOWN so the
            # existing retry path is blocked until the conflict is resolved.
            has_other_success = self._session.scalar(
                sa.select(sa.func.count())
                .select_from(BillingAttempt)
                .where(
                    BillingAttempt.conversion_snapshot_id == snapshot.id,
                    BillingAttempt.id != attempt.id,
                    BillingAttempt.status == BillingAttemptStatus.SUCCEEDED.value,
                )
            )
            if not has_other_success:
                attempt.status = BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
                attempt.failure_code = "PROVIDER_OBSERVATION_CONFLICT"
                attempt.failure_message = "provider observations conflict"
                attempt.updated_at = ensure_utc(self._clock.now())
                subscription.state = SubscriptionState.CONVERSION_SCHEDULED.value
                subscription.ended_at = None
                subscription.updated_at = ensure_utc(self._clock.now())
            return self._record_terminal_conflict(
                attempt,
                snapshot,
                subscription,
                observed,
                preserve_status="contradictory_observation",
            )

        raise FirstChargeConflict("reconciliation state changed unexpectedly")

    def _record_terminal_conflict(
        self, attempt, snapshot, subscription, observed, *, preserve_status
    ):
        now = ensure_utc(self._clock.now())
        observation_count = self._record_observation(
            attempt,
            "first_charge_reconciliation_contradictory_observation",
            now,
            observed.provider_event_reference,
            {
                "observed_outcome": observed.outcome.value,
                "stored_status": attempt.status,
                "economic_state_changed": False,
            },
        )
        self._audit.record(
            audit_events.FIRST_CHARGE_RECONCILIATION_CONFLICT,
            account_id=attempt.account_id,
            subscription_id=attempt.subscription_id,
            entity_type="billing_attempt",
            entity_id=attempt.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "observation_count": observation_count,
                "observed_outcome": observed.outcome.value,
                "stored_status": attempt.status,
                "economic_state_changed": False,
            },
        )
        return self._result(
            preserve_status,
            attempt,
            snapshot,
            subscription,
            replayed=True,
            reconciliation_required=(
                attempt.status
                == BillingAttemptStatus.PROVIDER_STATE_UNKNOWN.value
            ),
            observation_count=observation_count,
        )

    def _locked_authority(self, billing_attempt_id):
        reference = self._session.get(BillingAttempt, billing_attempt_id)
        if reference is None or reference.purpose != FIRST_CHARGE_PURPOSE:
            return None, None, None
        snapshot = self._session.scalar(
            sa.select(ConversionSnapshot)
            .where(ConversionSnapshot.id == reference.conversion_snapshot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.id == reference.subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = self._session.scalar(
            sa.select(BillingAttempt)
            .where(BillingAttempt.id == billing_attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None or snapshot is None or subscription is None:
            raise FirstChargeConflict("reconciliation authority is incomplete")
        return attempt, snapshot, subscription

    def _assert_indeterminate_authority(
        self, attempt, snapshot, subscription
    ) -> None:
        payment_owner = self._session.scalar(
            sa.select(PaymentMethod.account_id)
            .where(PaymentMethod.id == attempt.payment_method_id)
            .with_for_update()
        )
        live_entitlements = self._session.scalar(
            sa.select(sa.func.count())
            .select_from(Entitlement)
            .where(
                Entitlement.subscription_id == subscription.id,
                Entitlement.revoked_at.is_(None),
            )
        )
        paid_products = self._session.scalar(
            sa.select(sa.func.count())
            .select_from(SubscriptionProduct)
            .where(SubscriptionProduct.subscription_id == subscription.id)
        )
        if (
            attempt.account_id != snapshot.account_id
            or attempt.subscription_id != snapshot.subscription_id
            or snapshot.subscription_id != subscription.id
            or snapshot.account_id != subscription.account_id
            or payment_owner != attempt.account_id
            or attempt.amount_krw != snapshot.price_krw
            or attempt.currency != snapshot.currency
            or attempt.plan_code != snapshot.plan_code
            or attempt.price_version != snapshot.price_version
            or ensure_utc(snapshot.first_charge_at)
            != ensure_utc(subscription.trial_end_at)
            or snapshot.status != ConversionSnapshotStatus.PENDING.value
            or subscription.state
            != SubscriptionState.CONVERSION_SCHEDULED.value
            or subscription.contracted_plan_code is not None
            or subscription.billing_anchor_day is not None
            or subscription.current_period_start is not None
            or subscription.current_period_end is not None
            or subscription.next_billing_at is not None
            or int(live_entitlements or 0) != 0
            or int(paid_products or 0) != 0
            or not attempt.provider
            or not attempt.idempotency_key
        ):
            raise FirstChargeConflict("unknown first-charge authority is inconsistent")

    def _record_observation(self, attempt, event_type, now, reference, detail):
        provider_reference = _safe_reference(reference, required=False)
        if provider_reference is not None:
            existing = self._session.scalar(
                sa.select(BillingEvent).where(
                    BillingEvent.provider_event_reference == provider_reference
                )
            )
            if existing is not None:
                if existing.billing_attempt_id != attempt.id:
                    raise FirstChargeConflict(
                        "provider observation belongs to another attempt"
                    )
                provider_reference = None
        count = self._session.scalar(
            sa.select(sa.func.count())
            .select_from(BillingEvent)
            .where(
                BillingEvent.billing_attempt_id == attempt.id,
                BillingEvent.event_type.like("first_charge_reconciliation_%"),
            )
        )
        observation_count = int(count or 0) + 1
        bounded_detail = dict(detail)
        bounded_detail["observation_count"] = observation_count
        self._session.add(
            BillingEvent(
                billing_attempt_id=attempt.id,
                event_type=event_type,
                occurred_at=now,
                provider_event_reference=provider_reference,
                detail=bounded_detail,
                created_at=now,
            )
        )
        self._session.flush()
        return observation_count

    def _original_operation_reference(self, attempt_id):
        return self._session.scalar(
            sa.select(BillingEvent.provider_event_reference)
            .where(
                BillingEvent.billing_attempt_id == attempt_id,
                BillingEvent.event_type == "first_charge_provider_state_unknown",
                BillingEvent.provider_event_reference.is_not(None),
            )
            .order_by(BillingEvent.occurred_at.asc(), BillingEvent.id.asc())
            .limit(1)
        )

    @staticmethod
    def _empty_result(status):
        return ReconciliationExecutionResult(status, None, None, None)

    @staticmethod
    def _result(
        status,
        attempt,
        snapshot,
        subscription,
        *,
        replayed=False,
        reconciliation_required=False,
        observation_count=0,
        delivery_authority_available=None,
    ):
        return ReconciliationExecutionResult(
            status=status,
            billing_attempt_id=attempt.id,
            subscription_id=subscription.id,
            conversion_snapshot_id=snapshot.id,
            replayed=replayed,
            reconciliation_required=reconciliation_required,
            observation_count=observation_count,
            delivery_authority_available=delivery_authority_available,
        )


class FirstChargeReconciliationExecutor:
    """Future worker boundary that can query, but can never issue, a charge."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Clock,
        provider: FirstChargeReconciliationProvider,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider = provider

    def execute(self, billing_attempt_id: uuid.UUID) -> ReconciliationExecutionResult:
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
                prepared = FirstChargeReconciliationService(
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
            provider_result = self._provider.reconcile_first_charge(
                prepared.request
            )
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
                return FirstChargeReconciliationService(
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
