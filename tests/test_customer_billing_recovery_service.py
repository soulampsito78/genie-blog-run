"""Explicit first-charge and suspended-renewal recovery on PostgreSQL."""

import datetime as dt
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from customer.api.dependencies import get_billing_recovery_executor  # noqa: E402
from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.enums import AuthAssuranceLevel  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    BrowserSession,
    CommandIdempotency,
    ConversionSnapshot,
    Entitlement,
    PaymentMethod,
    Subscription,
    SubscriptionProduct,
)
from customer.services.billing_recovery_service import (  # noqa: E402
    BillingRecoveryExecutor,
    BillingRecoveryReconciliationExecutor,
    BillingRecoveryService,
)
from customer.services.charge_providers import (  # noqa: E402
    FirstChargeProviderResult,
    FirstChargeReconciliationCapabilities,
    FirstChargeReconciliationResult,
)
from customer.services.first_charge_service import FirstChargeExecutor  # noqa: E402
from customer.services.renewal_billing_service import RenewalBillingExecutor  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    make_payment_method,
    requires_customer_db,
    session,
)
from tests.test_customer_first_charge_service import (  # noqa: E402
    NOW,
    _seed_case,
    first_charge_engine,
    session_factory,
)
from tests.test_customer_payment_method_api import (  # noqa: E402
    ORIGIN,
    clock,
    payment_api,
)
from tests.test_customer_renewal_billing_service import (  # noqa: E402
    DUE,
    FakeRenewalProvider,
    _fail_at,
    _seed_paid_case,
)


pytestmark = requires_customer_db
__all__ = [
    "first_charge_engine",
    "session_factory",
    "clock",
    "payment_api",
    "customer_engine",
    "session",
]


class FakeRecoveryProvider:
    name = "fake_charge_provider"

    def __init__(self, *results, delay=0):
        self._results = list(results)
        self._delay = delay
        self._lock = threading.Lock()
        self.requests = []

    def _take(self, request):
        with self._lock:
            self.requests.append(request)
            if not self._results:
                raise AssertionError("recovery provider invoked more than expected")
            result = self._results.pop(0)
        if self._delay:
            time.sleep(self._delay)
        return result

    def charge(self, request):
        return self._take(request)

    def charge_renewal(self, request):
        return self._take(request)


class FakeRecoveryReconciliationProvider:
    name = "fake_charge_provider"

    def __init__(self, *results):
        self._results = list(results)
        self.requests = []
        self.charge_calls = 0
        self.reconciliation_capabilities = FirstChargeReconciliationCapabilities(
            authoritative_idempotency_lookup=True
        )

    def reconcile_renewal(self, request):
        self.requests.append(request)
        return self._results.pop(0)

    def charge_renewal(self, request):  # pragma: no cover - safety tripwire
        del request
        self.charge_calls += 1
        raise AssertionError("reconciliation must never charge")


def _initial_first_charge(session_factory, case, outcome):
    provider = FakeRecoveryProvider(outcome)
    result = FirstChargeExecutor(
        session_factory, FixedClock(NOW), provider
    ).execute(case.snapshot_id)
    assert len(provider.requests) == 1
    return result


def _replace_default(session_factory, case, *, usable=True, owner_id=None):
    with session_factory.begin() as session:
        old = session.get(PaymentMethod, case.payment_method_id)
        old.is_default = False
        from customer.persistence.models import CustomerAccount

        owner = session.get(CustomerAccount, owner_id or case.account_id)
        method = make_payment_method(session, owner)
        if not usable:
            method.own_name_verified = False
            method.own_name_verified_at = None
        return method.id


def _suspend(session_factory):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE, "DAY0_DECLINED")
    _fail_at(session_factory, case, DUE + dt.timedelta(days=1), "DAY1_DECLINED")
    final = _fail_at(
        session_factory, case, DUE + dt.timedelta(days=3), "DAY3_DECLINED"
    )
    assert final.status == "suspended"
    return case


def _recovery_executor(session_factory, clock_at, provider):
    return BillingRecoveryExecutor(
        session_factory,
        FixedClock(clock_at),
        provider,
        renewal_provider=provider,
    )


