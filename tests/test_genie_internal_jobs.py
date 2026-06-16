"""Unit tests for Genie + Kee-Suri internal scheduler job routes (Unit 6e)."""
from __future__ import annotations

import os
import unittest
from typing import Any, Dict
from unittest import mock

from fastapi.testclient import TestClient

from keysuri_live_source_smoke import LiveSourceSmokeResult, PROGRAM_GLOBAL, PROGRAM_KOREA
from main import app
from orchestrator import OrchestrationResult
from publishing_policy import PublishingDecision

_TOKEN = "unit-test-internal-token"
_GENIE_OWNER_REVIEW = "/internal/jobs/create-owner-review"
_GENIE_TIMEOUT = "/internal/jobs/process-approval-timeouts"
_KEYSURI = "/internal/jobs/create-keysuri-owner-review"


def _auth_headers() -> Dict[str, str]:
    return {"X-Genie-Internal-Job-Token": _TOKEN}


class InternalJobsSharedAuthTests(unittest.TestCase):
    ROUTES = (
        (_GENIE_OWNER_REVIEW, {}),
        (_GENIE_TIMEOUT, {}),
        (_KEYSURI, {"program_id": PROGRAM_KOREA, "dry_run": True}),
    )

    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_missing_env_token_returns_503_on_all_routes(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            for path, body in self.ROUTES:
                with self.subTest(path=path):
                    resp = self.client.post(path, json=body, headers=_auth_headers())
                    self.assertEqual(resp.status_code, 503)
                    self.assertEqual(resp.json()["error"], "internal_job_token_not_configured")

    def test_missing_header_returns_403_on_all_routes(self) -> None:
        for path, body in self.ROUTES:
            with self.subTest(path=path):
                resp = self.client.post(path, json=body)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.json()["error"], "forbidden")

    def test_wrong_header_returns_403_on_all_routes(self) -> None:
        bad = {"X-Genie-Internal-Job-Token": "wrong-token"}
        for path, body in self.ROUTES:
            with self.subTest(path=path):
                resp = self.client.post(path, json=body, headers=bad)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.json()["error"], "forbidden")

    def test_correct_token_accepted(self) -> None:
        with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
            mock_exec.return_value = ("run-id", mock.Mock(), False)
            with mock.patch("internal_jobs.find_scheduled_owner_review_for_kst_date", return_value=None):
                resp = self.client.post(_GENIE_OWNER_REVIEW, json={}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)


class GenieCreateOwnerReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_calls_today_genie_orchestrator(self) -> None:
        run_id = "20260609_120000_today_genie_aabbccdd"
        result = OrchestrationResult(
            decision=PublishingDecision(
                send_email=True,
                create_naver_draft=False,
                auto_publish=False,
                require_review=True,
                suppress_external=False,
            ),
            reason_summary="ok",
            response_status=200,
            mode="today_genie",
        )
        with mock.patch(
            "internal_jobs.find_scheduled_owner_review_for_kst_date",
            return_value=None,
        ):
            with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
                mock_exec.return_value = (run_id, result, True)
                resp = self.client.post(_GENIE_OWNER_REVIEW, json={}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        mock_exec.assert_called_once_with(
            "today_genie",
            trigger_source="scheduled_owner_review",
            send_owner_email=True,
        )
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "today_genie")
        self.assertEqual(body["run_id"], run_id)

    def test_does_not_route_keysuri_program_id(self) -> None:
        run_id = "20260609_120000_today_genie_aabbccdd"
        with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
            with mock.patch(
                "internal_jobs.find_scheduled_owner_review_for_kst_date",
                return_value=None,
            ):
                mock_exec.return_value = (run_id, mock.Mock(), False)
                resp = self.client.post(
                    _GENIE_OWNER_REVIEW,
                    json={"program_id": PROGRAM_KOREA},
                    headers=_auth_headers(),
                )
        self.assertEqual(resp.status_code, 200)
        mock_exec.assert_called_once_with(
            "today_genie",
            trigger_source="scheduled_owner_review",
            send_owner_email=True,
        )

    def test_does_not_call_keysuri_runner(self) -> None:
        with mock.patch("internal_jobs.create_keysuri_owner_review_job") as mock_keysuri:
            with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
                with mock.patch(
                    "internal_jobs.find_scheduled_owner_review_for_kst_date",
                    return_value=None,
                ):
                    mock_exec.return_value = ("run-id", mock.Mock(), False)
                    self.client.post(_GENIE_OWNER_REVIEW, json={}, headers=_auth_headers())
        mock_keysuri.assert_not_called()

    def test_orchestrator_exception_returns_500(self) -> None:
        with mock.patch(
            "internal_jobs.find_scheduled_owner_review_for_kst_date",
            return_value=None,
        ):
            with mock.patch(
                "internal_jobs.execute_orchestrator_run",
                side_effect=RuntimeError("boom"),
            ):
                resp = self.client.post(_GENIE_OWNER_REVIEW, json={}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "orchestration_failed")

    def test_no_send_verification_passes_send_owner_email_false_to_orchestrator(self) -> None:
        """Body send_owner_email=false must flow through to execute_orchestrator_run."""
        run_id = "20260616_130000_today_genie_nosend01"
        with mock.patch(
            "internal_jobs.find_scheduled_owner_review_for_kst_date",
            return_value=None,
        ):
            with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
                mock_exec.return_value = (run_id, mock.Mock(), False)
                resp = self.client.post(
                    _GENIE_OWNER_REVIEW,
                    json={"send_owner_email": False},
                    headers=_auth_headers(),
                )
        self.assertEqual(resp.status_code, 200)
        mock_exec.assert_called_once_with(
            "today_genie",
            trigger_source="scheduled_owner_review",
            send_owner_email=False,
        )

    def test_scheduler_empty_body_defaults_to_send_owner_email_true(self) -> None:
        """Scheduler natural body {} must default to send_owner_email=True (unchanged behavior)."""
        run_id = "20260616_063000_today_genie_sched01"
        with mock.patch(
            "internal_jobs.find_scheduled_owner_review_for_kst_date",
            return_value=None,
        ):
            with mock.patch("internal_jobs.execute_orchestrator_run") as mock_exec:
                mock_exec.return_value = (run_id, mock.Mock(), True)
                self.client.post(_GENIE_OWNER_REVIEW, json={}, headers=_auth_headers())
        _call = mock_exec.call_args
        self.assertTrue(_call.kwargs.get("send_owner_email", True))


class GenieTimeoutProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=False)
        self._env_patch = mock.patch.dict(
            os.environ,
            {
                "GENIE_INTERNAL_JOB_TOKEN": _TOKEN,
                "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "user@example.com",
                "SMTP_PASSWORD": "secret",
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_calls_admin_store_timeout_processor(self) -> None:
        summary = {
            "ok": True,
            "scanned": 2,
            "eligible": 0,
            "sent": 0,
            "skipped": 2,
            "errors": 0,
            "run_ids_sent": [],
            "skip_reasons": {},
            "error_run_ids": [],
            "retired": True,
        }
        with mock.patch("internal_jobs.process_approval_timeouts", return_value=summary) as mock_proc:
            resp = self.client.post(_GENIE_TIMEOUT, json={}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 200)
        mock_proc.assert_called_once()
        self.assertEqual(resp.json()["scanned"], 2)

    def test_missing_token_rejected(self) -> None:
        resp = self.client.post(_GENIE_TIMEOUT, json={})
        self.assertEqual(resp.status_code, 403)

    def test_wrong_token_rejected(self) -> None:
        resp = self.client.post(
            _GENIE_TIMEOUT,
            json={},
            headers={"X-Genie-Internal-Job-Token": "bad"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_controlled_response_shape(self) -> None:
        with mock.patch(
            "internal_jobs.process_approval_timeouts",
            return_value={
                "ok": True,
                "scanned": 0,
                "eligible": 0,
                "sent": 0,
                "skipped": 0,
                "errors": 0,
                "run_ids_sent": [],
                "skip_reasons": {},
                "error_run_ids": [],
                "retired": True,
            },
        ):
            resp = self.client.post(_GENIE_TIMEOUT, json={}, headers=_auth_headers())
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertIn("scanned", body)
        self.assertIn("run_ids_sent", body)

    def test_processor_exception_returns_500(self) -> None:
        with mock.patch(
            "internal_jobs.process_approval_timeouts",
            side_effect=RuntimeError("boom"),
        ):
            resp = self.client.post(_GENIE_TIMEOUT, json={}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "timeout_processor_failed")


class KeysuriEndpointRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_korea_dry_run_passes(self) -> None:
        resp = self.client.post(
            _KEYSURI,
            json={"program_id": PROGRAM_KOREA, "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["dry_run"])
        self.assertTrue(body["would_run"])

    def test_global_dry_run_passes(self) -> None:
        resp = self.client.post(
            _KEYSURI,
            json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["program_id"], PROGRAM_GLOBAL)

    def test_today_genie_rejected(self) -> None:
        resp = self.client.post(
            _KEYSURI,
            json={"program_id": "today_genie", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "forbidden_genie_program")

    def test_tomorrow_genie_rejected(self) -> None:
        resp = self.client.post(
            _KEYSURI,
            json={"program_id": "tomorrow_genie", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_program_rejected(self) -> None:
        resp = self.client.post(
            _KEYSURI,
            json={"program_id": "bad_program", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "unknown_program_id")

    def test_dry_run_does_not_call_runner(self) -> None:
        with mock.patch("internal_jobs.run_keysuri_live_source_smoke") as mock_runner:
            resp = self.client.post(
                _KEYSURI,
                json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 200)
        mock_runner.assert_not_called()

    def test_non_dry_mocked_runner_called_with_send_false(self) -> None:
        def _runner(**kwargs: Any) -> LiveSourceSmokeResult:
            self.assertFalse(kwargs["send"])
            self.assertTrue(kwargs["use_gemini"])
            self.assertTrue(kwargs["contract_preview"])
            return LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path="/tmp/pack.json",
                html_path="/tmp/preview.html",
                fetched_item_count=5,
                feed_urls_used=["https://example.com/feed"],
                sample_marker_pass=True,
            )

        with mock.patch("internal_jobs.run_keysuri_live_source_smoke", side_effect=_runner):
            resp = self.client.post(
                _KEYSURI,
                json={"program_id": PROGRAM_GLOBAL, "dry_run": False},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])


class RootEndpointRegressionTests(unittest.TestCase):
    def test_today_genie_root_unchanged(self) -> None:
        client = TestClient(app)
        with mock.patch(
            "main.build_runtime_input",
            return_value={"today_genie_feed_gate": "block"},
        ):
            resp = client.post("/", json={"type": "today_genie"})
        self.assertEqual(resp.status_code, 422)

    def test_tomorrow_genie_root_unchanged(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("main.build_runtime_input", return_value={}):
            with mock.patch("main.build_full_prompt", return_value="prompt"):
                with mock.patch(
                    "main.call_gemini",
                    side_effect=RuntimeError("mocked-gemini"),
                ):
                    resp = client.post("/", json={"type": "tomorrow_genie"})
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
