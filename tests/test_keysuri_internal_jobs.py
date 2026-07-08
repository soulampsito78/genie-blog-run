"""Unit tests for Kee-Suri internal owner-review job dispatch (Unit 6a)."""
from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest import mock

from fastapi.testclient import TestClient

from admin_store import process_approval_timeouts
from internal_jobs import (
    create_keysuri_owner_review_job,
    validate_keysuri_owner_review_program_id,
)
from keysuri_live_source_smoke import LiveSourceSmokeResult, PROGRAM_GLOBAL, PROGRAM_KOREA
from main import app

_ENDPOINT = "/internal/jobs/create-keysuri-owner-review"
_TOKEN = "unit-test-internal-token"


def _auth_headers() -> Dict[str, str]:
    return {"X-Genie-Internal-Job-Token": _TOKEN}


@dataclass
class _FakeSmokeResult:
    ok: bool = True
    program_id: str = PROGRAM_GLOBAL
    html_path: str = "/tmp/preview.html"
    source_pack_path: str = "/tmp/pack.json"
    called_gemini: bool = True
    parse_status: str = "OK"
    preview_overall_status: str = "PASS_OWNER_REVIEW_READY"
    ready_for_owner_visual_review: bool = True
    send_attempted: bool = False
    error: str | None = None
    side_effects: Dict[str, bool] = field(
        default_factory=lambda: {
            "called_gemini": True,
            "fetched_live_news": True,
            "sent_email": False,
            "published_naver": False,
            "changed_scheduler": False,
            "called_image_api": False,
            "mutated_admin_runs": False,
        }
    )


class KeysuriInternalJobsAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_missing_env_token_returns_503(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            resp = self.client.post(
                _ENDPOINT,
                json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"], "internal_job_token_not_configured")

    def test_missing_header_returns_403(self) -> None:
        resp = self.client.post(
            _ENDPOINT,
            json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "forbidden")

    def test_wrong_token_returns_403(self) -> None:
        resp = self.client.post(
            _ENDPOINT,
            json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
            headers={"X-Genie-Internal-Job-Token": "wrong-token"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "forbidden")

    def test_correct_token_accepted(self) -> None:
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value={
                "ok": True,
                "program_id": PROGRAM_GLOBAL,
                "dry_run": True,
                "trigger_source": "scheduled_owner_review",
                "would_run": True,
            },
        ) as mocked_job:
            resp = self.client.post(
                _ENDPOINT,
                json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 200)
        mocked_job.assert_called_once()


class KeysuriInternalJobsValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_missing_program_id_returns_400(self) -> None:
        resp = self.client.post(_ENDPOINT, json={"dry_run": True}, headers=_auth_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "program_id_required")

    def test_today_genie_rejected(self) -> None:
        resp = self.client.post(
            _ENDPOINT,
            json={"program_id": "today_genie", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "forbidden_genie_program")

    def test_tomorrow_genie_rejected(self) -> None:
        resp = self.client.post(
            _ENDPOINT,
            json={"program_id": "tomorrow_genie", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "forbidden_genie_program")

    def test_unknown_program_id_rejected(self) -> None:
        resp = self.client.post(
            _ENDPOINT,
            json={"program_id": "unknown_program", "dry_run": True},
            headers=_auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "unknown_program_id")

    def test_keysuri_global_tech_accepted(self) -> None:
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value={
                "ok": True,
                "program_id": PROGRAM_GLOBAL,
                "dry_run": True,
                "trigger_source": "scheduled_owner_review",
                "would_run": True,
            },
        ):
            resp = self.client.post(
                _ENDPOINT,
                json={"program_id": PROGRAM_GLOBAL, "dry_run": True},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["program_id"], PROGRAM_GLOBAL)

    def test_keysuri_korea_tech_accepted(self) -> None:
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value={
                "ok": True,
                "program_id": PROGRAM_KOREA,
                "dry_run": True,
                "trigger_source": "scheduled_owner_review",
                "would_run": True,
            },
        ):
            resp = self.client.post(
                _ENDPOINT,
                json={"program_id": PROGRAM_KOREA, "dry_run": True},
                headers=_auth_headers(),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["program_id"], PROGRAM_KOREA)


class KeysuriInternalJobsDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_call_smoke_runner(self) -> None:
        runner = mock.Mock()
        payload = create_keysuri_owner_review_job(
            PROGRAM_GLOBAL,
            dry_run=True,
            smoke_runner=runner,
        )
        runner.assert_not_called()
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["would_run"])

    def test_dry_run_returns_would_run_true(self) -> None:
        payload = create_keysuri_owner_review_job(PROGRAM_KOREA, dry_run=True)
        self.assertEqual(payload["would_run"], True)

    def test_dry_run_does_not_generate_html(self) -> None:
        runner = mock.Mock()
        payload = create_keysuri_owner_review_job(
            PROGRAM_GLOBAL,
            dry_run=True,
            smoke_runner=runner,
        )
        self.assertNotIn("html_path", payload)
        runner.assert_not_called()

    def test_dry_run_does_not_send_email(self) -> None:
        runner = mock.Mock()
        payload = create_keysuri_owner_review_job(
            PROGRAM_GLOBAL,
            dry_run=True,
            smoke_runner=runner,
        )
        self.assertNotIn("send_attempted", payload)
        runner.assert_not_called()


class KeysuriInternalJobsNonDryRunTests(unittest.TestCase):
    def _make_runner(self, program_id: str) -> mock.Mock:
        def _runner(**kwargs: Any) -> LiveSourceSmokeResult:
            self.assertEqual(kwargs["program_id"], program_id)
            self.assertTrue(kwargs["use_gemini"])
            self.assertTrue(kwargs["contract_preview"])
            self.assertFalse(kwargs["send"])
            return LiveSourceSmokeResult(
                ok=True,
                program_id=program_id,
                source_pack_path="/tmp/pack.json",
                html_path="/tmp/preview.html",
                fetched_item_count=5,
                feed_urls_used=["https://example.com/feed"],
                sample_marker_pass=True,
                contract_preview=True,
                called_gemini=True,
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                ready_for_owner_visual_review=True,
                side_effects={
                    "called_gemini": True,
                    "fetched_live_news": True,
                    "sent_email": False,
                    "published_naver": False,
                    "changed_scheduler": False,
                    "called_image_api": False,
                    "mutated_admin_runs": False,
                },
            )

        return mock.Mock(side_effect=_runner)

    def test_non_dry_global_calls_runner(self) -> None:
        runner = self._make_runner(PROGRAM_GLOBAL)
        payload = create_keysuri_owner_review_job(
            PROGRAM_GLOBAL,
            dry_run=False,
            smoke_runner=runner,
        )
        runner.assert_called_once()
        self.assertEqual(payload["program_id"], PROGRAM_GLOBAL)
        self.assertFalse(payload["dry_run"])

    def test_non_dry_korea_calls_runner(self) -> None:
        runner = self._make_runner(PROGRAM_KOREA)
        payload = create_keysuri_owner_review_job(
            PROGRAM_KOREA,
            dry_run=False,
            smoke_runner=runner,
        )
        runner.assert_called_once()
        self.assertEqual(payload["program_id"], PROGRAM_KOREA)

    def test_runner_result_is_returned(self) -> None:
        runner = self._make_runner(PROGRAM_GLOBAL)
        payload = create_keysuri_owner_review_job(
            PROGRAM_GLOBAL,
            dry_run=False,
            smoke_runner=runner,
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["html_path"], "/tmp/preview.html")
        self.assertEqual(payload["preview_overall_status"], "PASS_OWNER_REVIEW_READY")

    def test_runner_exception_returns_structured_failure_via_endpoint(self) -> None:
        client = TestClient(app)
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False):
            with mock.patch(
                "internal_jobs.create_keysuri_owner_review_job",
                side_effect=RuntimeError("boom"),
            ):
                resp = client.post(
                    _ENDPOINT,
                    json={"program_id": PROGRAM_GLOBAL, "dry_run": False},
                    headers=_auth_headers(),
                )
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "orchestration_failed")
        self.assertEqual(body["error_type"], "RuntimeError")


class KeysuriInternalJobsStructuredLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._env_patch = mock.patch.dict(
            os.environ,
            {
                "GENIE_INTERNAL_JOB_TOKEN": _TOKEN,
                "SMTP_PASSWORD": "unit-test-secret-password",
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def _post_with_payload_and_logs(self, payload: Dict[str, Any]):
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            return_value=payload,
        ):
            with self.assertLogs("internal_jobs", level="INFO") as logs:
                response = self.client.post(
                    _ENDPOINT,
                    json={
                        "program_id": PROGRAM_GLOBAL,
                        "service_full_run": True,
                        "send_owner_email": True,
                        "dry_run": False,
                        "trigger_source": "scheduled_service_full_run",
                    },
                    headers=_auth_headers(),
                )
        return response, "\n".join(logs.output)

    def _event_from_logs(self, log_text: str, event: str) -> Dict[str, Any]:
        for line in log_text.splitlines():
            if event not in line:
                continue
            start = line.find("{")
            if start >= 0:
                return json.loads(line[start:])
        self.fail(f"missing structured log event: {event}\n{log_text}")

    def test_safe_fail_payload_logs_structured_http_500_diagnostics(self) -> None:
        payload = {
            "ok": False,
            "run_id": "20260708_123000_keysuri_global_tech_fail",
            "program_id": PROGRAM_GLOBAL,
            "service_full_run": True,
            "validation_result": "block",
            "issue_codes": ["deep_dive_key_implications_empty"],
            "called_gemini": True,
            "called_image_api": False,
            "smtp_attempted": False,
            "email_sent": False,
            "customer_delivery_status": "not_sent",
            "approve_customer_final_send": False,
            "error": "validation_blocked",
        }

        response, log_text = self._post_with_payload_and_logs(payload)

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["customer_delivery_status"], "not_sent")
        self.assertFalse(body["approve_customer_final_send"])
        event = self._event_from_logs(log_text, "keysuri_owner_review_safe_fail_http_500")
        self.assertEqual(event["event"], "keysuri_owner_review_safe_fail_http_500")
        self.assertEqual(event["http_status"], 500)
        self.assertEqual(event["stage"], "validation")
        self.assertEqual(event["run_id"], payload["run_id"])
        self.assertEqual(event["validation_result"], "block")
        self.assertEqual(event["issue_codes"], ["deep_dive_key_implications_empty"])
        self.assertFalse(event["email_sent"])
        self.assertFalse(event["approve_customer_final_send"])
        self.assertNotIn(_TOKEN, log_text)
        self.assertNotIn("unit-test-secret-password", log_text)

    def test_success_payload_logs_structured_success_marker(self) -> None:
        payload = {
            "ok": True,
            "run_id": "20260708_123000_keysuri_global_tech_ok",
            "program_id": PROGRAM_GLOBAL,
            "service_full_run": True,
            "validation_result": "pass",
            "called_gemini": True,
            "called_image_api": True,
            "image_source": "generated",
            "artifact_status": "emailed",
            "smtp_attempted": True,
            "email_sent": True,
            "customer_delivery_status": "not_sent",
            "approve_customer_final_send": False,
        }

        response, log_text = self._post_with_payload_and_logs(payload)

        self.assertEqual(response.status_code, 200)
        event = self._event_from_logs(log_text, "keysuri_owner_review_success")
        self.assertEqual(event["event"], "keysuri_owner_review_success")
        self.assertEqual(event["http_status"], 200)
        self.assertEqual(event["stage"], "success")
        self.assertEqual(event["run_id"], payload["run_id"])
        self.assertTrue(event["called_gemini"])
        self.assertTrue(event["called_image_api"])
        self.assertTrue(event["email_sent"])
        self.assertEqual(event["artifact_status"], "emailed")
        self.assertNotIn(_TOKEN, log_text)
        self.assertNotIn("unit-test-secret-password", log_text)

    def test_exception_path_logs_structured_exception_marker(self) -> None:
        with mock.patch(
            "internal_jobs.create_keysuri_owner_review_job",
            side_effect=RuntimeError("mock boom"),
        ):
            with self.assertLogs("internal_jobs", level="INFO") as logs:
                response = self.client.post(
                    _ENDPOINT,
                    json={
                        "program_id": PROGRAM_KOREA,
                        "service_full_run": True,
                        "send_owner_email": True,
                        "dry_run": False,
                        "trigger_source": "scheduled_service_full_run",
                    },
                    headers=_auth_headers(),
                )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "orchestration_failed")
        self.assertEqual(body["error_type"], "RuntimeError")
        log_text = "\n".join(logs.output)
        event = self._event_from_logs(log_text, "keysuri_owner_review_endpoint_exception")
        self.assertEqual(event["event"], "keysuri_owner_review_endpoint_exception")
        self.assertEqual(event["http_status"], 500)
        self.assertEqual(event["stage"], "endpoint_exception")
        self.assertEqual(event["program_id"], PROGRAM_KOREA)
        self.assertEqual(event["error_type"], "RuntimeError")
        self.assertIn("mock boom", event["error_message"])
        self.assertNotIn(_TOKEN, log_text)
        self.assertNotIn("unit-test-secret-password", log_text)


