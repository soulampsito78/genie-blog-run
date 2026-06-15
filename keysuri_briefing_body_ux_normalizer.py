"""Normalize Kee-Suri visible briefing prose — readable private secretary tone."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from keysuri_contract_preview_quality import _sentence_count
from keysuri_korea_longform_ux import (
    build_korea_evening_memo,
    korea_evening_memo_too_thin,
    remove_internal_glue,
    structure_korea_deep_dive,
)
from keysuri_visible_text import (
    KEYSURI_DEEP_DIVE_UNCERTAINTY,
    KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX,
    build_visible_selection_reason,
    coerce_visible_lines,
    dedupe_adjacent_sentences,
    dedupe_repeated_paragraph,
    dedupe_sentences_in_paragraph,
    normalize_visible_text,
    polish_korea_checkpoint_text,
    sanitize_visible_impact_line,
    strip_watch_arrow_prefixes,
)

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"

MAX_OWNER_SALUTATION = 2
DEEP_DIVE_CHAR_MIN = 450
DEEP_DIVE_CHAR_MAX = 900

_INTERNAL_MARKER_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"TOP\s*신호\s*\d+", ""),
    (r"TOP\s*신호\s*\d+\s*[·•]\s*\d+", ""),
    (r"signal\s*marker", ""),
    (r"\bgate\b", ""),
    (r"검증(?:용| 목적)", ""),
    (r"scoring", ""),
    (r"category\s*layer", ""),
    (r"글로벌\s*테크\s*TOP5\s*선정\s*기준", "오늘 흐름에서 의미 있는 공식 보도"),
    (r"서로\s*다른\s*레이어를\s*동시에\s*보여\s*줍니다", "서로 다른 축을 동시에 보여 줍니다"),
    (r"점검하는\s*데\s*유용합니다", "함께 보면 흐름이 선명해집니다"),
    (r"이\s*신호는\s*.+?\s*레이어에서", "이 흐름은"),
    (r"레이어에서\s*경쟁사", "분야에서 경쟁사"),
    (r"선정\s*신호\s*가운데", "오늘 눈에 띄는 흐름 가운데"),
)

_MECHANICAL_PHRASES: Tuple[Tuple[str, str], ...] = (
    ("확인 가능한 범위는 제목·요약·공식 출처 수준에 머무릅니다.", "공개된 요약 범위 안에서만 정리했습니다."),
    ("주인님께서는 이 신호가 운영·파트너·콘텐츠·서비스 의사결정에 어떤 경계를 주는지 점검하시면 됩니다.", "운영·파트너·서비스 의사결정에 어떤 경계가 생기는지 보면 됩니다."),
    ("단기 과장과 구조 변화를 구분해 보시고, 불확실한 부분은 추가 확인 후 반영하시면 됩니다.", "단기 과장과 구조 변화는 구분해 보시면 됩니다."),
)

_COMPANY_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("nvidia", "엔비디아"),
    ("notion", "Notion"),
    ("anthropic", "Anthropic"),
    ("openai", "OpenAI"),
    ("endava", "Endava"),
    ("google", "Google"),
    ("lg", "LG"),
    ("doosan", "두산"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def remove_internal_validation_markers(text: str) -> str:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", _text(text)) if b.strip()]
    if not blocks:
        blocks = [_text(text)]
    cleaned_blocks: List[str] = []
    for block in blocks:
        out = block
        for pattern, repl in _INTERNAL_MARKER_PATTERNS:
            out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r"\s+([,.!?])", r"\1", out)
        if out.strip():
            cleaned_blocks.append(out.strip())
    return "\n\n".join(cleaned_blocks)


def limit_owner_salutation_repetition(text: str, *, max_count: int = MAX_OWNER_SALUTATION) -> str:
    if not text:
        return ""
    parts = re.split(r"(\n\s*\n)", text)
    kept: List[str] = []
    count = 0
    for part in parts:
        if not part.strip():
            kept.append(part)
            continue
        sentences = re.split(r"(?<=[.!?…])\s+", part.strip())
        new_sentences: List[str] = []
        for sent in sentences:
            if not sent.strip():
                continue
            if "주인님" in sent:
                if count >= max_count:
                    sent = sent.replace("주인님,", "").replace("주인님께서는", "").replace("주인님", "")
                    sent = re.sub(r"^\s*,\s*", "", sent)
                    sent = re.sub(r"\s+", " ", sent).strip()
                else:
                    count += 1
            if sent.strip():
                new_sentences.append(sent.strip())
        if new_sentences:
            kept.append(" ".join(new_sentences))
    return "\n\n".join(p.strip() for p in kept if p.strip())


def split_long_korean_paragraphs(text: str, *, max_sentences: int = 3) -> str:
    raw = _text(text)
    if not raw:
        return ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if not blocks:
        blocks = [raw]
    out_blocks: List[str] = []
    for block in blocks:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", block) if s.strip()]
        if len(sentences) <= max_sentences:
            out_blocks.append(" ".join(sentences))
            continue
        for i in range(0, len(sentences), max_sentences):
            chunk = " ".join(sentences[i : i + max_sentences])
            if chunk:
                out_blocks.append(chunk)
    return "\n\n".join(out_blocks)


def _de_mechanize(text: str) -> str:
    out = text
    for old, new in _MECHANICAL_PHRASES:
        out = out.replace(old, new)
    return out


def _title_tokens(item: dict) -> List[str]:
    title = _text(item.get("korean_title") or item.get("headline"))
    tokens: List[str] = []
    if title:
        tokens.append(title)
        short = title[:36] + ("…" if len(title) > 36 else "")
        if short != title:
            tokens.append(short)
    blob = title.lower()
    for needle, label in _COMPANY_ALIASES:
        if needle in blob and label not in tokens:
            tokens.append(label)
    for ko_label in ("엔비디아", "노션", "두산", "구글"):
        if ko_label in title and ko_label not in tokens:
            tokens.append(ko_label)
    return tokens


def _mentions_token(text: str, token: str) -> bool:
    if not token or not text:
        return False
    if token in text:
        return True
    return token.lower() in text.lower()


def count_signal_references(text: str, top5_items: Sequence[dict]) -> int:
    matched = 0
    seen: set[str] = set()
    for item in top5_items:
        if not isinstance(item, dict):
            continue
        for token in _title_tokens(item):
            key = token.lower()
            if key in seen:
                continue
            if _mentions_token(text, token):
                seen.add(key)
                matched += 1
                break
    return matched


def rewrite_signal_marker_sentence_to_natural_prose(
    text: str,
    top5_items: Sequence[dict],
) -> str:
    """Replace gate-shaped glue with company/title based phrasing."""
    if count_signal_references(text, top5_items) >= 2:
        return remove_internal_validation_markers(text)

    items = [i for i in top5_items if isinstance(i, dict)]
    if len(items) < 2:
        return remove_internal_validation_markers(text)

    a, b = items[0], items[1]
    ta = _text(a.get("korean_title") or a.get("headline"))
    tb = _text(b.get("korean_title") or b.get("headline"))
    companies_a = [label for needle, label in _COMPANY_ALIASES if needle in ta.lower()]
    companies_b = [label for needle, label in _COMPANY_ALIASES if needle in tb.lower()]
    lead_a = companies_a[0] if companies_a else (ta[:24] + "…" if len(ta) > 24 else ta)
    lead_b = companies_b[0] if companies_b else (tb[:24] + "…" if len(tb) > 24 else tb)

    natural = (
        f"오늘 눈에 띄는 점은 {lead_a} 흐름과 {lead_b} 이슈가 동시에 보인다는 것입니다. "
        f"한쪽은 산업·인프라 쪽이고, 다른 쪽은 소프트웨어·운영 쪽입니다."
    )
    cleaned = remove_internal_validation_markers(text)
    if count_signal_references(cleaned, top5_items) >= 2:
        return cleaned
    return f"{natural}\n\n{cleaned}".strip()


def normalize_visible_item_fields(item: dict, *, thin_source: bool = False) -> dict:
    out = copy.deepcopy(item)

    def _norm_field(key: str) -> None:
        raw = out.get(key)
        if raw in (None, ""):
            raw = _briefing_nested(out).get(key)
        if raw in (None, ""):
            return
        if key == "next_watch":
            lines = coerce_visible_lines(raw)
            val = strip_watch_arrow_prefixes("; ".join(lines[:4])) if lines else ""
        else:
            val = normalize_visible_text(raw, style="inline")
        if not val:
            return
        val = remove_internal_validation_markers(val)
        val = _de_mechanize(val)
        val = dedupe_sentences_in_paragraph(dedupe_repeated_paragraph(val))
        val = limit_owner_salutation_repetition(val, max_count=1)
        if key == "owner_angle":
            val = re.sub(r"^주인님께서는\s*", "", val)
            val = re.sub(r"^주인님,\s*", "", val)
            val = re.sub(r"\s*주인님께서는\s*", " ", val)
        if key in ("what_happened", "why_now", "owner_angle", "selection_reason"):
            val = split_long_korean_paragraphs(val, max_sentences=3)
        if key == "what_happened" and not thin_source:
            val = val.replace(_THIN_MARKER, "").replace(_THIN_MARKER_ALT, "")
            val = re.sub(r"\s+", " ", val).strip()
        _set_briefing_field(out, key, val)

    thin = thin_source or bool(out.get("detail_insufficient"))
    for field in ("selection_reason", "what_happened", "why_now", "owner_angle", "next_watch"):
        _norm_field(field)
    hype = _text(out.get("hype_caution") or _briefing_nested(out).get("hype_caution"))
    if hype:
        hype = remove_internal_validation_markers(hype)
        if not hype.startswith("과장 주의"):
            hype = f"과장 주의 — {hype}"
        _set_briefing_field(out, "hype_caution", hype)
    return out


_THIN_MARKER = KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX
_THIN_MARKER_ALT = KEYSURI_THIN_SOURCE_WHAT_HAPPENED_SUFFIX


def _briefing_nested(item: dict) -> dict:
    nested = item.get("briefing_item")
    return nested if isinstance(nested, dict) else {}


def _set_briefing_field(item: dict, key: str, value: str) -> None:
    item[key] = value
    nested = item.get("briefing_item")
    if isinstance(nested, dict):
        nested[key] = value
    elif value:
        item["briefing_item"] = {key: value}


def _dedupe_paragraphs(text: str) -> str:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", _text(text)) if b.strip()]
    unique: List[str] = []
    for block in blocks:
        if block not in unique:
            unique.append(block)
    return "\n\n".join(unique)


def _trim_deep_dive_length(text: str) -> str:
    if len(text) <= DEEP_DIVE_CHAR_MAX:
        return text
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    trimmed: List[str] = []
    total = 0
    for block in blocks:
        if total + len(block) > DEEP_DIVE_CHAR_MAX and trimmed:
            break
        trimmed.append(block)
        total += len(block) + 2
    return "\n\n".join(trimmed)


def normalize_visible_deep_dive_text(
    body: str,
    top5_items: Sequence[dict],
    *,
    gemini_body: str = "",
) -> Tuple[str, List[str]]:
    """Return normalized deep-dive body and linked signal titles for gate metadata."""
    base = _text(body) or _text(gemini_body)
    base = rewrite_signal_marker_sentence_to_natural_prose(base, top5_items)
    base = remove_internal_validation_markers(base)
    base = _de_mechanize(base)
    base = limit_owner_salutation_repetition(base, max_count=MAX_OWNER_SALUTATION)
    base = split_long_korean_paragraphs(base, max_sentences=3)

    if count_signal_references(base, top5_items) < 2:
        natural = rewrite_signal_marker_sentence_to_natural_prose("", top5_items)
        if natural and natural not in base:
            base = f"{natural}\n\n{base}"

    if "주인님" not in base:
        base = "주인님, 오늘 글로벌 테크 신호를 연결해 보겠습니다.\n\n" + base

    if not any(
        k in base for k in ("공식 발표", "보완될 가능성", "미확정", "불확실")
    ):
        base = f"{base}\n\n{KEYSURI_DEEP_DIVE_UNCERTAINTY}"

    base = _dedupe_paragraphs(_trim_deep_dive_length(base.strip()))
    linked = []
    for item in top5_items:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("korean_title") or item.get("headline"))
        if title and _mentions_token(base, title):
            linked.append(title)
        else:
            for _needle, label in _COMPANY_ALIASES:
                if _mentions_token(base, label) and _mentions_token(title, label):
                    linked.append(title)
                    break
    if len(linked) < 2 and len(top5_items) >= 2:
        for item in top5_items[:2]:
            if isinstance(item, dict):
                t = _text(item.get("korean_title") or item.get("headline"))
                if t and t not in linked:
                    linked.append(t)
    return base, linked[:5]


def _is_korea_program(program_id: str) -> bool:
    pid = str(program_id or "").strip()
    return pid == PROGRAM_KOREA or pid.startswith("keysuri_korea")


def normalize_korea_visible_deep_dive_text(
    body: str,
    top5_items: Sequence[dict],
    *,
    gemini_body: str = "",
    uncertainty: str = "",
) -> Tuple[str, List[str], List[Dict[str, str]]]:
    base = remove_internal_glue(_text(body) or _text(gemini_body))
    base = remove_internal_validation_markers(base)
    base = _de_mechanize(base)
    base = limit_owner_salutation_repetition(base, max_count=0)
    sections = structure_korea_deep_dive(base, top5_items, uncertainty=uncertainty)
    linked: List[str] = []
    for item in top5_items:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("korean_title") or item.get("headline"))
        if title and _mentions_token(" ".join(s.get("body", "") for s in sections), title):
            linked.append(title)
    if len(linked) < 2 and len(top5_items) >= 2:
        for item in top5_items[:2]:
            if isinstance(item, dict):
                t = _text(item.get("korean_title") or item.get("headline"))
                if t and t not in linked:
                    linked.append(t)
    # Legacy body field kept minimal for metadata/debug paths.
    compact_body = "\n\n".join(
        f"{section['label']}\n{section['body']}" for section in sections if section.get("body")
    )
    return compact_body, linked[:5], sections


def normalize_generated_briefing_visible_prose(
    generated_briefing: dict,
    program_id: str,
    prompt_input: dict,
) -> dict:
    if not isinstance(generated_briefing, dict):
        return generated_briefing
    if not _is_korea_program(program_id) and program_id != PROGRAM_GLOBAL:
        return generated_briefing

    out = copy.deepcopy(generated_briefing)
    is_korea = _is_korea_program(program_id)
    top = out.get("top_5_news")
    items = top.get("items") if isinstance(top, dict) and isinstance(top.get("items"), list) else []
    normalized_items: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue
        thin = bool(item.get("detail_insufficient"))
        normalized = normalize_visible_item_fields(item, thin_source=thin)
        if is_korea:
            meta_stub = {
                "primary_category": normalized.get("primary_category"),
                "selection_reason_tags": normalized.get("selection_reason_tags"),
                "selection_rationale": normalized.get("selection_rationale"),
                "reason_for_selection": normalized.get("reason_for_selection"),
            }
            reason = build_visible_selection_reason(
                normalized,
                meta_stub,
                program_id=PROGRAM_KOREA,
                existing=_text(normalized.get("selection_reason")),
            )
            if reason:
                normalized["selection_reason"] = reason
            impact = sanitize_visible_impact_line(
                normalized.get("next_day_impact_line") or "",
                category=str(normalized.get("primary_category") or ""),
            )
            if impact:
                normalized["next_day_impact_line"] = impact
        normalized_items.append(normalized)

    if isinstance(top, dict):
        out["top_5_news"] = {**top, "items": normalized_items}

    deep = out.get("deep_dive")
    if isinstance(deep, dict):
        deep_out = dict(deep)
        gemini_body = _text(deep.get("body"))
        if is_korea:
            unc_raw = deep_out.get("uncertainty") or deep_out.get("open_questions") or ""
            normalized_body, linked_titles, korea_sections = normalize_korea_visible_deep_dive_text(
                gemini_body,
                normalized_items,
                gemini_body=gemini_body,
                uncertainty=_text(unc_raw),
            )
            deep_out["korea_deep_dive_sections"] = korea_sections
        else:
            normalized_body, linked_titles = normalize_visible_deep_dive_text(
                gemini_body,
                normalized_items,
                gemini_body=gemini_body,
            )
        deep_out["body"] = normalized_body
        unc_raw = deep_out.get("uncertainty") or deep_out.get("open_questions")
        if unc_raw not in (None, ""):
            deep_out["uncertainty"] = normalize_visible_text(unc_raw, style="sentence")
        deep_out["linked_signal_titles"] = linked_titles
        deep_out["linked_signal_ids"] = [
            _text(i.get("news_id"))
            for i in normalized_items[: len(linked_titles)]
            if isinstance(i, dict) and _text(i.get("news_id"))
        ]
        out["deep_dive"] = deep_out

    one_line = out.get("one_line_checkpoint")
    if is_korea and isinstance(one_line, dict):
        body = _text(one_line.get("body"))
        if body:
            one_line_out = dict(one_line)
            one_line_out["body"] = polish_korea_checkpoint_text(body)
            out["one_line_checkpoint"] = one_line_out

    if is_korea:
        memo = build_korea_evening_memo(normalized_items)
        out["korea_evening_memo"] = memo
        closing_block = out.get("closing_sources")
        if isinstance(closing_block, dict):
            closing_block = dict(closing_block)
            closing_block["evening_memo"] = memo
            out["closing_sources"] = closing_block
        display = out.get("briefing_display")
        if isinstance(display, dict):
            display = dict(display)
            display["evening_memo"] = memo
            closing = _text(display.get("closing_message"))
            if closing and (
                korea_evening_memo_too_thin(closing)
                or "오늘의 정리와 퇴근 전 메모" in closing
            ):
                display["closing_message"] = (
                    "오늘 신호는 여기까지 정리했습니다. 출처는 아래에 그대로 남깁니다."
                )
            out["briefing_display"] = display

    return out