def test_first_charge_failure_requires_new_method_and_explicit_retry(session_factory):
    case = _seed_case(session_factory)
    failed = _initial_first_charge(
        session_factory, case, FirstChargeProviderResult.failed("DECLINED")
    )
    assert failed.status == "failed"

    blind_provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-blind")
    )
    blind = FirstChargeExecutor(
        session_factory, FixedClock(NOW), blind_provider
    ).execute(case.snapshot_id)
    assert blind.status == "failed"
    assert blind_provider.requests == []

    with session_factory.begin() as session:
        projection = BillingRecoveryService(session, FixedClock(NOW)).projection(
            case.account_id
        )
        assert projection.first_charge.status == "payment_method_update_required"
        assert projection.first_charge.eligible is False

    _replace_default(session_factory, case)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-first-recovery")
    )
    executor = _recovery_executor(session_factory, NOW, provider)
    result = executor.recover_first_charge(
        case.account_id, idempotency_key="first-recovery-success"
    )
    replay = executor.recover_first_charge(
        case.account_id, idempotency_key="first-recovery-success"
    )

    assert result.status == "succeeded"
    assert replay.status == "succeeded" and replay.replayed
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.amount_krw == 16500
    assert request.plan_code == "full_set"
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        snapshot = session.get(ConversionSnapshot, case.snapshot_id)
        attempts = list(
            session.scalars(
                sa.select(BillingAttempt)
                .where(BillingAttempt.conversion_snapshot_id == case.snapshot_id)
                .order_by(BillingAttempt.attempt_no)
            )
        )
        products = tuple(
            sorted(
                session.scalars(
                    sa.select(SubscriptionProduct.product_code).where(
                        SubscriptionProduct.subscription_id == case.subscription_id
                    )
                )
            )
        )
        assert subscription.state == "active"
        assert subscription.billing_anchor_day == 29
        assert subscription.next_billing_at.astimezone(UTC) == dt.datetime(
            2026, 9, 29, 9, 0, tzinfo=UTC
        )
        assert snapshot.status == "applied"
        assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
        assert {attempt.amount_krw for attempt in attempts} == {16500}
        assert products == ("keysuri_global", "keysuri_korea", "today_genie")
        assert session.query(CommandIdempotency).filter_by(
            command="billing_recovery.first_charge"
        ).count() == 1


def test_first_charge_unknown_absolutely_blocks_recovery_charge(session_factory):
    case = _seed_case(session_factory)
    unknown = _initial_first_charge(
        session_factory, case, FirstChargeProviderResult.unknown()
    )
    assert unknown.reconciliation_required
    _replace_default(session_factory, case)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-must-not-run")
    )
    result = _recovery_executor(session_factory, NOW, provider).recover_first_charge(
        case.account_id, idempotency_key="blocked-after-unknown"
    )
    assert result.status == "provider_state_unknown"
    assert result.reconciliation_required
    assert provider.requests == []
    with session_factory() as session:
        assert session.query(BillingAttempt).filter_by(
            conversion_snapshot_id=case.snapshot_id
        ).count() == 1


def test_first_charge_recovery_failure_remains_inactive_without_loop(session_factory):
    case = _seed_case(session_factory)
    _initial_first_charge(
        session_factory, case, FirstChargeProviderResult.failed("DECLINED")
    )
    _replace_default(session_factory, case)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.failed("RECOVERY_DECLINED")
    )
    executor = _recovery_executor(session_factory, NOW, provider)
    result = executor.recover_first_charge(
        case.account_id, idempotency_key="first-recovery-failed"
    )
    replay = executor.recover_first_charge(
        case.account_id, idempotency_key="first-recovery-failed"
    )
    assert result.status == replay.status == "failed"
    assert replay.replayed
    assert len(provider.requests) == 1
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "trial_expired"
        assert subscription.contracted_plan_code is None
        assert session.query(Entitlement).filter_by(
            subscription_id=case.subscription_id, revoked_at=None
        ).count() == 0


def test_first_charge_unverified_and_wrong_account_methods_are_blocked(session_factory):
    case = _seed_case(session_factory)
    _initial_first_charge(
        session_factory, case, FirstChargeProviderResult.failed("DECLINED")
    )
    _replace_default(session_factory, case, usable=False)
    provider = FakeRecoveryProvider(FirstChargeProviderResult.succeeded("never"))
    result = _recovery_executor(session_factory, NOW, provider).recover_first_charge(
        case.account_id, idempotency_key="unverified-block"
    )
    assert result.status == "blocked_payment_method"
    assert provider.requests == []

    with session_factory.begin() as session:
        owner = make_account(session)
        make_payment_method(session, owner)
    wrong = _recovery_executor(session_factory, NOW, provider).recover_first_charge(
        owner.id, idempotency_key="wrong-account-block"
    )
    assert wrong.status == "not_eligible"
    assert provider.requests == []


