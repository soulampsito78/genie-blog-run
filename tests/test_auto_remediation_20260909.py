"""2026-09-09: a reviewable natural run must remediate itself, exactly once.

Breaking the reissue deadlock made remediation *possible*; it still left the
owner pressing "reissue" for a defect the system had already detected on its
own. These tests pin the bounded automatic path and, just as importantly, every
place it must refuse to act: hard fails, corrupt artifacts, missing evidence,
preflight, QA/manual runs, an exhausted attempt budget, and any child it has
already produced.

Customer send is never performed here and never becomes possible: a corrected
child starts from a clean approval state and still has to pass
``can_approve_customer_send``.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

from admin_store import can_approve_customer_send, load_run_artifact, save_run_artifact
from auto_remediation import (
    AUTO_REMEDIATION_FIELDS,
    AUTO_REMEDIATION_MAX_ATTEMPTS,
    RESULT_CHILD_STILL_REVIEWABLE,
    RESULT_FAILED,
    RESULT_SKIPPED,
    RESULT_SUCCEEDED,
    SCOPE_BODY_AND_IMAGE,
    SCOPE_BODY_ONLY,
    SCOPE_IMAGE_ONLY,
    auto_remediation_owner_notice_html,
    build_remediation_report_html,
    classify_issue_codes,
    plan_auto_remediation,
    run_auto_remediation,
    strip_auto_remediation_notice,
)
from product_surface_contract import PRODUCT_REVIEW_REQUIRED

_TODAY_PARENT = "20260909_063102_today_genie_bc5aae92"
_KOREA_PARENT = "20260907_183002_keysuri_korea_tech_ac93e962"
_CHILD = "20260909_090000_today_genie_11223344"


def today_meta(**overrides: Any) -> Dict[str, Any]:
    """A Today artifact shaped like the production 06:30 natural run."""
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


def korea_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _KOREA_PARENT,
        "mode": "keysuri_korea_tech",
        "program_id": "keysuri_korea_tech",
        "execution_class": "natural_scheduled",
        "trigger_source": "scheduled_service_full_run",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
        "product_surface_issue_codes": ["customer_surface_internal_pipeline_concept"],
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "safety_verdict": "SAFE",
        "editorial_verdict": "READY",
        "email_sent": True,
        "generated_image_path_watermarked": "output/keysuri_preview/top.jpg",
    }
    meta.update(overrides)
    return meta


class _StoreBase(unittest.TestCase):
    """Sandboxed artifact store; no network, no SMTP, no generation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        runs = Path(self._tmp.name) / "admin_runs"
        runs.mkdir(parents=True)
        patcher = patch("admin_store.admin_runs_dir", return_value=runs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._env = patch.dict(os.environ, {"GENIE_AUTO_REMEDIATION": "1"}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.reports: List[Dict[str, Any]] = []
        self.runner_calls: List[Tuple[str, Dict[str, Any]]] = []

    def _report_fn(self, html: str, subject: str, **_kw: Any) -> bool:
        self.reports.append({"html": html, "subject": subject})
        return True

    def _save(self, meta: Dict[str, Any]) -> str:
        save_run_artifact(dict(meta), email_html="<html><body><p>brief</p></body></html>")
        return str(meta["run_id"])

    def _runner(
        self,
        *,
        child_run_id: str = _CHILD,
        child_overrides: Optional[Dict[str, Any]] = None,
        ok: bool = True,
        error: str = "",
    ):
        """A stand-in reissue runner that persists a child instead of generating."""

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
                "response_status": 200,
                "email_sent": True,
            }
            child.update(child_overrides or {})
            save_run_artifact(child, email_html="<html><body><p>child</p></body></html>")
            return {"ok": True, "run_id": child_run_id, "email_sent": True}

        return _run

    def _runners(self, fn, mode: str = "today_genie") -> Dict[Tuple[str, str], Any]:
        return {
            (mode, SCOPE_BODY_ONLY): fn,
            (mode, SCOPE_IMAGE_ONLY): fn,
            (mode, SCOPE_BODY_AND_IMAGE): fn,
        }


class ScopeSelectionTests(unittest.TestCase):
    """§4: the narrowest remediation that covers the observed defect."""

    def test_prose_defect_selects_body_only(self) -> None:
        self.assertEqual(
            classify_issue_codes(["unanchored_briefing_vs_input_news"])[0], SCOPE_BODY_ONLY
        )

    def test_internal_label_leak_selects_body_only(self) -> None:
        self.assertEqual(
            classify_issue_codes(["customer_surface_internal_pipeline_concept"])[0],
            SCOPE_BODY_ONLY,
        )

    def test_image_defect_selects_image_only(self) -> None:
        self.assertEqual(classify_issue_codes(["missing_image_prompt"])[0], SCOPE_IMAGE_ONLY)

    def test_independent_body_and_image_defects_select_full_scope(self) -> None:
        self.assertEqual(
            classify_issue_codes(["weak_opening", "missing_image_prompt"])[0],
            SCOPE_BODY_AND_IMAGE,
        )

    def test_finance_safety_code_is_never_auto_remediable(self) -> None:
        scope, blocking, _ = classify_issue_codes(["top3_not_grounded_in_input_news"])
        self.assertIsNone(scope)
        self.assertIn("top3_not_grounded_in_input_news", blocking)

    def test_terminal_registry_code_is_never_auto_remediable(self) -> None:
        scope, blocking, _ = classify_issue_codes(["keysuri_korea_post_render_qa_blocked"])
        self.assertIsNone(scope)
        self.assertIn("keysuri_korea_post_render_qa_blocked", blocking)

    def test_unknown_code_fails_closed_rather_than_guessing(self) -> None:
        scope, blocking, unclassified = classify_issue_codes(["a_code_added_next_quarter"])
        self.assertIsNone(scope)
        self.assertFalse(blocking)
        self.assertIn("a_code_added_next_quarter", unclassified)

    def test_already_repaired_codes_neither_select_nor_block(self) -> None:
        """A *_repaired code records a fix the pipeline already made.

        Production Korea runs carry several of these, including ones absent from
        the registry; treating them as unknown would refuse remediation on every
        Korea run (observed on 20260907_183002_keysuri_korea_tech_ac93e962).
        """
        scope, blocking, unclassified = classify_issue_codes(
            [
                "keysuri_korean_connector_ellipsis_repaired",
                "keysuri_korean_repeated_token_repaired",
                "customer_surface_internal_pipeline_concept",
            ]
        )
        self.assertEqual(scope, SCOPE_BODY_ONLY)
        self.assertFalse(blocking)
        self.assertFalse(unclassified)

    def test_repaired_codes_alone_select_no_remediation(self) -> None:
        self.assertEqual(
            classify_issue_codes(["keysuri_korean_particle_repaired"]),
            (None, [], []),
        )


class TriggerTests(_StoreBase):
    """§1 / §2 / §9: exactly which runs earn an automatic attempt."""

    def test_pass_natural_run_is_not_remediated(self) -> None:
        meta = today_meta(
            validation_result="pass", workflow_status="validated", issue_codes=[]
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "run_passed")

    def test_review_required_natural_run_is_remediated(self) -> None:
        plan = plan_auto_remediation(today_meta())
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

    def test_product_review_required_natural_run_is_remediated(self) -> None:
        plan = plan_auto_remediation(korea_meta())
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.review_class, "product_review_required")
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

    def test_korea_incident_shape_is_remediable_alongside_repaired_codes(self) -> None:
        """The 2026-09-07 internal-concept-leak run, as production recorded it."""
        plan = plan_auto_remediation(
            korea_meta(
                issue_codes=[
                    "keysuri_korean_connector_ellipsis_repaired",
                    "keysuri_korean_repeated_token_repaired",
                ]
            )
        )
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

    def test_hard_fail_is_never_remediated(self) -> None:
        plan = plan_auto_remediation(
            today_meta(validation_result="block", artifact_status="failed")
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.review_class, "hard_fail")

    def test_corrupt_artifact_is_never_remediated(self) -> None:
        plan = plan_auto_remediation(today_meta(selected_items="corrupt"))
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "parent_artifact_unusable")

    def test_missing_evidence_is_never_remediated(self) -> None:
        """body_only reuses the parent images; claimed-but-gone imagery stops it."""
        plan = plan_auto_remediation(
            today_meta(
                image_source="generated",
                image_generation_status="generated",
                generated_image_paths={},
            )
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "parent_missing_image_evidence")

    def test_preflight_run_is_never_remediated(self) -> None:
        plan = plan_auto_remediation(
            today_meta(execution_class="preflight_canary", trigger_source="natural_run_preflight")
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "not_a_natural_scheduled_run")

    def test_manual_qa_run_is_never_remediated_by_default(self) -> None:
        plan = plan_auto_remediation(
            today_meta(execution_class="manual_qa", trigger_source="admin_manual_run")
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "not_a_natural_scheduled_run")

    def test_manual_run_is_remediated_only_when_explicitly_configured(self) -> None:
        meta = today_meta(execution_class="manual_qa", trigger_source="admin_manual_run")
        with patch.dict(os.environ, {"GENIE_AUTO_REMEDIATION_ALLOW_MANUAL": "1"}, clear=False):
            self.assertTrue(plan_auto_remediation(meta).eligible)

    def test_no_send_verification_run_is_never_remediated(self) -> None:
        plan = plan_auto_remediation(today_meta(verification_mode="no_send_verification"))
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "no_send_verification_run")

    def test_kill_switch_disables_the_mechanism(self) -> None:
        with patch.dict(os.environ, {"GENIE_AUTO_REMEDIATION": "0"}, clear=False):
            plan = plan_auto_remediation(today_meta())
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "auto_remediation_disabled")

    def test_a_remediation_child_is_never_itself_remediated(self) -> None:
        """§3: no child-of-child."""
        plan = plan_auto_remediation(
            today_meta(run_id=_CHILD, parent_run_id=_TODAY_PARENT)
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "already_a_remediation_child")

    def test_spent_attempt_budget_blocks_a_second_attempt(self) -> None:
        plan = plan_auto_remediation(
            today_meta(automatic_remediation_attempt_count=AUTO_REMEDIATION_MAX_ATTEMPTS)
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "attempt_budget_exhausted")


