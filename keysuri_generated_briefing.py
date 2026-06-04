"""Kee-Suri generated briefing adapter contract (offline — not wired to runtime)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from keysuri_news_contract import (
    KEYSURI_PROGRAM_IDS,
    expected_news_scope_for_program,
    expected_top5_heading_for_program,
    validate_top_5_news_block,
)
from keysuri_private_briefing import (
    REQUIRED_OPERATIONAL_STATUS,
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
)
from keysuri_source_gate import CONFIDENCE_LABELS

GENERATED_STATUS_REQUIRED = "generated_review_required"

FORBIDDEN_IDENTITY_STRINGS = ("테크 앵커", "뉴스 앵커", "아나운서")
FORBIDDEN_RETIRED_STRINGS = ("Tomorrow_Geenee", "tomorrow_genie", "18:00")


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _collect_strings(value: Any, out: List[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_strings(v, out)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, out)


def _top5_sequence(top_5_news: dict) -> List[Tuple[int, str]]:
    items = top_5_news.get("items") if isinstance(top_5_news.get("items"), list) else []
    seq: List[Tuple[int, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            rank = -1
        news_id = str(item.get("news_id") or "").strip()
        seq.append((rank, news_id))
    return seq


def _allowed_source_ids(prompt_input: Optional[dict], top_5_news: dict) -> Set[str]:
    allowed: Set[str] = set()
    if prompt_input and isinstance(prompt_input.get("source_pack"), dict):
        sources = prompt_input["source_pack"].get("sources")
        if isinstance(sources, list):
            for src in sources:
                if isinstance(src, dict):
                    sid = str(src.get("source_id") or "").strip()
                    if sid:
                        allowed.add(sid)
    items = top_5_news.get("items") if isinstance(top_5_news.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        for sid in item.get("source_ids") or []:
            s = str(sid).strip()
            if s:
                allowed.add(s)
    return allowed


def load_keysuri_generated_briefing_fixture(path: str) -> dict:
    """Load a generated briefing JSON fixture from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Fixture must be a JSON object: {path}")
    return data


