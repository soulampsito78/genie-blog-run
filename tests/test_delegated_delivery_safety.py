import copy
import base64
import hashlib
import hmac
import datetime as dt
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as Row

import pytest

import admin_safety_store as store
import delegated_delivery_safety as safety

NOW = dt.datetime(2026, 9, 10, 0, 15, tzinfo=dt.timezone.utc)
DAY = NOW.astimezone(safety.KST).date()
RUN = "20260910_080444_today_genie_22a3d46a"


def eligible_rows():
    account = Row(id="a", status="active", withdrawn_at=None)
    subscription = Row(id="s", account_id="a", state="trialing",
        created_at=NOW - dt.timedelta(days=2), delivery_start_date=DAY,
        ended_at=None, cancellation_effective_at=None, withdrawal_effective_at=None,
        trial_start_at=NOW - dt.timedelta(days=2), trial_end_at=NOW + dt.timedelta(days=12),
        contracted_plan_code=None, contracted_price_version=None,
        current_period_start=DAY - dt.timedelta(days=2), current_period_end=DAY + dt.timedelta(days=28),
        next_billing_at=NOW)
    email = Row(id="e", account_id="a", email="safe@example.com", status="active",
        verified_at=NOW - dt.timedelta(days=2), suppression_reason=None,
        suppressed_at=None, deactivated_at=None)
    entitlement = Row(id="t", account_id="a", subscription_id="s", product_code="today_genie",
        source="trial", plan_code=None, price_version=None, revoked_at=None,
        effective_from=DAY, effective_to=None)
    return account, subscription, email, entitlement


def verdict(rows, **kwargs):
    return safety.evaluate_eligibility(*rows, product_code="today_genie", publication_date=DAY,
        now=NOW, **kwargs)


def plan(recipients=None):
    payload = {"schema": safety.SCHEMA, "product_code": "today_genie",
        "publication_date": DAY.isoformat(), "frozen_at": NOW.isoformat(),
        "recipients": recipients or [{"account_id": "a", "snapshot_id": "snap",
            "delivery_email": "safe@example.com", "delivery_email_id": "e", "entitlement_id": "t"}],
        "excluded_reason_counts": {}}
    payload["sha256"] = safety._digest(payload)
    payload["plan_id"] = "recipient_" + payload["sha256"]
    store._create_json_once("delegated_recipient_plans/" + payload["plan_id"] + ".json", payload)
    return payload


def reconcile(outcome="NO_SUBMISSION_CONFIRMED"):
    return safety.record_publication_reconciliation(mode="today_genie", publication_date=DAY,
        inventory_sha256="a" * 64, prior_outcome=outcome, evidence_refs=["test-inventory"],
        operator_id="integration-test", legacy_writers_drained=True)


def reserve(frozen, **kwargs):
    return safety.reserve_publication_attempt(frozen, run_id=kwargs.pop("run_id", RUN),
        candidate_sha256="b" * 64, review_id="review-a", now=NOW, **kwargs)


def test_trial_eligible_all_three_products():
    for product in ("today_genie", "keysuri_global", "keysuri_korea"):
        rows = eligible_rows()
        rows[3].product_code = product
        assert safety.evaluate_eligibility(*rows, product_code=product,
            publication_date=DAY, now=NOW) == "ELIGIBLE"


