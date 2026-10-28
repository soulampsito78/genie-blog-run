"""Tests for operations summary selection, review actionability, footer binding, and prompt rules.

Covers:
1. Summary-shaped case with submitted parent and child automatic_remediation_parent_run_id:
   latest_by_program points to sent parent; current review queue contains neither member.
2. Next day unsent natural run is not masked by previous day's submitted parent.
3. Runner race report test with malformed customer_delivery_accepted_count:
   notice treats outcome as unknown/reconciliation, never asserts completed SMTP acceptance.
4. Positive accepted count + refused count (accepted 5, refused 2) retains partial/unknown notice.
5. Authoritative parent read error fails into reconciliation notice, not blind reissue advice.
6. Footer source URLs strictly bound to selected source input; model-invented URLs ignored.
7. Prompt source faithfulness rules for annualized revenue run rate vs ARR and internal benchmarks.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch
from zoneinfo import ZoneInfo

from admin_view_models import latest_by_program, review_actionability_projection, is_child_run
from auto_remediation import (
    RESULT_CHILD_STILL_REVIEWABLE,
    _evaluate_parent_for_remediation_report,
    build_remediation_report_html,
    run_auto_remediation,
)
from keysuri_contract_preview_fixture import build_contract_preview_fixture_from_generated
from keysuri_generation_prompt import build_keysuri_generation_prompt


class OperationsSelectionAndFooterSourceTests(unittest.TestCase):
    def test_summary_shaped_parent_submitted_and_child_with_auto_parent_id(self) -> None:
        """A submitted natural parent is not masked on latest_by_program by a newer remediation child.

        Current customer-send/review actions contain neither already-published member.
        """
        parent_run = {
            "run_id": "20261028_063000_today_genie_parent11",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-28T06:30:00+09:00",
            "customer_delivery_status": "smtp_accepted",
            "customer_delivery_accepted_count": 10,
            "smtp_accepted_recipient_count": 10,
            "customer_delivery_refused_count": 0,
            "owner_review_status": "approved",
            "validation_result": "pass",
        }
        child_run = {
            "run_id": "20261028_063100_today_genie_child222",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-28T06:31:00+09:00",
            "automatic_remediation_parent_run_id": "20261028_063000_today_genie_parent11",
            "customer_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
            "validation_result": "pass",
        }

        self.assertFalse(is_child_run(parent_run))
        self.assertTrue(is_child_run(child_run))

        runs = [child_run, parent_run]  # child is newer by timestamp
        latest = latest_by_program(runs)
        self.assertEqual(latest["today_genie"]["run_id"], parent_run["run_id"])
        self.assertEqual(latest["today_genie"]["customer_delivery_status"], "smtp_accepted")

        # In review actionability, current send/review actions contain neither member
        fixed_now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        projection = review_actionability_projection(runs, now=fixed_now)
        current_ids = [r["run_id"] for r in projection["current"]]
        self.assertNotIn(parent_run["run_id"], current_ids)
        self.assertNotIn(child_run["run_id"], current_ids)

        # The child is discoverable under superseded reference history
        superseded_ids = [r["run_id"] for r in projection["superseded"]]
        self.assertIn(child_run["run_id"], superseded_ids)

    def test_next_day_unsent_slot_not_masked_by_yesterday_accepted_parent(self) -> None:
        """Yesterday's accepted run never carries over onto today's unsent natural slot."""
        yesterday_parent = {
            "run_id": "20261027_063000_today_genie_yday11",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-27T06:30:00+09:00",
            "customer_delivery_status": "smtp_accepted",
            "customer_delivery_accepted_count": 10,
            "owner_review_status": "approved",
            "validation_result": "pass",
        }
        today_natural = {
            "run_id": "20261028_063000_today_genie_today11",
            "program_id": "today_genie",
            "mode": "today_genie",
            "created_at": "2026-10-28T06:30:00+09:00",
            "customer_delivery_status": "not_sent",
            "owner_review_status": "pending_review",
            "validation_result": "pass",
        }

        runs = [today_natural, yesterday_parent]
        latest = latest_by_program(runs)
        self.assertEqual(latest["today_genie"]["run_id"], today_natural["run_id"])
        self.assertEqual(latest["today_genie"]["customer_delivery_status"], "not_sent")

    def test_runner_race_with_malformed_accepted_count_retains_unknown_notice(self) -> None:
        """Malformed accepted count is UNKNOWN, never asserted as completed customer SMTP acceptance."""
        html = build_remediation_report_html(
            parent_run_id="20261028_063000_today_genie_race01",
            child_run_id="20261028_063100_today_genie_race02",
            scope="body_only",
            attempted=True,
            stop_reason="child_still_reviewable",
            remaining_issue_codes=["issue_1"],
            parent_partial_or_unknown=True,
            parent_already_accepted=False,
        )
        self.assertIn("자동 교정 안내", html)
        self.assertIn("원본 실행의 고객 발송 상태", html)
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)
        self.assertNotIn("수동 재발행을 사용하세요", html)

    def test_accepted_and_refused_counts_retains_partial_notice(self) -> None:
        """Accepted 5 and refused 2 must show partial notice, never full acceptance."""
        html = build_remediation_report_html(
            parent_run_id="20261028_063000_today_genie_part01",
            child_run_id="20261028_063100_today_genie_part02",
            scope="body_only",
            attempted=True,
            stop_reason="child_still_reviewable",
            remaining_issue_codes=["issue_1"],
            parent_partial_or_unknown=True,
            parent_already_accepted=True,  # both flags true
        )
        self.assertIn("자동 교정 안내", html)
        self.assertIn("부분 거부", html)
        self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)

    def test_authoritative_read_error_reconciliation_notice(self) -> None:
        """Unreadable final parent evidence advises reconciliation and does not give blind reissue advice."""
        html = build_remediation_report_html(
            parent_run_id="20261028_063000_today_genie_err01",
            child_run_id=None,
            scope="body_only",
            attempted=True,
            stop_reason="authoritative_verification_unavailable_reconciliation_required",
            remaining_issue_codes=["unanchored_briefing"],
            parent_partial_or_unknown=True,
            parent_already_accepted=False,
        )
        self.assertIn("자동 교정 안내", html)
        self.assertIn("원장 확인 불가", html)
        self.assertNotIn("수동 재발행을 사용하세요", html)

    def test_footer_source_binding_rejects_model_invented_url(self) -> None:
        """Footer source URLs strictly bind to selected source input; model-invented URLs are ignored."""
        source_pack = {
            "generated_at": "2026-10-28T12:00:00+09:00",
            "sources": [
                {
                    "source_id": "techcrunch_01",
                    "source_name": "TechCrunch",
                    "source_url": "https://techcrunch.com/canonical/article-1",
                    "fetched_at": "2026-10-28T11:30:00+09:00",
                }
            ],
        }
        prompt_input = {
            "top_5_news": {
                "items": [
                    {
                        "source_id": "techcrunch_01",
                        "headline": "Real Headline",
                        "rank": 1,
                    }
                ]
            }
        }
        # Model generated briefing with invented URL and hallucinated second source
        generated_briefing = {
            "top_5_news": prompt_input["top_5_news"],
            "closing_sources": {
                "source_list": [
                    {
                        "source_id": "techcrunch_01",
                        "label": "TechCrunch",
                        "url": "https://hallucinated-slug.com/fake-story",  # Should be overridden by canonical!
                    },
                    {
                        "source_id": "unknown_source_99",
                        "label": "Made Up Source",
                        "url": "https://madeup.com/story-99",  # Should be blanked because source_id is not in source_pack!
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
        self.assertEqual(len(sources), 2)
        # 1. Trusted source bound to canonical input URL
        self.assertEqual(sources[0]["source_url"], "https://techcrunch.com/canonical/article-1")
        # 2. Unknown source identity cannot invent a canonical URL
        self.assertEqual(sources[1]["source_url"], "")

    def test_prompt_faithfulness_metric_and_benchmark_rules(self) -> None:
        """Prompt instructs model on revenue run rate vs ARR and internal benchmark scope."""
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

    def _run_with_isolated_storage(self, run_fn: Any) -> Any:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "admin_runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            safety_dir = Path(tmpdir) / "admin_safety"
            safety_dir.mkdir(parents=True, exist_ok=True)
            with patch("admin_store.admin_runs_dir", return_value=runs_dir), \
                 patch.dict(os.environ, {
                     "GENIE_AUTO_REMEDIATION": "1",
                     "GENIE_PRODUCT_REGRESSION_OFFLINE": "1",
                     "GENIE_ARTIFACT_STORE_BACKEND": "local",
                     "GENIE_ADMIN_SAFETY_LOCAL_DIR": str(safety_dir),
                 }):
                return run_fn(runs_dir, safety_dir)

    def test_canonical_producer_outcome_accepted_with_bound_attempt(self) -> None:
        """Canonical complete_publication_attempt with PROVIDER_ACCEPTED and bound attempt reports accepted parent."""
        from admin_store import save_run_artifact
        import admin_safety_store as s_store
        from delegated_delivery_safety import complete_publication_attempt, PRODUCTS, _digest

        def _test(_runs_dir: Path, _safety_dir: Path):
            p_run_id = "20261028_063000_today_genie_a1b2c3d1"
            c_run_id = "20261028_063100_today_genie_c1c2c3c1"
            parent = {
                "run_id": p_run_id,
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
            save_run_artifact(parent, email_html="<html><body><p>parent</p></body></html>")

            product = PRODUCTS["today_genie"]
            day = "2026-10-28"
            att_id = "publication_" + _digest([product, day])

            reports: List[Dict[str, Any]] = []
            def _report_fn(html: str, subject: str, **_kw: Any) -> bool:
                reports.append({"html": html, "subject": subject})
                return True

            def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
                attempt_record = {
                    "schema": "delegated_delivery_safety.v1",
                    "attempt_id": att_id,
                    "run_id": parent_run_id,
                    "product_code": product,
                    "publication_date": day,
                    "candidate_sha256": "0" * 64,
                    "review_id": "review_test_001",
                    "recipient_plan_id": "plan_test_001",
                    "recipient_plan_sha256": "1" * 64,
                    "approval_source": "HUMAN_OWNER",
                    "attempted_at": "2026-10-28T06:30:15+09:00",
                    "status": "RESERVED_OUTCOME_UNKNOWN",
                    "provider_exactly_once": False,
                }
                s_store._write_json(f"publication_attempts/{att_id}.json", attempt_record)

                complete_publication_attempt(
                    att_id,
                    outcome="PROVIDER_ACCEPTED",
                    evidence={
                        "approval_source": "HUMAN_OWNER",
                        "delivery_command_id": "cmd_test_001",
                        "smtp_result": "ACCEPTED_ALL",
                        "actual_receipt_verified": False,
                    },
                )

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
                save_run_artifact(child, email_html="<html><body><p>child</p></body></html>")
                return {"ok": True, "run_id": c_run_id, "email_sent": True}

            summary = run_auto_remediation(
                p_run_id,
                runners={("today_genie", "body_only"): _runner},
                report_fn=_report_fn,
            )

            (accepted, partial, approved, reason) = _evaluate_parent_for_remediation_report(
                p_run_id, "child_review_required"
            )
            self.assertTrue(accepted, "Bound PROVIDER_ACCEPTED outcome must be classified as parent_already_accepted")
            self.assertFalse(partial, "Bound PROVIDER_ACCEPTED outcome must not be classified as partial/unknown")

            self.assertEqual(len(reports), 1)
            html = reports[0]["html"]
            subject = reports[0]["subject"]
            self.assertIn("[자동 교정 안내]", subject)
            self.assertIn("원본 실행은 이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)
            self.assertNotIn("수동 재발행을 사용하세요", html)

        self._run_with_isolated_storage(_test)

    def test_unbound_outcome_missing_attempt_record_requires_reconciliation(self) -> None:
        """Outcome without corresponding publication_attempts record must require reconciliation."""
        from admin_store import save_run_artifact
        import admin_safety_store as s_store
        from delegated_delivery_safety import PRODUCTS, _digest

        def _test(_runs_dir: Path, _safety_dir: Path):
            p_run_id = "20261028_063000_today_genie_a1b2c3d2"
            c_run_id = "20261028_063100_today_genie_c1c2c3c2"
            parent = {
                "run_id": p_run_id,
                "mode": "today_genie",
                "program_id": "today_genie",
                "execution_class": "natural_scheduled",
                "scheduled_slot": "06:30",
                "trigger_source": "scheduled_owner_review",
                "created_at": "2026-10-28T06:30:00+09:00",
                "validation_result": "draft_only",
                "workflow_status": "review_required",
                "customer_delivery_status": "not_sent",
                "email_sent": True,
                "issue_codes": ["unanchored_briefing_vs_input_news"],
            }
            save_run_artifact(parent, email_html="<html><body><p>parent</p></body></html>")

            product = PRODUCTS["today_genie"]
            day = "2026-10-28"
            att_id = "publication_" + _digest([product, day])

            reports: List[Dict[str, Any]] = []
            def _report_fn(html: str, subject: str, **_kw: Any) -> bool:
                reports.append({"html": html, "subject": subject})
                return True

            def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
                outcome_payload = {
                    "attempt_id": att_id,
                    "outcome": "PROVIDER_ACCEPTED",
                    "provider_exactly_once": False,
                    "actual_receipt_verified": False,
                    "evidence": {"smtp_result": "ACCEPTED_ALL"},
                }
                s_store._write_json(f"publication_outcomes/{att_id}.json", outcome_payload)

                child = {
                    "run_id": c_run_id,
                    "mode": "today_genie",
                    "parent_run_id": parent_run_id,
                    "validation_result": "pass",
                    "workflow_status": "review_required",
                    "editorial_verdict": "REVIEW",
                }
                save_run_artifact(child, email_html="<html><body><p>child</p></body></html>")
                return {"ok": True, "run_id": c_run_id, "email_sent": True}

            summary = run_auto_remediation(
                p_run_id,
                runners={("today_genie", "body_only"): _runner},
                report_fn=_report_fn,
            )

            (accepted, partial, approved, reason) = _evaluate_parent_for_remediation_report(
                p_run_id, "child_review_required"
            )
            self.assertFalse(accepted, "Unbound outcome without attempt record must not be accepted")
            self.assertTrue(partial, "Unbound outcome without attempt record must require reconciliation")

            self.assertEqual(len(reports), 1)
            html = reports[0]["html"]
            self.assertIn("원본 실행의 고객 발송 상태", html)
            self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)

        self._run_with_isolated_storage(_test)

    def test_mismatched_run_binding_in_same_slot_requires_reconciliation(self) -> None:
        """Outcome bound to a different run in the same publication slot requires reconciliation, not parent acceptance."""
        from admin_store import save_run_artifact
        import admin_safety_store as s_store
        from delegated_delivery_safety import complete_publication_attempt, PRODUCTS, _digest

        def _test(_runs_dir: Path, _safety_dir: Path):
            p_run_id = "20261028_063000_today_genie_a1b2c3d3"
            other_run_id = "20261028_063000_today_genie_99998888"
            c_run_id = "20261028_063100_today_genie_c1c2c3c3"
            parent = {
                "run_id": p_run_id,
                "mode": "today_genie",
                "program_id": "today_genie",
                "execution_class": "natural_scheduled",
                "scheduled_slot": "06:30",
                "trigger_source": "scheduled_owner_review",
                "created_at": "2026-10-28T06:30:00+09:00",
                "validation_result": "draft_only",
                "workflow_status": "review_required",
                "customer_delivery_status": "not_sent",
                "email_sent": True,
                "issue_codes": ["unanchored_briefing_vs_input_news"],
            }
            save_run_artifact(parent, email_html="<html><body><p>parent</p></body></html>")

            product = PRODUCTS["today_genie"]
            day = "2026-10-28"
            att_id = "publication_" + _digest([product, day])

            reports: List[Dict[str, Any]] = []
            def _report_fn(html: str, subject: str, **_kw: Any) -> bool:
                reports.append({"html": html, "subject": subject})
                return True

            def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
                attempt_record = {
                    "schema": "delegated_delivery_safety.v1",
                    "attempt_id": att_id,
                    "run_id": other_run_id,
                    "product_code": product,
                    "publication_date": day,
                    "candidate_sha256": "0" * 64,
                    "review_id": "review_other_001",
                    "recipient_plan_id": "plan_other_001",
                    "recipient_plan_sha256": "1" * 64,
                    "approval_source": "HUMAN_OWNER",
                    "attempted_at": "2026-10-28T06:30:15+09:00",
                    "status": "RESERVED_OUTCOME_UNKNOWN",
                    "provider_exactly_once": False,
                }
                s_store._write_json(f"publication_attempts/{att_id}.json", attempt_record)

                complete_publication_attempt(
                    att_id,
                    outcome="PROVIDER_ACCEPTED",
                    evidence={"approval_source": "HUMAN_OWNER", "delivery_command_id": "cmd_002", "smtp_result": "ACCEPTED_ALL", "actual_receipt_verified": False},
                )

                child = {
                    "run_id": c_run_id,
                    "mode": "today_genie",
                    "parent_run_id": parent_run_id,
                    "validation_result": "pass",
                    "workflow_status": "review_required",
                    "editorial_verdict": "REVIEW",
                }
                save_run_artifact(child, email_html="<html><body><p>child</p></body></html>")
                return {"ok": True, "run_id": c_run_id, "email_sent": True}

            summary = run_auto_remediation(
                p_run_id,
                runners={("today_genie", "body_only"): _runner},
                report_fn=_report_fn,
            )

            (accepted, partial, approved, reason) = _evaluate_parent_for_remediation_report(
                p_run_id, "child_review_required"
            )
            self.assertFalse(accepted, "Mismatched run_id in attempt must not be accepted for this parent")
            self.assertTrue(partial, "Mismatched run_id in attempt must require reconciliation")

            self.assertEqual(len(reports), 1)
            html = reports[0]["html"]
            self.assertIn("원본 실행의 고객 발송 상태", html)
            self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)

        self._run_with_isolated_storage(_test)

    def test_outcome_conflict_unknown_after_submit_with_accepted_status(self) -> None:
        """Outcome of UNKNOWN_AFTER_SUBMIT cannot be overridden by customer_delivery_status=smtp_accepted."""
        from admin_store import save_run_artifact
        import admin_safety_store as s_store
        from delegated_delivery_safety import PRODUCTS, _digest

        def _test(_runs_dir: Path, _safety_dir: Path):
            p_run_id = "20261028_063000_today_genie_a1b2c3d4"
            c_run_id = "20261028_063100_today_genie_c1c2c3c4"
            parent = {
                "run_id": p_run_id,
                "mode": "today_genie",
                "program_id": "today_genie",
                "execution_class": "natural_scheduled",
                "scheduled_slot": "06:30",
                "trigger_source": "scheduled_owner_review",
                "created_at": "2026-10-28T06:30:00+09:00",
                "validation_result": "draft_only",
                "workflow_status": "review_required",
                "customer_delivery_status": "not_sent",
                "email_sent": True,
                "issue_codes": ["unanchored_briefing_vs_input_news"],
            }
            save_run_artifact(parent, email_html="<html><body><p>parent</p></body></html>")

            product = PRODUCTS["today_genie"]
            day = "2026-10-28"
            att_id = "publication_" + _digest([product, day])

            reports: List[Dict[str, Any]] = []
            def _report_fn(html: str, subject: str, **_kw: Any) -> bool:
                reports.append({"html": html, "subject": subject})
                return True

            def _runner(parent_run_id: str, **kwargs: Any) -> Dict[str, Any]:
                attempt_record = {
                    "schema": "delegated_delivery_safety.v1",
                    "attempt_id": att_id,
                    "run_id": parent_run_id,
                    "product_code": product,
                    "publication_date": day,
                    "candidate_sha256": "0" * 64,
                    "review_id": "review_conf_001",
                    "recipient_plan_id": "plan_conf_001",
                    "recipient_plan_sha256": "1" * 64,
                    "approval_source": "HUMAN_OWNER",
                    "attempted_at": "2026-10-28T06:30:15+09:00",
                    "status": "RESERVED_OUTCOME_UNKNOWN",
                    "provider_exactly_once": False,
                }
                s_store._write_json(f"publication_attempts/{att_id}.json", attempt_record)

                outcome_payload = {
                    "attempt_id": att_id,
                    "outcome": "UNKNOWN_AFTER_SUBMIT",
                    "customer_delivery_status": "smtp_accepted",
                    "provider_exactly_once": False,
                    "actual_receipt_verified": False,
                    "evidence": {"smtp_result": "ACCEPTED_ALL"},
                }
                s_store._write_json(f"publication_outcomes/{att_id}.json", outcome_payload)

                child = {
                    "run_id": c_run_id,
                    "mode": "today_genie",
                    "parent_run_id": parent_run_id,
                    "validation_result": "pass",
                    "workflow_status": "review_required",
                    "editorial_verdict": "REVIEW",
                }
                save_run_artifact(child, email_html="<html><body><p>child</p></body></html>")
                return {"ok": True, "run_id": c_run_id, "email_sent": True}

            summary = run_auto_remediation(
                p_run_id,
                runners={("today_genie", "body_only"): _runner},
                report_fn=_report_fn,
            )

            (accepted, partial, approved, reason) = _evaluate_parent_for_remediation_report(
                p_run_id, "child_review_required"
            )
            self.assertFalse(accepted, "UNKNOWN_AFTER_SUBMIT must never be classified as accepted")
            self.assertTrue(partial, "UNKNOWN_AFTER_SUBMIT must require reconciliation")

            self.assertEqual(len(reports), 1)
            html = reports[0]["html"]
            self.assertIn("원본 실행의 고객 발송 상태", html)
            self.assertNotIn("이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다", html)

        self._run_with_isolated_storage(_test)


if __name__ == "__main__":
    unittest.main()
