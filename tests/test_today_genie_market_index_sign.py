"""Market index direction integrity for Today_Geenee (no network, no send).

Covers the 2026-07-29 incident: a down session was published as a gain because
the Naver direction marker went undetected and an unsigned magnitude fell
through as positive, while a missing Nikkei rate was substituted with 0 and
then re-prefixed to '+0%' by the renderer.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "ops"))

import probe_today_genie_feeds as probe  # noqa: E402

from publishing_policy import decide_publishing_actions  # noqa: E402
from renderers import (  # noqa: E402
    _fmt_snapshot_change_pct,
    _norm_change_pct,
    _snapshot_row_cells,
)
from validators import (  # noqa: E402
    ValidationIssue,
    ValidationResult,
    _today_market_index_integrity_issues,
    market_index_validation_report,
)


def _naver_html(close: str, pts: str, pct: str, direction_markup: str, day: str = "2026.07.29") -> str:
    return f"""
    <div class="quotient">
    <em id="now_value">{close}</em>
    <span id="change_value_and_rate">{direction_markup}<span>{pts}</span> {pct}%</span>
    </div>
    <em id="time">{day}</em>
    """


def _blind(word: str) -> str:
    return f'<span class="blind">{word}</span>'


# Today's incident tape: domestic indexes fell hard, Nasdaq slipped, Nikkei rate
# was never parsed. Values as they appeared in the delivered mail.
INCIDENT_INDEX_TAPE = (
    ("코스피", "KOSPI", 6023.66, -10.84),
    ("코스닥", "KOSDAQ", 705.85, -7.72),
    ("S&P 500", "SPX", 7428.78, 0.21),
    ("나스닥", "NASDAQ", 24876.91, -0.22),
    ("니케이", "NIKKEI", 62364.92, None),
    ("다우존스", "DJI", 52747.32, 1.03),
)


def _feed_slot(close: float, pct, **extra) -> dict:
    slot = {
        "close": close,
        "change_pct": pct,
        "source_name": "fixture_source",
        "source_url": "https://example.invalid/index",
        "fetched_at": "2026-07-29T00:00:00Z",
        "verified_at": "2026-07-29T00:01:00Z",
        "accuracy_status": "verified",
    }
    slot.update(extra)
    return slot


def _runtime_input(overrides: dict | None = None) -> dict:
    """Six-index runtime feed pair with a consistent, corroborated tape."""
    rates = {
        "KOSPI": (6023.66, -10.84),
        "KOSDAQ": (705.85, -7.72),
        "SPX": (7428.78, 0.21),
        "NASDAQ": (24876.91, -0.22),
        "NIKKEI": (62364.92, -1.23),
        "DJI": (52747.32, 1.03),
    }
    slots = {}
    for sym, (close, pct) in rates.items():
        prev = close / (1.0 + pct / 100.0)
        slots[sym] = _feed_slot(close, pct, change_pts=round(close - prev, 2))
    if overrides:
        for sym, patch in overrides.items():
            if patch is None:
                slots.pop(sym, None)
            else:
                slots[sym] = {**slots[sym], **patch}
    return {
        "korea_japan_indices": {
            "as_of": "2026-07-29",
            "indices": {k: slots[k] for k in ("KOSPI", "KOSDAQ", "NIKKEI") if k in slots},
        },
        "overnight_us_market": {
            "as_of": "2026-07-29",
            "indices": {k: slots[k] for k in ("SPX", "NASDAQ", "DJI") if k in slots},
        },
    }


class NaverDirectionNormalizationTests(unittest.TestCase):
    """Source layer: magnitude + direction must normalize to one signed number."""

    def test_kospi_down_magnitude_normalizes_negative(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html("6,023.66", "589.12", "10.84", _blind("하락")), "KOSPI"
        )
        self.assertEqual(row["change_pct"], -10.84)
        self.assertEqual(row["change_pts"], -589.12)

    def test_kosdaq_down_magnitude_normalizes_negative(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html("705.85", "59.05", "7.72", _blind("하락")), "KOSDAQ"
        )
        self.assertEqual(row["change_pct"], -7.72)

    def test_up_direction_stays_positive(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html("7,484.41", "676.18", "8.29", _blind("상승")), "KOSPI"
        )
        self.assertEqual(row["change_pct"], 8.29)

    def test_direction_survives_changed_marker_markup(self) -> None:
        """The incident shape: direction present, but not in the exact old form."""
        row = probe.parse_naver_index_html(
            _naver_html("6,023.66", "589.12", "10.84", '<span class="blind ico">하락</span>'),
            "KOSPI",
        )
        self.assertEqual(row["change_pct"], -10.84)

    def test_direction_survives_unmatched_container_close(self) -> None:
        html = (
            '<em id="now_value">6,023.66</em>'
            '<dd id="change_value_and_rate"><span class="blind">하락</span>'
            "<span>589.12</span> 10.84%</dd>"
            '<em id="time">2026.07.29</em>'
        )
        row = probe.parse_naver_index_html(html, "KOSPI")
        self.assertEqual(row["change_pct"], -10.84)

    def test_undetermined_direction_fails_instead_of_going_positive(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(_naver_html("6,023.66", "589.12", "10.84", ""), "KOSPI")

    def test_already_signed_rate_is_preserved_without_direction_marker(self) -> None:
        row = probe.parse_naver_index_html(_naver_html("6,023.66", "-589.12", "-10.84", ""), "KOSPI")
        self.assertEqual(row["change_pct"], -10.84)

    def test_sign_conflict_between_marker_and_signed_rate_fails(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(
                _naver_html("6,023.66", "589.12", "-10.84", _blind("상승")), "KOSPI"
            )

    def test_flat_marker_contradicting_nonzero_rate_fails(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(
                _naver_html("6,023.66", "589.12", "10.84", _blind("보합")), "KOSPI"
            )

    def test_flat_marker_yields_zero_not_positive(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html("6,023.66", "0.00", "0", _blind("보합")), "KOSPI"
        )
        self.assertEqual(row["change_pct"], 0.0)

    def test_malformed_numeric_rate_fails(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(
                _naver_html("6,023.66", "589.12", "n/a", _blind("하락")), "KOSPI"
            )


class CnbcMissingRateTests(unittest.TestCase):
    """Source layer: a missing rate is unknown, never 0."""

    def test_signed_rate_sign_is_preserved(self) -> None:
        html = '"price":"24,876.91","priceChange":"-54.85","priceChangePercent":"-0.22"'
        self.assertEqual(probe.parse_cnbc_quote_html(html, "NASDAQ")["change_pct"], -0.22)

    def test_rate_outside_the_quote_chunk_is_still_found(self) -> None:
        html = '"price":"62,364.92"' + ("x" * 500) + '"priceChangePercent":"-1.23"'
        self.assertEqual(probe.parse_cnbc_quote_html(html, "NIKKEI")["change_pct"], -1.23)

    def test_missing_rate_recomputed_from_points_and_close(self) -> None:
        html = '"price":"62,364.92","priceChange":"-772.30"'
        row = probe.parse_cnbc_quote_html(html, "NIKKEI")
        self.assertIsNotNone(row["change_pct"])
        self.assertAlmostEqual(row["change_pct"], -1.22, places=2)

    def test_missing_rate_without_points_stays_unknown(self) -> None:
        row = probe.parse_cnbc_quote_html('"price":"62,364.92"', "NIKKEI")
        self.assertIsNone(row["change_pct"])
        self.assertIsNone(row["change_pts"])

    def test_recompute_change_pct_helper_is_direction_correct(self) -> None:
        self.assertAlmostEqual(probe.recompute_change_pct(90.0, -10.0), -10.0, places=2)
        self.assertAlmostEqual(probe.recompute_change_pct(110.0, 10.0), 10.0, places=2)
        self.assertIsNone(probe.recompute_change_pct(100.0, None))
        self.assertIsNone(probe.recompute_change_pct(None, 1.0))

    def test_summary_never_renders_unknown_or_flat_as_a_gain(self) -> None:
        self.assertEqual(probe._fmt_summary_pct(None), "n/a")
        self.assertEqual(probe._fmt_summary_pct(0.0), "0.00%")
        self.assertEqual(probe._fmt_summary_pct(-10.84), "-10.84%")


class SnapshotRendererSignTests(unittest.TestCase):
    """Renderer must not invent, drop, or double up a sign."""

    def test_negative_sign_is_preserved(self) -> None:
        for value in (-10.84, -7.72, -0.22):
            cell = _fmt_snapshot_change_pct(value)
            self.assertEqual(cell, f"{value:g}%")
            self.assertEqual(_norm_change_pct(cell), cell)

    def test_positive_gets_plus_sign(self) -> None:
        self.assertEqual(_norm_change_pct(_fmt_snapshot_change_pct(0.21)), "+0.21%")

    def test_zero_is_not_rendered_as_a_gain(self) -> None:
        self.assertEqual(_fmt_snapshot_change_pct(0), "0%")
        self.assertEqual(_norm_change_pct("0%"), "0%")
        self.assertEqual(_norm_change_pct(_fmt_snapshot_change_pct(0)), "0%")

    def test_normalization_is_idempotent(self) -> None:
        for raw in ("-10.84%", "+0.21%", "0%", "0.00%"):
            self.assertEqual(_norm_change_pct(_norm_change_pct(raw)), _norm_change_pct(raw))

    def test_no_doubled_or_mixed_signs(self) -> None:
        for value in (-10.84, -7.72):
            rendered = _norm_change_pct(_fmt_snapshot_change_pct(value))
            self.assertNotIn("--", rendered)
            self.assertNotIn("+-", rendered)
            self.assertFalse(rendered.startswith("+"))

    def test_unknown_rate_renders_as_placeholder_not_zero(self) -> None:
        _, pct_cell = _snapshot_row_cells({"label": "니케이", "close": 62364.92, "change_pct": None})
        self.assertEqual(pct_cell, "-")

    def test_incident_tape_renders_with_correct_directions(self) -> None:
        expected = {
            "코스피": "-10.84%",
            "코스닥": "-7.72%",
            "S&P 500": "+0.21%",
            "나스닥": "-0.22%",
            "다우존스": "+1.03%",
        }
        for label, _sym, close, pct in INCIDENT_INDEX_TAPE:
            if pct is None:
                continue
            _, cell = _snapshot_row_cells({"label": label, "close": close, "change_pct": pct})
            self.assertEqual(_norm_change_pct(cell), expected[label], label)


class MarketIndexValidationGateTests(unittest.TestCase):
    """Publish gate: invalid or unproven index rates must block owner-review."""

    def _codes(self, data: dict, runtime_input: dict) -> list[str]:
        return [i.code for i in _today_market_index_integrity_issues(data, runtime_input)]

    def test_consistent_tape_passes(self) -> None:
        ri = _runtime_input()
        self.assertEqual(self._codes({}, ri), [])
        self.assertEqual(
            market_index_validation_report({}, ri)["market_index_validation_status"], "pass"
        )

    def test_flipped_kospi_sign_is_blocked(self) -> None:
        """The exact incident: the tape says down, the published rate says up."""
        ri = _runtime_input({"KOSPI": {"change_pct": 10.84}})
        self.assertIn("market_index_sign_conflict", self._codes({}, ri))

    def test_flipped_kosdaq_sign_is_blocked(self) -> None:
        ri = _runtime_input({"KOSDAQ": {"change_pct": 7.72}})
        self.assertIn("market_index_sign_conflict", self._codes({}, ri))

    def test_missing_rate_is_blocked_and_not_read_as_zero(self) -> None:
        ri = _runtime_input({"NIKKEI": {"change_pct": None, "change_pts": None}})
        codes = self._codes({}, ri)
        self.assertIn("market_index_rate_invalid", codes)
        report = market_index_validation_report({}, ri)
        self.assertIsNone(report["market_index_normalized_values"]["니케이"])
        self.assertEqual(report["market_index_validation_status"], "fail")

    def test_zero_substituted_for_missing_rate_is_still_caught(self) -> None:
        """0 with a real point change does not survive the recompute check."""
        ri = _runtime_input({"NIKKEI": {"change_pct": 0.0}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_explicit_direction_conflict_is_blocked(self) -> None:
        ri = _runtime_input({"KOSPI": {"change_direction": 1}})
        self.assertIn("market_index_sign_conflict", self._codes({}, ri))

    def test_rate_disagreeing_with_previous_close_is_blocked(self) -> None:
        ri = _runtime_input({"SPX": {"previous_close": 8000.0}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_malformed_numeric_rate_is_blocked(self) -> None:
        ri = _runtime_input({"DJI": {"change_pct": "not-a-number"}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_non_positive_close_is_blocked(self) -> None:
        ri = _runtime_input({"DJI": {"close": 0}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_large_move_without_corroboration_is_held(self) -> None:
        ri = _runtime_input({"KOSPI": {"change_pts": None}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_large_move_with_corroboration_passes(self) -> None:
        self.assertEqual(self._codes({}, _runtime_input()), [])

    def test_absurd_rate_is_blocked(self) -> None:
        ri = _runtime_input({"KOSPI": {"change_pct": -95.0, "change_pts": None}})
        self.assertIn("market_index_rate_invalid", self._codes({}, ri))

    def test_snapshot_row_contradicting_the_feed_is_blocked(self) -> None:
        ri = _runtime_input()
        data = {
            "market_snapshot": [
                {"label": "코스피", "close": 6023.66, "change_pct": 10.84},
            ]
        }
        self.assertIn("market_index_sign_conflict", self._codes(data, ri))

    def test_report_carries_diagnostics_without_raw_payloads(self) -> None:
        report = market_index_validation_report({}, _runtime_input({"KOSPI": {"change_pct": 10.84}}))
        for key in (
            "market_index_validation_status",
            "market_index_validation_issues",
            "market_index_source_values",
            "market_index_normalized_values",
            "market_index_recomputed_change_rates",
            "market_index_sign_conflicts",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["market_index_validation_status"], "fail")
        for values in report["market_index_source_values"].values():
            self.assertEqual(set(values), {"close", "change_pct"})


class IncidentEndToEndTests(unittest.TestCase):
    """Today's incident, from parsed source through to the rendered cell."""

    def test_incident_source_html_produces_negative_rates(self) -> None:
        kospi = probe.parse_naver_index_html(
            _naver_html("6,023.66", "732.50", "10.84", _blind("하락")), "KOSPI"
        )
        kosdaq = probe.parse_naver_index_html(
            _naver_html("705.85", "59.05", "7.72", _blind("하락")), "KOSDAQ"
        )
        self.assertLess(kospi["change_pct"], 0)
        self.assertLess(kosdaq["change_pct"], 0)
        for row in (kospi, kosdaq):
            _, cell = _snapshot_row_cells(row)
            self.assertTrue(_norm_change_pct(cell).startswith("-"))

    def test_incident_nikkei_never_publishes_plus_zero(self) -> None:
        row = probe.parse_cnbc_quote_html('"price":"62,364.92"', "NIKKEI")
        self.assertIsNone(row["change_pct"])
        _, cell = _snapshot_row_cells(row | {"label": "니케이"})
        self.assertNotEqual(_norm_change_pct(cell), "+0%")

    def test_incident_feed_blocks_publication(self) -> None:
        """As-published values (KOSPI/KOSDAQ up, Nikkei 0) must not validate."""
        ri = _runtime_input(
            {
                "KOSPI": {"change_pct": 10.84},
                "KOSDAQ": {"change_pct": 7.72},
                "NIKKEI": {"change_pct": 0.0},
            }
        )
        codes = [i.code for i in _today_market_index_integrity_issues({}, ri)]
        self.assertTrue(codes)
        self.assertTrue(
            all(i.severity == "error" for i in _today_market_index_integrity_issues({}, ri))
        )


