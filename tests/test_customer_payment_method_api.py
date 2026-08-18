"""Stage 3 payment-method foundation against an isolated PostgreSQL database."""

import datetime as dt
import inspect
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient  # noqa: E402

from customer.api.dependencies import (  # noqa: E402
    CustomerApiSecurityConfig,
    get_clock,
    get_customer_api_security_config,
    get_customer_db_session,
    get_payment_method_provider,
)
from customer.api.router import create_customer_test_app  # noqa: E402
from customer.domain import auth_policy  # noqa: E402
from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.enums import AuthAssuranceLevel  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    BillingAttempt,
    BrowserSession,
    CommandIdempotency,
    PaymentMethod,
    Subscription,
)
from customer.services.cookies import session_cookie_settings  # noqa: E402
from customer.services.payment_providers import (  # noqa: E402
    PaymentRegistrationResult,
    PaymentRegistrationStart,
    PaymentRegistrationStatus,
)
from customer.services.session_service import SessionService  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    make_payment_method,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db
__all__ = ["customer_engine", "session"]

ORIGIN = "https://testserver"


class FakePaymentProvider:
    name = "fake_pg"

    def __init__(self):
        self.starts = {}
        self.results = {}
        self.start_calls = 0
        self.verify_calls = 0
        self.start_exception = None
        self.verify_exception = None

    def start_registration(self, *, account_reference, idempotency_key):
        del account_reference
        if self.start_exception is not None:
            raise self.start_exception
        if idempotency_key not in self.starts:
            self.start_calls += 1
            self.starts[idempotency_key] = "payment-registration-{0}".format(
                uuid.uuid4().hex
            )
        return PaymentRegistrationStart(self.starts[idempotency_key])

    def verify_registration(self, *, registration_reference):
        self.verify_calls += 1
        if self.verify_exception is not None:
            raise self.verify_exception
        return self.results.get(
            registration_reference,
            PaymentRegistrationResult(
                provider=self.name,
                registration_reference=registration_reference,
                status=PaymentRegistrationStatus.PENDING.value,
            ),
        )


@pytest.fixture()
def clock():
    return FixedClock(dt.datetime(2026, 8, 18, 9, 0, tzinfo=UTC))


@pytest.fixture()
def payment_api(session, clock):
    account = make_account(session, email="payment-owner@example.com")
    created = SessionService(session, clock).create_browser_session(
        account_id=account.id,
        assurance=AuthAssuranceLevel.STRONG_OTP.value,
    )
    provider = FakePaymentProvider()
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
    app.dependency_overrides[get_payment_method_provider] = lambda: provider
    app.dependency_overrides[
        get_customer_api_security_config
    ] = lambda: CustomerApiSecurityConfig(
        cookie_secure=True,
        allowed_state_changing_origins=frozenset({ORIGIN}),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        settings = session_cookie_settings(remember_login=False, secure=True)
        client.cookies.set(settings.name, created.token)
        yield client, provider, account, created


def _headers(key):
    return {"Origin": ORIGIN, "Idempotency-Key": key}


def _initiate(client, key, replacement_id=None):
    body = {}
    if replacement_id is not None:
        body["replacement_payment_method_id"] = str(replacement_id)
    return client.post(
        "/v1/customer/payment-methods/registration",
        headers=_headers(key),
        json=body,
    )


def _success_result(provider, reference, suffix):
    provider.results[reference] = PaymentRegistrationResult(
        provider=provider.name,
        registration_reference=reference,
        status=PaymentRegistrationStatus.SUCCEEDED.value,
        billing_key_reference="bk-server-only-{0}".format(suffix),
        own_name_verified=True,
        own_name_verification_reference="own-name-proof-{0}".format(suffix),
        card_brand="TESTCARD",
        card_last4="4242",
        # Any adapter-supplied label is ignored; the service constructs one
        # from separately validated brand and last-four metadata.
        display_label="TESTCARD 4242",
    )


def _finalize(client, key, reference, replacement_id=None):
    body = {"registration_reference": reference}
    if replacement_id is not None:
        body["replacement_payment_method_id"] = str(replacement_id)
    return client.post(
        "/v1/customer/payment-methods/registration/finalize",
        headers=_headers(key),
        json=body,
    )


def _register(client, provider, key, suffix, replacement_id=None):
    initiated = _initiate(client, key, replacement_id)
    assert initiated.status_code == 200
    reference = initiated.json()["registration_reference"]
    _success_result(provider, reference, suffix)
    return _finalize(client, key, reference, replacement_id)


def test_successful_own_name_registration_advances_only_to_trial_confirmation(
    payment_api, session
):
    client, provider, account, _ = payment_api
    response = _register(client, provider, "payment-success", "success")

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding"] == {
        "next_required_stage": "trial_start_confirmation_required"
    }
    assert body["payment_method"] == {
        "payment_method_id": body["payment_method"]["payment_method_id"],
        "provider": "fake_pg",
        "brand": "TESTCARD",
        "last4": "4242",
        "display_label": "TESTCARD •••• 4242",
        "status": "active",
        "is_default": True,
        "own_name_verified": True,
    }

    method = session.query(PaymentMethod).one()
    assert method.account_id == account.id
    assert method.billing_key_reference == "bk-server-only-success"
    assert session.query(Subscription).count() == 0
    assert session.query(BillingAttempt).count() == 0
    assert client.get("/v1/customer/onboarding/status").json() == {
        "next_required_stage": "trial_start_confirmation_required"
    }