class ExecutionTests(_StoreBase):
    """§1 / §3 / §9: one attempt, recorded, with the owner-review email sent."""

    def test_successful_remediation_creates_child_and_sends_owner_review(self) -> None:
        run_id = self._save(today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._runner()),
            report_fn=self._report_fn,
        )
        self.assertTrue(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["automatic_remediation_scope"], SCOPE_BODY_ONLY)
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SUCCEEDED)
        self.assertEqual(summary["automatic_remediation_child_run_id"], _CHILD)
        self.assertEqual(len(self.runner_calls), 1)
        _parent, kwargs = self.runner_calls[0]
        self.assertTrue(kwargs["send_owner_email"], "owner review must be sent automatically")
        self.assertTrue(load_run_artifact(_CHILD, normalize=False).get("email_sent"))
        # A success needs no incident report.
        self.assertEqual(self.reports, [])

    def test_every_cost_safety_field_is_recorded_on_both_sides(self) -> None:
        run_id = self._save(today_meta())
        run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        parent = load_run_artifact(run_id, normalize=False) or {}
        child = load_run_artifact(_CHILD, normalize=False) or {}
        for field in AUTO_REMEDIATION_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, parent)
                self.assertIn(field, child)
        self.assertEqual(parent["automatic_remediation_attempt_count"], 1)
        self.assertEqual(parent["automatic_remediation_parent_run_id"], run_id)
        self.assertEqual(parent["automatic_remediation_child_run_id"], _CHILD)

    def test_exactly_one_attempt_even_when_invoked_again(self) -> None:
        run_id = self._save(today_meta())
        first = run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        second = run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        self.assertTrue(first["automatic_remediation_triggered"])
        self.assertFalse(second["automatic_remediation_triggered"])
        self.assertEqual(second["stop_reason"], "attempt_budget_exhausted")
        self.assertEqual(len(self.runner_calls), 1, "budget must survive a re-entry")

    def test_failed_remediation_does_not_retry_and_reports(self) -> None:
        run_id = self._save(today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._runner(ok=False, error="text_regeneration_failed")),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_FAILED)
        self.assertEqual(summary["stop_reason"], "text_regeneration_failed")
        self.assertEqual(len(self.runner_calls), 1)
        self.assertEqual(len(self.reports), 1)
        self.assertIn("자동 교정 실패", self.reports[0]["html"])
        self.assertIn("text_regeneration_failed", self.reports[0]["html"])
        # And a second invocation still does not retry.
        run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        self.assertEqual(len(self.runner_calls), 1)

    def test_a_runner_exception_still_spends_the_single_attempt(self) -> None:
        def _boom(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            self.runner_calls.append((parent_run_id, kwargs))
            raise RuntimeError("generation exploded")

        run_id = self._save(today_meta())
        summary = run_auto_remediation(
            run_id, runners=self._runners(_boom), report_fn=self._report_fn
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_FAILED)
        parent = load_run_artifact(run_id, normalize=False) or {}
        self.assertEqual(parent["automatic_remediation_attempt_count"], 1)

    def test_child_still_reviewable_stops_and_reports_remaining_codes(self) -> None:
        run_id = self._save(today_meta())
        runner = self._runner(
            child_overrides={
                "validation_result": "draft_only",
                "workflow_status": "review_required",
                "issue_codes": ["weak_opening"],
            }
        )
        summary = run_auto_remediation(
            run_id, runners=self._runners(runner), report_fn=self._report_fn
        )
        self.assertEqual(
            summary["automatic_remediation_result"], RESULT_CHILD_STILL_REVIEWABLE
        )
        self.assertEqual(summary["child_remaining_issue_codes"], ["weak_opening"])
        self.assertEqual(len(self.reports), 1)
        report = self.reports[0]["html"]
        self.assertIn(run_id, report)
        self.assertIn(_CHILD, report)
        self.assertIn("weak_opening", report)

    def test_scope_without_a_runner_stops_without_spending_the_budget(self) -> None:
        run_id = self._save(today_meta())
        summary = run_auto_remediation(run_id, runners={}, report_fn=self._report_fn)
        self.assertFalse(summary["automatic_remediation_triggered"])
        self.assertEqual(summary["stop_reason"], "scope_not_supported_for_mode")

    def test_ineligible_run_records_nothing_and_calls_no_runner(self) -> None:
        run_id = self._save(
            today_meta(validation_result="pass", workflow_status="validated", issue_codes=[])
        )
        summary = run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        self.assertEqual(summary["automatic_remediation_result"], RESULT_SKIPPED)
        self.assertEqual(self.runner_calls, [])
        parent = load_run_artifact(run_id, normalize=False) or {}
        self.assertNotIn("automatic_remediation_triggered", parent)

    def test_keysuri_body_only_remediation_uses_the_frozen_parent_contract(self) -> None:
        """§4: never recollect news for a wording defect."""
        run_id = self._save(korea_meta())
        runner = self._runner(child_run_id="20260909_100000_keysuri_korea_tech_99887766")
        run_auto_remediation(
            run_id,
            runners=self._runners(runner, mode="keysuri_korea_tech"),
            report_fn=self._report_fn,
        )
        self.assertEqual(len(self.runner_calls), 1)
        _parent, kwargs = self.runner_calls[0]
        self.assertTrue(kwargs.get("frozen_parent"))


class SweepTests(_StoreBase):
    """Remediation runs on its own schedule, bounded, off the natural request.

    A natural run already takes 61-152s against a 300s Cloud Run timeout and a
    300s scheduler deadline; a second full generation inline would exceed that
    on the tail and report a successful natural run as a scheduler failure.
    """

    def test_remediation_is_not_inline_in_the_natural_owner_review_request(self) -> None:
        import internal_jobs

        source = Path(internal_jobs.__file__).read_text(encoding="utf-8")
        create_owner_review = source.split("def create_owner_review_endpoint")[1].split(
            "\n@router.post"
        )[0]
        self.assertNotIn("run_auto_remediation", create_owner_review)
        self.assertNotIn("sweep_auto_remediation", create_owner_review)

    def test_sweep_endpoint_is_registered(self) -> None:
        from main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/internal/jobs/auto-remediate-reviewable", paths)

    def _summary(self, run_id: str, **overrides: Any) -> Dict[str, Any]:
        row = {
            "run_id": run_id,
            "execution_class": "natural_scheduled",
            "parent_run_id": None,
            "automatic_remediation_attempt_count": 0,
        }
        row.update(overrides)
        return row

    def test_sweep_remediates_at_most_one_run_per_invocation(self) -> None:
        from auto_remediation import sweep_auto_remediation

        first = "20260909_063102_today_genie_bc5aae92"
        second = "20260909_073102_today_genie_bc5aae93"
        self._save(today_meta(run_id=first))
        self._save(today_meta(run_id=second))
        rows = [self._summary(first), self._summary(second)]
        result = sweep_auto_remediation(
            now=__import__("datetime").datetime(2026, 9, 9, 12, 0),
            runners=self._runners(self._runner()),
            report_fn=self._report_fn,
            list_fn=lambda **_kw: rows,
        )
        self.assertEqual(len(result["remediated"]), 1)
        self.assertEqual(len(self.runner_calls), 1)

    def test_sweep_ignores_runs_older_than_the_age_window(self) -> None:
        from auto_remediation import sweep_auto_remediation

        stale = "20260101_063102_today_genie_bc5aae92"
        self._save(today_meta(run_id=stale))
        result = sweep_auto_remediation(
            now=__import__("datetime").datetime(2026, 9, 9, 12, 0),
            runners=self._runners(self._runner()),
            report_fn=self._report_fn,
            list_fn=lambda **_kw: [self._summary(stale)],
        )
        self.assertEqual(result["remediated"], [])
        self.assertEqual(self.runner_calls, [])

    def test_sweep_skips_children_and_already_attempted_parents(self) -> None:
        from auto_remediation import sweep_auto_remediation

        child = "20260909_090000_today_genie_11223344"
        done = "20260909_073102_today_genie_bc5aae93"
        rows = [
            self._summary(child, parent_run_id=_TODAY_PARENT),
            self._summary(done, automatic_remediation_attempt_count=1),
            self._summary("20260909_083102_today_genie_bc5aae94", execution_class="manual_qa"),
        ]
        result = sweep_auto_remediation(
            now=__import__("datetime").datetime(2026, 9, 9, 12, 0),
            runners=self._runners(self._runner()),
            report_fn=self._report_fn,
            list_fn=lambda **_kw: rows,
        )
        self.assertEqual(result["shortlisted"], 0)
        self.assertEqual(self.runner_calls, [])

    def test_sweep_is_a_noop_when_the_mechanism_is_disabled(self) -> None:
        from auto_remediation import sweep_auto_remediation

        run_id = self._save(today_meta())
        with patch.dict(os.environ, {"GENIE_AUTO_REMEDIATION": "0"}, clear=False):
            result = sweep_auto_remediation(
                runners=self._runners(self._runner()),
                report_fn=self._report_fn,
                list_fn=lambda **_kw: [self._summary(run_id)],
            )
        self.assertFalse(result["auto_remediation_enabled"])
        self.assertEqual(self.runner_calls, [])

    def test_attempt_counter_survives_the_run_list_projection(self) -> None:
        """The sweep shortlists from summaries; a lost counter would re-attempt."""
        from admin_store import _RUN_LIST_SUMMARY_KEYS

        self.assertIn("automatic_remediation_attempt_count", _RUN_LIST_SUMMARY_KEYS)


class CustomerSafetyTests(_StoreBase):
    """Remediation is owner-review only; nothing here opens a customer path."""

    def test_customer_send_remains_blocked_after_successful_remediation(self) -> None:
        run_id = self._save(today_meta())
        run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        parent = load_run_artifact(run_id) or {}
        self.assertFalse(can_approve_customer_send(parent, has_email_html=True)[0])
        child = load_run_artifact(_CHILD) or {}
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")

    def test_parent_approval_never_carries_to_the_child(self) -> None:
        run_id = self._save(
            today_meta(
                owner_review_status="approved",
                approved_by="owner_admin",
                approved_at="2026-09-09T07:00:00+09:00",
                approval_snapshot_id="aps_parent_should_not_transfer",
            )
        )
        # An approved parent carries its own approval; the child must not.
        runner = self._runner(
            child_overrides={
                "owner_review_status": "approved",
                "approved_by": "owner_admin",
                "approval_snapshot_id": "aps_parent_should_not_transfer",
            }
        )
        run_auto_remediation(
            run_id, runners=self._runners(runner), report_fn=self._report_fn
        )
        child = load_run_artifact(_CHILD, normalize=False) or {}
        self.assertEqual(child.get("owner_review_status"), "pending_review")
        self.assertIsNone(child.get("approved_by"))
        self.assertIsNone(child.get("approved_at"))
        self.assertIsNone(child.get("approval_snapshot_id"))

    def test_child_requires_a_fresh_owner_approval_target(self) -> None:
        run_id = self._save(today_meta())
        run_auto_remediation(
            run_id, runners=self._runners(self._runner()), report_fn=self._report_fn
        )
        child = load_run_artifact(_CHILD) or {}
        self.assertEqual(child.get("owner_review_status"), "pending_review")
        self.assertIsNone(child.get("approval_snapshot_id"))
        # A fresh approval is possible for the child, and is a separate decision.
        ok, reason = can_approve_customer_send(child, has_email_html=True)
        self.assertNotEqual(reason, "already_approved")


class OwnerNoticeTests(unittest.TestCase):
    """§5: what the corrected owner-review email must say."""

    def _notice(self) -> str:
        return auto_remediation_owner_notice_html(
            parent_run_id=_TODAY_PARENT,
            scope=SCOPE_BODY_ONLY,
            original_issue_codes=["unanchored_briefing_vs_input_news"],
            current_result="REVIEW_REQUIRED",
        )

    def test_notice_states_every_required_field(self) -> None:
        html = self._notice()
        self.assertIn("자동 교정본", html)
        self.assertIn(_TODAY_PARENT, html)
        self.assertIn("body_only", html)
        self.assertIn("unanchored_briefing_vs_input_news", html)
        self.assertIn("REVIEW_REQUIRED", html)

    def test_notice_says_approval_does_not_transfer(self) -> None:
        self.assertIn("이전 고객 승인은 이 교정본으로 이전되지 않습니다", self._notice())

    def test_notice_is_stripped_before_any_customer_surface(self) -> None:
        body = f"<html><body>{self._notice()}<p>고객 본문</p></body></html>"
        stripped = strip_auto_remediation_notice(body)
        self.assertNotIn("자동 교정본", stripped)
        self.assertNotIn(_TODAY_PARENT, stripped)
        self.assertIn("고객 본문", stripped)

    def test_today_customer_delivery_strips_the_notice(self) -> None:
        from today_geenee_customer_delivery import prepare_customer_final_html

        body = f"<html><body>{self._notice()}<p>고객 본문</p></body></html>"
        out = prepare_customer_final_html(body)
        self.assertNotIn("자동 교정본", out)
        self.assertIn("고객 본문", out)

    def test_report_names_the_parent_child_scope_and_reason(self) -> None:
        html = build_remediation_report_html(
            parent_run_id=_TODAY_PARENT,
            child_run_id=_CHILD,
            scope=SCOPE_BODY_ONLY,
            attempted=True,
            stop_reason="child_review_required",
            remaining_issue_codes=["weak_opening"],
        )
        self.assertIn("자동 교정 실패", html)
        self.assertIn(_TODAY_PARENT, html)
        self.assertIn(_CHILD, html)
        self.assertIn("weak_opening", html)
        self.assertIn("child_review_required", html)


class FrozenParentContractTests(unittest.TestCase):
    """§4: a wording defect must not recollect or reselect news."""

    def _parent(self) -> Dict[str, Any]:
        item = {
            "rank": 1,
            "news_id": "claim-live-samsung-1",
            "canonical_url": "https://example.invalid/1",
            "headline": "삼성전자, 하반기 공채 일정 공개",
            "korean_title": "삼성전자, 하반기 공채 일정 공개",
            "summary": "삼성전자가 하반기 공채 일정을 공개했습니다.",
            # A slug retired by the 2026-09-07 internal-concept-leak fix.
            "category": "global_to_korea_translation",
        }
        return {
            "run_id": _KOREA_PARENT,
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "selected_items": [dict(item, rank=i, news_id=f"claim-{i}") for i in range(1, 6)],
        }

    def test_retired_category_slug_resolves_when_read_back(self) -> None:
        from keysuri_service_full_run import (
            _canonical_persisted_category,
            _canonicalize_persisted_top5_categories,
        )

        self.assertEqual(
            _canonical_persisted_category("global_to_korea_translation", "keysuri_korea_tech"),
            "korea_domestic_impact",
        )
        items = _canonicalize_persisted_top5_categories(
            [{"category": "global_to_korea_translation"}], "keysuri_korea_tech"
        )
        self.assertEqual(items[0]["category"], "korea_domestic_impact")

    def test_parent_items_carry_a_current_category_forward(self) -> None:
        from keysuri_service_full_run import _parent_selected_items_for_reissue

        items = _parent_selected_items_for_reissue(self._parent(), "keysuri_korea_tech")
        self.assertIsNotNone(items)
        for item in items:
            self.assertNotEqual(item["category"], "global_to_korea_translation")

    def test_frozen_parent_never_collects_live_sources(self) -> None:
        import keysuri_service_full_run as k

        parent = self._parent()

        def _explode(*_a: Any, **_kw: Any):
            raise AssertionError("frozen_parent must not collect live sources")

        with patch.object(k, "run_keysuri_live_source_smoke", _explode):
            _pi, _b, fields, err = k._regenerate_keysuri_text_from_frozen_parent(
                "keysuri_korea_tech", parent, text_caller=lambda *a, **kw: "{}"
            )
        self.assertEqual(fields["reissue_source_contract"], "frozen_parent")
        self.assertFalse(fields["reissue_source_recollected"])
        self.assertFalse(fields["reissue_news_reselected"])
        # No preserved source pack on this fixture, so it fails closed.
        self.assertEqual(err, "text_only_reissue_missing_parent_source_snapshot")

    def test_missing_source_snapshot_fails_closed(self) -> None:
        import keysuri_service_full_run as k

        _pi, _b, _f, err = k._regenerate_keysuri_text_from_frozen_parent(
            "keysuri_korea_tech", {"program_id": "keysuri_korea_tech"}
        )
        self.assertEqual(err, "text_only_reissue_missing_parent_source_snapshot")


class AdminPanelTests(unittest.TestCase):
    """§6: the parent page reports what was done, not "재발행하세요"."""

    def test_successful_remediation_panel_links_to_the_child(self) -> None:
        from admin_routes import _render_auto_remediation_panel

        html = _render_auto_remediation_panel(
            {
                "automatic_remediation_triggered": True,
                "automatic_remediation_result": RESULT_SUCCEEDED,
                "automatic_remediation_scope": SCOPE_BODY_ONLY,
                "automatic_remediation_child_run_id": _CHILD,
                "automatic_remediation_original_issue_codes": ["weak_opening"],
            }
        )
        self.assertIn("자동 교정을 수행했습니다.", html)
        self.assertIn("새 교정본 열기", html)
        self.assertIn(f"/admin/runs/{_CHILD}", html)

    def test_failed_remediation_panel_states_the_exact_reason(self) -> None:
        from admin_routes import _render_auto_remediation_panel

        html = _render_auto_remediation_panel(
            {
                "automatic_remediation_triggered": True,
                "automatic_remediation_result": RESULT_FAILED,
                "automatic_remediation_stop_reason": "text_regeneration_failed",
                "automatic_remediation_scope": SCOPE_BODY_ONLY,
            }
        )
        self.assertIn("자동 교정 실패", html)
        self.assertIn("text_regeneration_failed", html)
        self.assertIn("자동 재시도는 하지 않습니다", html)

    def test_panel_is_absent_when_nothing_was_attempted(self) -> None:
        from admin_routes import _render_auto_remediation_panel

        self.assertEqual(_render_auto_remediation_panel({"mode": "today_genie"}), "")


if __name__ == "__main__":
    unittest.main()
