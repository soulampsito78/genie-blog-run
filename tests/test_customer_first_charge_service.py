"""First paid-charge execution against a dedicated isolated PostgreSQL DB."""

import datetime as dt
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    ConversionSelection,
    ConversionSelectionProduct,
    ConversionSnapshot,
    ConversionSnapshotProduct,
    CustomerAccount,
    Entitlement,
    PaymentMethod,
    PlanCatalog,
    Subscription,
    SubscriptionProduct,
)
from customer.services.charge_providers import (  # noqa: E402
    FirstChargeProviderResult,
)
from customer.services.first_charge_service import FirstChargeExecutor  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    CUSTOMER_TEST_DATABASE_URL_ENV,
    REPO_ROOT,
    make_account,
    make_delivery_email,
    make_entitlement,
    make_payment_method,
    make_subscription,
    requires_customer_db,
)

pytestmark = requires_customer_db

NOW = dt.datetime(2026, 8, 29, 9, 0, tzinfo=UTC)  # 18:00 KST


class FakeChargeProvider:
    name = "fake_charge_provider"

    def __init__(self, *results, raises=False):
        self._results = list(results)
        self._raises = raises
        self._lock = threading.Lock()
        self.requests = []

    def charge(self, request):
        with self._lock:
            self.requests.append(request)
            if self._raises:
                raise RuntimeError("raw provider secret must never persist")
            if not self._results:
                raise AssertionError("provider was invoked more than expected")
            return self._results.pop(0)


@dataclass(frozen=True)
class ChargeCase:
    account_id: uuid.UUID
    subscription_id: uuid.UUID
    snapshot_id: uuid.UUID
    payment_method_id: uuid.UUID


@pytest.fixture(scope="module")
def first_charge_engine():
    base = os.environ.get(CUSTOMER_TEST_DATABASE_URL_ENV, "").strip()
    if not base:
        pytest.skip("no isolated Customer PostgreSQL URL configured")
    base_url = make_url(base)
    database_name = "genie_first_charge_{0}".format(uuid.uuid4().hex[:10])
    admin_url = base_url.set(database="postgres")
    test_url = base_url.set(database=database_name)
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text('CREATE DATABASE "{0}"'.format(database_name)))

    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(REPO_ROOT, "customer/migrations")
    )
    previous = os.environ.get("CUSTOMER_DATABASE_URL")
    os.environ["CUSTOMER_DATABASE_URL"] = test_url.render_as_string(
        hide_password=False
    )
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("CUSTOMER_DATABASE_URL", None)
        else:
            os.environ["CUSTOMER_DATABASE_URL"] = previous

    engine = sa.create_engine(test_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                sa.text(
                    'DROP DATABASE IF EXISTS "{0}" WITH (FORCE)'.format(
                        database_name
                    )
                )
            )
        admin_engine.dispose()


@pytest.fixture()
def session_factory(first_charge_engine):
    return sessionmaker(
        bind=first_charge_engine, future=True, expire_on_commit=False
    )


def _seed_case(
    session_factory,
    *,
    plan_code="full_set",
    products=("today_genie", "keysuri_global", "keysuri_korea"),
    price=16500,
    first_charge_at=NOW,
    delivery=True,
    payment=True,
):
    with session_factory.begin() as session:
        account = make_account(
            session, email="charge-{0}@example.com".format(uuid.uuid4().hex[:10])
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
            session, account, state="conversion_scheduled"
        )
        subscription.trial_start_at = first_charge_at - dt.timedelta(days=14)
        subscription.trial_end_at = first_charge_at
        for product in ("today_genie", "keysuri_global", "keysuri_korea"):
            make_entitlement(
                session,
                account,
                subscription,
                product,
                effective_from=(first_charge_at - dt.timedelta(days=13)).date(),
            )
        selection = ConversionSelection(
            account_id=account.id,
            subscription_id=subscription.id,
            plan_code=plan_code,
            price_krw=price,
            price_version=1,
            currency="KRW",
            selected_at=first_charge_at - dt.timedelta(days=3),
        )
        selection.products = [
            ConversionSelectionProduct(product_code=product)
            for product in products
        ]
        session.add(selection)
        session.flush()
        snapshot = ConversionSnapshot(
            selection_id=selection.id,
            account_id=account.id,
            person_id=account.person_id,
            subscription_id=subscription.id,
            payment_method_id=method.id,
            plan_code=plan_code,
            price_krw=price,
            price_version=1,
            currency="KRW",
            confirmed_at=first_charge_at - dt.timedelta(days=3),
            first_charge_at=first_charge_at,
            status="pending",
        )
        snapshot.products = [
            ConversionSnapshotProduct(product_code=product)
            for product in products
        ]
        session.add(snapshot)
        session.flush()
        return ChargeCase(account.id, subscription.id, snapshot.id, method.id)


