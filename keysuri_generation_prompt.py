"""Kee-Suri offline generation prompt contract and JSON parse guard (no LLM runtime)."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Set, Tuple

from keysuri_generated_briefing import (
    GENERATED_STATUS_REQUIRED,
    validate_keysuri_generated_briefing,
)
from keysuri_private_briefing import (
    REQUIRED_OPERATIONAL_STATUS,
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
    keysuri_output_schema_example,
)

IDENTITY_TITLE = "테크 비서 키수리"
IDENTITY_SUBTITLE = "프라이빗 테크 비서"

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"
KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE = "keysuri_deep_dive_key_implications_repaired"

_FORBIDDEN_VISIBLE_SCORE_TERMS: Tuple[str, ...] = (
    "총점",
    "점수",
    "스코어",
    "score",
    "scoring",
)

_GLOBAL_TOP5_METADATA_KEYS: Tuple[str, ...] = (
    "selection_score",
    "selection_score_before_diversity",
    "selection_rationale",
    "primary_category",
    "category_label_ko",
    "reason_for_category",
    "hype_warning",
    "sponsored_warning",
    "is_sponsored",
    "selection_note",
    "penalty_notes",
    "source_name",
    "source_domain",
    "source_count_in_top5",
    "source_concentration_reason",
)

_KOREA_TOP5_METADATA_KEYS: Tuple[str, ...] = (
    "selection_score",
    "selection_score_before_diversity",
    "selection_rationale",
    "primary_category",
    "category_label_ko",
    "category_display_label",
    "reason_for_category",
    "reason_for_selection",
    "owner_action_line",
    "next_day_impact_line",
    "briefing_angle",
    "angle_chip",
    "duplicate_resolution",
    "global_duplicate_detected",
    "korea_angle_required",
    "korea_angle_satisfied",
    "pr_hype_warning",
    "press_release_only",
    "hype_warning",
    "selection_reason_tags",
    "penalty_notes",
    "source_name",
    "source_domain",
    "source_count_in_top5",
    "source_concentration_limited",
    "same_entity_not_same_story",
    "matched_global_title",
)

FORBIDDEN_IDENTITY_KO = ("테크 앵커", "뉴스 앵커", "아나운서")
FORBIDDEN_IDENTITY_EN = ("tech anchor", "news anchor", "announcer")
FORBIDDEN_RETIRED = ("Tomorrow_Geenee", "tomorrow_genie", "18:00")

ACTIVE_SCHEDULER_RULES: List[Dict[str, str]] = [
    {"program": "Today_Geenee", "time_kst": "06:30 KST"},
    {"program": "Kee-Suri Global Tech", "time_kst": "12:30 KST"},
    {"program": "Kee-Suri Korea Tech", "time_kst": "18:30 KST"},
]

RETIRED_SCHEDULER_RULES: List[str] = [
    "Tomorrow_Geenee is permanently retired — do not reference, schedule, or preview.",
    "Do not use tomorrow_genie program identifiers.",
    "Do not use standalone 18:00 KST scheduler slots (Kee-Suri Korea is 18:30 KST).",
]

PARSE_RULES: List[str] = [
    "Return exactly one JSON object.",
    "Do not wrap the JSON in markdown fences.",
    "Do not add explanations before or after the JSON object.",
    "Do not return a JSON array as the top-level response.",
    "Do not return an empty JSON object.",
]


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _collect_allowed_source_ids(prompt_input: dict) -> List[str]:
    allowed: Set[str] = set()
    pack = prompt_input.get("source_pack")
    if isinstance(pack, dict):
        sources = pack.get("sources")
        if isinstance(sources, list):
            for src in sources:
                if isinstance(src, dict):
                    sid = str(src.get("source_id") or "").strip()
                    if sid:
                        allowed.add(sid)
    top = prompt_input.get("top_5_news")
    if isinstance(top, dict) and isinstance(top.get("items"), list):
        for item in top["items"]:
            if not isinstance(item, dict):
                continue
            for sid in item.get("source_ids") or []:
                s = str(sid).strip()
                if s:
                    allowed.add(s)
    return sorted(allowed)


def _source_pack_summary(source_pack: dict) -> Dict[str, Any]:
    sources = source_pack.get("sources") if isinstance(source_pack.get("sources"), list) else []
    claims = source_pack.get("claims") if isinstance(source_pack.get("claims"), list) else []
    summary_sources: List[Dict[str, Any]] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        summary_sources.append(
            {
                "source_id": src.get("source_id"),
                "source_name": src.get("source_name"),
                "source_tier": src.get("source_tier"),
                "source_url": src.get("source_url"),
            }
        )
    return {
        "program_id": source_pack.get("program_id"),
        "generated_at": source_pack.get("generated_at"),
        "notes": source_pack.get("notes"),
        "source_count": len(sources),
        "claim_count": len(claims),
        "sources": summary_sources,
    }


def _is_korea_program(program_id: str) -> bool:
    pid = str(program_id or "").strip()
    return pid == PROGRAM_KOREA or pid.startswith("keysuri_korea")


def _metadata_keys_for_program(program_id: str) -> Tuple[str, ...]:
    if _is_korea_program(program_id):
        return _KOREA_TOP5_METADATA_KEYS
    return _GLOBAL_TOP5_METADATA_KEYS


def _safe_visible_snippet(value: Any, *, max_chars: int = 54) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    text = re.sub(r"총점\s*\d+\s*점을?\s*기록했으며,?\s*", "", text)
    text = re.sub(r"\d+\s*점", "", text)
    for term in _FORBIDDEN_VISIBLE_SCORE_TERMS:
        text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:，。")
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" ,.;:，。") + " 흐름"
    return text


def _top_items_for_implication_repair(obj: Dict[str, Any], prompt_input: dict) -> List[dict]:
    pools: List[Any] = []
    top = obj.get("top_5_news") if isinstance(obj.get("top_5_news"), dict) else {}
    pools.append(top.get("items"))
    prompt_top = (
        prompt_input.get("top_5_news")
        if isinstance(prompt_input.get("top_5_news"), dict)
        else {}
    )
    pools.append(prompt_top.get("items"))
    pools.append(prompt_input.get("selected_items"))

    out: List[dict] = []
    seen: Set[str] = set()
    for pool in pools:
        if not isinstance(pool, list):
            continue
        for item in pool:
            if not isinstance(item, dict):
                continue
            key = str(item.get("news_id") or item.get("claim_id") or item.get("headline") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(item)
    return out


def _build_key_implication_repair_sentences(obj: Dict[str, Any], prompt_input: dict) -> List[str]:
    deep = obj.get("deep_dive") if isinstance(obj.get("deep_dive"), dict) else {}
    top_items = _top_items_for_implication_repair(obj, prompt_input)
    titles: List[str] = []
    for item in top_items:
        title = _safe_visible_snippet(
            item.get("korean_title")
            or item.get("headline")
            or item.get("title")
            or item.get("summary")
        )
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= 3:
            break

    deep_snippets: List[str] = []
    for key in (
        "summary",
        "body",
        "why_it_matters",
        "owner_angle",
        "business_implication",
        "interpretation",
        "keysuri_interpretation",
        "owner_impact",
        "korean_operator_impact",
    ):
        snippet = _safe_visible_snippet(deep.get(key), max_chars=42)
        if snippet and snippet not in deep_snippets:
            deep_snippets.append(snippet)

    sentences: List[str] = []
    if titles:
        sentences.append(
            f"{titles[0]} 흐름은 국내 사업자에게 적용 시점과 대응 우선순위를 다시 확인하게 하는 신호입니다."
        )
    if len(titles) >= 2:
        sentences.append(
            f"{titles[1]} 움직임은 공급망, 플랫폼, 정책 대응을 함께 보아야 하는 관측 대상으로 정리됩니다."
        )
    if deep_snippets:
        sentences.append(
            f"딥다이브 본문에서 확인된 {deep_snippets[0]} 흐름은 주인님께서 내일 실행 리스크와 기회 요인을 함께 점검하실 근거입니다."
        )
    if not sentences and len(titles) >= 3:
        sentences.append(
            f"{titles[2]} 신호는 국내 시장의 다음 대응 순서를 판단하기 위한 참고 축으로 남겨야 합니다."
        )

    cleaned: List[str] = []
    for sentence in sentences:
        safe = _safe_visible_snippet(sentence, max_chars=180)
        if not safe:
            continue
        if safe.endswith(("다", "요")):
            safe += "."
        elif not safe.endswith("."):
            safe += "입니다."
        if any(term.lower() in safe.lower() for term in _FORBIDDEN_VISIBLE_SCORE_TERMS):
            continue
        if safe not in cleaned:
            cleaned.append(safe)
    return cleaned[:3]


def _needs_key_implication_repair(deep: Any) -> bool:
    if not isinstance(deep, dict):
        return False
    implications = deep.get("key_implications")
    if not isinstance(implications, list):
        return True
    return not any(isinstance(item, str) and item.strip() for item in implications)


def _raw_parsed_field_presence_summary(obj: Dict[str, Any]) -> Dict[str, Any]:
    deep = obj.get("deep_dive") if isinstance(obj.get("deep_dive"), dict) else None
    top = obj.get("top_5_news") if isinstance(obj.get("top_5_news"), dict) else None
    items = top.get("items") if isinstance(top, dict) and isinstance(top.get("items"), list) else None
    implications = deep.get("key_implications") if isinstance(deep, dict) else None
    return {
        "expected_top_level_keys_present": [
            key for key in KEYSURI_EXPECTED_TOP_LEVEL_KEYS if obj.get(key) not in (None, "", [], {})
        ],
        "top_5_news_present": isinstance(top, dict),
        "top_5_news_items_count": len(items) if isinstance(items, list) else None,
        "deep_dive_present": isinstance(deep, dict),
        "deep_dive_body_present": bool(
            isinstance(deep, dict) and str(deep.get("body") or "").strip()
        ),
        "deep_dive_summary_present": bool(
            isinstance(deep, dict) and str(deep.get("summary") or "").strip()
        ),
        "deep_dive_why_it_matters_present": bool(
            isinstance(deep, dict) and str(deep.get("why_it_matters") or "").strip()
        ),
        "deep_dive_owner_angle_present": bool(
            isinstance(deep, dict)
            and str(deep.get("owner_angle") or deep.get("owner_impact") or "").strip()
        ),
        "deep_dive_key_implications_type": type(implications).__name__
        if implications is not None
        else None,
        "deep_dive_key_implications_count": len(implications)
        if isinstance(implications, list)
        else None,
    }


def _repair_deep_dive_key_implications_for_parse(
    obj: Dict[str, Any],
    prompt_input: dict,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    summary = _raw_parsed_field_presence_summary(obj)
    deep = obj.get("deep_dive")
    attempted = _needs_key_implication_repair(deep)
    diagnostics: Dict[str, Any] = {
        "raw_parsed_field_presence_summary": summary,
        "deep_dive_key_implications_repair_attempted": attempted,
        "deep_dive_key_implications_repair_success": False,
    }
    if not attempted:
        return obj, diagnostics

    if not isinstance(deep, dict):
        diagnostics["deep_dive_key_implications_repair_reason"] = "deep_dive_not_object"
        return obj, diagnostics

    repaired_items = _build_key_implication_repair_sentences(obj, prompt_input)
    if not repaired_items:
        diagnostics["deep_dive_key_implications_repair_reason"] = "insufficient_source_fields"
        return obj, diagnostics

    out = copy.deepcopy(obj)
    out_deep = dict(out.get("deep_dive") or {})
    out_deep["key_implications"] = repaired_items
    out["deep_dive"] = out_deep
    diagnostics.update(
        {
            "deep_dive_key_implications_repair_success": True,
            "deep_dive_key_implications_repair_reason": "deterministic_from_existing_fields",
            "internal_issue_codes": [KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE],
        }
    )
    return out, diagnostics


def _enrich_top5_with_selection_metadata(prompt_input: dict) -> dict:
    """Attach scored TOP5 selection metadata for Gemini depth enforcement."""
    top_5 = prompt_input.get("top_5_news")
    if not isinstance(top_5, dict):
        return {}
    enriched = copy.deepcopy(top_5)
    pack = prompt_input.get("source_pack")
    if not isinstance(pack, dict):
        return enriched

    claim_by_sid: Dict[str, dict] = {}
    for claim in pack.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for sid in claim.get("source_ids") or []:
            claim_by_sid[str(sid)] = claim

    program_id = str(prompt_input.get("program_id") or "").strip()
    metadata_keys = _metadata_keys_for_program(program_id)
    items_out: List[dict] = []
    for item in enriched.get("items") or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        claim = None
        for sid in item.get("source_ids") or []:
            claim = claim_by_sid.get(str(sid))
            if claim:
                break
        if claim:
            for key in metadata_keys:
                if claim.get(key) is not None:
                    row[key] = claim[key]
        items_out.append(row)
    enriched["items"] = items_out
    return enriched


def _required_output_schema(program_id: str) -> Dict[str, Any]:
    base = keysuri_output_schema_example(program_id)
    base["generated_status"] = GENERATED_STATUS_REQUIRED
    base["news_scope"] = base.get("news_scope") or (
        "global" if program_id == "keysuri_global_tech" else "korea"
    )
    base["section_heading"] = base["top_5_news"]["section_heading"]
    return base


def _identity_rules() -> List[str]:
    return [
        f"Kee-Suri identity: {IDENTITY_TITLE} — {IDENTITY_SUBTITLE}.",
        "Kee-Suri is a private tech secretary for CEO/operators, not a public broadcast anchor.",
        "Forbidden: public broadcast-anchor role titles in Korean or English.",
        "Forbidden English role labels: tech anchor, news anchor, announcer.",
        "Do not use public news desk / announcer framing.",
    ]


def build_keysuri_generation_prompt_contract(prompt_input: dict) -> dict:
    """Build structured generation prompt contract metadata from staged prompt_input."""
    if not isinstance(prompt_input, dict):
        raise ValueError("prompt_input must be a dict")

    program_id = str(prompt_input.get("program_id") or "").strip()
    if not program_id:
        raise ValueError("prompt_input.program_id is required")

    pack = prompt_input.get("source_pack")
    if not isinstance(pack, dict):
        raise ValueError("prompt_input.source_pack must be a dict")

    top_5 = prompt_input.get("top_5_news")
    if not isinstance(top_5, dict):
        raise ValueError("prompt_input.top_5_news is required for generation prompt")

    return {
        "_contract_note": "Offline generation prompt contract — staged sample only, not live production.",
        "program_id": program_id,
        "news_scope": prompt_input.get("news_scope"),
        "section_heading": prompt_input.get("section_heading"),
        "prompt_profile": prompt_input.get("prompt_profile"),
        "output_contract": prompt_input.get("output_contract"),
        "prompt_status": prompt_input.get("prompt_status"),
        "operational_status": REQUIRED_OPERATIONAL_STATUS,
        "required_output_schema": _required_output_schema(program_id),
        "allowed_source_ids": _collect_allowed_source_ids(prompt_input),
        "fixed_section_labels": prompt_input.get("fixed_section_labels"),
        "top_5_news": top_5,
        "source_pack_summary": _source_pack_summary(pack),
        "forbidden_outputs": prompt_input.get("forbidden_outputs"),
        "identity_rules": _identity_rules(),
        "scheduler_rules": {
            "active_programs": ACTIVE_SCHEDULER_RULES,
            "retired_rules": RETIRED_SCHEDULER_RULES,
        },
        "parse_rules": PARSE_RULES,
        "generation_instructions": prompt_input.get("generation_instructions"),
    }


def build_keysuri_generation_prompt(prompt_input: dict) -> str:
    """Build final offline generation prompt text from prompt_input."""
    contract = build_keysuri_generation_prompt_contract(prompt_input)
    program_id = contract["program_id"]
    top_5_for_prompt = (
        _enrich_top5_with_selection_metadata(prompt_input)
        if program_id in (PROGRAM_GLOBAL, PROGRAM_KOREA) or _is_korea_program(program_id)
        else contract.get("top_5_news")
    )
    labels = contract.get("fixed_section_labels") or {}
    deep_heading = labels.get("deep_dive") or SECTION_DEEP_DIVE
    one_line_heading = labels.get("one_line_checkpoint") or SECTION_ONE_LINE
    closing_heading = labels.get("closing_sources") or SECTION_CLOSING

    sections = [
        "=== Kee-Suri Offline Generation Prompt (staged) ===",
        f"Identity: {IDENTITY_TITLE} — {IDENTITY_SUBTITLE}",
        "",
        "ROLE",
        "- You are 테크 비서 키수리, a private tech secretary briefing CEO/operators.",
        "- Premium private secretary tone. Not public news anchor / announcer tone.",
        "",
        "PROGRAM",
        f"- program_id: {program_id}",
        f"- news_scope: {contract.get('news_scope')}",
        f"- section_heading: {contract.get('section_heading')}",
        f"- operational_status must be: {REQUIRED_OPERATIONAL_STATUS}",
        f"- generated_status must be: {GENERATED_STATUS_REQUIRED}",
        "",
        "JSON OUTPUT RULES (mandatory)",
        "- Return exactly one JSON object.",
        "- Do not wrap in markdown fences (no ```json blocks).",
        "- Do not add explanations, preface, or postscript outside the JSON.",
        "- No second corrected JSON. No duplicate JSON object.",
        "- If correcting, output only the final corrected JSON object.",
        "- Do not use external sources beyond the provided source_pack and allowed_source_ids.",
        "- Do not invent sources, dates, numbers, or legal/policy certainty.",
        "- Do not output unsupported numbers.",
        f"- Keep top_5_news rank/news_id sequence exactly as provided in TOP_5_SELECTED.",
        "- You MAY translate/adapt English RSS headlines into Korean headlines while preserving rank and news_id.",
        "- All reader-facing prose MUST be Korean (한국어). Never expose raw English field labels in prose.",
        f"- Use section headings exactly: {deep_heading!r}, {one_line_heading!r}, {closing_heading!r}",
        "- Do not use cross-scope TOP 5 headings listed in FORBIDDEN OUTPUTS.",
        "- Do not use …, ..., or .. where Korean prose needs a comma, particle, or connector.",
        "- Forbidden connector ellipsis: A를 위한… 흐름, B를 구축… 이슈, C가… 변화.",
        "- When shortening long Korean expressions, rewrite as short complete sentences instead of using ellipsis.",
        "- Do not end Korean sentences or summaries with trailing ellipsis such as '...' or '…'.",
        "- Do not use ellipsis in headlines. Write complete headline text.",
        "- Avoid repeated particles or repeated tokens such as '미 미칠' or '을 을'.",
        "- Use complete Korean sentences with proper punctuation (마침표, 쉼표).",
        "- When comparing two signals, use structures like 'A와 B', 'A 흐름과 B 움직임', or '한쪽은 A, 다른 한쪽은 B' with complete grammar.",
        "- Every summary sentence must be grammatically complete Korean.",
        "",
        "OWNER ADDRESS (mandatory)",
        '- Address the owner as "주인님" in opening_lead, deep_dive (at least once), one_line_checkpoint, and closing_message.',
        '- FORBIDDEN address: "귀사". Never use corporate third-person address.',
        "",
        "BRIEFING_DISPLAY (required object at top level)",
        "- briefing_display.opening_lead: 3-5 Korean sentences to 주인님. Explain today's overall signal pattern. Not generic greeting.",
        "- briefing_display.selected_title: Korean inbox title; prefer [키수리 브리핑] prefix.",
        "- briefing_display.title_candidates: array of 2+ Korean title strings including selected_title.",
        "- briefing_display.closing_message: optional override; short private-secretary tone to 주인님.",
        "",
        "TOP5 ITEM BRIEFING (required per item — briefing_item object OR top-level fields on each item)",
        "Each TOP5 item MUST include Korean display fields:",
        "- korean_title: Kee-Suri rewritten Korean headline (not raw English RSS title).",
        "- what_happened: 2-4 Korean sentences — what actually happened, grounded in source text.",
        "- why_now: 2-3 Korean sentences — why hot now, business/AI/platform/market context.",
        "- owner_angle: 2-3 Korean sentences — what 주인님 should watch, use, avoid, or prepare.",
        "- keysuri_judgment: object { label, explanation } — label one of: 기회 / 관찰 / 경계 / 활용 후보 / 사업 신호 / 리스크 신호 / 추가 확인 필요 / 과장 주의.",
        "- next_watch: concrete follow-up watch items in Korean (see program-specific depth rules).",
        "- detail_insufficient: true if RSS/summary too thin; when true, state uncertainty and do NOT invent facts.",
        "",
        "DEEP_DIVE (required — premium private briefing, not recap)",
        "- deep_dive.body: 5-8+ Korean sentences connecting selected news into a pattern.",
        "- deep_dive.confirmed_facts: array of confirmed fact strings from sources.",
        "- deep_dive.key_implications: mandatory non-empty array of 2-3 complete Korean implication sentences; never [], null, a string, or omitted.",
        "- deep_dive.key_implications must not expose internal scoring/evaluation language such as 총점, 점수, 스코어, score, or scoring.",
        "- deep_dive.interpretation OR keysuri_interpretation: Kee-Suri interpretation in Korean.",
        "- deep_dive.owner_impact OR korean_operator_impact: impact for Korean founders/operators.",
        "- deep_dive.uncertainty OR open_questions: what is still uncertain.",
        "- Must address 주인님 naturally at least once in body or owner_impact.",
        "",
        "ONE_LINE_CHECKPOINT",
        "- Sharp, decision-oriented Korean. Address or imply 주인님 context.",
        "",
        "CLOSING",
        "- Short private secretary tone to 주인님. No customer-service language.",
        "",
        "SOURCE THINNESS RULE",
        "- If RSS content is too thin for detailed reporting: set detail_insufficient=true.",
        "- Do not pretend article details are known. Do not invent numbers, dates, or quotes.",
        "",
        "FORBIDDEN READER-FACING PHRASES",
        '- Do not use "귀사".',
        '- Do not use "오늘 브리핑이 도움이 되셨기를 바랍니다" or "도움이 되기를 바랍니다" or similar customer-service closings.',
        '- Do not use "추가 문의사항은 언제든" or public support-desk tone.',
        '- Do not use "다음 브리핑에서 찾아뵙" or public anchor/newsletter tone.',
        "- Do not use generic newsletter closings or public anchor tone.",
        "",
        "FORBIDDEN IDENTITY / RETIRED",
        "- Do not use public broadcast-anchor / news-desk / announcer identity labels.",
        "- Forbidden English roles: tech anchor, news anchor, announcer.",
        f"- Forbidden retired refs: {', '.join(FORBIDDEN_RETIRED)}",
        "",
        "ACTIVE SCHEDULER (reference only — do not add other products)",
    ]
    for row in ACTIVE_SCHEDULER_RULES:
        sections.append(f"- {row['program']}: {row['time_kst']}")
    if _is_korea_program(program_id):
        sections.extend(
            [
                "",
                "KOREA TECH 18:30 LENS (mandatory for keysuri_korea_tech)",
                "- This is NOT a Global 12:30 summary. Write as an evening domestic interpretation desk.",
                "- Do not repeat Global morning framing or copy Global sentences verbatim.",
                "- Every TOP5 item must answer in Korean:",
                "  1) 무슨 일이 있었는가",
                "  2) 왜 오늘 한국에서 중요한가",
                "  3) 내일 주인님이 볼 지점",
                "- Use Korea angle terms naturally when relevant: 국내 적용, 내일 영향, 한국 기업, 정책, 공급망, 투자, 도입 일정.",
                "- Deep-dive subframe: 한국 기업·정책으로 읽으면.",
                "- Deep-dive must use five Korea contract blocks in order: 글로벌 영향, 국내 산업 영향, 기회 요인, 위험 요인, 키수리 판단.",
                "- 글로벌 영향 must synthesize global AI/infra/platform/robotics/semiconductor pressure into Korean companies, startups, supply chains, policy, and capital markets — not recap domestic TOP5 headlines.",
                "- 국내 산업 영향 must synthesize Korea TOP5 into industry impact — no glued headline fragments.",
                "- 위험 요인 must be declarative risk statements; do not use question-style bullets (무엇인가?, 얼마나?, 이어질 것인가?).",
                "- 키수리 판단 body must not repeat the label prefix '키수리 판단:'.",
                "- Every TOP5 field must end with complete Korean sentences; never truncate mid-word (e.g. 조명합, 수립에, 창구입니).",
                "- FORBIDDEN deep-dive block labels: 오늘의 핵심 흐름, 국내 적용, 내일 볼 지점, 아직 불확실한 점.",
                "- one_line_checkpoint: one Korea-market observation synthesizing global+domestic TOP5 — not a single-item recap or '내일 영향' cue.",
                "- Closing frame: 오늘의 정리와 퇴근 전 메모.",
                "- FORBIDDEN Korea briefing labels/phrases: 글로벌 원인, 한국 도착 전 압력, 다음 48시간 관찰 포인트, morning/global desk wording.",
                "- Avoid AI-only newsletter tone; balance industrial, policy, capital, and domestic application signals.",
                "- Avoid PR repost / promotional amplification; do not sound like a stock-news digest.",
                "- If global_duplicate_detected=true and korea_angle_satisfied=true: explain Korea-specific application; do not repeat Global angle.",
                "- If pr_hype_warning or press_release_only: use judgment label 과장 주의 and cautious framing; do not amplify hype.",
                "- Use TOP_5_SELECTED metadata (owner_action_line, next_day_impact_line, angle_chip) to guide depth — never expose internal field names in reader-facing copy.",
                "- If source detail is thin: set detail_insufficient=true and state uncertainty briefly; do not invent facts.",
                "",
                "KOREA TECH TOP5 DEPTH (mandatory per item — use TOP_5_SELECTED metadata)",
                "- selection_reason: 2+ Korean sentences — why selected for domestic interpretation (category, signal type, Korea angle).",
                "- what_happened: 2-4 Korean sentences grounded in source text only.",
                "- why_now: 2-3 Korean sentences — why it matters in Korea today (policy, supply chain, company action).",
                "- owner_angle: 2-3 Korean sentences — what 주인님 should watch, prepare, or decide tomorrow.",
                "- next_watch: concrete 내일 볼 지점 / follow-up checkpoints in Korean (2+ items when possible).",
                "- Reflect owner_action_line and next_day_impact_line from metadata in natural Korean prose.",
                "- angle_chip should read as 국내 적용 when item overlaps Global but has Korea application.",
                "- hype_caution: required when pr_hype_warning — state 과장 주의 / 보도자료 주의 without amplifying PR language.",
                "- FORBIDDEN in all visible fields: 총점, 점수, 스코어, score, scoring — never expose internal evaluation numbers in reader-facing copy.",
            ]
        )
    if program_id == PROGRAM_GLOBAL:
        sections.extend(
            [
                "",
                "GLOBAL TECH BREADTH (mandatory for keysuri_global_tech)",
                "- Global Tech is NOT an AI-only newsletter. Frame AI as one major layer.",
                "- Also cover: chips/infrastructure (physical layer), robots/manufacturing (application layer),",
                "  energy/battery/grid (constraint layer), policy/capital/supply chain (movement layer).",
                "- Explain why each item matters to 주인님; avoid generic AI adoption language.",
                "- Official customer case studies are vendor examples, not breaking product launches.",
                "- Sponsored/partner content must be framed as sponsored/partner content, not neutral news.",
                "- Use judgment label 과장 주의 when hype_warning, sponsored_warning, or customer-case penalties apply.",
                "",
                "GLOBAL TECH TOP5 DEPTH (mandatory per item — use TOP_5_SELECTED metadata)",
                "- selection_reason: 2+ Korean sentences — why this item was selected (category, signal type).",
                "- what_happened: 3+ Korean sentences grounded in source text only.",
                "- why_now: 3+ Korean sentences — timing, market/infra/policy context.",
                "- owner_angle: 3+ Korean sentences — what 주인님 should watch, use, avoid, or prepare.",
                "- keysuri_judgment.label: one of 기회 / 관찰 / 경계 / 활용 후보 / 사업 신호 / 리스크 신호 / 추가 확인 필요 / 과장 주의.",
                "- next_watch: 2+ distinct follow-up checkpoints in Korean (numbered or separated).",
                "- hype_caution: required string when hype_warning or sponsored_warning — state 과장 주의 / 스폰서·파트너 콘텐츠.",
                "- If source is thin: say '향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.' and set detail_insufficient=true.",
                "- FORBIDDEN generic filler: 'AI 도입이 가속화', '기업들이 AI를 활용', '업무 효율이 높아질 수 있습니다'.",
                "- FORBIDDEN in all visible fields: 총점, 점수, 스코어, score, scoring — never expose internal evaluation numbers in reader-facing copy.",
                "- Do NOT invent facts beyond provided source_pack and TOP_5_SELECTED metadata.",
            ]
        )
    sections.extend(
        [
            "",
            "RETIRED SCHEDULER RULES",
            *[f"- {rule}" for rule in RETIRED_SCHEDULER_RULES],
            "",
            "FORBIDDEN OUTPUTS",
            *[f"- {item}" for item in (contract.get("forbidden_outputs") or [])],
            "",
            "ALLOWED SOURCE IDS",
            json.dumps(contract.get("allowed_source_ids"), ensure_ascii=False, indent=2),
            "",
            "SOURCE PACK SUMMARY",
            json.dumps(contract.get("source_pack_summary"), ensure_ascii=False, indent=2),
            "",
            "TOP_5_SELECTED (preserve rank and news_id sequence; includes selection metadata)",
            json.dumps(top_5_for_prompt, ensure_ascii=False, indent=2),
            "",
            "REQUIRED OUTPUT JSON SCHEMA",
            json.dumps(contract.get("required_output_schema"), ensure_ascii=False, indent=2),
            "",
            "FIXED SECTION LABELS",
            json.dumps(contract.get("fixed_section_labels"), ensure_ascii=False, indent=2),
            "",
            "END — respond with JSON object only.",
        ]
    )
    return "\n".join(sections)


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return stripped


def _find_balanced_object_candidates(text: str) -> List[str]:
    candidates: List[str] = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        start = i
        for j in range(i, length):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            i += 1
    return candidates


def _parse_json_object(candidate: str) -> Dict[str, Any]:
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON: {exc}") from exc
    if isinstance(data, list):
        raise ValueError("Top-level JSON array is not allowed")
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON value must be an object")
    if not data:
        raise ValueError("Empty JSON object is not allowed")
    return data


# Discriminating top-level keys a valid Kee-Suri generated briefing payload
# carries. Used only to rank candidates when the model emits more than one JSON
# object; never to merge objects and never to relax downstream schema validation.
KEYSURI_EXPECTED_TOP_LEVEL_KEYS: Tuple[str, ...] = (
    "program_id",
    "operational_status",
    "generated_status",
    "news_scope",
    "section_heading",
    "top_5_news",
    "deep_dive",
    "one_line_checkpoint",
    "closing_sources",
)


def _expected_top_level_key_score(obj: Dict[str, Any]) -> int:
    """Count present, non-empty expected top-level keys (schema-match heuristic)."""
    if not isinstance(obj, dict):
        return 0
    score = 0
    for key in KEYSURI_EXPECTED_TOP_LEVEL_KEYS:
        if key in obj and obj.get(key) not in (None, "", [], {}):
            score += 1
    return score


def extract_json_candidates_from_model_text(raw_text: str) -> List[Dict[str, Any]]:
    """Return every distinct non-empty JSON object found in model output text.

    Order is preserved as encountered (whole-text candidate first, then balanced
    sub-objects). This does not choose between candidates and never merges them.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("raw_text must be a non-empty string")

    text = _strip_markdown_fences(raw_text)
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            top = json.loads(stripped)
            if isinstance(top, list):
                raise ValueError("Top-level JSON array is not allowed")
        except json.JSONDecodeError:
            pass

    candidate_strings: List[str] = [text]
    for fragment in _find_balanced_object_candidates(text):
        if fragment not in candidate_strings:
            candidate_strings.append(fragment)

    seen_canonical: Set[str] = set()
    parsed_objects: List[Dict[str, Any]] = []
    for candidate in candidate_strings:
        try:
            obj = _parse_json_object(candidate)
        except ValueError:
            continue
        canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        parsed_objects.append(obj)
    return parsed_objects


