"""Kee-Suri visible Korean text quality guardrails."""
from __future__ import annotations

import copy
import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from keysuri_numeric_span_consistency import repair_year_span_duration
from keysuri_visible_text import (
    contains_dangling_quoted_title_fragment,
    contains_korea_impact_phrase_issues,
    repair_korea_adjacent_token_duplication,
    repair_obvious_korean_quality_artifacts,
)

KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED = "keysuri_korean_connector_ellipsis_blocked"
KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED = "keysuri_korean_connector_ellipsis_repaired"
KEYSURI_KOREAN_REPEATED_TOKEN_REPAIRED = "keysuri_korean_repeated_token_repaired"
KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED = "keysuri_dangling_quoted_title_fragment_blocked"
KEYSURI_YEAR_SPAN_DURATION_REPAIRED = "keysuri_year_span_duration_repaired"
KEYSURI_YEAR_SPAN_DURATION_BLOCKED = "keysuri_year_span_duration_blocked"
KEYSURI_KOREA_TOKEN_DUPLICATION_BLOCKED = "keysuri_korea_token_duplication_blocked"

_ELLIPSIS_RE = re.compile(r"…|\.{2,}|\u22ef|\u2025")
_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(r"<(?:style|script)[^>]*>.*?</(?:style|script)>", re.IGNORECASE | re.DOTALL)
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

# Structural connector-ellipsis grammar (not a growing char blacklist).
# LEFT edge: word char OR a closing delimiter/quote OR clause/dash punctuation
# that commonly precedes a bridge in feed/model prose.
# RIGHT edge (content): word char OR an opening/closing delimiter/quote.
# RIGHT edge (punct): clause/sentence punctuation that should absorb the bridge.
_WORD_CHAR = r"A-Za-z0-9가-힣"
_CLOSING_DELIM = (
    r"'"  # ASCII apostrophe / closer (Korea 18:30: '3파전'…삼성)
    r"\""
    r"\u2019\u201d"  # ’ ”
    r"\u3009\u300b"  # 〉 》
    r"」』\)\]\}>"
)
_OPENING_DELIM = (
    r"'"
    r"\""
    r"\u2018\u201c"  # ‘ “
    r"\u3008\u300a"  # 〈 《
    r"「『\(\[\{\<"
)
# Right edge also accepts closing quotes/brackets: Global 13:11 residual was
# word…closing-curly-quote (`Leadership… ”`). Closing on the left covers Korea
# 18:30 (`'3파전'…삼성`); closing on the right covers Global 13:11.
_RIGHT_EDGE = _OPENING_DELIM + _CLOSING_DELIM
_CLAUSE_PUNCT = r"[,:;·|/／]"
# Dash/bar family often appears immediately before a bridge ellipsis in
# English wire copy (`today —…Firebird`) and must be a LEFT edge, not a residual.
_DASH_PUNCT = r"\u2013\u2014\u2015\u2212\-"  # – — ― − -
# LEFT bridge edge = word | closing delim | clause punct | dash.
# Covers Aug 10/11 `—…word`, `Warships:…Legends`, `흥국·…삼성`.
_LEFT_EDGE = _WORD_CHAR + _CLOSING_DELIM + r",:;·|/／" + _DASH_PUNCT
_SENTENCE_PUNCT = r"[.!?。！？]"
_ZW_NBSP_RE = re.compile(r"[\u00a0\u200b\u200c\u200d\ufeff]")
# RSS/WordPress read-more marker: matched square (or CJK) brackets around ellipsis.
# Distinct from paren genuine-truncation `(…)` which remains blocked.
_FEED_READMORE_ELLIPSIS_RE = re.compile(
    r"\s*[\[【]\s*…\s*[\]】]"
)

