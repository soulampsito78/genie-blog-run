"""Customer auth, session, and identity-verification invariants (PostgreSQL).

Time is never slept on: every expiry test advances a `FixedClock` to an exact
boundary. See tests/customer_db_fixtures.py for the database gating.
"""

import datetime as dt
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")

from sqlalchemy.exc import IntegrityError  # noqa: E402

from customer.domain import auth_policy  # noqa: E402
from customer.domain.clock import UTC, FixedClock  # noqa: E402
from customer.domain.enums import (  # noqa: E402
    AuthAssuranceLevel,
    AuthChallengeChannel,
    AuthChallengePurpose,
    AuthChallengeStatus,
    IdentityVerificationPurpose,
    IdentityVerificationStatus,
    SessionRevokeReason,
    assurance_at_least,
)
from customer.domain.errors import (  # noqa: E402
    AgeNotEligible,
    ChallengeRateLimited,
    IdentityAlreadyRegistered,
    IdentityMismatch,
    LoginChallengeInvalid,
    SessionExpired,
    SessionInvalid,
    SessionRevoked,
    StepUpRequired,
)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def idv_result(
    *,
    adult=True,
    stable_key="DI-person-1",
    mobile="+821012345678",
    failed=False,
    reference=None,
):
    return IdentityVerificationResult(
        provider="test_idv",
        provider_reference=reference or "ref-{0}".format(uuid.uuid4().hex[:12]),
        adult_verified=adult,
        stable_key=stable_key if adult else None,
        mobile_e164=mobile,
        failed=failed,
    )


def login_session(sessions, account, *, remember=False, assurance=None):
    return sessions.create_browser_session(
        account_id=account.id,
        remember_login=remember,
        assurance=assurance or AuthAssuranceLevel.RECENT_VERIFICATION.value,
    )



def keep_alive(sessions, clock, token, *, total, step):
    """Advance time in `step` increments, touching the session each time.

    Needed whenever a test targets the ABSOLUTE lifetime: without periodic
    activity the (much shorter) inactivity window fires first, which is correct
    behaviour but not what those tests are measuring.
    """
    elapsed = dt.timedelta(0)
    while elapsed + step <= total:
        clock.advance(step)
        elapsed += step
        sessions.authenticate_session(token=token)
    remainder = total - elapsed
    if remainder > dt.timedelta(0):
        clock.advance(remainder)

# ---------------------------------------------------------------------------
# IDENTITY - adult gate (Auth spec sec. 1)
# ---------------------------------------------------------------------------


def test_under_19_result_cannot_create_an_account(session, identities):
    verification = identities.record_verification_result(
        idv_result(adult=False), purpose=IdentityVerificationPurpose.SIGNUP.value
    )

    assert verification.status == IdentityVerificationStatus.AGE_NOT_ELIGIBLE.value
    with pytest.raises(AgeNotEligible):
        identities.resolve_person_for_signup(verification)


def test_under_19_outcome_is_recorded_as_its_own_status(session, identities):
    """Not a generic failure - the adult gate must be auditable."""
    verification = identities.record_verification_result(
        idv_result(adult=False), purpose=IdentityVerificationPurpose.SIGNUP.value
    )

    assert verification.adult_verified is False
    assert verification.idv_stable_key is None


