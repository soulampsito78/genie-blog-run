"""Persistence invariants for the customer domain.

Each test names the canonical rule it defends. These run only when
CUSTOMER_TEST_DATABASE_URL points at a local PostgreSQL database; see
tests/customer_db_fixtures.py.
"""

import datetime as dt
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not installed")

from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402

from tests.customer_db_fixtures import (  # noqa: E402
    customer_engine,
    force_deferred_constraints,
    make_account,
    make_delivery_email,
    make_entitlement,
    make_payment_method,
    make_person,
    make_recipient_snapshot,
    make_subscription,
    requires_customer_db,
    session,
)

pytestmark = requires_customer_db

UTC = dt.timezone.utc

# Silence linters about fixtures imported purely for pytest's benefit.
__all__ = ["customer_engine", "session"]


# ---------------------------------------------------------------------------
# Identity - Auth spec sec. 2
# ---------------------------------------------------------------------------


def test_one_stable_identity_cannot_hold_two_active_accounts(session):
    """1 verified person = 1 active customer account."""
    person = make_person(session)
    make_account(session, person)

    with pytest.raises(IntegrityError):
        make_account(session, person)


def test_withdrawn_account_frees_the_identity_for_re_registration(session):
    """Withdrawal must allow the person to return (Lifecycle sec. 13)."""
    person = make_person(session)
    make_account(session, person, status="withdrawn")

    reopened = make_account(session, person, status="active")

    assert reopened.status == "active"


def test_stable_identity_is_unique_across_persons(session):
    """The DI-equivalent key identifies exactly one person row."""
    make_person(session, idv_stable_key="DI-shared")

    with pytest.raises(IntegrityError):
        make_person(session, idv_stable_key="DI-shared")


def test_phone_number_is_not_the_person_identity(session):
    """Two distinct verified persons may share a phone number.

    Auth spec sec. 2 forbids merging users merely because a phone matches, so
    the schema must not impose uniqueness on `mobile_e164`.
    """
    first = make_account(session, make_person(session))
    second = make_account(session, make_person(session))

    assert first.mobile_e164 == second.mobile_e164
    assert first.person_id != second.person_id