def test_suspended_renewal_success_settles_original_obligation_once(session_factory):
    case = _suspend(session_factory)
    no_action_provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("blind-renewal")
    )
    no_action = RenewalBillingExecutor(
        session_factory, FixedClock(DUE + dt.timedelta(days=4)), no_action_provider
    ).execute(case.subscription_id)
    assert no_action.status == "final_failed"
    assert no_action_provider.requests == []

    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-renewal-recovery")
    )
    executor = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    )
    result = executor.recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-success"
    )
    replay = executor.recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-success"
    )

    assert result.status == "succeeded"
    assert result.delivery_available
    assert replay.status == "succeeded" and replay.replayed
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.purpose == "recovery_charge"
    assert request.billing_period_start == case.current_period_end
    assert request.retry_offset_day is None
    assert "bk-" not in repr(request)
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        recovery = list(
            session.scalars(
                sa.select(BillingAttempt).where(
                    BillingAttempt.subscription_id == case.subscription_id,
                    BillingAttempt.purpose == "recovery_charge",
                )
            )
        )
        assert subscription.state == "active"
        assert subscription.billing_anchor_day == 15
        assert subscription.current_period_start == dt.date(2026, 9, 15)
        assert subscription.current_period_end == dt.date(2026, 10, 15)
        assert subscription.next_billing_at == dt.datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
        assert len(recovery) == 1 and recovery[0].status == "succeeded"
        assert recovery[0].billing_period_start == dt.date(2026, 9, 15)
        assert session.query(Entitlement).filter_by(
            subscription_id=case.subscription_id, revoked_at=None
        ).count() == 3
        assert session.query(SubscriptionProduct).filter_by(
            subscription_id=case.subscription_id
        ).count() == 3


def test_suspended_recovery_failure_stays_suspended_and_never_auto_retries(
    session_factory,
):
    case = _suspend(session_factory)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.failed("RECOVERY_DECLINED")
    )
    executor = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    )
    result = executor.recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-failed"
    )
    replay = executor.recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-failed"
    )
    assert result.status == replay.status == "failed"
    assert len(provider.requests) == 1
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "suspended"
        assert subscription.current_period_end == dt.date(2026, 9, 15)
        assert subscription.next_billing_at == DUE
        assert session.query(BillingAttempt).filter_by(
            subscription_id=case.subscription_id, purpose="recovery_charge"
        ).count() == 1


def test_unknown_recovery_blocks_next_charge_until_query_only_reconciliation(
    session_factory,
):
    case = _suspend(session_factory)
    provider = FakeRecoveryProvider(FirstChargeProviderResult.unknown())
    executor = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    )
    unknown = executor.recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-unknown"
    )
    assert unknown.status == "provider_state_unknown"
    assert unknown.reconciliation_required

    forbidden = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("must-not-charge")
    )
    blocked = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=5), forbidden
    ).recover_suspended_renewal(
        case.account_id, idempotency_key="renewal-recovery-after-unknown"
    )
    assert blocked.reconciliation_required
    assert forbidden.requests == []

    reconciler = FakeRecoveryReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-reconciled-recovery")
    )
    reconciled = BillingRecoveryReconciliationExecutor(
        session_factory, FixedClock(DUE + dt.timedelta(days=5)), reconciler
    ).execute(unknown.billing_attempt_id)
    assert reconciled.status == "succeeded"
    assert len(reconciler.requests) == 1
    assert reconciler.charge_calls == 0
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "active"
        assert subscription.next_billing_at == dt.datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def test_prior_unknown_or_financial_conflict_blocks_suspended_recovery(session_factory):
    case = _suspend(session_factory)
    with session_factory.begin() as session:
        final = session.scalar(
            sa.select(BillingAttempt).where(
                BillingAttempt.subscription_id == case.subscription_id,
                BillingAttempt.purpose == "renewal_charge",
                BillingAttempt.attempt_no == 3,
            )
        )
        final.status = "provider_state_unknown"
        final.failure_code = "PROVIDER_OBSERVATION_CONFLICT"
        session.add(
            BillingEvent(
                billing_attempt_id=final.id,
                event_type="renewal_reconciliation_contradictory_observation",
                occurred_at=DUE + dt.timedelta(days=4),
                detail={"economic_state_changed": False},
                created_at=DUE + dt.timedelta(days=4),
            )
        )
    provider = FakeRecoveryProvider(FirstChargeProviderResult.succeeded("never"))
    blocked = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    ).recover_suspended_renewal(
        case.account_id, idempotency_key="conflict-block"
    )
    assert blocked.status == "reconciliation_required"
    assert blocked.reconciliation_required
    assert provider.requests == []


