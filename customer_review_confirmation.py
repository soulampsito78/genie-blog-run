"""Approved outbound review-copy selection.

This module selects wording for an already-authorized renderer call.  It does
not inspect or grant Owner, delegated-review, recipient, or delivery authority.
Those decisions remain in the corresponding approval and delivery gates.
"""
from __future__ import annotations

HUMAN_OWNER = "HUMAN_OWNER"
DELEGATED_WORK_REVIEW = "DELEGATED_WORK_REVIEW"
PRE_SEND_REVIEWED = "PRE_SEND_REVIEWED"

HUMAN_DIRECT_REVIEW_TEXT = "본 브리핑은 운영책임자의 직접 검수를 통과했습니다."
DELEGATED_REVIEW_TEXT = "본 브리핑은 운영책임자가 정한 정책에 따른 독립적인 AI 검토를 통과했습니다."

_SOURCES = frozenset({HUMAN_OWNER, DELEGATED_WORK_REVIEW})


def customer_review_confirmation(*, approval_source: str, display_state: str) -> tuple[str, str]:
    """Return a truthful pre-submit display state and its source-specific copy.

    Customer payload preparation occurs before SMTP/provider submission, so an
    outbound candidate must never claim that it has already been sent.
    """
    if approval_source not in _SOURCES:
        raise ValueError(f"unsupported customer review approval_source: {approval_source!r}")
    if display_state != PRE_SEND_REVIEWED:
        raise ValueError(f"unsupported customer review display_state: {display_state!r}")
    text = HUMAN_DIRECT_REVIEW_TEXT if approval_source == HUMAN_OWNER else DELEGATED_REVIEW_TEXT
    return "review_passed", text
