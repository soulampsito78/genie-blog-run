"""Build contract-preview fixtures from live generated briefing + prompt_input."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from keysuri_approved_image_assets import (
    default_top_role_for_program,
    resolve_approved_hero_image_path,
)
from keysuri_news_contract import expected_top5_heading_for_program
from keysuri_korea_longform_ux import (
    KOREA_EVENING_MEMO_HEADING,
    build_korea_evening_memo,
    korea_closing_internal_label_leak,
    korea_closing_structure_incomplete,
    korea_evening_memo_too_thin,
    memo_plain_text,
    structure_korea_deep_dive,
)
from keysuri_visible_text import (
    PROGRAM_KOREA,
    build_visible_selection_reason,
    coerce_visible_lines,
    dedupe_repeated_paragraph,
    dedupe_sentences_in_paragraph,
    normalize_visible_text,
    polish_korea_checkpoint_text,
    sanitize_visible_impact_line,
    sanitize_visible_selection_reason,
    strip_watch_arrow_prefixes,
)

PROGRAM_GLOBAL = "keysuri_global_tech"

GLOBAL_DEEP_LAYER_TITLES = (
    "인프라·플랫폼 신호",
    "통제권·규제 압력",
    "워크플로·락인",
)

KOREA_DEEP_LAYER_TITLES = (
    "국내 인프라·공급망",
    "정책·조달·투자",
    "내일 실행 포인트",
)

LIVE_VERIFICATION_STATUS = "live_fetch / not_verified"

_OWNER_ADDRESS_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("귀사의", "주인님의"),
    ("귀사", "주인님"),
    ("다음 브리핑에서 더 유익한 정보로 찾아뵙", "다음 확인 포인트는 원-라인 체크포인트를 기준으로 보시면 됩니다"),
    ("다음 브리핑에서 찾아뵙", "다음 확인 포인트는 원-라인 체크포인트를 기준으로 보시면 됩니다"),
    ("오늘 브리핑이 도움이 되셨기를", "오늘 신호는 여기까지 정리해 두었습니다"),
)


def _sanitize_owner_visible_text(text: str) -> str:
    out = dedupe_sentences_in_paragraph(
        dedupe_repeated_paragraph(normalize_visible_text(text, style="inline"))
    )
    if not out:
        return out
    for old, new in _OWNER_ADDRESS_REPLACEMENTS:
        out = out.replace(old, new)
    return out


def resolve_top_shot_image_path(repo_root: Path, program_id: str) -> Path:
    """Resolve routine approved top asset from registry (no latest-generated fallback)."""
    return resolve_approved_hero_image_path(
        repo_root,
        program_id,
        use_case="contract_preview",
        role=default_top_role_for_program(program_id),
    )


def top_shot_src_for_html(html_path: Path, image_path: Path) -> str:
    rel = os.path.relpath(str(image_path.resolve()), str(html_path.parent.resolve()))
    return rel.replace("\\", "/")


def _source_lookup(source_pack: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for src in source_pack.get("sources") or []:
        if isinstance(src, dict):
            sid = str(src.get("source_id") or "").strip()
            if sid:
                out[sid] = src
    return out


def _first_source_id(item: dict) -> str:
    for sid in item.get("source_ids") or []:
        s = str(sid).strip()
        if s:
            return s
    return ""


def _briefing_display(generated_briefing: dict) -> dict:
    display = generated_briefing.get("briefing_display")
    return display if isinstance(display, dict) else {}


def _item_display(item: dict) -> dict:
    nested = item.get("briefing_item")
    base = nested if isinstance(nested, dict) else {}
    merged = dict(base)
    for key in (
        "korean_title",
        "what_happened",
        "why_now",
        "owner_angle",
        "keysuri_judgment",
        "keysuri_judgment_label",
        "keysuri_judgment_text",
        "next_watch",
        "selection_reason",
        "hype_caution",
        "detail_insufficient",
    ):
        if key in item and item.get(key) not in (None, ""):
            merged[key] = item[key]
    return merged


def _fallback_opening_lead(deep_body: str, one_line: str) -> str:
    prefix = "주인님, "
    body = (deep_body or "").strip()
    if body:
        parts = re.split(r"(?<=[.!?…])\s+", body)
        lead = " ".join(parts[:3]).strip()
        if lead:
            return prefix + lead if not lead.startswith("주인님") else lead
    one = (one_line or "").strip()
    if one:
        return prefix + one if not one.startswith("주인님") else one
    return (
        "주인님, 오늘 글로벌 테크 신호는 개별 헤드라인이 아니라 "
        "AI·플랫폼·업무 루틴 쪽 구조적 움직임으로 읽히는 날입니다."
    )


def _deep_dive_layers(program_id: str, generated_briefing: dict) -> List[Dict[str, str]]:
    deep = generated_briefing.get("deep_dive") if isinstance(generated_briefing.get("deep_dive"), dict) else {}
    implications = deep.get("key_implications") if isinstance(deep.get("key_implications"), list) else []
    titles = KOREA_DEEP_LAYER_TITLES if program_id == PROGRAM_KOREA else GLOBAL_DEEP_LAYER_TITLES
    layers: List[Dict[str, str]] = []
    for idx, title in enumerate(titles, start=1):
        body = ""
        if idx - 1 < len(implications):
            body = _sanitize_owner_visible_text(str(implications[idx - 1] or ""))
        if not body and idx == 1:
            body = _sanitize_owner_visible_text(str(deep.get("body") or ""))[:400]
        layers.append(
            {
                "layer_number": str(idx),
                "layer_title": title,
                "layer_body": body or f"{title} 관련 신호를 점검합니다.",
            }
        )
    return layers


def _map_top_item(
    item: dict,
    *,
    src: dict,
    source_pack: dict,
    rank: int,
    program_id: str,
) -> Dict[str, Any]:
    extra = _item_display(item)
    sid = _first_source_id(item)
    korean_title = str(
        extra.get("korean_title") or item.get("korean_title") or item.get("headline") or ""
    ).strip()
    what_happened = str(
        extra.get("what_happened") or item.get("what_happened") or item.get("summary") or ""
    ).strip()
    why_now = str(extra.get("why_now") or item.get("why_now") or item.get("why_it_matters") or "").strip()
    owner_angle = str(
        extra.get("owner_angle") or item.get("owner_angle") or item.get("business_implication") or ""
    ).strip()
    next_watch_raw = (
        extra.get("next_watch") or item.get("next_watch") or item.get("next_check_point") or ""
    )
    next_watch = strip_watch_arrow_prefixes(
        "; ".join(coerce_visible_lines(next_watch_raw)[:4])
    )
    category_key = str(
        item.get("primary_category") or extra.get("primary_category") or ""
    ).strip()
    meta_stub = {
        "primary_category": category_key,
        "selection_reason_tags": item.get("selection_reason_tags") or extra.get("selection_reason_tags") or [],
        "selection_rationale": item.get("selection_rationale") or extra.get("selection_rationale"),
        "reason_for_selection": item.get("reason_for_selection") or extra.get("reason_for_selection"),
    }
    next_day_impact_line = sanitize_visible_impact_line(
        extra.get("next_day_impact_line")
        or item.get("next_day_impact_line")
        or extra.get("owner_action_line")
        or item.get("owner_action_line")
        or "",
        category=category_key,
    )
    selection_reason = sanitize_visible_selection_reason(
        extra.get("selection_reason")
        or item.get("selection_reason")
        or extra.get("selection_rationale")
        or item.get("selection_rationale")
        or "",
        item=item,
        meta=meta_stub,
        program_id=program_id,
    )
    if program_id == PROGRAM_KOREA:
        selection_reason = build_visible_selection_reason(
            item, meta_stub, program_id=program_id, existing=selection_reason
        )
    hype_caution = str(extra.get("hype_caution") or item.get("hype_caution") or "").strip()

    judgment = extra.get("keysuri_judgment")
    j_label = ""
    j_text = ""
    if isinstance(judgment, dict):
        j_label = str(judgment.get("label") or "").strip()
        j_text = str(judgment.get("explanation") or judgment.get("text") or "").strip()
    elif isinstance(judgment, str):
        j_text = judgment.strip()
    if not j_label:
        j_label = str(extra.get("keysuri_judgment_label") or item.get("keysuri_judgment_label") or "").strip()
    if not j_text:
        j_text = str(extra.get("keysuri_judgment_text") or item.get("keysuri_judgment") or "").strip()

    detail_insufficient = bool(
        extra.get("detail_insufficient") or item.get("detail_insufficient")
    )

    return {
        "rank": rank,
        "korean_title": _sanitize_owner_visible_text(korean_title),
        "headline": _sanitize_owner_visible_text(korean_title),
        "what_happened": _sanitize_owner_visible_text(what_happened),
        "why_now": _sanitize_owner_visible_text(why_now),
        "why_it_matters": _sanitize_owner_visible_text(why_now),
        "owner_angle": _sanitize_owner_visible_text(owner_angle),
        "business_implication": _sanitize_owner_visible_text(owner_angle),
        "keysuri_judgment_label": j_label,
        "keysuri_judgment": _sanitize_owner_visible_text(j_text),
        "next_watch": _sanitize_owner_visible_text(next_watch),
        "next_day_impact_line": _sanitize_owner_visible_text(next_day_impact_line),
        "owner_action_line": _sanitize_owner_visible_text(
            normalize_visible_text(extra.get("owner_action_line") or item.get("owner_action_line") or "", style="inline")
        ),
        "selection_reason": _sanitize_owner_visible_text(selection_reason),
        "hype_caution": _sanitize_owner_visible_text(hype_caution),
        "detail_insufficient": detail_insufficient,
        "source_name": str(src.get("source_name") or item.get("source_name") or "출처").strip(),
        "source_url": str(src.get("source_url") or item.get("source_url") or "").strip(),
        "checked_at": str(src.get("fetched_at") or source_pack.get("generated_at") or "").strip(),
        "verification_status": LIVE_VERIFICATION_STATUS,
    }


def build_contract_preview_fixture_from_generated(
    *,
    program_id: str,
    prompt_input: dict,
    generated_briefing: dict,
    source_pack: dict,
    top_shot_image_path: Optional[Path] = None,
    top_shot_image_src: Optional[str] = None,
) -> Dict[str, Any]:
    if program_id not in (PROGRAM_GLOBAL, PROGRAM_KOREA):
        raise ValueError(f"Unsupported program_id: {program_id!r}")

    slot = "12:30" if program_id == PROGRAM_GLOBAL else "18:30"
    src_map = _source_lookup(source_pack)
    display = _briefing_display(generated_briefing)

    top_block = generated_briefing.get("top_5_news")
    if not isinstance(top_block, dict):
        top_block = prompt_input.get("top_5_news") or {}
    items_in = top_block.get("items") if isinstance(top_block.get("items"), list) else []

    top_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items_in[:5], start=1):
        if not isinstance(item, dict):
            continue
        rank = int(item.get("rank") or idx)
        sid = _first_source_id(item)
        src = src_map.get(sid, {})
        top_items.append(
            _map_top_item(item, src=src, source_pack=source_pack, rank=rank, program_id=program_id)
        )

    deep = generated_briefing.get("deep_dive") if isinstance(generated_briefing.get("deep_dive"), dict) else {}
    one = (
        generated_briefing.get("one_line_checkpoint")
        if isinstance(generated_briefing.get("one_line_checkpoint"), dict)
        else {}
    )
    closing = (
        generated_briefing.get("closing_sources")
        if isinstance(generated_briefing.get("closing_sources"), dict)
        else {}
    )

    one_line_body = _sanitize_owner_visible_text(str(one.get("body") or ""))
    if program_id == PROGRAM_KOREA:
        one_line_body = polish_korea_checkpoint_text(one_line_body)
    opening_lead = _sanitize_owner_visible_text(str(display.get("opening_lead") or ""))
    if not opening_lead:
        opening_lead = _fallback_opening_lead(
            _sanitize_owner_visible_text(str(deep.get("body") or "")),
            one_line_body,
        )

    closing_message = _sanitize_owner_visible_text(
        str(closing.get("closing_message") or display.get("closing_message") or "")
    )
    if program_id == PROGRAM_KOREA and (
        korea_closing_internal_label_leak(closing_message)
        or "오늘의 정리와 퇴근 전 메모" in closing_message
        or (
            "퇴근 전" in closing_message
            and korea_evening_memo_too_thin(closing_message)
        )
    ):
        closing_message = "오늘 신호는 여기까지 정리했습니다. 출처는 아래에 그대로 남깁니다."
    if not closing_message:
        closing_message = "주인님, 오늘 신호는 여기까지 정리했습니다. 다음 확인 포인트는 원-라인 체크포인트를 기준으로 보시면 됩니다."

    source_list: List[Dict[str, str]] = []
    for entry in closing.get("source_list") or []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("source_id") or "").strip()
        src = src_map.get(sid, {})
        source_list.append(
            {
                "source_name": str(entry.get("label") or entry.get("source_name") or src.get("source_name") or sid),
                "source_url": str(entry.get("url") or entry.get("source_url") or src.get("source_url") or ""),
                "fetched_at": str(src.get("fetched_at") or source_pack.get("generated_at") or ""),
                "verification_status": LIVE_VERIFICATION_STATUS,
            }
        )
    if not source_list:
        for src in (source_pack.get("sources") or [])[:5]:
            if isinstance(src, dict):
                source_list.append(
                    {
                        "source_name": str(src.get("source_name") or ""),
                        "source_url": str(src.get("source_url") or ""),
                        "fetched_at": str(src.get("fetched_at") or source_pack.get("generated_at") or ""),
                        "verification_status": LIVE_VERIFICATION_STATUS,
                    }
                )

    korea_deep_sections: List[Dict[str, str]] = []
    evening_memo_body = ""
    korea_evening_memo: Dict[str, Any] = {}
    deep_body = _sanitize_owner_visible_text(str(deep.get("body") or ""))
    if program_id == PROGRAM_KOREA:
        korea_deep_sections = list(deep.get("korea_deep_dive_sections") or [])
        if not korea_deep_sections:
            korea_deep_sections = structure_korea_deep_dive(
                deep_body,
                top_items,
                uncertainty=normalize_visible_text(
                    deep.get("uncertainty") or deep.get("open_questions") or "",
                    style="sentence",
                ),
            )
        deep_body = "\n\n".join(
            f"{section['label']}\n{section['body']}"
            for section in korea_deep_sections
            if section.get("body")
        )
        raw_memo = generated_briefing.get("korea_evening_memo") or closing.get("evening_memo") or display.get("evening_memo")
        if isinstance(raw_memo, dict):
            korea_evening_memo = dict(raw_memo)
        if (
            not korea_evening_memo
            or korea_evening_memo_too_thin(korea_evening_memo)
            or korea_closing_structure_incomplete(korea_evening_memo)
            or korea_closing_internal_label_leak(memo_plain_text(korea_evening_memo))
        ):
            korea_evening_memo = build_korea_evening_memo(
                top_items,
                closing_message=closing_message,
            )
        evening_memo_body = memo_plain_text(korea_evening_memo)

    fixture: Dict[str, Any] = {
        "program_id": program_id,
        "slot": slot,
        "review_state": "preview_pending",
        "opening_lead": opening_lead,
        "top_5_heading": expected_top5_heading_for_program(program_id),
        "top_5_items": top_items,
        "deep_dive_heading": str(deep.get("section_heading") or "키수리의 딥-다이브"),
        "deep_dive_body": deep_body,
        "korea_deep_dive_sections": korea_deep_sections,
        "evening_memo_heading": KOREA_EVENING_MEMO_HEADING if program_id == PROGRAM_KOREA else "",
        "korea_evening_memo": korea_evening_memo if program_id == PROGRAM_KOREA else {},
        "evening_memo_body": evening_memo_body,
        "deep_dive_confirmed_facts": deep.get("confirmed_facts") if isinstance(deep.get("confirmed_facts"), list) else [],
        "deep_dive_interpretation": _sanitize_owner_visible_text(
            str(deep.get("interpretation") or deep.get("keysuri_interpretation") or "")
        ),
        "deep_dive_owner_impact": _sanitize_owner_visible_text(
            str(deep.get("owner_impact") or deep.get("korean_operator_impact") or "")
        ),
        "deep_dive_uncertainty": normalize_visible_text(
            deep.get("uncertainty") or deep.get("open_questions") or "",
            style="sentence",
        ),
        "deep_dive_layers": _deep_dive_layers(program_id, generated_briefing),
        "one_line_checkpoint": one_line_body,
        "closing_message": closing_message,
        "source_list": source_list,
        "operation_metadata": {
            "program_id": program_id,
            "mode": "contract_preview_live_generated",
            "status": "review_required",
            "slot": slot,
        },
    }

    if top_shot_image_path is not None:
        fixture["top_shot_image_path"] = str(top_shot_image_path)
    if top_shot_image_src:
        fixture["top_shot_image_src"] = top_shot_image_src

    return fixture
