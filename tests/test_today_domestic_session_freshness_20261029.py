"""Offline regressions for domestic-session freshness and monotonic settled-store repair.

Covers:
1. Fresh domestic date with aggregate (10/28 on 10/29)
2. Stale domestic (10/27) + fresh Japan (10/28) aggregate (cannot mask domestic row)
3. Missing latest completed session fails closed
4. Weekend / holiday / May 1 / year-end / calendar coverage boundary handling
5. History repair cannot restore with wrong older session (10/27)
6. Newer history usable when exact prior session (10/28)
7. Durable settled store monotonicity & GCS generation CAS:
   - Confirmed absent generation 0 new write
   - Malformed/unknown generation no upload
   - Stale write cannot overwrite newer capture
   - Same-date correction preserved with valid CAS
   - Competing write between read and upload (CAS mismatch leaves newer record unchanged)
   - Download generation pin
   - Nonfatal error boundary never raises into caller
8. End-to-end no-paid-model assertion through _generate_impl with call_gemini mocked:
   - Fresh domestic control passes runtime feed gate
   - Stale domestic + fresh Japan aggregate blocks before model invocation with 422
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

from fastapi import HTTPException

from main import (
    JobRequest,
    _generate_impl,
    _today_feed_payload_freshness,
    build_runtime_input,
)
from market_observation import (
    DOMESTIC_KRX_INSTRUMENTS,
    SETTLED,
    UNSETTLED_SESSION,
    is_krx_trading_day,
    krx_year_end_closure,
    latest_completed_krx_session,
    normalize_index_feed,
    normalize_market_observation,
    repair_feed_from_history,
)
from market_observation_store import (
    STORE_SCHEMA_VERSION,
    read_settled_observation,
    write_settled_observation,
)
from ops.probe_today_genie_feeds import (
    FeedProbeError,
    probe_korea_japan_indices,
    select_settled_naver_domestic_row,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "today_domestic_session_20261029"


class FakeBlob:
    def __init__(
        self,
        key: str,
        *,
        exists: bool = False,
        generation: int = 0,
        text: str = "",
        conflict_on_upload: bool = False,
        error_on_download: bool = False,
    ) -> None:
        self.key = key
        self._exists = exists
        self.generation = generation
        self._text = text
        self.conflict_on_upload = conflict_on_upload
        self.error_on_download = error_on_download
        self.download_generation_pin: Optional[int] = None
        self.uploaded_text: Optional[str] = None
        self.uploaded_kwargs: Optional[Dict[str, Any]] = None

    def exists(self) -> bool:
        return self._exists

    def reload(self) -> None:
        pass

    def download_as_text(self, *, encoding: str = "utf-8", if_generation_match: Optional[int] = None) -> str:
        self.download_generation_pin = if_generation_match
        if self.error_on_download:
            raise RuntimeError("simulated download error")
        if if_generation_match is not None and if_generation_match != self.generation:
            exc = RuntimeError("PreconditionFailed: generation mismatch on download")
            setattr(exc, "code", 412)
            raise exc
        return self._text

    def upload_from_string(self, text: str, **kwargs: Any) -> None:
        if self.conflict_on_upload:
            exc = RuntimeError("PreconditionFailed")
            setattr(exc, "code", 412)
            raise exc
        expected_gen = kwargs.get("if_generation_match")
        if expected_gen is not None and expected_gen != self.generation:
            exc = RuntimeError("PreconditionFailed: upload CAS conflict")
            setattr(exc, "code", 412)
            raise exc
        self.uploaded_text = text
        self.uploaded_kwargs = kwargs
        self._exists = True
        self.generation += 1
        self._text = text


class FakeBucket:
    def __init__(self, blobs: Optional[Dict[str, FakeBlob]] = None) -> None:
        self.blobs: Dict[str, FakeBlob] = blobs or {}

    def blob(self, key: str) -> FakeBlob:
        if key not in self.blobs:
            self.blobs[key] = FakeBlob(key, exists=False, generation=0)
        return self.blobs[key]


def _build_valid_feed_bundle(domestic_date: str, japan_date: str = "2026-10-28") -> Dict[str, Any]:
    """Complete, valid feed bundle with configurable domestic vs foreign market dates."""
    as_of = max(domestic_date, japan_date)
    return {
        "overnight_us_market": {
            "as_of": "2026-10-28",
            "indices": {
                "SPX": {"close": 7400.0, "change_pct": 0.3, "as_of": "2026-10-28"},
                "NASDAQ": {"close": 25000.0, "change_pct": 0.8, "as_of": "2026-10-28"},
                "DJI": {"close": 50000.0, "change_pct": -0.1, "as_of": "2026-10-28"},
            },
        },
        "macro_indicators": {
            "as_of": as_of,
            "headline": "Macro snapshot headline",
            "rates_watch": "Rates watch",
            "dxy_note": "DXY note",
        },
        "korea_japan_indices": {
            "as_of": as_of,
            "indices": {
                "KOSPI": {
                    "close": 6012.44 if domestic_date == "2026-10-28" else 5638.34,
                    "change_pct": 6.63 if domestic_date == "2026-10-28" else 3.09,
                    "change_pts": 374.10 if domestic_date == "2026-10-28" else 168.87,
                    "previous_close": 5638.34 if domestic_date == "2026-10-28" else 5469.47,
                    "market_date": domestic_date,
                    "as_of": domestic_date,
                    "session_state": "closed",
                    "settlement_evidence": f"naver_domestic_daily_close_api:{domestic_date}",
                },
                "KOSDAQ": {
                    "close": 771.28 if domestic_date == "2026-10-28" else 743.83,
                    "change_pct": 3.69 if domestic_date == "2026-10-28" else 2.29,
                    "change_pts": 27.45 if domestic_date == "2026-10-28" else 16.62,
                    "previous_close": 743.83 if domestic_date == "2026-10-28" else 727.21,
                    "market_date": domestic_date,
                    "as_of": domestic_date,
                    "session_state": "closed",
                    "settlement_evidence": f"naver_domestic_daily_close_api:{domestic_date}",
                },
                "NIKKEI": {
                    "close": 38000.0,
                    "change_pct": 0.53,
                    "change_pts": 200.0,
                    "previous_close": 37800.0,
                    "market_date": japan_date,
                    "as_of": japan_date,
                    "session_state": "closed",
                    "settlement_evidence": f"naver_world_daily_close_api:{japan_date}",
                },
            },
        },
        "top_market_news": [
            {"headline": "Market headline 1", "source": "CNBC", "date": "2026-10-28"},
            {"headline": "Market headline 2", "source": "CNBC", "date": "2026-10-28"},
            {"headline": "Market headline 3", "source": "CNBC", "date": "2026-10-28"},
            {"headline": "Market headline 4", "source": "CNBC", "date": "2026-10-28"},
        ],
        "risk_factors": [{"risk": "Macro", "detail": "Risk detail"}],
        "feed_json_decode_failed_envs": [],
    }


class TodayDomesticSessionFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kospi_fixture_raw = (FIXTURE_DIR / "KOSPI.json").read_text(encoding="utf-8")
        self.kosdaq_fixture_raw = (FIXTURE_DIR / "KOSDAQ.json").read_text(encoding="utf-8")

    # -------------------------------------------------------------------------
    # 1. Calendar coverage, weekend, holiday, May 1, year-end rules
    # -------------------------------------------------------------------------
    def test_krx_calendar_trading_day_and_closures(self) -> None:
        # Ordinary trading days
        self.assertTrue(is_krx_trading_day("2026-10-28"))  # Wednesday
        self.assertTrue(is_krx_trading_day("2026-10-29"))  # Thursday

        # Weekend
        self.assertFalse(is_krx_trading_day("2026-10-24"))  # Saturday
        self.assertFalse(is_krx_trading_day("2026-10-25"))  # Sunday

        # Statutory public holidays
        self.assertFalse(is_krx_trading_day("2026-05-05"))  # Children's day
        self.assertFalse(is_krx_trading_day("2026-09-24"))  # Chuseok eve
        self.assertFalse(is_krx_trading_day("2026-09-25"))  # Chuseok

        # Labor Day (May 1) is closed
        self.assertFalse(is_krx_trading_day("2026-05-01"))

        # Year-end closure
        # 2026-12-31 is Thursday -> year-end closure day
        self.assertEqual(krx_year_end_closure(2026), date(2026, 12, 31))
        self.assertFalse(is_krx_trading_day("2026-12-31"))
        self.assertTrue(is_krx_trading_day("2026-12-30"))  # Wednesday is trading day

        # 2028-12-31 is Sunday; 2028-12-30 is Sat -> Friday 2028-12-29 is year-end closure
        self.assertEqual(krx_year_end_closure(2028), date(2028, 12, 29))
        self.assertFalse(is_krx_trading_day("2028-12-29"))
        self.assertTrue(is_krx_trading_day("2028-12-28"))

    def test_latest_completed_krx_session_lookbacks(self) -> None:
        # Verified production date 2026-10-29 -> 2026-10-28
        self.assertEqual(latest_completed_krx_session("2026-10-29"), date(2026, 10, 28))

        # Monday target 2026-10-26 -> Friday 2026-10-23
        self.assertEqual(latest_completed_krx_session("2026-10-26"), date(2026, 10, 23))

        # Day after May 1 (Monday 2026-05-04) -> Thursday 2026-04-30
        self.assertEqual(latest_completed_krx_session("2026-05-04"), date(2026, 4, 30))

        # Day after holiday 2026-05-06 (Wed) -> Monday 2026-05-04 (May 5 Children's Day)
        self.assertEqual(latest_completed_krx_session("2026-05-06"), date(2026, 5, 4))

        # Day after New Year 2027-01-04 (Mon) -> 2026-12-30 (Dec 31 is closure, Jan 1 is holiday)
        self.assertEqual(latest_completed_krx_session("2027-01-04"), date(2026, 12, 30))

    def test_calendar_coverage_boundaries_fail_closed(self) -> None:
        # Target year outside coverage (> 2030) must return None immediately
        self.assertIsNone(latest_completed_krx_session("2031-01-01"))
        self.assertIsNone(latest_completed_krx_session("2031-06-15"))

        # Target year outside coverage (< 2025) must return None
        self.assertIsNone(latest_completed_krx_session("2024-12-31"))

        # Cross-year lookup crossing before COVERAGE_START_YEAR (2025-01-02 lookback to 2024)
        # 2025-01-01 is holiday; prior trading day would be in 2024 which is outside coverage
        self.assertIsNone(latest_completed_krx_session("2025-01-02"))

        # Invalid target date
        self.assertIsNone(latest_completed_krx_session("not-a-date"))
        self.assertIsNone(latest_completed_krx_session(""))

    # -------------------------------------------------------------------------
    # 2. Probe & domestic row selection: fresh vs stale vs missing
    # -------------------------------------------------------------------------
    def test_select_settled_naver_domestic_row_with_fresh_fixture(self) -> None:
        # Target 2026-10-29 correctly selects 2026-10-28 row from real public fixture
        row = select_settled_naver_domestic_row(
            self.kospi_fixture_raw,
            "KOSPI",
            target_date="2026-10-29",
        )
        self.assertEqual(row["market_date"], "2026-10-28")
        self.assertEqual(row["close"], 6012.44)
        self.assertEqual(row["change_pct"], 6.63)
        self.assertEqual(row["change_pts"], 374.10)
        self.assertEqual(row["previous_close"], 5638.34)

        kd_row = select_settled_naver_domestic_row(
            self.kosdaq_fixture_raw,
            "KOSDAQ",
            target_date="2026-10-29",
        )
        self.assertEqual(kd_row["market_date"], "2026-10-28")
        self.assertEqual(kd_row["close"], 771.28)
        self.assertEqual(kd_row["change_pct"], 3.69)

    def test_select_settled_naver_domestic_row_rejects_stale_prior_session(self) -> None:
        # Synthetic payload where latest completed row is 2026-10-27 (missing 10/28)
        stale_payload = json.dumps([
            {
                "localTradedAt": "2026-10-27",
                "closePrice": "5,638.34",
                "compareToPreviousClosePrice": "168.87",
                "compareToPreviousPrice": {"name": "RISING"},
                "fluctuationsRatio": "3.09",
            },
            {
                "localTradedAt": "2026-10-26",
                "closePrice": "5,469.47",
                "compareToPreviousClosePrice": "-80.83",
                "compareToPreviousPrice": {"name": "FALLING"},
                "fluctuationsRatio": "-1.46",
            },
        ])
        with self.assertRaises(FeedProbeError) as ctx:
            select_settled_naver_domestic_row(
                stale_payload,
                "KOSPI",
                target_date="2026-10-29",
            )
        self.assertIn("does not match latest completed KRX session 2026-10-28", str(ctx.exception))

    def test_probe_korea_japan_indices_rejects_stale_domestic_row(self) -> None:
        # If domestic row is stale (10/27) while target is 10/29, probe fails closed
        stale_kospi = json.dumps([
            {
                "localTradedAt": "2026-10-27",
                "closePrice": "5,638.34",
                "compareToPreviousClosePrice": "168.87",
                "compareToPreviousPrice": {"name": "RISING"},
                "fluctuationsRatio": "3.09",
            },
            {
                "localTradedAt": "2026-10-26",
                "closePrice": "5,469.47",
                "compareToPreviousClosePrice": "-80.83",
                "compareToPreviousPrice": {"name": "FALLING"},
                "fluctuationsRatio": "-1.46",
            },
        ])

        def _fetch(url: str, timeout_sec: int = 20) -> str:
            if "KOSPI" in url:
                return stale_kospi
            if "KOSDAQ" in url:
                return self.kosdaq_fixture_raw
            if ".N225" in url:
                return json.dumps([
                    {
                        "localTradedAt": "2026-10-28T15:00:00+09:00",
                        "closePrice": "38,000.00",
                        "compareToPreviousClosePrice": "200.00",
                        "compareToPreviousPrice": {"name": "RISING"},
                    },
                    {
                        "localTradedAt": "2026-10-27T15:00:00+09:00",
                        "closePrice": "37,800.00",
                        "compareToPreviousClosePrice": "100.00",
                        "compareToPreviousPrice": {"name": "RISING"},
                    },
                ])
            raise RuntimeError(f"unexpected url {url}")

        out = probe_korea_japan_indices("2026-10-29", fetch_fn=_fetch)
        self.assertNotIn("KOSPI", out["indices"])
        self.assertIn("does not match latest completed KRX session", str(out["errors"].get("KOSPI")))

    # -------------------------------------------------------------------------
    # 3. Feed freshness: Fresh vs Stale Domestic + Fresh Japan Aggregate
    # -------------------------------------------------------------------------
    def test_fresh_domestic_date_with_aggregate_passes(self) -> None:
        payload = {
            "as_of": "2026-10-28",
            "indices": {
                "KOSPI": {"close": 6012.44, "change_pct": 6.63, "market_date": "2026-10-28"},
                "KOSDAQ": {"close": 771.28, "change_pct": 3.69, "market_date": "2026-10-28"},
                "NIKKEI": {"close": 38000.0, "change_pct": 0.53, "market_date": "2026-10-28"},
            },
        }
        info = _today_feed_payload_freshness("korea_japan_indices", payload, "2026-10-29")
        self.assertTrue(info["fresh"])
        self.assertFalse(info["stale"])

    def test_stale_domestic_with_fresh_japan_aggregate_fails_freshness(self) -> None:
        # Incident reproduction: domestic has 10/27, Nikkei has 10/28, feed as_of is 10/28
        payload = {
            "as_of": "2026-10-28",
            "indices": {
                "KOSPI": {"close": 5638.34, "change_pct": 3.09, "market_date": "2026-10-27"},
                "KOSDAQ": {"close": 743.83, "change_pct": 2.29, "market_date": "2026-10-27"},
                "NIKKEI": {"close": 38000.0, "change_pct": 0.53, "market_date": "2026-10-28"},
            },
        }
        info = _today_feed_payload_freshness("korea_japan_indices", payload, "2026-10-29")
        self.assertFalse(info["fresh"])
        self.assertTrue(info["stale"])
        self.assertIn("kosdaq_session_stale", info["reason"])
        self.assertIn("expected=2026-10-28", info["reason"])

    # -------------------------------------------------------------------------
    # 4. Normalization and history repair boundaries
    # -------------------------------------------------------------------------
    def test_normalize_market_observation_rejects_older_domestic_session(self) -> None:
        # Target is 2026-10-29, KOSPI row is 2026-10-27
        slot = {
            "close": 5638.34,
            "change_pct": 3.09,
            "market_date": "2026-10-27",
            "session_state": "closed",
        }
        obs = normalize_market_observation(
            "KOSPI",
            slot,
            target_date="2026-10-29",
            feed_as_of="2026-10-28",
        )
        self.assertEqual(obs["observation_status"], UNSETTLED_SESSION)
        self.assertIn("does not match latest completed KRX session 2026-10-28", obs["observation_reason"])

    def test_normalize_market_observation_domestic_never_inherits_foreign_as_of(self) -> None:
        slot = {
            "close": 5638.34,
            "change_pct": 3.09,
            "session_state": "closed",
        }
        obs = normalize_market_observation(
            "KOSPI",
            slot,
            target_date="2026-10-29",
            feed_as_of="2026-10-28",
        )
        self.assertNotEqual(obs["observation_status"], SETTLED)
        self.assertEqual(obs["observation_reason"], "domestic_market_date_missing")

    def test_history_cannot_repair_with_wrong_older_session(self) -> None:
        unsettled_feed = {
            "as_of": "2026-10-29",
            "indices": {
                "KOSPI": {"close": 5638.34, "change_pct": 3.09, "market_date": "2026-10-27"},
            },
        }
        feed, report = normalize_index_feed(unsettled_feed, target_date="2026-10-29")
        self.assertTrue(report["unpublishable"])

        # History only holds older 2026-10-27 session
        history = {
            "KOSPI": {
                "observation_status": SETTLED,
                "market_date": "2026-10-27",
                "close": 5638.34,
                "previous_close": 5469.47,
                "point_change": 168.87,
                "pct_change": 3.09,
            }
        }
        repaired_feed, repaired_report = repair_feed_from_history(
            feed,
            report,
            target_date="2026-10-29",
            history=history,
        )
        # 10/27 cannot repair target 10/29 when expected KRX session is 10/28
        self.assertTrue(repaired_report["unpublishable"])
        self.assertNotIn("change_pct", repaired_feed["indices"]["KOSPI"])

    def test_newer_history_usable_when_exact_prior_session(self) -> None:
        unsettled_feed = {
            "as_of": "2026-10-29",
            "indices": {
                "KOSPI": {"close": 5638.34, "change_pct": 3.09, "market_date": "2026-10-27"},
            },
        }
        feed, report = normalize_index_feed(unsettled_feed, target_date="2026-10-29")
        self.assertTrue(report["unpublishable"])

        # History holds exact completed prior session 2026-10-28
        history = {
            "KOSPI": {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "previous_close": 5638.34,
                "point_change": 374.10,
                "pct_change": 6.63,
            }
        }
        repaired_feed, repaired_report = repair_feed_from_history(
            feed,
            report,
            target_date="2026-10-29",
            history=history,
        )
        self.assertEqual(repaired_report["unpublishable"], [])
        row = repaired_feed["indices"]["KOSPI"]
        self.assertEqual(row["observation_status"], SETTLED)
        self.assertEqual(row["market_date"], "2026-10-28")
        self.assertEqual(row["close"], 6012.44)
        self.assertEqual(row["change_pct"], 6.63)

    # -------------------------------------------------------------------------
    # 5. Settled observation store: Monotonicity & GCS CAS serialization
    # -------------------------------------------------------------------------
    def test_confirmed_absent_generation_0_new_write(self) -> None:
        blob = FakeBlob("runtime_feed_cache/today_genie/settled_index/KOSPI.json", exists=False, generation=0)
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            new_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation("today_genie", "KOSPI", new_obs, captured_at="2026-10-28T16:00:00Z")
            self.assertEqual(res, "written")
            self.assertEqual(blob.uploaded_kwargs.get("if_generation_match"), 0)
            self.assertEqual(blob.generation, 1)

    def test_malformed_generation_fails_closed_without_upload(self) -> None:
        blob = FakeBlob("runtime_feed_cache/today_genie/settled_index/KOSPI.json", exists=True, generation=0)
        setattr(blob, "generation", -1)  # Invalid non-positive generation for existing object
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            new_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation("today_genie", "KOSPI", new_obs, captured_at="2026-10-28T16:00:00Z")
            self.assertEqual(res, "skipped_unverified_existing_generation")
            self.assertIsNone(blob.uploaded_text)

    def test_stale_write_cannot_overwrite_newer_capture(self) -> None:
        # Pre-populate store with newer 2026-10-28 observation (generation 5)
        existing_record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": "today_genie",
            "instrument": "KOSPI",
            "captured_at": "2026-10-28T16:00:00Z",
            "observation": {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            },
        }
        blob = FakeBlob(
            "runtime_feed_cache/today_genie/settled_index/KOSPI.json",
            exists=True,
            generation=5,
            text=json.dumps(existing_record),
        )
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            # Attempt to overwrite with older 2026-10-27 observation
            stale_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-27",
                "close": 5638.34,
                "pct_change": 3.09,
            }
            res = write_settled_observation(
                "today_genie",
                "KOSPI",
                stale_obs,
                captured_at="2026-10-29T08:00:00Z",
            )
            self.assertEqual(res, "skipped_older_market_date")
            # Blob must NOT have been updated
            self.assertIsNone(blob.uploaded_text)
            self.assertEqual(blob.generation, 5)

            # Read back still yields 2026-10-28 and verified download pin
            stored = read_settled_observation("today_genie", "KOSPI")
            self.assertIsNotNone(stored)
            self.assertEqual(stored["market_date"], "2026-10-28")
            self.assertEqual(blob.download_generation_pin, 5)

    def test_same_date_correction_preserved_with_valid_cas(self) -> None:
        existing_record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": "today_genie",
            "instrument": "KOSPI",
            "captured_at": "2026-10-28T16:00:00Z",
            "observation": {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.60,
            },
        }
        blob = FakeBlob(
            "runtime_feed_cache/today_genie/settled_index/KOSPI.json",
            exists=True,
            generation=3,
            text=json.dumps(existing_record),
        )
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            corrected_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation(
                "today_genie",
                "KOSPI",
                corrected_obs,
                captured_at="2026-10-28T16:05:00Z",
            )
            self.assertEqual(res, "written")
            self.assertIsNotNone(blob.uploaded_text)
            self.assertEqual(blob.uploaded_kwargs.get("if_generation_match"), 3)
            self.assertEqual(blob.generation, 4)

    def test_simulated_competing_write_between_read_and_upload(self) -> None:
        existing_record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": "today_genie",
            "instrument": "KOSPI",
            "captured_at": "2026-10-28T16:00:00Z",
            "observation": {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            },
        }
        blob = FakeBlob(
            "runtime_feed_cache/today_genie/settled_index/KOSPI.json",
            exists=True,
            generation=3,
            text=json.dumps(existing_record),
        )
        bucket = FakeBucket({blob.key: blob})

        # Competing writer intercepts between read and upload, advancing generation to 4 with newer record
        orig_upload = blob.upload_from_string

        def _competing_interception(payload: str, **kwargs: Any) -> None:
            newer_record = {
                "schema_version": STORE_SCHEMA_VERSION,
                "program": "today_genie",
                "instrument": "KOSPI",
                "captured_at": "2026-10-28T16:02:00Z",
                "observation": {
                    "observation_status": SETTLED,
                    "market_date": "2026-10-28",
                    "close": 6012.44,
                    "pct_change": 6.63,
                    "competing_revision": True,
                },
            }
            blob._text = json.dumps(newer_record)
            blob.generation = 4
            orig_upload(payload, **kwargs)

        blob.upload_from_string = _competing_interception

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation("today_genie", "KOSPI", obs, captured_at="2026-10-28T16:05:00Z")
            self.assertEqual(res, "conflict")
            # The newer record placed by the competing write was preserved, not overwritten
            self.assertIn('"competing_revision": true', blob._text)
            self.assertEqual(blob.generation, 4)

    def test_malformed_existing_observation_skips_without_upload(self) -> None:
        bad_record = {
            "schema_version": STORE_SCHEMA_VERSION,
            "program": "today_genie",
            "instrument": "KOSPI",
            "observation": {
                "observation_status": SETTLED,
                "market_date": "corrupted-date",
            },
        }
        blob = FakeBlob(
            "runtime_feed_cache/today_genie/settled_index/KOSPI.json",
            exists=True,
            generation=2,
            text=json.dumps(bad_record),
        )
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            new_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation(
                "today_genie",
                "KOSPI",
                new_obs,
                captured_at="2026-10-28T16:00:00Z",
            )
            self.assertEqual(res, "skipped_unverified_existing_observation")
            self.assertIsNone(blob.uploaded_text)

    def test_backend_read_failure_fails_closed_without_raise_or_upload(self) -> None:
        blob = FakeBlob(
            "runtime_feed_cache/today_genie/settled_index/KOSPI.json",
            exists=True,
            generation=2,
            text="",
            error_on_download=True,
        )
        bucket = FakeBucket({blob.key: blob})

        with (
            mock.patch("admin_store.admin_artifact_bucket_name", return_value="fake-bucket"),
            mock.patch("admin_store._get_gcs_bucket", return_value=bucket),
        ):
            new_obs = {
                "observation_status": SETTLED,
                "market_date": "2026-10-28",
                "close": 6012.44,
                "pct_change": 6.63,
            }
            res = write_settled_observation(
                "today_genie",
                "KOSPI",
                new_obs,
                captured_at="2026-10-28T16:00:00Z",
            )
            self.assertEqual(res, "skipped_unverified_existing_generation")
            self.assertIsNone(blob.uploaded_text)

    # -------------------------------------------------------------------------
    # 6. End-to-end generation boundary: Model call denied on stale domestic feed
    # -------------------------------------------------------------------------
    def test_end_to_end_fresh_control_passes_runtime_feed_gate(self) -> None:
        fresh_bundle = _build_valid_feed_bundle("2026-10-28", "2026-10-28")

        with (
            mock.patch("main._load_today_genie_feed_bundle", return_value=fresh_bundle),
            mock.patch("main._probe_today_genie_live_feeds", side_effect=RuntimeError("offline")),
            mock.patch("main.fetch_seoul_weather_forecast", return_value={}),
            mock.patch("main.fetch_current_role_evidence", return_value=None),
            mock.patch("market_observation_store.read_settled_observation", return_value=None),
            mock.patch("market_observation_store.write_settled_observation", return_value="written"),
        ):
            runtime_input = build_runtime_input("today_genie", controlled_test_target_date="2026-10-29")
            self.assertEqual(runtime_input.get("today_genie_feed_gate"), "ok")
            self.assertTrue(runtime_input.get("today_required_feed_contract_passed"))

    def test_end_to_end_no_paid_model_on_stale_domestic_with_fresh_japan_aggregate(self) -> None:
        # Build bundle with stale domestic (10/27) and fresh Japan (10/28)
        stale_bundle = _build_valid_feed_bundle("2026-10-27", "2026-10-28")

        with (
            mock.patch("main._load_today_genie_feed_bundle", return_value=stale_bundle),
            mock.patch("main._probe_today_genie_live_feeds", side_effect=RuntimeError("offline")),
            mock.patch("main.fetch_seoul_weather_forecast", return_value={}),
            mock.patch("main.fetch_current_role_evidence", return_value=None),
            mock.patch("market_observation_store.read_settled_observation", return_value=None),
            mock.patch("market_observation_store.write_settled_observation", return_value="written"),
            mock.patch("main.call_gemini") as mock_gemini,
            mock.patch("main.run_today_genie_text_pipeline") as mock_pipeline,
            mock.patch("main.record_memory_stage"),
        ):
            job = JobRequest(
                type="today_genie",
                controlled_test_mode=True,
                controlled_test_target_date="2026-10-29",
            )
            with self.assertRaises(HTTPException) as ctx:
                _generate_impl(job)

            self.assertEqual(ctx.exception.status_code, 422)
            detail = ctx.exception.detail
            self.assertIsInstance(detail, dict)
            # Domestic staleness blocked the feed contract before any model call
            validation_check = detail.get("runtime_validation_check", {})
            stale_list = validation_check.get("today_required_feed_contract_stale", [])
            self.assertIn("korea_japan_indices", stale_list)

            # Crucial verification: paid model & text pipeline were NEVER invoked!
            mock_gemini.assert_not_called()
            mock_pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
