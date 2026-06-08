"""Tests for ops/probe_today_genie_feeds.py (no internet; mocked fetch)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_OPS = Path(__file__).resolve().parents[1] / "ops"
sys.path.insert(0, str(_OPS))

import probe_today_genie_feeds as probe  # noqa: E402


def _cnbc_html(price: str, change: str, pct: str, last_time: str) -> str:
    return (
        f'"price":"{price}","priceChange":"{change}","priceChangePercent":"{pct}",'
        f'"priceCurrency":"USD"}}</script>'
        f'"last_time":"{last_time}"'
    )


def _naver_html(close: str, pts: str, pct: str, direction: str, day: str) -> str:
    return f"""
    <em id="now_value">{close}</em>
    <span id="change_value_and_rate"><span>{pts}</span> {pct}%<span class="blind">{direction}</span></span>
    <em id="time">{day}</em>
    """


def _rss_xml(items: list[tuple[str, str]]) -> str:
    chunks = ['<?xml version="1.0"?><rss><channel>']
    for title, pub in items:
        chunks.append(
            f"<item><title><![CDATA[{title}]]></title><pubDate>{pub}</pubDate></item>"
        )
    chunks.append("</channel></rss>")
    return "".join(chunks)


class TodayGenieFeedProbeTests(unittest.TestCase):
    TARGET = "2026-06-09"

    def setUp(self) -> None:
        self._orig_feeds: dict[str, str] = {}
        for fname in probe.FEED_FILES.values():
            path = probe.FEEDS_DIR / fname
            if path.is_file():
                self._orig_feeds[fname] = path.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        for fname, content in self._orig_feeds.items():
            (probe.FEEDS_DIR / fname).write_text(content, encoding="utf-8")

    def _mock_fetch(self) -> mock.Mock:
        def _fetch(url: str, timeout_sec: int = 20) -> str:
            if url == probe.CNBC_QUOTES["SPX"]:
                return _cnbc_html("7,405.73", "21.99", "0.30", "2026-06-08T16:56:48.000-0400")
            if url == probe.CNBC_QUOTES["NASDAQ"]:
                return _cnbc_html("25,929.663", "220.231", "0.86", "2026-06-08T17:15:59.000-0400")
            if url == probe.CNBC_QUOTES["DJI"]:
                return _cnbc_html("50,786.01", "-80.77", "-0.16", "2026-06-08T16:56:57.000-0400")
            if url == probe.CNBC_QUOTES["NIKKEI"]:
                return _cnbc_html("64,024.60", "UNCH", "UNCH", "2026-06-08")
            if url == probe.NAVER_INDEX["KOSPI"]:
                return _naver_html("7,484.41", "676.18", "+8.29", "상승", "2026.06.08")
            if url == probe.NAVER_INDEX["KOSDAQ"]:
                return _naver_html("911.39", "91.05", "+9.08", "상승", "2026.06.08")
            if url == probe.CNBC_MARKET_NEWS_RSS:
                return _rss_xml(
                    [
                        ("US stocks rise on AI optimism", "Mon, 08 Jun 2026 21:39:02 GMT"),
                        ("Oil slips as traders watch Middle East", "Mon, 08 Jun 2026 20:43:04 GMT"),
                        ("Asia shares mixed into Tuesday open", "Mon, 08 Jun 2026 19:00:00 GMT"),
                        ("Fed speakers keep rates path in focus", "Mon, 08 Jun 2026 18:00:00 GMT"),
                    ]
                )
            raise probe.FeedProbeError(f"unexpected url {url}")

        return mock.Mock(side_effect=_fetch)

    def test_valid_us_market_writes_schema(self) -> None:
        fetch = self._mock_fetch()
        out = probe.probe_overnight_us_market(self.TARGET, fetch)
        self.assertEqual(out["as_of"], "2026-06-08")
        for sym in ("SPX", "NASDAQ", "DJI"):
            self.assertIn(sym, out["indices"])
            self.assertIsNotNone(out["indices"][sym]["close"])
            self.assertIn("source_url", out["indices"][sym])

    def test_valid_korea_japan_writes_schema(self) -> None:
        fetch = self._mock_fetch()
        out = probe.probe_korea_japan_indices(self.TARGET, fetch)
        self.assertEqual(out["as_of"], "2026-06-08")
        for sym in ("KOSPI", "KOSDAQ", "NIKKEI"):
            self.assertIn(sym, out["indices"])
            self.assertIsNotNone(out["indices"][sym]["close"])

    def test_valid_macro_schema(self) -> None:
        fetch = self._mock_fetch()
        us = probe.probe_overnight_us_market(self.TARGET, fetch)
        kj = probe.probe_korea_japan_indices(self.TARGET, fetch)
        macro = probe.build_macro_indicators(us, kj, self.TARGET)
        for key in ("as_of", "headline", "rates_watch", "dxy_note"):
            self.assertTrue(str(macro.get(key) or "").strip())

    def test_valid_news_schema(self) -> None:
        fetch = self._mock_fetch()
        news = probe.probe_top_market_news(self.TARGET, fetch)
        self.assertGreaterEqual(len(news), 4)
        for item in news:
            self.assertTrue(item["headline"])
            self.assertEqual(item["source"], "CNBC")
            self.assertEqual(item["date"], "2026-06-08")

    def test_stale_source_date_fails(self) -> None:
        with self.assertRaises(probe.FeedProbeError):
            probe._assert_as_of_fresh("2026-05-29", self.TARGET, "overnight_us_market")

    def test_missing_index_value_fails(self) -> None:
        html = '"priceCurrency":"USD"}</script>'
        with self.assertRaises(probe.FeedProbeError):
            probe.parse_cnbc_quote_html(html, "SPX")

    def test_source_fetch_failure_does_not_overwrite(self) -> None:
        fetch = mock.Mock(side_effect=probe.FeedProbeError("network down"))
        original = (probe.FEEDS_DIR / "overnight_us_market.json").read_text(encoding="utf-8")
        with self.assertRaises(probe.FeedProbeError):
            probe.probe_overnight_us_market(self.TARGET, fetch)
        current = (probe.FEEDS_DIR / "overnight_us_market.json").read_text(encoding="utf-8")
        self.assertEqual(original, current)

    def test_dry_run_does_not_write_files(self) -> None:
        before = (probe.FEEDS_DIR / "overnight_us_market.json").read_text(encoding="utf-8")
        with mock.patch.object(probe, "default_fetch_url", self._mock_fetch()):
            rc = probe.main(["--dry-run", "--strict", "--target-date", self.TARGET])
        self.assertEqual(rc, 0)
        after = (probe.FEEDS_DIR / "overnight_us_market.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_write_only_when_strict_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feed_dir = Path(tmp)
            for fname in probe.FEED_FILES.values():
                (feed_dir / fname).write_text("{}\n", encoding="utf-8")
            feeds = probe.probe_all_feeds(self.TARGET, self._mock_fetch())
            backup = probe.write_feed_files(feeds, feed_dir, backup=False)
            self.assertIsNone(backup)
            validation = probe.validate_today_genie_feed_files(self.TARGET, feed_dir)
            self.assertTrue(validation["ok"], validation.get("errors"))

    def test_validator_rejects_stale_may29_for_jun9(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feed_dir = Path(tmp)
            stale = {
                "as_of": "2026-05-29",
                "indices": {
                    "SPX": {"close": 1, "change_pct": 0},
                    "NASDAQ": {"close": 1, "change_pct": 0},
                    "DJI": {"close": 1, "change_pct": 0},
                },
            }
            (feed_dir / "overnight_us_market.json").write_text(json.dumps(stale), encoding="utf-8")
            (feed_dir / "macro_indicators.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-05-29",
                        "headline": "x",
                        "rates_watch": "x",
                        "dxy_note": "x",
                    }
                ),
                encoding="utf-8",
            )
            (feed_dir / "korea_japan_indices.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-05-29",
                        "indices": {
                            "KOSPI": {"close": 1, "change_pct": 0},
                            "KOSDAQ": {"close": 1, "change_pct": 0},
                            "NIKKEI": {"close": 1, "change_pct": 0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (feed_dir / "top_market_news.json").write_text(
                json.dumps([{"headline": "h", "source": "CNBC", "date": "2026-05-29"}]),
                encoding="utf-8",
            )
            (feed_dir / "risk_factors.json").write_text(
                json.dumps([{"risk": "r", "detail": "d"}]), encoding="utf-8"
            )
            result = probe.validate_today_genie_feed_files(self.TARGET, feed_dir)
            self.assertFalse(result["ok"])
            joined = " ".join(result["errors"])
            self.assertIn("2026-05-29", joined)

    def test_runtime_validator_stale_feed_date_for_may29(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from validators import _today_stale_date_issues  # noqa: WPS433

        runtime = {
            "target_date": self.TARGET,
            "overnight_us_market": {"as_of": "2026-05-29"},
            "korea_japan_indices": {"as_of": "2026-05-29"},
            "macro_indicators": {"as_of": "2026-05-29"},
        }
        issues = _today_stale_date_issues({}, runtime)
        codes = [i.code for i in issues]
        self.assertEqual(codes.count("stale_feed_date"), 3)

    def test_apply_script_untouched(self) -> None:
        apply_path = probe.OPS_ROOT / "apply_today_genie_feeds_env.py"
        text = apply_path.read_text(encoding="utf-8")
        self.assertIn("--update-env-vars", text)
        self.assertNotIn("--env-vars-file", text)

    def test_no_cloud_run_env_update_in_probe_script(self) -> None:
        text = (probe.OPS_ROOT / "probe_today_genie_feeds.py").read_text(encoding="utf-8")
        self.assertNotIn("gcloud run services update", text)
        self.assertNotIn("apply_today_genie_feeds_env", text)


if __name__ == "__main__":
    unittest.main()
