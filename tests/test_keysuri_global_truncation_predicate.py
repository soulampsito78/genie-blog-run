"""Dangling-particle predicate precision for the global post-render QA gate.

Run 20260730_185212_keysuri_global_tech_b09b8b02 blocked with
global_visible_text_truncated_deep_dive on this persisted line:

    구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가

"추가" is a complete two-syllable noun; it was flagged only because its final
syllable "가" is also the subject particle.
"""
from __future__ import annotations

import unittest

from keysuri_briefing_content_quality import (
    _find_truncated_visible_lines,
    _hangul_syllable_count,
    validate_global_post_render_visible_quality,
)

# Exactly as recovered from post_render_qa_diagnostics.truncated_visible_lines.
B09B8B02_OFFENDING_LINE = "구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가"


def _html(*lines: str) -> str:
    return "".join(f"<p>{line}</p>" for line in lines)


class B09B8B02RegressionTests(unittest.TestCase):
    def test_observed_offending_line_is_not_flagged(self) -> None:
        self.assertEqual(_find_truncated_visible_lines(_html(B09B8B02_OFFENDING_LINE)), [])

    def test_observed_line_passes_the_post_render_gate(self) -> None:
        result = validate_global_post_render_visible_quality(_html(B09B8B02_OFFENDING_LINE))
        codes = [i.code for i in result.issues]
        self.assertNotIn("global_visible_text_truncated_deep_dive", codes)

    def test_two_syllable_noun_tails_colliding_with_particles_pass(self) -> None:
        for tail in ("추가", "증가", "결과", "효과", "도로", "평가", "성과", "경로"):
            line = f"엔비디아와 구글이 공개한 신규 플랫폼 기능의 실질적인 운영 {tail}"
            self.assertEqual(_find_truncated_visible_lines(_html(line)), [], tail)


class TruncationStillDetectedTests(unittest.TestCase):
    def test_three_syllable_noun_plus_particle_is_still_flagged(self) -> None:
        cases = [
            "이번 발표는 향후 국내 인프라 투자 계획에 직접적인 영향을 주는 발표가",
            "주인님께서 점검하실 항목은 다음 분기 예산과 도입 우선순위 기능을",
            "해당 이슈는 국내 제조 현장과 오프라인 매장 운영 전반의 비용 구조에",
            "엔비디아가 공개한 신규 젯슨 모듈은 엣지 추론 성능을 끌어올리는 요소에서",
        ]
        for line in cases:
            self.assertEqual(_find_truncated_visible_lines(_html(line)), [line[:120]], line[:30])

    def test_literal_ellipsis_predicate_is_unchanged(self) -> None:
        line = "report maps how AI could reshape jobs… highlighting"
        self.assertEqual(_find_truncated_visible_lines(_html(line)), [line[:120]])

    def test_double_dot_predicate_is_unchanged(self) -> None:
        line = "Operators should read the raw claim.. before market open"
        self.assertEqual(_find_truncated_visible_lines(_html(line)), [line[:120]])

    def test_url_dots_do_not_trigger_ellipsis(self) -> None:
        line = "자세한 내용은 https://example.invalid/a.b.c 에서 확인하실 수 있습니다."
        self.assertEqual(_find_truncated_visible_lines(_html(line)), [])

    def test_short_line_is_not_evaluated(self) -> None:
        self.assertEqual(_find_truncated_visible_lines(_html("훅 추가")), [])


class SyllableCounterTests(unittest.TestCase):
    def test_counts_only_hangul_syllables(self) -> None:
        self.assertEqual(_hangul_syllable_count("추가"), 2)
        self.assertEqual(_hangul_syllable_count("발표가"), 3)
        self.assertEqual(_hangul_syllable_count("Gemini 3.6"), 0)
        self.assertEqual(_hangul_syllable_count(""), 0)
        self.assertEqual(_hangul_syllable_count(None), 0)


if __name__ == "__main__":
    unittest.main()
