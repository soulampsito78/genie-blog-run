"""Per-article editorial intent, derived from that article's own evidence.

The 2026-08-28 17:29 Global run recovered from a model-contract collapse and
produced five cards that were grounded, identity-correct and free of English —
and rhetorically identical. Tracing it, article-specific editorial intent
collapses in three places, earliest first:

1. **Evidence construction.** ``_claim_to_news_item`` fills ``why_it_matters``
   and ``business_implication`` with source/category templates when the claim
   carries none, so the "evidence" handed downstream is already generic:
   "AI·소프트웨어·플랫폼 영역의 공개 발표로, 사업 영향은 후속 공식 발표에서
   확인이 필요합니다."
2. **Corrective prompt construction.** The Global contract repair reuses
   ``build_keysuri_generation_prompt_compact``, written for a MAX_TOKENS
   emergency: it "drops long prose instructions" and truncates each article's
   summary — the one genuinely article-specific field — to 160 characters. The
   model is left with a schema and a title, which is not enough to differentiate
   five analyses, so it writes one shape five times.
3. **Enricher padding.** Thin output is then padded to a sentence floor from a
   fixed template per field.

This module addresses (1) and feeds (2): it derives a bounded, source-grounded
plan for each article separately, so the model writes *from evidence about this
article* rather than from a category. A field with no supporting evidence is
marked unavailable — never filled with a category template.

Nothing here is customer prose. These are intent/evidence fields.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: Marks a plan field the evidence cannot support.
UNAVAILABLE = None

PLAN_FIELDS: Tuple[str, ...] = (
    "primary_fact",
    "secondary_fact",
    "actual_change",
    "why_it_matters_now",
    "owner_relevance_basis",
    "followup_basis",
    "uncertainty_basis",
    "editorial_angle",
)

# Action signatures, matched against the article's own headline/summary. The
# angle comes from what the article reports happening — not from its category,
# so two unrelated stories filed under one category cannot inherit one angle.
_ACTION_SIGNATURES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("personnel_move", ("join", "joins", "joined", "hire", "hires", "poach", "defect", "recruit")),
    ("executive_departure", ("resign", "resigns", "step down", "steps down", "leaving", "leaves", "departs", "ousted", "exit")),
    ("capital_commitment", ("invest", "investment", "commits", "commitment", "funding", "raise", "raises", "billion", "million")),
    ("product_launch", ("launch", "launches", "unveil", "unveils", "announce", "announces", "release", "releases", "ships", "shipping")),
    ("security_disclosure", ("vulnerab", "exploit", "breach", "security", "attack", "malware", "unowned", "ransack")),
    ("regulatory_action", ("regulat", "antitrust", "lawsuit", "sues", "ban", "fine", "ruling", "court", "policy")),
    ("partnership", ("partner", "partnership", "deal", "agreement", "alliance", "acquire", "acquisition", "merger")),
    ("infrastructure_build", ("data center", "datacenter", "facility", "plant", "capacity", "grid", "campus", "build")),
    ("performance_result", ("earnings", "revenue", "profit", "results", "benchmark", "efficiency", "performance")),
)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*")
_NUMBER_RE = re.compile(r"\d[\d,.]*\s*(?:%|억|만|조|billion|million|bn|m\b|유로|달러|원)?", re.I)
_DATE_RE = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|\d{1,2}월\s*\d{1,2}일|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2})\b",
    re.I,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9''\-]{2,}|[가-힣]{2,}")

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "over", "after",
        "before", "who", "was", "were", "has", "have", "had", "its", "his", "her",
        "their", "not", "but", "are", "will", "would", "can", "could", "more", "than",
        "now", "new", "said", "says", "also", "been", "about", "which", "when",
    }
)


@dataclass(frozen=True)
class ArticleNarrativePlan:
    """Bounded editorial intent for one article. Not customer prose."""

    article_identity: str
    primary_fact: Optional[str] = None
    secondary_fact: Optional[str] = None
    actual_change: Optional[str] = None
    why_it_matters_now: Optional[str] = None
    owner_relevance_basis: Optional[str] = None
    followup_basis: Optional[str] = None
    uncertainty_basis: Optional[str] = None
    editorial_angle: str = "unclassified"
    discriminating_terms: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def unavailable_fields(self) -> Tuple[str, ...]:
        return tuple(name for name in PLAN_FIELDS if getattr(self, name) in (None, ""))

    def as_prompt_dict(self) -> Dict[str, Any]:
        """Plan as the model should receive it — unavailable stays explicit."""
        out: Dict[str, Any] = {"article_identity": self.article_identity}
        for name in PLAN_FIELDS:
            value = getattr(self, name)
            out[name] = value if value else "UNAVAILABLE"
        out["discriminating_terms"] = list(self.discriminating_terms)
        return out


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sentences(blob: str) -> List[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(blob or "") if p and p.strip()]
    return [p for p in parts if len(p) > 8]


def _terms(blob: str) -> List[str]:
    normalized = unicodedata.normalize("NFKC", blob or "").lower()
    return [w for w in _WORD_RE.findall(normalized) if w not in _STOPWORDS]


def _evidence_blob(item: Mapping[str, Any]) -> str:
    """Only genuinely source-derived fields.

    ``why_it_matters`` / ``business_implication`` are deliberately excluded:
    when the claim lacks them they hold a source/category template, and reading
    intent out of a template is how every article ends up with the same intent.
    """
    return " ".join(
        _text(item.get(key))
        for key in ("headline", "title", "summary", "statement")
        if _text(item.get(key))
    )


def _action_signature(blob: str) -> Optional[str]:
    lowered = unicodedata.normalize("NFKC", blob or "").lower()
    for name, markers in _ACTION_SIGNATURES:
        if any(marker in lowered for marker in markers):
            return name
    return None


_SIGNIFICANT_NUMBER_RE = re.compile(r"\d[\d,.]*")


def _significant_numbers(blob: str) -> List[str]:
    """Bare numeric tokens, normalized. Years are dropped: every article in a
    briefing shares the current year, so it discriminates nothing."""
    out: List[str] = []
    for raw in _SIGNIFICANT_NUMBER_RE.findall(blob or ""):
        token = raw.strip(".,").replace(",", "")
        if not token or token in out:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        out.append(token)
    return out


def _discriminating_terms(
    item: Mapping[str, Any],
    siblings: Sequence[Mapping[str, Any]],
    *,
    limit: int = 8,
) -> Tuple[str, ...]:
    """Terms this article's evidence has and the other selected articles do not.

    These are what make a sentence about *this* card impossible to reuse on
    another one, which is the property the specificity contract tests.
    """
    mine = set(_terms(_evidence_blob(item)))
    mine |= {t.lower() for t in (item.get("entity_keys") or []) if _text(t)}
    others: set = set()
    my_id = _text(item.get("news_id"))
    for sibling in siblings:
        if _text(sibling.get("news_id")) == my_id:
            continue
        others |= set(_terms(_evidence_blob(sibling)))
        others |= {t.lower() for t in (sibling.get("entity_keys") or []) if _text(t)}
    # Numbers and dates survive translation: a Global source is English while
    # the card is Korean, so word-level overlap alone would mark almost every
    # correctly-written card generic. "October 30" and "10월 30일" share 30.
    my_numbers = set(_significant_numbers(_evidence_blob(item)))
    other_numbers: set = set()
    for sibling in siblings:
        if _text(sibling.get("news_id")) == my_id:
            continue
        other_numbers |= set(_significant_numbers(_evidence_blob(sibling)))

    unique = [t for t in mine - others if len(t) >= 3]
    unique.sort(key=lambda t: (-len(t), t))
    unique_numbers = sorted(my_numbers - other_numbers)
    return tuple(unique[: max(limit - len(unique_numbers), 1)] + unique_numbers)


def build_article_narrative_plan(
    item: Mapping[str, Any],
    siblings: Sequence[Mapping[str, Any]] = (),
) -> ArticleNarrativePlan:
    """Derive one article's plan from its own evidence."""
    item = item if isinstance(item, Mapping) else {}
    blob = _evidence_blob(item)
    summary = _text(item.get("summary")) or _text(item.get("statement"))
    sentences = _sentences(summary)
    entities = [_text(e) for e in (item.get("entity_keys") or []) if _text(e)]
    numbers = _NUMBER_RE.findall(blob)
    dates = _DATE_RE.findall(blob)
    discriminating = _discriminating_terms(item, siblings)
    signature = _action_signature(blob)

    primary_fact = sentences[0] if sentences else (_text(item.get("headline")) or None)
    secondary_fact = sentences[1] if len(sentences) > 1 else None

    actual_change = None
    if signature and (entities or discriminating):
        anchor = entities[0] if entities else discriminating[0]
        actual_change = f"{signature}:{anchor}"

    # Only assert a "why now" basis when the evidence carries something that
    # dates or scales the change. Otherwise it stays unavailable rather than
    # becoming "이 분야의 공개 발표" for every card.
    why_now_basis = None
    if dates or numbers:
        why_now_basis = "; ".join(
            filter(None, [", ".join(dates[:2]) or None, ", ".join(numbers[:3]) or None])
        )
    elif signature and entities:
        why_now_basis = f"{signature} involving {', '.join(entities[:2])}"

    owner_relevance_basis = None
    if discriminating:
        owner_relevance_basis = ", ".join(discriminating[:3])
    elif entities:
        owner_relevance_basis = ", ".join(entities[:2])

    followup_basis = None
    if dates:
        followup_basis = f"dated_event:{dates[0]}"
    elif numbers:
        followup_basis = f"quantified_claim:{numbers[0]}"
    elif signature:
        followup_basis = f"unquantified_{signature}"

    uncertainty_basis = None
    if not numbers and not dates:
        uncertainty_basis = "source states no figures or dates"
    elif not numbers:
        uncertainty_basis = "scale not quantified in source"
    elif not dates:
        uncertainty_basis = "timing not stated in source"

    angle = signature or "unclassified"
    if discriminating:
        angle = f"{angle}::{discriminating[0]}"

    return ArticleNarrativePlan(
        article_identity=_text(item.get("news_id")),
        primary_fact=primary_fact,
        secondary_fact=secondary_fact,
        actual_change=actual_change,
        why_it_matters_now=why_now_basis,
        owner_relevance_basis=owner_relevance_basis,
        followup_basis=followup_basis,
        uncertainty_basis=uncertainty_basis,
        editorial_angle=angle,
        discriminating_terms=discriminating,
    )


