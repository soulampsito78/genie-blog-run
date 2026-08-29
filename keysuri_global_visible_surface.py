"""Deterministic visible-surface guards for the KeeSuri Global briefing.

Forensic origin — 2026-08-14 12:30 KST natural Global run
``20260814_123001_keysuri_global_tech_089c413b`` (revision
``genie-blog-run-00295-8xl`` @ ``260bfc0``) delivered an owner-review email with
``validation_result="pass"`` and ``issue_codes=[]`` while the visible surface
carried eight distinct defects. Every existing Global validator is either an
ellipsis/token-repair walker or a *literal* blacklist of phrases seen in an
earlier incident, so none of the following could fire:

1. subject/title cut mid-quote (``OpenAI introduces 'Ultrafast``) — the existing
   ``contains_dangling_quoted_title_fragment`` only inspects the *last*
   character inside ``「」``, never quote-mark balance;
2. raw English source prose in Korean explanatory fields — no language-surface
   rule existed at all;
3. source-pack scaffolding (``Public tech source (X) published:``) rendered to
   the customer — that string is built in ``keysuri_live_source_smoke`` as an
   internal claim field and was never on any blacklist;
4. semantically truncated feed excerpts that end on a syntactically valid
   period (``…an era in which companies.``);
5. per-item padding templates repeated across TOP5 — the existing repeat check
   counts *whole* sentences, and the padding builder prefixes each one with a
   per-item subject, so no two sentences are ever byte-identical;
6. deep-dive text that re-states ``opening_lead`` verbatim;
7. category labels that contradict the item's own category evidence;
8. Korean subject particles chosen without checking the preceding jongseong
   (``정책·규제·자본·공급망가``).

Everything here is deterministic string/structure analysis — no model calls, no
embeddings, no network. Detectors are written to be *narrow*: they key on the
pipeline's own assembled template families and on provenance evidence carried in
the item, not on open-ended style scoring.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED",
    "GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED",
    "GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED",
    "GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED",
    "GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED",
    "GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL",
    "GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED",
    "GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH",
    "GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT",
    "KOREAN_EXPLANATORY_FIELDS",
    "SOURCE_TITLE_FIELDS",
    "korean_subject_particle",
    "attach_korean_subject_particle",
    "balance_quote_marks",
    "title_integrity_issues",
    "internal_template_leak_hits",
    "raw_english_prose_hits",
    "semantic_truncation_hits",
    "sentence_skeleton",
    "repeated_skeleton_hits",
    "deep_dive_duplication_ratio",
    "category_grounding_mismatches",
    "korean_particle_defects",
    "evaluate_global_visible_surface",
]

# --- issue codes -----------------------------------------------------------

GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED = "global_visible_subject_integrity_blocked"
GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED = "global_visible_internal_template_leak_blocked"
GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED = "global_visible_raw_english_prose_blocked"
GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED = "global_visible_semantic_truncation_blocked"
GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED = "global_visible_repeated_template_skeleton_blocked"

GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL = "global_visible_repeated_low_information_label"
GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED = "global_visible_deep_dive_duplication_blocked"
GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH = "global_visible_category_grounding_mismatch"
GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT = "global_visible_korean_particle_defect"

# --- field taxonomy --------------------------------------------------------

#: Customer-visible fields that must read as Korean editorial prose.
KOREAN_EXPLANATORY_FIELDS: Tuple[str, ...] = (
    "what_happened",
    "why_now",
    "why_it_matters",
    "owner_angle",
    "business_implication",
    "selection_reason",
    "next_watch",
    "one_line_summary",
)

#: Fields that legitimately display a source title verbatim, in any language.
SOURCE_TITLE_FIELDS: Tuple[str, ...] = (
    "headline",
    "title",
    "korean_title",
    "news_title",
    "source",
    "source_name",
    "url",
    "canonical_url",
    "normalized_title",
)

_WS_RE = re.compile(r"\s+")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return _WS_RE.sub(" ", str(value)).strip()


# ---------------------------------------------------------------------------
# Korean subject particle (조사) — jongseong-aware
# ---------------------------------------------------------------------------

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3

#: Latin letters / digits whose Korean *reading* ends on a final consonant.
_LATIN_READING_HAS_FINAL = {
    "l", "m", "n", "r", "g", "k", "b", "p", "t", "d", "c", "x", "s", "z", "h",
    "0", "1", "3", "6", "7", "8",
}
_LATIN_READING_NO_FINAL = {"a", "e", "i", "o", "u", "y", "f", "j", "q", "v", "w",
                           "2", "4", "5", "9"}


def _last_meaningful_char(text: str) -> str:
    for char in reversed(_text(text)):
        if char.isalnum() or _HANGUL_BASE <= ord(char) <= _HANGUL_LAST:
            return char
    return ""


def _has_final_consonant(text: str) -> Optional[bool]:
    """True/False when decidable, None when the ending gives no signal."""
    char = _last_meaningful_char(text)
    if not char:
        return None
    code = ord(char)
    if _HANGUL_BASE <= code <= _HANGUL_LAST:
        return (code - _HANGUL_BASE) % 28 != 0
    lowered = char.lower()
    if lowered in _LATIN_READING_HAS_FINAL:
        return True
    if lowered in _LATIN_READING_NO_FINAL:
        return False
    return None


def korean_subject_particle(
    subject: str,
    *,
    with_final: str = "이",
    without_final: str = "가",
) -> str:
    """Pick the Korean particle that agrees with ``subject``'s last syllable.

    Returns ``without_final`` when the ending gives no signal (a closing
    ``」``/``'`` or punctuation), which matches the historical rendering for
    quoted-title subjects and keeps the change behaviour-preserving there.
    """
    final = _has_final_consonant(subject)
    if final is None:
        return without_final
    return with_final if final else without_final


def attach_korean_subject_particle(
    subject: str,
    *,
    with_final: str = "이",
    without_final: str = "가",
) -> str:
    """``subject`` + agreeing particle, e.g. ``공급망`` -> ``공급망이``."""
    subject = _text(subject)
    if not subject:
        return subject
    return subject + korean_subject_particle(
        subject, with_final=with_final, without_final=without_final
    )


# ---------------------------------------------------------------------------
# Phase 5 — title / subject integrity
# ---------------------------------------------------------------------------

#: Paired delimiters whose halves must balance in customer-visible text.
_PAIRED_QUOTES: Tuple[Tuple[str, str], ...] = (
    ("‘", "’"),  # ‘ ’
    ("“", "”"),  # “ ”
    ("「", "」"),  # 「 」
    ("『", "』"),  # 『 』
    ("〈", "〉"),  # 〈 〉
    ("《", "》"),  # 《 》
    ("(", ")"),
    ("[", "]"),
)

#: Trailing characters that mean the text was cut, not finished.
_DANGLING_TAIL_RE = re.compile(
    r"[‘“「『〈《(\[,·–—\-/&+]\s*$"
)

#: Korean connective particles that cannot legitimately end a title.
_DANGLING_KO_PARTICLE_RE = re.compile(r"(?:와|과|의|를|을|이|가|은|는|로|으로|및)\s*$")


def _straight_double_quote_unbalanced(text: str) -> bool:
    return text.count('"') % 2 == 1


def _is_word_internal(blob: str, idx: int) -> bool:
    before = blob[idx - 1] if idx > 0 else ""
    after = blob[idx + 1] if idx + 1 < len(blob) else ""
    return before.isalnum() and after.isalnum()


def _delimiter_positions(blob: str, mark: str) -> List[int]:
    """Positions of ``mark``, skipping word-internal use.

    U+2019 is both the closing single quote and the English typographic
    apostrophe: ``The builder’s guide`` must not read as an unbalanced quote.
    """
    return [
        idx
        for idx, char in enumerate(blob)
        if char == mark and not (mark in "’‘'" and _is_word_internal(blob, idx))
    ]


def _paired_counts(blob: str, opener: str, closer: str) -> Tuple[int, int]:
    return len(_delimiter_positions(blob, opener)), len(_delimiter_positions(blob, closer))


def title_integrity_issues(text: str) -> List[str]:
    """Structural defects in a customer-visible title/subject.

    Deliberately tolerant of apostrophes — ``don't``, ``builder’s`` and
    ``Apple’s`` are ordinary English and must keep passing.
    """
    blob = _text(text)
    if not blob:
        return []
    issues: List[str] = []
    for opener, closer in _PAIRED_QUOTES:
        opens, closes = _paired_counts(blob, opener, closer)
        if opens != closes:
            issues.append(f"unbalanced_quote:{opener}{closer}:{opens}/{closes}")
    if _straight_double_quote_unbalanced(blob):
        issues.append('unbalanced_quote:"":odd')
    if _DANGLING_TAIL_RE.search(blob):
        issues.append("dangling_punctuation")
    if _DANGLING_KO_PARTICLE_RE.search(blob):
        issues.append("dangling_korean_particle")
    return issues


def balance_quote_marks(text: str) -> str:
    """Drop unmatched paired delimiters left behind by a truncating split.

    Structural repair for the two deterministic shorteners that cut an English
    title on a comma (``_shorten_core`` / ``_natural_korean_subject_phrase``):
    an opener with no partner inside the kept span is removed rather than
    rendered as ``OpenAI introduces 'Ultrafast``.
    """
    blob = str(text or "")
    if not blob:
        return blob
    for opener, closer in _PAIRED_QUOTES:
        for _ in range(8):
            opens = _delimiter_positions(blob, opener)
            closes = _delimiter_positions(blob, closer)
            if len(opens) == len(closes):
                break
            # Word-internal apostrophes are never candidates for removal.
            drop = opens[-1] if len(opens) > len(closes) else closes[-1]
            blob = blob[:drop] + blob[drop + 1:]
    if blob.count('"') % 2 == 1:
        blob = blob.replace('"', "", 1)
    return _WS_RE.sub(" ", blob).strip().rstrip(",·-–— ")


# ---------------------------------------------------------------------------
# Phase 7 — internal implementation-language leakage
# ---------------------------------------------------------------------------

#: Internal scaffolding strings. Every entry is implementation language that a
#: customer must never read; ordinary editorial prose never contains them.
_INTERNAL_TEMPLATE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("public_tech_source_published", re.compile(r"public\s+tech\s+source\s*\(", re.I)),
    ("source_published_colon", re.compile(r"\b(?:published|publishes)\s*:", re.I)),
    ("source_summary_colon", re.compile(r"\bsource\s+summary\s*:", re.I)),
    ("public_summary_colon", re.compile(r"\bpublic\s+summary\s*:", re.I)),
    ("feed_metadata_colon", re.compile(r"\b(?:feed|rss)\s+(?:item|metadata)\s*:", re.I)),
    ("claim_statement_colon", re.compile(r"\bclaim\s+statement\s*:", re.I)),
    ("owner_review_only", re.compile(r"owner-?review only", re.I)),
    ("not_customer_final", re.compile(r"not\s+customer-?final", re.I)),
)


def internal_template_leak_hits(text: str) -> List[str]:
    blob = _text(text)
    if not blob:
        return []
    return [name for name, pattern in _INTERNAL_TEMPLATE_PATTERNS if pattern.search(blob)]


# ---------------------------------------------------------------------------
# Phase 6 — language surface
# ---------------------------------------------------------------------------

_QUOTED_SPAN_RE = re.compile(
    r"「[^」]*」|『[^』]*』|“[^”]*”|‘[^’]*’|\"[^\"]*\""
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’.\-]*")

#: Closed-class English words. Proper-noun strings (company/product names) do
#: not string these together; running prose does.
_ENGLISH_FUNCTION_WORDS = frozenset(
    """
    a an the is are was were be been being am
    to of in on at by for from with without into onto over under
    and or but nor so yet than that this these those which who whom whose
    it its they their them we our us you your he she his her
    has have had do does did will would shall should may might can could must
    not no as if when while because about after before during between
    more most less least other another such own same
    """.split()
)

#: A Latin run must be at least this long before it can count as raw prose.
RAW_ENGLISH_MIN_TOKENS = 6
#: ...and carry at least this many closed-class English words.
RAW_ENGLISH_MIN_FUNCTION_WORDS = 2


def _strip_allowed_english(text: str) -> str:
    """Remove spans where English is legitimate: quoted titles and URLs."""
    blob = _URL_RE.sub(" ", str(text or ""))
    return _QUOTED_SPAN_RE.sub(" ", blob)


def _latin_runs(text: str) -> List[List[str]]:
    """Maximal Latin token runs, split wherever Hangul intervenes."""
    runs: List[List[str]] = []
    for chunk in _HANGUL_RE.split(text):
        tokens = _LATIN_TOKEN_RE.findall(chunk)
        if tokens:
            runs.append(tokens)
    return runs


def raw_english_prose_hits(text: str) -> List[Dict[str, Any]]:
    """Raw English *sentences* inside a Korean explanatory field.

    Quoted source titles, URLs, and short proper-noun phrases are allowed; a
    long run of English carrying closed-class function words is running prose
    and must not be customer-visible in a Korean section.
    """
    stripped = _strip_allowed_english(text)
    if not stripped.strip():
        return []
    hits: List[Dict[str, Any]] = []
    for tokens in _latin_runs(stripped):
        if len(tokens) < RAW_ENGLISH_MIN_TOKENS:
            continue
        function_hits = [tok for tok in tokens if tok.lower().strip(".'’") in _ENGLISH_FUNCTION_WORDS]
        if len(function_hits) < RAW_ENGLISH_MIN_FUNCTION_WORDS:
            continue
        hits.append(
            {
                "token_count": len(tokens),
                "function_word_count": len(function_hits),
                "excerpt": " ".join(tokens)[:160],
            }
        )
    return hits


# ---------------------------------------------------------------------------
# Phase 9 — provenance-aware truncation
# ---------------------------------------------------------------------------

_TERMINAL_PUNCT = tuple(".!?。！？")
_CLOSING_AFTER_TERMINAL = tuple("\"'’”)]}」』")

#: ``…from an era in which companies.`` — a preposition+``which`` clause whose
#: body is a bare noun. Narrow on purpose: short sentences are not blocked.
_DANGLING_RELATIVE_RE = re.compile(
    r"\b(?:in|of|from|to|by|with|on|at|for|where)\s+which\s+[A-Za-z][A-Za-z\-]*\s*[.]\s*$",
    re.I,
)
#: A sentence ending on a bare coordinator/preposition before the period.
_DANGLING_CONNECTIVE_RE = re.compile(
    r"\b(?:and|or|but|with|from|into|onto|of|for|that|which|because|while|including)\s*[.]\s*$",
    re.I,
)

#: Tail length (words) used to test whether visible text reproduces a clipped
#: source excerpt.
_CLIPPED_TAIL_WORDS = 5


#: Minimum words after the excerpt's last sentence boundary before the
#: remainder counts as a mid-sentence cut rather than an unpunctuated summary.
_CLIPPED_TAIL_MIN_WORDS = 4


def source_excerpt_is_clipped(snippet: Any) -> bool:
    """True when the *source* excerpt itself was cut mid-sentence.

    Requires a completed sentence *before* the unterminated remainder. A short
    single-sentence RSS summary that simply lacks a final period (very common,
    e.g. ``Company has also published a 300-page whitepaper to support the
    project``) is therefore not treated as truncated.
    """
    blob = _text(snippet)
    if len(blob) < 40:
        return False
    tail = blob.rstrip()
    while tail and tail[-1] in _CLOSING_AFTER_TERMINAL:
        tail = tail[:-1]
    if not tail or tail.endswith(_TERMINAL_PUNCT):
        return False
    boundaries = [m.end() for m in re.finditer(r"[.!?。！？][\"'’”)\]}」』]*\s", tail)]
    if not boundaries:
        return False
    remainder = tail[boundaries[-1]:]
    return len(_normalized_words(remainder)) >= _CLIPPED_TAIL_MIN_WORDS


def _normalized_words(text: str) -> List[str]:
    return [w for w in re.split(r"[^\w'’\-]+", _text(text).lower()) if w]


def semantic_truncation_hits(text: str, *, source_excerpt: Any = None) -> List[Dict[str, Any]]:
    """Visible text that is syntactically sentence-final but semantically cut.

    Two independent, conservative signals:

    ``source_clipped_tail_reproduced``
        provenance — the source excerpt itself ends mid-clause (feed/read-more
        clipping) and the visible text reproduces that clipped tail;
    ``dangling_relative_clause`` / ``dangling_connective``
        lexical — the sentence ends on a relative/coordinating construction
        with nothing after it.
    """
    blob = _text(text)
    if not blob:
        return []
    hits: List[Dict[str, Any]] = []
    if source_excerpt is not None and source_excerpt_is_clipped(source_excerpt):
        tail_words = _normalized_words(source_excerpt)[-_CLIPPED_TAIL_WORDS:]
        if len(tail_words) >= 3:
            visible_words = _normalized_words(blob)
            joined = " ".join(visible_words)
            if " ".join(tail_words) in joined:
                hits.append(
                    {
                        "signal": "source_clipped_tail_reproduced",
                        "excerpt": " ".join(tail_words)[:120],
                    }
                )
    for sentence in re.split(r"(?<=[.!?。！？])\s+", blob):
        candidate = sentence.strip()
        if not candidate:
            continue
        if _DANGLING_RELATIVE_RE.search(candidate):
            hits.append({"signal": "dangling_relative_clause", "excerpt": candidate[-90:]})
        elif _DANGLING_CONNECTIVE_RE.search(candidate):
            hits.append({"signal": "dangling_connective", "excerpt": candidate[-90:]})
    return hits


# ---------------------------------------------------------------------------
# Phase 11 — repeated template skeletons
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")

#: Trailing-character window used as a sentence's "skeleton". The padding
#: builder varies only the *leading* subject, so the invariant is the tail.
SKELETON_TAIL_CHARS = 18
#: A skeleton must be at least this long to be considered distinctive.
SKELETON_MIN_CHARS = 12
#: Distinct TOP5 items that must share a skeleton before it blocks.
REPEATED_SKELETON_ITEM_THRESHOLD = 3


def sentence_skeleton(sentence: str) -> str:
    """Sentence tail with volatile leading material removed."""
    blob = _text(sentence)
    if not blob:
        return ""
    blob = re.sub(r"\s+", "", blob)
    blob = blob.rstrip("." "!?。！？")
    if len(blob) < SKELETON_MIN_CHARS:
        return ""
    return blob[-SKELETON_TAIL_CHARS:]


def _visible_sentences(value: Any) -> List[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(_text(value)) if s.strip()]


def repeated_skeleton_hits(
    items: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] = KOREAN_EXPLANATORY_FIELDS,
    threshold: int = REPEATED_SKELETON_ITEM_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Same sentence skeleton reused across ``threshold``+ distinct TOP5 items."""
    by_skeleton: Dict[str, set] = {}
    example: Dict[str, str] = {}
    for idx, item in enumerate(items or []):
        if not isinstance(item, Mapping):
            continue
        rank = item.get("rank") or idx + 1
        for field in fields:
            for sentence in _visible_sentences(item.get(field)):
                skeleton = sentence_skeleton(sentence)
                if not skeleton:
                    continue
                by_skeleton.setdefault(skeleton, set()).add(rank)
                example.setdefault(skeleton, sentence)
    hits = [
        {
            "skeleton": skeleton,
            "item_count": len(ranks),
            "ranks": sorted(ranks),
            "excerpt": example.get(skeleton, "")[:140],
        }
        for skeleton, ranks in by_skeleton.items()
        if len(ranks) >= threshold
    ]
    hits.sort(key=lambda h: (-h["item_count"], h["skeleton"]))
    return hits


#: Low-information judgment labels repeated across the visible surface.
LOW_INFORMATION_LABEL_THRESHOLD = 3
_JUDGMENT_LABEL_RE = re.compile(r"키수리\s*판단\s*([가-힣]{2,6})")


def repeated_low_information_labels(
    plain_text: str,
    *,
    threshold: int = LOW_INFORMATION_LABEL_THRESHOLD,
) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for label in _JUDGMENT_LABEL_RE.findall(_text(plain_text)):
        counts[label] = counts.get(label, 0) + 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items())
        if count >= threshold
    ]


