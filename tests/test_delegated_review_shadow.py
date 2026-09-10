from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from delegated_review import (
    ACTIVE_MODES, POLICY_VERSION, REQUIRED_CHECKS,
    delegated_send_gate, evaluate_shadow_review, record_shadow_review,
)

NOW = datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc)


def case(mode="today_genie"):
    candidate = {
        "run_id": f"20260910_153000_{mode}_abcdef12", "mode": mode,
        "publication_date": "2026-09-10", "subject_sha256": "a" * 64,
        "body_sha256": "b" * 64, "image_sha256": {"top": "c" * 64},
        "first_pass_verdict": "PASS", "customer_delivery_status": "not_sent",
        "owner_review_status": "pending_review", "received_message_id": "gmail-message-1",
        "artifact_status": "emailed", "safety_verdict": "SAFE", "editorial_verdict": "READY",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
    }
    if mode != "keysuri_global_tech":
        candidate["image_sha256"]["bottom"] = "f" * 64
    review = {
        **copy.deepcopy(candidate), "policy_version": POLICY_VERSION,
        "reviewer_agent": "GPT Work", "reviewer_model": "gpt-6",
        "verdict": "PASS", "reviewed_at": (NOW-timedelta(minutes=5)).isoformat(),
        "received_message": {
            "mailbox_id": "owner-review", "message_id": "gmail-message-1",
            "internet_message_id": "message-1@example.test",
            "received_at": (NOW-timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "d"*64, "render_capture_sha256": "e"*64,
        },
        "checks": {key: "PASS" for key in REQUIRED_CHECKS},
        "evidence": {key: [f"evidence://example/{key}"] for key in REQUIRED_CHECKS},
        "critical_sources_checked": True, "anomalies": [],
    }
    candidate["received_message"] = copy.deepcopy(review["received_message"])
    return candidate, review


@pytest.mark.parametrize("mode", sorted(ACTIVE_MODES))
def test_complete_normal_shadow_three_modes_never_authorizes_send(mode):
    candidate, review = case(mode)
    result = evaluate_shadow_review(candidate, review, now=NOW)
    assert result["verdict"] == "PASS"
    assert result["approval_authority"] == "NONE"
    assert result["customer_send_authorized"] is False
    assert result["authenticity_verified"] is False


@pytest.mark.parametrize("field", ["run_id", "mode", "publication_date", "subject_sha256", "body_sha256", "image_sha256"])
def test_binding_mismatch_holds(field):
    candidate, review = case()
    review[field] = "wrong"
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


def test_manual_reissue_child_must_be_independently_reviewed():
    candidate, review = case()
    candidate["run_id"] = "20260910_153100_today_genie_abcdef13"
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"
    review["run_id"] = candidate["run_id"]
    candidate["received_message_id"] = "new-message"
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


@pytest.mark.parametrize("field", sorted(REQUIRED_CHECKS))
@pytest.mark.parametrize("condition", ["missing", "unavailable", "anomaly", "no_evidence"])
def test_each_review_dimension_must_have_complete_inspection(field, condition):
    candidate, review = case()
    if condition == "missing":
        del review["checks"][field]
    elif condition == "no_evidence":
        review["evidence"][field] = []
    else:
        review["checks"][field] = condition.upper()
    result = evaluate_shadow_review(candidate, review, now=NOW)
    assert result["verdict"] == ("HOLD" if condition == "anomaly" else "REVIEW_INCOMPLETE")


@pytest.mark.parametrize("state", ["SUBMITTED", "ACCEPTED_ALL", "PARTIAL_REFUSAL", "OUTCOME_UNKNOWN", "failed", "NOT_SENT", ""])
def test_ambiguous_previous_delivery_never_passes(state):
    candidate, review = case()
    candidate["customer_delivery_status"] = state
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


@pytest.mark.parametrize("verdict", ["REVIEW_UNAVAILABLE", "REVIEW_INCOMPLETE", "WORK_REVIEW_ERROR"])
def test_explicit_review_failures_survive(verdict):
    candidate, review = case()
    review["verdict"] = verdict
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == verdict


def test_missing_email_no_run_or_timeout_cannot_be_pass():
    candidate, review = case()
    assert evaluate_shadow_review(candidate, None, now=NOW)["verdict"] == "REVIEW_UNAVAILABLE"
    review["received_message"] = None
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "REVIEW_UNAVAILABLE"
    candidate, review = case()
    assert evaluate_shadow_review(candidate, review, now=NOW+timedelta(hours=2))["verdict"] == "REVIEW_UNAVAILABLE"


@pytest.mark.parametrize("mutation,expected", [
    (lambda c,r: c.update(mode="tomorrow_genie"), "HOLD"),
    (lambda c,r: c.update(first_pass_verdict="REVIEW"), "HOLD"),
    (lambda c,r: c.update(owner_review_status="held"), "HOLD"),
    (lambda c,r: r.update(policy_version="obsolete"), "HOLD"),
    (lambda c,r: r.update(reviewer_model="gemini-2.5-flash"), "REVIEW_INCOMPLETE"),
    (lambda c,r: r.update(critical_sources_checked=False), "REVIEW_INCOMPLETE"),
    (lambda c,r: r.update(anomalies=["severe truncation"]), "HOLD"),
    (lambda c,r: r.update(reviewed_at="2026-09-10T12:00:00"), "WORK_REVIEW_ERROR"),
    (lambda c,r: r.update(reviewed_at=(NOW+timedelta(seconds=1)).isoformat()), "REVIEW_UNAVAILABLE"),
    (lambda c,r: r["received_message"].update(message_id="stale-message"), "HOLD"),
    (lambda c,r: r["received_message"].update(render_capture_sha256=""), "REVIEW_INCOMPLETE"),
    (lambda c,r: r.update(verdict=""), "REVIEW_INCOMPLETE"),
])
def test_adversarial_fail_closed(mutation, expected):
    candidate, review = case()
    mutation(candidate, review)
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == expected


@pytest.mark.parametrize("mode", ["manual", "shadow", "live", "delegated", "", "disabled"])
def test_no_input_or_mode_unlocks_live_send(mode):
    assert delegated_send_gate(operating_mode=mode, owner_approved=True, safety_verified=True, verdict="PASS")["allowed"] is False


def test_immutable_evidence_is_shadow_only_and_does_not_mutate_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", str(tmp_path))
    candidate, review = case()
    original = copy.deepcopy((candidate, review))
    with mock.patch("admin_safety_store._uses_gcs_backend", return_value=False):
        first = record_shadow_review(candidate, review, now=NOW)
        second = record_shadow_review(candidate, review, now=NOW)
    assert first["record_created"] is True
    assert second["record_created"] is False
    assert (candidate, review) == original
    saved = json.loads(next((tmp_path/"delegated_shadow_reviews").glob("*.json")).read_text())
    assert saved["evidence"]["review"]["received_message"]["message_id"] == "gmail-message-1"
    assert saved["approval_authority"] == "NONE"


@pytest.mark.parametrize("field", ["mailbox_id", "internet_message_id", "received_at", "raw_mime_sha256", "render_capture_sha256"])
def test_forged_envelope_binding_is_held(field):
    candidate, review = case()
    review["received_message"][field] = "f" * 64
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


@pytest.mark.parametrize("change", ["mode", "date", "lineage"])
def test_self_consistent_wrong_identity_is_not_pass(change):
    candidate, review = case()
    if change == "mode":
        candidate["mode"] = review["mode"] = "keysuri_global_tech"
    elif change == "date":
        candidate["publication_date"] = review["publication_date"] = "2026-09-09"
    else:
        candidate["parent_run_id"] = "20260910_063000_today_genie_abcdabcd"
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


def test_malformed_candidate_and_storage_failure_are_explicit_errors():
    assert evaluate_shadow_review(None, None, now=NOW)["verdict"] == "WORK_REVIEW_ERROR"
    candidate, review = case()
    with mock.patch("admin_safety_store._create_json_once", side_effect=OSError("offline")):
        result = record_shadow_review(candidate, review, now=NOW)
    assert result["verdict"] == "WORK_REVIEW_ERROR"
    assert result["record_created"] is False


@pytest.mark.parametrize("mode,role", [("today_genie", "bottom"), ("keysuri_korea_tech", "bottom"), ("keysuri_global_tech", "top")])
def test_missing_required_image_cannot_pass_even_self_consistent(mode, role):
    candidate, review = case(mode)
    del candidate["image_sha256"][role]
    del review["image_sha256"][role]
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "REVIEW_INCOMPLETE"


@pytest.mark.parametrize("field,value", [("artifact_status", "failed"), ("owner_review_status", "approved"), ("owner_review_status", "rejected"), ("owner_review_status", "unknown"), ("safety_verdict", "UNSAFE"), ("editorial_verdict", "POOR")])
def test_contradictory_operational_state_is_held(field, value):
    candidate, review = case("keysuri_korea_tech")
    candidate[field] = value
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


def test_old_publication_with_fresh_delivery_is_held():
    candidate, review = case()
    candidate["publication_date"] = review["publication_date"] = "2026-09-09"
    candidate["run_id"] = review["run_id"] = "20260909_153000_today_genie_abcdef12"
    result = evaluate_shadow_review(candidate, review, now=NOW)
    assert result["verdict"] == "HOLD"
    assert result["reason_codes"] == ["PUBLICATION_OUTSIDE_CURRENT_KST_DATE"]


@pytest.mark.parametrize("run_id,verdict", [("20260910_235959_today_genie_abcdef12", "HOLD"), ("20260910_999999_today_genie_abcdef12", "WORK_REVIEW_ERROR")])
def test_impossible_run_clock_fails_closed(run_id, verdict):
    candidate, review = case()
    candidate["run_id"] = review["run_id"] = run_id
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == verdict


@pytest.mark.parametrize("field,value", [("reissue_requested", True), ("last_reissue_child_run_id", "child"), ("superseded_by_run_id", "child")])
def test_superseded_parent_cannot_pass(field, value):
    candidate, review = case()
    candidate[field] = value
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"


@pytest.mark.parametrize("value", [None, "", "UNKNOWN", "PRODUCT_REVIEW_REQUIRED"])
def test_surface_inspection_must_explicitly_pass(value):
    candidate, review = case()
    candidate["customer_surface_status"] = value
    result = evaluate_shadow_review(candidate, review, now=NOW)
    assert result["verdict"] == "HOLD"
    assert result["reason_codes"] == ["PRODUCT_SURFACE_NOT_READY"]


@pytest.mark.parametrize("verdict", ["ANOMALY", "FAIL", "HOLD"])
def test_additional_anomaly_cannot_hide_behind_required_passes(verdict):
    candidate, review = case()
    review["checks"]["new_incident_class"] = verdict
    assert evaluate_shadow_review(candidate, review, now=NOW)["verdict"] == "HOLD"
