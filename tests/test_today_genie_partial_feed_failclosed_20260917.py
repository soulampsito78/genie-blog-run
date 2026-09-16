"""Fail-closed handling of a partially parsed Today_Geenee live feed.

Incident of 2026-09-17: the live overnight feed carried SPX and DJI but lost
NASDAQ to a TimeoutError. The partial payload was treated as fresh, selected
over a complete cache and written back to that cache, after which the six-row
number table validation blocked the run.
"""
from __future__ import annotations

import unittest
from unittest import mock

from main import (
    _refresh_today_genie_feeds_if_needed,
    _today_feed_payload_freshness,
    _today_required_feed_contract,
    _today_select_feed_source,
)
from ops.probe_today_genie_feeds import (
    CNBC_QUOTES,
    _probe_one_index,
    probe_overnight_us_market,
)

TARGET_DATE = "2026-09-17"
FEED_AS_OF = "2026-09-16"


def _index_row(close: float) -> dict:
    return {"close": close, "change_pct": 0.25, "as_of": FEED_AS_OF}


def _overnight(*, include_nasdaq: bool = True) -> dict:
    indices = {"SPX": _index_row(6000.0), "DJI": _index_row(44000.0)}
    if include_nasdaq:
        indices["NASDAQ"] = _index_row(20000.0)
    return {"as_of": FEED_AS_OF, "indices": indices}


def _korea_japan() -> dict:
    return {
        "as_of": FEED_AS_OF,
        "indices": {
            "KOSPI": _index_row(3200.0),
            "KOSDAQ": _index_row(800.0),
            "NIKKEI": _index_row(42000.0),
        },
    }


def _feed_bundle(as_of: str) -> dict:
    return {
        "overnight_us_market": {**_overnight(), "as_of": as_of},
        "macro_indicators": {
            "as_of": as_of,
            "headline": "Macro snapshot",
            "rates_watch": "Rates watch",
            "dxy_note": "DXY note",
        },
        "korea_japan_indices": {**_korea_japan(), "as_of": as_of},
        "top_market_news": [{"headline": "Market headline", "source": "CNBC", "date": as_of}],
        "risk_factors": [{"risk": "Macro", "detail": "Market risk"}],
        "feed_json_decode_failed_envs": [],
    }


class PartialFeedFreshnessTests(unittest.TestCase):
    def test_partial_overnight_feed_is_not_fresh(self) -> None:
        info = _today_feed_payload_freshness(
            "overnight_us_market",
            _overnight(include_nasdaq=False),
            TARGET_DATE,
        )

        self.assertFalse(info["fresh"])
        self.assertTrue(info["stale"])
        self.assertEqual(info["reason"], "missing_required_index_rows")
        self.assertEqual(info["missing_indices"], ["NASDAQ"])

    def test_index_row_without_change_pct_is_not_fresh(self) -> None:
        payload = _overnight()
        payload["indices"]["NASDAQ"] = {"close": 20000.0, "change_pct": None}

        info = _today_feed_payload_freshness("overnight_us_market", payload, TARGET_DATE)

        self.assertFalse(info["fresh"])
        self.assertEqual(info["missing_indices"], ["NASDAQ"])

    def test_complete_feed_stays_fresh(self) -> None:
        self.assertTrue(
            _today_feed_payload_freshness("overnight_us_market", _overnight(), TARGET_DATE)["fresh"]
        )
        self.assertTrue(
            _today_feed_payload_freshness("korea_japan_indices", _korea_japan(), TARGET_DATE)["fresh"]
        )

    def test_required_feed_contract_reports_partial_feed_as_missing(self) -> None:
        feeds = _feed_bundle(FEED_AS_OF)
        feeds["overnight_us_market"] = _overnight(include_nasdaq=False)

        contract = _today_required_feed_contract(feeds, TARGET_DATE)

        self.assertFalse(contract["passed"])
        self.assertIn("overnight_us_market", contract["missing"])


