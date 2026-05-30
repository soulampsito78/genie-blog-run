"""Tests for today_genie email text render quality (escaping, market_setup paragraphs)."""
from __future__ import annotations

import re
import unittest

from renderers import (
    _build_today_genie_email_editorial_html,
    _market_setup_html,
    _market_setup_paragraphs,
    _safe,
)


def _minimal_today_data(**overrides: object) -> dict:
    base = {
        "title": "오늘의 지니",
        "summary": "국내 증시는 장전 변동성에 주목합니다.",
        "greeting": "안녕하세요.",
        "closing_message": "오늘도 신중한 접근이 필요합니다.",
        "key_watchpoints": [
            {"headline": "코스피", "detail": "외국인 수급을 확인합니다."},
        ],
        "risk_check": [{"risk": "환율", "detail": "원/달러 변동성을 봅니다."}],
        "hashtags": ["#코스피", "#장전브리핑", "#지니"],
    }
    base.update(overrides)
    return base


class TodayGenieEmailRenderQualityTests(unittest.TestCase):
    def test_sp500_plain_input_renders_without_double_escape(self) -> None:
        html = _build_today_genie_email_editorial_html(
            _minimal_today_data(
                key_watchpoints=[
                    {
                        "headline": "미국 증시",
                        "detail": "원문 지표 기준: S&P 500·Nasdaq 신기록, 기술주 강세.",
                    }
                ]
            )
        )
        self.assertIn("S&amp;P 500", html)
        self.assertNotIn("S&amp;amp;P", html)
        self.assertNotRegex(html, r"S&amp;P(?![\s;])")

    def test_sp500_preescaped_input_renders_correctly(self) -> None:
        html = _build_today_genie_email_editorial_html(
            _minimal_today_data(
                key_watchpoints=[
                    {
                        "headline": "미국 증시",
                        "detail": "원문 지표 기준: S&amp;P 500·Nasdaq 신기록, 기술주 강세.",
                    }
                ]
            )
        )
        self.assertIn("S&amp;P 500", html)
        self.assertNotIn("S&amp;amp;P", html)

    def test_safe_keeps_basic_html_safety(self) -> None:
        escaped = _safe('<script>alert("x")</script>')
        self.assertIn("&lt;script&gt;", escaped)
        self.assertNotIn("<script>", escaped)

    def test_long_market_setup_splits_into_multiple_paragraphs(self) -> None:
        market_setup = (
            "첫 문장입니다. "
            "둘째 문장입니다. "
            "셋째 문장입니다. "
            "넷째 문장입니다. "
            "다섯째 문장입니다. "
            "여섯째 문장입니다."
        )
        parts = _market_setup_paragraphs(market_setup)
        self.assertGreaterEqual(len(parts), 3)
        html = _market_setup_html(market_setup)
        p_count = len(re.findall(r"<p style=", html))
        self.assertGreaterEqual(p_count, 3)
        joined = " ".join(parts)
        for sent in _market_setup_paragraphs(market_setup):
            for piece in sent.split(". "):
                if piece.strip():
                    self.assertIn(piece.strip().rstrip("."), joined)

    def test_short_market_setup_stays_single_paragraph(self) -> None:
        market_setup = "짧은 맥락 한 문장입니다."
        parts = _market_setup_paragraphs(market_setup)
        self.assertEqual(len(parts), 1)
        html = _market_setup_html(market_setup)
        self.assertEqual(len(re.findall(r"<p style=", html)), 1)

    def test_market_setup_sentence_order_preserved(self) -> None:
        market_setup = (
            "코스피는 강세로 마감했습니다. "
            "미국 증시는 S&P 500이 신기록을 경신했습니다. "
            "환율은 보합권입니다. "
            "외국인은 순매수를 기록했습니다. "
            "기관은 순매도를 보였습니다. "
            "반도체 업종이 주도했습니다."
        )
        parts = _market_setup_paragraphs(market_setup)
        merged = " ".join(parts)
        self.assertLess(merged.find("코스피"), merged.find("미국"))
        self.assertLess(merged.find("미국"), merged.find("환율"))
        self.assertLess(merged.find("환율"), merged.find("외국인"))
        self.assertLess(merged.find("외국인"), merged.find("기관"))
        self.assertLess(merged.find("기관"), merged.find("반도체"))


if __name__ == "__main__":
    unittest.main()
