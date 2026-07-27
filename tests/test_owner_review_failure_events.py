from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import MagicMock, patch

from keysuri_live_source_smoke import LiveSourceSmokeResult, PROGRAM_GLOBAL
from keysuri_service_full_run import run_keysuri_service_full_run
from owner_review_failure_events import (
    OWNER_REVIEW_RUN_FAILED_EVENT,
    build_owner_review_run_failed_payload,
    emit_owner_review_failure_from_artifact_meta,
    emit_owner_review_run_failed_once,
    reset_owner_review_failure_event_dedupe_for_tests,
    should_emit_owner_review_failure_event,
)


class OwnerReviewFailureEventUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def test_only_scheduled_trigger_is_eligible(self) -> None:
        self.assertTrue(
            should_emit_owner_review_failure_event(
                trigger_source="scheduled_service_full_run"
            )
        )
        self.assertFalse(
            should_emit_owner_review_failure_event(
                trigger_source="manual_service_full_run"
            )
        )
        self.assertFalse(
            should_emit_owner_review_failure_event(
                trigger_source="scheduled_service_full_run", dry_run=True
            )
        )

    def test_payload_has_required_fields_and_no_secrets(self) -> None:
        payload = build_owner_review_run_failed_payload(
            program_id="keysuri_global_tech",
            run_id="run-1",
            trigger_source="scheduled_service_full_run",
            first_failed_stage="generation_validation",
            error_code="validation_blocked",
            issue_codes=["gemini_json_missing_required_keys"],
            email_sent=False,
            artifact_url="gs://bucket/run-1.json",
            revision="rev-abc",
        )
        self.assertEqual(payload["event"], OWNER_REVIEW_RUN_FAILED_EVENT)
        self.assertEqual(payload["severity"], "ERROR")
        self.assertEqual(payload["program_id"], "keysuri_global_tech")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["error_code"], "validation_blocked")
        self.assertIn("gemini_json_missing_required_keys", payload["issue_codes"])
        serialized = json.dumps(payload)
        for banned in ("password", "smtp", "raw_response", "@example.com", "api_key"):
            self.assertNotIn(banned, serialized.lower())

    def test_duplicate_finalizer_emits_once(self) -> None:
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            first = emit_owner_review_run_failed_once(
                program_id="keysuri_global_tech",
                run_id="run-dedupe",
                trigger_source="scheduled_service_full_run",
                error_code="validation_blocked",
                issue_codes=["gemini_json_missing_required_keys"],
            )
            second = emit_owner_review_run_failed_once(
                program_id="keysuri_global_tech",
                run_id="run-dedupe",
                trigger_source="scheduled_service_full_run",
                error_code="validation_blocked",
                issue_codes=["gemini_json_missing_required_keys"],
            )
        self.assertTrue(first)
        self.assertFalse(second)
        error_lines = [line for line in captured.output if "owner_review_run_failed" in line]
        self.assertEqual(len(error_lines), 1)

    def test_manual_and_dry_run_emit_nothing(self) -> None:
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            logging.getLogger("keysuri_service_full_run").error("probe")
            self.assertFalse(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_global_tech",
                    run_id="run-manual",
                    trigger_source="manual_service_full_run",
                    error_code="validation_blocked",
                )
            )
            self.assertFalse(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_global_tech",
                    run_id="run-dry",
                    trigger_source="scheduled_service_full_run",
                    error_code="validation_blocked",
                    dry_run=True,
                )
            )
        self.assertTrue(all("owner_review_run_failed" not in line for line in captured.output))


class OwnerReviewFailureServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def _failed_smoke(self) -> LiveSourceSmokeResult:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=PROGRAM_GLOBAL,
            source_pack_path="/tmp/global-pack.json",
            html_path="",
            fetched_item_count=3,
            feed_urls_used=[],
            sample_marker_pass=False,
            called_gemini=True,
            use_gemini=True,
            parse_status="parsed_invalid",
            validation_issues=["gemini_json_missing_required_keys"],
            generation_diagnostics={
                "global_recovery_attempted": True,
                "global_recovery_result": "failed",
                "generation_recovery_attempted": True,
                "generation_recovery_result": "failed",
            },
            error="Gemini parse failed",
        )

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_scheduled_final_failure_emits_one_error_event(
        self, _save: MagicMock
    ) -> None:
        smoke = self._failed_smoke()
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source="scheduled_service_full_run",
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        events = [
            line for line in captured.output if "owner_review_run_failed" in line
        ]
        self.assertEqual(len(events), 1)
        message = events[0].split(":", 2)[-1]
        payload = json.loads(message)
        self.assertEqual(payload["event"], "owner_review_run_failed")
        self.assertEqual(payload["trigger_source"], "scheduled_service_full_run")
        self.assertEqual(payload["error_code"], "validation_blocked")
        self.assertIn("program_id", payload)
        self.assertIn("run_id", payload)
        self.assertFalse(payload["email_sent"])

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_manual_failure_emits_no_event(self, _save: MagicMock) -> None:
        smoke = self._failed_smoke()
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            logging.getLogger("keysuri_service_full_run").error("probe")
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source="manual_service_full_run",
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        self.assertTrue(
            all("owner_review_run_failed" not in line for line in captured.output)
        )

    def test_dry_run_emits_no_event(self) -> None:
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            logging.getLogger("keysuri_service_full_run").error("probe")
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source="scheduled_service_full_run",
                dry_run=True,
            )
        self.assertTrue(result.get("dry_run"))
        self.assertTrue(
            all("owner_review_run_failed" not in line for line in captured.output)
        )

    def test_intermediate_recovery_failure_alone_does_not_emit(self) -> None:
        """Recovery diagnostics without a scheduled finalizer emit nothing."""
        with self.assertLogs("keysuri_service_full_run", level="ERROR") as captured:
            logging.getLogger("keysuri_service_full_run").error("probe")
            # Simulate an intermediate recovery failure record that is not a
            # scheduled service finalizer call.
            self.assertFalse(
                should_emit_owner_review_failure_event(
                    trigger_source="keysuri_global_contract_repair"
                )
            )
        self.assertTrue(
            all("owner_review_run_failed" not in line for line in captured.output)
        )


if __name__ == "__main__":
    unittest.main()
