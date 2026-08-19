"""Paid monthly renewal billing against isolated PostgreSQL."""

import datetime as dt
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

sa = pytest.importorskip("sqlalchemy")

from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.errors import RenewalBillingConflict  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    DeliveryEmail,
    Entitlement,
    PlanCatalog,
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
from customer.services.renewal_billing_service import (  # noqa: E402
    RenewalBillingExecutor,
    RenewalBillingReconciliationExecutor,
    RenewalBillingReconciliationService,
    RenewalBillingService,
)
from tests.customer_db_fixtures import (  # noqa: E402
    make_account,
    make_delivery_email,
    make_entitlement,
    make_payment_method,
    make_subscription,
    requires_customer_db,
)
from tests.test_customer_first_charge_service import (  # noqa: E402
    first_charge_engine,
    session_factory,
)

pytestmark = requires_customer_db
__all__ = ["first_charge_engine", "session_factory"]

DUE = dt.datetime(2026, 9, 14, 15, 0, tzinfo=UTC)  # Sep 15 00:00 KST


class FakeRenewalProvider:
    name = "fake_charge_provider"

    def __init__(self, *results, raises=False):
        self._results = list(results)
        self._raises = raises
        self._lock = threading.Lock()
        self.requests = []

    def charge_renewal(self, request):
        with self._lock:
            self.requests.append(request)
            if self._raises:
                raise RuntimeError("raw renewal provider secret")
            if not self._results:
                raise AssertionError("renewal provider invoked unexpectedly")
            return self._results.pop(0)


class FakeRenewalReconciliationProvider:
    name = "fake_charge_provider"

    def __init__(self, *results, capabilities=None, raises=False):
        self._results = list(results)
        self.reconciliation_capabilities = (
            capabilities or FirstChargeReconciliationCapabilities()
        )
        self._raises = raises
        self.requests = []
        self.charge_calls = 0

    def reconcile_renewal(self, request):
        self.requests.append(request)
        if self._raises:
            raise RuntimeError("raw reconciliation provider secret")
        if not self._results:
            raise AssertionError("reconciliation provider invoked unexpectedly")
        return self._results.pop(0)

    def charge_renewal(self, request):  # pragma: no cover - safety tripwire
        del request
        self.charge_calls += 1
        raise AssertionError("reconciliation cannot issue a charge")


@dataclass(frozen=True)
class RenewalCase:
    account_id: uuid.UUID
    subscription_id: uuid.UUID
    payment_method_id: uuid.UUID
    due_at: dt.datetime
    current_period_start: dt.date
    current_period_end: dt.date
    products: tuple


def _previous_period_start(due_at, anchor_day):
    local = due_at.astimezone(dt.timezone(dt.timedelta(hours=9)))
    month = 12 if local.month == 1 else local.month - 1
    year = local.year - 1 if local.month == 1 else local.year
    import calendar

    return dt.date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def _seed_paid_case(
    session_factory,
    *,
    due_at=DUE,
    anchor_day=15,
    plan_code="full_set",
    products=("today_genie", "keysuri_global", "keysuri_korea"),
    price=16500,
    delivery=True,
    payment=True,
):
    due_date = due_at.astimezone(dt.timezone(dt.timedelta(hours=9))).date()
    period_start = _previous_period_start(due_at, anchor_day)
    with session_factory.begin() as session:
        account = make_account(
            session, email="renewal-{0}@example.com".format(uuid.uuid4().hex[:10])
        )
        method = make_payment_method(session, account)
        if not payment:
            method.status = "invalid"
            method.is_default = False
            method.own_name_verified = False
            method.own_name_verified_at = None
        if delivery:
            make_delivery_email(session, account, email=account.account_email)
        subscription = make_subscription(
            session,
            account,
            state="active",
            contracted_plan_code=plan_code,
            price_krw=price,
            price_version=1,
        )
        subscription.billing_anchor_day = anchor_day
        subscription.current_period_start = period_start
        subscription.current_period_end = due_date
        subscription.next_billing_at = due_at
        for product in products:
            session.add(
                SubscriptionProduct(
                    subscription_id=subscription.id,
                    product_code=product,
                    created_at=DUE,
                )
            )
            make_entitlement(
                session,
                account,
                subscription,
                product,
                source="paid",
                plan_code=plan_code,
                price_version=1,
                effective_from=period_start,
            )
        session.flush()
        return RenewalCase(
            account.id,
            subscription.id,
            method.id,
            due_at,
            period_start,
            due_date,
            tuple(sorted(products)),
        )