def build_narrative_plans(
    items: Sequence[Mapping[str, Any]],
) -> List[ArticleNarrativePlan]:
    """One plan per selected article, each derived independently.

    Angles are disambiguated after derivation: two articles that genuinely share
    an action signature keep distinct angles via their own discriminating terms,
    so a shared category can never collapse them onto one editorial intent.
    """
    items = [i for i in (items or []) if isinstance(i, Mapping)]
    plans = [build_article_narrative_plan(item, items) for item in items]

    seen: Dict[str, int] = {}
    resolved: List[ArticleNarrativePlan] = []
    for plan in plans:
        angle = plan.editorial_angle
        if angle in seen:
            suffix = plan.article_identity[-8:] or str(seen[angle])
            angle = f"{angle}#{suffix}"
        seen[angle] = seen.get(plan.editorial_angle, 0) + 1
        resolved.append(
            plan if angle == plan.editorial_angle
            else ArticleNarrativePlan(
                **{**plan.__dict__, "editorial_angle": angle}
            )
        )
    return resolved


def plans_as_prompt_payload(plans: Sequence[ArticleNarrativePlan]) -> List[Dict[str, Any]]:
    return [plan.as_prompt_dict() for plan in plans]


# ---------------------------------------------------------------------------
# Deep dive — synthesis, not repetition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeepDiveSynthesisPlan:
    """What the deep dive is *for*, derived from the five plans together.

    Built from structured facts, never from already-generated reader prose, so
    the deep dive cannot become a restatement of the TOP5 cards it sits under.
    """

    common_pattern: Optional[str] = None
    tensions: Optional[str] = None
    why_differences_matter: Optional[str] = None
    owner_implications: Tuple[str, ...] = field(default_factory=tuple)
    uncertainty: Optional[str] = None

    def as_prompt_dict(self) -> Dict[str, Any]:
        return {
            "common_pattern": self.common_pattern or "UNAVAILABLE",
            "tensions": self.tensions or "UNAVAILABLE",
            "why_differences_matter": self.why_differences_matter or "UNAVAILABLE",
            "owner_implications": list(self.owner_implications) or ["UNAVAILABLE"],
            "uncertainty": self.uncertainty or "UNAVAILABLE",
        }


