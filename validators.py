from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Literal

from renderers import (
    TODAY_GENIE_HASHTAG_COUNT,
    today_genie_hashtag_key,
    today_genie_hashtag_passes_locale_rule,
    today_genie_is_generic_hashtag,
)

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
    "무조건 매수",
    "반드시 매수",
    "적극 매수",
    "지금 매수",
    "매수 타이밍",
    "매수해야",
    "사야 한다",
    "사야 합니다",
    "담으라",
    "담으세요",
    "풀매수",
    "올인",
    "확실한 상승",
    "확실히 오른다",
    "투자 추천",
    "추천주",
    "추천 종목",
    "must buy",
    "guaranteed return",
]

# Definitive / promotional investment instruction (hard block)
DEFINITIVE_PROPOSAL_PHRASES = (
    "무조건 사",
    "반드시 사",
    "지금 사",
    "매수하라",
    "매수하세요",
    "비중을 늘려",
    "비중을 올려",
    "포트폴리오에 넣",
    "포트폴리오에 편입",
    "수익을 보장",
    "확정적으로",
    "확정 수익률",
    "이 가격이 매수",
    "이 구간이 매수",
    "매수 포인트",
    "매수 구간",
    "적극 매도",
    "무조건 매도",
    "should buy",
    "strong buy",
)

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
    "민감한 대응",
    "보수적 대응",
    "추가 확인이 필요",
    "시장 상황을 주시",
    "리스크 관리",
)

LECTURE_CLOSER_PHRASES = (
    "신중한 접근이 필요합니다",
    "신중한 접근이 필요하다",
    "신중하게 접근",
    "민감한 대응이 필요합니다",
    "민감한 대응이 필요하다",
    "민감하게 대응",
    "보수적으로 지켜봐야",
    "주의가 필요합니다",
    "면밀히 지켜볼 필요",
    "면밀히 지켜봐야 합니다",
    "면밀히 지켜봐야 한다",
    "주시할 필요가 있습니다",
    "주시할 필요가 있다",
)

