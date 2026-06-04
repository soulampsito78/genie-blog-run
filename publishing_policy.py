"""
Thin publishing orchestration layer: converts runtime API results into
concrete publishing actions. Does not change runtime behavior.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from programs.registry import UnknownProgramError, get_program, resolve_program_id


@dataclass(frozen=True)
class PublishingDecision:
    """Publishing actions derived from runtime validation outcome."""

    send_email: bool
    create_naver_draft: bool
    auto_publish: bool
    require_review: bool
    suppress_external: bool
    send_customer_email: bool = False


# Finance-safety issue codes: any of these must suppress downstream distribution.
FINANCE_SAFETY_CODES = frozenset({
    "forbidden_finance_phrase",
    "forbidden_financial_promise",
    "definitive_investment_proposal",
    "invalid_market_snapshot",
    "market_snapshot_missing_required_rows",
    "market_snapshot_required_row_malformed",
    "number_table_contract_malformed",
    "number_table_accuracy_fail",
    "stale_feed_date",
    "stale_content_date_conflict",
    "invalid_watchpoints",
    "invalid_opportunities",
    "top3_watchpoints_missing",
    "top3_item_insufficient_briefing",
    "top3_not_grounded_in_input_news",
    "feed_json_decode_failed",
    "unsupported_numeric_claim",
    "unsupported_news_claim",
    "unsupported_schedule_or_stock_claim",
})

# Critical today_genie inputs: if either is missing, no owner-review email.
CRITICAL_TODAY_INPUTS = ("overnight_us_market", "macro_indicators")

# Owner/internal review recipients only (not customer delivery).
OWNER_REVIEW_EMAIL_ALLOWLIST = frozenset(
    {
        "soulampsito@gmail.com",
        "ey2133@naver.com",
    }
)


def _owner_review_send_gate_active() -> bool:
    return os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _owner_recipients_only() -> bool:
    raw = os.getenv("EMAIL_TO", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return bool(parts) and all(p in OWNER_REVIEW_EMAIL_ALLOWLIST for p in parts)


def _program_spec_for_mode(mode: str):
    try:
        return get_program(resolve_program_id(mode))
    except UnknownProgramError:
        return None


def _today_owner_review_send_allowed(
    issues: List[Dict[str, Any]],
    runtime_input: Optional[Dict[str, Any]],
) -> bool:
    """
    Owner-review email for today_genie scheduled/manual runs.
    Requires GENIE_OWNER_REVIEW_SEND=1 and owner-only EMAIL_TO.
    Never authorizes customer delivery.
    """
    if not _owner_review_send_gate_active():
        return False
    if _critical_today_inputs_missing(runtime_input):
        return False
    if _has_finance_safety_issue(issues):
        return False
    if not _owner_recipients_only():
        return False
    return True


def _has_finance_safety_issue(issues: List[Dict[str, Any]]) -> bool:
    if not issues:
        return False
    codes = {i.get("code") for i in issues if isinstance(i, dict)}
    return bool(codes & FINANCE_SAFETY_CODES)


def _controlled_test_send_active() -> bool:
    """GENIE_CONTROLLED_TEST_MODE + target date (same contract as orchestrator)."""
    flag = os.getenv("GENIE_CONTROLLED_TEST_MODE", "").strip().lower()
    target = os.getenv("GENIE_CONTROLLED_TEST_TARGET_DATE", "").strip()
    return flag in ("1", "true", "yes") and bool(target)


def _critical_today_inputs_missing(runtime_input: Optional[Dict[str, Any]]) -> bool:
    if not runtime_input or not isinstance(runtime_input, dict):
        return True
    for key in CRITICAL_TODAY_INPUTS:
        val = runtime_input.get(key)
        if val is None or (isinstance(val, (list, dict)) and len(val) == 0):
            return True
    return False


def _today_geenee_scheduled_decision(
    result: str,
    issues: List[Dict[str, Any]],
    runtime_input: Optional[Dict[str, Any]],
) -> PublishingDecision:
    """
    Today_Geenee / today_genie: scheduler creates owner-review only.
    Customer send requires explicit owner/admin approval (never from policy here).
    """
    critical_missing = _critical_today_inputs_missing(runtime_input)
    owner_review_send = _today_owner_review_send_allowed(issues, runtime_input)

    if result == "draft_only":
        if owner_review_send and not critical_missing:
            return PublishingDecision(
                send_email=True,
                create_naver_draft=False,
                auto_publish=False,
                require_review=True,
                suppress_external=False,
                send_customer_email=False,
            )
        return PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
            send_customer_email=False,
        )

    # pass — owner-review email only when explicitly gated; never customer or Naver
    return PublishingDecision(
        send_email=owner_review_send and not critical_missing,
        create_naver_draft=False,
        auto_publish=False,
        require_review=True,
        suppress_external=False,
        send_customer_email=False,
    )


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
        require_review, suppress_external, send_customer_email.
    """
    issues = issues or []
    result = validation_result
    program = _program_spec_for_mode(mode)

    # Run failed (500, network, etc.) or explicit block → full suppress
    if result not in ("pass", "draft_only"):
        return PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
            send_customer_email=False,
        )

    # Finance-safety issue: always suppress distribution
    if mode == "today_genie" and _has_finance_safety_issue(issues):
        return PublishingDecision(
            send_email=False,
            create_naver_draft=False,
            auto_publish=False,
            require_review=True,
            suppress_external=True,
            send_customer_email=False,
        )

    if mode == "today_genie":
        if program and program.customer_send_requires_approval:
            return _today_geenee_scheduled_decision(result, issues, runtime_input)
        # fallback (should not happen once registry wired)
        return _today_geenee_scheduled_decision(result, issues, runtime_input)

    # tomorrow_genie (result is pass or draft_only; block handled above)
    if result == "draft_only":
        return PublishingDecision(
            send_email=True,
            create_naver_draft=True,
            auto_publish=False,
            require_review=True,
            suppress_external=False,
            send_customer_email=False,
        )
    # pass
    return PublishingDecision(
        send_email=True,
        create_naver_draft=True,
        auto_publish=False,
        require_review=True,
        suppress_external=False,
        send_customer_email=False,
    )
