"""Tests for the delegated warning-release path for Today Geenee.

Verifies:
1. Narrow pre09 warning eligibility without Human Owner impersonation.
2. Raw machine verdicts preserved in frozen candidate binding (no forged PASS).
3. Authenticated review evaluation with full 7-check evidence.
4. Blocked states: post09 boundary, unknown/mixed substantive codes, stale/naive dates,
   tampered metadata hash, count mismatches, held/superseded/delivered runs,
   missing/FAIL checks, and missing critical sources.
5. Forged caller boolean rejected as authority.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from customer_review_confirmation import (
    DELEGATED_REVIEW_TEXT,
    DELEGATED_WORK_REVIEW,
    HUMAN_DIRECT_REVIEW_TEXT,
    HUMAN_OWNER,
    HUMAN_OWNER_WARNING_TEXT,
    PRE_SEND_OWNER_WITH_WARNINGS,
    PRE_SEND_REVIEWED,
    customer_review_confirmation,
    today_delegated_warning_eligible,
    today_quality_warning_present,
)
import delegated_gate as gate
import delegated_review as review_module
import delegated_delivery_safety as safety
import admin_safety_store as store
from today_geenee_customer_delivery import (
    REVIEW_CONFIRMATION_STATE_OWNER_WARNING,
    REVIEW_CONFIRMATION_STATE_REVIEW_PASSED,
    TodayGenieCustomerImageResolution,
    prepare_today_geenee_customer_delivery,
)

KST = ZoneInfo("Asia/Seoul")
PRE09_NOW = datetime(2026, 11, 5, 7, 30, tzinfo=KST)
POST09_NOW = datetime(2026, 11, 5, 9, 15, tzinfo=KST)
REVIEWER_KEY = gate.ReviewerKey("delegated-reviewer", b"delegated-test-key-minimum-32-bytes-secure!")


@pytest.fixture
def base_warning_meta():
    return {
        "run_id": "20261105_065500_today_genie_a1b2c3d4",
        "mode": "today_genie",
        "program_id": "today_genie",
        "target_date": "2026-11-05",
        "response_status": 200,
        "validation_result": "draft_only",
        "runtime_safety_status": "REVIEW_REQUIRED",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "required_count": 3,
        "selected_items": [
            {"title": "Item 1", "url": "https://example.test/1"},
            {"title": "Item 2", "url": "https://example.test/2"},
            {"title": "Item 3", "url": "https://example.test/3"},
        ],
        "selected_items_count": 3,
        "created_at": "2026-11-05T06:55:00+09:00",
        "issue_codes": [
            "today_replay_temporal_conflict",
            "today_replay_temporal_conflict",
            "today_replay_temporal_conflict",
            "top3_item_insufficient_briefing",
        ],
        "parent_run_id": "20261105_063000_today_genie_00112233",
    }


@pytest.fixture
def sample_saved_html():
    return (
        "<!DOCTYPE html><html><body>"
        "<h1>오늘의 지니 장전 브리핑</h1>"
        "<p>민주당이 중간선거에서 압승을 거둔 후, 생활비 부담 완화 및 부패 척결을 위한 새로운 정책 의제를 발표했습니다. "
        "민주당의 정책 방향은 특정 산업 분야에 영향을 미칠 수 있으며, 이는 관련 기업들의 주가에 변동성을 줄 수 있습니다. "
        "국내 증시에서는 미국 민주당의 정책 변화가 국내 수출 기업 및 관련 섹터에 미칠 영향을 분석하여 코스피와 코스닥 흐름을 예측해야 합니다.</p>"
        "<p>06:55 개장 준비 시간에 맞추어 개장 전 확인 사항을 점검합니다.</p>"
        "<a href=\"https://example.test/1\">기사 1</a>"
        "<a href=\"https://example.test/2\">기사 2</a>"
        "<a href=\"https://example.test/3\">기사 3</a>"
        "</body></html>"
    )


def test_delegated_warning_eligible_predicate_positive(base_warning_meta):
    assert today_delegated_warning_eligible(base_warning_meta, now=PRE09_NOW) is True


def test_delegated_warning_eligible_post09_blocked(base_warning_meta):
    assert today_delegated_warning_eligible(base_warning_meta, now=POST09_NOW) is False


def test_delegated_warning_eligible_unknown_substantive_code_blocked(base_warning_meta):
    meta = copy.deepcopy(base_warning_meta)
    meta["issue_codes"].append("wrong_current_president")
    assert today_delegated_warning_eligible(meta, now=PRE09_NOW) is False


def test_delegated_warning_eligible_bare_legacy_pass_without_evidence_rejected():
    bare_meta = {
        "run_id": "20261105_065500_today_genie_a1b2c3d4",
        "mode": "today_genie",
        "target_date": "2026-11-05",
        "response_status": 200,
        "validation_result": "pass",
        "runtime_safety_status": "RUNTIME_SAFETY_PASS",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "created_at": "2026-11-05T06:55:00+09:00",
        "required_count": 3,
        "selected_items": ["a", "b", "c"],
        # Missing issue_codes / empty
    }
    assert today_delegated_warning_eligible(bare_meta, now=PRE09_NOW) is False


def test_delegated_warning_eligible_date_mismatch_blocked(base_warning_meta):
    stale_meta = copy.deepcopy(base_warning_meta)
    stale_meta["target_date"] = "2026-11-04"
    assert today_delegated_warning_eligible(stale_meta, now=PRE09_NOW) is False

    future_meta = copy.deepcopy(base_warning_meta)
    future_meta["target_date"] = "2026-11-06"
    assert today_delegated_warning_eligible(future_meta, now=PRE09_NOW) is False


def test_delegated_warning_eligible_timezone_naive_creation_blocked(base_warning_meta):
    naive_meta = copy.deepcopy(base_warning_meta)
    naive_meta["created_at"] = "2026-11-05T06:55:00"
    assert today_delegated_warning_eligible(naive_meta, now=PRE09_NOW) is False


def test_delegated_warning_eligible_count_mismatch_blocked(base_warning_meta):
    count_meta = copy.deepcopy(base_warning_meta)
    count_meta["required_count"] = 2
    assert today_delegated_warning_eligible(count_meta, now=PRE09_NOW) is False


def test_delegated_warning_eligible_held_or_superseded_blocked(base_warning_meta):
    held_meta = copy.deepcopy(base_warning_meta)
    held_meta["owner_review_status"] = "held"
    assert today_delegated_warning_eligible(held_meta, now=PRE09_NOW) is False

    superseded_meta = copy.deepcopy(base_warning_meta)
    superseded_meta["superseded_by_run_id"] = "20261105_071000_today_genie_beefbeef"
    assert today_delegated_warning_eligible(superseded_meta, now=PRE09_NOW) is False


_orig_today_quality_warning_present = today_quality_warning_present
_orig_today_delegated_warning_eligible = today_delegated_warning_eligible


def test_truthful_renderer_delegated_vs_human(base_warning_meta, sample_saved_html, monkeypatch, tmp_path):
    top_img = tmp_path / "top.jpg"
    top_img.write_bytes(b"jpeg top")
    bot_img = tmp_path / "bottom.jpg"
    bot_img.write_bytes(b"jpeg bottom")
    monkeypatch.setattr(
        "today_geenee_customer_delivery._resolve_today_genie_customer_image_result",
        lambda meta, **kw: TodayGenieCustomerImageResolution(
            inline_parts=[(str(top_img), "cid:top", "top.jpg"), (str(bot_img), "cid:bottom", "bottom.jpg")],
            source="test",
            reason_code="ok",
        ),
    )
    monkeypatch.setattr(
        "today_geenee_customer_delivery.today_quality_warning_present",
        lambda meta, **kw: _orig_today_quality_warning_present(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "today_geenee_customer_delivery.today_delegated_warning_eligible",
        lambda meta, **kw: _orig_today_delegated_warning_eligible(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "customer_review_confirmation.today_quality_warning_present",
        lambda meta, **kw: _orig_today_quality_warning_present(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "customer_review_confirmation.today_delegated_warning_eligible",
        lambda meta, **kw: _orig_today_delegated_warning_eligible(meta, now=kw.get("now") or PRE09_NOW),
    )

    # Delegated render: produces review_passed display state with DELEGATED_REVIEW_TEXT
    delegated_prep = prepare_today_geenee_customer_delivery(
        sample_saved_html,
        base_warning_meta,
        recipients_override=["reader@example.test"],
        approval_source=DELEGATED_WORK_REVIEW,
    )
    assert delegated_prep["ok"] is True
    html = delegated_prep["html_body"]
    assert DELEGATED_REVIEW_TEXT in html
    assert "운영책임자의 직접 검수" not in html
    assert 'data-review-state="review_passed"' in html
    assert f'data-review-source="{DELEGATED_WORK_REVIEW}"' in html

    # Human render: unchanged owner_send_with_warnings
    human_prep = prepare_today_geenee_customer_delivery(
        sample_saved_html,
        base_warning_meta,
        recipients_override=["reader@example.test"],
        approval_source=HUMAN_OWNER,
    )
    assert human_prep["ok"] is True
    human_html = human_prep["html_body"]
    assert HUMAN_OWNER_WARNING_TEXT in human_html
    assert 'data-review-state="owner_send_with_warnings"' in human_html


def test_freeze_candidate_preserves_raw_diagnostics(base_warning_meta, sample_saved_html, monkeypatch, tmp_path):
    top_img = tmp_path / "top.jpg"
    top_img.write_bytes(b"jpeg top")
    bot_img = tmp_path / "bottom.jpg"
    bot_img.write_bytes(b"jpeg bottom")
    monkeypatch.setattr(
        "today_geenee_customer_delivery._resolve_today_genie_customer_image_result",
        lambda meta, **kw: TodayGenieCustomerImageResolution(
            inline_parts=[(str(top_img), "cid:top", "top.jpg"), (str(bot_img), "cid:bottom", "bottom.jpg")],
            source="test",
            reason_code="ok",
        ),
    )
    monkeypatch.setattr(
        "today_geenee_customer_delivery.today_quality_warning_present",
        lambda meta, **kw: _orig_today_quality_warning_present(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "today_geenee_customer_delivery.today_delegated_warning_eligible",
        lambda meta, **kw: _orig_today_delegated_warning_eligible(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "customer_review_confirmation.today_quality_warning_present",
        lambda meta, **kw: _orig_today_quality_warning_present(meta, now=kw.get("now") or PRE09_NOW),
    )
    monkeypatch.setattr(
        "customer_review_confirmation.today_delegated_warning_eligible",
        lambda meta, **kw: _orig_today_delegated_warning_eligible(meta, now=kw.get("now") or PRE09_NOW),
    )

    plan = {
        "schema": safety.SCHEMA,
        "product_code": "today_genie",
        "publication_date": "2026-11-05",
        "frozen_at": (PRE09_NOW - timedelta(minutes=10)).isoformat(),
        "excluded_reason_counts": {},
        "recipients": [
            {
                "account_id": "acc-1",
                "snapshot_id": "snap-1",
                "subscription_id": "sub-1",
                "delivery_email": "reader@example.test",
                "delivery_email_id": "em-1",
                "entitlement_id": "ent-1",
            }
        ],
    }
    plan["sha256"] = safety._digest(plan)
    plan["plan_id"] = "recipient_" + plan["sha256"]

    receipt = {
        "mailbox_id": "owner-review",
        "message_id": "msg-123",
        "internet_message_id": "msg-123@example.test",
        "received_at": (PRE09_NOW - timedelta(minutes=5)).isoformat(),
        "raw_mime_sha256": "a" * 64,
        "render_capture_sha256": "b" * 64,
        "customer_render_capture_sha256": "c" * 64,
    }

    frozen = gate.freeze_candidate(
        meta=base_warning_meta,
        saved_html=sample_saved_html,
        received_message=receipt,
        recipient_plan=plan,
    )

    binding = frozen.binding
    # Raw verdicts explicitly preserved: NOT forged to PASS
    assert binding["first_pass_verdict"] == "HOLD"
    assert binding["customer_surface_status"] == "PRODUCT_REVIEW_REQUIRED"
    assert binding["delegated_warning_eligible"] is True
    assert binding["artifact_metadata"]["issue_codes"] == base_warning_meta["issue_codes"]
    frozen.assert_integrity()


def test_evaluate_shadow_review_warning_eligible_pre09(base_warning_meta):
    candidate = {
        "run_id": base_warning_meta["run_id"],
        "mode": "today_genie",
        "publication_date": "2026-11-05",
        "subject_sha256": "a" * 64,
        "body_sha256": "b" * 64,
        "image_sha256": {"top": "c" * 64, "bottom": "d" * 64},
        "first_pass_verdict": "HOLD",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "artifact_status": "reissued",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "artifact_metadata": base_warning_meta,
        "artifact_sha256": gate.digest(base_warning_meta),
        "received_message_id": "msg-123",
        "parent_run_id": base_warning_meta["parent_run_id"],
        "received_message": {
            "mailbox_id": "owner-review",
            "message_id": "msg-123",
            "internet_message_id": "msg-123@example.test",
            "received_at": (PRE09_NOW - timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "1" * 64,
            "render_capture_sha256": "2" * 64,
        },
    }

    review = {
        **{k: candidate[k] for k in review_module._BINDINGS},
        "policy_version": review_module.POLICY_VERSION,
        "reviewer_agent": "test-agent",
        "reviewer_model": "gpt-5-preview",
        "verdict": "PASS",
        "reviewed_at": (PRE09_NOW - timedelta(minutes=5)).isoformat(),
        "received_message": candidate["received_message"],
        "parent_run_id": candidate["parent_run_id"],
        "checks": {k: "PASS" for k in review_module.REQUIRED_CHECKS},
        "evidence": {k: [f"test://{k}"] for k in review_module.REQUIRED_CHECKS},
        "critical_sources_checked": True,
        "anomalies": [],
    }

    res_pre09 = review_module.evaluate_shadow_review(candidate, review, now=PRE09_NOW)
    assert res_pre09["verdict"] == "PASS"

    res_post09 = review_module.evaluate_shadow_review(candidate, review, now=POST09_NOW)
    assert res_post09["verdict"] == "HOLD"
    assert "FIRST_PASS_NOT_PASS" in res_post09["reason_codes"]


def test_forged_boolean_alone_not_trusted(base_warning_meta):
    tampered_meta = copy.deepcopy(base_warning_meta)
    tampered_meta["issue_codes"].append("substantive_material_error")

    candidate = {
        "run_id": tampered_meta["run_id"],
        "mode": "today_genie",
        "publication_date": "2026-11-05",
        "subject_sha256": "a" * 64,
        "body_sha256": "b" * 64,
        "image_sha256": {"top": "c" * 64, "bottom": "d" * 64},
        "first_pass_verdict": "HOLD",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "artifact_status": "reissued",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "delegated_warning_eligible": True,  # Forged flag
        "artifact_metadata": tampered_meta,
        "artifact_sha256": gate.digest(tampered_meta),
        "received_message_id": "msg-123",
        "parent_run_id": tampered_meta["parent_run_id"],
        "received_message": {
            "mailbox_id": "owner-review",
            "message_id": "msg-123",
            "internet_message_id": "msg-123@example.test",
            "received_at": (PRE09_NOW - timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "1" * 64,
            "render_capture_sha256": "2" * 64,
        },
    }

    review = {
        **{k: candidate[k] for k in review_module._BINDINGS},
        "policy_version": review_module.POLICY_VERSION,
        "reviewer_agent": "test-agent",
        "reviewer_model": "gpt-5-preview",
        "verdict": "PASS",
        "reviewed_at": (PRE09_NOW - timedelta(minutes=5)).isoformat(),
        "received_message": candidate["received_message"],
        "parent_run_id": candidate["parent_run_id"],
        "checks": {k: "PASS" for k in review_module.REQUIRED_CHECKS},
        "evidence": {k: [f"test://{k}"] for k in review_module.REQUIRED_CHECKS},
        "critical_sources_checked": True,
        "anomalies": [],
    }

    # Forged flag rejected because metadata does not satisfy narrow policy
    res = review_module.evaluate_shadow_review(candidate, review, now=PRE09_NOW)
    assert res["verdict"] == "HOLD"
    assert "FIRST_PASS_NOT_PASS" in res["reason_codes"]


def test_tampered_metadata_hash_mismatch_fails(base_warning_meta):
    candidate = {
        "run_id": base_warning_meta["run_id"],
        "mode": "today_genie",
        "publication_date": "2026-11-05",
        "subject_sha256": "a" * 64,
        "body_sha256": "b" * 64,
        "image_sha256": {"top": "c" * 64, "bottom": "d" * 64},
        "first_pass_verdict": "HOLD",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "artifact_status": "reissued",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "artifact_metadata": base_warning_meta,
        "artifact_sha256": "f" * 64,  # Wrong hash
        "received_message_id": "msg-123",
        "parent_run_id": base_warning_meta["parent_run_id"],
        "received_message": {
            "mailbox_id": "owner-review",
            "message_id": "msg-123",
            "internet_message_id": "msg-123@example.test",
            "received_at": (PRE09_NOW - timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "1" * 64,
            "render_capture_sha256": "2" * 64,
        },
    }

    review = {
        **{k: candidate[k] for k in review_module._BINDINGS},
        "policy_version": review_module.POLICY_VERSION,
        "reviewer_agent": "test-agent",
        "reviewer_model": "gpt-5-preview",
        "verdict": "PASS",
        "reviewed_at": (PRE09_NOW - timedelta(minutes=5)).isoformat(),
        "received_message": candidate["received_message"],
        "parent_run_id": candidate["parent_run_id"],
        "checks": {k: "PASS" for k in review_module.REQUIRED_CHECKS},
        "evidence": {k: [f"test://{k}"] for k in review_module.REQUIRED_CHECKS},
        "critical_sources_checked": True,
        "anomalies": [],
    }

    res = review_module.evaluate_shadow_review(candidate, review, now=PRE09_NOW)
    assert res["verdict"] == "HOLD"
    assert "ARTIFACT_METADATA_BINDING_MISMATCH" in res["reason_codes"]


def test_missing_critical_sources_fails(base_warning_meta):
    candidate = {
        "run_id": base_warning_meta["run_id"],
        "mode": "today_genie",
        "publication_date": "2026-11-05",
        "subject_sha256": "a" * 64,
        "body_sha256": "b" * 64,
        "image_sha256": {"top": "c" * 64, "bottom": "d" * 64},
        "first_pass_verdict": "HOLD",
        "customer_surface_status": "PRODUCT_REVIEW_REQUIRED",
        "artifact_status": "reissued",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "artifact_metadata": base_warning_meta,
        "artifact_sha256": gate.digest(base_warning_meta),
        "received_message_id": "msg-123",
        "parent_run_id": base_warning_meta["parent_run_id"],
        "received_message": {
            "mailbox_id": "owner-review",
            "message_id": "msg-123",
            "internet_message_id": "msg-123@example.test",
            "received_at": (PRE09_NOW - timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "1" * 64,
            "render_capture_sha256": "2" * 64,
        },
    }

    review = {
        **{k: candidate[k] for k in review_module._BINDINGS},
        "policy_version": review_module.POLICY_VERSION,
        "reviewer_agent": "test-agent",
        "reviewer_model": "gpt-5-preview",
        "verdict": "PASS",
        "reviewed_at": (PRE09_NOW - timedelta(minutes=5)).isoformat(),
        "received_message": candidate["received_message"],
        "parent_run_id": candidate["parent_run_id"],
        "checks": {k: "PASS" for k in review_module.REQUIRED_CHECKS},
        "evidence": {k: [f"test://{k}"] for k in review_module.REQUIRED_CHECKS},
        "critical_sources_checked": False,  # Failed check
        "anomalies": [],
    }

    res = review_module.evaluate_shadow_review(candidate, review, now=PRE09_NOW)
    assert res["verdict"] == "REVIEW_INCOMPLETE"
    assert "CRITICAL_SOURCE_CHECK_INCOMPLETE" in res["reason_codes"]
