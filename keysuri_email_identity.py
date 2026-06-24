"""Kee-Suri email subject and preheader identity helpers."""
from __future__ import annotations

import html
import re
from collections.abc import Mapping
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？…])\s+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]{2,}")
_TRAILING_PUNCT_RE = re.compile(r"[\s:：,，.;。!！?？/|·…-]+$")
_OWNER_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+")

_GLOBAL_LABEL = "글로벌 테크 브리핑"
_KOREA_LABEL = "국내 테크 브리핑"
_GLOBAL_FALLBACK = "글로벌 AI·테크 신호 점검"
_KOREA_FALLBACK = "국내 AI·테크 신호 점검"


def _is_korea(program_id: str) -> bool:
    pid = str(program_id or "").strip()
    return pid == PROGRAM_KOREA or pid.startswith("keysuri_korea")


def _program_label(program_id: str) -> str:
    return _KOREA_LABEL if _is_korea(program_id) else _GLOBAL_LABEL


def _fallback_core(program_id: str) -> str:
    return _KOREA_FALLBACK if _is_korea(program_id) else _GLOBAL_FALLBACK


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = _SPACE_RE.sub(" ", text).strip()
    repaired = repair_korean_connector_ellipsis_text(text)
    if repaired.found and not repaired.blocked:
        text = repaired.text
    text = _OWNER_PREFIX_RE.sub("", text).strip()
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    return text


def sanitize_subject_text(text: Any) -> str:
    return _clean_text(text)


def sanitize_preheader_text(text: Any) -> str:
    return _clean_text(text)


def _first_sentence(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    parts = _SENTENCE_SPLIT_RE.split(text)
    return _clean_text(parts[0] if parts else text)


def _date_parts(run_id: str, program_id: str = "") -> Tuple[str, str, str]:
    rid = str(run_id or "").strip()
    if len(rid) >= 8 and rid[:8].isdigit():
        stamp = rid[:8]
    else:
        stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    label = f"{int(stamp[4:6])}월 {int(stamp[6:8])}일"
    time_label = ""
    if len(rid) >= 15 and rid[9:15].isdigit():
        time_label = f"{rid[9:11]}:{rid[11:13]}"
    else:
        time_label = "18:30" if _is_korea(program_id) else "12:30"
    return stamp, label, time_label


def _program_schedule_label(program_id: str) -> str:
    return "18:30" if _is_korea(program_id) else "12:30"


def _manual_trigger_label(trigger_source: str) -> str:
    raw = str(trigger_source or "").strip().lower()
    if any(token in raw for token in ("manual", "force", "deploy", "check", "canary", "post_deploy")):
        return "수동"
    return "자동"


def _items_from_generated(generated_briefing: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    top = generated_briefing.get("top_5_news")
    if isinstance(top, Mapping):
        items = top.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, Mapping)]
    if isinstance(top, list):
        return [item for item in top if isinstance(item, Mapping)]
    return []


def _items_from_fixture(contract_fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = contract_fixture.get("top_5_items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, Mapping)]
    return []


def _candidate_from_item(item: Mapping[str, Any], *, summary: bool = False) -> str:
    if summary:
        keys = (
            "one_line_summary",
            "what_happened",
            "summary",
            "why_now",
            "owner_angle",
            "selection_reason",
            "next_watch",
        )
    else:
        keys = (
            "korean_title",
            "headline",
            "title",
            "selected_title",
            "news_title",
        )
    for key in keys:
        value = item.get(key)
        if isinstance(value, Mapping):
            value = value.get("text") or value.get("title") or value.get("summary")
        text = _first_sentence(value)
        if text:
            return text
    nested = item.get("briefing_item")
    if isinstance(nested, Mapping):
        return _candidate_from_item(nested, summary=summary)
    return ""


def _briefing_display(generated_briefing: Mapping[str, Any]) -> Mapping[str, Any]:
    display = generated_briefing.get("briefing_display")
    return display if isinstance(display, Mapping) else {}


def _select_subject_core(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]],
    prompt_input: Optional[Mapping[str, Any]],
    contract_fixture: Optional[Mapping[str, Any]],
) -> Tuple[str, str]:
    generated = generated_briefing if isinstance(generated_briefing, Mapping) else {}
    prompt = prompt_input if isinstance(prompt_input, Mapping) else {}
    fixture = contract_fixture if isinstance(contract_fixture, Mapping) else {}

    for item in _items_from_generated(generated):
        text = _candidate_from_item(item)
        if text:
            return text, "generated_top_signal_headline"
    for item in _items_from_fixture(fixture):
        text = _candidate_from_item(item)
        if text:
            return text, "fixture_top_signal_headline"
    top_prompt = prompt.get("top_5_news")
    if isinstance(top_prompt, Mapping) and isinstance(top_prompt.get("items"), list):
        for item in top_prompt.get("items") or []:
            if isinstance(item, Mapping):
                text = _candidate_from_item(item)
                if text:
                    return text, "prompt_top_signal_headline"

    for item in _items_from_generated(generated):
        text = _candidate_from_item(item, summary=True)
        if text:
            return text, "generated_top_signal_summary"
    for item in _items_from_fixture(fixture):
        text = _candidate_from_item(item, summary=True)
        if text:
            return text, "fixture_top_signal_summary"

    deep = generated.get("deep_dive")
    if isinstance(deep, Mapping):
        for key in ("title", "headline", "section_title"):
            text = _first_sentence(deep.get(key))
            if text and text != "키수리의 딥-다이브":
                return text, f"generated_deep_dive_{key}"

    display = _briefing_display(generated)
    for source, mapping in (("generated_display", display), ("generated", generated), ("fixture", fixture)):
        for key in ("selected_title", "title", "korean_title", "hero_title"):
            text = _first_sentence(mapping.get(key))
            if text:
                return text, f"{source}_{key}"

    text = _first_sentence(generated.get("summary") or generated.get("opening_lead"))
    if text:
        return text, "generated_summary_first_sentence"
    return _fallback_core(program_id), "fallback"