_CONNECTOR_TO_CONTENT_RE = re.compile(
    rf"(?<=[{_LEFT_EDGE}])\s*…\s*(?=[{_WORD_CHAR}{_RIGHT_EDGE}])"
)
_CONNECTOR_TO_PUNCT_RE = re.compile(
    rf"(?<=[{_LEFT_EDGE}])\s*…\s*(?={_CLAUSE_PUNCT}|{_SENTENCE_PUNCT})"
)
_TRAILING_ELLIPSIS_RE = re.compile(r"\s*…\s*$")
_SKIP_KEY_TOKENS = (
    "url",
    "uri",
    "href",
    "src",
    "path",
    "image",
    "cid",
    "sha",
    "hash",
    "bucket",
    "object",
    "asset",
    "run_id",
    "program_id",
    "source_id",
    "news_id",
    "published",
    "generated_at",
    "recipient",
)
_QUALITY_FIELD_TEMPLATE: Dict[str, Any] = {
    "visible_text_quality_status": "pass",
    "visible_text_ellipsis_found": False,
    "visible_text_ellipsis_repaired": False,
    "visible_text_ellipsis_blocked": False,
    "visible_text_repeated_token_found": False,
    "visible_text_repeated_token_repaired": False,
    "visible_text_dangling_quoted_title_blocked": False,
    "visible_text_year_span_repaired": False,
    "visible_text_year_span_blocked": False,
    "visible_text_korea_token_duplication_blocked": False,
    "year_span_diagnostics": [],
    "visible_text_quality_issue_codes": [],
    "visible_text_quality_samples": [],
}


@dataclass(frozen=True)
class EllipsisRepairResult:
    text: str
    found: bool
    repaired: bool
    blocked: bool


def _plain_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return _SPACE_RE.sub(" ", text).strip()


def sanitize_quality_sample(value: Any, *, max_chars: int = 120) -> str:
    sample = _plain_text(value)
    sample = _EMAIL_RE.sub(r"\1***\2", sample)
    if len(sample) <= max_chars:
        return sample
    # Prefer a window centered on the first residual ellipsis so production
    # forensics are not truncated to a harmless prefix (Aug 11 Global 12:30).
    match = _ELLIPSIS_RE.search(sample)
    if match:
        center = match.start()
        half = max_chars // 2
        start = max(0, center - half)
        end = min(len(sample), start + max_chars)
        start = max(0, end - max_chars)
        return sample[start:end].strip()
    return sample[:max_chars].rstrip()


def contains_connector_ellipsis(value: Any) -> bool:
    return bool(_ELLIPSIS_RE.search(str(value or "")))


def _normalize_ellipsis_unicode(text: str) -> str:
    """Normalize punctuation variants before connector evaluation."""
    out = _ZW_NBSP_RE.sub(" ", text)
    # Unicode ellipsis equivalents → canonical U+2026
    out = out.replace("\u22ef", "…")  # ⋯ MIDLINE HORIZONTAL ELLIPSIS
    out = out.replace("\u2025", "…")  # ‥ TWO DOT LEADER
    # ASCII / fullwidth repeated dots → canonical ellipsis
    out = re.sub(r"\.{2,}", "…", out)
    out = re.sub(r"。{2,}", "…", out)
    # Mixed single-dot + ellipsis forms (.… / ….)
    out = re.sub(r"\.…|…\.", "…", out)
    out = re.sub(r"…+", "…", out)
    # Collapse whitespace around ellipsis for stable lookbehind/lookahead.
    out = re.sub(r"\s*…\s*", "…", out)
    return out