def _executor(session_factory, clock_at, provider):
    return RenewalBillingExecutor(
        session_factory, FixedClock(clock_at), provider
    )


def _reconciler(session_factory, clock_at, provider):
    return RenewalBillingReconciliationExecutor(
        session_factory, FixedClock(clock_at), provider
    )


def _attempts(session_factory, subscription_id):
    with session_factory() as session:
        return list(
            session.scalars(
                sa.select(BillingAttempt)
                .where(
                    BillingAttempt.subscription_id == subscription_id,
                    BillingAttempt.purpose == "renewal_charge",
                )
                .order_by(BillingAttempt.attempt_no)
            )
        )


def _fail_at(session_factory, case, at, failure="DECLINED"):
    provider = FakeRenewalProvider(FirstChargeProviderResult.failed(failure))
    result = _executor(session_factory, at, provider).execute(case.subscription_id)
    assert len(provider.requests) == 1
    return result


def test_before_renewal_due_creates_no_charge(session_factory):
    case = _seed_paid_case(session_factory)
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-forbidden"))

    result = _executor(
        session_factory, DUE - dt.timedelta(seconds=1), provider
    ).execute(case.subscription_id)

    assert result.status == "not_due"
    assert provider.requests == []
    assert _attempts(session_factory, case.subscription_id) == []


@pytest.mark.parametrize(
    "state",
    [
        "trialing",
        "conversion_scheduled",
        "suspended",
        "cancellation_scheduled",
        "canceled",
    ],
)
def test_nonrenewable_subscription_states_never_charge(session_factory, state):
    if state in {"trialing", "conversion_scheduled"}:
        with session_factory.begin() as session:
            account = make_account(session)
            subscription = make_subscription(session, account, state=state)
            subscription_id = subscription.id
    else:
        case = _seed_paid_case(session_factory)
        subscription_id = case.subscription_id
        with session_factory.begin() as session:
            subscription = session.get(Subscription, subscription_id)
            subscription.state = state
            if state == "cancellation_scheduled":
                subscription.cancellation_effective_at = DUE + dt.timedelta(days=10)
            if state == "canceled":
                subscription.ended_at = DUE
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-ineligible-{0}".format(state))
    )

    result = _executor(session_factory, DUE, provider).execute(subscription_id)

    assert result.status in {"not_eligible", "final_failed"}
    assert provider.requests == []
    assert _attempts(session_factory, subscription_id) == []


def test_day0_success_uses_frozen_contract_and_advances_one_anchor_period(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-day0", event_reference="evt-day0")
    )

    result = _executor(session_factory, DUE, provider).execute(case.subscription_id)

    assert result.status == "succeeded"
    assert result.attempt_no == 1 and result.retry_offset_day == 0
    assert result.delivery_available and not result.grace_active
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.amount_krw == 16500 and request.currency == "KRW"
    assert request.plan_code == "full_set" and request.price_version == 1
    assert request.billing_period_start == dt.date(2026, 9, 15)
    assert request.billing_period_end == dt.date(2026, 10, 15)
    assert "billing-key" not in repr(request)
    assert request.idempotency_key not in repr(request)
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "active"
        assert subscription.billing_anchor_day == 15
        assert subscription.current_period_start == dt.date(2026, 9, 15)
        assert subscription.current_period_end == dt.date(2026, 10, 15)
        assert subscription.next_billing_at == dt.datetime(
            2026, 10, 14, 15, 0, tzinfo=UTC
        )
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.revoked_at.is_(None),
            )
        ) == 3


