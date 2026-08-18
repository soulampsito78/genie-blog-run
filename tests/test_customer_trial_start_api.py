"""Stage 4 explicit trial confirmation against isolated PostgreSQL."""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient  # noqa: E402

from customer.api.dependencies import (  # noqa: E402
    CustomerApiSecurityConfig,
    get_clock,
    get_customer_api_security_config,
    get_customer_db_session,
)
from customer.api.router import create_customer_test_app  # noqa: E402
from customer.domain import auth_policy  # noqa: E402
from customer.domain.catalog import (  # noqa: E402
    TRIAL_CALENDAR_DAYS,
    TRIAL_ELIGIBILITY_BLOCK_DAYS,
    TRIAL_PRODUCTS,
)
from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.enums import AuthAssuranceLevel  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    BrowserSession,
    CommandIdempotency,
    ConversionSnapshot,
    DeliveryEmail,
    Entitlement,
    PaymentMethod,
    Subscription,
    SubscriptionProduct,
    TrialEligibilityBlock,
)
from customer.services.cookies import session_cookie_settings  # noqa: E402
from customer.services.session_service import SessionService  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    make_delivery_email,
    make_payment_method,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db
__all__ = ["customer_engine", "session"]

ORIGIN = "https://testserver"
KST = ZoneInfo("Asia/Seoul")


@pytest.fixture()
def clock():
    # Friday 18:00 KST.  The next day is Liberation Day, followed by a
    # weekend and the substitute holiday, so first delivery is Tuesday.
    return FixedClock(dt.datetime(2026, 8, 14, 9, 0, tzinfo=UTC))