def _executor(session_factory, clock, provider):
    return FirstChargeExecutor(session_factory, clock, provider)


def test_before_trial_end_never_calls_provider(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-too-early")
    )
    result = _executor(
        session_factory, FixedClock(NOW - dt.timedelta(microseconds=1)), provider
    ).execute(case.snapshot_id)
    assert result.status == "not_due"
    assert provider.requests == []
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 0


def test_no_explicit_conversion_snapshot_never_charges(session_factory):
    provider = FakeChargeProvider(FirstChargeProviderResult.succeeded("tx-none"))
    result = _executor(session_factory, FixedClock(NOW), provider).execute(
        uuid.uuid4()
    )
    assert result.status == "not_eligible"
    assert provider.requests == []


def test_success_uses_frozen_snapshot_and_activates_atomically(session_factory):
    case = _seed_case(
        session_factory,
        plan_code="package_two",
        products=("today_genie", "keysuri_korea"),
        price=11000,
    )
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded(
            "tx-success", event_reference="evt-success"
        )
    )
    result = _executor(session_factory, FixedClock(NOW), provider).execute(
        case.snapshot_id
    )
    assert result.status == "succeeded"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.amount_krw == 11000
    assert request.plan_code == "package_two"
    assert "bk-" not in repr(request)

    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        snapshot = session.get(ConversionSnapshot, case.snapshot_id)
        attempts = list(
            session.scalars(
                sa.select(BillingAttempt).where(
                    BillingAttempt.conversion_snapshot_id == case.snapshot_id
                )
            )
        )
        assert len(attempts) == 1 and attempts[0].status == "succeeded"
        assert attempts[0].amount_krw == 11000
        assert attempts[0].retry_offset_day is None
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingEvent).where(
                BillingEvent.billing_attempt_id == attempts[0].id,
                BillingEvent.event_type == "first_charge_succeeded",
            )
        ) == 1
        assert subscription.state == "active"
        assert subscription.contracted_plan_code == "package_two"
        assert subscription.contracted_price_krw == 11000
        assert subscription.billing_anchor_day == NOW.astimezone(
            dt.timezone(dt.timedelta(hours=9))
        ).day
        assert subscription.current_period_start == dt.date(2026, 8, 29)
        assert subscription.current_period_end == dt.date(2026, 9, 29)
        assert subscription.next_billing_at == dt.datetime(
            2026, 9, 29, 9, 0, tzinfo=UTC
        )
        assert snapshot.status == "applied" and snapshot.applied_at is not None
        assert {
            row.product_code
            for row in session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == case.subscription_id
                )
            )
        } == {"today_genie", "keysuri_korea"}
        paid = list(
            session.scalars(
                sa.select(Entitlement).where(
                    Entitlement.subscription_id == case.subscription_id,
                    Entitlement.source == "paid",
                    Entitlement.revoked_at.is_(None),
                )
            )
        )
        assert {row.product_code for row in paid} == {
            "today_genie",
            "keysuri_korea",
        }
        assert all(row.plan_code == "package_two" for row in paid)
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.source == "trial",
                Entitlement.revoked_at.is_(None),
            )
        ) == 0


@pytest.mark.parametrize(
    "plan,products,price,count",
    [
        ("today_genie", ("today_genie",), 6600, 1),
        (
            "full_set",
            ("today_genie", "keysuri_global", "keysuri_korea"),
            16500,
            3,
        ),
    ],
)
def test_paid_entitlement_exactly_matches_frozen_plan(
    session_factory, plan, products, price, count
):
    case = _seed_case(
        session_factory, plan_code=plan, products=products, price=price
    )
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-{0}".format(uuid.uuid4().hex))
    )
    assert _executor(session_factory, FixedClock(NOW), provider).execute(
        case.snapshot_id
    ).status == "succeeded"
    with session_factory() as session:
        rows = list(
            session.scalars(
                sa.select(SubscriptionProduct).where(
                    SubscriptionProduct.subscription_id == case.subscription_id
                )
            )
        )
        assert len(rows) == count
        assert {row.product_code for row in rows} == set(products)