def test_day0_failure_enters_three_day_grace_without_period_shift(session_factory):
    case = _seed_paid_case(session_factory)

    result = _fail_at(session_factory, case, DUE)

    assert result.status == "past_due"
    assert result.grace_active and result.delivery_available
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "past_due"
        assert subscription.billing_anchor_day == 15
        assert subscription.current_period_start == case.current_period_start
        assert subscription.current_period_end == case.current_period_end
        assert subscription.next_billing_at == DUE
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.revoked_at.is_(None),
            )
        ) == 3


def test_day1_retry_is_not_early_and_success_settles_obligation_once(session_factory):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE)
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-day1"))
    early = _executor(
        session_factory, DUE + dt.timedelta(hours=23), provider
    ).execute(case.subscription_id)
    success = _executor(
        session_factory, DUE + dt.timedelta(days=1), provider
    ).execute(case.subscription_id)
    replay = _executor(
        session_factory, DUE + dt.timedelta(days=1), provider
    ).execute(case.subscription_id)

    assert early.status == "retry_not_due"
    assert success.status == "succeeded" and success.attempt_no == 2
    assert replay.status == "not_due"
    assert len(provider.requests) == 1
    attempts = _attempts(session_factory, case.subscription_id)
    assert [row.status for row in attempts] == ["failed", "succeeded"]


def test_day1_failure_remains_past_due_until_day3(session_factory):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE)

    result = _fail_at(session_factory, case, DUE + dt.timedelta(days=1))

    assert result.status == "past_due" and result.attempt_no == 2
    assert result.grace_active and result.delivery_available
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "past_due"
        assert subscription.next_billing_at == DUE


def test_day3_success_preserves_original_anchor_not_retry_timestamp(session_factory):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE)
    _fail_at(session_factory, case, DUE + dt.timedelta(days=1))
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-day3"))

    result = _executor(
        session_factory, DUE + dt.timedelta(days=3), provider
    ).execute(case.subscription_id)

    assert result.status == "succeeded" and result.attempt_no == 3
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "active"
        assert subscription.billing_anchor_day == 15
        assert subscription.current_period_end == dt.date(2026, 10, 15)
        assert subscription.next_billing_at == dt.datetime(
            2026, 10, 14, 15, 0, tzinfo=UTC
        )


def test_final_day3_failure_suspends_delivery_and_has_no_hidden_retry(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE)
    _fail_at(session_factory, case, DUE + dt.timedelta(days=1))
    final = _fail_at(session_factory, case, DUE + dt.timedelta(days=3))
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-extra"))

    later = _executor(
        session_factory, DUE + dt.timedelta(days=30), provider
    ).execute(case.subscription_id)

    assert final.status == "suspended"
    assert not final.grace_active and not final.delivery_available
    assert later.status == "final_failed" and provider.requests == []
    attempts = _attempts(session_factory, case.subscription_id)
    assert len(attempts) == 3
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "suspended"
        assert subscription.current_period_end == case.current_period_end
        assert subscription.next_billing_at == DUE
        assert session.scalar(
            sa.select(sa.func.count()).select_from(RecipientSnapshot).where(
                RecipientSnapshot.subscription_id == case.subscription_id
            )
        ) == 0


def test_unknown_blocks_all_later_retry_charge_creation(session_factory):
    case = _seed_paid_case(session_factory)
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.unknown(operation_reference="op-renewal-original")
    )
    unknown = _executor(session_factory, DUE, provider).execute(case.subscription_id)
    retry_provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-blind-retry")
    )

    blocked = _executor(
        session_factory, DUE + dt.timedelta(days=3), retry_provider
    ).execute(case.subscription_id)

    assert unknown.status == "provider_state_unknown"
    assert blocked.reconciliation_required
    assert retry_provider.requests == []
    assert len(_attempts(session_factory, case.subscription_id)) == 1