@pytest.fixture()
def trial_api(session, clock):
    account = make_account(session, email="trial-owner@example.com")
    method = make_payment_method(session, account)
    delivery_email = make_delivery_email(
        session, account, email=account.account_email
    )
    delivery_email.verified_at = clock.now() - dt.timedelta(minutes=5)
    session.flush()
    created = SessionService(session, clock).create_browser_session(
        account_id=account.id,
        assurance=AuthAssuranceLevel.RECENT_VERIFICATION.value,
    )
    app = create_customer_test_app()

    def transactional_test_session():
        transaction = session.begin_nested()
        try:
            yield session
            transaction.commit()
        except Exception:
            if transaction.is_active:
                transaction.rollback()
            raise

    app.dependency_overrides[get_customer_db_session] = transactional_test_session
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[
        get_customer_api_security_config
    ] = lambda: CustomerApiSecurityConfig(
        cookie_secure=True,
        allowed_state_changing_origins=frozenset({ORIGIN}),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        settings = session_cookie_settings(remember_login=False, secure=True)
        client.cookies.set(settings.name, created.token)
        yield client, account, method, created


def _start(client, key="trial-start", *, confirm=True, origin=ORIGIN):
    return client.post(
        "/v1/customer/trial/start",
        headers={"Origin": origin, "Idempotency-Key": key},
        json={"confirm": confirm},
    )


def test_valid_explicit_confirmation_creates_exact_trial_state(trial_api, session, clock):
    client, account, _, _ = trial_api

    response = _start(client)

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding"] == {"next_required_stage": "onboarding_complete"}
    assert body["replayed"] is False
    assert body["trial"]["state"] == "trialing"
    assert body["trial"]["products"] == sorted(TRIAL_PRODUCTS)
    assert body["trial"]["automatic_paid_conversion"] is False
    assert "plan" not in response.text.lower()
    assert "price" not in response.text.lower()
    assert "billing_key" not in response.text.lower()

    subscription = session.query(Subscription).one()
    assert subscription.account_id == account.id
    assert subscription.state == "trialing"
    assert subscription.trial_start_at == clock.now()
    assert subscription.trial_end_at - subscription.trial_start_at == dt.timedelta(
        days=TRIAL_CALENDAR_DAYS
    )
    assert subscription.trial_start_at.astimezone(KST).hour == 18
    assert subscription.trial_end_at.astimezone(KST).hour == 18
    assert subscription.delivery_start_date == dt.date(2026, 8, 18)
    assert subscription.contracted_plan_code is None
    assert subscription.contracted_price_krw is None
    assert subscription.contracted_price_version is None
    assert subscription.contracted_at is None
    assert subscription.next_billing_at is None

    entitlement_rows = session.query(Entitlement).all()
    assert {row.product_code for row in entitlement_rows} == set(TRIAL_PRODUCTS)
    assert len(entitlement_rows) == 3
    assert all(row.source == "trial" for row in entitlement_rows)
    assert all(row.plan_code is None and row.price_version is None for row in entitlement_rows)
    assert all(row.effective_from == dt.date(2026, 8, 18) for row in entitlement_rows)
    assert session.query(SubscriptionProduct).count() == 0

    delivery_email = session.query(DeliveryEmail).one()
    assert delivery_email.account_id == account.id
    assert delivery_email.email == account.account_email
    assert delivery_email.status == "active"
    assert delivery_email.verified_at == clock.now() - dt.timedelta(minutes=5)

    block = session.query(TrialEligibilityBlock).one()
    assert block.idv_stable_key == account.person.idv_stable_key
    assert block.trial_started_at == subscription.trial_start_at
    assert block.trial_ended_at == subscription.trial_end_at
    assert block.block_expires_at - block.trial_ended_at == dt.timedelta(
        days=TRIAL_ELIGIBILITY_BLOCK_DAYS
    )

    assert session.query(BillingAttempt).count() == 0
    assert session.query(BillingEvent).count() == 0
    assert session.query(ConversionSnapshot).count() == 0
    event = (
        session.query(AuditEvent)
        .filter_by(event_type="subscription.trial_started")
        .one()
    )
    assert event.account_id == account.id
    assert event.subscription_id == subscription.id
    assert event.payload == {
        "duration_days": 14,
        "product_count": 3,
        "delivery_start_date": "2026-08-18",
        "automatic_paid_conversion": False,
    }


def test_same_and_new_key_replays_create_no_duplicate_state(trial_api, session):
    client, _, _, _ = trial_api
    first = _start(client, "trial-same-key")
    same_key = _start(client, "trial-same-key")
    new_key = _start(client, "trial-new-key")

    assert first.status_code == same_key.status_code == new_key.status_code == 200
    trial_ids = {
        first.json()["trial"]["subscription_id"],
        same_key.json()["trial"]["subscription_id"],
        new_key.json()["trial"]["subscription_id"],
    }
    assert len(trial_ids) == 1
    assert same_key.json()["replayed"] is True
    assert new_key.json()["replayed"] is True
    assert session.query(Subscription).count() == 1
    assert session.query(Entitlement).count() == 3
    assert session.query(DeliveryEmail).count() == 1
    assert session.query(TrialEligibilityBlock).count() == 1
    assert session.query(CommandIdempotency).filter_by(
        command="subscription.trial_start"
    ).count() == 2
    assert session.query(AuditEvent).filter_by(
        event_type="subscription.trial_started"
    ).count() == 1


@pytest.mark.parametrize("invalid_kind", ["missing", "not_default", "not_verified", "invalid"])
def test_missing_or_invalid_payment_method_is_blocked(
    trial_api, session, invalid_kind
):
    client, _, method, _ = trial_api
    if invalid_kind == "missing":
        session.delete(method)
    elif invalid_kind == "not_default":
        method.is_default = False
    elif invalid_kind == "not_verified":
        method.own_name_verified = False
    else:
        method.status = "invalid"
        method.is_default = False
    session.flush()

    response = _start(client, "invalid-method-{0}".format(invalid_kind))

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "PAYMENT_METHOD_REQUIRED"}}
    assert session.query(Subscription).count() == 0
    assert session.query(Entitlement).count() == 0


def test_unverified_person_is_blocked(trial_api, session):
    client, account, _, _ = trial_api
    account.person.adult_verified = False
    account.person.adult_verified_at = None
    session.flush()

    response = _start(client, "unverified-person")

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "IDV_FAILED"}}
    assert session.query(Subscription).count() == 0


def test_prior_trial_identity_inside_one_year_window_is_blocked(
    trial_api, session, clock
):
    client, account, _, _ = trial_api
    trial_end = clock.now() - dt.timedelta(days=30)
    session.add(
        TrialEligibilityBlock(
            idv_stable_key=account.person.idv_stable_key,
            trial_started_at=trial_end - dt.timedelta(days=14),
            trial_ended_at=trial_end,
            block_expires_at=trial_end + dt.timedelta(days=365),
            created_at=trial_end - dt.timedelta(days=14),
        )
    )
    session.flush()

    response = _start(client, "blocked-person")

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "TRIAL_NOT_ELIGIBLE"}}
    assert session.query(Subscription).count() == 0
    assert session.query(Entitlement).count() == 0


