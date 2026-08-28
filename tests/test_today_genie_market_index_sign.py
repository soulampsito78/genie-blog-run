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

from main import enforce_today_genie_market_snapshot_from_feeds  # noqa: E402
from publishing_policy import decide_publishing_actions  # noqa: E402
from renderers import (  # noqa: E402
    _fmt_snapshot_change_pct,
    _norm_change_pct,
    _snapshot_row_cells,
    _today_snapshot_grouped_html,
)
from validators import (  # noqa: E402
    ValidationIssue,
    ValidationResult,
    _today_market_index_integrity_issues,
    market_index_validation_report,
)


def _naver_html(
    close: str,
    pts: str,
    pct: str,
    direction_markup: str,
    day: str = "2026.07.29",
    container_class: str = "quotient",
) -> str:
    """Naver index page shape, mirroring the live 2026-07-29 markup.

    Live layout is:
        <div class="quotient dn" id="quotient">
          <em id="now_value">5,663.24</em>
          <span class="fluc" id="change_value_and_rate">
            <span>360.42</span> -5.98%<span class="blind">상승</span>
          </span>
        </div>
    where the container class is the documented direction signal
    (상승장일때 up, 하락장일때 dn) and the blind label is a stale literal.
    """
    points_markup = f"<span>{pts}</span>" if pts is not None else ""
    return f"""
    <div class="{container_class}" id="quotient">
    <em id="now_value">{close}</em>
    <span class="fluc" id="change_value_and_rate">{points_markup} {pct}%{direction_markup}</span>
    </div>
    <em id="time">{day}</em>
    """


def _naver_world_day_html(rows) -> str:
    """Naver world 일별시세 markup: dated close + magnitude-only change.

    Direction lives in the row class, but the parser re-derives it from
    consecutive closes and only requires the class to agree.
    """
    cells = "".join(
        f'<tr class="{css} ">'
        f'<td class="tb_td">{day}</td>'
        f'<td class="tb_td2"><span>{close}</span></td>'
        f'<td class="tb_td3"><span class="point_status">{change}</span></td>'
        f'<td class="tb_td4"><span>0</span></td>'
        f'<td class="tb_td5"><span>0</span></td>'
        f'<td class="tb_td6"><span>0</span></td>'
        f'</tr>'
        for day, close, change, css in rows
    )
    return f'<table id="dayTable"><tbody>{cells}</tbody></table>'


def _blind(word: str) -> str:
    return f'<span class="blind">{word}</span>'


def _naver_day_html(rows: list) -> str:
    """Naver 일별시세 markup. `rate_down` is a static class present on every row."""
    cells = "".join(
        f'<td class="date">{day}</td>'
        f'<td class="number_1">{close}</td>'
        f'<td class="rate_down"><img alt="{arrow}"><span class="tah">{pts}</span></td>'
        f'<td class="number_1"><span class="tah">{pct}%</span></td>'
        f'<td class="number_1">1,000</td></tr>'
        for day, close, pts, pct, arrow in rows
    )
    return f'<table class="type_1">{cells}</table>'


# The same 2026-07-29 incident tape as the settled daily table publishes it: the
# session in progress leads the table, and the settled 07-28 row is the one a
# 07-29 pre-open briefing may quote.
# 2026-07-29 Nikkei tape as the world daily table publishes it: -1.49% on 07-28
# derived from the 07-27 close.
LIVE_NIKKEI_DAY_ROWS = [
    ("2026.07.29", "61,000.00", "434.19", "point_dn"),
    ("2026.07.28", "61,434.19", "929.86", "point_dn"),
    ("2026.07.27", "62,364.05", "100.00", "point_up"),
]

LIVE_DAY_ROWS = {
    "KOSPI": [
        ("2026.07.29", "5,600.00", "63.24", "-1.11", "하락"),
        ("2026.07.28", "5,663.24", "360.42", "-5.98", "하락"),
        ("2026.07.27", "6,023.66", "40.00", "+0.67", "상승"),
    ],
    "KOSDAQ": [
        ("2026.07.29", "650.00", "12.68", "-1.91", "하락"),
        ("2026.07.28", "662.68", "43.17", "-6.12", "하락"),
        ("2026.07.27", "705.85", "5.00", "+0.71", "상승"),
    ],
}


