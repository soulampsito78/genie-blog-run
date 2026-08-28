"""The one boundary every customer-visible KeeSuri article field must cross.

On 2026-08-28 the 12:30 Global model contract collapsed, the single corrective
call failed, and the scaffold completed the output with
``copy.deepcopy(prompt_input["top_5_news"])``. That structure is the *evidence*
pack: its ``headline`` / ``summary`` / ``why_it_matters`` carry the raw English
RSS text the claims were built from. Promoting it to the generated briefing
turned evidence into reader prose, and five cards shipped to owner review made
of English source text.

The fix is not another detector downstream. It is that a reader field can only
be produced here, from two separated inputs:

* **evidence** — the selected item's factual identity, and the raw source text
  behind it. Identity is bindable. The raw text is not: it is what the prose is
  *about*, never the prose itself.
* **authored** — Korean prose the model wrote for that same article.

Anything that cannot be bound from authored prose becomes an explicit,
reader-safe "not prepared" marker and an issue code. A scaffold may restore
structure; it can never restore prose, so a run whose model contributed nothing
now says so on its face instead of wearing its own source pack.

Every path — first parse, corrective generation, scaffold completion, repair,
reissue, degraded candidate, manual run — terminates here. There is no second
way to reach the renderer.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Issue codes this boundary can raise.
READER_PROSE_MISSING = "keysuri_reader_prose_missing"
READER_PROSE_WAS_SOURCE_TEXT = "keysuri_reader_prose_was_source_text"
READER_PROSE_NOT_KOREAN = "keysuri_reader_prose_not_korean"
READER_IDENTITY_UNMATCHED = "keysuri_reader_identity_unmatched"
READER_SURFACE_ENFORCED = "keysuri_reader_surface_enforced"

#: Shown when a reader field could not be produced. Reader-safe Korean, and
#: deliberately not mistakable for editorial prose.
UNAVAILABLE_MARKER = "(본문 준비되지 않음 — 운영자 확인 필요)"

#: Factual identity. Bound from evidence, immutable, never model-editable.
IDENTITY_FIELDS: Tuple[str, ...] = (
    "news_id",
    "source_ids",
    "source_url",
    "source_name",
    "canonical_headline",
)

#: Reader-facing prose. Bound only from authored model output.
PROSE_FIELDS: Tuple[str, ...] = (
    "headline",
    "summary",
    "why_it_matters",
    "business_implication",
    "next_watch",
)

#: Prose fields a briefing must carry for a card to read as a briefing at all.
REQUIRED_PROSE_FIELDS: Tuple[str, ...] = ("headline", "summary", "why_it_matters")

_LATIN_RUN_RE = re.compile(r"(?:[A-Za-z][A-Za-z0-9'’\-]*\s+){5,}[A-Za-z][A-Za-z0-9'’\-]*")
_HANGUL_RE = re.compile(r"[가-힣]")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ReaderArticle:
    """One customer-visible article, with identity and prose kept apart."""

    news_id: str
    canonical_url: str
    source_id: str
    source_name: str
    canonical_headline: str
    display_headline: str
    what_happened: str
    why_now: str
    business_implication: str
    next_watch: str
    category: str
    uncertainty: str
    source_attribution: str
    rank: int = 0
    issues: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def reader_ready(self) -> bool:
        """Whether every required reader field carries real authored prose."""
        return not any(
            getattr(self, name) == UNAVAILABLE_MARKER
            for name in ("display_headline", "what_happened", "why_now")
        )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    """Comparison form: case, spacing and punctuation width folded away."""
    text = unicodedata.normalize("NFKC", _text(value)).lower()
    text = re.sub(r"[^\w\s]", "", text)
    return _WS_RE.sub(" ", text).strip()


def _looks_like_raw_source_prose(text: str) -> bool:
    """A long unbroken run of Latin words in a field that should read as Korean.

    This is a typing rule, not a phrase list: a Korean explanatory field whose
    content is a paragraph of English is the source's text, whatever it says.
    A quoted product name or a short English clause inside Korean prose stays
    well under the run length.
    """
    if _HANGUL_RE.search(text):
        # Korean prose that quotes an English title is still Korean prose.
        return False
    return bool(_LATIN_RUN_RE.search(text)) or len(text.split()) >= 6


def _evidence_texts(evidence: Mapping[str, Any]) -> List[str]:
    """Every raw string this item's evidence carries, in comparison form."""
    out: List[str] = []
    for key in ("headline", "summary", "statement", "why_it_matters", "title", "description"):
        value = _normalized(evidence.get(key))
        if value:
            out.append(value)
    return out


