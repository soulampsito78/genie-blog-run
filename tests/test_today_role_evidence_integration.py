from __future__ import annotations

import unittest
from datetime import datetime as dt
from io import BytesIO
from unittest.mock import patch

from main import build_runtime_input
from admin_store import can_approve_customer_send
from product_surface_contract import (
    PRODUCT_SURFACE_DIAGNOSTIC_KEY,
    prepare_final_customer_copy,
    product_surface_run_fields,
)
from prompts import build_full_prompt, build_top3_extraction_prompt
from temporal_context_diagnostic import build_role_evidence_from_source_headings


class TodayRoleEvidenceIntegrationTests(unittest.TestCase):
    class _FixedClock:
        @staticmethod
        def now(tz=None):
            return dt.fromisoformat("2026-10-14T08:00:00+09:00")

        @staticmethod
        def fromisoformat(value):
            return dt.fromisoformat(value)

    def test_official_role_fetch_extracts_only_expected_headings_and_is_date_bound(self):
        from temporal_context_diagnostic import fetch_current_role_evidence

        html = b"<html><h2>President Donald J. Trump</h2><h3>Vice President JD Vance</h3></html>"

        class Response(BytesIO):
            status = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def geturl(self):
                return "https://www.whitehouse.gov/administration/"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with patch("temporal_context_diagnostic.datetime", self._FixedClock), patch(
            "temporal_context_diagnostic.urlopen", return_value=Response(html)
        ) as get:
            evidence = fetch_current_role_evidence("2026-10-14")
        self.assertEqual(evidence["roles"], {"trump": "president", "vance": "vice_president"})
        self.assertEqual(evidence["as_of"], "2026-10-14")
        self.assertTrue(evidence["source_sha256"])
        get.assert_called_once()

    def test_official_role_fetch_fails_closed_for_expired_day(self):
        from temporal_context_diagnostic import fetch_current_role_evidence

        with patch("temporal_context_diagnostic.datetime", self._FixedClock), patch(
            "temporal_context_diagnostic.urlopen"
        ) as get:
            self.assertIsNone(fetch_current_role_evidence("2026-10-13"))
        get.assert_not_called()

    def test_server_caller_passes_dated_snapshot_to_both_prompts_and_final_qa(self):
        empty_feeds = {
            "overnight_us_market": {},
            "macro_indicators": {},
            "top_market_news": [],
            "risk_factors": [],
            "korea_japan_indices": {},
        }
        with (
            patch("main._load_today_genie_feed_bundle", return_value=empty_feeds),
            patch("main._refresh_today_genie_feeds_if_needed", side_effect=lambda feeds, *a, **k: feeds),
            patch("main._normalize_today_genie_market_feeds", side_effect=lambda feeds, _date: feeds),
            patch("main.fetch_seoul_weather_forecast", return_value={}),
            patch("main.build_image_weather_context_for_today", return_value={}),
            patch("main.fetch_current_role_evidence", side_effect=lambda day: build_role_evidence_from_source_headings(
                day, ["President Donald J. Trump", "Vice President JD Vance"],
                observed_at=f"{day}T06:30:00+09:00", source_sha256="a" * 64,
            )),
        ):
            runtime_input = build_runtime_input("today_genie", controlled_test_target_date="2026-10-14")

        evidence = runtime_input["current_role_evidence"]
        self.assertEqual(evidence["as_of"], runtime_input["target_date"])
        for prompt in (build_top3_extraction_prompt(runtime_input), build_full_prompt("today_genie", runtime_input)):
            self.assertIn('"contract_version": "today-current-role-evidence-v1"', prompt)
            self.assertIn("DATED_CURRENT_ROLE_EVIDENCE", prompt)

        prepared = prepare_final_customer_copy(
            "today_genie", {"summary": "현재 트럼프 전 대통령이라고 본문이 잘못 부릅니다."},
            source_input=runtime_input,
        )
        diagnostic = prepared[PRODUCT_SURFACE_DIAGNOSTIC_KEY]
        self.assertIn("customer_surface_current_office_role_mismatch", diagnostic["issue_codes"])
        self.assertEqual(diagnostic["temporal_context"]["role_evidence_as_of"], evidence["as_of"])
        self.assertEqual(diagnostic["temporal_context"]["fact_verdict"], "NOT_CERTIFIED")
        gate_meta = {
            "mode": "today_genie",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "validation_result": "pass",
            "artifact_status": "emailed",
            **product_surface_run_fields(prepared),
        }
        self.assertEqual(
            can_approve_customer_send(gate_meta, has_email_html=True),
            (False, "product_surface_remediation_needed"),
        )

    def test_expired_date_passes_no_evidence_to_generation(self):
        from temporal_context_diagnostic import ROLE_CONTEXT_UNKNOWN

        empty_feeds = {
            "overnight_us_market": {}, "macro_indicators": {}, "top_market_news": [],
            "risk_factors": [], "korea_japan_indices": {},
        }
        with (
            patch("main._load_today_genie_feed_bundle", return_value=empty_feeds),
            patch("main._refresh_today_genie_feeds_if_needed", side_effect=lambda feeds, *a, **k: feeds),
            patch("main._normalize_today_genie_market_feeds", side_effect=lambda feeds, _date: feeds),
            patch("main.fetch_seoul_weather_forecast", return_value={}),
            patch("main.build_image_weather_context_for_today", return_value={}),
            patch("main.fetch_current_role_evidence", return_value=None),
        ):
            runtime_input = build_runtime_input("today_genie", controlled_test_target_date="2026-10-15")

        self.assertIsNone(runtime_input["current_role_evidence"])
        prompt = build_full_prompt("today_genie", runtime_input)
        self.assertIn("DATED_CURRENT_ROLE_EVIDENCE_UNAVAILABLE", prompt)
        prepared = prepare_final_customer_copy(
            "today_genie", {"summary": "현재 트럼프 대통령입니다."}, source_input=runtime_input,
        )
        self.assertIn(ROLE_CONTEXT_UNKNOWN, prepared[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["issue_codes"])


if __name__ == "__main__":
    unittest.main()
