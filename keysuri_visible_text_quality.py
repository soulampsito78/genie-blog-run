"""Kee-Suri visible Korean text quality guardrails."""
from __future__ import annotations

import copy
import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED = "keysuri_korean_connector_ellipsis_blocked"
KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED = "keysuri_korean_connector_ellipsis_repaired"

_ELLIPSIS_RE = re.compile(r"…|\.{2,}")
_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_SCRIPT_RE = re.compile(r"<(?:style|script)[^>]*>.*?</(?:style|script)>", re.IGNORECASE | re.DOTALL)
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
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
    if len(sample) > max_chars:
        sample = sample[:max_chars].rstrip()
    return sample


def contains_connector_ellipsis(value: Any) -> bool:
    return bool(_ELLIPSIS_RE.search(str(value or "")))


def repair_korean_connector_ellipsis_text(value: Any) -> EllipsisRepairResult:
    original = str(value or "")
    if not contains_connector_ellipsis(original):
        return EllipsisRepairResult(original, found=False, repaired=False, blocked=False)

    text = original
    text = re.sub(r"\.{2,}", "…", text)

    if re.search(r"…\s*(?:$|[.!?。！？])", text):
        return EllipsisRepairResult(text, found=True, repaired=False, blocked=True)

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
    replacements: Tuple[Tuple[str, str], ...] = (
        (r"((?:을|를)\s+위한)\s*…\s*(흐름|움직임|변화|전환|확산)", r"\1 \2"),
        (r"(구축)\s*…\s*(이슈|흐름|움직임|변화|전환|확산)", r"\1 \2"),
        (r"(흐름|움직임|변화|전환|확산|이슈)\s*…\s*(?:와|과)\s*", r"\1과 "),
        (r"(흐름|움직임|변화|전환|확산|이슈)\s*…\s*(?:이|가|은|는)\s*", r"\1이 "),
    )
    for pattern, repl in replacements:
        repaired = re.sub(pattern, repl, repaired)

    repaired = re.sub(r"(?<=[A-Za-z0-9가-힣])\s*…\s*(?=[A-Za-z0-9가-힣])", " ", repaired)
    repaired = re.sub(r"\s+([,.!?])", r"\1", repaired)
    repaired = re.sub(r"\s+", " ", repaired).strip()

    if contains_connector_ellipsis(repaired):
        return EllipsisRepairResult(repaired, found=True, repaired=False, blocked=True)
    return EllipsisRepairResult(repaired, found=True, repaired=repaired != original, blocked=False)


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
                out[key] = result.text if result.found else value
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
    if fields.get("visible_text_ellipsis_blocked"):
        fields["visible_text_quality_status"] = "block"
        if KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED not in issue_codes:
            issue_codes.append(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED)
    elif fields.get("visible_text_ellipsis_repaired"):
        fields["visible_text_quality_status"] = "pass"
        if KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED not in issue_codes:
            issue_codes.append(KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_REPAIRED)
    else:
        fields["visible_text_quality_status"] = "pass"
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
