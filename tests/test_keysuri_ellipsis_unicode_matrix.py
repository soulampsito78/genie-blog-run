"""Deterministic combinatorial matrix for KeeSuri connector-ellipsis repair."""
from __future__ import annotations

import unittest

from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

OPENING_DELIMS = (
    '"',
    "'",
    "\u201c",  # “
    "\u2018",  # ‘
    "(",
    "[",
    "{",
    "\u3008",  # 〈
    "\u300a",  # 《
    "\u300c",  # 「
    "\u300e",  # 『
)
CLOSING_DELIMS = (
    '"',
    "'",
    "\u201d",  # ”
    "\u2019",  # ’
    ")",
    "]",
    "}",
    "\u3009",  # 〉
    "\u300b",  # 》
    "\u300d",  # 」
    "\u300f",  # 』
)
ELLIPSIS_FORMS = (
    "..",
    "...",
    "….",
    "…",
    ".…",
    "…..",
    "\u22ef",  # ⋯
    "\u2025",  # ‥
)
WHITESPACE = (
    "",
    " ",
    "\u00a0",  # NBSP
    "\u200b",  # ZWSP
)

_KOREA_1830_HEADLINE = "KDB생명 인수전, 한국투자·한화·흥국 '3파전'…삼성·교보 불참"
_KOREA_1830_EXPECTED = "KDB생명 인수전, 한국투자·한화·흥국 '3파전' 삼성·교보 불참"


def _bridge(left: str, ell: str, right: str, ws: str) -> str:
    return f"{left}{ws}{ell}{ws}{right}"


def _iter_matrix_cases():
    """Yield (case_id, text, expect) where expect is 'pass' or 'blocked'."""
    for ell in ELLIPSIS_FORMS:
        for ws in WHITESPACE:
            for d in (*OPENING_DELIMS, *CLOSING_DELIMS):
                yield (
                    f"word_ellipsis_delim|{ell!r}|{ws!r}|{d!r}",
                    _bridge("단어", ell, f"{d}내용", ws),
                    "pass",
                )
            for d in CLOSING_DELIMS:
                yield (
                    f"delim_ellipsis_word|{ell!r}|{ws!r}|{d!r}",
                    _bridge(d, ell, "단어", ws),
                    "pass",
                )
                yield (
                    f"word_delim_ellipsis_word|{ell!r}|{ws!r}|{d!r}",
                    _bridge(f"앞단어{d}", ell, "뒷단어", ws),
                    "pass",
                )
            for o in OPENING_DELIMS:
                for c in CLOSING_DELIMS:
                    yield (
                        f"word_ellipsis_open_close|{ell!r}|{ws!r}|{o!r}|{c!r}",
                        _bridge("단어", ell, f"{o}인용{c}", ws),
                        "pass",
                    )
            yield (
                f"sentence_final|{ell!r}|{ws!r}",
                f"정상적인 문장 끝{ws}{ell}",
                "pass",
            )
            yield (
                f"genuine_truncation|{ell!r}|{ws!r}",
                f"확인 불가 ({ws}{ell}{ws})",
                "blocked",
            )


class KeysuriEllipsisUnicodeMatrixTests(unittest.TestCase):
    def test_00_matrix_is_large_and_deterministic(self) -> None:
        cases = list(_iter_matrix_cases())
        self.assertGreaterEqual(len(cases), 1000)
        # Deterministic order / contents across runs.
        again = list(_iter_matrix_cases())
        self.assertEqual(cases[0], again[0])
        self.assertEqual(cases[-1], again[-1])
        self.assertEqual(len(cases), len(again))

    def test_01_combinatorial_connector_matrix(self) -> None:
        failures = []
        for case_id, text, expect in _iter_matrix_cases():
            result = repair_korean_connector_ellipsis_text(text)
            if expect == "blocked":
                if not result.blocked:
                    failures.append((case_id, text, result))
                continue
            # Connector / sentence-final → PASS with no residual connector ellipsis.
            if result.blocked:
                failures.append((case_id, text, result))
                continue
            if "…" in result.text or ".." in result.text:
                failures.append((case_id, text, result))
        self.assertEqual(
            failures[:12],
            [],
            msg=f"{len(failures)} matrix failures; first={failures[:5]!r}",
        )

    def test_02_korea_1830_named_regression_row(self) -> None:
        """Production Korea 18:30 headline is one named row, not the sole case."""
        result = repair_korean_connector_ellipsis_text(_KOREA_1830_HEADLINE)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        self.assertEqual(result.text, _KOREA_1830_EXPECTED)
        self.assertNotIn("…", result.text)

    def test_03_normalize_maps_u22ef_and_u2025(self) -> None:
        from keysuri_visible_text_quality import _normalize_ellipsis_unicode

        self.assertEqual(_normalize_ellipsis_unicode("a\u22efb"), "a…b")
        self.assertEqual(_normalize_ellipsis_unicode("a\u2025b"), "a…b")
        self.assertEqual(_normalize_ellipsis_unicode("a.…b"), "a…b")
        self.assertEqual(_normalize_ellipsis_unicode("a….b"), "a…b")

    def test_04_angle_bracket_delims_are_structural_edges(self) -> None:
        for text in (
            "단어…〈인용〉",
            "단어…《인용》",
            "〉…다음",
            "《닫힘》…다음",
        ):
            result = repair_korean_connector_ellipsis_text(text)
            self.assertFalse(result.blocked, msg=text)
            self.assertNotIn("…", result.text)


if __name__ == "__main__":
    unittest.main()
