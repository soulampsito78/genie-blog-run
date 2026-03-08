"""
Thin publishing orchestration layer: converts runtime API results into
concrete publishing actions. Does not change runtime behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PublishingDecision:
    """Publishing actions derived from runtime validation outcome."""

    send_email: bool
    create_naver_draft: bool
    auto_publish: bool
    require_review: bool
    suppress_external: bool


# Finance-safety issue codes: any of these must suppress downstream distribution.
FINANCE_SAFETY_CODES = frozenset({
    "forbidden_finance_phrase",
    "invalid_market_snapshot",
    "invalid_watchpoints",
    "invalid_opportunities",
    "invalid_risk_check",
})

# Critical today_genie inputs: if either is missing, no auto email.
CRITICAL_TODAY_INPUTS = ("overnight_us_market", "macro_indicators")


def _has_finance_safety_issue(issues: List[Dict[str, Any]]) -> bool:
    if not issues:
        return False
    codes = {i.get("code") for i in issues if isinstance(i, dict)}
    return bool(codes & FINANCE_SAFETY_CODES)


def _critical_today_inputs_missing(runtime_input: Optional[Dict[str, Any]]) -> bool:
    if not runtime_input or not isinstance(runtime_input, dict):
        return True
    for key in CRITICAL_TODAY_INPUTS:
        val = runtime_input.get(key)
        if val is None or (isinstance(val, (list, dict)) and len(val) == 0):
            return True
    return False


def decide_publishing_actions(
    mode: str,
    validation_result: Optional[str],
    workflow_status: Optional[str],
    issues: Optional[List[Dict[str, Any]]] = None,
    runtime_input: Optional[Dict[str, Any]] = None,
) -> PublishingDecision:
    """
    Convert runtime outcome into publishing actions.

    Args:
        mode: "today_genie" or "tomorrow_genie"
        validation_result: "pass", "draft_only", "block", or None if run failed
        workflow_status: "validated" or "review_required"
        issues: list of {"code", "message", "severity"} from API
        runtime_input: optional runtime input dict (for today_genie critical-input check)

    Returns:
        PublishingDecision with send_email, create_naver_draft, auto_publish,
        require_review, suppress_external.
    """
    issues = issues or []
    result = validation_result

    # Run failed (500, network, etc.) or explicit block → full suppress
    if result not in ("pass", "draft_only"):
        return PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
        )

    # Finance-safety issue: always suppress distribution
    if mode == "today_genie" and _has_finance_safety_issue(issues):
        return PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
        )

    if mode == "today_genie":
        critical_missing = _critical_today_inputs_missing(runtime_input)
        if result == "draft_only":
            return PublishingDecision(
                send_email=False,
                create_naver_draft=True,
                auto_publish=False,
                require_review=True,
                suppress_external=False,
            )
        # pass
        return PublishingDecision(
            send_email=not critical_missing,
            create_naver_draft=True,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
        )

    # tomorrow_genie (result is pass or draft_only; block handled above)
    if result == "draft_only":
        return PublishingDecision(
            send_email=True,
            create_naver_draft=True,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
        )
    # pass
    return PublishingDecision(
        send_email=True,
        create_naver_draft=True,
        auto_publish=False,
        require_review=True,
        suppress_external=False,
    )
