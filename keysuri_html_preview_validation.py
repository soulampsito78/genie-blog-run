"""Kee-Suri HTML preview contract-validation (read-only).

This module validates Kee-Suri HTML preview files written for owner review under:

    output/keysuri_preview/html_test/

It checks contract-validation structure (sections, TOP 5 sources, deep-dive layers,
rights policy, negative guards, and Korea 18:30 placement when explicitly in scope).

Scope boundaries:
- Not a production renderer validator.
- Not a Genie / Today_Geenee JSON or delivery validator.
- Read-only: does not mutate HTML or inject validation boxes.
- Does not call image API, scheduler, or email systems.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from keysuri_news_contract import SECTION_TOP5_GLOBAL, SECTION_TOP5_KOREA
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
)

CheckStatus = Literal["PASS", "FAIL"]
OptionalCheckStatus = Literal["PASS", "FAIL", "SKIP"]
Severity = Literal["error", "warning"]

HTML_TEST_DIR_PARTS: Tuple[str, ...] = ("output", "keysuri_preview", "html_test")
TIMESTAMP_FILENAME_RE = re.compile(r"_\d{8}_\d{6}\.html$", re.IGNORECASE)
TIMESTAMP_SUFFIX_STEM_RE = re.compile(r"_\d{8}_\d{6}$", re.IGNORECASE)
KOREA_1830_FILENAME_TOKENS: Tuple[str, ...] = (
    "korea_1830",
    "korea-1830",
    "korea_18_30",
    "korea-18-30",
)
KOREA_1830_SLOT_HTML_RE = re.compile(r"slot\s*:\s*18\s*:?\s*30", re.IGNORECASE)
PROGRAM_KOREA = "keysuri_korea_tech"
PROGRAM_GLOBAL = "keysuri_global_tech"

IDENTITY_TITLE = "테크 비서 키수리"
RIGHTS_LINE_1 = "Copyright Ⓒ MirAI:ON. All rights reserved."
RIGHTS_LINE_2 = "무단 전재, 재배포 및 AI학습 이용 절대 금지"

KOREA_LAYER_LABELS = (
    "물리·인프라 병목",
    "규제·주권·조달 압력",
    "워크플로·락인",
)

VERIFICATION_MARKERS = (
    "sample_only",
    "not_verified",
    "not verified",
    "preview_only",
    "unverified",
)

HASHTAG_NEGATIVE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(?i)<section[^>]*hashtag", "hashtag_section"),
    (r"(?i)class=[\"']hashtag-list[\"']", "hashtag_list_class"),
    (r"<h2[^>]*>\s*해시태그\s*</h2>", "hashtag_ko_label"),
    (r"#키수리", "hashtag_keysuri"),
)

PRODUCTION_NEGATIVE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(?<![Nn]o )테크 앵커", "forbidden_tech_anchor"),
    (r"(?<![Nn]o )뉴스 앵커", "forbidden_news_anchor"),
    (r"Today_Geenee", "forbidden_today_geenee"),
    (r"Tomorrow_Geenee", "forbidden_tomorrow_geenee"),
    (r"tomorrow_genie", "forbidden_tomorrow_genie"),
    (r"(?<![:\w])production_ready\s*:\s*true", "production_ready_true"),
    (r"\"production_ready\"\s*:\s*true", "production_ready_json_true"),
    (r"(?<![:\w])scheduler_ready\s*:\s*true", "scheduler_ready_true"),
    (r"\"scheduler_ready\"\s*:\s*true", "scheduler_ready_json_true"),
    (r"(?<![:\w])email_ready\s*:\s*true", "email_ready_true"),
    (r"\"email_ready\"\s*:\s*true", "email_ready_json_true"),
    (r"static/email/", "static_email_path"),
    (r"image_canary/[^\"'\s>]+\.(?:jpg|jpeg|png|webp)[^\"'\s>]*(?:approved|production)", "image_api_production_asset"),
)

DEEP_DIVE_DENSITY_CHAR_THRESHOLD = 280


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = "error"


@dataclass
class ValidationResult:
    validation_status: CheckStatus
    validation_timestamp: str
    required_sections: CheckStatus
    top5_sources: CheckStatus
    deep_dive_readability: CheckStatus
    rights_policy: CheckStatus
    no_hashtags: CheckStatus
    no_production_implication: CheckStatus
    warm_close_order: OptionalCheckStatus
    claimed_pass_consistency: OptionalCheckStatus
    file_path: str = ""
    program_id: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)

    def is_pass(self) -> bool:
        return self.validation_status == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def _path_under_html_test_dir(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    for idx in range(len(parts) - len(HTML_TEST_DIR_PARTS) + 1):
        if tuple(parts[idx : idx + len(HTML_TEST_DIR_PARTS)]) == HTML_TEST_DIR_PARTS:
            return True
    return False


def _filename_stem_without_timestamp(path: Path) -> str:
    """Return lowercase filename stem with trailing _YYYYMMDD_HHMMSS removed."""
    return TIMESTAMP_SUFFIX_STEM_RE.sub("", path.stem.lower())


def _filename_has_korea_1830_token(path: Path) -> bool:
    stem = _filename_stem_without_timestamp(path)
    return any(token in stem for token in KOREA_1830_FILENAME_TOKENS)


def _html_has_korea_1830_slot(html: str) -> bool:
    return bool(KOREA_1830_SLOT_HTML_RE.search(html))


def _infer_program_id(path: Path, html: str, program_id: Optional[str]) -> str:
    if program_id in (PROGRAM_KOREA, PROGRAM_GLOBAL):
        return program_id

    stem = _filename_stem_without_timestamp(path)
    if _filename_has_korea_1830_token(path):
        return PROGRAM_KOREA
    if "global" in stem or "1230" in stem:
        return PROGRAM_GLOBAL
    if "korea" in stem:
        return PROGRAM_KOREA

    if SECTION_TOP5_KOREA in html:
        return PROGRAM_KOREA
    if SECTION_TOP5_GLOBAL in html:
        return PROGRAM_GLOBAL
    return ""


def _is_korea_1830_preview(path: Path, program_id: str, html: str) -> bool:
    """True only when filename or metadata explicitly indicates Korea 18:30 slot."""
    if _filename_has_korea_1830_token(path):
        return True
    if program_id == PROGRAM_KOREA and _html_has_korea_1830_slot(html):
        return True
    return False


def _find_anchor_index(html: str, *needles: str) -> Optional[int]:
    for needle in needles:
        idx = html.find(needle)
        if idx >= 0:
            return idx
    return None


def _extract_top_item_blocks(html: str) -> List[str]:
    blocks: List[str] = []
    for rank in range(1, 6):
        pattern = rf'<article\b[^>]*\bdata-top-item="{rank}"[^>]*>(.*?)</article>'
        match = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            blocks.append(match.group(1))
    if len(blocks) == 5:
        return blocks

    blocks = re.findall(r'<article\b[^>]*\bclass="[^"]*\btop-item\b[^"]*"[^>]*>(.*?)</article>', html, flags=re.DOTALL | re.IGNORECASE)
    return blocks


def _item_has_source_fields(item_html: str) -> bool:
    has_name = bool(re.search(r"(출처명|source_name)\s*[:：]", item_html, flags=re.IGNORECASE))
    has_url = bool(re.search(r"https?://[^\s<\"']+", item_html, flags=re.IGNORECASE))
    has_verification = bool(
        re.search(r"(검증 상태|verification_status)\s*[:：]", item_html, flags=re.IGNORECASE)
        and any(marker in item_html.lower() for marker in VERIFICATION_MARKERS)
    )
    return has_name and has_url and has_verification


def _rights_policy_present(html: str) -> bool:
    normalized = _norm_text(html)
    return RIGHTS_LINE_1 in normalized and RIGHTS_LINE_2 in normalized


def _deep_dive_region(html: str) -> str:
    match = re.search(
        rf"{re.escape(SECTION_DEEP_DIVE)}(.*?)(?={re.escape(SECTION_ONE_LINE)}|<section|<footer|$)",
        html,
        flags=re.DOTALL,
    )
    if match:
        return match.group(0)
    idx = html.find(SECTION_DEEP_DIVE)
    if idx < 0:
        return ""
    return html[idx : idx + 4000]


def _deep_dive_is_dense(region: str) -> bool:
    if not region:
        return False
    text_only = re.sub(r"<[^>]+>", " ", region)
    text_only = _norm_text(text_only)
    if len(text_only) >= DEEP_DIVE_DENSITY_CHAR_THRESHOLD:
        return True
    paragraph_count = len(re.findall(r"<p\b", region, flags=re.IGNORECASE))
    return paragraph_count >= 4


def _deep_dive_has_layer_structure(region: str) -> bool:
    if not region:
        return False

    layer_cards = len(re.findall(r'class="[^"]*\bdeep-layer\b', region, flags=re.IGNORECASE))
    if layer_cards >= 3:
        return True

    numbered_headings = 0
    for marker in ("deep-layer-number", "deep-layer-title"):
        numbered_headings = max(
            numbered_headings,
            len(re.findall(rf'class="[^"]*\b{marker}\b', region, flags=re.IGNORECASE)),
        )
    if numbered_headings >= 3:
        return True

    if all(label in region for label in KOREA_LAYER_LABELS):
        return True

    numbered_lines = len(re.findall(r">\s*[123]\s*[\./、]", region))
    return numbered_lines >= 3


def _deep_dive_is_single_dense_block(region: str) -> bool:
    if not region:
        return False
    layer_markers = len(re.findall(r"deep-layer|deep_layer|layer-card", region, flags=re.IGNORECASE))
    if layer_markers > 0:
        return False
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", region, flags=re.DOTALL | re.IGNORECASE)
    if len(paragraphs) <= 1:
        return len(_norm_text(region)) >= DEEP_DIVE_DENSITY_CHAR_THRESHOLD
    long_paragraphs = [p for p in paragraphs if len(_norm_text(re.sub(r"<[^>]+>", " ", p))) > 180]
    return len(long_paragraphs) >= 2 and layer_markers == 0


def _claimed_validation_status(html: str) -> Optional[str]:
    match = re.search(r"validation_status\s*:\s*(PASS|FAIL)", html, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _validate_file_path(path: Path, issues: List[ValidationIssue]) -> bool:
    ok = True
    if not path.exists() or not path.is_file():
        issues.append(ValidationIssue("file_missing", f"File not found: {path}"))
        return False

    if path.stat().st_size == 0:
        issues.append(ValidationIssue("file_empty", "HTML file is empty"))
        ok = False

    if not _path_under_html_test_dir(path.resolve()):
        issues.append(
            ValidationIssue(
                "file_path_not_html_test_dir",
                "Path must be under output/keysuri_preview/html_test/",
            )
        )
        ok = False

    if not TIMESTAMP_FILENAME_RE.search(path.name):
        issues.append(
            ValidationIssue(
                "filename_timestamp_missing",
                "Filename must include _YYYYMMDD_HHMMSS.html timestamp suffix",
            )
        )
        ok = False

    return ok


def _validate_basic_html(html: str, issues: List[ValidationIssue]) -> bool:
    ok = True
    lower = html.lower()
    for token, code in (
        ("<!doctype html", "missing_doctype"),
        ("<html", "missing_html_tag"),
        ("<head", "missing_head_tag"),
        ("<body", "missing_body_tag"),
    ):
        if token not in lower:
            issues.append(ValidationIssue(code, f"Missing basic HTML structure: {token}"))
            ok = False
    return ok


def _validate_required_sections(
    html: str,
    *,
    korea_1830: bool,
    program_id: str,
    issues: List[ValidationIssue],
) -> bool:
    ok = True
    required_all: List[Tuple[str, Sequence[str]]] = [
        ("preview_metadata", ("Preview metadata", 'id="preview-metadata"', "preview metadata")),
        ("identity_title", (IDENTITY_TITLE,)),
        ("deep_dive_section", (SECTION_DEEP_DIVE,)),
        ("one_line_checkpoint", (SECTION_ONE_LINE,)),
        ("closing_section", (SECTION_CLOSING,)),
        ("operation_metadata", ("Operation metadata", 'id="operation-metadata"')),
        ("compliance_checklist", ("Contract compliance checklist", 'id="compliance-checklist"')),
        ("validation_result_box", ("Validation result", 'id="validation-result-box"')),
    ]

    expected_top5 = SECTION_TOP5_KOREA if program_id == PROGRAM_KOREA else SECTION_TOP5_GLOBAL
    if program_id not in (PROGRAM_KOREA, PROGRAM_GLOBAL):
        expected_top5 = ""
        if SECTION_TOP5_KOREA in html:
            expected_top5 = SECTION_TOP5_KOREA
        elif SECTION_TOP5_GLOBAL in html:
            expected_top5 = SECTION_TOP5_GLOBAL

    if expected_top5:
        required_all.append(("top5_heading", (expected_top5,)))
    else:
        required_all.append(("top5_heading", (SECTION_TOP5_KOREA, SECTION_TOP5_GLOBAL)))

    if korea_1830:
        required_all.extend(
            [
                ("bottom_shot_placeholder", ("bottom-shot", 'id="bottom-shot-placeholder"', "18:30 bottom-shot")),
                (
                    "warm_close_section",
                    ("국내 18:30 따뜻한 마무리", "오늘도 수고하셨습니다"),
                ),
            ]
        )

    for code, needles in required_all:
        if code == "top5_heading" and len(needles) == 2:
            if not any(needle in html for needle in needles):
                issues.append(ValidationIssue(code, "Missing TOP 5 section heading"))
                ok = False
            continue
        if not any(needle in html for needle in needles):
            issues.append(ValidationIssue(code, f"Missing required section marker: {needles[0]!r}"))
            ok = False

    return ok


def _validate_top5_sources(html: str, issues: List[ValidationIssue]) -> bool:
    blocks = _extract_top_item_blocks(html)
    if len(blocks) < 5:
        issues.append(
            ValidationIssue(
                "top5_item_count_invalid",
                f"Expected 5 TOP items, found {len(blocks)}",
            )
        )
        return False

    ok = True
    for idx, block in enumerate(blocks, start=1):
        if not _item_has_source_fields(block):
            issues.append(
                ValidationIssue(
                    "top5_item_missing_source_fields",
                    f"TOP item {idx} missing source_name/URL/verification_status markers",
                )
            )
            ok = False
    return ok


def _validate_deep_dive_readability(html: str, issues: List[ValidationIssue]) -> bool:
    if SECTION_DEEP_DIVE not in html:
        issues.append(ValidationIssue("deep_dive_missing", f"Missing {SECTION_DEEP_DIVE!r}"))
        return False

    region = _deep_dive_region(html)
    if not _deep_dive_is_dense(region):
        return True

    if _deep_dive_has_layer_structure(region):
        return True

    if _deep_dive_is_single_dense_block(region):
        issues.append(
            ValidationIssue(
                "deep_dive_dense_without_layers",
                "Dense deep-dive content lacks 1/2/3 layer or card structure",
            )
        )
        return False

    issues.append(
        ValidationIssue(
            "deep_dive_layer_structure_missing",
            "Deep-dive section missing numbered layer structure",
        )
    )
    return False


def _validate_rights_policy(html: str, issues: List[ValidationIssue]) -> bool:
    if _rights_policy_present(html):
        return True
    issues.append(
        ValidationIssue(
            "rights_policy_missing",
            "Missing exact MirAI:ON rights policy footer text",
        )
    )
    return False


def _scan_negative_patterns(
    html: str,
    patterns: Sequence[Tuple[str, str]],
    issues: List[ValidationIssue],
) -> bool:
    scan_html = _strip_html_comments(html)
    ok = True
    for pattern, code in patterns:
        if re.search(pattern, scan_html):
            issues.append(ValidationIssue(code, f"Forbidden preview marker matched: {code}"))
            ok = False
    return ok


def _validate_warm_close_order(html: str, issues: List[ValidationIssue]) -> bool:
    anchors: List[Tuple[str, Sequence[str]]] = [
        ("one_line_checkpoint", (SECTION_ONE_LINE,)),
        ("bottom_shot", ("bottom-shot", 'id="bottom-shot-placeholder"', "18:30 bottom-shot")),
        ("warm_close", ("국내 18:30 따뜻한 마무리", "오늘도 수고하셨습니다")),
        ("closing_section", (SECTION_CLOSING,)),
        ("rights_policy", (RIGHTS_LINE_1,)),
        ("operation_metadata", ("Operation metadata", 'id="operation-metadata"')),
        ("validation_result", ("Validation result", 'id="validation-result-box"')),
    ]

    indices: List[Tuple[str, int]] = []
    for name, needles in anchors:
        idx = _find_anchor_index(html, *needles)
        if idx is None:
            issues.append(ValidationIssue("warm_close_anchor_missing", f"Missing order anchor: {name}"))
            return False
        indices.append((name, idx))

    ok = True
    for (prev_name, prev_idx), (next_name, next_idx) in zip(indices, indices[1:]):
        if prev_idx >= next_idx:
            issues.append(
                ValidationIssue(
                    "warm_close_order_violation",
                    f"Section order violation: {prev_name!r} must appear before {next_name!r}",
                )
            )
            ok = False
    return ok


def _aggregate_status(checks: Sequence[CheckStatus]) -> CheckStatus:
    return "FAIL" if any(status == "FAIL" for status in checks) else "PASS"


def validate_keysuri_html_preview(
    path: str,
    *,
    program_id: str | None = None,
) -> ValidationResult:
    """Validate a Kee-Suri HTML preview file. Read-only — does not mutate HTML."""
    resolved = Path(path).expanduser()
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    issues: List[ValidationIssue] = []

    file_ok = _validate_file_path(resolved, issues)
    html = ""
    if file_ok:
        html = resolved.read_text(encoding="utf-8")
        _validate_basic_html(html, issues)

    inferred_program = _infer_program_id(resolved, html, program_id)
    korea_1830 = _is_korea_1830_preview(resolved, inferred_program, html) if html else False

    required_sections: CheckStatus = "FAIL"
    top5_sources: CheckStatus = "FAIL"
    deep_dive_readability: CheckStatus = "FAIL"
    rights_policy: CheckStatus = "FAIL"
    no_hashtags: CheckStatus = "FAIL"
    no_production_implication: CheckStatus = "FAIL"
    warm_close_order: OptionalCheckStatus = "SKIP"
    claimed_pass_consistency: OptionalCheckStatus = "SKIP"

    if html:
        required_sections = "PASS" if _validate_required_sections(
            html,
            korea_1830=korea_1830,
            program_id=inferred_program,
            issues=issues,
        ) else "FAIL"

        top5_sources = "PASS" if _validate_top5_sources(html, issues) else "FAIL"
        deep_dive_readability = "PASS" if _validate_deep_dive_readability(html, issues) else "FAIL"
        rights_policy = "PASS" if _validate_rights_policy(html, issues) else "FAIL"

        hashtag_ok = _scan_negative_patterns(html, HASHTAG_NEGATIVE_PATTERNS, issues)
        no_hashtags = "PASS" if hashtag_ok else "FAIL"

        production_ok = _scan_negative_patterns(html, PRODUCTION_NEGATIVE_PATTERNS, issues)
        no_production_implication = "PASS" if production_ok else "FAIL"

        if korea_1830:
            warm_close_order = "PASS" if _validate_warm_close_order(html, issues) else "FAIL"

    sub_checks: List[CheckStatus] = [
        required_sections,
        top5_sources,
        deep_dive_readability,
        rights_policy,
        no_hashtags,
        no_production_implication,
    ]
    if warm_close_order != "SKIP":
        sub_checks.append(warm_close_order)  # type: ignore[arg-type]

    actual_pass = file_ok and html and _aggregate_status(sub_checks) == "PASS"

    claimed = _claimed_validation_status(html) if html else None
    if claimed == "PASS":
        if actual_pass:
            claimed_pass_consistency = "PASS"
        else:
            claimed_pass_consistency = "FAIL"
            issues.append(
                ValidationIssue(
                    "claimed_pass_mismatch",
                    "HTML claims validation_status: PASS but validator checks failed",
                )
            )
    elif claimed == "FAIL":
        if actual_pass:
            claimed_pass_consistency = "PASS"
            issues.append(
                ValidationIssue(
                    "claimed_fail_but_actual_pass",
                    "HTML claims validation_status: FAIL but validator checks passed",
                    severity="warning",
                )
            )
        else:
            claimed_pass_consistency = "PASS"

    validation_status: CheckStatus = "PASS" if actual_pass and claimed_pass_consistency != "FAIL" else "FAIL"

    return ValidationResult(
        validation_status=validation_status,
        validation_timestamp=timestamp,
        required_sections=required_sections,
        top5_sources=top5_sources,
        deep_dive_readability=deep_dive_readability,
        rights_policy=rights_policy,
        no_hashtags=no_hashtags,
        no_production_implication=no_production_implication,
        warm_close_order=warm_close_order,
        claimed_pass_consistency=claimed_pass_consistency,
        file_path=str(resolved.resolve()),
        program_id=inferred_program,
        issues=issues,
    )