def validate_keysuri_generated_briefing(
    program_id: str,
    generated_briefing: dict,
    prompt_input: dict | None = None,
) -> List[dict]:
    """Validate a staged/generated Kee-Suri briefing object. Returns issue dicts (empty if ok)."""
    issues: List[dict] = []
    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        issues.append(_issue("unsupported_program_id", f"Unsupported program_id: {program_id!r}", "program_id"))
        return issues

    if not isinstance(generated_briefing, dict):
        issues.append(
            _issue("generated_briefing_invalid", "generated_briefing must be a dict", "generated_briefing")
        )
        return issues

    gb_pid = str(generated_briefing.get("program_id") or "").strip()
    if gb_pid != pid:
        issues.append(
            _issue(
                "program_id_mismatch",
                f"generated_briefing.program_id {gb_pid!r} does not match {pid!r}",
                "program_id",
            )
        )

    expected_scope = expected_news_scope_for_program(pid)
    scope = str(generated_briefing.get("news_scope") or "").strip()
    if scope != expected_scope:
        issues.append(
            _issue(
                "news_scope_mismatch",
                f"news_scope must be {expected_scope!r}, got {scope!r}",
                "news_scope",
            )
        )

    expected_heading = expected_top5_heading_for_program(pid)
    heading = str(generated_briefing.get("section_heading") or "").strip()
    if heading != expected_heading:
        issues.append(
            _issue(
                "section_heading_mismatch",
                f"section_heading must be {expected_heading!r}, got {heading!r}",
                "section_heading",
            )
        )

    gen_status = str(generated_briefing.get("generated_status") or "").strip()
    if gen_status != GENERATED_STATUS_REQUIRED:
        issues.append(
            _issue(
                "generated_status_invalid",
                f"generated_status must be {GENERATED_STATUS_REQUIRED!r}",
                "generated_status",
            )
        )

    op_status = str(generated_briefing.get("operational_status") or "").strip()
    if op_status != REQUIRED_OPERATIONAL_STATUS:
        issues.append(
            _issue(
                "operational_status_invalid",
                f"operational_status must be {REQUIRED_OPERATIONAL_STATUS!r}",
                "operational_status",
            )
        )

    top_5 = generated_briefing.get("top_5_news")
    if not isinstance(top_5, dict):
        issues.append(_issue("top_5_news_missing", "top_5_news must be an object", "top_5_news"))
    else:
        for block_issue in validate_top_5_news_block(pid, top_5):
            issues.append(
                _issue(
                    block_issue.get("code", "top_5_news_invalid"),
                    block_issue.get("message", "top_5_news validation failed"),
                    block_issue.get("field", "top_5_news"),
                )
            )

        if prompt_input and isinstance(prompt_input.get("top_5_news"), dict):
            expected_seq = _top5_sequence(prompt_input["top_5_news"])
            actual_seq = _top5_sequence(top_5)
            if expected_seq != actual_seq:
                issues.append(
                    _issue(
                        "top_5_sequence_mismatch",
                        "top_5_news rank/news_id sequence must match prompt_input",
                        "top_5_news.items",
                    )
                )
            if len(actual_seq) != 5:
                issues.append(
                    _issue(
                        "top_5_item_count_invalid",
                        f"top_5_news must have exactly 5 items, got {len(actual_seq)}",
                        "top_5_news.items",
                    )
                )

    allowed_sources = _allowed_source_ids(prompt_input, top_5 if isinstance(top_5, dict) else {})

    deep = generated_briefing.get("deep_dive")
    if not isinstance(deep, dict):
        issues.append(_issue("deep_dive_missing", "deep_dive must be an object", "deep_dive"))
    else:
        if str(deep.get("section_heading") or "").strip() != SECTION_DEEP_DIVE:
            issues.append(
                _issue(
                    "deep_dive_heading_invalid",
                    f"deep_dive.section_heading must be {SECTION_DEEP_DIVE!r}",
                    "deep_dive.section_heading",
                )
            )
        if not _is_non_empty_str(deep.get("body")):
            issues.append(_issue("deep_dive_body_empty", "deep_dive.body is required", "deep_dive.body"))
        implications = deep.get("key_implications")
        if not isinstance(implications, list) or not implications:
            issues.append(
                _issue(
                    "deep_dive_key_implications_empty",
                    "deep_dive.key_implications must be a non-empty list",
                    "deep_dive.key_implications",
                )
            )
        elif not all(_is_non_empty_str(x) for x in implications):
            issues.append(
                _issue(
                    "deep_dive_key_implications_invalid",
                    "deep_dive.key_implications entries must be non-empty strings",
                    "deep_dive.key_implications",
                )
            )
        source_ids = deep.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            issues.append(
                _issue(
                    "deep_dive_source_ids_empty",
                    "deep_dive.source_ids must be a non-empty list",
                    "deep_dive.source_ids",
                )
            )
        else:
            for sid in source_ids:
                s = str(sid).strip()
                if prompt_input and allowed_sources and s not in allowed_sources:
                    issues.append(
                        _issue(
                            "deep_dive_source_id_invalid",
                            f"deep_dive source_id not in prompt pack/top5: {s!r}",
                            "deep_dive.source_ids",
                        )
                    )
        confidence = str(deep.get("confidence_label") or "").strip()
        if confidence not in CONFIDENCE_LABELS:
            issues.append(
                _issue(
                    "deep_dive_confidence_invalid",
                    f"deep_dive.confidence_label invalid: {confidence!r}",
                    "deep_dive.confidence_label",
                )
            )
        elif confidence == "unverified":
            issues.append(
                _issue(
                    "deep_dive_confidence_unverified",
                    "deep_dive.confidence_label cannot be unverified",
                    "deep_dive.confidence_label",
                )
            )

    one_line = generated_briefing.get("one_line_checkpoint")
    if not isinstance(one_line, dict):
        issues.append(
            _issue("one_line_checkpoint_missing", "one_line_checkpoint must be an object", "one_line_checkpoint")
        )
    else:
        if str(one_line.get("section_heading") or "").strip() != SECTION_ONE_LINE:
            issues.append(
                _issue(
                    "one_line_heading_invalid",
                    f"one_line_checkpoint.section_heading must be {SECTION_ONE_LINE!r}",
                    "one_line_checkpoint.section_heading",
                )
            )
        if not _is_non_empty_str(one_line.get("body")):
            issues.append(
                _issue("one_line_body_empty", "one_line_checkpoint.body is required", "one_line_checkpoint.body")
            )

    closing = generated_briefing.get("closing_sources")
    if not isinstance(closing, dict):
        issues.append(
            _issue("closing_sources_missing", "closing_sources must be an object", "closing_sources")
        )
    else:
        if str(closing.get("section_heading") or "").strip() != SECTION_CLOSING:
            issues.append(
                _issue(
                    "closing_heading_invalid",
                    f"closing_sources.section_heading must be {SECTION_CLOSING!r}",
                    "closing_sources.section_heading",
                )
            )
        if not _is_non_empty_str(closing.get("closing_message")):
            issues.append(
                _issue(
                    "closing_message_empty",
                    "closing_sources.closing_message is required",
                    "closing_sources.closing_message",
                )
            )
        source_list = closing.get("source_list")
        if not isinstance(source_list, list) or not source_list:
            issues.append(
                _issue(
                    "closing_source_list_empty",
                    "closing_sources.source_list must be a non-empty list",
                    "closing_sources.source_list",
                )
            )
        else:
            for i, entry in enumerate(source_list):
                if not isinstance(entry, dict):
                    issues.append(
                        _issue(
                            "closing_source_entry_invalid",
                            "closing_sources.source_list entries must be objects",
                            f"closing_sources.source_list[{i}]",
                        )
                    )
                    continue
                sid = str(entry.get("source_id") or "").strip()
                if not sid:
                    issues.append(
                        _issue(
                            "closing_source_id_missing",
                            "source_list entry requires source_id",
                            f"closing_sources.source_list[{i}].source_id",
                        )
                    )
                elif prompt_input and allowed_sources and sid not in allowed_sources:
                    issues.append(
                        _issue(
                            "closing_source_id_invalid",
                            f"closing source_id not in prompt pack/top5: {sid!r}",
                            f"closing_sources.source_list[{i}].source_id",
                        )
                    )
                if not _is_non_empty_str(entry.get("label")):
                    issues.append(
                        _issue(
                            "closing_source_label_missing",
                            "source_list entry requires label",
                            f"closing_sources.source_list[{i}].label",
                        )
                    )

    texts: List[str] = []
    _collect_strings(generated_briefing, texts)
    blob = "\n".join(texts)
    for forbidden in FORBIDDEN_IDENTITY_STRINGS:
        if forbidden in blob:
            issues.append(
                _issue(
                    "forbidden_identity_string",
                    f"Generated briefing must not contain {forbidden!r}",
                    "generated_briefing",
                )
            )
    for retired in FORBIDDEN_RETIRED_STRINGS:
        if retired in blob:
            issues.append(
                _issue(
                    "forbidden_retired_reference",
                    f"Generated briefing must not contain {retired!r}",
                    "generated_briefing",
                )
            )

    return issues


def build_keysuri_generated_briefing_preview_payload(
    prompt_input: dict,
    generated_briefing: dict | None = None,
) -> dict:
    """Build a renderer-ready payload merging prompt_input and optional generated briefing."""
    if not isinstance(prompt_input, dict):
        raise ValueError("prompt_input must be a dict")

    payload: Dict[str, Any] = dict(prompt_input)
    payload["generation_mode"] = "pending" if generated_briefing is None else "generated"

    if generated_briefing is None:
        payload["generated_briefing"] = None
        payload["generated_status"] = None
        payload["generated_validation_issues"] = []
        return payload

    if not isinstance(generated_briefing, dict):
        raise ValueError("generated_briefing must be a dict")

    pid = str(prompt_input.get("program_id") or generated_briefing.get("program_id") or "").strip()
    issues = validate_keysuri_generated_briefing(pid, generated_briefing, prompt_input)
    payload["generated_briefing"] = generated_briefing
    payload["generated_status"] = generated_briefing.get("generated_status")
    payload["generated_validation_issues"] = issues
    return payload