def test_provider_verification_failure_creates_no_usable_method(payment_api, session):
    client, provider, _, _ = payment_api
    initiated = _initiate(client, "payment-failed")
    reference = initiated.json()["registration_reference"]
    provider.results[reference] = PaymentRegistrationResult(
        provider=provider.name,
        registration_reference=reference,
        status=PaymentRegistrationStatus.FAILED.value,
        billing_key_reference="bk-must-not-persist",
        own_name_verified=False,
    )

    response = _finalize(client, "payment-failed", reference)

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "PAYMENT_METHOD_VERIFICATION_FAILED"}
    }
    assert session.query(PaymentMethod).count() == 0
    assert "bk-must-not-persist" not in response.text


def test_redirect_or_callback_without_provider_success_is_not_registration(
    payment_api, session
):
    client, provider, _, _ = payment_api

    direct = _finalize(client, "never-initiated", "browser-only-reference")
    assert direct.status_code == 404
    assert provider.verify_calls == 0

    initiated = _initiate(client, "provider-pending")
    pending = _finalize(
        client, "provider-pending", initiated.json()["registration_reference"]
    )
    assert pending.status_code == 409
    assert pending.json() == {"error": {"code": "PROVIDER_STATE_UNKNOWN"}}
    assert session.query(PaymentMethod).count() == 0


def test_initiation_and_finalization_are_idempotent(payment_api, session):
    client, provider, _, _ = payment_api
    first = _initiate(client, "payment-idempotent")
    second = _initiate(client, "payment-idempotent")

    assert first.status_code == second.status_code == 200
    assert first.json()["registration_reference"] == second.json()[
        "registration_reference"
    ]
    assert second.json()["replayed"] is True
    assert provider.start_calls == 1

    reference = first.json()["registration_reference"]
    _success_result(provider, reference, "idempotent")
    completed = _finalize(client, "payment-idempotent", reference)
    replayed = _finalize(client, "payment-idempotent", reference)

    assert completed.status_code == replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    assert completed.json()["payment_method"]["payment_method_id"] == replayed.json()[
        "payment_method"
    ]["payment_method_id"]
    assert session.query(PaymentMethod).count() == 1
    assert session.query(CommandIdempotency).one().status == "completed"
    assert session.query(AuditEvent).filter_by(event_type="payment_method.registered").count() == 1


def test_replacement_adds_before_switching_one_deterministic_default(
    payment_api, session
):
    client, provider, account, _ = payment_api
    first_response = _register(client, provider, "payment-first", "first")
    first_id = uuid.UUID(first_response.json()["payment_method"]["payment_method_id"])

    replacement = _register(
        client,
        provider,
        "payment-replacement",
        "replacement",
        replacement_id=first_id,
    )

    assert replacement.status_code == 200
    replacement_id = uuid.UUID(replacement.json()["payment_method"]["payment_method_id"])
    methods = session.query(PaymentMethod).filter_by(account_id=account.id).all()
    assert len(methods) == 2
    assert all(method.status == "active" for method in methods)
    assert sum(method.is_default for method in methods) == 1
    assert session.get(PaymentMethod, first_id).is_default is False
    assert session.get(PaymentMethod, replacement_id).is_default is True
    current = client.get("/v1/customer/payment-methods/default")
    assert current.status_code == 200
    assert current.json()["payment_method"]["payment_method_id"] == str(replacement_id)


def test_wrong_account_replacement_target_is_blocked_before_provider_call(
    payment_api, session
):
    client, provider, _, _ = payment_api
    other = make_account(session, email="other-payment-owner@example.com")
    other_method = make_payment_method(session, other)

    response = _initiate(client, "wrong-account", other_method.id)

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "PAYMENT_METHOD_NOT_FOUND"}}
    assert provider.start_calls == 0


@pytest.mark.parametrize("mode", ["stale", "weak"])
def test_payment_registration_requires_fresh_strong_auth(
    payment_api, session, clock, mode
):
    client, provider, _, created = payment_api
    row = session.get(BrowserSession, created.session_id)
    if mode == "stale":
        row.last_fresh_auth_at = clock.now() - auth_policy.FRESH_AUTH_WINDOW
    else:
        row.fresh_auth_assurance = AuthAssuranceLevel.RECENT_VERIFICATION.value
    session.flush()

    response = _initiate(client, "fresh-auth-{0}".format(mode))

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "STEP_UP_REQUIRED"}}
    assert provider.start_calls == 0


