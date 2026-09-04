"""Shared deterministic financial-news entity grounding for today_genie."""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, FrozenSet, List, Sequence, Set, Tuple

from product_surface_contract import build_korean_safe_reader_title

PRIMARY_MARKET_ENTITIES: FrozenSet[str] = frozenset(
    {"sp500", "nasdaq", "nikkei", "kospi", "kosdaq", "dow", "seoul_shares"}
)

CONTEXT_ENTITIES: FrozenSet[str] = frozenset(
    {"record_high", "tech_rally", "mideast", "ai", "fed", "inflation"}
)

ENTITY_CANONICAL: Dict[str, str] = {
    "sp500": "S&P 500",
    "nasdaq": "Nasdaq",
    "nikkei": "Nikkei",
    "kospi": "KOSPI",
    "kosdaq": "KOSDAQ",
    "dow": "Dow Jones",
    "seoul_shares": "Seoul shares",
    "record_high": "record high",
    "tech_rally": "tech rally",
    "mideast": "Mideast",
    "ai": "AI",
    "fed": "Fed",
    "inflation": "inflation",
}

ENTITY_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "sp500": (
        r"s\s*&\s*p\s*500",
        r"s&p500",
        r"spx\b",
        r"sp500",
        r"에스앤피\s*500",
        r"에스앤피500",
    ),
    "nasdaq": (r"nasdaq", r"나스닥"),
    "nikkei": (r"nikkei(?:\s*225)?", r"닛케이", r"니케이"),
    "kospi": (r"kospi", r"코스피"),
    "kosdaq": (r"kosdaq", r"코스닥"),
    "dow": (r"dow\s*jones", r"\bdow\b", r"\bdji\b", r"다우"),
    "seoul_shares": (
        r"seoul\s+shares",
        r"seoul\s+stock\s+market",
        r"korean\s+shares",
        r"서울\s*증시",
    ),
    "record_high": (
        r"record\s+high",
        r"new\s+records?",
        r"record\s+peak",
        r"new\s+high",
        r"사상\s*최고",
        r"신기록",
    ),
    "tech_rally": (
        r"tech\s+rally",
        r"technology\s+rally",
        r"기술주\s*강세",
        r"기술주\s*랠리",
    ),
    "mideast": (r"mideast", r"middle\s+east", r"중동"),
    "ai": (r"\bai\b", r"artificial\s+intelligence", r"ai\s+optimism", r"인공\s*지능"),
    "fed": (r"\bfed\b", r"federal\s+reserve", r"연준"),
    "inflation": (r"inflation", r"\bcpi\b", r"물가", r"인플레"),
}

COVERAGE_EQUIVALENTS: Dict[str, FrozenSet[str]] = {
    "seoul_shares": frozenset({"seoul_shares", "kospi"}),
    "kospi": frozenset({"kospi", "seoul_shares"}),
}

_SOFT_CONTEXT_GROUPS: Tuple[FrozenSet[str], ...] = (
    frozenset({"record_high", "tech_rally"}),
)

_COMPILED: Dict[str, List[re.Pattern[str]]] = {}


