"""Tests for admin /admin/notices/* routes: separation from briefing approve_run."""
from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin_routes import NOTICE_SEND_CONFIRM_PHRASE
from admin_store import load_run_artifact, save_run_artifact
from main import app


class AdminNoticeRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def test_notices_list_requires_login(self) -> None:
        anon = TestClient(app)
        resp = anon.get("/admin/notices", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    def test_notices_list_renders(self) -> None:
        resp = self.client.get("/admin/notices")
        self.assertEqual(resp.status_code, 200)

    def test_notice_new_page_prefills_template(self) -> None:
        resp = self.client.get("/admin/notices/new?notice_type=delay_notice")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("오늘 키수리 글로벌테크 브리핑은 품질 확인 과정", resp.text)

    def test_preview_creates_notice_without_sending(self) -> None:
        with patch("admin_routes.send_admin_notice_email") as mock_send:
            resp = self.client.post(
                "/admin/notices/preview",
                data={
                    "notice_type": "quality_check_notice",
                    "program_id": "keysuri_global_tech",
                    "related_run_id": "",
                    "subject": "테스트 제목",
                    "body_text": "테스트 본문",
                },
            )
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()
        self.assertIn("브리핑 발송이 아닙니다", resp.text)
        self.assertIn("visible MIME 헤더", resp.text)
        match = re.search(r"notice_id: <code>([^<]+)</code>", resp.text)
        self.assertIsNotNone(match)

    def _preview_and_extract_notice_id(self) -> str:
        resp = self.client.post(
            "/admin/notices/preview",
            data={
                "notice_type": "quality_check_notice",
                "program_id": "keysuri_global_tech",
                "related_run_id": "",
                "subject": "테스트 제목",
                "body_text": "테스트 본문",
            },
        )
        match = re.search(r"notice_id: <code>([^<]+)</code>", resp.text)
        assert match is not None
        return match.group(1)

    def test_send_without_confirm_text_is_blocked(self) -> None:
        notice_id = self._preview_and_extract_notice_id()
        with patch("admin_routes.send_admin_notice_email") as mock_send:
            resp = self.client.post(
                "/admin/notices/send",
                data={"notice_id": notice_id, "confirm": "wrong phrase"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("notice_error=confirm_mismatch", resp.headers["location"])
        mock_send.assert_not_called()

    def test_send_requires_previewed_status(self) -> None:
        resp = self.client.post(
            "/admin/notices/send",
            data={"notice_id": "notice_delay_notice_20260625_00000000", "confirm": NOTICE_SEND_CONFIRM_PHRASE},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("notice_error=not_found", resp.headers["location"])

    def test_send_with_correct_confirm_marks_sent(self) -> None:
        notice_id = self._preview_and_extract_notice_id()
        with patch("admin_routes.send_admin_notice_email", return_value=True) as mock_send:
            resp = self.client.post(
                "/admin/notices/send",
                data={"notice_id": notice_id, "confirm": NOTICE_SEND_CONFIRM_PHRASE},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        mock_send.assert_called_once()
        detail = self.client.get(f"/admin/notices/{notice_id}")
        self.assertIn("발송 완료", detail.text)

    def test_notice_send_does_not_modify_briefing_run_artifact(self) -> None:
        run_id = "20260625_010000_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "customer_sent": False,
                "smtp_accepted": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        before = load_run_artifact(run_id)

        notice_id = self._preview_and_extract_notice_id()
        with patch("admin_routes.send_admin_notice_email", return_value=True):
            self.client.post(
                "/admin/notices/send",
                data={"notice_id": notice_id, "confirm": NOTICE_SEND_CONFIRM_PHRASE},
                follow_redirects=False,
            )

        after = load_run_artifact(run_id)
        self.assertEqual(before.get("email_sent"), after.get("email_sent"))
        self.assertEqual(before.get("customer_sent"), after.get("customer_sent"))
        self.assertEqual(before.get("smtp_accepted"), after.get("smtp_accepted"))

    def test_notice_detail_does_not_show_recipient_email_list(self) -> None:
        notice_id = self._preview_and_extract_notice_id()
        resp = self.client.get(f"/admin/notices/{notice_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotRegex(resp.text, r"[\w.+-]+@[\w-]+\.[\w.]+")


class AdminNoticeDashboardEntryTests(unittest.TestCase):
    """The notice workflow must be reachable from the admin dashboard, not only
    by typing the URL directly."""

    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def test_runs_dashboard_links_to_notices(self) -> None:
        resp = self.client.get("/admin/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/admin/notices"', resp.text)
        self.assertIn("공지 메일 관리", resp.text)


if __name__ == "__main__":
    unittest.main()
