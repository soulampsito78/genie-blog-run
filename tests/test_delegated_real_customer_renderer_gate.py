"""Regression coverage for the real customer-renderer -> delegated-gate boundary.

External image retrieval and SMTP are deliberately absent here.  The product
preparation functions themselves remain real so this catches wording/state
drift at the boundary that produces the frozen candidate.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

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


def _email_semantics_without_layout(source):
    from html.parser import HTMLParser
    class Semantics(HTMLParser):
        def __init__(self):
            super().__init__(); self.events = []
        def handle_starttag(self, tag, attrs):
            self.events.append((tag, tuple((k, v) for k, v in attrs if k != "style")))
        def handle_endtag(self, tag): self.events.append(("end", tag))
        def handle_data(self, data): self.events.append(("text", data))
    parser = Semantics(); parser.feed(source); return parser.events


def _assert_gmail_tables_have_fixed_layout(source):
    from html.parser import HTMLParser
    class Tables(HTMLParser):
        def __init__(self): super().__init__(); self.tables = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "table" and attrs.get("role") == "presentation": self.tables.append(attrs)
    parser = Tables(); parser.feed(source)
    assert parser.tables
    assert all("table-layout:fixed" in a.get("style", "").replace(" ", "") for a in parser.tables)


@pytest.mark.parametrize("source", ["HUMAN_OWNER", "DELEGATED_WORK_REVIEW"])
def test_gmail_customer_saved_legacy_layout_is_bounded_not_just_future_generation(source):
    from keysuri_customer_delivery import prepare_gmail_global_customer_final_html
    from tests.test_keysuri_customer_delivery import _keysuri_global_gmail_owner_review_email_html
    saved = _keysuri_global_gmail_owner_review_email_html().replace("table-layout:fixed;", "")
    original = saved[:]
    prepared = prepare_gmail_global_customer_final_html(saved, approval_source=source)
    _assert_gmail_tables_have_fixed_layout(prepared)
    assert saved == original
    assert prepare_gmail_global_customer_final_html(prepared, approval_source=source) == prepared
    assert (gate._DELEGATED_COPY in prepared) == (source == "DELEGATED_WORK_REVIEW")


@pytest.mark.parametrize("program", ["global", "korea"])
def test_gmail_future_owner_and_actual_customer_share_bounded_table_layout(program):
    import keysuri_contract_preview_renderer as renderer
    from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture, build_korea_contract_fixture
    fixture = build_global_contract_fixture() if program == "global" else build_korea_contract_fixture()
    build = renderer.build_keysuri_global_gmail_owner_email_html if program == "global" else renderer.build_keysuri_korea_gmail_owner_email_html
    saved = build(fixture, subject="synthetic layout fixture")
    _assert_gmail_tables_have_fixed_layout(saved)


def test_gmail_layout_fix_preserves_every_content_link_cid_and_nonlayout_attribute():
    from keysuri_contract_preview_renderer import bound_gmail_presentation_table_layout
    before = ('<table role="presentation" width="100%" style="background:white;table-layout:auto">'
              '<tr><td><a href="https://example.test/exact?a=1&amp;b=2">원문 그대로</a>'
              '<img src="cid:exact-original-cid" width="896"><blockquote>정확 인용문</blockquote>'
              '</td></tr></table><table role="presentation" width="600"><tr><td>내용</td></tr></table>'
              '<table id="unrelated"><tr><td>다른 테이블</td></tr></table>')
    after = bound_gmail_presentation_table_layout(before)
    assert _email_semantics_without_layout(before) == _email_semantics_without_layout(after)
    assert bound_gmail_presentation_table_layout(after) == after
    assert '<table id="unrelated">' in after
    assert "overflow:hidden" not in after  # constrain the layout, do not hide content
    _assert_gmail_tables_have_fixed_layout(after)


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


@pytest.mark.parametrize(("mode", "slot"), [
    ("today_genie", "06:30"),
    ("keysuri_global_tech", "12:30"),
    ("keysuri_korea_tech", "18:30"),
])
@pytest.mark.parametrize("fault", [None, "early", "caution", "wrong_mime", "suppressed"])
def test_automatic_pass_uses_bound_mime_and_same_delivery_guard(tmp_path, monkeypatch, mode, slot, fault):
    from unittest.mock import Mock

    import admin_safety_store as store
    from customer_review_confirmation import AUTOMATIC_QA_TEXT, DELEGATED_AUTOMATIC_QA
    from scripts import submit_delegated_work_review as helper

    monkeypatch.setattr(store, "_uses_gcs_backend", lambda: False)
    monkeypatch.setenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", str(tmp_path / "ledger"))
    monkeypatch.setattr("admin_store._keysuri_korea_bottom_baseline_confirmed", lambda _: (True, "ok"))
    meta, saved_html, plan = _case(tmp_path, mode)
    now = NOW + timedelta(hours=3)
    if fault == "early":
        now = datetime.fromisoformat(f"2026-09-10T{slot}:00+09:00") - timedelta(seconds=1)
    meta.update(
        execution_class="natural_scheduled", scheduled_slot=slot, kst_schedule_date="2026-09-10",
        email_sent=True, runtime_safety_status="RUNTIME_SAFETY_PASS",
        issue_codes=["meta_lead_opening"], terminal_issue_codes=[], review_issue_codes=[],
    )
    if mode != "today_genie":
        meta.update(editorial_verdict="REVIEW", review_issue_codes=["meta_lead_opening"])
        meta["issue_codes"].append("keysuri_korean_connector_ellipsis_repaired")
        meta["repaired_issue_codes"] = ["keysuri_korean_connector_ellipsis_repaired"]
    if fault == "caution":
        meta["review_issue_codes"] = ["SOURCE_CLAIM_CONTRADICTION"]
    run_id = meta["run_id"]
    saved_html += f"<p>{run_id}</p>"
    receipt = {**_receipt(), "review_basis": DELEGATED_AUTOMATIC_QA}
    fixture = gate.freeze_candidate(meta=meta, saved_html=saved_html, received_message=receipt, recipient_plan=plan)
    monkeypatch.setattr("admin_store.load_run_artifact", lambda _: meta)
    monkeypatch.setattr("admin_store.load_run_email_html", lambda _: saved_html)
    safety.record_delivery_cutover(starts_on="2026-09-10", inventory_sha256="1"*64,
        evidence_refs=["fixture://inventory"], operator_id="fixture", all_writers_use_publication_guard=True)
    store._create_json_once("delegated_recipient_plans/" + plan["plan_id"] + ".json", plan)
    message = EmailMessage()
    message["Message-ID"] = "<automatic-qa@example.test>"
    message.set_content("Alternate body")
    message.add_alternative(saved_html, subtype="html")
    for image in fixture.images:
        data = b"not the received image" if fault == "wrong_mime" else image.content
        message.get_payload()[-1].add_related(data, maintype="image", subtype="jpeg", cid=f"<{image.cid}>")
    receipt_args = dict(
        run_id=run_id, mailbox_id="fixture-inbox", message_id="fixture-received-id",
        received_at=(NOW - timedelta(minutes=10)).isoformat(), raw_mime=message.as_bytes(),
        render_capture=b"", customer_render_capture=b"", recipient_plan=plan,
        review_basis=DELEGATED_AUTOMATIC_QA, now=now,
    )
    registration_errors = {
        "early": "AUTOMATIC_QA_BEFORE_PUBLICATION_TARGET",
        "caution": "AUTOMATIC_QA_WARNING_REQUIRES_REVIEW",
        "wrong_mime": "RECEIVED_IMAGE_ARTIFACT_MISMATCH",
    }
    if fault in registration_errors:
        with pytest.raises(gate.GateError, match=registration_errors[fault]):
            gate.register_received_mail_evidence(**receipt_args)
        assert store._read_json(f"delegated_received_bindings/{gate._sha(run_id.encode())}.json") is None
        return

    gate.register_received_mail_evidence(**receipt_args)
    authority = Mock()
    if fault == "suppressed":
        authority.revalidate.side_effect = safety.DeliverySafetyError("DELIVERY_SUPPRESSED")
    loader = gate.RunArtifactCandidateLoader(authority)
    candidate = loader.load(run_id, now=now)
    key = gate.ReviewerKey("fixture-runner", b"test-only-key-not-used-in-operation")
    settings = gate.GateSettings(mode="ON", authorized_policy=gate.POLICY_VERSION, reviewer_keys={"fixture": key})
    event = helper._construct_review_event(
        {"run_id": run_id}, candidate, principal=key.principal, reviewer_model="",
        policy_version=gate.POLICY_VERSION, now=now, event_id="auto_qa_fixture_event_1",
    )
    assert event["review"] == {"reviewer_agent": key.principal}
    sender = Mock(return_value={"outcome": "ACCEPTED_ALL"})

    def dispatch():
        signed = helper._sign_review_event(event, canonicalize=gate.canonical, key_id="fixture", secret=key.secret)
        return gate.process_review_event(*signed, loader=loader, recipient_authority=authority,
                                         now=now, settings=settings, sender=sender)

    result = dispatch()
    if fault == "suppressed":
        assert result["reason_codes"] == ["DELIVERY_SUPPRESSED"]
        sender.assert_not_called()
        return
    assert result["submission_outcome"] == "ACCEPTED_ALL"
    assert result["approval_source"] == DELEGATED_AUTOMATIC_QA
    assert result["owner_approval_basis"] == "STANDING_SCHEDULED_PUBLICATION_2026_11_10"
    assert result["reviewer_model"] is None and result["reviewed_at"] is None
    delivered = sender.call_args.args[0]
    assert AUTOMATIC_QA_TEXT in delivered.customer_html
    assert HUMAN_COPY not in delivered.customer_html and gate._DELEGATED_COPY not in delivered.customer_html
    assert store._read_json(f"publication_outcomes/{result['attempt_id']}.json")["outcome"] == "PROVIDER_ACCEPTED"
    event["event_id"] = "auto_qa_fixture_event_2"
    assert dispatch()["reason_codes"] == ["DELIVERY_HANDOFF_ALREADY_CLAIMED"]
    sender.assert_called_once()


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