# ---------------------------------------------------------------------------
# Phase 12 — deep-dive non-duplication
# ---------------------------------------------------------------------------

#: Fraction of deep-dive body characters that may be re-used from elsewhere.
DEEP_DIVE_DUPLICATION_THRESHOLD = 0.5


def _normalize_for_duplication(text: str) -> str:
    blob = unicodedata.normalize("NFKC", _text(text)).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", blob)


def deep_dive_duplication_ratio(
    deep_dive_body: Any,
    other_texts: Iterable[Any],
) -> Tuple[float, List[str]]:
    """Share of the deep-dive body that merely restates earlier sections.

    Sentence-level exact match after aggressive normalization — cheap, stable,
    and free of any embedding/API dependency.
    """
    sentences = _visible_sentences(deep_dive_body)
    if not sentences:
        return 0.0, []
    elsewhere = {
        _normalize_for_duplication(sentence)
        for text in other_texts
        for sentence in _visible_sentences(text)
        if _normalize_for_duplication(sentence)
    }
    total = 0
    duplicated = 0
    matched: List[str] = []
    for sentence in sentences:
        normalized = _normalize_for_duplication(sentence)
        if not normalized:
            continue
        total += len(normalized)
        if normalized in elsewhere:
            duplicated += len(normalized)
            matched.append(sentence[:120])
    if not total:
        return 0.0, []
    return duplicated / total, matched


