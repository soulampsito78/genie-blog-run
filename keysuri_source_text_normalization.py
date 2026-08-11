"""Deterministic normalization for text entering Kee-Suri from public feeds.

Only publisher UI chrome with an unambiguous structural signature is removed.
Editorial ellipses and ambiguous truncation remain available to the visible-text
validator instead of being silently rewritten at ingestion time.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Tuple


FEED_READ_MORE_MARKER = "FEED_READ_MORE_MARKER"
LEGIT_SENTENCE_FINAL = "LEGIT_SENTENCE_FINAL"
LEGIT_QUOTED = "LEGIT_QUOTED"
DASH_CONNECTOR = "DASH_CONNECTOR"
DELIMITER_ELLIPSIS_TOKEN = "DELIMITER_ELLIPSIS_TOKEN"
TOKEN_ELLIPSIS_DELIMITER = "TOKEN_ELLIPSIS_DELIMITER"
TRUE_TRUNCATION = "TRUE_TRUNCATION"
MALFORMED_DOT_RUN = "MALFORMED_DOT_RUN"
AMBIGUOUS_UNSAFE = "AMBIGUOUS_UNSAFE"

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_INVISIBLE_SPACE_RE = re.compile(r"[\u00a0\u200b\u200c\u200d\ufeff]")
_ELLIPSIS_TOKEN = r"(?:…|\.{2,}|\u2025|\u22ef)"
_FEED_READ_MORE_TAIL_RE = re.compile(
    rf"\s*(?:\[\s*{_ELLIPSIS_TOKEN}\s*\]|【\s*{_ELLIPSIS_TOKEN}\s*】)\s*$",
    re.IGNORECASE,
)
_TEXT_READ_MORE_TAIL_RE = re.compile(
    r"\s*(?:read\s+more|continue\s+reading|더\s*보기|계속\s*읽기)\s*[›»>→]*\s*$",
    re.IGNORECASE,
)
_MALFORMED_DOT_RE = re.compile(
    r"(?:\.\.(?!\.)|\.{4,}|\.\s*…|…\s*\.|…{2,}|\u2025|\u22ef)"
)
_DASH_CONNECTOR_RE = re.compile(r"[\u2013\u2014\u2015\u2212-]\s*" + _ELLIPSIS_TOKEN)
_DELIM_LEFT_RE = re.compile(r"['\"‘’“”\)\]\}」』〉》]\s*" + _ELLIPSIS_TOKEN + r"\s*[\w가-힣]")
_DELIM_RIGHT_RE = re.compile(r"[\w가-힣]\s*" + _ELLIPSIS_TOKEN + r"\s*['\"‘’“”\(\[\{「『〈《]")
_QUOTED_RE = re.compile(
    rf"(?:['\"‘“「『〈《][^'\"’”」』〉》]{{1,240}}{_ELLIPSIS_TOKEN}[^'\"’”」』〉》]{{0,240}}['\"’”」』〉》])"
)
_PAREN_ELLIPSIS_RE = re.compile(rf"[\(（]\s*{_ELLIPSIS_TOKEN}\s*[\)）]")
_TRAILING_ELLIPSIS_RE = re.compile(rf"{_ELLIPSIS_TOKEN}\s*$")
_DANGLING_TRAILING_TOKENS = frozenset(
    {
        "and", "or", "with", "to", "for", "of", "the", "a", "an",
        "및", "또는", "위한", "통해", "따라", "대해", "관한",
    }
)


@dataclass(frozen=True)
class SourceTextNormalizationResult:
    text: str
    changed: bool
    provenance_classes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changed": self.changed,
            "provenance_classes": list(self.provenance_classes),
        }


def _unique(values: Iterable[str]) -> Tuple[str, ...]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return tuple(out)


def classify_ellipsis_structure(value: Any) -> Tuple[str, ...]:
    """Classify ellipsis structure without deciding editorial intent globally."""
    text = html.unescape(str(value or ""))
    classes: List[str] = []
    if _FEED_READ_MORE_TAIL_RE.search(text):
        classes.append(FEED_READ_MORE_MARKER)
    if _MALFORMED_DOT_RE.search(text):
        classes.append(MALFORMED_DOT_RUN)
    if _DASH_CONNECTOR_RE.search(text):
        classes.append(DASH_CONNECTOR)
    if _DELIM_LEFT_RE.search(text):
        classes.append(DELIMITER_ELLIPSIS_TOKEN)
    if _DELIM_RIGHT_RE.search(text):
        classes.append(TOKEN_ELLIPSIS_DELIMITER)
    if _QUOTED_RE.search(text):
        classes.append(LEGIT_QUOTED)
    if _PAREN_ELLIPSIS_RE.search(text):
        classes.append(AMBIGUOUS_UNSAFE)
    if _TRAILING_ELLIPSIS_RE.search(text) and FEED_READ_MORE_MARKER not in classes:
        # A terminal ellipsis is editorial unless the visible prefix itself ends
        # in a known dangling connective. Feed chrome was handled above.
        prefix = _TRAILING_ELLIPSIS_RE.sub("", text).rstrip()
        last_token_match = re.search(r"([A-Za-z가-힣]+)\s*$", prefix)
        last_token = last_token_match.group(1).lower() if last_token_match else ""
        if last_token in _DANGLING_TRAILING_TOKENS:
            classes.append(TRUE_TRUNCATION)
        else:
            classes.append(LEGIT_SENTENCE_FINAL)
    if re.search(_ELLIPSIS_TOKEN, text) and not classes:
        classes.append(AMBIGUOUS_UNSAFE)
    return _unique(classes)


def normalize_feed_source_text(value: Any, *, strip_markup: bool = True) -> SourceTextNormalizationResult:
    original = str(value or "")
    text = html.unescape(original)
    if strip_markup:
        text = _TAG_RE.sub(" ", text)
    text = _INVISIBLE_SPACE_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    classes = list(classify_ellipsis_structure(text))

    # Square/CJK bracket ellipsis and explicit read-more labels are publisher
    # interface chrome when terminal. Parenthetical/quoted ellipses are retained.
    if _FEED_READ_MORE_TAIL_RE.search(text):
        text = _FEED_READ_MORE_TAIL_RE.sub("", text).rstrip()
    if _TEXT_READ_MORE_TAIL_RE.search(text):
        text = _TEXT_READ_MORE_TAIL_RE.sub("", text).rstrip(" -:|·")
        classes.append(FEED_READ_MORE_MARKER)
    text = _SPACE_RE.sub(" ", text).strip()
    return SourceTextNormalizationResult(
        text=text,
        changed=text != original,
        provenance_classes=_unique(classes),
    )


def normalize_keysuri_source_pack(source_pack: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a normalized copy plus bounded provenance diagnostics."""
    import copy

    out = copy.deepcopy(dict(source_pack))
    changed_fields: List[Dict[str, Any]] = []
    for collection, fields in (
        ("sources", ("title", "snippet")),
        ("claims", ("statement", "headline", "summary", "why_it_matters", "business_implication")),
    ):
        rows = out.get(collection)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in fields:
                if not isinstance(row.get(field), str):
                    continue
                result = normalize_feed_source_text(row[field])
                if result.changed:
                    row[field] = result.text
                    if len(changed_fields) < 24:
                        changed_fields.append(
                            {
                                "collection": collection,
                                "index": index,
                                "field": field,
                                "source_id": row.get("source_id") or row.get("claim_id"),
                                "provenance_classes": list(result.provenance_classes),
                            }
                        )
    out["source_text_normalization"] = {
        "version": "keysuri_source_text_v1",
        "changed_field_count": len(changed_fields),
        "changed_fields": changed_fields,
    }
    return out
