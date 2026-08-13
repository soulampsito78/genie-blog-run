"""Security-event emission for the customer auth domain.

Proves that security-significant actions actually append `audit_event` rows -
the table existing is not evidence that anything writes to it - and that no
audit row can carry secret material.
"""

import datetime as dt
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")

from sqlalchemy.exc import DBAPIError  # noqa: E402

from customer.domain import auth_policy  # noqa: E402
from customer.domain.clock import UTC, FixedClock  # noqa: E402
from customer.domain.enums import (  # noqa: E402
    AuthAssuranceLevel,
    AuthChallengeChannel,
    AuthChallengePurpose,
    IdentityVerificationPurpose,
)
from customer.domain.errors import (  # noqa: E402
    IdentityMismatch,
    LoginChallengeInvalid,
)
from customer.services import audit_service as audit_events  # noqa: E402
from customer.services.audit_service import AuditSecretLeak, AuditService  # noqa: E402
from customer.services.challenge_service import ChallengeService  # noqa: E402
from customer.services.identity_service import IdentityService  # noqa: E402
from customer.services.providers import (  # noqa: E402
    IdentityVerificationResult,
    NullVerificationCodeSender,
)
from customer.services.session_service import SessionService  # noqa: E402

from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    make_account,
    make_person,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db

__all__ = ["customer_engine", "session"]


@pytest.fixture()
def clock():
    return FixedClock(dt.datetime(2026, 8, 11, 9, 0, 0, tzinfo=UTC))


@pytest.fixture()
def sessions(session, clock):
    return SessionService(session, clock)


@pytest.fixture()
def challenges(session, clock):
    return ChallengeService(session, clock, sender=NullVerificationCodeSender())


@pytest.fixture()
def identities(session, clock):
    return IdentityService(session, clock)


def audit_types(session, account_id=None):
    from customer.persistence.models import AuditEvent

    statement = sa.select(AuditEvent.event_type)
    if account_id is not None:
        statement = statement.where(AuditEvent.account_id == account_id)
    return list(session.scalars(statement))


def audit_rows(session):
    from customer.persistence.models import AuditEvent

    return list(session.scalars(sa.select(AuditEvent)))


def idv(*, adult=True, stable_key="DI-audit", mobile="+821012345678"):
    return IdentityVerificationResult(
        provider="test_idv",
        provider_reference="ref-{0}".format(uuid.uuid4().hex[:12]),
        adult_verified=adult,
        stable_key=stable_key if adult else None,
        mobile_e164=mobile,
    )


# ---------------------------------------------------------------------------
# Challenge events
# ---------------------------------------------------------------------------


def test_challenge_issuance_emits_an_audit_event(session, challenges):
    account = make_account(session)

    challenges.issue_challenge(
        purpose=AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target="user@example.com",
        account_id=account.id,
    )

    assert audit_events.AUTH_CHALLENGE_ISSUED in audit_types(session, account.id)


def test_successful_verification_emits_an_audit_event(session, challenges):
    account = make_account(session)
    issued = challenges.issue_challenge(
        purpose=AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target="user@example.com",
        account_id=account.id,
    )

    challenges.verify_and_consume(
        challenge_id=issued.challenge_id,
        code=issued.code,
        purpose=AuthChallengePurpose.LOGIN.value,
        account_id=account.id,
    )

    assert audit_events.AUTH_CHALLENGE_VERIFIED in audit_types(session, account.id)


def test_failed_verification_emits_an_event_without_the_code(session, challenges):
    account = make_account(session)
    issued = challenges.issue_challenge(
        purpose=AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target="user@example.com",
        account_id=account.id,
    )
    wrong = "000000" if issued.code != "000000" else "111111"

    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=wrong,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )

    types = audit_types(session, account.id)
    assert audit_events.AUTH_CHALLENGE_FAILED in types
    for row in audit_rows(session):
        serialized = str(row.payload)
        assert issued.code not in serialized
        assert wrong not in serialized


def test_attempt_lock_emits_a_locked_event(session, challenges):
    account = make_account(session)
    issued = challenges.issue_challenge(
        purpose=AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target="user@example.com",
        account_id=account.id,
    )
    wrong = "000000" if issued.code != "000000" else "111111"

    for _ in range(auth_policy.CHALLENGE_MAX_ATTEMPTS):
        with pytest.raises(LoginChallengeInvalid):
            challenges.verify_and_consume(
                challenge_id=issued.challenge_id,
                code=wrong,
                purpose=AuthChallengePurpose.LOGIN.value,
                account_id=account.id,
            )

    assert audit_events.AUTH_CHALLENGE_LOCKED in audit_types(session, account.id)