def extract_json_object_from_model_text(raw_text: str) -> dict:
    """Extract exactly one non-empty JSON object from model output text.

    Strict single-object contract preserved for backward compatibility: raises
    when zero, or more than one, distinct object is present.
    """
    parsed_objects = extract_json_candidates_from_model_text(raw_text)
    if not parsed_objects:
        raise ValueError("No JSON object could be extracted from model text")
    if len(parsed_objects) > 1:
        raise ValueError("Multiple JSON objects found in model text")
    return parsed_objects[0]


def validate_parsed_keysuri_generated_briefing(
    program_id: str,
    parsed: dict,
    prompt_input: dict,
) -> dict:
    """Validate extracted JSON against generated briefing contract."""
    issues = validate_keysuri_generated_briefing(program_id, parsed, prompt_input)
    return {"valid": len(issues) == 0, "issues": issues}


def _parse_meta(
    *,
    candidate_count: int,
    selected_index: "int | None",
    recovery_used: bool,
    selected_repair_diagnostics: "Dict[str, Any] | None" = None,
) -> Dict[str, Any]:
    """Safe, PII-free metadata about the JSON extraction decision."""
    meta = {
        "multiple_json_objects_detected": candidate_count > 1,
        "json_candidate_count": candidate_count,
        "selected_json_candidate_index": selected_index,
        "parser_recovery_used": recovery_used,
    }
    if isinstance(selected_repair_diagnostics, dict):
        meta.update(selected_repair_diagnostics)
    return meta


