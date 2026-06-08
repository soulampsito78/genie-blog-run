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

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"

GLOBAL_DEEP_LAYER_TITLES = (
    "인프라·플랫폼 신호",
    "통제권·규제 압력",
    "워크플로·락인",
)

KOREA_DEEP_LAYER_TITLES = (
    "물리·인프라 병목",
    "규제·주권·조달 압력",
    "워크플로·락인",
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
    out = str(text or "").strip()
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
    next_watch = str(
        extra.get("next_watch") or item.get("next_watch") or item.get("next_check_point") or ""
    ).strip()
    selection_reason = str(
        extra.get("selection_reason")
        or item.get("selection_reason")
        or extra.get("selection_rationale")
        or item.get("selection_rationale")
        or ""
    ).strip()
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
        top_items.append(_map_top_item(item, src=src, source_pack=source_pack, rank=rank))

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
    opening_lead = _sanitize_owner_visible_text(str(display.get("opening_lead") or ""))
    if not opening_lead:
        opening_lead = _fallback_opening_lead(
            _sanitize_owner_visible_text(str(deep.get("body") or "")),
            one_line_body,
        )

    closing_message = _sanitize_owner_visible_text(
        str(closing.get("closing_message") or display.get("closing_message") or "")
    )
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

    fixture: Dict[str, Any] = {
        "program_id": program_id,
        "slot": slot,
        "review_state": "preview_pending",
        "opening_lead": opening_lead,
        "top_5_heading": expected_top5_heading_for_program(program_id),
        "top_5_items": top_items,
        "deep_dive_heading": str(deep.get("section_heading") or "키수리의 딥-다이브"),
        "deep_dive_body": _sanitize_owner_visible_text(str(deep.get("body") or "")),
        "deep_dive_confirmed_facts": deep.get("confirmed_facts") if isinstance(deep.get("confirmed_facts"), list) else [],
        "deep_dive_interpretation": _sanitize_owner_visible_text(
            str(deep.get("interpretation") or deep.get("keysuri_interpretation") or "")
        ),
        "deep_dive_owner_impact": _sanitize_owner_visible_text(
            str(deep.get("owner_impact") or deep.get("korean_operator_impact") or "")
        ),
        "deep_dive_uncertainty": str(deep.get("uncertainty") or deep.get("open_questions") or "").strip(),
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
