"""Transport tests for the unmounted customer onboarding API.

These use the same isolated PostgreSQL fixture as the Phase 1/2 persistence
tests.  No production ``main.py``, real IDV, SMTP, SMS, or browser database
access is involved.
"""

import datetime as dt
import ast
import importlib
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
    get_identity_provider,
    get_verification_code_sender,
)
from customer.api.router import create_customer_test_app  # noqa: E402
from customer.domain import auth_policy  # noqa: E402
from customer.domain.clock import FixedClock, UTC  # noqa: E402
from customer.domain.enums import AuthAssuranceLevel, AuthChallengeStatus  # noqa: E402
from customer.persistence.models import (  # noqa: E402
    AuditEvent,
    AuthChallenge,
    BrowserSession,
    CustomerAccount,
    DeliveryEmail,
    IdentityVerification,
    PersonIdentity,
    Subscription,
)
from customer.services import audit_service as audit_events  # noqa: E402
from customer.services.providers import IdentityVerificationResult  # noqa: E402
from customer.services.session_service import SessionService  # noqa: E402
from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db

__all__ = ["customer_engine", "session"]


class FakeIdentityProvider:
    name = "fake_test_idv"

    def __init__(self):
        self._counter = 0
        self.results = {}

    def start(self, purpose, reference_hint=None):
        del purpose, reference_hint
        self._counter += 1
        return "test-idv-{0}".format(self._counter)

    def result(self, provider_reference):
        return self.results[provider_reference]


class CapturingSender:
    """Test-only port: codes remain in process and never reach responses/logs."""

    def __init__(self):
        self.codes = {}

    def send(self, channel, target, code):
        self.codes[(channel, target)] = code


@pytest.fixture()
def clock():
    return FixedClock(dt.datetime(2026, 8, 13, 9, 0, tzinfo=UTC))


