"""Post-parse Kee-Suri briefing content depth enricher (no invented facts)."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from keysuri_contract_preview_quality import _sentence_count

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"

MIN_SELECTION_REASON = 2
MIN_SECTION_SENTENCES = 3
MIN_NEXT_WATCH_ITEMS = 2

_THIN_DETAIL_MARKER = "원문 정보가 제한적이므로 세부 내용은 추가 확인이 필요합니다."
_UNCERTAINTY_MARKER = "다만 원문 정보가 제한적이므로 세부 내용은 추가 확인이 필요합니다."

_CATEGORY_KO: Dict[str, str] = {
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

_WHY_NOW_CONTEXT: Dict[str, str] = {
    "ai_software_platform": "배포·워크플로·API 통제권 변화와 맞닿는 시점입니다.",
    "semiconductor_chip_infra": "연산 자원·공급망·데이터센터 병목과 연결되는 흐름입니다.",
    "semiconductor_equipment_materials": "생산 능력·패키징 제약이 커지는 구간입니다.",
    "robotics_automation_manufacturing": "현장 배치·운영 효율 논의로 이어지기 쉽습니다.",
    "battery_ev_energy_grid": "전력 수요·ESS·그리드 압력과 맞닿습니다.",
    "hardware_device_display": "사용자 접점·검색·쇼핑 경험 변화로 읽힙니다.",
    "cybersecurity_cloud_datacenter": "운영 안정성·인프라 의존성 이슈와 연결됩니다.",
    "policy_regulation_capital_supplychain": "투자·수출통제·조달 리스크와 맞닿습니다.",
}

_OWNER_CONTEXT: Dict[str, str] = {
    "ai_software_platform": "API·파트너·제품 로드맵에 단기 비용·배포 제약이 생기는지 보면 됩니다.",
    "semiconductor_chip_infra": "인프라·연산 조달·파트너 조건이 비용 구조에 미치는지 살보면 됩니다.",
    "robotics_automation_manufacturing": "자동화·운영 흐름에 물리 AI·로봇 적용 여지가 있는지 보면 됩니다.",
    "battery_ev_energy_grid": "전력·에너지 비용 민감도가 있는 사업에 반영할지 점검하면 됩니다.",
    "hardware_device_display": "사용자 접점·검색·쇼핑 경험 변화가 기획에 주는 시사점을 보면 됩니다.",
}

_BROAD_MOVEMENT = (
    "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."
)

_KOREA_CATEGORY_KO: Dict[str, str] = {
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

_KOREA_EVENING_CONTEXT = "오늘 한국 시장·정책·공급망에서 의미가 커진 시점입니다."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _briefing_fields(item: dict) -> dict:
    nested = item.get("briefing_item") if isinstance(item.get("briefing_item"), dict) else {}
    return nested


def _get_field(item: dict, *keys: str) -> str:
    nested = _briefing_fields(item)
    for key in keys:
        val = _text(item.get(key) or nested.get(key))
        if val:
            return val
    return ""


def _set_field(item: dict, key: str, value: str) -> None:
    item[key] = value
    nested = item.get("briefing_item")
    if isinstance(nested, dict):
        nested[key] = value
    elif value:
        item["briefing_item"] = {key: value}


def _split_clauses_to_sentences(text: str) -> str:
    stripped = _text(text)
    if not stripped:
        return ""
    if _sentence_count(stripped) >= MIN_SECTION_SENTENCES:
        return stripped
    clauses = [c.strip().rstrip(".") for c in re.split(r"[,，;；]\s*", stripped) if c.strip()]
    if len(clauses) >= MIN_SECTION_SENTENCES:
        return ". ".join(f"{c}." for c in clauses if c)
    return stripped


def _ensure_sentence_depth(
    text: str,
    *,
    min_sentences: int,
    padding: List[str],
) -> str:
    base = _split_clauses_to_sentences(text)
    parts: List[str] = []
    if base:
        parts.append(base.rstrip("."))
    for pad in padding:
        if _sentence_count(". ".join(parts) + ".") >= min_sentences:
            break
        if pad and pad not in " ".join(parts):
            parts.append(pad.rstrip("."))
    out = ". ".join(p for p in parts if p).strip()
    if out and not out.endswith((".", "!", "?", "…")):
        out += "."
    return out


def _claims_by_source_id(source_pack: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    claims = source_pack.get("claims") if isinstance(source_pack.get("claims"), list) else []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for sid in claim.get("source_ids") or []:
            s = _text(sid)
            if s:
                out[s] = claim
    return out


def _sources_by_id(source_pack: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for src in source_pack.get("sources") or []:
        if isinstance(src, dict):
            sid = _text(src.get("source_id"))
            if sid:
                out[sid] = src
    return out


def _item_metadata(item: dict, *, claims_by_sid: Dict[str, dict], sources_by_sid: Dict[str, dict]) -> dict:
    meta: dict = {}
    for sid in item.get("source_ids") or []:
        s = _text(sid)
        claim = claims_by_sid.get(s)
        src = sources_by_sid.get(s)
        if claim:
            meta.update(claim)
        if src:
            meta.setdefault("source_name", src.get("source_name"))
            meta.setdefault("source_url", src.get("source_url"))
    return meta


def _category_key(meta: dict, item: dict) -> str:
    return _text(
        meta.get("primary_category")
        or item.get("primary_category")
        or item.get("category")
        or "ai_software_platform"
    )


def _category_label(meta: dict, item: dict, *, program_id: str = PROGRAM_GLOBAL) -> str:
    if program_id == PROGRAM_KOREA or str(program_id).startswith("keysuri_korea"):
        return _text(
            meta.get("category_display_label")
            or meta.get("category_label_ko")
            or _KOREA_CATEGORY_KO.get(_category_key(meta, item), "")
            or item.get("category")
            or "국내 테크"
        )
    return _text(
        meta.get("category_label_ko")
        or _CATEGORY_KO.get(_category_key(meta, item), "")
        or item.get("category")
        or "글로벌 테크"
    )


def _is_thin_source(meta: dict, what: str) -> bool:
    if meta.get("detail_insufficient"):
        return True
    summary = _text(meta.get("summary") or meta.get("statement"))
    if len(summary) < 80 and _sentence_count(what) < MIN_SECTION_SENTENCES:
        return True
    return len(what) < 120 and _sentence_count(what) < MIN_SECTION_SENTENCES


def _build_hype_caution(meta: dict) -> str:
    parts: List[str] = []
    if meta.get("is_sponsored") or meta.get("sponsored_warning"):
        parts.append("스폰서·파트너 콘텐츠로 해석·홍보 성격이 있을 수 있어 후속 확인이 필요합니다.")
    if meta.get("is_customer_case_study") or "customer_case" in _text(meta.get("selection_classification")):
        parts.append("공식 고객 사례로, 제품 출시 발표가 아니라 사례 신호로 봐야 합니다.")
    if meta.get("hype_warning") and not parts:
        parts.append("마케팅성 해석 가능성이 있어 과장 없이 관찰하는 편이 안전합니다.")
    if meta.get("hype_warning") or meta.get("sponsored_warning"):
        prefix = "과장 주의 — "
        return prefix + " ".join(parts) if parts else prefix + "후속 공식 확인이 필요합니다."
    return ""


def _build_selection_reason(item: dict, meta: dict) -> str:
    existing = _get_field(item, "selection_reason", "selection_rationale")
    title = _get_field(item, "korean_title", "headline") or _text(meta.get("statement"))
    category = _category_label(meta, item)
    source = _text(meta.get("source_name") or item.get("source_name"))
    padding = [
        existing,
        _text(meta.get("selection_rationale")),
        f"오늘 흐름에서 {category} 축과 맞닿는 공식 보도라 포함했습니다.",
        f"{source} 공개 요약 범위 안에서 의사결정과 연결되는 신호입니다." if source else "",
    ]
    if meta.get("hype_warning") or meta.get("sponsored_warning"):
        padding.append("다만 마케팅·사례·스폰서 성격이 있을 수 있어 해석에 주의가 필요합니다.")
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SELECTION_REASON,
        padding=[p for p in padding if p],
    )


def _build_what_happened(item: dict, meta: dict) -> Tuple[str, bool]:
    existing = _get_field(item, "what_happened", "summary")
    title = _get_field(item, "korean_title", "headline") or _text(meta.get("statement"))
    source = _text(meta.get("source_name") or item.get("source_name"))
    thin = _is_thin_source(meta, existing)
    padding = [
        f"{source} 공개 요약에 따르면 「{title}」 관련 변화가 보고되었습니다." if title and source else "",
        "공개된 요약 범위 안에서만 정리했습니다.",
    ]
    if thin:
        padding.append(_UNCERTAINTY_MARKER)
    out = _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )
    return out, thin


def _build_why_now(item: dict, meta: dict) -> str:
    existing = _get_field(item, "why_now", "why_it_matters")
    cat = _category_key(meta, item)
    padding = [
        existing,
        _WHY_NOW_CONTEXT.get(cat, _BROAD_MOVEMENT),
        _BROAD_MOVEMENT,
    ]
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )


def _build_owner_angle(item: dict, meta: dict) -> str:
    existing = _get_field(item, "owner_angle", "business_implication")
    cat = _category_key(meta, item)
    padding = [
        existing,
        _OWNER_CONTEXT.get(
            cat,
            "운영·파트너·서비스 의사결정에 어떤 경계가 생기는지 보면 됩니다.",
        ),
        "단기 과장과 구조 변화는 구분해 보시면 됩니다.",
    ]
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )


def _next_watch_items(text: str) -> List[str]:
    stripped = _text(text)
    if not stripped:
        return []
    bullets = re.findall(r"(?:^|\n)\s*[-•]\s+(.+)", stripped)
    if bullets:
        return [b.strip() for b in bullets if b.strip()]
    if "→" in stripped:
        parts = [p.strip(" →\t") for p in stripped.split("→") if p.strip()]
        if parts:
            return parts
    numbered = re.findall(r"\d+\.\s*([^;\n]+)", stripped)
    if numbered:
        return [n.strip() for n in numbered if n.strip()]
    semi = [p.strip() for p in re.split(r"[;；]\s*", stripped) if p.strip()]
    if len(semi) >= 2:
        return semi
    if stripped:
        return [stripped]
    return []


def _build_next_watch(item: dict, meta: dict) -> str:
    existing = _get_field(item, "next_watch", "next_check_point")
    items = _next_watch_items(existing)
    source = _text(meta.get("source_name"))
    category = _category_label(meta, item)
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append(f"{source or '해당 출처'}의 후속 공식 발표·원문 업데이트를 확인하세요.")
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append(f"{category} 분야 경쟁사·공급망·규제 후속 보도를 추적하세요.")
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append("한국 시장·운영 환경에 적용 가능한지 점검하세요.")
    deduped: List[str] = []
    for it in items:
        if it and it not in deduped:
            deduped.append(it)
    return "; ".join(deduped[:4])


def _short_title(item: dict) -> str:
    title = _get_field(item, "korean_title", "headline")
    if len(title) > 48:
        return title[:45] + "…"
    return title


def enrich_deep_dive_content(
    deep_dive: dict,
    top5_items: List[dict],
    *,
    claims_by_sid: Optional[Dict[str, dict]] = None,
    sources_by_sid: Optional[Dict[str, dict]] = None,
) -> dict:
    """Preserve Gemini deep-dive; add uncertainty only when missing (UX pass follows)."""
    del claims_by_sid, sources_by_sid
    out = dict(deep_dive)
    body = _text(out.get("body"))
    uncertainty_para = (
        "다만 공개 요약만으로는 세부 수치·일정이 부족한 부분이 있어, 원문 확인이 필요합니다."
    )
    if body and not any(k in body for k in ("불확실", "추가 확인", "원문", "미확정")):
        body = f"{body}\n\n{uncertainty_para}"
    elif not body:
        body = uncertainty_para
    out["body"] = body.strip()
    if not _text(out.get("uncertainty")):
        out["uncertainty"] = uncertainty_para
    if len(top5_items) >= 2:
        out["linked_signal_titles"] = [
            _short_title(i) for i in top5_items[:2] if isinstance(i, dict)
        ]
    return out


def enrich_top5_item_content(
    item: dict,
    *,
    meta: dict,
) -> dict:
    """Enrich one TOP5 item to meet Korean depth requirements."""
    out = copy.deepcopy(item)
    selection_reason = _build_selection_reason(out, meta)
    what_happened, thin = _build_what_happened(out, meta)
    why_now = _build_why_now(out, meta)
    owner_angle = _build_owner_angle(out, meta)
    next_watch = _build_next_watch(out, meta)
    hype_caution = _build_hype_caution(meta)

    _set_field(out, "selection_reason", selection_reason)
    _set_field(out, "what_happened", what_happened)
    _set_field(out, "why_now", why_now)
    _set_field(out, "why_it_matters", why_now)
    _set_field(out, "owner_angle", owner_angle)
    _set_field(out, "business_implication", owner_angle)
    _set_field(out, "next_watch", next_watch)
    if thin:
        out["detail_insufficient"] = True
        nested = out.get("briefing_item")
        if isinstance(nested, dict):
            nested["detail_insufficient"] = True
    if hype_caution:
        _set_field(out, "hype_caution", hype_caution)
    if meta.get("primary_category"):
        out["primary_category"] = meta.get("primary_category")
    if meta.get("category_label_ko"):
        out["category_label_ko"] = meta.get("category_label_ko")
    return out


def _build_korea_hype_caution(meta: dict) -> str:
    parts: List[str] = []
    if meta.get("press_release_only"):
        parts.append("보도자료·홍보 성격이 있을 수 있어 과장 없이 확인이 필요합니다.")
    if meta.get("pr_hype_warning") or meta.get("hype_warning"):
        parts.append("마케팅·홍보 해석 가능성이 있어 과장 주의가 필요합니다.")
    if parts:
        return "과장 주의 — " + " ".join(parts)
    return ""


def _build_korea_selection_reason(item: dict, meta: dict) -> str:
    existing = _get_field(item, "selection_reason", "selection_rationale")
    category = _category_label(meta, item, program_id=PROGRAM_KOREA)
    padding = [
        existing,
        _text(meta.get("selection_rationale") or meta.get("reason_for_selection")),
        f"국내 {category} 관점에서 오늘 한국에서 의미 있는 신호로 선정했습니다.",
    ]
    if meta.get("global_duplicate_detected") and meta.get("korea_angle_satisfied"):
        padding.append("글로벌 이슈와 겹치지만 국내 적용·한국 기업·정책·공급망 관점이 달라 포함했습니다.")
    if meta.get("pr_hype_warning") or meta.get("press_release_only"):
        padding.append("다만 보도자료·홍보 성격이 있을 수 있어 해석에 주의가 필요합니다.")
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SELECTION_REASON,
        padding=[p for p in padding if p],
    )


def _build_korea_why_now(item: dict, meta: dict) -> str:
    existing = _get_field(item, "why_now", "why_it_matters")
    padding = [
        existing,
        _text(meta.get("next_day_impact_line")),
        _KOREA_EVENING_CONTEXT,
        "퇴근 전에 내일 영향을 짚어볼 가치가 있습니다.",
    ]
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )


def _build_korea_owner_angle(item: dict, meta: dict) -> str:
    existing = _get_field(item, "owner_angle", "business_implication")
    padding = [
        existing,
        _text(meta.get("owner_action_line")),
        "내일 파트너·고객·입찰·정책 일정에 반영할지 점검하시면 됩니다.",
    ]
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )


def _build_korea_next_watch(item: dict, meta: dict) -> str:
    existing = _get_field(item, "next_watch", "next_check_point")
    items = _next_watch_items(existing)
    category = _category_label(meta, item, program_id=PROGRAM_KOREA)
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append("내일 볼 지점: 공식 후속 발표·원문 업데이트를 확인하세요.")
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append(f"{category} 관련 국내 정책·공급망·기업 일정을 추적하세요.")
    deduped: List[str] = []
    for it in items:
        if it and it not in deduped:
            deduped.append(it)
    return "; ".join(deduped[:4])


def enrich_korea_top5_item_content(item: dict, *, meta: dict) -> dict:
    out = copy.deepcopy(item)
    selection_reason = _build_korea_selection_reason(out, meta)
    what_happened, thin = _build_what_happened(out, meta)
    why_now = _build_korea_why_now(out, meta)
    owner_angle = _build_korea_owner_angle(out, meta)
    next_watch = _build_korea_next_watch(out, meta)
    hype_caution = _build_korea_hype_caution(meta)

    _set_field(out, "selection_reason", selection_reason)
    _set_field(out, "what_happened", what_happened)
    _set_field(out, "why_now", why_now)
    _set_field(out, "why_it_matters", why_now)
    _set_field(out, "owner_angle", owner_angle)
    _set_field(out, "business_implication", owner_angle)
    _set_field(out, "next_watch", next_watch)
    if thin:
        out["detail_insufficient"] = True
    if hype_caution:
        _set_field(out, "hype_caution", hype_caution)
    out["briefing_angle"] = _text(meta.get("briefing_angle") or meta.get("angle_chip") or "국내 적용")
    out["angle_chip"] = out["briefing_angle"]
    if meta.get("next_day_impact_line"):
        out["next_day_impact_line"] = meta.get("next_day_impact_line")
    if meta.get("owner_action_line"):
        out["owner_action_line"] = meta.get("owner_action_line")
    if meta.get("primary_category"):
        out["primary_category"] = meta.get("primary_category")
    if meta.get("category_label_ko") or meta.get("category_display_label"):
        out["category_label_ko"] = meta.get("category_display_label") or meta.get("category_label_ko")
    return out


def enrich_korea_deep_dive_content(
    deep_dive: dict,
    top5_items: List[dict],
) -> dict:
    out = dict(deep_dive)
    body = _text(out.get("body"))
    opener = "한국 기업·정책으로 읽으면, 오늘 선정된 신호는 국내 적용과 내일 영향이 겹치는 흐름입니다."
    if body and opener not in body:
        body = f"{opener}\n\n{body}"
    elif not body:
        body = opener
    uncertainty_para = (
        "다만 공개 요약만으로는 세부 수치·일정이 부족한 부분이 있어, 원문 확인이 필요합니다."
    )
    if not any(k in body for k in ("불확실", "추가 확인", "원문", "미확정")):
        body = f"{body}\n\n{uncertainty_para}"
    out["body"] = body.strip()
    if not _text(out.get("uncertainty")):
        out["uncertainty"] = uncertainty_para
    if len(top5_items) >= 2:
        out["linked_signal_titles"] = [
            _short_title(i) for i in top5_items[:2] if isinstance(i, dict)
        ]
    return out


def enrich_generated_briefing_content(
    generated_briefing: dict,
    program_id: str,
    prompt_input: dict,
) -> dict:
    """Apply content-depth enrichment for generated briefings (Global or Korea)."""
    if program_id not in (PROGRAM_GLOBAL, PROGRAM_KOREA) and not str(program_id).startswith(
        "keysuri_korea"
    ):
        return generated_briefing
    if not isinstance(generated_briefing, dict):
        return generated_briefing

    out = copy.deepcopy(generated_briefing)
    pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    claims_by_sid = _claims_by_source_id(pack)
    sources_by_sid = _sources_by_id(pack)
    is_korea = program_id == PROGRAM_KOREA or str(program_id).startswith("keysuri_korea")

    top = out.get("top_5_news")
    if not isinstance(top, dict):
        return out
    items = top.get("items") if isinstance(top.get("items"), list) else []
    enriched_items: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            enriched_items.append(item)
            continue
        meta = _item_metadata(item, claims_by_sid=claims_by_sid, sources_by_sid=sources_by_sid)
        if is_korea:
            enriched_items.append(enrich_korea_top5_item_content(item, meta=meta))
        else:
            enriched_items.append(enrich_top5_item_content(item, meta=meta))

    out["top_5_news"] = {**top, "items": enriched_items}

    deep = out.get("deep_dive")
    if isinstance(deep, dict):
        if is_korea:
            out["deep_dive"] = enrich_korea_deep_dive_content(deep, enriched_items)
        else:
            out["deep_dive"] = enrich_deep_dive_content(
                deep,
                enriched_items,
                claims_by_sid=claims_by_sid,
                sources_by_sid=sources_by_sid,
            )

    display = out.get("briefing_display")
    if is_korea and isinstance(display, dict):
        closing = _text(display.get("closing_message"))
        if closing and "퇴근 전" not in closing and "오늘의 정리" not in closing:
            display["closing_message"] = f"{closing} 오늘의 정리와 퇴근 전 메모로 남겨 두었습니다."
            out["briefing_display"] = display

    from keysuri_briefing_body_ux_normalizer import normalize_generated_briefing_visible_prose

    return normalize_generated_briefing_visible_prose(out, program_id, prompt_input)