@pytest.mark.parametrize("unknown_offset", [1, 3])
def test_unknown_on_scheduled_retry_blocks_every_later_charge(
    session_factory,
    unknown_offset,
):
    case = _seed_paid_case(session_factory)
    _fail_at(session_factory, case, DUE)
    if unknown_offset == 3:
        _fail_at(session_factory, case, DUE + dt.timedelta(days=1))
    unknown_provider = FakeRenewalProvider(
        FirstChargeProviderResult.unknown(
            operation_reference="op-unknown-offset-{0}".format(unknown_offset)
        )
    )
    unknown = _executor(
        session_factory, DUE + dt.timedelta(days=unknown_offset), unknown_provider
    ).execute(case.subscription_id)
    later_provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-forbidden-after-unknown")
    )

    blocked = _executor(
        session_factory, DUE + dt.timedelta(days=10), later_provider
    ).execute(case.subscription_id)

    assert unknown.status == "provider_state_unknown"
    assert blocked.reconciliation_required
    assert later_provider.requests == []
    assert len(_attempts(session_factory, case.subscription_id)) == (
        2 if unknown_offset == 1 else 3
    )
    if unknown_offset == 3:
        assert not blocked.delivery_available


def test_unknown_reconciliation_success_settles_exactly_once(session_factory):
    case = _seed_paid_case(session_factory)
    unknown_provider = FakeRenewalProvider(
        FirstChargeProviderResult.unknown(operation_reference="op-reconcile-success")
    )
    unknown = _executor(session_factory, DUE, unknown_provider).execute(
        case.subscription_id
    )
    provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success(
            "tx-reconciled-renewal", event_reference="evt-reconciled-renewal"
        )
    )
    reconciler = _reconciler(session_factory, DUE, provider)

    first = reconciler.execute(unknown.billing_attempt_id)
    replay = reconciler.execute(unknown.billing_attempt_id)

    assert first.status == replay.status == "succeeded"
    assert replay.replayed
    assert len(provider.requests) == 1 and provider.charge_calls == 0
    assert provider.requests[0].lookup_basis == (
        ReconciliationLookupBasis.OPERATION_REFERENCE
    )
    assert len(_attempts(session_factory, case.subscription_id)) == 1


def test_reconciliation_failure_permits_only_next_policy_retry(session_factory):
    case = _seed_paid_case(session_factory)
    unknown_provider = FakeRenewalProvider(
        FirstChargeProviderResult.unknown(operation_reference="op-reconcile-failure")
    )
    unknown = _executor(session_factory, DUE, unknown_provider).execute(
        case.subscription_id
    )
    recon_provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_failure("DECLINED")
    )
    failure = _reconciler(session_factory, DUE, recon_provider).execute(
        unknown.billing_attempt_id
    )
    retry_provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-policy-retry")
    )
    early = _executor(
        session_factory, DUE + dt.timedelta(hours=23), retry_provider
    ).execute(case.subscription_id)
    success = _executor(
        session_factory, DUE + dt.timedelta(days=1), retry_provider
    ).execute(case.subscription_id)

    assert failure.status == "past_due"
    assert early.status == "retry_not_due" and retry_provider.requests
    assert success.status == "succeeded"
    assert len(retry_provider.requests) == 1


def test_still_unknown_reconciliation_remains_fail_closed(session_factory):
    case = _seed_paid_case(session_factory)
    unknown = _executor(
        session_factory,
        DUE,
        FakeRenewalProvider(
            FirstChargeProviderResult.unknown(operation_reference="op-still-unknown")
        ),
    ).execute(case.subscription_id)
    provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.still_unknown(
            event_reference="evt-still-unknown"
        )
    )

    result = _reconciler(session_factory, DUE, provider).execute(
        unknown.billing_attempt_id
    )

    assert result.status == "still_unknown" and result.reconciliation_required
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.get(BillingAttempt, unknown.billing_attempt_id).status == (
            "provider_state_unknown"
        )


