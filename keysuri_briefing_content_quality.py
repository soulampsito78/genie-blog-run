"""Kee-Suri briefing content quality gate (visible Korean text only)."""
from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Error code for the real owner-review send path (keysuri_service_full_run.py) to
# use when validate_global_post_render_visible_quality blocks SMTP dispatch.
KEYSURI_GLOBAL_POST_RENDER_QA_BLOCKED = "keysuri_global_post_render_qa_blocked"

# Korea counterpart — used when validate_korea_post_render_visible_quality
# blocks SMTP dispatch on the Korea Tech owner-review send path.
KEYSURI_KOREA_POST_RENDER_QA_BLOCKED = "keysuri_korea_post_render_qa_blocked"

from keysuri_contract_preview_quality import (
    FORBIDDEN_PHRASES,
    GENERIC_CLOSING_PHRASES,
    _block_text,
    _extract_top_item_blocks,
    _hangul_ratio,
    _is_mostly_english,
    _sentence_count,
    _visible_body_region,
)
from keysuri_korea_longform_ux import (
    KOREA_CLOSING_PARAGRAPH_MAX_CHARS,
    KOREA_DEEP_MAX_PARAGRAPH_CHARS,
    KOREA_EVENING_MEMO_HEADING,
    KOREA_MEMO_ACTION_MAX_CHARS,
    KOREA_NEWS_SUMMARY_CLICHE_PHRASES,
    contains_truncated_headline_fragment,
    count_korea_memo_action_lines_in_closing,
    extract_korea_memo_action_lines_from_html,
    has_incomplete_korean_sentence_ending,
    korea_checkpoint_lacks_confirm_and_hold,
    korea_cliche_phrase_overused,
    korea_closing_internal_label_leak,
    korea_closing_paragraph_too_long,
    korea_defensive_market_phrase_overused,
    korea_closing_repeats_title_only,
    korea_deep_block_too_long,
    korea_deep_dive_missing_blocks,
    korea_deep_dive_repeats_top5_headline,
    korea_deep_dive_uses_forbidden_labels,
    korea_everyday_impact_lens_insufficient,
    korea_market_lens_insufficient,
    korea_memo_action_line_too_long,
    korea_risk_lacks_hold_criteria,
    korea_section_label_not_user_facing,
    korea_upper_layer_only_without_everyday_lens,
    korea_warm_farewell_missing,
    max_paragraph_length,
)
from keysuri_visible_text import (
    contains_duplicate_watch_arrows,
    contains_internal_owner_copy_leaks,
    contains_korea_impact_phrase_issues,
    contains_visible_repr_artifacts,
    contains_visible_snake_case_token,
    count_owner_salutation,
    extract_user_facing_prose,
    korea_checkpoint_strategy_too_generic,
)

ALLOWED_JUDGMENT_LABELS: Tuple[str, ...] = (
    "기회",
    "관찰",
    "경계",
    "활용 후보",
    "사업 신호",
    "리스크 신호",
    "추가 확인 필요",
    "과장 주의",
)

GENERIC_OWNER_ANGLE_MARKERS: Tuple[str, ...] = (
    "점검하시면 됩니다",
    "구분해 보시는 것이 좋습니다",
    "반영할지 점검",
)

GENERIC_WHY_NOW_MARKERS: Tuple[str, ...] = (
    "지금 주목받는 신호입니다",
    "의사결정에 영향을 줄 수 있습니다",
    "경쟁사와 공급망",
)

RECAP_CHECKPOINT_MARKERS: Tuple[str, ...] = (
    "오늘 신호는",
    "정리했습니다",
    "여기까지",
    "다섯 신호",
)

CERTAINTY_WITHOUT_SOURCE: Tuple[str, ...] = (
    "확실히",
    "반드시",
    "틀림없",
    "100%",
)

GENERIC_AI_FILLER: Tuple[str, ...] = (
    "기업들이 AI를 도입",
    "AI 도입이 가속",
    "AI adoption is accelerating",
    "companies are adopting ai",
    "인공지능 도입이 확산",
    "업무 효율이 높아질 수 있습니다",
    "기업들이 ai를 활용",
)

# Global Tech abstract-filler endings. Any single use is normal Korean prose; the
# low-quality pattern is stacking these WITHOUT concrete facts (no numbers, dates,
# named actors) — the "그래서 어쩌자고?" abstract-summary state.
GLOBAL_ABSTRACT_FILLER_MARKERS: Tuple[str, ...] = (
    "중요합니다",
    "시사합니다",
    "촉진합니다",
    "보여줍니다",
    "필수적입니다",
    "영향력을 과시했습니다",
    "기반을 이해하는 데 필수적입니다",
)

# Minimum abstract-filler hits in one item (with no digit-backed specifics) to
# flag it as low quality.
GLOBAL_ABSTRACT_FILLER_ITEM_THRESHOLD = 2

# Category-generic "why now" padding sentences (see keysuri_briefing_content_enricher's
# _WHY_NOW_CONTEXT / _BROAD_MOVEMENT). A single use is normal fallback copy; the
# same sentence reused across 2+ of the 5 TOP items reads as a templated filler
# rather than a signal-specific briefing.
GLOBAL_COMMON_FILLER_SENTENCES: Tuple[str, ...] = (
    "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다.",
    "배포·워크플로·API 통제권 변화와 맞닿는 시점입니다.",
    "사용자 접점·검색·쇼핑 경험 변화로 읽힙니다.",
)

# Known visible-text artifacts observed in production Gmail owner-review email —
# a signal-chip/judgment label glued directly to the next word/title with no (or
# only one) separating space, instead of a proper "·" separator between chips.
# Literal known strings only (not a general grammar regex): a blanket "label
# directly followed by any Hangul character" pattern would false-positive on
# ordinary Korean sentences, since particles attach to nouns with no space
# (e.g. "...판단은 사업 신호이며..." is normal grammar, not a glue defect).
GLOBAL_SIGNAL_DISTRIBUTION_BROKEN_MARKERS: Tuple[str, ...] = (
    "사업 신호IEEE",
    "사업 신호 IEEE",
    "활용 후보구글",
    "활용 후보 구글",
    "과장 주의메타",
    "과장 주의 메타",
)

# Known "키수리 판단" judgment-row badge glued directly to the following
# explanation text with no separating space/character.
GLOBAL_BADGE_SPACING_BROKEN_MARKERS: Tuple[str, ...] = (
    "키수리 판단 사업 신호AI",
    "키수리 판단 활용 후보검증",
    "키수리 판단 관찰프리미엄",
)

# Known visible typo artifact ("살펴보면" mistyped as "살보면") that must never
# survive into the final owner-review email.
GLOBAL_POST_RENDER_TYPO_ARTIFACT_MARKERS: Tuple[str, ...] = (
    "살보면 됩니다",
    "살보면 될",
)

GLOBAL_COMMON_FILLER_REPEAT_THRESHOLD = 2

SPONSORED_FRAMING_MARKERS: Tuple[str, ...] = (
    "스폰서",
    "파트너 콘텐츠",
    "광고",
    "유료",
    "sponsored",
    "partner content",
)

NON_AI_CATEGORY_MARKERS: Tuple[str, ...] = (
    "반도체",
    "칩",
    "로봇",
    "배터리",
    "에너지",
    "전력",
    "그리드",
    "인프라",
    "공급망",
    "정책",
    "규제",
)

RAW_FIELD_LABEL_LEAKS: Tuple[str, ...] = (
    "category:",
    "confidence_label:",
    "source_ids:",
    "news_id:",
)

CASE_STUDY_MARKERS: Tuple[str, ...] = (
    "customer story",
    "case study",
    "고객 사례",
    "endava",
    "frontiers",
)

INTERNAL_VALIDATION_VISIBLE_MARKERS: Tuple[str, ...] = (
    "TOP 신호",
    "signal marker",
    "category layer",
    "글로벌 테크 TOP5 선정 기준",
    "점검하는 데 유용합니다",
)

