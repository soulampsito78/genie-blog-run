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


if __name__ == "__main__":
    unittest.main()
