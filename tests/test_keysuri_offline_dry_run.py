"""Tests for Kee-Suri offline dry-run orchestrator."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from keysuri_generation_prompt import ACTIVE_SCHEDULER_RULES, IDENTITY_TITLE
from keysuri_generated_briefing import GENERATED_STATUS_REQUIRED
from genie_weather_runtime_adapter import (
    load_genie_runtime_weather_payload_fixture,
    normalize_genie_runtime_weather_payload,
)
from keysuri_visual_context import IDENTITY_LABEL
from keysuri_offline_dry_run import (
    RUNTIME_SIDE_EFFECTS,
    dry_run_report_for_json,
    load_json_file,
    load_text_file,
    run_keysuri_global_offline_dry_run,
    run_keysuri_korea_offline_dry_run,
    run_keysuri_offline_dry_run,
)
_REPO = Path(__file__).resolve().parent.parent
_FEEDS = _REPO / "ops" / "feeds"


def _load_pack(name: str) -> dict:
    return load_json_file(str(_FEEDS / name))


def _load_raw(name: str) -> str:
    return load_text_file(str(_FEEDS / name))


def _minimal_claim(claim_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "statement": f"Staged example statement for {claim_id}.",
        "claim_type": "general",
        "source_ids": ["s1"],
        "confidence_label": "reported",
        "category": "policy",
        "headline": f"Headline {claim_id}",
        "summary": f"Summary {claim_id}",
        "why_it_matters": "Staged why it matters.",
        "business_implication": "Staged business implication.",
    }


def _minimal_pack(program_id: str, claims: list[dict]) -> dict:
    return {
        "program_id": program_id,
        "generated_at": "2026-06-04T10:00:00+09:00",
        "notes": "Test pack",
        "sources": [
            {
                "source_id": "s1",
                "source_name": "Example",
                "source_url": "https://example.com/source/test",
                "source_tier": "T2_TIER1_WIRE",
                "fetched_at": "2026-06-04T10:00:00+09:00",
            }
        ],
        "claims": claims,
    }


def _assert_side_effects_false(result: dict) -> None:
    side = result.get("runtime_side_effects") or {}
    for key, expected in RUNTIME_SIDE_EFFECTS.items():
        with self.subTest(key=key):
            self.assertEqual(side.get(key), expected)


class KeysuriOfflineDryRunHappyPathTests(unittest.TestCase):
    def test_global_offline_dry_run_pass(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        self.assertEqual(result["dry_run_status"], "pass")
        self.assertEqual(result["program_id"], "keysuri_global_tech")
        self.assertEqual(result["source_gate_result"], "pass")
        self.assertEqual(result["prompt_status"], "ready_for_generation")
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertEqual(result["top_5_count"], 5)
        self.assertEqual(result["generated_status"], GENERATED_STATUS_REQUIRED)
        self.assertEqual(result["identity_label"], IDENTITY_TITLE)
        self._assert_side_effects(result)

    def test_korea_offline_dry_run_pass(self) -> None:
        result = run_keysuri_korea_offline_dry_run()
        self.assertEqual(result["dry_run_status"], "pass")
        self.assertEqual(result["program_id"], "keysuri_korea_tech")
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertEqual(result["top_5_count"], 5)
        self._assert_side_effects(result)

    def test_rendered_html_identity_and_generated_content(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        html = result.get("rendered_html") or ""
        self.assertIn("테크 비서 키수리", html)
        self.assertIn("키수리의 딥-다이브", html)
        self.assertIn("generated-section", html)
        self.assertNotIn("generation_pending", html)

    def _assert_side_effects(self, result: dict) -> None:
        side = result.get("runtime_side_effects") or {}
        for key, val in RUNTIME_SIDE_EFFECTS.items():
            self.assertIs(val, False, msg=key)
            self.assertEqual(side.get(key), False, msg=key)


class KeysuriOfflineDryRunFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = _load_pack("keysuri_global_sources.sample.json")
        self.valid_raw = _load_raw("keysuri_global_raw_response.valid.sample.txt")

    def _run_with_raw(self, raw_name: str) -> dict:
        return run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            self.pack,
            _load_raw(raw_name),
        )

    def test_invalid_json_parse_failed(self) -> None:
        result = self._run_with_raw("keysuri_raw_response.invalid_json.sample.txt")
        self.assertEqual(result["dry_run_status"], "parse_failed")
        self.assertIsNone(result["generated_status"])
        self._assert_side_effects_false(result)

    def test_multiple_json_parse_failed(self) -> None:
        result = self._run_with_raw("keysuri_raw_response.multiple_json.sample.txt")
        self.assertEqual(result["dry_run_status"], "parse_failed")
        self.assertIsNone(result["generated_status"])

    def test_array_top_level_parse_failed(self) -> None:
        result = self._run_with_raw("keysuri_raw_response.array_top_level.sample.txt")
        self.assertEqual(result["dry_run_status"], "parse_failed")

    def test_invalid_schema_parsed_invalid(self) -> None:
        result = self._run_with_raw("keysuri_raw_response.invalid_schema.sample.txt")
        self.assertEqual(result["dry_run_status"], "parsed_invalid")
        self.assertIsNone(result["generated_status"])
        html = result.get("rendered_html") or ""
        self.assertNotRegex(html, r'class="badge-generated"')
        self.assertIn("generation_pending", html)

    def _assert_side_effects_false(self, result: dict) -> None:
        side = result.get("runtime_side_effects") or {}
        self.assertFalse(side.get("called_gemini"))
        self.assertFalse(side.get("fetched_live_news"))


class KeysuriOfflineDryRunHoldBlockTests(unittest.TestCase):
    def test_hold_review_required(self) -> None:
        pack = _minimal_pack(
            "keysuri_global_tech",
            [_minimal_claim("c1"), _minimal_claim("c2")],
        )
        result = run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            pack,
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
        )
        self.assertEqual(result["dry_run_status"], "hold_review_required")
        self.assertEqual(result["prompt_status"], "hold_review_required")
        self.assertEqual(result["parse_status"], "skipped_hold")
        self.assertEqual(result["top_5_count"], 0)
        self.assertIsNone(result["generated_status"])
        html = result.get("rendered_html") or ""
        self.assertIn("generation_pending", html)

    def test_source_gate_block(self) -> None:
        pack = {"program_id": "keysuri_global_tech", "sources": [], "claims": []}
        result = run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            pack,
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
        )
        self.assertEqual(result["dry_run_status"], "block")
        self.assertEqual(result["source_gate_result"], "block")
        self.assertIsNone(result["rendered_html"])

    def test_unsupported_program_id_blocks(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = run_keysuri_offline_dry_run(
            "invalid_program",
            pack,
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
        )
        self.assertEqual(result["dry_run_status"], "block")


class KeysuriOfflineDryRunGuardTests(unittest.TestCase):
    def test_report_json_omits_full_html(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        report = dry_run_report_for_json(result)
        self.assertNotIn("rendered_html", report)
        self.assertGreater(report.get("rendered_html_length", 0), 0)

    def test_active_scheduler_no_tomorrow_geenee(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        summary = result.get("prompt_contract_summary") or {}
        active = summary.get("active_programs") or []
        programs = [row.get("program") for row in active if isinstance(row, dict)]
        self.assertIn("Today_Geenee", programs)
        self.assertIn("Kee-Suri Global Tech", programs)
        self.assertIn("Kee-Suri Korea Tech", programs)
        self.assertNotIn("Tomorrow_Geenee", programs)
        for row in ACTIVE_SCHEDULER_RULES:
            self.assertIn(row["program"], programs)

    def test_rendered_html_forbidden_identity_and_retired(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        html = result.get("rendered_html") or ""
        for bad in ("테크 앵커", "뉴스 앵커", "아나운서"):
            self.assertNotIn(bad, html)
        self.assertNotIn("Tomorrow_Geenee", html)
        self.assertNotIn("tomorrow_genie", html)
        self.assertNotRegex(html, r"18:00\s*KST")


class KeysuriOfflineDryRunWeatherVisualTests(unittest.TestCase):
    def test_without_weather_unchanged(self) -> None:
        result = run_keysuri_global_offline_dry_run()
        self.assertEqual(result["dry_run_status"], "pass")
        self.assertEqual(result["weather_context_status"], "not_supplied")
        self.assertEqual(result["visual_prompt_status"], "not_requested")

    def test_global_with_normalized_weather_builds_visual(self) -> None:
        payload = load_genie_runtime_weather_payload_fixture(
            str(_FEEDS / "genie_weather_runtime_seoul_cloudy.sample.json")
        )
        weather = normalize_genie_runtime_weather_payload(payload)
        result = run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            _load_pack("keysuri_global_sources.sample.json"),
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
            weather_context=weather,
        )
        self.assertEqual(result["dry_run_status"], "pass")
        self.assertEqual(result["weather_context_status"], "normalized")
        self.assertEqual(result["visual_prompt_status"], "built")
        vsum = result.get("visual_prompt_summary") or {}
        self.assertEqual(vsum.get("schedule_time_kst"), "12:30")
        self.assertEqual(vsum.get("visual_time_band"), "daytime")
        preview = result.get("image_prompt_text_preview") or ""
        self.assertIn(IDENTITY_LABEL, preview)

    def test_korea_rainy_evening_visual(self) -> None:
        payload = load_genie_runtime_weather_payload_fixture(
            str(_FEEDS / "genie_weather_runtime_seoul_rain.sample.json")
        )
        weather = normalize_genie_runtime_weather_payload(payload)
        result = run_keysuri_offline_dry_run(
            "keysuri_korea_tech",
            _load_pack("keysuri_korea_sources.sample.json"),
            _load_raw("keysuri_korea_raw_response.valid.sample.txt"),
            weather_context=weather,
        )
        self.assertEqual(result["dry_run_status"], "pass")
        self.assertEqual(result["visual_prompt_status"], "built")
        preview = (result.get("image_prompt_text_preview") or "").lower()
        self.assertEqual(result["visual_prompt_summary"]["schedule_time_kst"], "18:30")
        self.assertEqual(result["visual_prompt_summary"]["visual_time_band"], "early_evening")
        self.assertIn("rain", preview)
        self.assertIn("interior", preview)

    def test_korea_fine_dust_hazy_visual(self) -> None:
        payload = load_genie_runtime_weather_payload_fixture(
            str(_FEEDS / "genie_weather_runtime_seoul_fine_dust.sample.json")
        )
        weather = normalize_genie_runtime_weather_payload(payload)
        result = run_keysuri_offline_dry_run(
            "keysuri_korea_tech",
            _load_pack("keysuri_korea_sources.sample.json"),
            _load_raw("keysuri_korea_raw_response.valid.sample.txt"),
            weather_context=weather,
        )
        preview = (result.get("image_prompt_text_preview") or "").lower()
        self.assertIn("haz", preview)

    def test_invalid_weather_context_blocks(self) -> None:
        bad_weather = {
            "location": "Busan",
            "timezone": "Asia/Seoul",
            "weather_date": "2026-06-04",
            "observed_or_forecast_time_kst": "12:00",
            "weather_condition": "sunny",
            "source_mode": "offline_fixture",
            "source_label": "bad",
        }
        result = run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            _load_pack("keysuri_global_sources.sample.json"),
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
            weather_context=bad_weather,
        )
        self.assertEqual(result["dry_run_status"], "block")
        self.assertEqual(result["weather_context_status"], "invalid")
        self.assertEqual(result["visual_prompt_status"], "invalid")

    def test_weather_report_json_omits_full_image_prompt_object(self) -> None:
        payload = load_genie_runtime_weather_payload_fixture(
            str(_FEEDS / "genie_weather_runtime_seoul_cloudy.sample.json")
        )
        weather = normalize_genie_runtime_weather_payload(payload)
        result = run_keysuri_offline_dry_run(
            "keysuri_global_tech",
            _load_pack("keysuri_global_sources.sample.json"),
            _load_raw("keysuri_global_raw_response.valid.sample.txt"),
            weather_context=weather,
        )
        report = dry_run_report_for_json(result)
        self.assertNotIn("image_prompt_object", report)
        self.assertTrue(report.get("image_prompt_object_included"))


class KeysuriOfflineDryRunLoaderTests(unittest.TestCase):
    def test_load_json_and_text(self) -> None:
        pack = load_json_file(str(_FEEDS / "keysuri_global_sources.sample.json"))
        self.assertEqual(pack["program_id"], "keysuri_global_tech")
        raw = load_text_file(str(_FEEDS / "keysuri_global_raw_response.valid.sample.txt"))
        self.assertIn("keysuri_global_tech", raw)


if __name__ == "__main__":
    unittest.main()
