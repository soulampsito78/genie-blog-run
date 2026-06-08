"""Kee-Suri Global/Korea TOP 5 news contract (foundation — not wired to runtime)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from keysuri_source_gate import CONFIDENCE_LABELS, GateResult

KEYSURI_TOP_NEWS_COUNT = 5
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

NEWS_CATEGORIES = frozenset(
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
    if explicit in NEWS_CATEGORIES:
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
                if cat not in NEWS_CATEGORIES:
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


def _claim_is_qualified(
    claim: Dict[str, Any],
    smap: Dict[str, Dict[str, Any]],
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
    return True, "ok"


def _claim_to_news_item(claim: Dict[str, Any], rank: int) -> Dict[str, Any]:
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
    risk = claim.get("risk_note")
    if _is_non_empty_str(risk):
        item["risk_note"] = str(risk).strip()
    return item


def select_top_5_news(source_pack: dict, gate_result: GateResult) -> dict:
    """
    Select TOP 5 news items from staged source_pack.claims (no live fetch).

    Returns dict with verdict pass|hold|block and optional top_5_news / issues.
    """
    if gate_result.verdict == "block":
        raise ValueError("source gate blocked; cannot select top news")

    if not isinstance(source_pack, dict):
        raise ValueError("source_pack must be a dict")

    program_id = str(source_pack.get("program_id") or "").strip()
    if program_id not in KEYSURI_PROGRAM_IDS:
        raise ValueError(f"Unsupported source_pack.program_id: {program_id!r}")

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
        ok, _reason = _claim_is_qualified(claim, smap)
        if not ok:
            continue
        tier_rank = _best_tier_rank(_source_tiers_for_claim(claim, smap))
        if not _is_non_empty_str(claim.get("business_implication")):
            missing_biz_impl = True
        qualified.append((tier_rank, claim))

    global_sel = source_pack.get("global_top5_selection")
    if program_id == "keysuri_global_tech" and isinstance(global_sel, dict):
        order = global_sel.get("selected_source_ids")
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
        return {
            "verdict": "hold",
            "issues": [
                _issue(
                    "insufficient_top_news_candidates",
                    f"Need {KEYSURI_TOP_NEWS_COUNT} qualified claims, found {len(qualified)}",
                )
            ],
        }

    selected = [_claim_to_news_item(claim, rank=i + 1) for i, (_t, claim) in enumerate(qualified[:KEYSURI_TOP_NEWS_COUNT])]
    top_5_news = {
        "news_scope": expected_news_scope_for_program(program_id),
        "section_heading": expected_top5_heading_for_program(program_id),
        "items": selected,
    }
    return {
        "verdict": "pass",
        "top_5_news": top_5_news,
        "issues": [],
    }