class SideEffectSuppressionTests(unittest.TestCase):
    """A blocked index tape must not reach image generation, email, or Naver."""

    def _blocked_result(self, runtime_input: dict) -> ValidationResult:
        issues = _today_market_index_integrity_issues({}, runtime_input)
        self.assertTrue(issues, "expected the gate to raise issues")
        return ValidationResult(result="block", issues=issues)

    def test_sign_conflict_suppresses_every_distribution_channel(self) -> None:
        ri = _runtime_input({"KOSPI": {"change_pct": 10.84}})
        result = self._blocked_result(ri)
        decision = decide_publishing_actions(
            "today_genie",
            result.result,
            "review_required",
            [{"code": i.code, "message": i.message, "severity": i.severity} for i in result.issues],
            ri,
        )
        self.assertFalse(decision.send_email)
        self.assertFalse(decision.send_customer_email)
        self.assertFalse(decision.create_naver_draft)
        self.assertFalse(decision.auto_publish)
        self.assertTrue(decision.suppress_external)

    def test_missing_rate_suppresses_every_distribution_channel(self) -> None:
        ri = _runtime_input({"NIKKEI": {"change_pct": None, "change_pts": None}})
        result = self._blocked_result(ri)
        decision = decide_publishing_actions("today_genie", result.result, "review_required", [], ri)
        self.assertFalse(decision.send_email)
        self.assertFalse(decision.send_customer_email)
        self.assertTrue(decision.suppress_external)

    def test_gate_issues_are_error_severity_so_validation_blocks(self) -> None:
        for override in (
            {"KOSPI": {"change_pct": 10.84}},
            {"NIKKEI": {"change_pct": None, "change_pts": None}},
            {"DJI": {"change_pct": "not-a-number"}},
        ):
            issues = _today_market_index_integrity_issues({}, _runtime_input(override))
            self.assertTrue(issues)
            for issue in issues:
                self.assertIsInstance(issue, ValidationIssue)
                self.assertEqual(issue.severity, "error", issue.code)

    def test_healthy_tape_keeps_the_existing_success_path(self) -> None:
        ri = _runtime_input()
        self.assertEqual(_today_market_index_integrity_issues({}, ri), [])
        decision = decide_publishing_actions("today_genie", "pass", "validated", [], ri)
        self.assertFalse(decision.suppress_external)


if __name__ == "__main__":
    unittest.main()
