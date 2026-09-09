"""Kee-Suri Global/Korea TOP 5 news contract (foundation — not wired to runtime)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from genie_schedule_policy import is_scheduled_trigger_source
from keysuri_korea_signal_scoring import CATEGORY_KO_LABELS, KOREA_TECH_CATEGORIES
from keysuri_source_gate import CONFIDENCE_LABELS, GateResult
from sent_news_dedup_gate import (
    canonicalize_url,
    editorial_cluster_key as _editorial_cluster_key,
    extract_company_entities,
    normalize_title,
    recent_log_duplicate_reason,
    select_with_diversity_caps,
)

KEYSURI_TOP_NEWS_COUNT = 5

# Internal-only marker recorded on the selection result (and, downstream, the
# failure/owner-review artifact) when an owner-review-exposure duplicate had to
# be re-injected to fill the TOP5. Owner-review exposure is not a customer send,
# so on scheduled runs re-showing an already-exposed item is preferable to a hard
# HTTP 500. This code must never surface in reader-facing HTML.
KEYSURI_EXPOSURE_DEDUP_BACKFILL_ISSUE_CODE = "keysuri_korea_exposure_dedup_backfill_used"

#: Raised when the final TOP5 carries cards the scorer classified "reject".
GLOBAL_SELECTION_BELOW_QUALITY_FLOOR = "global_selection_below_quality_floor"

#: Score at which a candidate stops being "reject". Imported rather than
#: duplicated so the selector and the contract stage cannot drift apart.
from keysuri_global_signal_scoring import TOP5_QUALITY_FLOOR_BASE_SCORE  # noqa: E402
NEWS_SCOPE_GLOBAL = "global"
NEWS_SCOPE_KOREA = "korea"

SECTION_TOP5_GLOBAL = "글로벌 테크 TOP 5"
SECTION_TOP5_KOREA = "국내 테크 TOP 5"

KEYSURI_PROGRAM_IDS = frozenset({"keysuri_global_tech", "keysuri_korea_tech"})

PROGRAM_TO_SCOPE: Dict[str, str] = {
    "keysuri_global_tech": NEWS_SCOPE_GLOBAL,
    "keysuri_korea_tech": NEWS_SCOPE_KOREA,
}

PROGRAM_TO_HEADING: Dict[str, str] = {
    "keysuri_global_tech": SECTION_TOP5_GLOBAL,
    "keysuri_korea_tech": SECTION_TOP5_KOREA,
}

FORBIDDEN_TOP5_HEADINGS = frozenset({"TOP 5", "Top 5", "top 5", "TOP 3", "Top 3"})

GLOBAL_NEWS_CATEGORIES = frozenset(
    {
        "ai_product",
        "bigtech",
        "semiconductor",
        "platform",
        "policy",
        "startup",
        "funding",
        "regulation",
        "business_opportunity",
        "security",
        "market_signal",
        "enterprise_adoption",
        "public_support",
        "procurement",
        # Global Tech v2 taxonomy (internal labels — render as natural Korean in prose)
        "ai_software_platform",
        "semiconductor_chip_infra",
        "semiconductor_equipment_materials",
        "robotics_automation_manufacturing",
        "battery_ev_energy_grid",
        "aerospace_satellite_defense_tech",
        "hardware_device_display",
        "cybersecurity_cloud_datacenter",
        "policy_regulation_capital_supplychain",
    }
)

# Korea Tech 18:30 taxonomy (internal slugs — render via CATEGORY_KO_LABELS in prose).
KOREA_NEWS_CATEGORIES = frozenset(KOREA_TECH_CATEGORIES)

KOREA_CATEGORY_DISPLAY_LABELS: Dict[str, str] = dict(CATEGORY_KO_LABELS)

# Backward-compatible alias for Global-only callers.
NEWS_CATEGORIES = GLOBAL_NEWS_CATEGORIES

PROGRAM_KOREA_TECH = "keysuri_korea_tech"
PROGRAM_GLOBAL_TECH = "keysuri_global_tech"

# Korea-only OPTIONAL market-signal fields on TOP5 items. Absent fields are always
# valid (old artifacts / partial Gemini output keep working via renderer fallback);
# when present they must follow this contract so the renderer can trust them.
KOREA_MARKET_LENS_VALUES = frozenset(
    {
        "주식",
        "채권/금리",
        "환율",
        "정책",
        "산업",
        "AI",
        "대기업 투자",
        "중소기업",
        "일자리",
        "자영업",
        "인프라",
        "조달",
        "규제",
    }
)

# Korea market fields are optional. Empty values are treated like missing values
# so old artifacts / partial Gemini output can fall back to renderer inference;
# non-empty dangerous terms remain blocking.
KOREA_MARKET_FIELD_FORBIDDEN_TERMS: Tuple[str, ...] = (
    "매수",
    "매도",
    "강력추천",
    "추천 종목",
    "목표가",
    "목표주가",
    "점수",
    "스코어",
    "총점",
    "90점",
    "투자하라",
    "사라",
    "팔아라",
    "지금 사라",
    "지금 팔아라",
)

# Backward-compatible alias for tests/callers that import the old name.
KOREA_MARKET_IMPACT_FORBIDDEN_DIRECTIVES: Tuple[str, ...] = KOREA_MARKET_FIELD_FORBIDDEN_TERMS

# Contract fallback when Gemini emits a non-dangerous unknown market_lens label.
# Use 산업 — Korea Tech is a broad industry/market-signal briefing; defaulting unknown
# labels to 주식 would over-index stock/investment framing.
KOREA_MARKET_LENS_CONTRACT_FALLBACK = "산업"

# Non-dangerous alias labels map to the allowed enum above — never add "투자" as a
# formal enum; impact-axis names belong in market_impact prose only.
KOREA_MARKET_LENS_ALIASES: Dict[str, str] = {
    "투자": "주식",
    "투자자": "주식",
    "개인 투자자": "주식",
    "투자 관점": "주식",
    "주가": "주식",
    "증시": "주식",
    "수혜주": "주식",
    "시장 신호": "산업",
    "정책금융": "정책",
    "정책 신호": "정책",
    "산업 신호": "산업",
    "사업 신호": "중소기업",
    "기업": "중소기업",
    "사업": "중소기업",
    "소부장": "산업",
    "협력사": "산업",
    "장비": "산업",
    "소재": "산업",
    "부품": "산업",
    "패키징": "산업",
    "전력": "인프라",
    "데이터센터": "인프라",
    "지역": "일자리",
    "프리랜서": "자영업",
    "생활 영향": "일자리",
}

KEYSURI_MARKET_LENS_NORMALIZED_ISSUE_CODE = "keysuri_market_lens_normalized"


def parse_korea_market_lens_values(raw: Any) -> List[str]:
    """Normalize market_lens (string or list) into label list. '/' is kept — it is
    part of the label 채권/금리, not a separator."""
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[·,]", text) if part.strip()]


def korea_market_lens_value_is_dangerous(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return any(term in text for term in KOREA_MARKET_FIELD_FORBIDDEN_TERMS)


def normalize_korea_market_lens_single(value: str) -> Tuple[Optional[str], bool]:
    """Map one label to an allowed enum. Returns (normalized, used_fallback)."""
    text = str(value or "").strip()
    if not text:
        return None, False
    if text in KOREA_MARKET_LENS_VALUES:
        return text, False
    if korea_market_lens_value_is_dangerous(text):
        return text, False
    mapped = KOREA_MARKET_LENS_ALIASES.get(text)
    if mapped:
        return mapped, False
    return KOREA_MARKET_LENS_CONTRACT_FALLBACK, True


def normalize_korea_market_lens_values(raw: Any) -> Tuple[List[str], List[str]]:
    """Normalize parsed market_lens labels; return repair notes for alias/fallback use."""
    parsed = parse_korea_market_lens_values(raw)
    if not parsed:
        return [], []

    normalized: List[str] = []
    repairs: List[str] = []
    seen: Set[str] = set()
    for value in parsed:
        if korea_market_lens_value_is_dangerous(value):
            if value not in seen:
                normalized.append(value)
                seen.add(value)
            continue
        mapped, used_fallback = normalize_korea_market_lens_single(value)
        if mapped is None:
            continue
        if used_fallback or (mapped != value and value not in KOREA_MARKET_LENS_VALUES):
            repairs.append(f"{value}->{mapped}")
        if mapped not in seen:
            normalized.append(mapped)
            seen.add(mapped)
    return normalized, repairs


def repair_korea_market_lens_fields_in_top5(top_5_news: dict) -> Tuple[dict, List[str]]:
    """In-place repair of Korea TOP5 market_lens values; returns repair notes."""
    if not isinstance(top_5_news, dict):
        return top_5_news, []
    repairs: List[str] = []
    items = top_5_news.get("items")
    if not isinstance(items, list):
        return top_5_news, repairs
    for idx, item in enumerate(items):
        if not isinstance(item, dict) or "market_lens" not in item:
            continue
        lens_raw = item.get("market_lens")
        if lens_raw is None:
            continue
        parsed = parse_korea_market_lens_values(lens_raw)
        if not parsed:
            continue
        if any(korea_market_lens_value_is_dangerous(v) for v in parsed):
            continue
        normalized, notes = normalize_korea_market_lens_values(lens_raw)
        if not normalized:
            continue
        if notes:
            repairs.extend(f"items[{idx}].market_lens:{note}" for note in notes)
        if isinstance(lens_raw, str):
            item["market_lens"] = " · ".join(normalized)
        else:
            item["market_lens"] = normalized
    return top_5_news, repairs


def get_news_categories_for_program(program_id: str) -> frozenset[str]:
    """Return allowed TOP5 item category slugs for a Kee-Suri program."""
    pid = (program_id or "").strip()
    if pid == PROGRAM_KOREA_TECH:
        return KOREA_NEWS_CATEGORIES | GLOBAL_NEWS_CATEGORIES
    if pid == PROGRAM_GLOBAL_TECH:
        return GLOBAL_NEWS_CATEGORIES
    if pid in KEYSURI_PROGRAM_IDS:
        return GLOBAL_NEWS_CATEGORIES
    return GLOBAL_NEWS_CATEGORIES

REQUIRED_ITEM_FIELDS = (
    "rank",
    "news_id",
    "headline",
    "category",
    "summary",
    "why_it_matters",
    "business_implication",
    "source_ids",
    "confidence_label",
)

SENSITIVE_CLAIM_TYPES = frozenset(
    {
        "law_policy",
        "executive_order",
        "funding",
        "revenue",
        "numeric",
        "product_spec",
    }
)

CLAIM_TYPE_TO_CATEGORY: Dict[str, str] = {
    "product_spec": "ai_product",
    "general": "startup",
    "interpretation": "business_opportunity",
    "law_policy": "policy",
    "executive_order": "regulation",
    "funding": "funding",
    "revenue": "market_signal",
    "numeric": "market_signal",
    "date": "market_signal",
    "forecast": "market_signal",
}

_TIER_RANK = {
    "T0_OFFICIAL_PRIMARY": 0,
    "T1_OFFICIAL_SECONDARY": 1,
    "T2_TIER1_WIRE": 2,
    "T3_QUALITY_PRESS": 3,
    "T4_AGGREGATOR_BLOG": 4,
    "T5_SOCIAL_UNVERIFIED": 5,
}

_BUSINESS_IMPLICATION_PLACEHOLDER = "검수 필요: business_implication 미작성"


def _issue(code: str, message: str, field: Optional[str] = None) -> Dict[str, str]:
    out: Dict[str, str] = {"code": code, "message": message}
    if field:
        out["field"] = field
    return out


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def expected_news_scope_for_program(program_id: str) -> str:
    key = (program_id or "").strip()
    if key not in PROGRAM_TO_SCOPE:
        raise ValueError(f"Unsupported program_id: {program_id!r}")
    return PROGRAM_TO_SCOPE[key]


def expected_top5_heading_for_program(program_id: str) -> str:
    key = (program_id or "").strip()
    if key not in PROGRAM_TO_HEADING:
        raise ValueError(f"Unsupported program_id: {program_id!r}")
    return PROGRAM_TO_HEADING[key]


def _source_tiers_for_claim(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
) -> List[str]:
    tiers: List[str] = []
    raw_ids = claim.get("source_ids")
    if not isinstance(raw_ids, list):
        return tiers
    for sid in raw_ids:
        src = smap.get(str(sid).strip())
        if src is None:
            continue
        tier = str(src.get("source_tier") or "").strip()
        if tier:
            tiers.append(tier)
    return tiers


def _tiers_only_t4_t5(tiers: Sequence[str]) -> bool:
    return bool(tiers) and all(t in {"T4_AGGREGATOR_BLOG", "T5_SOCIAL_UNVERIFIED"} for t in tiers)


def _best_tier_rank(tiers: Sequence[str]) -> int:
    if not tiers:
        return 99
    return min(_TIER_RANK.get(t, 99) for t in tiers)


def claim_to_news_category(claim: Dict[str, Any]) -> Optional[str]:
    explicit = str(claim.get("news_category") or claim.get("category") or "").strip()
    if explicit in GLOBAL_NEWS_CATEGORIES or explicit in KOREA_NEWS_CATEGORIES:
        return explicit
    claim_type = str(claim.get("claim_type") or "").strip()
    return CLAIM_TYPE_TO_CATEGORY.get(claim_type)


def validate_top_5_news_block(program_id: str, top_5_news: dict) -> List[Dict[str, str]]:
    """Validate a top_5_news object against the TOP 5 news contract."""
    issues: List[Dict[str, str]] = []
    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        issues.append(_issue("unsupported_program_id", f"Unsupported program_id: {program_id!r}"))
        return issues

    if isinstance(top_5_news, list):
        issues.append(
            _issue(
                "top_5_news_must_be_object",
                "top_5_news must be an object, not a plain list",
                "top_5_news",
            )
        )
        return issues

    if not isinstance(top_5_news, dict):
        issues.append(
            _issue(
                "top_5_news_missing_or_invalid",
                "top_5_news must be an object",
                "top_5_news",
            )
        )
        return issues

    expected_scope = expected_news_scope_for_program(pid)
    expected_heading = expected_top5_heading_for_program(pid)

    if pid == "keysuri_korea_tech" and "news_scope" not in top_5_news:
        top_5_news["news_scope"] = expected_scope
        top_5_news["_repaired_news_scope"] = True

    scope = str(top_5_news.get("news_scope") or "").strip()
    if not scope:
        issues.append(
            _issue(
                "top_5_news_scope_missing",
                "top_5_news.news_scope is required",
                "top_5_news.news_scope",
            )
        )
    elif scope != expected_scope:
        issues.append(
            _issue(
                "top_5_news_scope_wrong",
                f"top_5_news.news_scope must be {expected_scope!r}, got {scope!r}",
                "top_5_news.news_scope",
            )
        )

    heading = str(top_5_news.get("section_heading") or "").strip()
    if not heading:
        issues.append(
            _issue(
                "top_5_news_heading_missing",
                "top_5_news.section_heading is required",
                "top_5_news.section_heading",
            )
        )
    elif heading in FORBIDDEN_TOP5_HEADINGS:
        issues.append(
            _issue(
                "top_5_news_heading_forbidden",
                f"top_5_news.section_heading must not be generic {heading!r}",
                "top_5_news.section_heading",
            )
        )
    elif heading != expected_heading:
        issues.append(
            _issue(
                "top_5_news_heading_wrong",
                f"top_5_news.section_heading must be {expected_heading!r}, got {heading!r}",
                "top_5_news.section_heading",
            )
        )

    items = top_5_news.get("items")
    if not isinstance(items, list):
        issues.append(
            _issue(
                "top_5_news_items_invalid",
                "top_5_news.items must be a list",
                "top_5_news.items",
            )
        )
        return issues

    count = len(items)
    if count < KEYSURI_TOP_NEWS_COUNT:
        issues.append(
            _issue(
                "top_5_news_items_too_few",
                f"top_5_news.items must contain exactly {KEYSURI_TOP_NEWS_COUNT} entries, got {count}",
                "top_5_news.items",
            )
        )
    elif count > KEYSURI_TOP_NEWS_COUNT:
        issues.append(
            _issue(
                "top_5_news_items_too_many",
                f"top_5_news.items must contain exactly {KEYSURI_TOP_NEWS_COUNT} entries, got {count}",
                "top_5_news.items",
            )
        )

    ranks_seen: Set[int] = set()
    for idx, item in enumerate(items):
        prefix = f"top_5_news.items[{idx}]"
        if not isinstance(item, dict):
            issues.append(_issue("top_5_news_item_invalid", "Each item must be an object", prefix))
            continue

        rank_raw = item.get("rank")
        if not isinstance(rank_raw, int) or rank_raw not in (1, 2, 3, 4, 5):
            issues.append(
                _issue(
                    "top_5_news_item_rank_invalid",
                    "rank must be an integer 1 through 5",
                    f"{prefix}.rank",
                )
            )
        elif rank_raw in ranks_seen:
            issues.append(
                _issue(
                    "top_5_news_item_rank_duplicate",
                    f"duplicate rank {rank_raw}",
                    f"{prefix}.rank",
                )
            )
        else:
            ranks_seen.add(rank_raw)

        for field in REQUIRED_ITEM_FIELDS:
            if field == "rank":
                continue
            value = item.get(field)
            if field == "source_ids":
                if not isinstance(value, list) or not value:
                    issues.append(
                        _issue(
                            "top_5_news_item_source_ids_missing",
                            "source_ids must be a non-empty list",
                            f"{prefix}.source_ids",
                        )
                    )
                continue
            if field == "category":
                cat = str(value or "").strip()
                allowed_categories = get_news_categories_for_program(pid)
                if cat not in allowed_categories:
                    issues.append(
                        _issue(
                            "top_5_news_item_category_unknown",
                            f"unknown category: {cat!r}",
                            f"{prefix}.category",
                        )
                    )
                continue
            if field == "confidence_label":
                conf = str(value or "").strip()
                if conf not in CONFIDENCE_LABELS:
                    issues.append(
                        _issue(
                            "top_5_news_item_confidence_invalid",
                            f"invalid confidence_label: {conf!r}",
                            f"{prefix}.confidence_label",
                        )
                    )
                continue
            if not _is_non_empty_str(value):
                issues.append(
                    _issue(
                        f"top_5_news_item_{field}_missing",
                        f"{field} must be a non-empty string",
                        f"{prefix}.{field}",
                    )
                )

        if pid == "keysuri_korea_tech":
            headline = str(item.get("headline") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if is_korea_tech_irrelevant_headline(headline, summary):
                issues.append(
                    _issue(
                        "korea_tech_top5_irrelevant_item",
                        f"Item headline/summary contains non-tech foreign/accident news patterns",
                        f"{prefix}.headline",
                    )
                )

            lens_raw = item.get("market_lens")
            if lens_raw is not None:
                if not isinstance(lens_raw, (str, list, tuple)):
                    issues.append(
                        _issue(
                            "top_5_news_item_market_lens_invalid",
                            "market_lens must be a string or list of strings",
                            f"{prefix}.market_lens",
                        )
                    )
                else:
                    lens_values = parse_korea_market_lens_values(lens_raw)
                    if lens_values:
                        forbidden = [
                            term
                            for value in lens_values
                            for term in KOREA_MARKET_FIELD_FORBIDDEN_TERMS
                            if term in value
                        ]
                        if forbidden:
                            issues.append(
                                _issue(
                                    "top_5_news_item_market_lens_forbidden",
                                    f"market_lens must not contain forbidden visible terms: {forbidden!r}",
                                    f"{prefix}.market_lens",
                                )
                            )
                        else:
                            normalized_lens, _ = normalize_korea_market_lens_values(lens_raw)
                            unknown = [v for v in normalized_lens if v not in KOREA_MARKET_LENS_VALUES]
                            if unknown:
                                issues.append(
                                    _issue(
                                        "top_5_news_item_market_lens_unknown",
                                        f"market_lens values not in contract: {unknown!r}",
                                        f"{prefix}.market_lens",
                                    )
                                )
            impact_raw = item.get("market_impact")
            if impact_raw is not None:
                if not isinstance(impact_raw, str):
                    issues.append(
                        _issue(
                            "top_5_news_item_market_impact_invalid",
                            "market_impact must be a string when present",
                            f"{prefix}.market_impact",
                        )
                    )
                else:
                    impact_text = str(impact_raw).strip()
                    hit = [d for d in KOREA_MARKET_FIELD_FORBIDDEN_TERMS if d in impact_text]
                    if hit:
                        issues.append(
                            _issue(
                                "top_5_news_item_market_impact_directive",
                                f"market_impact must not contain buy/sell directives: {hit!r}",
                                f"{prefix}.market_impact",
                            )
                        )

    if items and ranks_seen != {1, 2, 3, 4, 5}:
        issues.append(
            _issue(
                "top_5_news_ranks_incomplete",
                "ranks must include exactly 1, 2, 3, 4, 5",
                "top_5_news.items",
            )
        )

    return issues


def validate_news_scope_matches_program(
    program_id: str,
    source_pack: dict | None = None,
    top_5_news: dict | None = None,
) -> List[Dict[str, str]]:
    """Validate program_id alignment across source_pack and top_5_news."""
    issues: List[Dict[str, str]] = []
    pid = (program_id or "").strip()
    if pid not in KEYSURI_PROGRAM_IDS:
        issues.append(_issue("unsupported_program_id", f"Unsupported program_id: {program_id!r}"))
        return issues

    expected_scope = expected_news_scope_for_program(pid)

    if source_pack is not None:
        if not isinstance(source_pack, dict):
            issues.append(_issue("source_pack_invalid", "source_pack must be a dict"))
        else:
            pack_pid = str(source_pack.get("program_id") or "").strip()
            if pack_pid and pack_pid != pid:
                issues.append(
                    _issue(
                        "source_pack_program_mismatch",
                        f"source_pack.program_id {pack_pid!r} does not match {pid!r}",
                        "source_pack.program_id",
                    )
                )

    if top_5_news is not None:
        issues.extend(validate_top_5_news_block(pid, top_5_news))
        scope = str(top_5_news.get("news_scope") or "").strip() if isinstance(top_5_news, dict) else ""
        if scope and scope != expected_scope:
            issues.append(
                _issue(
                    "news_scope_program_mismatch",
                    f"top_5_news.news_scope {scope!r} does not match program {pid!r}",
                    "top_5_news.news_scope",
                )
            )
    return issues


def is_korea_tech_irrelevant_headline(headline: str, summary: str = "") -> bool:
    """Filter out non-tech / out-of-scope headlines for Korea Tech TOP5.

    Selection-time scope rejects (global leak, casino/local economy, finance-only)
    are authoritative. Accident/crime heuristics remain as a secondary filter.
    """
    from keysuri_korea_signal_scoring import evaluate_korea_tech_scope

    text = f"{headline} {summary}"
    scope_reject, _status = evaluate_korea_tech_scope(text)
    if scope_reject:
        return True

    lower = text.lower()

    # Tech/Industry anchors: If it has these, it is a valid tech/industry news
    tech_anchors = [
        "ai", "반도체", "소부장", "데이터센터", "보안", "클라우드",
        "전력", "에너지", "투자", "규제", "기업", "산업", "스타트업",
        "플랫폼", "saas", "자율주행", "로봇", "스마트팩토리", "배터리",
        "빅테크", "apple", "google", "microsoft", "amazon", "meta", "nvidia",
        "애플", "구글", "마이크로소프트", "아마존", "메타", "엔비디아", "삼성", "sk", "현대", "lg",
    ]
    if any(anchor in lower for anchor in tech_anchors):
        return False

    # General/Foreign Accident patterns (No tech anchor + accident/crime keywords)
    accident_keywords = [
        "사망", "사고", "부상", "살인", "폭행", "경찰", "소방", "체포",
        "재난", "지진", "홍수", "화재", "사상자", "승려", "트럭", "추돌",
        "태국", "중국", "일본", "미국", "유럽", "소년", "소녀", "남성", "여성",
    ]
    accident_matches = sum(1 for kw in accident_keywords if kw in lower)
    if accident_matches >= 2:
        return True

    return False


# --- Global Tech TOP5 signal-quality gate -----------------------------------
# Global Tech TOP5 is a fresh-signal ranking, not a reading list. Evergreen
# educational explainers, consumer-culture soft stories, and corporate blog /
# conference recaps without a concrete change are rejected at selection time —
# regardless of how famous the source outlet is (TechCrunch/NVIDIA/IEEE included).
# The gate is content-based and runs in _claim_is_qualified, so the backfill pool
# cannot bypass it either.

# A/D. Evergreen educational explainer / generic technology background.
GLOBAL_EVERGREEN_EXPLAINER_MARKERS: Tuple[str, ...] = (
    "알아야 할",
    "핵심 지식",
    "기본 개념",
    "기초 지식",
    "기초 개념",
    "입문",
    "이해하기",
    "이해하는 데",
    "란 무엇",
    "이란 무엇",
    "무엇인가",
    "용어 정리",
    "총정리",
    "what is ",
    "what are ",
    "understanding ",
    "explained",
    "explainer",
    "guide to",
    "tutorial",
    "beginner",
    "introduction to",
    "everything you need to know",
    "need to know",
    "the basics",
)

# B. Consumer culture / entertainment soft story.
GLOBAL_CONSUMER_CULTURE_MARKERS: Tuple[str, ...] = (
    "몰아보기",
    "binge",
    "시청 습관",
    "시청 문화",
    "콘텐츠 소비",
    "소비 문화",
    "팬덤",
    "문화 현상",
    "streaming habits",
    "watching habits",
    "pop culture",
    "meme culture",
)

# C. Corporate blog / conference recap markers — allowed only with a concrete change.
GLOBAL_CORPORATE_RECAP_MARKERS: Tuple[str, ...] = (
    "시사점",
    "돌아보기",
    "회고",
    "recap",
    "highlights from",
    "takeaways",
    "what we learned",
    "lessons from",
)

# Concrete-change anchors that let a recap pass: an actual model/paper/benchmark/
# open-source/product change must be named, not just event impressions.
GLOBAL_RECAP_CONCRETE_ANCHORS: Tuple[str, ...] = (
    "공개",
    "출시",
    "발표",
    "릴리스",
    "벤치마크",
    "오픈소스",
    "release",
    "launch",
    "benchmark",
    "open source",
    "open-source",
)

# Action anchors that rescue an explainer/culture-flagged headline: recent product,
# policy, standard, regulation, pricing, security, or commercial-deployment moves.
GLOBAL_SIGNAL_EXCEPTION_ANCHORS: Tuple[str, ...] = (
    "출시",
    "공개",
    "발표",
    "개정",
    "규제",
    "정책 변경",
    "표준 제정",
    "상용",
    "계약",
    "수주",
    "인수",
    "합병",
    "투자 유치",
    "상장",
    "요금제",
    "가격 인상",
    "가격 인하",
    "수익 모델",
    "추천 알고리즘",
    "알고리즘 변경",
    "api 변경",
    "보안 사고",
    "침해",
    "유출",
    "취약점",
    "패치",
    "랜섬웨어",
    "해킹",
    "release",
    "launch",
    "acquisition",
    "funding",
    "ipo",
    "breach",
    "vulnerability",
    "ransomware",
    "pricing",
    "ad tier",
    "ad-supported",
    "regulation",
)


# --- Event novelty: document date is not event date ------------------------
# Incident 2026-09-09 (Global): an AWS Weekly Roundup published 2026-09-07 led
# the briefing as a fresh "Claude Fable 5.1 출시" launch, even though the roundup
# itself said the availability happened "Last week" (2026-09-01). Every existing
# gate passed it, because every existing gate reads a *document* timestamp:
#
#   * source gate  -> fetched_at (when we collected the page)
#   * _score_recency -> published_at (when the page was published)
#
# Neither is the time of the *news development* the item asserts. Re-fetching a
# page, republishing it at a new URL, or recapping it a week later all move a
# document timestamp forward while the underlying event stands still. This
# section keeps the two apart and refuses to promote a backward-referenced
# recap as a new development.
#
# Deliberately NOT a word blacklist and NOT a blanket age rule: a roundup that
# carries its own newly-evidenced development stays eligible, and a genuinely
# current story is never rejected for the age of its subject matter.

# Roundup / week-in-review context. A context signal only — never a rejection
# on its own.
GLOBAL_ROUNDUP_CONTEXT_MARKERS: Tuple[str, ...] = (
    "roundup",
    "round-up",
    "week in review",
    "weekly recap",
    "weekly digest",
    "weekly wrap",
    "this week in",
    "week of ",
    "주간 정리",
    "주간 브리핑",
    "주간 요약",
    "이번 주 정리",
    "이번 주 요약",
)

# Explicit backward attribution: the text itself says the development happened
# before this document. The number is the separation the WORDING suggests, in
# days, and is approximate by nature ("last week" from a Monday post can mean
# 1 day or 13). It is recorded as a hint and never used as a hard date bound —
# the only bound we assert is that the event predates its own document.
GLOBAL_BACKWARD_EVENT_MARKERS: Tuple[Tuple[str, int], ...] = (
    ("last week", 7),
    ("a week ago", 7),
    ("지난주", 7),
    ("지난 주", 7),
    ("last month", 30),
    ("지난달", 30),
    ("지난 달", 30),
    ("earlier this month", 7),
    ("earlier this year", 30),
    ("last year", 180),
    ("작년", 180),
    ("previously announced", 1),
    ("originally announced", 1),
    ("announced earlier", 1),
    ("as announced", 1),
    ("we announced", 1),
    ("앞서 발표", 1),
    ("이미 발표", 1),
    ("기존에 발표", 1),
)

# Wording that asserts a development. Used only to decide WHERE the novelty
# claim sits (backward-attributed sentence vs. its own), never to rescue an
# item by itself.
GLOBAL_DEVELOPMENT_ANCHORS: Tuple[str, ...] = (
    "launch",
    "launches",
    "launched",
    "release",
    "releases",
    "released",
    "announce",
    "announces",
    "announced",
    "announcing",
    "introduc",
    "unveil",
    "now available",
    "became available",
    "generally available",
    "rolls out",
    "rolling out",
    "expands to",
    "price",
    "pricing",
    "acquire",
    "acquisition",
    "vulnerability",
    "breach",
    "patch",
    "출시",
    "공개",
    "발표",
    "인수",
    "가격",
    "취약점",
)

# Present-time framing. Inside a roundup, novelty vocabulary alone proves
# nothing — "launch", "release", "출시" and a famous brand name all appear in a
# recap of last week's news. A development the roundup reports *itself* is
# anchored to the document's own present.
GLOBAL_PRESENT_TIME_ANCHORS: Tuple[str, ...] = (
    "today",
    "이번 주",
    "오늘",
    "this morning",
    "is announcing",
    "are announcing",
    "we are announcing",
    "effective immediately",
    "starting today",
    "as of today",
    "now generally available",
    "지금부터",
    "부터 적용",
)

# A development still reads as "current" inside the same window `_score_recency`
# already treats as recent (its <=48h bucket). Reused deliberately rather than
# invented: this is a FRAMING boundary, not an admission cutoff. Nothing is
# rejected for age — an older item stays selectable, it just may not be
# presented as a new development.
GLOBAL_CURRENT_DEVELOPMENT_WINDOW_HOURS = 48

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")


@dataclass(frozen=True)
class EventNoveltyVerdict:
    """How a candidate's news development relates in time to its document.

    ``event_date_basis`` values:
      * ``document_published_proxy`` — no backward attribution found. The
        publication timestamp is a DISCLOSED PROXY for the event time, never
        verified event evidence: a document published today may be reporting
        something that happened long ago. Absence of backward wording is not
        positive evidence that anything is new.
      * ``backward_relative_unresolved`` — the text attributes the development
        to an earlier period. ``event_not_later_than`` carries the only bound
        that cannot be falsified (the event predates its own document), and
        ``event_age_hint_days`` records what the wording loosely suggests. The
        exact event date stays unknown on purpose.
      * ``unknown`` — no usable publication date, so no event date can be
        derived. Never silently replaced with a fetch time or with "today".
    """

    is_roundup: bool = False
    backward_reference: str = ""
    event_age_hint_days: int = 0
    event_date_basis: str = "document_published_proxy"
    event_not_later_than: str = ""
    has_independent_development: bool = False
    eligible_as_new_development: bool = True
    presentable_as_new_development: bool = True
    framing_role: str = "new_development"
    document_age_hours: Optional[float] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_roundup": self.is_roundup,
            "backward_reference": self.backward_reference,
            "event_age_hint_days": self.event_age_hint_days,
            "event_date_basis": self.event_date_basis,
            "event_not_later_than": self.event_not_later_than,
            "has_independent_development": self.has_independent_development,
            "eligible_as_new_development": self.eligible_as_new_development,
            "presentable_as_new_development": self.presentable_as_new_development,
            "framing_role": self.framing_role,
            "document_age_hours": self.document_age_hours,
            "novelty_reason": self.reason,
        }


def _parse_event_dt(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
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


def _document_age_hours(pub_dt: datetime, as_of: str) -> Optional[float]:
    """Hours between a document's publication and the briefing's own clock.

    Returns None when no evaluation time was supplied — the age is then unknown
    and is never guessed from wall time.
    """
    ref = _parse_event_dt(as_of)
    if ref is None:
        return None
    if pub_dt.tzinfo is None or ref.tzinfo is None:
        return None
    return (ref - pub_dt).total_seconds() / 3600.0


def _backward_marker_in(text: str) -> Tuple[str, int]:
    """Return the strongest backward attribution present in ``text``."""
    best = ("", 0)
    for marker, hint_days in GLOBAL_BACKWARD_EVENT_MARKERS:
        if marker in text and hint_days > best[1]:
            best = (marker, hint_days)
    return best


def _independent_development_evidence(body: str) -> bool:
    """True only on positive evidence that the text reports something new itself.

    Requires a sentence that carries no backward attribution, asserts a
    development, AND anchors it to the document's own present. Silence is never
    treated as evidence.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(body.lower()):
        chunk = sentence.strip()
        if not chunk:
            continue
        if _backward_marker_in(chunk)[0]:
            continue
        if not any(anchor in chunk for anchor in GLOBAL_DEVELOPMENT_ANCHORS):
            continue
        if any(anchor in chunk for anchor in GLOBAL_PRESENT_TIME_ANCHORS):
            return True
    return False