def test_contradictory_late_success_after_failure_blocks_retry_fail_closed(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    failed = _fail_at(session_factory, case, DUE)
    with session_factory.begin() as session:
        result = RenewalBillingReconciliationService(
            session, FixedClock(DUE)
        ).apply_provider_result(
            billing_attempt_id=failed.billing_attempt_id,
            provider_result=FirstChargeReconciliationResult.confirmed_success(
                "tx-contradictory-late-success",
                event_reference="evt-contradictory-late-success",
            ),
            lookup_basis=ReconciliationLookupBasis.OPERATION_REFERENCE,
            idempotency_lookup_authoritative=False,
        )
        assert result.status == "contradictory_observation"
        assert result.reconciliation_required
    retry_provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-forbidden-conflict-retry")
    )

    blocked = _executor(
        session_factory, DUE + dt.timedelta(days=1), retry_provider
    ).execute(case.subscription_id)

    assert blocked.reconciliation_required
    assert retry_provider.requests == []


def test_pending_crash_window_without_query_authority_never_queries_or_resolves(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
    provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-forbidden")
    )

    result = _reconciler(session_factory, DUE, provider).execute(attempt_id)

    assert result.status == "query_authority_unavailable"
    assert result.reconciliation_required
    assert provider.requests == [] and provider.charge_calls == 0
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == "pending"


def test_pending_authoritative_idempotency_lookup_can_prove_original_success(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
        original_key = prepared.request.idempotency_key
    provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.confirmed_success("tx-idempotency-proof"),
        capabilities=FirstChargeReconciliationCapabilities(
            authoritative_idempotency_lookup=True
        ),
    )

    result = _reconciler(session_factory, DUE, provider).execute(attempt_id)

    assert result.status == "succeeded"
    assert provider.charge_calls == 0
    assert provider.requests[0].lookup_basis == ReconciliationLookupBasis.IDEMPOTENCY_KEY
    assert provider.requests[0].original_idempotency_key == original_key
    assert original_key not in repr(provider.requests[0])


@pytest.mark.parametrize(
    ("definitive_not_found", "expected_status", "stored_status"),
    [
        (False, "still_unknown", "provider_state_unknown"),
        (True, "past_due", "failed"),
    ],
)
def test_pending_not_found_requires_explicit_no_charge_guarantee(
    session_factory,
    definitive_not_found,
    expected_status,
    stored_status,
):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
    provider = FakeRenewalReconciliationProvider(
        FirstChargeReconciliationResult.not_found(
            event_reference="evt-renewal-not-found-{0}".format(attempt_id)
        ),
        capabilities=FirstChargeReconciliationCapabilities(
            authoritative_idempotency_lookup=True,
            definitive_not_found_means_no_charge=definitive_not_found,
        ),
    )

    result = _reconciler(session_factory, DUE, provider).execute(attempt_id)

    assert result.status == expected_status
    assert provider.charge_calls == 0
    with session_factory() as session:
        assert session.get(BillingAttempt, attempt_id).status == stored_status


@pytest.mark.parametrize("offset_day", [0, 1, 3])
def test_duplicate_and_concurrent_invocation_has_one_charge_authority_per_slot(
    session_factory,
    offset_day,
):
    case = _seed_paid_case(session_factory)
    if offset_day >= 1:
        _fail_at(session_factory, case, DUE)
    if offset_day >= 3:
        _fail_at(session_factory, case, DUE + dt.timedelta(days=1))
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-concurrent-{0}".format(offset_day))
    )
    executor = _executor(
        session_factory, DUE + dt.timedelta(days=offset_day), provider
    )
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait()
        return executor.execute(case.subscription_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: invoke(), range(2)))

    assert "succeeded" in statuses
    assert len(provider.requests) == 1
    attempts = _attempts(session_factory, case.subscription_id)
    assert [row.attempt_no for row in attempts] == list(
        range(1, offset_day == 0 and 2 or offset_day == 1 and 3 or 4)
    )
    assert sum(row.status == "succeeded" for row in attempts) == 1