@pytest.mark.parametrize("index,field,value,reason", [
    (0, "status", "withdrawn", "ACCOUNT_INELIGIBLE"),
    (0, "withdrawn_at", NOW, "ACCOUNT_INELIGIBLE"),
    (2, "verified_at", None, "DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"),
    (2, "verified_at", NOW + dt.timedelta(seconds=1), "DELIVERY_EMAIL_INVALID"),
    (2, "email", "SAFE@example.com", "DELIVERY_EMAIL_INVALID"),
    (2, "status", "pending_verification", "DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"),
    (2, "status", "superseded", "DELIVERY_EMAIL_NOT_VERIFIED_ACTIVE"),
    (2, "suppression_reason", "unsubscribe", "DELIVERY_SUPPRESSED"),
    (2, "suppression_reason", "complaint", "DELIVERY_SUPPRESSED"),
    (2, "suppression_reason", "hard_bounce", "DELIVERY_SUPPRESSED"),
    (2, "suppression_reason", "operator_manual", "DELIVERY_SUPPRESSED"),
    (2, "suppressed_at", NOW, "DELIVERY_SUPPRESSED"),
    (2, "deactivated_at", NOW, "DELIVERY_SUPPRESSED"),
    (1, "delivery_start_date", DAY + dt.timedelta(days=1), "DELIVERY_NOT_STARTED"),
    (1, "created_at", NOW, "SAME_DAY_SUBSCRIPTION"),
    (1, "state", "suspended", "SUBSCRIPTION_INELIGIBLE"),
    (1, "state", "trial_expired", "SUBSCRIPTION_INELIGIBLE"),
    (1, "state", "canceled", "SUBSCRIPTION_INELIGIBLE"),
    (1, "state", "withdrawn", "SUBSCRIPTION_INELIGIBLE"),
    (1, "trial_end_at", NOW, "TRIAL_NOT_EFFECTIVE"),
    (1, "cancellation_effective_at", NOW, "SUBSCRIPTION_END_EFFECTIVE"),
    (1, "withdrawal_effective_at", NOW, "SUBSCRIPTION_END_EFFECTIVE"),
    (3, "product_code", "keysuri_korea", "ENTITLEMENT_IDENTITY_CONFLICT"),
    (3, "account_id", "other", "ENTITLEMENT_IDENTITY_CONFLICT"),
    (3, "revoked_at", NOW, "ENTITLEMENT_NOT_EFFECTIVE"),
    (3, "effective_to", DAY - dt.timedelta(days=1), "ENTITLEMENT_NOT_EFFECTIVE"),
])
def test_recipient_safety_denials(index, field, value, reason):
    rows = eligible_rows()
    setattr(rows[index], field, value)
    assert verdict(rows) == reason


@pytest.mark.parametrize("state", ["active", "past_due", "cancellation_scheduled", "withdrawal_scheduled"])
def test_paid_contract_and_grace(state):
    rows = eligible_rows()
    rows[1].state = state
    rows[1].contracted_plan_code = rows[3].plan_code = "today_genie"
    rows[1].contracted_price_version = rows[3].price_version = 1
    rows[3].source = "paid"
    assert verdict(rows, subscription_products=("today_genie",)) == "ELIGIBLE"
    assert verdict(rows, subscription_products=("keysuri_korea",)) == "PAID_CONTRACT_PRODUCT_MISMATCH"
    if state == "past_due":
        rows[1].next_billing_at = NOW - dt.timedelta(days=3, seconds=1)
        assert verdict(rows, subscription_products=("today_genie",)) == "RENEWAL_GRACE_EXPIRED"


def test_missing_suppression_adapter_never_uses_env_list(monkeypatch):
    monkeypatch.setenv("GENIE_CUSTOMER_EMAIL_TO", "unsafe@example.com")
    with pytest.raises(safety.DeliverySafetyError, match="SUPPRESSION_INGESTION_UNVERIFIED"):
        safety.SqlAlchemyRecipientAuthority()._session()


def test_missing_database_fails_closed(monkeypatch):
    monkeypatch.delenv("CUSTOMER_DATABASE_URL", raising=False)
    with pytest.raises(safety.DeliverySafetyError, match="CUSTOMER_DATABASE_UNAVAILABLE"):
        safety.SqlAlchemyRecipientAuthority(suppression_health=lambda: True)._session()


def test_missing_reconciliation_does_not_reserve():
    with pytest.raises(safety.DeliverySafetyError, match="LEGACY_PUBLICATION_RECONCILIATION_REQUIRED"):
        reserve(plan())


@pytest.mark.parametrize("prior", ["PROVIDER_ACCEPTED", "UNKNOWN_AFTER_SUBMIT"])
def test_prior_legacy_accept_or_ambiguity_blocks(prior):
    reconcile(prior)
    with pytest.raises(safety.DeliverySafetyError, match="RECONCILIATION_REQUIRED"):
        reserve(plan())


def test_separate_runs_threads_claim_only_once():
    frozen = plan()
    reconcile()
    def attempt(index):
        return reserve(frozen, run_id="20260910_080444_today_genie_{:08x}".format(index))
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(20)))
    assert sum(result["allowed"] for result in results) == 1