def classify_global_event_novelty(
    headline: str,
    summary: str = "",
    *,
    published_at: str = "",
    as_of: str = "",
) -> EventNoveltyVerdict:
    """Decide whether a candidate asserts a development that is new *now*.

    The narrow rule this implements: **a recap whose development is attributed
    to an earlier period, and which carries no independently-evidenced
    development of its own, may not be promoted as a new development.**

    A roundup that also reports something new on its own keeps its eligibility;
    only the backward-referenced part loses it. The event date is never taken
    from the roundup — a resolved bound is recorded against the *document's*
    publication context, not against fetch time or "today".
    """
    head = str(headline or "")
    body = str(summary or "")
    text = f"{head} {body}".lower()

    is_roundup = any(marker in text for marker in GLOBAL_ROUNDUP_CONTEXT_MARKERS)
    backward_marker, min_age_days = _backward_marker_in(text)

    pub_dt = _parse_event_dt(published_at)
    if pub_dt is None:
        # No usable publication date. Record the gap explicitly rather than
        # borrowing a fetch time or asserting "today".
        return EventNoveltyVerdict(
            is_roundup=is_roundup,
            backward_reference=backward_marker,
            event_age_hint_days=min_age_days,
            event_date_basis="unknown",
            event_not_later_than="",
            has_independent_development=False,
            eligible_as_new_development=not (is_roundup and bool(backward_marker)),
            presentable_as_new_development=False,
            framing_role="historical_followup",
            reason=(
                "global_recap_backward_referenced_event"
                if (is_roundup and backward_marker)
                else "event_date_unknown"
            ),
        )

    if not backward_marker:
        # No backward wording. That is the ABSENCE of counter-evidence, not the
        # presence of evidence that something is new, so newness is decided by
        # what the item positively shows: either it reports a development
        # anchored to its own present, or its document is still inside the
        # window the product already treats as current. Otherwise it stays
        # selectable but must be framed as historical follow-up, never as a new
        # launch.
        independent = _independent_development_evidence(body)
        age_h = _document_age_hours(pub_dt, as_of)
        within_window = (
            age_h is not None and age_h <= GLOBAL_CURRENT_DEVELOPMENT_WINDOW_HOURS
        )
        presentable = bool(independent or within_window or age_h is None)
        return EventNoveltyVerdict(
            is_roundup=is_roundup,
            event_date_basis="document_published_proxy",
            event_not_later_than=pub_dt.isoformat(),
            has_independent_development=independent,
            eligible_as_new_development=True,
            presentable_as_new_development=presentable,
            framing_role=(
                "new_development" if presentable else "historical_followup"
            ),
            document_age_hours=age_h,
            reason="" if presentable else "global_past_announcement_no_new_development",
        )

    # The text attributes a development to an earlier period. The only bound
    # the evidence actually supports is that the event predates its own
    # document — anchored to the DOCUMENT's publication, never to the current
    # clock. Subtracting the wording's nominal offset would manufacture a date
    # ("last week" from a Monday post is anywhere from 1 to 13 days back), so
    # the offset is kept as an approximate hint instead.
    bound = pub_dt.isoformat()

    # Does the item report anything new on its own? Positive evidence only --
    # novelty vocabulary by itself is exactly what a recap of an old launch is
    # full of, and a roundup headline is a table of contents.
    independent = _independent_development_evidence(body)
    age_h = _document_age_hours(pub_dt, as_of)

    if not is_roundup:
        # A normal article that mentions an earlier announcement in passing is
        # still a current story. Only record the provenance.
        within_window = (
            age_h is not None and age_h <= GLOBAL_CURRENT_DEVELOPMENT_WINDOW_HOURS
        )
        presentable = bool(independent or within_window or age_h is None)
        return EventNoveltyVerdict(
            is_roundup=False,
            backward_reference=backward_marker,
            event_age_hint_days=min_age_days,
            event_date_basis="backward_relative_unresolved",
            event_not_later_than=bound,
            has_independent_development=independent,
            eligible_as_new_development=True,
            presentable_as_new_development=presentable,
            framing_role=(
                "new_development" if presentable else "historical_followup"
            ),
            document_age_hours=age_h,
            reason="" if presentable else "global_past_announcement_no_new_development",
        )

    eligible = independent
    return EventNoveltyVerdict(
        is_roundup=True,
        backward_reference=backward_marker,
        event_age_hint_days=min_age_days,
        event_date_basis="backward_relative_unresolved",
        event_not_later_than=bound,
        has_independent_development=independent,
        eligible_as_new_development=eligible,
        presentable_as_new_development=eligible,
        framing_role="new_development" if eligible else "historical_followup",
        document_age_hours=age_h,
        reason="" if eligible else "global_recap_backward_referenced_event",
    )


