"""D-3 conversion foundation against isolated PostgreSQL."""

import datetime as dt

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from customer.api.dependencies import (  # noqa: E402
    CustomerApiSecurityConfig,
    get_clock,
    get_customer_api_security_config,
    get_customer_db_session,
)
from customer.api.router import create_customer_test_app  # noqa: E402
from customer.domain.catalog import PLAN_FIXED_PRODUCTS, PLAN_PRICES_KRW  # noqa: E402
from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.enums import AuthAssuranceLevel  # noqa: E402
from customer.domain.errors import ConversionNotEligible  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BillingEvent,
    CommandIdempotency,
    ConversionSelection,
    ConversionSelectionProduct,
    ConversionSnapshot,
    ConversionSnapshotProduct,
    Entitlement,
    SubscriptionProduct,
)
from customer.services.cookies import session_cookie_settings  # noqa: E402
from customer.services.conversion_service import ConversionService  # noqa: E402
from customer.services.session_service import SessionService  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    make_entitlement,
    make_payment_method,
    make_subscription,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db
__all__ = ["customer_engine", "session"]

ORIGIN = "https://testserver"
NOW = dt.datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.fixture()
def clock():
    return FixedClock(NOW)


@pytest.fixture()
def conversion_api(session, clock):
    account = make_account(session, email="conversion-owner@example.com")
    method = make_payment_method(session, account)
    subscription = make_subscription(session, account, state="trialing")
    subscription.trial_start_at = NOW - dt.timedelta(days=12)
    subscription.trial_end_at = NOW + dt.timedelta(days=2)
    for product in ("today_genie", "keysuri_global", "keysuri_korea"):
        make_entitlement(session, account, subscription, product)
    created = SessionService(session, clock).create_browser_session(
        account_id=account.id,
        assurance=AuthAssuranceLevel.STRONG_OTP.value,
    )
    session.flush()
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
    app.dependency_overrides[get_customer_api_security_config] = lambda: (
        CustomerApiSecurityConfig(
            cookie_secure=True,
            allowed_state_changing_origins=frozenset({ORIGIN}),
        )
    )
    with TestClient(app, base_url=ORIGIN) as client:
        settings = session_cookie_settings(remember_login=False, secure=True)
        client.cookies.set(settings.name, created.token)
        yield client, account, method, subscription, created


def _select(client, plan="full_set", products=None):
    if products is None:
        products = list(PLAN_FIXED_PRODUCTS[plan])
    return client.put(
        "/v1/customer/conversion/selection",
        headers={"Origin": ORIGIN},
        json={"plan_code": plan, "products": products},
    )


def _confirm(client, key="confirm-1", confirm=True):
    return client.post(
        "/v1/customer/conversion/confirm",
        headers={"Origin": ORIGIN, "Idempotency-Key": key},
        json={"confirm": confirm},
    )


def test_catalog_is_canonical_neutral_and_vat_inclusive(conversion_api):
    client, _, _, _, _ = conversion_api
    response = client.get("/v1/customer/conversion/catalog")
    assert response.status_code == 200
    plans = response.json()["plans"]
    assert {row["plan_code"]: row["price_krw"] for row in plans} == PLAN_PRICES_KRW
    by_code = {row["plan_code"]: row for row in plans}
    assert by_code["full_set"]["price_krw"] - by_code["package_two"]["price_krw"] == 5500
    for plan_code, products in PLAN_FIXED_PRODUCTS.items():
        assert set(by_code[plan_code]["fixed_products"]) == set(products)
    assert all(row["currency"] == "KRW" and row["vat_included"] for row in plans)
    assert all(row["selected"] is False for row in plans)
    assert "14300" not in response.text and "3300" not in response.text
    assert "popular" not in response.text.lower() and "recommend" not in response.text.lower()


def test_eligibility_uses_exact_d3_window(conversion_api, clock):
    client, _, _, subscription, _ = conversion_api
    response = client.get("/v1/customer/conversion/eligibility")
    assert response.status_code == 200
    body = response.json()["conversion"]
    assert body["eligible"] is True
    assert body["opens_at"] == (subscription.trial_end_at - dt.timedelta(days=3)).isoformat()
    assert body["closes_at"] == subscription.trial_end_at.isoformat()
    clock.set(subscription.trial_end_at - dt.timedelta(days=3, microseconds=1))
    assert client.get("/v1/customer/conversion/eligibility").json()["conversion"]["eligible"] is False


