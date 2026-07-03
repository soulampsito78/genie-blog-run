"""Kee-Suri staged prompt input composer (foundation — not wired to runtime)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from keysuri_news_contract import (
    KEYSURI_TOP_NEWS_COUNT,
    KEYSURI_PROGRAM_IDS,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    expected_news_scope_for_program,
    expected_top5_heading_for_program,
    select_top_5_news,
)
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
    REQUIRED_OPERATIONAL_STATUS,
    keysuri_output_schema_example,
)
from keysuri_source_gate import GateResult, run_keysuri_source_gate
from programs.registry import get_program
from owner_review_exposure_log_store import recent_owner_review_exposure_log_with_status
from sent_news_dedup_gate import metadata_from_gate_result, run_sent_news_dedup_gate
from sent_news_log_store import recent_sent_news_log

OUTPUT_CONTRACT = "keysuri_private_briefing_v1"

_COMMON_FORBIDDEN_OUTPUTS: List[str] = [
    "TOP 3 output",
    "generic TOP 5",
    "unsupported numbers",
    "unsupported policy/legal certainty",
    "fake sources",
    "invented dates",
    "public news anchor tone",
    "Today_Geenee HTML email body",
    "Naver paste body",
    "HTML attachment language",
    "image attachment package language",
    "live-source claims not present in source_pack",
]

_PROGRAM_FORBIDDEN_CROSS_HEADING: Dict[str, str] = {
    "keysuri_global_tech": SECTION_TOP5_KOREA,
    "keysuri_korea_tech": SECTION_TOP5_GLOBAL,
}


def _gate_result_to_dict(result: GateResult) -> Dict[str, Any]:
    return {
        "verdict": result.verdict,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
                **({"source_id": issue.source_id} if issue.source_id else {}),
                **({"claim_id": issue.claim_id} if issue.claim_id else {}),
            }
            for issue in result.issues
        ],
    }


def _forbidden_outputs_for_program(program_id: str) -> List[str]:
    cross = _PROGRAM_FORBIDDEN_CROSS_HEADING.get(program_id)
    out = list(_COMMON_FORBIDDEN_OUTPUTS)
    if cross:
        out.append(cross)
    return out


def _fixed_section_labels(program_id: str) -> Dict[str, str]:
    return {
        "top_5_news": expected_top5_heading_for_program(program_id),
        "deep_dive": SECTION_DEEP_DIVE,
        "one_line_checkpoint": SECTION_ONE_LINE,
        "closing_sources": SECTION_CLOSING,
    }


def _generation_instructions(program_id: str, news_scope: str, section_heading: str) -> List[str]:
    cross = _PROGRAM_FORBIDDEN_CROSS_HEADING.get(program_id, "")
    return [
        "Return exactly one JSON object matching keysuri_private_briefing_v1.",
        f"top_5_news.news_scope must be {news_scope!r}.",
        f"top_5_news.section_heading must be {section_heading!r}.",
        f"Do not output {cross!r} or generic TOP 5 / TOP 3 headings.",
        "top_5_news.items must contain exactly 5 items grounded in source_pack claims.",
        "Use only facts, numbers, dates, and sources present in the provided source_pack.",
        "Maintain Kee-Suri premium private secretary tone; not public news anchor tone.",
        "Set operational_status to review_required.",
        "Do not produce email HTML, Naver paste, or attachment-package language.",
    ]


def _output_schema_summary(program_id: str) -> Dict[str, Any]:
    example = keysuri_output_schema_example(program_id)
    return {
        "output_contract": OUTPUT_CONTRACT,
        "required_top_level_keys": list(example.keys()),
        "top_5_news_item_fields": [
            "rank",
            "news_id",
            "headline",
            "category",
            "summary",
            "why_it_matters",
            "business_implication",
            "source_ids",
            "confidence_label",
        ],
        "operational_status": REQUIRED_OPERATIONAL_STATUS,
    }


def build_keysuri_prompt_input(
    program_id: str,
    source_pack: dict,
    gate_result: Optional[GateResult] = None,
    extra_recent_log: Optional[list] = None,
    *,
    trigger_source: Optional[str] = None,
) -> dict:
    """
    Build staged Kee-Suri prompt input from a source pack (offline; no LLM call).

    Runs source gate (unless gate_result provided) and TOP 5 selection.

    ``extra_recent_log`` adds extra rows to the cross-day dedup exclusion set on
    top of the recent sent-news / owner-review exposure logs. Reissue uses this to
    exclude the parent run's selected_items so the regenerated TOP5 picks fresh,
    non-duplicate news instead of re-selecting the parent's items.

    ``trigger_source`` distinguishes scheduled runs from manual/QA runs. On a
    scheduled run an owner-review-exposure duplicate is a soft duplicate that may
    be re-injected (controlled backfill) rather than collapsing the run into a
    hold; customer-sent items always stay a hard block. See
    :func:`keysuri_news_contract.select_top_5_news`.
    """
    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        raise ValueError(
            f"program_id must be keysuri_global_tech or keysuri_korea_tech, got {program_id!r}"
        )

    if not isinstance(source_pack, dict):
        raise ValueError("source_pack must be a dict")

    pack_pid = str(source_pack.get("program_id") or "").strip()
    if pack_pid and pack_pid != pid:
        raise ValueError(
            f"source_pack.program_id {pack_pid!r} does not match program_id {pid!r}"
        )

    if gate_result is None:
        gate_result = run_keysuri_source_gate(source_pack)

    if gate_result.verdict == "block":
        messages = "; ".join(issue.message for issue in gate_result.issues[:5])
        raise ValueError(f"Kee-Suri source gate blocked for {pid}: {messages}")

    # Read cross-day dedup history (recent sent-news + owner-review exposure +
    # caller-supplied extra rows) BEFORE the top-5 selection so duplicates are
    # removed from the FULL candidate pool prior to selection. Selecting five
    # first and deduping them afterwards can shrink the list to four with no
    # replacement pool left (root cause of top_5_news_items_too_few).
    sent_log_rows = recent_sent_news_log(pid)
    exposure_log_status = recent_owner_review_exposure_log_with_status(pid, days=5)
    exposure_log_rows = exposure_log_status["items"]
    extra_rows = [row for row in (extra_recent_log or []) if isinstance(row, dict)]
    combined_recent_log = list(sent_log_rows) + list(exposure_log_rows) + extra_rows

    # Customer-sent + reissue parent rows are a HARD block; owner-review exposure
    # rows are a SOFT duplicate that a scheduled run may controlled-backfill.
    hard_block_rows = list(sent_log_rows) + extra_rows
    selection = select_top_5_news(
        source_pack,
        gate_result,
        recent_dedup_rows=extra_rows,
        sent_log_rows=list(sent_log_rows),
        exposure_log_rows=None,  # Owner-review exposure log is purely admin trace; do not use as production dedupe source
        trigger_source=trigger_source,
    )
    spec = get_program(pid)
    news_scope = expected_news_scope_for_program(pid)
    section_heading = expected_top5_heading_for_program(pid)
    gate_dict = _gate_result_to_dict(gate_result)

    base: Dict[str, Any] = {
        "program_id": pid,
        "prompt_profile": spec.prompt_profile,
        "output_contract": OUTPUT_CONTRACT,
        "news_scope": news_scope,
        "section_heading": section_heading,
        "source_pack": source_pack,
        "source_gate_result": gate_dict["verdict"],
        "source_gate_issues": gate_dict["issues"],
        "top_5_selection_result": selection,
        "output_schema_summary": _output_schema_summary(pid),
        "fixed_section_labels": _fixed_section_labels(pid),
        "forbidden_outputs": _forbidden_outputs_for_program(pid),
        "generation_instructions": _generation_instructions(pid, news_scope, section_heading),
        "operational_status": REQUIRED_OPERATIONAL_STATUS,
    }

    def _attach_recent_log_fields() -> None:
        base["sent_log_read_count"] = len(sent_log_rows)
        base["exposure_log_read_count"] = len(exposure_log_rows)
        base["exposure_log_read_ok"] = exposure_log_status["read_ok"]
        base["combined_recent_log_count"] = len(combined_recent_log)
        base["extra_recent_log_count"] = len(extra_rows)
        if not exposure_log_status["read_ok"]:
            base["exposure_log_read_error_code"] = exposure_log_status["error_code"]

    if selection.get("verdict") == "hold":
        base["prompt_status"] = "hold_review_required"
        base["top_5_news"] = None
        _attach_recent_log_fields()
        if isinstance(selection.get("candidate_funnel_summary"), dict):
            base["candidate_funnel_summary"] = selection["candidate_funnel_summary"]
        if selection.get("hold_reason"):
            base["hold_reason"] = selection["hold_reason"]
        if selection.get("cross_day_dedup_removed_count") is not None:
            base["cross_day_dedup_removed_count"] = selection["cross_day_dedup_removed_count"]
        hold_codes = [
            str(issue.get("code") or "")
            for issue in (selection.get("issues") or [])
            if isinstance(issue, dict) and issue.get("code")
        ]
        if hold_codes:
            base["prompt_hold_reason_codes"] = hold_codes
        return base

    if selection.get("verdict") != "pass":
        raise ValueError(f"Unexpected TOP 5 selection verdict: {selection.get('verdict')!r}")

    base["prompt_status"] = "ready_for_generation"
    top_5_news = dict(selection["top_5_news"])
    items = top_5_news.get("items") if isinstance(top_5_news.get("items"), list) else []
    # Safety-net cross-day dedup over the already-deduped, diversity-selected five.
    # This layer hard-blocks only customer-sent (+ reissue parent) items. Owner-
    # review-exposure duplicates are deliberately NOT re-filtered here: the
    # selection above already made the controlled backfill decision, and running
    # exposure dedup a second time would strip a legitimately backfilled item and
    # collapse the count below five. Customer-send remains the irreversible block.
    dedup_result = run_sent_news_dedup_gate(
        briefing_type=pid,
        candidates=[item for item in items if isinstance(item, dict)],
        sent_log_last_5_days=hard_block_rows,
        required_count=KEYSURI_TOP_NEWS_COUNT,
    )
    dedup_meta = metadata_from_gate_result(dedup_result, required_count=KEYSURI_TOP_NEWS_COUNT)
    deduped_items = dedup_meta["selected_items"]
    _attach_recent_log_fields()
    # Surface the intra-briefing diversity gate (same-source / entity / cluster
    # caps) applied during TOP5 selection, separate from the cross-day sent-log
    # dedup_summary above, so both layers are auditable in the run artifact.
    if isinstance(selection.get("diversity_summary"), dict):
        base["diversity_summary"] = selection["diversity_summary"]
        base["diversity_rejected_items"] = selection.get("diversity_rejected_items") or []
    if isinstance(selection.get("candidate_funnel_summary"), dict):
        base["candidate_funnel_summary"] = selection["candidate_funnel_summary"]
    if selection.get("cross_day_dedup_removed_count") is not None:
        base["cross_day_dedup_removed_count"] = selection["cross_day_dedup_removed_count"]
    # Internal-only backfill audit trail (never reader-facing). Surfaced so the
    # run artifact records that an owner-review-exposure duplicate was re-injected.
    if selection.get("exposure_backfill_used"):
        base["exposure_dedup_backfill_used"] = True
    selection_internal_codes = [
        str(code)
        for code in (selection.get("internal_issue_codes") or [])
        if code
    ]
    if selection_internal_codes:
        base["internal_issue_codes"] = selection_internal_codes

    # Final exactly-5 contract guard: never emit an under-count TOP5 to the
    # generation prompt. If the safety-net gate (defensively) reduced the count
    # below the required five, hold for review instead of prompting Gemini.
    if len(deduped_items) != KEYSURI_TOP_NEWS_COUNT:
        base["prompt_status"] = "hold_review_required"
        base["top_5_news"] = None
        base.update(dedup_meta)
        base["prompt_hold_reason_codes"] = ["insufficient_fresh_candidates_after_dedup"]
        base["top5_undercount_after_safety_dedup"] = len(deduped_items)
        return base

    top_5_news["items"] = deduped_items
    base["top_5_news"] = top_5_news
    base.update(dedup_meta)
    return base
