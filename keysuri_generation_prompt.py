"""Kee-Suri offline generation prompt contract and JSON parse guard (no LLM runtime)."""
from __future__ import annotations

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
        f"- Use section headings exactly: {deep_heading!r}, {one_line_heading!r}, {closing_heading!r}",
        "- Do not use cross-scope TOP 5 headings listed in FORBIDDEN OUTPUTS.",
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
            "TOP_5_SELECTED (preserve rank and news_id sequence)",
            json.dumps(contract.get("top_5_news"), ensure_ascii=False, indent=2),
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
