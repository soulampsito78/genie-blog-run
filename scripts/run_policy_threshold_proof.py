#!/usr/bin/env python3
"""
No-send policy proof for publishing_policy + controlled editorial thresholds.
Run from repo root: python3 scripts/run_policy_threshold_proof.py
"""
from __future__ import annotations

import os
import sys

# Allow imports from package root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from publishing_policy import decide_publishing_actions  # noqa: E402

_FULL_RUNTIME = {"overnight_us_market": {"k": 1}, "macro_indicators": {"k": 2}}


def _with_controlled_env(fn):
    os.environ["GENIE_CONTROLLED_TEST_MODE"] = "true"
    os.environ["GENIE_CONTROLLED_TEST_TARGET_DATE"] = "2026-04-10"
    try:
        return fn()
    finally:
        os.environ.pop("GENIE_CONTROLLED_TEST_MODE", None)
        os.environ.pop("GENIE_CONTROLLED_TEST_TARGET_DATE", None)


def _without_controlled_env(fn):
    os.environ.pop("GENIE_CONTROLLED_TEST_MODE", None)
    os.environ.pop("GENIE_CONTROLLED_TEST_TARGET_DATE", None)
    return fn()


def main() -> int:
    # Case A: controlled + draft_only + only closing_lecture_tail (warning)
    def case_a():
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            [{"code": "closing_lecture_tail", "message": "m", "severity": "warning"}],
            _FULL_RUNTIME,
        )
        assert d.send_email is True, f"A send_email={d.send_email}"

    _with_controlled_env(case_a)

    # Case B: controlled + invalid_risk_check as error in issues (policy layer only)
    def case_b():
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            [{"code": "invalid_risk_check", "message": "m", "severity": "error"}],
            _FULL_RUNTIME,
        )
        assert d.send_email is True, f"B send_email={d.send_email}"

    _with_controlled_env(case_b)

    # Case C: controlled + forbidden finance phrase (true blocker)
    def case_c():
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            [{"code": "forbidden_financial_promise", "message": "m", "severity": "error"}],
            _FULL_RUNTIME,
        )
        assert d.send_email is False, f"C send_email={d.send_email}"

    _with_controlled_env(case_c)

    # Case D: production path stale_feed_date
    def case_d():
        d = decide_publishing_actions(
            "today_genie",
            "pass",
            "validated",
            [{"code": "stale_feed_date", "message": "stale", "severity": "error"}],
            _FULL_RUNTIME,
        )
        assert d.send_email is False, f"D send_email={d.send_email}"

    _without_controlled_env(case_d)

    # Case E: production draft_only + only editorial warning — still no email send, not finance-blocked
    def case_e():
        d = decide_publishing_actions(
            "today_genie",
            "draft_only",
            "review_required",
            [{"code": "closing_lecture_tail", "message": "m", "severity": "warning"}],
            _FULL_RUNTIME,
        )
        assert d.send_email is False, f"E send_email={d.send_email}"
        assert d.suppress_external is False

    _without_controlled_env(case_e)

    print("policy_threshold_proof: all cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
