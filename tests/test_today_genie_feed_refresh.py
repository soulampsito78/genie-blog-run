"""Runtime refresh behavior for Today_Geenee feed freshness."""
from __future__ import annotations

import unittest
from unittest import mock

from main import (
    build_runtime_input,
    _today_probe_one_live_source,
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

    def test_source_level_live_success_and_cache_recover_stale_env(self) -> None:
        stale = _feed_bundle("2026-06-08")
        fresh = _feed_bundle("2026-06-15")
        partial_live = {
            "overnight_us_market": fresh["overnight_us_market"],
            "top_market_news": fresh["top_market_news"],
            "today_genie_live_source_results": [
                {"source_id": "overnight_us_market", "live_status": "success"},
                {
                    "source_id": "korea_japan_indices",
                    "live_status": "failed",
                    "error_type": "TimeoutError",
                    "timeout": True,
                },
                {"source_id": "top_market_news", "live_status": "success"},
            ],
        }

        def _cache(source_id: str):
            if source_id == "korea_japan_indices":
                return {
                    "payload": fresh["korea_japan_indices"],
                    "fetched_at": "2026-06-15T21:00:00Z",
                    "payload_sha256": "",
                }
            return None

        with mock.patch("main._probe_today_genie_live_feeds", return_value=partial_live):
            with mock.patch("main._read_today_genie_feed_cache", side_effect=_cache):
                with mock.patch("main._write_today_genie_feed_cache", return_value="written"):
                    out = _refresh_today_genie_feeds_if_needed(
                        stale,
                        "2026-06-16",
                        controlled_active=False,
                    )

        self.assertTrue(out["today_required_feed_contract_passed"])
        self.assertEqual(out["today_genie_feed_refresh_status"], "live_refresh_partial_fallback_applied")
        self.assertTrue(out["today_genie_feed_partial_success"])
        self.assertEqual(out["today_genie_feed_cache_fallback_count"], 1)
        self.assertEqual(out["overnight_us_market"]["as_of"], "2026-06-15")
        self.assertEqual(out["korea_japan_indices"]["as_of"], "2026-06-15")
        self.assertEqual(out["macro_indicators"]["as_of"], "2026-06-15")
        self.assertFalse(any(item["stale"] for item in out["today_genie_feed_staleness"].values()))

    def test_timeout_source_retries_once_only(self) -> None:
        attempts = []

        def _eventual_success() -> dict:
            attempts.append("called")
            if len(attempts) == 1:
                raise TimeoutError("The read operation timed out")
            return {"as_of": "2026-06-15", "indices": {"SPX": {"close": 1, "change_pct": 0}}}

        payload, result = _today_probe_one_live_source("overnight_us_market", _eventual_success)

        self.assertIsNotNone(payload)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["live_status"], "success")

        attempts.clear()

        def _always_timeout() -> dict:
            attempts.append("called")
            raise TimeoutError("The read operation timed out")

        payload, result = _today_probe_one_live_source("overnight_us_market", _always_timeout)

        self.assertIsNone(payload)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["timeout_type"], "read_or_total_timeout")

    def test_stale_cache_is_not_used_as_fresh_fallback(self) -> None:
        stale = _feed_bundle("2026-06-08")
        fresher_live = _feed_bundle("2026-06-15")
        partial_live = {
            "overnight_us_market": fresher_live["overnight_us_market"],
            "top_market_news": fresher_live["top_market_news"],
            "today_genie_live_source_results": [
                {"source_id": "overnight_us_market", "live_status": "success"},
                {"source_id": "korea_japan_indices", "live_status": "failed"},
                {"source_id": "top_market_news", "live_status": "success"},
            ],
        }

        def _stale_cache(source_id: str):
            if source_id == "korea_japan_indices":
                return {
                    "payload": stale["korea_japan_indices"],
                    "fetched_at": "2026-06-08T21:00:00Z",
                    "payload_sha256": "",
                }
            return None

        with mock.patch("main._probe_today_genie_live_feeds", return_value=partial_live):
            with mock.patch("main._read_today_genie_feed_cache", side_effect=_stale_cache):
                out = _refresh_today_genie_feeds_if_needed(
                    stale,
                    "2026-06-16",
                    controlled_active=False,
                )

        self.assertFalse(out["today_required_feed_contract_passed"])
        self.assertIn("korea_japan_indices", out["today_required_feed_contract_stale"])
        korea_result = next(
            item
            for item in out["today_genie_feed_refresh_source_results"]
            if item.get("source_id") == "korea_japan_indices"
        )
        self.assertEqual(korea_result["cache_status"], "hit")
        self.assertEqual(korea_result["selected_source"], "env_stale")

    def test_stale_live_result_does_not_overwrite_cache(self) -> None:
        stale = _feed_bundle("2026-06-08")

        with mock.patch("main._probe_today_genie_live_feeds", return_value=stale):
            with mock.patch("main._write_today_genie_feed_cache") as write_cache:
                _refresh_today_genie_feeds_if_needed(
                    stale,
                    "2026-06-16",
                    controlled_active=False,
                )

        written_sources = [call.args[0] for call in write_cache.call_args_list]
        self.assertNotIn("overnight_us_market", written_sources)
        self.assertNotIn("korea_japan_indices", written_sources)
        self.assertNotIn("macro_indicators", written_sources)
        self.assertNotIn("top_market_news", written_sources)

    def test_unfresh_env_without_cache_blocks_required_contract(self) -> None:
        stale = _feed_bundle("2026-06-08")
        empty_live = {
            "today_genie_live_source_results": [
                {"source_id": "overnight_us_market", "live_status": "failed"},
                {"source_id": "korea_japan_indices", "live_status": "failed"},
                {"source_id": "top_market_news", "live_status": "failed"},
            ]
        }

        with mock.patch("main._probe_today_genie_live_feeds", return_value=empty_live):
            with mock.patch("main._read_today_genie_feed_cache", return_value=None):
                out = _refresh_today_genie_feeds_if_needed(
                    stale,
                    "2026-06-16",
                    controlled_active=False,
                )

        self.assertFalse(out["today_required_feed_contract_passed"])
        self.assertEqual(out["today_genie_feed_refresh_status"], "live_refresh_incomplete_blocked")
        self.assertEqual(
            set(out["today_required_feed_contract_stale"]),
            {
                "overnight_us_market",
                "korea_japan_indices",
                "macro_indicators",
                "top_market_news",
            },
        )
        self.assertTrue(out["manual_action_required"])

    def test_runtime_input_blocks_stale_env_before_generation(self) -> None:
        stale = _feed_bundle("2026-06-08")

        with mock.patch("main._load_today_genie_feed_bundle", return_value=stale):
            with mock.patch("main._probe_today_genie_live_feeds", return_value={}):
                with mock.patch("main._read_today_genie_feed_cache", return_value=None):
                    with mock.patch("main.fetch_seoul_weather_forecast", return_value={}):
                        runtime = build_runtime_input(
                            "today_genie",
                            controlled_test_target_date="2026-06-16",
                        )

        self.assertEqual(runtime["today_genie_feed_gate"], "block")
        self.assertFalse(runtime["today_required_feed_contract_passed"])
        self.assertEqual(runtime["today_genie_feed_gate_reason"], "required_feed_contract_failed")
        self.assertTrue(runtime["manual_action_required"])

    def test_runtime_check_carries_refresh_metadata(self) -> None:
        runtime = {
            "target_date": "2026-06-16",
            "today_genie_feed_source": "env",
            "today_genie_feed_refresh_attempted": True,
            "today_genie_feed_refresh_status": "live_refresh_failed_fallback",
            "today_genie_feed_fallback_used": True,
            "today_genie_feed_fallback_reason": "RuntimeError: network down",
            "today_genie_stale_feeds": ["overnight_us_market"],
            "today_genie_feed_refresh_source_results": [
                {
                    "source_id": "overnight_us_market",
                    "live_status": "failed",
                    "selected_source": "env_stale",
                }
            ],
            "today_required_feed_contract_passed": False,
            "manual_action_required": True,
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
        self.assertFalse(payload["today_required_feed_contract_passed"])
        self.assertTrue(payload["manual_action_required"])
        self.assertEqual(
            payload["today_genie_feed_refresh_source_results"][0]["selected_source"],
            "env_stale",
        )


if __name__ == "__main__":
    unittest.main()
