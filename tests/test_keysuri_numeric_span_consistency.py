"""Unit tests for year-span / duration consistency."""
from __future__ import annotations

import unittest

from keysuri_numeric_span_consistency import (
    analyze_year_span_claim,
    compute_year_spans,
    repair_year_span_duration,
)


class YearSpanConsistencyTests(unittest.TestCase):
    def test_inclusive_span_matches(self) -> None:
        self.assertEqual(compute_year_spans(2025, 2030)["inclusive"], 6)
        analysis = analyze_year_span_claim("2025년부터 2030년까지 6년간")
        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertFalse(analysis["mismatch"])

    def test_exclusive_span_matches(self) -> None:
        analysis = analyze_year_span_claim("2025년부터 2031년까지 6년간")
        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertFalse(analysis["mismatch"])
        self.assertEqual(analysis["computed_span"]["exclusive"], 6)

    def test_mismatched_span_detected_and_repaired(self) -> None:
        analysis = analyze_year_span_claim("2025년부터 2032년까지 6년간")
        self.assertTrue(analysis and analysis["mismatch"])
        repaired, diag = repair_year_span_duration(
            "시장은 2025년부터 2032년까지 6년간 성장할 전망입니다."
        )
        self.assertEqual(diag["resolution"], "removed_derived_duration")
        self.assertIn("2025년부터 2032년까지", repaired)
        self.assertNotIn("6년간", repaired)

    def test_explicit_basis_accepted(self) -> None:
        analysis = analyze_year_span_claim(
            "회계연도 기준으로 2025년부터 2032년까지 6년간"
        )
        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertFalse(analysis["mismatch"])
        self.assertEqual(analysis["resolution"], "explicit_basis_accepted")


if __name__ == "__main__":
    unittest.main()
