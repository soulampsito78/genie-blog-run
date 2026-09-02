"""Tests: today_genie draft_only owner-review email policy gate."""
from __future__ import annotations

import os
import unittest

from admin_store import can_approve_customer_send, derive_artifact_status
from publishing_policy import decide_publishing_actions
from today_genie_execution_identity import natural_slot_completer_qualification
from validators import ValidationIssue, _today_genie_result_from_issues

_FULL_RUNTIME = {"overnight_us_market": {"k": 1}, "macro_indicators": {"k": 2}}
_OWNER_TO = "soulampsito@gmail.com,ey2133@naver.com"
_WARNING_ISSUES = [
    {"code": "closing_lecture_tail", "message": "m", "severity": "warning"},
]
_FINANCE_ISSUES = [
    {"code": "forbidden_financial_promise", "message": "m", "severity": "error"},
]


class OwnerReviewSendPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_gate = os.environ.get("GENIE_OWNER_REVIEW_SEND")
        self._prev_to = os.environ.get("EMAIL_TO")
        self._prev_ctrl = os.environ.get("GENIE_CONTROLLED_TEST_MODE")
        self._prev_ctrl_date = os.environ.get("GENIE_CONTROLLED_TEST_TARGET_DATE")
        os.environ.pop("GENIE_CONTROLLED_TEST_MODE", None)
        os.environ.pop("GENIE_CONTROLLED_TEST_TARGET_DATE", None)

    def tearDown(self) -> None:
        if self._prev_gate is None:
            os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
        else:
            os.environ["GENIE_OWNER_REVIEW_SEND"] = self._prev_gate
        if self._prev_to is None:
            os.environ.pop("EMAIL_TO", None)
        else:
            os.environ["EMAIL_TO"] = self._prev_to
        if self._prev_ctrl is None:
            os.environ.pop("GENIE_CONTROLLED_TEST_MODE", None)
        else:
            os.environ["GENIE_CONTROLLED_TEST_MODE"] = self._prev_ctrl
        if self._prev_ctrl_date is None:
            os.environ.pop("GENIE_CONTROLLED_TEST_TARGET_DATE", None)
        else:
            os.environ["GENIE_CONTROLLED_TEST_TARGET_DATE"] = self._prev_ctrl_date

    def test_draft_only_owner_gate_off_no_send(self) -> None:
        os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            _WARNING_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)

    def test_draft_only_owner_gate_on_owner_recipients_send(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            _WARNING_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertTrue(d.send_email)
        self.assertFalse(d.create_naver_draft)
        self.assertFalse(d.suppress_external)

    def test_draft_only_owner_gate_on_non_owner_recipient_no_send(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = "soulampsito@gmail.com,other@example.com"
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            _WARNING_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)

    def test_draft_only_owner_gate_on_reviewable_finance_issue_sends_owner(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            _FINANCE_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertTrue(d.send_email)
        self.assertFalse(d.suppress_external)
        self.assertFalse(d.send_customer_email)

    def test_0902_review_required_is_owner_handoff_not_missed_delivery(self) -> None:
        issues = [
            ValidationIssue("market_fact_narrative_conflict", "market", "error"),
            ValidationIssue("top3_not_grounded_in_input_news", "news", "error"),
        ]
        validation_result = _today_genie_result_from_issues(issues)
        self.assertEqual(validation_result, "draft_only")

        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        decision = decide_publishing_actions(
            "today_genie",
            validation_result,
            "review_required",
            [
                {"code": issue.code, "message": issue.message, "severity": issue.severity}
                for issue in issues
            ],
            _FULL_RUNTIME,
        )
        self.assertTrue(decision.send_email)  # policy WOULD_SEND; no SMTP call
        self.assertFalse(decision.send_customer_email)

        artifact = {
            "run_id": "20260902_063000_today_genie_abcdef12",
            "mode": "today_genie",
            "execution_class": "natural_scheduled",
            "scheduled_slot": "06:30",
            "trigger_source": "scheduled_service_full_run",
            "response_status": 200,
            "validation_result": validation_result,
            "workflow_status": "review_required",
            "issue_codes": [issue.code for issue in issues],
            "email_sent": True,
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
        }
        artifact["artifact_status"] = derive_artifact_status(artifact)
        self.assertEqual(artifact["artifact_status"], "emailed")
        self.assertEqual(
            artifact["issue_codes"],
            ["market_fact_narrative_conflict", "top3_not_grounded_in_input_news"],
        )
        approvable, reason = can_approve_customer_send(artifact, has_email_html=True)
        self.assertFalse(approvable)
        self.assertEqual(reason, "review_required_remediation_needed")
        natural = natural_slot_completer_qualification(
            artifact, kst_date="2026-09-02", scheduled_slot="06:30"
        )
        self.assertTrue(natural.qualifies, natural.disqualify_reason)

    def test_only_unusable_or_unsafe_today_artifacts_hard_fail(self) -> None:
        self.assertEqual(
            _today_genie_result_from_issues(
                [ValidationIssue("feed_json_decode_failed", "feed", "error")]
            ),
            "block",
        )
        self.assertEqual(
            _today_genie_result_from_issues(
                [ValidationIssue("weak_opening", "editorial", "warning")]
            ),
            "draft_only",
        )

    def test_block_result_no_send(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "block",
            "review_required",
            _WARNING_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)
        self.assertTrue(d.suppress_external)

    def test_api_failure_none_result_no_send(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            None,
            None,
            _WARNING_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)
        self.assertTrue(d.suppress_external)

    def test_today_pass_requires_owner_gate_no_customer_send(self) -> None:
        os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
        d = decide_publishing_actions(
            "today_genie",
            "pass",
            "validated",
            [],
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)
        self.assertFalse(d.create_naver_draft)
        self.assertFalse(d.send_customer_email)

    def test_today_pass_owner_gate_on_owner_review_only(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "pass",
            "validated",
            [],
            _FULL_RUNTIME,
        )
        self.assertTrue(d.send_email)
        self.assertFalse(d.create_naver_draft)
        self.assertFalse(d.send_customer_email)

    def test_tomorrow_draft_only_unchanged(self) -> None:
        os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
        os.environ.pop("EMAIL_TO", None)
        d = decide_publishing_actions(
            "tomorrow_genie",
            "draft_only",
            "review_required",
            [{"code": "weather_input_missing", "message": "m", "severity": "warning"}],
            {},
        )
        self.assertTrue(d.send_email)


if __name__ == "__main__":
    unittest.main()