@pytest.fixture()
def api(session, clock):
    provider = FakeIdentityProvider()
    sender = CapturingSender()
    app = create_customer_test_app()
    def transactional_test_session():
        """Mirror the production dependency's commit/rollback boundary."""
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
    app.dependency_overrides[get_identity_provider] = lambda: provider
    app.dependency_overrides[get_verification_code_sender] = lambda: sender
    app.dependency_overrides[get_customer_api_security_config] = lambda: CustomerApiSecurityConfig(
        cookie_secure=True,
        allowed_state_changing_origins=frozenset({"https://testserver"}),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client, provider, sender


def _idv_result(*, stable_key, adult=True, mobile="+821012345678"):
    return IdentityVerificationResult(
        provider="fake_test_idv",
        provider_reference="provider-ref-{0}".format(uuid.uuid4().hex),
        adult_verified=adult,
        stable_key=stable_key if adult else None,
        mobile_e164=mobile,
    )


def _complete_idv(client, provider, *, stable_key="DI-api-1", adult=True):
    started = client.post("/v1/customer/identity/start", json={})
    assert started.status_code == 200
    reference = started.json()["verification_reference"]
    provider.results[reference] = _idv_result(stable_key=stable_key, adult=adult)
    return client.post(
        "/v1/customer/identity/complete",
        json={"verification_reference": reference},
    )


def _start_signup(client, provider, *, stable_key="DI-api-1", adult=True):
    completed = _complete_idv(client, provider, stable_key=stable_key, adult=adult)
    assert completed.status_code == 200
    return completed.json()["verification_id"]


def _issue_signup_challenge(client, sender, verification_id, email):
    response = client.post(
        "/v1/customer/auth/signup/email-challenge",
        json={"verification_id": verification_id, "account_email": email},
    )
    assert response.status_code == 200
    return response.json()["challenge_id"], sender.codes[("email", email)]


def _complete_signup_request(client, verification_id, email, challenge_id, code, **extra):
    payload = {
        "verification_id": verification_id,
        "account_email": email,
        "challenge_id": challenge_id,
        "code": code,
    }
    payload.update(extra)
    return client.post("/v1/customer/auth/signup/complete", json=payload)


def _assert_response_has_no_secret_material(response, *secret_values):
    serialized = response.text.lower()
    forbidden_keys = (
        "idv_stable_key",
        "code_hash",
        "code_salt",
        "session_token_hash",
        "password_hash",
        "audit_event",
        "raw_payload",
        "billing_key",
        "card_last4",
    )
    for key in forbidden_keys:
        assert key not in serialized
    for value in secret_values:
        if value:
            assert str(value).lower() not in serialized


def _signup(
    client,
    provider,
    sender,
    *,
    stable_key="DI-api-signup",
    email="signup@example.com",
    remember_login=False
):
    verification_id = _start_signup(client, provider, stable_key=stable_key)
    challenge_id, code = _issue_signup_challenge(
        client, sender, verification_id, email
    )
    return _complete_signup_request(
        client,
        verification_id,
        email,
        challenge_id,
        code,
        remember_login=remember_login,
    )


def _issue_login_challenge(client, sender, *, channel, target):
    response = client.post(
        "/v1/customer/auth/login/challenge",
        json={"channel": channel, "target": target},
    )
    assert response.status_code == 200
    return response.json()["challenge_id"], sender.codes[(channel, target)]


def _session_cookie(client):
    return client.cookies.get("__Host-genie_customer_session")


def test_router_is_importable_and_exposes_only_customer_namespace():
    app = create_customer_test_app()
    paths = {route.path for route in app.routes}
    assert "/v1/customer/account/me" in paths
    assert not any(path.startswith("/admin") or path.startswith("/internal") for path in paths)
    assert not any("password" in path for path in paths)


def test_route_inventory_is_exact_and_contains_no_operator_surface():
    app = create_customer_test_app()
    actual = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/v1/customer")
    }
    expected = {
        ("POST", "/v1/customer/identity/start"),
        ("POST", "/v1/customer/identity/complete"),
        ("POST", "/v1/customer/auth/signup/email-challenge"),
        ("POST", "/v1/customer/auth/signup/complete"),
        ("POST", "/v1/customer/auth/login/challenge"),
        ("POST", "/v1/customer/auth/login/verify"),
        ("POST", "/v1/customer/auth/logout"),
        ("POST", "/v1/customer/auth/logout-all"),
        ("GET", "/v1/customer/account/me"),
        ("GET", "/v1/customer/sessions"),
        ("DELETE", "/v1/customer/sessions/{session_id}"),
        ("GET", "/v1/customer/onboarding/status"),
        ("POST", "/v1/customer/payment-methods/registration"),
        ("POST", "/v1/customer/payment-methods/registration/finalize"),
        ("GET", "/v1/customer/payment-methods/default"),
        ("POST", "/v1/customer/trial/start"),
        ("GET", "/v1/customer/trial"),
    }
    assert actual == expected
    forbidden = ("/admin", "/internal", "owner-review", "approve", "send-now")
    assert not any(any(item in path.lower() for item in forbidden) for _, path in actual)


def test_identity_start_projects_identity_verification_required(api):
    client, _, _ = api
    response = client.post("/v1/customer/identity/start", json={})
    assert response.status_code == 200
    assert response.json()["onboarding"] == {
        "next_required_stage": "identity_verification_required"
    }


def test_eligible_signup_completes_only_stages_one_and_two(api, session):
    client, provider, sender = api
    response = _signup(client, provider, sender)

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding"]["next_required_stage"] == "payment_method_registration_required"
    assert "plan" not in str(body).lower()
    assert "price" not in str(body).lower()
    _assert_response_has_no_secret_material(response, "DI-api-signup")

    account = client.get("/v1/customer/account/me")
    assert account.status_code == 200
    assert account.json()["account"]["mobile_display"] == "+821***5678"
    assert client.get("/v1/customer/onboarding/status").json() == {
        "next_required_stage": "payment_method_registration_required"
    }
    assert "code" not in AuthChallenge.__table__.columns.keys()
    assert session.query(Subscription).count() == 0


def test_underage_idv_returns_canonical_error_and_creates_no_account(api, session):
    client, provider, _ = api
    response = _complete_idv(client, provider, stable_key="DI-minor", adult=False)

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "AGE_NOT_ELIGIBLE"}}
    assert session.query(CustomerAccount).count() == 0
    assert session.query(BrowserSession).count() == 0
    assert session.query(Subscription).count() == 0
    assert "DI-minor" not in response.text


