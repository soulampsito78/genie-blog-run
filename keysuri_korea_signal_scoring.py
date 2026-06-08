"""Kee-Suri Korea TOP5 signal scoring — domestic interpretation, not latest-link pickup."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

KOREA_TECH_CATEGORIES: Tuple[str, ...] = (
    "korea_ai_enterprise",
    "korea_semiconductor",
    "korea_robotics_manufacturing",
    "korea_battery_energy",
    "korea_platform_cloud_saas",
    "korea_policy_regulation",
    "korea_startup_investment",
    "korea_big_company_strategy",
    "korea_consumer_mobility",
    "global_to_korea_translation",
)

AI_PRIMARY_CATEGORY = "korea_ai_enterprise"

INDUSTRIAL_CATEGORIES = frozenset(
    {
        "korea_semiconductor",
        "korea_robotics_manufacturing",
        "korea_battery_energy",
    }
)

POLICY_CAPITAL_CATEGORIES = frozenset(
    {
        "korea_policy_regulation",
        "korea_startup_investment",
    }
)

CATEGORY_KO_LABELS: Dict[str, str] = {
    "korea_ai_enterprise": "국내 AI / 기업 AI 도입",
    "korea_semiconductor": "국내 반도체 / 장비 / 소재",
    "korea_robotics_manufacturing": "국내 로보틱스 / 스마트팩토리",
    "korea_battery_energy": "국내 배터리 / EV / 에너지",
    "korea_platform_cloud_saas": "국내 플랫폼 / 클라우드 / SaaS",
    "korea_policy_regulation": "국내 정책 / 규제 / 공공",
    "korea_startup_investment": "국내 스타트업 / 투자 / M&A",
    "korea_big_company_strategy": "국내 대기업 테크 전략",
    "korea_consumer_mobility": "국내 소비자 테크 / 디바이스 / 모빌리티",
    "global_to_korea_translation": "글로벌→한국 번역 신호",
}

CATEGORY_KEYWORD_GROUPS: Dict[str, Tuple[str, ...]] = {
    "korea_ai_enterprise": (
        "생성형 ai", "generative ai", "llm", "aicc", "기업 ai", "ai 도입", "ai 파일럿",
        "enterprise ai", "rag", "에이전트", "agent", "국산 ai", "ai 서비스",
    ),
    "korea_semiconductor": (
        "hbm", "dram", "nand", "파운드리", "반도체", "삼성전자", "sk하이닉스", "sk hynix",
        "samsung", "웨이퍼", "패키징", "장비", "소재", "메모리", "칩",
    ),
    "korea_robotics_manufacturing": (
        "로봇", "robot", "스마트팩토리", "자동화", "협동로봇", "amr", "물류로봇",
        "제조 자동화", "두산로보틱스", "현대로보틱스", "공장",
    ),
    "korea_battery_energy": (
        "배터리", "2차전지", "ess", "전고체", "lg에너지", "lges", "삼성sdi", "sk온",
        "ev", "충전", "양극재", "전력", "에너지저장",
    ),
    "korea_platform_cloud_saas": (
        "클라우드", "saas", "idc", "데이터센터", "네이버", "카카오", "토스", "nhn",
        "플랫폼", "api", "마켓플레이스", "공공클라우드",
    ),
    "korea_policy_regulation": (
        "정부", "과기정통부", "산업부", "규제", "법안", "시행령", "고시", "조달",
        "입찰", "국가전략", "정책", "공공", "부처", "국회",
    ),
    "korea_startup_investment": (
        "스타트업", "startup", "투자", "시리즈", "m&a", "인수", "vc", "cvc", "tips",
        "액셀러레이터", "프리ipo", "라운드",
    ),
    "korea_big_company_strategy": (
        "삼성", "sk", "lg", "현대", "네이버", "카카오", "대기업", "그룹", "사업재편",
        "전략투자", "조직개편", "신사업",
    ),
    "korea_consumer_mobility": (
        "출시", "단말", "스마트폰", "모빌리티", "요금제", "통신사", "ott", "디바이스",
    ),
    "global_to_korea_translation": (
        "한국 적용", "국내 파급", "국내 영향", "수혜", "한국 기업", "korea", "korean",
        "국내", "젠슨 황", "nvidia", "openai",
    ),
}

_TIER_SOURCE_SCORE: Dict[str, int] = {
    "T0_OFFICIAL_PRIMARY": 10,
    "T1_OFFICIAL_SECONDARY": 9,
    "T2_TIER1_WIRE": 8,
    "T3_QUALITY_PRESS": 7,
    "T4_AGGREGATOR_BLOG": 4,
    "T5_SOCIAL_UNVERIFIED": 2,
}

_KOREA_OFFICIAL_HOST_MARKERS = (
    "go.kr",
    "news.samsung.com",
    "skhynix.com",
    "lg.com",
)

_DOMESTIC_ENTITY_KEYWORDS: Tuple[str, ...] = (
    "삼성", "sk하이닉스", "sk hynix", "lg", "현대", "네이버", "카카오", "두산",
    "정부", "과기", "산업부", "금융위", "조달", "국회", "한국", "국내", "korea",
)

_STOCK_ONLY_MARKERS: Tuple[str, ...] = (
    "주가", "상한가", "하한가", "코스피", "코스닥", "장중", "마감", "급등", "급락",
    "stock price", "shares rose", "shares fell",
)

_ENTERTAINMENT_MARKERS: Tuple[str, ...] = (
    "연예", "아이돌", "드라마", "예능", "가십",
)

_OVERSEAS_NO_KOREA_MARKERS: Tuple[str, ...] = (
    "silicon valley", "washington", "european commission", "white house",
)

_PR_HYPE_MARKERS: Tuple[Tuple[str, int, str], ...] = (
    (r"보도자료", -8, "press_release"),
    (r"협력\s*강화|파트너십\s*체결", -6, "partnership_pr"),
    (r"선정|수상|기념|출범식", -4, "ceremonial_pr"),
    (r"customer story|case study|고객사례", -10, "customer_case"),
    (r"how .+ uses|도입\s*사례", -8, "case_study"),
    (r"repost|재탕|무단전재", -10, "repost"),
)

_STRUCTURE_KEYWORDS: Tuple[Tuple[str, int], ...] = (
    (r"투자|investment|funding|m&a|인수", 5),
    (r"정책|규제|법안|조달|입찰", 5),
    (r"증설|capex|공장|fab|패키징", 5),
    (r"hbm|dram|반도체|배터리|로봇", 4),
    (r"ai|llm|에이전트|클라우드", 4),
    (r"수주|계약|filed|approved", 4),
    (r"출시|launch|release", 3),
)

_OWNER_ACTION_KEYWORDS: Tuple[str, ...] = (
    "입찰", "조달", "수주", "투자", "정책", "규제", "파트너", "고객", "일정", "마감",
    "enterprise", "procurement", "contract",
)

_MAX_ITEMS_PER_SOURCE = 2
SOURCE_CONCENTRATION_SCORE_GAP = 15

GLOBAL_DUPLICATE_PENALTY_NO_ANGLE = -20
GLOBAL_DUPLICATE_PENALTY_WITH_ANGLE = -5

_STORY_STOP_WORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "종합", "기자",
        "서울", "연합뉴스", "보도", "관련", "등", "및",
    }
)

_ENTITY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"nvidia|엔비디아|젠슨\s*황|jensen\s*huang", "nvidia"),
    (r"openai", "openai"),
    (r"\bgoogle\b|구글|gemini", "google"),
    (r"microsoft|마이크로소프트", "microsoft"),
    (r"anthropic|클로드", "anthropic"),
    (r"samsung|삼성", "samsung"),
    (r"sk\s*hynix|sk하이닉스", "sk_hynix"),
    (r"\blg\b|lg전자|lg에너지", "lg"),
    (r"hyundai|현대", "hyundai"),
    (r"doosan|두산", "doosan"),
    (r"naver|네이버", "naver"),
    (r"kakao|카카오", "kakao"),
    (r"hanwha|한화", "hanwha"),
)

_EVENT_KEYWORD_SLUGS: Tuple[Tuple[str, str], ...] = (
    ("hbm", "hbm"),
    ("semiconductor", "semiconductor"),
    ("반도체", "semiconductor"),
    ("chip", "semiconductor"),
    ("robot", "robotics"),
    ("로봇", "robotics"),
    ("battery", "battery"),
    ("배터리", "battery"),
    ("ess", "battery"),
    ("cloud", "cloud"),
    ("클라우드", "cloud"),
    ("data center", "data_center"),
    ("데이터센터", "data_center"),
    ("startup", "startup"),
    ("스타트업", "startup"),
    ("policy", "policy"),
    ("정책", "policy"),
    ("regulation", "policy"),
    ("규제", "policy"),
    ("ministry", "policy"),
    ("부처", "policy"),
    ("launch", "launch"),
    ("출시", "launch"),
    ("investment", "investment"),
    ("투자", "investment"),
    ("m&a", "investment"),
    ("customer story", "customer_case"),
    ("고객사례", "customer_case"),
    ("case study", "customer_case"),
    ("gtc", "conference"),
    ("developer", "platform"),
    ("api", "platform"),
    ("model", "ai_model"),
    ("ai", "ai"),
)

_KOREA_ANGLE_MARKERS: Tuple[str, ...] = (
    "국내", "한국", "korea", "삼성", "sk하이닉스", "sk hynix", "lg", "현대", "네이버", "카카오",
    "두산", "한화", "정책", "규제", "조달", "입찰", "과기", "산업부", "공공", "수주", "증설",
    "공장", "fab", "공급망", "투자", "스타트업", "출시", "도입", "일정", "마감", "내일",
    "방한", "국내 적용", "국내 파급",
)

Classification = Literal[
    "deep_dive_candidate",
    "strong_top5",
    "top5_candidate",
    "watchlist",
    "reject",
    "hard_reject",
]


@dataclass
class KoreaScoreBreakdown:
    freshness_score: int = 0
    source_reliability_score: int = 0
    domestic_structure_impact_score: int = 0
    owner_actionability_score: int = 0
    business_risk_opportunity_score: int = 0
    domestic_repetition_score: int = 0
    next_step_clarity_score: int = 0
    domestic_relevance_boost: int = 0
    pr_hype_penalty: int = 0
    global_duplicate_penalty: int = 0
    category_diversity_bonus: int = 0
    ai_overconcentration_penalty: int = 0

    @property
    def base_score(self) -> int:
        return (
            self.freshness_score
            + self.source_reliability_score
            + self.domestic_structure_impact_score
            + self.owner_actionability_score
            + self.business_risk_opportunity_score
            + self.domestic_repetition_score
            + self.next_step_clarity_score
            + self.domestic_relevance_boost
            + self.pr_hype_penalty
            + self.global_duplicate_penalty
        )

    @property
    def final_score(self) -> int:
        return self.base_score + self.category_diversity_bonus + self.ai_overconcentration_penalty

    def to_dict(self) -> dict:
        return {
            "freshness_score": self.freshness_score,
            "source_reliability_score": self.source_reliability_score,
            "domestic_structure_impact_score": self.domestic_structure_impact_score,
            "owner_actionability_score": self.owner_actionability_score,
            "business_risk_opportunity_score": self.business_risk_opportunity_score,
            "domestic_repetition_score": self.domestic_repetition_score,
            "next_step_clarity_score": self.next_step_clarity_score,
            "domestic_relevance_boost": self.domestic_relevance_boost,
            "pr_hype_penalty": self.pr_hype_penalty,
            "global_duplicate_penalty": self.global_duplicate_penalty,
            "category_diversity_bonus": self.category_diversity_bonus,
            "ai_overconcentration_penalty": self.ai_overconcentration_penalty,
            "base_score": self.base_score,
            "final_score": self.final_score,
            "score": self.final_score,
        }


@dataclass
class ScoredKoreaSignal:
    source_id: str
    title: str
    url: str
    published_at: str
    source_name: str
    source_tier: str
    category: str
    summary: str
    scores: KoreaScoreBreakdown
    classification: Classification
    reason_for_selection: str
    primary_category: str = ""
    secondary_categories: List[str] = field(default_factory=list)
    category_confidence: float = 0.0
    reason_for_category: str = ""
    category_display_label: str = ""
    owner_action_line: str = ""
    next_day_impact_line: str = ""
    is_ai_category: bool = False
    is_industrial_category: bool = False
    is_policy_or_capital_category: bool = False
    pr_hype_warning: bool = False
    press_release_only: bool = False
    source_concentration_limited: bool = False
    selection_reason_tags: List[str] = field(default_factory=list)
    diversity_adjusted: bool = False
    diversity_decision: Optional[str] = None
    source_domain: str = ""
    source_count_in_top5: int = 0
    source_diversity_limited: bool = False
    hard_reject_reason: Optional[str] = None
    duplicate_group: Optional[str] = None
    penalty_notes: List[str] = field(default_factory=list)
    reason_not_selected: Optional[str] = None
    feed_id: str = ""
    story_cluster_key: str = ""
    global_duplicate_detected: bool = False
    korea_angle_required: bool = False
    korea_angle_satisfied: bool = False
    duplicate_resolution: Optional[str] = None
    same_entity_not_same_story: bool = False
    matched_global_story_key: Optional[str] = None
    matched_global_title: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "source_name": self.source_name,
            "source_domain": self.source_domain or _host(self.url),
            "source_tier": self.source_tier,
            "category": self.category,
            "primary_category": self.primary_category,
            "category_display_label": self.category_display_label
            or CATEGORY_KO_LABELS.get(self.primary_category, self.category),
            "secondary_categories": list(self.secondary_categories),
            "category_confidence": self.category_confidence,
            "reason_for_category": self.reason_for_category,
            "summary": self.summary,
            "scores": self.scores.to_dict(),
            "score": self.scores.final_score,
            "base_score": self.scores.base_score,
            "final_score": self.scores.final_score,
            "reason_for_selection": self.reason_for_selection,
            "owner_action_line": self.owner_action_line,
            "next_day_impact_line": self.next_day_impact_line,
            "is_ai_category": self.is_ai_category,
            "is_industrial_category": self.is_industrial_category,
            "is_policy_or_capital_category": self.is_policy_or_capital_category,
            "pr_hype_warning": self.pr_hype_warning,
            "press_release_only": self.press_release_only,
            "source_concentration_limited": self.source_concentration_limited,
            "selection_reason_tags": list(self.selection_reason_tags),
            "diversity_adjusted": self.diversity_adjusted,
            "diversity_decision": self.diversity_decision,
            "classification": self.classification,
            "source_count_in_top5": self.source_count_in_top5,
            "source_diversity_limited": self.source_diversity_limited,
            "hard_reject_reason": self.hard_reject_reason,
            "duplicate_group": self.duplicate_group,
            "penalty_notes": list(self.penalty_notes),
            "reason_not_selected": self.reason_not_selected,
            "feed_id": self.feed_id,
            "story_cluster_key": self.story_cluster_key,
            "global_duplicate_detected": self.global_duplicate_detected,
            "korea_angle_required": self.korea_angle_required,
            "korea_angle_satisfied": self.korea_angle_satisfied,
            "duplicate_resolution": self.duplicate_resolution,
            "same_entity_not_same_story": self.same_entity_not_same_story,
            "matched_global_story_key": self.matched_global_story_key,
            "matched_global_title": self.matched_global_title,
        }


@dataclass
class GlobalStoryIndex:
    cluster_keys: Dict[str, dict]
    items: List[dict]
    global_story_count: int = 0


@dataclass
class KoreaTop5SelectionResult:
    all_candidates: List[ScoredKoreaSignal]
    selected_top5: List[ScoredKoreaSignal]
    watchlist: List[ScoredKoreaSignal]
    rejected: List[ScoredKoreaSignal]
    duplicate_groups: Dict[str, List[str]]
    generated_at: str
    diversity_quota_decisions: List[str] = field(default_factory=list)
    diversity_limited_by_source_pool: bool = False
    source_diversity_limited: bool = False
    final_category_distribution: Dict[str, int] = field(default_factory=dict)
    final_source_distribution: Dict[str, int] = field(default_factory=dict)
    source_concentration_decisions: List[str] = field(default_factory=list)
    duplicate_guard_status: str = "not_applied_no_global_report"
    global_story_count: int = 0
    duplicate_detected_count: int = 0
    duplicate_penalized_count: int = 0
    duplicate_allowed_with_korea_angle_count: int = 0
    duplicate_watchlist_items: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        ai_count = sum(1 for c in self.selected_top5 if c.is_ai_category)
        return {
            "generated_at": self.generated_at,
            "policy": "keysuri_korea_top5_selection_v2_duplicate_guard",
            "all_candidates": [c.to_dict() for c in self.all_candidates],
            "selected_top5": [c.to_dict() for c in self.selected_top5],
            "watchlist": [c.to_dict() for c in self.watchlist],
            "rejected": [c.to_dict() for c in self.rejected],
            "duplicate_groups": self.duplicate_groups,
            "diversity_quota_decisions": list(self.diversity_quota_decisions),
            "diversity_limited_by_source_pool": self.diversity_limited_by_source_pool,
            "source_diversity_limited": self.source_diversity_limited,
            "final_category_distribution": dict(self.final_category_distribution),
            "final_source_distribution": dict(self.final_source_distribution),
            "source_concentration_decisions": list(self.source_concentration_decisions),
            "duplicate_guard_status": self.duplicate_guard_status,
            "global_story_count": self.global_story_count,
            "duplicate_detected_count": self.duplicate_detected_count,
            "duplicate_penalized_count": self.duplicate_penalized_count,
            "duplicate_allowed_with_korea_angle_count": self.duplicate_allowed_with_korea_angle_count,
            "duplicate_watchlist_items": list(self.duplicate_watchlist_items),
            "summary": {
                "candidate_count": len(self.all_candidates),
                "selected_count": len(self.selected_top5),
                "watchlist_count": len(self.watchlist),
                "rejected_count": len(self.rejected),
                "ai_count_in_top5": ai_count,
                "non_ai_count_in_top5": len(self.selected_top5) - ai_count,
            },
        }


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def _text_blob(item: dict) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("headline") or ""),
        str(item.get("statement") or ""),
        str(item.get("summary") or ""),
        str(item.get("snippet") or ""),
        str(item.get("source_name") or ""),
        str(item.get("publisher") or ""),
        str(item.get("feed_name") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _normalize_title(title: str) -> str:
    t = re.sub(r"[^\w\s가-힣]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


def normalize_story_text(text: str) -> str:
    return _normalize_title(text or "")


def _story_text_from_item(item: Union[dict, ScoredKoreaSignal]) -> str:
    if isinstance(item, ScoredKoreaSignal):
        return f"{item.title} {item.summary}".strip()
    parts = [
        str(item.get("title") or ""),
        str(item.get("headline") or ""),
        str(item.get("statement") or ""),
        str(item.get("summary") or ""),
        str(item.get("snippet") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def extract_story_entities(item: Union[dict, ScoredKoreaSignal]) -> List[str]:
    text = normalize_story_text(_story_text_from_item(item))
    entities: set[str] = set()
    for pattern, slug in _ENTITY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            entities.add(slug)
    return sorted(entities)


def extract_event_keywords(item: Union[dict, ScoredKoreaSignal]) -> List[str]:
    text = normalize_story_text(_story_text_from_item(item))
    events: set[str] = set()
    for keyword, slug in _EVENT_KEYWORD_SLUGS:
        if len(keyword) <= 3:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                events.add(slug)
        elif keyword in text:
            events.add(slug)
    return sorted(events)


def build_story_cluster_key(item: Union[dict, ScoredKoreaSignal]) -> str:
    entities = extract_story_entities(item)
    events = extract_event_keywords(item)
    if isinstance(item, ScoredKoreaSignal):
        title_src = item.title
        url = item.url
    else:
        title_src = str(item.get("title") or item.get("headline") or item.get("statement") or "")
        url = str(item.get("link") or item.get("source_url") or "")
    title_norm = normalize_story_text(title_src)
    words = [w for w in title_norm.split() if w not in _STORY_STOP_WORDS and len(w) > 1][:8]
    title_part = " ".join(words) or title_norm[:80]
    parts: List[str] = []
    if entities:
        parts.append("ent:" + "+".join(entities))
    if events:
        parts.append("evt:" + "+".join(events[:5]))
    if title_part:
        parts.append("ttl:" + title_part[:80])
    host = _host(url)
    if host and host not in ("yna.co.kr", "etnews.com"):
        parts.append(f"dom:{host}")
    return "|".join(parts) if parts else title_part[:120]


def _extract_global_selected_items(
    global_selection_report: Optional[Mapping[str, Any]] = None,
    global_selected_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[dict]:
    if global_selected_items:
        return [dict(x) for x in global_selected_items if isinstance(x, Mapping)]
    if isinstance(global_selection_report, Mapping):
        selected = global_selection_report.get("selected_top5")
        if isinstance(selected, list):
            return [dict(x) for x in selected if isinstance(x, Mapping)]
    return []


def build_global_story_index(
    global_selection_report: Optional[Mapping[str, Any]] = None,
    *,
    global_selected_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> GlobalStoryIndex:
    items = _extract_global_selected_items(global_selection_report, global_selected_items)
    cluster_keys: Dict[str, dict] = {}
    for raw in items:
        key = build_story_cluster_key(raw)
        cluster_keys[key] = {
            "story_cluster_key": key,
            "title": str(raw.get("title") or ""),
            "url": str(raw.get("url") or raw.get("source_url") or ""),
            "entities": extract_story_entities(raw),
            "events": extract_event_keywords(raw),
            "primary_category": str(raw.get("primary_category") or raw.get("category") or ""),
        }
    return GlobalStoryIndex(
        cluster_keys=cluster_keys,
        items=items,
        global_story_count=len(items),
    )


def has_korea_specific_angle(item: Union[dict, ScoredKoreaSignal]) -> bool:
    text = normalize_story_text(_story_text_from_item(item))
    if any(marker in text for marker in _KOREA_ANGLE_MARKERS):
        return True
    if isinstance(item, ScoredKoreaSignal):
        category = item.primary_category
    else:
        category = str(item.get("primary_category") or item.get("category") or "")
    if category in POLICY_CAPITAL_CATEGORIES:
        return True
    if category in INDUSTRIAL_CATEGORIES and any(
        kw in text for kw in ("삼성", "sk", "lg", "국내", "한국", "수주", "증설", "공장")
    ):
        return True
    return False


def detect_global_overlap(
    korea_item: Union[dict, ScoredKoreaSignal],
    global_story_index: GlobalStoryIndex,
) -> Optional[dict]:
    if not global_story_index.cluster_keys:
        return None
    k_key = build_story_cluster_key(korea_item)
    k_entities = set(extract_story_entities(korea_item))
    k_events = set(extract_event_keywords(korea_item))
    if k_key in global_story_index.cluster_keys:
        meta = global_story_index.cluster_keys[k_key]
        return {
            "matched_global_story_key": k_key,
            "matched_global_title": meta.get("title"),
            "same_entity_not_same_story": False,
        }
    same_entity_only: Optional[dict] = None
    for g_key, meta in global_story_index.cluster_keys.items():
        g_entities = set(meta.get("entities") or [])
        g_events = set(meta.get("events") or [])
        entity_overlap = k_entities & g_entities
        event_overlap = k_events & g_events
        if entity_overlap and event_overlap:
            return {
                "matched_global_story_key": g_key,
                "matched_global_title": meta.get("title"),
                "same_entity_not_same_story": False,
            }
        if entity_overlap and not event_overlap and not same_entity_only:
            same_entity_only = {
                "matched_global_story_key": g_key,
                "matched_global_title": meta.get("title"),
                "same_entity_not_same_story": True,
            }
    return same_entity_only


def load_global_selection_report(path: Union[str, Path]) -> dict:
    report_path = Path(path)
    if not report_path.is_file():
        raise FileNotFoundError(f"Global selection report not found: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in global selection report: {report_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Global selection report must be a JSON object: {report_path}")
    if not isinstance(payload.get("selected_top5"), list):
        raise ValueError(
            f"Global selection report missing selected_top5 list: {report_path}"
        )
    return payload


def _source_key(item: ScoredKoreaSignal) -> str:
    if item.feed_id:
        return item.feed_id
    return _host(item.url) or item.source_name or item.source_id


def classify_korea_tech_category(
    text: str,
    *,
    feed_default: str = "",
) -> Tuple[str, List[str], float, str]:
    lower = text.lower()
    hits: List[Tuple[str, int]] = []
    for cat, keywords in CATEGORY_KEYWORD_GROUPS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count:
            hits.append((cat, count))
    hits.sort(key=lambda pair: (-pair[1], pair[0]))
    if not hits:
        default = (feed_default or "").strip()
        if default in KOREA_TECH_CATEGORIES:
            return default, [], 0.55, f"feed_default:{default}"
        return "korea_big_company_strategy", [], 0.35, "fallback:korea_big_company_strategy"
    primary, top_hits = hits[0][0], hits[0][1]
    secondary = [cat for cat, n in hits[1:4] if n >= 1]
    confidence = min(0.95, 0.45 + top_hits * 0.12)
    return primary, secondary, round(confidence, 2), f"keyword_hits:{top_hits} for {primary}"


def _parse_published(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _score_freshness(published_at: str) -> int:
    dt = _parse_published(published_at)
    if dt is None:
        return 4
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hours = (now - dt.astimezone(timezone.utc)).total_seconds() / 3600
    if hours <= 12:
        return 10
    if hours <= 24:
        return 8
    if hours <= 48:
        return 6
    if hours <= 72:
        return 4
    return 2


def _score_source_reliability(url: str, tier: str) -> Tuple[int, bool]:
    host = _host(url)
    is_official = any(m in host for m in _KOREA_OFFICIAL_HOST_MARKERS)
    base = _TIER_SOURCE_SCORE.get(tier, 6)
    if is_official:
        base = max(base, 9)
    return min(10, base), is_official


def _score_domestic_structure(text: str) -> int:
    score = 2
    for pattern, pts in _STRUCTURE_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            score += pts
    return min(20, score)


def _score_owner_actionability(text: str, category: str) -> int:
    score = 3
    if any(k in text for k in _OWNER_ACTION_KEYWORDS):
        score += 6
    if category in POLICY_CAPITAL_CATEGORIES:
        score += 4
    if category in INDUSTRIAL_CATEGORIES:
        score += 3
    return min(20, score)


def _score_business_risk_opportunity(text: str) -> int:
    score = 2
    for kw in ("리스크", "기회", "수주", "투자", "규제", "비용", "공급", "risk", "opportunity"):
        if kw in text.lower():
            score += 3
    return min(15, score)


def _score_domestic_repetition(text: str) -> int:
    score = 2
    if sum(1 for kw in _DOMESTIC_ENTITY_KEYWORDS if kw in text.lower()) >= 2:
        score += 4
    return min(10, score)


def _score_next_step_clarity(text: str, *, press_release_only: bool) -> int:
    if press_release_only:
        return 2
    score = 3
    for kw in ("일정", "마감", "시행", "입찰", "확인", "공고", "timeline", "deadline"):
        if kw in text.lower():
            score += 3
    return min(10, score)


def _domestic_relevance_boost(text: str, category: str) -> Tuple[int, List[str]]:
    lower = text.lower()
    tags: List[str] = []
    boost = 0
    if any(k in lower for k in _DOMESTIC_ENTITY_KEYWORDS):
        boost += 6
        tags.append("korean_entity_mention")
    if category == "global_to_korea_translation":
        boost += 5
        tags.append("global_to_korea_translation")
    if category in POLICY_CAPITAL_CATEGORIES:
        boost += 4
        tags.append("policy_capital_signal")
    if category in INDUSTRIAL_CATEGORIES:
        boost += 3
        tags.append("industrial_signal")
    return min(15, boost), tags


def _pr_hype_penalty(text: str, *, is_official: bool) -> Tuple[int, List[str], bool, bool]:
    penalty = 0
    notes: List[str] = []
    press_release_only = False
    pr_warning = False
    for pattern, pts, tag in _PR_HYPE_MARKERS:
        if re.search(pattern, text, re.IGNORECASE):
            penalty += pts
            notes.append(tag)
            pr_warning = True
            if tag == "press_release":
                press_release_only = True
    if press_release_only and not is_official:
        penalty -= 4
    return max(-15, penalty), notes, pr_warning, press_release_only


def _is_stock_only(text: str) -> bool:
    lower = text.lower()
    has_stock = any(m in lower for m in _STOCK_ONLY_MARKERS)
    has_tech = any(
        kw in lower
        for kw in ("반도체", "ai", "배터리", "로봇", "정책", "투자", "수주", "클라우드", "스타트업")
    )
    return has_stock and not has_tech


def _is_overseas_without_korea(text: str) -> bool:
    lower = text.lower()
    has_overseas = any(m in lower for m in _OVERSEAS_NO_KOREA_MARKERS)
    has_korea = any(k in lower for k in _DOMESTIC_ENTITY_KEYWORDS) or "국내" in lower
    return has_overseas and not has_korea


def _classify_total(total: int, *, hard_reject: bool) -> Classification:
    if hard_reject:
        return "hard_reject"
    if total >= 85:
        return "deep_dive_candidate"
    if total >= 75:
        return "strong_top5"
    if total >= 60:
        return "top5_candidate"
    if total >= 45:
        return "watchlist"
    return "reject"


def _owner_action_line(category: str) -> str:
    label = CATEGORY_KO_LABELS.get(category, "국내 테크")
    return f"내일 {label} 관련 파트너·고객·입찰·정책 일정을 점검하세요."


def _next_day_impact_line(category: str) -> str:
    label = CATEGORY_KO_LABELS.get(category, "국내 테크")
    return f"내일 영향: {label} 신호가 의사결정·미팅 우선순위에 반영될 수 있습니다."


def _build_reason_for_selection(scores: KoreaScoreBreakdown, tags: Sequence[str]) -> str:
    parts = [
        f"국내 총점 {scores.final_score}점(구조 {scores.domestic_structure_impact_score}, "
        f"실행 {scores.owner_actionability_score}, 국내관련 +{scores.domestic_relevance_boost}).",
    ]
    if tags:
        parts.append(f"태그: {', '.join(tags[:4])}.")
    return " ".join(parts)


def score_korea_tech_item(item: dict) -> ScoredKoreaSignal:
    source_id = str(item.get("source_id") or item.get("claim_id") or "").strip()
    title = str(item.get("title") or item.get("headline") or item.get("statement") or "").strip()
    url = str(item.get("link") or item.get("source_url") or "").strip()
    published_at = str(item.get("published_at") or item.get("fetched_at") or "").strip()
    source_name = str(item.get("source_name") or item.get("publisher") or item.get("feed_name") or "").strip()
    source_tier = str(item.get("source_tier") or "T3_QUALITY_PRESS").strip()
    feed_default = str(item.get("category") or item.get("default_category") or "").strip()
    summary = str(item.get("summary") or item.get("snippet") or title).strip()
    feed_id = str(item.get("feed_id") or "").strip()

    text = _text_blob(item)
    primary, secondary, category_confidence, reason_for_category = classify_korea_tech_category(
        text, feed_default=feed_default
    )
    is_ai = primary == AI_PRIMARY_CATEGORY
    is_industrial = primary in INDUSTRIAL_CATEGORIES
    is_policy_capital = primary in POLICY_CAPITAL_CATEGORIES

    penalty_notes: List[str] = []
    tags: List[str] = []
    hard_reject_reason: Optional[str] = None

    if not url.startswith("http"):
        hard_reject_reason = "no_source_url"
    elif not published_at:
        hard_reject_reason = "no_date"
    elif _is_stock_only(text):
        hard_reject_reason = "stock_only_no_tech_signal"
    elif any(m in text for m in _ENTERTAINMENT_MARKERS):
        hard_reject_reason = "entertainment_not_tech"
    elif _is_overseas_without_korea(text) and primary != "global_to_korea_translation":
        hard_reject_reason = "overseas_no_korea_application"

    reliability, is_official = _score_source_reliability(url, source_tier)
    pr_pen, pr_notes, pr_warning, press_release_only = _pr_hype_penalty(text, is_official=is_official)
    penalty_notes.extend(pr_notes)
    domestic_boost, boost_tags = _domestic_relevance_boost(text, primary)
    tags.extend(boost_tags)

    scores = KoreaScoreBreakdown()
    scores.freshness_score = _score_freshness(published_at)
    scores.source_reliability_score = reliability
    scores.domestic_structure_impact_score = _score_domestic_structure(text)
    scores.owner_actionability_score = _score_owner_actionability(text, primary)
    scores.business_risk_opportunity_score = _score_business_risk_opportunity(text)
    scores.domestic_repetition_score = _score_domestic_repetition(text)
    scores.next_step_clarity_score = _score_next_step_clarity(text, press_release_only=press_release_only)
    scores.domestic_relevance_boost = domestic_boost
    scores.pr_hype_penalty = pr_pen
    scores.global_duplicate_penalty = 0

    if scores.owner_actionability_score < 6 and scores.business_risk_opportunity_score < 4:
        if not hard_reject_reason:
            hard_reject_reason = "low_domestic_actionability"

    if hard_reject_reason:
        classification: Classification = "hard_reject"
        reason = f"탈락: {hard_reject_reason}."
    else:
        classification = _classify_total(scores.base_score, hard_reject=False)
        reason = _build_reason_for_selection(scores, tags)

    if pr_warning:
        tags.append("pr_hype_warning")
    if press_release_only:
        tags.append("press_release_only")

    return ScoredKoreaSignal(
        source_id=source_id,
        title=title,
        url=url,
        published_at=published_at,
        source_name=source_name,
        source_tier=source_tier,
        category=primary,
        primary_category=primary,
        secondary_categories=list(secondary),
        category_confidence=category_confidence,
        reason_for_category=reason_for_category,
        category_display_label=CATEGORY_KO_LABELS.get(primary, primary),
        summary=summary,
        scores=scores,
        classification=classification,
        reason_for_selection=reason,
        owner_action_line=_owner_action_line(primary),
        next_day_impact_line=_next_day_impact_line(primary),
        is_ai_category=is_ai,
        is_industrial_category=is_industrial,
        is_policy_or_capital_category=is_policy_capital,
        pr_hype_warning=pr_warning,
        press_release_only=press_release_only,
        selection_reason_tags=tags,
        source_domain=_host(url) or source_name,
        hard_reject_reason=hard_reject_reason,
        penalty_notes=penalty_notes,
        feed_id=feed_id,
    )


def _duplicate_key(title: str, url: str = "") -> str:
    norm_title = _normalize_title(title)
    path = (urlparse(url).path or "").strip("/").lower()
    if path:
        return f"{norm_title}|{path}"[:120]
    words = [w for w in norm_title.split() if len(w) > 1]
    return " ".join(words[:8]) or norm_title


def _is_qualifying_candidate(item: ScoredKoreaSignal) -> bool:
    return (
        item.classification != "hard_reject"
        and not item.hard_reject_reason
        and item.scores.base_score >= 45
    )


def _is_global_duplicate_blocked(item: ScoredKoreaSignal) -> bool:
    return (
        item.global_duplicate_detected
        and item.korea_angle_required
        and not item.korea_angle_satisfied
    )


def _reclassify_after_duplicate_penalty(item: ScoredKoreaSignal) -> None:
    if item.hard_reject_reason:
        item.classification = "hard_reject"
        return
    item.classification = _classify_total(item.scores.base_score, hard_reject=False)


def _apply_global_duplicate_guard(
    item: ScoredKoreaSignal,
    global_story_index: GlobalStoryIndex,
) -> None:
    item.story_cluster_key = build_story_cluster_key(item)
    overlap = detect_global_overlap(item, global_story_index)
    if not overlap:
        return
    item.matched_global_story_key = str(overlap.get("matched_global_story_key") or "")
    item.matched_global_title = str(overlap.get("matched_global_title") or "")
    if overlap.get("same_entity_not_same_story"):
        item.same_entity_not_same_story = True
        item.selection_reason_tags.append("same_entity_not_same_story")
        return
    item.global_duplicate_detected = True
    item.korea_angle_required = True
    if has_korea_specific_angle(item):
        item.korea_angle_satisfied = True
        item.scores.global_duplicate_penalty = GLOBAL_DUPLICATE_PENALTY_WITH_ANGLE
        item.duplicate_resolution = "allowed_with_korea_angle"
        item.selection_reason_tags.append("global_duplicate_with_korea_angle")
        item.reason_for_selection = (
            f"{item.reason_for_selection} 국내 적용: 한국 기업·정책·공급망·내일 영향 관점에서 별도 선정."
        )
    else:
        item.korea_angle_satisfied = False
        item.scores.global_duplicate_penalty = GLOBAL_DUPLICATE_PENALTY_NO_ANGLE
        item.duplicate_resolution = "penalized_no_korea_angle"
        item.reason_not_selected = "global_angle_duplicate_without_korea_application"
        item.selection_reason_tags.append("global_duplicate_no_korea_angle")
        item.penalty_notes.append("global_angle_duplicate_without_korea_application")
    _reclassify_after_duplicate_penalty(item)


def select_korea_top5(
    candidates: Sequence[ScoredKoreaSignal],
    *,
    max_items: int = 5,
) -> Tuple[
    List[ScoredKoreaSignal],
    List[str],
    bool,
    Dict[str, int],
    bool,
    List[ScoredKoreaSignal],
]:
    decisions: List[str] = []
    source_blocked: List[ScoredKoreaSignal] = []
    pool = [s for s in candidates if s.classification != "hard_reject" and not s.hard_reject_reason]
    qualifying_non_ai = [
        s for s in pool if not s.is_ai_category and _is_qualifying_candidate(s)
    ]
    diversity_limited = len(qualifying_non_ai) < 2
    eligible_source_keys = {_source_key(s) for s in pool}
    source_diversity_limited = len(eligible_source_keys) < 3
    ranked = sorted(pool, key=lambda s: (-s.scores.base_score, s.title))

    selected: List[ScoredKoreaSignal] = []
    selected_keys: set[str] = set()

    def _key(s: ScoredKoreaSignal) -> str:
        return s.source_id or s.url

    def _ai_count() -> int:
        return sum(1 for s in selected if s.is_ai_category)

    def _source_count(sk: str) -> int:
        return sum(1 for s in selected if _source_key(s) == sk)

    def _best_alternative(*, exclude_source: str) -> Optional[ScoredKoreaSignal]:
        for cand in ranked:
            if _key(cand) in selected_keys:
                continue
            if exclude_source and _source_key(cand) == exclude_source:
                continue
            return cand
        return None

    def _check_source_concentration(item: ScoredKoreaSignal) -> Tuple[bool, str]:
        sk = _source_key(item)
        if _source_count(sk) < _MAX_ITEMS_PER_SOURCE:
            return True, ""
        if source_diversity_limited:
            item.source_diversity_limited = True
            decisions.append(f"source_diversity_limited_pool:{sk}:{item.title[:40]}")
            return True, "diversity_limited_by_source_pool"
        alt = _best_alternative(exclude_source=sk)
        if alt is None:
            item.source_diversity_limited = True
            return True, "no_alternative_source"
        if item.scores.base_score >= alt.scores.base_score + SOURCE_CONCENTRATION_SCORE_GAP:
            decisions.append(f"source_concentration_score_exception:{sk}:{item.title[:40]}")
            return True, "source_concentration_score_exception"
        item.source_concentration_limited = True
        item.reason_not_selected = "source_concentration_limit"
        decisions.append(f"source_concentration_limit:{sk}:{item.title[:50]}")
        if item not in source_blocked:
            source_blocked.append(item)
        return False, "source_concentration_limit"

    def _try_add(item: ScoredKoreaSignal, reason: str) -> bool:
        k = _key(item)
        if k in selected_keys or len(selected) >= max_items:
            return False
        if _is_global_duplicate_blocked(item):
            item.reason_not_selected = "global_angle_duplicate_without_korea_application"
            decisions.append(f"blocked_global_duplicate:{item.title[:60]}")
            return False
        if item.is_ai_category and _ai_count() >= 2 and not diversity_limited:
            item.reason_not_selected = "ai_cap"
            decisions.append(f"capped_ai:{item.title[:60]}")
            return False
        if item.press_release_only and selected:
            best = max(s.scores.base_score for s in selected)
            if item.scores.base_score < best - 10:
                item.reason_not_selected = "press_release_deprioritized"
                decisions.append(f"press_release_deprioritized:{item.title[:60]}")
                return False
        allowed, src_reason = _check_source_concentration(item)
        if not allowed:
            return False
        item.diversity_adjusted = True
        item.diversity_decision = reason
        if src_reason:
            item.selection_reason_tags.append(src_reason)
        selected.append(item)
        selected_keys.add(k)
        decisions.append(f"selected:{reason}:{item.primary_category}:{item.title[:50]}")
        return True

    industrial_qual = [
        s for s in ranked if s.is_industrial_category and _is_qualifying_candidate(s)
    ]
    if industrial_qual:
        _try_add(industrial_qual[0], "mandatory_industrial_slot")

    policy_qual = [
        s for s in ranked if s.is_policy_or_capital_category and _is_qualifying_candidate(s)
    ]
    if policy_qual:
        for cand in policy_qual:
            if _key(cand) not in selected_keys:
                _try_add(cand, "mandatory_policy_capital_slot")
                break

    for item in ranked:
        if len(selected) >= max_items:
            break
        if _key(item) in selected_keys:
            continue
        _try_add(item, "score_rank")

    if not diversity_limited:
        non_ai_selected = sum(1 for s in selected if not s.is_ai_category)
        if non_ai_selected < 2:
            for item in ranked:
                if len(selected) >= max_items:
                    break
                if item.is_ai_category or _key(item) in selected_keys:
                    continue
                if not _is_qualifying_candidate(item):
                    continue
                ai_items = [s for s in selected if s.is_ai_category]
                if ai_items and non_ai_selected < 2:
                    weakest_ai = min(ai_items, key=lambda s: s.scores.base_score)
                    if item.scores.base_score >= weakest_ai.scores.base_score - 5:
                        selected.remove(weakest_ai)
                        selected_keys.discard(_key(weakest_ai))
                        decisions.append(f"swapped_out_ai_for_diversity:{weakest_ai.title[:50]}")
                _try_add(item, "diversity_non_ai_quota")
                non_ai_selected = sum(1 for s in selected if not s.is_ai_category)

    dist: Dict[str, int] = {}
    src_dist: Dict[str, int] = {}
    for s in selected:
        dist[s.primary_category] = dist.get(s.primary_category, 0) + 1
        sk = _source_key(s)
        src_dist[sk] = src_dist.get(sk, 0) + 1
        s.source_count_in_top5 = src_dist[sk]

    return selected[:max_items], decisions, diversity_limited, dist, source_diversity_limited, source_blocked


def score_korea_signal_candidates(
    items: Sequence[dict],
    *,
    global_selection_report: Optional[Mapping[str, Any]] = None,
    global_selected_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> KoreaTop5SelectionResult:
    scored: List[ScoredKoreaSignal] = []
    dup_groups: Dict[str, List[str]] = {}
    seen_urls: set[str] = set()
    global_index = build_global_story_index(
        global_selection_report,
        global_selected_items=global_selected_items,
    )
    duplicate_guard_status = (
        "applied"
        if global_index.global_story_count > 0
        else "not_applied_no_global_report"
    )

    for raw in items:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("link") or raw.get("source_url") or "").strip()
        if url in seen_urls:
            dup = score_korea_tech_item(raw)
            dup.hard_reject_reason = dup.hard_reject_reason or "duplicate_story"
            dup.classification = "hard_reject"
            dup.duplicate_group = _duplicate_key(dup.title, dup.url)
            scored.append(dup)
            continue
        seen_urls.add(url)
        item = score_korea_tech_item(raw)
        item.story_cluster_key = build_story_cluster_key(item)
        dkey = _duplicate_key(item.title, item.url)
        dup_groups.setdefault(dkey, []).append(item.source_id or item.url)
        if len(dup_groups[dkey]) > 1:
            item.duplicate_group = dkey
        scored.append(item)

    for item in scored:
        if item.duplicate_group and dup_groups.get(item.duplicate_group, [""])[0] not in (
            item.source_id,
            item.url,
        ):
            item.hard_reject_reason = item.hard_reject_reason or "duplicate_story"
            item.classification = "hard_reject"

    duplicate_detected_count = 0
    duplicate_penalized_count = 0
    duplicate_allowed_with_korea_angle_count = 0
    duplicate_watchlist_items: List[dict] = []
    if global_index.global_story_count > 0:
        for item in scored:
            _apply_global_duplicate_guard(item, global_index)
            if item.global_duplicate_detected:
                duplicate_detected_count += 1
                if item.korea_angle_satisfied:
                    duplicate_allowed_with_korea_angle_count += 1
                else:
                    duplicate_penalized_count += 1
            if _is_global_duplicate_blocked(item):
                duplicate_watchlist_items.append(
                    {
                        "title": item.title,
                        "source": item.source_name,
                        "score": item.scores.final_score,
                        "category": item.primary_category,
                        "reason_not_selected": item.reason_not_selected,
                        "matched_global_title": item.matched_global_title,
                    }
                )

    pool = [s for s in scored if s.classification != "hard_reject" and not s.hard_reject_reason]
    selected, diversity_decisions, diversity_limited, category_dist, source_diversity_limited, source_blocked = (
        select_korea_top5(pool)
    )
    source_concentration_decisions = [
        d for d in diversity_decisions if d.startswith("source_concentration")
    ]
    selected_ids = {s.source_id or s.url for s in selected}
    blocked_ids = {s.source_id or s.url for s in source_blocked}
    watchlist_pool = [
        s
        for s in sorted(pool, key=lambda s: (-s.scores.base_score, s.title))
        if (s.source_id or s.url) not in selected_ids
        and s.classification in ("watchlist", "top5_candidate", "strong_top5", "deep_dive_candidate")
    ]
    watchlist_blocked = [s for s in source_blocked if (s.source_id or s.url) not in selected_ids]
    watchlist = (watchlist_blocked + [s for s in watchlist_pool if (s.source_id or s.url) not in blocked_ids])[:10]
    rejected = [s for s in scored if (s.source_id or s.url) not in selected_ids and s not in watchlist]

    return KoreaTop5SelectionResult(
        all_candidates=scored,
        selected_top5=selected,
        watchlist=watchlist,
        rejected=rejected,
        duplicate_groups={k: v for k, v in dup_groups.items() if len(v) > 1},
        generated_at=_now_kst_iso(),
        diversity_quota_decisions=diversity_decisions,
        diversity_limited_by_source_pool=diversity_limited,
        source_diversity_limited=source_diversity_limited,
        final_category_distribution=category_dist,
        final_source_distribution={
            _source_key(s): sum(1 for x in selected if _source_key(x) == _source_key(s))
            for s in selected
        },
        source_concentration_decisions=source_concentration_decisions,
        duplicate_guard_status=duplicate_guard_status,
        global_story_count=global_index.global_story_count,
        duplicate_detected_count=duplicate_detected_count,
        duplicate_penalized_count=duplicate_penalized_count,
        duplicate_allowed_with_korea_angle_count=duplicate_allowed_with_korea_angle_count,
        duplicate_watchlist_items=duplicate_watchlist_items,
    )


def _candidate_dict_from_source_pack(source_pack: dict) -> List[dict]:
    sources = source_pack.get("sources") if isinstance(source_pack.get("sources"), list) else []
    claims = source_pack.get("claims") if isinstance(source_pack.get("claims"), list) else []
    claim_by_sid: Dict[str, dict] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        sids = claim.get("source_ids") if isinstance(claim.get("source_ids"), list) else []
        for sid in sids:
            claim_by_sid[str(sid)] = claim

    out: List[dict] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("source_id") or "")
        claim = claim_by_sid.get(sid, {})
        out.append(
            {
                "source_id": sid,
                "title": src.get("title") or claim.get("statement"),
                "link": src.get("source_url"),
                "source_url": src.get("source_url"),
                "published_at": src.get("published_at") or src.get("fetched_at"),
                "source_name": src.get("source_name") or src.get("publisher"),
                "source_tier": src.get("source_tier"),
                "category": claim.get("category"),
                "default_category": claim.get("category"),
                "summary": src.get("snippet") or claim.get("summary"),
                "claim_id": claim.get("claim_id"),
                "feed_id": str(src.get("feed_id") or ""),
            }
        )
    return out


def score_candidates_from_source_pack(
    source_pack: dict,
    *,
    global_selection_report: Optional[Mapping[str, Any]] = None,
    global_selected_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> KoreaTop5SelectionResult:
    return score_korea_signal_candidates(
        _candidate_dict_from_source_pack(source_pack),
        global_selection_report=global_selection_report,
        global_selected_items=global_selected_items,
    )


def apply_scored_selection_to_source_pack(
    source_pack: dict,
    selection: KoreaTop5SelectionResult,
) -> dict:
    pack = dict(source_pack)
    selected_ids = {s.source_id for s in selection.selected_top5 if s.source_id}
    selected_urls = {s.url for s in selection.selected_top5}

    sources = pack.get("sources") if isinstance(pack.get("sources"), list) else []
    claims = pack.get("claims") if isinstance(pack.get("claims"), list) else []

    new_sources = [
        s
        for s in sources
        if isinstance(s, dict)
        and (
            str(s.get("source_id") or "") in selected_ids
            or str(s.get("source_url") or "") in selected_urls
        )
    ]
    new_claims = [
        c
        for c in claims
        if isinstance(c, dict)
        and any(str(sid) in selected_ids for sid in (c.get("source_ids") or []))
    ]

    score_by_sid = {s.source_id: s for s in selection.selected_top5}
    for claim in new_claims:
        sids = claim.get("source_ids") if isinstance(claim.get("source_ids"), list) else []
        for sid in sids:
            scored = score_by_sid.get(str(sid))
            if scored:
                claim["selection_score"] = scored.scores.final_score
                claim["selection_score_before_diversity"] = scored.scores.base_score
                claim["selection_rationale"] = scored.reason_for_selection
                claim["selection_classification"] = scored.classification
                claim["primary_category"] = scored.primary_category
                claim["secondary_categories"] = list(scored.secondary_categories)
                claim["category_confidence"] = scored.category_confidence
                claim["reason_for_category"] = scored.reason_for_category
                claim["category_label_ko"] = scored.category_display_label
                claim["owner_action_line"] = scored.owner_action_line
                claim["next_day_impact_line"] = scored.next_day_impact_line
                claim["briefing_angle"] = "국내 적용"
                claim["angle_chip"] = "국내 적용"
                claim["hype_warning"] = scored.pr_hype_warning
                claim["press_release_only"] = scored.press_release_only
                claim["selection_reason_tags"] = list(scored.selection_reason_tags)
                claim["source_name"] = scored.source_name
                claim["source_domain"] = scored.source_domain or _host(scored.url)
                claim["source_count_in_top5"] = scored.source_count_in_top5
                claim["source_diversity_limited"] = scored.source_diversity_limited
                claim["source_concentration_limited"] = scored.source_concentration_limited
                claim["global_duplicate_detected"] = scored.global_duplicate_detected
                claim["korea_angle_required"] = scored.korea_angle_required
                claim["korea_angle_satisfied"] = scored.korea_angle_satisfied
                claim["duplicate_resolution"] = scored.duplicate_resolution
                claim["same_entity_not_same_story"] = scored.same_entity_not_same_story
                if scored.matched_global_title:
                    claim["matched_global_title"] = scored.matched_global_title
                if scored.penalty_notes:
                    claim["penalty_notes"] = list(scored.penalty_notes)

    pack["sources"] = new_sources
    pack["claims"] = new_claims
    pack["korea_top5_selection"] = {
        "generated_at": selection.generated_at,
        "policy": "keysuri_korea_top5_selection_v2_duplicate_guard",
        "duplicate_guard_status": selection.duplicate_guard_status,
        "global_story_count": selection.global_story_count,
        "duplicate_detected_count": selection.duplicate_detected_count,
        "duplicate_penalized_count": selection.duplicate_penalized_count,
        "duplicate_allowed_with_korea_angle_count": selection.duplicate_allowed_with_korea_angle_count,
        "selected_source_ids": [s.source_id for s in selection.selected_top5],
        "selected_scores": [s.scores.final_score for s in selection.selected_top5],
        "selected_scores_before_diversity": [s.scores.base_score for s in selection.selected_top5],
        "selected_primary_categories": [s.primary_category for s in selection.selected_top5],
        "final_category_distribution": selection.final_category_distribution,
        "final_source_distribution": selection.final_source_distribution,
        "diversity_limited_by_source_pool": selection.diversity_limited_by_source_pool,
        "diversity_quota_decisions": selection.diversity_quota_decisions,
        "watchlist_count": len(selection.watchlist),
        "rejected_count": len(selection.rejected),
    }
    return pack


def build_korea_selection_debug_report(
    candidates: Sequence[ScoredKoreaSignal],
    selected: Sequence[ScoredKoreaSignal],
    watchlist: Sequence[ScoredKoreaSignal],
    *,
    rejected: Optional[Sequence[ScoredKoreaSignal]] = None,
) -> dict:
    result = KoreaTop5SelectionResult(
        all_candidates=list(candidates),
        selected_top5=list(selected),
        watchlist=list(watchlist),
        rejected=list(rejected or []),
        duplicate_groups={},
        generated_at=_now_kst_iso(),
    )
    return result.to_dict()


def write_korea_top5_selection_report(
    selection: KoreaTop5SelectionResult,
    path: Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(selection.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
