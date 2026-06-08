"""Kee-Suri offline generation prompt contract and JSON parse guard (no LLM runtime)."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Set

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

    metadata_keys = (
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
        if program_id == "keysuri_global_tech"
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
        "- Do not use external sources beyond the provided source_pack and allowed_source_ids.",
        "- Do not invent sources, dates, numbers, or legal/policy certainty.",
        "- Do not output unsupported numbers.",
        f"- Keep top_5_news rank/news_id sequence exactly as provided in TOP_5_SELECTED.",
        "- You MAY translate/adapt English RSS headlines into Korean headlines while preserving rank and news_id.",
        "- All reader-facing prose MUST be Korean (한국어). Never expose raw English field labels in prose.",
        f"- Use section headings exactly: {deep_heading!r}, {one_line_heading!r}, {closing_heading!r}",
        "- Do not use cross-scope TOP 5 headings listed in FORBIDDEN OUTPUTS.",
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
    if program_id == "keysuri_global_tech":
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
                "- selection_reason: 2+ Korean sentences — why this item was selected (category, score, signal type).",
                "- what_happened: 3+ Korean sentences grounded in source text only.",
                "- why_now: 3+ Korean sentences — timing, market/infra/policy context.",
                "- owner_angle: 3+ Korean sentences — what 주인님 should watch, use, avoid, or prepare.",
                "- keysuri_judgment.label: one of 기회 / 관찰 / 경계 / 활용 후보 / 사업 신호 / 리스크 신호 / 추가 확인 필요 / 과장 주의.",
                "- next_watch: 2+ distinct follow-up checkpoints in Korean (numbered or separated).",
                "- hype_caution: required string when hype_warning or sponsored_warning — state 과장 주의 / 스폰서·파트너 콘텐츠.",
                "- If source is thin: say '원문 정보가 제한적이므로 추가 확인이 필요합니다.' and set detail_insufficient=true.",
                "- FORBIDDEN generic filler: 'AI 도입이 가속화', '기업들이 AI를 활용', '업무 효율이 높아질 수 있습니다'.",
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


def extract_json_object_from_model_text(raw_text: str) -> dict:
    """Extract exactly one non-empty JSON object from model output text."""
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


def parse_keysuri_generated_response(
    raw_text: str,
    program_id: str,
    prompt_input: dict,
) -> dict:
    """Parse raw model text, validate, and return structured parse result."""
    pid = (program_id or "").strip()
    try:
        parsed = extract_json_object_from_model_text(raw_text)
    except ValueError as exc:
        return {
            "parse_status": "parse_failed",
            "program_id": pid,
            "issues": [_issue("json_extract_failed", str(exc), "raw_text")],
            "generated_briefing": None,
        }

    validation = validate_parsed_keysuri_generated_briefing(pid, parsed, prompt_input)
    if validation["valid"]:
        return {
            "parse_status": "parsed_valid",
            "program_id": pid,
            "issues": [],
            "generated_briefing": parsed,
        }

    return {
        "parse_status": "parsed_invalid",
        "program_id": pid,
        "issues": validation["issues"],
        "generated_briefing": None,
    }
