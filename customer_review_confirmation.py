"""Approved outbound review-copy selection.

This module selects wording for an already-authorized renderer call.  It does
not inspect or grant Owner, delegated-review, recipient, or delivery authority.
Those decisions remain in the corresponding approval and delivery gates.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

HUMAN_OWNER = "HUMAN_OWNER"
DELEGATED_WORK_REVIEW = "DELEGATED_WORK_REVIEW"
PRE_SEND_REVIEWED = "PRE_SEND_REVIEWED"
PRE_SEND_OWNER_WITH_WARNINGS = "PRE_SEND_OWNER_WITH_WARNINGS"
HUMAN_OWNER_WARNING_TEXT = "본 브리핑은 품질 검수 경고를 유지한 상태로 운영책임자의 발송 결정에 따라 제공됩니다."

HUMAN_DIRECT_REVIEW_TEXT = "본 브리핑은 운영책임자의 직접 검수를 통과했습니다."
DELEGATED_REVIEW_TEXT = "본 브리핑은 운영책임자가 정한 정책에 따른 독립적인 AI 검토를 통과했습니다."

_SOURCES = frozenset({HUMAN_OWNER, DELEGATED_WORK_REVIEW})

ALLOWED_WARNING_ISSUE_CODES = frozenset({
    "today_replay_temporal_conflict",
    "top3_item_insufficient_briefing",
})


def _collect_issue_codes(meta: Mapping[str, Any]) -> tuple[bool, list[str]]:
    raw_lists: list[Any] = []

    for key in ("issue_codes", "product_surface_issue_codes", "review_issue_codes"):
        if key in meta:
            val = meta.get(key)
            if not isinstance(val, (list, tuple)):
                return False, []
            raw_lists.append(val)

    ps_qa = meta.get("product_surface_qa")
    if isinstance(ps_qa, dict) and "issue_codes" in ps_qa:
        val = ps_qa.get("issue_codes")
        if not isinstance(val, (list, tuple)):
            return False, []
        raw_lists.append(val)

    rvc = meta.get("runtime_validation_check")
    if isinstance(rvc, dict):
        if "issue_codes" in rvc:
            val = rvc.get("issue_codes")
            if not isinstance(val, (list, tuple)):
                return False, []
            raw_lists.append(val)
        if "issue_details" in rvc and isinstance(rvc.get("issue_details"), (list, tuple)):
            details = rvc.get("issue_details")
            extracted: list[Any] = []
            for d in details:
                if not isinstance(d, dict) or "code" not in d:
                    return False, []
                extracted.append(d.get("code"))
            raw_lists.append(extracted)

    if "issue_details" in meta and isinstance(meta.get("issue_details"), (list, tuple)):
        details = meta.get("issue_details")
        extracted = []
        for d in details:
            if not isinstance(d, dict) or "code" not in d:
                return False, []
            extracted.append(d.get("code"))
        raw_lists.append(extracted)

    if not raw_lists:
        return False, []

    collected: list[str] = []
    for l in raw_lists:
        for item in l:
            if not isinstance(item, str) or not item.strip():
                return False, []
            collected.append(item.strip())

    if not collected:
        return False, []

    return True, collected


def today_quality_warning_present(
    meta: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Identify the narrow warning state; never grant approval or send authority."""
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode != "today_genie":
        return False

    val_res = str(meta.get("validation_result") or "")
    rss = str(meta.get("runtime_safety_status") or "")
    css = str(meta.get("customer_surface_status") or "")

    # 1. Existing pass/RUNTIME_SAFETY_PASS case unchanged
    if val_res == "pass" and rss == "RUNTIME_SAFETY_PASS" and css == "PRODUCT_REVIEW_REQUIRED":
        return True

    # 2. Tightly bounded HUMAN manual reviewable-warning case
    try:
        status_code = int(meta.get("response_status") or 0)
    except (TypeError, ValueError):
        return False

    if not (
        status_code == 200
        and val_res == "draft_only"
        and rss == "REVIEW_REQUIRED"
        and css == "PRODUCT_REVIEW_REQUIRED"
    ):
        return False

    valid_codes, collected_codes = _collect_issue_codes(meta)
    if not valid_codes:
        return False

    if not all(code in ALLOWED_WARNING_ISSUE_CODES for code in collected_codes):
        return False

    # Server time in Asia/Seoul
    if now is None:
        now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    elif now.tzinfo is None:
        now_kst = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    else:
        now_kst = now.astimezone(ZoneInfo("Asia/Seoul"))

    # Actual time must be strictly before 09:00 KST
    if now_kst.hour >= 9:
        return False

    # Actual server date must match exact artifact target date
    target_date = str(meta.get("target_date") or "").strip()
    if not target_date or target_date != now_kst.date().isoformat():
        return False

    # run_id day must match target date / server date
    run_id = str(meta.get("run_id") or "").strip()
    match = re.match(r"^(\d{8})", run_id)
    if not match or match.group(1) != now_kst.strftime("%Y%m%d"):
        return False

    # created_at must be timezone-aware and on the exact same date
    created_at_raw = meta.get("created_at")
    if not isinstance(created_at_raw, str) or not created_at_raw.strip():
        return False
    try:
        created_dt = datetime.fromisoformat(created_at_raw.strip())
    except Exception:
        return False
    if created_dt.tzinfo is None or created_dt.utcoffset() is None:
        return False
    created_kst = created_dt.astimezone(ZoneInfo("Asia/Seoul"))
    if created_kst.date() != now_kst.date():
        return False

    # Require actual exact 3 selected/required/selected-item count
    try:
        req_count = int(meta.get("required_count"))
    except (TypeError, ValueError):
        return False
    if req_count != 3:
        return False

    selected_items = meta.get("selected_items")
    if not isinstance(selected_items, list) or len(selected_items) != 3:
        return False

    for count_key in ("selected_items_count", "selected_item_count", "selected_count"):
        if count_key in meta:
            try:
                if int(meta[count_key]) != 3:
                    return False
            except (TypeError, ValueError):
                return False

    return True


def customer_review_confirmation(*, approval_source: str, display_state: str) -> tuple[str, str]:
    """Return a truthful pre-submit display state and its source-specific copy.

    Customer payload preparation occurs before SMTP/provider submission, so an
    outbound candidate must never claim that it has already been sent.
    """
    if approval_source not in _SOURCES:
        raise ValueError(f"unsupported customer review approval_source: {approval_source!r}")
    if display_state == PRE_SEND_OWNER_WITH_WARNINGS:
        if approval_source != HUMAN_OWNER:
            raise ValueError("manual warning display requires HUMAN_OWNER")
        return "owner_send_with_warnings", HUMAN_OWNER_WARNING_TEXT
    if display_state != PRE_SEND_REVIEWED:
        raise ValueError(f"unsupported customer review display_state: {display_state!r}")
    text = HUMAN_DIRECT_REVIEW_TEXT if approval_source == HUMAN_OWNER else DELEGATED_REVIEW_TEXT
    return "review_passed", text