def test_adult_verification_requires_a_timestamp(session):
    from customer.persistence.models import PersonIdentity

    session.add(
        PersonIdentity(
            idv_stable_key="DI-{0}".format(uuid.uuid4().hex),
            idv_provider="test_idv",
            adult_verified=True,
            adult_verified_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_person_identity_stores_no_birthdate_column():
    """Auth spec sec. 1: do not persist full birthdate."""
    from customer.persistence.models import PersonIdentity

    columns = set(PersonIdentity.__table__.columns.keys())
    forbidden = {"birthdate", "birth_date", "dob", "date_of_birth", "resident_number"}

    assert not (columns & forbidden)


# ---------------------------------------------------------------------------
# Trial eligibility - Lifecycle sec. 3.2
# ---------------------------------------------------------------------------


def test_trial_eligibility_block_is_unique_per_stable_identity(session):
    from customer.persistence.models import TrialEligibilityBlock

    now = dt.datetime.now(UTC)

    def build():
        return TrialEligibilityBlock(
            idv_stable_key="DI-blocked",
            trial_started_at=now - dt.timedelta(days=14),
            trial_ended_at=now,
            block_expires_at=now + dt.timedelta(days=365),
        )

    session.add(build())
    session.flush()
    session.add(build())

    with pytest.raises(IntegrityError):
        session.flush()


def test_trial_eligibility_block_has_no_foreign_key_to_membership_data():
    """Evidence must be separable from operational membership data."""
    from customer.persistence.models import TrialEligibilityBlock

    assert TrialEligibilityBlock.__table__.foreign_keys == set()


def test_trial_eligibility_block_expiry_must_follow_trial_end(session):
    from customer.persistence.models import TrialEligibilityBlock

    now = dt.datetime.now(UTC)
    session.add(
        TrialEligibilityBlock(
            idv_stable_key="DI-bad-window",
            trial_started_at=now - dt.timedelta(days=14),
            trial_ended_at=now,
            block_expires_at=now - dt.timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Subscription lifecycle - Lifecycle sec. 1.1, 14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    ["trialing", "renewal_pending", "conversion_scheduled", "active", "past_due"],
)
def test_canonical_subscription_states_are_accepted(session, state):
    account = make_account(session)
    kwargs = {}
    if state in {"active", "past_due"}:
        kwargs = {"contracted_plan_code": "full_set", "price_krw": 16500}

    subscription = make_subscription(session, account, state=state, **kwargs)

    assert subscription.state == state


def test_non_canonical_subscription_state_is_rejected(session):
    """`ended` and `cancel_scheduled` are NOT canonical names."""
    account = make_account(session)

    with pytest.raises(IntegrityError):
        make_subscription(session, account, state="ended")


def test_trial_subscription_cannot_carry_a_paid_plan(session):
    """Lifecycle sec. 1.1: no contracted paid price at trial signup."""
    account = make_account(session)

    with pytest.raises(IntegrityError):
        make_subscription(
            session,
            account,
            state="trialing",
            contracted_plan_code="full_set",
            price_krw=16500,
        )


def test_conversion_scheduled_still_has_no_paid_contract(session):
    """The D-3 choice is a PENDING snapshot, not yet a contract."""
    account = make_account(session)

    with pytest.raises(IntegrityError):
        make_subscription(
            session,
            account,
            state="conversion_scheduled",
            contracted_plan_code="keysuri_korea",
            price_krw=6600,
        )


def test_active_subscription_requires_a_frozen_contract(session):
    account = make_account(session)

    with pytest.raises(IntegrityError):
        make_subscription(session, account, state="active")


def test_account_cannot_hold_two_live_subscriptions(session):
    account = make_account(session)
    make_subscription(session, account, state="trialing")

    with pytest.raises(IntegrityError):
        make_subscription(session, account, state="trialing")


def test_terminal_subscription_does_not_block_a_new_contract(session):
    """Lifecycle sec. 13: a fully ended subscription yields a NEW contract."""
    account = make_account(session)
    make_subscription(session, account, state="trial_expired")

    fresh = make_subscription(
        session, account, state="active", contracted_plan_code="today_genie", price_krw=6600
    )

    assert fresh.state == "active"


def test_frozen_contract_price_must_reference_a_real_catalog_version(session):
    """A contract may not name a price version that was never published."""
    account = make_account(session)

    with pytest.raises(IntegrityError):
        make_subscription(
            session,
            account,
            state="active",
            contracted_plan_code="full_set",
            price_krw=16500,
            price_version=99,
        )


# ---------------------------------------------------------------------------
# Plan product-set cardinality - Lifecycle sec. 1
# ---------------------------------------------------------------------------


def _add_products(session, subscription, product_codes):
    from customer.persistence.models import SubscriptionProduct

    for code in product_codes:
        session.add(
            SubscriptionProduct(subscription_id=subscription.id, product_code=code)
        )


@pytest.mark.parametrize(
    "product_codes",
    [
        (),
        ("today_genie",),
        ("today_genie", "keysuri_global", "keysuri_korea"),
    ],
    ids=["zero", "one", "three"],
)
def test_package_two_rejects_wrong_product_counts(session, product_codes):
    """package_two MUST contain exactly two distinct products."""
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="package_two", price_krw=11000
    )
    _add_products(session, subscription, product_codes)

    with pytest.raises(DBAPIError, match="requires exactly"):
        force_deferred_constraints(session)


def test_package_two_accepts_exactly_two_products(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="package_two", price_krw=11000
    )
    _add_products(session, subscription, ("today_genie", "keysuri_korea"))

    force_deferred_constraints(session)  # must not raise


def test_full_set_requires_all_three_products(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    _add_products(session, subscription, ("today_genie", "keysuri_global"))

    with pytest.raises(DBAPIError, match="requires exactly"):
        force_deferred_constraints(session)


def test_full_set_accepts_all_three_products(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    _add_products(
        session, subscription, ("today_genie", "keysuri_global", "keysuri_korea")
    )

    force_deferred_constraints(session)  # must not raise


def test_single_product_plan_rejects_a_second_product(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="keysuri_korea", price_krw=6600
    )
    _add_products(session, subscription, ("keysuri_korea", "today_genie"))

    with pytest.raises(DBAPIError, match="requires exactly"):
        force_deferred_constraints(session)


def test_conversion_snapshot_package_two_requires_two_products(session):
    from customer.persistence.models import (
        ConversionSnapshot,
        ConversionSnapshotProduct,
    )

    account = make_account(session)
    subscription = make_subscription(session, account, state="conversion_scheduled")
    snapshot = ConversionSnapshot(
        subscription_id=subscription.id,
        plan_code="package_two",
        price_krw=11000,
        price_version=1,
        currency="KRW",
        confirmed_at=dt.datetime.now(UTC),
        status="pending",
    )
    session.add(snapshot)
    session.flush()
    session.add(
        ConversionSnapshotProduct(
            conversion_snapshot_id=snapshot.id, product_code="today_genie"
        )
    )

    with pytest.raises(DBAPIError, match="requires exactly"):
        force_deferred_constraints(session)


def test_subscription_may_hold_only_one_pending_conversion_snapshot(session):
    from customer.persistence.models import ConversionSnapshot

    account = make_account(session)
    subscription = make_subscription(session, account, state="conversion_scheduled")

    def build(plan_code, price):
        return ConversionSnapshot(
            subscription_id=subscription.id,
            plan_code=plan_code,
            price_krw=price,
            price_version=1,
            currency="KRW",
            confirmed_at=dt.datetime.now(UTC),
            status="pending",
        )

    session.add(build("full_set", 16500))
    session.flush()
    session.add(build("keysuri_korea", 6600))

    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Delivery email - Delivery contract sec. 5
# ---------------------------------------------------------------------------


def test_account_cannot_hold_two_active_delivery_emails(session):
    account = make_account(session)
    make_delivery_email(session, account, status="active")

    with pytest.raises(IntegrityError):
        make_delivery_email(session, account, status="active")


def test_pending_replacement_coexists_with_the_active_address(session):
    """Delivery sec. 5.1: the old address stays active until the new verifies."""
    account = make_account(session)
    active = make_delivery_email(session, account, status="active")
    pending = make_delivery_email(session, account, status="pending_verification")

    assert active.status == "active"
    assert pending.verified_at is None


def test_delivery_email_cannot_be_active_without_verification(session):
    from customer.persistence.models import DeliveryEmail

    account = make_account(session)
    session.add(
        DeliveryEmail(
            account_id=account.id,
            email="unverified@example.com",
            status="active",
            verified_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_suppressed_delivery_email_requires_a_reason(session):
    from customer.persistence.models import DeliveryEmail

    account = make_account(session)
    session.add(
        DeliveryEmail(
            account_id=account.id,
            email="bounced@example.com",
            status="suppressed",
            verified_at=dt.datetime.now(UTC),
            suppressed_at=dt.datetime.now(UTC),
            suppression_reason=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_delivery_email_is_distinct_from_account_email():
    """They are separate tables/columns even when the values match."""
    from customer.persistence.models import CustomerAccount, DeliveryEmail

    assert "delivery_email" not in CustomerAccount.__table__.columns
    assert "account_email" not in DeliveryEmail.__table__.columns


# ---------------------------------------------------------------------------
# Entitlement - Lifecycle sec. 15 / Delivery sec. 6
# ---------------------------------------------------------------------------


def test_trial_entitlement_covers_all_three_products(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")

    for code in ("today_genie", "keysuri_global", "keysuri_korea"):
        make_entitlement(session, account, subscription, code, source="trial")

    from customer.persistence.models import Entitlement

    codes = set(
        session.scalars(
            sa.select(Entitlement.product_code).where(
                Entitlement.subscription_id == subscription.id
            )
        )
    )
    assert codes == {"today_genie", "keysuri_global", "keysuri_korea"}


def test_paid_single_product_entitlement_covers_only_that_product(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="keysuri_korea", price_krw=6600
    )
    make_entitlement(
        session,
        account,
        subscription,
        "keysuri_korea",
        source="paid",
        plan_code="keysuri_korea",
        price_version=1,
    )

    from customer.persistence.models import Entitlement

    codes = set(
        session.scalars(
            sa.select(Entitlement.product_code).where(
                Entitlement.subscription_id == subscription.id
            )
        )
    )
    assert codes == {"keysuri_korea"}


def test_trial_entitlement_cannot_name_a_paid_plan(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")

    with pytest.raises(IntegrityError):
        make_entitlement(
            session,
            account,
            subscription,
            "today_genie",
            source="trial",
            plan_code="full_set",
            price_version=1,
        )


def test_paid_entitlement_must_name_its_plan(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="today_genie", price_krw=6600
    )

    with pytest.raises(IntegrityError):
        make_entitlement(session, account, subscription, "today_genie", source="paid")


def test_duplicate_open_entitlement_for_same_product_is_rejected(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")
    make_entitlement(session, account, subscription, "today_genie")

    with pytest.raises(IntegrityError):
        make_entitlement(session, account, subscription, "today_genie")


def test_entitlement_has_no_send_result_column():
    """Entitlement existence must not be coupled to email send success."""
    from customer.persistence.models import Entitlement

    columns = set(Entitlement.__table__.columns.keys())
    forbidden = {"delivered", "sent", "send_status", "smtp_accepted", "bounced"}

    assert not (columns & forbidden)


# ---------------------------------------------------------------------------
# Recipient snapshot - Delivery contract sec. 7, 8
# ---------------------------------------------------------------------------


def _snapshot_context(session, product_code="keysuri_korea"):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")
    email = make_delivery_email(session, account, status="active")
    entitlement = make_entitlement(session, account, subscription, product_code)
    return account, subscription, entitlement, email


def test_duplicate_recipient_snapshot_for_same_delivery_key_is_rejected(session):
    """account_id + product_code + publication_date is the delivery key."""
    account, subscription, entitlement, email = _snapshot_context(session)
    publication_date = dt.date(2026, 8, 12)

    make_recipient_snapshot(
        session,
        account,
        subscription,
        entitlement,
        email,
        product_code="keysuri_korea",
        publication_date=publication_date,
    )

    with pytest.raises(IntegrityError):
        make_recipient_snapshot(
            session,
            account,
            subscription,
            entitlement,
            email,
            product_code="keysuri_korea",
            publication_date=publication_date,
        )


def test_same_account_may_receive_different_products_on_one_date(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")
    email = make_delivery_email(session, account, status="active")
    publication_date = dt.date(2026, 8, 12)

    for code in ("today_genie", "keysuri_korea"):
        entitlement = make_entitlement(session, account, subscription, code)
        make_recipient_snapshot(
            session,
            account,
            subscription,
            entitlement,
            email,
            product_code=code,
            publication_date=publication_date,
        )

    from customer.persistence.models import RecipientSnapshot

    count = session.scalar(
        sa.select(sa.func.count())
        .select_from(RecipientSnapshot)
        .where(RecipientSnapshot.account_id == account.id)
    )
    assert count == 2


def test_frozen_recipient_snapshot_cannot_be_updated(session):
    """Changes apply to the NEXT snapshot, never to a frozen one."""
    account, subscription, entitlement, email = _snapshot_context(session)
    snapshot = make_recipient_snapshot(
        session,
        account,
        subscription,
        entitlement,
        email,
        product_code="keysuri_korea",
        publication_date=dt.date(2026, 8, 12),
    )

    with pytest.raises(DBAPIError):
        session.execute(
            sa.text(
                "UPDATE recipient_snapshot SET delivery_email = :email WHERE id = :id"
            ),
            {"email": "changed@example.com", "id": snapshot.id},
        )


def test_recipient_snapshot_freezes_the_address_as_a_value(session):
    """Send time must not depend on a mutable "current email" lookup."""
    from customer.persistence.models import RecipientSnapshot

    assert "delivery_email" in RecipientSnapshot.__table__.columns
    assert not RecipientSnapshot.__table__.columns["delivery_email"].foreign_keys


# ---------------------------------------------------------------------------
# Payment method - Lifecycle sec. 5
# ---------------------------------------------------------------------------


def test_payment_method_stores_no_raw_card_data():
    """Never persist PAN, CVV, card password, or raw auth payloads."""
    from customer.persistence.models import PaymentMethod

    columns = {name.lower() for name in PaymentMethod.__table__.columns.keys()}
    forbidden = {
        "pan",
        "card_number",
        "cardnumber",
        "cvv",
        "cvc",
        "card_password",
        "card_pwd",
        "expiry",
        "expiration_date",
        "raw_auth_payload",
        "card_auth_payload",
    }

    assert not (columns & forbidden), "prohibited card column present"


def test_payment_method_keeps_only_a_provider_token_reference():
    from customer.persistence.models import PaymentMethod

    columns = set(PaymentMethod.__table__.columns.keys())

    assert "billing_key_reference" in columns
    assert "provider" in columns


def test_account_may_have_only_one_default_payment_method(session):
    account = make_account(session)
    make_payment_method(session, account, is_default=True)

    with pytest.raises(IntegrityError):
        make_payment_method(session, account, is_default=True)


def test_replacement_card_may_coexist_before_the_old_one_is_removed(session):
    """Lifecycle sec. 5.2: ADD NEW CARD BEFORE DELETE OLD CARD."""
    account = make_account(session)
    make_payment_method(session, account, is_default=True)
    replacement = make_payment_method(session, account, is_default=False)

    assert replacement.status == "active"


def test_revoked_payment_method_cannot_remain_default(session):
    from customer.persistence.models import PaymentMethod

    account = make_account(session)
    session.add(
        PaymentMethod(
            account_id=account.id,
            provider="test_pg",
            billing_key_reference="bk-revoked",
            status="revoked",
            revoked_at=dt.datetime.now(UTC),
            is_default=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Billing - Lifecycle sec. 7, 8
# ---------------------------------------------------------------------------


def _billing_attempt(session, account, subscription, **overrides):
    from customer.persistence.models import BillingAttempt

    payload = dict(
        account_id=account.id,
        subscription_id=subscription.id,
        purpose="renewal_charge",
        status="pending",
        attempt_no=1,
        billing_period_start=dt.date(2026, 9, 1),
        billing_period_end=dt.date(2026, 10, 1),
        amount_krw=16500,
        currency="KRW",
        plan_code="full_set",
        price_version=1,
        idempotency_key="idem-{0}".format(uuid.uuid4().hex),
        scheduled_at=dt.datetime.now(UTC),
    )
    payload.update(overrides)
    row = BillingAttempt(**payload)
    session.add(row)
    session.flush()
    return row


def test_billing_attempt_idempotency_key_is_unique(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    _billing_attempt(session, account, subscription, idempotency_key="idem-fixed")

    with pytest.raises(IntegrityError):
        _billing_attempt(
            session,
            account,
            subscription,
            idempotency_key="idem-fixed",
            attempt_no=2,
        )


def test_retry_slot_cannot_be_charged_twice(session):
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    _billing_attempt(session, account, subscription, attempt_no=1)

    with pytest.raises(IntegrityError):
        _billing_attempt(session, account, subscription, attempt_no=1)


def test_billing_period_can_settle_only_once(session):
    """Day 0 may fail and Day +1 succeed, but never two successes."""
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    settled = dict(
        status="succeeded",
        settled_at=dt.datetime.now(UTC),
        provider="test_pg",
    )
    _billing_attempt(
        session,
        account,
        subscription,
        attempt_no=1,
        provider_transaction_reference="tx-1",
        **settled
    )

    with pytest.raises(IntegrityError):
        _billing_attempt(
            session,
            account,
            subscription,
            attempt_no=2,
            provider_transaction_reference="tx-2",
            **settled
        )


def test_successful_charge_requires_provider_settlement_evidence(session):
    """A browser redirect is not payment success."""
    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )

    with pytest.raises(IntegrityError):
        _billing_attempt(session, account, subscription, status="succeeded")


def test_first_conversion_charge_must_reference_the_frozen_choice(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="conversion_scheduled")

    with pytest.raises(IntegrityError):
        _billing_attempt(
            session,
            account,
            subscription,
            purpose="first_conversion_charge",
            conversion_snapshot_id=None,
        )


def test_provider_webhook_replay_cannot_duplicate_a_billing_event(session):
    from customer.persistence.models import BillingEvent

    account = make_account(session)
    subscription = make_subscription(
        session, account, state="active", contracted_plan_code="full_set", price_krw=16500
    )
    attempt = _billing_attempt(session, account, subscription)

    def build():
        return BillingEvent(
            billing_attempt_id=attempt.id,
            event_type="provider_settled",
            provider_event_reference="evt-1",
        )

    session.add(build())
    session.flush()
    session.add(build())

    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Delivery events - Delivery contract sec. 17
# ---------------------------------------------------------------------------


def test_provider_accepted_and_receipt_are_distinct_event_types():
    from customer.domain.enums import DeliveryEventType

    values = set(DeliveryEventType.values())

    assert "provider_accepted" in values
    assert "delivered_evidence" in values
    assert "unknown_after_submit" in values


def test_delivery_event_rejects_an_unknown_event_type(session):
    from customer.persistence.models import DeliveryEvent

    account, subscription, entitlement, email = _snapshot_context(session)
    snapshot = make_recipient_snapshot(
        session,
        account,
        subscription,
        entitlement,
        email,
        product_code="keysuri_korea",
        publication_date=dt.date(2026, 8, 12),
    )
    session.add(
        DeliveryEvent(recipient_snapshot_id=snapshot.id, event_type="definitely_received")
    )

    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Audit - append-oriented
# ---------------------------------------------------------------------------


def test_audit_event_cannot_be_rewritten(session):
    from customer.persistence.models import AuditEvent

    account = make_account(session)
    event = AuditEvent(
        actor_type="customer",
        actor_account_id=account.id,
        account_id=account.id,
        event_type="subscription.trial_started",
        payload={"state": "trialing"},
    )
    session.add(event)
    session.flush()

    with pytest.raises(DBAPIError):
        session.execute(
            sa.text("UPDATE audit_event SET event_type = :t WHERE id = :id"),
            {"t": "tampered", "id": event.id},
        )


def test_customer_actor_audit_event_requires_an_account(session):
    from customer.persistence.models import AuditEvent

    session.add(
        AuditEvent(actor_type="customer", event_type="account.changed", payload={})
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def test_account_with_a_subscription_cannot_be_hard_deleted(session):
    """Withdrawal is a state change, not a row deletion."""
    from customer.persistence.models import CustomerAccount

    account = make_account(session)
    make_subscription(session, account, state="trialing")

    with pytest.raises(IntegrityError):
        session.execute(
            sa.delete(CustomerAccount).where(CustomerAccount.id == account.id)
        )


def test_browser_sessions_are_removed_with_their_account(session):
    from customer.persistence.models import BrowserSession, CustomerAccount

    account = make_account(session)
    now = dt.datetime.now(UTC)
    session.add(
        BrowserSession(
            account_id=account.id,
            session_token_hash="a" * 64,
            remember_login=False,
            absolute_expires_at=now + dt.timedelta(hours=12),
            inactivity_expires_at=now + dt.timedelta(hours=2),
        )
    )
    session.flush()

    session.execute(sa.delete(CustomerAccount).where(CustomerAccount.id == account.id))
    session.flush()

    remaining = session.scalar(
        sa.select(sa.func.count())
        .select_from(BrowserSession)
        .where(BrowserSession.account_id == account.id)
    )
    assert remaining == 0


def test_browser_session_inactivity_cannot_outlive_absolute_expiry(session):
    from customer.persistence.models import BrowserSession

    account = make_account(session)
    now = dt.datetime.now(UTC)
    session.add(
        BrowserSession(
            account_id=account.id,
            session_token_hash="b" * 64,
            remember_login=True,
            absolute_expires_at=now + dt.timedelta(hours=2),
            inactivity_expires_at=now + dt.timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError, match="expiry_ordering"):
        session.flush()


def test_entitlement_cannot_reference_an_unknown_product(session):
    account = make_account(session)
    subscription = make_subscription(session, account, state="trialing")

    with pytest.raises(IntegrityError):
        make_entitlement(session, account, subscription, "keysuri_mars")
