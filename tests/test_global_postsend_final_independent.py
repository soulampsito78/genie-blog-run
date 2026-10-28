"""Independent designated QA adversarial postsend tests.

Covers uncovered and changed behavior on final frozen implementation bytes:
1. Canonical SMTP attempted booleans (customer_email_smtp_attempted, smtp_attempted, etc.)
2. Independent delivery status aliases (customer_delivery_status, customer_email_delivery_status)
3. Target count alone (customer_delivery_target_count) does not prove attempt/acceptance
4. Canonical unknown count (customer_delivery_unknown_count) boundary check
5. Malformed accepted/refused counts fail closed in plan and are UNKNOWN in reporting
6. Accepted 5 / refused 2 retains partial/unknown precedence over full acceptance
7. Missing/unreadable authoritative parent advises reconciliation, not blind reissue
8. UNKNOWN/refused/corrupt durable outcome racing runner does not become acceptance from object existence
9. Contradictory accepted status and false SMTP boolean must not infer accepted delivery in reporting
10. Approval racing during runner followed by failed/review child: approval alone is not SMTP acceptance,
    and child failure must not assert the approved parent was unready or advise blind reissue
11. Durable store read failure fails closed (delegated_review_boundary_unavailable)
12. Transition read exception fails closed (delegated_review_boundary_unavailable)
13. Consumed attempt budget is never refunded on runner crash/failure
14. Global SAFE + editorial REVIEW unsent positive remains eligible
15. Lineage self-reference (auto_parent_id == run_id) preserves eligibility and is not a child link
16. UI summary-shaped submitted parent + later child with ONLY auto_parent_id:
    latest card selects submitted parent, child is superseded, neither in active current actions
17. Source footer rendering strictly binds canonical URLs and rejects hallucinated/unknown links
18. Generation prompt metric/benchmark rules without company/date hardcoding
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch
from zoneinfo import ZoneInfo

from admin_store import load_run_artifact, save_run_artifact
import admin_safety_store as safety_store
from delegated_delivery_safety import PRODUCTS, _digest
from admin_view_models import (
    is_child_run,
    latest_by_program,
    review_actionability_projection,
)
from auto_remediation import (
    AUTO_REMEDIATION_FIELDS,
    AUTO_REMEDIATION_MAX_ATTEMPTS,
    RESULT_CHILD_STILL_REVIEWABLE,
    RESULT_FAILED,
    RESULT_SKIPPED,
    RESULT_SUCCEEDED,
    SCOPE_BODY_ONLY,
    _durable_delivery_and_approval_boundaries,
    build_remediation_report_html,
    plan_auto_remediation,
    run_auto_remediation,
)
from keysuri_contract_preview_fixture import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    build_contract_preview_fixture_from_generated,
)
from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from keysuri_generation_prompt import build_keysuri_generation_prompt

_TODAY_PARENT = "20261028_063000_today_genie_a1b2c3d4"
_GLOBAL_PARENT = "20261028_123000_keysuri_global_tech_e5f6a7b8"
_CHILD_RUN = "20261028_063100_today_genie_c1c2c3c4"


def _base_today_meta(**overrides: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "run_id": _TODAY_PARENT,
        "mode": "today_genie",
        "program_id": "today_genie",
        "execution_class": "natural_scheduled",
        "scheduled_slot": "06:30",
        "trigger_source": "scheduled_owner_review",
        "created_at": "2026-10-28T06:30:00+09:00",
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
        "program_id": "keysuri_global_tech",
        "execution_class": "natural_scheduled",
        "scheduled_slot": "12:30",
        "trigger_source": "scheduled_owner_review",
        "created_at": "2026-10-28T12:30:00+09:00",
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


class GlobalPostsendFinalIndependentTests(unittest.TestCase):
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

    def _runners(self, runner_fn, mode: str = "today_genie", scope: str = SCOPE_BODY_ONLY) -> Dict[Tuple[str, str], Any]:
        return {(mode, scope): runner_fn}

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

    # 1. Canonical SMTP attempted booleans
    def test_canonical_smtp_attempted_boolean_blocks_auto_remediation(self) -> None:
        """Any canonical SMTP attempted boolean must stop remediation."""
        for flag in (
            "customer_email_smtp_attempted",
            "smtp_attempted",
            "customer_email_delivery_attempted",
            "customer_delivery_attempted",
        ):
            with self.subTest(flag=flag):
                meta = _base_today_meta(**{flag: True})
                plan = plan_auto_remediation(meta)
                self.assertFalse(plan.eligible, f"Expected ineligible with {flag}=True")
                self.assertEqual(plan.stop_reason, "customer_delivery_already_attempted")

    # 2. Independent delivery status aliases
    def test_independent_delivery_status_aliases(self) -> None:
        """Either delivery status alias must independently stop auto-remediation if attempted."""
        for alias in ("customer_delivery_status", "customer_email_delivery_status"):
            for status in ("submitted", "smtp_accepted", "partial_refusal", "refused_all", "outcome_unknown"):
                with self.subTest(alias=alias, status=status):
                    meta = _base_today_meta(**{alias: status})
                    plan = plan_auto_remediation(meta)
                    self.assertFalse(plan.eligible)
                    self.assertEqual(plan.stop_reason, "customer_delivery_already_attempted")

    # 3. Target count alone does not prove attempt or acceptance
    def test_target_count_alone_does_not_prove_attempt_or_acceptance(self) -> None:
        """Target count alone (customer_delivery_target_count) is not proof of attempt or delivery."""
        meta = _base_today_meta(customer_delivery_target_count=100)
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible, f"Target count alone must remain eligible: {plan.stop_reason}")

    # 4. Canonical unknown count coverage
    def test_canonical_unknown_count_coverage(self) -> None:
        """Canonical unknown count (customer_delivery_unknown_count) must be treated as delivery attempt."""
        meta = _base_today_meta(customer_delivery_unknown_count=5)
        plan = plan_auto_remediation(meta)
        self.assertFalse(
            plan.eligible,
            "Positive customer_delivery_unknown_count must stop auto-remediation",
        )
        self.assertEqual(plan.stop_reason, "customer_delivery_already_attempted")

    # 5. Malformed accepted/refused counts fail closed and are UNKNOWN in reporting
    def test_malformed_counts_fail_closed_and_unknown_in_report(self) -> None:
        """Malformed count values fail closed in plan and are treated as UNKNOWN in reporting."""
        meta = _base_today_meta(customer_delivery_accepted_count="not_a_number")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "customer_delivery_already_attempted")

        run_id = self._save(_base_today_meta())

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["customer_delivery_accepted_count"] = "invalid_numeric"
                self._save(parent)
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "editorial_verdict": "REVIEW",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(run_id, runners=self._runners(_runner), report_fn=self._report_fn)
        self.assertEqual(len(self.reports), 1)
        html = self.reports[0]["html"]
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)
        self.assertNotIn("수동 재발행을 사용하세요", html)
        self.assertIn("원본 실행의 고객 발송 상태", html)

    # 6. Accepted 5 / refused 2 retains partial/unknown precedence over full acceptance
    def test_accepted5_refused2_and_unknown_aliases_retain_partial_precedence(self) -> None:
        """Positive accepted count plus positive refused count retains partial/unknown notice, not full acceptance."""
        run_id = self._save(_base_today_meta())

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["customer_delivery_accepted_count"] = 5
                parent["customer_delivery_refused_count"] = 2
                self._save(parent)
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "editorial_verdict": "REVIEW",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(run_id, runners=self._runners(_runner), report_fn=self._report_fn)
        self.assertEqual(len(self.reports), 1)
        html = self.reports[0]["html"]
        self.assertIn("부분 거부", html)
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)

    # 7. Missing/unreadable authoritative parent advises reconciliation, not blind reissue
    def test_final_parent_unreadable_advises_reconciliation_not_blind_reissue(self) -> None:
        """When authoritative parent read fails during child reporting, advise reconciliation and not blind reissue."""
        run_id = self._save(_base_today_meta())
        real_load = load_run_artifact
        load_count = [0]

        def flaky_load(rid: str, **kwargs: Any) -> Any:
            if rid == run_id and load_count[0] >= 3:
                raise OSError("authoritative parent artifact unavailable")
            art = real_load(rid, **kwargs)
            if rid == run_id:
                load_count[0] += 1
            return art

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "editorial_verdict": "REVIEW",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        with patch("auto_remediation.load_run_artifact", side_effect=flaky_load):
            summary = run_auto_remediation(run_id, runners=self._runners(_runner), report_fn=self._report_fn)
            self.assertEqual(len(self.reports), 1)
            html = self.reports[0]["html"]
            self.assertIn("원장 확인 불가", html)
            self.assertNotIn("수동 재발행을 사용하세요", html)

    # 8. UNKNOWN/refused/corrupt durable outcome racing runner does not become acceptance from mere object existence
    def test_racing_orphan_unknown_refused_corrupt_outcome_never_promoted_to_acceptance(self) -> None:
        """Existence of an outcome object with UNKNOWN/refused/corrupt status created during runner must not become full acceptance."""
        product = PRODUCTS["today_genie"]
        day = "2026-10-28"
        att_id = "publication_" + _digest([product, day])
        out_file = safety_store._local_path(f"publication_outcomes/{att_id}.json")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        test_cases = [
            ("unknown", {"attempt_id": att_id, "status": "UNKNOWN", "customer_delivery_status": "outcome_unknown"}, "20261028_063000_today_genie_a1000001", "20261028_063100_today_genie_c1000001"),
            ("refused", {"attempt_id": att_id, "status": "REFUSED_ALL", "customer_delivery_status": "refused_all"}, "20261028_063000_today_genie_a1000002", "20261028_063100_today_genie_c1000002"),
            ("corrupt", "CORRUPT_JSON_{{", "20261028_063000_today_genie_a1000003", "20261028_063100_today_genie_c1000003"),
        ]

        for case_name, outcome_payload, p_run_id, c_run_id in test_cases:
            with self.subTest(case=case_name):
                self.reports.clear()
                if out_file.exists():
                    out_file.unlink()
                run_id = self._save(_base_today_meta(run_id=p_run_id))

                def _runner_racing(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
                    # Create outcome object INSIDE the runner to simulate racing outcome write
                    if isinstance(outcome_payload, dict):
                        out_file.write_text(json.dumps(outcome_payload), encoding="utf-8")
                    else:
                        out_file.write_text(str(outcome_payload), encoding="utf-8")

                    child = {
                        "run_id": c_run_id,
                        "mode": "today_genie",
                        "parent_run_id": parent_run_id,
                        "validation_result": "pass",
                        "workflow_status": "review_required",
                        "editorial_verdict": "REVIEW",
                        "artifact_status": "reissued",
                        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
                    }
                    self._save(child)
                    return {"ok": True, "run_id": c_run_id, "email_sent": True}

                summary = run_auto_remediation(run_id, runners=self._runners(_runner_racing), report_fn=self._report_fn)
                self.assertEqual(len(self.reports), 1)
                html = self.reports[0]["html"]
                # Must NOT assert completed customer delivery
                self.assertNotIn(
                    "이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다",
                    html,
                    f"Mere object existence of {case_name} falsely promoted outcome to full acceptance notice",
                )
                # Must NOT advise blind manual reissue
                self.assertNotIn("수동 재발행을 사용하세요", html)

    # 9. Contradictory accepted status and false SMTP boolean
    def test_contradictory_accepted_status_and_false_smtp_boolean(self) -> None:
        """Contradictory accepted status and false SMTP boolean must not infer accepted delivery in reporting."""
        run_id = self._save(_base_today_meta())

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["customer_delivery_status"] = "smtp_accepted"
                parent["customer_email_smtp_attempted"] = False
                self._save(parent)
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "pass",
                "workflow_status": "review_required",
                "editorial_verdict": "REVIEW",
                "artifact_status": "reissued",
                "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            }
            self._save(child)
            return {"ok": True, "run_id": _CHILD_RUN, "email_sent": True}

        summary = run_auto_remediation(run_id, runners=self._runners(_runner), report_fn=self._report_fn)
        self.assertEqual(len(self.reports), 1)
        html = self.reports[0]["html"]
        self.assertNotIn(
            "이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다",
            html,
            "Contradicted delivery projection with false SMTP boolean must not infer accepted delivery",
        )

    # 10. Approval racing during runner followed by failed/review child
    def test_approval_racing_during_runner_followed_by_failed_child(self) -> None:
        """Approval alone is not SMTP acceptance, and child failure must not assert the approved parent was unready."""
        run_id = self._save(_base_today_meta())

        def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
            parent = load_run_artifact(parent_run_id)
            if parent:
                parent["owner_review_status"] = "approved"
                parent["approved_at"] = "2026-10-28T06:30:45+09:00"
                parent["customer_delivery_status"] = "not_sent"
                self._save(parent)
            child = {
                "run_id": _CHILD_RUN,
                "mode": "today_genie",
                "parent_run_id": parent_run_id,
                "validation_result": "draft_only",
            }
            self._save(child)
            return {"ok": False, "error": "child_failed"}

        summary = run_auto_remediation(run_id, runners=self._runners(_runner), report_fn=self._report_fn)
        self.assertEqual(len(self.reports), 1)
        html = self.reports[0]["html"]
        # Approval alone is not SMTP acceptance
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)
        # Child failure must not claim that the approved parent never became customer-ready
        self.assertNotIn(
            "이 실행은 고객 발송 가능 상태에 도달하지 못했습니다",
            html,
            "Optional child failure must not assert approved parent never became customer-ready",
        )
        # Must not advise blind manual reissue
        self.assertNotIn(
            "수동 재발행을 사용하세요",
            html,
            "Must not advise blind manual reissue when parent is already approved",
        )

    # 11. Durable store read failure fails closed
    def test_durable_store_read_failure_fails_closed(self) -> None:
        """Durable store read failure must fail closed to delegated_review_boundary_unavailable."""
        meta = _base_today_meta()
        with patch("admin_safety_store._local_path", side_effect=RuntimeError("store_disk_fault")):
            boundary = _durable_delivery_and_approval_boundaries(meta)
            self.assertEqual(boundary, "delegated_review_boundary_unavailable")

    # 12. Transition read exception fails closed
    def test_transition_read_exception_fails_closed(self) -> None:
        """Transition journal read exception must fail closed to delegated_review_boundary_unavailable."""
        meta = _base_today_meta()
        rid = meta["run_id"]
        j_key = f"run_delivery_transitions/{hashlib.sha256(rid.encode()).hexdigest()}/000.json"
        j_path = safety_store._local_path(j_key)
        j_path.parent.mkdir(parents=True, exist_ok=True)
        j_path.write_text("{}", encoding="utf-8")

        with patch("admin_store.run_delivery_transition", side_effect=RuntimeError("connection_reset")):
            boundary = _durable_delivery_and_approval_boundaries(meta)
            self.assertEqual(boundary, "delegated_review_boundary_unavailable")

    # 13. Consumed attempt budget is never refunded on runner crash/failure
    def test_held_and_consumed_attempt_count_not_refunded(self) -> None:
        """Attempt budget is consumed prior to runner invocation and never refunded on runner failure."""
        run_id = self._save(_base_today_meta())
        summary = run_auto_remediation(
            run_id,
            runners=self._runners(self._mock_runner(ok=False, error="generation_crash")),
            report_fn=self._report_fn,
        )
        self.assertEqual(summary["automatic_remediation_attempt_count"], AUTO_REMEDIATION_MAX_ATTEMPTS)
        parent = load_run_artifact(run_id)
        self.assertEqual(parent.get("automatic_remediation_attempt_count"), AUTO_REMEDIATION_MAX_ATTEMPTS)

        second_plan = plan_auto_remediation(parent)
        self.assertFalse(second_plan.eligible)
        self.assertEqual(second_plan.stop_reason, "attempt_budget_exhausted")

    # 14. Global SAFE + editorial REVIEW unsent positive remains eligible
    def test_global_safe_review_unsent_positive_remains_eligible(self) -> None:
        """Global natural run with SAFE + editorial REVIEW and unsent is eligible for body-only remediation."""
        meta = _base_global_meta()
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

    # 15. Lineage self-reference (auto_parent_id == run_id) preserves eligibility and is not a child link
    def test_lineage_self_reference_preserves_parent_eligibility_and_review(self) -> None:
        """A parent with automatic_remediation_parent_run_id == run_id is not a child and does not supersede itself."""
        meta = _base_today_meta(
            automatic_remediation_parent_run_id=_TODAY_PARENT,
            validation_result="pass",
        )
        self.assertFalse(is_child_run(meta))
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)

        fixed_now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        projection = review_actionability_projection([meta], now=fixed_now)
        current_ids = [r["run_id"] for r in projection["current"]]
        self.assertIn(_TODAY_PARENT, current_ids)
        superseded_ids = [r["run_id"] for r in projection["superseded"]]
        self.assertNotIn(_TODAY_PARENT, superseded_ids)

        child_meta = _base_today_meta(
            run_id="20261028_063100_today_genie_a1000009",
            automatic_remediation_parent_run_id=_TODAY_PARENT,
            validation_result="pass",
        )
        self.assertTrue(is_child_run(child_meta))
        child_plan = plan_auto_remediation(child_meta)
        self.assertFalse(child_plan.eligible)
        self.assertEqual(child_plan.stop_reason, "already_a_remediation_child")

    # 16. UI summary-shaped submitted parent + later child with ONLY auto_parent_id
    def test_ui_summary_submitted_parent_and_later_child_latest_card(self) -> None:
        """Same-program submitted parent + later child with ONLY automatic_remediation_parent_run_id."""
        parent_run = {
            "run_id": "20261028_063000_today_genie_a1000010",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-28T06:30:00+09:00",
            "customer_delivery_status": "submitted",
            "owner_review_status": "approved",
            "validation_result": "pass",
        }
        child_run = {
            "run_id": "20261028_063100_today_genie_a1000011",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-28T06:31:00+09:00",
            "automatic_remediation_parent_run_id": "20261028_063000_today_genie_a1000010",
            "customer_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
            "validation_result": "pass",
        }
        latest = latest_by_program([child_run, parent_run])
        self.assertEqual(latest["today_genie"]["run_id"], parent_run["run_id"])

        fixed_now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        projection = review_actionability_projection([child_run, parent_run], now=fixed_now)
        current_ids = [r["run_id"] for r in projection["current"]]
        self.assertNotIn(parent_run["run_id"], current_ids)
        self.assertNotIn(child_run["run_id"], current_ids)
        superseded_ids = [r["run_id"] for r in projection["superseded"]]
        self.assertIn(child_run["run_id"], superseded_ids)

    # 17. Source footer rendering strictly binds canonical URLs and rejects hallucinated/unknown links
    def test_source_footer_rendering_rejects_hallucinated_urls_and_unknown_sources(self) -> None:
        """Source footer binds only canonical URLs of selected input sources, rejecting hallucinated URLs in fixture and rendered HTML."""
        source_pack = {
            "generated_at": "2026-10-28T12:00:00+09:00",
            "sources": [
                {
                    "source_id": "trusted_src_1",
                    "source_name": "Trusted Source One",
                    "source_url": "https://trusted.example.com/canonical-news-1",
                    "fetched_at": "2026-10-28T11:30:00+09:00",
                },
                {
                    "source_id": "unselected_present_src_2",
                    "source_name": "Unselected Present Source Two",
                    "source_url": "https://trusted.example.com/canonical-news-2",
                    "fetched_at": "2026-10-28T11:35:00+09:00",
                },
            ],
        }
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "top_5_news": {
                "items": [
                    {
                        "source_id": "trusted_src_1",
                        "headline": "Real Headline",
                        "rank": 1,
                    }
                ]
            },
        }
        generated_briefing = {
            "top_5_news": prompt_input["top_5_news"],
            "closing_sources": {
                "source_list": [
                    {
                        "source_id": "trusted_src_1",
                        "label": "Trusted Source One",
                        "url": "https://model-invented.fake/2026/10/28/hallucinated-slug",
                    },
                    {
                        "source_id": "unselected_present_src_2",
                        "label": "Unselected Source Two",
                        "url": "https://model-invented.fake/unselected-slug",
                    },
                    {
                        "source_id": "unknown_unregistered_3",
                        "label": "Unknown Source",
                        "url": "https://unknown.fake/story",
                    },
                    {
                        "source_id": "",
                        "label": "Empty Source ID",
                        "url": "https://empty-id.fake/story",
                    },
                ]
            },
        }
        fixture = build_contract_preview_fixture_from_generated(
            program_id="keysuri_global_tech",
            prompt_input=prompt_input,
            generated_briefing=generated_briefing,
            source_pack=source_pack,
        )
        sources = fixture.get("source_list") or []
        self.assertEqual(len(sources), 4)
        # 1. Selected trusted source: bound to canonical input URL
        self.assertEqual(sources[0]["source_url"], "https://trusted.example.com/canonical-news-1")
        # 2. Present-but-unselected trusted source: bound to canonical input URL
        self.assertEqual(sources[1]["source_url"], "https://trusted.example.com/canonical-news-2")
        # 3. Unknown source identity: cannot invent canonical URL
        self.assertEqual(sources[2]["source_url"], "")
        # 4. Ambiguous empty source ID: cannot invent canonical URL
        self.assertEqual(sources[3]["source_url"], "")

        # Verify actual customer HTML rendering
        rendered_html = render_keysuri_contract_preview_html(fixture)
        self.assertIn("https://trusted.example.com/canonical-news-1", rendered_html)
        self.assertIn("https://trusted.example.com/canonical-news-2", rendered_html)
        self.assertNotIn("https://model-invented.fake/2026/10/28/hallucinated-slug", rendered_html)
        self.assertNotIn("https://model-invented.fake/unselected-slug", rendered_html)
        self.assertNotIn("https://unknown.fake/story", rendered_html)
        self.assertNotIn("https://empty-id.fake/story", rendered_html)

    # 18. Generation prompt metric/benchmark rules without company/date hardcoding
    def test_generation_prompt_metric_and_benchmark_rules_without_hardcoding(self) -> None:
        """Prompt includes generalized rules for revenue run rate vs ARR and internal benchmarks without hardcoded companies/dates."""
        prompt = build_keysuri_generation_prompt(
            {
                "program_id": "keysuri_global_tech",
                "top_5_news": {"items": []},
                "source_pack": {"sources": []},
            }
        )
        self.assertIn("annualized revenue run rate", prompt)
        self.assertIn("contracted ARR", prompt)
        self.assertIn("internal-benchmark", prompt)
        rule_section = [line for line in prompt.splitlines() if "annualized revenue run rate" in line]
        self.assertTrue(len(rule_section) > 0)
        for line in rule_section:
            self.assertNotIn("20261028", line)


if __name__ == "__main__":
    unittest.main()
