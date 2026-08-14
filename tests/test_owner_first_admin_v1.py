"""Owner-first Admin presentation tests (read-only GET paths only)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from admin_store import save_run_artifact
from main import app


class OwnerFirstAdminV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "admin_runs"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.incident_dir = Path(self.tmp.name) / "admin_incidents"
        self.incident_dir.mkdir(parents=True, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PASSWORD": "test-admin-secret",
                "GENIE_ARTIFACT_BUCKET": "",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
                "GENIE_CUSTOMER_EMAIL_TO": "one@example.com,two@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "owner@example.com",
                "SMTP_PASSWORD": "secret",
            },
            clear=False,
        )
        self.run_patch = mock.patch("admin_store.admin_runs_dir", return_value=self.run_dir)
        self.incident_patch = mock.patch(
            "natural_run_incident_store.incidents_local_dir", return_value=self.incident_dir
        )
        self.incident_gcs_patch = mock.patch(
            "natural_run_incident_store._uses_gcs", return_value=False
        )
        self.readiness_dir_patch = mock.patch(
            "natural_run_reliability._local_dir",
            side_effect=lambda prefix: Path(self.tmp.name) / prefix,
        )
        self.env.start()
        self.run_patch.start()
        self.incident_patch.start()
        self.incident_gcs_patch.start()
        self.readiness_dir_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.readiness_dir_patch.stop()
        self.incident_gcs_patch.stop()
        self.incident_patch.stop()
        self.run_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def login(self) -> None:
        response = self.client.post("/admin/login", data={"password": "test-admin-secret"})
        self.assertEqual(response.status_code, 200)

    def save_program_runs(self) -> None:
        fixtures = (
            ("20260813_063000_today_genie_aaaaaaaa", "today_genie", "Today actual"),
            ("20260813_123000_keysuri_global_tech_bbbbbbbb", "keysuri_global_tech", "Global actual"),
            ("20260813_183000_keysuri_korea_tech_cccccccc", "keysuri_korea_tech", "Korea actual"),
            ("20260813_180000_tomorrow_genie_dddddddd", "tomorrow_genie", "Tomorrow legacy"),
        )
        for run_id, mode, title in fixtures:
            save_run_artifact(
                {
                    "run_id": run_id,
                    "mode": mode,
                    "created_at": "2026-08-13T12:30:00+09:00",
                    "validation_result": "pass",
                    "workflow_status": "validated",
                    "owner_review_status": "pending_review",
                    "customer_delivery_status": "not_sent",
                    "customer_email_subject": title,
                    "email_sent": True,
                },
                email_html=f"<!doctype html><html><body><h1>{title} briefing</h1></body></html>",
            )

    def test_all_new_primary_routes_retain_auth_gate(self) -> None:
        for path in (
            "/admin/operations",
            "/admin/reviews",
            "/admin/incidents",
            "/admin/delivery",
            "/admin/system",
            "/admin/history",
            "/admin/settings",
        ):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303, msg=path)
            self.assertEqual(response.headers.get("location"), "/admin", msg=path)

    def test_operations_has_three_active_programs_and_no_tomorrow(self) -> None:
        self.save_program_runs()
        self.login()
        response = self.client.get("/admin/operations")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Today Genie", response.text)
        self.assertIn("KeeSuri Global Tech", response.text)
        self.assertIn("KeeSuri Korea Tech", response.text)
        self.assertNotIn("Tomorrow legacy", response.text)
        self.assertNotIn("Tomorrow Genie", response.text)
        self.assertNotIn("tomorrow_genie", response.text)

    def test_review_renders_real_html_inline_and_diagnostics_closed(self) -> None:
        run_id = "20260813_063000_today_genie_aaaaaaaa"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "customer_email_subject": "Actual customer subject",
            },
            email_html="<!doctype html><html><body><h1>Actual customer briefing</h1></body></html>",
        )
        self.login()
        response = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="briefing-frame"', response.text)
        self.assertNotIn("Actual customer briefing", response.text)
        self.assertIn(f'src="/admin/runs/{run_id}/email"', response.text)
        preview = self.client.get(f"/admin/runs/{run_id}/email")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Actual customer briefing", preview.text)
        self.assertIn("필수 구성 정상", response.text)
        self.assertIn("기술 세부정보 보기", response.text)
        self.assertIn("원본 JSON 보기", response.text)
        self.assertIn(f'/admin/runs/{run_id}/json', response.text)
        self.assertNotIn('<details class="technical-details" open', response.text)
        self.assertNotIn('<details class="raw-details" open', response.text)

    def test_partial_refusal_is_never_presented_as_full_or_received(self) -> None:
        run_id = "20260813_123000_keysuri_global_tech_bbbbbbbb"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_global_tech",
                "validation_result": "pass",
                "owner_review_status": "approved",
                "customer_delivery_status": "smtp_accepted",
                "customer_email_recipient_count": 13,
                "smtp_accepted_recipient_count": 12,
                "smtp_refused_recipient_count": 1,
                "smtp_partial_refusal": True,
            }
        )
        self.login()
        response = self.client.get("/admin/delivery")
        self.assertIn("PARTIAL DELIVERY", response.text)
        self.assertIn("접수 12명", response.text)
        self.assertIn("거절 1명", response.text)
        self.assertNotIn("FULLY ACCEPTED", response.text)
        self.assertIn("수신함 도착 확인이 아닙니다", response.text)

    def test_incident_decision_order_places_customer_safety_before_diagnostics(self) -> None:
        from natural_run_incident_store import new_incident, save_incident

        incident = new_incident(
            program_id="today_genie",
            kst_date="2026-08-13",
            confirmed_cause="콘텐츠 검수 실패",
            retry_verdict="SAFE_TO_RETRY",
        )
        incident["first_failed_stage"] = "generation_validation"
        save_incident(incident)
        self.login()
        response = self.client.get(f"/admin/incidents/{incident['incident_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("고객 영향", response.text)
        self.assertIn("고객 발송 없음", response.text)
        self.assertIn("안전한 다음 행동", response.text)
        self.assertLess(response.text.index("고객 영향"), response.text.index("기술 세부정보 보기"))
        self.assertLess(response.text.index("안전한 다음 행동"), response.text.index("원본 JSON 보기"))

    def test_approve_confirm_keeps_nonce_checkbox_and_real_preview(self) -> None:
        run_id = "20260813_063000_today_genie_aaaaaaaa"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "customer_email_subject": "Final briefing",
            },
            email_html="<html><body><h1>Final actual body</h1></body></html>",
        )
        self.login()
        response = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="approve_nonce"', response.text)
        self.assertIn('name="customer_send_confirm"', response.text)
        self.assertIn("Final actual body", response.text)
        self.assertIn("2명", response.text)
        self.assertIn("되돌릴 수 없", response.text)

    def test_history_and_settings_are_human_facing_and_reachable(self) -> None:
        self.save_program_runs()
        self.login()
        history = self.client.get("/admin/history")
        settings = self.client.get("/admin/settings")
        self.assertEqual(history.status_code, 200)
        self.assertIn("실행 이력", history.text)
        self.assertIn("2026.08.13", history.text)
        self.assertNotIn("email_sent</th>", history.text)
        self.assertEqual(settings.status_code, 200)
        self.assertIn('href="/admin/customer-recipients"', settings.text)
        self.assertIn('href="/admin/costs"', settings.text)
        self.assertIn('href="/admin/notices"', settings.text)


if __name__ == "__main__":
    unittest.main()
