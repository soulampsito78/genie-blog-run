"""Tests for editorial auto-reissue policy across Today, Global, and Korea.

Verifies:
1. Harmless-only natural scheduled REVIEW candidates skip auto-remediation
   and do not consume attempt budget or generate child artifacts.
2. Mixed real defects (harmless + remediable defect) retain original behavior
   and proceed to auto-remediation without broad exemption.
3. Unknown, numeric, source, image, and infrastructure codes retain fail-closed behavior.
4. Authoritative boundaries (already sent, HOLD, child-of-child, exhausted attempts)
   retain existing boundary behavior.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from auto_remediation import (
    AUTO_REMEDIATION_MAX_ATTEMPTS,
    RESULT_SKIPPED,
    SCOPE_BODY_AND_IMAGE,
    SCOPE_BODY_ONLY,
    SCOPE_IMAGE_ONLY,
    classify_issue_codes,
    plan_auto_remediation,
    run_auto_remediation,
)
from publication_review_policy import (
    ALL_HARMLESS_EDITORIAL_CODES,
    SURFACE_EDITORIAL_ONLY_CODES,
    VALIDATOR_EDITORIAL_ONLY_CODES,
    are_all_editorial_harmless,
)


def _today_meta(**overrides) -> dict:
    meta = {
        "run_id": "20261104_063001_today_genie_11112222",
        "mode": "today_genie",
        "program_id": "today_genie",
        "execution_class": "natural_scheduled",
        "validation_result": "draft_only",
        "workflow_status": "review_required",
        "artifact_status": "emailed",
        "customer_surface_status": "CUSTOMER_SURFACE_PASS",
        "issue_codes": ["weak_opening"],
        "customer_delivery_status": "not_sent",
        "owner_review_status": "pending_review",
    }
    meta.update(overrides)
    return meta


def _global_meta(**overrides) -> dict:
    meta = {
        "run_id": "20261104_123001_keysuri_global_tech_33334444",
        "mode": "keysuri_global_tech",
        "program_id": "keysuri_global_tech",
        "execution_class": "natural_scheduled",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "safety_verdict": "SAFE",
        "editorial_verdict": "REVIEW",
        "review_issue_codes": ["customer_surface_mixed_sentence_end_style"],
        "customer_delivery_status": "not_sent",
        "owner_review_status": "pending_review",
    }
    meta.update(overrides)
    return meta


def _korea_meta(**overrides) -> dict:
    meta = {
        "run_id": "20261104_123001_keysuri_korea_tech_55556666",
        "mode": "keysuri_korea_tech",
        "program_id": "keysuri_korea_tech",
        "execution_class": "natural_scheduled",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "safety_verdict": "SAFE",
        "editorial_verdict": "REVIEW",
        "product_surface_issue_codes": ["customer_surface_repeated_sentence_skeleton"],
        "review_issue_codes": ["keysuri_korean_repeated_token_repaired"],
        "customer_delivery_status": "not_sent",
        "owner_review_status": "pending_review",
    }
    meta.update(overrides)
    return meta


class EditorialAutoReissuePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = patch.dict(
            os.environ,
            {"GENIE_ADMIN_SAFETY_LOCAL_DIR": self._tmp.name},
            clear=False,
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    # 1. Harmless-only natural scheduled candidates skip auto-remediation across all 3 products
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_harmless_only_today_skips_auto_remediation(self, _del):
        meta = _today_meta(issue_codes=["weak_opening", "low_summary_density"])
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "editorial_only")
        self.assertEqual(plan.review_class, "review_required")
        self.assertIn("weak_opening", plan.issue_codes)
        self.assertIn("low_summary_density", plan.issue_codes)

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_harmless_only_global_skips_auto_remediation(self, _del):
        meta = _global_meta(
            review_issue_codes=[
                "customer_surface_mixed_sentence_end_style",
                "today_replay_edition_label_warning",
            ]
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "editorial_only")
        self.assertEqual(plan.review_class, "review_required")
        self.assertIn("customer_surface_mixed_sentence_end_style", plan.issue_codes)
        self.assertIn("today_replay_edition_label_warning", plan.issue_codes)

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_harmless_global_low_information_label_skips_auto_remediation(self, _del):
        meta = _global_meta(
            review_issue_codes=["global_visible_repeated_low_information_label"]
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "editorial_only")
        self.assertEqual(plan.review_class, "review_required")
        self.assertIn("global_visible_repeated_low_information_label", plan.issue_codes)

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_harmless_only_korea_with_informational_repaired_skips_auto_remediation(self, _del):
        # Korea with harmless surface issue + informational *_repaired code
        meta = _korea_meta(
            product_surface_issue_codes=["customer_surface_repeated_sentence_skeleton"],
            review_issue_codes=["keysuri_korean_repeated_token_repaired"],
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "editorial_only")
        self.assertEqual(plan.review_class, "review_required")
        # Preserves both diagnostic codes
        self.assertIn("customer_surface_repeated_sentence_skeleton", plan.issue_codes)
        self.assertIn("keysuri_korean_repeated_token_repaired", plan.issue_codes)

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_harmless_only_via_surface_editorial_warning_codes(self, _del):
        meta = _today_meta(
            issue_codes=[],
            product_surface_editorial_warning_codes=["customer_surface_duplicate_filler"],
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "editorial_only")
        self.assertIn("customer_surface_duplicate_filler", plan.issue_codes)

    # 2. Harmless runs do NOT consume attempts or invoke runners (no generation)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_run_auto_remediation_skips_without_consuming_attempts_all_three_products(self, _del):
        products = [
            ("today_genie", _today_meta()),
            ("keysuri_global_tech", _global_meta()),
            ("keysuri_korea_tech", _korea_meta()),
        ]
        for mode, meta in products:
            runner_mock = MagicMock()
            runners = {
                (mode, SCOPE_BODY_ONLY): runner_mock,
                (mode, SCOPE_IMAGE_ONLY): runner_mock,
                (mode, SCOPE_BODY_AND_IMAGE): runner_mock,
            }
            with patch("auto_remediation.load_run_artifact", return_value=dict(meta)), \
                 patch("auto_remediation.update_run_artifact"):
                summary = run_auto_remediation(meta["run_id"], runners=runners)
                self.assertFalse(summary["automatic_remediation_triggered"])
                self.assertEqual(summary["automatic_remediation_result"], RESULT_SKIPPED)
                self.assertEqual(summary["stop_reason"], "editorial_only")
                self.assertEqual(summary["automatic_remediation_attempt_count"], 0)
                # Generation runner was never invoked
                runner_mock.assert_not_called()

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_global_low_information_label_skips_without_consuming_attempts_or_generation(self, _del):
        meta = _global_meta(
            review_issue_codes=["global_visible_repeated_low_information_label"]
        )
        runner_mock = MagicMock()
        runners = {
            ("keysuri_global_tech", SCOPE_BODY_ONLY): runner_mock,
            ("keysuri_global_tech", SCOPE_IMAGE_ONLY): runner_mock,
            ("keysuri_global_tech", SCOPE_BODY_AND_IMAGE): runner_mock,
        }
        with patch("auto_remediation.load_run_artifact", return_value=dict(meta)), \
             patch("auto_remediation.update_run_artifact"):
            summary = run_auto_remediation(meta["run_id"], runners=runners)
            self.assertFalse(summary["automatic_remediation_triggered"])
            self.assertEqual(summary["automatic_remediation_result"], RESULT_SKIPPED)
            self.assertEqual(summary["stop_reason"], "editorial_only")
            self.assertEqual(summary["automatic_remediation_attempt_count"], 0)
            runner_mock.assert_not_called()

    # 3. Mixed real defects retain original behavior (not exempted)
    @patch("admin_store._reissue_parent_top_images_provably_gone", return_value=False)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_mixed_real_defect_today_proceeds_to_remediation(self, _del, _img):
        # Harmless weak_opening + genuine body defect unanchored_briefing_vs_input_news
        meta = _today_meta(issue_codes=["weak_opening", "unanchored_briefing_vs_input_news"])
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)
        self.assertIn("unanchored_briefing_vs_input_news", plan.issue_codes)

    @patch("admin_store._reissue_parent_top_images_provably_gone", return_value=False)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_mixed_real_defect_global_image_proceeds_to_remediation(self, _del, _img):
        # Harmless surface + missing image -> body_and_image
        meta = _global_meta(
            review_issue_codes=[
                "customer_surface_mixed_sentence_end_style",
                "keysuri_top_image_missing",
            ]
        )
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_AND_IMAGE)

    @patch("admin_store._reissue_parent_top_images_provably_gone", return_value=False)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_mixed_global_low_information_label_with_image_defect_proceeds_to_remediation(self, _del, _img):
        # Harmless low-info label + missing image defect -> body_and_image
        meta = _global_meta(
            review_issue_codes=[
                "global_visible_repeated_low_information_label",
                "keysuri_top_image_missing",
            ]
        )
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_AND_IMAGE)
        self.assertIn("keysuri_top_image_missing", plan.issue_codes)

    @patch("admin_store._reissue_parent_top_images_provably_gone", return_value=False)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_mixed_real_defect_korea_proceeds_to_remediation(self, _del, _img):
        # Harmless skeleton + genuine weak_summary
        meta = _korea_meta(
            product_surface_issue_codes=["customer_surface_repeated_sentence_skeleton"],
            review_issue_codes=["weak_summary"],
        )
        plan = plan_auto_remediation(meta)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)

    # 4. Unknown and infrastructure codes retain original fail-closed behavior
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_unknown_issue_code_fails_closed(self, _del):
        meta = _today_meta(issue_codes=["weak_opening", "unknown_editorial_anomaly_99"])
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "unclassified_issue_code")
        self.assertIn("unknown_editorial_anomaly_99", plan.unclassified_codes)

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_infrastructure_code_fails_closed(self, _del):
        meta = _global_meta(
            review_issue_codes=[
                "customer_surface_mixed_sentence_end_style",
                "feed_json_decode_failed",
            ]
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "non_remediable_issue_code")
        self.assertIn("feed_json_decode_failed", plan.blocking_codes)

    # 5. Authoritative boundaries retain existing behavior
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_post_send_boundary_retains_block(self, _del):
        meta = _today_meta(
            customer_delivery_status="accepted_all",
            customer_delivery_accepted_count=1,
            customer_email_sent_at_kst="2026-11-04T08:00:00+09:00",
        )
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "customer_delivery_already_attempted")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_child_run_boundary_retains_block(self, _del):
        meta = _global_meta(parent_run_id="20261104_120000_parent_artifact")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "already_a_remediation_child")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_exhausted_attempts_budget_retains_block(self, _del):
        meta = _korea_meta(automatic_remediation_attempt_count=AUTO_REMEDIATION_MAX_ATTEMPTS)
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "attempt_budget_exhausted")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_manual_execution_class_retains_block(self, _del):
        meta = _today_meta(execution_class="manual_trigger")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "not_a_natural_scheduled_run")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_no_send_verification_retains_block(self, _del):
        meta = _global_meta(verification_mode="no_send_verification")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "no_send_verification_run")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_human_approval_present_retains_block(self, _del):
        meta = _today_meta(owner_review_status="approved")
        plan = plan_auto_remediation(meta)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.stop_reason, "human_approval_present")


if __name__ == "__main__":
    unittest.main()