def extract_keysuri_top_headline(
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
) -> str:
    headline, _source = _select_subject_core(PROGRAM_GLOBAL, generated_briefing, prompt_input, None)
    return _clean_text(headline)


def _too_repetitive(text: str) -> bool:
    tokens = [tok.lower() for tok in _TOKEN_RE.findall(text)]
    if len(tokens) < 4:
        return False
    most_common = Counter(tokens).most_common(1)[0][1]
    return most_common > len(tokens) / 2


def _shorten_core(core: str, *, max_len: int) -> str:
    text = _clean_text(core)
    if len(text) <= max_len:
        return text
    separators = (" — ", " - ", ": ", "：", "·", ",", "，")
    for sep in separators:
        if sep in text:
            head = _clean_text(text.split(sep, 1)[0])
            if 12 <= len(head) <= max_len:
                return head
    cut = text[: max_len + 1]
    for idx in range(len(cut) - 1, 10, -1):
        if cut[idx].isspace():
            return _clean_text(cut[:idx])
    return _clean_text(text[:max_len])


def _subject_components(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    kst_date, kst_label, kst_time = _date_parts(run_id, program_id)
    program_label = _program_label(program_id)
    core, source = _select_subject_core(program_id, generated_briefing, prompt_input, contract_fixture)
    core = _clean_text(core)
    if not core or _too_repetitive(core):
        core = _fallback_core(program_id)
        source = "fallback"
    suffix = f"{kst_label} {program_label}"
    core = _shorten_core(core, max_len=max(18, 74 - len(suffix) - 2))
    if not core:
        core = _fallback_core(program_id)
        source = "fallback"
    editorial = f"{core}: {suffix}"
    if len(editorial) > 80:
        core = _shorten_core(core, max_len=max(18, 75 - len(suffix) - 2))
        editorial = f"{core}: {suffix}"
    trigger_label = _manual_trigger_label(trigger_source)
    schedule_label = _program_schedule_label(program_id)
    return {
        "editorial_subject": editorial,
        "subject_top_headline": core,
        "subject_source": source,
        "subject_kst_date": kst_date,
        "subject_kst_time": kst_time,
        "subject_kst_label": kst_label,
        "subject_program_label": program_label,
        "subject_trigger_label": trigger_label,
        "program_schedule_label": schedule_label,
    }


def build_keysuri_editorial_subject(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
) -> str:
    return _subject_components(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )["editorial_subject"]


def build_keysuri_owner_review_subject(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
) -> str:
    editorial = build_keysuri_editorial_subject(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )
    trigger_label = _manual_trigger_label(trigger_source)
    prefix = "[운영자 검토][수동]" if trigger_label == "수동" else "[운영자 검토]"
    return f"{prefix} {editorial}"


def build_keysuri_customer_subject(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
    meta: Optional[Mapping[str, Any]] = None,
) -> str:
    if isinstance(meta, Mapping):
        for key in ("customer_email_subject", "editorial_subject", "email_subject", "owner_email_subject"):
            text = _clean_text(meta.get(key))
            if text:
                return _OWNER_PREFIX_RE.sub("", text).strip()
    return build_keysuri_editorial_subject(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )


def build_keysuri_preheader(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
    subject: str = "",
    audience: str = "owner",
) -> str:
    parts = _subject_components(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )
    scope = "국내" if _is_korea(program_id) else "글로벌"
    headline = parts["subject_top_headline"] or _fallback_core(program_id)
    if str(audience or "").strip().lower() == "customer":
        preheader = f"{scope} AI·테크 신호 브리핑 · 주요 신호: {headline}"
    else:
        preheader = f"{scope} AI·테크 신호 검수 대기 · 주요 신호: {headline}"
        if parts.get("subject_trigger_label") == "수동":
            preheader = f"수동 검증 run · {preheader}"
    preheader = sanitize_preheader_text(preheader)
    if _clean_text(subject) == preheader:
        preheader = f"{scope} AI·테크 신호 검수 대기 · 상위 신호와 출처를 확인하세요"
    return _shorten_core(preheader, max_len=110)


def build_keysuri_customer_preheader(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
    subject: str = "",
) -> str:
    return build_keysuri_preheader(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
        subject=subject,
        audience="customer",
    )


def build_keysuri_subject_artifact_fields(
    program_id: str,
    generated_briefing: Optional[Mapping[str, Any]] = None,
    prompt_input: Optional[Mapping[str, Any]] = None,
    run_id: str = "",
    trigger_source: str = "",
    contract_fixture: Optional[Mapping[str, Any]] = None,
    *,
    include_customer: bool = False,
) -> Dict[str, str]:
    parts = _subject_components(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )
    editorial = parts["editorial_subject"]
    owner_subject = build_keysuri_owner_review_subject(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
    )
    preheader = build_keysuri_preheader(
        program_id,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture,
        subject=owner_subject,
    )
    fields = {
        "email_subject": editorial,
        "owner_email_subject": owner_subject,
        "email_preheader": preheader,
        "owner_email_preheader": preheader,
        **parts,
    }
    if include_customer:
        fields["customer_email_subject"] = editorial
        fields["customer_email_preheader"] = build_keysuri_customer_preheader(
            program_id,
            generated_briefing=generated_briefing,
            prompt_input=prompt_input,
            run_id=run_id,
            trigger_source=trigger_source,
            contract_fixture=contract_fixture,
            subject=editorial,
        )
    return fields
