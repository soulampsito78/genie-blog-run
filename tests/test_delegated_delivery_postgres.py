"""Real migrated PostgreSQL adapter tests; never use CUSTOMER_DATABASE_URL.

The separately configured CUSTOMER_TEST_DATABASE_URL must point to an isolated
test DB. Existing repo fixtures migrate it and roll every case back.
"""
import datetime as dt
import uuid
import os

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
from sqlalchemy.orm import Session

import delegated_delivery_safety as safety
from tests.customer_db_fixtures import (customer_engine, session, requires_customer_db,
    make_account, make_subscription, make_delivery_email, make_entitlement)
from customer.persistence.models import RecipientSnapshot, DeliveryEvent, DeliveryEmail, AuditEvent
from tests.test_delegated_delivery_safety import signed_bridge_record

pytestmark = requires_customer_db
NOW = dt.datetime(2026, 9, 10, 0, 15, tzinfo=dt.timezone.utc)
DAY = NOW.astimezone(safety.KST).date()


def setup_authority(session):
    account = make_account(session)
    subscription = make_subscription(session, account)
    subscription.created_at = NOW - dt.timedelta(days=2)
    subscription.trial_start_at = NOW - dt.timedelta(days=2)
    subscription.trial_end_at = NOW + dt.timedelta(days=12)
    subscription.delivery_start_date = DAY
    email = make_delivery_email(session, account)
    email.verified_at = NOW - dt.timedelta(days=2)
    entitlement = make_entitlement(session, account, subscription, "today_genie", effective_from=DAY)
    session.flush()
    connection = session.connection()
    authority = safety.SqlAlchemyRecipientAuthority(
        session_factory=lambda: Session(bind=connection, expire_on_commit=False),
        suppression_health=lambda: True)
    return authority, account, subscription, email, entitlement


def test_real_postgres_freezes_and_revalidates_canonical_snapshot(session):
    authority, account, subscription, email, entitlement = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    assert len(plan["recipients"]) == 1
    snap = session.get(RecipientSnapshot, uuid.UUID(plan["recipients"][0]["snapshot_id"]))
    assert snap.delivery_email == email.email
    assert snap.account_id == account.id
    assert snap.entitlement_id == entitlement.id
    assert snap.subscription_id == subscription.id
    assert authority.revalidate(plan, NOW) is True
    assert safety.load_recipient_plan(plan["plan_id"]) == plan


@pytest.mark.parametrize("reason", ["unsubscribe", "complaint", "hard_bounce", "operator_manual"])
def test_real_suppression_committed_after_snapshot_blocks_final_send(session, reason):
    authority, _, _, email, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    email.status = "suppressed"
    email.suppression_reason = reason
    email.suppressed_at = NOW
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"):
        authority.revalidate(plan, NOW)


def test_real_changed_verified_address_cannot_replace_frozen_recipient(session):
    authority, account, _, email, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    email.status = "superseded"
    session.flush()
    new_email = DeliveryEmail(account_id=account.id, email="new-delivery@example.com",
        status="active", verified_at=NOW)
    session.add(new_email)
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"):
        authority.revalidate(plan, NOW)
    with pytest.raises(safety.DeliverySafetyError, match="RECIPIENT_SNAPSHOT_STATE_CONFLICT"):
        authority.prepare("today_genie", DAY, NOW)


@pytest.mark.parametrize("prior", ["provider_accepted", "unknown_after_submit", "send_attempted"])
def test_real_prior_delivery_history_reconciles_instead_of_blind_retry(session, prior):
    authority, _, _, _, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    session.add(DeliveryEvent(recipient_snapshot_id=uuid.UUID(plan["recipients"][0]["snapshot_id"]),
                             event_type=prior, occurred_at=NOW))
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="PRIOR_DELIVERY_REQUIRES_RECONCILIATION"):
        authority.revalidate(plan, NOW)


def test_real_entitlement_revocation_after_freeze_blocks(session):
    authority, _, _, _, entitlement = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    entitlement.revoked_at = NOW
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="ENTITLEMENT_NOT_EFFECTIVE"):
        authority.revalidate(plan, NOW)


def test_real_subscription_trial_end_after_freeze_blocks(session):
    authority, _, subscription, _, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    subscription.trial_end_at = NOW
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="TRIAL_NOT_EFFECTIVE"):
        authority.revalidate(plan, NOW)


def test_real_preparation_does_not_include_suppressed_recipient(session):
    authority, _, _, email, _ = setup_authority(session)
    email.status = "suppressed"
    email.suppression_reason = "unsubscribe"
    email.suppressed_at = NOW
    session.flush()
    with pytest.raises(safety.DeliverySafetyError, match="NO_ELIGIBLE_RECIPIENTS"):
        authority.prepare("today_genie", DAY, NOW)


def test_real_database_snapshot_update_trigger_is_enforced(session):
    authority, _, _, _, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    with pytest.raises(sa.exc.DBAPIError, match="append-only"):
        session.execute(sa.update(RecipientSnapshot).where(
            RecipientSnapshot.id == uuid.UUID(plan["recipients"][0]["snapshot_id"]))
            .values(delivery_email="bad@example.com"))