# Live 2026-07-29 Naver tape. Both indexes fell while the blind label read 상승;
# the container class, the signed rate and the close/points arithmetic all agree
# on 하락. Verified against the captured page: 5663.24 + 360.42 = 6023.66 and
# -360.42/6023.66 = -5.98%; 662.68 + 43.17 = 705.85 and -43.17/705.85 = -6.12%.
LIVE_KOSPI = dict(close="5,663.24", pts="360.42", pct="-5.98", container_class="quotient dn")
LIVE_KOSDAQ = dict(close="662.68", pts="43.17", pct="-6.12", container_class="quotient dn")


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


class NaverLiveTapeTests(unittest.TestCase):
    """The live 2026-07-29 tape: a stale 상승 label must not block a real drop."""

    def test_live_kospi_parses_negative_despite_stale_up_label(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSPI, direction_markup=_blind("상승")), "KOSPI")
        self.assertEqual(row["change_pct"], -5.98)
        self.assertEqual(row["change_pts"], -360.42)
        self.assertEqual(row["close"], 5663.24)
        self.assertEqual(row["previous_close"], 6023.66)
        self.assertEqual(row["change_direction"], -1)

    def test_live_kosdaq_parses_negative_despite_stale_up_label(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSDAQ, direction_markup=_blind("상승")), "KOSDAQ")
        self.assertEqual(row["change_pct"], -6.12)
        self.assertEqual(row["change_pts"], -43.17)
        self.assertEqual(row["close"], 662.68)
        self.assertEqual(row["previous_close"], 705.85)

    def test_stale_label_is_recorded_as_a_diagnostic_not_a_failure(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSPI, direction_markup=_blind("상승")), "KOSPI")
        notes = row.get("direction_diagnostics") or []
        self.assertTrue(any("stale_blind_label" in n for n in notes), notes)

    def test_agreeing_label_produces_no_diagnostic(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSPI, direction_markup=_blind("하락")), "KOSPI")
        self.assertEqual(row["change_pct"], -5.98)
        self.assertFalse(row.get("direction_diagnostics"))

    def test_blind_label_alone_cannot_flip_a_corroborated_sign(self) -> None:
        for label in ("상승", "하락", "보합"):
            row = probe.parse_naver_index_html(
                _naver_html(**LIVE_KOSPI, direction_markup=_blind(label)), "KOSPI"
            )
            self.assertEqual(row["change_pct"], -5.98, label)


