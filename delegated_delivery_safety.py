"""Staged final recipient and durable publication boundary; no automatic activation.

The adapter reads the existing PostgreSQL customer authority, never the legacy
environment/beta address list. Provider submission is a caller-owned operation:
this module grants no review/owner authority and installs no route or scheduler.
Missing database, migration reconciliation, or suppression integration fails
closed. Atomic claims survive crashes and are never silently released.
"""
from __future__ import annotations

import datetime as dt
import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
PRODUCTS = {"today_genie": "today_genie", "keysuri_global_tech": "keysuri_global",
            "keysuri_korea_tech": "keysuri_korea", "keysuri_global": "keysuri_global",
            "keysuri_korea": "keysuri_korea"}
SCHEMA = "delegated-delivery-v1"


class DeliverySafetyError(RuntimeError):
    """A stable, non-PII reason suitable for a fail-closed owner packet."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _instant(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise DeliverySafetyError("AWARE_CLOCK_REQUIRED")
    return value.astimezone(dt.timezone.utc)


def _day(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        raise DeliverySafetyError("PUBLICATION_DATE_REQUIRED")
    try:
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DeliverySafetyError("PUBLICATION_DATE_REQUIRED")


def _product(mode: str) -> str:
    if mode not in PRODUCTS:
        raise DeliverySafetyError("UNSUPPORTED_PRODUCT")
    return PRODUCTS[mode]


def evaluate_eligibility(account, subscription, email, entitlement, *, product_code,
                         publication_date, now, subscription_products=()) -> str:
    """Evaluate actual model rows. This pure function is not a trust boundary."""
    from genie_schedule_policy import holiday_calendar_covers, is_korean_publishing_day
    from customer.domain.email import is_valid_email
    now = _instant(now)
    day = _day(publication_date)
    if not holiday_calendar_covers(day):
        return "CALENDAR_UNAVAILABLE"
    if not is_korean_publishing_day(day):
        return "NOT_PUBLICATION_DAY"
    if day != now.astimezone(KST).date():
        return "STALE_PUBLICATION"
    if account.status != "active" or account.withdrawn_at is not None:
        return "ACCOUNT_INELIGIBLE"
    if email.account_id != account.id or subscription.account_id != account.id:
        return "ACCOUNT_IDENTITY_CONFLICT"
    if email.status != "active" or email.verified_at is None:
        return "DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"
    if (_instant(email.verified_at) > now or not is_valid_email(email.email)
            or email.email != email.email.strip().lower()):
        return "DELIVERY_EMAIL_INVALID"
    if any((email.suppression_reason, email.suppressed_at, email.deactivated_at)):
        return "DELIVERY_SUPPRESSED"
    if (entitlement.account_id != account.id or entitlement.subscription_id != subscription.id
            or entitlement.product_code != product_code):
        return "ENTITLEMENT_IDENTITY_CONFLICT"
    if (entitlement.revoked_at is not None or day < entitlement.effective_from
            or (entitlement.effective_to is not None and day > entitlement.effective_to)):
        return "ENTITLEMENT_NOT_EFFECTIVE"
    if day < subscription.delivery_start_date:
        return "DELIVERY_NOT_STARTED"
    # Defend malformed legacy rows as well as relying on trial service rules.
    if day <= _instant(subscription.created_at).astimezone(KST).date():
        return "SAME_DAY_SUBSCRIPTION"
    if subscription.ended_at is not None:
        return "SUBSCRIPTION_ENDED"
    for boundary in (subscription.cancellation_effective_at, subscription.withdrawal_effective_at):
        if boundary is not None and now >= _instant(boundary):
            return "SUBSCRIPTION_END_EFFECTIVE"
    state = subscription.state
    if state in {"trialing", "renewal_pending", "conversion_scheduled"}:
        if (entitlement.source != "trial" or subscription.contracted_plan_code is not None
                or subscription.trial_start_at is None or subscription.trial_end_at is None
                or not _instant(subscription.trial_start_at) <= now < _instant(subscription.trial_end_at)):
            return "TRIAL_NOT_EFFECTIVE"
    elif state in {"active", "past_due", "cancellation_scheduled", "withdrawal_scheduled"}:
        if (entitlement.source != "paid" or not subscription.contracted_plan_code
                or entitlement.plan_code != subscription.contracted_plan_code
                or entitlement.price_version != subscription.contracted_price_version
                or product_code not in set(subscription_products)):
            return "PAID_CONTRACT_PRODUCT_MISMATCH"
        if subscription.current_period_start is None or day < subscription.current_period_start:
            return "PAID_PERIOD_NOT_STARTED"
        if state == "past_due":
            if (subscription.next_billing_at is None or
                    now > _instant(subscription.next_billing_at) + dt.timedelta(days=3)):
                return "RENEWAL_GRACE_EXPIRED"
        elif subscription.current_period_end is None or day >= subscription.current_period_end:
            return "PAID_PERIOD_ENDED"
    else:
        return "SUBSCRIPTION_INELIGIBLE"
    return "ELIGIBLE"


class SqlAlchemyRecipientAuthority:
    """Actual existing-schema adapter, usable only after controlled integration.

    ``suppression_health`` is an integration-owned probe, not a reviewer field.
    It must establish that the authenticated unsubscribe/complaint/bounce
    ingestors feeding this database are healthy. The repository currently has
    no such ingestor, therefore the default is deliberately unavailable.
    """

    def __init__(self, session_factory=None, suppression_health: Optional[Callable] = None):
        self._session_factory = session_factory
        self._suppression_health = suppression_health

    def _session(self):
        if self._suppression_health is None or self._suppression_health() is not True:
            raise DeliverySafetyError("SUPPRESSION_INGESTION_UNVERIFIED")
        try:
            from customer.persistence.session import customer_session_factory
            factory = self._session_factory or customer_session_factory()
            session = factory()
            if session.get_bind().dialect.name != "postgresql":
                session.close()
                raise DeliverySafetyError("POSTGRESQL_AUTHORITY_REQUIRED")
            return session
        except DeliverySafetyError:
            raise
        except Exception as exc:
            raise DeliverySafetyError("CUSTOMER_DATABASE_UNAVAILABLE") from exc

    @staticmethod
    def _rows(session, product):
        import sqlalchemy as sa
        from customer.persistence.models import CustomerAccount, Subscription, DeliveryEmail, Entitlement
        return session.execute(sa.select(CustomerAccount, Subscription, DeliveryEmail, Entitlement)
            .join(Subscription, Subscription.account_id == CustomerAccount.id)
            .join(DeliveryEmail, DeliveryEmail.account_id == CustomerAccount.id)
            .join(Entitlement, sa.and_(Entitlement.subscription_id == Subscription.id,
                                      Entitlement.account_id == CustomerAccount.id))
            .where(Entitlement.product_code == product, DeliveryEmail.status == "active",
                   CustomerAccount.status == "active", Entitlement.revoked_at.is_(None))).all()

    @staticmethod
    def _products(session, subscription):
        import sqlalchemy as sa
        from customer.persistence.models import SubscriptionProduct
        return tuple(session.scalars(sa.select(SubscriptionProduct.product_code).where(
            SubscriptionProduct.subscription_id == subscription.id)))

    def prepare(self, mode, publication_date, now):
        """Freeze eligible recipients in canonical immutable RecipientSnapshot rows.

        This is a staged production-data mutation and is not executed on a live
        DB by the preparation task. Existing snapshots are retained unchanged.
        """
        product, day, now = _product(mode), _day(publication_date), _instant(now)
        session = self._session()
        from customer.persistence.models import RecipientSnapshot, DeliveryEvent
        import sqlalchemy as sa
        recipients, excluded, seen = [], {}, set()
        try:
            for account, subscription, email, entitlement in self._rows(session, product):
                reason = evaluate_eligibility(account, subscription, email, entitlement,
                    product_code=product, publication_date=day, now=now,
                    subscription_products=self._products(session, subscription))
                if reason != "ELIGIBLE":
                    excluded[reason] = excluded.get(reason, 0) + 1
                    continue
                if account.id in seen:
                    raise DeliverySafetyError("AMBIGUOUS_ACCOUNT_ENTITLEMENT")
                seen.add(account.id)
                snap = session.scalar(sa.select(RecipientSnapshot).where(
                    RecipientSnapshot.account_id == account.id,
                    RecipientSnapshot.product_code == product,
                    RecipientSnapshot.publication_date == day))
                if snap is None:
                    snap = RecipientSnapshot(id=uuid.uuid4(), account_id=account.id,
                        subscription_id=subscription.id, product_code=product, publication_date=day,
                        delivery_email=email.email, delivery_email_id=email.id,
                        entitlement_id=entitlement.id, entitlement_source=entitlement.source,
                        plan_code=entitlement.plan_code, price_version=entitlement.price_version,
                        subscription_state_at_snapshot=subscription.state,
                        billing_state_at_snapshot=subscription.state, frozen_at=now)
                    session.add(snap)
                    session.flush()
                    session.add(DeliveryEvent(recipient_snapshot_id=snap.id,
                        event_type="snapshot_frozen", occurred_at=now,
                        detail={"authority": "DELEGATED_WORK_REVIEW_PREPARATION"}))
                # Changing the address after a freeze does not mutate or duplicate
                # this publication. A later publication may select the new address.
                if (snap.subscription_id != subscription.id or snap.delivery_email_id != email.id
                        or snap.delivery_email != email.email or snap.entitlement_id != entitlement.id):
                    raise DeliverySafetyError("RECIPIENT_SNAPSHOT_STATE_CONFLICT")
                recipients.append({"account_id": str(account.id), "snapshot_id": str(snap.id),
                    "subscription_id": str(subscription.id), "delivery_email": snap.delivery_email,
                    "delivery_email_id": str(snap.delivery_email_id),
                    "entitlement_id": str(snap.entitlement_id)})
            if not recipients:
                raise DeliverySafetyError("NO_ELIGIBLE_RECIPIENTS")
            recipients.sort(key=lambda row: row["account_id"])
            plan = {"schema": SCHEMA, "product_code": product, "publication_date": day.isoformat(),
                    "frozen_at": now.isoformat(), "recipients": recipients,
                    "excluded_reason_counts": excluded}
            plan["sha256"] = _digest(plan)
            plan["plan_id"] = "recipient_" + plan["sha256"]
            session.commit()
            import admin_safety_store as store
            if not store._create_json_once("delegated_recipient_plans/" + plan["plan_id"] + ".json", plan):
                if store._read_json("delegated_recipient_plans/" + plan["plan_id"] + ".json") != plan:
                    raise DeliverySafetyError("RECIPIENT_PLAN_STORE_CONFLICT")
            return plan
        except DeliverySafetyError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            raise DeliverySafetyError("RECIPIENT_AUTHORITY_FAILURE") from exc
        finally:
            session.close()

    def revalidate(self, plan, now):
        """Read committed authority immediately before the provider handoff.

        This does not hold a DB transaction across the network. A suppression
        committed after this boundary cannot retract a provider submission.
        """
        plan = load_recipient_plan(plan["plan_id"], expected_sha256=plan["sha256"])
        now = _instant(now)
        session = self._session()
        from customer.persistence.models import (RecipientSnapshot, CustomerAccount, Subscription,
                                                  DeliveryEmail, Entitlement, DeliveryEvent)
        import sqlalchemy as sa
        try:
            for recipient in plan["recipients"]:
                snap = session.get(RecipientSnapshot, uuid.UUID(recipient["snapshot_id"]))
                if (snap is None or str(snap.account_id) != recipient["account_id"]
                        or snap.delivery_email != recipient["delivery_email"]
                        or str(snap.delivery_email_id) != recipient["delivery_email_id"]
                        or str(snap.entitlement_id) != recipient["entitlement_id"]
                        or str(snap.subscription_id) != recipient["subscription_id"]
                        or snap.product_code != plan["product_code"]
                        or snap.publication_date.isoformat() != plan["publication_date"]):
                    raise DeliverySafetyError("RECIPIENT_SNAPSHOT_STATE_CONFLICT")
                rows = [session.get(model, key) for model, key in (
                    (CustomerAccount, snap.account_id), (Subscription, snap.subscription_id),
                    (DeliveryEmail, snap.delivery_email_id), (Entitlement, snap.entitlement_id))]
                if any(row is None for row in rows):
                    raise DeliverySafetyError("RECIPIENT_AUTHORITY_INCOMPLETE")
                reason = evaluate_eligibility(*rows, product_code=plan["product_code"],
                    publication_date=plan["publication_date"], now=now,
                    subscription_products=self._products(session, rows[1]))
                if reason != "ELIGIBLE":
                    raise DeliverySafetyError(reason)
                if rows[2].email != snap.delivery_email:
                    raise DeliverySafetyError("DELIVERY_EMAIL_CHANGED_AFTER_FREEZE")
                prior = tuple(session.scalars(sa.select(DeliveryEvent.event_type).where(
                    DeliveryEvent.recipient_snapshot_id == snap.id,
                    DeliveryEvent.event_type.in_(["provider_accepted", "delivered_evidence",
                        "send_attempted", "unknown_after_submit", "hard_bounce", "complaint", "suppressed"]))))
                if prior:
                    raise DeliverySafetyError("PRIOR_DELIVERY_REQUIRES_RECONCILIATION")
            return True
        except DeliverySafetyError:
            raise
        except Exception as exc:
            raise DeliverySafetyError("RECIPIENT_AUTHORITY_FAILURE") from exc
        finally:
            session.close()


def load_recipient_plan(plan_id, expected_sha256=None):
    import admin_safety_store as store
    if not re.fullmatch(r"recipient_[a-f0-9]{64}", str(plan_id)):
        raise DeliverySafetyError("INVALID_RECIPIENT_PLAN")
    plan = store._read_json("delegated_recipient_plans/" + plan_id + ".json")
    if not isinstance(plan, dict):
        raise DeliverySafetyError("RECIPIENT_PLAN_UNAVAILABLE")
    payload = {k: v for k, v in plan.items() if k not in {"plan_id", "sha256"}}
    digest = _digest(payload)
    if (plan.get("sha256") != digest or plan_id != "recipient_" + digest
            or (expected_sha256 is not None and digest != expected_sha256)):
        raise DeliverySafetyError("RECIPIENT_PLAN_CHANGED")
    recipients = plan.get("recipients")
    if (plan.get("schema") != SCHEMA or not isinstance(recipients, list) or not recipients
            or len({r["account_id"] for r in recipients}) != len(recipients)):
        raise DeliverySafetyError("INVALID_RECIPIENT_PLAN")
    return plan


def publication_guard_required():
    """A kill switch never disables an already-installed publication ledger."""
    import admin_safety_store as store
    configured = (os.getenv("DELEGATED_SEND_MODE", "OFF").upper() == "ON" or
                  os.getenv("GENIE_PUBLICATION_GUARD_ENFORCED", "").upper() in {"1", "TRUE", "ON"})
    try:
        key = "publication_cutover/v1.json"
        exists = (store._get_gcs_bucket().blob(store.SAFETY_PREFIX + "/" + key).exists()
                  if store._uses_gcs_backend() else store._local_path(key).exists())
        if exists and store._read_json(key) is None:
            raise DeliverySafetyError("CUTOVER_RECORD_UNREADABLE")
        return configured or exists
    except DeliverySafetyError:
        raise
    except Exception as exc:
        raise DeliverySafetyError("PUBLICATION_GUARD_STORE_UNAVAILABLE") from exc


def recipient_authority():
    """Configured authority factory; unknown selectors fail closed."""
    selector = os.getenv("GENIE_RECIPIENT_AUTHORITY", "CUSTOMER_DATABASE").strip().upper()
    if selector == "ADMIN_BETA_DELEGATION":
        from admin_beta_delegation import AdminBetaRecipientAuthority

        return AdminBetaRecipientAuthority()
    if selector != "CUSTOMER_DATABASE":
        raise DeliverySafetyError("RECIPIENT_AUTHORITY_CONFIG_INVALID")
    return SqlAlchemyRecipientAuthority(suppression_health=suppression_ingestion_healthy)


SUPPRESSION_FEEDS = frozenset({"unsubscribe", "complaint", "hard_bounce"})
# Delivery contract sections 10, 12 and 13 give complaint/unsubscribe stricter
# recovery requirements than address hard-bounce. Ingestion cannot release an
# operator hold; only the separate authorized recovery flow may clear it.
_SUPPRESSION_PRECEDENCE = {"hard_bounce": 0, "unsubscribe": 1, "complaint": 2, "operator_manual": 3}


def _suppression_bridge_keys():
    """Trusted service configuration. Keys/feeds are never taken from an event."""
    try:
        keys = json.loads(os.getenv("GENIE_SUPPRESSION_BRIDGE_KEYS", "{}"))
        if not isinstance(keys, dict):
            raise ValueError()
        result = {}
        for key_id, record in keys.items():
            secret = base64.b64decode(record["secret_b64"], validate=True)
            feeds = frozenset(record["allowed_feeds"])
            if (len(secret) < 32 or not record["principal"] or not feeds
                    or not feeds <= SUPPRESSION_FEEDS):
                raise ValueError()
            result[key_id] = {"secret": secret, "principal": record["principal"], "feeds": feeds}
        return result
    except (TypeError, ValueError, KeyError):
        raise DeliverySafetyError("SUPPRESSION_BRIDGE_CONFIG_INVALID")


def _authenticate_suppression_record(raw, *, key_id, signature, audience, now):
    """Authenticate exact bridge bytes; different audiences cannot substitute."""
    now = _instant(now)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 32768:
        raise DeliverySafetyError("SUPPRESSION_EVENT_INVALID")
    key = _suppression_bridge_keys().get(key_id)
    if not key or not isinstance(signature, str):
        raise DeliverySafetyError("SUPPRESSION_BRIDGE_AUTH_FAILED")
    expected = hmac.new(key["secret"], b"GENIE_SUPPRESSION_V1\n" + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise DeliverySafetyError("SUPPRESSION_BRIDGE_AUTH_FAILED")
    try:
        record = json.loads(raw)
        issued = _instant(dt.datetime.fromisoformat(record["issued_at"]))
        expires = _instant(dt.datetime.fromisoformat(record["expires_at"]))
        database_url = os.getenv("CUSTOMER_DATABASE_URL", "").strip()
        authority_id = os.getenv("GENIE_CUSTOMER_AUTHORITY_ID", "").strip()
        if (record.get("schema") != SCHEMA or record.get("audience") != audience
                or record.get("key_id") != key_id or record.get("principal") != key["principal"]
                or not authority_id or record.get("authority_id") != authority_id
                or not database_url or record.get("database_fingerprint") != hashlib.sha256(database_url.encode()).hexdigest()
                or not issued <= now < expires or expires - issued > dt.timedelta(minutes=5)):
            raise ValueError()
        if audience == "genie-suppression-health":
            if key["feeds"] != SUPPRESSION_FEEDS or set(record["streams"]) != SUPPRESSION_FEEDS:
                raise ValueError()
            for feed in SUPPRESSION_FEEDS:
                stream = record["streams"][feed]
                checked = _instant(dt.datetime.fromisoformat(stream["checked_at"]))
                if (stream.get("state") != "AUTHENTICATED_AND_CHECKPOINTED"
                        or not stream.get("checkpoint") or not stream.get("source_reference")
                        or not now - dt.timedelta(minutes=5) <= checked <= issued):
                    raise ValueError()
        elif audience == "genie-suppression-event":
            if (record.get("reason") not in key["feeds"]
                    or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", record.get("event_id", ""))
                    or not record.get("source_reference")):
                raise ValueError()
            uuid.UUID(record["account_id"])
            uuid.UUID(record["delivery_email_id"])
        else:
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DeliverySafetyError("SUPPRESSION_EVIDENCE_INVALID_OR_STALE")


def record_authenticated_suppression_health(raw, *, key_id, signature, now):
    """Trusted bridge heartbeat entrypoint, with signed per-feed checkpoints.

    No route/scheduler is installed. Integration invokes this after authenticated
    one-click unsubscribe and provider complaint/bounce sources are checkpointed.
    A valid signature proves bridge identity, not that a dishonest bridge is
    truthful: deployment must verify its real event-to-database path.
    """
    import admin_safety_store as store
    record = _authenticate_suppression_record(raw, key_id=key_id, signature=signature,
        audience="genie-suppression-health", now=now)
    envelope = {"raw_b64": base64.b64encode(raw).decode(), "key_id": key_id, "signature": signature}
    store._create_json_once("suppression_health_evidence/" + hashlib.sha256(raw).hexdigest() + ".json", envelope)
    store._write_json("suppression_health/current.json", envelope)
    return {"stored": True, "principal": record["principal"], "expires_at": record["expires_at"]}


def suppression_ingestion_healthy(now=None):
    """Fail closed if any authenticated source/checkpoint/auth has expired."""
    import admin_safety_store as store
    try:
        envelope = store._read_json("suppression_health/current.json")
        if not envelope:
            return False
        raw = base64.b64decode(envelope["raw_b64"], validate=True)
        _authenticate_suppression_record(raw, key_id=envelope["key_id"], signature=envelope["signature"],
            audience="genie-suppression-health", now=now or dt.datetime.now(dt.timezone.utc))
        return True
    except Exception:
        return False


def apply_authenticated_suppression_event(raw, *, key_id, signature, now, session_factory=None):
    """Idempotently stop the briefing stream using real authoritative DB rows.

    This narrow delivery adapter does not delete payment tokens or alter billing;
    it appends a lifecycle follow-up requirement for the existing billing worker.
    Re-consent/address replacement never occurs through this event entrypoint.
    """
    event = _authenticate_suppression_record(raw, key_id=key_id, signature=signature,
        audience="genie-suppression-event", now=now)
    # The ingestor must operate even if health has expired so suppression can
    # recover safely. It still requires exact authenticated bridge event evidence.
    authority = SqlAlchemyRecipientAuthority(session_factory=session_factory, suppression_health=lambda: True)
    session = authority._session()
    import sqlalchemy as sa
    from customer.persistence.models import CustomerAccount, DeliveryEmail, CommandIdempotency, AuditEvent
    try:
        account_id, email_id = uuid.UUID(event["account_id"]), uuid.UUID(event["delivery_email_id"])
        account = session.scalar(sa.select(CustomerAccount).where(CustomerAccount.id == account_id).with_for_update())
        email = session.scalar(sa.select(DeliveryEmail).where(DeliveryEmail.id == email_id).with_for_update())
        if account is None or email is None or email.account_id != account_id:
            raise DeliverySafetyError("SUPPRESSION_ACCOUNT_IDENTITY_CONFLICT")
        command_key = _digest([event["principal"], event["event_id"]])
        fingerprint = hashlib.sha256(raw).hexdigest()
        existing = session.scalar(sa.select(CommandIdempotency).where(
            CommandIdempotency.command == "briefing/suppress", CommandIdempotency.idempotency_key == command_key))
        if existing is not None:
            if existing.request_fingerprint != fingerprint or existing.account_id != account_id:
                raise DeliverySafetyError("SUPPRESSION_REPLAY_STATE_CONFLICT")
            return {"suppressed": True, "replayed": True, "lifecycle_followup_required": True}
        targets = [email]
        if event["reason"] in {"unsubscribe", "complaint"}:
            # An unsubscribe from an older received briefing still stops the
            # account's current briefing address after a verified address change.
            targets = list(session.scalars(sa.select(DeliveryEmail).where(
                DeliveryEmail.account_id == account_id).with_for_update()))
        effective_reason_counts = {}
        for target in targets:
            previous_reason = target.suppression_reason
            incoming_reason = event["reason"]
            effective_reason = (previous_reason
                if _SUPPRESSION_PRECEDENCE.get(previous_reason, -1) >= _SUPPRESSION_PRECEDENCE[incoming_reason]
                else incoming_reason)
            target.status = "suppressed"
            target.suppression_reason = effective_reason
            # A later provider event must not hide when suppression first began.
            target.suppressed_at = target.suppressed_at or _instant(now)
            target.updated_at = _instant(now)
            effective_reason_counts[effective_reason] = effective_reason_counts.get(effective_reason, 0) + 1
        session.add(CommandIdempotency(account_id=account_id, command="briefing/suppress",
            idempotency_key=command_key, request_fingerprint=fingerprint, status="completed",
            result_reference=str(email_id), completed_at=_instant(now)))
        session.add(AuditEvent(actor_type="system", account_id=account_id,
            event_type="briefing_suppression_applied", entity_type="delivery_email", entity_id=str(email_id),
            occurred_at=_instant(now), payload={"incoming_reason": event["reason"],
                "effective_reason_counts": effective_reason_counts, "principal": event["principal"],
                "source_reference": event["source_reference"], "event_id": event["event_id"],
                "lifecycle_followup_required": True, "billing_mutated": False}))
        session.commit()
        return {"suppressed": True, "replayed": False, "lifecycle_followup_required": True}
    except DeliverySafetyError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise DeliverySafetyError("SUPPRESSION_DATABASE_FAILURE") from exc
    finally:
        session.close()


def manual_recipient_plan(*, run_id, mode, now):
    """Freeze/reuse the canonical recipient plan before manual confirmation."""
    import admin_safety_store as store
    from admin_store import validate_run_id
    if not validate_run_id(run_id):
        raise DeliverySafetyError("INVALID_ATTEMPT_IDENTITY")
    key = "manual_recipient_plan_bindings/" + _digest(run_id) + ".json"
    binding = store._read_json(key)
    authority = recipient_authority()
    if binding is None:
        # Same run always retains its original plan once created. A racing
        # creator must load the winner; it may not replace the frozen target.
        day = dt.datetime.strptime(run_id[:8], "%Y%m%d").date()
        plan = authority.prepare(mode, day, now)
        proposed = {"plan_id": plan["plan_id"], "sha256": plan["sha256"]}
        store._create_json_once(key, proposed)
        binding = store._read_json(key)
    if not binding:
        raise DeliverySafetyError("RECIPIENT_PLAN_UNAVAILABLE")
    plan = load_recipient_plan(binding["plan_id"], expected_sha256=binding["sha256"])
    authority.revalidate(plan, now)
    return plan


def manual_publication_guard(*, run_id, snapshot, prepared_recipients, now):
    """Manual approval uses the same claims after cutover, even with mode OFF."""
    if not publication_guard_required():
        return {"required": False, "allowed": True}
    plan = load_recipient_plan(snapshot.get("recipient_plan_id"),
                               expected_sha256=snapshot.get("recipient_plan_sha256"))
    if prepared_recipients != [row["delivery_email"] for row in plan["recipients"]]:
        raise DeliverySafetyError("RECIPIENT_SNAPSHOT_STATE_CONFLICT")
    recipient_authority().revalidate(plan, now)
    reservation = reserve_publication_attempt(plan, run_id=run_id,
        candidate_sha256=snapshot.get("approval_target_sha256"),
        review_id=snapshot.get("approval_snapshot_id"), now=now, approval_source="HUMAN_OWNER")
    return dict(reservation, required=True, plan=plan)


def revalidate_manual_publication(guard, *, now):
    if guard.get("required"):
        recipient_authority().revalidate(guard["plan"], now)
    return True


def record_publication_reconciliation(*, mode, publication_date, inventory_sha256,
        prior_outcome, evidence_refs, operator_id, legacy_writers_drained):
    """Migration/manual integration entrypoint, never exposed to the reviewer.

    A complete durable legacy inventory must establish NO_SUBMISSION_CONFIRMED
    before this publication is first eligible. ACCEPTED or UNKNOWN are retained
    as blocking evidence. No timeout/retry/reissue can turn those states into PASS.
    """
    import admin_safety_store as store
    if (prior_outcome not in {"NO_SUBMISSION_CONFIRMED", "PROVIDER_ACCEPTED", "UNKNOWN_AFTER_SUBMIT"}
            or legacy_writers_drained is not True or not operator_id or not evidence_refs
            or not re.fullmatch(r"[a-f0-9]{64}", str(inventory_sha256))):
        raise DeliverySafetyError("RECONCILIATION_EVIDENCE_REQUIRED")
    product, day = _product(mode), _day(publication_date).isoformat()
    record = {"schema": SCHEMA, "product_code": product, "publication_date": day,
        "inventory_sha256": inventory_sha256, "prior_outcome": prior_outcome,
        "evidence_refs": list(evidence_refs), "operator_id": operator_id,
        "legacy_writers_drained": True}
    key = "publication_reconciliation/" + _digest([product, day]) + ".json"
    if not store._create_json_once(key, record) and store._read_json(key) != record:
        raise DeliverySafetyError("RECONCILIATION_STATE_CONFLICT")
    return record


def record_delivery_cutover(*, starts_on, inventory_sha256, evidence_refs, operator_id,
                            all_writers_use_publication_guard):
    """One controlled activation record permits unattended future publications.

    Integration must drain old writers, reconcile all publications before this
    date, and route BOTH manual and delegated sends through the shared claim.
    This task prepares this function but never writes production cutover state.
    The record cannot be rewritten by review retries or normal operation.
    """
    import admin_safety_store as store
    if (all_writers_use_publication_guard is not True or not operator_id or not evidence_refs
            or not re.fullmatch(r"[a-f0-9]{64}", str(inventory_sha256))):
        raise DeliverySafetyError("CUTOVER_EVIDENCE_REQUIRED")
    record = {"schema": SCHEMA, "starts_on": _day(starts_on).isoformat(),
        "inventory_sha256": inventory_sha256, "evidence_refs": list(evidence_refs),
        "operator_id": operator_id, "all_writers_use_publication_guard": True}
    key = "publication_cutover/v1.json"
    if not store._create_json_once(key, record) and store._read_json(key) != record:
        raise DeliverySafetyError("CUTOVER_STATE_CONFLICT")
    return record


def reserve_publication_attempt(plan, *, run_id, candidate_sha256, review_id, now,
                                approval_source="DELEGATED_WORK_REVIEW"):
    """At most one participating provider handoff per product/date/account.

    Shared GCS create-if-absent is authoritative in production. Publication,
    account, and address claims are monotonic; partial reservations fail closed.
    A held review makes no reservation, so its newly reviewed manual reissue can
    proceed if the publication has never reached this submission boundary.
    """
    import admin_safety_store as store
    from admin_store import validate_run_id
    plan = load_recipient_plan(plan["plan_id"], expected_sha256=plan["sha256"])
    if (not validate_run_id(run_id) or not review_id
            or approval_source not in {"DELEGATED_WORK_REVIEW", "HUMAN_OWNER"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(candidate_sha256))):
        raise DeliverySafetyError("INVALID_ATTEMPT_IDENTITY")
    product, day = plan["product_code"], plan["publication_date"]
    run_mode = run_id[16:-9]
    if PRODUCTS.get(run_mode) != product or run_id[:8] != day.replace("-", ""):
        raise DeliverySafetyError("RUN_PUBLICATION_IDENTITY_CONFLICT")
    if day != _instant(now).astimezone(KST).date().isoformat():
        raise DeliverySafetyError("STALE_PUBLICATION")
    reconciliation = store._read_json("publication_reconciliation/" + _digest([product, day]) + ".json")
    if reconciliation:
        if (reconciliation.get("prior_outcome") != "NO_SUBMISSION_CONFIRMED"
                or reconciliation.get("legacy_writers_drained") is not True):
            raise DeliverySafetyError("LEGACY_PUBLICATION_RECONCILIATION_REQUIRED")
    else:
        cutover = store._read_json("publication_cutover/v1.json")
        if (not cutover or cutover.get("all_writers_use_publication_guard") is not True
                or day < cutover.get("starts_on", "9999-12-31")):
            raise DeliverySafetyError("LEGACY_PUBLICATION_RECONCILIATION_REQUIRED")
    attempt_id = "publication_" + _digest([product, day])
    record = {"schema": SCHEMA, "attempt_id": attempt_id, "run_id": run_id,
        "product_code": product, "publication_date": day,
        "candidate_sha256": candidate_sha256, "review_id": review_id,
        "recipient_plan_id": plan["plan_id"], "recipient_plan_sha256": plan["sha256"],
        "approval_source": approval_source, "attempted_at": _instant(now).isoformat(),
        "status": "RESERVED_OUTCOME_UNKNOWN", "provider_exactly_once": False}
    key = "publication_attempts/" + attempt_id + ".json"
    if not store._create_json_once(key, record):
        return {"allowed": False, "reason": "PUBLICATION_ALREADY_RESERVED_RECONCILE",
                "attempt_id": attempt_id}
    for recipient in plan["recipients"]:
        # Account key persists across verified address changes; address key also
        # avoids duplicate BCC deliveries if two accounts share a delivery email.
        for kind, identity in (("account", recipient["account_id"]),
                               ("address", recipient["delivery_email"].strip().lower())):
            claim = "publication_recipient_claims/" + _digest([kind, identity, product, day]) + ".json"
            if not store._create_json_once(claim, record):
                return {"allowed": False, "reason": "RECIPIENT_ALREADY_RESERVED_RECONCILE",
                        "attempt_id": attempt_id}
    return {"allowed": True, "reason": "RESERVED", "attempt_id": attempt_id}


def complete_publication_attempt(attempt_id, *, outcome, evidence):
    """Append a single immutable provider outcome; accepted never means received."""
    import admin_safety_store as store
    if (not re.fullmatch(r"publication_[a-f0-9]{64}", str(attempt_id))
            or outcome not in {"PROVIDER_ACCEPTED", "PROVIDER_REJECTED", "UNKNOWN_AFTER_SUBMIT",
                               "NOT_SUBMITTED_FINAL_GUARD_BLOCKED"}):
        raise DeliverySafetyError("INVALID_PROVIDER_OUTCOME")
    attempt = store._read_json("publication_attempts/" + attempt_id + ".json")
    if not attempt:
        raise DeliverySafetyError("ATTEMPT_NOT_FOUND")
    payload = {"attempt_id": attempt_id, "outcome": outcome,
        "provider_exactly_once": False, "actual_receipt_verified": False,
        "evidence": store.sanitize_audit_metadata(evidence)}
    key = "publication_outcomes/" + attempt_id + ".json"
    if not store._create_json_once(key, payload) and store._read_json(key) != payload:
        raise DeliverySafetyError("PROVIDER_OUTCOME_CONFLICT_RECONCILE")
    return payload


def guarded_submit(*, authority, plan, run_id, candidate_sha256, review_id, now, submit):
    """Invoke only from the authenticated, enabled, complete-PASS gate.

    ``submit`` must use exactly the supplied immutable recipient plan. It must
    return {outcome: PROVIDER_ACCEPTED|PROVIDER_REJECTED|UNKNOWN_AFTER_SUBMIT,
    evidence: ...}; exceptions and partial/batch ambiguity are unknown. No retry.
    """
    authority.revalidate(plan, now)
    reservation = reserve_publication_attempt(plan, run_id=run_id,
        candidate_sha256=candidate_sha256, review_id=review_id, now=now)
    if not reservation["allowed"]:
        return reservation
    try:
        authority.revalidate(plan, now)
    except Exception:
        complete_publication_attempt(reservation["attempt_id"],
            outcome="NOT_SUBMITTED_FINAL_GUARD_BLOCKED", evidence={"reason": "FINAL_ELIGIBILITY_CHANGED"})
        raise
    try:
        result = submit(load_recipient_plan(plan["plan_id"], expected_sha256=plan["sha256"]))
        if not isinstance(result, dict) or result.get("outcome") not in {
                "PROVIDER_ACCEPTED", "PROVIDER_REJECTED", "UNKNOWN_AFTER_SUBMIT"}:
            raise DeliverySafetyError("PROVIDER_RESULT_INVALID")
    except Exception:
        result = {"outcome": "UNKNOWN_AFTER_SUBMIT", "evidence": {"reason": "SUBMIT_EXCEPTION_OR_MALFORMED"}}
    outcome = complete_publication_attempt(reservation["attempt_id"], outcome=result["outcome"],
                                            evidence=result.get("evidence", {}))
    return dict(reservation, provider_outcome=outcome)
