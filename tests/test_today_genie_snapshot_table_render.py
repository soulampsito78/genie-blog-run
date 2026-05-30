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


if __name__ == "__main__":
    unittest.main()
