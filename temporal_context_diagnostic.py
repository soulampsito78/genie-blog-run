"""Pure, fail-closed Today role-context diagnostics.

This snapshot is deliberately date-bound: it can only assess current-role
wording for its as-of date. It is not a general entity/fact checker and it
never edits customer copy or contacts a provider. Historical statements remain
outside current-role comparison, not certified historical truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
from typing import Iterable, Any, Mapping
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROLE_CONTEXT_UNKNOWN = "customer_surface_current_office_context_unknown"
ROLE_CONTEXT_MISMATCH = "customer_surface_current_office_role_mismatch"

ROLE_EVIDENCE_SOURCE = "https://www.whitehouse.gov/administration/"
ROLE_EVIDENCE_CONTRACT = "today-current-role-evidence-v1"
ROLE_EVIDENCE_MAX_BYTES = 1_000_000
ROLE_EVIDENCE_TIMEOUT_SECONDS = 3.0


class _RoleHeadingParser(HTMLParser):
    """Extract only visible heading text from the pinned first-party page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._active = False
        self._parts: list[str] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"h1", "h2", "h3", "h4"}:
            self._active = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._active and tag.lower() in {"h1", "h2", "h3", "h4"}:
            heading = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if heading:
                self.headings.append(heading)
            self._active = False
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active:
            self._parts.append(data)


def build_role_evidence_from_source_headings(
    target_date: Any,
    headings: Iterable[str],
    *,
    observed_at: str,
    source_sha256: str,
) -> dict[str, Any] | None:
    """Build a same-day role snapshot only from exact recognized source headings."""
    target = _target_day(target_date)
    try:
        observed = datetime.fromisoformat(observed_at)
    except (TypeError, ValueError):
        return None
    if target is None or observed.date() != target:
        return None
    normalized = [re.sub(r"\s+", " ", str(value)).strip() for value in headings]
    required = {
        "trump": re.compile(r"^President Donald J\. Trump$", re.I),
        "vance": re.compile(r"^Vice President JD Vance$", re.I),
    }
    matched: dict[str, str] = {}
    for entity, pattern in required.items():
        heading = next((value for value in normalized if pattern.fullmatch(value)), None)
        if heading is None:
            return None
        matched[entity] = heading
    excerpt = "\n".join(matched[entity] for entity in ("trump", "vance"))
    return {
        "contract_version": ROLE_EVIDENCE_CONTRACT,
        "as_of": target.isoformat(),
        "valid_through": target.isoformat(),
        "observed_at": observed.isoformat(),
        "source": ROLE_EVIDENCE_SOURCE,
        "source_sha256": source_sha256,
        "evidence_text": excerpt,
        "evidence_text_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
        "roles": {"trump": "president", "vance": "vice_president"},
    }