def test_stale_failure_cannot_suspend_already_settled_renewal(session_factory):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
    with session_factory.begin() as session:
        result = RenewalBillingService(session, FixedClock(DUE)).apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeProviderResult.succeeded("tx-winner"),
        )
        assert result.status == "succeeded"
    with session_factory.begin() as session:
        stale = RenewalBillingService(session, FixedClock(DUE)).apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeProviderResult.failed("STALE_FAILURE"),
        )
        assert stale.status == "succeeded"
    with session_factory() as session:
        assert session.get(Subscription, case.subscription_id).state == "active"


def test_month_end_anchor_clamps_then_returns_to_original_day(session_factory):
    feb_due = dt.datetime(2027, 2, 27, 15, 0, tzinfo=UTC)  # Feb 28 KST
    case = _seed_paid_case(
        session_factory, due_at=feb_due, anchor_day=31
    )
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-month-end-renewal")
    )

    result = _executor(session_factory, feb_due, provider).execute(
        case.subscription_id
    )

    assert result.status == "succeeded"
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.billing_anchor_day == 31
        assert subscription.current_period_start == dt.date(2027, 2, 28)
        assert subscription.current_period_end == dt.date(2027, 3, 31)
        assert subscription.next_billing_at == dt.datetime(
            2027, 3, 30, 15, 0, tzinfo=UTC
        )


@pytest.mark.parametrize("missing", ["payment", "delivery"])
def test_missing_billing_authority_blocks_attempt(session_factory, missing):
    case = _seed_paid_case(
        session_factory,
        payment=missing != "payment",
        delivery=missing != "delivery",
    )
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-blocked"))

    result = _executor(session_factory, DUE, provider).execute(case.subscription_id)

    assert result.status == "blocked_{0}".format(
        "payment_method" if missing == "payment" else "delivery_email"
    )
    assert provider.requests == []
    assert _attempts(session_factory, case.subscription_id) == []


def test_wrong_account_payment_method_evidence_is_rejected(session_factory):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
        other_account = make_account(session)
        other_method = make_payment_method(session, other_account)
        session.get(BillingAttempt, attempt_id).payment_method_id = other_method.id

    with session_factory.begin() as session:
        with pytest.raises(RenewalBillingConflict):
            RenewalBillingService(session, FixedClock(DUE)).apply_provider_result(
                billing_attempt_id=attempt_id,
                provider_result=FirstChargeProviderResult.succeeded("tx-forbidden"),
            )


def test_invalid_email_blocks_new_command_without_rewriting_frozen_contract(
    session_factory,
):
    case = _seed_paid_case(
        session_factory,
        plan_code="package_two",
        products=("today_genie", "keysuri_korea"),
        price=11000,
    )
    with session_factory.begin() as session:
        delivery = session.scalar(
            sa.select(DeliveryEmail).where(
                DeliveryEmail.account_id == case.account_id
            )
        )
        delivery.status = "superseded"
        delivery.deactivated_at = DUE
    provider = FakeRenewalProvider(FirstChargeProviderResult.succeeded("tx-no-email"))

    blocked = _executor(session_factory, DUE, provider).execute(case.subscription_id)

    assert blocked.status == "blocked_delivery_email"
    assert provider.requests == []
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.contracted_plan_code == "package_two"
        assert subscription.contracted_price_krw == 11000
        assert {
            row.product_code
            for row in session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == case.subscription_id
                )
            )
        } == {"today_genie", "keysuri_korea"}


