"""Does this card say anything only this article could support?

The repeated-skeleton detector measures sentence *shape*. This measures
*content*: an explanatory field must carry at least one fact, entity, number,
date or named event that comes from this article's own evidence and does not
come from the other selected articles.

NOT PRODUCTION-GATING. Measured against real artifacts on 2026-08-28 this does
not track editorial quality: the known-good 2026-08-26 Global briefing (editorial
READY, no findings) scores 70% generic fields and 3 fully-generic cards, while
the rejected 2026-08-28 17:29 run scores 30% and 0. The measure is dominated by
whether Korean prose happens to retain Latin tokens or digits from an English
source, which varies with the story rather than with the writing. Gating on it
would block good briefings and pass bad ones. It is kept as an offline
diagnostic; sentence-shape repetition
(``global_visible_repeated_template_skeleton_blocked``) remains the signal that
actually caught the failure.

The operational definition is the headline-swap test the owner specified. If a
card's explanatory prose would remain equally valid after swapping its headline
with another TOP5 article's, the prose is about the category, not the article.
Implemented deterministically: strip the card's own title tokens from the field
and ask whether any *discriminating* evidence term survives. No phrase list, no
LLM judge — the evidence decides.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from keysuri_narrative_plan import ArticleNarrativePlan, build_narrative_plans

#: Explanatory fields a reader card must ground in its own article.
EXPLANATORY_FIELDS: Tuple[str, ...] = (
    "what_happened",
    "why_now",
    "owner_angle",
    "next_watch",
)

#: Field aliases as they appear on generated items.
_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "what_happened": ("what_happened", "summary"),
    "why_now": ("why_now", "why_it_matters"),
    "owner_angle": ("owner_angle", "business_implication", "owner_perspective"),
    "next_watch": ("next_watch", "next_check_point"),
}

ARTICLE_SPECIFICITY_ISSUE = "keysuri_card_not_article_specific"

#: Above this share of a field's tokens coming from its own headline, the field
#: is restating the title rather than explaining the article.
_TITLE_ECHO_RATIO = 0.6

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9''\-]{2,}|[가-힣]{2,}")
_NUMBER_RE = re.compile(r"\d[\d,.]*")


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower()


def _tokens(value: Any) -> List[str]:
    return _WORD_RE.findall(_norm(value)) + _NUMBER_RE.findall(_norm(value))


def _field_value(item: Mapping[str, Any], field: str) -> str:
    for alias in _FIELD_ALIASES.get(field, (field,)):
        raw = item.get(alias)
        if isinstance(raw, (list, tuple)):
            raw = " ".join(str(x) for x in raw)
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def field_is_article_specific(
    text: str,
    plan: ArticleNarrativePlan,
    *,
    own_title: str = "",
) -> bool:
    """Whether ``text`` carries evidence only this article supplies.

    A field that is mostly its own headline is an echo, not analysis: a template
    interpolating the title would otherwise look specific on every card, which
    is how the 2026-08-28 cards read as distinct while sharing one skeleton. But
    naming the company the headline names *is* legitimate, so the guard is a
    ratio rather than a blanket removal of every title token.
    """
    if not text.strip():
        return False
    body_tokens = _tokens(text)
    if not body_tokens:
        return False
    title_tokens = set(_tokens(own_title))
    if title_tokens:
        echoed = sum(1 for t in body_tokens if t in title_tokens)
        if echoed / len(body_tokens) > _TITLE_ECHO_RATIO:
            return False
    body = set(body_tokens)
    return any(_norm(term) in body for term in plan.discriminating_terms)


def evaluate_article_specificity(
    items: Sequence[Mapping[str, Any]],
    *,
    required_fields: Sequence[str] = EXPLANATORY_FIELDS,
) -> Dict[str, Any]:
    """Per-card specificity over the whole TOP5 set.

    Returns ``{"ok", "findings", "per_item", "generic_cards"}``.

    ``ok`` is card-level, not field-level, and deliberately so. A Global source
    is English while the card is Korean, so a correctly written sentence like
    "조프가 구글로 합류했습니다" carries no token tying it to "Barret Zoph …
    Google" — transliteration defeats token correspondence. Demanding every
    field be provably anchored would therefore fail good briefings. What is
    checkable is that a card anchors *somewhere*: at least one explanatory field
    must carry a number, date, or retained Latin term that only this article's
    evidence supplies. Per-field findings are still reported as diagnostics.

    Sentence *shape* repetition is a separate measure —
    ``global_visible_repeated_template_skeleton_blocked`` — and the two together
    cover the 2026-08-28 failure: identical shape, no article anchoring.
    """
    items = [i for i in (items or []) if isinstance(i, Mapping)]
    plans = {p.article_identity: p for p in build_narrative_plans(items)}
    findings: List[Dict[str, Any]] = []
    per_item: List[Dict[str, Any]] = []

    for item in items:
        news_id = str(item.get("news_id") or "").strip()
        plan = plans.get(news_id)
        title = str(item.get("headline") or item.get("korean_title") or "")
        generic: List[str] = []
        checked: List[str] = []
        if plan is None or not plan.discriminating_terms:
            # No discriminating evidence exists for this article at all; the
            # card cannot be asked to prove specificity it was never given.
            per_item.append(
                {"news_id": news_id, "checked": [], "generic": [], "skipped": True}
            )
            continue
        for name in required_fields:
            text = _field_value(item, name)
            if not text:
                continue
            checked.append(name)
            if not field_is_article_specific(text, plan, own_title=title):
                generic.append(name)
        anchored = [name for name in checked if name not in generic]
        per_item.append(
            {
                "news_id": news_id,
                "checked": checked,
                "generic": generic,
                "anchored": anchored,
                "card_is_generic": bool(checked) and not anchored,
                "skipped": False,
            }
        )
        for name in generic:
            findings.append(
                {
                    "issue_code": ARTICLE_SPECIFICITY_ISSUE,
                    "news_id": news_id,
                    "field": name,
                    "detail": (
                        f"{name} carries no evidence unique to this article "
                        f"(expected one of: {', '.join(plan.discriminating_terms[:5])})"
                    ),
                }
            )
    generic_cards = [row["news_id"] for row in per_item if row.get("card_is_generic")]
    return {
        "ok": not generic_cards,
        "findings": findings,
        "per_item": per_item,
        "generic_cards": generic_cards,
    }


def headline_swap_is_survivable(
    item: Mapping[str, Any],
    other: Mapping[str, Any],
    *,
    required_fields: Sequence[str] = EXPLANATORY_FIELDS,
) -> bool:
    """The owner's test, literally: does this card still read as valid prose
    about ``other`` once its headline is swapped in?

    True means the explanatory prose never depended on the original article —
    i.e. the card is too generic.
    """
    plans = {p.article_identity: p for p in build_narrative_plans([item, other])}
    plan = plans.get(str(item.get("news_id") or "").strip())
    if plan is None or not plan.discriminating_terms:
        return True
    own_title = str(item.get("headline") or item.get("korean_title") or "")
    for name in required_fields:
        text = _field_value(item, name)
        if not text:
            continue
        if field_is_article_specific(text, plan, own_title=own_title):
            # At least one field is anchored to this article's own evidence,
            # so the swap would produce a factually wrong card — good.
            return False
    return True