def test_separate_process_restart_does_not_retry():
    frozen = plan()
    reconcile()
    assert reserve(frozen)["allowed"] is True
    script = """import datetime as dt, json
import delegated_delivery_safety as s
p=s.load_recipient_plan(%r)
r=s.reserve_publication_attempt(p,run_id='20260910_081500_today_genie_12345678',candidate_sha256='c'*64,review_id='fresh-review',now=dt.datetime(2026,9,10,0,15,tzinfo=dt.timezone.utc))
print(json.dumps(r))
""" % frozen["plan_id"]
    result = subprocess.run([sys.executable, "-c", script], cwd=os.getcwd(), env=os.environ.copy(),
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["allowed"] is False


def test_acceptance_never_receipt_and_never_automatic_reissue():
    frozen = plan()
    reconcile()
    reserved = reserve(frozen)
    outcome = safety.complete_publication_attempt(reserved["attempt_id"],
        outcome="PROVIDER_ACCEPTED", evidence={"provider": "test"})
    assert outcome["actual_receipt_verified"] is False
    assert reserve(frozen, run_id="20260910_091500_today_genie_12345678")["allowed"] is False
    with pytest.raises(safety.DeliverySafetyError, match="CONFLICT_RECONCILE"):
        safety.complete_publication_attempt(reserved["attempt_id"],
            outcome="PROVIDER_REJECTED", evidence={})


def test_outcome_unknown_on_submit_exception_never_retried():
    frozen = plan()
    reconcile()
    calls = []
    def submit(_):
        calls.append(1)
        raise TimeoutError("network after provider submit")
    authority = Row(revalidate=lambda *args: True)
    result = safety.guarded_submit(authority=authority, plan=frozen, run_id=RUN,
        candidate_sha256="c" * 64, review_id="review", now=NOW, submit=submit)
    assert result["provider_outcome"]["outcome"] == "UNKNOWN_AFTER_SUBMIT"
    again = safety.guarded_submit(authority=authority, plan=frozen, run_id=RUN,
        candidate_sha256="c" * 64, review_id="review", now=NOW, submit=submit)
    assert again["allowed"] is False
    assert len(calls) == 1


def test_unsubscribe_between_review_and_final_handoff_stops_sender():
    frozen = plan()
    reconcile()
    count = []
    def revalidate(*args):
        count.append(1)
        if len(count) == 2:
            raise safety.DeliverySafetyError("DELIVERY_SUPPRESSED")
        return True
    sender = []
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_SUPPRESSED"):
        safety.guarded_submit(authority=Row(revalidate=revalidate), plan=frozen, run_id=RUN,
            candidate_sha256="c" * 64, review_id="review", now=NOW,
            submit=lambda _: sender.append(1))
    assert not sender
    assert reserve(frozen)["allowed"] is False


def test_frozen_plan_tampering_fails_closed():
    frozen = plan()
    key = "delegated_recipient_plans/" + frozen["plan_id"] + ".json"
    modified = copy.deepcopy(frozen)
    modified["recipients"][0]["delivery_email"] = "attacker@example.com"
    store._write_json(key, modified)
    with pytest.raises(safety.DeliverySafetyError, match="RECIPIENT_PLAN_CHANGED"):
        safety.load_recipient_plan(frozen["plan_id"])


def test_one_cutover_allows_unattended_future_and_preserves_human_authority():
    safety.record_delivery_cutover(starts_on=DAY, inventory_sha256="d" * 64,
        evidence_refs=["drained-all-writers"], operator_id="owner-integration",
        all_writers_use_publication_guard=True)
    frozen = plan()
    result = reserve(frozen, approval_source="HUMAN_OWNER")
    assert result["allowed"]
    record = store._read_json("publication_attempts/" + result["attempt_id"] + ".json")
    assert record["approval_source"] == "HUMAN_OWNER"


def test_prior_known_acceptance_overrides_cutover():
    safety.record_delivery_cutover(starts_on=DAY, inventory_sha256="d" * 64,
        evidence_refs=["drained-all-writers"], operator_id="owner-integration",
        all_writers_use_publication_guard=True)
    reconcile("PROVIDER_ACCEPTED")
    with pytest.raises(safety.DeliverySafetyError, match="RECONCILIATION_REQUIRED"):
        reserve(plan())


@pytest.mark.parametrize("run", ["20260909_080444_today_genie_22a3d46a",
                                  "20260910_080444_keysuri_korea_tech_22a3d46a"])
def test_run_publication_identity_conflict(run):
    reconcile()
    with pytest.raises(safety.DeliverySafetyError, match="RUN_PUBLICATION_IDENTITY_CONFLICT"):
        reserve(plan(), run_id=run)


def cutover():
    return safety.record_delivery_cutover(starts_on=DAY, inventory_sha256="d" * 64,
        evidence_refs=["drained-all-writers"], operator_id="owner-integration",
        all_writers_use_publication_guard=True)


def test_kill_switch_off_retains_cutover_guard(monkeypatch):
    monkeypatch.setenv("DELEGATED_SEND_MODE", "OFF")
    assert safety.publication_guard_required() is False
    cutover()
    assert safety.publication_guard_required() is True


def test_corrupt_cutover_record_fails_closed(monkeypatch):
    monkeypatch.setenv("DELEGATED_SEND_MODE", "OFF")
    store._local_path("publication_cutover/v1.json").write_text("{corrupt")
    with pytest.raises(safety.DeliverySafetyError, match="CUTOVER_RECORD_UNREADABLE"):
        safety.publication_guard_required()


def test_enabled_mode_never_uses_legacy_manual_list(monkeypatch):
    monkeypatch.setenv("DELEGATED_SEND_MODE", "ON")
    assert safety.publication_guard_required() is True
    with pytest.raises(safety.DeliverySafetyError, match="INVALID_RECIPIENT_PLAN"):
        safety.manual_publication_guard(run_id=RUN, snapshot={},
            prepared_recipients=["legacy@example.com"], now=NOW)


def test_manual_guard_shares_claim_with_delegated_and_truthful_source(monkeypatch):
    frozen = plan()
    cutover()
    monkeypatch.setattr(safety, "recipient_authority", lambda: Row(revalidate=lambda *args: True))
    snapshot = {"recipient_plan_id": frozen["plan_id"], "recipient_plan_sha256": frozen["sha256"],
                "approval_target_sha256": "e" * 64, "approval_snapshot_id": "human-snapshot"}
    result = safety.manual_publication_guard(run_id=RUN, snapshot=snapshot,
        prepared_recipients=["safe@example.com"], now=NOW)
    assert result["required"] and result["allowed"]
    assert reserve(frozen)["allowed"] is False
    record = store._read_json("publication_attempts/" + result["attempt_id"] + ".json")
    assert record["approval_source"] == "HUMAN_OWNER"


def test_manual_final_guard_rechecks_suppression(monkeypatch):
    frozen = plan()
    def reject(*args):
        raise safety.DeliverySafetyError("DELIVERY_SUPPRESSED")
    monkeypatch.setattr(safety, "recipient_authority", lambda: Row(revalidate=reject))
    with pytest.raises(safety.DeliverySafetyError, match="DELIVERY_SUPPRESSED"):
        safety.revalidate_manual_publication({"required": True, "plan": frozen}, now=NOW)


def test_manual_recipient_plan_reuses_first_freeze(monkeypatch):
    frozen = plan()
    calls = []
    def prepare(*args):
        calls.append(1)
        return frozen
    monkeypatch.setattr(safety, "recipient_authority", lambda: Row(prepare=prepare,
        revalidate=lambda *args: True))
    first = safety.manual_recipient_plan(run_id=RUN, mode="today_genie", now=NOW)
    second = safety.manual_recipient_plan(run_id=RUN, mode="today_genie", now=NOW + dt.timedelta(seconds=1))
    assert first == second
    assert len(calls) == 1


def test_admin_approval_after_cutover_uses_db_plan_not_legacy_addresses(monkeypatch, tmp_path):
    import admin_approval
    frozen = plan()
    cutover()
    image = tmp_path / "fixture.jpg"
    image.write_bytes(b"image-fixture")
    monkeypatch.setattr(admin_approval, "_prepare_content_and_images",
                        lambda *args: ("subject", "html", [(str(image), "cid", "image.jpg")]))
    monkeypatch.setattr(safety, "manual_recipient_plan", lambda **kwargs: frozen)
    def unsafe_legacy():
        raise AssertionError("legacy recipient resolver must not be called after cutover")
    monkeypatch.setattr(admin_approval, "resolve_customer_recipients", unsafe_legacy)
    target = admin_approval.build_current_approval_target(run_id=RUN,
        meta={"mode": "today_genie"}, saved_html="html")
    assert target.recipients == ["safe@example.com"]
    assert target.snapshot_fields["recipient_plan_id"] == frozen["plan_id"]
    assert target.snapshot_fields["recipient_configuration_hash"] == frozen["sha256"]


def signed_bridge_record(monkeypatch, *, audience="genie-suppression-health", now=NOW,
                         patch=None, database_url="postgresql+psycopg://test@localhost/isolated"):
    secret = b"isolated-test-bridge-key-material-only"
    monkeypatch.setenv("CUSTOMER_DATABASE_URL", database_url)
    monkeypatch.setenv("GENIE_CUSTOMER_AUTHORITY_ID", "isolated-customer-db")
    monkeypatch.setenv("GENIE_SUPPRESSION_BRIDGE_KEYS", json.dumps({"test-key": {
        "secret_b64": base64.b64encode(secret).decode(), "principal": "verified-test-bridge",
        "allowed_feeds": list(safety.SUPPRESSION_FEEDS)}}))
    record = {"schema": safety.SCHEMA, "audience": audience, "key_id": "test-key",
        "principal": "verified-test-bridge", "authority_id": "isolated-customer-db",
        "database_fingerprint": hashlib.sha256(database_url.encode()).hexdigest(),
        "issued_at": now.isoformat(), "expires_at": (now + dt.timedelta(minutes=4)).isoformat(),
        "streams": {feed: {"state": "AUTHENTICATED_AND_CHECKPOINTED", "checked_at": now.isoformat(),
            "checkpoint": "test-cursor", "source_reference": "isolated-source"}
            for feed in safety.SUPPRESSION_FEEDS}}
    if patch:
        record.update(patch)
    raw = json.dumps(record, sort_keys=True).encode()
    signature = hmac.new(secret, b"GENIE_SUPPRESSION_V1\n" + raw, hashlib.sha256).hexdigest()
    return raw, signature


def test_signed_suppression_health_closes_configurable_factory_gap(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    raw, signature = signed_bridge_record(monkeypatch, now=now)
    assert not safety.suppression_ingestion_healthy(now)
    safety.record_authenticated_suppression_health(raw, key_id="test-key", signature=signature, now=now)
    assert safety.suppression_ingestion_healthy(now)
    assert safety.recipient_authority()._suppression_health() is True
    assert safety.suppression_ingestion_healthy(now + dt.timedelta(minutes=5)) is False


def test_unsigned_health_boolean_never_passes(monkeypatch):
    monkeypatch.setenv("GENIE_SUPPRESSION_HEALTHY", "true")
    store._write_json("suppression_health/current.json", {"healthy": True})
    assert safety.suppression_ingestion_healthy(NOW) is False


@pytest.mark.parametrize("patch", [
    {"authority_id": "wrong-db"}, {"database_fingerprint": "f" * 64},
    {"audience": "genie-suppression-event"}, {"principal": "untrusted"},
    {"expires_at": (NOW + dt.timedelta(minutes=6)).isoformat()},
    {"issued_at": (NOW + dt.timedelta(seconds=1)).isoformat()},
    {"streams": {"unsubscribe": {"state": "AUTHENTICATED_AND_CHECKPOINTED"}}},
])
def test_signed_but_incomplete_or_wrong_scope_health_fails_closed(monkeypatch, patch):
    raw, signature = signed_bridge_record(monkeypatch, patch=patch)
    with pytest.raises(safety.DeliverySafetyError, match="INVALID_OR_STALE"):
        safety.record_authenticated_suppression_health(raw, key_id="test-key", signature=signature, now=NOW)


def test_health_byte_tamper_fails_authentication(monkeypatch):
    raw, signature = signed_bridge_record(monkeypatch)
    with pytest.raises(safety.DeliverySafetyError, match="AUTH_FAILED"):
        safety.record_authenticated_suppression_health(raw + b" ", key_id="test-key", signature=signature, now=NOW)


def test_health_source_checkpoint_must_be_fresh(monkeypatch):
    streams = {feed: {"state": "AUTHENTICATED_AND_CHECKPOINTED", "checked_at":
        (NOW - dt.timedelta(minutes=6)).isoformat(), "checkpoint": "cursor", "source_reference": "source"}
        for feed in safety.SUPPRESSION_FEEDS}
    raw, signature = signed_bridge_record(monkeypatch, patch={"streams": streams})
    with pytest.raises(safety.DeliverySafetyError, match="INVALID_OR_STALE"):
        safety.record_authenticated_suppression_health(raw, key_id="test-key", signature=signature, now=NOW)