def test_failed_or_unverified_identity_cannot_issue_signup_challenge(api, session):
    client, provider, sender = api
    started = client.post("/v1/customer/identity/start", json={}).json()
    provider.results[started["verification_reference"]] = IdentityVerificationResult(
        provider="fake_test_idv",
        provider_reference="failed-provider-reference",
        adult_verified=None,
        stable_key=None,
        failed=True,
    )
    completed = client.post(
        "/v1/customer/identity/complete",
        json={"verification_reference": started["verification_reference"]},
    )
    assert completed.status_code == 422

    verification = session.query(IdentityVerification).one()
    challenged = client.post(
        "/v1/customer/auth/signup/email-challenge",
        json={
            "verification_id": str(verification.id),
            "account_email": "blocked@example.com",
        },
    )
    assert challenged.status_code == 400
    assert challenged.json()["error"]["code"] == "IDV_FAILED"
    assert sender.codes == {}
    assert session.query(CustomerAccount).count() == 0


def test_duplicate_identity_returns_recovery_outcome_without_second_account(api, session):
    client, provider, sender = api
    first = _signup(client, provider, sender, stable_key="DI-duplicate", email="one@example.com")
    assert first.status_code == 200

    second = _signup(client, provider, sender, stable_key="DI-duplicate", email="two@example.com")
    assert second.status_code == 200
    assert second.json() == {"outcome": "existing_account_recovery_required"}
    assert session.query(BrowserSession).count() == 1
    assert session.query(CustomerAccount).count() == 1


def test_same_mobile_does_not_merge_two_distinct_verified_people(api, session):
    client, provider, sender = api
    first = _signup(
        client, provider, sender, stable_key="DI-contact-a", email="a@example.com"
    )
    second = _signup(
        client, provider, sender, stable_key="DI-contact-b", email="b@example.com"
    )
    assert first.status_code == second.status_code == 200
    accounts = session.query(CustomerAccount).order_by(CustomerAccount.account_email).all()
    assert len(accounts) == 2
    assert accounts[0].mobile_e164 == accounts[1].mobile_e164 == "+821012345678"
    assert accounts[0].person_id != accounts[1].person_id
    assert session.query(PersonIdentity).count() == 2


@pytest.mark.parametrize("failure", ["invalid", "expired", "replayed"])
def test_signup_email_challenge_rejects_invalid_expired_and_replayed_codes(
    api, session, clock, failure
):
    client, provider, sender = api
    email = "signup-{0}@example.com".format(failure)
    verification_id = _start_signup(
        client, provider, stable_key="DI-signup-{0}".format(failure)
    )
    challenge_id, code = _issue_signup_challenge(
        client, sender, verification_id, email
    )
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    assert challenge.code_hash != code and challenge.code_salt != code

    if failure == "invalid":
        response = _complete_signup_request(
            client, verification_id, email, challenge_id, "0000000"
        )
    elif failure == "expired":
        clock.advance(auth_policy.CHALLENGE_TTL)
        response = _complete_signup_request(
            client, verification_id, email, challenge_id, code
        )
    else:
        first = _complete_signup_request(
            client, verification_id, email, challenge_id, code
        )
        assert first.status_code == 200
        response = _complete_signup_request(
            client, verification_id, email, challenge_id, code
        )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "LOGIN_CHALLENGE_INVALID"}}
    _assert_response_has_no_secret_material(response, code, challenge.code_hash, challenge.code_salt)
    expected_accounts = 1 if failure == "replayed" else 0
    assert session.query(CustomerAccount).count() == expected_accounts


def test_signup_binds_verified_email_and_materializes_delivery_evidence(
    api, session
):
    client, provider, sender = api
    verification_id = _start_signup(
        client, provider, stable_key="DI-email-evidence"
    )
    requested_email = "  Verified.Owner@Example.COM  "
    normalized_email = "verified.owner@example.com"
    issued = client.post(
        "/v1/customer/auth/signup/email-challenge",
        json={
            "verification_id": verification_id,
            "account_email": requested_email,
        },
    )
    assert issued.status_code == 200
    challenge_id = issued.json()["challenge_id"]
    code = sender.codes[("email", normalized_email)]

    response = _complete_signup_request(
        client,
        verification_id,
        " VERIFIED.OWNER@example.com ",
        challenge_id,
        code,
    )

    assert response.status_code == 200
    account = session.query(CustomerAccount).one()
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    delivery_email = session.query(DeliveryEmail).one()
    assert account.account_email == normalized_email
    assert challenge.target == normalized_email
    assert challenge.status == AuthChallengeStatus.CONSUMED.value
    assert challenge.account_id == account.id
    assert challenge.verified_at is not None
    assert challenge.consumed_at == challenge.verified_at
    assert delivery_email.account_id == account.id
    assert delivery_email.email == normalized_email
    assert delivery_email.status == "active"
    assert delivery_email.verified_at == challenge.verified_at


