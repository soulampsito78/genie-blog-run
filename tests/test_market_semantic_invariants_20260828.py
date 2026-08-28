"""Contract regressions for the 2026-08-28 semantic-invariant remediation.

The delivered incident: a recovery run probed Naver's live quote page at 08:24
KST, before the KRX session opened. The page showed KOSPI 6912.37 — the
previous session's close, still standing — with a 0.00 change, because the new
session had not traded. Every stage carried that faithfully, so the mail read
"코스피 6912.37 0%" and "전일 대비 변동 없이" when 2026-08-27 had actually closed
+104.16 / +1.53%.

Nothing in the pipeline was arithmetically wrong. What was missing was the
notion of *which session* an observation describes. These tests pin that
contract, and the adversarial cases prove the pipeline refuses to publish a
false fact rather than repairing its way into one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "ops"))

import probe_today_genie_feeds as probe  # noqa: E402
from main import (  # noqa: E402
    _fmt_signed_pct,
    enforce_today_genie_market_snapshot_from_feeds,
)
from market_observation import (  # noqa: E402
    INCOHERENT,
    SETTLED,
    UNSETTLED_SESSION,
    UNAVAILABLE,
    UNVERIFIABLE_ZERO,
    normalize_index_feed,
    normalize_market_observation,
    prose_fact_conflicts,
    repair_feed_from_history,
)
from validators import (  # noqa: E402
    _today_market_fact_consistency_issues,
    market_index_validation_report,
)

TARGET = "2026-08-28"


def _obs(**slot):
    return normalize_market_observation("KOSPI", slot, target_date=TARGET)


def _naver_day_html(rows) -> str:
    cells = "".join(
        f'<td class="date">{day}</td>'
        f'<td class="number_1">{close}</td>'
        f'<td class="rate_down"><img alt="{arrow}"><span class="tah">{pts}</span></td>'
        f'<td class="number_1"><span class="tah">{pct}%</span></td>'
        f'<td class="number_1">1,000</td></tr>'
        for day, close, pts, pct, arrow in rows
    )
    return f'<table class="type_1">{cells}</table>'


# The real 2026-08-27 tape, exactly as Naver's settled daily table publishes it.
KOSPI_DAY_ROWS = [
    ("2026.08.28", "6,843.91", "68.46", "-0.99", "하락"),
    ("2026.08.27", "6,912.37", "104.16", "+1.53", "상승"),
    ("2026.08.26", "6,808.21", "65.47", "+0.97", "상승"),
]
KOSDAQ_DAY_ROWS = [
    ("2026.08.28", "832.85", "4.80", "-0.57", "하락"),
    ("2026.08.27", "837.65", "10.78", "+1.30", "상승"),
    ("2026.08.26", "826.87", "5.00", "+0.61", "상승"),
]


class NumericObservationInvariantTests(unittest.TestCase):
    """Unknown is unknown; zero is a claim; the fields must agree."""

    def test_missing_rate_never_becomes_zero(self) -> None:
        obs = _obs(close=6912.37, market_date="2026-08-27")
        self.assertEqual(obs["observation_status"], UNAVAILABLE)
        self.assertIsNone(obs["pct_change"])

    def test_blank_rate_string_is_unknown_not_zero(self) -> None:
        # _parse_float used to turn "" into 0.0, which is how a field the source
        # never published became a published 0%.
        self.assertIsNone(probe._parse_float(""))
        self.assertIsNone(probe._parse_float("   "))
        self.assertIsNone(probe._parse_float(None))

    def test_explicit_sourced_zero_remains_zero(self) -> None:
        # A dated settled-session table may publish a genuine flat close.
        obs = _obs(
            close=6912.37,
            previous_close=6912.37,
            change_pct=0.0,
            market_date="2026-08-27",
            session_state="closed",
            settlement_evidence="naver_daily_close_table:2026-08-27",
        )
        self.assertEqual(obs["observation_status"], SETTLED)
        self.assertEqual(obs["pct_change"], 0.0)

    def test_a_quotes_own_previous_close_is_not_zero_evidence(self) -> None:
        """A provider rolling its reference forward looks exactly like a flat close.

        Observed on CNBC's US indices at 03:29 ET on 2026-08-28:
        previous_day_closing had rolled to equal the last settled close and the
        change read 0.00, which would have published "S&P 500 +0.00%" for a
        session that actually closed +0.72%.
        """
        obs = _obs(
            close=7730.99,
            previous_close=7730.99,
            change_pct=0.0,
            market_date="2026-08-27",
            session_state="closed",
        )
        self.assertEqual(obs["observation_status"], UNVERIFIABLE_ZERO)
        self.assertIsNone(obs["pct_change"])

    def test_zero_without_a_sourced_previous_close_is_refused(self) -> None:
        # The exact shape the 08:24 pre-open Naver quote arrived in: the change
        # is zero and the "previous close" is only that zero read backwards.
        obs = _obs(
            close=6912.37,
            change_pts=0.0,
            change_pct=0.0,
            market_date="2026-08-27",
        )
        self.assertEqual(obs["observation_status"], UNVERIFIABLE_ZERO)
        self.assertIsNone(obs["pct_change"])

    def test_close_and_previous_close_derive_point_and_rate(self) -> None:
        obs = _obs(close=6912.37, previous_close=6808.21, market_date="2026-08-27")
        self.assertEqual(obs["observation_status"], SETTLED)
        self.assertAlmostEqual(obs["point_change"], 104.16, places=2)
        self.assertEqual(obs["pct_change"], 1.53)

    def test_inconsistent_supplied_rate_is_repaired_from_previous_close(self) -> None:
        obs = _obs(
            close=6912.37,
            previous_close=6808.21,
            change_pct=0.0,
            market_date="2026-08-27",
        )
        self.assertEqual(obs["observation_status"], SETTLED)
        self.assertEqual(obs["pct_change"], 1.53)
        self.assertTrue(
            any("pct_change_repaired" in r for r in obs["observation_repairs"]),
            obs["observation_repairs"],
        )

    def test_point_change_contradicting_the_rate_is_incoherent(self) -> None:
        obs = _obs(close=6912.37, change_pts=104.16, change_pct=-1.53,
                   market_date="2026-08-27")
        self.assertEqual(obs["observation_status"], INCOHERENT)

    def test_absurd_move_is_refused(self) -> None:
        obs = _obs(close=6912.37, change_pct=91.0, market_date="2026-08-27")
        self.assertEqual(obs["observation_status"], INCOHERENT)


class SessionIdentityTests(unittest.TestCase):
    """An observation belongs to one session, and a pre-open one is not settled."""

    def test_same_day_session_is_not_a_previous_close(self) -> None:
        obs = _obs(close=6912.37, change_pct=0.0, change_pts=0.0, market_date=TARGET)
        self.assertEqual(obs["observation_status"], UNSETTLED_SESSION)

    def test_a_past_session_date_outranks_a_live_market_status(self) -> None:
        """Session state describes the market, not the quote.

        A US close read at 03:29 ET carries curmktstatus PRE_MKT because the
        *next* session is being flagged; the quote itself still belongs to the
        completed prior session, and refusing it blocked every evening run.
        """
        obs = _obs(
            close=7730.99,
            previous_close=7675.70,
            change_pct=0.72,
            market_date="2026-08-27",
            session_state="PRE_MKT",
        )
        self.assertEqual(obs["observation_status"], SETTLED)
        self.assertEqual(obs["pct_change"], 0.72)

    def test_a_live_status_on_the_target_session_is_still_unsettled(self) -> None:
        obs = _obs(
            close=66653.59,
            previous_close=66131.98,
            change_pct=0.79,
            market_date=TARGET,
            session_state="REG_MKT",
        )
        self.assertEqual(obs["observation_status"], UNSETTLED_SESSION)

    def test_a_row_never_inherits_another_instruments_session_date(self) -> None:
        # The feed-level as_of is the max across instruments; using it as a
        # row's date lets one index publish another's session.
        feed = {
            "as_of": "2026-08-28",
            "indices": {
                "KOSPI": {
                    "close": 6912.37,
                    "previous_close": 6808.21,
                    "market_date": "2026-08-27",
                    "session_state": "closed",
                },
                "NIKKEI": {"close": 66653.59, "change_pct": 0.79, "market_date": "2026-08-28"},
            },
        }
        normalized, report = normalize_index_feed(feed, target_date=TARGET)
        self.assertEqual(report["observations"]["KOSPI"]["observation_status"], SETTLED)
        self.assertEqual(
            report["observations"]["NIKKEI"]["observation_status"], UNSETTLED_SESSION
        )
        # The feed date follows the settled rows, not the live one.
        self.assertEqual(normalized["as_of"], "2026-08-27")

    def test_unpublishable_row_keeps_identity_but_loses_its_numbers(self) -> None:
        feed = {
            "as_of": TARGET,
            "indices": {
                "KOSPI": {
                    "close": 6912.37,
                    "change_pct": 0.0,
                    "change_pts": 0.0,
                    "previous_close": 6912.37,
                    "market_date": TARGET,
                    "source_name": "Naver Finance",
                }
            },
        }
        normalized, report = normalize_index_feed(feed, target_date=TARGET)
        row = normalized["indices"]["KOSPI"]
        self.assertNotIn("change_pct", row)
        self.assertEqual(row["source_name"], "Naver Finance")
        self.assertTrue(report["unpublishable"])

    def test_simultaneous_exact_zeros_are_flagged_as_a_pre_session_snapshot(self) -> None:
        feed = {
            "as_of": "2026-08-27",
            "indices": {
                "KOSPI": {"close": 6912.37, "previous_close": 6912.37, "change_pct": 0.0,
                          "market_date": "2026-08-27", "session_state": "closed",
                          "settlement_evidence": "naver_daily_close_table:2026-08-27"},
                "KOSDAQ": {"close": 837.65, "previous_close": 837.65, "change_pct": 0.0,
                           "market_date": "2026-08-27", "session_state": "closed",
                           "settlement_evidence": "naver_daily_close_table:2026-08-27"},
            },
        }
        _normalized, report = normalize_index_feed(feed, target_date=TARGET)
        self.assertTrue(report["all_zero_change"])


class SettledSourceTests(unittest.TestCase):
    """The settled daily table answers the question the briefing actually asks."""

    def test_kospi_20260827_yields_the_real_close_and_rate(self) -> None:
        row = probe.select_settled_naver_day_row(
            _naver_day_html(KOSPI_DAY_ROWS), "KOSPI", target_date=TARGET
        )
        self.assertEqual(row["market_date"], "2026-08-27")
        self.assertEqual(row["close"], 6912.37)
        self.assertEqual(row["change_pts"], 104.16)
        self.assertEqual(row["change_pct"], 1.53)
        self.assertEqual(row["previous_close"], 6808.21)

    def test_kosdaq_20260827_yields_the_real_close_and_rate(self) -> None:
        row = probe.select_settled_naver_day_row(
            _naver_day_html(KOSDAQ_DAY_ROWS), "KOSDAQ", target_date=TARGET
        )
        self.assertEqual(row["market_date"], "2026-08-27")
        self.assertEqual(row["close"], 837.65)
        self.assertEqual(row["change_pts"], 10.78)
        self.assertEqual(row["change_pct"], 1.30)

    def test_selection_is_by_date_not_by_row_position(self) -> None:
        # The session in progress always leads the table.
        row = probe.select_settled_naver_day_row(
            _naver_day_html(KOSPI_DAY_ROWS), "KOSPI", target_date=TARGET
        )
        self.assertNotEqual(row["market_date"], TARGET)

    def test_no_settled_session_before_target_is_an_error_not_a_guess(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_day_row(
                _naver_day_html(KOSPI_DAY_ROWS[:1]), "KOSPI", target_date="2026-08-28"
            )

    def test_arrow_and_signed_rate_must_agree(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_day_row(
                _naver_day_html([("2026.08.27", "6,912.37", "104.16", "+1.53", "하락")]),
                "KOSPI",
                target_date=TARGET,
            )

    def test_static_rate_down_class_never_sets_direction(self) -> None:
        # Every row carries class="rate_down"; a rising session must still read
        # as a gain.
        row = probe.select_settled_naver_day_row(
            _naver_day_html(KOSPI_DAY_ROWS), "KOSPI", target_date=TARGET
        )
        self.assertGreater(row["change_pct"], 0)

    def test_cnbc_quote_carries_session_state_and_previous_close(self) -> None:
        html = (
            '"price":"66,676.62","priceChange":"+544.64","priceChangePercent":"+0.82",'
            '"last_time":"2026-08-28T10:51:40.000+0900","curmktstatus":"REG_MKT",'
            '"previous_day_closing":"66,131.98"'
        )
        row = probe.parse_cnbc_quote_html(html, "NIKKEI")
        self.assertEqual(row["session_state"], "REG_MKT")
        self.assertEqual(row["previous_close"], 66131.98)
        self.assertEqual(row["market_date"], "2026-08-28")


class HistoryRepairTests(unittest.TestCase):
    """A late run reinstates the settled fact; it never invents one."""

    def _unsettled_feed(self):
        return {
            "as_of": TARGET,
            "indices": {
                "NIKKEI": {"close": 66653.59, "change_pct": 0.79, "market_date": TARGET}
            },
        }

    def test_stored_settled_observation_restores_the_row(self) -> None:
        feed, report = normalize_index_feed(self._unsettled_feed(), target_date=TARGET)
        feed, report = repair_feed_from_history(
            feed,
            report,
            target_date=TARGET,
            history={
                "NIKKEI": {
                    "observation_status": SETTLED,
                    "market_date": "2026-08-27",
                    "close": 66131.98,
                    "previous_close": 66262.16,
                    "point_change": -130.18,
                    "pct_change": -0.2,
                }
            },
        )
        row = feed["indices"]["NIKKEI"]
        self.assertEqual(row["observation_status"], SETTLED)
        self.assertEqual(row["change_pct"], -0.2)
        self.assertEqual(row["market_date"], "2026-08-27")
        self.assertEqual(report["unpublishable"], [])

    def test_stored_observation_from_the_target_session_is_refused(self) -> None:
        feed, report = normalize_index_feed(self._unsettled_feed(), target_date=TARGET)
        feed, report = repair_feed_from_history(
            feed,
            report,
            target_date=TARGET,
            history={
                "NIKKEI": {
                    "observation_status": SETTLED,
                    "market_date": TARGET,
                    "close": 66653.59,
                    "pct_change": 0.79,
                }
            },
        )
        self.assertTrue(report["unpublishable"])
        self.assertNotIn("change_pct", feed["indices"]["NIKKEI"])

    def test_stale_stored_observation_is_refused(self) -> None:
        feed, report = normalize_index_feed(self._unsettled_feed(), target_date=TARGET)
        feed, report = repair_feed_from_history(
            feed,
            report,
            target_date=TARGET,
            history={
                "NIKKEI": {
                    "observation_status": SETTLED,
                    "market_date": "2026-07-01",
                    "close": 61434.19,
                    "pct_change": -1.49,
                }
            },
        )
        self.assertTrue(report["unpublishable"])


class ValidationGateTests(unittest.TestCase):
    """A refused observation may not be re-admitted downstream."""

    def _runtime_input(self, kospi_slot):
        return {
            "target_date": TARGET,
            "input_feed_status": "full",
            "korea_japan_indices": {"as_of": "2026-08-27", "indices": {"KOSPI": kospi_slot}},
        }

    def test_unsettled_row_blocks_index_validation(self) -> None:
        report = market_index_validation_report(
            {},
            self._runtime_input(
                {
                    "close": 6912.37,
                    "change_pct": 0.0,
                    "observation_status": UNSETTLED_SESSION,
                    "observation_reason": "pre-open quote",
                    "market_date": TARGET,
                }
            ),
        )
        self.assertEqual(report["market_index_validation_status"], "block")
        self.assertTrue(
            any("확정 세션 관측이 아님" in m for m in report["market_index_validation_issues"])
        )

    def test_settled_row_still_passes(self) -> None:
        report = market_index_validation_report(
            {},
            self._runtime_input(
                {
                    "close": 6912.37,
                    "previous_close": 6808.21,
                    "change_pct": 1.53,
                    "change_pts": 104.16,
                    "change_direction": 1,
                    "observation_status": SETTLED,
                    "market_date": "2026-08-27",
                }
            ),
        )
        self.assertEqual(report["market_index_normalized_values"]["코스피"], 1.53)
        self.assertEqual(report["market_index_sign_conflicts"], [])

    def test_source_values_record_the_observation_identity(self) -> None:
        report = market_index_validation_report(
            {},
            self._runtime_input(
                {
                    "close": 6912.37,
                    "change_pct": 1.53,
                    "previous_close": 6808.21,
                    "observation_status": SETTLED,
                    "market_date": "2026-08-27",
                }
            ),
        )
        values = report["market_index_source_values"]["코스피"]
        self.assertEqual(values["market_date"], "2026-08-27")
        self.assertEqual(values["observation_status"], SETTLED)


class ProseFactConsistencyTests(unittest.TestCase):
    """The model does not get to reinterpret a number the pipeline established."""

    LABELS = {"KOSPI": ("코스피",), "KOSDAQ": ("코스닥",)}
    OBS = {
        "KOSPI": {"observation_status": SETTLED, "pct_change": 1.53},
        "KOSDAQ": {"observation_status": SETTLED, "pct_change": 1.30},
    }

    def test_flat_claim_against_a_real_move_is_a_conflict(self) -> None:
        text = "코스피와 코스닥이 전일 대비 변동 없이 각각 6912.37과 837.65를 기록했습니다."
        conflicts = prose_fact_conflicts(text, self.OBS, self.LABELS)
        self.assertEqual(len(conflicts), 2, conflicts)

    def test_boha_claim_against_a_real_move_is_a_conflict(self) -> None:
        conflicts = prose_fact_conflicts(
            "코스피는 보합세를 보였습니다.", self.OBS, self.LABELS
        )
        self.assertTrue(conflicts)

    def test_wrong_direction_is_a_conflict(self) -> None:
        conflicts = prose_fact_conflicts(
            "코스피가 하락 마감했습니다.", self.OBS, self.LABELS
        )
        self.assertTrue(conflicts)

    def test_correct_prose_is_clean(self) -> None:
        text = "코스피는 1.53% 상승했고 코스닥도 1.30% 올랐습니다."
        self.assertEqual(prose_fact_conflicts(text, self.OBS, self.LABELS), [])

    def test_a_genuinely_flat_index_may_be_called_flat(self) -> None:
        obs = {"KOSPI": {"observation_status": SETTLED, "pct_change": 0.0}}
        self.assertEqual(
            prose_fact_conflicts("코스피는 보합이었습니다.", obs, self.LABELS), []
        )

    def test_refused_observation_never_drives_a_prose_conflict(self) -> None:
        obs = {"KOSPI": {"observation_status": UNSETTLED_SESSION, "pct_change": None}}
        self.assertEqual(
            prose_fact_conflicts("코스피는 보합이었습니다.", obs, self.LABELS), []
        )

    def test_validator_reports_the_delivered_incident_sentence(self) -> None:
        runtime_input = {
            "target_date": TARGET,
            "korea_japan_indices": {
                "indices": {
                    "KOSPI": {
                        "close": 6912.37,
                        "change_pct": 1.53,
                        "observation_status": SETTLED,
                        "market_date": "2026-08-27",
                    }
                }
            },
        }
        data = {
            "market_setup": (
                "아시아 시장에서는 코스피와 코스닥이 전일 대비 변동 없이 "
                "각각 6912.37과 837.65를 기록했습니다."
            )
        }
        issues = _today_market_fact_consistency_issues(data, runtime_input)
        self.assertEqual([i.code for i in issues], ["market_fact_narrative_conflict"])


class AdversarialMutationTests(unittest.TestCase):
    """Injected corruption must never reach a reader as a fact."""

    def _feed(self, kospi):
        return {"as_of": "2026-08-27", "indices": {"KOSPI": kospi}}

    def test_close_correct_rate_missing(self) -> None:
        _n, report = normalize_index_feed(
            self._feed({"close": 6912.37, "market_date": "2026-08-27"}),
            target_date=TARGET,
        )
        self.assertTrue(report["unpublishable"])

    def test_close_correct_rate_wrong(self) -> None:
        normalized, _report = normalize_index_feed(
            self._feed(
                {
                    "close": 6912.37,
                    "previous_close": 6808.21,
                    "change_pct": -9.99,
                    "market_date": "2026-08-27",
                }
            ),
            target_date=TARGET,
        )
        self.assertEqual(normalized["indices"]["KOSPI"]["change_pct"], 1.53)

    def test_close_correct_rate_zeroed(self) -> None:
        # The delivered incident, injected directly.
        normalized, report = normalize_index_feed(
            self._feed(
                {
                    "close": 6912.37,
                    "change_pct": 0.0,
                    "change_pts": 0.0,
                    "previous_close": 6912.37,
                    "market_date": "2026-08-28",
                }
            ),
            target_date=TARGET,
        )
        self.assertNotIn("change_pct", normalized["indices"]["KOSPI"])
        self.assertTrue(report["unpublishable"])

    def test_refused_row_is_dropped_from_the_customer_number_table(self) -> None:
        runtime_input = {
            "korea_japan_indices": {
                "as_of": "2026-08-27",
                "indices": {
                    "KOSPI": {"close": 6912.37, "observation_status": UNSETTLED_SESSION},
                    "KOSDAQ": {
                        "close": 837.65,
                        "change_pct": 1.30,
                        "observation_status": SETTLED,
                        "market_date": "2026-08-27",
                        "source_name": "Naver Finance",
                        "source_url": "https://finance.naver.com/",
                        "verified_at": "2026-08-28T00:00:00Z",
                    },
                },
            }
        }
        data = enforce_today_genie_market_snapshot_from_feeds({}, runtime_input)
        labels = {row["label"] for row in data.get("market_snapshot", [])}
        self.assertNotIn("코스피", labels)
        self.assertIn("코스닥", labels)

    def test_model_supplied_snapshot_cannot_override_the_canonical_number(self) -> None:
        runtime_input = {
            "korea_japan_indices": {
                "as_of": "2026-08-27",
                "indices": {
                    "KOSPI": {
                        "close": 6912.37,
                        "change_pct": 1.53,
                        "observation_status": SETTLED,
                        "market_date": "2026-08-27",
                        "source_name": "Naver Finance",
                        "source_url": "https://finance.naver.com/",
                        "verified_at": "2026-08-28T00:00:00Z",
                    }
                },
            }
        }
        model_data = {
            "market_snapshot": [{"label": "코스피", "value": "6912.37 (0%)", "change_pct": 0.0}]
        }
        data = enforce_today_genie_market_snapshot_from_feeds(model_data, runtime_input)
        kospi = next(r for r in data["market_snapshot"] if r["label"] == "코스피")
        self.assertEqual(kospi["change_pct"], 1.53)
        self.assertIn("+1.53%", kospi["value"])

    def test_an_evidenced_zero_renders_as_a_measured_rate(self) -> None:
        self.assertEqual(_fmt_signed_pct(0.0), "0.00%")
        self.assertEqual(_fmt_signed_pct(1.53), "+1.53%")
        self.assertEqual(_fmt_signed_pct(None), "")


class ProgramBoundaryTests(unittest.TestCase):
    """Today, Global and Korea must not move each other's semantics."""

    def test_market_observation_contract_is_today_only(self) -> None:
        import keysuri_global_signal_scoring
        import keysuri_korea_signal_scoring
        import keysuri_service_full_run

        for module in (
            keysuri_global_signal_scoring,
            keysuri_korea_signal_scoring,
            keysuri_service_full_run,
        ):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("market_observation", source, module.__name__)

    def test_global_classifier_is_unchanged_by_the_today_repair(self) -> None:
        from keysuri_global_signal_scoring import classify_global_tech_category

        primary, _score, _conf, _reasons = classify_global_tech_category(
            "Startup unveils companion robot for home care",
            feed_default="ai_software_platform",
        )
        self.assertNotIn(primary, {"battery_ev_energy_grid"})

    def test_korea_classifier_stays_inside_the_korea_vocabulary(self) -> None:
        from keysuri_global_signal_scoring import GLOBAL_TECH_CATEGORIES
        from keysuri_korea_signal_scoring import (
            KOREA_TECH_CATEGORIES,
            classify_korea_tech_category,
        )

        primary, _score, _conf, _reasons = classify_korea_tech_category(
            "국내 스타트업, 가정용 돌봄 로봇 공개",
            feed_default="korea_platform_cloud_saas",
        )
        self.assertIn(primary, set(KOREA_TECH_CATEGORIES))
        korea_only = set(KOREA_TECH_CATEGORIES) - set(GLOBAL_TECH_CATEGORIES)
        self.assertTrue(korea_only, "Korea must keep a vocabulary of its own")

    def test_global_classifier_stays_inside_the_global_vocabulary(self) -> None:
        from keysuri_global_signal_scoring import (
            GLOBAL_TECH_CATEGORIES,
            classify_global_tech_category,
        )

        primary, _score, _conf, _reasons = classify_global_tech_category(
            "Startup unveils companion robot for home care",
            feed_default="ai_software_platform",
        )
        self.assertIn(primary, set(GLOBAL_TECH_CATEGORIES))

    def test_today_renderer_zero_change_does_not_touch_keysuri_surfaces(self) -> None:
        import keysuri_visible_text

        source = Path(keysuri_visible_text.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_fmt_snapshot_change_pct", source)


if __name__ == "__main__":
    unittest.main()


def _naver_world_day_html(rows) -> str:
    cells = "".join(
        f'<tr class="{css} "><td class="tb_td">{day}</td>'
        f'<td class="tb_td2"><span>{close}</span></td>'
        f'<td class="tb_td3"><span class="point_status">{change}</span></td>'
        f'<td class="tb_td4"><span>0</span></td><td class="tb_td5"><span>0</span></td>'
        f'<td class="tb_td6"><span>0</span></td></tr>'
        for day, close, change, css in rows
    )
    return f'<table id="dayTable"><tbody>{cells}</tbody></table>'


# The real Nikkei tape from Naver's world daily table.
NIKKEI_DAY_ROWS = [
    ("2026.08.28", "66,405.56", "273.58", "point_up"),
    ("2026.08.27", "66,131.98", "130.18", "point_dn"),
    ("2026.08.26", "66,262.16", "405.73", "point_up"),
    ("2026.08.25", "65,856.43", "328.34", "point_up"),
]


class SettledNikkeiTests(unittest.TestCase):
    """The Nikkei residual: a dated completed session, not a live quote.

    CNBC's .N225 resets its change at the Tokyo pre-open while its timestamp
    still lags the prior session, which is how "니케이 66131.98 0%" shipped on
    2026-08-28 when the session had actually closed -130.18 / -0.20%.
    """

    def _row(self, target):
        return probe.select_settled_naver_world_row(
            _naver_world_day_html(NIKKEI_DAY_ROWS), "NIKKEI", target_date=target
        )

    def test_20260828_target_yields_the_settled_0827_session(self) -> None:
        row = self._row("2026-08-28")
        self.assertEqual(row["market_date"], "2026-08-27")
        self.assertEqual(row["close"], 66131.98)
        self.assertEqual(row["change_pts"], -130.18)
        self.assertEqual(row["change_pct"], -0.2)
        self.assertEqual(row["previous_close"], 66262.16)

    def test_monday_target_yields_the_friday_close(self) -> None:
        # Monday 06:30 must not depend on Monday's live quote state.
        row = self._row("2026-08-31")
        self.assertEqual(row["market_date"], "2026-08-28")
        self.assertEqual(row["close"], 66405.56)
        self.assertEqual(row["change_pct"], 0.41)

    def test_change_is_derived_from_consecutive_closes(self) -> None:
        row = self._row("2026-08-28")
        self.assertAlmostEqual(
            row["close"] - row["previous_close"], row["change_pts"], places=2
        )

    def test_a_row_class_contradicting_the_arithmetic_is_refused(self) -> None:
        rows = [
            ("2026.08.28", "66,405.56", "273.58", "point_up"),
            ("2026.08.27", "66,131.98", "130.18", "point_up"),  # actually fell
            ("2026.08.26", "66,262.16", "405.73", "point_up"),
        ]
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                _naver_world_day_html(rows), "NIKKEI", target_date="2026-08-28"
            )

    def test_a_published_magnitude_disagreeing_with_arithmetic_is_refused(self) -> None:
        rows = [
            ("2026.08.27", "66,131.98", "999.99", "point_dn"),
            ("2026.08.26", "66,262.16", "405.73", "point_up"),
        ]
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                _naver_world_day_html(rows), "NIKKEI", target_date="2026-08-28"
            )

    def test_no_preceding_session_is_an_error_not_a_guess(self) -> None:
        rows = [("2026.08.27", "66,131.98", "130.18", "point_dn")]
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                _naver_world_day_html(rows), "NIKKEI", target_date="2026-08-28"
            )

    def test_settled_row_carries_settlement_evidence(self) -> None:
        row = self._row("2026-08-28")
        self.assertIn("naver_world_daily_close_table", row["settlement_evidence"])
        self.assertEqual(row["session_state"], "closed")

    def test_the_observation_contract_accepts_it(self) -> None:
        obs = normalize_market_observation(
            "NIKKEI", self._row("2026-08-28"), target_date="2026-08-28"
        )
        self.assertEqual(obs["observation_status"], SETTLED)
        self.assertEqual(obs["pct_change"], -0.2)
