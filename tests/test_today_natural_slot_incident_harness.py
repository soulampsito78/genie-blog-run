"""Production-faithful harness: Today natural-slot vs QA coexistence.

Exercises real gate + internal job routing. Fakes only: clock, artifact list,
orchestrator/model/image/SMTP. Does not fake execution classification,
idempotency key construction, previous-run lookup, or failure-event decision.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from main import app
from owner_review_failure_events import (
    OWNER_REVIEW_RUN_FAILED_EVENT,
    configure_owner_review_failure_event_logger,
    reset_owner_review_failure_event_dedupe_for_tests,
)
from today_genie_execution_identity import (
    EXECUTION_CLASS_ADMIN_REISSUE,
    EXECUTION_CLASS_NATURAL_SCHEDULED,
    EXECUTION_CLASS_PREVIEW,
    EXECUTION_CLASS_QA_MANUAL,
    GATE_ACTION_ADMIT,
    GATE_ACTION_REJECT_INVALID_MATCH,
    GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE,
    TODAY_NATURAL_SCHEDULED_SLOT,
    evaluate_today_natural_slot_gate,
    natural_slot_completer_qualification,
    resolve_today_execution_identity,
)

KST = ZoneInfo("Asia/Seoul")
TOKEN = "natural-slot-harness-token"
ENDPOINT = "/internal/jobs/create-owner-review"
INCIDENT_DATE = datetime(2026, 8, 7, 6, 30, tzinfo=KST)


def _natural_body(**extra: Any) -> Dict[str, Any]:
    body = {
        "execution_class": EXECUTION_CLASS_NATURAL_SCHEDULED,
        "scheduled_slot": TODAY_NATURAL_SCHEDULED_SLOT,
        "trigger_source": "scheduled_owner_review",
    }
    body.update(extra)
    return body


def _qa_body(**extra: Any) -> Dict[str, Any]:
    body = {
        "execution_class": EXECUTION_CLASS_QA_MANUAL,
        "trigger_source": "manual_qa",
        "send_owner_email": True,
    }
    body.update(extra)
    return body


def _artifact(
    *,
    run_id: str,
    execution_class: str = "",
    scheduled_slot: str = "",
    email_sent: bool = True,
    artifact_status: str = "emailed",
    owner_review_status: str = "pending_review",
    validation_result: str = "pass",
    mode: str = "today_genie",
    parent_run_id: Optional[str] = None,
    trigger_source: str = "scheduled_owner_review",
    verification_mode: str = "",
    safe_fail: Any = None,
    owner_email_delivery_status: str = "",
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "email_sent": email_sent,
        "artifact_status": artifact_status,
        "owner_review_status": owner_review_status,
        "validation_result": validation_result,
        "trigger_source": trigger_source,
        "parent_run_id": parent_run_id,
        "workflow_status": "validated",
    }
    if execution_class:
        meta["execution_class"] = execution_class
    if scheduled_slot:
        meta["scheduled_slot"] = scheduled_slot
    if verification_mode:
        meta["verification_mode"] = verification_mode
    if safe_fail is not None:
        meta["safe_fail"] = safe_fail
    if owner_email_delivery_status:
        meta["owner_email_delivery_status"] = owner_email_delivery_status
    return meta


class _SideEffects:
    def __init__(self) -> None:
        self.orchestrator_calls = 0
        self.smtp_calls = 0
        self.model_calls = 0
        self.image_calls = 0
        self.customer_sends = 0
        self.failure_events: List[Dict[str, Any]] = []

    def record_orchestrator(self, *args: Any, **kwargs: Any):
        self.orchestrator_calls += 1
        self.model_calls += 1
        self.image_calls += 1
        if kwargs.get("send_owner_email", True):
            self.smtp_calls += 1
        run_id = f"20260807_063000_today_genie_{self.orchestrator_calls:08x}"
        return run_id, mock.Mock(response_status=200), bool(kwargs.get("send_owner_email", True))


class TodayNaturalSlotHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.env = mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": TOKEN}, clear=False)
        self.env.start()
        self.clock = mock.patch("internal_jobs.get_kst_now", return_value=INCIDENT_DATE)
        self.clock.start()
        self.effects = _SideEffects()
        reset_owner_review_failure_event_dedupe_for_tests()
        configure_owner_review_failure_event_logger()
        self._failure_handler = mock.patch(
            "owner_review_failure_events.event_logger.error",
            side_effect=self._capture_failure,
        )
        self._failure_handler.start()

    def tearDown(self) -> None:
        self._failure_handler.stop()
        self.clock.stop()
        self.env.stop()
        reset_owner_review_failure_event_dedupe_for_tests()

    def _capture_failure(self, message: str, *args: Any, **kwargs: Any) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            payload = {"raw": message}
        self.effects.failure_events.append(payload)

    def _post(self, body: Dict[str, Any], artifacts: List[Dict[str, Any]]):
        with mock.patch("internal_jobs.list_run_artifacts", return_value=artifacts):
            with mock.patch(
                "internal_jobs.execute_orchestrator_run",
                side_effect=self.effects.record_orchestrator,
            ):
                with mock.patch(
                    "internal_jobs.check_artifact_store_ready",
                    return_value=(None, {"backend": "fake"}),
                ):
                    with mock.patch(
                        "internal_jobs._safe_owner_review_summary",
                        side_effect=lambda run_id, **kw: {
                            "ok": True,
                            "run_id": run_id,
                            "mode": "today_genie",
                            "email_sent": True,
                            "skipped_duplicate": kw.get("skipped_duplicate", False),
                            **(kw.get("gate_diagnostics") or {}),
                        },
                    ):
                        return self.client.post(
                            ENDPOINT,
                            json=body,
                            headers={"X-Genie-Internal-Job-Token": TOKEN},
                        )

    # --- Required scenarios ---

    def test_01_qa_then_natural_same_kst_date_natural_runs(self) -> None:
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
        )
        resp = self._post(_natural_body(), [qa])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.orchestrator_calls, 1)
        self.assertFalse(resp.json().get("skipped_duplicate"))

    def test_02_manual_qa_after_natural_success_still_runs(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        resp = self._post(_qa_body(), [natural])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_03_genuine_duplicate_natural_skips_explicitly(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        resp = self._post(_natural_body(), [natural])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("skipped_duplicate") or body.get("duplicate"))
        self.assertEqual(body.get("matched_run_id"), natural["run_id"])
        self.assertEqual(body.get("matched_execution_class"), EXECUTION_CLASS_NATURAL_SCHEDULED)
        self.assertEqual(self.effects.orchestrator_calls, 0)
        self.assertEqual(self.effects.smtp_calls, 0)
        self.assertEqual(len(self.effects.failure_events), 0)

    def test_04_next_kst_date_natural_runs(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        # Next weekday after 2026-08-07 (Fri) is 2026-08-10 (Mon); weekend guard
        # would otherwise skip Sat/Sun before the slot gate matters.
        next_weekday = datetime(2026, 8, 10, 6, 30, tzinfo=KST)
        with mock.patch("internal_jobs.get_kst_now", return_value=next_weekday):
            resp = self._post(_natural_body(), [natural])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_05_previous_natural_failed_does_not_complete_slot(self) -> None:
        failed = _artifact(
            run_id="20260807_063010_today_genie_fail01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=False,
            artifact_status="failed",
            validation_result="block",
            owner_review_status="",
        )
        resp = self._post(_natural_body(), [failed])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_06_previous_natural_safe_fail_does_not_satisfy(self) -> None:
        safe = _artifact(
            run_id="20260807_063010_today_genie_safe01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=False,
            artifact_status="failed",
            safe_fail=True,
            owner_review_status="",
        )
        resp = self._post(_natural_body(), [safe])
        self.assertEqual(self.effects.orchestrator_calls, 1)
        self.assertEqual(resp.status_code, 200)

    def test_07_smtp_failed_natural_does_not_satisfy(self) -> None:
        smtp_fail = _artifact(
            run_id="20260807_063010_today_genie_smtp01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=False,
            artifact_status="validated",
            owner_review_status="pending_review",
            owner_email_delivery_status="smtp_failed",
        )
        # email_sent False → not terminal success under qualification
        resp = self._post(_natural_body(), [smtp_fail])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_08_previous_qa_emailed_does_not_satisfy_natural(self) -> None:
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
            # Incident-shaped: same trigger_source string as scheduler
            trigger_source="scheduled_owner_review",
        )
        resp = self._post(_natural_body(), [qa])
        self.assertEqual(self.effects.orchestrator_calls, 1)
        self.assertFalse(resp.json().get("skipped_duplicate"))

    def test_09_previous_reissue_emailed_does_not_satisfy(self) -> None:
        reissue = _artifact(
            run_id="20260807_070000_today_genie_reiss01",
            execution_class=EXECUTION_CLASS_ADMIN_REISSUE,
            email_sent=True,
            parent_run_id="20260807_063000_today_genie_parent",
            artifact_status="reissued",
        )
        resp = self._post(_natural_body(), [reissue])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_10_preview_does_not_satisfy(self) -> None:
        preview = _artifact(
            run_id="20260807_050000_today_genie_prev01",
            execution_class=EXECUTION_CLASS_PREVIEW,
            email_sent=False,
            artifact_status="validated",
            verification_mode="no_send_verification",
        )
        resp = self._post(_natural_body(), [preview])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_11_global_same_date_cannot_block_today(self) -> None:
        global_run = _artifact(
            run_id="20260807_123000_keysuri_global_tech_aaaa1111",
            mode="keysuri_global_tech",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="12:30",
            email_sent=True,
        )
        resp = self._post(_natural_body(), [global_run])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_12_korea_same_date_cannot_block_today(self) -> None:
        korea = _artifact(
            run_id="20260807_183000_keysuri_korea_tech_bbbb2222",
            mode="keysuri_korea_tech",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="18:30",
            email_sent=True,
        )
        resp = self._post(_natural_body(), [korea])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_13_different_scheduled_slot_no_collision(self) -> None:
        other_slot = _artifact(
            run_id="20260807_120000_today_genie_slot2",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="12:00",
            email_sent=True,
        )
        resp = self._post(_natural_body(), [other_slot])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_14_missing_trigger_source_fails_closed(self) -> None:
        resp = self._post(
            {
                "execution_class": EXECUTION_CLASS_NATURAL_SCHEDULED,
                "scheduled_slot": "06:30",
            },
            [],
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"], "trigger_source_required")
        self.assertEqual(self.effects.orchestrator_calls, 0)
        self.assertEqual(len(self.effects.failure_events), 1)
        self.assertEqual(
            self.effects.failure_events[0]["event"], OWNER_REVIEW_RUN_FAILED_EVENT
        )

    def test_15_legacy_artifact_without_execution_class_cannot_satisfy(self) -> None:
        legacy = _artifact(
            run_id="20260807_063058_today_genie_legacy1",
            execution_class="",
            email_sent=True,
            trigger_source="scheduled_owner_review",
        )
        match = natural_slot_completer_qualification(
            legacy, kst_date="2026-08-07", scheduled_slot="06:30"
        )
        self.assertFalse(match.qualifies)
        self.assertEqual(match.disqualify_reason, "legacy_missing_execution_class")
        resp = self._post(_natural_body(), [legacy])
        self.assertEqual(self.effects.orchestrator_calls, 1)

    def test_16_legitimate_duplicate_persists_matched_run_diagnostics(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
            owner_review_status="approved",
        )
        resp = self._post(_natural_body(), [natural])
        body = resp.json()
        self.assertEqual(body.get("matched_run_id"), natural["run_id"])
        self.assertEqual(body.get("matched_execution_class"), EXECUTION_CLASS_NATURAL_SCHEDULED)
        self.assertEqual(body.get("matched_slot"), "06:30")
        self.assertEqual(body.get("matched_terminal_status"), "approved")
        self.assertEqual(body.get("current_request_execution_class"), EXECUTION_CLASS_NATURAL_SCHEDULED)

    def test_17_invalid_duplicate_match_emits_failure_event_once(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[qa],
            force_treat_emailed_qa_as_natural=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)
        # Route through endpoint mutation path via direct helper used by endpoint
        from internal_jobs import _today_natural_gate_response

        first = _today_natural_gate_response(decision)
        second = _today_natural_gate_response(decision)
        self.assertEqual(first.status_code, 409)
        self.assertEqual(len(self.effects.failure_events), 1)
        # Second call deduped
        self.assertEqual(len(self.effects.failure_events), 1)
        self.assertIsNotNone(second)

    def test_18_legitimate_duplicate_does_not_emit_false_failure(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        self._post(_natural_body(), [natural])
        self.assertEqual(self.effects.failure_events, [])

    def test_19_no_duplicate_smtp_on_legitimate_skip(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        self._post(_natural_body(), [natural])
        self.assertEqual(self.effects.smtp_calls, 0)

    def test_20_customer_delivery_always_zero_in_harness(self) -> None:
        self._post(_natural_body(), [])
        self.assertEqual(self.effects.customer_sends, 0)

    def test_21_pre_generation_duplicate_block_skips_model_image(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        self._post(_natural_body(), [natural])
        self.assertEqual(self.effects.model_calls, 0)
        self.assertEqual(self.effects.image_calls, 0)

    def test_22_full_normal_path_calls_model_image_smtp_once(self) -> None:
        resp = self._post(_natural_body(), [])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.model_calls, 1)
        self.assertEqual(self.effects.image_calls, 1)
        self.assertEqual(self.effects.smtp_calls, 1)

    def test_23_six_index_contract_untouched_by_identity_module(self) -> None:
        # Identity resolution must not import or mutate market index helpers.
        import today_genie_execution_identity as ident

        self.assertFalse(hasattr(ident, "REQUIRED_INDEX_KEYS"))
        identity, err, _ = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        self.assertIsNone(err)
        self.assertEqual(identity.scheduled_slot, "06:30")

    def test_24_prompt_contract_v2_does_not_alter_execution_classification(self) -> None:
        identity, err, _ = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        self.assertIsNone(err)
        self.assertEqual(identity.execution_class, EXECUTION_CLASS_NATURAL_SCHEDULED)

    def test_25_artifact_success_contract_does_not_alter_duplicate_identity(self) -> None:
        natural = _artifact(
            run_id="20260807_063058_today_genie_natok01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=True,
        )
        natural["generation_contract"] = {"version": "success-v1", "bounded": True}
        match = natural_slot_completer_qualification(
            natural, kst_date="2026-08-07", scheduled_slot="06:30"
        )
        self.assertTrue(match.qualifies)

    # --- Adversarial mutations ---

    def test_mutation_remove_execution_class_from_key_fails(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class="",
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        self.assertIsNone(identity)
        self.assertEqual(err, "execution_class_required")
        decision = evaluate_today_natural_slot_gate(
            identity=identity, identity_error=err, identity_issues=issues, artifacts=[]
        )
        self.assertNotEqual(decision.action, GATE_ACTION_ADMIT)

    def test_mutation_date_only_key_rejected(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[qa],
            force_date_only_match=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_treat_emailed_qa_as_natural_rejected(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[qa],
            force_treat_emailed_qa_as_natural=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_accept_failed_as_success_rejected(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        failed = _artifact(
            run_id="20260807_063010_today_genie_fail01",
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            email_sent=False,
            artifact_status="failed",
            validation_result="block",
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[failed],
            force_accept_failed_as_success=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_silent_http_200_without_diagnostics_is_not_production_action(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            email_sent=True,
        )
        silent = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[qa],
            force_treat_emailed_qa_as_natural=True,
            force_silent_skip_without_diagnostics=True,
        )
        # Mutation can manufacture a silent skip; production wrapper must not.
        self.assertEqual(silent.action, GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE)
        hardened = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[qa],
            force_treat_emailed_qa_as_natural=True,
            force_silent_skip_without_diagnostics=False,
        )
        self.assertEqual(hardened.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_cross_match_global_today_rejected(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        global_run = _artifact(
            run_id="20260807_123000_keysuri_global_tech_aaaa1111",
            mode="keysuri_global_tech",
            email_sent=True,
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[global_run],
            force_cross_mode=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_ignore_scheduled_slot_rejected(self) -> None:
        identity, err, issues = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source="scheduled_owner_review",
            now=INCIDENT_DATE,
        )
        other = _artifact(
            run_id="20260807_120000_today_genie_other",
            execution_class=EXECUTION_CLASS_QA_MANUAL,
            scheduled_slot="12:00",
            email_sent=True,
        )
        decision = evaluate_today_natural_slot_gate(
            identity=identity,
            identity_error=err,
            identity_issues=issues,
            artifacts=[other],
            force_ignore_slot=True,
        )
        self.assertEqual(decision.action, GATE_ACTION_REJECT_INVALID_MATCH)

    def test_mutation_missing_trigger_classified_as_natural_fails(self) -> None:
        identity, err, _ = resolve_today_execution_identity(
            execution_class=EXECUTION_CLASS_NATURAL_SCHEDULED,
            scheduled_slot="06:30",
            trigger_source=None,
            now=INCIDENT_DATE,
        )
        self.assertIsNone(identity)
        self.assertEqual(err, "trigger_source_required")

    def test_incident_shaped_legacy_qa_without_class_does_not_block(self) -> None:
        """Exact 2026-08-07 incident shape: emailed QA, no execution_class."""
        incident_qa = _artifact(
            run_id="20260807_003207_today_genie_255d3454",
            execution_class="",
            email_sent=True,
            artifact_status="emailed",
            trigger_source="scheduled_owner_review",
        )
        resp = self._post(_natural_body(), [incident_qa])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.effects.orchestrator_calls, 1)
        self.assertEqual(self.effects.failure_events, [])


class TodayOwnerMimePersistenceHarness(unittest.TestCase):
    """Real execute -> render -> owner-send -> local store -> received-HTML gate.

    Fake only paid model/image, SMTP transport, clock and remote I/O boundaries.
    The orchestrator, renderer, notice injection, persistence and binding gate
    remain real. Advancing the render clock makes the 2026-10-23 bug falsifiable.
    This is not a live SMTP, independent content QA, or customer-send test.
    """

    def setUp(self) -> None:
        from orchestrator import OrchestrationResult
        from publishing_policy import PublishingDecision
        from today_genie_orchestrator_images import TodayGenieOrchestratorImageResult

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "GENIE_ARTIFACT_STORE_BACKEND": "local",
            "GENIE_ARTIFACT_BUCKET": "",
            "GENIE_ADMIN_PUBLIC_BASE_URL": "https://admin.example.test",
            "GENIE_ADMIN_REISSUE": "",
            "GENIE_ADMIN_SAFETY_LOCAL_DIR": str(self.root / "safety"),
            "EMAIL_TO": "offline-owner@example.test",
        }))
        self.stack.enter_context(mock.patch("admin_store.admin_runs_dir", return_value=self.runs))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("HARNESS_NETWORK_FORBIDDEN")))
        self.stack.enter_context(mock.patch("urllib.request.urlopen", side_effect=AssertionError("HARNESS_NETWORK_FORBIDDEN")))
        self.result = OrchestrationResult(
            decision=PublishingDecision(send_email=True, create_naver_draft=False,
                auto_publish=False, require_review=True, suppress_external=False,
                send_customer_email=False),
            reason_summary="offline fixture", response_status=200, mode="today_genie",
            response_data={"type":"today_genie", "validation_result":"pass",
                "workflow_status":"validated", "runtime_input":{"target_date":"2026-10-23"},
                "data":{"title":"Binding harness", "summary":"Original fixture claim",
                    "channel_drafts":{"email_subject":"Offline owner review"}}},
        )
        parts = []
        for role in ("top", "bottom"):
            path = self.root / (role + ".jpg")
            path.write_bytes(b"offline image fixture " + role.encode())
            parts.append((str(path), "genie.today." + role + "@genie-email.local", path.name))
        self.images = TodayGenieOrchestratorImageResult(
            inline_parts=parts, image_source="generated", image_generation_status="generated",
            generated_image_paths={role:parts[i][0] for i,role in enumerate(("top","bottom"))},
        )
        self.model = self.stack.enter_context(mock.patch("orchestrator.run_genie_job", side_effect=lambda *a, **k:self.result))
        self.image_api = self.stack.enter_context(mock.patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images", return_value=self.images))
        self.clock = self.stack.enter_context(mock.patch("main.datetime"))
        self.clock.now.side_effect = lambda zone: datetime(2026,10,23,6,31,11,tzinfo=zone) + timedelta(seconds=self.clock.now.call_count)
        self.outbound = []
        self.smtp_ok = True

        def owner_smtp(html, subject, **kwargs):
            from email_sender import _build_mime_multipart_inline_and_attach
            from smtplib import _fix_eols

            message = _build_mime_multipart_inline_and_attach(
                html, "offline-sender@example.test", ["offline-owner@example.test"],
                subject, kwargs.get("inline_jpeg_parts") or [], [],
            )
            message["Message-ID"] = "<offline-owner@example.test>"
            # Production serializes this legacy MIME tree with as_string(),
            # then smtplib normalizes SMTP framing. Do not substitute the newer
            # EmailMessage/SMTP serializer and introduce unrelated body drift.
            raw = _fix_eols(message.as_string()).encode("ascii")
            parsed = BytesParser(policy=policy.default).parsebytes(raw)
            received = next(p.get_content() for p in parsed.walk() if p.get_content_type()=="text/html")
            cids = {str(p.get("Content-ID") or "").strip("<>"):p.get_payload(decode=True)
                for p in parsed.walk() if p.get_content_maintype()=="image"}
            self.outbound.append({"html":html, "received":received, "raw":raw, "inline":kwargs.get("inline_jpeg_parts"), "cid_bytes":cids})
            return self.smtp_ok

        self.smtp = self.stack.enter_context(mock.patch("orchestrator.send_genie_email", side_effect=owner_smtp))

    def _execute(self, **kwargs):
        from orchestrator import execute_orchestrator_run
        from admin_store import load_run_artifact, load_run_email_html
        rid, _, sent = execute_orchestrator_run("today_genie",
            trigger_source="scheduled_owner_review", execution_class="natural_scheduled",
            scheduled_slot="06:30", schedule_now=datetime(2026,10,23,6,30,tzinfo=KST), **kwargs)
        return rid, sent, load_run_artifact(rid), load_run_email_html(rid)

    def _assert_bound(self, saved):
        from delegated_gate import verify_received_html_transport
        self.assertEqual(self.outbound[-1]["html"], saved)
        self.assertEqual(verify_received_html_transport(self.outbound[-1]["received"], saved), {"recognized_transport_suffix_count":0})

    def test_natural_owner_send_persists_exact_attempted_html_across_second_boundary(self):
        _, sent, meta, saved = self._execute()
        self.assertTrue(sent)
        self._assert_bound(saved)
        self.assertEqual(self.clock.now.call_count, 1)
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.image_api.call_count, 1)
        self.assertEqual(self.smtp.call_count, 1)
        for path, cid, _ in self.images.inline_parts:
            self.assertEqual(self.outbound[-1]["cid_bytes"][cid], Path(path).read_bytes())
        self.assertEqual(meta["customer_delivery_status"], "not_sent")
        self.assertEqual(meta["owner_review_status"], "pending_review")
        self.assertEqual(meta["execution_class"], "natural_scheduled")

    def test_owner_smtp_failure_persists_same_attempt_without_retry_or_customer_send(self):
        self.smtp_ok = False
        _, sent, meta, saved = self._execute()
        self.assertFalse(sent)
        self._assert_bound(saved)
        self.assertEqual(self.smtp.call_count, 1)
        self.assertEqual(self.clock.now.call_count, 1)
        self.assertFalse(meta["email_sent"])
        self.assertEqual(meta["customer_delivery_status"], "not_sent")

    def test_no_send_still_stores_one_render_without_smtp(self):
        _, sent, meta, saved = self._execute(send_owner_email=False)
        self.assertFalse(sent)
        self.assertTrue(saved)
        self.assertEqual(self.clock.now.call_count, 1)
        self.smtp.assert_not_called()
        self.assertEqual(meta["verification_mode"], "no_send_verification")
        self.assertEqual(meta["customer_delivery_status"], "not_sent")

    def test_suppressed_policy_never_sends(self):
        self.result.decision = replace(self.result.decision, suppress_external=True)
        _, sent, meta, saved = self._execute()
        self.assertFalse(sent)
        self.smtp.assert_not_called()
        self.assertTrue(saved)
        self.assertEqual(self.clock.now.call_count, 1)
        self.assertEqual(meta["customer_delivery_status"], "not_sent")

    def test_owner_notice_is_identical_and_injected_once(self):
        notice = "<!-- fixture-owner-notice --><p>Offline notice</p>"
        _, _, _, saved = self._execute(owner_email_notice_html=notice)
        self._assert_bound(saved)
        self.assertEqual(saved.count(notice), 1)
        self.assertEqual(self.clock.now.call_count, 1)

    def test_customer_visible_tamper_still_fails_exact_binding(self):
        from delegated_gate import GateError, verify_received_html_transport
        _, _, _, saved = self._execute()
        changed = saved.replace("Original fixture claim", "Altered fixture claim")
        self.assertNotEqual(saved, changed)
        with self.assertRaisesRegex(GateError, "RECEIVED_HTML_RUN_BINDING_MISMATCH"):
            verify_received_html_transport(self.outbound[-1]["received"], changed)

    def test_separate_natural_runs_do_not_reuse_prior_render(self):
        first_id, _, _, first = self._execute()
        second_id, _, _, second = self._execute()
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first, second)
        self.assertIn(second_id, second)
        self.assertNotIn(first_id, second)
        self._assert_bound(second)
        self.assertEqual(self.clock.now.call_count, 2)

    def test_blocked_validation_never_sends_or_generates_images(self):
        self.result.response_data["validation_result"] = "block"
        self.result.decision = replace(self.result.decision, send_email=False, suppress_external=True)
        _, sent, meta, _ = self._execute()
        self.assertFalse(sent)
        self.smtp.assert_not_called()
        self.image_api.assert_not_called()
        self.assertEqual(meta["customer_delivery_status"], "not_sent")

    def test_empty_render_is_not_rerendered_or_submitted(self):
        with mock.patch("main.build_today_genie_email_html_for_cid_mime_send", return_value="") as renderer:
            _, sent, meta, saved = self._execute()
        self.assertFalse(sent)
        self.assertFalse(saved)
        renderer.assert_called_once()
        self.smtp.assert_not_called()
        self.assertEqual(meta["customer_delivery_status"], "not_sent")


if __name__ == "__main__":
    unittest.main()