def test_live_catalog_difference_cannot_reprice_frozen_charge(session_factory):
    case = _seed_case(session_factory)
    with session_factory.begin() as session:
        row = session.scalar(
            sa.select(PlanCatalog).where(
                PlanCatalog.plan_code == "full_set",
                PlanCatalog.price_version == 1,
            )
        )
        row.price_krw = 99999
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-frozen-price")
    )
    try:
        result = _executor(session_factory, FixedClock(NOW), provider).execute(
            case.snapshot_id
        )
        assert result.status == "succeeded"
        assert provider.requests[0].amount_krw == 16500
        with session_factory() as session:
            assert session.scalar(
                sa.select(BillingAttempt.amount_krw).where(
                    BillingAttempt.conversion_snapshot_id == case.snapshot_id
                )
            ) == 16500
    finally:
        with session_factory.begin() as session:
            row = session.scalar(
                sa.select(PlanCatalog).where(
                    PlanCatalog.plan_code == "full_set",
                    PlanCatalog.price_version == 1,
                )
            )
            row.price_krw = 16500


def test_definitive_failure_expires_without_grace_and_requires_explicit_retry(
    session_factory,
):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.failed(
            "CARD_DECLINED", event_reference="evt-declined"
        ),
        FirstChargeProviderResult.succeeded("tx-retry"),
    )
    executor = _executor(session_factory, FixedClock(NOW), provider)
    failed = executor.execute(case.snapshot_id)
    assert failed.status == "failed" and failed.retry_required
    replay = executor.execute(case.snapshot_id)
    assert replay.status == "failed" and replay.replayed
    explicit_same_card = executor.execute(case.snapshot_id, explicit_retry=True)
    assert explicit_same_card.status == "payment_method_update_required"
    assert len(provider.requests) == 1

    with session_factory.begin() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.state == "trial_expired"
        assert subscription.contracted_plan_code is None
        assert subscription.billing_anchor_day is None
        assert subscription.next_billing_at is None
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.revoked_at.is_(None),
            )
        ) == 0
        old = session.get(PaymentMethod, case.payment_method_id)
        old.is_default = False
        account = session.get(CustomerAccount, case.account_id)
        new_method = make_payment_method(session, account)
        new_method_id = new_method.id

    succeeded = executor.execute(case.snapshot_id, explicit_retry=True)
    assert succeeded.status == "succeeded"
    assert len(provider.requests) == 2
    with session_factory() as session:
        attempts = list(
            session.scalars(
                sa.select(BillingAttempt)
                .where(BillingAttempt.conversion_snapshot_id == case.snapshot_id)
                .order_by(BillingAttempt.attempt_no)
            )
        )
        assert [row.status for row in attempts] == ["failed", "succeeded"]
        assert attempts[1].payment_method_id == new_method_id
        assert attempts[1].retry_offset_day is None
        assert session.get(Subscription, case.subscription_id).billing_anchor_day == 29


def test_unknown_outcome_blocks_blind_and_explicit_retry(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.unknown(operation_reference="op-unknown")
    )
    executor = _executor(session_factory, FixedClock(NOW), provider)
    first = executor.execute(case.snapshot_id)
    duplicate = executor.execute(case.snapshot_id)
    explicit = executor.execute(case.snapshot_id, explicit_retry=True)
    assert first.status == duplicate.status == explicit.status == "provider_state_unknown"
    assert first.reconciliation_required
    assert len(provider.requests) == 1
    with session_factory() as session:
        attempt = session.scalar(
            sa.select(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        )
        assert attempt.status == "provider_state_unknown"
        assert session.get(Subscription, case.subscription_id).state == "conversion_scheduled"
        assert session.scalar(
            sa.select(sa.func.count()).select_from(SubscriptionProduct).where(
                SubscriptionProduct.subscription_id == case.subscription_id
            )
        ) == 0


def test_provider_exception_is_sanitized_unknown(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(raises=True)
    result = _executor(session_factory, FixedClock(NOW), provider).execute(
        case.snapshot_id
    )
    assert result.status == "provider_state_unknown"
    with session_factory() as session:
        attempt = session.scalar(
            sa.select(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        )
        text = " ".join(
            str(value)
            for value in (
                attempt.failure_code,
                attempt.failure_message,
                *session.scalars(
                    sa.select(BillingEvent.detail).where(
                        BillingEvent.billing_attempt_id == attempt.id
                    )
                ),
            )
        )
        assert "raw provider secret" not in text
        assert "bk-" not in text


def test_duplicate_success_never_calls_provider_twice(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-idempotent")
    )
    executor = _executor(session_factory, FixedClock(NOW), provider)
    first = executor.execute(case.snapshot_id)
    duplicate = executor.execute(case.snapshot_id)
    assert first.status == duplicate.status == "succeeded"
    assert duplicate.replayed
    assert len(provider.requests) == 1
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id,
                BillingAttempt.status == "succeeded",
            )
        ) == 1


def test_concurrent_invocation_has_one_provider_authority(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-concurrent")
    )
    executor = _executor(session_factory, FixedClock(NOW), provider)
    barrier = threading.Barrier(2)

    def invoke():
        barrier.wait()
        return executor.execute(case.snapshot_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: invoke(), range(2)))
    assert len(provider.requests) == 1
    assert "succeeded" in statuses
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 1


