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


def test_global_warm_cold_restore_keeps_frozen_identity(tmp_path, monkeypatch):
    """Real restore/renderer/freeze: paths are not payload identity."""
    import hashlib
    import socket
    from pathlib import Path
    import keysuri_customer_delivery as delivery

    def no_network(*args, **kwargs):
        raise AssertionError("OFFLINE_ONLY")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    meta, saved_html, plan = _case(tmp_path, "keysuri_global_tech")
    top = Path(meta["generated_image_path"])
    payload = top.read_bytes()
    run_id = meta["run_id"]
    cid = "keysuri_topshot_global_20260910"
    meta.update(
        generated_image_gcs_bucket="offline-artifacts",
        top_image_gcs_object=f"admin_runs/{run_id}.images/global_top.jpg",
        owner_email_inline_image_hashes=[{
            "cid": cid, "filename": top.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }],
    )
    monkeypatch.setattr(delivery, "admin_artifact_bucket_name", lambda: "offline-artifacts")
    monkeypatch.setattr(delivery, "_writable_keysuri_service_assets_dir", lambda: tmp_path)
    downloads = []

    def download(bucket, obj, dest):
        assert bucket == "offline-artifacts"
        assert obj == meta["top_image_gcs_object"]
        downloads.append(str(dest))
        dest.write_bytes(payload)

    resolver = delivery.resolve_keysuri_inline_jpeg_parts
    monkeypatch.setattr(delivery, "resolve_keysuri_inline_jpeg_parts",
                        lambda html, meta: resolver(html, meta, download_fn=download))
    warm = gate.freeze_candidate(meta=meta, saved_html=saved_html,
                                 received_message=_receipt(), recipient_plan=plan)
    assert downloads == []
    top.rename(tmp_path / "preserved-original.jpg")
    cold = gate.freeze_candidate(meta=meta, saved_html=saved_html,
                                 received_message=_receipt(), recipient_plan=plan)
    assert len(downloads) == 1
    assert warm.images[0].content == cold.images[0].content == payload
    assert warm.images[0].filename == cold.images[0].filename == f"{cid}.jpg"
    assert warm.customer_html == cold.customer_html
    assert warm.subject == cold.subject
    assert warm.binding["artifact_sha256"] == cold.binding["artifact_sha256"]
    assert warm.candidate_sha256 == cold.candidate_sha256
    warm.assert_integrity()
    cold.assert_integrity()


def test_global_filename_canonicalization_does_not_ignore_changed_image(tmp_path):
    """Stable transport names must never collapse distinct image content."""
    from pathlib import Path
    meta, saved_html, plan = _case(tmp_path, "keysuri_global_tech")
    first = gate.freeze_candidate(meta=meta, saved_html=saved_html,
                                  received_message=_receipt(), recipient_plan=plan)
    Path(meta["generated_image_path"]).write_bytes(b"different synthetic image")
    second = gate.freeze_candidate(meta=meta, saved_html=saved_html,
                                   received_message=_receipt(), recipient_plan=plan)
    assert first.images[0].filename == second.images[0].filename
    assert first.images[0].content != second.images[0].content
    assert first.candidate_sha256 != second.candidate_sha256


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
