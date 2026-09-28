"""Preflight / reliability canary side-effect and isolation tests (no live Gemini)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from today_genie_execution_identity import (
    EXECUTION_CLASS_PREFLIGHT_CANARY,
    EXECUTION_CLASS_RELIABILITY_CANARY,
    EXECUTION_CLASS_NATURAL_SCHEDULED,
    TODAY_NATURAL_SCHEDULED_SLOT,
    evaluate_today_natural_slot_gate,
    natural_slot_completer_qualification,
)


class PreflightIsolationTests(unittest.TestCase):
    @staticmethod
    def _global_probe(*, ok: bool, artifact: str) -> dict:
        return {
            "ok": ok,
            "program_id": "keysuri_global_tech",
            "execution_class": EXECUTION_CLASS_PREFLIGHT_CANARY,
            "input_mode": "live_current_feed",
            "parse_status": "parsed_valid" if ok else "parsed_invalid",
            "called_gemini": True,
            "called_image_api": 0,
            "smtp": 0,
            "customer": 0,
            "natural_slot_mutation": 0,
            "model": "gemini-3-flash-preview",
            "deployed_revision": "revision-a",
            "deployed_commit_sha": "sha-a",
            "source_snapshot_hash": "source-a",
            "source_count": 25,
            "selection_fingerprint": "selection-a",
            "contract_fingerprint": "contract-a",
            "artifact_uri": artifact,
            "finished_at": "2026-09-28T11:47:00+09:00",
            "issue_codes": [] if ok else [
                "keysuri_reader_surface_blocked",
                "top_5_news_item_headline_missing",
                "top_5_news_item_summary_missing",
                "Gemini parse failed (parsed_invalid): keysuri_reader_surface_blocked: Reader-surface boundary withheld",
            ],
            "generation_diagnostics": {
                "retry_applied": True,
                "global_generation_budget_exhausted": True,
                "global_generation_call_count": 2,
                "generation_attempt_count": 1,
                "initial_generation_issue_codes": [
                    "keysuri_reader_surface_blocked",
                    "top_5_news_item_headline_missing",
                    "top_5_news_item_summary_missing",
                ],
                "recovery_generation_issue_codes": [],
            },
        }

    def test_global_model_only_failure_is_inconclusive_without_alert_or_second_probe(self) -> None:
        from natural_run_reliability import run_natural_preflight

        first = self._global_probe(ok=False, artifact="memory://first")
        sender = mock.Mock(return_value=True)
        with mock.patch(
            "natural_run_reliability.run_program_canary", return_value=first
        ) as canary, mock.patch(
            "natural_run_reliability._save_json", return_value="memory://readiness"
        ):
            readiness = run_natural_preflight("keysuri_global_tech", send_fn=sender)
        canary.assert_called_once()
        sender.assert_not_called()
        self.assertEqual(readiness["status"], "PRECHECK_INCONCLUSIVE")
        self.assertFalse(readiness["validation_pass"])
        self.assertEqual(readiness["alert_suppressed_reason"], "model_output_unconfirmed")
        self.assertEqual(readiness["canary_artifact_uri"], "memory://first")
        self.assertEqual(readiness["natural_slot_mutation"], 0)
        self.assertEqual(readiness["customer"], 0)

    def test_global_missing_input_identity_keeps_failure_alert(self) -> None:
        from natural_run_reliability import run_natural_preflight

        first = self._global_probe(ok=False, artifact="memory://first")
        first["source_snapshot_hash"] = ""
        sender = mock.Mock(return_value=True)
        with mock.patch(
            "natural_run_reliability.run_program_canary", return_value=first
        ), mock.patch(
            "natural_run_reliability._save_json", return_value="memory://readiness"
        ):
            readiness = run_natural_preflight("keysuri_global_tech", send_fn=sender)
        self.assertEqual(readiness["status"], "PRECHECK_FAIL")
        sender.assert_called_once()

    def test_non_budget_failure_keeps_failure_alert(self) -> None:
        from natural_run_reliability import run_natural_preflight

        first = self._global_probe(ok=False, artifact="memory://first")
        first["generation_diagnostics"]["global_generation_budget_exhausted"] = False
        sender = mock.Mock(return_value=True)
        with mock.patch(
            "natural_run_reliability.run_program_canary", return_value=first
        ) as canary, mock.patch(
            "natural_run_reliability._save_json", return_value="memory://readiness"
        ):
            readiness = run_natural_preflight("keysuri_global_tech", send_fn=sender)
        canary.assert_called_once()
        self.assertEqual(readiness["status"], "PRECHECK_FAIL")
        sender.assert_called_once()

    def test_global_additional_source_or_safety_issue_keeps_failure_alert(self) -> None:
        from natural_run_reliability import run_natural_preflight

        first = self._global_probe(ok=False, artifact="memory://first")
        first["issue_codes"].append("source_fetch_failed")
        sender = mock.Mock(return_value=True)
        with mock.patch(
            "natural_run_reliability.run_program_canary", return_value=first
        ), mock.patch(
            "natural_run_reliability._save_json", return_value="memory://readiness"
        ):
            readiness = run_natural_preflight("keysuri_global_tech", send_fn=sender)
        self.assertEqual(readiness["status"], "PRECHECK_FAIL")
        sender.assert_called_once()

    def test_missing_model_identity_keeps_failure_alert(self) -> None:
        from natural_run_reliability import run_natural_preflight

        first = self._global_probe(ok=False, artifact="memory://first")
        first["model"] = None
        sender = mock.Mock(return_value=True)
        with mock.patch(
            "natural_run_reliability.run_program_canary", return_value=first
        ) as canary, mock.patch(
            "natural_run_reliability._save_json", return_value="memory://readiness"
        ):
            readiness = run_natural_preflight("keysuri_global_tech", send_fn=sender)
        canary.assert_called_once()
        self.assertEqual(readiness["status"], "PRECHECK_FAIL")
        self.assertIn("keysuri_preflight_model_identity_missing", readiness["issue_codes"])
        sender.assert_called_once()

    def test_admin_does_not_present_inconclusive_as_pass(self) -> None:
        from admin_view_models import preflight_projection

        projection = preflight_projection(
            {"status": "PRECHECK_INCONCLUSIVE", "checked_at": "2026-09-28T11:47:00+09:00"},
            {"preflight_time": "11:45"},
        )
        self.assertEqual(projection["state"], "warn")
        self.assertEqual(projection["label"], "사전점검 불확실")

    def test_preflight_and_reliability_never_complete_natural_slot(self) -> None:
        for cls in (EXECUTION_CLASS_PREFLIGHT_CANARY, EXECUTION_CLASS_RELIABILITY_CANARY):
            art = {
                "run_id": "20260807_today_genie_probe01",
                "mode": "today_genie",
                "execution_class": cls,
                "scheduled_slot": TODAY_NATURAL_SCHEDULED_SLOT,
                "email_sent": True,
                "artifact_status": "emailed",
                "owner_review_status": "pending_review",
                "validation_result": "pass",
                "trigger_source": cls,
            }
            match = natural_slot_completer_qualification(
                art,
                program_id="today_genie",
                kst_date="2026-08-07",
                scheduled_slot=TODAY_NATURAL_SCHEDULED_SLOT,
            )
            self.assertFalse(match.qualifies, cls)
            self.assertIn("execution_class", match.disqualify_reason)

    def test_preflight_request_admits_without_consuming_slot(self) -> None:
        from today_genie_execution_identity import resolve_today_execution_identity

        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_PREFLIGHT_CANARY,
            trigger_source="preflight_scheduler",
            scheduled_slot=TODAY_NATURAL_SCHEDULED_SLOT,
        )
        self.assertIsNone(err)
        self.assertIsNotNone(identity)
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[],
        )
        self.assertEqual(decision.action, "admit")
        # Empty artifacts: no completer found; probe identity does not mark slot done.
        self.assertFalse(decision.duplicate)

    def test_preflight_email_copy_does_not_claim_natural_started(self) -> None:
        from natural_run_reliability import build_preflight_failure_email_html

        html = build_preflight_failure_email_html(
            {
                "program_id": "today_genie",
                "finished_at": "2026-08-11T05:45:00+09:00",
                "issue_codes": ["validation_blocked"],
                "deployed_revision": "genie-blog-run-test",
                "deployed_commit_sha": "abc",
            }
        )
        self.assertIn("아직 정규 자연실행은 시작되지 않았습니다", html)
        self.assertNotIn("재실행할까요", html)

    def test_endpoint_rejects_wrong_execution_class(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "tok"}, clear=False):
            client = TestClient(app)
            resp = client.post(
                "/internal/jobs/natural-run-preflight",
                headers={"X-Genie-Internal-Job-Token": "tok"},
                json={
                    "program_id": "today_genie",
                    "execution_class": EXECUTION_CLASS_NATURAL_SCHEDULED,
                },
            )
        self.assertEqual(resp.status_code, 400)

    def test_endpoint_accepts_inconclusive_without_scheduler_retry(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "tok"}, clear=False), mock.patch(
            "natural_run_reliability.run_natural_preflight",
            return_value={"program_id": "keysuri_global_tech", "status": "PRECHECK_INCONCLUSIVE"},
        ), mock.patch(
            "internal_jobs.scheduled_holiday_skip_payload", return_value=None,
        ):
            client = TestClient(app)
            resp = client.post(
                "/internal/jobs/natural-run-preflight",
                headers={"X-Genie-Internal-Job-Token": "tok"},
                json={"program_id": "keysuri_global_tech", "execution_class": EXECUTION_CLASS_PREFLIGHT_CANARY},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "PRECHECK_INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