def _explainer_marker_present(text: str, markers: Sequence[str]) -> bool:
    """Match evergreen-explainer markers against lowercased text.

    Single-token ASCII markers (e.g. "explained", "tutorial") match on a word
    boundary so they do not fire inside a larger word — "explained" must NOT flag
    "unexplained cloud outage". Korean markers and multi-word English phrases keep
    substring semantics (Korean has no word boundaries; a phrase substring is
    already specific enough).
    """
    for marker in markers:
        token = marker.strip()
        if not token:
            continue
        if " " in marker or not token.isascii():
            if marker in text:
                return True
        elif re.search(rf"\b{re.escape(token)}\b", text):
            return True
    return False


def is_global_tech_low_signal_headline(headline: str, summary: str = "") -> Tuple[bool, str]:
    """Return (True, reason) when a Global Tech candidate is a low-signal story.

    Covers: evergreen educational explainers, consumer-culture/entertainment soft
    stories, and corporate blog/conference recaps without a concrete change. A
    flagged headline is rescued only by explicit action anchors (release, policy,
    regulation, pricing, security incident, commercial deployment).
    """
    raw = f"{headline} {summary}"
    # 가이드라인 (policy guideline) must not trigger the 가이드 explainer marker.
    text = raw.replace("가이드라인", "").lower()

    has_exception = any(anchor in text for anchor in GLOBAL_SIGNAL_EXCEPTION_ANCHORS)

    explainer_hit = "가이드" in text or _explainer_marker_present(
        text, GLOBAL_EVERGREEN_EXPLAINER_MARKERS
    )
    if explainer_hit and not has_exception:
        return True, "global_evergreen_explainer"

    culture_hit = any(marker in text for marker in GLOBAL_CONSUMER_CULTURE_MARKERS)
    if culture_hit and not has_exception:
        return True, "global_consumer_culture_story"

    recap_hit = any(marker in text for marker in GLOBAL_CORPORATE_RECAP_MARKERS)
    if recap_hit and not any(anchor in text for anchor in GLOBAL_RECAP_CONCRETE_ANCHORS):
        return True, "global_corporate_recap_no_concrete_change"

    return False, ""


