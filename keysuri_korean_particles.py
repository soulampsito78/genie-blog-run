"""Korean particle agreement for dynamically assembled reader prose.

Korean postpositions agree with the final sound of the noun they attach to. A
template that writes ``f"{term}와"`` is correct only when ``term`` happens to end
in a vowel, and the 2026-08-29 07:23 owner mail carried two failures of exactly
this kind:

    투자 환경·후속 라운드(팔로우온) 흐름와 ...   (흐름 has a final ㅁ → 흐름과)
    창업자 실행 리스크·번 레이트·GTM 후속를 봅니다.  (후속 has a final ㄱ → 후속을)

Both came from padding templates that hard-coded the particle onto a dynamic
checkpoint phrase. This module is the shared safe attachment point, and the
detector below catches the other half of the problem: particles the model itself
writes incorrectly.

Latin letters, digits, symbols and parenthesised endings are deliberately NOT
guessed. Their Korean pronunciation is not derivable from the characters, so the
attachment functions report that no safe choice exists and the caller must
restructure the sentence instead of inventing phonology.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_HANGUL_START = 0xAC00
_HANGUL_END = 0xD7A3
#: Index of ㄹ in the jongseong table.
_JONG_RIEUL = 8

#: (after final consonant, after vowel)
SUBJECT = ("이", "가")
TOPIC = ("은", "는")
OBJECT = ("을", "를")
CONJUNCTION = ("과", "와")
#: 으로/로 takes the vowel form after ㄹ as well as after a vowel.
INSTRUMENT = ("으로", "로")

PARTICLE_PAIRS: Tuple[Tuple[str, str], ...] = (
    SUBJECT,
    TOPIC,
    OBJECT,
    CONJUNCTION,
    INSTRUMENT,
)

PARTICLE_MISMATCH_ISSUE = "keysuri_korean_particle_mismatch"


def is_hangul_syllable(ch: str) -> bool:
    return bool(ch) and _HANGUL_START <= ord(ch[-1]) <= _HANGUL_END


def jongseong_index(ch: str) -> Optional[int]:
    """Final-consonant index of one Hangul syllable, or None if not Hangul.

    0 means the syllable ends in a vowel.
    """
    if not is_hangul_syllable(ch):
        return None
    return (ord(ch[-1]) - _HANGUL_START) % 28


def has_final_consonant(word: str) -> Optional[bool]:
    """True/False for a Hangul-final word, None when it cannot be determined."""
    text = (word or "").strip()
    if not text:
        return None
    index = jongseong_index(text[-1])
    if index is None:
        return None
    return index != 0


def select_particle(word: str, pair: Tuple[str, str]) -> Optional[str]:
    """The agreeing particle, or None when the ending is not Hangul.

    None is a refusal, not a default: guessing how "GTM", "5G" or "(팔로우온)"
    is pronounced is how wrong particles get published.
    """
    text = (word or "").strip()
    index = jongseong_index(text[-1]) if text else None
    if index is None:
        return None
    if pair == INSTRUMENT:
        # 으로/로: the vowel form is also correct after ㄹ.
        return pair[1] if index in (0, _JONG_RIEUL) else pair[0]
    return pair[1] if index == 0 else pair[0]


def attach_particle(word: str, pair: Tuple[str, str]) -> Optional[str]:
    """``word`` + agreeing particle, or None when no safe choice exists."""
    particle = select_particle(word, pair)
    if particle is None:
        return None
    return f"{word}{particle}"


def attach_or_none(word: str, pair: Tuple[str, str]) -> Optional[str]:
    return attach_particle(word, pair)


# --- detection -------------------------------------------------------------

#: Only 을/를 and 과/와 are scanned. 이/가 and 은/는 collide with Korean verbal
#: and interrogative endings — 것인가, 무엇인가, 같은, 하는 — where the trailing
#: syllable is part of the verb, not a particle. Scanning them turned
#: "영향을 미칠 것인가?" into "것인이?" in test, which is a worse defect than the
#: one being fixed. 으로/로 is excluded for the same reason (…으로 as an adverb,
#: 로 inside 로봇 etc. are handled by the word-break guard but the ending
#: ambiguity remains).
_SCAN_PAIRS: Tuple[Tuple[str, str], ...] = (OBJECT, CONJUNCTION, SUBJECT)

#: Verbal / interrogative endings that must never be read as noun + particle.
_VERBAL_ENDINGS: Tuple[str, ...] = (
    # Noun-final syllables that are actually verb/adjective inflection. The
    # particle regex consumes the trailing 가, so the ending seen here is the
    # syllable before it: 달라졌"는"가, 무엇"인"가, 어떻"은"가.
    "인", "은", "는", "던", "한", "할", "된", "될", "있", "없", "같",
    "하", "되", "지", "느", "리", "우", "쁘", "크",
)

#: 이 is deliberately absent. Korean loanwords routinely END in that syllable —
#: 릴레이, 플레이, 디스플레이 — and scanning it rewrote them to 릴레가/플레가 in a
#: sweep over the real corpus. 가 alone still catches the 2026-08-14 공급망가
#: defect, because that is the wrong-direction case.
_TOKEN_RE = re.compile(r"([가-힣]{2,})(을|를|과|와|가)(?![가-힣])")


def particle_findings(
    text: str,
    *,
    field: str = "",
    news_id: str = "",
    rank: Optional[int] = None,
) -> List[Dict[str, object]]:
    """Mechanically impossible Hangul + particle pairs in ``text``.

    Only reports where the rule is deterministic: the noun ends in a Hangul
    syllable, so the correct particle follows from its final consonant. Anything
    ending in Latin, a digit or a bracket is skipped rather than guessed.
    """
    findings: List[Dict[str, object]] = []
    blob = str(text or "")
    if not blob.strip():
        return findings
    for match in _TOKEN_RE.finditer(blob):
        noun, actual = match.group(1), match.group(2)
        if noun.endswith(_VERBAL_ENDINGS):
            continue
        pair = _pair_for(actual)
        if pair is None:
            continue
        expected = select_particle(noun, pair)
        if expected is None or expected == actual:
            continue
        findings.append(
            {
                "issue_code": PARTICLE_MISMATCH_ISSUE,
                "field": field,
                "news_id": news_id,
                "rank": rank,
                "sentence": _sentence_around(blob, match.start()),
                "token": f"{noun}{actual}",
                "stem": noun[-1],
                "expected_particle": expected,
                "actual_particle": actual,
                "corrected_token": f"{noun}{expected}",
            }
        )
    return findings


def _pair_for(particle: str) -> Optional[Tuple[str, str]]:
    for pair in (OBJECT, CONJUNCTION, SUBJECT, TOPIC, INSTRUMENT):
        if particle in pair:
            return pair
    return None


def _sentence_around(blob: str, index: int) -> str:
    start = max(blob.rfind(".", 0, index), blob.rfind("\n", 0, index)) + 1
    end = blob.find(".", index)
    end = len(blob) if end < 0 else end + 1
    return blob[start:end].strip()[:200]


def correct_particles(text: str) -> Tuple[str, List[Dict[str, object]]]:
    """Apply the deterministic corrections only.

    Bounded and mechanical: each replacement swaps one particle for the one the
    noun's final consonant requires. No semantic rewriting, so this cannot
    change what a sentence says.
    """
    findings = particle_findings(text)
    if not findings:
        return text, []
    out = text
    for finding in findings:
        out = out.replace(str(finding["token"]), str(finding["corrected_token"]))
    return out, findings


def attach_or(word: str, pair: Tuple[str, str], fallback: str) -> str:
    """``word`` + agreeing particle, or ``fallback`` when the ending is not Hangul.

    Callers pass a restructured phrase as ``fallback`` — usually the particle
    moved onto a fixed Korean noun — so a Latin or digit ending never forces a
    guess.
    """
    attached = attach_particle(word, pair)
    return attached if attached is not None else fallback
