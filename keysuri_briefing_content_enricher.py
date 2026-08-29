"""Post-parse Kee-Suri briefing content depth enricher (no invented facts)."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Set, Tuple  # Any used for next_watch list input

from keysuri_briefing_content_quality import (
    GLOBAL_COMMON_FILLER_SENTENCES,
    GLOBAL_EXACT_REPEATED_FILLER_PHRASES,
    GLOBAL_ENERGY_NEXT_WATCH_MARKERS,
    GLOBAL_STARTUP_FOUNDER_MARKERS,
)
from keysuri_contract_preview_quality import _sentence_count
from keysuri_global_signal_scoring import CATEGORY_KEYWORD_GROUPS
from keysuri_global_visible_surface import (
    attach_korean_subject_particle,
    balance_quote_marks,
)
from keysuri_visible_text import (
    KEYSURI_DEEP_DIVE_UNCERTAINTY,
    KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX,
    build_visible_selection_reason,
    coerce_visible_lines,
    contains_dangling_quoted_title_fragment,
    dedupe_repeated_paragraph,
    dedupe_sentences_in_paragraph,
    looks_like_internal_owner_copy,
    normalize_visible_title,
    normalize_visible_text,
    sanitize_visible_impact_line,
    strip_watch_arrow_prefixes,
)

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"

MIN_SELECTION_REASON = 2
MIN_SECTION_SENTENCES = 3
MIN_NEXT_WATCH_ITEMS = 2

_THIN_DETAIL_MARKER = KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX
_UNCERTAINTY_MARKER = KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX

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
    "semiconductor_chip_infra": "인프라·연산 조달·파트너 조건이 비용 구조에 미치는지 살펴보면 됩니다.",
    "robotics_automation_manufacturing": "자동화·운영 흐름에 물리 AI·로봇 적용 여지가 있는지 보면 됩니다.",
    "battery_ev_energy_grid": "전력·에너지 비용 민감도가 있는 사업에 반영할지 점검하면 됩니다.",
    "hardware_device_display": "사용자 접점·검색·쇼핑 경험 변화가 기획에 주는 시사점을 보면 됩니다.",
}

_BROAD_MOVEMENT = (
    "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."
)

# Per-category concrete why_now padding (used when a repeated common filler is stripped).
_WHY_NOW_CONCRETE_BY_CAT: Dict[str, str] = {
    "ai_software_platform": "확인 포인트는 API 공개 일정·엔터프라이즈 도입·가격 조건입니다.",
    "semiconductor_chip_infra": "확인 포인트는 공급 일정·파운드리/벤더 고객·벤치마크입니다.",
    "semiconductor_equipment_materials": "확인 포인트는 장비 납기·소재 수급·양산 일정입니다.",
    "robotics_automation_manufacturing": "확인 포인트는 현장 배치 일정·고객 레퍼런스·운영 지표입니다.",
    "battery_ev_energy_grid": "확인 포인트는 전력 조달·ESS 계약·그리드 연계 일정입니다.",
    "aerospace_satellite_defense_tech": "확인 포인트는 계약 규모·발사/납품 일정·파트너십입니다.",
    "hardware_device_display": "확인 포인트는 출시 일정·유통 채널·사용자 접점 변화입니다.",
    "cybersecurity_cloud_datacenter": "확인 포인트는 캡엑스·리전 확장·엔터프라이즈 계약입니다.",
    "policy_regulation_capital_supplychain": "확인 포인트는 시행 시점·적용 범위·기업 대응입니다.",
}

# Category-specific next_watch fallbacks (Global only). Avoids repeating generic
# "후속 발표를 확인하세요" across every TOP5 item.
_NEXT_WATCH_BY_CAT: Dict[str, Tuple[str, str]] = {
    "ai_software_platform": (
        "API 공개·엔터프라이즈 도입 일정",
        "가격·파트너/고객 발표",
    ),
    "semiconductor_chip_infra": (
        "공급 일정·파운드리/벤더 고객 발표",
        "벤치마크·양산 일정",
    ),
    "semiconductor_equipment_materials": (
        "장비 납기·소재 수급 일정",
        "고객 인증·양산 전환 발표",
    ),
    "robotics_automation_manufacturing": (
        "현장 배치·파일럿 확대 일정",
        "고객 레퍼런스·운영 효율 지표",
    ),
    "battery_ev_energy_grid": (
        "전력 조달·ESS 계약 일정",
        "그리드 연계·규제 후속",
    ),
    "aerospace_satellite_defense_tech": (
        "계약 규모·발사/납품 일정",
        "파트너십·후속 수주",
    ),
    "hardware_device_display": (
        "출시·유통 일정",
        "가격·사용자 접점 변화",
    ),
    "cybersecurity_cloud_datacenter": (
        "캡엑스·리전 확장 발표",
        "전력 조달·엔터프라이즈 계약",
    ),
    "policy_regulation_capital_supplychain": (
        "시행 시점·컴플라이언스 범위",
        "기업 대응·투자/M&A 후속",
    ),
}

_GENERIC_NEXT_WATCH_MARKERS: Tuple[str, ...] = (
    "확인해야 합니다",
    "지켜봐야 합니다",
    "단정하지",
    "확인하는 것이 중요",
    "다음 확인 지점입니다",
    "흐름을 봐야 합니다",
    "시장 반응을 지켜봐야",
    "아직 단정하지",
    "후속 공식 발표·원문 업데이트",
    "경쟁사·공급망·규제 후속 보도",
    "한국 시장·운영 환경에 적용",
)

# Soft filler endings that read as templated when repeated across TOP5 items.
_GLOBAL_SOFT_FILLER_PHRASES: Tuple[str, ...] = (
    "계속 확인해야 합니다.",
    "지켜봐야 합니다.",
    "단정하지 말아야 합니다.",
    "확인하는 것이 중요합니다.",
    "다음 확인 지점입니다.",
    "흐름을 봐야 합니다.",
    "시장 반응을 지켜봐야 합니다.",
    "아직 단정하지 말 것.",
)

_GLOBAL_FILLER_SANITIZER_KEY = "_global_filler_sanitizer"

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

# Strong, mutually distinct vertical markers used only to keep an item's
# generated context attached to that same item's grounded identity.  Generic
# words such as ``AI``, ``전력`` and ``정책`` are deliberately absent: they are
# too broad to prove a contradiction.  This is a deterministic finalizer seam,
# not a delivery validator.
_KOREA_VERTICAL_MARKERS: Dict[str, Tuple[str, ...]] = {
    "korea_semiconductor": (
        "반도체",
        "npu",
        "파운드리",
        "패키징",
        "웨이퍼",
        "소부장",
        "후공정",
        "dx-m1",
    ),
    "korea_battery_energy": (
        "배터리",
        "2차전지",
        "전기차",
        "에너지 기술",
        "에너지 시장",
        "태양광",
        "풍력",
        "ess",
        "충전",
        "그리드",
    ),
    "korea_robotics_manufacturing": (
        "로봇",
        "피지컬 ai",
        "스마트팩토리",
        "amr",
        "휴머노이드",
        "자동화",
    ),
}


def _korea_vertical_domains(text: Any) -> Set[str]:
    """Return strong semantic verticals present in visible text."""
    value = _text(text).lower()
    domains: Set[str] = set()
    for category, markers in _KOREA_VERTICAL_MARKERS.items():
        for marker in markers:
            token = marker.lower()
            if token.isascii() and token.isalnum():
                if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", value):
                    domains.add(category)
                    break
            elif token in value:
                domains.add(category)
                break
    return domains


def _strip_foreign_korea_context(
    text: str,
    *,
    expected_category: str,
    identity_domains: Set[str],
) -> str:
    """Drop only sentences that introduce a vertical absent from this item."""
    value = _text(text)
    if not value or expected_category not in identity_domains:
        return value
    kept: List[str] = []
    for sentence in re.split(r"(?<=[.!?;])\s+", value):
        sentence = sentence.strip()
        if not sentence:
            continue
        foreign = _korea_vertical_domains(sentence) - identity_domains
        if not foreign:
            kept.append(sentence)
    return " ".join(kept).strip()


def _repair_korea_item_context(item: dict, meta: dict) -> dict:
    """Bind context prose to this item's grounded category/source identity.

    Model-authored sentences that remain in the item's real domain are kept
    byte-for-byte.  Only a sentence carrying a strong foreign vertical absent
    from the same source/title/what-happened evidence is removed; the existing
    builders then add the authoritative category-specific fallback if needed.
    """
    expected_category = _text(meta.get("primary_category") or item.get("primary_category"))
    if expected_category not in _KOREA_VERTICAL_MARKERS:
        return item
    identity_text = " ".join(
        _text(value)
        for value in (
            meta.get("statement"),
            meta.get("headline"),
            meta.get("summary"),
            _get_title_field(item, "korean_title", "headline"),
            _get_field(item, "what_happened", "summary"),
        )
        if _text(value)
    )
    identity_domains = _korea_vertical_domains(identity_text)
    if expected_category not in identity_domains:
        return item

    out = copy.deepcopy(item)
    for field in (
        "selection_reason",
        "selection_rationale",
        "why_now",
        "why_it_matters",
        "owner_angle",
        "business_implication",
        "next_watch",
        "next_check_point",
        "owner_action_line",
        "next_day_impact_line",
    ):
        current = _get_field(out, field)
        if not current:
            continue
        repaired = _strip_foreign_korea_context(
            current,
            expected_category=expected_category,
            identity_domains=identity_domains,
        )
        if repaired != current:
            _set_field(out, field, repaired)
    return out


def _text(value: Any) -> str:
    return str(value or "").strip()


def _briefing_fields(item: dict) -> dict:
    nested = item.get("briefing_item") if isinstance(item.get("briefing_item"), dict) else {}
    return nested


def _raw_field(item: dict, *keys: str) -> Any:
    nested = _briefing_fields(item)
    for key in keys:
        raw = item.get(key)
        if raw in (None, ""):
            raw = nested.get(key)
        if raw not in (None, ""):
            return raw
    return None


def _get_field(item: dict, *keys: str) -> str:
    raw = _raw_field(item, *keys)
    if raw is None:
        return ""
    return normalize_visible_text(raw, style="inline")


def _get_title_field(item: dict, *keys: str) -> str:
    """Read a title while preserving balanced source-owned quote marks."""
    raw = _raw_field(item, *keys)
    if raw is None:
        return ""
    return normalize_visible_title(raw)


def _grounded_title(item: dict, meta: dict) -> str:
    """Return a safe item title, falling back only to grounded source text.

    A model title that is already quote-damaged is never completed with
    invented words.  When the canonical source statement/headline is present
    and balanced, use it; otherwise omit the quoted title padding.
    """
    item_title = _get_title_field(item, "korean_title", "headline")
    source_title = normalize_visible_title(
        meta.get("statement")
        or meta.get("korean_title")
        or meta.get("headline")
        or meta.get("title")
    )

    def _safe(title: str) -> bool:
        return bool(title) and not contains_dangling_quoted_title_fragment(
            f"「{title}」"
        )

    if _safe(item_title):
        return item_title
    if _safe(source_title):
        return source_title
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


_NEAR_DUPLICATE_STRIP_RE = re.compile(r"[\s,·，、.!?\"'“”‘’()\[\]「」]+")


def near_duplicate_key(text: str) -> str:
    """Punctuation/whitespace-insensitive key for near-duplicate comparison.

    ``_split_clauses_to_sentences`` rewrites comma-separated clauses, so an
    exact substring check treats "플랫폼 인프라 AI" and "플랫폼, 인프라, AI" as
    different strings and appends the second on top of the first. Comparing on
    this key is what stops that double-append.
    """
    return _NEAR_DUPLICATE_STRIP_RE.sub("", str(text or ""))


def _is_near_duplicate_of(candidate: str, existing_parts: List[str]) -> bool:
    key = near_duplicate_key(candidate)
    if not key:
        return True
    for part in existing_parts:
        part_key = near_duplicate_key(part)
        if not part_key:
            continue
        if key == part_key or key in part_key or part_key in key:
            return True
    return False


def _ensure_sentence_depth(
    text: str,
    *,
    min_sentences: int,
    padding: List[str],
) -> str:
    base = dedupe_sentences_in_paragraph(_split_clauses_to_sentences(text))
    parts: List[str] = []
    if base:
        parts.append(base.rstrip("."))
    for pad in padding:
        if _sentence_count(". ".join(parts) + ".") >= min_sentences:
            break
        pad_clean = _text(pad).rstrip(".")
        # Padding that only differs in punctuation is not additional meaning:
        # a short paragraph is preferable to the same sentence twice.
        if pad_clean and not _is_near_duplicate_of(pad_clean, parts):
            parts.append(pad_clean)
    out = ". ".join(p for p in parts if p).strip()
    if out and not out.endswith((".", "!", "?")):
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


def _natural_korean_subject_phrase(title: str, *, max_len: int = 36) -> str:
    """Cut at a Korean syntactic boundary — never blind fixed-character slicing."""
    title = _text(title).rstrip(".")
    if not title:
        return ""
    if len(title) <= max_len:
        return title
    # Prefer the leading entity/clause before the first comma or middot.
    for sep in ("，", ",", "·"):
        if sep in title:
            # An English title's comma can fall between the halves of a quote
            # pair — "OpenAI introduces ‘Ultrafast,’ a new mode…" split here
            # yields a hook holding an orphaned ‘ , which then rendered as
            # 「OpenAI introduces ‘Ultrafast」 across the 2026-08-14 Global email.
            head = balance_quote_marks(title.split(sep, 1)[0].strip())
            if 2 <= len(head) <= max_len and not re.search(
                r"(?:을|를|이|가|은|는|와|과|의|로|으로|및)\s*$", head
            ):
                return head
    window = title[:max_len]
    # Last safe boundary inside the window (particle/punctuation), then strip
    # trailing connectives so we never keep an incomplete 「…와」 fragment.
    best = ""
    for match in re.finditer(
        r"^[\s\S]{4," + str(max_len) + r"}?(?:을|를|이|가|은|는|와|과|의|에|에서|로|으로|및|·|,|，)",
        window,
    ):
        cand = match.group(0)
        cand = re.sub(
            r"(?:을|를|이|가|은|는|와|과|의|에|에서|로|으로|및)\s*$",
            "",
            cand,
        ).rstrip(" ,·，")
        if 4 <= len(cand) <= max_len and not cand.startswith(("통한", "위한", "대한")):
            best = cand
    if best:
        return best
    return ""


def _item_title_hook(item: dict, meta: dict, *, max_len: int = 36) -> str:
    """Subject phrase used to anchor padding sentences to THIS item.

    Prefer structured entity/topic fields. Never blind-slice mid-phrase into
    a quoted fragment that renders as dangling Korean.
    """
    for key in (
        "subject_phrase",
        "topic_label",
        "entity_label",
        "primary_entity",
        "company_name",
    ):
        structured = _text(item.get(key) or meta.get(key))
        if structured and len(structured) <= max_len:
            return structured.rstrip(".")
    title = _grounded_title(item, meta)
    return _natural_korean_subject_phrase(title, max_len=max_len)


def _looks_startup_founder_item(item: dict, meta: dict) -> bool:
    blob = " ".join(
        _text(v)
        for v in (
            _get_field(item, "korean_title", "headline"),
            meta.get("statement"),
            meta.get("summary"),
            item.get("summary"),
            item.get("what_happened"),
            meta.get("source_name"),
            item.get("source_name"),
        )
    ).lower()
    return any(marker in blob for marker in GLOBAL_STARTUP_FOUNDER_MARKERS)


_STARTUP_NEXT_WATCH_PAIR: Tuple[str, str] = (
    "투자 환경·후속 라운드(팔로우온) 흐름",
    "창업자 실행 리스크·번 레이트·GTM 후속",
)
_STARTUP_CATEGORY_KEY = "policy_regulation_capital_supplychain"
_STARTUP_CATEGORY_LABEL = "스타트업·자본·운영 리스크"


def _repair_startup_founder_category(item: dict, meta: dict) -> Tuple[dict, dict]:
    """Do not let founder/startup advice inherit an energy/EV category."""
    if not _looks_startup_founder_item(item, meta):
        return item, meta
    category = _category_key(meta, item)
    label = _category_label(meta, item)
    if category != "battery_ev_energy_grid" and "배터리" not in label:
        return item, meta
    fixed_item = dict(item)
    fixed_meta = dict(meta)
    fixed_item["primary_category"] = _STARTUP_CATEGORY_KEY
    fixed_item["category_label_ko"] = _STARTUP_CATEGORY_LABEL
    fixed_meta["primary_category"] = _STARTUP_CATEGORY_KEY
    fixed_meta["category_label_ko"] = _STARTUP_CATEGORY_LABEL
    fixed_meta["category_display_label"] = _STARTUP_CATEGORY_LABEL
    fixed_item["category_repair_reason"] = "startup_founder_not_energy"
    return fixed_item, fixed_meta


def _pick(index: int, variants: Tuple[str, ...]) -> str:
    return variants[index % len(variants)]




def _checkpoint_variant_index(item: dict) -> int:
    """Which phrasing this card uses, from its own rank.

    Deterministic so a rerun of the same briefing renders identically, and
    rank-keyed so the five TOP5 cards never draw the same sentence shape.
    """
    try:
        rank = int(item.get("rank") or 0)
    except (TypeError, ValueError):
        rank = 0
    return max(rank - 1, 0)


#: ``_item_specific_checkpoint`` used to live here: five rotations each of a
#: why_now / owner / what / decision / follow sentence, anchored on the item's
#: title and filled from ``_NEXT_WATCH_BY_CAT``. It was the engine that met
#: ``MIN_SECTION_SENTENCES`` when the model wrote less than three sentences, and
#: measured across the real 2026-08-24..08-28 Global corpus it was supplying 32%
#: of why_now and 29% of owner_angle — 60% on the run accepted on 08-28.
#:
#: Rotating the phrasing made the five cards textually distinct while leaving
#: them structurally identical, and the content came from the *category*, so any
#: article in that category would have carried the same sentence. It is deleted
#: rather than left unwired: a depth quota and a bank of category sentences in
#: the same module is how this returns.


def _build_selection_reason(item: dict, meta: dict) -> str:
    """Why this article was picked — the model's reason, plus its source.

    The category sentence that used to pad this field ("「X」를 <category> 축에서
    먼저 볼 신호로 골라 포함했습니다") named the category and the title and said
    nothing else, so it read the same on all five cards and would have been just
    as true of any article in that category. Naming the source is different: it
    is a fact about this item, and it is the reader's warrant for the card.
    """
    existing = _get_field(item, "selection_reason", "selection_rationale")
    # "총점 44점(구조 4, 주인님 12, 사업 4)." is internal owner copy. Carrying it
    # into the visible field meant the whole field was rejected downstream as
    # internal, and a category sentence was written in its place — so the score
    # never reached the reader but neither did any real reason.
    if existing and looks_like_internal_owner_copy(existing):
        existing = ""
    source = _text(meta.get("source_name") or item.get("source_name"))
    variant = _checkpoint_variant_index(item)
    meta_reason = _text(meta.get("selection_rationale"))
    if meta_reason and looks_like_internal_owner_copy(meta_reason):
        meta_reason = ""
    padding = [
        existing,
        meta_reason,
        _pick(
            variant,
            (
                f"{source} 공식 보도 기준으로 의사결정과 연결되는 신호입니다.",
                f"근거는 {source} 공식 보도입니다.",
                f"{source} 보도라 판단 근거로 쓸 수 있습니다.",
                f"출처는 {source} 공식 보도입니다.",
                f"{source} 공식 보도라 신뢰도를 두었습니다.",
            ),
        )
        if source
        else "",
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
    title = _grounded_title(item, meta)
    source = _text(meta.get("source_name") or item.get("source_name"))
    thin = _is_thin_source(meta, existing)
    # Never pad the same disclaimer into every item ("공개된 요약 범위 안에서만
    # 정리했습니다" ×5 in the 2026-07-10 Gmail) — the supplement is anchored on
    # this item's title so each item's padding stays distinct. Any model-written
    # disclaimer repeats are deduped by sanitize_global_repeated_common_filler
    # (keep-first, ≤1 per briefing) and hard-blocked by the final email QA.
    variant = _checkpoint_variant_index(item)
    attribution = (
        _pick(
            variant,
            (
                f"{source} 공개 요약에 따르면 「{title}」 관련 변화가 보고되었습니다.",
                f"{source} 보도가 「{title}」 내용을 전했습니다.",
                f"「{title}」 관련 내용은 {source} 공개 보도에서 확인됩니다.",
                f"{source} 보도를 기준으로 「{title}」 상황이 정리됩니다.",
                f"「{title}」에 대해 {source} 공개 요약을 근거로 삼았습니다.",
            ),
        )
        if title and source
        else ""
    )
    # Attribution is a *factual transformation*: this article's own source name
    # and title, rendered deterministically. It stays.
    #
    # The category checkpoint that used to follow it does not. It says nothing
    # about this article — "세부 수치·일정은 후속 공식 발표에서 보완될 수 있습니다"
    # is true of every story ever written — and it existed only to reach
    # MIN_SECTION_SENTENCES. Measured across the real 08-24..08-28 corpus, that
    # quota was filling 12% of what_happened, 32% of why_now and 29% of
    # owner_angle with category prose, reaching 60% on the 08-28 run that was
    # accepted. A depth requirement met with generic sentences is not depth.
    #
    # When the source really is thin the honest signal already exists and is
    # already rendered: the limitation marker, which the content-quality gate
    # accepts in place of depth (``insufficient_marked``).
    # Thinness is a *state*, not a sentence. Appending the limitation marker to
    # the body put the identical sentence — "향후 공식 발표를 통해 세부 내용이
    # 보완될 가능성이 있습니다." — on every thin card, which is a repeated
    # skeleton across TOP5 by construction. ``detail_insufficient`` already
    # carries the state, and the card already renders it as a badge
    # ("공개 요약 한계 · 공식 발표 대기") which the content gate reads.
    padding = [attribution]
    out = _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )
    return out, thin


def _build_why_now(item: dict, meta: dict) -> str:
    """Pad why_now without stacking the same GLOBAL_COMMON_FILLER across items.

    Prefer category-specific concrete checkpoints over ``_BROAD_MOVEMENT`` /
    shared ``_WHY_NOW_CONTEXT`` sentences. Cross-item dedupe still runs in
    ``sanitize_global_repeated_common_filler`` after all TOP5 items are enriched.
    """
    existing = _get_field(item, "why_now", "why_it_matters")
    # No padding. Anchoring a category checkpoint on the item's own title made
    # the five sentences textually distinct while leaving them structurally
    # identical, and the checkpoints themselves come from _NEXT_WATCH_BY_CAT —
    # they are keyed on the *category*, so any article in that category gets the
    # same advice. That is the "could this paragraph move to another article
    # with only the headline changed?" failure, manufactured by us.
    #
    # A field the model did not write is now empty, and the reader-surface
    # boundary withholds it. Fallback filler must not stand in for missing
    # authored prose.
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[],
    )


def _build_owner_angle(item: dict, meta: dict) -> str:
    existing = _get_field(item, "owner_angle", "business_implication")
    # Same reasoning as why_now. The "owner" and "decision" checkpoints were the
    # most visibly mechanical prose in the product — on 2026-08-29 every card
    # read "<category> 영역의 공개 발표로 ... <category> 후속은 ... <category>이
    # 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다", the category name
    # carrying three sentences in place of an argument.
    return _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[],
    )


def _next_watch_items(text: Any) -> List[str]:
    if isinstance(text, (list, tuple, dict)):
        return coerce_visible_lines(text)
    stripped = _text(text)
    if not stripped:
        return []
    if stripped.startswith("[") and ("'" in stripped or '"' in stripped):
        parsed = coerce_visible_lines(stripped)
        if parsed:
            return parsed
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


def _looks_generic_next_watch(text: str) -> bool:
    stripped = _text(text)
    if not stripped:
        return True
    lower = stripped.lower()
    return any(marker.lower() in lower for marker in _GENERIC_NEXT_WATCH_MARKERS)


# Minimum classifier confidence before a vertical-specific checkpoint pair may
# assert something concrete about an item ("전력 조달·ESS 계약 일정"). Below this,
# only a neutral same-source follow-up is honest.
_CATEGORY_FALLBACK_MIN_CONFIDENCE = 0.5


def _same_item_category_evidence(meta: dict, item: dict, category: str) -> bool:
    """Does THIS item's own text carry evidence for THIS category?

    One misclassification used to fan out into several reader-visible false
    statements at once — wrong why_now, wrong owner_angle, wrong next_watch,
    wrong deep-dive framing — because every fallback map is keyed on the
    category alone and never re-checks the item. A companion-robot story whose
    summary merely mentioned charging inherited 전력 조달·ESS 계약 일정 as a
    checkpoint the article said nothing about.
    """
    keywords = CATEGORY_KEYWORD_GROUPS.get(category)
    if not keywords:
        return False
    blob = " ".join(
        _text(v)
        for v in (
            _get_field(item, "korean_title", "headline"),
            item.get("title"),
            meta.get("statement"),
            meta.get("summary"),
            item.get("summary"),
            item.get("what_happened"),
        )
    ).lower()
    if not blob:
        return False
    return any(kw in blob for kw in keywords)


def _category_fallback_is_grounded(meta: dict, item: dict, category: str) -> bool:
    """Gate vertical-specific fallback copy on same-item evidence.

    A category assigned with real confidence AND corroborated by this item's own
    words may speak in that vertical's language. Anything weaker falls back to a
    neutral, source-grounded follow-up rather than inventing a vertical.
    """
    raw_conf = meta.get("category_confidence")
    if raw_conf is None:
        raw_conf = item.get("category_confidence")
    try:
        confidence = float(raw_conf) if raw_conf is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and confidence < _CATEGORY_FALLBACK_MIN_CONFIDENCE:
        return False
    return _same_item_category_evidence(meta, item, category)


#: Second checkpoint of the neutral pair. Rotated by rank so several items
#: falling back to the same-source follow-up do not all read identically.
_NEUTRAL_SECOND_CHECKPOINTS: Tuple[str, ...] = (
    "원문 업데이트·구체 수치 공개 여부",
    "공식 자료의 수치 보강 시점",
    "발표 범위가 넓어지는지 여부",
    "후속 문서에서 조건이 구체화되는지",
    "추가 공지에서 일정이 확정되는지",
)


def _neutral_next_watch_pair(meta: dict, item: dict) -> Tuple[str, str]:
    """Same-source grounded follow-up that asserts no vertical.

    Several TOP5 items can legitimately land here at once — the category is
    plausible but uncorroborated for each of them — and a fixed pair then puts
    the same checkpoint skeleton on every one of those cards.
    """
    source = _text(meta.get("source_name") or item.get("source_name"))
    second = _pick(_checkpoint_variant_index(item), _NEUTRAL_SECOND_CHECKPOINTS)
    if source:
        return (f"{source} 후속 공식 발표", second)
    return ("해당 출처의 후속 공식 발표", second)


def _concrete_next_watch_pair(meta: dict, item: dict) -> Tuple[str, str]:
    # Startup/founder/investor articles must never carry energy checkpoints
    # (2026-07-10 TOP4: founder-advice article got 전력/ESS/그리드 next_watch).
    if _looks_startup_founder_item(item, meta):
        return _STARTUP_NEXT_WATCH_PAIR
    cat = _category_key(meta, item)
    pair = _NEXT_WATCH_BY_CAT.get(cat)
    if pair and _category_fallback_is_grounded(meta, item, cat):
        return pair
    if pair:
        # Category is plausible but this item does not corroborate it. Say
        # something true about the source instead of something specific and
        # wrong about a vertical.
        return _neutral_next_watch_pair(meta, item)
    # Last-resort category pair. Several items can share a generic category
    # label, so this rotates too — otherwise the same two checkpoints land on
    # every card that reaches this branch.
    category = _category_label(meta, item)
    return _pick(
        _checkpoint_variant_index(item),
        (
            (f"{category} 후속 일정·공식 발표", f"{category} 파트너·고객·규제 반응"),
            (f"{category} 공식 확인 시점", f"{category} 수요·공급 쪽 반응"),
            (f"{category} 다음 공지", f"{category} 경쟁사 대응 여부"),
            (f"{category} 일정 확정 여부", f"{category} 규제·계약 조건 변화"),
            (f"{category} 추가 발표 유무", f"{category} 도입 사례 확대 여부"),
        ),
    )


def _build_next_watch(item: dict, meta: dict) -> str:
    items = _next_watch_items(_raw_field(item, "next_watch", "next_check_point"))
    startup_item = _looks_startup_founder_item(item, meta)
    # Drop generic filler bullets so category-specific checkpoints can replace
    # them; on startup/founder items also drop energy/EV/grid bullets left by a
    # miscategorized model output.
    kept: List[str] = []
    for it in items:
        if not it or _looks_generic_next_watch(it):
            continue
        if startup_item and any(
            marker in it.lower() for marker in GLOBAL_ENERGY_NEXT_WATCH_MARKERS
        ):
            continue
        kept.append(it)
    items = kept
    # No category top-up. `_concrete_next_watch_pair` reads its checkpoints out
    # of `_NEXT_WATCH_BY_CAT`, so every article in a category was told to watch
    # the same two things — "공급 일정·파운드리/벤더 고객 발표" appeared on the
    # 08-24 card about AI-factory *security*, which that article said nothing
    # about. A checkpoint the article does not support is not a checkpoint; one
    # real one is better than two, and none is better than a wrong one.
    deduped: List[str] = []
    for it in items:
        if it and it not in deduped:
            deduped.append(it)
    return "; ".join(deduped[:4])


def _short_title(item: dict) -> str:
    title = _get_title_field(item, "korean_title", "headline")
    if contains_dangling_quoted_title_fragment(f"「{title}」"):
        title = balance_quote_marks(title)
    if contains_dangling_quoted_title_fragment(f"「{title}」"):
        return ""
    if len(title) > 48:
        cut = title[:48].rstrip()
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(" ,·.")
    return title


def _item_prose_blob(item: dict) -> str:
    parts = [
        _get_field(item, "selection_reason", "selection_rationale"),
        _get_field(item, "what_happened"),
        _get_field(item, "why_now", "why_it_matters"),
        _get_field(item, "owner_angle", "business_implication"),
        _get_field(item, "next_watch", "next_check_point"),
        _get_field(item, "hype_caution"),
    ]
    return " ".join(p for p in parts if p)


def _remove_phrase_once(text: str, phrase: str) -> Tuple[str, bool]:
    """Remove the first occurrence of ``phrase`` from ``text``; keep prose non-empty."""
    raw = _text(text)
    if not raw or not phrase or phrase not in raw:
        return raw, False
    cleaned = raw.replace(phrase, " ", 1)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .")
    cleaned = re.sub(r"\.\s*\.", ".", cleaned).strip()
    if cleaned and not cleaned.endswith((".", "!", "?")):
        cleaned += "."
    return cleaned, True


def _replace_or_pad_after_filler_removal(
    text: str,
    *,
    removed: bool,
    cat: str,
    field: str,
) -> str:
    # Removing a sentence that repeated across cards leaves the field shorter,
    # and that is the correct outcome. Substituting a sentence from
    # ``_WHY_NOW_CONCRETE_BY_CAT`` / ``_OWNER_CONTEXT`` swapped one piece of
    # category prose for another: the *repeat* was gone, the interchangeability
    # was not, since every article in the category received the same
    # replacement. A field carries what the model wrote for this article, or
    # less of it — never a substitute written for its category.
    del cat, field
    return dedupe_sentences_in_paragraph(dedupe_repeated_paragraph(_text(text)))


_GLOBAL_PROSE_FIELDS: Tuple[Tuple[str, ...], ...] = (
    ("why_now", "why_it_matters"),
    ("what_happened",),
    ("owner_angle", "business_implication"),
    ("selection_reason", "selection_rationale"),
)


def sanitize_global_repeated_common_filler(items: List[dict]) -> Tuple[List[dict], Dict[str, Any]]:
    """Keep each GLOBAL_COMMON_FILLER / soft filler phrase to at most one TOP5 item.

    First occurrence is kept; later items drop the phrase and, when needed, get a
    category-specific concrete checkpoint so the section does not go empty.
    Does not invent facts — only removes templated padding or swaps in known
    category checkpoint copy.
    """
    diagnostics: Dict[str, Any] = {
        "sanitizer_applied": False,
        "sanitizer_removed_count": 0,
        "sanitizer_rewritten_count": 0,
        "repeated_phrases": [],
        "affected_item_ids": [],
    }
    if not items:
        return items, diagnostics

    working = [copy.deepcopy(i) if isinstance(i, dict) else i for i in items]
    dict_items = [i for i in working if isinstance(i, dict)]
    phrases = (
        list(GLOBAL_COMMON_FILLER_SENTENCES)
        + list(GLOBAL_EXACT_REPEATED_FILLER_PHRASES)
        + list(_GLOBAL_SOFT_FILLER_PHRASES)
    )

    for phrase in phrases:
        hit_indices = [
            idx for idx, item in enumerate(dict_items) if phrase in _item_prose_blob(item)
        ]
        if len(hit_indices) < 2:
            continue
        diagnostics["sanitizer_applied"] = True
        diagnostics["repeated_phrases"].append(
            {"phrase": phrase[:120], "count_before": len(hit_indices)}
        )
        # Keep first; strip from subsequent items.
        for idx in hit_indices[1:]:
            item = dict_items[idx]
            cat = _category_key(item, item)
            item_touched = False
            for keys in _GLOBAL_PROSE_FIELDS:
                primary = keys[0]
                current = _get_field(item, *keys)
                if phrase not in current:
                    continue
                cleaned, removed = _remove_phrase_once(current, phrase)
                if not removed:
                    continue
                cleaned = _replace_or_pad_after_filler_removal(
                    cleaned,
                    removed=True,
                    cat=cat,
                    field=primary,
                )
                _set_field(item, primary, cleaned)
                if primary == "why_now":
                    _set_field(item, "why_it_matters", cleaned)
                if primary == "owner_angle":
                    _set_field(item, "business_implication", cleaned)
                diagnostics["sanitizer_removed_count"] += 1
                diagnostics["sanitizer_rewritten_count"] += 1
                item_touched = True
            if item_touched:
                nid = _text(item.get("news_id") or item.get("rank") or f"item_{idx}")
                if nid and nid not in diagnostics["affected_item_ids"]:
                    diagnostics["affected_item_ids"].append(nid)

    return working, diagnostics


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
    uncertainty_para = KEYSURI_DEEP_DIVE_UNCERTAINTY
    if body and not any(
        k in body for k in ("불확실", "공식 발표", "보완될 가능성", "미확정")
    ):
        body = f"{body}\n\n{uncertainty_para}"
    elif not body:
        body = uncertainty_para
    out["body"] = body.strip()
    unc_raw = out.get("uncertainty") or out.get("open_questions")
    if unc_raw not in (None, ""):
        out["uncertainty"] = normalize_visible_text(unc_raw, style="sentence")
    elif not _text(out.get("uncertainty")):
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
    out, meta = _repair_startup_founder_category(out, meta)
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
    meta_reason = _text(meta.get("selection_rationale") or meta.get("reason_for_selection"))
    padding: List[str] = []
    if existing and not looks_like_internal_owner_copy(existing):
        padding.append(existing)
    if meta_reason and not looks_like_internal_owner_copy(meta_reason):
        padding.append(meta_reason)
    padding.append(f"국내 {category} 관점에서 오늘 한국에서 의미 있는 신호로 선정했습니다.")
    if meta.get("global_duplicate_detected") and meta.get("korea_angle_satisfied"):
        padding.append("글로벌 이슈와 겹치지만 국내 적용·한국 기업·정책·공급망 관점이 달라 포함했습니다.")
    if meta.get("pr_hype_warning") or meta.get("press_release_only"):
        padding.append("다만 보도자료·홍보 성격이 있을 수 있어 해석에 주의가 필요합니다.")
    draft = _ensure_sentence_depth(
        existing if existing and not looks_like_internal_owner_copy(existing) else "",
        min_sentences=MIN_SELECTION_REASON,
        padding=[p for p in padding if p],
    )
    return build_visible_selection_reason(item, meta, program_id=PROGRAM_KOREA, existing=draft)


def _build_korea_why_now(item: dict, meta: dict) -> str:
    existing = _get_field(item, "why_now", "why_it_matters")
    impact = sanitize_visible_impact_line(
        meta.get("next_day_impact_line") or "",
        category=str(meta.get("primary_category") or ""),
    )
    # ``impact`` is this item's own next-day line from the source pack — a
    # factual transformation, kept. The two sentences that followed it were
    # fixed strings: every Korea card carried the same evening framing and the
    # same "퇴근 전에 …" closer, which is the Global category-padding defect in
    # its Korea form. A field the model did not write stays empty and is
    # withheld at the reader-surface boundary.
    padding = [existing, impact]
    why = _ensure_sentence_depth(
        existing,
        min_sentences=MIN_SECTION_SENTENCES,
        padding=[p for p in padding if p],
    )
    return dedupe_sentences_in_paragraph(dedupe_repeated_paragraph(why))


def _build_korea_owner_angle(item: dict, meta: dict) -> str:
    existing = _get_field(item, "owner_angle", "business_implication")
    # owner_action_line is this item's own; the sentence after it was the same
    # on every card.
    padding = [existing, _text(meta.get("owner_action_line"))]
    return dedupe_sentences_in_paragraph(
        dedupe_repeated_paragraph(
            _ensure_sentence_depth(
                existing,
                min_sentences=MIN_SECTION_SENTENCES,
                padding=[p for p in padding if p],
            )
        )
    )


def _build_korea_next_watch(item: dict, meta: dict) -> str:
    items = _next_watch_items(_raw_field(item, "next_watch", "next_check_point"))
    category = _category_label(meta, item, program_id=PROGRAM_KOREA)
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append("내일 볼 지점: 공식 후속 발표·원문 업데이트를 확인하세요.")
    if len(items) < MIN_NEXT_WATCH_ITEMS:
        items.append(f"{category} 관련 국내 정책·공급망·기업 일정을 추적하세요.")
    deduped: List[str] = []
    for it in items:
        if it and it not in deduped:
            deduped.append(it)
    return strip_watch_arrow_prefixes("; ".join(deduped[:4]))


def enrich_korea_top5_item_content(item: dict, *, meta: dict) -> dict:
    out = _repair_korea_item_context(copy.deepcopy(item), meta)
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
    category_key = str(meta.get("primary_category") or out.get("primary_category") or "")
    if meta.get("next_day_impact_line"):
        out["next_day_impact_line"] = sanitize_visible_impact_line(
            meta.get("next_day_impact_line"),
            category=category_key,
        )
    if meta.get("owner_action_line"):
        out["owner_action_line"] = dedupe_sentences_in_paragraph(
            normalize_visible_text(meta.get("owner_action_line"), style="inline")
        )
    if meta.get("primary_category"):
        out["primary_category"] = meta.get("primary_category")
    if meta.get("category_label_ko") or meta.get("category_display_label"):
        out["category_label_ko"] = meta.get("category_display_label") or meta.get("category_label_ko")
    return out


def enrich_korea_deep_dive_content(
    deep_dive: dict,
    top5_items: List[dict],
) -> dict:
    from keysuri_korea_longform_ux import structure_korea_deep_dive

    out = dict(deep_dive)
    unc_raw = out.get("uncertainty") or out.get("open_questions")
    uncertainty = normalize_visible_text(unc_raw, style="sentence") if unc_raw not in (None, "") else ""
    sections = structure_korea_deep_dive(_text(out.get("body")), top5_items, uncertainty=uncertainty)
    out["korea_deep_dive_sections"] = sections
    out["body"] = "\n\n".join(
        f"{section['label']}\n{section['body']}" for section in sections if section.get("body")
    ).strip()
    if uncertainty:
        out["uncertainty"] = uncertainty
    elif not _text(out.get("uncertainty")):
        out["uncertainty"] = "세부 수치·양산 일정은 공개 요약만으로는 아직 부족합니다."
    if len(top5_items) >= 2:
        out["linked_signal_titles"] = [
            _short_title(i) for i in top5_items[:2] if isinstance(i, dict)
        ]
    return out


#: Where the reader-surface boundary records what it had to withhold.
_READER_SURFACE_DIAGNOSTIC_KEY = "_reader_surface_diagnostics"


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

    if not is_korea:
        enriched_items, filler_diag = sanitize_global_repeated_common_filler(enriched_items)
        out[_GLOBAL_FILLER_SANITIZER_KEY] = filler_diag

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

    if is_korea:
        from keysuri_korea_longform_ux import build_korea_evening_memo

        memo = build_korea_evening_memo(enriched_items)
        out["korea_evening_memo"] = memo
        display = out.get("briefing_display")
        if isinstance(display, dict):
            display = dict(display)
            display["evening_memo"] = memo
            out["briefing_display"] = display
        closing = out.get("closing_sources")
        if isinstance(closing, dict):
            closing = dict(closing)
            closing["evening_memo"] = memo
            out["closing_sources"] = closing

    from keysuri_briefing_body_ux_normalizer import normalize_generated_briefing_visible_prose

    out = normalize_generated_briefing_visible_prose(out, program_id, prompt_input)

    # The canonical reader-surface boundary, applied last so nothing in this
    # function can write past it. Every path that produces a briefing — first
    # parse, corrective generation, scaffold completion, repair, reissue,
    # degraded candidate, manual run — calls this function, so this is the one
    # place a customer-visible article field can be produced.
    from keysuri_reader_surface import enforce_reader_surface

    out, reader_diag = enforce_reader_surface(
        out, program_id=program_id, prompt_input=prompt_input
    )
    if isinstance(out, dict) and reader_diag.get("reader_surface_enforced"):
        out[_READER_SURFACE_DIAGNOSTIC_KEY] = reader_diag
    return out