def test_payment_routes_require_customer_authentication_and_same_site_origin(
    payment_api
):
    client, provider, _, _ = payment_api
    no_origin = client.post(
        "/v1/customer/payment-methods/registration",
        headers={"Idempotency-Key": "missing-origin"},
        json={},
    )
    assert no_origin.status_code == 403
    assert no_origin.json() == {"error": {"code": "REQUEST_ORIGIN_REJECTED"}}
    assert provider.start_calls == 0

    client.cookies.clear()
    anonymous_read = client.get("/v1/customer/payment-methods/default")
    anonymous_write = _initiate(client, "anonymous-payment")
    assert anonymous_read.status_code == 401
    assert anonymous_write.status_code == 401
    assert provider.start_calls == 0


def test_unverified_person_cannot_register_payment_method(payment_api, session):
    client, provider, account, _ = payment_api
    account.person.adult_verified = False
    account.person.adult_verified_at = None
    session.flush()

    response = _initiate(client, "unverified-person")

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "IDV_FAILED"}}
    assert provider.start_calls == 0


def test_card_secrets_are_rejected_at_transport_and_absent_from_contract(
    payment_api, session
):
    client, provider, _, _ = payment_api
    response = client.post(
        "/v1/customer/payment-methods/registration",
        headers=_headers("raw-card-input"),
        json={
            "card_number": "4111111111111111",
            "cvv": "123",
            "card_password": "00",
        },
    )

    assert response.status_code == 422
    assert provider.start_calls == 0
    assert session.query(PaymentMethod).count() == 0
    provider_fields = set(PaymentRegistrationResult.__dataclass_fields__)
    assert not provider_fields.intersection(
        {"pan", "card_number", "cvv", "cvc", "card_password", "raw_payload"}
    )
    service_source = inspect.getsource(
        __import__(
            "customer.services.payment_method_service", fromlist=["PaymentMethodService"]
        )
    ).lower()
    assert "card_number" not in service_source
    assert "cvv" not in service_source
    assert "card_password" not in service_source


@pytest.mark.parametrize(
    "billing_key,brand",
    [
        ("4111111111111111", "TESTCARD"),
        ("bk-safe-reference", "4111 1111 1111 1111"),
    ],
)
def test_provider_metadata_that_resembles_pan_fails_closed(
    payment_api, session, billing_key, brand
):
    client, provider, _, _ = payment_api
    key = "provider-pan-{0}".format(uuid.uuid4().hex)
    initiated = _initiate(client, key)
    reference = initiated.json()["registration_reference"]
    provider.results[reference] = PaymentRegistrationResult(
        provider=provider.name,
        registration_reference=reference,
        status=PaymentRegistrationStatus.SUCCEEDED.value,
        billing_key_reference=billing_key,
        own_name_verified=True,
        own_name_verification_reference="own-name-safe-reference",
        card_brand=brand,
        card_last4="1111",
    )

    response = _finalize(client, key, reference)

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "PROVIDER_STATE_UNKNOWN"}}
    assert session.query(PaymentMethod).count() == 0


def test_billing_key_and_provider_proof_never_leak_to_response_log_or_audit(
    payment_api, session, caplog
):
    client, provider, _, _ = payment_api
    response = _register(client, provider, "no-token-leak", "ultra-secret")

    assert response.status_code == 200
    serialized = response.text + "\n" + caplog.text
    assert "bk-server-only-ultra-secret" not in serialized
    assert "own-name-proof-ultra-secret" not in serialized
    event = session.query(AuditEvent).filter_by(event_type="payment_method.registered").one()
    assert "bk-server-only-ultra-secret" not in str(event.payload)
    assert "own-name-proof-ultra-secret" not in str(event.payload)
    assert event.payload == {"provider": "fake_pg", "replacement": False}


def test_provider_exception_is_sanitized_and_creates_no_state(
    payment_api, session, caplog
):
    client, provider, _, _ = payment_api
    provider.start_exception = RuntimeError("provider leaked bk-do-not-expose")

    response = _initiate(client, "provider-exception")

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "PAYMENT_PROVIDER_UNAVAILABLE"}}
    assert "bk-do-not-expose" not in response.text
    assert "bk-do-not-expose" not in caplog.text
    assert session.query(PaymentMethod).count() == 0
    assert session.query(CommandIdempotency).count() == 0


def test_idempotency_key_cannot_be_reused_for_different_replacement(
    payment_api, session
):
    client, _, account, _ = payment_api
    old = make_payment_method(session, account)
    assert _initiate(client, "conflicting-key").status_code == 200

    conflict = _initiate(client, "conflicting-key", old.id)

    assert conflict.status_code == 409
    assert conflict.json() == {"error": {"code": "IDEMPOTENCY_KEY_CONFLICT"}}


def test_payment_routes_remain_customer_only_and_production_unmounted():
    app = create_customer_test_app()
    paths = {route.path for route in app.routes}
    assert "/v1/customer/payment-methods/registration" in paths
    assert not any(path.startswith("/admin") or path.startswith("/internal") for path in paths)

    import main

    production_paths = {getattr(route, "path", "") for route in main.app.routes}
    assert not any(path.startswith("/v1/customer") for path in production_paths)