class KeysuriInternalJobsRegressionTests(unittest.TestCase):
    def test_supported_modes_unchanged(self) -> None:
        import main

        self.assertEqual(main.SUPPORTED_MODES, ["today_genie", "tomorrow_genie"])

    def test_keysuri_not_routable_via_root_post(self) -> None:
        client = TestClient(app)
        resp = client.post("/", json={"type": "keysuri_global_tech"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported type", resp.json()["detail"])

    def test_today_genie_root_endpoint_unchanged(self) -> None:
        client = TestClient(app)
        with mock.patch(
            "main.build_runtime_input",
            return_value={"today_genie_feed_gate": "block"},
        ):
            resp = client.post("/", json={"type": "today_genie"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"]["reason"], "today_genie_feed_unavailable")

    def test_tomorrow_genie_root_endpoint_unchanged(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        with mock.patch("main.build_runtime_input", return_value={}):
            with mock.patch("main.build_full_prompt", return_value="prompt") as build_prompt:
                with mock.patch(
                    "main.call_gemini",
                    side_effect=RuntimeError("mocked-gemini"),
                ) as call_gemini:
                    resp = client.post("/", json={"type": "tomorrow_genie"})
        self.assertEqual(resp.status_code, 500)
        build_prompt.assert_called_once()
        call_gemini.assert_called_once_with("prompt", "tomorrow_genie")

    def test_process_approval_timeouts_retired_policy_unchanged(self) -> None:
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        result = process_approval_timeouts()
        self.assertTrue(result["ok"])
        self.assertTrue(result["retired"])
        self.assertEqual(result["sent"], 0)


class KeysuriInternalJobsValidatorTests(unittest.TestCase):
    def test_validate_accepts_supported_programs(self) -> None:
        for program_id in (PROGRAM_GLOBAL, PROGRAM_KOREA):
            normalized, err = validate_keysuri_owner_review_program_id(program_id)
            self.assertIsNone(err)
            self.assertEqual(normalized, program_id)

    def test_validate_rejects_genie_modes(self) -> None:
        for program_id in ("today_genie", "tomorrow_genie"):
            normalized, err = validate_keysuri_owner_review_program_id(program_id)
            self.assertIsNone(normalized)
            self.assertEqual(err["error"], "forbidden_genie_program")


if __name__ == "__main__":
    unittest.main()