DECISION_HINT_TERMS = (
    "기준",
    "우선",
    "먼저",
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
    "과해석",
    "단정",
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
    """Split on ASCII/East Asian sentence breaks; fallback for Korean clauses without periods."""
    if not text.strip():
        return []
    primary = [s.strip() for s in re.split(r"[.!?。\n]+", text) if s.strip()]
    if len(primary) >= 2:
        return primary
    secondary = [
        s.strip()
        for s in re.split(r"(?<=[다요음임])\s+(?=[가-힣ㄱ-ㅎ\d\(「\"'])", text)
        if s.strip()
    ]
    if len(secondary) >= 2:
        return secondary
    return primary or [text.strip()]


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


def _hangul_jamo_count(text: str) -> int:
    return len(re.findall(r"[\uac00-\ud7a3]", _norm_text(text)))


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


_SHORT_CRITICAL_TOKENS = frozenset({"cpi", "fed", "imf", "gdp", "oil", "ust"})


def _significant_tokens(text: str) -> List[str]:
    n = _norm_text(text).lower()
    n = re.sub(r"[^0-9a-z가-힣\s]", " ", n)
    tokens = [t for t in n.split() if len(t) >= 4]
    for t in n.split():
        if t in _SHORT_CRITICAL_TOKENS and t not in tokens:
            tokens.append(t)
    return tokens


def _watchpoint_covers_news_headline(news_headline: str, wp_head: str, wp_detail: str) -> bool:
    blob = (_norm_text(wp_head) + " " + _norm_text(wp_detail)).lower()
    nh = _norm_text(news_headline).lower()
    for candidate in (
        re.sub(r"\s+", " ", nh).strip(),
        re.sub(r"\s+", " ", re.sub(r"[^\w\s가-힣]", " ", nh)).strip(),
    ):
        if len(candidate) >= 14:
            for ln in (50, 36, 24):
                frag = candidate[:ln].strip()
                if len(frag) >= 12 and frag in blob:
                    return True
    tokens = _significant_tokens(news_headline)
    if not tokens:
        return len(nh) >= 10 and nh[: min(24, len(nh))] in blob
    hits = sum(1 for t in tokens[:10] if t in blob)
    need = 2 if len(tokens) >= 3 else 1
    return hits >= min(need, len(tokens))


def _detail_has_what_and_why_today(detail: str) -> bool:
    """TOP3 item: both 'what happened' and 'why it matters today' (not keyword-only)."""
    d = _norm_text(detail)
    if len(d) < 66:
        return False
    sents = _split_sentences(d)
    if len(sents) < 2:
        return False
    if len(d) < 72 and len(sents) < 3:
        return False
    dl = d.lower()
    todayish = _has_any(
        dl,
        (
            "오늘",
            "장전",
            "장중",
            "아침",
            "개장",
            "장 초반",
            "현재 시점",
            "금일",
            "당일",
            "다음 주",
            "주초",
        ),
    )
    tactical_today = len(sents) >= 2 and _has_any(
        d,
        ("주시", "관찰", "확인", "대응", "접근", "운용", "판단", "시나리오", "점검"),
    )
    meaning = _has_any(d, INTERPRETATION_CUE_TERMS) or _has_any(
        d,
        ("무엇", "배경", "원인", "촉발", "발표", "이슈", "변수", "영향을", "의미를"),
    )
    return (todayish or tactical_today) and meaning


def _detail_has_domestic_or_operational_watch(detail: str) -> bool:
    """TOP3: 국내 시장 관전 또는 '오늘 무엇을 먼저 볼지' 성격의 운용 확인 문장."""
    d = _norm_text(detail).lower()
    if _has_any(
        d,
        (
            "국내",
            "코스피",
            "코스닥",
            "krx",
            "원/달러",
            "원화",
            "환율",
            "외국인",
            "기관",
            "선물",
            "유가",
            "금리",
            "채권",
        ),
    ):
        return True
    if _has_any(d, ("오늘", "장전", "장중", "아침", "개장", "금일")) and _has_any(
        d,
        (
            "먼저",
            "우선",
            "주시",
            "확인",
            "살펴",
            "점검",
            "관찰",
            "대응",
            "유의",
            "체크",
            "볼 변수",
            "봐야",
        ),
    ):
        return True
    return False


def _text_blob_aligns_news_headline(news_headline: str, blob: str) -> bool:
    """True if blob (e.g. combined image prompts) carries the same story as the input headline."""
    return _watchpoint_covers_news_headline(news_headline, "", blob)


def _watchpoint_topic_aligns_news_headline(news_headline: str, wp: Dict[str, Any]) -> bool:
    """When headline languages differ, allow topic-level grounding (CPI/index/geo, etc.)."""
    nh = _norm_text(news_headline).lower()
    blob = (
        _norm_text(wp.get("headline", "")) + " " + _norm_text(wp.get("detail", ""))
    ).lower()
    if not nh:
        return False
    if "inflation" in nh or "cpi" in nh:
        return (
            "cpi" in blob
            or "물가" in blob
            or "인플레" in blob
            or "inflation" in blob
        )
    if (
        "index" in nh
        or "fared" in nh
        or "indexes" in nh
        or "stock" in nh
        or "mixed" in nh
    ):
        return (
            "지수" in blob
            or "나스닥" in blob
            or "다우" in blob
            or "s&p" in blob
            or "스펜" in blob
            or "증시" in blob
            or "nasdaq" in blob
            or "dow" in blob
            or "sp500" in blob
            or "index" in blob
            or "indices" in blob
            or "혼조" in blob
            or "미국" in blob
        )
    if "ceasefire" in nh or "iran" in nh or "geopolit" in nh or "middle east" in nh:
        return (
            "중동" in blob
            or "지정학" in blob
            or "휴전" in blob
            or "외교" in blob
            or "middle east" in blob
            or "geopolit" in blob
            or "ceasefire" in blob
        )
    return False


def _soft_image_news_anchor(news_headline: str, blob: str) -> bool:
    """Topic-shaped rescue when headline/detail token overlap is thin but story theme matches."""
    nh = _norm_text(news_headline).lower()
    b = blob.lower()
    if not nh:
        return False
    bundles = (
        (
            ("cpi", "inflation", "consumer price"),
            ("cpi", "inflation", "물가", "인플레"),
        ),
        (
            (
                "nasdaq",
                "dow",
                "s&p",
                "sp500",
                "stock",
                "index",
                "indexes",
                "fared",
                "mixed",
            ),
            (
                "nasdaq",
                "dow",
                "sp500",
                "s&p",
                "index",
                "indices",
                "지수",
                "나스닥",
                "다우",
                "증시",
                "혼조",
                "스펜",
            ),
        ),
        (
            ("ceasefire", "iran", "geopolit", "middle east"),
            (
                "ceasefire",
                "geopolit",
                "middle east",
                "중동",
                "지정학",
                "휴전",
                "외교",
                "oil",
                "유가",
            ),
        ),
        (
            ("yield", "treasury", "bond", "rate"),
            ("yield", "treasury", "rate", "금리", "채권", "국채"),
        ),
    )
    for nh_keys, blob_keys in bundles:
        if any(k in nh for k in nh_keys):
            if any(k in b for k in blob_keys):
                return True
    return False


def _validate_top_three_news_briefing(
    runtime_input: Dict[str, Any], data: Dict[str, Any]
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    wps = [w for w in data.get("key_watchpoints", []) if isinstance(w, dict)]
    if len(wps) < 3:
        issues.append(
            ValidationIssue(
                "top3_watchpoints_missing",
                "본문에 TOP3 핵심 체크포인트(정확히 3개)가 없거나 비어 있음",
                "error",
            )
        )
        return issues
    for i in range(3):
        detail = _norm_text(wps[i].get("detail", ""))
        if not _detail_has_what_and_why_today(detail):
            issues.append(
                ValidationIssue(
                    "top3_item_insufficient_briefing",
                    f"TOP3 체크포인트 {i + 1}: 사실(무엇이 있었는지)과 오늘 관점(왜 중요한지)이 detail에 구체 서술로 드러나야 함(키워드만 금지)",
                    "error",
                )
            )
        if not _detail_has_domestic_or_operational_watch(detail):
            issues.append(
                ValidationIssue(
                    "top3_item_missing_domestic_watch",
                    f"TOP3 체크포인트 {i + 1}: 국내 시장 관전 또는 오늘 우선 확인할 변수가 detail에 포함돼야 함",
                    "error",
                )
            )
    news = runtime_input.get("top_market_news")
    if isinstance(news, list) and len(news) >= 1:
        n_need = min(3, len(news))
        for i in range(n_need):
            item = news[i]
            if not isinstance(item, dict):
                continue
            nh = item.get("headline", "")
            if not isinstance(nh, str) or not nh.strip():
                continue
            wp = wps[i]
            head = _norm_text(wp.get("headline", ""))
            det = _norm_text(wp.get("detail", ""))
            if not (
                _watchpoint_covers_news_headline(nh, head, det)
                or _watchpoint_topic_aligns_news_headline(nh, wp)
            ):
                issues.append(
                    ValidationIssue(
                        "top3_not_grounded_in_input_news",
                        f"TOP3 체크포인트 {i + 1}: 입력 top_market_news 헤드라인과의 정합이 약함",
                        "error",
                    )
                )
    return issues


def _validate_image_prompts_news_anchoring(
    runtime_input: Dict[str, Any], data: Dict[str, Any]
) -> List[ValidationIssue]:
    """Full feeds: studio+outdoor English prompts should visibly carry feed/news themes (customer-facing alignment)."""
    issues: List[ValidationIssue] = []
    if runtime_input.get("input_feed_status") != "full":
        return issues
    studio = _norm_text(data.get("image_prompt_studio", ""))
    outdoor = _norm_text(data.get("image_prompt_outdoor", ""))
    blob = studio + "\n" + outdoor
    if len(blob.strip()) < 80:
        return issues
    news = runtime_input.get("top_market_news")
    if not isinstance(news, list) or len(news) < 1:
        return issues
    n_need = min(3, len(news))
    weak: List[int] = []
    for i in range(n_need):
        item = news[i]
        if not isinstance(item, dict):
            continue
        nh = item.get("headline", "")
        if not isinstance(nh, str) or not nh.strip():
            continue
        if (
            _text_blob_aligns_news_headline(nh, blob)
            or _watchpoint_topic_aligns_news_headline(nh, {"headline": "", "detail": blob})
            or _soft_image_news_anchor(nh, blob)
        ):
            continue
        weak.append(i + 1)
    if weak:
        issues.append(
            ValidationIssue(
                "image_prompt_underanchored_vs_news",
                "상·하단 이미지 영문 프롬프트가 입력 뉴스 헤드라인과 주제 연결이 약함(헤드라인 번호: "
                + ", ".join(str(x) for x in weak)
                + "). CPI·지수·지정학 등 입력 앵커를 스튜디오/야외 프롬프트에 명시할 것",
                "error",
            )
        )
    return issues


def _body_underuses_news_when_feeds_full(
    runtime_input: Dict[str, Any], all_text: str
) -> bool:
    """Full feeds: briefing should visibly carry input headlines, not generic filler."""
    if runtime_input.get("input_feed_status") != "full":
        return False
    news = runtime_input.get("top_market_news")
    if not isinstance(news, list) or len(news) < 2:
        return False
    blob = all_text.lower()
    anchored = 0
    for item in news[:5]:
        if not isinstance(item, dict):
            continue
        h = item.get("headline", "")
        if not isinstance(h, str) or not h.strip():
            continue
        toks = _significant_tokens(h)[:8]
        if toks:
            if len(toks) == 1:
                hit_need = 1
            else:
                hit_need = min(2, len(toks))
            if sum(1 for t in toks if t in blob) >= hit_need:
                anchored += 1
                continue
        nh = h.lower()
        bl = blob.lower()
        topic_hit = False
        if "inflation" in nh or "cpi" in nh:
            topic_hit = "cpi" in bl or "물가" in bl or "인플레" in bl
        elif "index" in nh or "fared" in nh:
            topic_hit = (
                "지수" in bl or "나스닥" in bl or "다우" in bl or "스펜" in bl or "s&p" in bl
            )
        elif "ceasefire" in nh or "iran" in nh or "geopolit" in nh or "middle east" in nh:
            topic_hit = "중동" in bl or "지정학" in bl or "휴전" in bl
        if topic_hit:
            anchored += 1
    need = 1 if len(news) <= 2 else 2
    return anchored < min(need, len(news))


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
    if re.search(
        r"\d{1,2}월|\d{1,2}일|장전|개장 직전|개장|야간|어젯밤|미국 증시|나스닥|다우|코스피|코스닥|금리|환율|지수",
        first,
    ):
        return False
    if _has_any(first, META_OPENING_PATTERNS) and _specificity_score(first) == 0:
        return True
    return False


def _last_sentence(text: str) -> str:
    sents = _split_sentences(_norm_text(text))
    return sents[-1] if sents else _norm_text(text)


def _lecture_tail_without_anchor(text: str) -> bool:
    """Closing sentence is generic caution lecturing without a concrete anchor."""
    last = _last_sentence(text)
    if len(last) < 18:
        return False
    if not _has_any(last, LECTURE_CLOSER_PHRASES):
        return False
    if _specificity_score(last) >= 1:
        return False
    return True


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


_KO_WEEKDAY_NAMES = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")

# YYYY년 M월 D일 + 요일 — briefing 기준일과 요일이 어긋나면 차단
_RX_KO_DATE_THEN_WEEKDAY = re.compile(
    r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일\s*(?P<wd>[월화수목금토일]요일)"
)
_RX_TODAY_WEEKDAY_WORD = re.compile(r"오늘(?:은)?\s*(?P<wd>[월화수목금토일]요일)")

# 고객 표면에서 피할 느슨한 완충/메타 표현(폴리시 배치)
_POLISH_VAGUE_PHRASE_ERRORS = (
    "방향성을 가늠",
    "가늠해야 합니다",
    "가늠해야 할",
    "막연히 주목",
    "무엇을 주목해야 할지",
)

# Hollow psychological prediction closers (summary / indices narrative / checkpoints / risks)
_HOLLOW_PREDICTION_CLOSURE_ERRORS = (
    "신중한 접근이 예상됩니다",
    "신중한 접근이 예상된다",
    "신중한 접근은 예상됩니다",
)

_DOMESTIC_DIVERGENCE_MARKERS = (
    "엇갈",
    "차별",
    "온도차",
    "대형주",
    "중소형",
    "달리 움직",
    "다르게 움직",
    "반대로",
    "상반",
    "대조",
    "괴리",
    "순환매",
    "시가총액",
)


def _expected_korean_weekday(target_date_str: object) -> str | None:
    if not isinstance(target_date_str, str) or len(target_date_str) < 10:
        return None
    try:
        d = date.fromisoformat(target_date_str[:10])
    except ValueError:
        return None
    return _KO_WEEKDAY_NAMES[d.weekday()]


def _target_weekday_accuracy_issues(
    data: Dict[str, Any], runtime_input: Dict[str, Any]
) -> List[ValidationIssue]:
    """브리핑 기준일(target_date)과 불일치하는 요일 표기 차단(결정적 검증)."""
    issues: List[ValidationIssue] = []
    exp = _expected_korean_weekday(runtime_input.get("target_date"))
    if not exp:
        return issues
    td_raw = runtime_input.get("target_date")
    td_str = td_raw[:10] if isinstance(td_raw, str) and len(td_raw) >= 10 else ""
    try:
        td_date = date.fromisoformat(td_str) if td_str else None
    except ValueError:
        td_date = None
    if td_date is None:
        return issues

    fields = (
        ("summary", data.get("summary")),
        ("greeting", data.get("greeting")),
        ("market_setup", data.get("market_setup")),
        ("closing_message", data.get("closing_message")),
    )
    for label, raw in fields:
        if not isinstance(raw, str):
            continue
        text = raw
        for m in _RX_KO_DATE_THEN_WEEKDAY.finditer(text):
            y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
            wd = m.group("wd")
            try:
                mentioned = date(y, mo, d)
            except ValueError:
                continue
            if mentioned == td_date and wd != exp:
                issues.append(
                    ValidationIssue(
                        "briefing_date_weekday_mismatch",
                        f"{label}: 기준일({td_str})에 맞지 않는 요일 표기({wd}). "
                        f"올바른 요일은 {exp}이거나, 요일을 생략하고 날짜만 쓸 것.",
                        "error",
                    )
                )
        for m in _RX_TODAY_WEEKDAY_WORD.finditer(text):
            wd = m.group("wd")
            if wd != exp:
                issues.append(
                    ValidationIssue(
                        "today_weekday_word_mismatch",
                        f"{label}: '오늘'과 함께 쓰인 요일({wd})이 기준일 요일({exp})과 불일치",
                        "error",
                    )
                )
    return issues


def _polish_vague_phrase_issues(data: Dict[str, Any]) -> List[ValidationIssue]:
    """느슨한 메타·완충 표현 축소(요약·셋업·TOP3·리스크 대상)."""
    issues: List[ValidationIssue] = []
    checks: list[tuple[str, str]] = []
    for label in ("summary", "market_setup"):
        t = data.get(label)
        if isinstance(t, str):
            checks.append((label, t))
    for idx, w in enumerate([w for w in data.get("key_watchpoints", []) if isinstance(w, dict)][:3]):
        d = w.get("detail")
        if isinstance(d, str):
            checks.append((f"key_watchpoints[{idx + 1}].detail", d))
    for idx, r in enumerate([r for r in data.get("risk_check", []) if isinstance(r, dict)][:8]):
        d = r.get("detail")
        if isinstance(d, str):
            checks.append((f"risk_check[{idx + 1}].detail", d))
    for path, blob in checks:
        for phrase in _POLISH_VAGUE_PHRASE_ERRORS:
            if phrase in blob:
                issues.append(
                    ValidationIssue(
                        "polish_vague_meta_phrase",
                        f"{path}: '{phrase}' 류의 막연한 표현 — 명명 변수·우선 확인 순서로 구체화",
                        "error",
                    )
                )
                break
    return issues


def _hollow_prediction_closure_issues(data: Dict[str, Any]) -> List[ValidationIssue]:
    """Block empty 'psychology forecast' endings on high-visibility briefing surfaces."""
    issues: List[ValidationIssue] = []
    checks: list[tuple[str, str]] = []
    for label in ("summary", "market_setup"):
        t = data.get(label)
        if isinstance(t, str):
            checks.append((label, t))
    for idx, w in enumerate([w for w in data.get("key_watchpoints", []) if isinstance(w, dict)][:3]):
        d = w.get("detail")
        if isinstance(d, str):
            checks.append((f"key_watchpoints[{idx + 1}].detail", d))
    for idx, r in enumerate([r for r in data.get("risk_check", []) if isinstance(r, dict)][:8]):
        d = r.get("detail")
        if isinstance(d, str):
            checks.append((f"risk_check[{idx + 1}].detail", d))
    for path, blob in checks:
        for phrase in _HOLLOW_PREDICTION_CLOSURE_ERRORS:
            if phrase in blob:
                issues.append(
                    ValidationIssue(
                        "hollow_prediction_closure",
                        f"{path}: 막연한 심리 예측형 맺음('{phrase}') — 금리·환율·수급 등 명명 변수와 확인 순서로 대체",
                        "error",
                    )
                )
                break
    return issues


def _kospi_kosdaq_change_pct_divergent(indices: Dict[str, Any]) -> bool:
    ks = indices.get("KOSPI")
    kd = indices.get("KOSDAQ")
    if not isinstance(ks, dict) or not isinstance(kd, dict):
        return False
    pk = ks.get("change_pct")
    pd = kd.get("change_pct")
    if not isinstance(pk, (int, float)) or not isinstance(pd, (int, float)):
        return False
    if pk == 0 or pd == 0:
        return False
    return (pk > 0) != (pd > 0)


def _domestic_index_divergence_narrative_issues(
    data: Dict[str, Any], runtime_input: Dict[str, Any]
) -> List[ValidationIssue]:
    """코스피·코스닥 등락 방향이 반대일 때 해석 문단 요구."""
    issues: List[ValidationIssue] = []
    kj = runtime_input.get("korea_japan_indices")
    if not isinstance(kj, dict):
        return issues
    idx = kj.get("indices")
    if not isinstance(idx, dict):
        return issues
    if not _kospi_kosdaq_change_pct_divergent(idx):
        return issues
    ms = _norm_text(data.get("market_setup", ""))
    if not any(m in ms for m in _DOMESTIC_DIVERGENCE_MARKERS):
        issues.append(
            ValidationIssue(
                "domestic_kospi_kosdaq_divergence_thin",
                "코스피와 코스닥 등락 방향이 엇갈리는데 market_setup에서 "
                "그 차이가 의미하는 바(대형주 대비 중소·테마 온도차 등)가 드러나지 않음",
                "error",
            )
        )
    return issues


def _forbidden_surface_cliche_issues(data: Dict[str, Any]) -> List[ValidationIssue]:
    """Block dominant generic closer in customer-facing editorial fields (success HTML surface)."""
    issues: List[ValidationIssue] = []
    bad_phrases = (
        "신중한 접근이 필요합니다",
        "신중한 접근이 필요하다",
        "신중한 접근이 필요해",
    )

    def _has_bad(s: str) -> bool:
        return any(b in s for b in bad_phrases)

    for label, text in (
        ("summary", data.get("summary")),
        ("market_setup", data.get("market_setup")),
    ):
        if isinstance(text, str) and _has_bad(text):
            issues.append(
                ValidationIssue(
                    "forbidden_surface_cliche_phrase",
                    f"{label}: 금지 맺음 문구 포함 — 금리·환율·수급 등 명명 변수와 확인 순서로 대체",
                    "error",
                )
            )
    for idx, w in enumerate([w for w in data.get("key_watchpoints", []) if isinstance(w, dict)][:3]):
        d = w.get("detail", "")
        if isinstance(d, str) and _has_bad(d):
            issues.append(
                ValidationIssue(
                    "forbidden_surface_cliche_phrase",
                    f"key_watchpoints[{idx}] detail: 금지 맺음 문구 포함",
                    "error",
                )
            )
    for idx, r in enumerate([r for r in data.get("risk_check", []) if isinstance(r, dict)][:8]):
        d = r.get("detail", "")
        if isinstance(d, str) and _has_bad(d):
            issues.append(
                ValidationIssue(
                    "forbidden_surface_cliche_phrase",
                    f"risk_check[{idx}] detail: 금지 맺음 문구 포함",
                    "error",
                )
            )
    return issues


def _market_indices_customer_narrative_gate(
    data: Dict[str, Any], runtime_input: Dict[str, Any]
) -> List[ValidationIssue]:
    """When feeds carry US index inputs, market_setup must read as interpretive briefing (not a table dump)."""
    issues: List[ValidationIssue] = []
    if runtime_input.get("input_feed_status") != "full":
        return issues
    snap = data.get("market_snapshot")
    has_snap = isinstance(snap, list) and len(snap) >= 2
    ov = runtime_input.get("overnight_us_market")
    has_idx = False
    if isinstance(ov, dict):
        idx = ov.get("indices")
        if isinstance(idx, dict) and len(idx) >= 2:
            has_idx = True
    kj = runtime_input.get("korea_japan_indices")
    has_kj_numbers = False
    has_nikkei_number = False
    has_kospi_number = False
    has_kosdaq_number = False
    if isinstance(kj, dict):
        kjx = kj.get("indices")
        if isinstance(kjx, dict):
            for sym, slot in kjx.items():
                if isinstance(slot, dict) and slot.get("close") is not None:
                    has_kj_numbers = True
                    if sym in ("NIKKEI", "N225", "NI225"):
                        has_nikkei_number = True
                    if sym == "KOSPI":
                        has_kospi_number = True
                    if sym == "KOSDAQ":
                        has_kosdaq_number = True
    if not has_snap and not has_idx and not has_kj_numbers:
        return issues
    ms = _norm_text(data.get("market_setup", ""))
    min_chars = 260 if has_kj_numbers else 220
    if len(ms) < min_chars:
        issues.append(
            ValidationIssue(
                "market_indices_narrative_thin",
                "market_setup이 야간 지수 흐름·해석·국내 연결을 서술형으로 전달하기에 부족함",
                "error",
            )
        )
        return issues
    domestic = (
        "한국",
        "국내",
        "코스피",
        "코스닥",
        "원/",
        "원·달러",
        "환율",
        "외국인",
        "개장",
        "서울",
        "장전",
        "KRX",
    )
    if not any(d in ms for d in domestic):
        issues.append(
            ValidationIssue(
                "market_indices_korea_link_missing",
                "market_setup에 오늘 국내 증시·환율·수급 등 확인 관점이 명시되지 않음",
                "error",
            )
        )
    if has_kospi_number and "코스피" not in ms:
        issues.append(
            ValidationIssue(
                "market_indices_kospi_anchor_missing",
                "입력에 코스피 수준이 있는데 market_setup에 코스피 맥락이 드러나지 않음",
                "error",
            )
        )
    if has_kosdaq_number and "코스닥" not in ms:
        issues.append(
            ValidationIssue(
                "market_indices_kosdaq_anchor_missing",
                "입력에 코스닥 수준이 있는데 market_setup에 코스닥 맥락이 드러나지 않음",
                "error",
            )
        )
    if has_nikkei_number:
        jp_markers = ("니케이", "일본", "아시아", "도쿄")
        if not any(m in ms for m in jp_markers):
            issues.append(
                ValidationIssue(
                    "market_indices_japan_anchor_missing",
                    "입력에 니케이 수준이 있는데 market_setup에 일본·아시아 맥락이 드러나지 않음",
                    "error",
                )
            )
    digit_ratio = sum(1 for c in ms if c.isdigit()) / max(len(ms), 1)
    if digit_ratio > 0.26:
        issues.append(
            ValidationIssue(
                "market_indices_numbers_heavy",
                "market_setup 숫자 비중이 높아 서술형 주요 지수 브리핑 요건을 충족하지 못함",
                "error",
            )
        )
    return issues


def _korean_surface_issues_today_genie(data: Dict[str, Any]) -> List[ValidationIssue]:
    """Require Hangul-rich customer-facing briefing fields (English-only leakage guard)."""
    issues: List[ValidationIssue] = []

    def check_field(path: str, text: object, min_hangul: int, min_len: int) -> None:
        if not isinstance(text, str):
            return
        t = _norm_text(text)
        if len(t) < min_len:
            return
        if _hangul_jamo_count(t) < min_hangul:
            issues.append(
                ValidationIssue(
                    "korean_surface_weak",
                    f"{path}: 고객 표면 한국어 서술이 부족함(한글 음절·문맥 점검 필요)",
                    "error",
                )
            )

    check_field("title", data.get("title"), 4, 10)
    check_field("summary", data.get("summary"), 14, 48)
    g = data.get("greeting")
    if isinstance(g, str) and len(_norm_text(g)) >= 6:
        check_field("greeting", g, 2, 6)
    check_field("market_setup", data.get("market_setup"), 6, 36)
    check_field("closing_message", data.get("closing_message"), 5, 20)
    for idx, w in enumerate([w for w in data.get("key_watchpoints", []) if isinstance(w, dict)][:3]):
        check_field(f"key_watchpoints[{idx + 1}].headline", w.get("headline"), 2, 5)
        check_field(f"key_watchpoints[{idx + 1}].detail", w.get("detail"), 18, 60)
    for idx, r in enumerate([r for r in data.get("risk_check", []) if isinstance(r, dict)][:5]):
        if isinstance(r.get("risk"), str) and len(_norm_text(r.get("risk", ""))) >= 5:
            check_field(f"risk_check[{idx + 1}].risk", r.get("risk"), 1, 5)
        if isinstance(r.get("detail"), str) and len(_norm_text(r.get("detail", ""))) >= 24:
            check_field(f"risk_check[{idx + 1}].detail", r.get("detail"), 4, 24)
    return issues


def validate_today_genie(data: Dict[str, Any], runtime_input: Dict[str, Any]) -> ValidationResult:
    common = validate_common_structure(data, "today_genie")
    if common.result == "block":
        return common

    issues = list(common.issues)

    tags = data.get("hashtags")
    if not isinstance(tags, list) or len(tags) != TODAY_GENIE_HASHTAG_COUNT:
        issues.append(
            ValidationIssue(
                "hashtag_count_contract",
                f"hashtags는 정확히 {TODAY_GENIE_HASHTAG_COUNT}개여야 함",
                "error",
            )
        )
    else:
        seen_ht: set[str] = set()
        for idx, t in enumerate(tags):
            if not isinstance(t, str) or not str(t).strip():
                issues.append(
                    ValidationIssue("hashtag_empty", f"hashtags[{idx}] 비어 있음", "error")
                )
                continue
            ts = str(t).strip()
            if not ts.startswith("#"):
                issues.append(
                    ValidationIssue(
                        "hashtag_format",
                        f"hashtags[{idx}]는 '#'으로 시작해야 함",
                        "warning",
                    )
                )
            if today_genie_is_generic_hashtag(ts):
                issues.append(
                    ValidationIssue(
                        "generic_hashtag_filler",
                        f"hashtags[{idx}]가 검색 가치가 낮은 일반 단독 태그로 분류됨",
                        "warning",
                    )
                )
            if not today_genie_hashtag_passes_locale_rule(ts):
                issues.append(
                    ValidationIssue(
                        "hashtag_locale",
                        f"hashtags[{idx}] 한국어 우선(또는 허용 매크로 기호) 규칙 필요",
                        "warning",
                    )
                )
            hk = today_genie_hashtag_key(ts)
            if hk in seen_ht:
                issues.append(
                    ValidationIssue(
                        "hashtag_duplicate",
                        "hashtags에 중복 태그가 있음",
                        "error",
                    )
                )
            seen_ht.add(hk)

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

    decode_failed = runtime_input.get("feed_json_decode_failed_envs") or []
    if decode_failed:
        issues.append(
            ValidationIssue(
                "feed_json_decode_failed",
                f"핵심 피드 JSON 파싱 실패(재시도 후에도 복구 불가): {', '.join(decode_failed)}",
                "error",
            )
        )

    if not data.get("image_prompt_studio"):
        issues.append(ValidationIssue("missing_image_prompt", "today 스튜디오 이미지 프롬프트 누락", "error"))
    if not data.get("image_prompt_outdoor"):
        issues.append(ValidationIssue("missing_image_prompt", "today 야외 이미지 프롬프트 누락", "error"))

    if _basis_invalid(data.get("market_snapshot", []), ["label", "value"]):
        issues.append(ValidationIssue("invalid_market_snapshot", "market_snapshot 구조 오류", "error"))
    if _basis_invalid(data.get("key_watchpoints", []), ["headline", "detail"]):
        issues.append(ValidationIssue("invalid_watchpoints", "key_watchpoints 구조 오류", "error"))
    if _basis_invalid(data.get("opportunities", []), ["theme", "reason"]):
        issues.append(ValidationIssue("invalid_opportunities", "opportunities 구조 오류", "error"))
    if _basis_invalid(data.get("risk_check", []), ["risk", "detail"]):
        issues.append(ValidationIssue("invalid_risk_check", "risk_check 구조 오류", "error"))

    all_text = _joined_today_editorial_text(data)
    for phrase in FORBIDDEN_FINANCE_PHRASES:
        if phrase in all_text:
            issues.append(ValidationIssue("forbidden_financial_promise", f"금지 표현 탐지: {phrase}", "error"))
    if _has_any(all_text, DEFINITIVE_PROPOSAL_PHRASES):
        issues.append(
            ValidationIssue(
                "definitive_investment_proposal",
                "투자 권유·확정·매수/매도 지시형 표현(브리핑 범위를 넘는 제안 톤)이 탐지됨",
                "error",
            )
        )

    title = _norm_text(data.get("title", ""))
    summary = _norm_text(data.get("summary", ""))
    closing = _norm_text(data.get("closing_message", ""))
    watchpoints = [w for w in data.get("key_watchpoints", []) if isinstance(w, dict)]
    risks = [r for r in data.get("risk_check", []) if isinstance(r, dict)]
    opportunities = [o for o in data.get("opportunities", []) if isinstance(o, dict)]

    # A) Opening quality checks
    if _has_any(title, WEAK_TITLE_PATTERNS):
        issues.append(
            ValidationIssue(
                "template_title",
                "제목이 템플릿형 문구에 가까워 오프닝 차별성이 약함",
                "error",
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

    if _lecture_tail_without_anchor(summary):
        issues.append(
            ValidationIssue(
                "summary_lecture_tail",
                "요약 맺음이 강의형 완충으로 끝나 판단 보조가 약함",
                "warning",
            )
        )
    for idx, w in enumerate(watchpoints[:3]):
        det = _norm_text(w.get("detail", ""))
        if len(det) >= 40 and _lecture_tail_without_anchor(det):
            issues.append(
                ValidationIssue(
                    "watchpoint_lecture_tail",
                    f"TOP3 체크포인트 {idx + 1}: detail 맺음이 강의형 완충에 치우침",
                    "warning",
                )
            )
    for idx, r in enumerate(risks[:4]):
        det = _norm_text(r.get("detail", ""))
        if len(det) >= 36 and _lecture_tail_without_anchor(det):
            issues.append(
                ValidationIssue(
                    "risk_lecture_tail",
                    f"risk_check {idx + 1}: detail 맺음이 추상 경고형 완충에 치우침(구체 변수·대응 기준 필요)",
                    "warning",
                )
            )
    if len(closing) >= 28 and _lecture_tail_without_anchor(closing):
        issues.append(
            ValidationIssue(
                "closing_lecture_tail",
                "한 줄 기준이 강의형 완충으로만 끝남(우선 확인·과해석 금지를 구체화할 것)",
                "warning",
            )
        )

    issues.extend(
        _non_briefing_customer_language_issues(
            summary,
            data.get("market_setup", ""),
            section_failures,
        )
    )

    issues.extend(_forbidden_surface_cliche_issues(data))
    issues.extend(_target_weekday_accuracy_issues(data, runtime_input))
    issues.extend(_polish_vague_phrase_issues(data))
    issues.extend(_hollow_prediction_closure_issues(data))
    issues.extend(_domestic_index_divergence_narrative_issues(data, runtime_input))

    issues.extend(_market_indices_customer_narrative_gate(data, runtime_input))

    # C) TOP 3 news briefing (mandatory structure + grounding)
    issues.extend(_validate_top_three_news_briefing(runtime_input, data))
    issues.extend(_validate_image_prompts_news_anchoring(runtime_input, data))
    issues.extend(_korean_surface_issues_today_genie(data))
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
                "error",
            )
        )
        issues.append(
            ValidationIssue(
                "authority_exceeds_input_support",
                "입력 지원 범위를 넘는 권위적 브리핑 톤이 감지됨",
                "error",
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
    if (
        runtime_input.get("input_feed_status") == "full"
        and filler_hits >= 2
        and _specificity_score(all_text) < 10
    ):
        issues.append(
            ValidationIssue(
                "generic_filler_despite_full_feeds",
                "입력이 충분한데도 구체 앵커 대신 상투적 완충 문구 비중이 높음",
                "error",
            )
        )
    if _body_underuses_news_when_feeds_full(runtime_input, all_text):
        issues.append(
            ValidationIssue(
                "unanchored_briefing_vs_input_news",
                "입력 뉴스 헤드라인이 본문에 충분히 녹지 않아 근거 부족 브리핑으로 보임",
                "error",
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
    if status in THIN_INPUT_STATUSES and section_failures >= 3:
        issues.append(
            ValidationIssue(
                "thin_input_briefing_inadequate",
                "입력이 불완전한데 본문이 완성형 브리핑처럼 보이거나 핵심 섹션 밀도가 부족함",
                "error",
            )
        )
    core_threshold = 3 if status in THIN_INPUT_STATUSES else 4
    if section_failures >= core_threshold:
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


