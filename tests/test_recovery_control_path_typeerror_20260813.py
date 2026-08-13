"""Regression: 2026-08-13 Admin recovery control-path TypeError.

Production evidence (revision genie-blog-run-00293-gsx):

    File "/app/natural_run_recovery.py", line 92, in execute_approved_recovery
        run_id, result, email_sent = runner(
    TypeError: execute_approved_recovery.<locals>.runner() takes 0 positional
               arguments but 1 was given

``execute_orchestrator_run`` takes ``mode`` positionally, but the Today branch
wrapped it in a kwargs-only closure, so every Today recovery raised TypeError at
the call boundary — before any source fetch, model call, image, or SMTP. No
recovery run was ever created. The generic exception handler nevertheless fed a
failure signature to ``complete_recovery``, so two owner clicks incremented the
repeat-recovery guard to 2 and flipped the incident to
RETRY_BLOCKED_PENDING_PATCH, blocking an authorized recovery that had never run.

Fakes: incident store dir, runners. Does not fake: the call contract, the guard
threshold, or the actionability contract.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from natural_run_incident_store import (
    RETRY_ALLOWED_WITH_WARNING,
    RETRY_BLOCKED,
    STATUS_RECOVERY_FAILED,
    STATUS_REPORTED,
    STATUS_RETRY_BLOCKED_PENDING_PATCH,
    acquire_recovery_lease,
    clear_control_plane_recovery_guard,
    is_retry_actionable,
    load_incident,
    recovery_effective_retry_verdict,
    recovery_guard_is_blocked,
    recovery_guard_was_control_plane_only,
    save_incident,
)
from natural_run_recovery import execute_approved_recovery

INCIDENT_ID = "2026-08-13_today_genie_06-30"
ORIGINAL_RUN_ID = "20260813_063055_today_genie_1f6f0814"
ISSUE_CODE = "unanchored_briefing_vs_input_news"
REVISION = "genie-blog-run-00293-gsx"


def _pre_click_incident(**overrides: Any) -> Dict[str, Any]:
    """Incident exactly as the patched watchdog left it before the owner click."""
    meta: Dict[str, Any] = {
        "incident_id": INCIDENT_ID,
        "program_id": "today_genie",
        "program_display": "Today_Geenee",
        "kst_date": "2026-08-13",
        "scheduled_slot": "06:30",
        "status": STATUS_REPORTED,
        "original_run_id": ORIGINAL_RUN_ID,
        "issue_codes": [ISSUE_CODE],
        "first_failed_stage": "generation_validation",
        "error_code": ISSUE_CODE,
        "root_cause_verdict": "ROOT_CAUSE_PARTIAL",
        "retry_verdict": RETRY_ALLOWED_WITH_WARNING,
        "recommendation_ko": "주의 후 재실행 가능",
        "report_sent_at": "2026-08-13T06:45:07.374115+09:00",
        "report_send_count": 1,
        "recovery_run_id": None,
        "recovery_lease_token": None,
        "recovery_approved_at": None,
        "recovery_customer_send_count": 0,
        "recovery_failure_signature": None,
        "recovery_failure_signature_count": 0,
        "recovery_failure_history": [],
        "revision": REVISION,
    }
    meta.update(overrides)
    return meta


class _StoreIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inc_dir = Path(self.tmp.name) / "admin_incidents"
        self.inc_dir.mkdir(parents=True, exist_ok=True)
        self._patches = [
            mock.patch(
                "natural_run_incident_store.incidents_local_dir",
                return_value=self.inc_dir,
            ),
            mock.patch("natural_run_incident_store._uses_gcs", return_value=False),
            mock.patch.dict(
                os.environ,
                {"GENIE_ARTIFACT_BUCKET": "", "GENIE_ADMIN_ARTIFACT_BUCKET": ""},
                clear=False,
            ),
        ]
        for p in self._patches:
            p.start()
        self.reports: List[Any] = []

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()

    def _send(self, **kwargs: Any) -> bool:
        self.reports.append(kwargs)
        return True


class TodayRunnerCallContract(_StoreIsolation):
    """Phase 6/7 — the exact production TypeError must not recur."""

    def test_today_recovery_passes_mode_positionally(self) -> None:
        save_incident(_pre_click_incident())
        seen: Dict[str, Any] = {}

        def today_runner(mode, **kwargs):
            seen["mode"] = mode
            seen["kwargs"] = kwargs
            return ("20260813_150000_today_genie_recovered", None, True)

        result = execute_approved_recovery(
            INCIDENT_ID, today_runner=today_runner, send_fn=self._send
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen["mode"], "today_genie")
        self.assertEqual(seen["kwargs"]["execution_class"], "recovery")
        self.assertEqual(seen["kwargs"]["trigger_source"], "admin_recovery_approved")
        self.assertTrue(seen["kwargs"]["send_owner_email"])
        self.assertEqual(result["customer_send"], 0)

    def test_default_today_runner_accepts_positional_mode(self) -> None:
        """The real default runner must bind execute_orchestrator_run directly."""
        import inspect

        import natural_run_recovery as mod
        from orchestrator import execute_orchestrator_run

        src = inspect.getsource(mod.execute_approved_recovery)
        self.assertIn("runner = execute_orchestrator_run", src)
        self.assertNotIn("def runner(**kwargs)", src)
        params = list(inspect.signature(execute_orchestrator_run).parameters.values())
        self.assertEqual(params[0].name, "mode")
        self.assertIn(
            params[0].kind,
            (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD),
        )


class ControlPlaneFailureDoesNotPoisonGuard(_StoreIsolation):
    """Phase 8/10 — controller errors must not advance the content guard."""

    def _typeerror_runner(self, *args: Any, **kwargs: Any):
        raise TypeError("runner() takes 0 positional arguments but 1 was given")

    def test_single_control_error_leaves_guard_untouched(self) -> None:
        save_incident(_pre_click_incident())
        result = execute_approved_recovery(
            INCIDENT_ID, today_runner=self._typeerror_runner, send_fn=self._send
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TypeError")
        self.assertIsNone(result["recovery_run_id"])
        self.assertEqual(result["customer_send"], 0)

        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertIsNone(after["recovery_failure_signature"])
        self.assertEqual(after["recovery_failure_signature_count"], 0)
        self.assertEqual(after["recovery_failure_history"], [])
        self.assertNotEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertEqual(after["recovery_control_error"], "TypeError")
        self.assertIn("재실행 요청 처리 오류", after["recovery_outcomes"]["생성 결과"])
        # Still actionable for a genuine retry.
        self.assertEqual(
            recovery_effective_retry_verdict(after), RETRY_ALLOWED_WITH_WARNING
        )
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(after)))

    def test_two_control_errors_still_do_not_block(self) -> None:
        """The exact production sequence: two owner clicks, both TypeError."""
        save_incident(_pre_click_incident())
        for _ in range(2):
            meta = load_incident(INCIDENT_ID) or {}
            meta["recovery_lease_token"] = None
            save_incident(meta)
            execute_approved_recovery(
                INCIDENT_ID, today_runner=self._typeerror_runner, send_fn=self._send
            )
        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["recovery_failure_signature_count"], 0)
        self.assertNotEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertFalse(recovery_guard_is_blocked(after))
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(after)))

    def test_no_child_run_or_customer_side_effects(self) -> None:
        save_incident(_pre_click_incident())
        result = execute_approved_recovery(
            INCIDENT_ID, today_runner=self._typeerror_runner, send_fn=self._send
        )
        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertIsNone(after["recovery_run_id"])
        self.assertEqual(after.get("recovery_customer_send_count") or 0, 0)
        self.assertEqual(result["auto_retry"], 0)
        self.assertEqual(after["recovery_outcomes"]["고객 발송"], "수행하지 않음")


class GenuineRecoveryFailureStillBlocks(_StoreIsolation):
    """Phase 10 — real repeated content failures must still trip the guard."""

    def _failing_runner(self, mode, **kwargs):
        return (
            "20260813_150000_today_genie_recovery",
            _Result({"validation_result": "block", "issue_codes": [ISSUE_CODE]}),
            False,
        )

    def test_first_genuine_failure_increments_but_stays_actionable(self) -> None:
        save_incident(_pre_click_incident())
        execute_approved_recovery(
            INCIDENT_ID, today_runner=self._failing_runner, send_fn=self._send
        )
        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["recovery_failure_signature_count"], 1)
        self.assertIsNotNone(after["recovery_failure_signature"])
        self.assertEqual(after["status"], STATUS_RECOVERY_FAILED)
        self.assertEqual(len(after["recovery_failure_history"]), 1)
        self.assertEqual(
            after["recovery_failure_history"][0]["recovery_run_id"],
            "20260813_150000_today_genie_recovery",
        )

    def test_second_identical_genuine_failure_blocks(self) -> None:
        save_incident(_pre_click_incident())
        for _ in range(2):
            meta = load_incident(INCIDENT_ID) or {}
            meta["recovery_lease_token"] = None
            save_incident(meta)
            execute_approved_recovery(
                INCIDENT_ID, today_runner=self._failing_runner, send_fn=self._send
            )
        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["recovery_failure_signature_count"], 2)
        self.assertEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertTrue(recovery_guard_is_blocked(after))
        self.assertEqual(recovery_effective_retry_verdict(after), RETRY_BLOCKED)
        self.assertFalse(is_retry_actionable(recovery_effective_retry_verdict(after)))

    def test_genuine_block_is_never_cleared_by_repair(self) -> None:
        save_incident(_pre_click_incident())
        for _ in range(2):
            meta = load_incident(INCIDENT_ID) or {}
            meta["recovery_lease_token"] = None
            save_incident(meta)
            execute_approved_recovery(
                INCIDENT_ID, today_runner=self._failing_runner, send_fn=self._send
            )
        blocked = load_incident(INCIDENT_ID)
        assert blocked is not None
        self.assertFalse(recovery_guard_was_control_plane_only(blocked))

        repaired = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert repaired is not None
        self.assertEqual(repaired["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertEqual(repaired["recovery_failure_signature_count"], 2)
        self.assertTrue(recovery_guard_is_blocked(repaired))


class _Result:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.response_data = data


class PoisonedIncidentReconciliation(_StoreIsolation):
    """Phase 9 — restore the incident poisoned by the two TypeError clicks."""

    def _poisoned(self) -> Dict[str, Any]:
        sig = "3ff7335a7fcdda7194b0e09d7ba304e6426034cefb18d054b2e39ae775808087"
        components = {
            "incident_id": INCIDENT_ID,
            "issue_code": "unknown_recovery_failure",
            "revision": REVISION,
            "selected_input_fingerprint": "",
            "stage": "generation_validation",
            "structural_failure_class": "unknown_recovery_failure",
        }
        return _pre_click_incident(
            status=STATUS_RETRY_BLOCKED_PENDING_PATCH,
            retry_verdict=RETRY_BLOCKED,
            retry_verdict_before_recovery_guard=RETRY_ALLOWED_WITH_WARNING,
            recovery_failure_signature=sig,
            recovery_failure_signature_components=components,
            recovery_failure_signature_count=2,
            recovery_failure_history=[
                {
                    "signature": sig,
                    "failed_at": "2026-08-13T14:36:51.127870+09:00",
                    "recovery_run_id": None,
                    "components": components,
                },
                {
                    "signature": sig,
                    "failed_at": "2026-08-13T14:38:47.366609+09:00",
                    "recovery_run_id": None,
                    "components": components,
                },
            ],
            recovery_approved_at="2026-08-13T14:38:47.110199+09:00",
            recovery_completed_at="2026-08-13T14:38:47.366553+09:00",
        )

    def test_production_poisoned_state_is_detected(self) -> None:
        meta = self._poisoned()
        self.assertTrue(recovery_guard_was_control_plane_only(meta))
        # Before repair it really is blocked.
        self.assertTrue(recovery_guard_is_blocked(meta))
        self.assertEqual(recovery_effective_retry_verdict(meta), RETRY_BLOCKED)

    def test_repair_restores_actionability(self) -> None:
        save_incident(self._poisoned())
        repaired = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert repaired is not None

        self.assertIsNone(repaired["recovery_failure_signature"])
        self.assertEqual(repaired["recovery_failure_signature_count"], 0)
        self.assertEqual(repaired["recovery_failure_history"], [])
        self.assertIsNone(repaired["recovery_run_id"])
        self.assertEqual(repaired["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)
        self.assertNotEqual(repaired["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertFalse(recovery_guard_is_blocked(repaired))
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(repaired)))

        # Original diagnosis preserved.
        self.assertEqual(repaired["original_run_id"], ORIGINAL_RUN_ID)
        self.assertIn(ISSUE_CODE, repaired["issue_codes"])
        self.assertEqual(repaired["first_failed_stage"], "generation_validation")
        # Forensics kept, not silently discarded.
        self.assertEqual(len(repaired["recovery_control_plane_failures"]), 2)

    def test_repair_is_idempotent_and_noop_when_clean(self) -> None:
        save_incident(self._poisoned())
        first = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert first is not None
        second = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert second is not None
        self.assertEqual(second["recovery_failure_signature_count"], 0)
        self.assertEqual(len(second["recovery_control_plane_failures"]), 2)

    def test_clean_incident_is_untouched(self) -> None:
        save_incident(_pre_click_incident())
        out = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert out is not None
        self.assertEqual(out["status"], STATUS_REPORTED)
        self.assertEqual(out["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)
        self.assertFalse(recovery_guard_was_control_plane_only(out))


class WatchdogReconciliationRepairsPoisonedIncident(_StoreIsolation):
    """Phase 17 — the natural watchdog poll must self-heal the incident."""

    def test_report_incident_once_repairs_without_resending(self) -> None:
        from natural_run_watchdog import diagnose_program_sla, report_incident_once
        from datetime import datetime
        from zoneinfo import ZoneInfo

        kst = ZoneInfo("Asia/Seoul")
        sig = "sig-control-plane"
        components = {
            "incident_id": INCIDENT_ID,
            "issue_code": "unknown_recovery_failure",
            "structural_failure_class": "unknown_recovery_failure",
        }
        save_incident(
            _pre_click_incident(
                status=STATUS_RETRY_BLOCKED_PENDING_PATCH,
                retry_verdict=RETRY_BLOCKED,
                retry_verdict_before_recovery_guard=RETRY_ALLOWED_WITH_WARNING,
                recovery_failure_signature=sig,
                recovery_failure_signature_count=2,
                recovery_failure_history=[
                    {"signature": sig, "recovery_run_id": None, "components": components},
                    {"signature": sig, "recovery_run_id": None, "components": components},
                ],
            )
        )
        artifact = {
            "run_id": ORIGINAL_RUN_ID,
            "mode": "today_genie",
            "execution_class": "natural_scheduled",
            "scheduled_slot": "06:30",
            "kst_schedule_date": "2026-08-13",
            "validation_result": "block",
            "artifact_status": "failed",
            "email_sent": False,
            "customer_delivery_status": "not_sent",
            "policy": {"send_email": False},
            "issue_codes": [ISSUE_CODE],
        }
        fresh = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[artifact],
            now=datetime(2026, 8, 13, 15, 0, tzinfo=kst),
        )
        assert fresh is not None
        result = report_incident_once(fresh, send_fn=self._send)

        self.assertEqual(self.reports, [])
        self.assertFalse(result["report_sent"])

        after = load_incident(INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["original_run_id"], ORIGINAL_RUN_ID)
        self.assertIn(ISSUE_CODE, after["issue_codes"])
        self.assertEqual(after["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)
        self.assertIsNone(after["recovery_failure_signature"])
        self.assertEqual(after["recovery_failure_signature_count"], 0)
        self.assertIsNone(after["recovery_run_id"])
        self.assertNotEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(after)))
        self.assertEqual(after["report_send_count"], 1)


class CrossProgramGuardIsolation(_StoreIsolation):
    """Phase 10/12 — Global and Korea recovery paths keep their protection."""

    def test_global_genuine_failure_still_increments(self) -> None:
        meta = _pre_click_incident(
            incident_id="2026-08-13_keysuri_global_tech_12-30",
            program_id="keysuri_global_tech",
            scheduled_slot="12:30",
        )
        save_incident(meta)

        def keysuri_runner(program_id, **kwargs):
            return {
                "ok": False,
                "run_id": "20260813_150000_keysuri_global_tech_rec",
                "email_sent": False,
                "validation_result": "block",
                "issue_codes": ["keysuri_code"],
            }

        with mock.patch("admin_store.update_run_artifact", return_value=None):
            execute_approved_recovery(
                "2026-08-13_keysuri_global_tech_12-30",
                keysuri_runner=keysuri_runner,
                send_fn=self._send,
            )
        after = load_incident("2026-08-13_keysuri_global_tech_12-30")
        assert after is not None
        self.assertEqual(after["recovery_failure_signature_count"], 1)
        self.assertFalse(recovery_guard_was_control_plane_only(after))

    def test_korea_control_error_does_not_increment(self) -> None:
        meta = _pre_click_incident(
            incident_id="2026-08-13_keysuri_korea_tech_18-30",
            program_id="keysuri_korea_tech",
            scheduled_slot="18:30",
        )
        save_incident(meta)

        def boom(program_id, **kwargs):
            raise TypeError("bad contract")

        execute_approved_recovery(
            "2026-08-13_keysuri_korea_tech_18-30",
            keysuri_runner=boom,
            send_fn=self._send,
        )
        after = load_incident("2026-08-13_keysuri_korea_tech_18-30")
        assert after is not None
        self.assertEqual(after["recovery_failure_signature_count"], 0)
        self.assertIsNone(after["recovery_failure_signature"])
        self.assertNotEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class GuardRepairFailsClosed(_StoreIsolation):
    """Phase 10 — ambiguous history must never clear a guard."""

    def _blocked(self, history):
        return _pre_click_incident(
            status=STATUS_RETRY_BLOCKED_PENDING_PATCH,
            retry_verdict=RETRY_BLOCKED,
            retry_verdict_before_recovery_guard=RETRY_ALLOWED_WITH_WARNING,
            recovery_failure_signature="sig",
            recovery_failure_signature_count=2,
            recovery_failure_history=history,
        )

    def test_history_without_components_is_not_cleared(self) -> None:
        meta = self._blocked([{"signature": "sig"}, {"signature": "sig"}])
        self.assertFalse(recovery_guard_was_control_plane_only(meta))
        save_incident(meta)
        out = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert out is not None
        self.assertEqual(out["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertEqual(out["recovery_failure_signature_count"], 2)

    def test_real_issue_code_history_is_not_cleared(self) -> None:
        comp = {"incident_id": INCIDENT_ID, "structural_failure_class": ISSUE_CODE}
        meta = self._blocked(
            [
                {"signature": "sig", "recovery_run_id": None, "components": comp},
                {"signature": "sig", "recovery_run_id": None, "components": comp},
            ]
        )
        self.assertFalse(recovery_guard_was_control_plane_only(meta))
        save_incident(meta)
        out = clear_control_plane_recovery_guard(INCIDENT_ID)
        assert out is not None
        self.assertTrue(recovery_guard_is_blocked(out))
        self.assertEqual(recovery_effective_retry_verdict(out), RETRY_BLOCKED)

    def test_empty_history_is_not_cleared(self) -> None:
        meta = self._blocked([])
        self.assertFalse(recovery_guard_was_control_plane_only(meta))