class NaverDirectionEvidenceTests(unittest.TestCase):
    """Evidence priority: strong signals decide, weak signals only annotate."""

    # An internally consistent rise: 5683.77 -> 6023.66 is +339.89pts = +5.98%.
    UP_TAPE = dict(close="6,023.66", pts="339.89", pct="+5.98", container_class="quotient up")

    def test_a_signed_and_recomputed_and_class_agree_down_with_stale_label(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSPI, direction_markup=_blind("상승")), "KOSPI")
        self.assertEqual(row["change_pct"], -5.98)

    def test_b_signed_and_recomputed_and_class_agree_up(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html(**self.UP_TAPE, direction_markup=_blind("상승")), "KOSPI"
        )
        self.assertEqual(row["change_pct"], 5.98)
        self.assertEqual(row["change_pts"], 339.89)
        self.assertEqual(row["change_direction"], 1)

    def test_c_signed_negative_with_class_dn_and_agreeing_label(self) -> None:
        row = probe.parse_naver_index_html(_naver_html(**LIVE_KOSDAQ, direction_markup=_blind("하락")), "KOSDAQ")
        self.assertEqual(row["change_pct"], -6.12)

    def test_d_signed_negative_but_arithmetic_says_up_blocks(self) -> None:
        """Rate text says -5.98 while close/points only reproduce +5.98."""
        with self.assertRaises(probe.FeedProbeError) as ctx:
            probe.parse_naver_index_html(
                _naver_html(
                    close="6,023.66", pts="339.89", pct="-5.98", container_class="quotient",
                    direction_markup="",
                ),
                "KOSPI",
            )
        self.assertIn("conflicting direction evidence", str(ctx.exception))

    def test_e_signed_negative_with_class_up_and_no_points_blocks(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(
                _naver_html(
                    close="6,023.66", pts=None, pct="-5.98", container_class="quotient up",
                    direction_markup="",
                ),
                "KOSPI",
            )

    def test_f_blind_label_only_is_not_enough_to_establish_direction(self) -> None:
        with self.assertRaises(probe.FeedProbeError) as ctx:
            probe.parse_naver_index_html(
                _naver_html(
                    close="6,023.66", pts=None, pct="5.98", container_class="quotient",
                    direction_markup=_blind("상승"),
                ),
                "KOSPI",
            )
        self.assertIn("undetermined", str(ctx.exception))

    def test_unsigned_magnitude_resolved_by_arithmetic_alone(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html(
                close="5,663.24", pts="360.42", pct="5.98", container_class="quotient",
                direction_markup="",
            ),
            "KOSPI",
        )
        self.assertEqual(row["change_pct"], -5.98)

    def test_unsigned_magnitude_resolved_by_container_class_alone(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html(
                close="5,663.24", pts=None, pct="5.98", container_class="quotient dn",
                direction_markup=_blind("상승"),
            ),
            "KOSPI",
        )
        self.assertEqual(row["change_pct"], -5.98)

    def test_already_signed_rate_is_preserved_without_other_evidence(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html(
                close="6,023.66", pts=None, pct="-10.84", container_class="quotient",
                direction_markup="",
            ),
            "KOSPI",
        )
        self.assertEqual(row["change_pct"], -10.84)

    def test_flat_rate_yields_zero_not_positive(self) -> None:
        row = probe.parse_naver_index_html(
            _naver_html(
                close="6,023.66", pts="0.00", pct="0", container_class="quotient",
                direction_markup=_blind("보합"),
            ),
            "KOSPI",
        )
        self.assertEqual(row["change_pct"], 0.0)
        self.assertEqual(row["change_direction"], 0)

    def test_malformed_numeric_rate_fails(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_index_html(
                _naver_html(**LIVE_KOSPI | {"pct": "n/a"}, direction_markup=_blind("하락")), "KOSPI"
            )

    def test_direction_survives_unmatched_container_close(self) -> None:
        html = (
            '<div class="quotient dn" id="quotient">'
            '<em id="now_value">5,663.24</em>'
            '<dd id="change_value_and_rate"><span>360.42</span> -5.98%'
            '<span class="blind">상승</span></dd>'
            "</div>"
            '<em id="time">2026.07.29</em>'
        )
        row = probe.parse_naver_index_html(html, "KOSPI")
        self.assertEqual(row["change_pct"], -5.98)

    def test_recompute_helper_picks_the_matching_hypothesis(self) -> None:
        self.assertEqual(probe._recomputed_direction_sign(5663.24, 360.42, -5.98), -1)
        self.assertEqual(probe._recomputed_direction_sign(5663.24, 360.42, 5.98), -1)
        self.assertEqual(probe._recomputed_direction_sign(6023.66, 339.89, 5.98), 1)
        self.assertIsNone(probe._recomputed_direction_sign(6023.66, None, 5.98))
        self.assertIsNone(probe._recomputed_direction_sign(6023.66, 339.89, 99.0))


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
        self.assertEqual(_fmt_snapshot_change_pct(0), "0.00%")
        self.assertEqual(_norm_change_pct("0%"), "0%")
        self.assertEqual(_norm_change_pct(_fmt_snapshot_change_pct(0)), "0.00%")

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
        self.assertEqual(report["market_index_validation_status"], "block")

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
            "market_index_missing_required_rows",
            "market_index_warnings",
            "market_index_source_values",
            "market_index_normalized_values",
            "market_index_recomputed_change_rates",
            "market_index_sign_conflicts",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["market_index_validation_status"], "block")
        for values in report["market_index_source_values"].values():
            self.assertEqual(
                set(values), {"close", "change_pct", "market_date", "observation_status"}
            )


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

    def test_live_20260729_tape_end_to_end(self) -> None:
        """Live tape: probe -> runtime context -> snapshot rows -> rendered cells."""
        pages = {
            probe.NAVER_INDEX_DAY["KOSPI"]: _naver_day_html(LIVE_DAY_ROWS["KOSPI"]),
            probe.NAVER_INDEX_DAY["KOSDAQ"]: _naver_day_html(LIVE_DAY_ROWS["KOSDAQ"]),
            probe.NAVER_WORLD_INDEX["NIKKEI"]: _naver_world_day_html(LIVE_NIKKEI_DAY_ROWS),
        }
        for sym, body in PerIndexIsolationTests.LIVE_CNBC.items():
            pages[probe.CNBC_QUOTES[sym]] = body

        def fetch(url: str, timeout_sec: int = 20) -> str:
            return pages[url]

        runtime_input = {
            "target_date": "2026-07-29",
            "input_feed_status": "full",
            "overnight_us_market": probe.probe_overnight_us_market("2026-07-29", fetch),
            "korea_japan_indices": probe.probe_korea_japan_indices("2026-07-29", fetch),
        }

        data = enforce_today_genie_market_snapshot_from_feeds({}, runtime_input)
        rows = {r["label"]: r for r in data["market_snapshot"]}
        self.assertEqual(len(rows), 6)

        expected = {
            "코스피": (5663.24, -5.98, "-5.98%"),
            "코스닥": (662.68, -6.12, "-6.12%"),
            "S&P 500": (7428.78, 0.21, "+0.21%"),
            "나스닥": (24876.912, -0.22, "-0.22%"),
            "니케이": (61434.19, -1.49, "-1.49%"),
            "다우존스": (52747.32, 1.03, "+1.03%"),
        }
        for label, (close, pct, cell) in expected.items():
            row = rows[label]
            self.assertAlmostEqual(row["close"], close, places=3, msg=label)
            self.assertEqual(row["change_pct"], pct, label)
            _, pct_cell = _snapshot_row_cells(row)
            self.assertEqual(_norm_change_pct(pct_cell), cell, label)

        report = market_index_validation_report(data, runtime_input)
        self.assertEqual(report["market_index_validation_status"], "pass")
        self.assertEqual(_today_market_index_integrity_issues(data, runtime_input), [])
        # The settled daily table carries the arrow alt and a signed rate that
        # agree, so it never produces the quote page's stale-blind-label dissent.
        self.assertEqual(report["market_index_warnings"], [])

        html = _today_snapshot_grouped_html(data["market_snapshot"])
        for forbidden in ("+5.98%", "+6.12%", "+0%", "+-", "--"):
            self.assertNotIn(forbidden, html, forbidden)
        for required in ("-5.98%", "-6.12%", "+0.21%", "-0.22%", "-1.49%", "+1.03%"):
            self.assertIn(required, html, required)

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


class PerIndexIsolationTests(unittest.TestCase):
    """One unusable symbol must not discard the symbols that parsed cleanly."""

    LIVE_CNBC = {
        "SPX": '"price":"7,428.78","priceChange":"15.60","priceChangePercent":"0.21","last_time":"2026-07-29"',
        "NASDAQ": '"price":"24,876.912","priceChange":"-55.169","priceChangePercent":"-0.22","last_time":"2026-07-29"',
        "DJI": '"price":"52,747.32","priceChange":"537.24","priceChangePercent":"1.03","last_time":"2026-07-29"',
        "NIKKEI": '"price":"61,434.19","priceChange":"-930.73","priceChangePercent":"-1.49","last_time":"2026-07-29"',
    }

    def _fetch(self, *, broken: tuple[str, ...] = ()) -> object:
        pages = {
            probe.NAVER_INDEX_DAY["KOSPI"]: _naver_day_html(LIVE_DAY_ROWS["KOSPI"]),
            probe.NAVER_INDEX_DAY["KOSDAQ"]: _naver_day_html(LIVE_DAY_ROWS["KOSDAQ"]),
            probe.NAVER_WORLD_INDEX["NIKKEI"]: _naver_world_day_html(LIVE_NIKKEI_DAY_ROWS),
        }
        for sym, body in self.LIVE_CNBC.items():
            pages[probe.CNBC_QUOTES[sym]] = body
        broken_urls = set()
        for sym in broken:
            broken_urls.add(
                probe.NAVER_INDEX_DAY.get(sym)
                or probe.NAVER_WORLD_INDEX.get(sym)
                or probe.CNBC_QUOTES[sym]
            )

        def fetch(url: str, timeout_sec: int = 20) -> str:
            if url in broken_urls:
                raise probe.FeedProbeError(f"simulated source failure for {url}")
            return pages[url]

        return fetch

    def test_all_three_asia_indices_parse(self) -> None:
        out = probe.probe_korea_japan_indices("2026-07-29", self._fetch())
        self.assertEqual(out["indices"]["KOSPI"]["change_pct"], -5.98)
        self.assertEqual(out["indices"]["KOSDAQ"]["change_pct"], -6.12)
        self.assertEqual(out["indices"]["NIKKEI"]["change_pct"], -1.49)
        self.assertEqual(out["errors"], {"KOSPI": None, "KOSDAQ": None, "NIKKEI": None})

    def test_g_kospi_failure_preserves_kosdaq_and_nikkei(self) -> None:
        out = probe.probe_korea_japan_indices("2026-07-29", self._fetch(broken=("KOSPI",)))
        self.assertNotIn("KOSPI", out["indices"])
        self.assertEqual(out["indices"]["KOSDAQ"]["change_pct"], -6.12)
        self.assertEqual(out["indices"]["NIKKEI"]["change_pct"], -1.49)
        self.assertIsNotNone(out["errors"]["KOSPI"])
        self.assertIsNone(out["errors"]["KOSDAQ"])

    def test_h_nikkei_failure_preserves_kospi_and_kosdaq(self) -> None:
        out = probe.probe_korea_japan_indices("2026-07-29", self._fetch(broken=("NIKKEI",)))
        self.assertNotIn("NIKKEI", out["indices"])
        self.assertEqual(out["indices"]["KOSPI"]["change_pct"], -5.98)
        self.assertEqual(out["indices"]["KOSDAQ"]["change_pct"], -6.12)
        self.assertIsNotNone(out["errors"]["NIKKEI"])

    def test_us_symbol_failure_preserves_the_others(self) -> None:
        out = probe.probe_overnight_us_market("2026-07-29", self._fetch(broken=("SPX",)))
        self.assertNotIn("SPX", out["indices"])
        self.assertEqual(out["indices"]["NASDAQ"]["change_pct"], -0.22)
        self.assertEqual(out["indices"]["DJI"]["change_pct"], 1.03)

    def test_total_source_failure_still_raises(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.probe_korea_japan_indices(
                "2026-07-29", self._fetch(broken=("KOSPI", "KOSDAQ", "NIKKEI"))
            )

    def test_summary_marks_a_dropped_symbol_without_crashing(self) -> None:
        out = probe.probe_korea_japan_indices("2026-07-29", self._fetch(broken=("KOSPI",)))
        self.assertIn("KOSPI n/a", out["summary"])
        self.assertIn("KOSDAQ -6.12%", out["summary"])


class ValidationStatusTests(unittest.TestCase):
    """market_index_validation_status must not read 'pass' on an incomplete tape."""

    def test_i_missing_required_row_reports_block(self) -> None:
        ri = _runtime_input({"NIKKEI": None})
        report = market_index_validation_report({}, ri)
        self.assertEqual(report["market_index_validation_status"], "block")
        self.assertTrue(report["market_index_missing_required_rows"])
        self.assertTrue(any("니케이" in m for m in report["market_index_validation_issues"]))

    def test_j_complete_tape_reports_pass(self) -> None:
        report = market_index_validation_report({}, _runtime_input())
        self.assertEqual(report["market_index_validation_status"], "pass")
        self.assertEqual(report["market_index_validation_issues"], [])
        self.assertEqual(report["market_index_missing_required_rows"], [])

    def test_missing_row_reports_the_probe_error(self) -> None:
        ri = _runtime_input({"KOSPI": None})
        ri["korea_japan_indices"]["errors"] = {"KOSPI": "FeedProbeError: simulated"}
        report = market_index_validation_report({}, ri)
        self.assertTrue(
            any("source_parse_failure" in m for m in report["market_index_missing_required_rows"])
        )

    def test_stale_label_warning_does_not_block(self) -> None:
        ri = _runtime_input(
            {"KOSPI": {"direction_diagnostics": ["stale_blind_label:KOSPI:label=+1:resolved=-1"]}}
        )
        report = market_index_validation_report({}, ri)
        self.assertEqual(report["market_index_validation_status"], "pass")
        self.assertTrue(report["market_index_warnings"])
        self.assertEqual(_today_market_index_integrity_issues({}, ri), [])

    def test_sign_conflict_still_reports_block(self) -> None:
        report = market_index_validation_report({}, _runtime_input({"KOSPI": {"change_pct": 10.84}}))
        self.assertEqual(report["market_index_validation_status"], "block")


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
