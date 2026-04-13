from __future__ import annotations

import re
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

INTERNAL_LEAK_TERMS = (
    "e2e",
    "qa",
    "스테이징",
    "staging",
    "검증용",
    "내부 테스트",
    "시스템 안내",
    "테스트 스캐폴드",
    "placeholder",
)

# Customer-facing today_genie: pipeline / placeholder / "status of the data" copy (not conservative briefing).
NON_BRIEFING_HARD_PHRASES = (
    "현재 제공되는 정보",
    "제공되는 정보는",
    "초기 단계의 데이터",
    "초기 단계 데이터",
    "임시 수치",
    "파이프라인 테스트",
    "파이프라인 점검",
    "테스트 목적",
    "스테이징 환경",
)

NON_BRIEFING_SOFT_PHRASES = (
    "전반적인 흐름을 파악",
    "전반적 흐름을 파악",
    "전반적인 흐름 파악",
)

_PREP_NOTICE_PHRASES = ("준비를 하겠습니다", "준비하겠습니다")

WEAK_TITLE_PATTERNS = (
    "오늘의 장전 브리핑",
    "장전 브리핑",
    "시장 브리핑",
    "모닝 브리핑",
)

META_OPENING_PATTERNS = (
    "안녕하세요",
    "좋은 아침",
    "오늘은",
    "본 브리핑",
    "아래는",
    "요약하면",
    "이번 브리핑",
)

GENERIC_FINANCE_PHRASES = (
    "변동성에 유의",
    "관망이 필요",
    "신중한 접근",
    "보수적 대응",
    "추가 확인이 필요",
    "시장 상황을 주시",
    "리스크 관리",
)

DECISION_HINT_TERMS = (
    "기준",
    "우선",
    "보류",
    "확인",
    "관찰",
    "대응",
    "비중",
    "손절",
    "익절",
    "진입",
    "유지",
    "축소",
)

ASSERTIVE_TONE_TERMS = (
    "분명",
    "확실",
    "명확한 추세",
    "강하게",
    "주도할",
    "유력",
    "단정",
)

UNCERTAINTY_TONE_TERMS = (
    "불확실",
    "제한적",
    "확인 필요",
    "보수적",
    "단정 어렵",
    "가능성",
)

INTERPRETATION_CUE_TERMS = (
    "때문",
    "영향",
    "의미",
    "시사",
    "관건",
    "시나리오",
    "전제",
    "경로",
)

SPECIFICITY_TOKENS = (
    "지수",
    "금리",
    "환율",
    "국채",
    "유가",
    "달러",
    "연준",
    "cpi",
    "pce",
    "실적",
    "업종",
    "종목",
)

THIN_INPUT_STATUSES = ("none", "partial")


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


def _norm_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[.!?。\n]+", text) if s.strip()]


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in patterns)


def _evasive_prep_notice_in_field(text: str) -> bool:
    """'준비하겠습니다' 등이 거래·대응 맥락 없이 파이프라인형으로 쓰인 경우만 잡는다."""
    for sent in _split_sentences(text):
        if not any(p in sent for p in _PREP_NOTICE_PHRASES):
            continue
        if _has_any(sent, DECISION_HINT_TERMS):
            continue
        if _specificity_score(sent) < 2:
            return True
    return False