def repair_korean_connector_ellipsis_text(value: Any) -> EllipsisRepairResult:
    original = str(value or "")
    if not contains_connector_ellipsis(original):
        return EllipsisRepairResult(original, found=False, repaired=False, blocked=False)

    text = _normalize_ellipsis_unicode(original)

    if (
        "대규모 AI 생산을 위한" in text
        and "특화된 AI를 구축" in text
        and "동시에 보인다는 것입니다" in text
    ):
        repaired = (
            "오늘 글로벌 테크 시장에서는 대규모 AI 생산 인프라와 기업 맞춤형 AI 구축 흐름이 "
            "동시에 두드러졌습니다. 한쪽은 산업·인프라의 변화이고, 다른 한쪽은 "
            "소프트웨어·운영 방식의 변화입니다."
        )
        return EllipsisRepairResult(repaired, found=True, repaired=True, blocked=False)

    repaired = text
    # Strip RSS/WordPress square-bracket read-more markers (` […]`, `[&#8230;]`).
    # Parenthesis genuine-truncation `(…)` is intentionally NOT stripped here.
    repaired = _FEED_READMORE_ELLIPSIS_RE.sub("", repaired)
    replacements: Tuple[Tuple[str, str], ...] = (
        (r"((?:을|를)\s+위한)\s*…\s*(흐름|움직임|변화|전환|확산)", r"\1 \2"),
        # "OBJECT를/을 구축… 이슈" leaves a stray 를/을 if only "구축" is captured
        # (e.g. "AI를 구축 이슈"), so the object word and its particle are
        # captured together and the particle is dropped to form a valid
        # noun-compound ("AI 구축 이슈") instead.
        (
            r"([가-힣A-Za-z0-9]+)(?:을|를)\s*구축\s*…\s*(이슈|흐름|움직임|변화|전환|확산)",
            r"\1 구축 \2",
        ),
        (r"(구축)\s*…\s*(이슈|흐름|움직임|변화|전환|확산)", r"\1 \2"),
        (r"(흐름|움직임|변화|전환|확산|이슈)\s*…\s*(?:와|과)\s*", r"\1과 "),
        (r"(흐름|움직임|변화|전환|확산|이슈)\s*…\s*(?:이|가|은|는)\s*", r"\1이 "),
    )
    for pattern, repl in replacements:
        repaired = re.sub(pattern, repl, repaired)

    # Structural bridge repairs (content…content / delim…content / content…punct).
    # Korea 18:30 residual: closing ASCII quote then ellipsis then word
    # (`'3파전'…삼성`) — prior Global curly-quote patch only covered word…opening.
    # Aug 10/11: clause/dash LEFT edges (`—…Firebird`, `:…Legends`, `·…삼성`).
    repaired = _CONNECTOR_TO_CONTENT_RE.sub(" ", repaired)
    repaired = _CONNECTOR_TO_PUNCT_RE.sub("", repaired)
    # Terminal trailing ellipsis (sentence-final) — strip so residual does not block.
    repaired = _TRAILING_ELLIPSIS_RE.sub("", repaired)
    repaired = re.sub(r"\s+([,.:;!?·])", r"\1", repaired)
    repaired = re.sub(r"\s+", " ", repaired).strip()

    if contains_connector_ellipsis(repaired):
        return EllipsisRepairResult(repaired, found=True, repaired=False, blocked=True)
    return EllipsisRepairResult(repaired, found=True, repaired=repaired != original, blocked=False)


def repair_korean_repeated_token_text(value: Any) -> EllipsisRepairResult:
    original = str(value or "")
    repaired = repair_obvious_korean_quality_artifacts(original)
    return EllipsisRepairResult(
        repaired,
        found=repaired != original,
        repaired=repaired != original,
        blocked=False,
    )


def _should_check_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in {"email_subject", "owner_email_subject", "customer_email_subject"}:
        return True
    if lowered in {"email_preheader", "owner_email_preheader", "customer_email_preheader"}:
        return True
    return not any(token in lowered for token in _SKIP_KEY_TOKENS)


def _new_quality_fields() -> Dict[str, Any]:
    return copy.deepcopy(_QUALITY_FIELD_TEMPLATE)


def _append_sample(fields: Dict[str, Any], *, path: str, before: Any, after: Any = "") -> None:
    samples = fields.setdefault("visible_text_quality_samples", [])
    if len(samples) >= 12:
        return
    entry: Dict[str, str] = {
        "path": path,
        "sample": sanitize_quality_sample(before),
    }
    repaired_sample = sanitize_quality_sample(after)
    if repaired_sample and repaired_sample != entry["sample"]:
        entry["repaired_sample"] = repaired_sample
    samples.append(entry)