def test_pre_d3_selection_and_confirmation_are_blocked(conversion_api, clock, session):
    client, _, _, subscription, _ = conversion_api
    clock.set(subscription.trial_end_at - dt.timedelta(days=3, microseconds=1))
    assert _select(client).json() == {"error": {"code": "CONVERSION_NOT_ELIGIBLE"}}
    assert _confirm(client).json() == {"error": {"code": "CONVERSION_NOT_ELIGIBLE"}}
    assert session.query(ConversionSelection).count() == 0
    assert session.query(ConversionSnapshot).count() == 0

    clock.set(subscription.trial_end_at)
    with pytest.raises(ConversionNotEligible):
        ConversionService(session, clock).select(
            account_id=subscription.account_id,
            plan_code="full_set",
            products=PLAN_FIXED_PRODUCTS["full_set"],
        )


def test_selection_is_persisted_but_not_conversion_consent(conversion_api, session):
    client, account, _, subscription, _ = conversion_api
    response = _select(client)
    assert response.status_code == 200
    body = response.json()["conversion"]
    assert body["state"] == "renewal_pending"
    assert body["confirmed"] is False and body["charged"] is False
    assert body["price_krw"] == 16500
    selection = session.query(ConversionSelection).one()
    assert selection.account_id == account.id
    assert {row.product_code for row in selection.products} == set(PLAN_FIXED_PRODUCTS["full_set"])
    assert subscription.contracted_plan_code is None
    assert session.query(ConversionSnapshot).count() == 0
    assert session.query(BillingAttempt).count() == 0


def test_duplicate_selection_is_idempotent_and_preconfirm_change_is_allowed(conversion_api, session):
    client, _, _, _, _ = conversion_api
    first = _select(client)
    duplicate = _select(client)
    changed = _select(client, "package_two", ["today_genie", "keysuri_korea"])
    assert first.status_code == duplicate.status_code == changed.status_code == 200
    assert first.json()["conversion"]["selection_id"] == duplicate.json()["conversion"]["selection_id"]
    assert changed.json()["conversion"]["plan_code"] == "package_two"
    assert changed.json()["conversion"]["price_krw"] == 11000
    assert session.query(ConversionSelection).count() == 1
    assert session.query(ConversionSelectionProduct).count() == 2


@pytest.mark.parametrize(
    "plan,products",
    [
        ("package_two", ["today_genie"]),
        ("package_two", ["today_genie", "today_genie"]),
        ("full_set", ["today_genie", "keysuri_global"]),
        ("today_genie", ["keysuri_korea"]),
        ("unknown", ["today_genie"]),
    ],
)
def test_invalid_plan_composition_is_rejected(conversion_api, session, plan, products):
    client, _, _, _, _ = conversion_api
    response = _select(client, plan, products)
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "CONVERSION_SELECTION_INVALID"}}
    assert session.query(ConversionSelection).count() == 0


def test_confirmation_requires_explicit_selection_and_boolean_consent(conversion_api, session):
    client, _, _, _, _ = conversion_api
    missing = _confirm(client)
    refused = _confirm(client, key="refused", confirm=False)
    assert missing.status_code == 409
    assert missing.json() == {"error": {"code": "CONVERSION_SELECTION_REQUIRED"}}
    assert refused.status_code == 400
    assert refused.json() == {"error": {"code": "CONVERSION_NOT_CONFIRMED"}}
    assert session.query(ConversionSnapshot).count() == 0


