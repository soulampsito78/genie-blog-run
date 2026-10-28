"""Comprehensive post-send and post-publication boundary regressions.

Verifies:
- Eligible unsent parent remediation and attempt spending
- Human/delegated approval boundaries
- Stale supplied meta rejected in favor of fresh authoritative store
- Unavailable authoritative read fails closed (no fallback to stale meta)
- Publication reservation without outcome blocks remediation
- Orphan publication outcome blocks remediation
- Child lineage (parent_run_id, regen_parent_run_id, automatic_remediation_is_child)
- Approval racing before stamp
- Delivery claim racing immediately before runner
- Truthful report formatting: SAFE+REVIEW advisory, parent SMTP acceptance distinction
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

from admin_store import load_run_artifact, save_run_artifact
import admin_safety_store as safety_store
from delegated_delivery_safety import PRODUCTS, _digest
from auto_remediation import (
    AUTO_REMEDIATION_FIELDS,
    AUTO_REMEDIATION_MAX_ATTEMPTS,
    RESULT_CHILD_STILL_REVIEWABLE,
    RESULT_FAILED,
    RESULT_SKIPPED,
    RESULT_SUCCEEDED,
    SCOPE_BODY_ONLY,
    build_remediation_report_html,
    plan_auto_remediation,
    run_auto_remediation,
)

_PARENT_RUN = "20261028_063000_today_genie_a1b2c3d4"
_CHILD_RUN = "20261028_063100_today_genie_c1c2c3c4"


def _base_parent_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _PARENT_RUN,
        "mode": "today_genie",
        "execution_class": "natural_scheduled",
        "scheduled_slot": "06:30",
        "trigger_source": "scheduled_owner_review",
        "validation_result": "draft_only",
        "workflow_status": "review_required",
        "artifact_status": "emailed",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "response_status": 200,
        "email_sent": True,
        "issue_codes": ["unanchored_briefing_vs_input_news"],
    }
    meta.update(overrides)
    return meta


class PostsendBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        runs = Path(self._tmp.name) / "admin_runs"
        runs.mkdir(parents=True, exist_ok=True)
        safety = Path(self._tmp.name) / "admin_safety"
        safety.mkdir(parents=True, exist_ok=True)

        patcher = patch("admin_store.admin_runs_dir", return_value=runs)
        patcher.start()
        self.addCleanup(patcher.stop)

        self._env = patch.dict(
            os.environ,
            {
                "GENIE_AUTO_REMEDIATION": "1",
                "GENIE_ADMIN_SAFETY_LOCAL_DIR": str(safety),
            },
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)

        self.reports: List[Dict[str, Any]] = []
        self.runner_calls: List[Tuple[str, Dict[str, Any]]] = []

    def _report_fn(self, html: str, subject: str, **_kw: Any) -> bool:
        self.reports.append({"html": html, "subject": subject})
        return True

    def _save(self, meta: Dict[str, Any]) -> str:
        save_run_artifact(dict(meta), email_html="<html><body><p>content</p></body></html>")
        return str(meta["run_id"])

    def _mock_runner(
        self,
        *,
        child_run_id: str = _CHILD_RUN,
        child_overrides: Optional[Dict[str, Any]] = None,
        ok: bool = True,
        error: str = "",
    ):
        def _run(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            self.runner_calls.append((parent_run_id, kwargs))
            if not ok:
                return {"ok": False, "error": error or "runner_failed"}
            child = {
                "run_id": child_run_id,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "validated",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "safety_verdict": "SAFE",
                "editorial_verdict": "READY",
                "email_sent": True,
            }
            if child_overrides:
                child.update(child_overrides)
            self._save(child)
            return {"ok": True, "run_id": child_run_id, "email_sent": True}

        return _run

    def _runners(self, runner_fn) -> Dict[Tuple[str, str], Any]:
        return {("today_genie", SCOPE_BODY_ONLY): runner_fn}

    # 1. Eligible unsent parent
    def test_positive_eligible_unsent_parent_triggers_and_succeeds(self) -> None:
        run_id = self._save(_base_parent_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertTrue(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SUCCEEDED)
        self.assertEqual(summary["automatic_remediation_child_run_id"], _CHILD_RUN)
        self.assertEqual(summary["automatic_remediation_attempt_count"], 1)
        self.assertEqual(len(self.runner_calls), 1)
        self.assertEqual(self.reports, [])

    # 2. Human approval present
    def test_human_approval_stops_remediation_without_false_reports(self) -> None:
        for key, val in [
            ("owner_review_status", "approved"),
            ("approved_at", "2026-10-28T06:35:00+09:00"),
            ("approved_by", "owner_admin"),
            ("approval_snapshot_id", "aps_20261028_1234567890abcdef"),
        ]:
            with self.subTest(key=key):
                self.reports.clear()
                self.runner_calls.clear()
                run_id = self._save(_base_parent_meta(**{key: val}))
                summary = run_auto_remediation(
                    run_id,
                    runners=self._runners(self._mock_runner()),
                    report_fn=self._report_fn,
                )
                self.assertFalse(summary["automatic_remediation_triggered"])
                self.assertEqual(summary["stop_reason"], "human_approval_present")
                self.assertEqual(len(self.runner_calls), 0)
                self.assertEqual(self.reports, [])

    # 3. Current accepted parent (SMTP accepted)
    def test_current_accepted_parent_stops_remediation(self) -> None:
        for status in ["smtp_accepted", "sent_after_approval", "accepted_all"]:
            with self.subTest(status=status):
                self.reports.clear()
                self.runner_calls.clear()
                run_id = self._save(_base_parent_meta(customer_delivery_status=status))
                summary = run_auto_remediation(
                    run_id,
                    runners=self._runners(self._mock_runner()),
                    report_fn=self._report_fn,
                )
                self.assertFalse(summary["automatic_remediation_triggered"])
                self.assertEqual(summary["stop_reason"], "customer_delivery_already_attempted")
                self.assertEqual(len(self.runner_calls), 0)
                self.assertEqual(self.reports, [])

    # 4. Stale supplied meta overridden by authoritative store
    def test_stale_supplied_meta_stops_on_fresh_authoritative_parent(self) -> None:
        run_id = self._save(_base_parent_meta(customer_delivery_status="smtp_accepted"))
        stale_meta = _base_parent_meta(customer_delivery_status="not_sent")
        summary = run_auto_remediation(
            run_id,
            meta=stale_meta,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertFalse(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["stop_reason"], "customer_delivery_already_attempted")
        self.assertEqual(len(self.runner_calls), 0)

    # 5. Authoritative read error fails closed, never falls back to meta
    def test_authoritative_read_error_fails_closed_without_meta_fallback(self) -> None:
        run_id = "20261028_063000_today_genie_nonexistent"
        stale_meta = _base_parent_meta(run_id=run_id)
        # Artifact not found
        summary = run_auto_remediation(
            run_id,
            meta=stale_meta,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertFalse(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["stop_reason"], "artifact_not_found")
        self.assertEqual(len(self.runner_calls), 0)

        # Artifact read exception
        with patch("auto_remediation.load_run_artifact", side_effect=OSError("disk read failure")):
            summary_err = run_auto_remediation(
                _PARENT_RUN,
                meta=stale_meta,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertFalse(summary_err["automatic_remediation_triggered"])
            self.assertEqual(summary_err["stop_reason"], "artifact_read_error")
            self.assertEqual(len(self.runner_calls), 0)

    # 6. Unreadable safety store fails closed
    def test_unreadable_safety_store_fails_closed(self) -> None:
        run_id = self._save(_base_parent_meta())
        with patch("admin_safety_store._local_path", side_effect=PermissionError("permission denied")):
            summary = run_auto_remediation(
                run_id,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertFalse(summary["automatic_remediation_triggered"])
            self.assertEqual(summary["stop_reason"], "delegated_review_boundary_unavailable")
            self.assertEqual(len(self.runner_calls), 0)

    # 7. Publication reservation without outcome blocks remediation
    def test_publication_reservation_without_outcome_blocks_remediation(self) -> None:
        run_id = self._save(_base_parent_meta())
        product = PRODUCTS["today_genie"]
        day = "2026-10-28"
        attempt_id = "publication_" + _digest([product, day])
        attempt_file = safety_store._local_path(f"publication_attempts/{attempt_id}.json")
        attempt_file.write_text(json.dumps({"attempt_id": attempt_id, "status": "RESERVED"}), encoding="utf-8")

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertFalse(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["stop_reason"], "publication_already_reserved_or_accepted")
        self.assertEqual(len(self.runner_calls), 0)
        self.assertEqual(self.reports, [])

    # 8. Orphan publication outcome blocks remediation
    def test_orphan_publication_outcome_blocks_remediation(self) -> None:
        run_id = self._save(_base_parent_meta())
        product = PRODUCTS["today_genie"]
        day = "2026-10-28"
        attempt_id = "publication_" + _digest([product, day])
        outcome_file = safety_store._local_path(f"publication_outcomes/{attempt_id}.json")
        outcome_file.write_text(
            json.dumps({"attempt_id": attempt_id, "outcome": "UNKNOWN_AFTER_SUBMIT"}),
            encoding="utf-8",
        )

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertFalse(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["stop_reason"], "publication_already_reserved_or_accepted")
        self.assertEqual(len(self.runner_calls), 0)
        self.assertEqual(self.reports, [])

    # 9. Child lineage blocks remediation
    def test_child_lineage_blocks_remediation(self) -> None:
        for key, val in [
            ("parent_run_id", "20261028_060000_today_genie_root"),
            ("regen_parent_run_id", "20261028_060000_today_genie_root"),
            ("automatic_remediation_is_child", True),
        ]:
            with self.subTest(key=key):
                run_id = self._save(_base_parent_meta(**{key: val}))
                summary = run_auto_remediation(
                    run_id,
                    runners=self._runners(self._mock_runner()),
                    report_fn=self._report_fn,
                )
                self.assertFalse(summary["automatic_remediation_triggered"])
                self.assertEqual(summary["stop_reason"], "already_a_remediation_child")
                self.assertEqual(len(self.runner_calls), 0)

    # 10. Approval racing before stamp
    def test_approval_racing_before_stamp_stops_without_spending_attempt(self) -> None:
        run_id = self._save(_base_parent_meta())
        call_count = [0]
        real_load = load_run_artifact

        def racing_load(rid, **kwargs):
            artifact = real_load(rid, **kwargs)
            call_count[0] += 1
            if call_count[0] >= 2 and artifact:  # Second call is the pre-spend recheck
                artifact["owner_review_status"] = "approved"
                artifact["approved_at"] = "2026-10-28T06:30:10+09:00"
            return artifact

        with patch("auto_remediation.load_run_artifact", side_effect=racing_load):
            summary = run_auto_remediation(
                run_id,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertFalse(summary["automatic_remediation_triggered"])
            self.assertEqual(summary["stop_reason"], "human_approval_present")
            self.assertEqual(summary["automatic_remediation_attempt_count"], 0)
            self.assertEqual(len(self.runner_calls), 0)
            self.assertEqual(self.reports, [])

    # 11. Delivery racing immediately before runner
    def test_delivery_racing_immediately_before_runner_stops_remediation(self) -> None:
        run_id = self._save(_base_parent_meta())
        call_count = [0]
        real_load = load_run_artifact

        def racing_load(rid, **kwargs):
            artifact = real_load(rid, **kwargs)
            call_count[0] += 1
            if call_count[0] >= 3 and artifact:  # Third call is the pre-runner recheck
                artifact["customer_delivery_status"] = "smtp_accepted"
            return artifact

        with patch("auto_remediation.load_run_artifact", side_effect=racing_load):
            summary = run_auto_remediation(
                run_id,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertEqual(summary["automatic_remediation_result"], RESULT_SKIPPED)
            self.assertEqual(summary["stop_reason"], "customer_delivery_already_attempted")
            self.assertEqual(len(self.runner_calls), 0)

    # 12. Racing delivery with child review state produces truthful report
    def test_racing_delivery_with_child_review_state_truthful_report(self) -> None:
        run_id = self._save(_base_parent_meta())

        def _review_runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            # During runner execution, parent gets SMTP accepted
            save_run_artifact(
                _base_parent_meta(customer_delivery_status="smtp_accepted"),
                email_html="<html><body>sent</body></html>",
            )
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "safety_verdict": "SAFE",
                "editorial_verdict": "REVIEW",
                "email_sent": True,
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(_review_runner),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_CHILD_STILL_REVIEWABLE)
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]
        self.assertIn("[자동 교정 안내]", report["subject"])
        self.assertIn("자동 교정 안내", report["html"])
        self.assertIn("이미 고객에게 발송(SMTP 접수)", report["html"])
        self.assertNotIn("고객 발송 가능 상태에 도달하지 못했습니다", report["html"])
        self.assertNotIn("자동 교정 실패", report["html"])

    # 13. Preserves SAFE+REVIEW as advisory when parent not accepted
    def test_child_review_state_when_parent_unsent_is_advisory_notice(self) -> None:
        run_id = self._save(_base_parent_meta())

        def _review_runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
                "safety_verdict": "SAFE",
                "editorial_verdict": "REVIEW",
                "email_sent": True,
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(_review_runner),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_CHILD_STILL_REVIEWABLE)
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]
        self.assertIn("[자동 교정 검토 필요]", report["subject"])
        self.assertIn("자동 교정 검토 필요", report["html"])
        self.assertIn("SAFE+REVIEW", report["html"])
        self.assertNotIn("고객 발송 가능 상태에 도달하지 못했습니다", report["html"])
        self.assertNotIn("자동 교정 실패", report["html"])


if __name__ == "__main__":
    unittest.main()
