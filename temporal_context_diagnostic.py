"""Pure, fail-closed Today role-context diagnostics; no live fact registry.

The existing service boundary has no independently verified dated role input.
Consequently every current/ambiguous recognized role requires review, including
a plausible or correctly worded role. No generated flag, source-link status,
article publication date, or hard-coded current-office table can clear it.
An explicitly dated historical statement is outside current-role comparison,
not certified historical truth. The detector is deliberately narrow, not a
general entity/fact checker. It never edits its fields or contacts a provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable, Any


ROLE_CONTEXT_UNKNOWN = "customer_surface_current_office_context_unknown"

_NAMED_ROLE = re.compile(
    r"(?P<entity>트럼프|Donald\s+(?:J\.?\s+)?Trump|(?<![A-Za-z])Trump(?![A-Za-z])"
    r"|밴스|J\.?D\.?\s+Vance|(?<![A-Za-z])Vance(?![A-Za-z]))\s*"
    r"(?P<role>전\s*대통령|전\s*부통령|상원의원|의원|부통령|대통령"
    r"|former\s+(?:president|vice\s+president)|vice\s+president|president|senator|lawmaker)",
    re.I,
)
_PRONOUN_ROLE = re.compile(
    r"(?<![가-힣])(?:그|그녀|해당\s*인물)(?:는|은|가|이)?\s*"
    r"(?:전\s*대통령|전\s*부통령|상원의원|의원|부통령|대통령)"
    r"|\b(?:he|she)\s+(?:is|was)\s+(?:the\s+)?(?:former\s+)?"
    r"(?:vice\s+president|president|senator|lawmaker)\b", re.I,
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?:\s*년|[-/.]\d{1,2}[-/.]\d{1,2})(?!\d)")
_HISTORY = re.compile(r"당시|과거|그때|회고|\bhistorical\b|\bat\s+the\s+time\b", re.I)
_CURRENT = re.compile(r"오늘|현재|지금|이번\s*장전|\btoday\b|\bcurrently\b|\bnow\b", re.I)
_ATTRIBUTION = re.compile(r"인용|발언|말했|기록|\bquoted\b|\bsaid\b|\bremark", re.I)
_QUOTES = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』')
_CLAUSE_BREAK = re.compile(r"[.!?;。\n]|하지만|그러나|반면(?:에)?|\bbut\b", re.I)


@dataclass(frozen=True)
class RoleContextFinding:
    path: str
    card_index: int
    start: int
    end: int
    entity: str
    context: str
    reason: str
    review_required: bool
    fact_verdict: str = "NOT_CERTIFIED"


def _target_day(value: Any) -> date | None:
    # No clock fallback and no conversion of arbitrary/generated objects.
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _clause(text: str, start: int, end: int) -> str:
    left, right = 0, len(text)
    for boundary in _CLAUSE_BREAK.finditer(text):
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    return text[left:right]


def _context(text: str, match: re.Match, target: date | None) -> tuple[str, str]:
    if target is None:
        return "AMBIGUOUS", "target_date_invalid_or_missing"
    clause = _clause(text, match.start(), match.end())
    years = {int(year) for year in _YEAR.findall(clause)}
    current = bool(_CURRENT.search(clause))
    quoted = any(q.start() <= match.start() and match.end() <= q.end()
                 for q in _QUOTES.finditer(text))
    historical = bool(_HISTORY.search(clause))
    attribution = bool(_ATTRIBUTION.search(clause))
    if any(mark in clause for mark in ('"', '“', '”', '「', '」', '『', '』')) and not quoted:
        return "AMBIGUOUS", "quote_span_scope_unverified"
    if years and (len(years) != 1 or max(years) >= target.year):
        return "AMBIGUOUS", "same_year_future_or_conflicting_event_time"
    if current and (years or historical or quoted):
        return "AMBIGUOUS", "mixed_current_historical_or_quoted_context"
    if years and not current:
        if quoted:
            # Quote attribution must be explicit in the same clause. A nearby
            # older year alone cannot silently clear an unverified quotation.
            if attribution:
                return "HISTORICAL_QUOTE", "outside_current_role_comparison_not_fact_PASS"
            return "AMBIGUOUS", "quote_attribution_unverified"
        if historical:
            return "HISTORICAL", "outside_current_role_comparison_not_fact_PASS"
        return "AMBIGUOUS", "event_date_role_scope_unverified"
    if quoted or historical:
        return "AMBIGUOUS", "historical_or_quote_event_time_unverified"
    return "CURRENT_ASSERTION", "independent_dated_role_evidence_not_injected"


def inspect_role_fields(fields: Iterable[Any], *, target_date: Any = None) -> tuple[RoleContextFinding, ...]:
    """Inspect only text/path/card_index. Caller flags and facts are not inputs.

    No API for caller-supplied 'verified' evidence is exposed in this candidate:
    the server-side authenticated evidence path has not been implemented or
    reviewed. Even NO_CURRENT_ROLE_FINDING would not certify any other claim.
    """
    target = _target_day(target_date)
    out = []
    for field in fields:
        text = field.text
        for match in _NAMED_ROLE.finditer(text):
            context, reason = _context(text, match, target)
            out.append(RoleContextFinding(
                field.path, field.card_index, match.start(), match.end(),
                match.group("entity"), context, reason,
                context not in {"HISTORICAL", "HISTORICAL_QUOTE"},
            ))
        for match in _PRONOUN_ROLE.finditer(text):
            out.append(RoleContextFinding(
                field.path, field.card_index, match.start(), match.end(),
                "UNRESOLVED", "AMBIGUOUS", "actor_identity_unverified", True,
            ))
    return tuple(out)