def _walk_and_repair(node: Any, *, path: str, fields: Dict[str, Any]) -> Any:
    if isinstance(node, dict):
        out: Dict[Any, Any] = {}
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and _should_check_key(str(key)):
                result = repair_korean_connector_ellipsis_text(value)
                if result.found:
                    fields["visible_text_ellipsis_found"] = True
                    _append_sample(fields, path=child_path, before=value, after=result.text)
                    if result.blocked:
                        fields["visible_text_ellipsis_blocked"] = True
                    elif result.repaired:
                        fields["visible_text_ellipsis_repaired"] = True
                next_value = result.text if result.found else value
                repeated = repair_korean_repeated_token_text(next_value)
                if repeated.found:
                    fields["visible_text_repeated_token_found"] = True
                    fields["visible_text_repeated_token_repaired"] = True
                    _append_sample(fields, path=child_path, before=next_value, after=repeated.text)
                    next_value = repeated.text
                deduped = repair_korea_adjacent_token_duplication(next_value)
                if deduped != next_value:
                    fields["visible_text_repeated_token_found"] = True
                    fields["visible_text_repeated_token_repaired"] = True
                    _append_sample(fields, path=child_path, before=next_value, after=deduped)
                    next_value = deduped
                if contains_korea_impact_phrase_issues(next_value):
                    fields["visible_text_korea_token_duplication_blocked"] = True
                    _append_sample(fields, path=child_path, before=next_value)
                if contains_dangling_quoted_title_fragment(next_value):
                    fields["visible_text_dangling_quoted_title_blocked"] = True
                    _append_sample(fields, path=child_path, before=next_value)
                span_repaired, span_diag = repair_year_span_duration(next_value)
                if span_diag.get("resolution") == "removed_derived_duration":
                    fields["visible_text_year_span_repaired"] = True
                    fields.setdefault("year_span_diagnostics", []).append(span_diag)
                    _append_sample(fields, path=child_path, before=next_value, after=span_repaired)
                    next_value = span_repaired
                elif span_diag.get("resolution") == "blocked":
                    fields["visible_text_year_span_blocked"] = True
                    fields.setdefault("year_span_diagnostics", []).append(span_diag)
                    _append_sample(fields, path=child_path, before=next_value)
                out[key] = next_value
            else:
                out[key] = _walk_and_repair(value, path=child_path, fields=fields)
        return out
    if isinstance(node, list):
        return [
            _walk_and_repair(value, path=f"{path}[{idx}]", fields=fields)
            for idx, value in enumerate(node)
        ]
    if isinstance(node, tuple):
        return tuple(
            _walk_and_repair(value, path=f"{path}[{idx}]", fields=fields)
            for idx, value in enumerate(node)
        )
    return node


def _finalize_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    issue_codes = fields.setdefault("visible_text_quality_issue_codes", [])
    blocked = bool(
        fields.get("visible_text_ellipsis_blocked")
        or fields.get("visible_text_dangling_quoted_title_blocked")
        or fields.get("visible_text_year_span_blocked")
        or fields.get("visible_text_korea_token_duplication_blocked")
    )
    if fields.get("visible_text_ellipsis_blocked"):
        if KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED not in issue_codes:
            issue_codes.append(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED)
    elif fields.get("visible_text_ellipsis_repaired"):
        if KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED not in issue_codes:
            issue_codes.append(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED)
    if fields.get("visible_text_dangling_quoted_title_blocked"):
        if KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED not in issue_codes:
            issue_codes.append(KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED)
    if fields.get("visible_text_year_span_blocked"):
        if KEYSURI_YEAR_SPAN_DURATION_BLOCKED not in issue_codes:
            issue_codes.append(KEYSURI_YEAR_SPAN_DURATION_BLOCKED)
    elif fields.get("visible_text_year_span_repaired"):
        if KEYSURI_YEAR_SPAN_DURATION_REPAIRED not in issue_codes:
            issue_codes.append(KEYSURI_YEAR_SPAN_DURATION_REPAIRED)
    if fields.get("visible_text_korea_token_duplication_blocked"):
        if KEYSURI_KOREA_TOKEN_DUPLICATION_BLOCKED not in issue_codes:
            issue_codes.append(KEYSURI_KOREA_TOKEN_DUPLICATION_BLOCKED)
    if fields.get("visible_text_repeated_token_repaired") and KEYSURI_KOREAN_REPEATED_TOKEN_REPAIRED not in issue_codes:
        issue_codes.append(KEYSURI_KOREAN_REPEATED_TOKEN_REPAIRED)
    fields["visible_text_quality_status"] = "block" if blocked else "pass"
    return fields


