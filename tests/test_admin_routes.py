"""Minimal tests for owner admin routes and artifact listing."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin_store import (
    EXECUTABLE_REISSUE_SCOPE,
    admin_runs_dir,
    apply_reissue_child_metadata,
    approve_run,
    load_run_artifact,
    save_run_artifact,
)
from main import app


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
        self.assertIn("고객 이메일 전달", resp.text)
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
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
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


if __name__ == "__main__":
    unittest.main()