class PartialFeedSelectionTests(unittest.TestCase):
    def test_partial_live_feed_is_not_selected_and_not_cached(self) -> None:
        cache_record = {
            "payload": _overnight(),
            "fetched_at": "2026-09-17T05:30:00Z",
            "payload_sha256": "",
        }

        with mock.patch("main._read_today_genie_feed_cache", return_value=cache_record):
            with mock.patch("main._write_today_genie_feed_cache", return_value="written") as write:
                payload, result = _today_select_feed_source(
                    "overnight_us_market",
                    live_feeds={"overnight_us_market": _overnight(include_nasdaq=False)},
                    env_feeds={},
                    target_date=TARGET_DATE,
                    live_results={"overnight_us_market": {"live_status": "success"}},
                )

        write.assert_not_called()
        self.assertEqual(result["selected_source"], "cache")
        self.assertEqual(result["live_freshness"]["reason"], "missing_required_index_rows")
        self.assertEqual(payload, cache_record["payload"])
        self.assertIn("NASDAQ", payload["indices"])

    def test_partial_live_refresh_keeps_complete_cache_and_passes_contract(self) -> None:
        stale_env = _feed_bundle("2026-09-08")
        fresh = _feed_bundle(FEED_AS_OF)
        partial_live = {
            "overnight_us_market": _overnight(include_nasdaq=False),
            "korea_japan_indices": fresh["korea_japan_indices"],
            "top_market_news": fresh["top_market_news"],
            "today_genie_live_source_results": [
                {"source_id": "overnight_us_market", "live_status": "success"},
                {"source_id": "korea_japan_indices", "live_status": "success"},
                {"source_id": "top_market_news", "live_status": "success"},
            ],
        }

        def _cache(source_id: str):
            if source_id == "overnight_us_market":
                return {
                    "payload": _overnight(),
                    "fetched_at": "2026-09-17T05:30:00Z",
                    "payload_sha256": "",
                }
            return None

        with mock.patch("main._probe_today_genie_live_feeds", return_value=partial_live):
            with mock.patch("main._read_today_genie_feed_cache", side_effect=_cache):
                with mock.patch(
                    "main._write_today_genie_feed_cache", return_value="written"
                ) as write:
                    out = _refresh_today_genie_feeds_if_needed(
                        stale_env,
                        TARGET_DATE,
                        controlled_active=False,
                    )

        cached_sources = [call.args[0] for call in write.call_args_list]
        self.assertNotIn("overnight_us_market", cached_sources)
        self.assertIn("NASDAQ", out["overnight_us_market"]["indices"])
        self.assertTrue(out["today_required_feed_contract_passed"])

    def test_partial_live_without_usable_cache_fails_closed(self) -> None:
        stale_env = _feed_bundle("2026-09-08")
        fresh = _feed_bundle(FEED_AS_OF)
        partial_live = {
            "overnight_us_market": _overnight(include_nasdaq=False),
            "korea_japan_indices": fresh["korea_japan_indices"],
            "top_market_news": fresh["top_market_news"],
            "today_genie_live_source_results": [
                {"source_id": "overnight_us_market", "live_status": "success"},
                {"source_id": "korea_japan_indices", "live_status": "success"},
                {"source_id": "top_market_news", "live_status": "success"},
            ],
        }

        with mock.patch("main._probe_today_genie_live_feeds", return_value=partial_live):
            with mock.patch("main._read_today_genie_feed_cache", return_value=None):
                with mock.patch("main._write_today_genie_feed_cache", return_value="written"):
                    out = _refresh_today_genie_feeds_if_needed(
                        stale_env,
                        TARGET_DATE,
                        controlled_active=False,
                    )

        self.assertFalse(out["today_required_feed_contract_passed"])
        self.assertEqual(out["today_genie_feed_gate_reason"], "required_feed_contract_failed")
        self.assertTrue(out["manual_action_required"])
        self.assertEqual(
            out["today_genie_feed_refresh_status"],
            "live_refresh_incomplete_blocked",
        )