def _claim_published_at(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
) -> str:
    """Document publication date for a claim, from its sources.

    Deliberately does NOT fall back to ``fetched_at``: when we collected a page
    says nothing about when it was published, and substituting one for the
    other is what lets an old event read as new.
    """
    direct = str(claim.get("published_at") or "").strip()
    if direct:
        return direct
    for sid in claim.get("source_ids") or []:
        src = smap.get(str(sid))
        if isinstance(src, dict):
            value = str(src.get("published_at") or "").strip()
            if value:
                return value
    return ""


def _news_item_is_current_development(item: Dict[str, Any], as_of: str = "") -> bool:
    """Item-level mirror of the claim-level event-novelty rule.

    Used where an already-materialised news item (not a claim) re-enters the
    pool, so no admission path reaches a different verdict than the primary
    ranking did.
    """
    if not isinstance(item, dict):
        return False
    headline = str(item.get("headline") or item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    verdict = classify_global_event_novelty(
        headline,
        summary,
        published_at=str(item.get("published_at") or "").strip(),
        as_of=as_of,
    )
    return verdict.eligible_as_new_development


def _claim_fetched_at(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
) -> str:
    """Collection timestamp for a claim — kept distinct from publication."""
    direct = str(claim.get("fetched_at") or "").strip()
    if direct:
        return direct
    for sid in claim.get("source_ids") or []:
        src = smap.get(str(sid))
        if isinstance(src, dict):
            value = str(src.get("fetched_at") or "").strip()
            if value:
                return value
    return ""


def _claim_is_qualified(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
    program_id: str = "",
    as_of: str = "",
) -> Tuple[bool, str]:
    if not isinstance(claim, dict):
        return False, "invalid_claim"
    if not claim.get("source_ids"):
        return False, "missing_source_ids"
    confidence = str(claim.get("confidence_label") or "").strip()
    if confidence == "unverified":
        return False, "unverified_confidence"
    claim_type = str(claim.get("claim_type") or "").strip()
    tiers = _source_tiers_for_claim(claim, smap)
    if claim_type in SENSITIVE_CLAIM_TYPES and _tiers_only_t4_t5(tiers):
        return False, "t4_t5_only_sensitive"
    if not claim_to_news_category(claim):
        return False, "unmapped_category"
    if not _is_non_empty_str(claim.get("statement")):
        return False, "missing_statement"
    if program_id == "keysuri_korea_tech":
        headline = str(claim.get("headline") or claim.get("statement") or "").strip()
        summary = str(claim.get("summary") or "").strip()
        if is_korea_tech_irrelevant_headline(headline, summary):
            return False, "korea_tech_irrelevant_headline"
    if program_id == "keysuri_global_tech":
        headline = str(claim.get("headline") or claim.get("statement") or "").strip()
        summary = str(claim.get("summary") or "").strip()
        low_signal, reason = is_global_tech_low_signal_headline(headline, summary)
        if low_signal:
            return False, reason
        # Temporal identity: a recap may not re-present an old event as new.
        # Runs on the same gate as every other content rule, so the primary
        # ranking and the backfill pool reach the same verdict.
        verdict = classify_global_event_novelty(
            headline,
            summary,
            published_at=_claim_published_at(claim, smap),
            as_of=as_of,
        )
        if not verdict.eligible_as_new_development:
            return False, verdict.reason or "global_recap_backward_referenced_event"
    return True, "ok"


def _source_domain_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    netloc = urlsplit(raw).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _resolve_claim_source(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Hydrate source/url metadata from the first resolvable source_id.

    Without this the dedup gate sees empty source/url and its source/url layers
    silently no-op (the root cause of same-outlet TOP5 duplicates).
    """
    source_name = ""
    url = ""
    for sid in claim.get("source_ids") or []:
        src = smap.get(str(sid).strip())
        if not isinstance(src, dict):
            continue
        source_name = str(src.get("source_name") or src.get("publisher") or src.get("name") or "").strip()
        url = str(src.get("source_url") or src.get("url") or src.get("link") or "").strip()
        if source_name or url:
            break
    return {
        "source": source_name,
        "source_name": source_name,
        "url": url,
        "canonical_url": canonicalize_url(url),
        "normalized_source": normalize_title(source_name),
        "source_domain": _source_domain_from_url(url),
    }


def _claim_to_news_item(
    claim: Dict[str, Any],
    rank: int,
    smap: Optional[Dict[str, Dict[str, Any]]] = None,
    program_id: str = "",
    as_of: str = "",
) -> Dict[str, Any]:
    primary = str(claim.get("primary_category") or "").strip()
    category = primary or claim_to_news_category(claim) or "market_signal"
    claim_id = str(claim.get("claim_id") or f"news-{rank}").strip()
    statement = str(claim.get("statement") or "").strip()
    summary = str(claim.get("summary") or statement).strip()
    why = str(claim.get("why_it_matters") or claim.get("statement") or "").strip()
    biz = str(claim.get("business_implication") or "").strip()
    if not biz:
        biz = _BUSINESS_IMPLICATION_PLACEHOLDER
    item: Dict[str, Any] = {
        "rank": rank,
        "news_id": claim_id,
        "headline": str(claim.get("headline") or statement[:120]).strip(),
        "category": category,
        "summary": summary,
        "why_it_matters": why,
        "business_implication": biz,
        "source_ids": list(claim.get("source_ids") or []),
        "confidence_label": str(claim.get("confidence_label") or "reported").strip(),
    }
    item.update(_resolve_claim_source(claim, smap or {}))
    # Date provenance travels with the item: which timestamp we hold, what it
    # means, and how the event relates to it. Downstream surfaces must be able
    # to tell a document date from an event date without re-deriving it.
    if program_id == "keysuri_global_tech":
        published_at = _claim_published_at(claim, smap or {})
        if published_at:
            item["published_at"] = published_at
        fetched_at = _claim_fetched_at(claim, smap or {})
        if fetched_at:
            item["fetched_at"] = fetched_at
        item["event_novelty"] = classify_global_event_novelty(
            item.get("headline") or statement,
            summary,
            published_at=published_at,
            as_of=as_of,
        ).to_dict()
    risk = claim.get("risk_note")
    if _is_non_empty_str(risk):
        item["risk_note"] = str(risk).strip()
    return item


# --- Cross-day editorial novelty (Phase 4) --------------------------------
# Exact URL/title dedup stops the same *article* recurring; it does nothing about
# the same *ecosystem* recurring. 2026-08-24/25/26 Global each led with NVIDIA AI
# Factory + OpenAI + IEEE Spectrum: fifteen TOP5 slots, nine of them those three
# source brands, three days of near-identical narrative, and every article
# technically new. These weights demote a candidate whose source / entity /
# editorial cluster has dominated recent owner-review briefings — as a bounded
# rank offset, never a ban, so a materially stronger signal still wins and a
# genuinely important repeat NVIDIA story can still lead.
_CROSS_DAY_AXIS_PENALTY_CAP = 2
_CROSS_DAY_TOTAL_PENALTY_CAP = 3


def _recent_axis_day_counts(
    recent_rows: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, set], Dict[str, set], Dict[str, set]]:
    """Distinct KST days on which each source / entity / cluster was exposed."""
    by_source: Dict[str, set] = {}
    by_entity: Dict[str, set] = {}
    by_cluster: Dict[str, set] = {}
    for row in recent_rows:
        if not isinstance(row, dict):
            continue
        day = str(row.get("exposed_date_kst") or row.get("sent_date_kst") or "").strip()
        if not day:
            day = str(row.get("run_id") or "").strip()
        if not day:
            continue
        source = str(row.get("normalized_source") or row.get("source") or "").strip().lower()
        if source:
            by_source.setdefault(source, set()).add(day)
        cluster = str(row.get("editorial_cluster_key") or "").strip().lower()
        if cluster:
            by_cluster.setdefault(cluster, set()).add(day)
        for entity in row.get("entity_keys") or []:
            key = str(entity or "").strip().lower()
            if key:
                by_entity.setdefault(key, set()).add(day)
    return by_source, by_entity, by_cluster


def _cross_day_novelty_penalty(
    item: Dict[str, Any],
    by_source: Dict[str, set],
    by_entity: Dict[str, set],
    by_cluster: Dict[str, set],
) -> Dict[str, Any]:
    source = str(item.get("normalized_source") or item.get("source") or "").strip().lower()
    # Candidate-pool items are not yet enriched with the structured keys the
    # exposure log stores, so derive them the same way the log does. Without
    # this, entity and cluster penalties silently evaluate to zero and the whole
    # signal collapses to "same source brand", which every major feed trips.
    cluster = str(item.get("editorial_cluster_key") or "").strip().lower()
    if not cluster:
        cluster = str(_editorial_cluster_key(item) or "").strip().lower()
    raw_entities = item.get("entity_keys")
    if not isinstance(raw_entities, list) or not raw_entities:
        raw_entities = extract_company_entities(item)
    entities = [
        str(entity or "").strip().lower()
        for entity in (raw_entities or [])
        if str(entity or "").strip()
    ]
    source_penalty = min(_CROSS_DAY_AXIS_PENALTY_CAP, len(by_source.get(source, ())) if source else 0)
    cluster_penalty = min(
        _CROSS_DAY_AXIS_PENALTY_CAP, len(by_cluster.get(cluster, ())) if cluster else 0
    )
    entity_penalty = min(
        _CROSS_DAY_AXIS_PENALTY_CAP,
        max((len(by_entity.get(entity, ())) for entity in entities), default=0),
    )
    total = min(
        _CROSS_DAY_TOTAL_PENALTY_CAP, source_penalty + entity_penalty + cluster_penalty
    )
    return {
        "recent_source_penalty": source_penalty,
        "recent_entity_penalty": entity_penalty,
        "recent_cluster_penalty": cluster_penalty,
        "cross_day_novelty_penalty": total,
    }


def apply_cross_day_novelty_ordering(
    pool: List[Dict[str, Any]],
    recent_rows: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Bounded re-ordering of an already score-ordered pool.

    The penalty is added to the candidate's existing rank, so it can move a
    candidate down by at most ``_CROSS_DAY_TOTAL_PENALTY_CAP`` places' worth of
    score advantage. A candidate that is genuinely stronger by a wider margin
    keeps its lead — repetition is a tie-breaker, not censorship.
    """
    if not pool or not recent_rows:
        return list(pool), []
    by_source, by_entity, by_cluster = _recent_axis_day_counts(recent_rows)
    if not (by_source or by_entity or by_cluster):
        return list(pool), []
    decisions: List[Dict[str, Any]] = []
    keyed: List[Tuple[float, int, Dict[str, Any]]] = []
    for index, item in enumerate(pool):
        penalties = _cross_day_novelty_penalty(item, by_source, by_entity, by_cluster)
        penalty = int(penalties["cross_day_novelty_penalty"])
        keyed.append((index + penalty, index, item))
        if penalty:
            decisions.append(
                {
                    "news_id": item.get("news_id") or item.get("claim_id") or "",
                    "title": item.get("title") or item.get("headline") or "",
                    "source": item.get("normalized_source") or item.get("source") or "",
                    "original_rank": index,
                    "effective_rank": index + penalty,
                    **penalties,
                }
            )
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    reordered = [entry[2] for entry in keyed]
    for decision in decisions:
        decision["final_rank"] = next(
            (i for i, candidate in enumerate(reordered)
             if (candidate.get("news_id") or candidate.get("claim_id") or "") == decision["news_id"]),
            None,
        )
        decision["demoted"] = (
            decision["final_rank"] is not None
            and decision["final_rank"] > decision["original_rank"]
        )
    return reordered, decisions


def select_top_5_news(
    source_pack: dict,
    gate_result: GateResult,
    recent_dedup_rows: Optional[List[Dict[str, Any]]] = None,
    *,
    sent_log_rows: Optional[List[Dict[str, Any]]] = None,
    exposure_log_rows: Optional[List[Dict[str, Any]]] = None,
    trigger_source: Optional[str] = None,
    allow_exposure_backfill: Optional[bool] = None,
) -> dict:
    """
    Select TOP 5 news items from staged source_pack.claims (no live fetch).

    Returns dict with verdict pass|hold|block and optional top_5_news / issues.

    Cross-day dedup runs over the FULL hydrated candidate pool BEFORE the
    intra-briefing diversity selection, so a recent-log duplicate is dropped and
    backfilled from the next fresh candidate instead of shrinking the final five.

    Two dedup layers with different strictness:

    * ``sent_log_rows`` — items already sent to *customers*. These are a HARD
      block: never re-selected, never backfilled.
    * ``exposure_log_rows`` — items shown only in an earlier *owner-review* email
      the same window. These are a SOFT duplicate: removed first, but on a
      scheduled run they may be re-injected (controlled backfill) rather than
      collapsing the run into a hold, because an owner-review re-exposure is not a
      customer send. Manual/QA runs keep them as a hard block so the operator sees
      the real dedup state.

    ``recent_dedup_rows`` is the legacy combined param and is treated as a hard
    block (used by reissue to exclude a parent run's items). When ``sent_log_rows``
    /``exposure_log_rows`` are supplied they take precedence for the layered logic.

    Backfill priority when the fresh deduped pool is short: first fill from the
    source_pack's fresh ``backfill_claims`` (never-selected, in-scope watchlist
    items, themselves dedup-checked), then — only if still short and allowed —
    re-inject the soft (owner-review-exposure) duplicates. Customer-sent items are
    never used to backfill. If neither can reach five, a ``hold`` verdict with a
    full candidate funnel summary is returned so the caller safe-fails.
    """
    if gate_result.verdict == "block":
        raise ValueError("source gate blocked; cannot select top news")

    if not isinstance(source_pack, dict):
        raise ValueError("source_pack must be a dict")

    program_id = str(source_pack.get("program_id") or "").strip()
    if program_id not in KEYSURI_PROGRAM_IDS:
        raise ValueError(f"Unsupported source_pack.program_id: {program_id!r}")

    # The briefing's own clock. Document age is measured against when THIS
    # briefing collected its sources, never against wall time, so a replay of
    # frozen evidence reaches the same framing verdict.
    pack_as_of = str(source_pack.get("generated_at") or "").strip()

    sources = source_pack.get("sources") if isinstance(source_pack.get("sources"), list) else []
    smap: Dict[str, Dict[str, Any]] = {}
    for src in sources:
        if isinstance(src, dict):
            sid = str(src.get("source_id") or "").strip()
            if sid:
                smap[sid] = src

    claims = source_pack.get("claims") if isinstance(source_pack.get("claims"), list) else []
    qualified: List[Tuple[int, Dict[str, Any]]] = []
    missing_biz_impl = False

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        ok, _reason = _claim_is_qualified(claim, smap, program_id, pack_as_of)
        if not ok:
            continue
        tier_rank = _best_tier_rank(_source_tiers_for_claim(claim, smap))
        if not _is_non_empty_str(claim.get("business_implication")):
            missing_biz_impl = True
        qualified.append((tier_rank, claim))

    global_sel = source_pack.get("global_top5_selection")
    if program_id == "keysuri_global_tech" and isinstance(global_sel, dict):
        order = global_sel.get("downstream_candidate_source_ids") or global_sel.get("selected_source_ids")
        if isinstance(order, list) and order:
            rank_map = {str(sid): idx for idx, sid in enumerate(order)}
            qualified.sort(
                key=lambda pair: (
                    min(
                        rank_map.get(str(sid), 999)
                        for sid in (pair[1].get("source_ids") or [])
                    ),
                    pair[0],
                    str(pair[1].get("claim_id") or ""),
                )
            )
        else:
            qualified.sort(key=lambda pair: (-int(pair[1].get("selection_score") or 0), pair[0]))
    else:
        qualified.sort(key=lambda pair: (pair[0], str(pair[1].get("claim_id") or "")))

    # The product quality floor, enforced where the briefing is actually built.
    #
    # It was added to ``_select_diverse_top5`` on 2026-08-29, which decides the
    # *pack's* ``selected_top5``. This function does not read that decision — it
    # picks from every qualified claim, replacement candidates included — so the
    # floor never governed the briefing. Qualification on 2026-08-30 replayed the
    # 08-29 pack and got three below-floor cards through:
    #
    #   3 new ways to plan and book travel in Search        base 44  reject
    #   Trump admin considers more semiconductor tariffs    base 43  reject
    #   Is the best way to watch a movie on sunglasses?     base 39  reject
    #
    # ``reject`` is the scorer's own verdict for "below the bar"
    # (``_classify_total``: >=45 watchlist, below that reject). Filling five
    # slots is not a reason to publish one.
    #
    # Applied only to claims that actually carry a numeric base score, so a pack
    # produced without scoring is unaffected. Korea scores on the same field and
    # sits well above the floor (58-69 on the pinned 08-26 pack).
    below_floor_refused: List[str] = []
    floored: List[Any] = []
    for pair in qualified:
        claim = pair[1]
        base = claim.get("selection_score_before_diversity")
        if base is None:
            base = claim.get("selection_score")
        if isinstance(base, (int, float)) and base < TOP5_QUALITY_FLOOR_BASE_SCORE:
            below_floor_refused.append(
                f"{claim.get('claim_id')}:{base}:{str(claim.get('headline') or '')[:60]}"
            )
            continue
        floored.append(pair)
    qualified = floored

    if missing_biz_impl:
        return {
            "verdict": "hold",
            "issues": [
                _issue(
                    "business_implication_missing",
                    "One or more qualified claims lack business_implication",
                )
            ],
        }

    if len(qualified) < KEYSURI_TOP_NEWS_COUNT:
        # Fail closed. Topping the list up from the reject pile is what put five
        # cards the scorer had already refused in front of the owner.
        detail = (
            f"Need {KEYSURI_TOP_NEWS_COUNT} qualified claims, found {len(qualified)}"
        )
        if below_floor_refused:
            detail += (
                f"; {len(below_floor_refused)} refused below quality floor "
                f"{TOP5_QUALITY_FLOOR_BASE_SCORE}: "
                + "; ".join(below_floor_refused[:5])
            )
        return {
            "verdict": "hold",
            "issues": [_issue("insufficient_top_news_candidates", detail)],
            "below_quality_floor_refused": below_floor_refused,
        }

    # Hydrate the FULL qualified pool (not just the first 5), then apply the
    # intra-briefing diversity caps over the priority-ordered candidates so a
    # capped duplicate is replaced by the next distinct candidate instead of
    # only shrinking the final five.
    hydrated = [
        _claim_to_news_item(
            claim, rank=i + 1, smap=smap, program_id=program_id, as_of=pack_as_of
        )
        for i, (_t, claim) in enumerate(qualified)
    ]

    # Resolve the two dedup layers. When the caller supplies the split rows we run
    # the layered (hard sent / soft exposure) logic; otherwise fall back to the
    # legacy combined param, treated entirely as a hard block for compatibility.
    layered = sent_log_rows is not None or exposure_log_rows is not None
    hard_rows = [row for row in (sent_log_rows or []) if isinstance(row, dict)]
    soft_rows = [row for row in (exposure_log_rows or []) if isinstance(row, dict)]
    # Legacy/reissue rows are always a hard block (never backfilled).
    hard_rows += [row for row in (recent_dedup_rows or []) if isinstance(row, dict)]

    if allow_exposure_backfill is None:
        # Owner-review exposure is a SOFT duplicate, and a soft duplicate must
        # never be able to force a hold: collapsing below five is strictly worse
        # for the owner than a recorded repeat, and it is the historic
        # "fewer than 5 candidates" failure. So last-resort backfill is always
        # permitted; `trigger_source` only records whether this was a scheduled
        # run, because the *preference* for fresh candidates (applied above) is
        # what differs, not the willingness to avoid an under-count.
        allow_exposure_backfill = True
    scheduled_trigger = is_scheduled_trigger_source(trigger_source)

    # Cross-day dedup over the FULL hydrated pool, applied BEFORE the diversity
    # caps so a recent-log duplicate is dropped and backfilled from the next fresh
    # candidate instead of shrinking the final five. (Running this after selection
    # is the root cause of 4-item TOP5.)
    candidate_count_before_dedup = len(hydrated)
    hard_rejected: List[Dict[str, Any]] = []
    soft_rejected: List[Dict[str, Any]] = []
    deduped_pool: List[Dict[str, Any]] = []
    for item in hydrated:
        hard_reason = recent_log_duplicate_reason(item, hard_rows) if hard_rows else ""
        if hard_reason:
            hard_rejected.append({**item, "rejected_reason": hard_reason})
            continue
        soft_reason = recent_log_duplicate_reason(item, soft_rows) if soft_rows else ""
        if soft_reason:
            soft_rejected.append({**item, "rejected_reason": soft_reason})
            continue
        deduped_pool.append(item)

    dedup_removed_by_sent_log_count = len(hard_rejected)
    dedup_removed_by_exposure_log_count = len(soft_rejected)
    cross_day_rejected = hard_rejected + soft_rejected
    cross_day_dedup_removed_count = len(cross_day_rejected)
    candidate_count_after_hard_dedup = candidate_count_before_dedup - dedup_removed_by_sent_log_count

    # Fresh backfill: never-selected, in-scope watchlist claims carried by the
    # source pack. Dedup-check them against BOTH layers so we never re-add a
    # customer-sent or already-exposed item as if it were fresh.
    exposure_backfill_used = False
    fresh_backfill_used_count = 0
    exposure_backfill_used_count = 0
    if len(deduped_pool) < KEYSURI_TOP_NEWS_COUNT:
        seen_ids = {str(it.get("news_id") or "") for it in deduped_pool}
        backfill_claims = (
            source_pack.get("backfill_claims")
            if isinstance(source_pack.get("backfill_claims"), list)
            else []
        )
        backfill_sources = (
            source_pack.get("backfill_sources")
            if isinstance(source_pack.get("backfill_sources"), list)
            else []
        )
        bsmap = dict(smap)
        for src in backfill_sources:
            if isinstance(src, dict):
                sid = str(src.get("source_id") or "").strip()
                if sid:
                    bsmap[sid] = src
        for j, claim in enumerate(backfill_claims):
            if len(deduped_pool) >= KEYSURI_TOP_NEWS_COUNT:
                break
            if not isinstance(claim, dict):
                continue
            ok, _reason = _claim_is_qualified(claim, bsmap, program_id, pack_as_of)
            if not ok or not _is_non_empty_str(claim.get("business_implication")):
                continue
            item = _claim_to_news_item(
                claim,
                rank=candidate_count_before_dedup + j + 1,
                smap=bsmap,
                program_id=program_id,
                as_of=pack_as_of,
            )
            if str(item.get("news_id") or "") in seen_ids:
                continue
            if hard_rows and recent_log_duplicate_reason(item, hard_rows):
                continue
            if soft_rows and recent_log_duplicate_reason(item, soft_rows):
                continue
            deduped_pool.append(item)
            seen_ids.add(str(item.get("news_id") or ""))
            fresh_backfill_used_count += 1

    # Controlled backfill of last resort: re-inject soft (owner-review-exposure)
    # duplicates so a scheduled run recovers instead of returning HTTP 500. Never
    # touches customer-sent (hard) items.
    if (
        len(deduped_pool) < KEYSURI_TOP_NEWS_COUNT
        and allow_exposure_backfill
        and soft_rejected
    ):
        need = KEYSURI_TOP_NEWS_COUNT - len(deduped_pool)
        for row in soft_rejected:
            if exposure_backfill_used_count >= need:
                break
            item = {k: v for k, v in row.items() if k != "rejected_reason"}
            # Last-resort re-injection is still an admission path. An item that
            # the event-novelty rule refuses may not re-enter here just because
            # it was exposed in an earlier owner-review email.
            if program_id == "keysuri_global_tech" and not _news_item_is_current_development(item, pack_as_of):
                continue
            deduped_pool.append(item)
            exposure_backfill_used_count += 1
        exposure_backfill_used = exposure_backfill_used_count > 0

    candidate_count_after_dedup = len(deduped_pool)

    source_pack_funnel = (
        source_pack.get("source_pack_funnel_summary")
        if isinstance(source_pack.get("source_pack_funnel_summary"), dict)
        else {}
    )

    def _funnel(selected_count: int, hold_reason: Optional[str] = None) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            **source_pack_funnel,
            "candidate_count_before_dedup": candidate_count_before_dedup,
            "sent_log_read_count": len(hard_rows),
            "exposure_log_read_count": len(soft_rows),
            "recent_combined_log_count": len(hard_rows) + len(soft_rows),
            "dedup_removed_count": cross_day_dedup_removed_count,
            # Backward-compatible alias for the combined cross-day removal count.
            "cross_day_dedup_removed_count": cross_day_dedup_removed_count,
            "dedup_removed_by_sent_log_count": dedup_removed_by_sent_log_count,
            "dedup_removed_by_exposure_log_count": dedup_removed_by_exposure_log_count,
            "candidate_count_after_hard_dedup": candidate_count_after_hard_dedup,
            "candidate_count_after_dedup": candidate_count_after_dedup,
            "fresh_backfill_used_count": fresh_backfill_used_count,
            "exposure_backfill_used": exposure_backfill_used,
            "exposure_backfill_used_count": exposure_backfill_used_count,
            "exposure_backfill_on_scheduled_run": bool(
                exposure_backfill_used and scheduled_trigger
            ),
            "final_selected_count": selected_count,
            "selected_count": selected_count,
        }
        if hold_reason:
            summary["hold_reason"] = hold_reason
        return summary

    if candidate_count_after_dedup < KEYSURI_TOP_NEWS_COUNT:
        hold_reason = "insufficient_fresh_candidates_after_dedup"
        return {
            "verdict": "hold",
            "issues": [
                _issue(
                    hold_reason,
                    f"Need {KEYSURI_TOP_NEWS_COUNT} candidates after cross-day dedup, "
                    f"have {candidate_count_after_dedup} "
                    f"(removed {cross_day_dedup_removed_count} recent-log duplicate(s) "
                    f"[{dedup_removed_by_sent_log_count} customer-sent, "
                    f"{dedup_removed_by_exposure_log_count} owner-exposure] "
                    f"from {candidate_count_before_dedup}; "
                    f"fresh backfill {fresh_backfill_used_count})",
                )
            ],
            "candidate_funnel_summary": _funnel(0, hold_reason=hold_reason),
            "hold_reason": hold_reason,
            "cross_day_dedup_removed_count": cross_day_dedup_removed_count,
            "cross_day_dedup_rejected_items": cross_day_rejected,
        }

    # Bounded cross-day editorial novelty: prefer, among comparably valuable
    # candidates, the one whose source/entity/cluster has NOT dominated recent
    # owner-review briefings. Applied to the ordering only — never a filter.
    deduped_pool, cross_day_novelty_decisions = apply_cross_day_novelty_ordering(
        deduped_pool, list(soft_rows) + list(hard_rows)
    )
    diversity = select_with_diversity_caps(deduped_pool, required_count=KEYSURI_TOP_NEWS_COUNT)
    selected = diversity["selected_items"]
    diversity_summary = diversity["diversity_summary"]
    candidate_funnel_summary = {
        **_funnel(len(selected)),
        "pre_diversity_candidate_count": len(deduped_pool),
        "post_diversity_selected_count": len(selected),
        "diversity_rejected_count": len(diversity["rejected_items"]),
        "relaxed_due_to_candidate_shortage": bool(
            diversity_summary.get("relaxed_due_to_candidate_shortage")
        ),
        "cross_day_novelty_penalized_count": len(cross_day_novelty_decisions),
        "cross_day_novelty_demoted_count": sum(
            1 for decision in cross_day_novelty_decisions if decision.get("demoted")
        ),
    }
    internal_issue_codes: List[str] = []
    if exposure_backfill_used:
        internal_issue_codes.append(KEYSURI_EXPOSURE_DEDUP_BACKFILL_ISSUE_CODE)

    # A card the scorer classified "reject" is not made customer-worthy by the
    # fact that five slots must be filled. On 2026-08-29 cross-day dedup removed
    # all five real picks and the replacement pool supplied the whole briefing:
    # five cards scoring 39-44, every one classified reject, two with structural
    # impact 0. The replacement pool is meant for swapping out a duplicate, not
    # for composing a briefing — the count is recorded either way, and a floor
    # breach is a finding rather than a silent substitution.
    # Backstop. The pool was already floored above; this proves it on the way
    # out. ``_claim_to_news_item`` does not copy the selection fields onto the
    # news item, which is why reading them here reported zero while three
    # below-floor cards were in the briefing — so the claim is consulted.
    claim_scores = {
        str(c.get("claim_id")): c.get("selection_score_before_diversity")
        if c.get("selection_score_before_diversity") is not None
        else c.get("selection_score")
        for c in (source_pack.get("claims") or [])
        if isinstance(c, dict)
    }
    below_floor = [
        item
        for item in selected
        if isinstance(item, dict)
        and isinstance(claim_scores.get(str(item.get("news_id"))), (int, float))
        and float(claim_scores[str(item.get("news_id"))]) < TOP5_QUALITY_FLOOR_BASE_SCORE
    ]
    candidate_funnel_summary["below_quality_floor_selected_count"] = len(below_floor)
    candidate_funnel_summary["below_quality_floor_refused_count"] = len(below_floor_refused)
    candidate_funnel_summary["quality_floor_base_score"] = TOP5_QUALITY_FLOOR_BASE_SCORE
    if below_floor:
        internal_issue_codes.append(GLOBAL_SELECTION_BELOW_QUALITY_FLOOR)
    top_5_news = {
        "news_scope": expected_news_scope_for_program(program_id),
        "section_heading": expected_top5_heading_for_program(program_id),
        "items": selected,
    }
    return {
        "verdict": "pass",
        "top_5_news": top_5_news,
        "issues": [],
        "diversity_summary": diversity_summary,
        "diversity_rejected_items": diversity["rejected_items"],
        "candidate_funnel_summary": candidate_funnel_summary,
        "cross_day_dedup_removed_count": cross_day_dedup_removed_count,
        "cross_day_dedup_rejected_items": cross_day_rejected,
        "cross_day_novelty_decisions": cross_day_novelty_decisions,
        "exposure_backfill_used": exposure_backfill_used,
        "internal_issue_codes": internal_issue_codes,
    }
