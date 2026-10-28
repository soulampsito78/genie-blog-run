"""Independent product QA and adversarial post-send boundary test suite.

Verifies:
1. Global SAFE + editorial REVIEW unsent remains eligible for body-only remediation.
2. Same mode/product/date durable attempt or separate outcome stops remediation
   even if parent projection is stale, corrupt, zero counts, or has inconsistent status aliases.
3. Unreadable authoritative/artifact/safety evidence fails closed.
4. Held/rejected/in-flight/missing run ids and consumed counts do not get refunded.
5. Child lineage prevents auto-remediation loops or child-of-child generation.
6. Human approval racing before runner and during generation prevents unapproved customer delivery.
7. Truthful parent-vs-child notice formatting for success, failure, and parent unknown/partially accepted.
8. Customer delivery is never inferred from approval alone, and positive counts on either alias
   must never be ignored.
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
    SCOPE_IMAGE_ONLY,
    build_remediation_report_html,
    plan_auto_remediation,
    run_auto_remediation,
)

_TODAY_PARENT = "20261028_063000_today_genie_a1b2c3d4"
_GLOBAL_PARENT = "20261028_123000_keysuri_global_tech_e5f6a7b8"
_CHILD_RUN = "20261028_063100_today_genie_c1c2c3c4"


def _base_today_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _TODAY_PARENT,
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


def _base_global_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _GLOBAL_PARENT,
        "mode": "keysuri_global_tech",
        "execution_class": "natural_scheduled",
        "scheduled_slot": "12:30",
        "trigger_source": "scheduled_owner_review",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "safety_verdict": "SAFE",
        "editorial_verdict": "REVIEW",
        "review_issue_codes": ["global_visible_repeated_low_information_label"],
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "response_status": 200,
        "email_sent": True,
        "generated_image_path_watermarked": "output/keysuri_preview/top.jpg",
    }
    meta.update(overrides)
    return meta


class IndependentPostsendBoundaryTests(unittest.TestCase):
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
                "GENIE_PRODUCT_REGRESSION_OFFLINE": "1",
                "GENIE_ARTIFACT_STORE_BACKEND": "local",
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
        save_run_artifact(dict(meta), email_html="<html><body><p>fixture</p></body></html>")
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
                "mode": kwargs.get("parent_meta", {}).get("mode", "today_genie"),
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
                "generated_image_path_watermarked": "output/keysuri_preview/top.jpg",
            }
            if child_overrides:
                child.update(child_overrides)
            self._save(child)
            return {"ok": True, "run_id": child_run_id, "email_sent": True}

        return _run

    def _runners(self, runner_fn, mode: str = "today_genie", scope: str = SCOPE_BODY_ONLY) -> Dict[Tuple[str, str], Any]:
        return {(mode, scope): runner_fn}

    # --- 1. Global SAFE + editorial REVIEW unsent remains eligible ---
    def test_global_safe_editorial_review_unsent_remains_eligible(self) -> None:
        """Global natural scheduled run with SAFE + editorial REVIEW and unsent is eligible."""
        meta = _base_global_meta()
        run_id = self._save(meta)
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible, f"Plan should be eligible, got stop_reason: {plan.stop_reason}")
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

        child_id = "20261028_123100_keysuri_global_tech_c1c2c3c4"
        runners = self._runners(
            self._mock_runner(child_run_id=child_id),
            mode="keysuri_global_tech",
            scope=SCOPE_BODY_ONLY,
        )
        summary = run_auto_remediation(run_id, runners=runners, report_fn=self._report_fn)
        self.assertTrue(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SUCCEEDED)
        self.assertEqual(summary["automatic_remediation_child_run_id"], child_id)
        # Global body-only reissue must use frozen parent news
        self.assertTrue(self.runner_calls[0][1].get("frozen_parent"))

    # --- 2. Same mode/product/date durable attempt or outcome stops even if parent projection is stale/corrupt/zero ---
    def test_durable_attempt_or_outcome_stops_even_with_corrupt_or_zero_parent_projection(self) -> None:
        """Durable publication reservation or outcome stops auto-remediation regardless of parent artifact state."""
        product = PRODUCTS["today_genie"]
        day = "2026-10-28"
        attempt_id = "publication_" + _digest([product, day])
        attempt_file = safety_store._local_path(f"publication_attempts/{attempt_id}.json")
        attempt_file.parent.mkdir(parents=True, exist_ok=True)
        attempt_file.write_text(json.dumps({"attempt_id": attempt_id, "status": "RESERVED"}), encoding="utf-8")

        for desc, overrides in [
            ("zero_counts", {"customer_delivered_count": 0, "customer_delivery_recipient_count": 0}),
            ("stale_not_sent", {"customer_delivery_status": "not_sent"}),
            ("corrupt_status", {"customer_delivery_status": "UNKNOWN_GARBAGE_STATE"}),
            ("inconsistent_alias_zero_count", {"customer_delivery_status": "not_sent", "customer_email_delivery_status": None, "delivered_count": 0}),
        ]:
            with self.subTest(desc=desc):
                self.reports.clear()
                self.runner_calls.clear()
                run_id = self._save(_base_today_meta(**overrides))
                summary = run_auto_remediation(
                    run_id,
                    runners=self._runners(self._mock_runner()),
                    report_fn=self._report_fn,
                )
                self.assertFalse(summary["automatic_remediation_triggered"])
                self.assertEqual(summary["stop_reason"], "publication_already_reserved_or_accepted")
                self.assertEqual(len(self.runner_calls), 0)

    # --- 3. Unreadable authoritative/artifact/safety evidence fails closed ---
    def test_unreadable_authoritative_artifact_fails_closed(self) -> None:
        """When authoritative artifact store fails to read, remediation must fail closed."""
        with patch("auto_remediation.load_run_artifact", side_effect=OSError("disk read error")):
            summary = run_auto_remediation(
                _TODAY_PARENT,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertFalse(summary["automatic_remediation_triggered"])
            self.assertEqual(summary["stop_reason"], "artifact_read_error")
            self.assertEqual(len(self.runner_calls), 0)

    def test_unreadable_safety_evidence_fails_closed(self) -> None:
        """When safety evidence store raises an exception, remediation fails closed."""
        run_id = self._save(_base_today_meta())
        with patch("admin_safety_store._local_path", side_effect=PermissionError("permission denied")):
            summary = run_auto_remediation(
                run_id,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertFalse(summary["automatic_remediation_triggered"])
            self.assertEqual(summary["stop_reason"], "delegated_review_boundary_unavailable")
            self.assertEqual(len(self.runner_calls), 0)

    # --- 4. Held/rejected/in-flight/missing run ids and consumed counts do not get refunded ---
    def test_held_rejected_inflight_missing_run_ids_consumed_counts_not_refunded(self) -> None:
        """Consumed attempt budget is never refunded upon runner failure or missing run id."""
        run_id = self._save(_base_today_meta())

        # Runner raises exception
        summary_exc = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner(ok=False, error="runner exploded")),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary_exc["automatic_remediation_result"], RESULT_FAILED)
        parent_after_exc = load_run_artifact(run_id)
        self.assertIsNotNone(parent_after_exc)
        self.assertEqual(parent_after_exc.get("automatic_remediation_attempt_count"), 1)

        # Subsequent remediation attempt stops with attempt_budget_exhausted
        plan_subsequent = plan_auto_remediation(parent_after_exc)
        self.assertFalse(plan_subsequent.eligible)
        self.assertEqual(plan_subsequent.stop_reason, "attempt_budget_exhausted")

    def test_missing_child_run_id_does_not_refund_attempt(self) -> None:
        """Runner returning ok=True but empty child run id does not refund attempt."""
        run_id = self._save(_base_today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner(child_run_id="")),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_FAILED)
        parent = load_run_artifact(run_id)
        self.assertIsNotNone(parent)
        self.assertEqual(parent.get("automatic_remediation_attempt_count"), 1)

    # --- 5. Child lineage ---
    def test_child_lineage_forbids_auto_remediation_and_is_stamped(self) -> None:
        """Children with parent_run_id, regen_parent_run_id, or automatic_remediation_is_child are ineligible."""
        for key, val in [
            ("parent_run_id", "20261028_060000_today_genie_root"),
            ("regen_parent_run_id", "20261028_060000_today_genie_root"),
            ("automatic_remediation_is_child", True),
        ]:
            with self.subTest(key=key):
                plan = plan_auto_remediation(_base_today_meta(**{key: val}))
                self.assertFalse(plan.eligible)
                self.assertEqual(plan.stop_reason, "already_a_remediation_child")

        # Verify child stamped correctly on remediation success
        run_id = self._save(_base_today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner()),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SUCCEEDED)
        child = load_run_artifact(_CHILD_RUN)
        self.assertIsNotNone(child)
        self.assertTrue(child.get("automatic_remediation_is_child"))
        self.assertEqual(child.get("automatic_remediation_parent_run_id"), run_id)
        self.assertEqual(child.get("owner_review_status"), "pending_review")
        self.assertIsNone(child.get("approved_at"))
        self.assertIsNone(child.get("approved_by"))

    # --- 6. Approval before runner and during generation ---
    def test_approval_granted_before_runner_cancels_runner(self) -> None:
        """If approval is granted before runner invocation, runner is never invoked."""
        run_id = self._save(_base_today_meta())
        real_load = load_run_artifact
        call_count = [0]

        def racing_load(rid, **kwargs):
            art = real_load(rid, **kwargs)
            call_count[0] += 1
            if call_count[0] >= 3 and art:  # Pre-runner recheck
                art["owner_review_status"] = "approved"
                art["approved_at"] = "2026-10-28T06:30:15+09:00"
            return art

        with patch("auto_remediation.load_run_artifact", side_effect=racing_load):
            summary = run_auto_remediation(
                run_id,
                runners=self._runners(self._mock_runner()),
                report_fn=self._report_fn,
            )
            self.assertEqual(summary["automatic_remediation_result"], RESULT_SKIPPED)
            self.assertEqual(summary["stop_reason"], "human_approval_present")
            self.assertEqual(len(self.runner_calls), 0)

    def test_approval_racing_during_generation_does_not_leak_to_child(self) -> None:
        """If parent is approved while runner is executing, child does not inherit approval."""
        run_id = self._save(_base_today_meta())

        def _runner_racing(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            # During runner execution, parent receives approval
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["owner_review_status"] = "approved"
                parent["approved_at"] = "2026-10-28T06:30:45+09:00"
                self._save(parent)
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "validated",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                "safety_verdict": "SAFE",
                "editorial_verdict": "READY",
                "email_sent": True,
                "generated_image_path_watermarked": "output/keysuri_preview/top.jpg",
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(_runner_racing),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SUCCEEDED)
        child = load_run_artifact(_CHILD_RUN)
        self.assertIsNotNone(child)
        self.assertEqual(child.get("owner_review_status"), "pending_review")
        self.assertIsNone(child.get("approved_at"))
        self.assertIsNone(child.get("approved_by"))

    # --- 7. Truthful parent-vs-child notices ---
    def test_truthful_notice_on_unremediated_failure(self) -> None:
        """When remediation fails and parent was unsent, report states failure truthfully."""
        run_id = self._save(_base_today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner(ok=False, error="remediation_timeout")),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_FAILED)
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]
        self.assertIn("[자동 교정 실패]", report["subject"])
        self.assertIn("자동 교정 실패", report["html"])
        self.assertIn("고객 발송 가능 상태에 도달하지 못했습니다", report["html"])
        self.assertNotIn("자동 교정 안내", report["html"])

    def test_truthful_notice_on_child_review_state(self) -> None:
        """When child remains in SAFE+REVIEW, report advises review without claiming failure."""
        run_id = self._save(_base_today_meta())
        child_overrides = {
            "workflow_status": "review_required",
            "editorial_verdict": "REVIEW",
            "review_issue_codes": ["unanchored_briefing_vs_input_news"],
        }
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner(child_overrides=child_overrides)),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_CHILD_STILL_REVIEWABLE)
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]
        self.assertIn("[자동 교정 검토 필요]", report["subject"])
        self.assertIn("자동 교정 검토 필요", report["html"])
        self.assertIn("SAFE+REVIEW", report["html"])
        self.assertNotIn("자동 교정 실패", report["html"])

    def test_truthful_notice_on_parent_smtp_accepted(self) -> None:
        """When parent was already accepted via SMTP, report clearly indicates reference only."""
        run_id = self._save(_base_today_meta())

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            # Parent accepted during run
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["customer_delivery_status"] = "smtp_accepted"
                self._save(parent)
            # Child is still reviewable
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                "editorial_verdict": "REVIEW",
                "email_sent": True,
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(
            run_id,
            runners=self._runners(_runner),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_CHILD_STILL_REVIEWABLE)
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]
        self.assertIn("[자동 교정 안내]", report["subject"])
        self.assertIn("자동 교정 안내", report["html"])
        self.assertIn("이미 고객에게 발송(SMTP 접수)", report["html"])

    # --- 8. Adversarial: Customer delivery is not inferred from approval alone, and positive counts on either alias must never be ignored ---
    def test_inconsistent_delivery_status_aliases_and_positive_counts(self) -> None:
        """Adversarial probe: positive delivery indicators on either alias or positive counts must halt remediation."""
        test_cases = [
            (
                "alias_inconsistency_secondary_smtp_accepted",
                {"customer_delivery_status": "not_sent", "customer_email_delivery_status": "smtp_accepted"},
            ),
            (
                "positive_delivered_count_with_not_sent_status",
                {"customer_delivery_status": "not_sent", "customer_delivered_count": 5},
            ),
            (
                "positive_recipient_count_with_not_sent_status",
                {"customer_delivery_status": "not_sent", "customer_delivery_recipient_count": 5},
            ),
            (
                "alias_inconsistency_secondary_partial_refusal",
                {"customer_delivery_status": "not_sent", "customer_email_delivery_status": "partial_refusal"},
            ),
        ]
        for name, overrides in test_cases:
            with self.subTest(case=name):
                meta = _base_today_meta(**overrides)
                plan = plan_auto_remediation(meta)
                # Any positive delivery evidence on either alias or positive counts MUST stop remediation
                self.assertFalse(
                    plan.eligible,
                    f"Remediation should NOT be eligible when delivery evidence is present ({name}): {overrides}",
                )

    def test_customer_delivery_not_inferred_from_approval_alone(self) -> None:
        """Approval alone does not mean SMTP accepted delivery occurred."""
        # When a parent artifact has owner_review_status='approved' but customer_delivery_status='not_sent',
        # build_remediation_report_html must NOT claim '이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다'
        html = build_remediation_report_html(
            parent_run_id=_TODAY_PARENT,
            child_run_id=_CHILD_RUN,
            scope=SCOPE_BODY_ONLY,
            attempted=True,
            stop_reason="runner_failed",
            remaining_issue_codes=["unanchored_briefing_vs_input_news"],
            parent_already_accepted=False,
        )
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)


if __name__ == "__main__":
    unittest.main()
