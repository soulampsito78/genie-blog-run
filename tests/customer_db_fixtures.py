"""Shared PostgreSQL fixtures and builders for customer-domain tests.

SAFETY: these tests read `CUSTOMER_TEST_DATABASE_URL`, deliberately a DIFFERENT
variable from the runtime `CUSTOMER_DATABASE_URL`. A deployed environment that
has the runtime variable set can therefore never have its database migrated or
truncated by a test run. When the test variable is unset, every DB test skips.

The schema is created by running the real Alembic migration, so the migration
itself is exercised on every run rather than being bypassed by
`metadata.create_all()`.
"""

import datetime as dt
import os
import uuid
from typing import Optional

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")
pytest.importorskip("alembic", reason="Alembic not installed")

from sqlalchemy.orm import Session  # noqa: E402

CUSTOMER_TEST_DATABASE_URL_ENV = "CUSTOMER_TEST_DATABASE_URL"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_database_url() -> Optional[str]:
    return os.environ.get(CUSTOMER_TEST_DATABASE_URL_ENV, "").strip() or None


requires_customer_db = pytest.mark.skipif(
    _test_database_url() is None,
    reason=(
        "{0} is not set; customer persistence invariants require a local "
        "PostgreSQL test database".format(CUSTOMER_TEST_DATABASE_URL_ENV)
    ),
)


@pytest.fixture(scope="session")
def customer_engine():
    """Engine bound to a freshly migrated test database."""
    url = _test_database_url()
    if url is None:  # pragma: no cover - guarded by requires_customer_db
        pytest.skip("no customer test database configured")

    from alembic import command
    from alembic.config import Config

    config = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(REPO_ROOT, "customer/migrations"))

    # env.py resolves the URL from CUSTOMER_DATABASE_URL; point it at the test
    # database only for the duration of the migration.
    previous = os.environ.get("CUSTOMER_DATABASE_URL")
    os.environ["CUSTOMER_DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("CUSTOMER_DATABASE_URL", None)
        else:
            os.environ["CUSTOMER_DATABASE_URL"] = previous

    engine = sa.create_engine(url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def session(customer_engine):
    """Session inside a transaction that is always rolled back.

    Nothing a test writes survives, so ordering between tests cannot matter.
    """
    connection = customer_engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, future=True, expire_on_commit=False)
    try:
        yield db
    finally:
        db.close()
        # A test that provoked an IntegrityError has already aborted the
        # transaction; rolling back again is harmless but must not mask the
        # real failure.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def force_deferred_constraints(session) -> None:
    """Fire DEFERRABLE INITIALLY DEFERRED constraint triggers now.

    Product-set cardinality is checked at COMMIT in production. Tests roll
    back instead of committing, so they ask PostgreSQL to evaluate the
    deferred checks immediately.
    """
    session.flush()
    session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))


# ---------------------------------------------------------------------------
# Builders - minimal valid rows, so each test states only what it is about.
# ---------------------------------------------------------------------------

UTC = dt.timezone.utc


def make_person(session, *, idv_stable_key: Optional[str] = None):
    from customer.persistence.models import PersonIdentity

    person = PersonIdentity(
        idv_stable_key=idv_stable_key or "DI-{0}".format(uuid.uuid4().hex),
        idv_provider="test_idv",
        idv_reference="ref-{0}".format(uuid.uuid4().hex[:8]),
        adult_verified=True,
        adult_verified_at=dt.datetime.now(UTC),
    )
    session.add(person)
    session.flush()
    return person


def make_account(session, person=None, *, status: str = "active", email: Optional[str] = None):
    from customer.persistence.models import CustomerAccount

    person = person or make_person(session)
    account = CustomerAccount(
        person_id=person.id,
        account_email=email or "user-{0}@example.com".format(uuid.uuid4().hex[:10]),
        mobile_e164="+821012345678",
        status=status,
        withdrawn_at=dt.datetime.now(UTC) if status == "withdrawn" else None,
    )
    session.add(account)
    session.flush()
    return account


