from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json
import re
from threading import Event
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

import admin_store as artifacts
import admin_safety_store as safety
import original_copy_edit as edit
from delegated_gate import GateError, validate_automatic_qa_producer
from publication_content_guard import publication_content_guard, ContentMutationBusy


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    for name in ("GENIE_ARTIFACT_BUCKET", "GENIE_ADMIN_ARTIFACT_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GENIE_ARTIFACT_STORE_BACKEND", "local")
    monkeypatch.setenv("GENIE_ADMIN_SAFETY_LOCAL_DIR", str(tmp_path / "safety"))
    monkeypatch.setenv("GENIE_ADMIN_PASSWORD", "copy-editor-test-password")
    monkeypatch.setattr(artifacts, "admin_runs_dir", lambda: tmp_path)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    run = now.strftime("%Y%m%d_060542_today_genie_") + "abcdef12"
    meta = {"run_id": run, "mode": "today_genie", "target_date": now.date().isoformat(),
            "response_status": 200, "validation_result": "pass", "workflow_status": "validated",
            "runtime_safety_status": "RUNTIME_SAFETY_PASS", "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            "issue_codes": [], "terminal_issue_codes": [], "email_sent": True,
            "owner_review_status": "pending_review", "customer_delivery_status": "not_sent",
            "selected_items": [{"news_id": "source1", "url": "https://example.test/article"}]}
    original = '<html><head><style>.test{color:red}</style></head><body><h1>뉴스</h1><p>트럼프 전 대통령 발언입니다.</p><p>다른 기사는 유지합니다.</p><img src="cid:top"><a href="https://example.test/article">출처</a><table><tr><td>4697.51</td></tr></table><p>운영자 검수 상태</p><p>검수 기록</p></body></html>'
    artifacts.save_run_artifact(meta, email_html=original)
    sender = Mock(return_value={"smtp_accepted": True, "smtp_accepted_recipient_count": 1})
    monkeypatch.setattr(edit, "send_corrected_owner_review", sender)
    return run, original, sender


def packet(run, replacement="트럼프 대통령 발언입니다."):
    original = artifacts.load_run_email_html(run)
    meta = artifacts.load_run_artifact(run, normalize=False)
    _, fields = edit.editable_segments(original)
    field = next(f for f in fields if "트럼프" in f["text"])
    return [{"field_id": field["field_id"], "before_sha256": field["text_sha256"], "replacement": replacement}], {
        "expected_html_sha256": sha256(original.encode()).hexdigest(), "expected_meta_sha256": edit._digest(meta)}


def test_literal_edit_preserves_received_original_images_links_and_other_story(setup):
    run, original, sender = setup
    changes, basis = packet(run)
    before = artifacts.load_run_artifact(run)
    result = edit.apply_copy_edit(run, changes, **basis, actual_actor="CODEX")
    revised = artifacts.load_run_email_html(run)
    assert revised == original.replace("트럼프 전 대통령", "트럼프 대통령")
    assert artifacts.artifact_email_path(run).read_text() == original
    assert sender.call_count == 1
    assert sender.call_args.args[0] == revised
    meta = artifacts.load_run_artifact(run)
    assert meta["validation_result"] == before["validation_result"]
    assert meta["original_copy_revision"]["producer_qa_is_pre_edit"] is True
    assert meta["copy_review_required"] is True
    assert meta["customer_delivery_status"] == "not_sent"
    assert result["model_calls"] == result["image_calls"] == 0
    assert not list(safety._local_root().glob("publication_attempts/*"))


def test_old_automatic_qa_cannot_authorize_the_edited_copy(setup):
    run, _, _ = setup
    validate_automatic_qa_producer(artifacts.load_run_artifact(run))
    changes, basis = packet(run)
    edit.apply_copy_edit(run, changes, **basis)
    with pytest.raises(GateError, match="AUTOMATIC_QA_STALE_AFTER_COPY_EDIT"):
        validate_automatic_qa_producer(artifacts.load_run_artifact(run))


