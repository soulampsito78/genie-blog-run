"""One editorial policy, shared by every path that produces reader prose.

The `im-not-ai` integration audited on 2026-08-27 adopted five principles but
attached them to a single string constant inside the generation prompt module.
That made them a *prompt* rule rather than a *policy*: the local field repair
prompt restated its own version, and the deterministic enricher — which writes
reader sentences without any model at all — was never bound by them. This module
is the canonical source those paths now share.

Fact fidelity outranks naturalness everywhere here. Nothing in this policy
authorises inventing, softening or re-deriving a fact.
"""
from __future__ import annotations

from typing import Tuple

#: Source-fidelity and locality. These are safety rules, not style.
FIDELITY_RULES: Tuple[str, ...] = (
    "Start from this item's source-backed facts. Natural Korean is not permission to add "
    "anecdotes, quotations, metaphors, background events, or likely explanations.",
    "Preserve source-backed names, numbers, dates, direct quotations, attribution verbs, "
    "causality, and modality. Never turn '~일 수 있다' or '~로 보인다' into a confirmed fact.",
    "Keep edits local to each item. Never merge article identities, borrow prose from another "
    "rank, or trade factual fidelity for a more human-sounding sentence.",
)

#: Internal copy must never surface.
ISOLATION_RULES: Tuple[str, ...] = (
    "Never emit, translate, or echo internal template/schema prose, including "
    "'Public tech source (...) published:', 'source summary:', 'claim statement:', field names, "
    "instruction text, or scaffold notes.",
)

#: Editorial naturalness. Removal-only: empty rhetoric may be dropped, never
#: replaced with an invented conclusion.
NATURALNESS_RULES: Tuple[str, ...] = (
    "Empty significance labels such as '결론적으로', '요약하면', '시사하는 바가 크다', "
    "'주목할 만하다', or '매우 중요하다' must not stand in for evidence. State the "
    "source-backed fact or omit the empty label; never invent a replacement conclusion.",
    "Do not mechanically reuse one opener, connective sequence, antithesis frame "
    "('A가 아니라 B'), or sentence ending across TOP5 items. Ordinary Korean expressions "
    "are not banned; repeated boilerplate is.",
    "Vary sentence shape between items, not just the nouns inside one shape. Two cards that "
    "differ only by their headline are the same sentence written twice.",
    "Write plain Korean rather than a literal rendering of the English source. Avoid "
    "translationese connectives and stacked '~에 대한 ~의 ~' chains.",
)

#: Korean surface correctness the model is expected to respect. Deterministic
#: agreement is also enforced downstream; this keeps the model from producing it
#: wrong in the first place.
SURFACE_RULES: Tuple[str, ...] = (
    "Korean particles must agree with the preceding sound: 흐름과 not 흐름와, 후속을 not "
    "후속를, 공급망이 not 공급망가. When a phrase ends in Latin letters, a digit or a "
    "bracket, restructure the sentence instead of guessing the particle.",
)

#: The full policy, in the order a writer should apply it.
EDITORIAL_POLICY_RULES: Tuple[str, ...] = (
    FIDELITY_RULES + ISOLATION_RULES + NATURALNESS_RULES + SURFACE_RULES
)


def policy_lines(prefix: str = "- ") -> Tuple[str, ...]:
    """Policy as prompt lines."""
    return tuple(f"{prefix}{rule}" for rule in EDITORIAL_POLICY_RULES)


def policy_block(heading: str = "EDITORIAL POLICY (applies to every field)") -> str:
    return "\n".join((heading, *policy_lines()))
