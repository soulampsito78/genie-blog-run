"""Kee-Suri briefing content quality gate (visible Korean text only)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

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

ALLOWED_JUDGMENT_LABELS: Tuple[str, ...] = (
    "기회",
    "관찰",
    "경계",
    "활용 후보",
    "사업 신호",
    "리스크 신호",
    "추가 확인 필요",
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


def _english_rss_leak(text: str) -> bool:
    if not text.strip():
        return False
    if _is_mostly_english(text):
        return True
    if re.search(r"\b(RSS|feed|published|announcement|update)\b", text, flags=re.IGNORECASE):
        if _hangul_ratio(text) < 0.4:
            return True
    return False


def validate_briefing_content_gate(html: str) -> BriefingContentQualityResult:
    """Validate visible Korean briefing substance — not HTML structure."""
    issues: List[BriefingContentIssue] = []
    warnings: List[BriefingContentIssue] = []
    region = _visible_body_region(html)

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

    owner_angles: List[str] = []
    why_now_texts: List[str] = []
    thin_detail_count = 0
    insufficient_marked = 0

    for idx, block in enumerate(item_blocks, start=1):
        headline_m = re.search(r'<h3[^>]*>\d+\.\s*(.*?)</h3>', block, flags=re.DOTALL)
        headline = re.sub(r"<[^>]+>", "", headline_m.group(1)).strip() if headline_m else ""
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

        if what and _sentence_count(what) < 2:
            thin_detail_count += 1
            issues.append(
                BriefingContentIssue(
                    "item_detail_too_thin",
                    f"TOP item {idx} '무슨 일이 있었나' needs at least 2 sentences",
                    section="top5",
                    item_index=idx,
                    excerpt=what[:100],
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

        if "원문 상세 확인 필요" in block or "추가 확인 필요" in block:
            insufficient_marked += 1
        elif what and _sentence_count(what) < 2:
            issues.append(
                BriefingContentIssue(
                    "source_detail_insufficient",
                    f"TOP item {idx} thin detail without '원문 상세 확인 필요' marker",
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

    if deep_text:
        if "주인님" not in deep_text:
            issues.append(
                BriefingContentIssue(
                    "weak_deep_dive",
                    "Deep-dive must include Korean operator/founder relevance (주인님)",
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
        if any(m in checkpoint for m in RECAP_CHECKPOINT_MARKERS) and "?" not in checkpoint:
            issues.append(
                BriefingContentIssue(
                    "weak_checkpoint",
                    "One-line checkpoint reads as recap, not decision cue",
                    section="one_line_checkpoint",
                    excerpt=checkpoint[:100],
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

    src_section = ""
    src_m = re.search(r'id="closing-section"[^>]*>(.*?)(?=<section|<div class="rights|<div id="rights|$)', html, flags=re.DOTALL)
    if not src_m:
        src_m = re.search(r'id="closing-sources"[^>]*>(.*?)(?=<section|<div|$)', html, flags=re.DOTALL)
    if src_m:
        src_section = src_m.group(1)
    urls = URL_PATTERN.findall(src_section)
    if len(urls) < 1:
        issues.append(
            BriefingContentIssue(
                "source_list_incomplete",
                "Closing source list must include at least one URL",
                section="closing_sources",
            )
        )

    ok = len(issues) == 0
    return BriefingContentQualityResult(ok=ok, issues=issues, warnings=warnings)