def test_existing_unverified_delivery_state_is_not_bypassed(trial_api, session):
    client, _, _, _ = trial_api
    delivery_email = session.query(DeliveryEmail).one()
    delivery_email.status = "pending_verification"
    delivery_email.verified_at = None
    session.flush()

    response = _start(client, "unverified-delivery")

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "DELIVERY_EMAIL_UNVERIFIED"}}
    assert session.query(DeliveryEmail).count() == 1
    assert session.query(Subscription).count() == 0


def test_pending_replacement_never_switches_before_its_own_verification(
    trial_api, session
):
    client, account, _, _ = trial_api
    active = session.query(DeliveryEmail).one()
    pending = make_delivery_email(
        session,
        account,
        status="pending_verification",
        email="replacement-pending@example.com",
    )

    response = _start(client, "pending-replacement")

    assert response.status_code == 200
    session.refresh(active)
    session.refresh(pending)
    assert active.status == "active"
    assert active.email == account.account_email
    assert pending.status == "pending_verification"
    assert pending.verified_at is None


def test_trial_uses_prior_email_evidence_without_new_verification_event(
    trial_api, session, clock
):
    client, _, _, _ = trial_api
    delivery_email = session.query(DeliveryEmail).one()
    prior_verified_at = delivery_email.verified_at
    prior_event_count = session.query(AuditEvent).filter_by(
        event_type="auth.challenge_verified"
    ).count()

    response = _start(client, "no-fabricated-email-verification")

    assert response.status_code == 200
    session.refresh(delivery_email)
    assert delivery_email.verified_at == prior_verified_at
    assert delivery_email.verified_at < clock.now()
    assert session.query(AuditEvent).filter_by(
        event_type="auth.challenge_verified"
    ).count() == prior_event_count


def test_confirmation_must_be_explicit_and_same_site(trial_api, session):
    client, _, _, _ = trial_api
    declined = _start(client, "not-confirmed", confirm=False)
    wrong_origin = _start(client, "wrong-origin", origin="https://evil.example")

    assert declined.status_code == 400
    assert declined.json() == {"error": {"code": "TRIAL_CONFIRMATION_REQUIRED"}}
    assert wrong_origin.status_code == 403
    assert wrong_origin.json() == {"error": {"code": "REQUEST_ORIGIN_REJECTED"}}
    assert session.query(Subscription).count() == 0


def test_trial_requires_authentication_and_is_account_scoped(trial_api, session):
    client, account, _, _ = trial_api
    other = make_account(session, email="other-trial-owner@example.com")
    make_payment_method(session, other)

    response = _start(client, "account-scoped")
    assert response.status_code == 200
    assert session.query(Subscription).one().account_id == account.id
    assert session.query(Subscription).filter_by(account_id=other.id).count() == 0

    client.cookies.clear()
    anonymous = _start(client, "anonymous")
    assert anonymous.status_code == 401
    assert anonymous.json() == {"error": {"code": "AUTHENTICATION_REQUIRED"}}


def test_trial_start_does_not_invent_step_up_beyond_current_contract(
    trial_api, session, clock
):
    client, _, _, created = trial_api
    browser_session = session.get(BrowserSession, created.session_id)
    browser_session.last_fresh_auth_at = clock.now() - auth_policy.FRESH_AUTH_WINDOW
    session.flush()

    response = _start(client, "authenticated-not-step-up")

    assert response.status_code == 200
    assert session.query(Subscription).count() == 1


def test_current_projection_is_customer_safe(trial_api):
    client, _, method, _ = trial_api
    started = _start(client, "projection")
    assert started.status_code == 200

    response = client.get("/v1/customer/trial")

    assert response.status_code == 200
    assert response.json()["trial"]["subscription_id"] == started.json()["trial"][
        "subscription_id"
    ]
    serialized = response.text
    assert method.billing_key_reference not in serialized
    assert method.own_name_verification_reference not in serialized
    assert "price" not in serialized.lower()
    assert "plan" not in serialized.lower()


def test_trial_routes_remain_production_unmounted_and_customer_only():
    app = create_customer_test_app()
    paths = {route.path for route in app.routes}
    assert "/v1/customer/trial/start" in paths
    assert "/v1/customer/trial" in paths
    assert not any(path.startswith("/admin") or path.startswith("/internal") for path in paths)

    import main

    production_paths = {getattr(route, "path", "") for route in main.app.routes}
    assert not any(path.startswith("/v1/customer") for path in production_paths)