def test_concurrent_recovery_has_one_economic_charge_authority(session_factory):
    case = _suspend(session_factory)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-concurrent-recovery"), delay=0.15
    )

    def run(index):
        return _recovery_executor(
            session_factory, DUE + dt.timedelta(days=4), provider
        ).recover_suspended_renewal(
            case.account_id, idempotency_key="concurrent-{0}".format(index)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))

    assert len(provider.requests) == 1
    assert "succeeded" in {item.status for item in results}
    with session_factory() as session:
        attempts = list(
            session.scalars(
                sa.select(BillingAttempt).where(
                    BillingAttempt.subscription_id == case.subscription_id,
                    BillingAttempt.purpose == "recovery_charge",
                )
            )
        )
        assert len(attempts) == 1
        assert attempts[0].status == "succeeded"


def test_stale_failure_cannot_undo_successful_recovery(session_factory):
    case = _suspend(session_factory)
    provider = FakeRecoveryProvider(
        FirstChargeProviderResult.succeeded("tx-stale-safe")
    )
    result = _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    ).recover_suspended_renewal(
        case.account_id, idempotency_key="stale-safe"
    )
    with session_factory.begin() as session:
        replay = BillingRecoveryService(
            session, FixedClock(DUE + dt.timedelta(days=5))
        ).apply_suspended_renewal_result(
            account_id=case.account_id,
            billing_attempt_id=result.billing_attempt_id,
            provider_result=FirstChargeProviderResult.failed("STALE_FAILURE"),
        )
        assert replay.status == "succeeded" and replay.replayed
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        attempt = session.get(BillingAttempt, result.billing_attempt_id)
        assert subscription.state == "active"
        assert attempt.status == "succeeded"


def test_recovery_api_requires_strong_fresh_auth_and_exposes_no_amounts(
    payment_api, session
):
    client, _, account, created = payment_api

    class Gateway:
        def __init__(self):
            self.calls = []

        def recover_first_charge(self, account_id, *, idempotency_key):
            self.calls.append(("first", account_id, idempotency_key))
            from customer.services.billing_recovery_service import BillingRecoveryResult

            return BillingRecoveryResult("first_charge", "not_eligible", account_id, None)

        def recover_suspended_renewal(self, account_id, *, idempotency_key):
            self.calls.append(("renewal", account_id, idempotency_key))
            from customer.services.billing_recovery_service import BillingRecoveryResult

            return BillingRecoveryResult(
                "suspended_renewal", "not_eligible", account_id, None
            )

    gateway = Gateway()
    client.app.dependency_overrides[get_billing_recovery_executor] = lambda: gateway
    headers = {"Origin": ORIGIN, "Idempotency-Key": "api-recovery"}
    response = client.post(
        "/v1/customer/billing/recovery/first-charge",
        headers=headers,
        json={"confirm": True},
    )
    assert response.status_code == 200
    assert gateway.calls == [("first", account.id, "api-recovery")]
    assert "amount" not in response.text.lower()
    assert "billing_key" not in response.text.lower()

    browser_session = session.get(BrowserSession, created.session_id)
    browser_session.fresh_auth_assurance = AuthAssuranceLevel.RECENT_VERIFICATION.value
    session.flush()
    blocked = client.post(
        "/v1/customer/billing/recovery/suspended-renewal",
        headers={"Origin": ORIGIN, "Idempotency-Key": "weak"},
        json={"confirm": True},
    )
    assert blocked.status_code == 403
    assert gateway.calls == [("first", account.id, "api-recovery")]


def test_recovery_routes_are_customer_only_and_production_unmounted():
    from customer.api.router import create_customer_test_app
    from main import app as production_app

    paths = {route.path for route in create_customer_test_app().routes}
    assert "/v1/customer/billing/recovery" in paths
    assert "/v1/customer/billing/recovery/first-charge" in paths
    assert "/v1/customer/billing/recovery/suspended-renewal" in paths
    assert not any(path.startswith("/admin") or path.startswith("/internal") for path in paths)
    assert not any(
        getattr(route, "path", "").startswith("/v1/customer")
        for route in production_app.routes
    )


def test_recovery_audit_and_events_never_expose_provider_credentials(session_factory):
    case = _suspend(session_factory)
    with session_factory() as session:
        method = session.get(PaymentMethod, case.payment_method_id)
        secret = method.billing_key_reference
    provider = FakeRecoveryProvider(FirstChargeProviderResult.failed("DECLINED"))
    _recovery_executor(
        session_factory, DUE + dt.timedelta(days=4), provider
    ).recover_suspended_renewal(case.account_id, idempotency_key="secret-safe")
    assert secret not in repr(provider.requests[0])
    with session_factory() as session:
        audit = [repr(row.payload) for row in session.query(AuditEvent).all()]
        events = [repr(row.detail) for row in session.query(BillingEvent).all()]
        assert all(secret not in item for item in audit + events)