KOREA_FORBIDDEN_GLOBAL_LABELS: Tuple[str, ...] = (
    "글로벌 원인",
    "한국 도착 전 압력",
    "다음 48시간 관찰 포인트",
)

KOREA_LENS_TERMS: Tuple[str, ...] = (
    "국내 적용",
    "한국 해석",
    "국내 해석",
    "내일 영향",
    "내일 볼 지점",
    "퇴근 전 메모",
    "오늘의 정리",
)

KOREA_STOCK_DIGEST_MARKERS: Tuple[str, ...] = (
    "코스피",
    "코스닥",
    "주가",
    "상한가",
    "하한가",
    "장중",
)

KOREA_GLOBAL_LAYER_LABEL_LEAKS: Tuple[str, ...] = (
    "워크플로·락인",
    "물리·인프라 병목",
    "규제·주권·조달 압력",
)

KOREA_OWNER_SALUTATION_MAX = 6

MIN_DETAIL_SENTENCES = 3

URL_PATTERN = re.compile(r"https?://[^\s<\"']+")


@dataclass
class BriefingContentIssue:
    code: str
    message: str
    section: str = ""
    item_index: Optional[int] = None
    excerpt: str = ""
    severity: str = "error"


@dataclass
class BriefingContentQualityResult:
    ok: bool
    issues: List[BriefingContentIssue] = field(default_factory=list)
    warnings: List[BriefingContentIssue] = field(default_factory=list)
    manual_review_required: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "manual_review_required": self.manual_review_required,
            "issues": [i.__dict__ for i in self.issues],
            "warnings": [w.__dict__ for w in self.warnings],
        }


def _judgment_label(block: str) -> str:
    match = re.search(r'class="judgment-badge"[^>]*>([^<]+)<', block)
    return match.group(1).strip() if match else ""


def _normalize_for_dup(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())[:120]


def _watch_checkpoint_count(text: str) -> int:
    if not text.strip():
        return 0
    bullets = len(re.findall(r"(?:^|\n)\s*[-•]\s+", text))
    if bullets >= 2:
        return bullets
    numbered = len(re.findall(r"\d+\.", text))
    if numbered >= 2:
        return numbered
    arrows = text.count("→")
    if arrows >= 1:
        return arrows + 1
    parts = [p.strip() for p in re.split(r"[;；]\s*", text) if p.strip()]
    if len(parts) >= 2:
        return len(parts)
    return _sentence_count(text)


def _english_rss_leak(text: str) -> bool:
    if not text.strip():
        return False
    if _is_mostly_english(text):
        return True
    if re.search(r"\b(RSS|feed|published|announcement|update)\b", text, flags=re.IGNORECASE):
        if _hangul_ratio(text) < 0.4:
            return True
    return False


def _claim_for_top_item(
    idx: int,
    block: str,
    scored_claims: List[dict],
    source_metadata: Optional[dict],
) -> Optional[dict]:
    """Match TOP item claim by source URL when possible (rank order may differ)."""
    src_match = re.search(r'class="chip-url"[^>]*href="([^"]+)"', block)
    if src_match and isinstance(source_metadata, dict):
        url = src_match.group(1).strip()
        sid_for_url: Dict[str, str] = {}
        for src in source_metadata.get("sources") or []:
            if not isinstance(src, dict):
                continue
            src_url = str(src.get("source_url") or "").strip()
            sid = str(src.get("source_id") or "").strip()
            if src_url and sid:
                sid_for_url[src_url] = sid
        sid = sid_for_url.get(url)
        if sid:
            for claim in scored_claims:
                sids = claim.get("source_ids") if isinstance(claim.get("source_ids"), list) else []
                if sid in [str(s) for s in sids]:
                    return claim
    if 1 <= idx <= len(scored_claims):
        return scored_claims[idx - 1]
    return None


def _deep_dive_references_multiple_signals(
    deep_text: str,
    *,
    top_headlines: Sequence[str],
    source_metadata: Optional[dict],
) -> bool:
    if any(k in deep_text for k in ("단일", "하나의 신호", "이번", "해당 사례")):
        return True

    if isinstance(source_metadata, dict):
        linked = source_metadata.get("deep_dive_linked_signals") or []
        if isinstance(linked, list) and len([x for x in linked if str(x).strip()]) >= 2:
            return True

    from keysuri_briefing_body_ux_normalizer import count_signal_references

    pseudo_items = [{"korean_title": h} for h in top_headlines if str(h).strip()]
    if count_signal_references(deep_text, pseudo_items) >= 2:
        return True

    if isinstance(source_metadata, dict):
        matched_sources = 0
        for src in source_metadata.get("sources") or []:
            if not isinstance(src, dict):
                continue
            name = str(src.get("source_name") or "").strip()
            if not name:
                continue
            token = name.split()[0]
            if len(token) >= 2 and (token in deep_text or token.lower() in deep_text.lower()):
                matched_sources += 1
        if matched_sources >= 2:
            return True

    legacy_markers = sum(1 for n in ("1.", "2.", "3.", "4.", "5.", "신호", "TOP") if n in deep_text)
    return legacy_markers >= 2


def _has_duplicate_adjacent_sentence(text: str) -> bool:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", str(text or "").strip()) if s.strip()]
    seen: set[str] = set()
    for sent in sentences:
        norm = re.sub(r"\s+", " ", sent).strip()
        if norm in seen:
            return True
        seen.add(norm)
    return False


def _plain_text(html_fragment: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_module.unescape(str(html_fragment or "")))


def _html_is_korea_briefing(html: str, *, use_korea_scoring_rules: bool) -> bool:
    if use_korea_scoring_rules:
        return True
    return bool(re.search(r'<body[^>]*\btheme-korea\b', html, flags=re.IGNORECASE))


def _briefing_prose_region(region: str) -> str:
    prose = region
    for marker in ('class="audit-fold"', 'id="operation-metadata"', "Operation metadata"):
        idx = prose.find(marker)
        if idx >= 0:
            prose = prose[:idx]
    return prose