def _count_any(text: str, patterns: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(1 for p in patterns if p.lower() in low)


def _count_digits(text: str) -> int:
    return len(re.findall(r"\d", text))


def _joined_today_editorial_text(data: Dict[str, Any]) -> str:
    blobs: List[str] = [
        _norm_text(data.get("title", "")),
        _norm_text(data.get("summary", "")),
        _norm_text(data.get("greeting", "")),
        _norm_text(data.get("market_setup", "")),
        _norm_text(data.get("closing_message", "")),
    ]
    for field in ("market_snapshot", "key_watchpoints", "opportunities", "risk_check"):
        for item in data.get(field, []):
            if isinstance(item, dict):
                blobs.extend(_norm_text(v) for v in item.values() if isinstance(v, str))
    return "\n".join([b for b in blobs if b])


def _is_functional_watchpoint(item: Dict[str, Any]) -> bool:
    headline = _norm_text(item.get("headline", ""))
    detail = _norm_text(item.get("detail", ""))
    if not headline or not detail:
        return False
    if headline in ("체크", "이슈", "항목", "포인트"):
        return False
    if _has_any(detail, ("내용 없음", "추후 확인", "별도 확인")):
        return False
    return True


def _is_functional_risk(item: Dict[str, Any]) -> bool:
    risk = _norm_text(item.get("risk", ""))
    detail = _norm_text(item.get("detail", ""))
    return len(risk) >= 3 and len(detail) >= 12


def _summary_opening_is_weak(summary: str) -> bool:
    s = _norm_text(summary)
    sentences = _split_sentences(s)
    if not sentences:
        return True
    first = sentences[0]
    if _has_any(first, META_OPENING_PATTERNS) and _specificity_score(first) == 0:
        return True
    return False


def _decision_line_missing(closing: str) -> bool:
    lines = [ln.strip() for ln in closing.splitlines() if ln.strip()]
    last = lines[-1] if lines else _norm_text(closing)
    if not last:
        return True
    if _has_any(last, ("감사합니다", "좋은 하루", "행복한 하루")) and not _has_any(last, DECISION_HINT_TERMS):
        return True
    if _has_any(last, DECISION_HINT_TERMS):
        return False
    if _has_any(last, ("면", "경우", "우선", "이후", "전까지")):
        return False
    if _specificity_score(last) == 0:
        return True
    return False


def _watchpoints_are_repetitive(items: List[Dict[str, Any]]) -> bool:
    heads = [_norm_text(i.get("headline", "")) for i in items if isinstance(i, dict)]
    heads = [h for h in heads if h]
    if len(heads) < 3:
        return False
    token_sets = []
    for h in heads:
        norm = re.sub(r"[^0-9a-zA-Z가-힣 ]", " ", h).lower()
        token_sets.append({t for t in norm.split() if t})
    high_overlap_pairs = 0
    total_pairs = 0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a = token_sets[i]
            b = token_sets[j]
            if not a or not b:
                continue
            total_pairs += 1
            overlap = len(a & b) / max(1, min(len(a), len(b)))
            if overlap >= 0.8:
                high_overlap_pairs += 1
    if total_pairs == 0:
        return False
    return high_overlap_pairs >= 2


def _specificity_score(text: str) -> int:
    return _count_digits(text) + _count_any(text, SPECIFICITY_TOKENS)


def _summary_is_low_density(summary: str) -> bool:
    s = _norm_text(summary)
    if not s:
        return True
    sentences = _split_sentences(s)
    if len(sentences) < 2 and _specificity_score(s) < 2:
        return True
    if _count_any(s, GENERIC_FINANCE_PHRASES) >= 2 and _specificity_score(s) == 0:
        return True
    return False


def _interpretation_is_low_density(data: Dict[str, Any]) -> bool:
    candidates: List[str] = [_norm_text(data.get("market_setup", ""))]
    for field, key in (
        ("key_watchpoints", "detail"),
        ("opportunities", "reason"),
        ("risk_check", "detail"),
    ):
        for item in data.get(field, []):
            if isinstance(item, dict):
                candidates.append(_norm_text(item.get(key, "")))
    reasoning_hits = 0
    for c in candidates:
        if not c:
            continue
        if _has_any(c, INTERPRETATION_CUE_TERMS):
            reasoning_hits += 1
            continue
        if _specificity_score(c) >= 2 and len(_split_sentences(c)) >= 1:
            reasoning_hits += 1
    return reasoning_hits < 1


def _thin_input_overconfident(runtime_input: Dict[str, Any], data: Dict[str, Any]) -> bool:
    status = runtime_input.get("input_feed_status")
    if status not in THIN_INPUT_STATUSES:
        return False
    body = _joined_today_editorial_text(data)
    watch_count = len([w for w in data.get("key_watchpoints", []) if isinstance(w, dict)])
    assertive = _count_any(body, ASSERTIVE_TONE_TERMS)
    uncertainty = _count_any(body, UNCERTAINTY_TONE_TERMS)
    return watch_count >= 3 and assertive >= 2 and uncertainty == 0


def _strong_numeric_assertions(text: str) -> bool:
    explicit_values = re.findall(r"\d+(?:\.\d+)?\s*(?:%|bp|포인트|달러|원)", text.lower())
    assertive_verbs = _count_any(text, ("기록", "마감", "급등", "급락", "확정", "발표됐다", "집계됐다"))
    return len(explicit_values) >= 2 and assertive_verbs >= 1


def _unsupported_news_claim(runtime_input: Dict[str, Any], text: str) -> bool:
    if runtime_input.get("top_market_news"):
        return False
    return _has_any(text, ("속보", "단독", "복수의 보도", "보도에 따르면")) and _count_any(
        text, ("발표", "보도", "전했다")
    ) >= 2


def _unsupported_schedule_or_stock_claim(runtime_input: Dict[str, Any], text: str) -> bool:
    has_runtime_support = bool(runtime_input.get("top_market_news")) or bool(runtime_input.get("risk_factors"))
    if has_runtime_support:
        return False
    lower = text.lower()
    stock_code_like = bool(re.search(r"\b\d{6}\b", text))
    ticker_like = bool(re.search(r"\(([A-Z]{2,5})\)", text)) or bool(re.search(r"티커\s*[:：]\s*[A-Z]{2,5}\b", text))
    schedule_like = _has_any(lower, ("실적 발표 일정", "장 마감 후", "개장 직후", "발표 일정"))
    assertive_context = _count_any(lower, ("확정", "공식", "발표됐다", "예정", "확인됐다")) >= 2
    return assertive_context and ((stock_code_like and schedule_like) or (ticker_like and schedule_like))


def _non_briefing_customer_language_issues(
    summary: str, market_setup: str, section_failures: int
) -> List[ValidationIssue]:
    """Flag notice-like / pipeline / placeholder copy in summary or market_setup (customer-facing)."""
    issues: List[ValidationIssue] = []
    any_hard = False
    for label, text in (
        ("summary", _norm_text(summary)),
        ("market_setup", _norm_text(market_setup)),
    ):
        if not text:
            continue
        if _has_any(text, NON_BRIEFING_HARD_PHRASES):
            any_hard = True
            issues.append(
                ValidationIssue(
                    "placeholder_like_market_copy",
                    f"{label}에 플레이스홀더·파이프라인·단계성 안내 문구가 포함됨",
                    "warning",
                )
            )
        elif (
            (_has_any(text, NON_BRIEFING_SOFT_PHRASES) and _specificity_score(text) < 2)
            or _evasive_prep_notice_in_field(text)
        ):
            issues.append(
                ValidationIssue(
                    "non_briefing_notice_language",
                    f"{label}에 브리핑 가치가 약한 안내·준비 중심 서술이 감지됨",
                    "warning",
                )
            )
    if any_hard and section_failures >= 3:
        issues.append(
            ValidationIssue(
                "handoff_not_almost_final",
                "비브리핑성 안내 문구와 다수 핵심 섹션 미흡이 겹쳐 송고 수준에 이르지 못함",
                "error",
            )
        )
    return issues


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
            issues.append(ValidationIssue("forbidden_financial_promise", f"금지 표현 탐지: {phrase}", "error"))

    if _basis_invalid(data.get("market_snapshot", []), ["label", "value"]):
        issues.append(ValidationIssue("invalid_market_snapshot", "market_snapshot 구조 오류", "error"))
    if _basis_invalid(data.get("key_watchpoints", []), ["headline", "detail"]):
        issues.append(ValidationIssue("invalid_watchpoints", "key_watchpoints 구조 오류", "error"))
    if _basis_invalid(data.get("opportunities", []), ["theme", "reason"]):
        issues.append(ValidationIssue("invalid_opportunities", "opportunities 구조 오류", "error"))
    if _basis_invalid(data.get("risk_check", []), ["risk", "detail"]):
        issues.append(ValidationIssue("invalid_risk_check", "risk_check 구조 오류", "error"))

    title = _norm_text(data.get("title", ""))
    summary = _norm_text(data.get("summary", ""))
    closing = _norm_text(data.get("closing_message", ""))
    watchpoints = [w for w in data.get("key_watchpoints", []) if isinstance(w, dict)]
    risks = [r for r in data.get("risk_check", []) if isinstance(r, dict)]
    opportunities = [o for o in data.get("opportunities", []) if isinstance(o, dict)]
    all_text = _joined_today_editorial_text(data)

    # A) Opening quality checks
    if _has_any(title, WEAK_TITLE_PATTERNS):
        issues.append(
            ValidationIssue(
                "template_title",
                "제목이 템플릿형 문구에 가까워 오프닝 차별성이 약함",
                "warning",
            )
        )
    if _summary_opening_is_weak(summary):
        issues.append(
            ValidationIssue(
                "weak_opening",
                "초반 오프닝의 정보·관전 포인트 제시력이 약함",
                "warning",
            )
        )
    if _has_any(_split_sentences(summary)[0] if _split_sentences(summary) else summary, META_OPENING_PATTERNS):
        issues.append(
            ValidationIssue(
                "meta_lead_opening",
                "요약 첫 리드가 메타/인사형 문장으로 시작함",
                "warning",
            )
        )

    # B) Section integrity / density checks
    section_failures = 0
    if _summary_is_low_density(summary):
        section_failures += 1
        issues.append(ValidationIssue("low_summary_density", "summary 기능 밀도 부족", "warning"))

    functional_watch = [w for w in watchpoints if _is_functional_watchpoint(w)]
    if len(functional_watch) < 2:
        section_failures += 1
        issues.append(
            ValidationIssue("low_watchpoint_density", "체크포인트가 기능적으로 약함", "warning")
        )

    if _interpretation_is_low_density(data):
        section_failures += 1
        issues.append(
            ValidationIssue("low_interpretation_density", "해석 레이어가 기능적으로 약함", "warning")
        )

    functional_risks = [r for r in risks if _is_functional_risk(r)]
    if len(functional_risks) < 1:
        section_failures += 1
        issues.append(ValidationIssue("low_risk_density", "risk_check가 비기능적 또는 과도하게 추상적", "warning"))

    if _decision_line_missing(closing):
        section_failures += 1
        issues.append(
            ValidationIssue("missing_decision_line", "마무리 결정 기준 문장이 없거나 실사용성이 약함", "warning")
        )

    issues.extend(
        _non_briefing_customer_language_issues(
            summary,
            data.get("market_setup", ""),
            section_failures,
        )
    )

    # C) TOP 3 / watchpoint quality checks
    if len(watchpoints) < 3:
        issues.append(
            ValidationIssue("low_watchpoint_density", "핵심 체크포인트 TOP3 미충족", "warning")
        )
    if _watchpoints_are_repetitive(watchpoints):
        issues.append(
            ValidationIssue("repetitive_market_generalities", "체크포인트 간 차별성이 부족하거나 반복적임", "warning")
        )

    # D) Thin-input overconfidence checks
    if _thin_input_overconfident(runtime_input, data):
        issues.append(
            ValidationIssue(
                "overconfident_with_thin_input",
                "입력 피드가 얇은데 결과 톤/밀도가 과도하게 권위적으로 보임",
                "warning",
            )
        )
        issues.append(
            ValidationIssue(
                "authority_exceeds_input_support",
                "입력 지원 범위를 넘는 권위적 브리핑 톤이 감지됨",
                "warning",
            )
        )

    # E) Generic finance filler checks
    filler_hits = _count_any(all_text, GENERIC_FINANCE_PHRASES)
    if filler_hits >= 3 and _specificity_score(all_text) < 8:
        issues.append(
            ValidationIssue(
                "generic_finance_filler",
                "비구체적 금융 상투 문구 비중이 높아 상업적 밀도가 부족함",
                "warning",
            )
        )

    # G) Severe block conditions
    if _has_any(all_text, INTERNAL_LEAK_TERMS):
        issues.append(
            ValidationIssue(
                "internal_or_system_language_leak",
                "고객 메시지에 내부/검증 시스템 용어가 유출됨",
                "error",
            )
        )
    status = runtime_input.get("input_feed_status")
    if status == "none" and _strong_numeric_assertions(all_text):
        issues.append(
            ValidationIssue(
                "unsupported_numeric_claim",
                "입력 근거가 비어 있는 상태에서 단정형 수치 주장이 탐지됨",
                "error",
            )
        )
    if status == "none" and _unsupported_news_claim(runtime_input, all_text.lower()):
        issues.append(
            ValidationIssue(
                "unsupported_news_claim",
                "입력 근거가 비어 있는 상태에서 단정형 뉴스 주장이 탐지됨",
                "error",
            )
        )
    if status == "none" and _unsupported_schedule_or_stock_claim(runtime_input, all_text):
        issues.append(
            ValidationIssue(
                "unsupported_schedule_or_stock_claim",
                "입력 근거가 비어 있는 상태에서 종목/일정 단정 주장이 탐지됨",
                "error",
            )
        )
    if section_failures >= 4:
        issues.append(
            ValidationIssue(
                "core_section_breakdown",
                "핵심 섹션 기능이 다수 붕괴되어 발행 가능한 품질이 아님",
                "error",
            )
        )

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