def make_subscription(
    session,
    account,
    *,
    state: str = "trialing",
    contracted_plan_code: Optional[str] = None,
    price_krw: Optional[int] = None,
    price_version: int = 1,
):
    from customer.persistence.models import Subscription

    now = dt.datetime.now(UTC)
    trial_bounds = state in {
        "trialing",
        "renewal_pending",
        "conversion_scheduled",
        "trial_expired",
    }
    subscription = Subscription(
        account_id=account.id,
        state=state,
        trial_start_at=now if trial_bounds else None,
        trial_end_at=now + dt.timedelta(days=14) if trial_bounds else None,
        delivery_start_date=(now + dt.timedelta(days=1)).date(),
        contracted_plan_code=contracted_plan_code,
        contracted_price_krw=price_krw if contracted_plan_code else None,
        contracted_price_version=price_version if contracted_plan_code else None,
        contracted_currency="KRW" if contracted_plan_code else None,
        contracted_at=now if contracted_plan_code else None,
        billing_anchor_day=15 if contracted_plan_code else None,
        ended_at=now if state in {"trial_expired", "canceled", "withdrawn"} else None,
    )
    session.add(subscription)
    session.flush()
    return subscription


def make_delivery_email(
    session, account, *, status: str = "active", email: Optional[str] = None
):
    from customer.persistence.models import DeliveryEmail

    now = dt.datetime.now(UTC)
    row = DeliveryEmail(
        account_id=account.id,
        email=email or "deliver-{0}@example.com".format(uuid.uuid4().hex[:10]),
        status=status,
        verified_at=now if status in {"active", "superseded", "suppressed"} else None,
        suppression_reason="hard_bounce" if status == "suppressed" else None,
        suppressed_at=now if status == "suppressed" else None,
    )
    session.add(row)
    session.flush()
    return row


def make_entitlement(
    session,
    account,
    subscription,
    product_code: str,
    *,
    source: str = "trial",
    plan_code: Optional[str] = None,
    price_version: Optional[int] = None,
    effective_from: Optional[dt.date] = None,
):
    from customer.persistence.models import Entitlement

    row = Entitlement(
        account_id=account.id,
        subscription_id=subscription.id,
        product_code=product_code,
        source=source,
        plan_code=plan_code,
        price_version=price_version,
        effective_from=effective_from or dt.date(2026, 8, 12),
    )
    session.add(row)
    session.flush()
    return row


def make_recipient_snapshot(
    session,
    account,
    subscription,
    entitlement,
    delivery_email,
    *,
    product_code: str,
    publication_date: dt.date,
):
    from customer.persistence.models import RecipientSnapshot

    row = RecipientSnapshot(
        account_id=account.id,
        subscription_id=subscription.id,
        product_code=product_code,
        publication_date=publication_date,
        delivery_email=delivery_email.email,
        delivery_email_id=delivery_email.id,
        entitlement_id=entitlement.id,
        entitlement_source=entitlement.source,
        plan_code=entitlement.plan_code,
        price_version=entitlement.price_version,
        subscription_state_at_snapshot=subscription.state,
    )
    session.add(row)
    session.flush()
    return row


def make_payment_method(session, account, *, is_default: bool = True, status: str = "active"):
    from customer.persistence.models import PaymentMethod

    now = dt.datetime.now(UTC)
    row = PaymentMethod(
        account_id=account.id,
        provider="test_pg",
        billing_key_reference="bk-{0}".format(uuid.uuid4().hex),
        card_brand="TESTCARD",
        card_last4="4242",
        display_label="TESTCARD 4242",
        own_name_verified=True,
        own_name_verified_at=now,
        own_name_verification_reference="onv-{0}".format(uuid.uuid4().hex[:8]),
        status=status,
        is_default=is_default,
        revoked_at=now if status == "revoked" else None,
    )
    session.add(row)
    session.flush()
    return row