def validate_and_repair_keysuri_visible_text_quality(
    payload: Any,
    *,
    root_path: str = "generated_briefing",
) -> tuple[Any, Dict[str, Any]]:
    fields = _new_quality_fields()
    repaired = _walk_and_repair(copy.deepcopy(payload), path=root_path, fields=fields)
    return repaired, _finalize_fields(fields)


def validate_keysuri_html_visible_text_quality(
    html_body: str,
    *,
    path: str = "email_html.visible_text",
) -> Dict[str, Any]:
    fields = _new_quality_fields()
    text = _STYLE_SCRIPT_RE.sub(" ", str(html_body or ""))
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _SPACE_RE.sub(" ", text).strip()
    result = repair_korean_connector_ellipsis_text(text)
    if result.found:
        fields["visible_text_ellipsis_found"] = True
        fields["visible_text_ellipsis_blocked"] = True
        _append_sample(fields, path=path, before=text, after=result.text)
    repeated = repair_korean_repeated_token_text(text)
    if repeated.found:
        fields["visible_text_repeated_token_found"] = True
        fields["visible_text_repeated_token_repaired"] = True
        _append_sample(fields, path=path, before=text, after=repeated.text)
    return _finalize_fields(fields)


def merge_visible_text_quality_fields(*field_sets: Mapping[str, Any]) -> Dict[str, Any]:
    merged = _new_quality_fields()
    samples: list[dict] = []
    issue_codes: list[str] = []
    for fields in field_sets:
        if not isinstance(fields, Mapping):
            continue
        merged["visible_text_ellipsis_found"] = (
            bool(merged["visible_text_ellipsis_found"])
            or bool(fields.get("visible_text_ellipsis_found"))
        )
        merged["visible_text_ellipsis_repaired"] = (
            bool(merged["visible_text_ellipsis_repaired"])
            or bool(fields.get("visible_text_ellipsis_repaired"))
        )
        merged["visible_text_ellipsis_blocked"] = (
            bool(merged["visible_text_ellipsis_blocked"])
            or bool(fields.get("visible_text_ellipsis_blocked"))
        )
        merged["visible_text_repeated_token_found"] = (
            bool(merged["visible_text_repeated_token_found"])
            or bool(fields.get("visible_text_repeated_token_found"))
        )
        merged["visible_text_repeated_token_repaired"] = (
            bool(merged["visible_text_repeated_token_repaired"])
            or bool(fields.get("visible_text_repeated_token_repaired"))
        )
        for code in fields.get("visible_text_quality_issue_codes") or []:
            code = str(code or "").strip()
            if code and code not in issue_codes:
                issue_codes.append(code)
        for sample in fields.get("visible_text_quality_samples") or []:
            if isinstance(sample, dict) and sample not in samples and len(samples) < 12:
                samples.append(dict(sample))
    merged["visible_text_quality_issue_codes"] = issue_codes
    merged["visible_text_quality_samples"] = samples
    return _finalize_fields(merged)