# ---------------------------------------------------------------------------
# Phase 8 — category grounding coherence
# ---------------------------------------------------------------------------

#: The English business-implication sentence is generated *from* a category in
#: ``keysuri_live_source_smoke._business_implication``. When it disagrees with
#: the item's rendered category the item carries two different classifications.
_IMPLICATION_CATEGORY_MARKERS: Tuple[Tuple[str, str], ...] = (
    ("ai_software_platform", "AI/software/platform shifts"),
    ("semiconductor_chip_infra", "Chip and AI infrastructure signals"),
    ("semiconductor_equipment_materials", "Equipment/materials moves"),
    ("robotics_automation_manufacturing", "Robotics/automation adoption"),
    ("battery_ev_energy_grid", "Battery/EV/energy signals"),
    ("aerospace_satellite_defense_tech", "Aerospace/defense tech"),
    ("hardware_device_display", "Device/display shifts"),
    ("cybersecurity_cloud_datacenter", "Security/cloud/datacenter moves"),
    ("policy_regulation_capital_supplychain", "Policy/capital/supply-chain moves"),
)


def _implied_category(text: str) -> str:
    blob = _text(text)
    for category, marker in _IMPLICATION_CATEGORY_MARKERS:
        if marker.lower() in blob.lower():
            return category
    return ""