def parse_keysuri_generated_response(
    raw_text: str,
    program_id: str,
    prompt_input: dict,
) -> dict:
    """Parse raw model text, validate, and return structured parse result.

    A single JSON object keeps the original behavior exactly. When the model
    emits multiple JSON objects, candidates are ranked without merging: the first
    object that passes full schema validation is selected; otherwise the object
    with the best top-level-key match is reported through the normal
    ``parsed_invalid`` (validation_blocked) path. Only the chosen object's content
    is ever returned — raw model text is never propagated or stored.
    """
    pid = (program_id or "").strip()
    try:
        candidates = extract_json_candidates_from_model_text(raw_text)
    except ValueError as exc:
        return {
            "parse_status": "parse_failed",
            "program_id": pid,
            "issues": [_issue("json_extract_failed", str(exc), "raw_text")],
            "generated_briefing": None,
            "parse_meta": _parse_meta(candidate_count=0, selected_index=None, recovery_used=False),
        }

    if not candidates:
        return {
            "parse_status": "parse_failed",
            "program_id": pid,
            "issues": [
                _issue(
                    "json_extract_failed",
                    "No JSON object could be extracted from model text",
                    "raw_text",
                )
            ],
            "generated_briefing": None,
            "parse_meta": _parse_meta(candidate_count=0, selected_index=None, recovery_used=False),
        }

    candidate_count = len(candidates)
    multiple = candidate_count > 1

    validations: List[Dict[str, Any]] = []
    repaired_candidates: List[Dict[str, Any]] = []
    repair_diagnostics: List[Dict[str, Any]] = []
    best_index = 0
    best_score = -1
    valid_indices: List[int] = []
    for idx, obj in enumerate(candidates):
        repaired_obj, repair_diag = _repair_deep_dive_key_implications_for_parse(
            obj,
            prompt_input,
        )
        repaired_candidates.append(repaired_obj)
        repair_diagnostics.append(repair_diag)
        validation = validate_parsed_keysuri_generated_briefing(pid, repaired_obj, prompt_input)
        validations.append(validation)
        score = _expected_top_level_key_score(repaired_obj)
        if score > best_score:
            best_score = score
            best_index = idx
        if validation["valid"]:
            valid_indices.append(idx)

    if len(valid_indices) == 1:
        valid_index = valid_indices[0]
        return {
            "parse_status": "parsed_valid",
            "program_id": pid,
            "issues": [],
            "generated_briefing": repaired_candidates[valid_index],
            "parse_meta": _parse_meta(
                candidate_count=candidate_count,
                selected_index=valid_index,
                recovery_used=multiple,
                selected_repair_diagnostics=repair_diagnostics[valid_index],
            ),
        }

    # No fully valid candidate or ambiguous candidates: surface the best schema match
    selected_index = best_index
    issues = list(validations[selected_index]["issues"])
    if multiple:
        if len(valid_indices) > 1:
            issues.insert(
                0,
                _issue(
                    "parse_multiple_json_objects_ambiguous",
                    f"{candidate_count} JSON objects found; {len(valid_indices)} passed schema validation (ambiguous)",
                    "raw_text",
                ),
            )
        else:
            issues.insert(
                0,
                _issue(
                    "parse_multiple_json_objects_unrecoverable",
                    f"{candidate_count} JSON objects found; none passed schema validation",
                    "raw_text",
                ),
            )
            for i, val in enumerate(validations):
                if i != selected_index:
                    c_issues = [iss.get("code", "unknown") for iss in val.get("issues", [])]
                    issues.append(
                        _issue(
                            f"candidate_{i}_summary",
                            f"Candidate {i} issues: {', '.join(c_issues)}",
                            "raw_text"
                        )
                    )
    return {
        "parse_status": "parsed_invalid",
        "program_id": pid,
        "issues": issues,
        "generated_briefing": None,
        "parse_meta": _parse_meta(
            candidate_count=candidate_count,
            selected_index=selected_index,
            recovery_used=False,
            selected_repair_diagnostics=repair_diagnostics[selected_index]
            if repair_diagnostics
            else None,
        ),
    }
