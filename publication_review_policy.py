"""Shared publication review policy for GENIE/KeeSuri.

Explicitly classifies known harmless editorial findings as nonblocking while
preserving all automated diagnostics. Unknown findings, factual/source/
number/date/rights/privacy/security/internal leak/missing required content
remain strictly blocking/review-required.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence, Tuple

# Known harmless validator editorial-only findings (Requirement 1)
VALIDATOR_EDITORIAL_ONLY_CODES: frozenset[str] = frozenset({
    "weak_opening",
    "meta_lead_opening",
    "template_title",
    "repetitive_market_generalities",
    "generic_finance_filler",
    "low_summary_density",
    "low_watchpoint_density",
    "low_interpretation_density",
    "low_risk_density",
    "summary_lecture_tail",
    "watchpoint_lecture_tail",
    "risk_lecture_tail",
    "closing_lecture_tail",
    "today_replay_edition_label_warning",
})

# Known harmless surface editorial-only findings (Requirement 1)
SURFACE_EDITORIAL_ONLY_CODES: frozenset[str] = frozenset({
    "customer_surface_mixed_sentence_end_style",
    "customer_surface_repeated_sentence_skeleton",
    "customer_surface_repeated_canned_bridge",
    "customer_surface_duplicate_filler",
    "global_visible_repeated_low_information_label",
    "today_replay_edition_label_warning",
})

ALL_HARMLESS_EDITORIAL_CODES: frozenset[str] = (
    VALIDATOR_EDITORIAL_ONLY_CODES | SURFACE_EDITORIAL_ONLY_CODES
)

# Replay edition-label paths ONLY (Requirement 3)
REPLAY_EDITION_LABEL_PATHS: frozenset[str] = frozenset({
    "title",
    "channel_drafts.email_subject",
    "channel_drafts.naver_blog_title",
})

# Temporal instruction patterns for distinguishing label vs instruction
_TIME_WINDOW = r"(?:첫\s*30\s*분|장\s*초반|장전|개장\s*전)"
_PAST_WINDOW = re.compile(r"(?:전일|어제|지난\s*거래일|당시)\s*(?:개장\s*후\s*)?" + _TIME_WINDOW)
_COMPLETED_WINDOW = re.compile(
    _TIME_WINDOW + r"\s*(?:에\s*)?(?:발표|공개|집계|관측|확인|확정|발생|기록)(?:된|한|됐|되었)"
)
_START_INSTRUCTION = re.compile(
    r"장을\s*시작(?:해야|하겠|합시다|하세요|합니다|할\s*준비(?:를)?\s*하세요)"
)
_ADVICE = (
    r"(?:(?:확인|점검|관찰|체크|정리|대비|준비|재정렬)"
    r"(?:해야|하겠|합니다|하세요|합시다|해\s*(?:보세요|봅시다|주세요)|할\s*(?:필요|예정|수))"
    r"|(?:살펴|지켜)(?:봅니다|보세요|봐야|보겠|볼\s*필요))"
)
_EDITION_LABEL_MASK = re.compile(
    r"\[[^\]]*?(?:장전|개장\s*전)[^\]]*?\]"
    r"|(?:\[재발행\]\s*)?(?:\d{1,2}\s*월\s*\d{1,2}\s*일\s*(?:장전|개장\s*전)\s*[:\-])"
    r"|(?:오늘의\s*지니\s*)?(?:장전|개장\s*전)\s*브리핑"
)
_WINDOW_INSTRUCTION = re.compile(_TIME_WINDOW + r"[^.!?\n]*" + _ADVICE)
_PREOPEN_FORECAST = re.compile(
    r"(?:오늘\s+)?(?:장전|개장\s*전)(?:에서는|에는|에서)|개장을\s*앞두고"
)


def is_validator_editorial_finding(code: str) -> bool:
    """Whether a validator issue code is explicitly classified as harmless editorial."""
    return str(code or "").strip() in VALIDATOR_EDITORIAL_ONLY_CODES


def is_surface_editorial_finding(code: str) -> bool:
    """Whether a surface issue code is explicitly classified as harmless editorial."""
    return str(code or "").strip() in SURFACE_EDITORIAL_ONLY_CODES


def is_harmless_editorial_code(code: str) -> bool:
    """Whether an issue code is classified as harmless editorial across all contracts."""
    return str(code or "").strip() in ALL_HARMLESS_EDITORIAL_CODES


def is_replay_edition_label_path(path: str) -> bool:
    """Check if the path is strictly an edition-label path."""
    return str(path or "").strip() in REPLAY_EDITION_LABEL_PATHS


def is_temporal_instruction_or_forecast(text: str) -> bool:
    """True if text contains an active temporal instruction or future forecast, not bare edition label."""
    if not isinstance(text, str) or not text.strip():
        return False
    inspected = _PAST_WINDOW.sub("과거 시간대", text)
    inspected = _COMPLETED_WINDOW.sub("완료된 사건", inspected)
    inspected = _EDITION_LABEL_MASK.sub("판본라벨", inspected)
    return bool(
        _START_INSTRUCTION.search(inspected)
        or _WINDOW_INSTRUCTION.search(inspected)
        or _PREOPEN_FORECAST.search(inspected)
    )


def classify_validator_issues(
    issues: Iterable[Any],
) -> Tuple[list[str], list[str]]:
    """Return (blocking_issue_codes, editorial_warning_codes)."""
    blocking: list[str] = []
    editorial: list[str] = []
    for issue in issues:
        code = str(getattr(issue, "code", None) or (issue.get("code") if isinstance(issue, dict) else issue) or "").strip()
        if not code:
            continue
        if is_validator_editorial_finding(code):
            editorial.append(code)
        else:
            blocking.append(code)
    return blocking, editorial


def classify_surface_findings(
    findings: Iterable[Any],
) -> Tuple[list[str], list[str]]:
    """Return (blocking_issue_codes, editorial_warning_codes)."""
    blocking: list[str] = []
    editorial: list[str] = []
    for finding in findings:
        code = str(getattr(finding, "code", None) or (finding.get("code") if isinstance(finding, dict) else finding) or "").strip()
        if not code:
            continue
        if is_surface_editorial_finding(code):
            editorial.append(code)
        else:
            blocking.append(code)
    return blocking, editorial


def are_all_editorial_harmless(codes: Iterable[str]) -> bool:
    """Whether all non-empty codes in the iterable belong to known harmless editorial codes."""
    code_list = [str(c or "").strip() for c in codes if str(c or "").strip()]
    if not code_list:
        return False
    return all(is_harmless_editorial_code(c) for c in code_list)