def test_signup_email_target_mismatch_is_blocked_without_partial_customer_state(
    api, session, caplog
):
    client, provider, sender = api
    verification_id = _start_signup(
        client, provider, stable_key="DI-email-mismatch"
    )
    verified_email = "verified-a@example.com"
    challenge_id, code = _issue_signup_challenge(
        client, sender, verification_id, verified_email
    )

    response = _complete_signup_request(
        client,
        verification_id,
        "unverified-b@example.com",
        challenge_id,
        code,
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "LOGIN_CHALLENGE_INVALID"}}
    _assert_response_has_no_secret_material(response, code, verified_email)
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    assert challenge.status == AuthChallengeStatus.PENDING.value
    assert challenge.verified_at is None
    assert challenge.consumed_at is None
    assert challenge.account_id is None
    assert session.query(AuditEvent).filter_by(
        event_type=audit_events.AUTH_CHALLENGE_VERIFIED
    ).count() == 0
    assert code not in caplog.text
    assert verified_email not in caplog.text
    assert "unverified-b@example.com" not in caplog.text
    assert all(
        verified_email not in str(event.payload)
        and "unverified-b@example.com" not in str(event.payload)
        for event in session.query(AuditEvent).all()
    )
    assert session.query(PersonIdentity).count() == 0
    assert session.query(CustomerAccount).count() == 0
    assert session.query(DeliveryEmail).count() == 0


def test_login_is_enumeration_safe_and_issues_secure_server_session_cookie(api):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="login@example.com").status_code == 200
    assert client.post("/v1/customer/auth/logout", headers={"Origin": "https://testserver"}).status_code == 200

    known = client.post(
        "/v1/customer/auth/login/challenge",
        json={"channel": "email", "target": "login@example.com"},
    )
    unknown = client.post(
        "/v1/customer/auth/login/challenge",
        json={"channel": "email", "target": "unknown@example.com"},
    )
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json()) == {"accepted", "challenge_id"}

    verified = client.post(
        "/v1/customer/auth/login/verify",
        json={
            "channel": "email",
            "target": "login@example.com",
            "challenge_id": known.json()["challenge_id"],
            "code": sender.codes[("email", "login@example.com")],
        },
    )
    assert verified.status_code == 200
    cookie = verified.headers["set-cookie"].lower()
    assert "__host-genie_customer_session=" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "max-age" not in cookie
    assert "token" not in verified.text.lower()


def test_email_and_mobile_login_challenge_initiation_is_enumeration_resistant(api):
    client, provider, sender = api
    assert _signup(
        client, provider, sender, email="known@example.com"
    ).status_code == 200

    requests = (
        ("email", "known@example.com"),
        ("email", "unknown@example.com"),
        ("sms", "+821012345678"),
        ("sms", "+821099999999"),
    )
    public = []
    for channel, target in requests:
        response = client.post(
            "/v1/customer/auth/login/challenge",
            json={"channel": channel, "target": target},
        )
        public.append((response.status_code, set(response.json()), response.json()["accepted"]))
    assert public == [(200, {"accepted", "challenge_id"}, True)] * 4


@pytest.mark.parametrize("failure", ["bad_code", "expired", "replayed", "attempt_limit"])
def test_login_rejects_bad_expired_consumed_and_attempt_limited_challenges(
    api, session, clock, failure
):
    client, provider, sender = api
    email = "login-failure@example.com"
    assert _signup(client, provider, sender, email=email).status_code == 200
    challenge_id, code = _issue_login_challenge(
        client, sender, channel="email", target=email
    )
    payload = {
        "channel": "email",
        "target": email,
        "challenge_id": challenge_id,
        "code": code,
    }

    if failure == "bad_code":
        payload["code"] = "0000000"
        response = client.post("/v1/customer/auth/login/verify", json=payload)
    elif failure == "expired":
        clock.advance(auth_policy.CHALLENGE_TTL)
        response = client.post("/v1/customer/auth/login/verify", json=payload)
    elif failure == "replayed":
        assert client.post("/v1/customer/auth/login/verify", json=payload).status_code == 200
        response = client.post("/v1/customer/auth/login/verify", json=payload)
    else:
        payload["code"] = "0000000"
        responses = [
            client.post("/v1/customer/auth/login/verify", json=payload)
            for _ in range(auth_policy.CHALLENGE_MAX_ATTEMPTS)
        ]
        response = responses[-1]
        challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
        assert challenge.status == AuthChallengeStatus.LOCKED.value

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "LOGIN_CHALLENGE_INVALID"}}
    _assert_response_has_no_secret_material(response, code)


