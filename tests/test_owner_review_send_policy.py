"""Tests: today_genie draft_only owner-review email policy gate."""
from __future__ import annotations

import os
import unittest

from publishing_policy import decide_publishing_actions

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

    def test_draft_only_owner_gate_on_finance_issue_no_send(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = _OWNER_TO
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            _FINANCE_ISSUES,
            _FULL_RUNTIME,
        )
        self.assertFalse(d.send_email)
        self.assertTrue(d.suppress_external)

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
