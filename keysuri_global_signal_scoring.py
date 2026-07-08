"""Kee-Suri global TOP5 signal scoring — value-based selection, not latest-link pickup."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import urlparse

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

GLOBAL_TECH_CATEGORIES: Tuple[str, ...] = (
    "ai_software_platform",
    "semiconductor_chip_infra",
    "semiconductor_equipment_materials",
    "robotics_automation_manufacturing",
    "battery_ev_energy_grid",
    "aerospace_satellite_defense_tech",
    "hardware_device_display",
    "cybersecurity_cloud_datacenter",
    "policy_regulation_capital_supplychain",
)

AI_PRIMARY_CATEGORY = "ai_software_platform"

CATEGORY_KEYWORD_GROUPS: Dict[str, Tuple[str, ...]] = {
    "ai_software_platform": (
        "openai", "google ai", "anthropic", "microsoft ai", "meta ai", "apple ai",
        "agent", "enterprise ai", "developer tools", "cloud ai", "llm", "gemini", "chatgpt",
    ),
    "semiconductor_chip_infra": (
        "nvidia", "amd", "intel", "tsmc", "samsung foundry", "sk hynix", "micron", "hbm",
        "gpu", "ai accelerator", "wafer", "fab", "packaging", "chiplet", "semiconductor", "chip",
    ),
    "semiconductor_equipment_materials": (
        "asml", "applied materials", "lam research", "tokyo electron", "photoresist", "euv",
        "silicon carbide", "gallium nitride", "substrate", "advanced packaging",
    ),
    "robotics_automation_manufacturing": (
        "robotics", "humanoid robot", "industrial robot", "warehouse automation",
        "factory automation", "collaborative robot", "autonomous systems", "manufacturing",
    ),
    "battery_ev_energy_grid": (
        "battery", "solid-state battery", "lithium", "lfp", "sodium-ion", "ess", "grid storage",
        "ev supply chain", "charging", "power demand", "data center energy", "energy grid",
    ),
    "aerospace_satellite_defense_tech": (
        "spacex", "satellite", "launch", "defense ai", "drone", "autonomous defense", "space internet",
        "aerospace", "missile", "defense",
        "위성", "우주", "방산", "국방", "미사일", "군사용",
    ),
    "hardware_device_display": (
        "smartphone", "xr", "wearable", "display", "oled", "sensor", "edge ai device", "gadget",
        "pixel", "google pixel", "android", "phone", "mobile device", "on-device ai",
        "온디바이스 ai", "스마트폰", "픽셀",
    ),
    "cybersecurity_cloud_datacenter": (
        "cybersecurity", "cloud infrastructure", "datacenter", "data center", "liquid cooling",
        "networking", "enterprise security",
    ),
    "policy_regulation_capital_supplychain": (
        "export control", "regulation", "antitrust", "investment", "m&a", "funding", "tariff",
        "supply chain", "sanction", "policy", "capital",
    ),
}

# Guard: "aerospace_satellite_defense_tech" keyword hits (e.g. the generic word
# "launch") are not sufficient on their own — a Google Pixel/Android launch is
# not aerospace/defense. The category is only allowed through when one of these
# unambiguous aerospace/defense/military terms is actually present.
AEROSPACE_DEFENSE_REQUIRED_KEYWORDS: Tuple[str, ...] = (
    "satellite", "space", "defense", "missile", "drone warfare", "aerospace",
    "위성", "우주", "방산", "국방", "미사일", "군사용",
)

# Consumer device signals that must never fall through to aerospace/defense —
# they belong to hardware_device_display / ai_software_platform instead.
CONSUMER_MOBILE_DEVICE_KEYWORDS: Tuple[str, ...] = (
    "pixel", "google pixel", "android", "smartphone", "phone", "mobile device",
    "온디바이스 ai", "스마트폰", "픽셀",
)

ROBOTICS_BATTERY_MATERIALS_CATEGORIES = frozenset(
    {
        "robotics_automation_manufacturing",
        "battery_ev_energy_grid",
        "semiconductor_equipment_materials",
    }
)

SEMICONDUCTOR_CATEGORIES = frozenset(
    {"semiconductor_chip_infra", "semiconductor_equipment_materials"}
)

CATEGORY_KO_LABELS: Dict[str, str] = {
    "ai_software_platform": "AI·소프트웨어·플랫폼",
    "semiconductor_chip_infra": "반도체·칩·AI 인프라",
    "semiconductor_equipment_materials": "반도체 장비·소재",
    "robotics_automation_manufacturing": "로봇·자동화·제조",
    "battery_ev_energy_grid": "배터리·EV·에너지·전력",
    "aerospace_satellite_defense_tech": "항공우주·위성·방산 테크",
    "hardware_device_display": "하드웨어·디바이스·디스플레이",
    "cybersecurity_cloud_datacenter": "보안·클라우드·데이터센터",
    "policy_regulation_capital_supplychain": "정책·규제·자본·공급망",
}

Classification = Literal[
    "deep_dive_candidate",
    "strong_top5",
    "top5_candidate",
    "watchlist",
    "reject",
    "hard_reject",
]

_TIER_SOURCE_SCORE: Dict[str, int] = {
    "T0_OFFICIAL_PRIMARY": 10,
    "T1_OFFICIAL_SECONDARY": 9,
    "T2_TIER1_WIRE": 8,
    "T3_QUALITY_PRESS": 7,
    "T4_AGGREGATOR_BLOG": 4,
    "T5_SOCIAL_UNVERIFIED": 2,
}

_OFFICIAL_HOSTS = (
    "openai.com",
    "blog.google",
    "microsoft.com",
    "apple.com",
    "meta.com",
    "nvidia.com",
    "anthropic.com",
    "sec.gov",
)

_STRUCTURAL_KEYWORDS: Tuple[Tuple[str, int], ...] = (
    (r"\blaunch(?:ed|es)?\b", 4),
    (r"\brelease[ds]?\b", 3),
    (r"\bmodel\b", 3),
    (r"\bapi\b", 3),
    (r"\bplatform\b", 3),
    (r"\bregulat", 5),
    (r"\bpolicy\b", 4),
    (r"\bpricing\b", 4),
    (r"\bfunding\b", 4),
    (r"\bacquisition\b", 4),
    (r"\bchip\b|\bgpu\b|\bsemiconductor\b", 4),
    (r"\benterprise\b", 3),
    (r"\bdeveloper\b", 3),
    (r"\bagent\b", 4),
    (r"\bworkflow\b", 3),
    (r"\bdistribution\b", 3),
    (r"\bsearch\b", 2),
)

_OWNER_KEYWORDS: Tuple[str, ...] = (
    "founder",
    "operator",
    "startup",
    "enterprise",
    "korea",
    "korean",
    "automation",
    "content",
    "service",
    "saas",
    "api",
    "developer",
    "monetiz",
    "pricing",
    "workflow",
    "agent",
)

_BUSINESS_KEYWORDS: Tuple[str, ...] = (
    "revenue",
    "monetiz",
    "pricing",
    "cost",
    "automation",
    "labor",
    "operations",
    "sales",
    "market",
    "opportunity",
    "risk",
    "compliance",
    "procurement",
    "packaging",
    "positioning",
)

_HYPE_MARKERS: Tuple[Tuple[str, int], ...] = (
    (r"customer story|case study|customer case", -10),
    (r"how .+ uses|helping .+ transform", -8),
    (r"ai transformation|digital transformation", -6),
    (r"partnership with|partnered with", -5),
    (r"announces collaboration", -5),
    (r"repost|via rss|syndicated", -8),
)

_SPONSORED_MARKERS: Tuple[Tuple[str, str], ...] = (
    (r"\bsponsored\b", "sponsored"),
    (r"partner content", "partner_content"),
    (r"paid content", "paid_content"),
    (r"\bpromoted\b", "promoted"),
    (r"advertorial", "advertorial"),
    (r"from our partner", "from_our_partner"),
    (r"brand post", "brand_post"),
    (r"sponsored by", "sponsored_by"),
    (r"presented by", "presented_by"),
)

MAX_ITEMS_PER_SOURCE = 2
SOURCE_CONCENTRATION_SCORE_GAP = 15
REPLACEMENT_POOL_MAX_REJECTED = 12
REPLACEMENT_POOL_MIN_BASE_SCORE = 30

_GENERIC_MARKETING = (
    "ai adoption is accelerating",
    "companies are adopting ai",
    "기업들이 ai를 도입",
    "transform their business with ai",
)

_ENDAVA_URL = "https://openai.com/index/endava-frontiers/"


@dataclass
class ScoreBreakdown:
    recency: int = 0
    source_reliability: int = 0
    structural_impact: int = 0
    owner_relevance: int = 0
    business_leverage: int = 0
    signal_strength: int = 0
    actionability: int = 0
    hype_penalty: int = 0
    category_diversity_bonus: int = 0
    ai_overconcentration_penalty: int = 0

    @property
    def base_total(self) -> int:
        return (
            self.recency
            + self.source_reliability
            + self.structural_impact
            + self.owner_relevance
            + self.business_leverage
            + self.signal_strength
            + self.actionability
            + self.hype_penalty
        )

    @property
    def total(self) -> int:
        return (
            self.base_total
            + self.category_diversity_bonus
            + self.ai_overconcentration_penalty
        )

    def to_dict(self) -> dict:
        return {
            "recency": self.recency,
            "source_reliability": self.source_reliability,
            "structural_impact": self.structural_impact,
            "owner_relevance": self.owner_relevance,
            "business_leverage": self.business_leverage,
            "signal_strength": self.signal_strength,
            "actionability": self.actionability,
            "hype_penalty": self.hype_penalty,
            "category_diversity_bonus": self.category_diversity_bonus,
            "ai_overconcentration_penalty": self.ai_overconcentration_penalty,
            "base_total": self.base_total,
            "total": self.total,
        }


@dataclass
class ScoredGlobalSignal:
    source_id: str
    title: str
    url: str
    published_at: str
    source_name: str
    source_tier: str
    category: str
    summary: str
    scores: ScoreBreakdown
    classification: Classification
    selection_rationale: str
    primary_category: str = ""
    secondary_categories: List[str] = field(default_factory=list)
    category_confidence: float = 0.0
    reason_for_category: str = ""
    diversity_adjusted: bool = False
    diversity_decision: Optional[str] = None
    hype_warning: bool = False
    sponsored_warning: bool = False
    is_sponsored: bool = False
    selection_note: Optional[str] = None
    source_domain: str = ""
    source_count_in_top5: int = 0
    source_diversity_limited: bool = False
    source_concentration_penalty: int = 0
    source_concentration_reason: Optional[str] = None
    hard_reject_reason: Optional[str] = None
    duplicate_group: Optional[str] = None
    penalty_notes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    is_breaking_launch: bool = False
    is_customer_case_study: bool = False
    is_official_source: bool = False

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
            "secondary_categories": list(self.secondary_categories),
            "category_confidence": self.category_confidence,
            "reason_for_category": self.reason_for_category,
            "category_label_ko": CATEGORY_KO_LABELS.get(self.primary_category, self.category),
            "summary": self.summary,
            "scores": self.scores.to_dict(),
            "score_before_diversity": self.scores.base_total,
            "score_after_diversity": self.scores.total,
            "diversity_adjusted": self.diversity_adjusted,
            "diversity_decision": self.diversity_decision,
            "classification": self.classification,
            "selection_rationale": self.selection_rationale,
            "hype_warning": self.hype_warning,
            "sponsored_warning": self.sponsored_warning,
            "is_sponsored": self.is_sponsored,
            "selection_note": self.selection_note,
            "source_count_in_top5": self.source_count_in_top5,
            "source_diversity_limited": self.source_diversity_limited,
            "source_concentration_penalty": self.source_concentration_penalty,
            "source_concentration_reason": self.source_concentration_reason,
            "hard_reject_reason": self.hard_reject_reason,
            "duplicate_group": self.duplicate_group,
            "penalty_notes": list(self.penalty_notes),
            "tags": list(self.tags),
            "is_breaking_launch": self.is_breaking_launch,
            "is_customer_case_study": self.is_customer_case_study,
            "is_official_source": self.is_official_source,
        }


@dataclass
class GlobalTop5SelectionResult:
    all_candidates: List[ScoredGlobalSignal]
    selected_top5: List[ScoredGlobalSignal]
    watchlist: List[ScoredGlobalSignal]
    rejected: List[ScoredGlobalSignal]
    duplicate_groups: Dict[str, List[str]]
    generated_at: str
    diversity_quota_decisions: List[str] = field(default_factory=list)
    diversity_limited_by_source_pool: bool = False
    source_diversity_limited: bool = False
    final_category_distribution: Dict[str, int] = field(default_factory=dict)
    final_source_distribution: Dict[str, int] = field(default_factory=dict)
    source_concentration_decisions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        ai_count = sum(
            1 for c in self.selected_top5 if c.primary_category == AI_PRIMARY_CATEGORY
        )
        non_ai_count = len(self.selected_top5) - ai_count
        return {
            "generated_at": self.generated_at,
            "policy": "keysuri_global_top5_selection_v2_diversity",
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
            "summary": {
                "candidate_count": len(self.all_candidates),
                "selected_count": len(self.selected_top5),
                "watchlist_count": len(self.watchlist),
                "rejected_count": len(self.rejected),
                "ai_count_in_top5": ai_count,
                "non_ai_count_in_top5": non_ai_count,
            },
        }


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _parse_published(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _host(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            return host[4:]
        return host
    except ValueError:
        return ""


def _source_key(item: ScoredGlobalSignal) -> str:
    domain = _host(item.url)
    if domain:
        return domain
    return (item.source_name or "").strip().lower() or "unknown"


def _safe_source_key_from_raw(item: dict) -> str:
    url = str(item.get("source_url") or item.get("link") or "").strip()
    domain = _host(url)
    if domain:
        return domain
    return str(item.get("source_name") or item.get("publisher") or "unknown").strip().lower() or "unknown"


def _count_by_source_key(items: Sequence[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _safe_source_key_from_raw(item)
        out[key] = out.get(key, 0) + 1
    return out


def _normalize_title(title: str) -> str:
    t = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()[:100]


def _text_blob(item: dict) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("summary") or item.get("snippet") or ""),
        str(item.get("link") or item.get("source_url") or ""),
    ]
    return " ".join(parts).lower()


def _score_recency(published_at: str, *, strategic_evergreen: bool) -> int:
    dt = _parse_published(published_at)
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
    if age_h <= 24:
        return 10
    if age_h <= 48:
        return 8
    if age_h <= 168:
        return 6
    if strategic_evergreen:
        return 4
    return 2


def _score_source_reliability(url: str, tier: str) -> Tuple[int, bool]:
    base = _TIER_SOURCE_SCORE.get(tier, 5)
    host = _host(url)
    official = any(h in host for h in _OFFICIAL_HOSTS)
    if official:
        base = max(base, 9)
    if "sec.gov" in host or "reuters.com" in host or "bloomberg.com" in host:
        base = max(base, 9)
    if "medium.com" in host or "substack" in host:
        base = min(base, 4)
    return min(10, base), official


def _score_structural(text: str) -> int:
    score = 0
    for pattern, pts in _STRUCTURAL_KEYWORDS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score += pts
    return min(20, score)


def _score_owner_relevance(text: str, category: str) -> int:
    hits = sum(1 for k in _OWNER_KEYWORDS if k in text)
    cat_boost = {
        AI_PRIMARY_CATEGORY: 4,
        "semiconductor_chip_infra": 5,
        "semiconductor_equipment_materials": 5,
        "robotics_automation_manufacturing": 4,
        "battery_ev_energy_grid": 4,
        "policy_regulation_capital_supplychain": 4,
        "cybersecurity_cloud_datacenter": 3,
    }.get(category, 2)
    return min(20, 6 + hits * 2 + cat_boost)


def _score_business_leverage(text: str) -> int:
    hits = sum(1 for k in _BUSINESS_KEYWORDS if k in text)
    return min(15, 4 + hits * 2)


def _score_signal_strength(text: str) -> int:
    vendors = ("openai", "google", "microsoft", "anthropic", "meta", "nvidia", "apple")
    hits = sum(1 for v in vendors if v in text)
    pattern = any(
        k in text
        for k in ("funding", "regulation", "agent", "chip", "platform", "enterprise", "policy")
    )
    base = 3 + hits
    if pattern:
        base += 3
    return min(10, base)


def _score_actionability(text: str, *, is_case_study: bool) -> int:
    if is_case_study:
        return 5
    verbs = ("monitor", "update", "adjust", "prepare", "compare", "evaluate", "watch", "build")
    hits = sum(1 for v in verbs if v in text)
    return min(10, 4 + hits)


def _sponsored_penalty(text: str) -> Tuple[bool, int, List[str]]:
    notes: List[str] = []
    lower = text.lower()
    is_sponsored = False
    for pattern, code in _SPONSORED_MARKERS:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            is_sponsored = True
            notes.append(f"sponsored_content_penalty:{code}")
    penalty = -25 if is_sponsored else 0
    return is_sponsored, penalty, notes


def _hype_penalty(text: str, url: str) -> Tuple[int, List[str], bool, bool]:
    notes: List[str] = []
    penalty = 0
    is_case = False
    hype_warning = False
    lower = text.lower()
    if "endava" in lower or "endava-frontiers" in url:
        is_case = True
        penalty -= 10
        notes.append("official_openai_customer_case_study")
        hype_warning = True
    for pattern, pts in _HYPE_MARKERS:
        if re.search(pattern, lower):
            penalty += pts
            notes.append(f"hype_marker:{pattern}")
            if "customer" in pattern or "case study" in pattern:
                is_case = True
                hype_warning = True
    for g in _GENERIC_MARKETING:
        if g in lower:
            penalty -= 4
            notes.append(f"generic_marketing:{g}")
    return max(-15, penalty), notes, hype_warning, is_case


def _is_breaking_launch(text: str, *, is_case_study: bool) -> bool:
    if is_case_study:
        return False
    if re.search(r"\b(launches?|unveils?|introduces?)\b.+\b(product|model|platform|service)\b", text):
        return True
    return False


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


def classify_global_tech_category(
    text: str,
    *,
    feed_default: str = "",
) -> Tuple[str, List[str], float, str]:
    """Return primary_category, secondary_categories, confidence, reason."""
    lower = text.lower()
    hits: List[Tuple[str, int]] = []
    for cat, keywords in CATEGORY_KEYWORD_GROUPS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count:
            hits.append((cat, count))

    # Guard: only allow aerospace/defense through when an unambiguous
    # aerospace/defense/military term is present — a stray "launch" hit from a
    # Pixel/Android/consumer-device headline must never win this category.
    has_strict_aerospace_signal = any(kw in lower for kw in AEROSPACE_DEFENSE_REQUIRED_KEYWORDS)
    if not has_strict_aerospace_signal:
        hits = [(cat, n) for cat, n in hits if cat != "aerospace_satellite_defense_tech"]

    hits.sort(key=lambda pair: (-pair[1], pair[0]))
    if not hits:
        if any(kw in lower for kw in CONSUMER_MOBILE_DEVICE_KEYWORDS):
            return "hardware_device_display", [], 0.4, "consumer_device_keyword_fallback"
        legacy = (feed_default or "market_signal").strip()
        mapped = {
            "ai_product": AI_PRIMARY_CATEGORY,
            "bigtech": AI_PRIMARY_CATEGORY,
            "semiconductor": "semiconductor_chip_infra",
            "platform": AI_PRIMARY_CATEGORY,
            "policy": "policy_regulation_capital_supplychain",
            "startup": "policy_regulation_capital_supplychain",
            "security": "cybersecurity_cloud_datacenter",
            "market_signal": AI_PRIMARY_CATEGORY,
        }.get(legacy, "hardware_device_display")
        return mapped, [], 0.35, f"feed_default_mapped:{legacy}"
    primary, top_hits = hits[0][0], hits[0][1]
    secondary = [cat for cat, n in hits[1:4] if n >= 1]
    confidence = min(0.95, 0.45 + top_hits * 0.12)
    reason = f"keyword_hits:{top_hits} for {primary}"
    return primary, secondary, round(confidence, 2), reason


def _is_qualifying_candidate(item: ScoredGlobalSignal) -> bool:
    return (
        item.classification != "hard_reject"
        and not item.hard_reject_reason
        and item.scores.base_total >= 45
    )


def _select_diverse_top5(
    pool: List[ScoredGlobalSignal],
) -> Tuple[
    List[ScoredGlobalSignal],
    List[str],
    bool,
    Dict[str, int],
    bool,
    List[ScoredGlobalSignal],
]:
    """Category- and source-aware TOP5 selection after base scoring."""
    decisions: List[str] = []
    source_blocked: List[ScoredGlobalSignal] = []
    eligible = [s for s in pool if s.classification != "hard_reject" and not s.hard_reject_reason]
    qualifying_non_ai = [
        s for s in eligible if s.primary_category != AI_PRIMARY_CATEGORY and _is_qualifying_candidate(s)
    ]
    diversity_limited = len(qualifying_non_ai) < 2
    eligible_source_keys = {_source_key(s) for s in eligible}
    source_diversity_limited = len(eligible_source_keys) < 3

    ranked = sorted(eligible, key=lambda s: (-s.scores.base_total, s.title))

    selected: List[ScoredGlobalSignal] = []
    selected_keys: set[str] = set()

    def _key(s: ScoredGlobalSignal) -> str:
        return s.source_id or s.url

    def _ai_count() -> int:
        return sum(1 for s in selected if s.primary_category == AI_PRIMARY_CATEGORY)

    def _source_count(sk: str) -> int:
        return sum(1 for s in selected if _source_key(s) == sk)

    def _best_alternative(*, exclude_source: str) -> Optional[ScoredGlobalSignal]:
        for cand in ranked:
            if _key(cand) in selected_keys:
                continue
            if exclude_source and _source_key(cand) == exclude_source:
                continue
            return cand
        return None

    def _check_source_concentration(item: ScoredGlobalSignal) -> Tuple[bool, str]:
        sk = _source_key(item)
        item.source_domain = _host(item.url) or item.source_name
        count = _source_count(sk)
        if count < MAX_ITEMS_PER_SOURCE:
            return True, ""
        if source_diversity_limited:
            item.source_diversity_limited = True
            decisions.append(
                f"source_diversity_limited_pool:{sk}:{item.title[:40]}"
            )
            return True, "diversity_limited_by_source_pool"
        alt = _best_alternative(exclude_source=sk)
        if alt is None:
            item.source_diversity_limited = True
            decisions.append(f"no_alternative_source:{sk}:{item.title[:40]}")
            return True, "no_alternative_source"
        if item.scores.base_total >= alt.scores.base_total + SOURCE_CONCENTRATION_SCORE_GAP:
            decisions.append(
                f"source_concentration_score_exception:{sk}:{item.title[:40]}"
            )
            return True, "source_concentration_score_exception"
        item.source_concentration_penalty = -8
        item.source_concentration_reason = "source_concentration_limit"
        decisions.append(f"source_concentration_limit:{sk}:{item.title[:50]}")
        if item not in source_blocked:
            source_blocked.append(item)
        return False, "source_concentration_limit"

    def _check_sponsored(item: ScoredGlobalSignal) -> bool:
        if not item.is_sponsored:
            return True
        non_spon = [
            x
            for x in ranked
            if not x.is_sponsored and _key(x) not in selected_keys and _is_qualifying_candidate(x)
        ]
        if non_spon and len(selected) < 5:
            best_alt = non_spon[0]
            strong_enough = (
                item.scores.structural_impact >= 8
                and item.scores.base_total >= best_alt.scores.base_total
            )
            if not strong_enough:
                item.source_concentration_reason = item.source_concentration_reason or "advertorial_watchlist"
                decisions.append(f"advertorial_watchlist:{item.title[:50]}")
                if item not in source_blocked:
                    source_blocked.append(item)
                return False
        item.sponsored_warning = True
        item.hype_warning = True
        item.selection_note = "sponsored/partner content; watch with caution"
        decisions.append(f"sponsored_top5_exception:{item.title[:50]}")
        return True

    def _try_add(item: ScoredGlobalSignal, reason: str) -> bool:
        k = _key(item)
        if k in selected_keys or len(selected) >= 5:
            return False
        if (
            item.primary_category == AI_PRIMARY_CATEGORY
            and _ai_count() >= 2
            and not diversity_limited
        ):
            decisions.append(f"capped_ai:{item.title[:60]}")
            return False
        if item.is_customer_case_study and selected:
            best = max(s.scores.base_total for s in selected)
            if item.scores.base_total < best - 12:
                decisions.append(f"marketing_case_deprioritized:{item.title[:60]}")
                return False
        if not _check_sponsored(item):
            return False
        allowed, src_reason = _check_source_concentration(item)
        if not allowed:
            return False
        if src_reason:
            item.source_concentration_reason = src_reason
        item.diversity_adjusted = True
        item.diversity_decision = reason
        selected.append(item)
        selected_keys.add(k)
        decisions.append(f"selected:{reason}:{item.primary_category}:{item.title[:50]}")
        return True

    semi_qual = [
        s for s in ranked if s.primary_category in SEMICONDUCTOR_CATEGORIES and _is_qualifying_candidate(s)
    ]
    if semi_qual:
        _try_add(semi_qual[0], "mandatory_semiconductor_slot")

    rob_qual = [
        s
        for s in ranked
        if s.primary_category in ROBOTICS_BATTERY_MATERIALS_CATEGORIES and _is_qualifying_candidate(s)
    ]
    if rob_qual:
        for cand in rob_qual:
            if _key(cand) not in selected_keys:
                _try_add(cand, "mandatory_robotics_battery_materials_slot")
                break

    for item in ranked:
        if len(selected) >= 5:
            break
        if _key(item) in selected_keys:
            continue
        _try_add(item, "score_rank")

    if diversity_limited and len(selected) < 5:
        decisions.append("diversity_limited_by_source_pool:true")
        for item in ranked:
            if len(selected) >= 5:
                break
            if _key(item) in selected_keys:
                continue
            _try_add(item, "diversity_limited_fill")

    if not diversity_limited:
        non_ai_selected = sum(1 for s in selected if s.primary_category != AI_PRIMARY_CATEGORY)
        if non_ai_selected < 2:
            for item in ranked:
                if len(selected) >= 5:
                    break
                if item.primary_category == AI_PRIMARY_CATEGORY:
                    continue
                if _key(item) in selected_keys:
                    continue
                if not _is_qualifying_candidate(item):
                    continue
                ai_items = [s for s in selected if s.primary_category == AI_PRIMARY_CATEGORY]
                if ai_items and non_ai_selected < 2:
                    weakest_ai = min(ai_items, key=lambda s: s.scores.base_total)
                    if item.scores.base_total >= weakest_ai.scores.base_total - 5:
                        selected.remove(weakest_ai)
                        selected_keys.discard(_key(weakest_ai))
                        decisions.append(f"swapped_out_ai_for_diversity:{weakest_ai.title[:50]}")
                        _ai_count()
                _try_add(item, "diversity_non_ai_quota")
                non_ai_selected = sum(
                    1 for s in selected if s.primary_category != AI_PRIMARY_CATEGORY
                )

    for item in selected:
        if item.primary_category != AI_PRIMARY_CATEGORY:
            item.scores.category_diversity_bonus = min(8, item.scores.category_diversity_bonus + 4)
        else:
            if _ai_count() > 2:
                item.scores.ai_overconcentration_penalty = -10

    ai_in_final = sum(1 for s in selected if s.primary_category == AI_PRIMARY_CATEGORY)
    if ai_in_final > 2:
        decisions.append(f"ai_cap_warning:count={ai_in_final}")

    dist: Dict[str, int] = {}
    for s in selected:
        dist[s.primary_category] = dist.get(s.primary_category, 0) + 1

    src_dist: Dict[str, int] = {}
    for s in selected:
        sk = _source_key(s)
        src_dist[sk] = src_dist.get(sk, 0) + 1
        s.source_domain = _host(s.url) or s.source_name
        s.source_count_in_top5 = src_dist[sk]

    return selected[:5], decisions, diversity_limited, dist, source_diversity_limited, source_blocked


def _build_rationale(scores: ScoreBreakdown, *, tags: Sequence[str], penalty_notes: Sequence[str]) -> str:
    parts = [
        f"총점 {scores.total}점(구조 {scores.structural_impact}, 주인님 {scores.owner_relevance}, 사업 {scores.business_leverage}).",
    ]
    if tags:
        parts.append(f"신호 유형: {', '.join(tags[:3])}.")
    if penalty_notes:
        parts.append(f"감점: {'; '.join(penalty_notes[:2])}.")
    return " ".join(parts)


def score_global_signal_item(item: dict) -> ScoredGlobalSignal:
    """Score one candidate feed/source item."""
    source_id = str(item.get("source_id") or item.get("claim_id") or "").strip()
    title = str(item.get("title") or item.get("headline") or item.get("statement") or "").strip()
    url = str(item.get("link") or item.get("source_url") or "").strip()
    published_at = str(item.get("published_at") or item.get("fetched_at") or "").strip()
    source_name = str(item.get("source_name") or item.get("publisher") or item.get("feed_name") or "").strip()
    source_tier = str(item.get("source_tier") or "T3_QUALITY_PRESS").strip()
    category = str(item.get("category") or item.get("default_category") or "market_signal").strip()
    summary = str(item.get("summary") or item.get("snippet") or title).strip()

    text = _text_blob(item)
    primary_category, secondary_categories, category_confidence, reason_for_category = (
        classify_global_tech_category(text, feed_default=category)
    )
    category = primary_category
    penalty_notes: List[str] = []
    tags: List[str] = []
    hard_reject_reason: Optional[str] = None

    if not url.startswith("http"):
        hard_reject_reason = "no_source_url"
    elif not published_at:
        hard_reject_reason = "no_date"
    elif any(g in text for g in _GENERIC_MARKETING) and _score_structural(text) < 6:
        hard_reject_reason = "marketing_only_no_strategic_signal"

    hype_pen, hype_notes, hype_warning, is_case = _hype_penalty(text, url)
    is_sponsored, sponsored_pen, sponsored_notes = _sponsored_penalty(text)
    penalty_notes.extend(hype_notes)
    penalty_notes.extend(sponsored_notes)
    if is_sponsored:
        hype_warning = True
        tags.append("sponsored_content")
    if is_case:
        tags.append("customer_case_study")
    if url.rstrip("/") == _ENDAVA_URL.rstrip("/"):
        tags.append("openai_official_endava_case")

    strategic = is_case or "policy" in category or "regulation" in text
    scores = ScoreBreakdown()
    scores.recency = _score_recency(published_at, strategic_evergreen=strategic)
    scores.source_reliability, is_official = _score_source_reliability(url, source_tier)
    scores.structural_impact = _score_structural(text)
    scores.owner_relevance = _score_owner_relevance(text, category)
    scores.business_leverage = _score_business_leverage(text)
    scores.signal_strength = _score_signal_strength(text)
    scores.actionability = _score_actionability(text, is_case_study=is_case)
    scores.hype_penalty = hype_pen + sponsored_pen

    if scores.owner_relevance < 6 and scores.business_leverage < 5:
        if not hard_reject_reason:
            hard_reject_reason = "no_owner_relevance_or_business_connection"

    if hard_reject_reason:
        classification: Classification = "hard_reject"
        rationale = f"탈락: {hard_reject_reason}."
    else:
        classification = _classify_total(scores.total, hard_reject=False)
        rationale = _build_rationale(scores, tags=tags, penalty_notes=penalty_notes)

    is_launch = _is_breaking_launch(text, is_case_study=is_case)

    return ScoredGlobalSignal(
        source_id=source_id,
        title=title,
        url=url,
        published_at=published_at,
        source_name=source_name,
        source_tier=source_tier,
        category=category,
        primary_category=primary_category,
        secondary_categories=list(secondary_categories),
        category_confidence=category_confidence,
        reason_for_category=reason_for_category,
        summary=summary,
        scores=scores,
        classification=classification,
        selection_rationale=rationale,
        hype_warning=hype_warning,
        is_sponsored=is_sponsored,
        source_domain=_host(url) or source_name,
        hard_reject_reason=hard_reject_reason,
        penalty_notes=penalty_notes,
        tags=tags,
        is_breaking_launch=is_launch,
        is_customer_case_study=is_case,
        is_official_source=is_official,
    )


def _duplicate_key(title: str, url: str = "") -> str:
    norm_title = _normalize_title(title)
    path = (urlparse(url).path or "").strip("/").lower()
    if path:
        return f"{norm_title}|{path}"[:120]
    words = [w for w in norm_title.split() if len(w) > 3]
    return " ".join(words[:8]) or norm_title


def score_global_signal_candidates(items: Sequence[dict]) -> GlobalTop5SelectionResult:
    """Score all candidates, dedupe, and partition into TOP5 / watchlist / rejected."""
    scored: List[ScoredGlobalSignal] = []
    dup_groups: Dict[str, List[str]] = {}
    seen_urls: set[str] = set()

    for raw in items:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("link") or raw.get("source_url") or "").strip()
        if url in seen_urls:
            dup = score_global_signal_item(raw)
            dup.hard_reject_reason = dup.hard_reject_reason or "duplicate_story"
            dup.classification = "hard_reject"
            dup.duplicate_group = _duplicate_key(dup.title, dup.url)
            scored.append(dup)
            continue
        seen_urls.add(url)
        item = score_global_signal_item(raw)
        dkey = _duplicate_key(item.title, item.url)
        dup_groups.setdefault(dkey, []).append(item.source_id or item.url)
        if len(dup_groups[dkey]) > 1:
            item.duplicate_group = dkey
        scored.append(item)

    for idx, item in enumerate(scored):
        if item.duplicate_group and dup_groups.get(item.duplicate_group, [""])[0] not in (
            item.source_id,
            item.url,
        ):
            item.hard_reject_reason = item.hard_reject_reason or "duplicate_story"
            item.classification = "hard_reject"

    pool = [
        s
        for s in scored
        if s.classification != "hard_reject" and not s.hard_reject_reason
    ]
    selected, diversity_decisions, diversity_limited, category_dist, source_diversity_limited, source_blocked = (
        _select_diverse_top5(pool)
    )
    source_concentration_decisions = [
        d for d in diversity_decisions if d.startswith("source_concentration")
    ]
    selected_ids = {s.source_id or s.url for s in selected}
    blocked_ids = {s.source_id or s.url for s in source_blocked}
    watchlist_pool = [
        s
        for s in sorted(pool, key=lambda s: (-s.scores.base_total, s.title))
        if (s.source_id or s.url) not in selected_ids
        and s.classification in ("watchlist", "top5_candidate", "strong_top5", "deep_dive_candidate")
    ]
    watchlist_blocked = [s for s in source_blocked if (s.source_id or s.url) not in selected_ids]
    watchlist = (watchlist_blocked + [s for s in watchlist_pool if (s.source_id or s.url) not in blocked_ids])[:10]
    rejected = [s for s in scored if (s.source_id or s.url) not in selected_ids and s not in watchlist]

    return GlobalTop5SelectionResult(
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
                "summary": src.get("snippet") or claim.get("summary"),
                "claim_id": claim.get("claim_id"),
            }
        )
    return out


def score_candidates_from_source_pack(source_pack: dict) -> GlobalTop5SelectionResult:
    return score_global_signal_candidates(_candidate_dict_from_source_pack(source_pack))


def _is_safe_replacement_candidate(item: ScoredGlobalSignal) -> bool:
    """Allow non-top5 scored items as duplicate replacements, not as primary picks.

    Operationally, a lower-scoring but valid distinct item is better than
    silently keeping a same-source duplicate in the final TOP5. Still exclude
    validation failures, untrusted tiers, sponsored/advertorial items, and rows
    without basic source/title grounding.
    """
    if item.classification == "hard_reject" or item.hard_reject_reason:
        return False
    if item.source_tier in {"T4_AGGREGATOR_BLOG", "T5_SOCIAL_UNVERIFIED"}:
        return False
    if item.is_sponsored:
        return False
    if item.scores.base_total < REPLACEMENT_POOL_MIN_BASE_SCORE:
        return False
    if not item.source_id or not item.title or not item.url.startswith("http"):
        return False
    return True


def apply_scored_selection_to_source_pack(
    source_pack: dict,
    selection: GlobalTop5SelectionResult,
) -> dict:
    """Preserve scored candidate pool for downstream TOP5 diversity selection.

    The prompt/contract stage needs more than the initial scored TOP5 so it can
    reject same-source/entity duplicates and promote the next distinct item.
    """
    pack = dict(source_pack)
    replacement_from_rejected = sorted(
        [s for s in selection.rejected if _is_safe_replacement_candidate(s)],
        key=lambda s: (-s.scores.base_total, s.title),
    )[:REPLACEMENT_POOL_MAX_REJECTED]

    candidate_order = (
        list(selection.selected_top5)
        + list(selection.watchlist)
        + replacement_from_rejected
    )
    candidate_ids = {s.source_id for s in candidate_order if s.source_id}
    candidate_urls = {s.url for s in candidate_order if s.url}

    sources = pack.get("sources") if isinstance(pack.get("sources"), list) else []
    claims = pack.get("claims") if isinstance(pack.get("claims"), list) else []

    new_sources = [
        s
        for s in sources
        if isinstance(s, dict)
        and (
            str(s.get("source_id") or "") in candidate_ids
            or str(s.get("source_url") or "") in candidate_urls
        )
    ]
    new_claims = [
        c
        for c in claims
        if isinstance(c, dict)
        and any(str(sid) in candidate_ids for sid in (c.get("source_ids") or []))
    ]

    score_by_sid = {s.source_id: s for s in candidate_order if s.source_id}
    selected_ids = {s.source_id for s in selection.selected_top5 if s.source_id}
    watchlist_ids = {s.source_id for s in selection.watchlist if s.source_id}
    replacement_ids = {s.source_id for s in replacement_from_rejected if s.source_id}
    for claim in new_claims:
        sids = claim.get("source_ids") if isinstance(claim.get("source_ids"), list) else []
        for sid in sids:
            scored = score_by_sid.get(str(sid))
            if scored:
                claim["selection_score"] = scored.scores.total
                claim["selection_score_before_diversity"] = scored.scores.base_total
                claim["selection_rationale"] = scored.selection_rationale
                claim["selection_classification"] = scored.classification
                claim["primary_category"] = scored.primary_category
                claim["secondary_categories"] = list(scored.secondary_categories)
                claim["category_confidence"] = scored.category_confidence
                claim["reason_for_category"] = scored.reason_for_category
                claim["category_label_ko"] = CATEGORY_KO_LABELS.get(
                    scored.primary_category, scored.category
                )
                claim["hype_warning"] = scored.hype_warning
                claim["sponsored_warning"] = scored.sponsored_warning
                claim["is_sponsored"] = scored.is_sponsored
                claim["selection_note"] = scored.selection_note
                claim["source_name"] = scored.source_name
                claim["source_domain"] = scored.source_domain or _host(scored.url)
                claim["source_count_in_top5"] = scored.source_count_in_top5
                claim["source_diversity_limited"] = scored.source_diversity_limited
                claim["source_concentration_penalty"] = scored.source_concentration_penalty
                claim["source_concentration_reason"] = scored.source_concentration_reason
                if scored.source_id in selected_ids:
                    claim["selection_pool"] = "selected_top5"
                elif scored.source_id in watchlist_ids:
                    claim["selection_pool"] = "watchlist"
                elif scored.source_id in replacement_ids:
                    claim["selection_pool"] = "replacement_candidate"
                if scored.penalty_notes:
                    claim["penalty_notes"] = list(scored.penalty_notes)

    pack["sources"] = new_sources
    pack["claims"] = new_claims
    downstream_ids = [s.source_id for s in candidate_order if s.source_id]
    per_source_candidate_counts = _count_by_source_key(sources)
    per_source_selected_counts = {
        _source_key(s): sum(1 for x in selection.selected_top5 if _source_key(x) == _source_key(s))
        for s in selection.selected_top5
    }
    funnel_summary = {
        "source_fetch_count": len(sources),
        "unique_source_count_before_scoring": len(per_source_candidate_counts),
        "scored_candidate_count": len(selection.all_candidates),
        "scored_selected_count": len(selection.selected_top5),
        "scored_watchlist_count": len(selection.watchlist),
        "scored_rejected_count": len(selection.rejected),
        "replacement_pool_count": len(replacement_from_rejected) + len(selection.watchlist),
        "pre_diversity_candidate_count": len(candidate_order),
        "post_diversity_selected_count": len(selection.selected_top5),
        "diversity_rejected_count": 0,
        "relaxed_due_to_candidate_shortage": False,
        "per_source_candidate_counts": per_source_candidate_counts,
        "per_source_selected_counts": per_source_selected_counts,
    }
    pack["source_pack_funnel_summary"] = funnel_summary
    pack["global_top5_selection"] = {
        "generated_at": selection.generated_at,
        "policy": "keysuri_global_top5_selection_v2_diversity",
        "selected_source_ids": [s.source_id for s in selection.selected_top5],
        "watchlist_source_ids": [s.source_id for s in selection.watchlist],
        "replacement_source_ids": [s.source_id for s in replacement_from_rejected],
        "downstream_candidate_source_ids": downstream_ids,
        "selected_scores": [s.scores.total for s in selection.selected_top5],
        "selected_scores_before_diversity": [s.scores.base_total for s in selection.selected_top5],
        "selected_primary_categories": [s.primary_category for s in selection.selected_top5],
        "final_category_distribution": selection.final_category_distribution,
        "diversity_limited_by_source_pool": selection.diversity_limited_by_source_pool,
        "diversity_quota_decisions": selection.diversity_quota_decisions,
        "watchlist_count": len(selection.watchlist),
        "rejected_count": len(selection.rejected),
        "replacement_pool_count": funnel_summary["replacement_pool_count"],
        "source_pack_funnel_summary": funnel_summary,
    }
    return pack


def write_global_top5_selection_report(
    selection: GlobalTop5SelectionResult,
    path: Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(selection.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def classify_endava_article_test_item() -> ScoredGlobalSignal:
    """Reference classification for OpenAI Endava Frontiers customer case page."""
    return score_global_signal_item(
        {
            "source_id": "live-openai-endava",
            "title": "Endava Frontiers: OpenAI enterprise agents across software delivery",
            "link": _ENDAVA_URL,
            "published_at": _now_kst_iso(),
            "source_name": "OpenAI",
            "source_tier": "T1_OFFICIAL_SECONDARY",
            "category": "enterprise_adoption",
            "summary": (
                "OpenAI highlights Endava as an enterprise case for AI agents moving beyond coding "
                "into software delivery, legal, project management, and operations workflows."
            ),
        }
    )