def test_registered_mobile_login_uses_routine_sms_challenge_not_full_idv(api):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="sms@example.com").status_code == 200
    assert client.post("/v1/customer/auth/logout", headers={"Origin": "https://testserver"}).status_code == 200

    issued = client.post(
        "/v1/customer/auth/login/challenge",
        json={"channel": "sms", "target": "+821012345678"},
    )
    assert issued.status_code == 200
    verified = client.post(
        "/v1/customer/auth/login/verify",
        json={
            "channel": "sms",
            "target": "+821012345678",
            "challenge_id": issued.json()["challenge_id"],
            "code": sender.codes[("sms", "+821012345678")],
            "remember_login": True,
        },
    )
    assert verified.status_code == 200
    assert "max-age=2592000" in verified.headers["set-cookie"].lower()


@pytest.mark.parametrize(
    "remember,expected_max_age",
    [(False, None), (True, 30 * 24 * 60 * 60)],
)
def test_cookie_attributes_and_persistence_match_session_policy(
    api, session, remember, expected_max_age
):
    client, provider, sender = api
    response = _signup(
        client,
        provider,
        sender,
        email="cookie@example.com",
        remember_login=remember,
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    lowered = cookie.lower()
    assert cookie.startswith("__Host-genie_customer_session=")
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "domain=" not in lowered
    if expected_max_age is None:
        assert "max-age=" not in lowered and "expires=" not in lowered
    else:
        assert "max-age={0}".format(expected_max_age) in lowered
        row = session.query(BrowserSession).one()
        assert int((row.absolute_expires_at - row.created_at).total_seconds()) == expected_max_age


@pytest.mark.parametrize(
    "state,error_code",
    [
        ("revoked", "SESSION_REVOKED"),
        ("absolute_expired", "SESSION_EXPIRED"),
        ("inactivity_expired", "SESSION_EXPIRED"),
    ],
)
def test_server_authoritative_session_state_rejects_revoked_and_expired_cookies(
    api, session, clock, state, error_code
):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="state@example.com").status_code == 200
    row = session.query(BrowserSession).one()
    if state == "revoked":
        SessionService(session, clock).revoke_session(row.id)
    elif state == "absolute_expired":
        row.absolute_expires_at = clock.now()
        row.inactivity_expires_at = clock.now()
        session.flush()
    else:
        row.inactivity_expires_at = clock.now()
        session.flush()

    response = client.get("/v1/customer/account/me")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": error_code}}


def test_no_cookie_and_forged_identifiers_do_not_authenticate(api):
    client, provider, sender = api
    response = _signup(client, provider, sender, email="authn@example.com")
    account_id = response.json()["account"]["account_id"]
    session_id = response.json()["session"]["session_id"]
    client.cookies.clear()
    missing = client.get("/v1/customer/account/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    for forged in (account_id, session_id, str(uuid.uuid4())):
        forged_response = client.get(
            "/v1/customer/account/me",
            headers={"Cookie": "__Host-genie_customer_session={0}".format(forged)},
        )
        assert forged_response.status_code == 401
        assert forged_response.json()["error"]["code"] == "SESSION_INVALID"


def test_mobile_login_and_session_management_enforce_ownership_csrf_and_fresh_auth(
    api, session, clock
):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="mobile@example.com").status_code == 200
    other = make_account(session, email="other@example.com")
    other_session = SessionService(session, clock).create_browser_session(account_id=other.id)

    listed = client.get("/v1/customer/sessions")
    assert listed.status_code == 200 and len(listed.json()["sessions"]) == 1
    cross = client.delete(
        "/v1/customer/sessions/{0}".format(other_session.session_id),
        headers={"Origin": "https://testserver"},
    )
    assert cross.status_code == 404
    assert session.get(BrowserSession, other_session.session_id).revoked_at is None

    csrf_rejected = client.post("/v1/customer/auth/logout")
    assert csrf_rejected.status_code == 403
    assert csrf_rejected.json()["error"]["code"] == "REQUEST_ORIGIN_REJECTED"

    clock.advance(dt.timedelta(minutes=11))
    stale = client.post("/v1/customer/auth/logout-all", headers={"Origin": "https://testserver"})
    assert stale.status_code == 403
    assert stale.json()["error"]["code"] == "STEP_UP_REQUIRED"