def _bind_prose(
    field_name: str,
    authored: Mapping[str, Any],
    evidence_forms: Sequence[str],
) -> Tuple[str, Optional[str]]:
    """One reader field, or the unavailable marker plus the reason it failed."""
    value = _text(authored.get(field_name))
    if not value:
        return UNAVAILABLE_MARKER, READER_PROSE_MISSING

    normalized = _normalized(value)
    if normalized and normalized in evidence_forms:
        # The scaffold's signature: the field *is* the evidence, byte for byte.
        return UNAVAILABLE_MARKER, READER_PROSE_WAS_SOURCE_TEXT
    for form in evidence_forms:
        # A prefix graft (statement[:120]) is the same failure, truncated.
        if form and normalized and (form.startswith(normalized) or normalized.startswith(form)):
            if min(len(form), len(normalized)) >= 40:
                return UNAVAILABLE_MARKER, READER_PROSE_WAS_SOURCE_TEXT

    if _looks_like_raw_source_prose(value):
        return UNAVAILABLE_MARKER, READER_PROSE_NOT_KOREAN
    return value, None


def build_reader_article(
    authored: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    rank: int = 0,
) -> ReaderArticle:
    """Produce one reader article from separated evidence and authored prose."""
    authored = authored if isinstance(authored, Mapping) else {}
    evidence = evidence if isinstance(evidence, Mapping) else {}
    evidence_forms = _evidence_texts(evidence)
    issues: List[str] = []

    bound: Dict[str, str] = {}
    for name in PROSE_FIELDS:
        value, issue = _bind_prose(name, authored, evidence_forms)
        bound[name] = value
        if issue and name in REQUIRED_PROSE_FIELDS:
            issues.append(f"{issue}:{name}")
        elif issue and value is UNAVAILABLE_MARKER and name != "next_watch":
            issues.append(f"{issue}:{name}")

    source_ids = evidence.get("source_ids") or authored.get("source_ids") or []
    if not isinstance(source_ids, (list, tuple)):
        source_ids = [source_ids]
    source_id = _text(source_ids[0]) if source_ids else ""

    return ReaderArticle(
        # Identity is the evidence's, always.
        news_id=_text(evidence.get("news_id")) or _text(authored.get("news_id")),
        canonical_url=_text(evidence.get("source_url") or evidence.get("url")),
        source_id=source_id,
        source_name=_text(evidence.get("source_name") or evidence.get("source")),
        canonical_headline=_text(evidence.get("headline")),
        # Prose is the model's, or nothing.
        display_headline=bound["headline"],
        what_happened=bound["summary"],
        why_now=bound["why_it_matters"],
        business_implication=bound["business_implication"],
        next_watch=bound["next_watch"],
        category=_text(authored.get("category") or evidence.get("category")),
        uncertainty=_text(authored.get("confidence_label") or evidence.get("confidence_label")),
        source_attribution=_text(evidence.get("source_name") or evidence.get("source")),
        rank=int(authored.get("rank") or evidence.get("rank") or rank or 0),
        issues=tuple(issues),
    )


def _evidence_by_news_id(prompt_input: Any) -> Dict[str, Mapping[str, Any]]:
    if not isinstance(prompt_input, Mapping):
        return {}
    top = prompt_input.get("top_5_news")
    items = top.get("items") if isinstance(top, Mapping) else None
    out: Dict[str, Mapping[str, Any]] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                key = _text(item.get("news_id"))
                if key:
                    out[key] = item
    return out