# ---------------------------------------------------------------------------
# Session events
# ---------------------------------------------------------------------------


def test_session_creation_emits_an_audit_event(session, sessions):
    account = make_account(session)

    sessions.create_browser_session(account_id=account.id)

    assert audit_events.SESSION_CREATED in audit_types(session, account.id)


def test_single_session_revoke_emits_an_audit_event(session, sessions):
    account = make_account(session)
    created = sessions.create_browser_session(account_id=account.id)

    sessions.revoke_session(created.session_id)

    assert audit_events.SESSION_REVOKED in audit_types(session, account.id)


def test_logout_all_emits_an_audit_event_with_the_count(session, sessions):
    from customer.persistence.models import AuditEvent

    account = make_account(session)
    for _ in range(3):
        sessions.create_browser_session(account_id=account.id)

    sessions.revoke_all_sessions(account.id)

    row = session.scalars(
        sa.select(AuditEvent).where(
            AuditEvent.event_type == audit_events.SESSION_LOGOUT_ALL
        )
    ).one()
    assert row.payload["revoked_count"] == 3


def test_fresh_auth_elevation_emits_an_audit_event(session, sessions):
    account = make_account(session)
    created = sessions.create_browser_session(account_id=account.id)
    live = sessions.authenticate_session(token=created.token)

    sessions.record_fresh_auth(live, assurance=AuthAssuranceLevel.STRONG_OTP.value)

    assert audit_events.AUTH_FRESH_AUTH_RECORDED in audit_types(session, account.id)


# ---------------------------------------------------------------------------
# Identity events
# ---------------------------------------------------------------------------


def test_eligible_verification_emits_a_verified_event(session, identities):
    identities.record_verification_result(
        idv(), purpose=IdentityVerificationPurpose.SIGNUP.value
    )

    assert "identity.verification_verified" in audit_types(session)


def test_age_not_eligible_emits_its_own_event(session, identities):
    identities.record_verification_result(
        idv(adult=False), purpose=IdentityVerificationPurpose.SIGNUP.value
    )

    assert "identity.verification_age_not_eligible" in audit_types(session)


def test_identity_mismatch_emits_an_audit_event(session, identities):
    person = make_person(session, idv_stable_key="DI-owner-audit")
    account = make_account(session, person)
    verification = identities.record_verification_result(
        idv(stable_key="DI-intruder"),
        purpose=IdentityVerificationPurpose.PHONE_CHANGE.value,
        account_id=account.id,
    )

    with pytest.raises(IdentityMismatch):
        identities.apply_phone_change(account_id=account.id, verification=verification)

    assert audit_events.IDENTITY_PHONE_CHANGE_MISMATCH in audit_types(
        session, account.id
    )


def test_phone_change_success_emits_an_audit_event(session, identities):
    person = make_person(session, idv_stable_key="DI-same-audit")
    account = make_account(session, person)
    verification = identities.record_verification_result(
        idv(stable_key="DI-same-audit", mobile="+821033334444"),
        purpose=IdentityVerificationPurpose.PHONE_CHANGE.value,
        account_id=account.id,
    )

    identities.apply_phone_change(account_id=account.id, verification=verification)

    assert audit_events.IDENTITY_PHONE_CHANGED in audit_types(session, account.id)


# ---------------------------------------------------------------------------
# No secret leakage
# ---------------------------------------------------------------------------


def test_no_audit_payload_contains_a_session_token(session, sessions):
    account = make_account(session)
    created = sessions.create_browser_session(account_id=account.id)

    for row in audit_rows(session):
        serialized = str(row.payload) + str(row.entity_id)
        assert created.token not in serialized


def test_no_audit_payload_contains_a_token_hash(session, sessions):
    from customer.persistence.models import BrowserSession

    account = make_account(session)
    created = sessions.create_browser_session(account_id=account.id)
    stored = session.get(BrowserSession, created.session_id)

    for row in audit_rows(session):
        assert stored.session_token_hash not in str(row.payload)


def test_no_audit_payload_contains_the_stable_identity_key(session, identities):
    identities.record_verification_result(
        idv(stable_key="DI-super-secret-key"),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
    )

    for row in audit_rows(session):
        assert "DI-super-secret-key" not in str(row.payload)


