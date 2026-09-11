"""Security/dispatch contract tests. No Gmail, actual images or live SMTP used."""
import copy
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import delegated_gate as gate
import delegated_delivery_safety as safety
import admin_safety_store as store

NOW = datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc)
KEY = gate.ReviewerKey("work-cloud-reviewer", b"test-only-shared-key-never-used-live-12345")


class Authority:
    def __init__(self):
        self.calls = 0
        self.fail_on = None
        self.action = None

    def revalidate(self, plan, now):
        self.calls += 1
        safety.load_recipient_plan(plan["plan_id"], plan["sha256"])
        if self.action:
            self.action(self.calls)
        if self.calls == self.fail_on:
            raise safety.DeliverySafetyError("DELIVERY_SUPPRESSED")
        return True


class Loader:
    def __init__(self, candidate, next_candidate=None):
        self.candidate, self.next_candidate, self.calls = candidate, next_candidate, 0

    def load(self, run_id, now):
        self.calls += 1
        return self.next_candidate if self.calls > 1 and self.next_candidate else self.candidate


@pytest.fixture
def setup_case(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_uses_gcs_backend", lambda: False)
    monkeypatch.setattr("admin_store._keysuri_korea_bottom_baseline_confirmed", lambda _: (True, "ok"))
    monkeypatch.setenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", str(tmp_path / "safety"))
    safety.record_delivery_cutover(starts_on="2026-09-10", inventory_sha256="1" * 64,
        evidence_refs=["fixture://inventory"], operator_id="fixture-owner",
        all_writers_use_publication_guard=True)

    def make(mode="today_genie", *, suffix="abcdef12", source="https://example.test/news?a=1", parent=None):
        product = safety.PRODUCTS[mode]
        plan = {"schema": safety.SCHEMA, "product_code": product, "publication_date": "2026-09-10",
            "frozen_at": (NOW-timedelta(minutes=15)).isoformat(), "excluded_reason_counts": {},
            "recipients": [{"account_id": "account-1", "snapshot_id": "snapshot-1",
                "subscription_id": "subscription-1", "delivery_email": "reader@example.test",
                "delivery_email_id": "email-1", "entitlement_id": "entitlement-1"}]}
        plan["sha256"] = safety._digest(plan)
        plan["plan_id"] = "recipient_" + plan["sha256"]
        store._create_json_once("delegated_recipient_plans/" + plan["plan_id"] + ".json", plan)
        meta = {"run_id": f"20260910_153000_{mode}_{suffix}", "mode": mode,
            "validation_result": "pass", "artifact_status": "emailed", "owner_review_status": "pending_review",
            "customer_surface_status": "CUSTOMER_SURFACE_PASS", "customer_delivery_status": "not_sent",
            "safety_verdict": "SAFE", "editorial_verdict": "READY", "parent_run_id": parent,
            "selected_items": [{"url": source}], "repair_trace": [{"stage": "pre_review", "validation_reran": True}]}
        if mode in {"keysuri_global_tech", "keysuri_korea_tech"}:
            meta.update({
                "reader_surface_enforced": True,
                "reader_surface_complete": True,
                "reader_surface_ready_count": 5,
            })
        parts = []
        for role in (["top"] if mode == "keysuri_global_tech" else ["top", "bottom"]):
            path = tmp_path / f"{mode}_{role}.jpg"
            path.write_bytes(b"fixture image bytes " + role.encode())
            parts.append((str(path), role, f"{role}.jpg"))
        def prepared(*args, **kwargs):
            copy = gate._DELEGATED_COPY if kwargs.get("approval_source") == "DELEGATED_WORK_REVIEW" else gate._HUMAN_COPY
            return {"ok": True, "subject": "Reviewed briefing", "html_body": f'<p>{copy}</p><a href="{source}">Source</a>',
                    "inline_jpeg_parts": parts, "recipients": kwargs["recipients_override"]}
        if mode == "today_genie":
            monkeypatch.setattr("today_geenee_customer_delivery.prepare_today_geenee_customer_delivery", prepared)
        else:
            monkeypatch.setattr("keysuri_customer_delivery.prepare_keysuri_customer_delivery", prepared)
        receipt = {"mailbox_id": "owner-review", "message_id": "received-message-1",
            "internet_message_id": "message-1@example.test", "received_at": (NOW-timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "a"*64, "render_capture_sha256": "b"*64,
            "customer_render_capture_sha256": "c"*64}
        return gate.freeze_candidate(meta=meta, saved_html="<p>Actual received briefing</p>",
                                     received_message=receipt, recipient_plan=plan)
    return make


def event_for(candidate, *, event_id="event_000000000001", verdict="PASS"):
    return {"event_id": event_id, "run_id": candidate.binding["run_id"], "audience": "genie-delegated-review",
        "policy_version": gate.POLICY_VERSION, "issued_at": NOW.isoformat(),
        "candidate_sha256": candidate.candidate_sha256,
        "review": {**candidate.binding, "policy_version": gate.POLICY_VERSION,
            "reviewer_agent": KEY.principal, "reviewer_model": "gpt-6", "verdict": verdict,
            "reviewed_at": (NOW-timedelta(minutes=5)).isoformat(),
            "checks": {key: "PASS" for key in gate.REQUIRED_CHECKS},
            "evidence": {key: [f"fixture://{key}"] for key in gate.REQUIRED_CHECKS},
            "critical_sources_checked": True, "anomalies": []}}


def signed(event):
    raw = gate.canonical(event).encode()
    return raw, {"x-genie-review-key-id": "runner-v1", "x-genie-review-signature": hmac.new(KEY.secret, raw, hashlib.sha256).hexdigest()}


def settings(mode="ON", **kwargs):
    return gate.GateSettings(mode=mode, authorized_policy=gate.POLICY_VERSION,
                             reviewer_keys={"runner-v1": KEY}, **kwargs)


def run(candidate, *, event=None, authority=None, loader=None, sender=None, configuration=None):
    return gate.process_review_event(*signed(event or event_for(candidate)), loader=loader or Loader(candidate),
        recipient_authority=authority or Authority(), now=NOW, settings=configuration or settings(),
        sender=sender or (lambda frozen, plan, audit: {"outcome": "ACCEPTED_ALL", "received": False}))


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
def test_authenticated_normal_dispatch_uses_frozen_bytes_and_truthful_authority(setup_case, mode):
    candidate = setup_case(mode)
    called = []
    result = run(candidate, sender=lambda frozen, plan, audit: called.append((frozen, plan, audit)) or {"outcome": "ACCEPTED_ALL"})
    assert result["verdict"] == "PASS"
    assert result["customer_send_authorized"] is True
    assert result["approval_source"] == "DELEGATED_WORK_REVIEW"
    assert result["owner_notification_required"] is False
    assert result["inbox_receipt_confirmed"] is False
    assert result["reviewer_model_independently_verified"] is False
    assert called[0][0].customer_html == candidate.customer_html
    assert gate._HUMAN_COPY not in candidate.customer_html
    assert gate._DELEGATED_COPY in candidate.customer_html
    assert called[0][1] == candidate.recipient_plan


@pytest.mark.parametrize("mode", ["OFF", "", "manual", "timeout", "unknown"])
def test_no_request_can_override_kill_switch(setup_case, mode):
    candidate = setup_case()
    event = event_for(candidate)
    event.update(operating_mode="ON", owner_approved=True, customer_send_authorized=True)
    result = run(candidate, event=event, configuration=settings(mode))
    assert result["customer_send_authorized"] is False
    assert result["reason_codes"] == ["DELEGATED_SEND_MODE_OFF"]


def test_missing_policy_activation_and_default_environment_are_off(setup_case, monkeypatch):
    candidate = setup_case()
    result = run(candidate, configuration=replace(settings(), authorized_policy=""))
    assert result["reason_codes"] == ["OWNER_DELEGATION_POLICY_NOT_ACTIVATED"]
    monkeypatch.delenv("DELEGATED_SEND_MODE", raising=False)
    assert gate.GateSettings.from_environment().mode == "OFF"


def test_authenticated_shadow_cannot_reserve_publication(setup_case, tmp_path):
    result = run(setup_case(), configuration=settings("SHADOW"))
    assert result["verdict"] == "PASS" and result["customer_send_authorized"] is False
    assert not (tmp_path / "safety/publication_attempts").exists()


@pytest.mark.parametrize("verdict", sorted(gate.VERDICTS - {"PASS"}) + ["OWNER_APPROVED", "probably_pass"])
def test_non_pass_or_unknown_review_never_dispatches(setup_case, verdict):
    result = run(setup_case(), event=event_for(setup_case(), verdict=verdict))
    assert result["verdict"] != "PASS" and result["customer_send_authorized"] is False


@pytest.mark.parametrize("dimension", sorted(gate.REQUIRED_CHECKS))
def test_missing_independent_review_dimension_fails_closed(setup_case, dimension):
    candidate = setup_case()
    event = event_for(candidate)
    del event["review"]["checks"][dimension]
    assert run(candidate, event=event)["verdict"] == "HOLD_INCOMPLETE"


def test_forged_signature_never_loads_authoritative_candidate(setup_case):
    candidate = setup_case()
    raw, headers = signed(event_for(candidate))
    headers["x-genie-review-signature"] = "0" * 64
    loader = Loader(candidate)
    result = gate.process_review_event(raw, headers, loader=loader, recipient_authority=Authority(), now=NOW, settings=settings())
    assert result["reason_codes"] == ["REVIEW_AUTHENTICATION_FAILED"] and loader.calls == 0


@pytest.mark.parametrize("change,reason", [
    (lambda e: e["review"].update(reviewer_agent="Owner"), "REVIEWER_PRINCIPAL_MISMATCH"),
    (lambda e: e.update(audience="another-service"), "REVIEW_AUDIENCE_OR_POLICY_MISMATCH"),
    (lambda e: e.update(policy_version="old-policy"), "REVIEW_AUDIENCE_OR_POLICY_MISMATCH"),
    (lambda e: e.update(issued_at=(NOW-timedelta(minutes=6)).isoformat()), "STALE_EVENT"),
    (lambda e: e.update(issued_at=(NOW+timedelta(seconds=1)).isoformat()), "STALE_EVENT"),
])
def test_signed_wrong_identity_audience_policy_or_clock_is_blocked(setup_case, change, reason):
    candidate = setup_case()
    event = event_for(candidate)
    change(event)
    assert run(candidate, event=event)["reason_codes"] == [reason]


def test_duplicate_json_keys_are_rejected_even_when_signature_valid(setup_case):
    candidate = setup_case()
    raw = b'{"event_id":"event_000000000001","event_id":"event_000000000002"}'
    headers = {"x-genie-review-key-id": "runner-v1", "x-genie-review-signature": hmac.new(KEY.secret, raw, hashlib.sha256).hexdigest()}
    result = gate.process_review_event(raw, headers, loader=Loader(candidate), recipient_authority=Authority(), now=NOW, settings=settings())
    assert result["reason_codes"] == ["MALFORMED_REVIEW_EVENT"]


def test_persistent_event_replay_and_separate_run_duplicate_are_blocked(setup_case):
    candidate = setup_case()
    assert run(candidate)["customer_send_authorized"] is True
    assert run(candidate)["reason_codes"] == ["REPLAYED_REVIEW_EVENT_RECONCILE"]
    second = setup_case(suffix="abcdef13")
    result = run(second, event=event_for(second, event_id="new_event_00000000002"))
    assert result["reason_codes"] == ["PUBLICATION_ALREADY_RESERVED_RECONCILE"]


@pytest.mark.parametrize("kind", ["body", "image", "source", "lineage", "artifact", "receipt", "recipients"])
def test_material_candidate_change_invalidates_old_pass(setup_case, kind):
    candidate = setup_case()
    event = event_for(candidate)
    if kind == "body":
        changed = replace(candidate, customer_html="<p>B</p>")
    elif kind == "image":
        changed = replace(candidate, images=(replace(candidate.images[0], content=b"B"),) + candidate.images[1:])
    else:
        binding = candidate.binding
        field = {"source": "source_urls", "lineage": "parent_run_id", "artifact": "artifact_id", "receipt": "received_message_id", "recipients": "recipient_plan_sha256"}[kind]
        binding[field] = ["https://changed.test"] if kind == "source" else "changed"
        changed = replace(candidate, binding_json=gate.canonical(binding))
    result = run(changed, event=event)
    assert result["verdict"] == "STATE_CONFLICT" and result["customer_send_authorized"] is False


def test_candidate_changes_between_review_and_provider_boundary(setup_case):
    candidate = setup_case()
    newer = setup_case(source="https://example.test/news?a=2")
    result = run(candidate, loader=Loader(candidate, newer))
    assert result["reason_codes"] == ["CANDIDATE_CHANGED_BEFORE_SUBMIT"]


def test_work_anomaly_never_triggers_repair_or_send(setup_case):
    candidate = setup_case()
    event = event_for(candidate)
    event["review"]["anomalies"] = ["material contradiction"]
    result = run(candidate, event=event)
    assert result["verdict"] == "HOLD_ANOMALY"


def test_reissue_cannot_inherit_parent_pass_but_new_unsent_review_can_pass(setup_case):
    parent = setup_case()
    child = setup_case(suffix="abcdef13", parent=parent.binding["run_id"])
    old = event_for(parent)
    old["run_id"] = child.binding["run_id"]
    assert run(child, event=old)["reason_codes"] == ["CANDIDATE_CHANGED_REVIEW_REQUIRED"]
    result = run(child, event=event_for(child, event_id="fresh_child_event_002"))
    assert result["customer_send_authorized"] is True


def test_pre_review_repairs_are_bound_and_remain_reviewable(setup_case):
    candidate = setup_case()
    assert json.loads(candidate.meta_json)["repair_trace"][0]["validation_reran"] is True
    assert run(candidate)["verdict"] == "PASS"


def test_final_unsubscribe_revalidation_blocks_without_releasing_claim(setup_case):
    candidate = setup_case()
    authority = Authority()
    authority.fail_on = 2
    called = []
    result = run(candidate, authority=authority, sender=lambda *a, **k: called.append(True))
    assert result["reason_codes"] == ["DELIVERY_SUPPRESSED"] and called == []
    assert result["reconciliation_required"] is True
    retried = run(candidate, event=event_for(candidate, event_id="new_after_unsub_002"))
    assert retried["reason_codes"] == ["PUBLICATION_ALREADY_RESERVED_RECONCILE"]


def test_provider_exception_retains_durable_claim_and_never_blind_retries(setup_case):
    candidate = setup_case()
    def ambiguous(*args, **kwargs):
        raise TimeoutError("provider may have accepted")
    result = run(candidate, sender=ambiguous)
    assert result["customer_send_authorized"] is False and result["reconciliation_required"] is True
    retried = run(candidate, event=event_for(candidate, event_id="after_crash_retry_02"))
    assert retried["reason_codes"] == ["DELIVERY_HANDOFF_ALREADY_CLAIMED"]


def test_missing_durable_store_cannot_pass(setup_case, monkeypatch):
    candidate = setup_case()
    def unavailable(*args, **kwargs):
        raise OSError("store unavailable")
    monkeypatch.setattr(store, "_create_json_once", unavailable)
    assert run(candidate)["verdict"] == "REVIEW_UNAVAILABLE"


@pytest.mark.parametrize("outcome", ["PARTIAL_REFUSAL", "SUBMITTED", "OUTCOME_UNKNOWN", "REFUSED_ALL", "NOT_SENT"])
def test_provider_non_success_is_an_exception_and_never_claims_receipt(setup_case, outcome):
    result = run(setup_case(), sender=lambda *a, **k: {"outcome": outcome})
    assert result["owner_notification_required"] is True
    assert result["inbox_receipt_confirmed"] is False


def test_default_run_loader_rejects_missing_independent_gmail_binding(setup_case, monkeypatch):
    candidate = setup_case()
    monkeypatch.setattr("admin_store.load_run_artifact", lambda _: json.loads(candidate.meta_json))
    monkeypatch.setattr("admin_store.load_run_email_html", lambda _: candidate.saved_html)
    result = run(candidate, loader=gate.RunArtifactCandidateLoader(Authority()))
    assert result["reason_codes"] == ["AUTHORITATIVE_ARTIFACT_OR_RECEIPT_UNAVAILABLE"]


def test_real_product_send_adapter_preserves_exact_bytes_and_does_not_forge_owner(setup_case, monkeypatch):
    candidate = setup_case()
    monkeypatch.setenv("DELEGATED_SEND_MODE", "ON")
    rows, submitted = [], []
    def update(run_id, action):
        row = copy.deepcopy(rows[-1] if rows else json.loads(candidate.meta_json))
        action(row)
        rows.append(row)
        return row
    def product_send(saved_html, meta, prepared_delivery):
        submitted.append(prepared_delivery)
        assert prepared_delivery["html_body"] == candidate.customer_html
        for (path, cid, filename), image in zip(prepared_delivery["inline_jpeg_parts"], candidate.images):
            assert Path(path).read_bytes() == image.content
        return True
    monkeypatch.setattr("admin_store.update_run_artifact", update)
    monkeypatch.setattr("today_geenee_customer_delivery.send_today_geenee_customer_final_email", product_send)
    monkeypatch.setattr("email_sender.last_send_trace", lambda: {"smtp_submission_started": True, "smtp_accepted_recipient_count": 1})
    monkeypatch.setattr("email_sender.last_send_diagnostic", lambda: "")
    raw, headers = signed(event_for(candidate))
    result = gate.process_review_event(raw, headers, loader=Loader(candidate), recipient_authority=Authority(), now=NOW, settings=settings())
    assert result["submission_outcome"] == "ACCEPTED_ALL" and len(submitted) == 1
    assert rows[-1]["approval_source"] == "DELEGATED_WORK_REVIEW"
    assert rows[-1]["owner_review_status"] == "pending_review"
    assert "approved_by" not in rows[-1] and "owner_reviewed_at" not in rows[-1]


def test_kill_switch_changed_after_review_before_submit_is_obeyed(setup_case, monkeypatch):
    candidate = setup_case()
    monkeypatch.setenv("DELEGATED_SEND_MODE", "ON")
    authority = Authority()
    authority.action = lambda n: monkeypatch.setenv("DELEGATED_SEND_MODE", "OFF") if n == 2 else None
    raw, headers = signed(event_for(candidate))
    result = gate.process_review_event(raw, headers, loader=Loader(candidate), recipient_authority=authority, now=NOW, settings=settings())
    assert result["reason_codes"] == ["DELEGATED_SEND_DISABLED_BEFORE_SUBMIT"]


@pytest.mark.parametrize("fault", [None, "html", "image", "message_id", "run"])
def test_received_mime_must_match_actual_artifact_before_binding(setup_case, monkeypatch, fault):
    from email.message import EmailMessage
    candidate = setup_case()
    run_id = candidate.binding["run_id"]
    saved = f"<p>Received briefing {run_id}</p>"
    monkeypatch.setattr("admin_store.load_run_artifact", lambda _: json.loads(candidate.meta_json))
    monkeypatch.setattr("admin_store.load_run_email_html", lambda _: saved)
    mime = EmailMessage()
    mime["Subject"] = "Received owner review"
    if fault != "message_id":
        mime["Message-ID"] = "<exact-message@example.test>"
    mime.set_content("Plain alternative")
    html = "<p>Wrong candidate</p>" if fault == "html" else saved
    if fault == "run":
        html = saved.replace(run_id, "another-run")
    mime.add_alternative(html, subtype="html")
    for image in candidate.images:
        mime.get_payload()[-1].add_related(b"corrupt" if fault == "image" else image.content,
            maintype="image", subtype="jpeg", cid=f"<{image.cid}>", filename=image.filename)
    kwargs = dict(run_id=run_id, mailbox_id="verified-test-mailbox", message_id="gmail-exact-id",
        received_at=(NOW-timedelta(minutes=10)).isoformat(), raw_mime=mime.as_bytes(),
        render_capture=b"fixture capture bytes, not real visual evidence",
        customer_render_capture=b"separate final-customer-render fixture", recipient_plan=candidate.recipient_plan)
    if fault:
        with pytest.raises(gate.GateError):
            gate.register_received_mail_evidence(**kwargs)
    else:
        record = gate.register_received_mail_evidence(**kwargs)
        loaded = gate.RunArtifactCandidateLoader(Authority()).load(run_id, now=NOW)
        assert loaded.candidate_sha256 == record["candidate_sha256"]
        assert record["received_message"]["raw_mime_sha256"] == hashlib.sha256(mime.as_bytes()).hexdigest()


def test_korea_baseline_gate_is_preserved_before_candidate_freeze(setup_case, monkeypatch):
    monkeypatch.setattr("admin_store._keysuri_korea_bottom_baseline_confirmed", lambda _: (False, "BASELINE_NOT_CONFIRMED"))
    with pytest.raises(gate.GateError, match="BASELINE_NOT_CONFIRMED"):
        setup_case("keysuri_korea_tech")


def manual_call(candidate, monkeypatch, *, authority=None):
    """Exercise real approve_run publication wiring after mocked human snapshot verification."""
    import admin_store
    from types import SimpleNamespace
    authority = authority or Authority()
    monkeypatch.setattr(safety, "recipient_authority", lambda: authority)
    monkeypatch.setattr(admin_store, "can_approve_customer_send", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(admin_store, "load_run_artifact", lambda _: json.loads(candidate.meta_json))
    monkeypatch.setattr(admin_store, "load_run_email_html", lambda _: candidate.saved_html)
    monkeypatch.setattr(admin_store, "datetime", SimpleNamespace(now=lambda *a: NOW))
    snapshot = {"approval_snapshot_id": "aps_20260910_0123456789abcdef",
        "approval_target_sha256": candidate.candidate_sha256,
        "recipient_plan_id": candidate.recipient_plan["plan_id"],
        "recipient_plan_sha256": candidate.recipient_plan["sha256"]}
    prepared = SimpleNamespace(recipients=[r["delivery_email"] for r in candidate.recipient_plan["recipients"]],
        customer_html=candidate.customer_html, subject=candidate.subject, inline_jpeg_parts=[])
    monkeypatch.setattr("admin_approval.verify_approval_snapshot", lambda **k: (snapshot, prepared))
    rows, sends = [], []
    def update(run_id, action):
        row = copy.deepcopy(rows[-1] if rows else json.loads(candidate.meta_json))
        action(row)
        rows.append(row)
        return row
    monkeypatch.setattr(admin_store, "update_run_artifact", update)
    monkeypatch.setattr(admin_store, "_update_sent_news_log_after_customer_success", lambda *a, **k: None)
    monkeypatch.setattr("today_geenee_customer_delivery.send_today_geenee_customer_final_email", lambda *a, **k: sends.append(True) or True)
    monkeypatch.setattr("email_sender.last_send_trace", lambda: {"smtp_submission_started": True, "smtp_accepted_recipient_count": 1})
    monkeypatch.setattr("email_sender.last_send_diagnostic", lambda: "")
    result = admin_store.approve_run(candidate.binding["run_id"],
        approval_snapshot_id=snapshot["approval_snapshot_id"], operator_id="fixture-human-owner")
    return result, sends, rows


def test_delegated_then_manual_separate_run_uses_same_durable_publication_claim(setup_case, monkeypatch):
    first = setup_case()
    assert run(first)["customer_send_authorized"] is True
    second = setup_case(suffix="abcdef13")
    (_, reason), sends, _ = manual_call(second, monkeypatch)
    assert reason == "PUBLICATION_ALREADY_RESERVED_RECONCILE" and sends == []


def test_manual_off_mode_then_delegated_separate_run_still_cannot_duplicate(setup_case, monkeypatch):
    first = setup_case()
    monkeypatch.setenv("DELEGATED_SEND_MODE", "OFF")
    (updated, reason), sends, _ = manual_call(first, monkeypatch)
    assert reason == "ok" and sends == [True]
    assert updated["approval_source"] == "HUMAN_OWNER"
    second = setup_case(suffix="abcdef13")
    result = run(second, event=event_for(second, event_id="after_manual_event_002"))
    assert result["reason_codes"] == ["PUBLICATION_ALREADY_RESERVED_RECONCILE"]


def test_manual_final_unsubscribe_revalidation_prevents_provider_submit(setup_case, monkeypatch):
    authority = Authority()
    authority.fail_on = 2
    (_, reason), sends, rows = manual_call(setup_case(), monkeypatch, authority=authority)
    assert reason == "DELIVERY_SUPPRESSED" and sends == [] and rows == []


NAVER_SUFFIX = '<table style=\'display:none\'><tr><td><img src="https://mail.naver.com/readReceipt/notify/?img=FIXTURE%2Btoken.gif" border="0"/></td></tr></table>'


@pytest.mark.parametrize("saved", ["<html><body>Briefing</body></html>", "<section>Briefing fragment</section>"])
def test_only_observed_naver_hidden_transport_suffix_is_accepted(saved):
    assert gate.verify_received_html_transport(saved, saved)["recognized_transport_suffix_count"] == 0
    result = gate.verify_received_html_transport(saved + NAVER_SUFFIX, saved)
    assert result["recognized_transport_suffix_count"] == 1
    assert result["transport_suffix_sha256"] == hashlib.sha256(NAVER_SUFFIX.encode()).hexdigest()


@pytest.mark.parametrize("suffix", [
    NAVER_SUFFIX + NAVER_SUFFIX,
    NAVER_SUFFIX + "<p>Altered content</p>",
    NAVER_SUFFIX.replace("display:none", "display:block"),
    NAVER_SUFFIX.replace("mail.naver.com/", "mail.naver.com.attacker.test/"),
    NAVER_SUFFIX.replace("token.gif", "token.gif&another=1"),
    NAVER_SUFFIX.replace("border=\"0\"", "onerror=\"alert(1)\" border=\"0\""),
    NAVER_SUFFIX.replace("%2B", "%ZZ"),
    "<script>change()</script>" + NAVER_SUFFIX,
])
def test_other_material_or_tracking_like_differences_never_normalized(suffix):
    with pytest.raises(gate.GateError):
        gate.verify_received_html_transport("<p>Briefing</p>" + suffix, "<p>Briefing</p>")


@pytest.mark.parametrize("fault", ["missing", "mismatch", "check", "evidence"])
def test_customer_final_render_must_be_independently_examined_and_bound(setup_case, fault):
    candidate = setup_case()
    event = event_for(candidate)
    if fault == "missing":
        binding = candidate.binding
        binding["customer_render_capture_sha256"] = None
        candidate = replace(candidate, binding_json=gate.canonical(binding))
        event = event_for(candidate)
    elif fault == "mismatch":
        event["review"]["customer_render_capture_sha256"] = "f" * 64
    elif fault == "check":
        del event["review"]["checks"]["customer_render"]
    else:
        event["review"]["evidence"]["customer_render"] = []
    result = run(candidate, event=event)
    assert result["verdict"] in {"HOLD_INCOMPLETE", "STATE_CONFLICT"}
    assert result["customer_send_authorized"] is False


def test_wrong_product_recipient_plan_cannot_freeze_candidate(setup_case):
    candidate = setup_case()
    plan = candidate.recipient_plan
    plan["product_code"] = "keysuri_global"
    with pytest.raises(gate.GateError, match="RECIPIENT_PUBLICATION_PRODUCT_MISMATCH"):
        gate.freeze_candidate(meta=json.loads(candidate.meta_json), saved_html=candidate.saved_html,
            received_message=candidate.binding["received_message"], recipient_plan=plan)


@pytest.mark.parametrize("reported", ["verdict", "anomalies", "check"])
def test_meaningful_work_hold_latches_across_new_event_ids_until_fresh_run(setup_case, reported):
    parent = setup_case()
    event = event_for(parent)
    if reported == "verdict":
        event["review"]["verdict"] = "HOLD_ANOMALY"
    elif reported == "anomalies":
        event["review"]["anomalies"] = ["material source contradiction"]
    else:
        event["review"]["checks"]["content"] = "ANOMALY"
    assert run(parent, event=event)["verdict"] == "HOLD_ANOMALY"
    retry = run(parent, event=event_for(parent, event_id="new_pass_after_anomaly_001"))
    assert retry["reason_codes"] == ["RUN_HELD_MANUAL_RECOVERY_REQUIRED"]
    from admin_store import run_delivery_transition
    assert run_delivery_transition(parent.binding["run_id"], action="REOPEN", authority="HUMAN_OWNER")["allowed"] is False
    child = setup_case(suffix="abcdef13", parent=parent.binding["run_id"])
    assert run(child, event=event_for(child, event_id="fresh_reissue_review_001"))["customer_send_authorized"] is True


@pytest.mark.parametrize("state", ["HOLD_INCOMPLETE", "REVIEW_UNAVAILABLE"])
def test_transient_review_failure_may_retry_complete_without_regeneration(setup_case, state):
    candidate = setup_case()
    assert run(candidate, event=event_for(candidate, verdict=state))["customer_send_authorized"] is False
    retry = run(candidate, event=event_for(candidate, event_id="fresh_complete_retry_001"))
    assert retry["customer_send_authorized"] is True


def test_human_hold_committed_after_final_load_prevents_delegated_handoff(setup_case, monkeypatch):
    import admin_store
    candidate = setup_case()
    rows = [json.loads(candidate.meta_json)]
    monkeypatch.setattr(admin_store, "load_run_artifact", lambda _: copy.deepcopy(rows[-1]))
    def update(run_id, action):
        row = copy.deepcopy(rows[-1]); action(row); rows.append(row); return row
    monkeypatch.setattr(admin_store, "update_run_artifact", update)
    authority = Authority()
    held, sent = [], []
    def concurrent_hold(n):
        if n == 2:
            held.append(admin_store.hold_run(candidate.binding["run_id"], operator_id="fixture-owner"))
    authority.action = concurrent_hold
    result = run(candidate, authority=authority, sender=lambda *a, **k: sent.append(True))
    assert held[0][1] == "ok" and sent == []
    assert result["reason_codes"] == ["RUN_EXPLICITLY_HELD"]
    assert rows[-1]["owner_review_status"] == "held"


def test_later_hold_cannot_claim_to_retract_already_claimed_handoff(setup_case, monkeypatch):
    import admin_store
    candidate = setup_case()
    # Leave run metadata deliberately not_sent: journal must be authoritative
    # in the gap after claiming handoff and before writing SUBMITTED metadata.
    monkeypatch.setattr(admin_store, "load_run_artifact", lambda _: json.loads(candidate.meta_json))
    result = admin_store.run_delivery_transition(candidate.binding["run_id"], action="SUBMIT",
        authority="DELEGATED_WORK_REVIEW", candidate_sha256=candidate.candidate_sha256)
    assert result["allowed"] is True
    updated, reason = admin_store.hold_run(candidate.binding["run_id"])
    assert updated is None and reason == "DELIVERY_HANDOFF_ALREADY_CLAIMED"
    assert admin_store.run_delivery_transition(candidate.binding["run_id"], action="REOPEN", authority="HUMAN_OWNER")["allowed"] is False


def test_human_hold_can_reopen_but_transitions_are_not_reset(setup_case, monkeypatch):
    import admin_store
    candidate = setup_case()
    rows = [json.loads(candidate.meta_json)]
    monkeypatch.setattr(admin_store, "load_run_artifact", lambda _: copy.deepcopy(rows[-1]))
    def update(run_id, action):
        row = copy.deepcopy(rows[-1]); action(row); rows.append(row); return row
    monkeypatch.setattr(admin_store, "update_run_artifact", update)
    assert admin_store.hold_run(candidate.binding["run_id"])[1] == "ok"
    assert admin_store.reopen_held_run(candidate.binding["run_id"])[1] == "ok"
    state = admin_store.run_delivery_transition(candidate.binding["run_id"])
    assert state["state"] == "READY" and state["version"] == 1


def test_corrupt_transition_object_fails_closed(setup_case):
    import admin_store
    candidate = setup_case()
    run_id = candidate.binding["run_id"]
    key = "run_delivery_transitions/" + hashlib.sha256(run_id.encode()).hexdigest() + "/000.json"
    store._local_path(key).write_text("{partial")
    for action in ("READ", "SUBMIT", "HOLD"):
        with pytest.raises(RuntimeError, match="DELIVERY_TRANSITION_CORRUPT"):
            admin_store.run_delivery_transition(run_id, action=action, candidate_sha256=candidate.candidate_sha256)


def test_independent_processes_linearize_hold_against_provider_handoff(setup_case):
    import os, sys, subprocess
    from concurrent.futures import ThreadPoolExecutor
    import admin_store
    candidate = setup_case()
    run_id = candidate.binding["run_id"]
    script = """import json,sys
import admin_store, admin_safety_store
admin_safety_store._uses_gcs_backend=lambda:False
print(json.dumps(admin_store.run_delivery_transition(sys.argv[1],action=sys.argv[2],authority='fixture-process',candidate_sha256='a'*64)))
"""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
        "GENIE_ADMIN_SAFETY_LOCAL_DIR": os.environ["GENIE_ADMIN_SAFETY_LOCAL_DIR"]}
    actions = ["HOLD"] + ["SUBMIT"] * 5
    def actor(action):
        result = subprocess.run([sys.executable, "-c", script, run_id, action], env=env,
            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True)
        return action, json.loads(result.stdout.strip().splitlines()[-1])
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(actor, actions))
    winners = [(action, row) for action, row in results if row["allowed"]]
    assert len(winners) == 1
    final = admin_store.run_delivery_transition(run_id)
    assert final["state"] == ("HELD" if winners[0][0] == "HOLD" else "SUBMITTED")


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
def test_real_manual_preparation_after_cutover_requires_no_legacy_recipient_config(setup_case, monkeypatch, tmp_path, mode):
    import admin_store, admin_approval
    import today_geenee_customer_delivery as today
    import keysuri_customer_delivery as keysuri
    # Retain actual preparation functions; fixture constructor only supplies
    # known artifact/image/DB-plan data. Mock image fetching, never this boundary.
    real_today, real_keysuri = today.prepare_today_geenee_customer_delivery, keysuri.prepare_keysuri_customer_delivery
    candidate = setup_case(mode)
    monkeypatch.setattr(today, "prepare_today_geenee_customer_delivery", real_today)
    monkeypatch.setattr(keysuri, "prepare_keysuri_customer_delivery", real_keysuri)
    meta = json.loads(candidate.meta_json)
    meta["email_subject"] = "[운영자 검토] Independent preparation regression"
    parts = []
    for index, image in enumerate(candidate.images):
        path = tmp_path / f"manual-real-{index}.jpg"; path.write_bytes(image.content)
        parts.append((str(path), image.cid, image.filename))
    monkeypatch.setattr(today, "_resolve_today_genie_inline_jpeg_parts", lambda _: parts)
    monkeypatch.setattr(keysuri, "resolve_keysuri_inline_jpeg_parts", lambda *a: parts)
    monkeypatch.setattr(keysuri, "prepare_keysuri_customer_final_html", lambda *a, **k: "<p>Final review</p>")
    monkeypatch.setattr(safety, "manual_recipient_plan", lambda **k: candidate.recipient_plan)
    def forbidden_legacy():
        raise AssertionError("Legacy recipient authority must not run after cutover")
    for module in (admin_store, admin_approval, today, keysuri):
        monkeypatch.setattr(module, "resolve_customer_recipients", forbidden_legacy)
    monkeypatch.delenv("GENIE_CUSTOMER_EMAIL_TO", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "fixture@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "isolated-fixture-password")
    assert admin_store.can_approve_customer_send(meta, has_email_html=True)[0] is True
    target = admin_approval.build_current_approval_target(run_id=meta["run_id"], meta=meta, saved_html=candidate.saved_html)
    assert target.recipients == ["reader@example.test"]
    assert target.snapshot_fields["recipient_plan_id"] == candidate.recipient_plan["plan_id"]


def test_read_only_shadow_anomaly_does_not_mutate_live_hold_state(setup_case):
    import admin_store
    candidate = setup_case()
    event = event_for(candidate, verdict="HOLD_ANOMALY")
    result = run(candidate, event=event, configuration=settings("SHADOW"))
    assert result["verdict"] == "HOLD_ANOMALY" and result["customer_send_authorized"] is False
    assert admin_store.run_delivery_transition(candidate.binding["run_id"])["state"] == "READY"