def _validate_visible_serialization_issues(
    html: str,
    region: str,
    *,
    use_korea_scoring_rules: bool,
    item_blocks: Sequence[str],
) -> List[BriefingContentIssue]:
    issues: List[BriefingContentIssue] = []
    prose_region = _briefing_prose_region(region)

    if contains_visible_repr_artifacts(prose_region):
        issues.append(
            BriefingContentIssue(
                "visible_python_list_repr",
                "Visible body contains Python list/dict repr artifacts",
                section="visible_body",
                excerpt=prose_region[prose_region.find("["): prose_region.find("[") + 80]
                if "[" in prose_region
                else "",
            )
        )

    user_prose = extract_user_facing_prose(html)
    user_plain = _plain_text(user_prose)

    if contains_internal_owner_copy_leaks(user_plain):
        issues.append(
            BriefingContentIssue(
                "visible_internal_score_leak",
                "Visible body leaks internal scoring or debug selection copy",
                section="visible_body",
                excerpt=user_plain[:120],
            )
        )
    if contains_visible_snake_case_token(user_plain):
        issues.append(
            BriefingContentIssue(
                "visible_snake_case_token",
                "Visible body contains snake_case internal token",
                section="visible_body",
                excerpt=user_plain[:120],
            )
        )
    if contains_korea_impact_phrase_issues(user_plain):
        issues.append(
            BriefingContentIssue(
                "korea_impact_phrase_duplicate",
                "Visible impact line has awkward duplicated phrasing",
                section="visible_body",
            )
        )
    if contains_duplicate_watch_arrows(user_plain):
        issues.append(
            BriefingContentIssue(
                "korea_next_watch_arrow_duplicate",
                "Next-watch block has duplicated arrow markers",
                section="visible_body",
            )
        )

    for idx, block in enumerate(item_blocks, start=1):
        watch = _block_text(block, "다음 확인 포인트")
        if watch and contains_visible_repr_artifacts(watch):
            issues.append(
                BriefingContentIssue(
                    "korea_next_watch_list_repr",
                    f"TOP item {idx} next-watch block leaks list repr",
                    section="top5",
                    item_index=idx,
                    excerpt=watch[:100],
                )
            )
        if watch and contains_duplicate_watch_arrows(watch):
            issues.append(
                BriefingContentIssue(
                    "korea_next_watch_arrow_duplicate",
                    f"TOP item {idx} next-watch block has duplicated arrows",
                    section="top5",
                    item_index=idx,
                    excerpt=watch[:100],
                )
            )
        selection = _block_text(block, "선정 이유")
        if use_korea_scoring_rules and selection and contains_internal_owner_copy_leaks(selection):
            issues.append(
                BriefingContentIssue(
                    "korea_visible_rationale_not_user_facing",
                    f"TOP item {idx} selection reason is not owner-facing",
                    section="top5",
                    item_index=idx,
                    excerpt=selection[:100],
                )
            )
        emphasis_m = re.search(
            r'<p class="card-emphasis-line">(.*?)</p>',
            block,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if emphasis_m:
            emphasis_plain = _plain_text(emphasis_m.group(1))
            if contains_korea_impact_phrase_issues(emphasis_plain):
                issues.append(
                    BriefingContentIssue(
                        "korea_impact_phrase_duplicate",
                        f"TOP item {idx} card emphasis has awkward impact phrasing",
                        section="top5",
                        item_index=idx,
                        excerpt=emphasis_plain[:100],
                    )
                )
        if _html_is_korea_briefing(html, use_korea_scoring_rules=use_korea_scoring_rules):
            for label, code in (
                ("무슨 일이 있었나", "what_happened"),
                ("왜 지금 중요한가", "why_now"),
                ("주인님 관점", "owner_angle"),
                ("선정 이유", "selection_reason"),
            ):
                body = _block_text(block, label)
                if body and has_incomplete_korean_sentence_ending(body):
                    issues.append(
                        BriefingContentIssue(
                            "korea_incomplete_sentence_ending",
                            f"TOP item {idx} {code} has incomplete Korean sentence ending",
                            section="top5",
                            item_index=idx,
                            excerpt=body[:100],
                        )
                    )
            for label, code in (
                ("무슨 일이 있었나", "what_happened"),
                ("왜 지금 중요한가", "why_now"),
                ("주인님 관점", "owner_angle"),
            ):
                body = _block_text(block, label)
                if body and _has_duplicate_adjacent_sentence(body):
                    issues.append(
                        BriefingContentIssue(
                            "duplicate_sentence_in_visible_block",
                            f"TOP item {idx} {code} block repeats the same sentence",
                            section="top5",
                            item_index=idx,
                            excerpt=body[:100],
                        )
                    )

    unc_m = re.search(
        r'class="deep-uncertainty"[^>]*>.*?<p>(.*?)</p>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if unc_m:
        uncertainty = re.sub(r"<[^>]+>", "", unc_m.group(1)).strip()
        if uncertainty and contains_visible_repr_artifacts(uncertainty):
            issues.append(
                BriefingContentIssue(
                    "korea_uncertainty_list_repr",
                    "Deep-dive uncertainty block leaks list repr",
                    section="deep_dive",
                    excerpt=uncertainty[:100],
                )
            )

    if _html_is_korea_briefing(html, use_korea_scoring_rules=use_korea_scoring_rules):
        prose_region = _briefing_prose_region(region)
        label_only = re.findall(
            r'<p class="card-emphasis-line">\s*<span class="card-emphasis-label">[^<]+</span>\s*</p>',
            html,
            flags=re.IGNORECASE,
        )
        if label_only:
            issues.append(
                BriefingContentIssue(
                    "korea_emphasis_line_missing_text",
                    "Korea card emphasis line shows label without impact text",
                    section="top5",
                )
            )
        owner_count = count_owner_salutation(prose_region)
        if owner_count > KOREA_OWNER_SALUTATION_MAX:
            issues.append(
                BriefingContentIssue(
                    "korea_owner_name_overused",
                    f"Korea visible body uses 주인님 {owner_count} times (max {KOREA_OWNER_SALUTATION_MAX})",
                    section="visible_body",
                )
            )
        for label in KOREA_GLOBAL_LAYER_LABEL_LEAKS:
            if label in prose_region:
                issues.append(
                    BriefingContentIssue(
                        "korea_global_layer_label_leak",
                        f"Korea briefing exposes Global-style layer label: {label!r}",
                        section="deep_dive",
                        excerpt=label,
                    )
                )
                break

    return issues


def _extract_html_section(html: str, section_id: str) -> str:
    pattern = rf'<section[^>]*\bid=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>'
    match = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else ""


def _extract_source_list_region(html: str) -> str:
    """Return the HTML region used for closing source URL completeness checks."""
    appendix = _extract_html_section(html, "source-appendix-section")
    if appendix:
        return appendix
    legacy = _extract_html_section(html, "closing-section")
    if legacy and "evening-memo-body" not in legacy:
        return legacy
    closing_sources = _extract_html_section(html, "closing-sources")
    if closing_sources:
        return closing_sources
    return ""


def _parse_korea_deep_blocks(section_html: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    for match in re.finditer(
        r'class="korea-deep-block"[^>]*>.*?class="korea-deep-label"[^>]*>(.*?)</h4>.*?class="korea-deep-body"[^>]*>(.*?)</div>',
        section_html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        body = re.sub(r"<[^>]+>", "\n", match.group(2)).strip()
        body = re.sub(r"\n\s*\n+", "\n", body)
        if label or body:
            blocks.append({"label": label, "body": body})
    return blocks


def _validate_korea_longform_visible_ux(
    html: str,
    *,
    use_korea_scoring_rules: bool,
    top_headlines: Sequence[str] = (),
) -> List[BriefingContentIssue]:
    if not _html_is_korea_briefing(html, use_korea_scoring_rules=use_korea_scoring_rules):
        return []

    issues: List[BriefingContentIssue] = []
    visible_plain = _plain_text(extract_user_facing_prose(html))
    deep_section = _extract_html_section(html, "deep-dive-section")
    memo_section = _extract_html_section(html, "closing-section")
    if "evening-memo-body" not in memo_section:
        memo_section = _extract_html_section(html, "warm-close-section")
    deep_plain = _plain_text(deep_section)
    memo_plain = _plain_text(memo_section)
    action_lines = extract_korea_memo_action_lines_from_html(memo_section)
    memo_action_count = count_korea_memo_action_lines_in_closing(memo_section, plain_fallback=memo_plain)

    if korea_section_label_not_user_facing(visible_plain):
        issues.append(
            BriefingContentIssue(
                "korea_section_label_not_user_facing",
                "Korea visible body includes internal or non-user-facing section label",
                section="visible_body",
            )
        )

    deep_blocks = _parse_korea_deep_blocks(deep_section)
    if deep_blocks:
        if korea_deep_block_too_long(deep_blocks):
            issues.append(
                BriefingContentIssue(
                    "korea_deep_block_too_long",
                    f"Korea deep-dive block exceeds {KOREA_DEEP_MAX_PARAGRAPH_CHARS} Korean characters",
                    section="deep_dive",
                )
            )
        if korea_deep_dive_missing_blocks(deep_blocks):
            issues.append(
                BriefingContentIssue(
                    "korea_deep_dive_missing_blocks",
                    "Korea deep-dive must include all five contract blocks",
                    section="deep_dive",
                )
            )
        if korea_deep_dive_uses_forbidden_labels(deep_blocks):
            issues.append(
                BriefingContentIssue(
                    "korea_deep_dive_forbidden_labels",
                    "Korea deep-dive uses retired four-box labels instead of contract blocks",
                    section="deep_dive",
                )
            )
        pseudo_top_items = [{"korean_title": h} for h in top_headlines if str(h or "").strip()]
        if pseudo_top_items and korea_deep_dive_repeats_top5_headline(deep_blocks, pseudo_top_items):
            issues.append(
                BriefingContentIssue(
                    "korea_deep_dive_repeats_top5_recap",
                    "Korea deep-dive must synthesize a market-structure judgment, not restate "
                    "TOP5 headlines verbatim",
                    section="deep_dive",
                )
            )
        for block in deep_blocks:
            body = block.get("body", "")
            label = str(block.get("label") or "").strip()
            if contains_truncated_headline_fragment(body):
                issues.append(
                    BriefingContentIssue(
                        "korea_truncated_headline_fragment",
                        "Korea deep-dive contains malformed truncated headline fragment",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
            if has_incomplete_korean_sentence_ending(body):
                issues.append(
                    BriefingContentIssue(
                        "korea_incomplete_sentence_ending",
                        f"Korea deep-dive block {label!r} has incomplete Korean sentence ending",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
            if label == "위험 요인" and "?" in body:
                issues.append(
                    BriefingContentIssue(
                        "korea_risk_section_question_style",
                        "Korea risk section must use declarative risk statements, not questions",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
            if label == "위험 요인" and korea_risk_lacks_hold_criteria(body):
                issues.append(
                    BriefingContentIssue(
                        "korea_risk_lacks_hold_criteria",
                        "Korea risk section must state what to not assume yet / hold off on "
                        "until confirmed (보류/단정/확인 전), not just an abstract warning",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
            if label == "키수리 판단" and re.search(r"^키수리\s*판단\s*[:：]", body.strip()):
                issues.append(
                    BriefingContentIssue(
                        "korea_judgment_label_duplicated",
                        "Korea judgment block body must not repeat the section label",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
            if label == "글로벌 영향" and not any(
                term in body for term in ("글로벌", "한국 기업", "국내 산업", "공급망", "플랫폼")
            ):
                issues.append(
                    BriefingContentIssue(
                        "korea_global_impact_missing_bridge",
                        "Korea global-impact block must bridge global pressure to Korea",
                        section="deep_dive",
                        excerpt=body[:100],
                    )
                )
                break
    elif deep_plain and max_paragraph_length(deep_plain) > KOREA_DEEP_MAX_PARAGRAPH_CHARS:
        issues.append(
            BriefingContentIssue(
                "korea_deep_dive_wall_text",
                f"Korea deep-dive paragraph exceeds {KOREA_DEEP_MAX_PARAGRAPH_CHARS} Korean characters",
                section="deep_dive",
                excerpt=deep_plain[:120],
            )
        )

    if korea_closing_internal_label_leak(memo_plain) or korea_closing_internal_label_leak(visible_plain):
        issues.append(
            BriefingContentIssue(
                "korea_closing_internal_label_leak",
                "Korea closing leaks internal evening-close label",
                section="closing_sources",
            )
        )
    if KOREA_EVENING_MEMO_HEADING not in memo_plain:
        issues.append(
            BriefingContentIssue(
                "korea_closing_memo_too_thin",
                f"Korea closing must include {KOREA_EVENING_MEMO_HEADING!r} heading",
                section="closing_sources",
            )
        )
    if korea_closing_repeats_title_only(memo_plain):
        issues.append(
            BriefingContentIssue(
                "korea_closing_repeats_title_only",
                "Korea closing repeats title-only or thin farewell copy",
                section="closing_sources",
                excerpt=memo_plain[:120],
            )
        )
    if memo_action_count < 2:
        issues.append(
            BriefingContentIssue(
                "korea_evening_memo_missing_actions",
                "Korea evening memo must include at least 2 concrete action lines",
                section="closing_sources",
                excerpt=memo_plain[:120],
            )
        )
    if korea_warm_farewell_missing(memo_plain):
        issues.append(
            BriefingContentIssue(
                "korea_closing_warm_farewell_missing",
                "Korea closing must include warm farewell lines after memo",
                section="closing_sources",
                excerpt=memo_plain[:120],
            )
        )
    if korea_closing_paragraph_too_long(memo_section):
        issues.append(
            BriefingContentIssue(
                "korea_closing_paragraph_too_long",
                f"Korea closing paragraph exceeds {KOREA_CLOSING_PARAGRAPH_MAX_CHARS} Korean characters",
                section="closing_sources",
            )
        )
    if korea_memo_action_line_too_long(action_lines):
        issues.append(
            BriefingContentIssue(
                "korea_memo_action_line_too_long",
                f"Korea memo action line exceeds {KOREA_MEMO_ACTION_MAX_CHARS} Korean characters",
                section="closing_sources",
            )
        )
    has_summary = "오늘은" in memo_plain and "묶었습니다" in memo_plain
    has_caution = "확정되지 않은" in memo_plain or "조심" in memo_plain
    has_warm = not korea_warm_farewell_missing(memo_plain)
    if not (has_summary and len(action_lines) >= 2 and has_caution and has_warm):
        issues.append(
            BriefingContentIssue(
                "korea_closing_structure_incomplete",
                "Korea closing must include memo summary, actions, caution, and warm farewell",
                section="closing_sources",
            )
        )

    return issues


def _claims_with_scores(source_metadata: Optional[dict]) -> List[dict]:
    if not isinstance(source_metadata, dict):
        return []
    claims = source_metadata.get("claims")
    if not isinstance(claims, list):
        return []
    return [c for c in claims if isinstance(c, dict)]


def validate_briefing_content_gate(
    html: str,
    *,
    source_metadata: Optional[dict] = None,
) -> BriefingContentQualityResult:
    """Validate visible Korean briefing substance — not HTML structure."""
    issues: List[BriefingContentIssue] = []
    warnings: List[BriefingContentIssue] = []
    region = _visible_body_region(html)

    for phrase in RAW_FIELD_LABEL_LEAKS:
        if phrase.lower() in region.lower():
            issues.append(
                BriefingContentIssue(
                    "raw_field_label_leak",
                    f"Visible body leaks raw field label: {phrase!r}",
                    section="visible_body",
                    excerpt=phrase,
                )
            )

    for phrase in FORBIDDEN_PHRASES:
        if phrase in region:
            issues.append(
                BriefingContentIssue(
                    "forbidden_phrase",
                    f"Forbidden phrase in briefing: {phrase!r}",
                    section="visible_body",
                    excerpt=phrase,
                )
            )

    for phrase in GENERIC_CLOSING_PHRASES:
        if phrase in region:
            issues.append(
                BriefingContentIssue(
                    "generic_closing",
                    f"Generic customer-service closing: {phrase!r}",
                    section="closing",
                    excerpt=phrase,
                )
            )

    item_blocks = _extract_top_item_blocks(html)
    if len(item_blocks) < 5:
        issues.append(
            BriefingContentIssue(
                "top5_item_count",
                f"Expected 5 briefing items, found {len(item_blocks)}",
                section="top5",
            )
        )

    use_global_scoring_rules = isinstance(source_metadata, dict) and isinstance(
        source_metadata.get("global_top5_selection"), dict
    )
    use_korea_scoring_rules = isinstance(source_metadata, dict) and isinstance(
        source_metadata.get("korea_top5_selection"), dict
    )
    min_detail_sentences = MIN_DETAIL_SENTENCES if use_global_scoring_rules else 2

    if use_korea_scoring_rules:
        for label in KOREA_FORBIDDEN_GLOBAL_LABELS:
            if label in region:
                issues.append(
                    BriefingContentIssue(
                        "korea_global_label_leak",
                        f"Korea briefing must not use Global-only label: {label!r}",
                        section="visible_body",
                        excerpt=label,
                    )
                )
        if not any(term in region for term in KOREA_LENS_TERMS):
            warnings.append(
                BriefingContentIssue(
                    "korea_lens_terms_missing",
                    "Korea briefing should include domestic-application or evening-memo lens terms",
                    section="visible_body",
                    severity="warning",
                )
            )
        stock_hits = sum(1 for m in KOREA_STOCK_DIGEST_MARKERS if m in region)
        tech_hits = sum(
            1
            for m in ("반도체", "정책", "공급망", "투자", "AI", "배터리", "로봇")
            if m in region
        )
        if stock_hits >= 2 and tech_hits < 2:
            warnings.append(
                BriefingContentIssue(
                    "korea_stock_digest_tone",
                    "Korea briefing reads like stock-price digest without tech/industry signal",
                    section="visible_body",
                    severity="warning",
                )
            )
        if korea_cliche_phrase_overused(region):
            issues.append(
                BriefingContentIssue(
                    "korea_news_summary_cliche_overused",
                    "Korea briefing overuses press-release/news-summary cliche phrases "
                    f"(watch for: {', '.join(KOREA_NEWS_SUMMARY_CLICHE_PHRASES)})",
                    section="visible_body",
                )
            )
        if korea_market_lens_insufficient(region):
            warnings.append(
                BriefingContentIssue(
                    "korea_market_lens_thin",
                    "Korea briefing should connect to at least 3 market lenses (stock/bond/FX/rate/"
                    "corporate investment/policy/industry/SME-worker/AI adoption/market reaction)",
                    section="visible_body",
                    severity="warning",
                )
            )
        if korea_everyday_impact_lens_insufficient(region):
            warnings.append(
                BriefingContentIssue(
                    "korea_everyday_impact_lens_thin",
                    "Korea Tech should translate signals into related industries, suppliers/materials/"
                    "parts/equipment, jobs/regions, personal investors, and SMB/freelancer impact.",
                    section="visible_body",
                    severity="warning",
                )
            )
        if korea_upper_layer_only_without_everyday_lens(region):
            warnings.append(
                BriefingContentIssue(
                    "korea_upper_layer_only_without_everyday_lens",
                    "Korea Tech leans on M&A/funding/procurement/beneficiary-stock language without "
                    "enough tangible downstream impact translation.",
                    section="visible_body",
                    severity="warning",
                )
            )
        if korea_defensive_market_phrase_overused(region):
            issues.append(
                BriefingContentIssue(
                    "korea_defensive_market_phrase_overused",
                    "Korea Tech overuses defensive market-impact phrasing instead of explaining where "
                    "the signal lands for industries, workers, operators, or ordinary investors.",
                    section="visible_body",
                )
            )

    scored_claims = _claims_with_scores(source_metadata)
    if use_global_scoring_rules and scored_claims and not any(
        c.get("selection_score") is not None or c.get("selection_rationale") for c in scored_claims
    ):
        issues.append(
            BriefingContentIssue(
                "missing_selection_score",
                "Source metadata lacks TOP5 selection scores or rationale",
                section="top5",
            )
        )

    owner_angles: List[str] = []
    why_now_texts: List[str] = []
    top_headlines: List[str] = []
    global_filler_item_texts: List[str] = []
    thin_detail_count = 0
    insufficient_marked = 0

    for idx, block in enumerate(item_blocks, start=1):
        headline_m = re.search(r'<h3[^>]*>\d+\.\s*(.*?)</h3>', block, flags=re.DOTALL)
        headline = re.sub(r"<[^>]+>", "", headline_m.group(1)).strip() if headline_m else ""
        if headline:
            top_headlines.append(headline)
        if headline and _english_rss_leak(headline):
            issues.append(
                BriefingContentIssue(
                    "english_rss_leakage",
                    f"TOP item {idx} headline is English-primary RSS text",
                    section="top5",
                    item_index=idx,
                    excerpt=headline[:80],
                )
            )

        what = _block_text(block, "무슨 일이 있었나")
        why = _block_text(block, "왜 지금 중요한가")
        owner = _block_text(block, "주인님 관점")
        watch = _block_text(block, "다음 확인 포인트")
        selection_reason = _block_text(block, "선정 이유")
        j_label = _judgment_label(block)

        for label, text, code in (
            ("무슨 일이 있었나", what, "item_detail_missing"),
            ("왜 지금 중요한가", why, "missing_why_now"),
            ("주인님 관점", owner, "missing_owner_angle"),
            ("다음 확인 포인트", watch, "missing_next_watch"),
        ):
            if not text.strip():
                issues.append(
                    BriefingContentIssue(
                        code,
                        f"TOP item {idx} missing {label}",
                        section="top5",
                        item_index=idx,
                    )
                )

        depth_fields: List[Tuple[str, str, int, str]] = [
            ("무슨 일이 있었나", what, min_detail_sentences, "item_detail_too_thin"),
        ]
        if use_global_scoring_rules:
            depth_fields.extend(
                [
                    ("선정 이유", selection_reason, 2, "missing_selection_reason_depth"),
                    ("왜 지금 중요한가", why, min_detail_sentences, "missing_why_now_depth"),
                    ("주인님 관점", owner, min_detail_sentences, "missing_owner_angle_depth"),
                ]
            )
            if not selection_reason.strip():
                issues.append(
                    BriefingContentIssue(
                        "missing_selection_reason",
                        f"TOP item {idx} missing 선정 이유",
                        section="top5",
                        item_index=idx,
                    )
                )
            if watch and _watch_checkpoint_count(watch) < 2:
                issues.append(
                    BriefingContentIssue(
                        "missing_next_watch_depth",
                        f"TOP item {idx} needs at least 2 next-watch checkpoints",
                        section="top5",
                        item_index=idx,
                        excerpt=watch[:100],
                    )
                )
        for label, text, min_sent, code in depth_fields:
            if text and _sentence_count(text) < min_sent:
                thin_detail_count += 1
                issues.append(
                    BriefingContentIssue(
                        code,
                        f"TOP item {idx} '{label}' needs at least {min_sent} sentences",
                        section="top5",
                        item_index=idx,
                        excerpt=text[:100],
                    )
                )

        combined_item_text = f"{what} {why} {owner}".lower()
        if use_global_scoring_rules:
            global_filler_item_texts.append(combined_item_text)
        for filler in GENERIC_AI_FILLER:
            if filler.lower() in combined_item_text:
                issues.append(
                    BriefingContentIssue(
                        "generic_ai_filler",
                        f"TOP item {idx} repeats generic AI adoption filler",
                        section="top5",
                        item_index=idx,
                        excerpt=filler,
                    )
                )

        if use_global_scoring_rules:
            combined_raw = f"{what} {why} {owner}"
            abstract_hits = sum(
                combined_raw.count(marker) for marker in GLOBAL_ABSTRACT_FILLER_MARKERS
            )
            has_concrete_specifics = bool(re.search(r"\d", combined_raw))
            if abstract_hits >= GLOBAL_ABSTRACT_FILLER_ITEM_THRESHOLD and not has_concrete_specifics:
                issues.append(
                    BriefingContentIssue(
                        "global_abstract_filler_no_specifics",
                        f"TOP item {idx} stacks abstract filler endings without concrete facts "
                        "(no numbers/dates/actors — '그래서 어쩌자고?' state)",
                        section="top5",
                        item_index=idx,
                        excerpt=combined_raw[:100],
                    )
                )

        is_case_study_item = any(m in combined_item_text for m in CASE_STUDY_MARKERS)
        if is_case_study_item and not any(
            m in block for m in ("과장 주의", "공식 고객 사례", "고객 사례")
        ):
            issues.append(
                BriefingContentIssue(
                    "marketing_case_study_unframed",
                    f"TOP item {idx} looks like marketing/customer case without framing",
                    section="top5",
                    item_index=idx,
                )
            )

        if use_korea_scoring_rules and scored_claims:
            claim = _claim_for_top_item(idx, block, scored_claims, source_metadata)
            if claim:
                if claim.get("global_duplicate_detected") and claim.get("korea_angle_satisfied"):
                    if not any(
                        t in block for t in ("국내", "한국", "내일", "공급망", "정책")
                    ):
                        issues.append(
                            BriefingContentIssue(
                                "korea_duplicate_angle_missing",
                                f"TOP item {idx} overlaps Global but lacks Korea-specific application copy",
                                section="top5",
                                item_index=idx,
                            )
                        )
                pr_warn = claim.get("pr_hype_warning") or claim.get("hype_warning")
                if pr_warn and not any(
                    m in block for m in ("과장 주의", "보도자료", "홍보")
                ):
                    issues.append(
                        BriefingContentIssue(
                            "korea_pr_hype_unframed",
                            f"TOP item {idx} has PR/hype warning but lacks caution framing",
                            section="top5",
                            item_index=idx,
                        )
                    )

        if use_global_scoring_rules and scored_claims:
            claim = _claim_for_top_item(idx, block, scored_claims, source_metadata)
            if claim:
                if claim.get("selection_score") is None and not claim.get("selection_rationale"):
                    issues.append(
                        BriefingContentIssue(
                            "missing_selection_score",
                            f"TOP item {idx} missing selection score/rationale in source data",
                            section="top5",
                            item_index=idx,
                        )
                    )
                if claim.get("hype_warning") and "과장 주의" not in block:
                    issues.append(
                        BriefingContentIssue(
                            "hype_warning_missing",
                            f"TOP item {idx} scored with hype penalty but lacks '과장 주의'",
                            section="top5",
                            item_index=idx,
                        )
                    )
                if claim.get("sponsored_warning") and not any(
                    m in block.lower() for m in SPONSORED_FRAMING_MARKERS
                ):
                    issues.append(
                        BriefingContentIssue(
                            "sponsored_warning_missing",
                            f"TOP item {idx} is sponsored/partner content but lacks sponsored framing",
                            section="top5",
                            item_index=idx,
                        )
                    )
                tier = str(claim.get("source_tier") or "")
                if tier in ("T4_AGGREGATOR_BLOG", "T5_SOCIAL_UNVERIFIED") and j_label != "추가 확인 필요":
                    issues.append(
                        BriefingContentIssue(
                            "weak_source_unmarked",
                            f"TOP item {idx} weak source tier must be marked '추가 확인 필요'",
                            section="top5",
                            item_index=idx,
                        )
                    )

        if what and _english_rss_leak(what):
            issues.append(
                BriefingContentIssue(
                    "english_rss_leakage",
                    f"TOP item {idx} body contains English RSS leakage",
                    section="top5",
                    item_index=idx,
                    excerpt=what[:80],
                )
            )

        if why:
            why_now_texts.append(_normalize_for_dup(why))
            if any(m in why for m in GENERIC_WHY_NOW_MARKERS) and len(why) < 80:
                issues.append(
                    BriefingContentIssue(
                        "generic_business_implication",
                        f"TOP item {idx} '왜 지금 중요한가' reads as generic template",
                        section="top5",
                        item_index=idx,
                        excerpt=why[:100],
                    )
                )

        if owner:
            owner_angles.append(_normalize_for_dup(owner))
            has_practical = any(
                k in owner for k in ("제품", "파트너", "로드맵", "비용", "API", "운영", "의사결정")
            )
            if len(owner) < 40 and not has_practical:
                issues.append(
                    BriefingContentIssue(
                        "missing_owner_angle",
                        f"TOP item {idx} '주인님 관점' lacks practical relevance",
                        section="top5",
                        item_index=idx,
                        excerpt=owner[:100],
                    )
                )
            elif not has_practical and all(m in owner for m in GENERIC_OWNER_ANGLE_MARKERS):
                issues.append(
                    BriefingContentIssue(
                        "missing_owner_angle",
                        f"TOP item {idx} '주인님 관점' reads as generic filler",
                        section="top5",
                        item_index=idx,
                        excerpt=owner[:100],
                    )
                )

        if "출처" not in block:
            issues.append(
                BriefingContentIssue(
                    "item_source_missing",
                    f"TOP item {idx} missing 출처 label",
                    section="top5",
                    item_index=idx,
                )
            )

        if j_label and j_label not in ALLOWED_JUDGMENT_LABELS:
            issues.append(
                BriefingContentIssue(
                    "invalid_judgment_label",
                    f"TOP item {idx} judgment label {j_label!r} not in allowed set",
                    section="top5",
                    item_index=idx,
                    excerpt=j_label,
                )
            )

        if "공개 요약 한계" in block or "공식 발표 대기" in block:
            insufficient_marked += 1
        elif what and _sentence_count(what) < min_detail_sentences:
            issues.append(
                BriefingContentIssue(
                    "source_detail_insufficient",
                    f"TOP item {idx} thin detail without limitation marker",
                    section="top5",
                    item_index=idx,
                )
            )

        src_match = re.search(r'class="chip-url"[^>]*href="([^"]+)"', block)
        if not src_match:
            issues.append(
                BriefingContentIssue(
                    "item_source_missing",
                    f"TOP item {idx} missing source URL",
                    section="top5",
                    item_index=idx,
                )
            )

    if owner_angles:
        from collections import Counter

        norm_counts = Counter(owner_angles)
        dup = [t for t, c in norm_counts.items() if c >= 3]
        if dup:
            issues.append(
                BriefingContentIssue(
                    "duplicate_implication",
                    "Same owner-angle implication repeated across 3+ items",
                    section="top5",
                    excerpt=dup[0][:80],
                )
            )

    if thin_detail_count >= 3:
        issues.append(
            BriefingContentIssue(
                "top5_insufficient_detail",
                f"{thin_detail_count} items have thin '무슨 일이 있었나' detail",
                section="top5",
            )
        )

    if use_global_scoring_rules and global_filler_item_texts:
        for filler in GLOBAL_COMMON_FILLER_SENTENCES:
            filler_lower = filler.lower()
            hits = sum(1 for t in global_filler_item_texts if filler_lower in t)
            if hits >= GLOBAL_COMMON_FILLER_REPEAT_THRESHOLD:
                issues.append(
                    BriefingContentIssue(
                        "global_repeated_common_filler",
                        f"Common filler sentence repeated across {hits} TOP5 items: {filler!r}",
                        section="top5",
                        excerpt=filler[:100],
                    )
                )

    deep_region = ""
    m = re.search(
        r'id="deep-dive-section"[^>]*>(.*?)(?=<section|<div class="footer-cluster"|$)',
        html,
        flags=re.DOTALL,
    )
    if m:
        deep_region = m.group(1)
    deep_text = re.sub(r"<[^>]+>", " ", deep_region).strip()

    if _sentence_count(deep_text) < 5:
        issues.append(
            BriefingContentIssue(
                "weak_deep_dive",
                "Deep-dive needs at least 5 Korean sentences",
                section="deep_dive",
                excerpt=deep_text[:120],
            )
        )

    if use_global_scoring_rules and scored_claims:
        non_ai_claims = [
            c
            for c in scored_claims
            if str(c.get("primary_category") or "") != "ai_software_platform"
        ]
        if non_ai_claims:
            combined_top = " ".join(owner_angles + why_now_texts)
            if not any(m in combined_top for m in NON_AI_CATEGORY_MARKERS):
                issues.append(
                    BriefingContentIssue(
                        "ai_only_framing",
                        "TOP5 includes non-AI categories but briefing frames AI-only",
                        section="top5",
                    )
                )

    if deep_text:
        korea_deep_dive = _html_is_korea_briefing(html, use_korea_scoring_rules=use_korea_scoring_rules)
        if not korea_deep_dive and "주인님" not in deep_text:
            issues.append(
                BriefingContentIssue(
                    "weak_deep_dive",
                    "Deep-dive must include Korean operator/founder relevance (주인님)",
                    section="deep_dive",
                )
            )
        if use_global_scoring_rules:
            if not _deep_dive_references_multiple_signals(
                deep_text,
                top_headlines=top_headlines,
                source_metadata=source_metadata,
            ):
                issues.append(
                    BriefingContentIssue(
                        "weak_deep_dive",
                        "Deep-dive must reference at least 2 selected signals or justify single-signal focus",
                        section="deep_dive",
                        excerpt=deep_text[:120],
                    )
                )
        for marker in INTERNAL_VALIDATION_VISIBLE_MARKERS:
            if marker.lower() in deep_text.lower():
                issues.append(
                    BriefingContentIssue(
                        "internal_validation_marker_visible",
                        f"Deep-dive exposes internal validation marker: {marker!r}",
                        section="deep_dive",
                        excerpt=deep_text[:120],
                    )
                )
                break
        if use_global_scoring_rules and any(g in deep_text for g in GENERIC_AI_FILLER):
            issues.append(
                BriefingContentIssue(
                    "weak_deep_dive",
                    "Deep-dive contains generic AI adoption filler",
                    section="deep_dive",
                )
            )
        has_uncertainty = any(
            k in deep_text for k in ("불확실", "추가 확인", "원문", "아직", "미확정")
        )
        if not has_uncertainty and insufficient_marked >= 1:
            warnings.append(
                BriefingContentIssue(
                    "unsupported_claim",
                    "Deep-dive lacks uncertainty marker while items need source review",
                    section="deep_dive",
                    severity="warning",
                )
            )
        for cert in CERTAINTY_WITHOUT_SOURCE:
            if cert in deep_text:
                warnings.append(
                    BriefingContentIssue(
                        "unsupported_claim",
                        f"Deep-dive may overstate certainty: {cert!r}",
                        section="deep_dive",
                        severity="warning",
                    )
                )

    checkpoint = ""
    cp_m = re.search(
        r'id="one-line-section"[^>]*>.*?<div[^>]*class="checkpoint"[^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not cp_m:
        cp_m = re.search(
            r'id="one-line-checkpoint"[^>]*>.*?<p[^>]*>(.*?)</p>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
    if cp_m:
        checkpoint = re.sub(r"<[^>]+>", "", cp_m.group(1)).strip()
    if checkpoint:
        if _html_is_korea_briefing(html, use_korea_scoring_rules=use_korea_scoring_rules) and korea_checkpoint_strategy_too_generic(
            checkpoint
        ):
            issues.append(
                BriefingContentIssue(
                    "korea_checkpoint_strategy_too_generic",
                    "Korea one-line checkpoint uses generic business-strategy CTA without investment lens",
                    section="one_line_checkpoint",
                    excerpt=checkpoint[:100],
                )
            )
        if any(m in checkpoint for m in RECAP_CHECKPOINT_MARKERS) and "?" not in checkpoint:
            issues.append(
                BriefingContentIssue(
                    "weak_checkpoint",
                    "One-line checkpoint reads as recap, not decision cue",
                    section="one_line_checkpoint",
                    excerpt=checkpoint[:100],
                )
            )
        if _html_is_korea_briefing(
            html, use_korea_scoring_rules=use_korea_scoring_rules
        ) and korea_checkpoint_lacks_confirm_and_hold(checkpoint):
            warnings.append(
                BriefingContentIssue(
                    "korea_checkpoint_lacks_confirm_and_hold",
                    "Korea one-line checkpoint should state both what to confirm first "
                    "tomorrow and what to hold off judging until confirmed",
                    section="one_line_checkpoint",
                    excerpt=checkpoint[:100],
                    severity="warning",
                )
            )
    else:
        issues.append(
            BriefingContentIssue(
                "weak_checkpoint",
                "One-line checkpoint missing",
                section="one_line_checkpoint",
            )
        )

    src_section = _extract_source_list_region(html)
    urls = URL_PATTERN.findall(src_section)
    if len(urls) < 1:
        issues.append(
            BriefingContentIssue(
                "source_list_incomplete",
                "Closing source list must include at least one URL",
                section="closing_sources",
            )
        )

    issues.extend(
        _validate_visible_serialization_issues(
            html,
            region,
            use_korea_scoring_rules=use_korea_scoring_rules,
            item_blocks=item_blocks,
        )
    )
    issues.extend(
        _validate_korea_longform_visible_ux(
            html,
            use_korea_scoring_rules=use_korea_scoring_rules,
            top_headlines=top_headlines,
        )
    )

    ok = len(issues) == 0
    return BriefingContentQualityResult(ok=ok, issues=issues, warnings=warnings)


def validate_global_post_render_visible_quality(html: str) -> BriefingContentQualityResult:
    """Public, self-contained entry point for the real owner-review send path.

    Checks the FINAL rendered HTML text — works for both the premium preview
    template (<article data-top-item>/<h4> markup) and the Gmail-safe
    owner-review email template (<p>-only markup, no <article>/<h4> tags).
    validate_briefing_content_gate's own filler-repeat check walks item_blocks
    built from _extract_top_item_blocks()/_block_text(), which only match the
    <article data-top-item>/<h4> structure — that structure never appears in
    the Gmail email template, so a block-based check alone would silently
    never fire on the real send path. Checking whole-plain-text occurrence
    counts instead makes the same GLOBAL_COMMON_FILLER_SENTENCES /
    global_repeated_common_filler check work on both templates.

    Also blocks three known visible-text artifacts on the same final-HTML
    plain text: signal-chip/title glue, "키수리 판단" badge/text glue, and the
    "살보면" typo — regardless of whether the renderer/sanitizer upstream was
    supposed to have already fixed them.
    """
    plain = _plain_text(html)
    issues: List[BriefingContentIssue] = []
    for filler in GLOBAL_COMMON_FILLER_SENTENCES:
        hits = plain.count(filler)
        if hits >= GLOBAL_COMMON_FILLER_REPEAT_THRESHOLD:
            issues.append(
                BriefingContentIssue(
                    "global_repeated_common_filler",
                    f"Common filler sentence repeated {hits} times in final HTML: {filler!r}",
                    section="top5",
                    excerpt=filler[:100],
                )
            )
    for marker in GLOBAL_SIGNAL_DISTRIBUTION_BROKEN_MARKERS:
        if marker in plain:
            issues.append(
                BriefingContentIssue(
                    "global_signal_distribution_visible_text_broken",
                    f"Signal-chip label glued to next word/title without separator: {marker!r}",
                    section="visible_body",
                    excerpt=marker,
                )
            )
    for marker in GLOBAL_BADGE_SPACING_BROKEN_MARKERS:
        if marker in plain:
            issues.append(
                BriefingContentIssue(
                    "global_post_render_badge_spacing_broken",
                    f"'키수리 판단' badge glued to explanation text without separator: {marker!r}",
                    section="visible_body",
                    excerpt=marker,
                )
            )
    for marker in GLOBAL_POST_RENDER_TYPO_ARTIFACT_MARKERS:
        if marker in plain:
            issues.append(
                BriefingContentIssue(
                    "global_visible_text_typo_artifact",
                    f"Known visible typo survived to final HTML: {marker!r}",
                    section="visible_body",
                    excerpt=marker,
                )
            )
    return BriefingContentQualityResult(ok=len(issues) == 0, issues=issues, warnings=[])


# ---------------------------------------------------------------------------
# Korea post-render visible QA (real owner-review send path)

# Judgment-label taxonomy allowed inside the "오늘 국내에서 움직인 것" signal
# strip — mirrors the keysuri_judgment.label contract in the generation prompt.
# Anything else in a chip (e.g. a truncated headline fragment like
# "삼성전자, '나를 아는 AI'가") is a rendering defect that must block SMTP.
KOREA_SIGNAL_BADGE_ALLOWED_LABELS: Tuple[str, ...] = (
    "기회",
    "관찰",
    "경계",
    "활용 후보",
    "사업 신호",
    "리스크 신호",
    "추가 확인 필요",
    "과장 주의",
)

KOREA_DOMESTIC_STRIP_HEADING = "오늘 국내에서 움직인 것"
_KOREA_TOP5_HEADING = "국내 테크 TOP 5"

# Legacy fixed "lesson board" sentences that used to render verbatim every day
# in the "오늘 신호가 내려오는 곳" section. build_korea_market_impact_summary now
# generates day-specific rows; if this many of the old fixed sentences still
# reach the final HTML, some path regressed to the static board.
KOREA_STATIC_LESSON_LEGACY_SENTENCES: Tuple[str, ...] = (
    "반도체·AI·인프라 뉴스는 장비, 소재, 부품, 전력, 냉각처럼 주변 업종으로 내려오는 순서를 보겠습니다.",
    "대기업 투자와 정책 신호는 협력사, 소부장, 패키징, 테스트 물량으로 번질 때 체감 영향이 커집니다.",
    "데이터센터·공장·정책 사업은 지역 채용, 교육, 공사, 유지보수 수요로 내려오는지 확인하겠습니다.",
    "수혜주를 단정하기보다 관련 업종의 계약, 비용 구조, 도입 일정이 숫자로 확인되는지 보겠습니다.",
    "AI·클라우드·정책 변화는 외주 단가, SaaS 비용, 교육 수요, 중소기업 도입 일정으로 먼저 체감될 수 있습니다.",
)
KOREA_STATIC_LESSON_SENTENCE_THRESHOLD = 3

# Imperative ending glued to a bare "확인" — the "…비교 분석하세요 확인" /
# "…주시하세요 확인" double-ending artifact. The (?![가-힣]) guard requires the
# trailing 확인 token to stand alone, so a new sentence starting with 확인
# after a normal imperative ("…하세요 확인이 필요한 부분은 …") does not match.
_KOREA_DOUBLE_ENDING_RE = re.compile(r"[가-힣]+(?:하세요|하십시오)\s+확인(?![가-힣])")

_KOREA_HOLD_FIELD_MARKER = "아직 단정하지 말 것"
_KOREA_JUDGMENT_MARKER = "키수리 판단"
_KOREA_HOLD_DUP_MIN_CHARS = 25

# Event words that must never appear in the synthesis sections (시장 판단 이후)
# unless today's TOP5 cards themselves mention them — the production defect was
# "엔비디아 방한 이슈" injected as background knowledge into the market frame
# while no TOP5 article said anything about a visit. Narrow, literal tokens
# only: this is a safety net, not the fix (generation-side grounding is).
_KOREA_UNGROUNDED_EVENT_TOKENS: Tuple[str, ...] = ("방한",)
_KOREA_SYNTHESIS_HEADING = "키수리의 시장 판단"


def _korea_ungrounded_event_tokens(plain: str) -> List[str]:
    """Event tokens present after the synthesis heading but absent from the
    TOP5 cards region (which contains today's headlines/summaries/sources)."""
    cards_start = plain.find(_KOREA_TOP5_HEADING)
    synthesis_start = plain.find(_KOREA_SYNTHESIS_HEADING)
    if cards_start < 0 or synthesis_start < 0 or synthesis_start <= cards_start:
        return []
    cards = plain[cards_start:synthesis_start]
    synthesis = plain[synthesis_start:]
    return [
        token
        for token in _KOREA_UNGROUNDED_EVENT_TOKENS
        if token in synthesis and token not in cards
    ]


def _korea_signal_strip_chip_texts(html: str) -> List[str]:
    """Chip texts inside the Korea domestic signal strip of the FINAL HTML.

    Works for both the Gmail email template (inline-styled <span> chips) and
    the premium preview template (<span class="signal-chip">): every <span>
    between the strip heading and the TOP5 heading is a chip.
    """
    idx = html.find(KOREA_DOMESTIC_STRIP_HEADING)
    if idx < 0:
        return []
    window = html[idx:]
    end = window.find(_KOREA_TOP5_HEADING)
    if end > 0:
        window = window[:end]
    chips: List[str] = []
    for m in re.finditer(r"<span[^>]*>(.*?)</span>", window, flags=re.S):
        text = re.sub(r"\s+", " ", _plain_text(m.group(1))).strip()
        if text:
            chips.append(text)
    return chips


def _norm_visible_ko(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text or "")


def _korea_hold_duplicate_judgment_excerpts(plain: str) -> List[str]:
    """Hold-field texts that duplicate the same card's '키수리 판단' explanation.

    Scans the plain text in document order: for each "아직 단정하지 말 것"
    occurrence, compares its text against the nearest preceding "키수리 판단"
    explanation. Near-duplicates count too (the hold field is clamped to 90
    chars, so it may be a prefix of the judgment sentence rather than equal).
    """
    out: List[str] = []
    for m in re.finditer(_KOREA_HOLD_FIELD_MARKER, plain):
        seg = plain[m.end(): m.end() + 400].lstrip(" :：")
        stop = len(seg)
        for stop_marker in ("출처", _KOREA_JUDGMENT_MARKER, "내일 먼저 볼 것"):
            j = seg.find(stop_marker)
            if 0 <= j < stop:
                stop = j
        hold_text = seg[:stop].strip()

        j_idx = plain.rfind(_KOREA_JUDGMENT_MARKER, 0, m.start())
        if j_idx < 0:
            continue
        j_seg = plain[j_idx + len(_KOREA_JUDGMENT_MARKER): j_idx + len(_KOREA_JUDGMENT_MARKER) + 500]
        j_stop = len(j_seg)
        for stop_marker in ("내일 먼저 볼 것", _KOREA_HOLD_FIELD_MARKER, "출처"):
            j2 = j_seg.find(stop_marker)
            if 0 <= j2 < j_stop:
                j_stop = j2
        judgment_text = j_seg[:j_stop].strip()

        norm_hold = _norm_visible_ko(hold_text)
        norm_judgment = _norm_visible_ko(judgment_text)
        if (
            len(norm_hold) >= _KOREA_HOLD_DUP_MIN_CHARS
            and norm_judgment
            and (norm_hold in norm_judgment or norm_judgment in norm_hold)
        ):
            out.append(hold_text[:100])
    return out


def validate_korea_post_render_visible_quality(html: str) -> BriefingContentQualityResult:
    """Korea Tech post-render QA on the FINAL owner-review email HTML.

    Runs after rendering and before SMTP dispatch — mirrors
    validate_global_post_render_visible_quality but targets the four visible
    defects observed in the Korea Tech production owner-review email:
    headline fragments in the signal-strip badge row, "…하세요 확인" double
    endings, hold fields copy-pasted from the judgment sentence, and the
    static daily lesson board rendered verbatim.
    """
    issues: List[BriefingContentIssue] = []
    plain = _plain_text(html)

    for chip in _korea_signal_strip_chip_texts(html):
        if chip not in KOREA_SIGNAL_BADGE_ALLOWED_LABELS:
            issues.append(
                BriefingContentIssue(
                    "korea_signal_distribution_badge_fragment",
                    f"Signal strip badge is not an allowed judgment label: {chip!r}",
                    section="signal_summary",
                    excerpt=chip[:100],
                )
            )

    for m in _KOREA_DOUBLE_ENDING_RE.finditer(plain):
        issues.append(
            BriefingContentIssue(
                "korea_visible_text_double_ending_artifact",
                f"Imperative ending directly followed by bare '확인' (double ending): {m.group(0)!r}",
                section="visible_body",
                excerpt=m.group(0),
            )
        )

    for excerpt in _korea_hold_duplicate_judgment_excerpts(plain):
        issues.append(
            BriefingContentIssue(
                "korea_hold_field_duplicate_judgment",
                "'아직 단정하지 말 것' field duplicates the same card's '키수리 판단' text",
                section="top5",
                excerpt=excerpt,
            )
        )

    for token in _korea_ungrounded_event_tokens(plain):
        issues.append(
            BriefingContentIssue(
                "korea_ungrounded_event_context",
                f"Synthesis section mentions event {token!r} that no TOP5 card contains "
                "(background knowledge injected as today's signal)",
                section="market_judgment",
                excerpt=token,
            )
        )

    static_hits = [s for s in KOREA_STATIC_LESSON_LEGACY_SENTENCES if s in plain]
    if len(static_hits) >= KOREA_STATIC_LESSON_SENTENCE_THRESHOLD:
        issues.append(
            BriefingContentIssue(
                "korea_static_lesson_section_overused",
                f"{len(static_hits)} legacy fixed lesson sentences rendered verbatim — "
                "the market-impact section regressed to the static daily board",
                section="market_impact_summary",
                excerpt=static_hits[0][:100],
            )
        )

    return BriefingContentQualityResult(ok=len(issues) == 0, issues=issues, warnings=[])
