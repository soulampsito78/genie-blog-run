"""Minimal tests for owner admin routes and artifact listing."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin_store import admin_runs_dir, save_run_artifact
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
            data={"reason_option": "기타", "reason_note": ""},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/admin", resp.headers.get("location", ""))

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_executes_when_logged_in(self, mock_exec) -> None:
        mock_exec.return_value = ("20260530_130000_today_genie_11223344", object(), True)
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
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={"reason_option": "구성 품질 이슈", "reason_note": "retry"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        mock_exec.assert_called_once()
        kwargs = mock_exec.call_args.kwargs
        self.assertTrue(kwargs.get("admin_reissue"))
        self.assertEqual(kwargs.get("parent_run_id"), parent_id)


if __name__ == "__main__":
    unittest.main()