@pytest.mark.parametrize(
    "bad_key",
    ["otp", "code_hash", "session_token", "raw_token", "idv_payload", "card_last4"],
)
def test_audit_helper_rejects_secret_bearing_keys(session, clock, bad_key):
    """The choke point fails loudly rather than silently scrubbing."""
    audit = AuditService(session, clock)

    with pytest.raises(AuditSecretLeak):
        audit.record("test.event", payload={bad_key: "whatever"})


def test_audit_helper_rejects_nested_payloads(session, clock):
    audit = AuditService(session, clock)

    with pytest.raises(AuditSecretLeak):
        audit.record("test.event", payload={"detail": {"nested": "dump"}})


def test_audit_helper_allows_safe_classification_keys(session, clock):
    audit = AuditService(session, clock)

    event = audit.record(
        "test.event", payload={"plan_code": "full_set", "failure_code": "X"}
    )

    assert event.payload["plan_code"] == "full_set"


def test_audit_rows_remain_append_only(session, sessions):
    """Phase 1's UPDATE-blocking trigger must still hold."""
    account = make_account(session)
    sessions.create_browser_session(account_id=account.id)
    row = audit_rows(session)[0]

    with pytest.raises(DBAPIError):
        session.execute(
            sa.text("UPDATE audit_event SET event_type = :t WHERE id = :i"),
            {"t": "tampered", "i": row.id},
        )


def test_auth_services_do_not_insert_audit_rows_directly():
    """One choke point: no ad-hoc AuditEvent inserts scattered in services."""
    import pathlib

    services = pathlib.Path(__file__).resolve().parent.parent / "customer" / "services"
    offenders = []
    for path in services.glob("*.py"):
        if path.name == "audit_service.py":
            continue
        if "AuditEvent(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)

    assert offenders == []


# ---------------------------------------------------------------------------
# OTP verifier hardening (server-side pepper boundary)
# ---------------------------------------------------------------------------


def test_verification_code_verifier_is_salted_and_slow():
    """PBKDF2 + per-challenge salt, not a bare fast hash."""
    from customer.domain import auth_policy as policy
    from customer.domain.security import issue_verification_code

    assert policy.CHALLENGE_CODE_KDF_ITERATIONS >= 100_000

    code, salt_a, hash_a = issue_verification_code()
    _, salt_b, _ = issue_verification_code()

    from customer.domain.security import hash_verification_code

    assert salt_a != salt_b
    # Same code, different salt -> different verifier (no rainbow reuse).
    assert hash_verification_code(code, salt_a) != hash_verification_code(code, salt_b)


def test_pepper_boundary_changes_the_verifier(monkeypatch):
    """A pepper kept outside the DB defeats a read-only DB compromise."""
    from customer.domain.security import (
        CUSTOMER_AUTH_CODE_PEPPER_ENV,
        hash_verification_code,
        new_code_salt,
    )

    salt = new_code_salt()
    monkeypatch.delenv(CUSTOMER_AUTH_CODE_PEPPER_ENV, raising=False)
    unpeppered = hash_verification_code("123456", salt)

    monkeypatch.setenv(CUSTOMER_AUTH_CODE_PEPPER_ENV, "some-server-side-key")
    peppered = hash_verification_code("123456", salt)

    assert unpeppered != peppered


def test_pepper_is_optional_and_unset_by_default(monkeypatch):
    """No production secret is required for this phase."""
    from customer.domain.security import (
        CUSTOMER_AUTH_CODE_PEPPER_ENV,
        current_code_pepper,
    )

    monkeypatch.delenv(CUSTOMER_AUTH_CODE_PEPPER_ENV, raising=False)

    assert current_code_pepper() is None


def test_challenge_flow_works_with_a_pepper_configured(session, clock, monkeypatch):
    """End-to-end verification stays correct once a pepper is introduced."""
    from customer.domain.security import CUSTOMER_AUTH_CODE_PEPPER_ENV

    monkeypatch.setenv(CUSTOMER_AUTH_CODE_PEPPER_ENV, "phase-2-pepper")
    service = ChallengeService(session, clock, sender=NullVerificationCodeSender())
    account = make_account(session)

    issued = service.issue_challenge(
        purpose=AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target="peppered@example.com",
        account_id=account.id,
    )
    consumed = service.verify_and_consume(
        challenge_id=issued.challenge_id,
        code=issued.code,
        purpose=AuthChallengePurpose.LOGIN.value,
        account_id=account.id,
    )

    assert consumed.consumed_at is not None