def test_revoked_and_expired_sessions_do_not_authenticate(api, session, clock):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="expired@example.com").status_code == 200
    assert client.post("/v1/customer/auth/logout", headers={"Origin": "https://testserver"}).status_code == 200
    assert client.get("/v1/customer/account/me").status_code == 401


def test_session_list_is_account_scoped_supports_multiple_sessions_and_leaks_no_secret(
    api, session, clock
):
    client, provider, sender = api
    signup = _signup(client, provider, sender, email="sessions@example.com")
    account_id = uuid.UUID(signup.json()["account"]["account_id"])
    second = SessionService(session, clock).create_browser_session(
        account_id=account_id, user_agent_summary="second-device"
    )
    other = make_account(session, email="session-other@example.com")
    other_created = SessionService(session, clock).create_browser_session(
        account_id=other.id
    )

    response = client.get("/v1/customer/sessions")
    assert response.status_code == 200
    body = response.json()
    assert len(body["sessions"]) == 2
    assert {item["session_id"] for item in body["sessions"]} == {
        signup.json()["session"]["session_id"],
        str(second.session_id),
    }
    _assert_response_has_no_secret_material(
        response, second.token, other_created.token
    )
    assert "token" not in response.text.lower()
    assert "hash" not in response.text.lower()


def test_revoke_own_session_immediately_blocks_that_cookie(api, session, clock):
    client, provider, sender = api
    signup = _signup(client, provider, sender, email="revoke-own@example.com")
    account_id = uuid.UUID(signup.json()["account"]["account_id"])
    second = SessionService(session, clock).create_browser_session(account_id=account_id)

    revoked = client.delete(
        "/v1/customer/sessions/{0}".format(second.session_id),
        headers={"Origin": "https://testserver"},
    )
    assert revoked.status_code == 200
    assert session.get(BrowserSession, second.session_id).revoked_at is not None

    with TestClient(client.app, base_url="https://testserver") as second_client:
        denied = second_client.get(
            "/v1/customer/account/me",
            headers={
                "Cookie": "__Host-genie_customer_session={0}".format(second.token)
            },
        )
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "SESSION_REVOKED"


def test_logout_revokes_server_session_and_clears_cookie(api, session):
    client, provider, sender = api
    signup = _signup(client, provider, sender, email="logout@example.com")
    session_id = uuid.UUID(signup.json()["session"]["session_id"])
    response = client.post(
        "/v1/customer/auth/logout", headers={"Origin": "https://testserver"}
    )
    assert response.status_code == 200
    assert session.get(BrowserSession, session_id).revoked_at is not None
    cookie = response.headers["set-cookie"].lower()
    assert "__host-genie_customer_session=" in cookie
    assert "max-age=0" in cookie


