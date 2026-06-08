"""Safe normalization of briefing field values for visible HTML copy."""
from __future__ import annotations

import ast
import html as html_module
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

PROGRAM_KOREA = "keysuri_korea_tech"

_PYTHON_LIST_RE = re.compile(r"^\s*\[.+]\s*$", re.DOTALL)

_VISIBLE_REPR_MARKERS: tuple[str, ...] = (
    "['",
    "']",
    "&#x27;, &#x27;",
    '[&quot;',
    "{'",
    " None",
    " null",
)

_DICT_TEXT_KEYS = ("text", "label", "body", "summary", "explanation")


def _clean_line(text: str) -> str:
    out = html_module.unescape(str(text or "").strip())
    out = out.replace("\\'", "'").replace('\\"', '"')
    out = re.sub(r"^\s*['\"]|['\"]\s*$", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def looks_like_python_list_repr(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if isinstance(text, (list, tuple)):
        return True
    if not _PYTHON_LIST_RE.match(stripped):
        return False
    return ("'" in stripped or '"' in stripped) and "," in stripped


def coerce_visible_lines(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        lines: List[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, dict):
                for key in _DICT_TEXT_KEYS:
                    chunk = _clean_line(str(item.get(key) or ""))
                    if chunk:
                        lines.append(chunk)
                        break
                continue
            chunk = _clean_line(str(item))
            if chunk:
                lines.append(chunk)
        return lines

    if isinstance(value, dict):
        for key in _DICT_TEXT_KEYS:
            chunk = _clean_line(str(value.get(key) or ""))
            if chunk:
                return [chunk]
        return []

    text = _clean_line(str(value))
    if not text:
        return []

    if looks_like_python_list_repr(text):
        try:
            parsed = ast.literal_eval(text)
            return coerce_visible_lines(parsed)
        except (ValueError, SyntaxError):
            text = re.sub(r"^\s*\[", "", text)
            text = re.sub(r"]\s*$", "", text)
            parts = [p.strip() for p in re.split(r"',\s*'|\",\s*\"|',\s*\"|\",\s*'", text) if p.strip()]
            if len(parts) >= 2:
                return [_clean_line(p) for p in parts if _clean_line(p)]
    return [text]


def dedupe_adjacent_sentences(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", raw) if s.strip()]
    if not sentences:
        return raw
    deduped: List[str] = []
    for sent in sentences:
        if deduped and deduped[-1] == sent:
            continue
        deduped.append(sent)
    return " ".join(deduped)


def dedupe_repeated_paragraph(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if not blocks:
        blocks = [raw]
    out_blocks: List[str] = []
    for block in blocks:
        cleaned = dedupe_adjacent_sentences(block)
        if cleaned and (not out_blocks or out_blocks[-1] != cleaned):
            out_blocks.append(cleaned)
    return "\n\n".join(out_blocks)


def render_visible_lines(value: Any, *, style: str = "inline") -> str:
    lines = [dedupe_adjacent_sentences(line) for line in coerce_visible_lines(value)]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    if style == "watch":
        return " ".join(f"→ {line.rstrip('.')}" for line in lines[:4])
    if style == "bullets":
        return "\n".join(f"• {line}" for line in lines)
    if style == "sentence":
        parts = [line if line.endswith((".", "!", "?", "…")) else f"{line}." for line in lines]
        return " ".join(parts)
    return " / ".join(lines)


def normalize_visible_text(value: Any, *, style: str = "inline") -> str:
    return render_visible_lines(value, style=style)


def contains_visible_repr_artifacts(text: str) -> bool:
    blob = str(text or "")
    if not blob:
        return False
    blob = re.sub(r"<style>.*?</style>", " ", blob, flags=re.DOTALL | re.IGNORECASE)
    blob = re.sub(r"<[^>]+>", " ", blob)
    blob = html_module.unescape(blob)
    blob = re.sub(r"\s+", " ", blob).strip()
    if re.search(r"\[\s*['\"]", blob):
        return True
    if re.search(r"['\"]\s*,\s*['\"]", blob):
        return True
    if "{'" in blob or '{"' in blob:
        return True
    if re.search(r"\bNone\b", blob):
        return True
    if re.search(r"\bnull\b", blob):
        return True
    return False


def count_owner_salutation(text: str, *, exclude_block_labels: bool = True) -> int:
    blob = str(text or "")
    if exclude_block_labels:
        blob = re.sub(r"<h4[^>]*class=\"block-label\"[^>]*>.*?</h4>", "", blob, flags=re.DOTALL | re.IGNORECASE)
        blob = re.sub(r"<p class=\"hero-subtitle\">.*?</p>", "", blob, flags=re.DOTALL | re.IGNORECASE)
        blob = re.sub(r"<span class=\"judgment-label\">.*?</span>", "", blob, flags=re.DOTALL | re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", " ", blob)
    return plain.count("주인님")


_INTERNAL_SCORE_MARKERS: tuple[str, ...] = (
    "국내 총점",
    "국내관련",
    "태그:",
    "selection_reason_tags",
    "reason_tags",
    "confidence math",
    "scoring",
)

_INTERNAL_SCORE_CONTEXT_MARKERS: tuple[str, ...] = (
    "신호 점수",
    "선정 점수",
    "점수(",
    "점수와",
    "점수 ",
)

_INTERNAL_DEBUG_MARKERS: tuple[str, ...] = (
    "source_pack",
    "candidate",
    "debug",
    "raw",
)

_INTERNAL_SNAKE_TAGS: frozenset[str] = frozenset(
    {
        "korean_entity_mention",
        "policy_capital_signal",
        "industrial_signal",
        "global_to_korea_translation",
        "korea_ai_enterprise",
        "korea_semiconductor",
        "korea_robotics_manufacturing",
        "korea_battery_energy",
        "korea_platform_cloud_saas",
        "korea_policy_regulation",
        "korea_startup_investment",
        "korea_big_company_strategy",
        "korea_consumer_mobility",
        "press_release_only",
        "pr_hype_warning",
        "same_entity_not_same_story",
        "global_duplicate_with_korea_angle",
        "global_duplicate_no_korea_angle",
    }
)

_SNAKE_CASE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "not_verified",
        "live_fetch",
        "rss_summary",
        "preview_pending",
        "review_passed",
        "sent_archived",
        "data_top",
        "card_emphasis",
        "block_body",
        "block_label",
    }
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

_KOREA_CATEGORY_REASON: Dict[str, str] = {
    "korea_ai_enterprise": (
        "국내 AI 도입·서비스 검토와 내일 미팅 우선순위에 올릴 만한 신호입니다."
    ),
    "korea_semiconductor": (
        "반도체·공급망 판단에 직접 연결되는 신호라서 우선 확인이 필요합니다."
    ),
    "korea_robotics_manufacturing": (
        "스마트팩토리·자동화 투자 판단에 바로 연결되는 신호라서 우선 확인이 필요합니다."
    ),
    "korea_battery_energy": (
        "배터리·에너지 공급망과 투자 검토 우선순위에 올릴 만한 신호입니다."
    ),
    "korea_platform_cloud_saas": (
        "국내 플랫폼·클라우드 도입 일정과 파트너십 검토에 연결되는 신호입니다."
    ),
    "korea_policy_regulation": (
        "국내 정책과 투자 흐름이 함께 움직인 신호라서, 내일 관련 사업·파트너십 검토 우선순위에 올릴 만합니다."
    ),
    "korea_startup_investment": (
        "투자·M&A 검토와 지원사업 확인 우선순위가 올라가는 신호입니다."
    ),
    "korea_big_company_strategy": (
        "대기업 전략·조직 개편이 내일 파트너·공급망 판단에 영향을 줄 수 있는 신호입니다."
    ),
    "korea_consumer_mobility": (
        "국내 소비자·모빌리티 시장 일정과 실행 확인이 필요한 신호입니다."
    ),
    "global_to_korea_translation": (
        "글로벌 발표가 국내 AI 기업의 투자·GPU 확보 문제로 이어지는 신호라서 한국 적용 관점에서 확인해야 합니다."
    ),
}

_TAG_REASON_LEAD: Dict[str, str] = {
    "policy_capital_signal": "국내 정책과 투자 흐름이 함께 움직인",
    "industrial_signal": "산업·공급망 판단에 직접 연결되는",
    "korean_entity_mention": "국내 주요 기업·기관이 직접 언급된",
    "global_to_korea_translation": "글로벌 발표가 국내 적용으로 이어지는",
}

_KOREA_IMPACT_BY_CATEGORY: Dict[str, str] = {
    "global_to_korea_translation": (
        "글로벌 발표가 국내 AI 기업의 투자·GPU 확보 논의로 이어질 수 있습니다."
    ),
    "korea_startup_investment": (
        "원자력·딥테크 투자 검토와 지원사업 확인 우선순위가 올라갑니다."
    ),
    "korea_policy_regulation": (
        "정책·조달 일정과 내일 관련 사업 검토 우선순위가 올라갑니다."
    ),
    "korea_semiconductor": (
        "HBM·파운드리 공급망 판단과 내일 미팅 우선순위에 반영될 수 있습니다."
    ),
}

_MACHINE_IMPACT_RE = re.compile(
    r"^(?:내일\s*영향\s*[:：]\s*)?(?P<cat>.+?)\s*신호(?:\s*신호)?가\s*의사결정·미팅\s*우선순위에\s*반영될\s*수\s*있습니다\.?$"
)

_SNAKE_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _normalize_sentence_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def looks_like_internal_owner_copy(text: str) -> bool:
    blob = _normalize_sentence_ws(html_module.unescape(str(text or "")))
    if not blob:
        return False
    lowered = blob.lower()
    if any(marker in blob for marker in _INTERNAL_SCORE_MARKERS):
        return True
    if any(marker in blob for marker in _INTERNAL_SCORE_CONTEXT_MARKERS):
        return True
    if any(marker in lowered for marker in _INTERNAL_DEBUG_MARKERS):
        return True
    if "탈락:" in blob and "_" in blob:
        return True
    if re.search(r"총점\s*\d", blob):
        return True
    if re.search(r"구조\s*\d+", blob) and re.search(r"실행\s*\d+", blob):
        return True
    for tag in _INTERNAL_SNAKE_TAGS:
        if tag in lowered:
            return True
    return bool(_SNAKE_TOKEN_RE.search(lowered) and not _is_allowlisted_snake_blob(lowered))


def _is_allowlisted_snake_blob(blob: str) -> bool:
    tokens = _SNAKE_TOKEN_RE.findall(blob.lower())
    if not tokens:
        return True
    return all(token in _SNAKE_CASE_ALLOWLIST for token in tokens)


def strip_watch_arrow_prefixes(text: str) -> str:
    parts = re.split(r"[;；]\s*", str(text or "").strip())
    cleaned: List[str] = []
    for part in parts:
        chunk = re.sub(r"^(?:→\s*)+", "", part.strip())
        chunk = re.sub(r"^(?:-\s*)+", "", chunk).strip()
        if chunk:
            cleaned.append(chunk)
    return "; ".join(cleaned)


def dedupe_sentences_in_paragraph(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", raw) if s.strip()]
    if not sentences:
        return raw
    deduped: List[str] = []
    seen: set[str] = set()
    for sent in sentences:
        norm = _normalize_sentence_ws(sent)
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(sent)
    return " ".join(deduped)


def _strip_impact_label_prefix(text: str, *, label: str = "내일 영향") -> str:
    out = str(text or "").strip()
    prefixes = (
        f"{label}:",
        f"{label} :",
        "내일 영향:",
        "내일 영향 :",
        "내일영향:",
    )
    changed = True
    while changed and out:
        changed = False
        for prefix in prefixes:
            if out.startswith(prefix):
                out = out[len(prefix) :].strip()
                changed = True
    return out


def sanitize_visible_impact_line(
    text: Any,
    *,
    label: str = "내일 영향",
    category: str = "",
) -> str:
    out = _strip_impact_label_prefix(normalize_visible_text(text, style="inline"), label=label)
    if not out:
        cat = str(category or "").strip()
        if cat in _KOREA_IMPACT_BY_CATEGORY:
            return _KOREA_IMPACT_BY_CATEGORY[cat]
        return ""
    out = re.sub(r"신호\s+신호", "신호", out)
    match = _MACHINE_IMPACT_RE.match(out)
    if match:
        cat_label = match.group("cat").strip()
        for key, replacement in _KOREA_IMPACT_BY_CATEGORY.items():
            if cat_label == _KOREA_CATEGORY_KO.get(key, "") or key == category:
                return replacement
        if "글로벌→한국" in cat_label or "번역" in cat_label:
            return _KOREA_IMPACT_BY_CATEGORY["global_to_korea_translation"]
        if "스타트업" in cat_label or "투자" in cat_label:
            return _KOREA_IMPACT_BY_CATEGORY["korea_startup_investment"]
        return "내일 관련 투자·공급망·정책 확인 우선순위가 올라갑니다."
    out = re.sub(r"신호\s+신호", "신호", out)
    return dedupe_sentences_in_paragraph(out)


def _entity_hook_from_title(title: str) -> str:
    title = str(title or "").strip()
    if not title:
        return ""
    if len(title) <= 36:
        return title.rstrip(".")
    return title[:33].rstrip() + "…"


def _korea_reason_from_tags_and_category(
    *,
    tags: Sequence[str],
    category: str,
    title: str,
) -> str:
    tag_set = {str(t).strip() for t in tags if str(t).strip()}
    if "global_to_korea_translation" in tag_set or category == "global_to_korea_translation":
        return _KOREA_CATEGORY_REASON["global_to_korea_translation"]
    if category in _KOREA_CATEGORY_REASON:
        base = _KOREA_CATEGORY_REASON[category]
        hook = _entity_hook_from_title(title)
        if hook and category == "korea_semiconductor" and ("협력" in hook or "HBM" in hook.upper()):
            return f"{hook}이 공급망 판단에 직접 연결되는 신호라서 우선 확인이 필요합니다."
        if hook and category in ("korea_big_company_strategy", "korea_semiconductor"):
            return f"{hook} 관련 {base}"
        return base
    for tag in ("policy_capital_signal", "industrial_signal", "korean_entity_mention"):
        if tag in tag_set:
            lead = _TAG_REASON_LEAD[tag]
            return (
                f"{lead} 신호라서, 내일 관련 사업·파트너십 검토 우선순위에 올릴 만합니다."
            )
    return "국내 적용·실행 확인 관점에서 오늘 의미 있는 신호로 선정했습니다."


def build_visible_selection_reason(
    item: Mapping[str, Any],
    meta: Optional[Mapping[str, Any]] = None,
    *,
    program_id: str = PROGRAM_KOREA,
    existing: str = "",
) -> str:
    meta = meta or {}
    if program_id != PROGRAM_KOREA:
        cleaned = dedupe_sentences_in_paragraph(normalize_visible_text(existing, style="inline"))
        return cleaned

    candidate = normalize_visible_text(existing, style="inline")
    if candidate and not looks_like_internal_owner_copy(candidate):
        return dedupe_sentences_in_paragraph(candidate)[:120]

    for key in ("selection_reason", "selection_rationale", "reason_for_selection"):
        raw = normalize_visible_text(item.get(key) or meta.get(key) or "", style="inline")
        if raw and not looks_like_internal_owner_copy(raw):
            return dedupe_sentences_in_paragraph(raw)[:120]

    category = str(
        meta.get("primary_category")
        or item.get("primary_category")
        or item.get("category")
        or ""
    ).strip()
    tags = meta.get("selection_reason_tags") or item.get("selection_reason_tags") or []
    if not isinstance(tags, list):
        tags = coerce_visible_lines(tags)
    title = str(
        item.get("korean_title") or item.get("headline") or meta.get("statement") or ""
    ).strip()
    return _korea_reason_from_tags_and_category(tags=tags, category=category, title=title)


def sanitize_visible_selection_reason(
    value: Any,
    item: Optional[Mapping[str, Any]] = None,
    meta: Optional[Mapping[str, Any]] = None,
    *,
    program_id: str = PROGRAM_KOREA,
) -> str:
    item = item or {}
    existing = normalize_visible_text(value, style="inline")
    return build_visible_selection_reason(item, meta, program_id=program_id, existing=existing)


def contains_internal_owner_copy_leaks(text: str) -> bool:
    return looks_like_internal_owner_copy(text)


def contains_visible_snake_case_token(text: str) -> bool:
    blob = html_module.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    lowered = blob.lower()
    for tag in _INTERNAL_SNAKE_TAGS:
        if tag in lowered:
            return True
    for token in _SNAKE_TOKEN_RE.findall(lowered):
        if token not in _SNAKE_CASE_ALLOWLIST:
            return True
    return False


def contains_korea_impact_phrase_issues(text: str) -> bool:
    blob = str(text or "")
    if "신호 신호" in blob:
        return True
    if "내일 영향: 내일 영향:" in blob.replace(" ", ""):
        return True
    if re.search(r"내일\s*영향\s*[:：].*내일\s*영향\s*[:：]", blob):
        return True
    return False


def contains_duplicate_watch_arrows(text: str) -> bool:
    return bool(re.search(r"→\s*→", str(text or "")))


_KOREA_CHECKPOINT_STRATEGY_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("내일의 사업 전략을 구체화하십시오", "내일의 투자 및 사업 전략을 구체화하십시오"),
    ("내일 사업 전략을 구체화하십시오", "내일의 투자 및 사업 전략을 구체화하십시오"),
    ("내일의 사업 전략을 재점검하십시오", "내일의 투자 및 사업 전략을 재점검하십시오"),
    ("내일 사업 전략을 재점검하십시오", "내일의 투자 및 사업 전략을 재점검하십시오"),
    ("사업 전략을 구체화하십시오", "투자 및 사업 전략을 구체화하십시오"),
    ("사업 전략을 점검하십시오", "투자 및 사업 전략을 점검하십시오"),
    ("사업 전략을 재점검하십시오", "투자 및 사업 전략을 재점검하십시오"),
    ("사업 전략을 정리하십시오", "투자 및 사업 전략을 정리하십시오"),
)

_KOREA_CHECKPOINT_DOUBLE_INVEST_RE = re.compile(
    r"투자\s*및\s*(?:투자\s*및\s*)+"
)
_KOREA_CHECKPOINT_DOUBLE_STRATEGY_RE = re.compile(
    r"투자\s*및\s*사업\s*및\s*사업\s*전략"
)


def _collapse_korea_checkpoint_duplicates(text: str) -> str:
    out = str(text or "")
    out = _KOREA_CHECKPOINT_DOUBLE_INVEST_RE.sub("투자 및 ", out)
    out = _KOREA_CHECKPOINT_DOUBLE_STRATEGY_RE.sub("투자 및 사업 전략", out)
    return re.sub(r"\s+", " ", out).strip()


def polish_korea_checkpoint_text(text: Any) -> str:
    out = _normalize_sentence_ws(normalize_visible_text(text, style="inline"))
    if not out:
        return ""
    if "투자 및 사업 전략" in out:
        return _collapse_korea_checkpoint_duplicates(out)
    for old, new in _KOREA_CHECKPOINT_STRATEGY_REPLACEMENTS:
        if "투자 및 사업 전략" in out:
            break
        out = out.replace(old, new)
    return _collapse_korea_checkpoint_duplicates(out)


def korea_checkpoint_strategy_too_generic(text: str) -> bool:
    blob = _normalize_sentence_ws(str(text or ""))
    if not blob:
        return False
    if "투자 및 사업 전략" in blob:
        return False
    if re.search(r"내일의?\s*사업\s*전략", blob):
        return True
    generic_patterns = (
        r"사업\s*전략을\s*구체화하십시오",
        r"사업\s*전략을\s*점검하십시오",
        r"사업\s*전략을\s*재점검하십시오",
        r"사업\s*전략을\s*정리하십시오",
    )
    return any(re.search(pattern, blob) for pattern in generic_patterns)


def extract_user_facing_prose(html: str) -> str:
    region = str(html or "")
    cut = region.find('id="operation-metadata"')
    if cut >= 0:
        region = region[:cut]
    for pattern in (
        r'<div class="source-box"[^>]*>.*?</div>',
        r'<details class="audit-fold"[^>]*>.*',
        r'<div class="meta-box"[^>]*>.*?</div>',
        r'<div class="validation-box"[^>]*>.*?</div>',
        r'<div class="compliance-box"[^>]*>.*?</div>',
        r'<div class="review-box"[^>]*>.*?</div>',
        r"<style>.*?</style>",
    ):
        region = re.sub(pattern, " ", region, flags=re.DOTALL | re.IGNORECASE)
    return region
