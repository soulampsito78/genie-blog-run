from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal

GateResultType = Literal["pass", "draft_only", "block"]


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class ValidationResult:
    result: GateResultType
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.result in ("pass", "draft_only")


FORBIDDEN_FINANCE_PHRASES = [
    "무조건 오른다",
    "확정 수익",
    "수익 보장",
    "반드시 오른다",
    "지금 사야 한다",
    "매수 확정",
]


def validate_common_structure(data: Dict[str, Any], mode: str) -> ValidationResult:
    issues: List[ValidationIssue] = []

    required_base = [
        "mode",
        "title",
        "summary",
        "greeting",
        "closing_message",
        "hashtags",
        "channel_drafts",
    ]
    for key in required_base:
        if key not in data:
            issues.append(ValidationIssue("missing_key", f"필수 키 누락: {key}", "error"))

    if data.get("mode") != mode:
        issues.append(ValidationIssue("invalid_mode", f"mode 불일치: {data.get('mode')}", "error"))

    title = data.get("title", "")
    if not isinstance(title, str) or not title.strip():
        issues.append(ValidationIssue("missing_title", "title 비어 있음", "error"))

    hashtags = data.get("hashtags", [])
    if not isinstance(hashtags, list) or len(hashtags) < 1:
        issues.append(ValidationIssue("missing_hashtags", "hashtags 누락 또는 비정상", "error"))

    channel_drafts = data.get("channel_drafts", {})
    if not isinstance(channel_drafts, dict):
        issues.append(ValidationIssue("missing_channel_drafts", "channel_drafts 비정상", "error"))
    else:
        if not channel_drafts.get("email_subject"):
            issues.append(ValidationIssue("missing_email_subject", "email_subject 누락", "error"))
        if not channel_drafts.get("naver_blog_title"):
            issues.append(ValidationIssue("missing_naver_title", "naver_blog_title 누락", "error"))

    if issues:
        return ValidationResult(result="block", issues=issues)
    return ValidationResult(result="pass", issues=issues)


def _basis_invalid(items: list, required_fields: List[str]) -> bool:
    for item in items:
        if not isinstance(item, dict):
            return True
        if item.get("basis") not in ("fact", "interpretation", "speculation"):
            return True
        for field_name in required_fields:
            if not item.get(field_name):
                return True
    return False


def validate_today_genie(data: Dict[str, Any], runtime_input: Dict[str, Any]) -> ValidationResult:
    common = validate_common_structure(data, "today_genie")
    if common.result == "block":
        return common

    issues = list(common.issues)

    today_keys = [
        "market_setup",
        "market_snapshot",
        "key_watchpoints",
        "opportunities",
        "risk_check",
        "image_prompt_studio",
        "image_prompt_outdoor",
    ]
    for key in today_keys:
        if key not in data:
            issues.append(ValidationIssue("missing_key", f"today 필수 키 누락: {key}", "error"))

    required_inputs = ["overnight_us_market", "macro_indicators", "top_market_news", "risk_factors"]
    missing_inputs = [k for k in required_inputs if not runtime_input.get(k)]
    if missing_inputs:
        issues.append(
            ValidationIssue(
                "input_insufficient",
                f"핵심 입력 부족: {', '.join(missing_inputs)}",
                "warning",
            )
        )

    if not data.get("image_prompt_studio"):
        issues.append(ValidationIssue("missing_image_prompt", "today 스튜디오 이미지 프롬프트 누락", "error"))
    if not data.get("image_prompt_outdoor"):
        issues.append(ValidationIssue("missing_image_prompt", "today 야외 이미지 프롬프트 누락", "error"))

    text_blobs = [
        data.get("title", ""),
        data.get("summary", ""),
        data.get("market_setup", ""),
        data.get("closing_message", ""),
    ]
    for item in data.get("key_watchpoints", []):
        if isinstance(item, dict):
            text_blobs.append(item.get("headline", ""))
            text_blobs.append(item.get("detail", ""))

    joined = "\n".join(text_blobs)
    for phrase in FORBIDDEN_FINANCE_PHRASES:
        if phrase in joined:
            issues.append(ValidationIssue("forbidden_finance_phrase", f"금지 표현 탐지: {phrase}", "error"))

    if _basis_invalid(data.get("market_snapshot", []), ["label", "value"]):
        issues.append(ValidationIssue("invalid_market_snapshot", "market_snapshot 구조 오류", "error"))
    if _basis_invalid(data.get("key_watchpoints", []), ["headline", "detail"]):
        issues.append(ValidationIssue("invalid_watchpoints", "key_watchpoints 구조 오류", "error"))
    if _basis_invalid(data.get("opportunities", []), ["theme", "reason"]):
        issues.append(ValidationIssue("invalid_opportunities", "opportunities 구조 오류", "error"))
    if _basis_invalid(data.get("risk_check", []), ["risk", "detail"]):
        issues.append(ValidationIssue("invalid_risk_check", "risk_check 구조 오류", "error"))

    has_error = any(i.severity == "error" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)

    if has_error:
        return ValidationResult(result="block", issues=issues)
    if has_warning:
        return ValidationResult(result="draft_only", issues=issues)
    return ValidationResult(result="pass", issues=issues)


def validate_tomorrow_genie(data: Dict[str, Any], runtime_input: Dict[str, Any]) -> ValidationResult:
    common = validate_common_structure(data, "tomorrow_genie")
    if common.result == "block":
        return common

    issues = list(common.issues)

    tomorrow_keys = [
        "weather_summary_block",
        "weather_briefing",
        "outfit_recommendation",
        "lifestyle_notes",
        "zodiac_fortunes",
        "image_prompt_studio",
        "image_prompt_outdoor",
    ]
    for key in tomorrow_keys:
        if key not in data:
            issues.append(ValidationIssue("missing_key", f"tomorrow 필수 키 누락: {key}", "error"))

    weather_context = runtime_input.get("weather_context", {})
    if not weather_context:
        issues.append(ValidationIssue("weather_input_missing", "weather_context 누락", "warning"))

    if not data.get("image_prompt_studio"):
        issues.append(ValidationIssue("missing_image_prompt", "tomorrow 스튜디오 이미지 프롬프트 누락", "error"))
    if not data.get("image_prompt_outdoor"):
        issues.append(ValidationIssue("missing_image_prompt", "tomorrow 야외 이미지 프롬프트 누락", "error"))

    zodiac = data.get("zodiac_fortunes", [])
    if not isinstance(zodiac, list) or len(zodiac) != 12:
        issues.append(ValidationIssue("invalid_zodiac_count", "운세는 12개여야 함", "error"))

    deterministic_bad = ["반드시", "무조건", "확정", "운명적으로 정해진"]
    for item in zodiac:
        if isinstance(item, dict):
            fortune = item.get("fortune", "")
            if any(bad in fortune for bad in deterministic_bad):
                issues.append(ValidationIssue("deterministic_fortune", "운세가 과도하게 결정론적임", "error"))

    has_error = any(i.severity == "error" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)

    if has_error:
        return ValidationResult(result="block", issues=issues)
    if has_warning:
        return ValidationResult(result="draft_only", issues=issues)
    return ValidationResult(result="pass", issues=issues)


