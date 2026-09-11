"""Deterministic replay of the 2026-09-11 Today_Geenee Nikkei feed incident.

Naver retired the server-rendered world 일별시세 table and left a client-rendered
shell behind. The fetch kept succeeding, the regex kept matching nothing, and
the Nikkei observation quietly stopped refreshing after 2026-09-09 — so the
2026-09-11 06:30 natural run and the 08:36 operator recovery both blocked on
``market_snapshot_missing_required_rows`` with five of six index rows healthy.

The rules these tests pin:

- a payload that is not a session list is an error, never zero rows
- the settled session is still re-derived arithmetically from consecutive closes
- the real 2026-09-10 Tokyo close reaches a 2026-09-11 briefing
"""
from __future__ import annotations

import json
import unittest

from ops import probe_today_genie_feeds as probe


# The Next.js shell Naver served in place of the retired daily table.
SPA_SHELL_HTML = (
    '<!DOCTYPE html><html lang="ko"><head><meta charSet="utf-8"/>'
    '<link rel="stylesheet" href="https://ssl.pstatic.net/imgstock/fn/real/pc/_next/'
    'static/css/9349f3b462cc41d1.css"/></head><body><div id="__next"></div></body></html>'
)

# The sessions the price API published for .N225 around the incident.
N225_SESSIONS = [
    ("2026-09-10", "65,270.95", "128.17", "RISING"),
    ("2026-09-09", "65,142.78", "-126.55", "FALLING"),
    ("2026-09-08", "65,269.33", "-1,130.51", "FALLING"),
    ("2026-09-07", "66,399.84", "1,378.90", "RISING"),
]


def _payload(sessions) -> str:
    return json.dumps(
        [
            {
                "localTradedAt": f"{day}T15:45:02+09:00",
                "closePrice": close,
                "compareToPreviousClosePrice": change,
                "compareToPreviousPrice": {"name": name},
            }
            for day, close, change, name in sessions
        ]
    )


class RetiredTableIsAnErrorNotSilence(unittest.TestCase):
    def test_the_spa_shell_raises_instead_of_parsing_to_zero_rows(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_world_price_rows(SPA_SHELL_HTML, "NIKKEI")

    def test_a_non_list_payload_is_refused(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_naver_world_price_rows(json.dumps({"error": "nope"}), "NIKKEI")

    def test_selection_surfaces_the_refusal(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                SPA_SHELL_HTML, "NIKKEI", target_date="2026-09-11"
            )


class The20260911BriefingGetsItsNikkeiRow(unittest.TestCase):
    def _row(self, target="2026-09-11"):
        return probe.select_settled_naver_world_row(
            _payload(N225_SESSIONS), "NIKKEI", target_date=target
        )

    def test_the_settled_0910_session_reaches_a_0911_briefing(self) -> None:
        row = self._row()
        self.assertEqual(row["market_date"], "2026-09-10")
        self.assertEqual(row["close"], 65270.95)
        self.assertEqual(row["change_pts"], 128.17)
        self.assertEqual(row["change_pct"], 0.2)
        self.assertEqual(row["previous_close"], 65142.78)
        self.assertEqual(row["session_state"], "closed")

    def test_the_change_is_derived_from_consecutive_closes(self) -> None:
        row = self._row()
        self.assertAlmostEqual(
            row["close"] - row["previous_close"], row["change_pts"], places=2
        )

    def test_the_0909_session_still_reads_as_it_did_before_the_migration(self) -> None:
        # The value the stalled cache held, re-read from the replacement source.
        row = self._row("2026-09-10")
        self.assertEqual(row["market_date"], "2026-09-09")
        self.assertEqual(row["close"], 65142.78)
        self.assertEqual(row["change_pts"], -126.55)
        self.assertEqual(row["change_pct"], -0.19)

    def test_a_direction_token_contradicting_the_arithmetic_is_refused(self) -> None:
        lying = [("2026-09-10", "65,270.95", "128.17", "FALLING")] + N225_SESSIONS[1:]
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                _payload(lying), "NIKKEI", target_date="2026-09-11"
            )

    def test_a_published_magnitude_disagreeing_with_arithmetic_is_refused(self) -> None:
        lying = [("2026-09-10", "65,270.95", "999.99", "RISING")] + N225_SESSIONS[1:]
        with self.assertRaises(probe.FeedProbeError):
            probe.select_settled_naver_world_row(
                _payload(lying), "NIKKEI", target_date="2026-09-11"
            )

    def test_an_unsettled_tokyo_session_is_not_quoted(self) -> None:
        # 15:45 JST rows exist, but a same-day session before the 15:10 cutoff
        # may not be published as settled.
        from datetime import datetime
        from zoneinfo import ZoneInfo

        pre_close = datetime(2026, 9, 10, 11, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        row = probe.select_settled_naver_world_row(
            _payload(N225_SESSIONS),
            "NIKKEI",
            target_date="2026-09-11",
            now_jst=pre_close,
        )
        self.assertEqual(row["market_date"], "2026-09-09")


if __name__ == "__main__":
    unittest.main()
