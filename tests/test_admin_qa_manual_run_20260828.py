"""Gate 7: an authenticated operator action for a verification full run.

The 2026-08-28 Global acceptance run was triggered with
``gcloud scheduler jobs run KeeSuri_Global_Tech``, which produced a second
``natural_scheduled`` execution against the already-consumed 12:30 slot. A QA
run must be its own kind of execution: auditable, idempotent, customer-silent,
and unable to impersonate or consume the day's natural slot.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from admin_routes import QA_MANUAL_CONFIRM_PHRASE  # noqa: E402
from keysuri_service_full_run import (  # noqa: E402
    QA_MANUAL_FULL_RUN_TRIGGER,
    _keysuri_qa_manual_identity_fields,
    _keysuri_scheduled_natural_identity_fields,
)
from main import app  # noqa: E402


class QaManualExecutionIdentityTests(unittest.TestCase):
    def test_qa_trigger_yields_qa_manual_class(self) -> None:
        self.assertEqual(
            _keysuri_qa_manual_identity_fields(trigger_source=QA_MANUAL_FULL_RUN_TRIGGER),
            {"execution_class": "qa_manual"},
        )

    def test_scheduler_trigger_is_not_qa_manual(self) -> None:
        self.assertEqual(
            _keysuri_qa_manual_identity_fields(trigger_source="scheduled_service_full_run"),
            {},
        )

    def test_qa_run_claims_no_natural_slot(self) -> None:
        """The defect the Scheduler trigger caused: a second natural execution."""
        fields = _keysuri_scheduled_natural_identity_fields(
            program_id="keysuri_global_tech",
            run_id="20260828_170000_keysuri_global_tech_abcd1234",
            trigger_source=QA_MANUAL_FULL_RUN_TRIGGER,
        )
        self.assertEqual(fields, {})

    def test_scheduler_path_still_claims_its_slot(self) -> None:
        fields = _keysuri_scheduled_natural_identity_fields(
            program_id="keysuri_global_tech",
            run_id="20260828_123001_keysuri_global_tech_abcd1234",
            trigger_source="scheduled_service_full_run",
        )
        self.assertEqual(fields["execution_class"], "natural_scheduled")
        self.assertEqual(fields["scheduled_slot"], "12:30")


class QaManualRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev

    def _confirm_page(self):
        resp = self.client.get("/admin/qa-manual-run?program_id=keysuri_global_tech")
        self.assertEqual(resp.status_code, 200)
        return resp.text

    def _fields(self, page):
        import re

        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page)
        cid = re.search(r'name="command_id" value="([^"]+)"', page)
        return (csrf.group(1) if csrf else ""), (cid.group(1) if cid else "")

    def test_confirm_page_requires_login(self) -> None:
        anon = TestClient(app)
        resp = anon.get("/admin/qa-manual-run", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    def test_execute_requires_login(self) -> None:
        anon = TestClient(app)
        resp = anon.post("/admin/qa-manual-run", data={}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    def test_confirm_page_states_the_safety_contract(self) -> None:
        page = self._confirm_page()
        for phrase in (
            "운영자 검증용 수동 풀런",
            "자연실행 슬롯을 사용하지 않습니다",
            "고객 발송 없음",
            "운영자 검토 메일 1회",
        ):
            self.assertIn(phrase, page, phrase)

    def test_opening_the_confirm_page_starts_nothing(self) -> None:
        with patch("internal_jobs.create_keysuri_owner_review_job") as job:
            self._confirm_page()
            job.assert_not_called()

    def test_missing_csrf_is_rejected(self) -> None:
        """CSRF is enforced whenever K_SERVICE is set, i.e. on Cloud Run."""
        os.environ["GENIE_ADMIN_CSRF_ENABLED"] = "1"
        try:
            _csrf, cid = self._fields(self._confirm_page())
            with patch("internal_jobs.create_keysuri_owner_review_job") as job:
                resp = self.client.post(
                    "/admin/qa-manual-run",
                    data={
                        "program_id": "keysuri_global_tech",
                        "command_id": cid,
                        "confirm_phrase": QA_MANUAL_CONFIRM_PHRASE,
                    },
                )
            self.assertEqual(resp.status_code, 403)
            job.assert_not_called()
        finally:
            os.environ.pop("GENIE_ADMIN_CSRF_ENABLED", None)

    def test_csrf_is_enforced_on_cloud_run_by_default(self) -> None:
        from admin_routes import _csrf_enabled

        prev = os.environ.get("K_SERVICE")
        os.environ.pop("GENIE_ADMIN_CSRF_ENABLED", None)
        os.environ["K_SERVICE"] = "genie-blog-run"
        try:
            self.assertTrue(_csrf_enabled())
        finally:
            if prev is None:
                os.environ.pop("K_SERVICE", None)
            else:
                os.environ["K_SERVICE"] = prev

    def test_wrong_confirm_phrase_is_rejected(self) -> None:
        csrf, cid = self._fields(self._confirm_page())
        with patch("internal_jobs.create_keysuri_owner_review_job") as job:
            resp = self.client.post(
                "/admin/qa-manual-run",
                data={
                    "program_id": "keysuri_global_tech",
                    "command_id": cid,
                    "confirm_phrase": "그냥 실행",
                    "csrf_token": csrf,
                },
            )
        self.assertEqual(resp.status_code, 400)
        job.assert_not_called()

    def test_one_click_runs_once_with_the_canonical_identity(self) -> None:
        csrf, cid = self._fields(self._confirm_page())
        with patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value={"run_id": "20260828_999999_keysuri_global_tech_deadbeef"},
        ) as job:
            resp = self.client.post(
                "/admin/qa-manual-run",
                data={
                    "program_id": "keysuri_global_tech",
                    "command_id": cid,
                    "confirm_phrase": QA_MANUAL_CONFIRM_PHRASE,
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(job.call_count, 1)
        _args, kwargs = job.call_args
        self.assertEqual(kwargs["trigger_source"], QA_MANUAL_FULL_RUN_TRIGGER)
        self.assertTrue(kwargs["service_full_run"])
        self.assertTrue(kwargs["send_owner_email"])
        self.assertFalse(kwargs["dry_run"])
        self.assertIn("20260828_999999_keysuri_global_tech_deadbeef", resp.headers["location"])

    def test_double_submit_does_not_run_twice(self) -> None:
        csrf, cid = self._fields(self._confirm_page())
        data = {
            "program_id": "keysuri_global_tech",
            "command_id": cid,
            "confirm_phrase": QA_MANUAL_CONFIRM_PHRASE,
            "csrf_token": csrf,
        }
        with patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value={"run_id": "20260828_999999_keysuri_global_tech_deadbeef"},
        ) as job:
            first = self.client.post("/admin/qa-manual-run", data=data, follow_redirects=False)
            second = self.client.post("/admin/qa-manual-run", data=data, follow_redirects=False)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(job.call_count, 1)

    def test_an_unknown_program_is_refused(self) -> None:
        csrf, cid = self._fields(self._confirm_page())
        with patch("internal_jobs.create_keysuri_owner_review_job") as job:
            resp = self.client.post(
                "/admin/qa-manual-run",
                data={
                    "program_id": "today_genie",
                    "command_id": cid,
                    "confirm_phrase": QA_MANUAL_CONFIRM_PHRASE,
                    "csrf_token": csrf,
                },
            )
        self.assertEqual(resp.status_code, 400)
        job.assert_not_called()

    def test_the_action_is_reachable_from_the_program_state_card(self) -> None:
        with patch("admin_routes.list_run_artifacts", return_value=[]):
            page = self.client.get("/admin/incidents").text
        self.assertIn("/admin/qa-manual-run?program_id=keysuri_global_tech", page)
        self.assertIn("검증용 수동 풀런", page)

    def test_no_internal_token_is_exposed_to_the_browser(self) -> None:
        page = self._confirm_page()
        self.assertNotIn("GENIE_INTERNAL_JOB_TOKEN", page)
        self.assertNotIn("X-Genie-Internal-Job-Token", page)


if __name__ == "__main__":
    unittest.main()
