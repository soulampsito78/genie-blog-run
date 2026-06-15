"""Korea 18:30 longform visible structure — deep-dive blocks and evening memo."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from keysuri_visible_text import (
    coerce_visible_lines,
    dedupe_sentences_in_paragraph,
    normalize_visible_text,
    repair_obvious_korean_quality_artifacts,
    sanitize_visible_impact_line,
    strip_watch_arrow_prefixes,
)

KOREA_DEEP_MAX_PARAGRAPH_CHARS = 220
KOREA_CLOSING_PARAGRAPH_MAX_CHARS = 220
KOREA_MEMO_ACTION_MAX_CHARS = 180
KOREA_EVENING_MEMO_HEADING = "퇴근 전 메모"
KOREA_DEEP_SUBFRAME = "한국 기업·정책으로 읽으면"
KOREA_CHECKPOINT_SUBFRAME = "한국 시장 관찰 포인트"
KOREA_DEEP_DIVE_REQUIRED_LABELS: tuple[str, ...] = (
    "글로벌 영향",
    "국내 산업 영향",
    "기회 요인",
    "위험 요인",
    "키수리 판단",
)
KOREA_DEEP_DIVE_FORBIDDEN_LABELS: tuple[str, ...] = (
    "오늘의 핵심 흐름",
    "국내 적용",
    "내일 볼 지점",
    "아직 불확실한 점",
)
KOREA_WARM_FAREWELL_LINES: tuple[str, ...] = (
    "오늘도 수고 많으셨습니다.",
    "내일 아침에 다시 볼 흐름만 남겨두겠습니다.",
)

FORBIDDEN_KOREA_VISIBLE_LABELS: tuple[str, ...] = (
    "국내 18:30 따뜻한 마무리",
    "오늘의 정리와 퇴근 전 메모",
    "warm ending",
    "evening close",
    "domestic evening close",
)

_TRUNCATED_GLUE_RE = re.compile(
    r"오늘 눈에 띄는 점은[^.!?…]*[가-힣A-Za-z0-9]{1,3}…[^.!?…]*"
    r"(?:동시에 보인다는 것입니다|이슈가 동시에 보인다는 것입니다)\.?\s*",
    flags=re.DOTALL,
)
_GENERIC_AXIS_RE = re.compile(
    r"한쪽은 산업·인프라 쪽이고,\s*다른 쪽은 소프트웨어·운영 쪽입니다\.?\s*"
)
_TRUNCATED_TOKEN_RE = re.compile(
    r"(?:^|[\s,·])[\uac00-\ud7a3A-Za-z0-9]{1,3}…"
)
_INCOMPLETE_KOREAN_TAIL_RE = re.compile(
    r"(?:"
    r"[가-힣]{1,4}합$|"
    r"[가-힣]{0,3}입니$|"
    r"[가-힣]{0,3}습니$|"
    r"[가-힣]{0,3}됩니$|"
    r"[가-힣]{0,3}했습$|"
    r"수립에$|"
    r"중요한 흐름$|"
    r"중요하여 글로벌$|"
    r"국내 로봇$|"
    r"국내 스타트업/투$|"
    r"국내 대기업 테크 전략$|"
    r"/투$|"
    r"주인님의 투$|"
    r"[가-힣]\s*내$|"
    r"조명합$|"
    r"작용합$|"
    r"제공합니$"
    r")"
)
_KOREA_VISIBLE_FIELD_MAX_CHARS = 220
_THIN_CLOSING_ONLY_RE = re.compile(
    r"^(?:오늘도 수고하셨습니다\.?\s*)?(?:내일 다시 뵙겠습니다\.?\s*)?$"
)
_DUPLICATE_KOREAN_MORPHEME_RE = re.compile(r"(?<![가-힣])([가-힣]{1,3})\s+\1(?=[가-힣])")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_duplicate_korean_morpheme(text: str) -> bool:
    return bool(_DUPLICATE_KOREAN_MORPHEME_RE.search(_text(text)))


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", _text(text)) if s.strip()]


def _first_sentences(text: str, count: int) -> str:
    parts = _split_sentences(text)
    return " ".join(parts[:count])


def clamp_action_line(text: str, *, max_chars: int = KOREA_MEMO_ACTION_MAX_CHARS) -> str:
    out = remove_truncated_headline_fragments(_text(text))
    if not out:
        return ""
    if len(out) <= max_chars:
        return out.rstrip(".")
    suffix = " 등"
    budget = max_chars - len(suffix)
    cut = out[:budget].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(",·")
    if not cut:
        cut = out[:budget].rstrip()
    return (cut + suffix)[:max_chars]


def clamp_korea_block(text: str, *, max_chars: int = KOREA_DEEP_MAX_PARAGRAPH_CHARS, max_sentences: int = 2) -> str:
    out = dedupe_sentences_in_paragraph(_text(text))
    if not out:
        return ""
    out = _first_sentences(out, max_sentences)
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out


def remove_truncated_headline_fragments(text: str) -> str:
    out = _text(text)
    if not out:
        return ""
    out = _TRUNCATED_GLUE_RE.sub("", out)
    out = _GENERIC_AXIS_RE.sub("", out)
    out = re.sub(r"[가-힣A-Za-z0-9]{1,2}…", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return repair_obvious_korean_quality_artifacts(out)


def contains_truncated_headline_fragment(text: str) -> bool:
    blob = _text(text)
    if not blob:
        return False
    if _TRUNCATED_TOKEN_RE.search(blob):
        return True
    if re.search(r"[H][가-힣A-Za-z0-9]{0,2}…", blob):
        return True
    if re.search(r"[가-힣]{1,2}…", blob):
        return True
    return "동시에 보인다는 것입니다" in blob and "…" in blob


def _last_visible_sentence(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", _text(text)) if s.strip()]
    return sentences[-1] if sentences else _text(text)


def _sentence_ends_complete_korean(sentence: str) -> bool:
    sent = _text(sentence)
    if not sent:
        return True
    if re.search(r"[.!?…]$", sent):
        return True
    if re.search(
        r"(습니다|입니다|니다|세요|요|다|함|음|겠습니다|되었습니다|할 수 있습니다|있습니다|됩니다)\.?$",
        sent,
    ):
        return True
    return False


def has_incomplete_korean_sentence_ending(text: str) -> bool:
    blob = _text(text)
    if not blob:
        return False
    if contains_truncated_headline_fragment(blob):
        return True
    if _has_duplicate_korean_morpheme(blob):
        return True
    last = _last_visible_sentence(blob)
    if _sentence_ends_complete_korean(last):
        return False
    if _INCOMPLETE_KOREAN_TAIL_RE.search(last):
        return True
    if re.search(r"[가-힣]{2,}(?:합|입니|습니|됩니|했습)$", last):
        return True
    if len(last) >= 10 and not re.search(r"[.!?…]$", last):
        if re.search(r"(?:에|의|를|을|와|과|로|에서|으로|및|등)$", last):
            return True
    return False


def clamp_korea_visible_field_at_sentence(text: str, *, max_chars: int = _KOREA_VISIBLE_FIELD_MAX_CHARS) -> str:
    out = dedupe_sentences_in_paragraph(_text(text))
    if not out:
        return ""
    if len(out) <= max_chars:
        return out
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", out) if s.strip()]
    kept: List[str] = []
    total = 0
    for sent in sentences:
        extra = len(sent) + (1 if kept else 0)
        if total + extra > max_chars and kept:
            break
        kept.append(sent)
        total += extra
    if kept:
        return " ".join(kept)
    return out[: max_chars - 1].rstrip() + "…"


def repair_incomplete_korean_visible_text(text: str, *, fallback: str = "") -> str:
    blob = remove_truncated_headline_fragments(repair_obvious_korean_quality_artifacts(_text(text)))
    if not blob:
        return remove_truncated_headline_fragments(_text(fallback))
    if not has_incomplete_korean_sentence_ending(blob):
        return blob
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", blob) if s.strip()]
    while sentences and has_incomplete_korean_sentence_ending(sentences[-1]):
        sentences.pop()
    if sentences:
        repaired = " ".join(sentences)
        if not has_incomplete_korean_sentence_ending(repaired):
            return remove_truncated_headline_fragments(repaired)
    repaired = re.sub(
        r"(?:\s*[가-힣A-Za-z0-9·,]{0,48}(?:합|입니|습니|됩니|했습|수립에|중요한 흐름|국내 로봇|주인님의 투))\s*$",
        "",
        blob,
    ).strip()
    if repaired and has_incomplete_korean_sentence_ending(repaired):
        clauses = [c.strip() for c in re.split(r"[,，]", repaired) if c.strip()]
        complete = [c for c in clauses if not has_incomplete_korean_sentence_ending(c)]
        if complete:
            repaired = ". ".join(f"{clause.rstrip('.')}." for clause in complete)
    if repaired and not has_incomplete_korean_sentence_ending(repaired):
        return remove_truncated_headline_fragments(repaired)
    fb = remove_truncated_headline_fragments(_text(fallback))
    if fb and not has_incomplete_korean_sentence_ending(fb):
        return fb
    return remove_truncated_headline_fragments(repaired or fb)


def finalize_korea_visible_field(text: str, *, fallback: str = "") -> str:
    clamped = clamp_korea_visible_field_at_sentence(text)
    return repair_incomplete_korean_visible_text(clamped, fallback=fallback)


def _short_title(title: str, *, max_len: int = 42) -> str:
    clean = remove_truncated_headline_fragments(title)
    if not clean:
        return ""
    if len(clean) <= max_len:
        return clean.rstrip(".")
    cut = clean[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    if cut:
        return cut.rstrip(",·") + " 등"
    return clean[: max_len - 1].rstrip()


def _item_watch_lines(item: Mapping[str, Any]) -> List[str]:
    raw = item.get("next_watch") or item.get("next_check_point") or ""
    lines = coerce_visible_lines(raw)
    if not lines:
        text = strip_watch_arrow_prefixes(_text(raw))
        if text:
            lines = [p.strip() for p in re.split(r"[;；]", text) if p.strip()]
    out: List[str] = []
    for line in lines:
        for part in re.split(r"[;；]", strip_watch_arrow_prefixes(line)):
            part = re.sub(r"^내일 볼 지점:\s*", "", part.strip())
            if part and part not in out:
                out.append(part.rstrip("."))
    return out


def _expand_action_candidates(lines: Sequence[str], *, max_chars: int) -> List[str]:
    out: List[str] = []
    for line in lines:
        parts = re.split(r"[;；]", line) if re.search(r"[;；]", line) else [line]
        for part in parts:
            cleaned = clamp_action_line(part, max_chars=max_chars)
            if cleaned and cleaned not in out:
                out.append(cleaned)
            if len(out) >= 3:
                return out[:3]
    return out


def _theme_phrase(items: Sequence[Mapping[str, Any]]) -> str:
    blob = " ".join(_text(i.get("korean_title") or i.get("headline")) for i in items if isinstance(i, dict))
    if any(k in blob for k in ("젠슨 황", "엔비디아", "NVIDIA", "nvidia")):
        return "엔비디아 방한 이슈"
    if any(k in blob for k in ("HBM", "반도체", "삼성", "SK하이닉스")):
        return "반도체·HBM 협력 이슈"
    if any(k in blob for k in ("스타트업", "투자", "아토믹")):
        return "국내 투자·딥테크 이슈"
    return "국내 테크 핵심 이슈"


def _format_bullets(lines: Sequence[str]) -> str:
    cleaned = [remove_truncated_headline_fragments(_text(line)) for line in lines]
    cleaned = [line for line in cleaned if line]
    if not cleaned:
        return ""
    return "\n".join(f"• {line}" for line in cleaned)


def _item_judgment(item: Mapping[str, Any]) -> tuple[str, str]:
    nested = item.get("keysuri_judgment")
    if isinstance(nested, dict):
        label = _text(nested.get("label"))
        explanation = _text(nested.get("explanation") or nested.get("text"))
        if label or explanation:
            return label, explanation
    label = _text(item.get("keysuri_judgment_label") or item.get("judgment_label"))
    text = _text(
        item.get("keysuri_judgment")
        if isinstance(item.get("keysuri_judgment"), str)
        else item.get("keysuri_judgment_text") or item.get("judgment_explanation")
    )
    return label, text


_OPPORTUNITY_LABELS = frozenset({"기회", "활용 후보", "사업 신호"})
_RISK_LABELS = frozenset({"경계", "리스크 신호", "과장 주의", "추가 확인 필요"})
_GLOBAL_MARKERS = (
    "엔비디아",
    "NVIDIA",
    "nvidia",
    "OpenAI",
    "구글",
    "Google",
    "Microsoft",
    "미국",
    "글로벌",
    "해외",
    "빅테크",
    "AWS",
)


def _item_blob(item: Mapping[str, Any]) -> str:
    return " ".join(
        _text(item.get(key))
        for key in (
            "korean_title",
            "headline",
            "what_happened",
            "why_now",
            "why_it_matters",
            "owner_angle",
            "selection_reason",
        )
    )


def _is_global_signal_item(item: Mapping[str, Any]) -> bool:
    if item.get("global_duplicate_detected") or item.get("global_overlap"):
        return True
    blob = _item_blob(item)
    return any(marker in blob for marker in _GLOBAL_MARKERS)


_GLOBAL_BRIDGE_MARKERS: tuple[str, ...] = (
    "글로벌 AI 인프라",
    "플랫폼 경쟁",
    "반도체 공급망",
    "로봇",
    "에이전트 AI",
    "한국 기업",
    "국내 산업",
)
_KOREA_INDUSTRY_LABELS: Dict[str, str] = {
    "korea_ai_enterprise": "국내 AI·기업 도입",
    "korea_semiconductor": "국내 반도체·장비·소재",
    "korea_robotics_manufacturing": "국내 로보틱스·스마트팩토리",
    "korea_battery_energy": "국내 배터리·에너지",
    "korea_platform_cloud_saas": "국내 플랫폼·클라우드",
    "korea_policy_regulation": "국내 정책·규제",
    "korea_startup_investment": "국내 스타트업·투자",
    "korea_big_company_strategy": "국내 대기업 테크 전략",
    "korea_consumer_mobility": "국내 소비자 테크·모빌리티",
    "global_to_korea_translation": "글로벌→한국 번역 신호",
}


def _korea_top_axis(items: Sequence[Mapping[str, Any]]) -> str:
    titles = [
        _short_title(_text(item.get("korean_title") or item.get("headline")))
        for item in items
        if isinstance(item, dict)
    ]
    titles = [title for title in titles if title]
    if len(titles) >= 2:
        return "·".join(titles[:2])
    if titles:
        return titles[0]
    return _theme_phrase(items)


def _korea_industry_label(value: str) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if raw in _KOREA_INDUSTRY_LABELS:
        return _KOREA_INDUSTRY_LABELS[raw]
    if "_" in raw:
        return ""
    return raw


def _strip_keysuri_judgment_label_prefix(text: str) -> str:
    out = _text(text)
    out = re.sub(r"^키수리\s*판단\s*[:：]\s*", "", out)
    return out.strip()


def _declarative_risk_statement(line: str) -> str:
    out = finalize_korea_visible_field(line)
    if not out:
        return ""
    stripped = re.sub(r"[?？]+\s*$", "", out).strip()
    if not stripped:
        return ""
    question_markers = (
        "무엇일까요",
        "무엇일까",
        "무엇인가",
        "무엇인지",
        "어떨까요",
        "될까요",
        "있을까요",
        "얼마나",
        "이어질 것인가",
        "어떻게",
        "무엇을",
        "몇 ",
        "인가",
    )
    if "?" in out or any(marker in stripped for marker in question_markers):
        topic = re.sub(r"[?？].*$", "", stripped).strip()
        topic = re.sub(
            r"\s*(?:무엇일까요|무엇일까|무엇인가|무엇인지|어떨까요|될까요|있을까요)\s*$",
            "",
            topic,
        ).strip()
        topic = re.sub(r"(?:구체적인\s*)?영향은\s*$", "영향", topic).strip()
        topic = re.sub(r"(?:은|는|이|가|을|를|에|의)\s*$", "", topic).strip()
        if any(marker in topic for marker in question_markers):
            topic = ""
        if len(topic) >= 8:
            return f"{topic}에 대한 불확실성과 검증 공백이 리스크로 남아 있습니다."
        return "세부 방향·규모·일정에 대한 불확실성이 리스크로 남아 있습니다."
    if not _sentence_ends_complete_korean(stripped):
        stripped = finalize_korea_visible_field(stripped)
    if stripped and not stripped.endswith((".", "!", "…")):
        stripped += "."
    return stripped


def _build_global_impact_block(
    items: Sequence[Mapping[str, Any]],
    cleaned_body: str,
) -> str:
    items = [item for item in items if isinstance(item, dict)]
    global_pressure: List[str] = []
    if any(_is_global_signal_item(item) for item in items):
        global_pressure.append("해외 빅테크·플랫폼 일정")
    blob = " ".join(_item_blob(item) for item in items)
    if any(marker in blob for marker in _GLOBAL_MARKERS):
        global_pressure.append("글로벌 공급망·인프라 변화")
    pressure = "·".join(global_pressure[:2]) if global_pressure else "글로벌 AI 인프라·플랫폼 경쟁"
    body = (
        f"글로벌 AI 인프라·플랫폼 경쟁과 반도체 공급망·로봇/에이전트 AI 축은 "
        f"{pressure}와 맞물려 한국 기업·스타트업·공급망과 정책·자본시장에 압력을 전달합니다. "
        f"한국 쪽에서는 해외 인프라·조달 구조 변화에 맞춰 투자·조달·파트너십 우선순위를 "
        f"재배치해야 하는 단계입니다."
    )
    return clamp_korea_block(finalize_korea_visible_field(body))


def _build_domestic_industry_block(items: Sequence[Mapping[str, Any]]) -> str:
    items = [item for item in items if isinstance(item, dict)]
    industries: List[str] = []
    for item in items:
        cat = _korea_industry_label(_text(item.get("category_label_ko") or item.get("primary_category")))
        if cat and cat not in industries:
            industries.append(cat)
    industry_phrase = ", ".join(industries[:3]) if industries else "반도체·AI·정책·투자"
    body = (
        f"국내 TOP5를 묶으면 {industry_phrase} 축이 동시에 움직이며 "
        f"산업 일정·자본 배분·규제 대응이 겹칩니다. "
        f"한국 기업·공급망 관점에서 협력·조달·투자 우선순위가 함께 흔들리는 국내 산업 영향입니다."
    )
    return clamp_korea_block(finalize_korea_visible_field(body))


def _build_opportunity_block(items: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label, explanation = _item_judgment(item)
        if label in _OPPORTUNITY_LABELS:
            line = explanation or _first_sentences(
                _text(item.get("owner_angle") or item.get("next_day_impact_line")), 1
            )
            line = remove_truncated_headline_fragments(line)
            if line and line not in lines:
                lines.append(line)
    if not lines:
        for item in items[:2]:
            if not isinstance(item, dict):
                continue
            impact = sanitize_visible_impact_line(
                _text(item.get("next_day_impact_line") or item.get("owner_action_line")),
                category=str(item.get("primary_category") or ""),
            )
            if impact and impact not in lines:
                lines.append(impact)
    if not lines:
        lines = [
            "국내 파트너십·투자 후속 일정이 열리면 실행 속도를 앞당길 여지가 있습니다.",
            "정책·조달 신호가 맞물리면 밸류체인 내 협력 포인트가 분명해질 수 있습니다.",
        ]
    return _format_bullets(lines[:3])


def _build_risk_block(
    items: Sequence[Mapping[str, Any]],
    uncertainty: str,
) -> str:
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label, explanation = _item_judgment(item)
        hype = _text(item.get("hype_caution"))
        if label in _RISK_LABELS and explanation:
            line = _declarative_risk_statement(explanation)
            if line and line not in lines:
                lines.append(line)
        elif hype:
            line = _declarative_risk_statement(hype)
            if line and line not in lines:
                lines.append(line)
        if item.get("detail_insufficient"):
            line = "세부 수치·일정은 공개 요약만으로는 아직 제한적입니다."
            if line not in lines:
                lines.append(line)
    unc_lines = [
        _declarative_risk_statement(line)
        for line in coerce_visible_lines(uncertainty)
        if _text(line)
    ]
    for line in unc_lines[:2]:
        if line and line not in lines:
            lines.append(line)
    if not lines:
        lines = [
            "과장된 해석이나 보도자료 톤은 분리해 볼 필요가 있습니다.",
            "세부 일정·수치는 향후 공식 발표로 보완될 가능성이 있습니다.",
        ]
    return _format_bullets(lines[:3])


def _build_keysuri_judgment_block(items: Sequence[Mapping[str, Any]]) -> str:
    labels: List[str] = []
    explanations: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label, explanation = _item_judgment(item)
        if label and label not in labels:
            labels.append(label)
        if explanation and explanation not in explanations:
            explanations.append(_strip_keysuri_judgment_label_prefix(explanation))
    if explanations:
        core = " ".join(explanations[:2])
    elif labels:
        core = f"오늘 신호는 {', '.join(labels[:3])} 관점에서 균형 있게 관찰하는 편이 안전합니다."
    else:
        core = (
            "오늘 신호는 단기 과장과 구조 변화를 구분해 보는 것이 중요합니다. "
            "확인 가능한 범위 안에서만 실행 포인트를 좁혀 가겠습니다."
        )
    return clamp_korea_block(
        f"{finalize_korea_visible_field(core)} "
        f"주인님께서는 협력·조달·투자 우선순위를 내일 의사결정 기준에 맞춰 점검하시면 됩니다."
    )


def build_korea_one_line_checkpoint(
    top5_items: Sequence[Mapping[str, Any]],
    *,
    existing: str = "",
) -> str:
    """Synthesize a Korea-market observation from global+domestic TOP5 (not item recap)."""
    existing = remove_truncated_headline_fragments(_text(existing))
    thin_markers = (
        "먼저 보시면 됩니다",
        "내일 영향을 줄",
        "한 가지",
        "사업 전략을 구체화",
        "사업 전략을 점검",
        "사업 전략을 재점검",
    )
    if existing and not any(marker in existing for marker in thin_markers):
        if "한국" in existing or "국내" in existing or "글로벌" in existing:
            if len(existing) >= 28:
                return existing

    items = [i for i in top5_items if isinstance(i, dict)][:5]
    theme = _theme_phrase(items)
    axis = theme

    opportunity = False
    risk = False
    for item in items:
        label, _ = _item_judgment(item)
        if label in _OPPORTUNITY_LABELS:
            opportunity = True
        if label in _RISK_LABELS or item.get("hype_caution") or item.get("detail_insufficient"):
            risk = True

    if opportunity and risk:
        move = "기회와 리스크가 동시에 이동"
    elif opportunity:
        move = "실행·협력 기회 신호가 앞으로 이동"
    elif risk:
        move = "일정·수치 불확실성과 리스크 관리 압력이 앞으로 이동"
    else:
        move = "구조 변화 판단 압력이 앞으로 이동"

    return (
        f"글로벌·국내 TOP5를 종합하면, {axis} 축에서 한국 시장의 관건은 {move}하고 있습니다."
    )


def structure_korea_deep_dive(
    body: str,
    top5_items: Sequence[Mapping[str, Any]],
    *,
    uncertainty: str = "",
) -> List[Dict[str, str]]:
    """Return five Korea deep-dive contract blocks for visible rendering."""
    items = [i for i in top5_items if isinstance(i, dict)][:5]
    cleaned_body = remove_truncated_headline_fragments(
        dedupe_sentences_in_paragraph(remove_internal_glue(_text(body)))
    )

    sections: List[Dict[str, str]] = [
        {"label": "글로벌 영향", "body": _build_global_impact_block(items, cleaned_body)},
        {"label": "국내 산업 영향", "body": _build_domestic_industry_block(items)},
        {"label": "기회 요인", "body": _build_opportunity_block(items)},
        {"label": "위험 요인", "body": _build_risk_block(items, uncertainty)},
        {"label": "키수리 판단", "body": _build_keysuri_judgment_block(items)},
    ]
    return [s for s in sections if _text(s.get("body")) and _text(s.get("label"))]


def remove_internal_glue(text: str) -> str:
    out = _text(text)
    out = _TRUNCATED_GLUE_RE.sub("", out)
    out = _GENERIC_AXIS_RE.sub("", out)
    opener = "한국 기업·정책으로 읽으면, 오늘 선정된 신호는 국내 적용과 내일 영향이 겹치는 흐름입니다."
    out = out.replace(opener, "").strip()
    return re.sub(r"\n\s*\n+", "\n\n", out).strip()


def _collect_memo_action_lines(items: Sequence[Mapping[str, Any]]) -> List[str]:
    action_lines: List[str] = []
    for item in items:
        for line in _item_watch_lines(item):
            cleaned = clamp_action_line(remove_truncated_headline_fragments(line))
            if cleaned and cleaned not in action_lines:
                action_lines.append(cleaned)
            if len(action_lines) >= 3:
                return action_lines[:3]
    while len(action_lines) < 2 and items:
        idx = len(action_lines)
        item = items[min(idx, len(items) - 1)]
        title = _short_title(_text(item.get("korean_title") or item.get("headline"))) or "핵심 신호"
        fallback = clamp_action_line(f"{title} 관련 후속 확인")
        if fallback and fallback not in action_lines:
            action_lines.append(fallback)
    return action_lines[:3]


def build_korea_evening_memo(
    top5_items: Sequence[Mapping[str, Any]],
    *,
    closing_message: str = "",
) -> Dict[str, Any]:
    items = [i for i in top5_items if isinstance(i, dict)][:5]
    theme = _theme_phrase(items)
    action_lines = _collect_memo_action_lines(items)
    memo: Dict[str, Any] = {
        "summary": (
            f"오늘은 {theme}가 HBM·파운드리·국내 AI 투자 흐름을 한 번에 묶었습니다."
        ),
        "action_intro": "내일은 세 가지만 확인하시면 됩니다.",
        "action_lines": action_lines,
        "caution": "확정되지 않은 수치와 일정은 아직 조심해서 보겠습니다.",
        "warm_lines": list(KOREA_WARM_FAREWELL_LINES),
    }

    closing = remove_truncated_headline_fragments(_text(closing_message))
    if any(label in closing for label in FORBIDDEN_KOREA_VISIBLE_LABELS):
        return memo
    return memo


def memo_plain_text(memo: Mapping[str, Any]) -> str:
    lines = [
        _text(memo.get("summary")),
        _text(memo.get("action_intro")),
        *[
            f"{idx + 1}. {line}"
            for idx, line in enumerate(memo.get("action_lines") or [])
            if _text(line)
        ],
        _text(memo.get("caution")),
        *[_text(line) for line in memo.get("warm_lines") or [] if _text(line)],
    ]
    return "\n".join(line for line in lines if line)


def count_korea_memo_action_lines(text: str) -> int:
    blob = _text(text)
    numbered = len(re.findall(r"^\s*\d+\.\s+", blob, flags=re.MULTILINE))
    bullets = len(re.findall(r"^\s*•\s+", blob, flags=re.MULTILINE))
    explicit = len(
        re.findall(
            r"(?:확인|점검|추적|검토|후속|일정|공급|투자|협력|우선순위)",
            blob,
        )
    )
    return max(numbered, bullets, explicit // 2)


def extract_korea_memo_action_lines_from_html(html: str) -> List[str]:
    section = _text(html)
    if not section:
        return []
    action_block = re.search(
        r'<ol[^>]*class="evening-memo-actions"[^>]*>(.*?)</ol>',
        section,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not action_block:
        return []
    return [
        remove_truncated_headline_fragments(re.sub(r"<[^>]+>", "", match).strip())
        for match in re.findall(r"<li>(.*?)</li>", action_block.group(1), flags=re.DOTALL | re.IGNORECASE)
        if re.sub(r"<[^>]+>", "", match).strip()
    ]


def count_korea_memo_action_lines_in_closing(html: str, *, plain_fallback: str = "") -> int:
    html_lines = extract_korea_memo_action_lines_from_html(html)
    if html_lines:
        return len(html_lines)
    return count_korea_memo_action_lines(plain_fallback)


def korea_evening_memo_too_thin(memo: Any) -> bool:
    if isinstance(memo, dict):
        return len([line for line in memo.get("action_lines") or [] if _text(line)]) < 2
    blob = _text(memo)
    if not blob:
        return True
    if _THIN_CLOSING_ONLY_RE.match(blob):
        return True
    if "오늘도 수고하셨습니다" in blob and count_korea_memo_action_lines(blob) < 2:
        return True
    return count_korea_memo_action_lines(blob) < 2


def korea_warm_farewell_missing(text: str) -> bool:
    blob = _text(text)
    return not all(line in blob for line in KOREA_WARM_FAREWELL_LINES)


def _visible_closing_line_length(fragment: str) -> int:
    import html as html_module

    plain = html_module.unescape(re.sub(r"<[^>]+>", " ", _text(fragment)))
    return len(re.sub(r"\s+", " ", plain).strip())


def korea_closing_paragraph_too_long(text: str) -> bool:
    """True when any visible closing <p> or <li> exceeds the paragraph threshold."""
    for pattern in (r"<p[^>]*>(.*?)</p>", r"<li[^>]*>(.*?)</li>"):
        for match in re.finditer(pattern, text, flags=re.DOTALL | re.IGNORECASE):
            if _visible_closing_line_length(match.group(1)) > KOREA_CLOSING_PARAGRAPH_MAX_CHARS:
                return True
    return False


def korea_memo_action_line_too_long(lines: Sequence[str]) -> bool:
    for line in lines:
        plain = _text(line)
        if plain and len(plain) > KOREA_MEMO_ACTION_MAX_CHARS:
            return True
    return False


def korea_deep_block_too_long(sections: Sequence[Mapping[str, str]]) -> bool:
    for section in sections:
        body = _text(section.get("body"))
        if not body:
            continue
        for block in body.split("\n"):
            block = block.lstrip("• ").strip()
            if block and len(block) > KOREA_DEEP_MAX_PARAGRAPH_CHARS:
                return True
    return False


def korea_closing_structure_incomplete(memo: Mapping[str, Any]) -> bool:
    if not _text(memo.get("summary")):
        return True
    if len([line for line in memo.get("action_lines") or [] if _text(line)]) < 2:
        return True
    if not _text(memo.get("caution")):
        return True
    warm = [line for line in memo.get("warm_lines") or [] if _text(line)]
    return len(warm) < 1


def max_paragraph_length(text: str) -> int:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", _text(text)) if b.strip()]
    if not blocks:
        blocks = [_text(text)]
    return max((len(b) for b in blocks), default=0)


def korea_deep_dive_wall_text(sections: Sequence[Mapping[str, str]]) -> bool:
    return korea_deep_block_too_long(sections)


def korea_deep_dive_missing_blocks(sections: Sequence[Mapping[str, str]]) -> bool:
    visible = {str(s.get("label") or "").strip() for s in sections if _text(s.get("body"))}
    return not all(label in visible for label in KOREA_DEEP_DIVE_REQUIRED_LABELS)


def korea_deep_dive_uses_forbidden_labels(sections: Sequence[Mapping[str, str]]) -> bool:
    labels = {str(s.get("label") or "").strip() for s in sections}
    return any(label in labels for label in KOREA_DEEP_DIVE_FORBIDDEN_LABELS)


def korea_closing_internal_label_leak(text: str) -> bool:
    blob = _text(text)
    return any(label in blob for label in FORBIDDEN_KOREA_VISIBLE_LABELS)


def korea_section_label_not_user_facing(text: str) -> bool:
    blob = _text(text)
    if not blob:
        return False
    forbidden = (
        "warm ending",
        "evening close",
        "domestic evening close",
    )
    return any(token in blob for token in forbidden) or korea_closing_internal_label_leak(blob)


def korea_closing_repeats_title_only(text: str) -> bool:
    blob = _text(text).replace(KOREA_EVENING_MEMO_HEADING, "").strip()
    if not blob:
        return True
    if _THIN_CLOSING_ONLY_RE.match(blob):
        return True
    return (
        blob.count("\n") < 1
        and count_korea_memo_action_lines(blob) < 2
        and "오늘도 수고하셨습니다" in blob
    )