@pytest.mark.parametrize("missing_kind", ["payment", "delivery"])
def test_missing_charge_precondition_creates_no_attempt(
    session_factory, missing_kind
):
    case = _seed_case(
        session_factory,
        payment=missing_kind != "payment",
        delivery=missing_kind != "delivery",
    )
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-blocked")
    )
    result = _executor(session_factory, FixedClock(NOW), provider).execute(
        case.snapshot_id
    )
    assert result.status == "blocked_{0}".format(
        "payment_method" if missing_kind == "payment" else "delivery_email"
    )
    assert result.retry_required
    assert provider.requests == []
    with session_factory() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(BillingAttempt).where(
                BillingAttempt.conversion_snapshot_id == case.snapshot_id
            )
        ) == 0
        assert session.get(Subscription, case.subscription_id).state == "trial_expired"
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Entitlement).where(
                Entitlement.subscription_id == case.subscription_id,
                Entitlement.revoked_at.is_(None),
            )
        ) == 0


def test_month_end_anchor_is_preserved(session_factory):
    first_charge = dt.datetime(2027, 1, 31, 9, 0, tzinfo=UTC)
    case = _seed_case(session_factory, first_charge_at=first_charge)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-month-end")
    )
    result = _executor(
        session_factory, FixedClock(first_charge), provider
    ).execute(case.snapshot_id)
    assert result.status == "succeeded"
    with session_factory() as session:
        subscription = session.get(Subscription, case.subscription_id)
        assert subscription.billing_anchor_day == 31
        assert subscription.current_period_start == dt.date(2027, 1, 31)
        assert subscription.current_period_end == dt.date(2027, 2, 28)
        assert subscription.next_billing_at == dt.datetime(
            2027, 2, 28, 9, 0, tzinfo=UTC
        )


def test_conversion_snapshot_remains_immutable_after_success(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.succeeded("tx-immutable")
    )
    _executor(session_factory, FixedClock(NOW), provider).execute(case.snapshot_id)
    with session_factory() as session:
        with pytest.raises(sa.exc.DBAPIError):
            session.execute(
                sa.text(
                    "UPDATE conversion_snapshot SET price_krw = 1 WHERE id = :id"
                ),
                {"id": case.snapshot_id},
            )
        session.rollback()


def test_no_public_charge_route_or_operational_wiring():
    from customer.api.router import create_customer_test_app
    from main import app

    customer_paths = {
        route.path
        for route in create_customer_test_app().routes
        if route.path.startswith("/v1/customer")
    }
    assert not any("charge" in path or "billing" in path for path in customer_paths)
    assert not any(
        getattr(route, "path", "").startswith("/v1/customer") for route in app.routes
    )
    assert any(getattr(route, "path", "").startswith("/internal") for route in app.routes)


def test_audit_and_events_expose_no_billing_key(session_factory):
    case = _seed_case(session_factory)
    provider = FakeChargeProvider(
        FirstChargeProviderResult.failed("raw card 4242")
    )
    _executor(session_factory, FixedClock(NOW), provider).execute(case.snapshot_id)
    with session_factory() as session:
        persisted = " ".join(
            str(value)
            for value in (
                *session.scalars(
                    sa.select(BillingEvent.detail)
                    .join(BillingAttempt)
                    .where(BillingAttempt.conversion_snapshot_id == case.snapshot_id)
                ),
                *session.scalars(
                    sa.select(AuditEvent.payload).where(
                        AuditEvent.subscription_id == case.subscription_id
                    )
                ),
            )
        )
        assert "bk-" not in persisted
        assert "4242" not in persisted
        assert "raw card" not in persisted
        assert "PROVIDER_DECLINED" in persisted
