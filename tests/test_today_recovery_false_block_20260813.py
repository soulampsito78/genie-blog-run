"""Regression: 2026-08-13 Today_Geenee recovery false-block.

Production incident: the 06:30 natural run started, reached generation and
parsing, then was blocked by content validation
(``unanchored_briefing_vs_input_news``). Fail-closed correctly suppressed the
owner-review mail. The 06:45 watchdog then created an incident that was
diagnostically blind — ``original_run_id=None``, ``issue_codes=[]``,
``RETRY_STATUS_UNKNOWN`` — because no structured failure event exists for the
Today validation path and the poll endpoint supplies no request evidence. That
UNKNOWN verdict is not actionable, so Admin disabled the recovery control even
though the persisted artifact proves zero delivery side effects.

Fakes: clock, incident store dir. Does not fake: diagnosis logic, retry
actionability contract, repeat-recovery guard, natural identity matching.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest import mock
from zoneinfo import ZoneInfo

from natural_run_incident_store import (
    RETRY_ALLOWED_WITH_WARNING,
    RETRY_BLOCKED,
    RETRY_STATUS_UNKNOWN,
    ROOT_CAUSE_PARTIAL,
    STATUS_REPORTED,
    STATUS_RETRY_BLOCKED_PENDING_PATCH,
    is_retry_actionable,
    load_incident,
    recovery_effective_retry_verdict,
    save_incident,
)
from natural_run_watchdog import (
    diagnose_program_sla,
    failed_natural_artifact_for_slot,
    natural_artifact_side_effects,
    report_incident_once,
)

KST = ZoneInfo("Asia/Seoul")
AFTER_TODAY_SLOT = datetime(2026, 8, 13, 7, 0, tzinfo=KST)

TODAY_INCIDENT_ID = "2026-08-13_today_genie_06-30"
TODAY_RUN_ID = "20260813_063055_today_genie_1f6f0814"
TODAY_ISSUE_CODE = "unanchored_briefing_vs_input_news"

# Production-derived, operational fields only (no recipients / no content).
TODAY_FAILED_NATURAL: Dict[str, Any] = {
    "run_id": TODAY_RUN_ID,
    "mode": "today_genie",
    "created_at": "2026-08-13T06:30:55.396915+09:00",
    "response_status": 500,
    "reason_summary": "validation_block",
    "validation_result": "block",
    "workflow_status": "review_required",
    "email_sent": False,
    "reissue_count": 0,
    "parent_run_id": None,
    "policy": {
        "send_email": False,
        "create_naver_draft": False,
        "require_review": True,
        "suppress_external": True,
    },
    "issue_codes": [TODAY_ISSUE_CODE],
    "content_quality_warnings": [],
    "target_date": "2026-08-13",
    "owner_review_status": "pending_review",
    "customer_delivery_status": "not_sent",
    "admin_reissue": False,
    "execution_class": "natural_scheduled",
    "scheduled_slot": "06:30",
    "kst_schedule_date": "2026-08-13",
    "natural_slot_key": "today_genie|2026-08-13|06:30|natural_scheduled",
    "trigger_source": "scheduled_owner_review",
    "artifact_status": "failed",
    "artifact_storage_backend": "gcs",
    "artifact_storage_durable": True,
}

# The blind incident exactly as the 06:45 watchdog persisted it.
BLIND_INCIDENT: Dict[str, Any] = {
    "incident_id": TODAY_INCIDENT_ID,
    "program_id": "today_genie",
    "program_display": "Today_Geenee",
    "kst_date": "2026-08-13",
    "scheduled_slot": "06:30",
    "status": STATUS_REPORTED,
    "original_run_id": None,
    "issue_codes": [],
    "first_failed_stage": "unknown",
    "error_code": "natural_sla_miss",
    "root_cause_verdict": "ROOT_CAUSE_UNKNOWN",
    "retry_verdict": RETRY_STATUS_UNKNOWN,
    "confirmed_cause": None,
    "outcomes": {"자연실행 artifact": "생성되지 않음"},
    "report_sent_at": "2026-08-13T06:45:07.374115+09:00",
    "report_send_count": 1,
    "recovery_failure_signature": None,
    "recovery_failure_signature_count": 0,
    "recovery_failure_history": [],
    "recovery_run_id": None,
    "recovery_approved_at": None,
    "revision": "genie-blog-run-00292-ncq",
}


def _variant(**overrides: Any) -> Dict[str, Any]:
    art = copy.deepcopy(TODAY_FAILED_NATURAL)
    art.update(overrides)
    return art


def _diagnose(artifacts, program_id: str = "today_genie", now=AFTER_TODAY_SLOT, **kw):
    return diagnose_program_sla(
        program_id=program_id, artifacts=artifacts, now=now, **kw
    )


class _IncidentStoreIsolation(unittest.TestCase):
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

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()


class TodayFailedNaturalArtifactBinding(unittest.TestCase):
    """Phase 3/4/5/11 — the exact production failure becomes actionable."""

    def test_today_20260813_incident_is_enriched_and_actionable(self) -> None:
        inc = _diagnose([TODAY_FAILED_NATURAL])
        self.assertIsNotNone(inc, "SLA miss must still raise an incident")
        assert inc is not None

        # Phase 4 — diagnostic evidence bound from the artifact.
        self.assertEqual(inc["original_run_id"], TODAY_RUN_ID)
        self.assertIn(TODAY_ISSUE_CODE, inc["issue_codes"])
        self.assertEqual(inc["first_failed_stage"], "generation_validation")
        self.assertEqual(inc["error_code"], TODAY_ISSUE_CODE)
        self.assertEqual(inc["root_cause_verdict"], ROOT_CAUSE_PARTIAL)
        self.assertIsNotNone(inc["confirmed_cause"])

        # Phase 11 — artifact existence reported accurately, without ever
        # claiming the natural execution succeeded.
        self.assertNotEqual(inc["outcomes"]["자연실행 artifact"], "생성되지 않음")
        self.assertIn("생성됨", inc["outcomes"]["자연실행 artifact"])
        self.assertEqual(inc["outcomes"]["운영자 검수 메일"], "발송되지 않음")
        self.assertEqual(inc["outcomes"]["고객 메일"], "발송되지 않음")
        self.assertEqual(inc["stage_map"]["검증"], "실패")

        # Phase 5 — actionability derived from real side effects.
        self.assertEqual(inc["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(inc["retry_verdict"]))
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(inc)))

    def test_side_effect_extraction_is_exact(self) -> None:
        side = natural_artifact_side_effects(TODAY_FAILED_NATURAL)
        self.assertEqual(
            side,
            {
                "email_sent": False,
                "customer_delivery_status": "not_sent",
                "customer_send": 0,
                "smtp_attempted": False,
            },
        )

    def test_binding_selects_the_exact_natural_artifact(self) -> None:
        bound = failed_natural_artifact_for_slot(
            [TODAY_FAILED_NATURAL],
            program_id="today_genie",
            kst_date="2026-08-13",
            scheduled_slot="06:30",
        )
        self.assertIsNotNone(bound)
        assert bound is not None
        self.assertEqual(bound["run_id"], TODAY_RUN_ID)


class ConservativeFallbackBehaviour(unittest.TestCase):
    """Phase 6 — unknown stays unknown; delivered stays blocked."""

    def test_case_a_no_artifact_stays_unknown_and_blocked(self) -> None:
        inc = _diagnose([])
        assert inc is not None
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)
        self.assertFalse(is_retry_actionable(inc["retry_verdict"]))
        self.assertIsNone(inc["original_run_id"])
        self.assertEqual(inc["issue_codes"], [])

    def test_case_b_missing_customer_status_stays_unknown(self) -> None:
        art = _variant()
        art.pop("customer_delivery_status")
        inc = _diagnose([art])
        assert inc is not None
        # Diagnosis still binds the run, but actionability stays conservative.
        self.assertEqual(inc["original_run_id"], TODAY_RUN_ID)
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)
        self.assertFalse(is_retry_actionable(inc["retry_verdict"]))

    def test_case_c_customer_delivered_stays_blocked(self) -> None:
        art = _variant(
            customer_delivery_status="smtp_accepted",
            customer_recipient_count=13,
            email_sent=True,
            smtp_attempted=True,
        )
        inc = _diagnose([art])
        assert inc is not None
        self.assertEqual(inc["retry_verdict"], RETRY_BLOCKED)
        self.assertFalse(is_retry_actionable(inc["retry_verdict"]))

    def test_case_c_delivered_status_without_count_still_blocked(self) -> None:
        art = _variant(
            customer_delivery_status="delivered",
            email_sent=True,
            smtp_attempted=True,
        )
        side = natural_artifact_side_effects(art)
        assert side is not None
        self.assertGreater(side["customer_send"], 0)
        inc = _diagnose([art])
        assert inc is not None
        self.assertEqual(inc["retry_verdict"], RETRY_BLOCKED)

    def test_case_d_smtp_ambiguity_stays_unknown(self) -> None:
        # Owner mail was sent but the artifact never records an SMTP outcome
        # and policy did not suppress sending: side effects are unprovable.
        art = _variant(email_sent=True, policy={"send_email": True})
        self.assertIsNone(natural_artifact_side_effects(art))
        inc = _diagnose([art])
        assert inc is not None
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)

    def test_non_terminal_artifact_is_not_bound(self) -> None:
        art = _variant(artifact_status="running", validation_result="pending")
        self.assertIsNone(
            failed_natural_artifact_for_slot(
                [art],
                program_id="today_genie",
                kst_date="2026-08-13",
                scheduled_slot="06:30",
            )
        )


class ExecutionIdentityIsolation(unittest.TestCase):
    """Phase 10 — SAME_DATE_ARTIFACT_FALSE_MATCH / QA_CONSUMED_NATURAL_SLOT."""

    def _assert_never_binds(self, art: Dict[str, Any]) -> None:
        self.assertIsNone(
            failed_natural_artifact_for_slot(
                [art],
                program_id="today_genie",
                kst_date="2026-08-13",
                scheduled_slot="06:30",
            )
        )
        inc = _diagnose([art])
        assert inc is not None
        self.assertIsNone(inc["original_run_id"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)
        self.assertFalse(is_retry_actionable(inc["retry_verdict"]))

    def test_preflight_canary_artifact_never_binds(self) -> None:
        self._assert_never_binds(_variant(execution_class="preflight_canary"))

    def test_reliability_canary_artifact_never_binds(self) -> None:
        self._assert_never_binds(_variant(execution_class="reliability_canary"))

    def test_qa_manual_artifact_never_binds(self) -> None:
        self._assert_never_binds(_variant(execution_class="qa_manual"))

    def test_smoke_artifact_never_binds(self) -> None:
        self._assert_never_binds(_variant(execution_class="smoke"))

    def test_recovery_artifact_never_binds(self) -> None:
        self._assert_never_binds(_variant(execution_class="recovery"))

    def test_missing_execution_class_never_binds(self) -> None:
        art = _variant()
        art.pop("execution_class")
        self._assert_never_binds(art)

    def test_reissue_child_never_binds(self) -> None:
        self._assert_never_binds(_variant(parent_run_id="20260813_000000_today_genie_x"))

    def test_admin_reissue_never_binds(self) -> None:
        self._assert_never_binds(_variant(admin_reissue=True))

    def test_successful_natural_completion_is_not_a_failure_artifact(self) -> None:
        art = _variant(
            email_sent=True,
            validation_result="pass",
            artifact_status="emailed",
            response_status=200,
        )
        self.assertIsNone(
            failed_natural_artifact_for_slot(
                [art],
                program_id="today_genie",
                kst_date="2026-08-13",
                scheduled_slot="06:30",
            )
        )


class CrossDateIsolation(unittest.TestCase):
    """Phase 8 — exact service-date isolation."""

    def test_previous_day_artifact_cannot_enrich_today(self) -> None:
        art = _variant(
            run_id="20260812_063058_today_genie_646239c4",
            kst_schedule_date="2026-08-12",
            target_date="2026-08-12",
        )
        self._assert_isolated(art)

    def test_next_day_artifact_cannot_enrich_today(self) -> None:
        art = _variant(
            run_id="20260814_063050_today_genie_aaaaaaaa",
            kst_schedule_date="2026-08-14",
            target_date="2026-08-14",
        )
        self._assert_isolated(art)

    def test_today_artifact_cannot_enrich_another_date(self) -> None:
        inc = diagnose_program_sla(
            program_id="today_genie",
            artifacts=[TODAY_FAILED_NATURAL],
            now=datetime(2026, 8, 14, 7, 0, tzinfo=KST),
        )
        assert inc is not None
        self.assertEqual(inc["kst_date"], "2026-08-14")
        self.assertIsNone(inc["original_run_id"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)

    def test_mismatched_slot_cannot_bind(self) -> None:
        self._assert_isolated(_variant(scheduled_slot="18:30"))

    def _assert_isolated(self, art: Dict[str, Any]) -> None:
        inc = _diagnose([art])
        assert inc is not None
        self.assertIsNone(inc["original_run_id"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)
        self.assertFalse(is_retry_actionable(inc["retry_verdict"]))


class CrossProgramIsolation(unittest.TestCase):
    """Phase 9 — program identity is mandatory."""

    GLOBAL_FAILED = {
        "run_id": "20260813_123001_keysuri_global_tech_299d057e",
        "mode": "keysuri_global_tech",
        "execution_class": "natural_scheduled",
        "scheduled_slot": "12:30",
        "kst_schedule_date": "2026-08-13",
        "validation_result": "block",
        "artifact_status": "failed",
        "email_sent": False,
        "customer_delivery_status": "not_sent",
        "policy": {"send_email": False},
        "issue_codes": ["keysuri_global_only_code"],
    }

    def test_global_artifact_cannot_enrich_today(self) -> None:
        inc = _diagnose([self.GLOBAL_FAILED])
        assert inc is not None
        self.assertIsNone(inc["original_run_id"])
        self.assertNotIn("keysuri_global_only_code", inc["issue_codes"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)

    def test_korea_artifact_cannot_enrich_today(self) -> None:
        korea = dict(self.GLOBAL_FAILED, mode="keysuri_korea_tech", scheduled_slot="18:30")
        inc = _diagnose([korea])
        assert inc is not None
        self.assertIsNone(inc["original_run_id"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)

    def test_today_artifact_cannot_enrich_global(self) -> None:
        inc = diagnose_program_sla(
            program_id="keysuri_global_tech",
            artifacts=[TODAY_FAILED_NATURAL],
            now=datetime(2026, 8, 13, 13, 0, tzinfo=KST),
        )
        assert inc is not None
        self.assertIsNone(inc["original_run_id"])
        self.assertNotIn(TODAY_ISSUE_CODE, inc["issue_codes"])
        self.assertEqual(inc["retry_verdict"], RETRY_STATUS_UNKNOWN)

    def test_global_failed_artifact_still_binds_for_global(self) -> None:
        inc = diagnose_program_sla(
            program_id="keysuri_global_tech",
            artifacts=[self.GLOBAL_FAILED],
            now=datetime(2026, 8, 13, 13, 0, tzinfo=KST),
        )
        assert inc is not None
        self.assertEqual(
            inc["original_run_id"], "20260813_123001_keysuri_global_tech_299d057e"
        )
        self.assertEqual(inc["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)


class FailureEventPrecedence(unittest.TestCase):
    """Phase 6 — richer structured evidence must win over the fallback."""

    def test_failure_event_stage_is_not_overwritten_by_fallback(self) -> None:
        fe = {
            "program_id": "today_genie",
            "first_failed_stage": "email_delivery",
            "error_code": "smtp_connect_failed",
            "artifact_saved": True,
            "email_sent": False,
        }
        inc = _diagnose([TODAY_FAILED_NATURAL], failure_events=[fe])
        assert inc is not None
        self.assertEqual(inc["first_failed_stage"], "email_delivery")
        self.assertEqual(inc["error_code"], "smtp_connect_failed")
        self.assertNotEqual(inc["first_failed_stage"], "generation_validation")


class RepeatRecoveryGuardPreserved(_IncidentStoreIsolation):
    """Phase 7 — the guard must be untouched by diagnostic reconciliation."""

    def test_blocked_pending_patch_incident_is_not_reconciled(self) -> None:
        blocked = dict(
            BLIND_INCIDENT,
            status=STATUS_RETRY_BLOCKED_PENDING_PATCH,
            recovery_failure_signature="sig-abc",
            recovery_failure_signature_count=2,
            recovery_failure_history=[{"signature": "sig-abc"}],
        )
        save_incident(blocked)
        fresh = _diagnose([TODAY_FAILED_NATURAL])
        assert fresh is not None
        result = report_incident_once(fresh, send_fn=lambda **kw: True)

        self.assertFalse(result["report_sent"])
        self.assertTrue(result["deduped"])
        self.assertFalse(result["reconciled"])

        after = load_incident(TODAY_INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["status"], STATUS_RETRY_BLOCKED_PENDING_PATCH)
        self.assertEqual(after["recovery_failure_signature"], "sig-abc")
        self.assertEqual(after["recovery_failure_signature_count"], 2)
        self.assertEqual(len(after["recovery_failure_history"]), 1)
        # The guard still governs the effective verdict.
        self.assertEqual(recovery_effective_retry_verdict(after), RETRY_BLOCKED)

    def test_reconciliation_never_resets_signature_state(self) -> None:
        seeded = dict(
            BLIND_INCIDENT,
            recovery_failure_signature="sig-xyz",
            recovery_failure_signature_count=1,
            recovery_failure_history=[{"signature": "sig-xyz"}],
        )
        save_incident(seeded)
        fresh = _diagnose([TODAY_FAILED_NATURAL])
        assert fresh is not None
        report_incident_once(fresh, send_fn=lambda **kw: True)

        after = load_incident(TODAY_INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["recovery_failure_signature"], "sig-xyz")
        self.assertEqual(after["recovery_failure_signature_count"], 1)
        self.assertEqual(len(after["recovery_failure_history"]), 1)


class ExistingIncidentReconciliation(_IncidentStoreIsolation):
    """Phase 13 — the already-open blind incident must self-heal, no resend."""

    def test_blind_incident_reconciles_without_resending(self) -> None:
        save_incident(copy.deepcopy(BLIND_INCIDENT))
        before = load_incident(TODAY_INCIDENT_ID)
        assert before is not None
        self.assertIsNone(before["original_run_id"])
        self.assertEqual(before["retry_verdict"], RETRY_STATUS_UNKNOWN)
        self.assertFalse(is_retry_actionable(before["retry_verdict"]))

        sends: list = []

        def _send(**kwargs: Any) -> bool:
            sends.append(kwargs)
            return True

        fresh = _diagnose([TODAY_FAILED_NATURAL])
        assert fresh is not None
        result = report_incident_once(fresh, send_fn=_send)

        # No second report email, ever.
        self.assertEqual(sends, [])
        self.assertFalse(result["report_sent"])
        self.assertTrue(result["deduped"])
        self.assertTrue(result["reconciled"])

        after = load_incident(TODAY_INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["original_run_id"], TODAY_RUN_ID)
        self.assertIn(TODAY_ISSUE_CODE, after["issue_codes"])
        self.assertEqual(after["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)
        self.assertTrue(is_retry_actionable(recovery_effective_retry_verdict(after)))
        self.assertNotEqual(after["outcomes"]["자연실행 artifact"], "생성되지 않음")

        # Report/lease and recovery state preserved exactly.
        self.assertEqual(after["report_sent_at"], BLIND_INCIDENT["report_sent_at"])
        self.assertEqual(after["report_send_count"], 1)
        self.assertEqual(after["status"], STATUS_REPORTED)
        self.assertIsNone(after["recovery_run_id"])
        self.assertIsNone(after["recovery_approved_at"])
        self.assertIsNone(after["recovery_failure_signature"])
        self.assertEqual(after["recovery_failure_signature_count"], 0)

    def test_reconciliation_is_idempotent(self) -> None:
        save_incident(copy.deepcopy(BLIND_INCIDENT))
        fresh = _diagnose([TODAY_FAILED_NATURAL])
        assert fresh is not None
        for _ in range(3):
            result = report_incident_once(fresh, send_fn=lambda **kw: True)
            self.assertFalse(result["report_sent"])
        after = load_incident(TODAY_INCIDENT_ID)
        assert after is not None
        self.assertEqual(after["report_send_count"], 1)
        self.assertEqual(after["retry_verdict"], RETRY_ALLOWED_WITH_WARNING)

    def test_reconciliation_cannot_start_recovery(self) -> None:
        save_incident(copy.deepcopy(BLIND_INCIDENT))
        fresh = _diagnose([TODAY_FAILED_NATURAL])
        assert fresh is not None
        result = report_incident_once(fresh, send_fn=lambda **kw: True)
        self.assertEqual(result["auto_retry"], 0)
        after = load_incident(TODAY_INCIDENT_ID)
        assert after is not None
        self.assertIsNone(after["recovery_run_id"])
        self.assertIsNone(after["recovery_approved_at"])
        self.assertEqual(after.get("recovery_customer_send_count") or 0, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
