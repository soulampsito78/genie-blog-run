"""Track D — failure-event + recurrence-metrics sandbox harness.

Proves the actual emitted payload format, trigger gates, final-failure coverage,
privacy bans, in-process dedupe scope, and the local inspection script.
No network. No alert policy. No production failure forced.
"""
from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genie_schedule_policy import is_scheduled_trigger_source
from keysuri_recurrence_metrics import (
    RECURRENCE_COUNTER_NAMES,
    aggregate_recurrence_counters,
    recurrence_counters_for_run,
)
from owner_review_failure_events import (
    OWNER_REVIEW_FAILURE_EVENT_LOGGER,
    OWNER_REVIEW_RUN_FAILED_EVENT,
    _BANNED_PAYLOAD_KEYS,
    build_owner_review_run_failed_payload,
    configure_owner_review_failure_event_logger,
    emit_owner_review_run_failed_once,
    infer_first_failed_stage,
    reset_owner_review_failure_event_dedupe_for_tests,
    should_emit_owner_review_failure_event,
)

_REPO = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO / "tests" / "fixtures" / "owner_review_ops"
_SCRIPT = _REPO / "scripts" / "inspect_owner_review_ops_local.py"

_SCHEDULED_ALIASES = (
    "scheduler",
    "cloud_scheduler",
    "internal_job",
    "scheduled_owner_review",
    "scheduled_service_full_run",
    "scheduled_custom_alias",
)

_NON_ALERT_TRIGGERS = (
    "manual",
    "manual_service_full_run",
    "manual_admin",
    "admin_text_only_reissue",
    "admin_image_only_reissue",
    "dry_run",
    "preview",
    "test",
    "local",
    "",
    None,
)


class PayloadFormatRealityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()
        configure_owner_review_failure_event_logger()

    def test_runtime_emits_bare_json_text_line_not_prefixed_textpayload(self) -> None:
        stream = io.StringIO()
        event_logger = logging.getLogger(OWNER_REVIEW_FAILURE_EVENT_LOGGER)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        event_logger.addHandler(handler)
        try:
            emitted = emit_owner_review_run_failed_once(
                program_id="keysuri_global_tech",
                run_id="fmt_run_1",
                trigger_source="scheduled_owner_review",
                first_failed_stage="generation_validation",
                error_code="gemini_json_schema_validation_failed",
                issue_codes=["gemini_json_schema_validation_failed"],
            )
            self.assertTrue(emitted)
            line = stream.getvalue().strip()
            self.assertTrue(line.startswith("{"), line)
            self.assertNotIn("ERROR genie", line)
            payload = json.loads(line)
            self.assertEqual(payload["event"], OWNER_REVIEW_RUN_FAILED_EVENT)
            self.assertEqual(payload["severity"], "ERROR")
            # Cloud Logging may parse this bare JSON line into jsonPayload;
            # the process itself emits a raw JSON text line.
            self.assertIn("program_id", payload)
            self.assertIn("first_failed_stage", payload)
        finally:
            event_logger.removeHandler(handler)

    def test_documented_query_substring_matches_emitted_line(self) -> None:
        docs = (_REPO / "docs" / "ops" / "OWNER_REVIEW_FAILURE_ALERTING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn('jsonPayload.event="owner_review_run_failed"', docs)
        self.assertIn('textPayload:"\\"event\\": \\"owner_review_run_failed\\""', docs)
        self.assertIn("in-process only", docs)
        payload = build_owner_review_run_failed_payload(
            program_id="keysuri_korea_tech",
            run_id="doc_match",
            trigger_source="scheduler",
            first_failed_stage="email_delivery",
            error_code="smtp_send_failed",
        )
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertIn('"event": "owner_review_run_failed"', line)


class TriggerRecognitionTests(unittest.TestCase):
    def test_all_real_scheduler_aliases_are_recognized(self) -> None:
        for alias in _SCHEDULED_ALIASES:
            self.assertTrue(is_scheduled_trigger_source(alias), alias)
            self.assertTrue(
                should_emit_owner_review_failure_event(trigger_source=alias, dry_run=False),
                alias,
            )

    def test_manual_dry_run_preview_do_not_alert(self) -> None:
        for trigger in _NON_ALERT_TRIGGERS:
            self.assertFalse(
                should_emit_owner_review_failure_event(
                    trigger_source=trigger, dry_run=False
                ),
                trigger,
            )
        self.assertFalse(
            should_emit_owner_review_failure_event(
                trigger_source="scheduled_owner_review", dry_run=True
            )
        )


class FinalFailureCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def _emit(self, *, run_id: str, stage: str, error_code: str) -> bool:
        return emit_owner_review_run_failed_once(
            program_id="keysuri_global_tech",
            run_id=run_id,
            trigger_source="scheduled_service_full_run",
            first_failed_stage=stage,
            error_code=error_code,
            issue_codes=[error_code],
        )

    def test_final_failure_paths_emit_once_each(self) -> None:
        cases = [
            ("source_prompt_hold", "validation_hold", "source_shortage_hold"),
            ("generation_failure", "generation_validation", "contentless_response"),
            ("schema_block", "generation_validation", "gemini_json_schema_validation_failed"),
            ("image_failure", "image_generation", "image_api_failed"),
            ("render_failure", "email_rendering", "post_render_qa_failed"),
            ("smtp_failure", "email_delivery", "smtp_send_failed"),
            ("artifact_persistence", "artifact_persistence", "artifact_save_failed"),
            ("unexpected_exception", "service_exception", "unexpected_exception"),
        ]
        for run_id, stage, code in cases:
            self.assertTrue(self._emit(run_id=run_id, stage=stage, error_code=code), run_id)
            # dedupe: second emit for same run is suppressed
            self.assertFalse(self._emit(run_id=run_id, stage=stage, error_code=code), run_id)

    def test_intermediate_recoverable_failure_does_not_alert(self) -> None:
        # Intermediate recovery attempt is not a finalizer emit; gate alone is
        # not enough — callers must not emit until final safe-fail. Prove the
        # helper remains quiet for dry-run scheduled recovery noise.
        self.assertFalse(
            should_emit_owner_review_failure_event(
                trigger_source="scheduled_owner_review", dry_run=True
            )
        )

    def test_infer_stages_cover_documented_set(self) -> None:
        self.assertEqual(
            infer_first_failed_stage(error_code="smtp_send_failed"), "email_delivery"
        )
        self.assertEqual(
            infer_first_failed_stage(error_code="image_api_failed"), "image_generation"
        )
        self.assertEqual(
            infer_first_failed_stage(error_code="artifact_save_failed"),
            "artifact_persistence",
        )
        self.assertEqual(
            infer_first_failed_stage(error_code="unexpected_exception"),
            "service_exception",
        )
        self.assertEqual(
            infer_first_failed_stage(
                error_code="validation_blocked",
                hold_reason="source_shortage_hold",
            ),
            "validation_hold",
        )


class PrivacyAndDedupTests(unittest.TestCase):
    def test_payload_excludes_banned_keys_and_secrets(self) -> None:
        payload = build_owner_review_run_failed_payload(
            program_id="keysuri_global_tech",
            run_id="priv1",
            trigger_source="scheduled_owner_review",
            first_failed_stage="generation_validation",
            error_code="gemini_json_missing_required_keys",
            issue_codes=["gemini_json_missing_required_keys", "password_should_drop"],
        )
        blob = json.dumps(payload)
        for banned in _BANNED_PAYLOAD_KEYS:
            self.assertNotIn(f'"{banned}"', blob)
        self.assertNotIn("password_should_drop", payload["issue_codes"])
        self.assertNotIn("raw_response", payload)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("recipients", payload)

    def test_dedup_is_in_process_only(self) -> None:
        docs = (_REPO / "docs" / "ops" / "OWNER_REVIEW_FAILURE_ALERTING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("in-process only", docs)
        self.assertNotIn("cross-instance dedup implemented", docs.lower())


class RecurrenceMetricsHarnessTests(unittest.TestCase):
    def test_counter_names_stable_and_aggregation_deterministic(self) -> None:
        self.assertEqual(
            RECURRENCE_COUNTER_NAMES,
            (
                "generation_attempts",
                "bounded_retry_count",
                "retry_success",
                "retry_exhausted",
                "json_extraction_failure",
                "contentless_response_failure",
                "program_id_repair_count",
                "conflicting_program_id_block_count",
                "schema_validation_failure",
                "post_render_truncation_block",
                "global_run_success",
                "global_run_safe_fail",
            ),
        )
        records = [
            {
                "generation_attempt_count": 2,
                "global_recovery_attempted": True,
                "global_recovery_result": "succeeded",
                "validation_result": "pass",
                "email_sent": True,
                "parse_meta": {"repaired_fields": ["program_id"]},
            },
            {
                "generation_attempt_count": 2,
                "global_generation_budget_exhausted": True,
                "validation_result": "block",
                "issue_codes": ["gemini_json_missing_required_keys"],
            },
        ]
        a = aggregate_recurrence_counters(records)
        b = aggregate_recurrence_counters(list(reversed(records)))
        self.assertEqual(a, b)
        self.assertEqual(a["generation_attempts"], 4)
        self.assertEqual(a["retry_success"], 1)
        self.assertEqual(a["retry_exhausted"], 1)
        # inspection is side-effect free: re-reading does not mutate
        before = json.dumps(records, sort_keys=True)
        recurrence_counters_for_run(records[0])
        after = json.dumps(records, sort_keys=True)
        self.assertEqual(before, after)


class InspectScriptHarnessTests(unittest.TestCase):
    def test_fixture_inspection_groups_and_exits_zero(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT),
                "--failure-log",
                str(_FIXTURES / "sample_failure_events.jsonl"),
                "--artifacts-dir",
                str(_FIXTURES / "artifacts"),
                "--json",
            ],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["event_count"], 3)
        self.assertEqual(report["artifact_count"], 2)
        self.assertFalse(report["network"])
        self.assertFalse(report["writes"])
        self.assertIn(
            "program_id=keysuri_global_tech|first_failed_stage=generation_validation|issue_code=gemini_json_missing_required_keys",
            report["grouped_events"],
        )

    def test_malformed_input_exits_nonzero(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as handle:
            handle.write('{"event": "owner_review_run_failed", broken\n')
            path = handle.name
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--failure-log", path],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ERROR", proc.stderr)


if __name__ == "__main__":
    unittest.main()
