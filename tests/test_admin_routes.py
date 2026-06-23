"""Minimal tests for owner admin routes and artifact listing."""
from __future__ import annotations

import json
import os
import re
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from admin_store import (
    EXECUTABLE_REISSUE_SCOPE,
    admin_runs_dir,
    apply_reissue_child_metadata,
    approve_run,
    build_customer_delivery_admin_panel,
    load_run_artifact,
    mask_customer_email,
    save_run_artifact,
)
from main import app


def post_customer_approve_with_confirm(
    client: TestClient,
    run_id: str,
    *,
    note: str = "ok",
    include_checkbox: bool = True,
    include_nonce: bool = True,
    nonce_override: str | None = None,
):
    confirm_resp = client.get(f"/admin/runs/{run_id}/approve-confirm")
    nonce = nonce_override
    if include_nonce and nonce is None:
        match = re.search(r'name="approve_nonce" value="([^"]+)"', confirm_resp.text)
        nonce = match.group(1) if match else ""
    data: dict[str, str] = {"approve_note": note}
    if include_nonce:
        data["approve_nonce"] = nonce or ""
    if include_checkbox:
        data["customer_send_confirm"] = "1"
    return client.post(f"/admin/runs/{run_id}/approve", data=data, follow_redirects=False)


class AdminRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def test_admin_disabled_without_password(self) -> None:
        os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        client = TestClient(app)
        resp = client.get("/admin")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("GENIE_ADMIN_PASSWORD", resp.text)

    def test_wrong_password_rejected(self) -> None:
        resp = self.client.post("/admin/login", data={"password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_correct_password_sets_session(self) -> None:
        resp = self.client.post(
            "/admin/login",
            data={"password": "test-admin-secret"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("genie_admin_session", resp.cookies)
        runs = self.client.get("/admin/runs")
        self.assertEqual(runs.status_code, 200)

    def test_run_list_reads_json_artifacts(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = save_run_artifact(
            {
                "run_id": "20260530_120000_today_genie_aabbccdd",
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<p>test email</p>",
        )
        path = admin_runs_dir() / f"{run_id}.json"
        self.assertTrue(path.is_file())
        resp = self.client.get("/admin/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(run_id, resp.text)

    def test_reissue_requires_login(self) -> None:
        run_id = "20260530_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{run_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": EXECUTABLE_REISSUE_SCOPE,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/admin", resp.headers.get("location", ""))

    def test_admin_detail_includes_reissue_scope_labels(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_121000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:10:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("본문만 재발행", resp.text)
        self.assertIn("이미지만 재발행", resp.text)
        self.assertIn("본문·이미지 모두 재발행", resp.text)
        self.assertIn("운영자 검토 메일", resp.text)
        self.assertIn("고객 이메일 발송 상태", resp.text)
        self.assertIn("선택할 수 있지만, 실행은 아직 차단됩니다", resp.text)

    def test_reissue_scope_radios_are_selectable_not_disabled(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_121100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotRegex(resp.text, r'value="text_only"[^>]*\bdisabled\b')
        self.assertNotRegex(resp.text, r'value="image_only"[^>]*\bdisabled\b')
        self.assertRegex(resp.text, r'value="text_and_image"[^>]*\bchecked\b')
        self.assertIn('name="reissue_scope"', resp.text)
        self.assertIn('class="radio-scope"', resp.text)
        self.assertIn('class="radio-helper"', resp.text)

    def test_admin_pages_include_viewport_meta(self) -> None:
        login_resp = self.client.get("/admin")
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn('name="viewport"', login_resp.text)
        self.assertIn("width=device-width", login_resp.text)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        runs_resp = self.client.get("/admin/runs")
        self.assertEqual(runs_resp.status_code, 200)
        self.assertIn('name="viewport"', runs_resp.text)
        self.assertIn('class="table-wrap"', runs_resp.text)
        run_id = "20260530_121200_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        detail_resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn('name="viewport"', detail_resp.text)
        self.assertIn('class="page-head"', detail_resp.text)

    def test_admin_detail_labels_smtp_accepted_not_delivery_confirmed(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_122000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "customer_delivery_status": "smtp_accepted",
                "customer_sent_at": "2026-05-30T12:20:00+09:00",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertIn("고객 이메일 발송 상태", resp.text)
        self.assertIn("PASS", resp.text)
        self.assertIn("발송 접수 완료", resp.text)
        self.assertIn("SMTP 접수", resp.text)
        self.assertNotIn("전달 확인", resp.text)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_text_and_image_executes_and_persists_scope(self, mock_exec) -> None:
        child_id = "20260530_130000_today_genie_11223344"
        mock_exec.return_value = (child_id, object(), True)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "today_genie",
                "parent_run_id": parent_id,
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "구성 품질 이슈",
                "reason_note": "retry",
                "reissue_scope": EXECUTABLE_REISSUE_SCOPE,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        mock_exec.assert_called_once()
        kwargs = mock_exec.call_args.kwargs
        self.assertTrue(kwargs.get("admin_reissue"))
        self.assertEqual(kwargs.get("parent_run_id"), parent_id)
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("reissue_scope"), EXECUTABLE_REISSUE_SCOPE)
        self.assertTrue(child.get("reissue_scope_supported"))
        self.assertEqual(child.get("reissue_scope_status"), "executed")
        self.assertEqual(child.get("reissue_reason_code"), "구성 품질 이슈")
        self.assertEqual(child.get("reissue_reason_note"), "retry")
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("last_reissue_scope_requested"), EXECUTABLE_REISSUE_SCOPE)
        self.assertEqual(parent.get("last_reissue_child_run_id"), child_id)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_text_only_blocked(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": "text_only",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("unsupported_reissue_scope", str(resp.url))
        self.assertIn("아직 실행할 수 없습니다", resp.text)
        self.assertNotIn("sent_archived", resp.text)
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_image_only_blocked(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120200_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "이미지 품질 이슈",
                "reason_note": "",
                "reissue_scope": "image_only",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("unsupported_reissue_scope", str(resp.url))
        self.assertIn("본문·이미지 모두 재발행만 실행 가능합니다", resp.text)
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_invalid_scope_rejected(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120300_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={"reason_option": "기타", "reason_note": "", "reissue_scope": "full_reset"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("invalid_reissue_scope", resp.headers.get("location", ""))
        mock_exec.assert_not_called()


class AdminApprovalHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        self._prev_customer = os.environ.get("GENIE_CUSTOMER_EMAIL_TO")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_PASSWORD", self._prev_pwd),
            ("GENIE_CUSTOMER_EMAIL_TO", self._prev_customer),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def _save_today_run(self, run_id: str) -> None:
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
            },
            email_html="<p>brief</p>",
        )

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_direct_post_approve_without_nonce_rejected(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170000_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={"approve_note": "ok", "customer_send_confirm": "1"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("missing_approval_nonce", resp.headers.get("location", ""))
        mock_send.assert_not_called()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_post_approve_without_checkbox_rejected(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170100_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = post_customer_approve_with_confirm(
            self.client,
            run_id,
            include_checkbox=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("missing_customer_send_confirm", resp.headers.get("location", ""))
        mock_send.assert_not_called()

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_post_approve_with_valid_nonce_and_checkbox_sends_once(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170200_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = post_customer_approve_with_confirm(self.client, run_id, note="browser ok")
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("approve_error", resp.headers.get("location", ""))
        mock_send.assert_called_once()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "approved")
        self.assertEqual(meta.get("approval_channel"), "browser_confirm")
        self.assertTrue(meta.get("approval_nonce_used"))
        self.assertEqual(meta.get("approval_note"), "browser ok")

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_approval_nonce_cannot_be_reused(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170300_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        confirm_resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        match = re.search(r'name="approve_nonce" value="([^"]+)"', confirm_resp.text)
        self.assertIsNotNone(match)
        nonce = match.group(1)
        first = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={
                "approve_note": "once",
                "approve_nonce": nonce,
                "customer_send_confirm": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(first.status_code, 303)
        mock_send.assert_called_once()
        second = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={
                "approve_note": "twice",
                "approve_nonce": nonce,
                "customer_send_confirm": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(second.status_code, 303)
        self.assertIn("approve_error", second.headers.get("location", ""))
        mock_send.assert_called_once()

    def test_approve_confirm_includes_checkbox_and_hidden_nonce(self) -> None:
        run_id = "20260615_170400_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("고객 이메일 발송을 승인합니다", resp.text)
        self.assertIn('name="approve_nonce"', resp.text)
        self.assertIn("genie_approve_nonce", resp.cookies)


class AdminStoreReissueMetadataTests(unittest.TestCase):
    def test_apply_reissue_child_metadata_persists_scope(self) -> None:
        child_id = "20260530_140000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        updated = apply_reissue_child_metadata(
            child_id,
            reissue_scope=EXECUTABLE_REISSUE_SCOPE,
            reissue_reason_code="제목 수정 요청",
            reissue_reason_note="note",
        )
        assert updated is not None
        reloaded = load_run_artifact(child_id) or {}
        self.assertEqual(reloaded.get("reissue_scope"), EXECUTABLE_REISSUE_SCOPE)
        self.assertEqual(reloaded.get("reissue_scope_status"), "executed")


class CustomerDeliveryAdminPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def _login(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def test_mask_customer_email(self) -> None:
        self.assertEqual(mask_customer_email("tera9003@daum.net"), "t***3@daum.net")
        self.assertEqual(mask_customer_email("tomato3593@gmail.com"), "t***3@gmail.com")
        self.assertEqual(mask_customer_email("aegis001@naver.com"), "a***1@naver.com")
        self.assertEqual(mask_customer_email("kha6210@hanmail.com"), "k***0@hanmail.com")

    def test_panel_smtp_accepted_run(self) -> None:
        panel = build_customer_delivery_admin_panel(
            {"customer_delivery_status": "smtp_accepted", "mode": "today_genie"}
        )
        self.assertEqual(panel["status_grade"], "PASS")
        self.assertEqual(panel["status_detail"], "발송 접수 완료")

    def test_panel_failed_run(self) -> None:
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "failed",
                "customer_delivery_error_code": "send_failed",
                "customer_delivery_error_summary": "SMTPException: relay denied",
            }
        )
        self.assertEqual(panel["status_grade"], "FAIL")
        self.assertEqual(panel["failure_reason_code"], "send_failed")
        self.assertIn("relay denied", panel["failure_message"])

    def test_panel_blocked_run(self) -> None:
        panel = build_customer_delivery_admin_panel({"customer_delivery_status": "blocked"})
        self.assertEqual(panel["status_grade"], "BLOCKED")

    def test_panel_not_sent_run(self) -> None:
        panel = build_customer_delivery_admin_panel({"customer_delivery_status": "not_sent"})
        self.assertEqual(panel["status_grade"], "대기")
        self.assertEqual(panel["status_detail"], "미발송")

    def test_panel_five_recipients(self) -> None:
        recipients = [
            "tera9003@daum.net",
            "tomato3593@gmail.com",
            "aegis001@naver.com",
            "kha6210@hanmail.com",
            "beta5@example.com",
        ]
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "smtp_accepted",
                "customer_recipients": recipients,
                "customer_recipient_count": 5,
            }
        )
        self.assertEqual(panel["recipient_count"], "5")
        self.assertEqual(len(panel["recipients_masked"]), 5)

    def test_panel_missing_metadata_is_safe(self) -> None:
        panel = build_customer_delivery_admin_panel({})
        self.assertEqual(panel["recipient_count"], "미기록")
        self.assertEqual(panel["smtp_message_id"], "미기록")
        self.assertEqual(panel["subject"], "미기록")

    def test_detail_page_shows_panel_for_modes(self) -> None:
        self._login()
        fixtures = (
            ("20260530_123000_today_genie_aabbccdd", "today_genie"),
            ("20260530_123100_keysuri_global_tech_aabbccdd", "keysuri_global_tech"),
            ("20260530_123200_keysuri_korea_tech_aabbccdd", "keysuri_korea_tech"),
        )
        for run_id, mode in fixtures:
            save_run_artifact(
                {
                    "run_id": run_id,
                    "mode": mode,
                    "validation_result": "pass",
                    "customer_delivery_status": "not_sent",
                }
            )
            resp = self.client.get(f"/admin/runs/{run_id}")
            self.assertEqual(resp.status_code, 200, msg=mode)
            self.assertIn("고객 이메일 발송 상태", resp.text, msg=mode)
            self.assertIn("미발송", resp.text, msg=mode)

    def test_detail_failed_and_double_send_blocked(self) -> None:
        self._login()
        run_id = "20260530_124000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "customer_delivery_status": "failed",
                "customer_delivery_error_code": "send_failed",
                "customer_delivery_error_summary": "timeout",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertIn("FAIL", resp.text)
        self.assertIn("send_failed", resp.text)

        approved_id = "20260530_124100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": approved_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "customer_delivery_status": "smtp_accepted",
                "owner_review_status": "approved",
            }
        )
        approved_resp = self.client.get(f"/admin/runs/{approved_id}")
        self.assertIn("재발송 차단", approved_resp.text)


if __name__ == "__main__":
    unittest.main()
