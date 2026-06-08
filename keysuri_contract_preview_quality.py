"""Visible-body quality gates for Kee-Suri premium contract-preview HTML."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

INTERNAL_VISIBLE_LABELS: Tuple[str, ...] = (
    "category:",
    "why_it_matters:",
    "business_implication:",
    "confidence:",
    "source_ids:",
    "source_gate_result",
    "prompt_status",
    "operational_status",
    "generated_status",
    "output_contract",
    "generation_pending",
    "source-led cards only",
    "Source Gate / TOP 5 Selection Audit",
    "Review Status & Guardrails",
    "Active scheduler (GENIE)",
)

FORBIDDEN_PHRASES: Tuple[str, ...] = (
    "귀사",
    "오늘 브리핑이 도움이 되셨기를",
    "다음 브리핑에서 더 유익한 정보로 찾아뵙",
    "다음 브리핑에서 찾아뵙",
)

GENERIC_CLOSING_PHRASES: Tuple[str, ...] = (
    "도움이 되셨기를 바랍니다",
    "도움이 되기를 바랍니다",
    "더 유익한 정보로 찾아뵙",
    "추가 문의사항은 언제든",
)

REQUIRED_ITEM_LABELS: Tuple[str, ...] = (
    "무슨 일이 있었나",
    "왜 지금 중요한가",
    "주인님 관점",
    "키수리 판단",
    "다음 확인 포인트",
)

PREMIUM_CSS_MARKERS: Tuple[str, ...] = (
    "premium-briefing",
    "premium-hero",
    "briefing-card",
    "owner-angle-block",
    "judgment-badge",
)

STAGED_PLACEHOLDER_MARKERS: Tuple[str, ...] = (
    "스테이징",
    "staged",
    "Staged",
    "sample",
    "Sample",
    "Infrastructure signal",
    "Platform control shift",
    "Workflow leverage",
    "global layer one",
    "global layer two",
    "global layer three",
    "source-led cards only",
    "generation_pending",
    "Example Corp",
    "example.com",
    "global-t0-ai-official",
    "global-t2-market-wire",
    "DESIGN FIXTURE",
)


@dataclass
class VisibleBodyIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass
class VisibleBodyQualityResult:
    ok: bool
    issues: List[VisibleBodyIssue] = field(default_factory=list)
    warnings: List[VisibleBodyIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [{"code": i.code, "message": i.message, "severity": i.severity} for i in self.issues],
            "warnings": [{"code": w.code, "message": w.message, "severity": w.severity} for w in self.warnings],
        }


def _visible_body_region(html: str) -> str:
    idx = html.find('id="operation-metadata"')
    if idx >= 0:
        return html[:idx]
    idx = html.find("Operation metadata")
    if idx >= 0:
        return html[:idx]
    return html


def _extract_top_item_blocks(html: str) -> List[str]:
    blocks: List[str] = []
    for rank in range(1, 6):
        pattern = rf'<article\b[^>]*\bdata-top-item="{rank}"[^>]*>(.*?)</article>'
        match = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            blocks.append(match.group(1))
    return blocks


def _hangul_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha() or ("\uac00" <= ch <= "\ud7a3")]
    if not letters:
        return 0.0
    hangul = sum(1 for ch in letters if "\uac00" <= ch <= "\ud7a3")
    return hangul / len(letters)


def _is_mostly_english(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return _hangul_ratio(stripped) < 0.15 and bool(re.search(r"[A-Za-z]{4,}", stripped))


def _sentence_count(text: str) -> int:
    stripped = re.sub(r"<[^>]+>", " ", text)
    parts = re.split(r"[.!?…]\s+", stripped.strip())
    return len([p for p in parts if len(p.strip()) > 8])


def _block_text(item_html: str, label: str) -> str:
    pattern = rf'<h4[^>]*>{re.escape(label)}</h4>\s*<p[^>]*>(.*?)</p>'
    match = re.search(pattern, item_html, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


def _operation_before_briefing(html: str) -> bool:
    op = html.find('id="operation-metadata"')
    top5 = html.find('id="top5-section"')
    if op < 0 or top5 < 0:
        return False
    return op < top5


def validate_contract_preview_hero_layout_gate(html: str) -> VisibleBodyQualityResult:
    """Hero image frame/layout gate — catches thumbnail card and over-framed hero."""
    issues: List[VisibleBodyIssue] = []
    warnings: List[VisibleBodyIssue] = []

    if "105936" in html or "keysuri_global_canary_20260605_105936" in html:
        issues.append(
            VisibleBodyIssue(
                "hero_role_asset_mismatch",
                "korea_bottom 105936 asset must not appear in global preview HTML",
            )
        )

    style_match = re.search(r"<style>(.*?)</style>", html, flags=re.DOTALL | re.IGNORECASE)
    if not style_match:
        return VisibleBodyQualityResult(ok=len(issues) == 0, issues=issues, warnings=warnings)

    style = style_match.group(1)
    style_compact = re.sub(r"\s+", "", style)

    if re.search(r"hero-image-card[^}]*max-width:\s*(2\d\d|3\d\d|4\d\d)px", style):
        issues.append(
            VisibleBodyIssue(
                "hero_image_too_small",
                "Hero image max-width under 520px on desktop — thumbnail-like layout",
            )
        )
    if "flex:01 38%" in style_compact or "max-width:300px" in style_compact:
        issues.append(
            VisibleBodyIssue(
                "hero_thumbnail_layout",
                "Two-column right-side thumbnail hero layout detected",
            )
        )
    if re.search(r"hero-image-card[^}]*border:\s*1px", style) and "border:0" not in style_compact:
        if "box-shadow:var(--shadow-card)" in style_compact:
            issues.append(
                VisibleBodyIssue(
                    "hero_frame_too_heavy",
                    "Heavy card border/shadow on hero image frame",
                )
            )
    if re.search(r"hero-image-card[^}]*padding:\s*(1[6-9]|[2-9]\d)px", style):
        issues.append(
            VisibleBodyIssue(
                "hero_excessive_padding",
                "Excessive padding around hero image card shrinks visible image",
            )
        )
    if re.search(r"\.top-shot-hero\{[^}]*object-fit:\s*cover", style) and "object-fit:contain" not in style:
        issues.append(
            VisibleBodyIssue(
                "hero_crop_without_approval",
                "Hero uses object-fit:cover — may crop face/body without approval",
            )
        )

    return VisibleBodyQualityResult(ok=len(issues) == 0, issues=issues, warnings=warnings)


def validate_contract_preview_structural_gate(html: str) -> VisibleBodyQualityResult:
    """Structural / HTML quality only — not briefing substance or visual identity."""
    issues: List[VisibleBodyIssue] = []
    warnings: List[VisibleBodyIssue] = []
    region = _visible_body_region(html)

    hero_layout = validate_contract_preview_hero_layout_gate(html)
    issues.extend(hero_layout.issues)
    warnings.extend(hero_layout.warnings)

    if 'id="top-shot-image"' not in html:
        issues.append(VisibleBodyIssue("hero_image_missing", "Top-shot hero section required"))
    elif 'class="top-shot-hero"' not in html and "hero-fallback" not in html:
        issues.append(VisibleBodyIssue("hero_image_missing", "Top-shot hero image or fallback required"))

    img_src_match = re.search(
        r'id="top-shot-image"[^>]*>[\s\S]*?<img[^>]+src="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    if img_src_match:
        src = img_src_match.group(1)
        if "../" in src or src.startswith("image_canary/"):
            issues.append(
                VisibleBodyIssue(
                    "hero_image_relative_path",
                    f"Hero image must not use fragile relative path: {src!r}",
                )
            )
        elif not (
            src.startswith("data:image/")
            or src.startswith("cid:")
            or src.startswith("https://")
            or src.startswith("http://")
        ):
            issues.append(
                VisibleBodyIssue(
                    "hero_image_src_not_embed_ready",
                    f"Hero src must be data URI, cid, or absolute URL: {src!r}",
                )
            )

    if 'id="premium-hero"' not in html:
        issues.append(VisibleBodyIssue("premium_hero_missing", "Premium hero header section missing"))

    for marker in PREMIUM_CSS_MARKERS:
        if marker not in html:
            issues.append(VisibleBodyIssue("premium_design_missing", f"Premium CSS marker missing: {marker}"))
            break

    if "주인님" not in region:
        issues.append(VisibleBodyIssue("owner_address_missing", 'Visible body must address "주인님"'))

    for phrase in FORBIDDEN_PHRASES:
        if phrase in region:
            issues.append(VisibleBodyIssue("forbidden_phrase", f"Forbidden phrase: {phrase!r}"))

    if _operation_before_briefing(html):
        issues.append(VisibleBodyIssue("operation_metadata_order", "Operation metadata appears before briefing content"))

    if 'id="opening-lead"' not in html:
        issues.append(VisibleBodyIssue("opening_lead_missing", "Opening lead section missing"))

    item_blocks = _extract_top_item_blocks(html)
    if len(item_blocks) < 5:
        issues.append(VisibleBodyIssue("top5_item_count", f"Expected 5 briefing cards, found {len(item_blocks)}"))
    else:
        for idx, block in enumerate(item_blocks, start=1):
            for label in REQUIRED_ITEM_LABELS:
                if label == "키수리 판단":
                    if "judgment-row" not in block and "judgment-badge" not in block:
                        issues.append(
                            VisibleBodyIssue(
                                "item_subsection_missing",
                                f"TOP item {idx} missing subsection: {label}",
                            )
                        )
                elif label not in block:
                    issues.append(
                        VisibleBodyIssue(
                            "item_subsection_missing",
                            f"TOP item {idx} missing subsection: {label}",
                        )
                    )

    for label in INTERNAL_VISIBLE_LABELS:
        if label in region:
            issues.append(VisibleBodyIssue("internal_label_exposed", f"Internal label exposed: {label!r}"))

    for marker in STAGED_PLACEHOLDER_MARKERS:
        if marker in region:
            issues.append(
                VisibleBodyIssue(
                    "staged_placeholder_leak",
                    f"Staged/sample placeholder leaked into visible body: {marker!r}",
                )
            )
            break

    if "Copyright Ⓒ MirAI:ON. All rights reserved." not in html:
        issues.append(VisibleBodyIssue("rights_footer_missing", "MirAI:ON rights footer missing"))

    ok = len(issues) == 0
    return VisibleBodyQualityResult(ok=ok, issues=issues, warnings=warnings)


def validate_contract_preview_visible_body(html: str) -> VisibleBodyQualityResult:
    """Backward-compatible combined gate (structural + content briefing)."""
    from keysuri_briefing_content_quality import validate_briefing_content_gate

    structural = validate_contract_preview_structural_gate(html)
    content = validate_briefing_content_gate(html)

    issues = list(structural.issues)
    warnings = list(structural.warnings)
    for i in content.issues:
        issues.append(VisibleBodyIssue(i.code, i.message, severity=i.severity))
    for w in content.warnings:
        warnings.append(VisibleBodyIssue(w.code, w.message, severity=w.severity))

    lead_match = re.search(
        r'id="opening-lead"[^>]*>.*?<p[^>]*>(.*?)</p>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if lead_match:
        lead_text = re.sub(r"<[^>]+>", "", lead_match.group(1)).strip()
        if _sentence_count(lead_text) < 2:
            issues.append(VisibleBodyIssue("opening_lead_too_short", "Opening lead needs at least 2 sentences"))
        if "주인님" not in lead_text:
            warnings.append(
                VisibleBodyIssue(
                    "opening_lead_no_juinim",
                    "Opening lead should address 주인님",
                    severity="warning",
                )
            )

    ok = len(issues) == 0
    return VisibleBodyQualityResult(ok=ok, issues=issues, warnings=warnings)