def test_double_post_is_idempotent_but_different_change_is_not_silently_ignored(setup):
    run, _, sender = setup
    changes, basis = packet(run)
    one = edit.apply_copy_edit(run, changes, **basis)
    two = edit.apply_copy_edit(run, changes, **basis)
    assert two["already_applied"] and one["revision_id"] == two["revision_id"]
    assert sender.call_count == 1
    changes[0]["replacement"] = "다른 수정"
    with pytest.raises(edit.CopyEditError, match="BASE_CHANGED"):
        edit.apply_copy_edit(run, changes, **basis)


def test_storage_failure_after_pointer_resumes_without_reediting(setup, monkeypatch):
    run, original, sender = setup
    changes, basis = packet(run)
    write = safety._write_json
    def fail_once(key, row):
        if row.get("state") == "APPLIED_OWNER_MAIL_PENDING":
            raise OSError("fixture storage interrupted")
        return write(key, row)
    monkeypatch.setattr(safety, "_write_json", fail_once)
    with pytest.raises(OSError):
        edit.apply_copy_edit(run, changes, **basis)
    sender.assert_not_called()
    assert artifacts.load_run_email_html(run) == original.replace("트럼프 전 대통령", "트럼프 대통령")
    monkeypatch.setattr(safety, "_write_json", write)
    assert edit.apply_copy_edit(run, changes, **basis)["owner_mail_state"] == "SMTP_ACCEPTED"
    sender.assert_called_once()


def test_accepted_mail_projection_failure_is_repaired_without_smtp(setup, monkeypatch):
    run, _, sender = setup
    changes, basis = packet(run)
    update = artifacts.update_run_artifact
    monkeypatch.setattr(artifacts, "update_run_artifact", Mock(side_effect=OSError("fixture stamp failed")))
    with pytest.raises(OSError):
        edit.apply_copy_edit(run, changes, **basis)
    sender.assert_called_once()
    monkeypatch.setattr(artifacts, "update_run_artifact", update)
    assert edit.apply_copy_edit(run, changes, **basis)["owner_mail_state"] == "SMTP_ACCEPTED"
    sender.assert_called_once()
    assert artifacts.load_run_artifact(run)["owner_email_delivery_status"] == "smtp_accepted"


def test_unknown_mail_outcome_never_repeats_smtp_or_discards_copy(setup):
    run, original, sender = setup
    changes, basis = packet(run)
    sender.side_effect = OSError("fixture unknown after SMTP")
    with pytest.raises(edit.CopyEditError, match="OWNER_MAIL_RECONCILE"):
        edit.apply_copy_edit(run, changes, **basis)
    assert edit.apply_copy_edit(run, changes, **basis)["owner_mail_state"] == "RECONCILE"
    sender.assert_called_once()
    assert artifacts.load_run_email_html(run) != original


def test_old_review_projection_is_retained_as_history_and_removed_from_active_copy(setup):
    run, _, _ = setup
    artifacts.update_run_artifact(run, lambda m: m.update(delegated_review_id="old-review", delegated_review_status="passed",
        delegated_candidate_sha256="a" * 64, approval_source="DELEGATED_WORK_REVIEW"))
    changes, basis = packet(run)
    edit.apply_copy_edit(run, changes, **basis)
    meta = artifacts.load_run_artifact(run)
    assert meta["original_copy_revision"]["prior_review_projection"]["delegated_review_id"] == "old-review"
    assert meta["delegated_review_status"] == "pending" and "delegated_review_id" not in meta


def test_preview_has_no_storage_or_send_effect(setup):
    run, original, sender = setup
    changes, basis = packet(run)
    result = edit.prepare_copy_edit(run, changes, **basis)
    assert result["html"] != original
    assert artifacts.load_run_email_html(run) == original
    assert not artifacts.load_run_artifact(run).get("original_copy_revision")
    sender.assert_not_called()


def test_quoted_markup_and_source_attributes_are_never_editable():
    raw = '<img title="x>attribute" src="cid:top"><!-- keep > comment --><p>문장</p>'
    tokens, fields = edit.editable_segments(raw)
    assert "".join(tokens) == raw
    assert [f["text"] for f in fields] == ["문장"]