def signed_event(monkeypatch, account, email, reason="unsubscribe", **patch):
    return signed_bridge_record(monkeypatch, audience="genie-suppression-event", now=NOW,
        database_url=os.environ["CUSTOMER_TEST_DATABASE_URL"], patch={"account_id": str(account.id),
        "delivery_email_id": str(email.id), "event_id": "event-1234567890abcdef",
        "reason": reason, "source_reference": "isolated-authenticated-ingress", **patch})


@pytest.mark.parametrize("reason", ["unsubscribe", "complaint", "hard_bounce"])
def test_authenticated_event_updates_pg_and_blocks_final_send(session, monkeypatch, reason):
    authority, account, subscription, email, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    raw, signature = signed_event(monkeypatch, account, email, reason)
    result = safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)
    assert result == {"suppressed": True, "replayed": False, "lifecycle_followup_required": True}
    session.refresh(email)
    session.refresh(subscription)
    assert email.status == "suppressed" and email.suppression_reason == reason
    assert subscription.state == "trialing"  # No unauthorized billing/subscription mutation.
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"):
        authority.revalidate(plan, NOW)
    audit = session.scalar(sa.select(AuditEvent).where(AuditEvent.account_id == account.id))
    assert audit.payload["lifecycle_followup_required"] is True
    assert audit.payload["billing_mutated"] is False
    again = safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)
    assert again["replayed"] is True
    assert session.scalar(sa.select(sa.func.count()).select_from(AuditEvent).where(
        AuditEvent.account_id == account.id)) == 1


def test_unsigned_suppression_event_never_changes_database(session, monkeypatch):
    authority, account, _, email, _ = setup_authority(session)
    raw, signature = signed_event(monkeypatch, account, email)
    with pytest.raises(safety.DeliverySafetyError, match="AUTH_FAILED"):
        safety.apply_authenticated_suppression_event(raw + b" ", key_id="test-key", signature=signature,
            now=NOW, session_factory=authority._session_factory)
    session.refresh(email)
    assert email.status == "active"


def test_reused_event_id_different_reason_is_state_conflict(session, monkeypatch):
    authority, account, _, email, _ = setup_authority(session)
    raw, signature = signed_event(monkeypatch, account, email, "unsubscribe")
    safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)
    other, other_signature = signed_event(monkeypatch, account, email, "complaint")
    with pytest.raises(safety.DeliverySafetyError, match="SUPPRESSION_REPLAY_STATE_CONFLICT"):
        safety.apply_authenticated_suppression_event(other, key_id="test-key", signature=other_signature,
            now=NOW, session_factory=authority._session_factory)


def test_old_email_unsubscribe_stops_current_verified_address(session, monkeypatch):
    authority, account, _, email, _ = setup_authority(session)
    email.status = "superseded"
    session.flush()
    current = DeliveryEmail(account_id=account.id, email="new-address@example.com",
                            status="active", verified_at=NOW)
    session.add(current)
    session.flush()
    raw, signature = signed_event(monkeypatch, account, email, "unsubscribe")
    safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)
    session.refresh(current)
    session.refresh(email)
    assert current.status == email.status == "suppressed"


def test_old_address_hardbounce_does_not_suppress_verified_replacement(session, monkeypatch):
    authority, account, _, email, _ = setup_authority(session)
    email.status = "superseded"
    session.flush()
    current = DeliveryEmail(account_id=account.id, email="new-address@example.com",
                            status="active", verified_at=NOW)
    session.add(current)
    session.flush()
    raw, signature = signed_event(monkeypatch, account, email, "hard_bounce")
    safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)
    session.refresh(current)
    session.refresh(email)
    assert current.status == "active"
    assert email.status == "suppressed"


@pytest.mark.parametrize("previous,incoming,effective", [
    ("complaint", "hard_bounce", "complaint"),
    ("unsubscribe", "hard_bounce", "unsubscribe"),
    ("operator_manual", "hard_bounce", "operator_manual"),
    ("operator_manual", "unsubscribe", "operator_manual"),
    ("operator_manual", "complaint", "operator_manual"),
    ("hard_bounce", "complaint", "complaint"),
    ("complaint", "unsubscribe", "complaint"),
    ("complaint", "complaint", "complaint"),
])
def test_later_suppression_preserves_stronger_hold_and_first_timestamp(
        session, monkeypatch, previous, incoming, effective):
    authority, account, _, email, _ = setup_authority(session)
    plan = authority.prepare("today_genie", DAY, NOW)
    first_suppressed_at = NOW - dt.timedelta(hours=1)
    email.status = "suppressed"
    email.suppression_reason = previous
    email.suppressed_at = first_suppressed_at
    session.flush()

    raw, signature = signed_event(monkeypatch, account, email, incoming)
    safety.apply_authenticated_suppression_event(raw, key_id="test-key", signature=signature,
        now=NOW, session_factory=authority._session_factory)

    session.refresh(email)
    assert email.status == "suppressed"
    assert email.suppression_reason == effective
    assert email.suppressed_at == first_suppressed_at
    audit = session.scalar(sa.select(AuditEvent).where(AuditEvent.account_id == account.id))
    assert audit.payload["incoming_reason"] == incoming
    assert audit.payload["effective_reason_counts"] == {effective: 1}
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"):
        authority.revalidate(plan, NOW)
