"""Kee-Suri private briefing output schema and validation (foundation — not wired to runtime)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from keysuri_news_contract import (
    PROGRAM_TO_HEADING as TOP5_HEADING_BY_PROGRAM,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    validate_top_5_news_block,
)

KeysuriBriefingVerdict = Literal["pass", "block"]

KEYSURI_PROGRAM_IDS = frozenset({"keysuri_global_tech", "keysuri_korea_tech"})

SECTION_DEEP_DIVE = "키수리의 딥-다이브"
SECTION_ONE_LINE = "원-라인 체크포인트"
SECTION_CLOSING = "마무리 및 출처 리스트"

FORBIDDEN_SECTION_RENAMES: Dict[str, Tuple[str, ...]] = {
    "deep_dive": ("심층 분석",),
    "one_line_checkpoint": ("핵심 요약",),
    "closing_sources": ("출처",),
    "top_5_news": ("TOP 5", "Top 5", "top 5"),
}

REQUIRED_OPERATIONAL_STATUS = "review_required"

CONFIDENCE_LABELS = frozenset(
    {"confirmed", "reported", "claimed", "estimated", "unverified"}
)


@dataclass(frozen=True)
class KeysuriBriefingIssue:
    code: str
    message: str
    field: Optional[str] = None


@dataclass(frozen=True)
class KeysuriBriefingValidationResult:
    verdict: KeysuriBriefingVerdict
    issues: Tuple[KeysuriBriefingIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.verdict == "pass"


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_object(
    payload: Dict[str, Any],
    key: str,
    issues: List[KeysuriBriefingIssue],
) -> Optional[Dict[str, Any]]:
    value = payload.get(key)
    if isinstance(value, str):
        issues.append(
            KeysuriBriefingIssue(
                code=f"{key}_must_be_object",
                message=f"{key} must be an object, not a plain string",
                field=key,
            )
        )
        return None
    if not isinstance(value, dict):
        issues.append(
            KeysuriBriefingIssue(
                code=f"{key}_missing_or_invalid",
                message=f"{key} must be a non-empty object",
                field=key,
            )
        )
        return None
    return value


def _check_section_heading(
    section: Dict[str, Any],
    *,
    field_key: str,
    expected: str,
    issues: List[KeysuriBriefingIssue],
) -> None:
    heading = section.get("section_heading")
    if not _is_non_empty_str(heading):
        issues.append(
            KeysuriBriefingIssue(
                code=f"{field_key}_heading_missing",
                message=f"{field_key}.section_heading is required",
                field=f"{field_key}.section_heading",
            )
        )
        return
    heading_s = heading.strip()
    if heading_s != expected:
        issues.append(
            KeysuriBriefingIssue(
                code=f"{field_key}_heading_wrong",
                message=(
                    f"{field_key}.section_heading must be exactly {expected!r}, "
                    f"got {heading_s!r}"
                ),
                field=f"{field_key}.section_heading",
            )
        )
    forbidden = FORBIDDEN_SECTION_RENAMES.get(field_key, ())
    if heading_s in forbidden:
        issues.append(
            KeysuriBriefingIssue(
                code=f"{field_key}_heading_forbidden_rename",
                message=f"{field_key}.section_heading uses forbidden renamed label {heading_s!r}",
                field=f"{field_key}.section_heading",
            )
        )


def validate_keysuri_private_briefing(
    output: dict,
    *,
    program_id: str,
) -> KeysuriBriefingValidationResult:
    """Validate Kee-Suri private briefing JSON against fixed section terminology."""
    issues: List[KeysuriBriefingIssue] = []

    if not isinstance(output, dict):
        return KeysuriBriefingValidationResult(
            verdict="block",
            issues=(
                KeysuriBriefingIssue(
                    code="invalid_output",
                    message="Output must be a dict",
                ),
            ),
        )

    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        issues.append(
            KeysuriBriefingIssue(
                code="unsupported_program_id",
                message=f"Unsupported program_id: {program_id!r}",
                field="program_id",
            )
        )
        return KeysuriBriefingValidationResult(verdict="block", issues=tuple(issues))

    op_status = str(output.get("operational_status") or "").strip()
    if op_status != REQUIRED_OPERATIONAL_STATUS:
        issues.append(
            KeysuriBriefingIssue(
                code="operational_status_wrong",
                message=(
                    f"operational_status must be {REQUIRED_OPERATIONAL_STATUS!r}, "
                    f"got {op_status!r}"
                ),
                field="operational_status",
            )
        )

    top5 = _require_object(output, "top_5_news", issues)
    if top5 is not None:
        for news_issue in validate_top_5_news_block(pid, top5):
            issues.append(
                KeysuriBriefingIssue(
                    code=news_issue["code"],
                    message=news_issue["message"],
                    field=news_issue.get("field"),
                )
            )

    deep = _require_object(output, "deep_dive", issues)
    if deep is not None:
        _check_section_heading(
            deep,
            field_key="deep_dive",
            expected=SECTION_DEEP_DIVE,
            issues=issues,
        )
        if not _is_non_empty_str(deep.get("body")):
            issues.append(
                KeysuriBriefingIssue(
                    code="deep_dive_body_missing",
                    message="deep_dive.body is required",
                    field="deep_dive.body",
                )
            )
        implications = deep.get("key_implications")
        if not isinstance(implications, list) or not all(
            _is_non_empty_str(x) for x in implications
        ):
            issues.append(
                KeysuriBriefingIssue(
                    code="deep_dive_key_implications_invalid",
                    message="deep_dive.key_implications must be a non-empty list of strings",
                    field="deep_dive.key_implications",
                )
            )
        source_ids = deep.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            issues.append(
                KeysuriBriefingIssue(
                    code="deep_dive_source_ids_missing",
                    message="deep_dive.source_ids must be a non-empty list",
                    field="deep_dive.source_ids",
                )
            )
        confidence = str(deep.get("confidence_label") or "").strip()
        if confidence not in CONFIDENCE_LABELS:
            issues.append(
                KeysuriBriefingIssue(
                    code="deep_dive_confidence_invalid",
                    message=f"deep_dive.confidence_label must be one of {sorted(CONFIDENCE_LABELS)}",
                    field="deep_dive.confidence_label",
                )
            )

    checkpoint = _require_object(output, "one_line_checkpoint", issues)
    if checkpoint is not None:
        _check_section_heading(
            checkpoint,
            field_key="one_line_checkpoint",
            expected=SECTION_ONE_LINE,
            issues=issues,
        )
        if not _is_non_empty_str(checkpoint.get("body")):
            issues.append(
                KeysuriBriefingIssue(
                    code="one_line_checkpoint_body_missing",
                    message="one_line_checkpoint.body is required",
                    field="one_line_checkpoint.body",
                )
            )

    closing = _require_object(output, "closing_sources", issues)
    if closing is not None:
        _check_section_heading(
            closing,
            field_key="closing_sources",
            expected=SECTION_CLOSING,
            issues=issues,
        )
        if not _is_non_empty_str(closing.get("closing_message")):
            issues.append(
                KeysuriBriefingIssue(
                    code="closing_sources_message_missing",
                    message="closing_sources.closing_message is required",
                    field="closing_sources.closing_message",
                )
            )
        source_list = closing.get("source_list")
        if not isinstance(source_list, list) or len(source_list) == 0:
            issues.append(
                KeysuriBriefingIssue(
                    code="closing_sources_list_missing",
                    message="closing_sources.source_list must be a non-empty list",
                    field="closing_sources.source_list",
                )
            )
        elif not all(isinstance(entry, dict) for entry in source_list):
            issues.append(
                KeysuriBriefingIssue(
                    code="closing_sources_list_invalid",
                    message="closing_sources.source_list entries must be objects",
                    field="closing_sources.source_list",
                )
            )

    verdict: KeysuriBriefingVerdict = "block" if issues else "pass"
    return KeysuriBriefingValidationResult(verdict=verdict, issues=tuple(issues))


def _example_top5_item(rank: int, *, news_id: str, category: str) -> Dict[str, Any]:
    return {
        "rank": rank,
        "news_id": news_id,
        "headline": "Example headline",
        "category": category,
        "summary": "Example summary grounded in staged source pack.",
        "why_it_matters": "Example why-it-matters for owner review.",
        "business_implication": "Example business implication for money/work decisions.",
        "source_ids": ["example-source-id"],
        "confidence_label": "reported",
    }


def keysuri_output_schema_example(program_id: str) -> Dict[str, Any]:
    """Return a structural example with exact required section headings."""
    from keysuri_news_contract import PROGRAM_TO_SCOPE, expected_news_scope_for_program

    top5_heading = TOP5_HEADING_BY_PROGRAM.get(program_id, SECTION_TOP5_GLOBAL)
    scope = PROGRAM_TO_SCOPE.get(program_id, expected_news_scope_for_program("keysuri_global_tech"))
    categories = ["ai_product", "bigtech", "semiconductor", "platform", "policy"]
    return {
        "program_id": program_id,
        "operational_status": REQUIRED_OPERATIONAL_STATUS,
        "top_5_news": {
            "news_scope": scope,
            "section_heading": top5_heading,
            "items": [
                _example_top5_item(i + 1, news_id=f"example-news-{i + 1}", category=categories[i])
                for i in range(5)
            ],
        },
        "deep_dive": {
            "section_heading": SECTION_DEEP_DIVE,
            "body": "string",
            "key_implications": ["string"],
            "source_ids": ["source_id"],
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": SECTION_ONE_LINE,
            "body": "string",
        },
        "closing_sources": {
            "section_heading": SECTION_CLOSING,
            "closing_message": "string",
            "source_list": [
                {
                    "source_id": "string",
                    "source_name": "string",
                    "source_url": "https://example.com/source/example",
                }
            ],
        },
    }