@pytest.mark.parametrize("conflict", [False, True])
def test_gcs_pointer_is_generation_conditioned_and_never_overwrites_a_race(setup, monkeypatch, conflict):
    from google.api_core.exceptions import PreconditionFailed
    run, _, _ = setup
    changes, basis = packet(run)
    prepared = edit.prepare_copy_edit(run, changes, **basis)
    class Blob:
        generation = 123
        def reload(self): pass
        def download_as_bytes(self, **kw):
            assert kw == {"if_generation_match": 123}
            return json.dumps(prepared["meta"]).encode()
        def upload_from_string(self, data, **kw):
            assert kw["if_generation_match"] == 123
            if conflict:
                raise PreconditionFailed("fixture concurrent metadata writer")
            self.saved = json.loads(data)
    blob = Blob()
    monkeypatch.setattr(artifacts, "_uses_gcs_backend", lambda: True)
    monkeypatch.setattr(artifacts, "_get_gcs_bucket", lambda: Mock(blob=lambda k: blob))
    monkeypatch.setattr(artifacts, "_write_summary_blob", Mock())
    revision = {"revision_id": prepared["revision_id"], "html_sha256": prepared["html_sha256"]}
    if conflict:
        with pytest.raises(edit.CopyEditError, match="BASE_CHANGED"):
            edit._commit_pointer(prepared, revision)
        assert not hasattr(blob, "saved")
    else:
        edit._commit_pointer(prepared, revision)
        assert blob.saved["copy_review_required"] is True


def test_nov26_pce_correction_keeps_the_other_cards_korea_tariff_conditions(setup):
    run, _, _ = setup
    original = '<h1>검수본</h1><p>한국산 최대 15% 검토는 기존 MFN·301조 관세 고려와 일부 상품 예외가 있는 미확정안입니다.</p><p>미국 10월 전체 PCE는 예상보다 높은 3.8%입니다.</p><p>근원 PCE는 3.3%, 예상은 3.2%입니다.</p>'
    artifacts._write_email_blob(run, original)
    _, fields = edit.editable_segments(original)
    field = next(f for f in fields if "전체 PCE" in f["text"])
    changes = [{"field_id": field["field_id"], "before_sha256": field["text_sha256"],
                "replacement": "미국 10월 전체 PCE는 전년 대비 3.8%로 예상 3.8%에 부합했습니다."}]
    meta = artifacts.load_run_artifact(run, normalize=False)
    edit.apply_copy_edit(run, changes, expected_html_sha256=sha256(original.encode()).hexdigest(),
                         expected_meta_sha256=edit._digest(meta))
    revised = artifacts.load_run_email_html(run)
    assert "한국산 최대 15% 검토는 기존 MFN·301조 관세 고려와 일부 상품 예외가 있는 미확정안입니다." in revised
    assert "근원 PCE는 3.3%, 예상은 3.2%입니다." in revised
    assert revised == original.replace(field["text"], changes[0]["replacement"])


def test_markup_is_escaped_and_source_links_are_not_editable(setup):
    run, original, _ = setup
    changes, basis = packet(run, '<script>alert("x")</script>')
    result = edit.prepare_copy_edit(run, changes, **basis)
    assert "&lt;script&gt;" in result["html"] and '<script>' not in result["html"]
    _, fields = edit.editable_segments(original)
    assert not any(f["text"] in {"出처", "출처", "4697.51", "검수 기록", ".test{color:red}"} for f in fields)


@pytest.mark.parametrize("state", ["held", "approved", "dismissed"])
def test_owner_hold_and_review_states_are_preserved(setup, state):
    run, original, sender = setup
    changes, basis = packet(run)
    artifacts.update_run_artifact(run, lambda m: m.update(owner_review_status=state))
    with pytest.raises(edit.CopyEditError):
        edit.apply_copy_edit(run, changes, **basis)
    assert artifacts.load_run_email_html(run) == original
    assert artifacts.load_run_artifact(run)["owner_review_status"] == state
    sender.assert_not_called()