class ProbeIndexTimeoutRetryTests(unittest.TestCase):
    def _parse(self, html: str, symbol: str) -> dict:
        return {"close": 20000.0, "change_pct": 0.25, "as_of": FEED_AS_OF, "html": html}

    def test_timeout_then_success_returns_row(self) -> None:
        calls = []

        def _fetch(url: str, timeout_sec: int) -> str:
            calls.append(url)
            if len(calls) == 1:
                raise TimeoutError("The read operation timed out")
            return "<html>ok</html>"

        row, error = _probe_one_index(
            "NASDAQ",
            _fetch,
            20,
            url=CNBC_QUOTES["NASDAQ"],
            parse=self._parse,
        )

        self.assertEqual(len(calls), 2)
        self.assertIsNone(error)
        self.assertIsNotNone(row)
        self.assertEqual(row["close"], 20000.0)

    def test_repeated_timeout_retries_once_only_and_reports_error(self) -> None:
        calls = []

        def _fetch(url: str, timeout_sec: int) -> str:
            calls.append(url)
            raise TimeoutError("The read operation timed out")

        row, error = _probe_one_index(
            "NASDAQ",
            _fetch,
            20,
            url=CNBC_QUOTES["NASDAQ"],
            parse=self._parse,
        )

        self.assertEqual(len(calls), 2)
        self.assertIsNone(row)
        self.assertIn("TimeoutError", error)

    def test_non_timeout_failure_is_not_retried(self) -> None:
        calls = []

        def _fetch(url: str, timeout_sec: int) -> str:
            calls.append(url)
            raise ValueError("bad markup")

        row, error = _probe_one_index(
            "NASDAQ",
            _fetch,
            20,
            url=CNBC_QUOTES["NASDAQ"],
            parse=self._parse,
        )

        self.assertEqual(len(calls), 1)
        self.assertIsNone(row)
        self.assertIn("ValueError", error)


class ProbeOvernightIsolationTests(unittest.TestCase):
    def _fetch_factory(self, *, timeout_for: str, always: bool):
        calls: list[str] = []

        def _fetch(url: str, timeout_sec: int) -> str:
            calls.append(url)
            if url == CNBC_QUOTES[timeout_for] and (always or calls.count(url) == 1):
                raise TimeoutError("The read operation timed out")
            return "<html>ok</html>"

        return _fetch, calls

    def _parsed(self, html: str, symbol: str) -> dict:
        return {
            "close": 1000.0,
            "change_pts": 1.0,
            "change_pct": 0.1,
            "as_of": FEED_AS_OF,
            "source_url": CNBC_QUOTES[symbol],
        }

    def test_transient_nasdaq_timeout_recovers_complete_feed(self) -> None:
        fetch, calls = self._fetch_factory(timeout_for="NASDAQ", always=False)

        with mock.patch(
            "ops.probe_today_genie_feeds.parse_cnbc_quote_html",
            side_effect=self._parsed,
        ):
            feed = probe_overnight_us_market(TARGET_DATE, fetch)

        self.assertEqual(calls.count(CNBC_QUOTES["NASDAQ"]), 2)
        self.assertEqual(set(feed["indices"]), {"SPX", "NASDAQ", "DJI"})
        self.assertIsNone(feed["errors"]["NASDAQ"])

    def test_persistent_nasdaq_timeout_leaves_row_absent(self) -> None:
        fetch, calls = self._fetch_factory(timeout_for="NASDAQ", always=True)

        with mock.patch(
            "ops.probe_today_genie_feeds.parse_cnbc_quote_html",
            side_effect=self._parsed,
        ):
            feed = probe_overnight_us_market(TARGET_DATE, fetch)

        self.assertEqual(calls.count(CNBC_QUOTES["NASDAQ"]), 2)
        self.assertEqual(set(feed["indices"]), {"SPX", "DJI"})
        self.assertIn("TimeoutError", feed["errors"]["NASDAQ"])
        self.assertFalse(
            _today_feed_payload_freshness("overnight_us_market", feed, TARGET_DATE)["fresh"]
        )


if __name__ == "__main__":
    unittest.main()