def fetch_current_role_evidence(target_date: Any) -> dict[str, Any] | None:
    """Read the existing official source once; failure/format drift stays UNKNOWN.

    This is a bounded, no-auth GET to the already-referenced White House page;
    it is not a paid API call and has no retry or cache-extension behavior.
    """
    target = _target_day(target_date)
    observed = datetime.now(ZoneInfo("Asia/Seoul"))
    if target is None or target != observed.date():
        return None
    request = Request(
        ROLE_EVIDENCE_SOURCE,
        headers={"User-Agent": "GENIE-role-evidence/1.0", "Accept": "text/html"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=ROLE_EVIDENCE_TIMEOUT_SECONDS) as response:
            final_url = urlparse(response.geturl())
            if response.status != 200 or final_url.scheme != "https" or final_url.hostname != "www.whitehouse.gov":
                return None
            raw = response.read(ROLE_EVIDENCE_MAX_BYTES + 1)
            if len(raw) > ROLE_EVIDENCE_MAX_BYTES:
                return None
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return None
        html = raw.decode("utf-8", errors="strict")
    except Exception:
        return None
    parser = _RoleHeadingParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    return build_role_evidence_from_source_headings(
        target.isoformat(), parser.headings,
        observed_at=observed.isoformat(), source_sha256=sha256(raw).hexdigest(),
    )


def _validated_role_evidence(target_date: Any, evidence: Any) -> Mapping[str, Any] | None:
    target = _target_day(target_date)
    if target is None or not isinstance(evidence, Mapping):
        return None
    if evidence.get("contract_version") != ROLE_EVIDENCE_CONTRACT:
        return None
    if evidence.get("as_of") != target.isoformat() or evidence.get("valid_through") != target.isoformat():
        return None
    try:
        observed = datetime.fromisoformat(str(evidence.get("observed_at") or ""))
    except ValueError:
        return None
    if observed.date() != target:
        return None
    excerpt = evidence.get("evidence_text")
    if not isinstance(excerpt, str) or sha256(excerpt.encode("utf-8")).hexdigest() != evidence.get("evidence_text_sha256"):
        return None
    expected = build_role_evidence_from_source_headings(
        target.isoformat(), excerpt.splitlines(), observed_at=observed.isoformat(),
        source_sha256=str(evidence.get("source_sha256") or ""),
    )
    if not expected or expected["source"] != evidence.get("source"):
        return None
    # Fresh parser output is compared exactly; model-supplied fields cannot
    # extend validity, source, entities, or roles.
    return evidence if dict(evidence) == expected else None

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
    expected_role: str | None = None
    evidence_as_of: str | None = None
    evidence_reference: str | None = None


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
    return "CURRENT_ASSERTION", "current_role_requires_snapshot_comparison"


def _normalize_role(role: str) -> str:
    normalized = re.sub(r"\s+", " ", role.casefold()).strip()
    if normalized in {"전 대통령", "전대통령", "former president"}:
        return "former_president"
    if normalized in {"대통령", "president"}:
        return "president"
    if normalized in {"전 부통령", "전부통령", "former vice president"}:
        return "former_vice_president"
    if normalized in {"부통령", "vice president"}:
        return "vice_president"
    return "lawmaker"


def inspect_role_fields(
    fields: Iterable[Any], *, target_date: Any = None, role_evidence: Any = None
) -> tuple[RoleContextFinding, ...]:
    """Compare recognized current-role spans with the dated first-party snapshot.

    Generated payload flags and publication date are not role evidence. A
    snapshot on a different day cannot clear either UNKNOWN or a mismatch.
    """
    target = _target_day(target_date)
    evidence = _validated_role_evidence(target_date, role_evidence)
    out = []
    for field in fields:
        text = field.text
        for match in _NAMED_ROLE.finditer(text):
            context, reason = _context(text, match, target)
            entity = "trump" if match.group("entity").casefold() in {"트럼프", "trump"} or "trump" in match.group("entity").casefold() else "vance"
            observed = _normalize_role(match.group("role"))
            expected = None
            evidence_reference = None
            review_required = context not in {"HISTORICAL", "HISTORICAL_QUOTE"}
            if context == "CURRENT_ASSERTION":
                if target is None or evidence is None:
                    context, reason = "AMBIGUOUS", "dated_current_role_snapshot_unavailable"
                    review_required = True
                else:
                    expected = evidence["roles"][entity]
                    evidence_reference = evidence["source"]
                    if observed != expected:
                        context, reason = "CURRENT_ROLE_MISMATCH", "observed_role_conflicts_with_dated_first_party_snapshot"
                        review_required = True
                    else:
                        reason = "matches_dated_first_party_snapshot"
                        review_required = False
            out.append(RoleContextFinding(
                field.path, field.card_index, match.start(), match.end(),
                match.group("entity"), context, reason, review_required,
                "NOT_CERTIFIED", expected, evidence["as_of"] if expected and evidence else None,
                evidence_reference,
            ))
        for match in _PRONOUN_ROLE.finditer(text):
            out.append(RoleContextFinding(
                field.path, field.card_index, match.start(), match.end(),
                "UNRESOLVED", "AMBIGUOUS", "actor_identity_unverified", True,
            ))
    return tuple(out)
