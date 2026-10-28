"""Unit tests: today_genie email numeric table render (structured fields only)."""
from __future__ import annotations

import unittest

from renderers import _today_snapshot_grouped_html


def _kospi_row(
    *,
    close: float = 2587.12,
    change_pct: float = -0.59,
    value: str = "2587.12 (-0.59%)",
) -> dict:
    return {
        "label": "코스피",
        "value": value,
        "basis": "fact",
        "close": close,
        "change_pct": change_pct,
    }


class TodayGenieSnapshotTableRenderTests(unittest.TestCase):
    def test_structured_close_and_change_pct_render_exactly(self) -> None:
        html = _today_snapshot_grouped_html([_kospi_row()])
        self.assertIn("2587.12", html)
        self.assertIn("-0.59%", html)
        self.assertIn("전일 국내 마감", html)

    def test_conflicting_value_string_does_not_override_structured_fields(self) -> None:
        row = _kospi_row(value="99999.99 (+9.99%)")
        html = _today_snapshot_grouped_html([row])
        self.assertIn("2587.12", html)
        self.assertIn("-0.59%", html)
        self.assertNotIn("99999.99", html)
        self.assertNotIn("+9.99%", html)

    def test_narrative_global_context_is_not_used(self) -> None:
        # Legacy path set market_setup on a module global; renderer must ignore it.
        import renderers

        renderers._TODAY_EMAIL_MARKET_SETUP_CONTEXT = (
            "코스피는 99999.99로 급등(+9.99%)했습니다."
        )
        try:
            row = {
                "label": "코스피",
                "value": "2587.12 (-0.59%)",
                "close": 2587.12,
                "change_pct": -0.59,
            }
            html = _today_snapshot_grouped_html([row])
            self.assertIn("2587.12", html)
            self.assertIn("-0.59%", html)
            self.assertNotIn("99999.99", html)
            self.assertNotIn("+9.99%", html)
        finally:
            if hasattr(renderers, "_TODAY_EMAIL_MARKET_SETUP_CONTEXT"):
                delattr(renderers, "_TODAY_EMAIL_MARKET_SETUP_CONTEXT")

    def test_row_without_numeric_fields_is_omitted(self) -> None:
        html = _today_snapshot_grouped_html(
            [{"label": "코스피", "value": "", "basis": "fact"}]
        )
        self.assertEqual(html, "")

    def test_six_rows_grouped_and_ordered_correctly(self) -> None:
        snapshot = [
            {"label": "코스피", "close": 2587.12, "change_pct": -0.59},
            {"label": "코스닥", "close": 720.50, "change_pct": 0.35},
            {"label": "니케이", "close": 38981.75, "change_pct": 1.25},
            {"label": "S&P 500", "close": 5800.10, "change_pct": -0.20},
            {"label": "나스닥", "close": 18500.20, "change_pct": 0.45},
            {"label": "다우존스", "close": 42000.55, "change_pct": -0.15},
        ]
        html = _today_snapshot_grouped_html(snapshot)

        # Ensure correct section headings are present and legacy heading is absent
        self.assertIn("전일 국내 마감", html)
        self.assertIn("전일 일본 마감", html)
        self.assertIn("밤사이 미국 마감", html)
        self.assertNotIn("밤사이 해외 마감", html)

        # Validate section order: Korea domestic -> Japan -> US overnight
        idx_kr = html.index("전일 국내 마감")
        idx_jp = html.index("전일 일본 마감")
        idx_us = html.index("밤사이 미국 마감")
        self.assertLess(idx_kr, idx_jp)
        self.assertLess(idx_jp, idx_us)

        # Slice sections to verify item confinement
        kr_section = html[idx_kr:idx_jp]
        jp_section = html[idx_jp:idx_us]
        us_section = html[idx_us:]

        # Korea group checks
        self.assertIn("코스피", kr_section)
        self.assertIn("코스닥", kr_section)
        self.assertNotIn("니케이", kr_section)
        self.assertIn("2587.12", kr_section)
        self.assertIn("-0.59%", kr_section)
        self.assertIn("720.5", kr_section)
        self.assertIn("+0.35%", kr_section)

        # Japan group checks (Nikkei must never be in domestic or US)
        self.assertIn("니케이", jp_section)
        self.assertNotIn("코스피", jp_section)
        self.assertNotIn("코스닥", jp_section)
        self.assertNotIn("나스닥", jp_section)
        self.assertIn("38981.75", jp_section)
        self.assertIn("+1.25%", jp_section)

        # US group checks
        self.assertIn("나스닥", us_section)
        self.assertIn("다우존스", us_section)
        self.assertTrue("S&P 500" in us_section or "S&amp;P 500" in us_section)
        self.assertNotIn("니케이", us_section)
        self.assertNotIn("코스피", us_section)
        self.assertIn("18500.2", us_section)
        self.assertIn("42000.55", us_section)

    def test_only_japan_group_renders_isolated_section(self) -> None:
        snapshot = [{"label": "니케이", "close": 38981.75, "change_pct": 1.25}]
        html = _today_snapshot_grouped_html(snapshot)

        self.assertIn("전일 일본 마감", html)
        self.assertIn("니케이", html)
        self.assertIn("38981.75", html)
        self.assertIn("+1.25%", html)

        self.assertNotIn("전일 국내 마감", html)
        self.assertNotIn("밤사이 미국 마감", html)
        self.assertNotIn("밤사이 해외 마감", html)

    def test_partial_korea_and_us_without_japan(self) -> None:
        snapshot = [
            {"label": "코스닥", "close": 720.50, "change_pct": 0.35},
            {"label": "나스닥", "close": 18500.20, "change_pct": 0.45},
        ]
        html = _today_snapshot_grouped_html(snapshot)

        self.assertIn("전일 국내 마감", html)
        self.assertIn("코스닥", html)
        self.assertIn("720.5", html)
        self.assertNotIn("코스피", html)

        self.assertIn("밤사이 미국 마감", html)
        self.assertIn("나스닥", html)
        self.assertIn("18500.2", html)
        self.assertNotIn("S&P 500", html)
        self.assertNotIn("다우존스", html)

        self.assertNotIn("전일 일본 마감", html)
        self.assertNotIn("니케이", html)
        self.assertNotIn("밤사이 해외 마감", html)

    def test_empty_and_partial_missing_numeric_rows(self) -> None:
        self.assertEqual(_today_snapshot_grouped_html([]), "")
        self.assertEqual(_today_snapshot_grouped_html(None), "")
        self.assertEqual(_today_snapshot_grouped_html("not-a-list"), "")
        self.assertEqual(_today_snapshot_grouped_html([{}, {"label": ""}]), "")
        self.assertEqual(
            _today_snapshot_grouped_html([{"label": "니케이", "close": None, "change_pct": None, "value": ""}]),
            "",
        )
        self.assertEqual(
            _today_snapshot_grouped_html([{"label": "알수없는인덱스", "close": 1234.5, "change_pct": 0.5}]),
            "",
        )

    def test_nikkei_never_rendered_under_overnight_or_domestic(self) -> None:
        snapshot = [
            {"label": "니케이", "close": 38981.75, "change_pct": 1.25},
            {"label": "코스피", "close": 2587.12, "change_pct": -0.59},
            {"label": "다우존스", "close": 42000.55, "change_pct": -0.15},
        ]
        html = _today_snapshot_grouped_html(snapshot)

        idx_kr = html.index("전일 국내 마감")
        idx_jp = html.index("전일 일본 마감")
        idx_us = html.index("밤사이 미국 마감")

        kr_part = html[idx_kr:idx_jp]
        jp_part = html[idx_jp:idx_us]
        us_part = html[idx_us:]

        self.assertNotIn("니케이", kr_part)
        self.assertIn("니케이", jp_part)
        self.assertNotIn("니케이", us_part)


if __name__ == "__main__":
    unittest.main()