def test_verified_identity_cannot_be_stored_without_a_stable_key(session):
    """DB-level: a 'verified' row without adult+stable key is unrepresentable."""
    from customer.persistence.models import IdentityVerification

    session.add(
        IdentityVerification(
            purpose=IdentityVerificationPurpose.SIGNUP.value,
            status=IdentityVerificationStatus.VERIFIED.value,
            provider="test_idv",
            provider_reference="ref-bad",
            idv_stable_key=None,
            adult_verified=True,
            completed_at=dt.datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_identity_verification_stores_no_raw_payload_or_birthdate():
    from customer.persistence.models import IdentityVerification

    columns = {c.lower() for c in IdentityVerification.__table__.columns.keys()}
    forbidden = {
        "raw_payload",
        "payload",
        "birthdate",
        "birth_date",
        "dob",
        "resident_number",
        "ci",
        "name",
    }

    assert not (columns & forbidden)


# ---------------------------------------------------------------------------
# IDENTITY - one person, one active account (Auth spec sec. 2)
# ---------------------------------------------------------------------------


def test_duplicate_stable_identity_cannot_create_a_second_active_account(
    session, identities
):
    first = identities.record_verification_result(
        idv_result(stable_key="DI-dup"), purpose=IdentityVerificationPurpose.SIGNUP.value
    )
    verified = identities.resolve_person_for_signup(first)
    make_account(session, session.get(_person_model(), verified.person_id))

    second = identities.record_verification_result(
        idv_result(stable_key="DI-dup"), purpose=IdentityVerificationPurpose.SIGNUP.value
    )
    with pytest.raises(IdentityAlreadyRegistered):
        identities.resolve_person_for_signup(second)


def test_returning_withdrawn_person_reuses_the_same_person_row(session, identities):
    first = identities.record_verification_result(
        idv_result(stable_key="DI-return"),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
    )
    verified_first = identities.resolve_person_for_signup(first)
    person = session.get(_person_model(), verified_first.person_id)
    make_account(session, person, status="withdrawn")

    second = identities.record_verification_result(
        idv_result(stable_key="DI-return"),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
    )
    verified_second = identities.resolve_person_for_signup(second)

    assert verified_second.person_id == verified_first.person_id


def test_same_phone_and_email_do_not_merge_two_persons(session, identities):
    """Contact channels are not identity (Auth spec sec. 2)."""
    shared_phone = "+821099998888"
    a = identities.record_verification_result(
        idv_result(stable_key="DI-a", mobile=shared_phone),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
    )
    b = identities.record_verification_result(
        idv_result(stable_key="DI-b", mobile=shared_phone),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
    )

    person_a = identities.resolve_person_for_signup(a)
    person_b = identities.resolve_person_for_signup(b)

    assert person_a.person_id != person_b.person_id


# ---------------------------------------------------------------------------
# IDENTITY - phone change (Auth spec sec. 9)
# ---------------------------------------------------------------------------


def test_phone_change_with_same_stable_identity_succeeds(session, identities):
    person = make_person(session, idv_stable_key="DI-phone")
    account = make_account(session, person)

    verification = identities.record_verification_result(
        idv_result(stable_key="DI-phone", mobile="+821055556666"),
        purpose=IdentityVerificationPurpose.PHONE_CHANGE.value,
        account_id=account.id,
    )
    updated = identities.apply_phone_change(
        account_id=account.id, verification=verification
    )

    assert updated.mobile_e164 == "+821055556666"


def test_phone_change_with_different_identity_is_rejected(session, identities):
    person = make_person(session, idv_stable_key="DI-owner")
    account = make_account(session, person)
    original_phone = account.mobile_e164

    verification = identities.record_verification_result(
        idv_result(stable_key="DI-someone-else", mobile="+821077778888"),
        purpose=IdentityVerificationPurpose.PHONE_CHANGE.value,
        account_id=account.id,
    )
    with pytest.raises(IdentityMismatch):
        identities.apply_phone_change(account_id=account.id, verification=verification)

    assert account.mobile_e164 == original_phone


def test_signup_verification_cannot_be_replayed_as_a_phone_change(session, identities):
    """Purpose binding: verifications are not interchangeable."""
    from customer.domain.errors import IdentityVerificationFailed

    person = make_person(session, idv_stable_key="DI-purpose")
    account = make_account(session, person)
    verification = identities.record_verification_result(
        idv_result(stable_key="DI-purpose"),
        purpose=IdentityVerificationPurpose.SIGNUP.value,
        account_id=account.id,
    )

    with pytest.raises(IdentityVerificationFailed):
        identities.apply_phone_change(account_id=account.id, verification=verification)


def test_consumed_verification_cannot_be_reused(session, identities):
    from customer.domain.errors import IdentityVerificationFailed

    person = make_person(session, idv_stable_key="DI-once")
    account = make_account(session, person)
    verification = identities.record_verification_result(
        idv_result(stable_key="DI-once", mobile="+821011112222"),
        purpose=IdentityVerificationPurpose.PHONE_CHANGE.value,
        account_id=account.id,
    )
    identities.apply_phone_change(account_id=account.id, verification=verification)

    with pytest.raises(IdentityVerificationFailed):
        identities.apply_phone_change(account_id=account.id, verification=verification)


# ---------------------------------------------------------------------------
# SESSION - canonical lifetimes (Auth spec sec. 4)
# ---------------------------------------------------------------------------


def test_remember_off_absolute_lifetime_is_12_hours(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    assert created.absolute_expires_at - clock.now() == dt.timedelta(hours=12)


def test_remember_off_inactivity_lifetime_is_2_hours(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    assert created.inactivity_expires_at - clock.now() == dt.timedelta(hours=2)


def test_remember_on_absolute_lifetime_is_30_days(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=True)

    assert created.absolute_expires_at - clock.now() == dt.timedelta(days=30)


def test_remember_on_inactivity_lifetime_is_7_days(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=True)

    assert created.inactivity_expires_at - clock.now() == dt.timedelta(days=7)


def test_remember_login_defaults_to_off():
    assert auth_policy.REMEMBER_LOGIN_DEFAULT is False


def test_absolute_expiry_rejects_the_session(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    clock.advance(dt.timedelta(hours=12))
    with pytest.raises(SessionExpired):
        sessions.authenticate_session(token=created.token)


def test_session_valid_just_before_absolute_expiry(session, sessions, clock):
    """Kept continuously active, the session survives right up to 12h."""
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    keep_alive(
        sessions,
        clock,
        created.token,
        total=dt.timedelta(hours=12) - dt.timedelta(seconds=1),
        step=dt.timedelta(hours=1),
    )
    assert sessions.authenticate_session(token=created.token) is not None


def test_absolute_limit_ends_a_continuously_active_session(session, sessions, clock):
    """Activity slides inactivity but can never defeat the absolute lifetime."""
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    # Alive and continuously used up to 11h...
    keep_alive(
        sessions,
        clock,
        created.token,
        total=dt.timedelta(hours=11),
        step=dt.timedelta(hours=1),
    )
    assert sessions.authenticate_session(token=created.token) is not None

    # ...and dead the moment the 12h absolute limit lands, despite that use.
    clock.advance(dt.timedelta(hours=1))
    with pytest.raises(SessionExpired):
        sessions.authenticate_session(token=created.token)


def test_inactivity_expiry_rejects_the_session(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    clock.advance(dt.timedelta(hours=2))
    with pytest.raises(SessionExpired):
        sessions.authenticate_session(token=created.token)


def test_activity_slides_the_inactivity_window(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    clock.advance(dt.timedelta(hours=1))
    sessions.authenticate_session(token=created.token)
    clock.advance(dt.timedelta(hours=1, minutes=30))

    assert sessions.authenticate_session(token=created.token) is not None


def test_inactivity_window_never_slides_past_the_absolute_limit(
    session, sessions, clock
):
    account = make_account(session)
    created = login_session(sessions, account, remember=False)

    keep_alive(
        sessions,
        clock,
        created.token,
        total=dt.timedelta(hours=11, minutes=30),
        step=dt.timedelta(hours=1),
    )
    live = sessions.authenticate_session(token=created.token)

    assert live.inactivity_expires_at == created.absolute_expires_at


def test_revoked_session_is_rejected(session, sessions):
    account = make_account(session)
    created = login_session(sessions, account)
    sessions.revoke_session(created.session_id)

    with pytest.raises(SessionRevoked):
        sessions.authenticate_session(token=created.token)


def test_unknown_token_is_rejected(session, sessions):
    make_account(session)
    with pytest.raises(SessionInvalid):
        sessions.authenticate_session(token="not-a-real-token")


def test_multiple_device_sessions_are_allowed(session, sessions):
    account = make_account(session)
    first = login_session(sessions, account)
    second = login_session(sessions, account, remember=True)
    third = login_session(sessions, account)

    active = sessions.list_active_sessions(account.id)

    assert len({first.session_id, second.session_id, third.session_id}) == 3
    assert len(active) == 3


def test_revoking_one_session_leaves_the_others_alive(session, sessions):
    account = make_account(session)
    first = login_session(sessions, account)
    second = login_session(sessions, account)

    sessions.revoke_session(
        first.session_id, reason=SessionRevokeReason.USER_REVOKED_SESSION.value
    )

    with pytest.raises(SessionRevoked):
        sessions.authenticate_session(token=first.token)
    assert sessions.authenticate_session(token=second.token) is not None


def test_logout_all_revokes_every_server_side_session(session, sessions):
    account = make_account(session)
    tokens = [login_session(sessions, account) for _ in range(3)]

    revoked = sessions.revoke_all_sessions(account.id)

    assert revoked == 3
    for created in tokens:
        with pytest.raises(SessionRevoked):
            sessions.authenticate_session(token=created.token)
    assert sessions.list_active_sessions(account.id) == []


def test_logout_all_can_preserve_the_current_session(session, sessions):
    account = make_account(session)
    keep = login_session(sessions, account)
    other = login_session(sessions, account)

    sessions.revoke_all_sessions(account.id, except_session_id=keep.session_id)

    assert sessions.authenticate_session(token=keep.token) is not None
    with pytest.raises(SessionRevoked):
        sessions.authenticate_session(token=other.token)


def test_revoke_is_idempotent(session, sessions):
    account = make_account(session)
    created = login_session(sessions, account)

    assert sessions.revoke_session(created.session_id) is True
    assert sessions.revoke_session(created.session_id) is False


def test_withdrawn_account_cannot_authenticate(session, sessions):
    from customer.domain.errors import AccountNotActive
    from customer.persistence.models import CustomerAccount

    account = make_account(session)
    created = login_session(sessions, account)

    session.execute(
        sa.update(CustomerAccount)
        .where(CustomerAccount.id == account.id)
        .values(status="withdrawn", withdrawn_at=dt.datetime.now(UTC))
    )
    session.flush()
    session.expire_all()

    with pytest.raises(AccountNotActive):
        sessions.authenticate_session(token=created.token)


# ---------------------------------------------------------------------------
# SESSION - token handling (Auth spec sec. 7; sec. 22 of the phase brief)
# ---------------------------------------------------------------------------


def test_raw_session_token_is_never_stored(session, sessions):
    from customer.persistence.models import BrowserSession

    account = make_account(session)
    created = login_session(sessions, account)

    stored = session.get(BrowserSession, created.session_id)

    assert stored.session_token_hash != created.token
    assert len(stored.session_token_hash) == 64
    row_values = [
        str(v) for v in session.execute(
            sa.select(BrowserSession).where(BrowserSession.id == created.session_id)
        ).first()
    ]
    assert all(created.token not in value for value in row_values)


def test_session_id_alone_does_not_authenticate(session, sessions):
    account = make_account(session)
    created = login_session(sessions, account)

    with pytest.raises(SessionInvalid):
        sessions.authenticate_session(token=str(created.session_id))


def test_session_tokens_are_unique_per_session(session, sessions):
    account = make_account(session)
    tokens = {login_session(sessions, account).token for _ in range(5)}

    assert len(tokens) == 5


def test_duplicate_token_hash_is_rejected_by_the_database(session, sessions):
    from customer.persistence.models import BrowserSession

    account = make_account(session)
    created = login_session(sessions, account)
    original = session.get(BrowserSession, created.session_id)

    now = dt.datetime.now(UTC)
    session.add(
        BrowserSession(
            account_id=account.id,
            session_token_hash=original.session_token_hash,
            remember_login=False,
            absolute_expires_at=now + dt.timedelta(hours=12),
            inactivity_expires_at=now + dt.timedelta(hours=2),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# FRESH AUTH (Auth spec sec. 5)
# ---------------------------------------------------------------------------


def test_fresh_auth_window_is_10_minutes():
    assert auth_policy.FRESH_AUTH_WINDOW == dt.timedelta(minutes=10)


def test_sensitive_action_fails_without_fresh_auth(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account)
    live = sessions.authenticate_session(token=created.token)

    clock.advance(dt.timedelta(minutes=11))
    with pytest.raises(StepUpRequired):
        sessions.require_fresh_auth(
            live, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
        )


def test_fresh_auth_is_valid_just_inside_the_window(session, sessions, clock):
    account = make_account(session)
    created = login_session(
        sessions, account, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    live = sessions.authenticate_session(token=created.token)

    clock.advance(dt.timedelta(minutes=9, seconds=59))
    sessions.require_fresh_auth(
        live, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
    )


def test_fresh_auth_expires_exactly_at_10_minutes(session, sessions, clock):
    account = make_account(session)
    created = login_session(
        sessions, account, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    live = sessions.authenticate_session(token=created.token)

    clock.advance(dt.timedelta(minutes=10))
    assert sessions.is_fresh(live) is False


def test_remembered_session_is_not_automatically_fresh(session, sessions, clock):
    """A 30-day session stays authenticated but stops being fresh at 10 min."""
    account = make_account(session)
    created = login_session(
        sessions, account, remember=True, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )

    clock.advance(dt.timedelta(days=6))
    live = sessions.authenticate_session(token=created.token)

    assert live is not None
    with pytest.raises(StepUpRequired):
        sessions.require_fresh_auth(live)


def test_recording_step_up_restores_freshness(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=True)
    clock.advance(dt.timedelta(days=6))
    live = sessions.authenticate_session(token=created.token)

    sessions.record_fresh_auth(live, assurance=AuthAssuranceLevel.STRONG_OTP.value)

    sessions.require_fresh_auth(
        live, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
    )


def test_weak_recent_verification_does_not_satisfy_a_financial_action(
    session, sessions
):
    """Fresh but not strong enough: assurance is not a single boolean."""
    account = make_account(session)
    created = login_session(
        sessions, account, assurance=AuthAssuranceLevel.RECENT_VERIFICATION.value
    )
    live = sessions.authenticate_session(token=created.token)

    with pytest.raises(StepUpRequired):
        sessions.require_fresh_auth(
            live, required_assurance=AuthAssuranceLevel.STRONG_OTP.value
        )


def test_strong_otp_does_not_satisfy_an_identity_destructive_action(session, sessions):
    """Phone change / withdrawal require full IDV, above strong OTP."""
    account = make_account(session)
    created = login_session(
        sessions, account, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    live = sessions.authenticate_session(token=created.token)

    with pytest.raises(StepUpRequired):
        sessions.require_fresh_auth(
            live, required_assurance=AuthAssuranceLevel.IDENTITY_VERIFIED.value
        )


def test_full_idv_satisfies_every_lower_tier(session, sessions):
    account = make_account(session)
    created = login_session(
        sessions, account, assurance=AuthAssuranceLevel.IDENTITY_VERIFIED.value
    )
    live = sessions.authenticate_session(token=created.token)

    for level in AuthAssuranceLevel.values():
        sessions.require_fresh_auth(live, required_assurance=level)


def test_assurance_levels_are_ordered_not_boolean():
    assert assurance_at_least("identity_verified", "strong_otp")
    assert assurance_at_least("strong_otp", "recent_verification")
    assert not assurance_at_least("session", "recent_verification")


# ---------------------------------------------------------------------------
# ACCESS CONTEXT (Auth spec sec. 4.2)
# ---------------------------------------------------------------------------


def test_access_context_is_short_lived(session, sessions, clock):
    account = make_account(session)
    created = login_session(sessions, account, remember=True)
    live = sessions.authenticate_session(token=created.token)

    context = sessions.refresh_access_context(live)

    assert context.expires_at - clock.now() == dt.timedelta(minutes=15)


def test_access_context_expires_long_before_a_remembered_session(
    session, sessions, clock
):
    """The 30-day session must never become a 30-day bearer credential."""
    account = make_account(session)
    created = login_session(sessions, account, remember=True)
    live = sessions.authenticate_session(token=created.token)
    context = sessions.refresh_access_context(live)

    clock.advance(dt.timedelta(minutes=16))

    assert context.is_expired(clock.now()) is True
    assert sessions.authenticate_session(token=created.token) is not None


def test_access_context_carries_freshness_separately(session, sessions, clock):
    account = make_account(session)
    created = login_session(
        sessions, account, remember=True, assurance=AuthAssuranceLevel.STRONG_OTP.value
    )
    live = sessions.authenticate_session(token=created.token)
    context = sessions.refresh_access_context(live)

    assert context.is_fresh(clock.now()) is True
    clock.advance(dt.timedelta(minutes=11))
    assert context.is_fresh(clock.now()) is False


# ---------------------------------------------------------------------------
# CHALLENGE (Auth spec sec. 3, 8)
# ---------------------------------------------------------------------------


def _issue(challenges, account=None, purpose=None, target="user@example.com"):
    return challenges.issue_challenge(
        purpose=purpose or AuthChallengePurpose.LOGIN.value,
        channel=AuthChallengeChannel.EMAIL.value,
        target=target,
        account_id=account.id if account is not None else None,
    )


def test_correct_code_verifies_and_consumes_atomically(session, challenges):
    from customer.persistence.models import AuthChallenge

    account = make_account(session)
    issued = _issue(challenges, account)

    consumed = challenges.verify_and_consume(
        challenge_id=issued.challenge_id,
        code=issued.code,
        purpose=AuthChallengePurpose.LOGIN.value,
        account_id=account.id,
    )

    assert consumed.status == AuthChallengeStatus.CONSUMED.value
    assert consumed.verified_at is not None
    stored = session.get(AuthChallenge, issued.challenge_id)
    assert stored.consumed_at is not None


def test_challenge_cannot_be_replayed(session, challenges):
    account = make_account(session)
    issued = _issue(challenges, account)
    challenges.verify_and_consume(
        challenge_id=issued.challenge_id,
        code=issued.code,
        purpose=AuthChallengePurpose.LOGIN.value,
        account_id=account.id,
    )

    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=issued.code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )


def test_expired_challenge_is_rejected(session, challenges, clock):
    account = make_account(session)
    issued = _issue(challenges, account)

    clock.advance(auth_policy.CHALLENGE_TTL)
    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=issued.code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )


def test_challenge_valid_just_before_expiry(session, challenges, clock):
    account = make_account(session)
    issued = _issue(challenges, account)

    clock.advance(auth_policy.CHALLENGE_TTL - dt.timedelta(seconds=1))
    consumed = challenges.verify_and_consume(
        challenge_id=issued.challenge_id,
        code=issued.code,
        purpose=AuthChallengePurpose.LOGIN.value,
        account_id=account.id,
    )

    assert consumed.status == AuthChallengeStatus.CONSUMED.value


def test_attempt_limit_locks_the_challenge(session, challenges):
    from customer.persistence.models import AuthChallenge

    account = make_account(session)
    issued = _issue(challenges, account)
    wrong = "000000" if issued.code != "000000" else "111111"

    for _ in range(auth_policy.CHALLENGE_MAX_ATTEMPTS):
        with pytest.raises(LoginChallengeInvalid):
            challenges.verify_and_consume(
                challenge_id=issued.challenge_id,
                code=wrong,
                purpose=AuthChallengePurpose.LOGIN.value,
                account_id=account.id,
            )

    stored = session.get(AuthChallenge, issued.challenge_id)
    assert stored.status == AuthChallengeStatus.LOCKED.value

    # Even the correct code must now fail: the challenge is spent.
    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=issued.code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )


def test_cross_purpose_reuse_is_rejected(session, challenges):
    """A login code must not authorize a withdrawal-tier action."""
    account = make_account(session)
    issued = _issue(challenges, account, purpose=AuthChallengePurpose.LOGIN.value)

    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=issued.code,
            purpose=AuthChallengePurpose.STEP_UP.value,
            account_id=account.id,
        )


def test_cross_account_reuse_is_rejected(session, challenges):
    account = make_account(session)
    other = make_account(session)
    issued = _issue(challenges, account)

    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=issued.challenge_id,
            code=issued.code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=other.id,
        )


def test_raw_code_is_absent_from_the_database(session, challenges):
    from customer.persistence.models import AuthChallenge

    account = make_account(session)
    issued = _issue(challenges, account)

    row = session.execute(
        sa.select(AuthChallenge).where(AuthChallenge.id == issued.challenge_id)
    ).first()
    values = [str(v) for v in row]

    assert all(issued.code != value for value in values)
    assert all(issued.code not in value for value in values)


def test_challenge_hash_is_salted_per_challenge(session, challenges, clock):
    from customer.persistence.models import AuthChallenge

    account = make_account(session)
    first = _issue(challenges, account, target="a@example.com")
    clock.advance(auth_policy.CHALLENGE_ISSUE_COOLDOWN)
    second = _issue(challenges, account, target="b@example.com")

    rows = {
        c.id: c
        for c in session.scalars(
            sa.select(AuthChallenge).where(
                AuthChallenge.id.in_([first.challenge_id, second.challenge_id])
            )
        )
    }
    assert (
        rows[first.challenge_id].code_salt != rows[second.challenge_id].code_salt
    )


def test_issue_cooldown_is_enforced(session, challenges):
    account = make_account(session)
    _issue(challenges, account)

    with pytest.raises(ChallengeRateLimited):
        _issue(challenges, account)


def test_reissue_after_cooldown_expires_the_previous_challenge(
    session, challenges, clock
):
    from customer.persistence.models import AuthChallenge

    account = make_account(session)
    first = _issue(challenges, account)
    clock.advance(auth_policy.CHALLENGE_ISSUE_COOLDOWN)
    second = _issue(challenges, account)

    stored_first = session.get(AuthChallenge, first.challenge_id)

    assert stored_first.status == AuthChallengeStatus.EXPIRED.value
    with pytest.raises(LoginChallengeInvalid):
        challenges.verify_and_consume(
            challenge_id=first.challenge_id,
            code=first.code,
            purpose=AuthChallengePurpose.LOGIN.value,
            account_id=account.id,
        )
    assert second.challenge_id != first.challenge_id


def test_only_one_pending_challenge_per_target_and_purpose(session):
    """DB-level partial unique index backs the service-level expiry."""
    from customer.persistence.models import AuthChallenge

    now = dt.datetime.now(UTC)

    def build():
        return AuthChallenge(
            purpose=AuthChallengePurpose.LOGIN.value,
            channel=AuthChallengeChannel.EMAIL.value,
            target="dup@example.com",
            code_hash="a" * 64,
            code_salt="b" * 32,
            status=AuthChallengeStatus.PENDING.value,
            attempt_count=0,
            max_attempts=5,
            created_at=now,
            expires_at=now + dt.timedelta(minutes=5),
        )

    session.add(build())
    session.flush()
    session.add(build())
    with pytest.raises(IntegrityError):
        session.flush()


def test_attempt_count_cannot_exceed_max_attempts(session):
    from customer.persistence.models import AuthChallenge

    now = dt.datetime.now(UTC)
    session.add(
        AuthChallenge(
            purpose=AuthChallengePurpose.LOGIN.value,
            channel=AuthChallengeChannel.EMAIL.value,
            target="over@example.com",
            code_hash="a" * 64,
            code_salt="b" * 32,
            status=AuthChallengeStatus.PENDING.value,
            attempt_count=9,
            max_attempts=5,
            created_at=now,
            expires_at=now + dt.timedelta(minutes=5),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# SECURITY / BOUNDARY
# ---------------------------------------------------------------------------


def test_no_password_column_exists_anywhere():
    """The service is passwordless; a password column must never appear."""
    from customer.persistence.base import customer_metadata

    offenders = []
    for table in customer_metadata.tables.values():
        for column in table.columns:
            name = column.name.lower()
            if "password" in name or name in {"pwd", "passwd", "password_hash"}:
                offenders.append("{0}.{1}".format(table.name, column.name))

    assert offenders == []


def test_cookie_defaults_are_secure_and_http_only():
    from customer.services.cookies import session_cookie_settings

    settings = session_cookie_settings(remember_login=False)

    assert settings.http_only is True
    assert settings.secure is True
    assert settings.same_site == "Lax"
    assert settings.domain is None


def test_remember_off_cookie_is_non_persistent():
    from customer.services.cookies import session_cookie_settings

    assert session_cookie_settings(remember_login=False).max_age is None


def test_remember_on_cookie_persists_for_the_absolute_lifetime():
    from customer.services.cookies import session_cookie_settings

    settings = session_cookie_settings(remember_login=True)

    assert settings.max_age == int(
        auth_policy.SESSION_ABSOLUTE_TTL_REMEMBER_ON.total_seconds()
    )


def test_no_supabase_auth_dependency_in_customer_package():
    """Supabase is hosted PostgreSQL only; its Auth stack is not authority.

    Deliberately a blunt token scan rather than an import check: a Supabase
    Auth dependency could arrive as an import, a client construction, a JWT
    audience string, or a settings key, and any of those would breach the
    infrastructure decision.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "customer"
    banned = ("supabase", "gotrue", "postgrest", "realtime-py")

    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in banned:
            if token in text:
                offenders.append("{0}: {1}".format(path.name, token))

    assert offenders == [], "Supabase-stack reference in customer package"


def test_customer_session_carries_no_operator_authority(session, sessions):
    """A customer session exposes an account only - never an operator role."""
    from customer.persistence.models import BrowserSession

    account = make_account(session)
    created = login_session(sessions, account)
    live = sessions.authenticate_session(token=created.token)
    context = sessions.refresh_access_context(live)

    columns = {c.lower() for c in BrowserSession.__table__.columns.keys()}
    assert not (columns & {"role", "is_admin", "is_operator", "scopes", "permissions"})
    assert not hasattr(context, "role")
    assert context.account_id == account.id


# ---------------------------------------------------------------------------
# Helpers that need the ORM at call time
# ---------------------------------------------------------------------------


def _person_model():
    from customer.persistence.models import PersonIdentity

    return PersonIdentity