def enforce_reader_surface(
    generated_briefing: Any,
    *,
    program_id: str,
    prompt_input: Any,
) -> Tuple[Any, Dict[str, Any]]:
    """Rebind every customer-visible article field through the producer.

    Identity is matched by ``news_id`` only. Positional pairing is what let one
    card wear another's source on 2026-08-27, so an item whose identity cannot
    be matched keeps its own identity and loses its prose rather than borrowing
    a neighbour's evidence.
    """
    diagnostics: Dict[str, Any] = {
        "reader_surface_enforced": False,
        "reader_surface_issue_codes": [],
        "reader_surface_unavailable_fields": [],
        "reader_surface_ready_item_count": 0,
    }
    if not isinstance(generated_briefing, dict):
        return generated_briefing, diagnostics
    top = generated_briefing.get("top_5_news")
    if not isinstance(top, dict):
        return generated_briefing, diagnostics
    items = top.get("items")
    if not isinstance(items, list) or not items:
        return generated_briefing, diagnostics

    evidence_map = _evidence_by_news_id(prompt_input)
    issue_codes: List[str] = []
    unavailable: List[str] = []
    ready = 0
    rebound: List[Any] = []

    for index, authored in enumerate(items):
        if not isinstance(authored, dict):
            rebound.append(authored)
            continue
        news_id = _text(authored.get("news_id"))
        evidence = evidence_map.get(news_id)
        if evidence is None:
            evidence = {}
            issue_codes.append(f"{READER_IDENTITY_UNMATCHED}:{news_id or index + 1}")

        article = build_reader_article(authored, evidence, rank=index + 1)
        for issue in article.issues:
            issue_codes.append(issue)
            unavailable.append(f"{news_id or index + 1}:{issue.split(':')[-1]}")
        if article.reader_ready:
            ready += 1

        item = dict(authored)
        item["headline"] = article.display_headline
        item["summary"] = article.what_happened
        item["why_it_matters"] = article.why_now
        if article.business_implication != UNAVAILABLE_MARKER or _text(
            authored.get("business_implication")
        ):
            item["business_implication"] = article.business_implication
        if _text(authored.get("next_watch")) or article.next_watch != UNAVAILABLE_MARKER:
            item["next_watch"] = article.next_watch
        # Identity may not drift, whatever the model or a scaffold wrote.
        if article.news_id:
            item["news_id"] = article.news_id
        # Source attribution is the evidence's or it is nothing. A model-supplied
        # URL or outlet for an item whose identity could not be matched is
        # unverifiable, and leaving it in place is how a card ends up citing an
        # article it was not written from.
        item["source_ids"] = list(evidence.get("source_ids") or []) if evidence else []
        item["source_url"] = article.canonical_url
        item["source_name"] = article.source_name
        item["reader_surface_ready"] = article.reader_ready
        rebound.append(item)

    out = dict(generated_briefing)
    out_top = dict(top)
    out_top["items"] = rebound
    out["top_5_news"] = out_top

    diagnostics["reader_surface_enforced"] = True
    diagnostics["reader_surface_issue_codes"] = sorted(set(issue_codes))
    diagnostics["reader_surface_unavailable_fields"] = sorted(set(unavailable))
    diagnostics["reader_surface_ready_item_count"] = ready
    if issue_codes:
        diagnostics["reader_surface_issue_codes"].append(READER_SURFACE_ENFORCED)
    return out, diagnostics


#: Required reader-ready article count for a KeeSuri briefing.
READER_READY_REQUIRED_COUNT = 5


def reader_surface_run_fields(generated_briefing: Any) -> Dict[str, Any]:
    """Run-artifact fields describing what the boundary had to withhold.

    Recorded so that service state, Admin and any later audit can see that a
    briefing reached owner review with fields the producer refused, without
    having to re-derive it from the briefing body.
    """
    if not isinstance(generated_briefing, Mapping):
        return {}
    diag = generated_briefing.get("_reader_surface_diagnostics")
    if not isinstance(diag, Mapping) or not diag.get("reader_surface_enforced"):
        return {}
    ready = int(diag.get("reader_surface_ready_item_count") or 0)
    codes = list(diag.get("reader_surface_issue_codes") or [])
    return {
        "reader_surface_enforced": True,
        "reader_surface_ready_item_count": ready,
        "reader_surface_issue_codes": codes,
        "reader_surface_unavailable_fields": list(
            diag.get("reader_surface_unavailable_fields") or []
        ),
        "reader_surface_complete": ready >= READER_READY_REQUIRED_COUNT,
    }
