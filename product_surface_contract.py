"""Deterministic contract for GENIE's final customer-visible copy.

This module intentionally has no delivery side effects and never calls a model.
It separates product/editorial readiness from the runtime safety validator:

* runtime safety decides whether an artifact is usable at all;
* this contract decides whether usable copy is ready for a customer;
* owner-review delivery is controlled elsewhere and is never suppressed here.

All three products cross :func:`prepare_final_customer_copy` immediately before
rendering or persistence.  That boundary is **inspect-only**: this module has no
authority to author, rewrite, summarize, replace or delete customer prose.  It
reports ``CUSTOMER_SURFACE_PASS`` or ``PRODUCT_REVIEW_REQUIRED`` as metadata and
leaves the copy exactly as the grounded generation produced it, so an editorial
defect reaches owner review instead of being papered over with filler.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

TECHNICAL_TEST_PASS = "TECHNICAL_TEST_PASS"
RUNTIME_SAFETY_PASS = "RUNTIME_SAFETY_PASS"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
HARD_FAIL = "HARD_FAIL"
CUSTOMER_SURFACE_PASS = "CUSTOMER_SURFACE_PASS"
PRODUCT_REVIEW_REQUIRED = "PRODUCT_REVIEW_REQUIRED"
RELEASE_REGRESSION_PASS = "RELEASE_REGRESSION_PASS"
RELEASE_REGRESSION_FAIL = "RELEASE_REGRESSION_FAIL"

STRUCTURAL_SIMILARITY_THRESHOLD = 0.82
PRODUCT_SURFACE_DIAGNOSTIC_KEY = "_product_surface_qa"

TRUNCATED_ENGLISH_HEADLINE = "customer_surface_truncated_english_headline"
RAW_ENGLISH_HEADLINE = "customer_surface_raw_english_headline"
INTERNAL_KEYWORD_FRAGMENT = "customer_surface_internal_keyword_fragment"
REPEATED_SENTENCE_SKELETON = "customer_surface_repeated_sentence_skeleton"
REPEATED_CANNED_BRIDGE = "customer_surface_repeated_canned_bridge"
MIXED_SENTENCE_END_STYLE = "customer_surface_mixed_sentence_end_style"
INTERNAL_PLACEHOLDER_LEAK = "customer_surface_internal_placeholder_leak"
DUPLICATE_FILLER = "customer_surface_duplicate_filler"
FABRICATED_GENERIC_READER_TITLE = "customer_surface_fabricated_generic_reader_title"
MISSING_GROUNDED_READER_TITLE = "customer_surface_missing_grounded_reader_title"

# Set by the grounded assembly layer when no grounded Korean reader title or
# fact sentence existed for a card.  The assembly never invents one; it marks
# the card and this contract turns the marker into PRODUCT_REVIEW_REQUIRED.
PRODUCT_REVIEW_MARKER_KEY = "product_review_required"
PRODUCT_REVIEW_REASON_KEY = "product_review_reason"

_TRUNCATED_ENGLISH_RE = re.compile(
    r"(?:^|[\s「『(])(?:[A-Za-z][A-Za-z0-9'’&+.,:/()\-]*\s+){2,}"
    r"[A-Za-z][A-Za-z0-9'’&+.,:/()\-]*(?:…|\.\.\.)(?=$|[\s」』)])"
)
_KEYWORD_FRAGMENT_RE = re.compile(
    r"(?<![가-힣])(?:[A-Za-z][A-Za-z0-9&+._-]*)(?:·[A-Za-z][A-Za-z0-9&+._-]*)+\s*관련(?:[.!?]|$)"
)
_PLACEHOLDER_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{[^{}]+\}\}|\[\[[^\[\]]+\]\]"),
    re.compile(r"\b(?:TODO|TBD|PLACEHOLDER|DEBUG|LOREM IPSUM)\b", re.I),
    re.compile(r"\b(?:news_id|source_id|prompt_status|validation_result)\s*[:=]", re.I),
    re.compile(r"(?:원문\s*키워드|내부\s*검증|모델\s*출력\s*필드)\s*[:：]"),
)
_CANNED_BRIDGES: Tuple[str, ...] = (
    "야간·장전 맥락에서",
    "흐름이 대응 축으로 남아",
    "체크리스트 상단에 남",
    "후속 일정과 공식 발표부터 보면 됩니다",
    "향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다",
)
_PLAIN_END_RE = re.compile(
    r"(?:한다|된다|있다|없다|본다|남는다|정한다|확인한다|살핀다|좋다|이다)\s*[.!?]?$"
)
_POLITE_END_RE = re.compile(
    r"(?:합니다|됩니다|있습니다|없습니다|봅니다|입니다|좋습니다|필요합니다|바랍니다|드립니다|해요|세요)\s*[.!?]?$"
)
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’&+.-]*")

# A reader title is fabricated when the WHOLE title is a fixed generic frame with
# one interchangeable slot: the frame carries no article-specific information, so
# swapping the slot token changes nothing a reader could use.  These patterns
# match the frame, never a specific entity — there is no per-token stopword list
# here, and adding one would only move the same defect somewhere else.
_GENERIC_TITLE_FRAMES: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^\S{1,24}\s*관련\s*시장\s*소식$"),
    re.compile(r"^\S{1,24}\s*주가\s*변동$"),
    re.compile(r"^\S{1,24}\s*관련\s*보도(?:입니다)?[.!?]?$"),
    re.compile(r"^해외시장\s*주요\s*이슈\s*\d*$"),
)
# A manufactured *title* frame spliced into body prose.  Only the title frames
# count here: a grounded entity anchor ("나스닥과 AI 맥락의 보도입니다.") names real
# entities from the headline and is legitimate reader copy, whereas these frames
# carry no article-specific information wherever they appear.
# "주가 변동" must not fire inside ordinary Korean nouns such as "주가 변동성"
# or "주가 변동폭", so the frame has to end the phrase; the other two frames are
# unambiguous manufactured strings.
_GENERIC_FRAME_IN_PROSE_RE = re.compile(
    r"\S{1,24}\s*관련\s*시장\s*소식"
    r"|\S{1,24}\s*주가\s*변동(?![가-힣])"
    r"|해외시장\s*주요\s*이슈\s*\d"
)


def _looks_like_generic_frame_title(text: str) -> bool:
    stripped = _one_line(text)
    return any(pattern.match(stripped) for pattern in _GENERIC_TITLE_FRAMES)


def is_grounded_korean_reader_title(text: Any) -> bool:
    """True when ``text`` is usable as-is as a Korean reader-facing title.

    This is a *selection* predicate for the grounded assembly layer: it decides
    which already-generated candidate to bind to a card.  It never produces a
    title, and there is deliberately no fallback that manufactures one.
    """
    stripped = _one_line(text)
    if len(stripped) < 4 or _hangul_count(stripped) < 2:
        return False
    if _looks_like_generic_frame_title(stripped):
        return False
    if _TRUNCATED_ENGLISH_RE.search(stripped) or _looks_like_truncated_english(stripped):
        return False
    if _looks_like_raw_english_prose(stripped, role="headline"):
        return False
    if _KEYWORD_FRAGMENT_RE.search(stripped):
        return False
    if any(pattern.search(stripped) for pattern in _PLACEHOLDER_PATTERNS):
        return False
    return True


def is_grounded_korean_reader_sentence(text: Any) -> bool:
    """True when ``text`` is usable as-is as Korean reader-facing body prose."""
    stripped = _one_line(text)
    if len(stripped) < 12 or _hangul_count(stripped) < 6:
        return False
    if _GENERIC_FRAME_IN_PROSE_RE.search(stripped):
        return False
    if _TRUNCATED_ENGLISH_RE.search(stripped) or _looks_like_truncated_english(stripped):
        return False
    if _looks_like_raw_english_prose(stripped, role="body"):
        return False
    if _KEYWORD_FRAGMENT_RE.search(stripped):
        return False
    if any(pattern.search(stripped) for pattern in _PLACEHOLDER_PATTERNS):
        return False
    return True


_REPETITION_FIELD_SUFFIXES = (
    ".detail",
    ".what_happened",
    ".summary",
    ".why_now",
    ".why_it_matters",
    ".why_it_matters_today",
)


@dataclass(frozen=True)
class SurfaceField:
    path: str
    text: str
    role: str
    card_index: int = -1


@dataclass(frozen=True)
class ProductSurfaceFinding:
    code: str
    path: str
    message: str
    card_indices: Tuple[int, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "card_indices": list(self.card_indices),
        }


@dataclass(frozen=True)
class ProductSurfaceResult:
    status: str
    findings: Tuple[ProductSurfaceFinding, ...]

    @property
    def customer_ready(self) -> bool:
        return self.status == CUSTOMER_SURFACE_PASS

    def as_dict(self) -> Dict[str, Any]:
        return {
            "customer_surface_status": self.status,
            "customer_ready": self.customer_ready,
            "issue_codes": sorted({finding.code for finding in self.findings}),
            "findings": [finding.as_dict() for finding in self.findings],
            "contract_version": "genie-product-surface-v1",
            "structural_similarity_threshold": STRUCTURAL_SIMILARITY_THRESHOLD,
        }


def runtime_safety_status(validation_result: Any) -> str:
    """Map legacy wire values without changing them."""
    value = str(validation_result or "").strip().lower()
    if value == "pass":
        return RUNTIME_SAFETY_PASS
    if value == "draft_only":
        return REVIEW_REQUIRED
    return HARD_FAIL


def acceptance_status_fields(
    *, validation_result: Any, surface_result: ProductSurfaceResult
) -> Dict[str, Any]:
    return {
        "runtime_safety_status": runtime_safety_status(validation_result),
        "customer_surface_status": surface_result.status,
        "product_surface_issue_codes": sorted(
            {finding.code for finding in surface_result.findings}
        ),
    }


def _one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _split_sentences(text: str) -> List[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?…])\s+|\n+", _one_line(text))
        if part.strip()
    ]


def _hangul_count(text: str) -> int:
    return len(re.findall(r"[가-힣]", text))


def _latin_word_count(text: str) -> int:
    return len(_ENGLISH_WORD_RE.findall(text))


def _looks_like_raw_english_prose(text: str, *, role: str) -> bool:
    stripped = _one_line(text)
    if not stripped or "http://" in stripped or "https://" in stripped:
        return False
    latin_words = _latin_word_count(stripped)
    hangul = _hangul_count(stripped)
    if role in {"headline", "title", "anchor"}:
        return latin_words >= 5 and hangul < 4
    for sentence in _split_sentences(stripped):
        words = _latin_word_count(sentence)
        if words >= 7 and _hangul_count(sentence) < 3:
            return True
    return False


def _looks_like_truncated_english(text: str) -> bool:
    stripped = _one_line(text)
    return bool(
        stripped.endswith(("…", "..."))
        and _latin_word_count(stripped) >= 3
        and _hangul_count(stripped) < 4
    )


def _source_headlines(source_input: Mapping[str, Any] | None) -> List[str]:
    if not isinstance(source_input, Mapping):
        return []
    candidates: List[Any] = []
    for key in ("top_market_news", "top_5_news", "items"):
        value = source_input.get(key)
        if isinstance(value, Mapping):
            value = value.get("items")
        if isinstance(value, list):
            candidates.extend(value)
    out: List[str] = []
    for item in candidates:
        if isinstance(item, Mapping):
            title = _one_line(
                item.get("canonical_headline") or item.get("headline") or item.get("title")
            )
            if title:
                out.append(title)
    return out


def _contains_source_headline(text: str, headlines: Sequence[str]) -> bool:
    compact = _one_line(text).lower()
    for headline in headlines:
        normalized = _one_line(headline).lower()
        if _hangul_count(normalized) >= 4 or _latin_word_count(normalized) < 4:
            continue
        if len(normalized) >= 18 and normalized in compact:
            return True
        # A cut headline followed by an ellipsis is still evidence leakage.
        prefix = normalized[:24].rstrip()
        if len(prefix) >= 18 and prefix in compact and re.search(
            re.escape(prefix) + r"[^가-힣]{0,16}(?:…|\.\.\.)", compact
        ):
            return True
    return False


def _surface_items(mode: str, payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    if mode == "today_genie":
        raw = payload.get("key_watchpoints") or payload.get("top_3_news") or []
    else:
        raw = payload.get("top_5_items") or payload.get("items") or []
        if not raw and isinstance(payload.get("top_5_news"), Mapping):
            raw = payload["top_5_news"].get("items") or []
    return [item for item in raw if isinstance(item, Mapping)]


def _collect_surface_fields(mode: str, payload: Mapping[str, Any]) -> List[SurfaceField]:
    fields: List[SurfaceField] = []
    top_level_roles = {
        "title": "title",
        "summary": "body",
        "greeting": "body",
        "market_setup": "body",
        "closing": "body",
        "closing_message": "body",
        "opening_lead": "body",
        "one_line_checkpoint": "body",
        "selected_title": "title",
        "section_heading": "title",
    }
    for key, role in top_level_roles.items():
        value = _one_line(payload.get(key))
        if value:
            fields.append(SurfaceField(key, value, role))

    item_keys = (
        ("headline", "headline"),
        ("korean_title", "headline"),
        ("detail", "body"),
        ("what_happened", "body"),
        ("summary", "body"),
        ("why_now", "body"),
        ("why_it_matters", "body"),
        ("why_it_matters_today", "body"),
        ("owner_angle", "body"),
        ("business_implication", "body"),
        ("next_watch", "body"),
        ("selection_reason", "body"),
    )
    for index, item in enumerate(_surface_items(mode, payload), start=1):
        for key, role in item_keys:
            value = _one_line(item.get(key))
            if value:
                fields.append(SurfaceField(f"items[{index}].{key}", value, role, index))

    deep_dive = payload.get("deep_dive")
    if isinstance(deep_dive, Mapping):
        for key in ("section_heading", "body"):
            value = _one_line(deep_dive.get(key))
            if value:
                fields.append(
                    SurfaceField(f"deep_dive.{key}", value, "title" if key.endswith("heading") else "body")
                )
    deep_body = _one_line(payload.get("deep_dive_body"))
    if deep_body:
        fields.append(SurfaceField("deep_dive_body", deep_body, "body"))
    return fields


def _sentence_skeleton(sentence: str) -> str:
    value = sentence.lower()
    value = re.sub(r"「[^」]+」|『[^』]+』|\([^)]{2,}\)", " <topic> ", value)
    value = re.sub(r"(?:[A-Za-z][A-Za-z0-9'’&+.,:/()\-]*\s*){2,}", " <topic> ", value)
    value = re.sub(r"\d[\d,.%:/-]*", " <num> ", value)
    value = re.sub(r"[^a-z가-힣<>]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_findings(findings: Iterable[ProductSurfaceFinding]) -> Tuple[ProductSurfaceFinding, ...]:
    seen: set[Tuple[str, str, Tuple[int, ...]]] = set()
    out: List[ProductSurfaceFinding] = []
    for finding in findings:
        key = (finding.code, finding.path, finding.card_indices)
        if key not in seen:
            seen.add(key)
            out.append(finding)
    return tuple(out)


def evaluate_product_surface(
    mode: str,
    structured_output: Mapping[str, Any],
    *,
    source_input: Mapping[str, Any] | None = None,
) -> ProductSurfaceResult:
    """Evaluate only reader-facing fields; identity, URLs and source labels are excluded."""
    fields = _collect_surface_fields(mode, structured_output)
    source_titles = _source_headlines(source_input)
    findings: List[ProductSurfaceFinding] = []

    for field in fields:
        if _TRUNCATED_ENGLISH_RE.search(field.text) or _looks_like_truncated_english(
            field.text
        ):
            findings.append(
                ProductSurfaceFinding(
                    TRUNCATED_ENGLISH_HEADLINE,
                    field.path,
                    "독자면에 잘린 영문 헤드라인이 노출되었습니다.",
                    (field.card_index,) if field.card_index > 0 else (),
                )
            )
        if _looks_like_raw_english_prose(field.text, role=field.role) or _contains_source_headline(
            field.text, source_titles
        ):
            findings.append(
                ProductSurfaceFinding(
                    RAW_ENGLISH_HEADLINE,
                    field.path,
                    "한국어 독자용 필드에 원문 영문 헤드라인/문장이 복사되었습니다.",
                    (field.card_index,) if field.card_index > 0 else (),
                )
            )
        if _KEYWORD_FRAGMENT_RE.search(field.text):
            findings.append(
                ProductSurfaceFinding(
                    INTERNAL_KEYWORD_FRAGMENT,
                    field.path,
                    "내부 키워드 결합 구문이 독자면에 노출되었습니다.",
                    (field.card_index,) if field.card_index > 0 else (),
                )
            )
        if any(pattern.search(field.text) for pattern in _PLACEHOLDER_PATTERNS):
            findings.append(
                ProductSurfaceFinding(
                    INTERNAL_PLACEHOLDER_LEAK,
                    field.path,
                    "placeholder 또는 내부 진단 토큰이 독자면에 노출되었습니다.",
                    (field.card_index,) if field.card_index > 0 else (),
                )
            )
        generic_title = field.role in {"headline", "title", "anchor"} and (
            _looks_like_generic_frame_title(field.text)
        )
        generic_prose = field.role == "body" and bool(
            _GENERIC_FRAME_IN_PROSE_RE.search(field.text)
        )
        if generic_title or generic_prose:
            findings.append(
                ProductSurfaceFinding(
                    FABRICATED_GENERIC_READER_TITLE,
                    field.path,
                    "기사 고유 정보가 없는 일반화 제목 틀이 독자면에 노출되었습니다.",
                    (field.card_index,) if field.card_index > 0 else (),
                )
            )

    # The grounded assembly marks a card when no grounded Korean reader title or
    # fact sentence existed.  It never invents one, so the marker is the only
    # signal that the card needs a human before it can reach a customer.
    for index, item in enumerate(_surface_items(mode, structured_output), start=1):
        if not item.get(PRODUCT_REVIEW_MARKER_KEY):
            continue
        reason = _one_line(item.get(PRODUCT_REVIEW_REASON_KEY)) or "unspecified"
        findings.append(
            ProductSurfaceFinding(
                MISSING_GROUNDED_READER_TITLE,
                f"items[{index}]",
                f"근거 있는 한국어 독자 제목/사실 문장이 없어 검수가 필요합니다: {reason}",
                (index,),
            )
        )

    # Repetition is compared across cards, never between aliases on one card.
    card_sentences: Dict[int, List[Tuple[str, str]]] = {}
    for field in fields:
        if field.card_index <= 0 or not field.path.endswith(_REPETITION_FIELD_SUFFIXES):
            continue
        for sentence in _split_sentences(field.text):
            if len(sentence) >= 18:
                card_sentences.setdefault(field.card_index, []).append((field.path, sentence))

    compared: set[Tuple[int, int, str, str]] = set()
    for left_idx, left_values in sorted(card_sentences.items()):
        for right_idx, right_values in sorted(card_sentences.items()):
            if right_idx <= left_idx:
                continue
            for left_path, left_sentence in left_values:
                for right_path, right_sentence in right_values:
                    left_skeleton = _sentence_skeleton(left_sentence)
                    right_skeleton = _sentence_skeleton(right_sentence)
                    if min(len(left_skeleton), len(right_skeleton)) < 24:
                        continue
                    pair = (left_idx, right_idx, left_skeleton, right_skeleton)
                    if pair in compared:
                        continue
                    compared.add(pair)
                    ratio = SequenceMatcher(None, left_skeleton, right_skeleton).ratio()
                    if ratio >= STRUCTURAL_SIMILARITY_THRESHOLD:
                        findings.append(
                            ProductSurfaceFinding(
                                REPEATED_SENTENCE_SKELETON,
                                f"{left_path} <-> {right_path}",
                                f"카드 간 문장 구조 유사도 {ratio:.2f}가 기준 {STRUCTURAL_SIMILARITY_THRESHOLD:.2f} 이상입니다.",
                                (left_idx, right_idx),
                            )
                        )

    for phrase in _CANNED_BRIDGES:
        cards = sorted(
            {
                field.card_index
                for field in fields
                if field.card_index > 0 and phrase in field.text
            }
        )
        if len(cards) >= 2:
            findings.append(
                ProductSurfaceFinding(
                    REPEATED_CANNED_BRIDGE,
                    "items[*]",
                    f"동일 상투 연결구가 여러 카드에 반복되었습니다: {phrase}",
                    tuple(cards),
                )
            )

    known_skeleton_cards = sorted(
        {
            field.card_index
            for field in fields
            if field.card_index > 0
            and "야간·장전 맥락에서" in field.text
            and "흐름이 대응 축으로 남아" in field.text
        }
    )
    if len(known_skeleton_cards) >= 2:
        findings.append(
            ProductSurfaceFinding(
                REPEATED_SENTENCE_SKELETON,
                "items[*].detail",
                "기사명만 바뀌는 동일한 야간·장전 문장 골격이 여러 카드에 반복되었습니다.",
                tuple(known_skeleton_cards),
            )
        )

    polite_paths: List[str] = []
    plain_paths: List[str] = []
    for field in fields:
        for sentence in _split_sentences(field.text):
            if _POLITE_END_RE.search(sentence):
                polite_paths.append(field.path)
            elif _PLAIN_END_RE.search(sentence):
                plain_paths.append(field.path)
    if polite_paths and plain_paths:
        findings.append(
            ProductSurfaceFinding(
                MIXED_SENTENCE_END_STYLE,
                "reader_surface",
                "동일 제품면에 존댓말과 평서형 종결이 혼재합니다.",
            )
        )

    exact_sentences: Dict[str, List[Tuple[int, str]]] = {}
    for card_index, values in card_sentences.items():
        for path, sentence in values:
            normalized = re.sub(r"[^0-9a-z가-힣]+", " ", sentence.lower()).strip()
            if len(normalized) >= 20:
                exact_sentences.setdefault(normalized, []).append((card_index, path))
    for values in exact_sentences.values():
        cards = sorted({card for card, _ in values})
        if len(cards) >= 2:
            paths = sorted({path for _, path in values})
            findings.append(
                ProductSurfaceFinding(
                    DUPLICATE_FILLER,
                    " <-> ".join(paths[:3]),
                    "기사 고유 정보를 더하지 않는 동일 문장이 여러 카드에 반복되었습니다.",
                    tuple(cards),
                )
            )

    unique = _dedupe_findings(findings)
    return ProductSurfaceResult(
        PRODUCT_REVIEW_REQUIRED if unique else CUSTOMER_SURFACE_PASS,
        unique,
    )


def prepare_final_customer_copy(
    mode: str,
    structured_output: Mapping[str, Any],
    *,
    source_input: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Inspect the final customer copy immediately before render/persistence.

    **This function must never author, rewrite, summarize, replace or delete
    substantive customer prose.**  Product-surface QA is a diagnosis, not an
    editor: it returns the payload byte-identical apart from the additive
    ``_product_surface_qa`` diagnostic, so a defect is escalated to owner review
    instead of being hidden behind deterministic filler.

    The 2026-09-07 Today incident came from the opposite arrangement — a repair
    pass here deleted grounded sentences and inserted manufactured leads, which
    both damaged the copy and prevented the detectors from seeing the damage.
    """
    out = copy.deepcopy(dict(structured_output))
    result = evaluate_product_surface(mode, out, source_input=source_input)
    out[PRODUCT_SURFACE_DIAGNOSTIC_KEY] = result.as_dict()
    return out


def product_surface_run_fields(structured_output: Any) -> Dict[str, Any]:
    if not isinstance(structured_output, Mapping):
        return {}
    diag = structured_output.get(PRODUCT_SURFACE_DIAGNOSTIC_KEY)
    if not isinstance(diag, Mapping):
        return {}
    return {
        "customer_surface_status": diag.get("customer_surface_status"),
        "product_surface_issue_codes": list(diag.get("issue_codes") or []),
        "product_surface_contract_version": diag.get("contract_version"),
    }
