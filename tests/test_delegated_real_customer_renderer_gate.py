"""Regression coverage for the real customer-renderer -> delegated-gate boundary.

External image retrieval and SMTP are deliberately absent here.  The product
preparation functions themselves remain real so this catches wording/state
drift at the boundary that produces the frozen candidate.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

import delegated_delivery_safety as safety
import delegated_gate as gate


NOW = datetime(2026, 9, 10, 7, 0, tzinfo=timezone.utc)
HUMAN_COPY = "운영책임자의 직접 검수"


def _recipient_plan(mode: str) -> dict:
    plan = {
        "schema": safety.SCHEMA,
        "product_code": safety.PRODUCTS[mode],
        "publication_date": "2026-09-10",
        "frozen_at": NOW.isoformat(),
        "excluded_reason_counts": {},
        "recipients": [{
            "account_id": "fixture-account",
            "snapshot_id": "fixture-snapshot",
            "subscription_id": "fixture-subscription",
            "delivery_email": "fixture-reader@example.test",
            "delivery_email_id": "fixture-email",
            "entitlement_id": "fixture-entitlement",
        }],
    }
    plan["sha256"] = safety._digest(plan)
    plan["plan_id"] = f"recipient_{plan['sha256']}"
    return plan


def _receipt() -> dict:
    return {
        "mailbox_id": "fixture-owner-review",
        "message_id": "fixture-message-1",
        "internet_message_id": "fixture-message-1@example.test",
        "received_at": NOW.isoformat(),
        "raw_mime_sha256": "a" * 64,
        "render_capture_sha256": "b" * 64,
        "customer_render_capture_sha256": "c" * 64,
    }


def _case(tmp_path, mode: str) -> tuple[dict, str, dict]:
    run_id = f"20260910_153000_{mode}_aabbccdd"
    top = tmp_path / f"{mode}-top.jpg"
    bottom = tmp_path / f"{mode}-bottom.jpg"
    top.write_bytes(b"fixture top image")
    bottom.write_bytes(b"fixture bottom image")
    meta = {
        "run_id": run_id,
        "mode": mode,
        "validation_result": "pass",
        "artifact_status": "emailed",
        "owner_review_status": "pending_review",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "customer_delivery_status": "not_sent",
        "safety_verdict": "SAFE",
        "editorial_verdict": "READY",
        "selected_items": [{"url": "https://example.test/source"}],
        "service_full_run": True,
        "generated_image_path": str(top),
    }
    if mode == "today_genie":
        meta.update({
            "image_source": "generated",
            "image_generation_status": "generated",
            "generated_image_paths": {"top": str(top), "bottom": str(bottom)},
        })
        saved_html = "<article><h1>Today fixture</h1><a href=\"https://example.test/source\">source</a></article>"
    elif mode == "keysuri_global_tech":
        meta.update({
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "reader_surface_ready_count": 5,
        })
        saved_html = (
            '<table role="presentation"><tr><td><h1>Global fixture</h1>'
            '<img src="cid:keysuri_topshot_global_20260910"></td></tr></table>'
            '<p>본 브리핑은 운영책임자의 직접 검수를 통과했습니다.</p>'
            "<p>Copyright Ⓒ MirAI:ON</p>"
        )
    else:
        meta.update({
            "korea_bottom_shot_path": str(bottom),
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "reader_surface_ready_count": 5,
        })
        saved_html = "<article><h1>Korea fixture</h1><a href=\"https://example.test/source\">source</a></article>"
    return meta, saved_html, _recipient_plan(mode)


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
def test_real_customer_renderer_freezes_a_delegated_candidate(tmp_path, monkeypatch, mode):
    """Actual product preparation must create the final delegated wording pre-freeze."""
    monkeypatch.setattr("admin_store._keysuri_korea_bottom_baseline_confirmed", lambda _: (True, "ok"))
    meta, saved_html, plan = _case(tmp_path, mode)

    candidate = gate.freeze_candidate(
        meta=meta,
        saved_html=saved_html,
        received_message=_receipt(),
        recipient_plan=plan,
    )

    assert HUMAN_COPY not in candidate.customer_html
    assert gate._DELEGATED_COPY in candidate.customer_html
    assert "발송되었습니다" not in candidate.customer_html
    candidate.assert_integrity()
    with pytest.raises(gate.GateError, match="FROZEN_PAYLOAD_CHANGED"):
        replace(candidate, customer_html=candidate.customer_html + "mutated").assert_integrity()


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
def test_real_customer_renderer_manual_path_keeps_human_display_state(tmp_path, mode):
    """The display source changes copy only; it does not grant delivery authority."""
    from keysuri_customer_delivery import prepare_keysuri_customer_delivery
    from today_geenee_customer_delivery import prepare_today_geenee_customer_delivery

    meta, saved_html, _ = _case(tmp_path, mode)
    prepare = prepare_today_geenee_customer_delivery if mode == "today_genie" else prepare_keysuri_customer_delivery
    prepared = prepare(saved_html, meta, recipients_override=["fixture-reader@example.test"])

    assert prepared["ok"] is True
    assert HUMAN_COPY in prepared["html_body"]
    assert gate._DELEGATED_COPY not in prepared["html_body"]
    assert "발송되었습니다" not in prepared["html_body"]


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
def test_real_customer_renderer_rejects_unknown_display_source(tmp_path, mode):
    from keysuri_customer_delivery import prepare_keysuri_customer_delivery
    from today_geenee_customer_delivery import prepare_today_geenee_customer_delivery

    meta, saved_html, _ = _case(tmp_path, mode)
    prepare = prepare_today_geenee_customer_delivery if mode == "today_genie" else prepare_keysuri_customer_delivery
    prepared = prepare(
        saved_html,
        meta,
        recipients_override=["fixture-reader@example.test"],
        approval_source="UNTRUSTED_REQUEST_VALUE",
    )

    assert prepared["ok"] is False
    assert "unsupported customer review approval_source" in prepared["error"]


def test_gate_keeps_human_copy_fail_closed_when_a_renderer_ignores_the_source(tmp_path, monkeypatch):
    meta, saved_html, plan = _case(tmp_path, "today_genie")
    top = tmp_path / "ignored-source-top.jpg"
    bottom = tmp_path / "ignored-source-bottom.jpg"
    top.write_bytes(b"top")
    bottom.write_bytes(b"bottom")
    monkeypatch.setattr(
        "today_geenee_customer_delivery.prepare_today_geenee_customer_delivery",
        lambda *_args, **kwargs: {
            "ok": True,
            "subject": "fixture",
            "html_body": "<p>본 브리핑은 운영책임자의 직접 검수를 통과했습니다.</p>",
            "inline_jpeg_parts": [(str(top), "top", top.name), (str(bottom), "bottom", bottom.name)],
            "recipients": kwargs["recipients_override"],
        },
    )
    with pytest.raises(gate.GateError, match="UNSUPPORTED_HUMAN_APPROVAL_COPY"):
        gate.freeze_candidate(
            meta=meta,
            saved_html=saved_html,
            received_message=_receipt(),
            recipient_plan=plan,
        )