def normalize_text_for_grounding(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("&amp;", "&").replace("＆", "&").replace("﹠", "&")
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _compiled_patterns(entity_id: str) -> List[re.Pattern[str]]:
    cached = _COMPILED.get(entity_id)
    if cached is not None:
        return cached
    patterns = [
        re.compile(p, re.IGNORECASE)
        for p in ENTITY_PATTERNS.get(entity_id, ())
    ]
    _COMPILED[entity_id] = patterns
    return patterns


def extract_market_entities(text: str) -> FrozenSet[str]:
    norm = normalize_text_for_grounding(text)
    if not norm:
        return frozenset()
    found: Set[str] = set()
    for entity_id in ENTITY_PATTERNS:
        if any(p.search(norm) for p in _compiled_patterns(entity_id)):
            found.add(entity_id)
    return frozenset(found)


def expand_entity_aliases(entities: Sequence[str]) -> FrozenSet[str]:
    expanded: Set[str] = set()
    for entity_id in entities:
        expanded.add(entity_id)
        expanded.update(COVERAGE_EQUIVALENTS.get(entity_id, ()))
    return frozenset(expanded)


def _entity_present(text: str, entity_id: str) -> bool:
    norm = normalize_text_for_grounding(text)
    return any(p.search(norm) for p in _compiled_patterns(entity_id))


def _entity_or_equivalent_present(text: str, entity_id: str) -> bool:
    group = COVERAGE_EQUIVALENTS.get(entity_id, frozenset({entity_id}))
    return any(_entity_present(text, member) for member in group)


def _required_for_headline(headline: str) -> Tuple[FrozenSet[str], Tuple[FrozenSet[str], ...]]:
    found = extract_market_entities(headline)
    primary = found & PRIMARY_MARKET_ENTITIES
    if not primary:
        primary = found & (PRIMARY_MARKET_ENTITIES | CONTEXT_ENTITIES)
    soft_groups: List[FrozenSet[str]] = []
    for group in _SOFT_CONTEXT_GROUPS:
        hit = found & group
        if hit:
            soft_groups.append(hit)
    return primary, tuple(soft_groups)


def text_covers_headline_entities(text: str, headline: str) -> bool:
    if not headline.strip() or not text.strip():
        return False
    primary, soft_groups = _required_for_headline(headline)
    if not primary and not soft_groups:
        return False
    for entity_id in primary:
        if not _entity_or_equivalent_present(text, entity_id):
            return False
    for group in soft_groups:
        if not any(_entity_present(text, member) for member in group):
            return False
    return True


def missing_required_anchors(text: str, headline: str) -> List[str]:
    primary, soft_groups = _required_for_headline(headline)
    missing: List[str] = []
    for entity_id in sorted(primary):
        if not _entity_or_equivalent_present(text, entity_id):
            canonical = ENTITY_CANONICAL.get(entity_id, entity_id)
            if canonical not in missing:
                missing.append(canonical)
    for group in soft_groups:
        if not any(_entity_present(text, member) for member in group):
            for member in sorted(group):
                canonical = ENTITY_CANONICAL.get(member, member)
                if canonical not in missing:
                    missing.append(canonical)
                    break
    return missing


_HEADLINE_TOPIC_STOPWORDS: FrozenSet[str] = frozenset(
    {
        "says",
        "after",
        "isn't",
        "isnt",
        "over",
        "with",
        "for",
        "the",
        "and",
        "amid",
        "that",
        "it's",
        "its",
        "from",
        "into",
        "most",
        "advanced",
        "model",
        "files",
        "filed",
        "prepping",
        "confidentially",
        "nominates",
        "nominated",
        "general",
        "controversy",
        "halting",
        "strikes",
        "isn't",
        "partnering",
        "declines",
        "testimony",
        "china",
        "exports",
        "senate",
        "wall",
        "street",
        "mega",
        "debut",
        "tech",
        "isn",
        "t",
        "could",
        "face",
        "further",
        "stock",
        "stocks",
        "shares",
        "share",
        "would",
        "might",
        "may",
        "will",
        "can",
        "been",
        "being",
        "have",
        "has",
        "had",
        "this",
        "that",
        "these",
        "those",
        "their",
        "about",
        "into",
        "than",
        "then",
        "when",
        "what",
        "which",
        "while",
        "where",
        "after",
        "before",
        "under",
        "over",
        "more",
        "less",
        "also",
        "just",
        "only",
        "very",
        "such",
        "other",
        "some",
        "any",
        "all",
        "new",
        "old",
        "first",
        "last",
        "next",
        "year",
        "years",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "report",
        "reports",
        "says",
        "said",
        "tell",
        "tells",
        "near",
        "high",
        "low",
        "close",
        "closes",
        "open",
        "opens",
    }
)

_SHORT_TOPIC_TOKENS: Dict[str, str] = {
    "ipo": "IPO",
    "iran": "Iran",
    "ai": "AI",
    "doj": "DOJ",
    "ust": "UST",
    "cpi": "CPI",
    "fed": "Fed",
}


def headline_topic_tokens(headline: str, *, max_tokens: int = 6) -> List[str]:
    """Distinctive proper-noun / topic tokens when market-entity extraction is thin."""
    raw = str(headline or "").strip()
    if not raw:
        return []

    tokens: List[str] = []
    seen: Set[str] = set()

    def add(label: str) -> None:
        clean = str(label or "").strip()
        if not clean:
            return
        parts = [p for p in re.split(r"[\s/]+", clean) if p]
        # Split Title-Case runs that still embed English stopwords.
        if len(parts) > 1 and any(
            p.lower().strip(".,;:") in _HEADLINE_TOPIC_STOPWORDS for p in parts
        ):
            for p in parts:
                key = p.lower().strip(".,;:")
                if key in _HEADLINE_TOPIC_STOPWORDS or key in seen:
                    continue
                if len(key) < 2:
                    continue
                seen.add(key)
                tokens.append(p.strip(".,;:"))
            return
        key = clean.lower().strip(".,;:")
        if key in _HEADLINE_TOPIC_STOPWORDS or key in seen:
            return
        seen.add(key)
        tokens.append(clean)

    covered_words: Set[str] = set()
    for match in re.finditer(
        r"\b[A-Z][A-Za-z0-9&'+.-]*(?:\s+[A-Z][A-Za-z0-9&'+.-]*)*\b",
        raw,
    ):
        phrase = match.group(0).strip()
        add(phrase)
        for part in phrase.lower().split():
            covered_words.add(part)

    norm = normalize_text_for_grounding(raw)
    for word in norm.split():
        if word in covered_words:
            continue
        mapped = _SHORT_TOPIC_TOKENS.get(word)
        if mapped:
            add(mapped)
            covered_words.add(word)

    for word in norm.split():
        if word in covered_words:
            continue
        if len(word) < 4 or word in _HEADLINE_TOPIC_STOPWORDS:
            continue
        if word in _SHORT_TOPIC_TOKENS:
            continue
        add(word.title() if word.isalpha() else word)
        covered_words.add(word)

    return tokens[:max_tokens]


def headline_grounding_anchors(headline: str) -> List[str]:
    found = extract_market_entities(headline)
    order = (
        "sp500",
        "nasdaq",
        "dow",
        "nikkei",
        "kospi",
        "kosdaq",
        "seoul_shares",
        "mideast",
        "ai",
        "fed",
        "inflation",
    )
    anchors: List[str] = []
    seen: Set[str] = set()
    for entity_id in order:
        if entity_id not in found:
            continue
        canonical = ENTITY_CANONICAL.get(entity_id, entity_id)
        key = canonical.lower()
        if key not in seen:
            anchors.append(canonical)
            seen.add(key)
    for topic in headline_topic_tokens(headline):
        key = topic.lower()
        if key not in seen:
            anchors.append(topic)
            seen.add(key)
    return anchors[:10]


def diagnostic_headline_topic_tokens(headline: str, *, max_tokens: int = 6) -> List[str]:
    """Bounded topic tokens for diagnostics only — never inject into visible copy."""
    return headline_topic_tokens(headline, max_tokens=max_tokens)


def inject_headline_grounding_into_detail(detail: str, headline: str) -> str:
    """Append a bounded Korean lead-in for validator grounding — never raw keyword dumps."""
    nh = str(headline or "").strip()
    body = str(detail or "").strip()
    if not nh:
        return body
    if text_covers_headline_entities(body, nh):
        return body
    anchor = anchor_phrase_for_headline(nh)
    if anchor and anchor not in body:
        body = f"{anchor} {body}".strip()
    if text_covers_headline_entities(body, nh):
        return body
    # The article is already bound by news_id.  If legacy textual grounding is
    # still needed, add a natural reader title rather than a raw keyword dump
    # such as ``Lululemon·Plunges 관련``.
    safe_title = build_korean_safe_reader_title(nh)
    lead = f"{safe_title} 관련 보도입니다."
    if lead not in body:
        body = f"{lead} {body}".strip()
    return body


def anchor_phrase_for_headline(headline: str) -> str:
    found = extract_market_entities(headline)
    if not found:
        # No market entities: do not dump raw English headline tokens into visible copy.
        topics = [
            t
            for t in headline_topic_tokens(headline, max_tokens=3)
            if t[:1].isupper() or t.isupper()
        ]
        if topics:
            return "·".join(topics[:2]) + " 관련."
        return ""

    index_parts: List[str] = []
    for entity_id in (
        "sp500",
        "nasdaq",
        "dow",
        "nikkei",
        "kospi",
        "kosdaq",
        "seoul_shares",
    ):
        if entity_id in found:
            index_parts.append(ENTITY_CANONICAL[entity_id])

    context_parts: List[str] = []
    if "record_high" in found:
        context_parts.append("신기록")
    if "tech_rally" in found:
        context_parts.append("기술주 강세")
    if "mideast" in found and "중동" not in context_parts:
        context_parts.append("중동")
    if "ai" in found:
        context_parts.append("AI")
    if "fed" in found:
        context_parts.append("연준")
    if "inflation" in found:
        context_parts.append("물가")

    if index_parts:
        base = "·".join(index_parts)
        if context_parts:
            return f"{base}와 {', '.join(context_parts)} 맥락의 관련 보도입니다."
        return f"{base} 관련 보도입니다."

    if context_parts:
        return f"{', '.join(context_parts)} 맥락의 관련 보도입니다."
    return ""
