"""Tests for Korea 18:30 longform visible structure and evening memo."""
from __future__ import annotations

import unittest

from keysuri_briefing_content_quality import validate_briefing_content_gate
from keysuri_korea_longform_ux import (
    KOREA_CLOSING_PARAGRAPH_MAX_CHARS,
    KOREA_DEEP_MAX_PARAGRAPH_CHARS,
    KOREA_MEMO_ACTION_MAX_CHARS,
    KOREA_WARM_FAREWELL_LINES,
    build_korea_evening_memo,
    clamp_action_line,
    contains_truncated_headline_fragment,
    korea_closing_paragraph_too_long,
    korea_deep_block_too_long,
    korea_evening_memo_too_thin,
    korea_memo_action_line_too_long,
    korea_warm_farewell_missing,
    remove_truncated_headline_fragments,
    structure_korea_deep_dive,
)
from tests.test_keysuri_contract_preview_renderer import (
    _CONTRACT_RENDERER,
    _render_contract_html,
    build_global_contract_fixture,
    build_korea_contract_fixture,
)


def _top_items() -> list[dict]:
    return [
        {
            "korean_title": "엔비디아 CEO 방한, HBM4 협력 논의",
            "next_watch": "삼성전자·SK하이닉스 HBM4 후속 일정; GPU 공급 약속 대상 확인",
        },
        {
            "korean_title": "국내 AI 스타트업 투자 확대",
            "next_watch": "정부 AI 팩토리 구체화; 국내 스타트업 투자 후속",
        },
    ]


def _korea_closing_html(memo_html: str) -> str:
    return f"""
    <html><body class="premium-briefing theme-korea">
    <section id="deep-dive-section">
      <div class="korea-deep-block"><h4 class="korea-deep-label">오늘의 핵심 흐름</h4>
      <div class="korea-deep-body"><p>짧은 흐름입니다.</p></div></div>
      <div class="korea-deep-block"><h4 class="korea-deep-label">국내 적용</h4>
      <div class="korea-deep-body"><p>국내 적용 문장입니다.</p></div></div>
      <div class="korea-deep-block"><h4 class="korea-deep-label">내일 볼 지점</h4>
      <div class="korea-deep-body"><ul><li>후속 확인</li><li>일정 점검</li></ul></div></div>
    </section>
    <section id="closing-section"><h2>퇴근 전 메모</h2>{memo_html}</section>
  </body></html>
    """


class KeysuriKoreaLongformUxTests(unittest.TestCase):
    def test_structure_splits_wall_paragraph_into_blocks(self) -> None:
        wall = (
            "오늘 눈에 띄는 점은 H… 이슈가 동시에 보인다는 것입니다. "
            "한쪽은 산업·인프라 쪽이고, 다른 쪽은 소프트웨어·운영 쪽입니다."
        )
        sections = structure_korea_deep_dive(wall, _top_items())
        labels = [section["label"] for section in sections]
        self.assertIn("오늘의 핵심 흐름", labels)
        self.assertIn("국내 적용", labels)
        self.assertIn("내일 볼 지점", labels)
        self.assertGreaterEqual(len(sections), 3)
        blob = " ".join(section["body"] for section in sections)
        self.assertNotIn("H…", blob)
        self.assertNotIn("한쪽은 산업·인프라", blob)

    def test_wall_text_gate_flags_unnormalized_paragraph(self) -> None:
        sections = [{"label": "오늘의 핵심 흐름", "body": "가" * (KOREA_DEEP_MAX_PARAGRAPH_CHARS + 5)}]
        self.assertTrue(korea_deep_block_too_long(sections))

    def test_remove_truncated_headline_fragments(self) -> None:
        cleaned = remove_truncated_headline_fragments("H… 만… 후속 일정")
        self.assertFalse(contains_truncated_headline_fragment(cleaned))

    def test_evening_memo_has_actions_and_warm_farewell(self) -> None:
        memo = build_korea_evening_memo(_top_items())
        self.assertGreaterEqual(len(memo["action_lines"]), 2)
        self.assertFalse(korea_evening_memo_too_thin(memo))
        self.assertEqual(memo["warm_lines"], list(KOREA_WARM_FAREWELL_LINES))

    def test_action_lines_split_from_semicolon_chain(self) -> None:
        memo = build_korea_evening_memo(_top_items())
        self.assertGreaterEqual(len(memo["action_lines"]), 2)
        for line in memo["action_lines"]:
            self.assertNotIn(";", line)
            self.assertLessEqual(len(line), KOREA_MEMO_ACTION_MAX_CHARS)

    def test_thin_closing_without_warm_farewell_fails_gate(self) -> None:
        html = _korea_closing_html(
            '<div class="evening-memo-body"><p>오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.</p></div>'
        )
        result = validate_briefing_content_gate(html)
        codes = {issue.code for issue in result.issues}
        self.assertIn("korea_closing_warm_farewell_missing", codes)

    def test_gate_fails_when_closing_paragraph_too_long(self) -> None:
        long_para = "가" * (KOREA_CLOSING_PARAGRAPH_MAX_CHARS + 1)
        self.assertTrue(korea_closing_paragraph_too_long(f"<p>{long_para}</p>"))

    def test_gate_fails_when_action_line_too_long(self) -> None:
        long_line = "가" * (KOREA_MEMO_ACTION_MAX_CHARS + 1)
        self.assertTrue(korea_memo_action_line_too_long([long_line]))
        self.assertLessEqual(len(clamp_action_line(long_line)), KOREA_MEMO_ACTION_MAX_CHARS)

    def test_renderer_includes_warm_farewell_after_memo(self) -> None:
        if _CONTRACT_RENDERER is None:
            raise unittest.SkipTest("keysuri_contract_preview_renderer not implemented yet")
        html = _render_contract_html(_CONTRACT_RENDERER, build_korea_contract_fixture())
        self.assertNotIn("국내 18:30 따뜻한 마무리", html)
        self.assertIn("퇴근 전 메모", html)
        self.assertIn("오늘도 수고 많으셨습니다.", html)
        self.assertIn("내일 아침에 다시 볼 흐름만 남겨두겠습니다.", html)
        self.assertFalse(korea_warm_farewell_missing(html))

    def test_global_rendering_unchanged(self) -> None:
        if _CONTRACT_RENDERER is None:
            raise unittest.SkipTest("keysuri_contract_preview_renderer not implemented yet")
        html = _render_contract_html(_CONTRACT_RENDERER, build_global_contract_fixture())
        self.assertNotRegex(html, r'class="korea-deep-block"')
        self.assertNotIn("퇴근 전 메모", html)
        self.assertNotIn("오늘도 수고 많으셨습니다.", html)
        self.assertIn("deep-dive-prose", html)


if __name__ == "__main__":
    unittest.main()