def test_other_lineage_publication_claim_prevents_editing_a_not_sent_ancestor(setup):
    from delegated_delivery_safety import PRODUCTS, _digest
    run, original, sender = setup
    changes, basis = packet(run)
    meta = artifacts.load_run_artifact(run)
    attempt = "publication_" + _digest([PRODUCTS[meta["mode"]], meta["target_date"]])
    safety._create_json_once(f"publication_attempts/{attempt}.json", {"run_id": "other-child", "status": "RESERVED_OUTCOME_UNKNOWN"})
    with pytest.raises(edit.CopyEditError, match="PUBLICATION_ALREADY_ATTEMPTED"):
        edit.apply_copy_edit(run, changes, **basis)
    assert artifacts.load_run_email_html(run) == original
    sender.assert_not_called()


def test_tampered_immutable_revision_is_not_served(setup):
    run, _, _ = setup
    changes, basis = packet(run)
    result = edit.apply_copy_edit(run, changes, **basis)
    edit._local_revision_path(run, result["revision_id"]).write_text("tampered")
    with pytest.raises(edit.CopyEditError, match="HASH_MISMATCH"):
        artifacts.load_run_email_html(run)


def test_original_copy_edit_and_existing_owner_submission_are_serialized(setup):
    run, _, _ = setup
    meta = artifacts.load_run_artifact(run)
    entered, leave = Event(), Event()
    def holding():
        with publication_content_guard(meta["mode"], meta["target_date"], run_id=run, action="fixture_edit"):
            entered.set()
            assert leave.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(holding)
        assert entered.wait(5)
        try:
            result, error = artifacts.approve_run(run)
            assert result is None and error == "PUBLICATION_CONTENT_OPERATION_RUNNING_OR_UNKNOWN"
        finally:
            leave.set()
        future.result()
    with publication_content_guard(meta["mode"], meta["target_date"], run_id=run, action="after_release"):
        pass


def test_unknown_inflight_mutex_never_expires_into_another_attempt(setup):
    from publication_content_guard import _key
    run, _, _ = setup
    meta = artifacts.load_run_artifact(run)
    safety._create_json_once(_key(meta["mode"], meta["target_date"]),
                             {"operation_id": "old", "state": "RUNNING", "created_at": "2000-01-01"})
    with pytest.raises(ContentMutationBusy):
        with publication_content_guard(meta["mode"], meta["target_date"], run_id=run, action="no_guessing"):
            pytest.fail("unknown operation must not be replaced")


def test_admin_entry_requires_auth_csrf_and_saves_literal_copy_only(setup, monkeypatch):
    from main import app
    run, original, sender = setup
    client = TestClient(app, base_url="https://testserver")
    assert client.get(f"/admin/runs/{run}/copy-edit", follow_redirects=False).status_code == 303
    client.post("/admin/login", data={"password": "copy-editor-test-password"})
    page = client.get(f"/admin/runs/{run}/copy-edit")
    assert page.status_code == 200 and "문구만 수정" in page.text
    changes, basis = packet(run)
    data = {**basis, "changes_json": json.dumps(changes), "actual_actor": "CODEX"}
    monkeypatch.setenv("K_SERVICE", "csrf-enabled-fixture")
    monkeypatch.setenv("GENIE_ADMIN_ALLOW_LOCAL_SAFETY_STORE", "1")
    assert client.post(f"/admin/runs/{run}/copy-edit", data=data).status_code == 403
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text).group(1)
    data["csrf_token"] = token
    preview = client.post(f"/admin/runs/{run}/copy-edit/preview", data=data)
    assert preview.status_code == 200 and "아직 저장" in preview.text
    assert 'name="changes_json"' in preview.text and "수정 전" in preview.text and "수정 후" in preview.text
    assert artifacts.load_run_email_html(run) == original
    applied = client.post(f"/admin/runs/{run}/copy-edit", data=data, follow_redirects=False)
    assert applied.status_code == 303 and "copy_edit=saved" in applied.headers["location"]
    assert "트럼프 전 대통령" not in artifacts.load_run_email_html(run)
    sender.assert_called_once()