def _item_category(item: Mapping[str, Any]) -> str:
    for key in ("primary_category", "category"):
        value = _text(item.get(key))
        if value:
            return value
    return ""


def category_grounding_mismatches(
    items: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Items whose rendered category contradicts their own category evidence."""
    mismatches: List[Dict[str, Any]] = []
    for idx, item in enumerate(items or []):
        if not isinstance(item, Mapping):
            continue
        category = _item_category(item)
        if not category:
            continue
        evidence = " ".join(
            _text(item.get(field))
            for field in ("business_implication", "owner_angle", "why_it_matters")
        )
        implied = _implied_category(evidence)
        if implied and implied != category:
            mismatches.append(
                {
                    "rank": item.get("rank") or idx + 1,
                    "news_id": _text(item.get("news_id")),
                    "rendered_category": category,
                    "evidence_category": implied,
                    "category_label_ko": _text(item.get("category_label_ko")),
                }
            )
    return mismatches


# ---------------------------------------------------------------------------
# Phase 10 — Korean assembly sanity
# ---------------------------------------------------------------------------

#: Assembled template tails that follow a subject + subject-particle. Only the
#: pipeline's own deterministic families are checked — this is not a grammar
#: engine and never inspects free model prose.
_PARTICLE_TEMPLATE_TAILS: Tuple[str, ...] = (
    "실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다",
    "실제 비용, 계약, 일정 변화로 이어지는지가 판단 기준입니다",
)
_SUBJECT_PARTICLE_RE = re.compile(r"([가-힣A-Za-z0-9])(이|가)\s+(?=실제)")


def korean_particle_defects(text: str) -> List[Dict[str, Any]]:
    """Particles that disagree with the preceding noun's final consonant.

    Previously this covered only 이/가 and only inside a few template tails,
    which is why "흐름와" and "후속를" reached the owner's Gmail on 2026-08-29.
    It now delegates to the shared particle contract, which covers 을/를, 과/와,
    이/가, 은/는 and 으로/로 including the ㄹ exception, and which refuses to
    judge a noun ending in Latin, a digit or a bracket rather than guessing its
    pronunciation.
    """
    from keysuri_korean_particles import particle_findings

    blob = _text(text)
    if not blob:
        return []
    return [
        {
            "stem": str(finding["stem"]),
            "token": str(finding["token"]),
            "particle": str(finding["actual_particle"]),
            "expected": str(finding["expected_particle"]),
            "corrected": str(finding["corrected_token"]),
            "excerpt": str(finding["sentence"])[:120],
        }
        for finding in particle_findings(blob)
    ]


# ---------------------------------------------------------------------------
# Phase 13 — severity policy + aggregate entry point
# ---------------------------------------------------------------------------

#: Issue code -> severity. BLOCK stops the owner-review send; REVIEW is
#: recorded on the artifact for the owner but does not stop delivery.
GLOBAL_VISIBLE_SEVERITY: Dict[str, str] = {
    GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED: "block",
    GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED: "block",
    GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED: "block",
    GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED: "block",
    GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED: "block",
    # REVIEW, not BLOCK: 관찰/기회/경계 is a small closed taxonomy, so a quiet
    # day can legitimately mark every TOP5 item 관찰. Blocking here would make
    # Global unusable; the owner still sees the repetition on the artifact.
    GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL: "review",
    GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED: "block",
    GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH: "review",
    # BLOCK, not REVIEW: this fires only on deterministic Hangul agreement
    # errors, which are corrected automatically upstream. Anything still present
    # here survived that correction and is simply wrong Korean.
    GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT: "block",
}


def _finding(code: str, *, section: str, detail: str, excerpt: str = "") -> Dict[str, Any]:
    return {
        "issue_code": code,
        "severity": GLOBAL_VISIBLE_SEVERITY.get(code, "review"),
        "section": section,
        "detail": detail,
        "excerpt": excerpt[:160],
    }


def evaluate_global_visible_surface(
    *,
    subject: Any = "",
    items: Optional[Sequence[Mapping[str, Any]]] = None,
    deep_dive: Optional[Mapping[str, Any]] = None,
    opening_lead: Any = "",
    plain_text: Any = "",
    evidence_items: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate the whole customer-visible Global surface.

    Returns ``{"ok", "blocked", "issue_codes", "findings", "diagnostics"}``.
    ``ok`` is False when any BLOCK-severity finding is present; REVIEW findings
    are reported without stopping delivery.
    """
    items = [i for i in (items or []) if isinstance(i, Mapping)]
    findings: List[Dict[str, Any]] = []

    # --- title / subject integrity ---------------------------------------
    for issue in title_integrity_issues(subject):
        findings.append(
            _finding(
                GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED,
                section="subject",
                detail=issue,
                excerpt=_text(subject),
            )
        )
    for idx, item in enumerate(items):
        rank = item.get("rank") or idx + 1
        for field in ("headline", "korean_title", "title"):
            value = _text(item.get(field))
            if not value:
                continue
            for issue in title_integrity_issues(value):
                # A source headline is displayed verbatim; only an *unbalanced*
                # quote is a defect there, dangling punctuation is not.
                if not issue.startswith("unbalanced_quote"):
                    continue
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED,
                        section=f"top5[{rank}].{field}",
                        detail=issue,
                        excerpt=value,
                    )
                )

    # --- per-item field scans --------------------------------------------
    for idx, item in enumerate(items):
        rank = item.get("rank") or idx + 1
        source_excerpt = item.get("summary")
        for field in KOREAN_EXPLANATORY_FIELDS:
            value = _text(item.get(field))
            if not value:
                continue
            path = f"top5[{rank}].{field}"
            for name in internal_template_leak_hits(value):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
                        section=path,
                        detail=name,
                        excerpt=value,
                    )
                )
            for hit in raw_english_prose_hits(value):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED,
                        section=path,
                        detail=f"tokens={hit['token_count']} function_words={hit['function_word_count']}",
                        excerpt=hit["excerpt"],
                    )
                )
            for hit in semantic_truncation_hits(
                value, source_excerpt=source_excerpt if field == "what_happened" else None
            ):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED,
                        section=path,
                        detail=hit["signal"],
                        excerpt=hit["excerpt"],
                    )
                )
            for defect in korean_particle_defects(value):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT,
                        section=path,
                        detail=f"{defect['stem']}{defect['particle']} -> {defect['stem']}{defect['expected']}",
                        excerpt=defect["excerpt"],
                    )
                )

    # --- cross-item repetition -------------------------------------------
    skeleton_hits = repeated_skeleton_hits(items)
    for hit in skeleton_hits:
        findings.append(
            _finding(
                GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED,
                section="top5",
                detail=f"skeleton reused by {hit['item_count']} items (ranks {hit['ranks']})",
                excerpt=hit["excerpt"],
            )
        )
    label_hits = repeated_low_information_labels(plain_text)
    for hit in label_hits:
        findings.append(
            _finding(
                GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL,
                section="visible_body",
                detail=f"low-information judgment label '{hit['label']}' repeated {hit['count']}×",
                excerpt=hit["label"],
            )
        )

    # --- deep dive --------------------------------------------------------
    deep_dive = deep_dive if isinstance(deep_dive, Mapping) else {}
    deep_body = deep_dive.get("body")
    comparison_texts: List[Any] = [opening_lead]
    for item in items:
        for field in KOREAN_EXPLANATORY_FIELDS:
            comparison_texts.append(item.get(field))
    ratio, matched = deep_dive_duplication_ratio(deep_body, comparison_texts)
    if ratio >= DEEP_DIVE_DUPLICATION_THRESHOLD:
        findings.append(
            _finding(
                GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED,
                section="deep_dive",
                detail=f"{ratio:.0%} of the deep-dive body restates earlier sections",
                excerpt="; ".join(matched)[:160],
            )
        )
    for field in ("body", "uncertainty"):
        value = _text(deep_dive.get(field))
        for name in internal_template_leak_hits(value):
            findings.append(
                _finding(
                    GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
                    section=f"deep_dive.{field}",
                    detail=name,
                    excerpt=value,
                )
            )
        for hit in raw_english_prose_hits(value):
            findings.append(
                _finding(
                    GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED,
                    section=f"deep_dive.{field}",
                    detail=f"tokens={hit['token_count']}",
                    excerpt=hit["excerpt"],
                )
            )
    implications = deep_dive.get("key_implications")
    if isinstance(implications, (list, tuple)):
        for pos, value in enumerate(implications):
            text = _text(value)
            for name in internal_template_leak_hits(text):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
                        section=f"deep_dive.key_implications[{pos}]",
                        detail=name,
                        excerpt=text,
                    )
                )
            for hit in raw_english_prose_hits(text):
                findings.append(
                    _finding(
                        GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED,
                        section=f"deep_dive.key_implications[{pos}]",
                        detail=f"tokens={hit['token_count']}",
                        excerpt=hit["excerpt"],
                    )
                )

    # --- category grounding ----------------------------------------------
    mismatches = category_grounding_mismatches(items)
    for mismatch in mismatches:
        findings.append(
            _finding(
                GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH,
                section=f"top5[{mismatch['rank']}].category",
                detail=(
                    f"rendered={mismatch['rendered_category']} "
                    f"evidence={mismatch['evidence_category']}"
                ),
                excerpt=mismatch["category_label_ko"],
            )
        )

    issue_codes: List[str] = []
    for finding in findings:
        if finding["issue_code"] not in issue_codes:
            issue_codes.append(finding["issue_code"])
    blocked = [f for f in findings if f["severity"] == "block"]
    return {
        "ok": not blocked,
        "blocked": bool(blocked),
        "issue_codes": issue_codes,
        "block_issue_codes": sorted({f["issue_code"] for f in blocked}),
        "findings": findings,
        "diagnostics": {
            "checked_surface": "global_visible_customer_surface",
            "item_count": len(items),
            "deep_dive_duplication_ratio": round(ratio, 4),
            "repeated_skeleton_count": len(skeleton_hits),
            "repeated_label_count": len(label_hits),
            "category_grounding_mismatches": mismatches,
        },
    }
