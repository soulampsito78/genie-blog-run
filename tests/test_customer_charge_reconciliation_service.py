"""Provider-neutral, query-only reconciliation of UNKNOWN first charges."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

sa = pytest.importorskip("sqlalchemy")

from customer.domain.clock import FixedClock  # noqa: E402
from customer.domain.errors import FirstChargeConflict  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    CustomerAccount,
    DeliveryEmail,
    DeliveryEvent,
    Entitlement,
    RecipientSnapshot,
    Subscription,
    SubscriptionProduct,
)
from customer.services.charge_providers import (  # noqa: E402
    FirstChargeProviderResult,
    FirstChargeReconciliationCapabilities,
    FirstChargeReconciliationResult,
    ReconciliationLookupBasis,
)
from customer.services.charge_reconciliation_service import (  # noqa: E402
    FirstChargeReconciliationExecutor,
    FirstChargeReconciliationService,
)
from customer.services.first_charge_service import (  # noqa: E402
    FirstChargeExecutor,
    FirstChargeService,
)
from tests.test_customer_first_charge_service import (  # noqa: E402
    NOW,
    FakeChargeProvider,
    _seed_case,
    first_charge_engine,
    session_factory,
)
from tests.customer_db_fixtures import (  # noqa: E402
    make_account,
    make_entitlement,
    make_payment_method,
)

__all__ = ["first_charge_engine", "session_factory"]


class FakeReconciliationProvider:
    name = "fake_charge_provider"

    def __init__(self, *results, raises=False, capabilities=None):
        self._results = list(results)
        self._raises = raises
        self.reconciliation_capabilities = (
            capabilities or FirstChargeReconciliationCapabilities()
        )
        self._lock = threading.Lock()
        self.reconciliation_requests = []
        self.charge_calls = 0

    def reconcile_first_charge(self, request):
        with self._lock:
            self.reconciliation_requests.append(request)
            if self._raises:
                raise RuntimeError("raw provider reconciliation secret")
            if not self._results:
                raise AssertionError("unexpected reconciliation query")
            return self._results.pop(0)

    def charge(self, request):  # pragma: no cover - absolute safety tripwire
        del request
        self.charge_calls += 1
        raise AssertionError("reconciliation must never issue a charge")


def _unknown_case(session_factory):
    case = _seed_case(session_factory)
    operation_reference = "op-original-{0}".format(case.snapshot_id)
    original = FakeChargeProvider(
        FirstChargeProviderResult.unknown(
            operation_reference=operation_reference
        )
    )
    result = FirstChargeExecutor(
        session_factory, FixedClock(NOW), original
    ).execute(case.snapshot_id)
    assert result.status == "provider_state_unknown"
    with session_factory() as session:
        attempt = session.scalar(
            sa.select(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        )
        return case, attempt.id, attempt.idempotency_key


def _executor(session_factory, provider):
    return FirstChargeReconciliationExecutor(
        session_factory, FixedClock(NOW), provider
    )


def test_unknown_to_confirmed_success_resolves_original_charge_once(
    session_factory,
):
    case, attempt_id, original_key = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success(
            "tx-reconciled", event_reference="evt-reconciled-success"
        )
    )
    result = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == "confirmed_success"
    assert result.delivery_authority_available is True
    assert provider.charge_calls == 0
    assert len(provider.reconciliation_requests) == 1
    request = provider.reconciliation_requests[0]
    assert request.original_idempotency_key == original_key
    assert request.original_operation_reference == "op-original-{0}".format(
        case.snapshot_id
    )
    assert original_key not in repr(request)
    assert "op-original" not in repr(request)

    with session_factory() as session:
        attempt = session.get(BillingAttempt, attempt_id)
        subscription = session.get(Subscription, case.subscription_id)
        assert attempt.status == "succeeded"
        assert attempt.provider_transaction_reference == "tx-reconciled"
        assert attempt.amount_krw == 16500 and attempt.currency == "KRW"
        assert subscription.state == "active"
        assert subscription.billing_anchor_day == 29
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 1
        assert {
            row.product_code
            for row in session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == case.subscription_id
                )
            )
        } == {"today_genie", "keysuri_global", "keysuri_korea"}
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.source == "paid",
                Entitlement.revoked_at.is_(None),
            )
        ) == 3


def test_unknown_to_confirmed_failure_preserves_explicit_retry_gate(
    session_factory,
):
    case, attempt_id, _ = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_failure(
            "DECLINED", event_reference="evt-reconciled-failure"
        )
    )
    result = _executor(session_factory, provider).execute(attempt_id)
    assert result.status == "confirmed_failure"
    assert provider.charge_calls == 0

    retry_provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-must-not-run")
    )
    first_charge = FirstChargeExecutor(
        session_factory, FixedClock(NOW), retry_provider
    )
    assert first_charge.execute(case.snapshot_id).status == "failed"
    assert first_charge.execute(
        case.snapshot_id, explicit_retry=True
    ).status == "payment_method_update_required"
    assert retry_provider.requests == []

    with session_factory() as session:
        attempt = session.get(BillingAttempt, attempt_id)
        subscription = session.get(Subscription, case.subscription_id)
        assert attempt.status == "failed" and attempt.failure_code == "DECLINED"
        assert subscription.state == "trial_expired"
        assert subscription.contracted_plan_code is None
        assert subscription.next_billing_at is None
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.revoked_at.is_(None),
            )
        ) == 0


def test_still_unknown_records_bounded_observations_without_economic_change(
    session_factory,
):
    case, attempt_id, _ = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.still_unknown(
            event_reference="evt-still-unknown-1"
        ),
        FirstChargeReconciliationResult.still_unknown(
            event_reference="evt-still-unknown-2"
        ),
    )
    executor = _executor(session_factory, provider)
    first = executor.execute(attempt_id)
    second = executor.execute(attempt_id)

    assert first.status == second.status == "still_unknown"
    assert first.observation_count == 1
    assert second.observation_count == 2
    assert first.reconciliation_required and second.reconciliation_required
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == "provider_state_unknown"
        assert session.get(Subscription, case.subscription_id).state == "conversion_scheduled"
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(SubscriptionProduct).where(
                SubscriptionProduct.subscription_id == case.subscription_id
            )
        ) == 0


def _pending_case(session_factory):
    case = _seed_case(session_factory)
    with session_factory.begin() as session:
        prepared = FirstChargeService(session, FixedClock(NOW)).prepare(
            conversion_snapshot_id=case.snapshot_id,
            provider_name="fake_charge_provider",
        )
        assert prepared.request is not None
        attempt_id = uuid.UUID(prepared.request.attempt_id)
        original_key = prepared.request.idempotency_key
    return case, attempt_id, original_key


def _assert_single_attempt_authority(session_factory, snapshot_id):
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == snapshot_id
            )
        ) == 1


def test_pending_command_without_authoritative_lookup_fails_closed(session_factory):
    case, attempt_id, original_key = _pending_case(session_factory)

    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success(
            "tx-durable-pending-operation"
        )
    )
    result = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == "query_authority_unavailable"
    assert result.reconciliation_required
    assert provider.charge_calls == 0
    assert provider.reconciliation_requests == []
    with session_factory() as session:
        attempt = session.get(BillingAttempt, attempt_id)
        assert attempt.status == "pending"
        assert attempt.idempotency_key == original_key
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 1


def test_pending_command_can_use_explicit_authoritative_idempotency_lookup(
    session_factory,
):
    case, attempt_id, original_key = _pending_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-pending-authoritative"),
        capabilities=FirstChargeReconciliationCapabilities(
            authoritative_idempotency_lookup=True
        ),
    )

    result = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == "confirmed_success"
    assert provider.charge_calls == 0
    assert len(provider.reconciliation_requests) == 1
    request = provider.reconciliation_requests[0]
    assert request.lookup_basis == ReconciliationLookupBasis.IDEMPOTENCY_KEY
    assert request.original_idempotency_key == original_key
    assert request.original_operation_reference is None
    _assert_single_attempt_authority(session_factory, case.snapshot_id)


@pytest.mark.parametrize(
    ("definitive_not_found", "expected_status", "attempt_status"),
    [
        (False, "still_unknown", "provider_state_unknown"),
        (True, "confirmed_failure", "failed"),
    ],
)
def test_pending_not_found_requires_explicit_provider_no_charge_guarantee(
    session_factory,
    definitive_not_found,
    expected_status,
    attempt_status,
):
    case, attempt_id, _ = _pending_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.not_found(
            event_reference="evt-not-found-{0}".format(attempt_id)
        ),
        capabilities=FirstChargeReconciliationCapabilities(
            authoritative_idempotency_lookup=True,
            definitive_not_found_means_no_charge=definitive_not_found,
        ),
    )

    result = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == expected_status
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == attempt_status
    _assert_single_attempt_authority(session_factory, case.snapshot_id)


def test_pending_command_can_use_durable_original_operation_reference(
    session_factory,
):
    case, attempt_id, original_key = _pending_case(session_factory)
    with session_factory.begin() as session:
        session.add(
            BillingEvent(
                billing_attempt_id=attempt_id,
                event_type="first_charge_provider_state_unknown",
                occurred_at=NOW,
                provider_event_reference="op-durable-pending",
                detail={"durable_before_query": True},
                created_at=NOW,
            )
        )
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success(
            "tx-durable-pending-operation"
        )
    )

    result = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == "confirmed_success"
    assert provider.charge_calls == 0
    assert provider.reconciliation_requests[0].lookup_basis == (
        ReconciliationLookupBasis.OPERATION_REFERENCE
    )
    assert provider.reconciliation_requests[0].original_idempotency_key == original_key
    assert (
        provider.reconciliation_requests[0].original_operation_reference
        == "op-durable-pending"
    )
    _assert_single_attempt_authority(session_factory, case.snapshot_id)


def test_duplicate_success_is_idempotent_and_does_not_query_again(session_factory):
    case, attempt_id, _ = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-one")
    )
    executor = _executor(session_factory, provider)
    first = executor.execute(attempt_id)
    second = executor.execute(attempt_id)
    assert first.status == second.status == "confirmed_success"
    assert second.replayed
    assert len(provider.reconciliation_requests) == 1
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id,
                BillingAttempt.status == "succeeded",
            )
        ) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.source == "paid",
                Entitlement.revoked_at.is_(None),
            )
        ) == 3


def test_concurrent_success_has_one_state_transition_authority(session_factory):
    case, attempt_id, _ = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-concurrent"),
        FirstChargeReconciliationResult.confirmed_success("tx-concurrent"),
    )
    executor = _executor(session_factory, provider)
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait()
        return executor.execute(attempt_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: invoke(), range(2)))
    assert statuses == ["confirmed_success", "confirmed_success"]
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.source == "paid",
                Entitlement.revoked_at.is_(None),
            )
        ) == 3


def test_stale_failure_cannot_roll_back_settled_success(session_factory):
    case, attempt_id, _ = _unknown_case(session_factory)
    with session_factory.begin() as session:
        service = FirstChargeReconciliationService(session, FixedClock(NOW))
        assert service.prepare(
            billing_attempt_id=attempt_id,
            provider_name="fake_charge_provider",
        ).request is not None
    with session_factory.begin() as session:
        service = FirstChargeReconciliationService(session, FixedClock(NOW))
        service.apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeReconciliationResult.confirmed_success(
                "tx-winner", event_reference="evt-winner"
            ),
        )
    with session_factory.begin() as session:
        result = FirstChargeReconciliationService(
            session, FixedClock(NOW)
        ).apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeReconciliationResult.confirmed_failure(
                "STALE_FAILURE", event_reference="evt-stale-failure"
            ),
        )
        assert result.status == "confirmed_success"
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == "succeeded"
        assert session.get(Subscription, case.subscription_id).state == "active"


def test_failure_then_contradictory_success_blocks_retry_fail_closed(
    session_factory,
):
    case, attempt_id, _ = _unknown_case(session_factory)
    with session_factory.begin() as session:
        service = FirstChargeReconciliationService(session, FixedClock(NOW))
        service.apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeReconciliationResult.confirmed_failure(
                "DECLINED", event_reference="evt-first-failure"
            ),
        )
    with session_factory.begin() as session:
        result = FirstChargeReconciliationService(
            session, FixedClock(NOW)
        ).apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeReconciliationResult.confirmed_success(
                "tx-contradiction", event_reference="evt-late-success"
            ),
        )
        assert result.status == "contradictory_observation"
        assert result.reconciliation_required

    retry_provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-forbidden-retry")
    )
    retry = FirstChargeExecutor(
        session_factory, FixedClock(NOW), retry_provider
    ).execute(case.snapshot_id, explicit_retry=True)
    assert retry.status == "provider_state_unknown"
    assert retry_provider.requests == []
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == "provider_state_unknown"
        assert (
            session.get(Subscription, case.subscription_id).state
            == "conversion_scheduled"
        )
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.source == "paid",
            )
        ) == 0


def test_reconciliation_preserves_frozen_amount_products_and_anchor(session_factory):
    case = _seed_case(
        session_factory,
        plan_code="package_two",
        products=("today_genie", "keysuri_korea"),
        price=11000,
    )
    original = FakeChargeProvider(
        FirstChargeProviderResult.unknown(operation_reference="op-frozen")
    )
    first = FirstChargeExecutor(
        session_factory, FixedClock(NOW), original
    ).execute(case.snapshot_id)
    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-frozen")
    )
    _executor(session_factory, provider).execute(first.billing_attempt_id)
    with session_factory() as session:
        attempt = session.get(BillingAttempt, first.billing_attempt_id)
        subscription = session.get(Subscription, case.subscription_id)
        assert attempt.amount_krw == 11000 and attempt.plan_code == "package_two"
        assert subscription.contracted_price_krw == 11000
        assert subscription.billing_anchor_day == 29
        assert {
            row.product_code
            for row in session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == case.subscription_id
                )
            )
        } == {"today_genie", "keysuri_korea"}


def test_provider_exception_and_secret_material_are_sanitized(session_factory):
    case, attempt_id, original_key = _unknown_case(session_factory)
    provider = FakeReconciliationProvider(raises=True)
    result = _executor(session_factory, provider).execute(attempt_id)
    assert result.status == "still_unknown"
    assert provider.charge_calls == 0
    persisted = []
    with session_factory() as session:
        persisted.extend(
            session.scalars(
                sa.select(BillingEvent.detail).where(
                    BillingEvent.billing_attempt_id == attempt_id
                )
            )
        )
        persisted.extend(
            session.scalars(
                sa.select(AuditEvent.payload).where(
                    AuditEvent.subscription_id == case.subscription_id
                )
            )
        )
    text = " ".join(str(value) for value in persisted)
    assert "raw provider reconciliation secret" not in text
    assert original_key not in text
    assert "op-original" not in text


def test_reconciliation_rejects_cross_account_payment_authority(session_factory):
    _, attempt_id, _ = _unknown_case(session_factory)
    with session_factory.begin() as session:
        other_account = make_account(session)
        other_method = make_payment_method(session, other_account)
        session.get(BillingAttempt, attempt_id).payment_method_id = other_method.id

    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-forbidden")
    )
    with pytest.raises(FirstChargeConflict):
        _executor(session_factory, provider).execute(attempt_id)
    assert provider.reconciliation_requests == []
    assert provider.charge_calls == 0


def test_reconciliation_rejects_unexpected_live_delivery_authority(
    session_factory,
):
    case, attempt_id, _ = _unknown_case(session_factory)
    with session_factory.begin() as session:
        account_id = session.get(BillingAttempt, attempt_id).account_id
        make_entitlement(
            session,
            session.get(CustomerAccount, account_id),
            session.get(Subscription, case.subscription_id),
            "today_genie",
            source="paid",
            plan_code="full_set",
            price_version=1,
            effective_from=NOW.date(),
        )

    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_failure("DECLINED")
    )
    with pytest.raises(FirstChargeConflict):
        _executor(session_factory, provider).execute(attempt_id)
    assert provider.reconciliation_requests == []
    assert provider.charge_calls == 0


@pytest.mark.parametrize("invalid_delivery_state", ["superseded", "unverified"])
def test_confirmed_payment_success_does_not_fabricate_delivery_authority(
    session_factory,
    invalid_delivery_state,
):
    case, attempt_id, _ = _unknown_case(session_factory)
    with session_factory.begin() as session:
        delivery_email = session.scalar(
            sa.select(DeliveryEmail).where(
                DeliveryEmail.account_id == case.account_id
            )
        )
        original_email = delivery_email.email
        if invalid_delivery_state == "superseded":
            original_verified_at = delivery_email.verified_at
            delivery_email.status = "superseded"
            delivery_email.deactivated_at = NOW
        else:
            original_verified_at = None
            delivery_email.status = "pending_verification"
            delivery_email.verified_at = None

    provider = FakeReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success(
            "tx-financially-settled-{0}".format(invalid_delivery_state)
        )
    )
    result = _executor(session_factory, provider).execute(attempt_id)
    replay = _executor(session_factory, provider).execute(attempt_id)

    assert result.status == "confirmed_success"
    assert result.delivery_authority_available is False
    assert replay.status == "confirmed_success" and replay.replayed
    assert len(provider.reconciliation_requests) == 1
    assert provider.charge_calls == 0
    with session_factory() as session:
        attempt = session.get(BillingAttempt, attempt_id)
        subscription = session.get(Subscription, case.subscription_id)
        delivery_emails = list(
            session.scalars(
                sa.select(DeliveryEmail).where(
                    DeliveryEmail.account_id == case.account_id
                )
            )
        )
        assert attempt.status == "succeeded"
        assert subscription.state == "active"
        assert len(delivery_emails) == 1
        assert delivery_emails[0].email == original_email
        assert delivery_emails[0].verified_at == original_verified_at
        assert delivery_emails[0].status == (
            "superseded"
            if invalid_delivery_state == "superseded"
            else "pending_verification"
        )
        assert session.scalar(
            sa.select(sa.func.count()).select_from(RecipientSnapshot).where(
                RecipientSnapshot.account_id == case.account_id
            )
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count()).select_from(DeliveryEvent)
        ) == 0


def test_no_public_reconciliation_route_or_production_wiring():
    from customer.api.router import create_customer_test_app
    from main import app

    customer_paths = {
        route.path
        for route in create_customer_test_app().routes
        if route.path.startswith("/v1/customer")
    }
    assert not any("reconcil" in path for path in customer_paths)
    assert not any(
        getattr(route, "path", "").startswith("/v1/customer") for route in app.routes
    )
    assert any(getattr(route, "path", "").startswith("/internal") for route in app.routes)