def build_deep_dive_synthesis_plan(
    plans: Sequence[ArticleNarrativePlan],
) -> DeepDiveSynthesisPlan:
    """Synthesis intent across the selected articles."""
    plans = [p for p in plans if isinstance(p, ArticleNarrativePlan)]
    if not plans:
        return DeepDiveSynthesisPlan()

    signatures = [p.editorial_angle.split("::", 1)[0] for p in plans]
    counts: Dict[str, int] = {}
    for sig in signatures:
        counts[sig] = counts.get(sig, 0) + 1
    shared = sorted([s for s, c in counts.items() if c > 1])
    distinct = sorted({s for s, c in counts.items() if c == 1})

    common_pattern = None
    if shared:
        common_pattern = "recurring:" + ", ".join(shared)
    elif len(distinct) >= 3:
        # No repeated signature is itself the pattern: the day is broad.
        common_pattern = "dispersed:" + ", ".join(distinct[:4])

    tensions = None
    if len(distinct) >= 2:
        tensions = " vs ".join(distinct[:3])

    why = None
    if shared and distinct:
        why = f"concentration in {shared[0]} against isolated {distinct[0]}"
    elif distinct:
        why = f"no single axis dominates ({len(distinct)} distinct movements)"

    implications: List[str] = []
    for plan in plans:
        if plan.owner_relevance_basis:
            implications.append(f"{plan.article_identity}:{plan.owner_relevance_basis}")
    uncertainty_bits = sorted(
        {p.uncertainty_basis for p in plans if p.uncertainty_basis}
    )
    return DeepDiveSynthesisPlan(
        common_pattern=common_pattern,
        tensions=tensions,
        why_differences_matter=why,
        owner_implications=tuple(implications[:3]),
        uncertainty="; ".join(uncertainty_bits[:2]) or None,
    )


def deep_dive_repeats_top5(deep_dive_body: Any, top5_items: Sequence[Mapping[str, Any]]) -> List[str]:
    """Sentences the deep dive reuses from the TOP5 cards it sits under.

    Overlap is measured on whole sentences rather than keywords: a deep dive
    *should* mention the same companies, but restating a card's sentence is
    repetition rather than synthesis.
    """
    body_sentences = {_norm_sentence(s) for s in _sentences(_text(deep_dive_body))}
    if not body_sentences:
        return []
    reused: List[str] = []
    for item in top5_items or ():
        if not isinstance(item, Mapping):
            continue
        for key in ("what_happened", "summary", "why_now", "why_it_matters", "next_watch"):
            raw = item.get(key)
            if isinstance(raw, (list, tuple)):
                raw = " ".join(str(x) for x in raw)
            for sentence in _sentences(_text(raw)):
                normalized = _norm_sentence(sentence)
                if len(normalized) >= 20 and normalized in body_sentences:
                    reused.append(sentence)
    return reused


def _norm_sentence(sentence: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", sentence or "")).strip().lower()
