"""Real prepare/freeze parity plus authenticated, side-effect-free preview GETs."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
import hashlib
import pytest
from fastapi.testclient import TestClient
import admin_routes as routes
import delegated_gate as gate
from main import app
from tests.test_delegated_real_customer_renderer_gate import _case, _receipt, NOW


@pytest.fixture
def preview(tmp_path, monkeypatch):
    monkeypatch.setenv("GENIE_ADMIN_PASSWORD", "fixture-preview-only")
    monkeypatch.setenv("GENIE_RECIPIENT_AUTHORITY", "ADMIN_BETA_DELEGATION")
    monkeypatch.setenv("GENIE_ARTIFACT_STORE_BACKEND", "local")
    meta, html, plan = _case(tmp_path, "keysuri_global_tech")
    meta["owner_review_status"] = "held"
    meta["top_image_cid"] = "keysuri_topshot_global_20260910"
    grant = {"products": [meta["mode"]], "recipients": ["fixture-reader@example.test"],
             "grant_id": "fixture-grant", "_pointer_generation": "fixture-generation",
             "recipient_configuration_version": "fixture-v1", "recipient_configuration_hash": "a" * 64}
    loader = Mock(return_value=grant)
    monkeypatch.setattr("admin_beta_delegation.load_active_admin_beta_delegation", loader)
    monkeypatch.setattr(routes, "load_run_artifact", lambda rid: deepcopy(meta) if rid == meta["run_id"] else None)
    monkeypatch.setattr(routes, "load_run_email_html", lambda rid: html if rid == meta["run_id"] else None)
    monkeypatch.setattr(routes, "active_natural_run_snapshot", lambda: {"active": False})
    from admin_preview_assets import PreviewAsset
    asset = PreviewAsset("top", meta["top_image_cid"], "local", local_path=Path(meta["generated_image_path"]))
    monkeypatch.setattr("admin_preview_assets.preview_assets_for_run", lambda *a: {"top": asset})
    def read_asset(rid, m, slot):
        if rid != meta["run_id"] or slot != "top": return None, None
        return Path(meta["generated_image_path"]).read_bytes(), "image/jpeg"
    monkeypatch.setattr(routes, "read_preview_asset", read_asset)
    real = routes._delegated_email_preview_target
    monkeypatch.setattr(routes, "_delegated_email_preview_target", lambda rid, m, h: real(rid, m, h, now=NOW))
    # Any accidental durable claim/plan/receipt write or sender is a hard failure.
    zero = Mock(side_effect=AssertionError("PREVIEW_MUST_NOT_WRITE_OR_SEND"))
    for target in ["admin_safety_store._create_json_once", "admin_store.hold_run",
                   "admin_store.reopen_held_run", "admin_store.save_run_artifact",
                   "admin_beta_delegation.AdminBetaRecipientAuthority.prepare",
                   "email_sender.send_genie_email", "delegated_gate.register_received_mail_evidence"]:
        monkeypatch.setattr(target, zero)
    for name in ["hold_run", "reopen_held_run", "approve_run", "issue_approval_nonce", "append_operator_audit"]:
        monkeypatch.setattr(routes, name, zero)
    client = TestClient(app)
    client.post("/admin/login", data={"password": "fixture-preview-only"})
    content, binding, target = real(meta["run_id"], meta, html, now=NOW)
    return client, meta, html, plan, grant, loader, zero, content, binding, target, real


def url(p, **extra):
    return f"/admin/runs/{p[1]['run_id']}/email", {"preview_source": "DELEGATED_WORK_REVIEW", "target_sha256": p[9], **extra}


def test_real_target_matches_frozen_candidate_without_mutating_held_run(preview):
    client, meta, html, plan, grant, loader, zero, content, binding, target, real = preview
    before = deepcopy(meta)
    frozen = gate.freeze_candidate(meta=meta, saved_html=html, received_message=_receipt(), recipient_plan=plan)
    assert frozen.customer_html == content
    for field in ["run_id", "mode", "artifact_sha256", "received_html_sha256", "subject_sha256", "body_sha256", "image_identity"]:
        assert binding[field] == frozen.binding[field]
    path, params = url(preview)
    response = client.get(path, params=params)
    assert response.status_code == 200
    assert gate._DELEGATED_COPY in response.text and "운영책임자의 직접 검수" not in response.text
    assert grant["recipients"][0] not in response.text
    assert response.headers["x-genie-preview-target-sha256"] == target
    assert response.headers["x-genie-preview-body-sha256"] == frozen.binding["body_sha256"]
    assert response.headers["cache-control"] == "private, no-store"
    assert "expected_sha256=" + binding["image_identity"][0]["sha256"] in response.text
    assert meta == before and meta["owner_review_status"] == "held"
    assert zero.call_count == 0
    assert all(call.kwargs == {"reconcile_edits": False} for call in loader.call_args_list)


@pytest.mark.parametrize("change", ["body", "meta", "image", "recipient", "grant"])
def test_changed_frozen_target_fails_closed(preview, change, monkeypatch):
    client, meta, html, plan, grant, loader, zero, *_ = preview
    if change == "body":
        monkeypatch.setattr(routes, "load_run_email_html", lambda _: html + "<p>changed</p>")
    elif change == "meta": meta["new_repair_trace"] = "changed"
    elif change == "image": Path(meta["generated_image_path"]).write_bytes(b"changed-image")
    elif change == "recipient": grant["recipients"] = ["changed@example.test"]
    else: grant["_pointer_generation"] = "changed-generation"
    path, params = url(preview)
    assert client.get(path, params=params).status_code == 409
    assert zero.call_count == 0


@pytest.mark.parametrize("extra", [{"approval_snapshot_id": "ambiguous"}, {"preview_source": "HUMAN_OWNER"}, {"target_sha256": ""}, {"target_sha256": "bad"}])
def test_ambiguous_or_unbound_selection_fails_closed(preview, extra):
    path, params = url(preview, **extra)
    assert preview[0].get(path, params=params).status_code == 409
    assert preview[6].call_count == 0


def test_auth_missing_run_and_unsupported_stale_authority(preview, monkeypatch):
    client, meta, html, plan, grant, loader, zero, content, binding, target, real = preview
    path, params = url(preview)
    assert TestClient(app).get(path, params=params, follow_redirects=False).status_code == 303
    assert client.get("/admin/runs/20260910_153000_keysuri_global_tech_deadbeef/email", params=params).status_code == 404
    with pytest.raises(ValueError, match="STALE_PUBLICATION"):
        real(meta["run_id"], meta, html, now=NOW + timedelta(days=1))
    wrong = dict(meta, mode="unsupported")
    with pytest.raises(ValueError, match="UNSUPPORTED_TARGET"):
        real(meta["run_id"], wrong, html, now=NOW)
    monkeypatch.setenv("GENIE_RECIPIENT_AUTHORITY", "unknown")
    assert client.get(path, params=params).status_code == 409
    assert zero.call_count == 0


def test_default_preview_stays_owner_and_has_no_delegated_headers(preview):
    client, meta, html, *_ = preview
    response = client.get(f"/admin/runs/{meta['run_id']}/email")
    assert response.status_code == 200
    assert "x-genie-preview-target-sha256" not in response.headers
    assert gate._DELEGATED_COPY not in response.text


def test_existing_human_snapshot_path_stays_distinct(preview, monkeypatch):
    from types import SimpleNamespace
    verify = Mock(return_value=({}, SimpleNamespace(customer_html="<p>human snapshot fixture</p>")))
    monkeypatch.setattr("admin_approval.verify_approval_snapshot", verify)
    response = preview[0].get(f"/admin/runs/{preview[1]['run_id']}/email", params={"approval_snapshot_id": "existing"})
    assert response.status_code == 200 and "human snapshot fixture" in response.text
    assert "x-genie-preview-target-sha256" not in response.headers
    verify.assert_called_once()


@pytest.mark.parametrize("expected", ["", "bad", "f" * 64])
def test_asset_rejects_bad_or_drifted_bytes(preview, expected):
    path = f"/admin/runs/{preview[1]['run_id']}/preview-assets/top"
    response = preview[0].get(path, params={"expected_sha256": expected})
    assert response.status_code == 409
    assert response.headers["cache-control"] == "private, no-store"
    assert preview[6].call_count == 0


def test_asset_returns_exact_single_verified_read_and_default_is_unchanged(preview, monkeypatch):
    payload = b"exact server artifact bytes"
    read = Mock(side_effect=[(payload, "image/jpeg"), (b"unverified second read", "image/jpeg")])
    monkeypatch.setattr(routes, "read_preview_asset", read)
    path = f"/admin/runs/{preview[1]['run_id']}/preview-assets/top"
    response = preview[0].get(path, params={"expected_sha256": hashlib.sha256(payload).hexdigest()})
    assert response.status_code == 200 and response.content == payload
    assert read.call_count == 1
    assert response.headers["cache-control"] == "private, no-store"
    response = preview[0].get(path)
    assert response.status_code == 200 and response.content == b"unverified second read"


def test_asset_auth_cross_run_slot_and_duplicate_hash(preview):
    path = f"/admin/runs/{preview[1]['run_id']}/preview-assets/top"
    assert TestClient(app).get(path, follow_redirects=False).status_code == 303
    assert preview[0].get(path.replace("aabbccdd", "deadbeef")).status_code == 404
    assert preview[0].get(path.replace("/top", "/bottom")).status_code == 404
    assert preview[0].get(path.replace("/top", "/arbitrary")).status_code == 404
    assert preview[0].get(path, params=[("expected_sha256", "a"*64), ("expected_sha256", "b"*64)]).status_code == 409


def test_artifact_or_grant_changes_during_preparation_fail_closed(preview, monkeypatch):
    path, params = url(preview)
    reads = Mock(side_effect=[deepcopy(preview[1]), dict(preview[1], mutation="raced")])
    monkeypatch.setattr(routes, "load_run_artifact", reads)
    assert preview[0].get(path, params=params).status_code == 409
    monkeypatch.setattr(routes, "load_run_artifact", lambda _: deepcopy(preview[1]))
    preview[5].side_effect = [preview[4], dict(preview[4], _pointer_generation="raced")]
    assert preview[0].get(path, params=params).status_code == 409
    assert preview[6].call_count == 0


@pytest.mark.parametrize("mode", ["today_genie", "keysuri_korea_tech"])
def test_other_two_products_use_real_frozen_display_adapter(preview, tmp_path, monkeypatch, mode):
    meta, html, plan = _case(tmp_path, mode)
    meta["owner_review_status"] = "held"
    monkeypatch.setattr("admin_store._keysuri_korea_bottom_baseline_confirmed", lambda _: (True, "ok"))
    preview[4]["products"] = [mode]
    frozen = gate.freeze_candidate(meta=meta, saved_html=html, received_message=_receipt(), recipient_plan=plan)
    from admin_preview_assets import PreviewAsset
    assets = {image.role: PreviewAsset(image.role, image.cid, "local", local_path=tmp_path / f"{image.role}.jpg") for image in frozen.images}
    monkeypatch.setattr("admin_preview_assets.preview_assets_for_run", lambda *a: assets)
    content, binding, target = preview[10](meta["run_id"], meta, html, now=NOW)
    assert content == frozen.customer_html
    assert binding["subject_sha256"] == frozen.binding["subject_sha256"]
    assert binding["image_identity"] == frozen.binding["image_identity"]
    assert binding["artifact_sha256"] == frozen.binding["artifact_sha256"]
    assert preview[6].call_count == 0