def test_catalog_price_change_does_not_reprice_frozen_subscription(session_factory):
    case = _seed_paid_case(
        session_factory,
        plan_code="package_two",
        products=("today_genie", "keysuri_korea"),
        price=11000,
    )
    with session_factory.begin() as session:
        old = session.scalar(
            sa.select(PlanCatalog).where(
                PlanCatalog.plan_code == "package_two",
                PlanCatalog.price_version == 1,
            )
        )
        old.effective_to = DUE - dt.timedelta(days=1)
        session.add(
            PlanCatalog(
                plan_code="package_two",
                price_version=2,
                price_krw=22000,
                currency="KRW",
                vat_included=True,
                product_count=2,
                effective_from=DUE - dt.timedelta(days=1),
            )
        )
    provider = FakeRenewalProvider(
        FirstChargeProviderResult.succeeded("tx-frozen-price")
    )

    result = _executor(session_factory, DUE, provider).execute(case.subscription_id)

    assert result.status == "succeeded"
    assert provider.requests[0].amount_krw == 11000
    assert provider.requests[0].price_version == 1


def test_email_change_after_provider_command_does_not_rewrite_payment_success(
    session_factory,
):
    case = _seed_paid_case(session_factory)
    with session_factory.begin() as session:
        prepared = RenewalBillingService(session, FixedClock(DUE)).prepare(
            subscription_id=case.subscription_id,
            provider_name="fake_charge_provider",
        )
        attempt_id = uuid.UUID(prepared.request.attempt_id)
    with session_factory.begin() as session:
        delivery = session.scalar(
            sa.select(DeliveryEmail).where(
                DeliveryEmail.account_id == case.account_id
            )
        )
        verified_at = delivery.verified_at
        delivery.status = "superseded"
        delivery.deactivated_at = DUE
    with session_factory.begin() as session:
        result = RenewalBillingService(session, FixedClock(DUE)).apply_provider_result(
            billing_attempt_id=attempt_id,
            provider_result=FirstChargeProviderResult.succeeded(
                "tx-financial-success-email-blocked"
            ),
        )

    assert result.status == "succeeded"
    assert not result.delivery_available
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        delivery = session.scalar(
            sa.select(DeliveryEmail).where(
                DeliveryEmail.account_id == case.account_id
            )
        )
        assert subscription.state == "active"
        assert delivery.status == "superseded"
        assert delivery.verified_at == verified_at
        assert session.scalar(
            sa.select(sa.func.count()).select_from(RecipientSnapshot).where(
                RecipientSnapshot.subscription_id == case.subscription_id
            )
        ) == 0


def test_provider_errors_and_keys_are_absent_from_audit_and_events(session_factory):
    case = _seed_paid_case(session_factory)
    provider = FakeRenewalProvider(raises=True)
    result = _executor(session_factory, DUE, provider).execute(case.subscription_id)
    assert result.status == "provider_state_unknown"
    request = provider.requests[0]
    persisted = []
    with session_factory() as session:
        persisted.extend(
            session.scalars(
                sa.select(BillingEvent.detail).join(BillingAttempt).where(
                    BillingAttempt.subscription_id == case.subscription_id
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
    assert "raw renewal provider secret" not in text
    assert request.idempotency_key not in text
    assert request.billing_key_reference not in text


def test_no_public_renewal_route_worker_or_production_mount():
    from customer.api.router import create_customer_test_app
    from main import app

    customer_paths = {
        route.path
        for route in create_customer_test_app().routes
        if route.path.startswith("/v1/customer")
    }
    assert {
        path
        for path in customer_paths
        if "renewal" in path or "billing" in path
    } == {
        "/v1/customer/billing/recovery",
        "/v1/customer/billing/recovery/first-charge",
        "/v1/customer/billing/recovery/suspended-renewal",
    }
    assert not any(
        getattr(route, "path", "").startswith("/v1/customer") for route in app.routes
    )
    assert any(getattr(route, "path", "").startswith("/internal") for route in app.routes)
