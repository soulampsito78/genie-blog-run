"""Runtime refresh behavior for Today_Geenee feed freshness."""
from __future__ import annotations

import unittest
from unittest import mock

from main import (
    _refresh_today_genie_feeds_if_needed,
    _runtime_validation_check_payload,
    _today_feed_staleness,
)
from validators import ValidationIssue, _today_stale_date_issues


def _feed_bundle(as_of: str) -> dict:
    return {
        "overnight_us_market": {
            "as_of": as_of,
            "indices": {
                "SPX": {"close": 1, "change_pct": 0, "as_of": as_of},
                "NASDAQ": {"close": 1, "change_pct": 0, "as_of": as_of},
                "DJI": {"close": 1, "change_pct": 0, "as_of": as_of},
            },
        },
        "macro_indicators": {
            "as_of": as_of,
            "headline": "Macro snapshot",
            "rates_watch": "Rates watch",
            "dxy_note": "DXY note",
        },
        "korea_japan_indices": {
            "as_of": as_of,
            "indices": {
                "KOSPI": {"close": 1, "change_pct": 0, "as_of": as_of},
                "KOSDAQ": {"close": 1, "change_pct": 0, "as_of": as_of},
                "NIKKEI": {"close": 1, "change_pct": 0, "as_of": as_of},
            },
        },
        "top_market_news": [{"headline": "Market headline", "source": "CNBC", "date": as_of}],
        "risk_factors": [{"risk": "Macro", "detail": "Market risk"}],
        "feed_json_decode_failed_envs": [],
    }


class TodayGenieFeedRefreshTests(unittest.TestCase):
    def test_fresh_feeds_do_not_report_stale(self) -> None:
        feeds = _feed_bundle("2026-06-15")
        staleness = _today_feed_staleness(feeds, "2026-06-16")
        self.assertFalse(any(item["stale"] for item in staleness.values()))

        issues = _today_stale_date_issues({}, {"target_date": "2026-06-16", **feeds})
        self.assertNotIn("stale_feed_date", [issue.code for issue in issues])

    def test_stale_feeds_still_block(self) -> None:
        feeds = _feed_bundle("2026-06-08")
        issues = _today_stale_date_issues({}, {"target_date": "2026-06-16", **feeds})
        codes = [issue.code for issue in issues]
        self.assertEqual(codes.count("stale_feed_date"), 3)

    def test_live_refresh_replaces_stale_env_feeds(self) -> None:
        stale = _feed_bundle("2026-06-08")
        fresh = _feed_bundle("2026-06-15")

        with mock.patch("main._probe_today_genie_live_feeds", return_value=fresh) as probe:
            out = _refresh_today_genie_feeds_if_needed(
                stale,
                "2026-06-16",
                controlled_active=False,
            )

        probe.assert_called_once()
        self.assertEqual(out["today_genie_feed_source"], "live_refresh")
        self.assertEqual(out["today_genie_feed_refresh_status"], "live_refresh_applied")
        self.assertFalse(out["today_genie_feed_fallback_used"])
        self.assertEqual(out["overnight_us_market"]["as_of"], "2026-06-15")
        self.assertEqual(out["korea_japan_indices"]["as_of"], "2026-06-15")
        self.assertEqual(out["macro_indicators"]["as_of"], "2026-06-15")

    def test_live_refresh_failure_falls_back_with_metadata(self) -> None:
        stale = _feed_bundle("2026-06-08")

        with mock.patch(
            "main._probe_today_genie_live_feeds",
            side_effect=RuntimeError("network down"),
        ):
            out = _refresh_today_genie_feeds_if_needed(
                stale,
                "2026-06-16",
                controlled_active=False,
            )

        self.assertEqual(out["today_genie_feed_source"], "env")
        self.assertEqual(
            out["today_genie_feed_refresh_status"],
            "live_refresh_failed_fallback",
        )
        self.assertTrue(out["today_genie_feed_fallback_used"])
        self.assertIn("network down", out["today_genie_feed_fallback_reason"])
        self.assertEqual(
            set(out["today_genie_stale_feeds"]),
            {"overnight_us_market", "korea_japan_indices", "macro_indicators"},
        )

    def test_live_refresh_returning_stale_data_falls_back_explicitly(self) -> None:
        stale = _feed_bundle("2026-06-08")

        with mock.patch("main._probe_today_genie_live_feeds", return_value=stale):
            out = _refresh_today_genie_feeds_if_needed(
                stale,
                "2026-06-16",
                controlled_active=False,
            )

        self.assertEqual(
            out["today_genie_feed_refresh_status"],
            "live_refresh_returned_stale_fallback",
        )
        self.assertTrue(out["today_genie_feed_fallback_used"])
        self.assertEqual(out["today_genie_feed_fallback_reason"], "live_refresh_returned_stale_feeds")
        self.assertIn("today_genie_live_feed_staleness", out)

    def test_runtime_check_carries_refresh_metadata(self) -> None:
        runtime = {
            "target_date": "2026-06-16",
            "today_genie_feed_source": "env",
            "today_genie_feed_refresh_attempted": True,
            "today_genie_feed_refresh_status": "live_refresh_failed_fallback",
            "today_genie_feed_fallback_used": True,
            "today_genie_feed_fallback_reason": "RuntimeError: network down",
            "today_genie_stale_feeds": ["overnight_us_market"],
        }
        payload = _runtime_validation_check_payload(
            runtime_input=runtime,
            validation_result="block",
            workflow_status="review_required",
            issues=[ValidationIssue("stale_feed_date", "stale", "error")],
            content_quality_warnings=[],
        )

        self.assertEqual(payload["today_genie_feed_source"], "env")
        self.assertTrue(payload["today_genie_feed_refresh_attempted"])
        self.assertTrue(payload["today_genie_feed_fallback_used"])
        self.assertEqual(payload["today_genie_stale_feeds"], ["overnight_us_market"])


if __name__ == "__main__":
    unittest.main()