def test_confirmation_freezes_contract_and_schedules_zero_charge(conversion_api, session, clock):
    client, account, method, subscription, _ = conversion_api
    assert _select(client, "package_two", ["today_genie", "keysuri_global"]).status_code == 200
    response = _confirm(client)
    assert response.status_code == 200
    body = response.json()
    assert body["replayed"] is False
    assert body["conversion"]["state"] == "conversion_scheduled"
    assert body["conversion"]["first_charge_at"] == subscription.trial_end_at.isoformat()
    assert body["conversion"]["charged"] is False
    assert "billing_key" not in response.text.lower()
    assert method.billing_key_reference not in response.text

    snapshot = session.query(ConversionSnapshot).one()
    assert snapshot.account_id == account.id
    assert snapshot.person_id == account.person_id
    assert snapshot.payment_method_id == method.id
    assert snapshot.first_charge_at == subscription.trial_end_at
    assert snapshot.confirmed_at == clock.now()
    assert snapshot.plan_code == "package_two" and snapshot.price_krw == 11000
    assert {row.product_code for row in snapshot.products} == {"today_genie", "keysuri_global"}
    assert subscription.contracted_plan_code is None
    assert subscription.next_billing_at is None
    assert session.query(SubscriptionProduct).count() == 0
    assert session.query(BillingAttempt).count() == 0
    assert session.query(BillingEvent).count() == 0
    assert session.query(Entitlement).count() == 3
    assert session.query(AuditEvent).filter_by(event_type="subscription.conversion_confirmed").count() == 1


def test_confirmation_replay_and_different_key_do_not_duplicate(conversion_api, session):
    client, _, _, _, _ = conversion_api
    _select(client)
    first = _confirm(client, "same")
    replay = _confirm(client, "same")
    different = _confirm(client, "different")
    assert first.status_code == replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert different.status_code == 409
    assert different.json() == {"error": {"code": "CONVERSION_NOT_ELIGIBLE"}}
    assert session.query(ConversionSnapshot).count() == 1
    assert session.query(CommandIdempotency).filter_by(command="subscription.conversion_confirm").count() == 1


def test_confirmation_requires_fresh_strong_mobile_auth(conversion_api, session):
    client, _, _, _, browser_session = conversion_api
    _select(client)
    from customer.persistence.models import BrowserSession

    stored_session = session.get(BrowserSession, browser_session.session_id)
    stored_session.fresh_auth_assurance = AuthAssuranceLevel.RECENT_VERIFICATION.value
    session.flush()
    response = _confirm(client)
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "STEP_UP_REQUIRED"}}
    assert session.query(ConversionSnapshot).count() == 0


def test_missing_verified_default_payment_method_blocks_confirmation(conversion_api, session):
    client, _, method, _, _ = conversion_api
    _select(client)
    method.own_name_verified = False
    method.own_name_verified_at = None
    session.flush()
    response = _confirm(client)
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "PAYMENT_METHOD_REQUIRED"}}
    assert session.query(ConversionSnapshot).count() == 0


def test_post_confirmation_selection_is_immutable(conversion_api, session):
    client, _, _, _, _ = conversion_api
    _select(client)
    assert _confirm(client).status_code == 200
    response = _select(client, "today_genie", ["today_genie"])
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "CONVERSION_NOT_ELIGIBLE"}}
    assert session.query(ConversionSnapshot).one().plan_code == "full_set"


def test_database_rejects_confirmed_snapshot_rewrite(conversion_api, session):
    client, _, _, _, _ = conversion_api
    _select(client)
    assert _confirm(client).status_code == 200
    snapshot = session.query(ConversionSnapshot).one()
    with pytest.raises(sa.exc.DBAPIError):
        session.execute(
            sa.text("UPDATE conversion_snapshot SET price_krw = 6600 WHERE id = :id"),
            {"id": snapshot.id},
        )
        session.flush()


def test_wrong_account_cannot_read_or_confirm_selection(conversion_api, session, clock):
    client, _, _, _, _ = conversion_api
    _select(client)
    other = make_account(session, email="other@example.com")
    other_session = SessionService(session, clock).create_browser_session(
        account_id=other.id, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    settings = session_cookie_settings(remember_login=False, secure=True)
    client.cookies.set(settings.name, other_session.token)
    read = client.get("/v1/customer/conversion/selection")
    confirm = _confirm(client, "other")
    assert read.status_code == confirm.status_code == 409
    assert session.query(ConversionSnapshot).count() == 0


def test_production_app_has_no_customer_routes():
    from main import app

    assert not any(getattr(route, "path", "").startswith("/v1/customer") for route in app.routes)
    assert any(getattr(route, "path", "").startswith("/internal") for route in app.routes)


def test_schema_has_no_prohibited_card_secret_columns():
    names = {
        column.name.lower()
        for table in (ConversionSelection.__table__, ConversionSnapshot.__table__)
        for column in table.columns
    }
    assert not names.intersection({"pan", "card_number", "cvv", "cvc", "card_password", "billing_key_reference"})