def test_logout_all_revokes_only_current_accounts_sessions(api, session, clock):
    client, provider, sender = api
    signup = _signup(client, provider, sender, email="logout-all@example.com")
    account_id = uuid.UUID(signup.json()["account"]["account_id"])
    second = SessionService(session, clock).create_browser_session(account_id=account_id)
    other = make_account(session, email="logout-all-other@example.com")
    other_session = SessionService(session, clock).create_browser_session(
        account_id=other.id
    )

    response = client.post(
        "/v1/customer/auth/logout-all",
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    assert response.json()["revoked_count"] == 2
    own_rows = session.query(BrowserSession).filter_by(account_id=account_id).all()
    assert all(row.revoked_at is not None for row in own_rows)
    assert session.get(BrowserSession, second.session_id).revoked_at is not None
    assert session.get(BrowserSession, other_session.session_id).revoked_at is None


def test_remembered_session_is_not_fresh_without_recent_assurance(api, session):
    client, provider, sender = api
    assert _signup(
        client,
        provider,
        sender,
        email="remembered@example.com",
        remember_login=True,
    ).status_code == 200
    row = session.query(BrowserSession).one()
    assert row.remember_login is True
    row.last_fresh_auth_at = None
    row.fresh_auth_assurance = None
    session.flush()

    response = client.post(
        "/v1/customer/auth/logout-all",
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STEP_UP_REQUIRED"
    assert row.revoked_at is None


def test_strong_fresh_auth_passes_within_ten_minutes_and_expires_at_boundary(
    api, session, clock
):
    client, provider, sender = api
    assert _signup(
        client, provider, sender, email="fresh@example.com", remember_login=True
    ).status_code == 200
    row = session.query(BrowserSession).one()
    service = SessionService(session, clock)
    service.record_fresh_auth(
        row, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    assert service.is_fresh(
        row, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    clock.advance(auth_policy.FRESH_AUTH_WINDOW)
    assert not service.is_fresh(
        row, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    response = client.post(
        "/v1/customer/auth/logout-all",
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "STEP_UP_REQUIRED"


def test_strong_fresh_auth_allows_sensitive_api_within_window(api, session, clock):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="fresh-pass@example.com").status_code == 200
    row = session.query(BrowserSession).one()
    SessionService(session, clock).record_fresh_auth(
        row, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    clock.advance(dt.timedelta(minutes=9, seconds=59))
    response = client.post(
        "/v1/customer/auth/logout-all",
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null", "not-an-origin"])
def test_csrf_rejects_missing_foreign_and_malformed_origins(api, origin):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="csrf@example.com").status_code == 200
    headers = {} if origin is None else {"Origin": origin}
    response = client.post("/v1/customer/auth/logout", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REQUEST_ORIGIN_REJECTED"


def test_csrf_allows_configured_origin_and_does_not_burden_read_only_get(api):
    client, provider, sender = api
    assert _signup(client, provider, sender, email="csrf-positive@example.com").status_code == 200
    assert client.get("/v1/customer/account/me").status_code == 200
    allowed = client.post(
        "/v1/customer/auth/logout", headers={"Origin": "https://testserver"}
    )
    assert allowed.status_code == 200


def test_cors_is_closed_and_never_returns_credentialed_wildcard(api):
    client, _, _ = api
    response = client.options(
        "/v1/customer/account/me",
        headers={
            "Origin": "https://foreign.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "*"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_serialized_identity_auth_account_and_session_responses_leak_no_secret(api, session):
    client, provider, sender = api
    stable_key = "DI-never-serialize"
    verification_id = _start_signup(client, provider, stable_key=stable_key)
    email = "leak-audit@example.com"
    challenge_id, code = _issue_signup_challenge(
        client, sender, verification_id, email
    )
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    responses = [
        _complete_signup_request(
            client, verification_id, email, challenge_id, code
        ),
        client.get("/v1/customer/account/me"),
        client.get("/v1/customer/onboarding/status"),
        client.get("/v1/customer/sessions"),
    ]
    browser_session = session.query(BrowserSession).one()
    for response in responses:
        assert response.status_code == 200
        _assert_response_has_no_secret_material(
            response,
            stable_key,
            code,
            challenge.code_hash,
            challenge.code_salt,
            browser_session.session_token_hash,
        )
    assert "raw_payload" not in IdentityVerificationResult.__dataclass_fields__
    assert "password" not in " ".join(response.text.lower() for response in responses)


def test_customer_dependency_graph_and_context_have_no_operator_authority():
    modules = [
        importlib.import_module("customer.api.router"),
        importlib.import_module("customer.api.dependencies"),
        importlib.import_module("customer.services.login_service"),
        importlib.import_module("customer.services.onboarding_service"),
        importlib.import_module("customer.services.payment_method_service"),
        importlib.import_module("customer.services.payment_providers"),
    ]
    imported_modules = set()
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
    protected = {
        "main",
        "internal_jobs",
        "admin_routes",
        "admin_store",
        "orchestrator",
        "email_sender",
    }
    assert not (imported_modules & protected)
    assert set(__import__("customer.services.session_service", fromlist=["AccessContext"]).AccessContext.__dataclass_fields__) == {
        "account_id",
        "session_id",
        "issued_at",
        "expires_at",
        "assurance",
        "fresh_until",
    }


def test_api_orchestration_emits_required_audit_events_without_secrets(
    api, session, clock
):
    client, provider, sender = api
    first = _signup(
        client,
        provider,
        sender,
        stable_key="DI-audit-api",
        email="audit-api@example.com",
    )
    assert first.status_code == 200
    duplicate = _signup(
        client,
        provider,
        sender,
        stable_key="DI-audit-api",
        email="audit-api-duplicate@example.com",
    )
    assert duplicate.json()["outcome"] == "existing_account_recovery_required"

    challenge_id, code = _issue_login_challenge(
        client, sender, channel="email", target="audit-api@example.com"
    )
    bad = client.post(
        "/v1/customer/auth/login/verify",
        json={
            "channel": "email",
            "target": "audit-api@example.com",
            "challenge_id": challenge_id,
            "code": "0000000",
        },
    )
    assert bad.status_code == 400
    logged_in = client.post(
        "/v1/customer/auth/login/verify",
        json={
            "channel": "email",
            "target": "audit-api@example.com",
            "challenge_id": challenge_id,
            "code": code,
        },
    )
    assert logged_in.status_code == 200
    account_id = uuid.UUID(logged_in.json()["account"]["account_id"])
    extra = SessionService(session, clock).create_browser_session(account_id=account_id)
    assert client.delete(
        "/v1/customer/sessions/{0}".format(extra.session_id),
        headers={"Origin": "https://testserver"},
    ).status_code == 200
    token = _session_cookie(client)
    assert client.post(
        "/v1/customer/auth/logout-all",
        headers={"Origin": "https://testserver"},
    ).status_code == 200

    rows = session.query(AuditEvent).all()
    event_types = {row.event_type for row in rows}
    expected = {
        "identity.verification_verified",
        audit_events.IDENTITY_DUPLICATE_SIGNUP_BLOCKED,
        audit_events.AUTH_CHALLENGE_ISSUED,
        audit_events.AUTH_CHALLENGE_FAILED,
        audit_events.AUTH_CHALLENGE_VERIFIED,
        audit_events.SESSION_CREATED,
        audit_events.SESSION_REVOKED,
        audit_events.SESSION_LOGOUT_ALL,
    }
    assert expected <= event_types
    serialized = " ".join(str(row.payload) for row in rows)
    assert code not in serialized
    assert token not in serialized
    assert "DI-audit-api" not in serialized


def test_account_creation_rolls_back_if_session_creation_fails(
    api, session, monkeypatch
):
    client, provider, sender = api
    verification_id = _start_signup(
        client, provider, stable_key="DI-account-atomic"
    )
    challenge_id, code = _issue_signup_challenge(
        client, sender, verification_id, "atomic-account@example.com"
    )

    def fail_session_creation(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("controlled session creation failure")

    monkeypatch.setattr(
        SessionService, "create_browser_session", fail_session_creation
    )
    with pytest.raises(RuntimeError, match="controlled session creation failure"):
        _complete_signup_request(
            client,
            verification_id,
            "atomic-account@example.com",
            challenge_id,
            code,
        )

    session.expire_all()
    assert session.query(CustomerAccount).count() == 0
    assert session.query(BrowserSession).count() == 0
    verification = session.get(IdentityVerification, uuid.UUID(verification_id))
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    assert verification.person_id is None and verification.consumed_at is None
    assert challenge.status == AuthChallengeStatus.PENDING.value


def test_login_challenge_consumption_rolls_back_if_session_creation_fails(
    api, session, monkeypatch
):
    client, provider, sender = api
    email = "atomic-login@example.com"
    assert _signup(client, provider, sender, email=email).status_code == 200
    challenge_id, code = _issue_login_challenge(
        client, sender, channel="email", target=email
    )
    sessions_before = session.query(BrowserSession).count()

    def fail_session_creation(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("controlled login session failure")

    monkeypatch.setattr(
        SessionService, "create_browser_session", fail_session_creation
    )
    with pytest.raises(RuntimeError, match="controlled login session failure"):
        client.post(
            "/v1/customer/auth/login/verify",
            json={
                "channel": "email",
                "target": email,
                "challenge_id": challenge_id,
                "code": code,
            },
        )

    session.expire_all()
    assert session.query(BrowserSession).count() == sessions_before
    challenge = session.get(AuthChallenge, uuid.UUID(challenge_id))
    assert challenge.status == AuthChallengeStatus.PENDING.value
    assert challenge.consumed_at is None
