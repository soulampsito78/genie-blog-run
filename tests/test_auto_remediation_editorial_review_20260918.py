"""A runtime PASS with graded editorial REVIEW must not be mistaken for ready."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from auto_remediation import (
    RESULT_CHILD_STILL_REVIEWABLE,
    RESULT_FAILED,
    RESULT_SUCCEEDED,
    SCOPE_BODY_ONLY,
    _child_outcome,
    classify_issue_codes,
    plan_auto_remediation,
)

_CODE = "global_visible_repeated_low_information_label"


def _global_meta(**overrides):
    meta = {
        "run_id": "20260918_123001_keysuri_global_tech_cff48972",
        "mode": "keysuri_global_tech",
        "execution_class": "natural_scheduled",
        "validation_result": "pass",
        "artifact_status": "emailed",
        "editorial_verdict": "REVIEW",
        "review_issue_codes": [_CODE],
        "customer_delivery_status": "not_sent",
        "owner_review_status": "pending_review",
    }
    meta.update(overrides)
    return meta


class EditorialReviewRemediationTests(unittest.TestCase):
    def test_exact_issue_code_is_body_only_but_unknown_stays_blocked(self):
        self.assertEqual(
            classify_issue_codes([_CODE, "keysuri_korean_repeated_token_repaired"]),
            (SCOPE_BODY_ONLY, [], []),
        )
        self.assertEqual(
            classify_issue_codes(["unknown_editorial_code"]),
            (None, [], ["unknown_editorial_code"]),
        )

    @patch("admin_store._reissue_parent_top_images_provably_gone", return_value=False)
    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_reviewed_runtime_pass_is_eligible_for_one_body_repair(self, _boundary, _image):
        plan = plan_auto_remediation(_global_meta())
        self.assertTrue(plan.eligible, plan.stop_reason)
        self.assertEqual(plan.scope, SCOPE_BODY_ONLY)
        self.assertEqual(plan.review_class, "review_required")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_ready_and_attempted_runs_remain_ineligible(self, _boundary):
        ready = plan_auto_remediation(
            _global_meta(editorial_verdict="READY", review_issue_codes=[])
        )
        attempted = plan_auto_remediation(
            _global_meta(automatic_remediation_attempt_count=1)
        )
        self.assertEqual(ready.stop_reason, "run_passed")
        self.assertEqual(attempted.stop_reason, "attempt_budget_exhausted")

    @patch("auto_remediation._delegated_review_repair_boundary", return_value=None)
    def test_children_and_no_send_verification_remain_ineligible(self, _boundary):
        child = plan_auto_remediation(_global_meta(parent_run_id="parent"))
        no_send = plan_auto_remediation(
            _global_meta(verification_mode="no_send_verification")
        )
        self.assertEqual(child.stop_reason, "already_a_remediation_child")
        self.assertEqual(no_send.stop_reason, "no_send_verification_run")

    def test_child_still_under_editorial_review_is_not_success(self):
        result, label, remaining = _child_outcome(_global_meta())
        self.assertEqual(result, RESULT_CHILD_STILL_REVIEWABLE)
        self.assertEqual(label, "REVIEW_REQUIRED")
        self.assertIn(_CODE, remaining)

    def test_child_poor_fails_and_ready_succeeds(self):
        poor, _, _ = _child_outcome(_global_meta(editorial_verdict="POOR"))
        ready, _, _ = _child_outcome(
            _global_meta(editorial_verdict="READY", review_issue_codes=[])
        )
        self.assertEqual(poor, RESULT_FAILED)
        self.assertEqual(ready, RESULT_SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
