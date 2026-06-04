"""Tests for GENIE runtime weather binding design (offline, no live API)."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from genie_runtime_weather_binding import (
    ALLOWED_CONSUMERS,
    FORBIDDEN_CONSUMERS,
    SOURCE_MODES_FORBIDDEN,
    build_runtime_weather_binding_contract,
    build_runtime_weather_binding_report,
    build_runtime_weather_binding_report_from_canary_lock,
    build_weather_context_for_consumer,
    get_allowed_weather_consumers,
    load_weather_context_from_canary_lock,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_REPORT = _REPO / "output" / "keysuri_preview" / "weather_canary" / "runtime_weather_binding_report.json"


def _weather_context() -> dict:
    return load_weather_context_from_canary_lock(str(_LOCK_PATH))


class RuntimeWeatherBindingContractTests(unittest.TestCase):
    def test_allowed_consumers(self) -> None:
        self.assertEqual(
            get_allowed_weather_consumers(),
            [
                "today_geenee",
                "keysuri_global_tech",
                "keysuri_korea_tech",
            ],
        )
        self.assertEqual(tuple(get_allowed_weather_consumers()), ALLOWED_CONSUMERS)

    def test_contract_shape_and_guards(self) -> None:
        contract = build_runtime_weather_binding_contract()
        self.assertEqual(contract["binding_type"], "runtime_weather_context_binding_design")
        self.assertEqual(contract["runtime_binding_status"], "design_ready_not_wired")
        self.assertEqual(contract["allowed_consumers"], list(ALLOWED_CONSUMERS))
        for retired in ("tomorrow_geenee", "tomorrow_genie", "tomorrow"):
            self.assertIn(retired, contract["forbidden_consumers"])
        self.assertIn("tomorrow_geenee", FORBIDDEN_CONSUMERS)
        self.assertTrue(contract["ready_for_runtime_binding_plan"])
        self.assertFalse(contract["ready_for_scheduler"])
        self.assertFalse(contract["ready_for_production_auto_call"])
        side = contract["side_effects"]
        self.assertFalse(any(side.values()))
        self.assertIn("automatic_live_weather_api_call", contract["source_modes_forbidden"])
        self.assertIn("scheduler_invoked_weather_call", contract["source_modes_forbidden"])
        self.assertIn("production_auto_call", contract["source_modes_forbidden"])


class CanaryLockWeatherContextLoaderTests(unittest.TestCase):
    def test_loads_and_validates_fixture(self) -> None:
        ctx = _weather_context()
        self.assertEqual(ctx["source_mode"], "sanitized_canary_lock")
        self.assertEqual(ctx["provider"], "openweather")
        self.assertEqual(ctx["location"], "Seoul")
        self.assertEqual(ctx["timezone"], "Asia/Seoul")
        self.assertEqual(ctx["weather_condition"], "cloudy")
        self.assertEqual(ctx["weather_date"], "2026-06-04")
        self.assertEqual(ctx["observed_or_forecast_time_kst"], "17:37")
        self.assertEqual(ctx["source_label"], "OpenWeather live canary lock")
        self.assertEqual(ctx["canary_lock_status"], "pass")

    def test_fixture_excludes_secrets_and_retired(self) -> None:
        blob = json.dumps(_weather_context(), ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn('"raw_provider_payload":', blob)
        for bad in ("테크 앵커", "뉴스 앵커", "아나운서", "Tomorrow_Geenee", "tomorrow_genie"):
            self.assertNotIn(bad, blob)
        self.assertNotRegex(blob, r"\b18:00\b")

    def test_invalid_lock_blocks(self) -> None:
        lock = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
        bad = deepcopy(lock)
        bad["canary_status"] = "blocked"
        bad_path = _REPO / "output" / "keysuri_preview" / "weather_canary" / "_test_bad_lock.json"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                load_weather_context_from_canary_lock(str(bad_path))
        finally:
            if bad_path.is_file():
                bad_path.unlink()


class ConsumerBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _weather_context()

    def test_today_geenee_binding(self) -> None:
        binding = build_weather_context_for_consumer("today_geenee", self.ctx)
        self.assertEqual(binding["role"], "market_life_realism_layer")
        self.assertEqual(binding["emphasis"], "light")
        self.assertTrue(binding["must_not_become_weather_only"])
        cues = binding["weather_cues"]
        self.assertEqual(cues["location"], "Seoul")
        self.assertEqual(cues["weather_condition"], "cloudy")
        self.assertEqual(cues["observed_or_forecast_time_kst"], "17:37")
        self.assertIn("brief_life_context_hint", cues)
        hint_blob = json.dumps(cues).lower()
        self.assertNotIn("7-day forecast", hint_blob)
        self.assertNotIn("weather-only product", hint_blob)

    def test_keysuri_global_binding(self) -> None:
        binding = build_weather_context_for_consumer("keysuri_global_tech", self.ctx)
        self.assertEqual(binding["role"], "visual_realism_layer")
        self.assertEqual(binding["visual_time_context"], "seoul_daytime_1230")
        self.assertTrue(binding["must_not_change_persona"])
        self.assertIn("office_window_light", binding["visual_reflects"])
        positive_blob = json.dumps(
            {
                "role": binding["role"],
                "visual_reflects": binding["visual_reflects"],
                "weather_context_summary": binding["weather_context_summary"],
            }
        ).lower()
        self.assertNotIn("public news anchor", positive_blob)
        self.assertNotIn("broadcaster", positive_blob)

    def test_keysuri_korea_binding(self) -> None:
        binding = build_weather_context_for_consumer("keysuri_korea_tech", self.ctx)
        self.assertEqual(binding["role"], "visual_realism_layer")
        self.assertEqual(binding["visual_time_context"], "seoul_early_evening_1830")
        self.assertTrue(binding["must_not_change_persona"])
        self.assertIn("evening_window_tone", binding["visual_reflects"])

    def test_unknown_consumer_blocks(self) -> None:
        with self.assertRaises(ValueError):
            build_weather_context_for_consumer("unknown_consumer", self.ctx)

    def test_tomorrow_variants_block(self) -> None:
        for retired in ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            with self.subTest(consumer=retired):
                with self.assertRaises(ValueError):
                    build_weather_context_for_consumer(retired, self.ctx)


class BindingReportTests(unittest.TestCase):
    def test_pass_report_from_canary_lock(self) -> None:
        report = build_runtime_weather_binding_report_from_canary_lock(str(_LOCK_PATH))
        self.assertEqual(report["binding_status"], "pass")
        self.assertEqual(report["runtime_binding_status"], "design_ready_not_wired")
        self.assertEqual(report["weather_context_source"], "sanitized_canary_lock")
        self.assertFalse(report["forbidden_consumers_present"])
        self.assertFalse(report["ready_for_scheduler"])
        self.assertFalse(report["ready_for_production_auto_call"])
        self.assertFalse(any(report["side_effects"].values()))
        self.assertEqual(report["issues"], [])
        bindings = report["consumer_bindings"]
        self.assertEqual(set(bindings.keys()), set(ALLOWED_CONSUMERS))

    def test_forbidden_source_mode_blocks(self) -> None:
        ctx = _weather_context()
        for mode in SOURCE_MODES_FORBIDDEN:
            with self.subTest(mode=mode):
                bad = deepcopy(ctx)
                bad["source_mode"] = mode
                report = build_runtime_weather_binding_report(bad)
                self.assertEqual(report["binding_status"], "blocked")
                codes = {i["code"] for i in report["issues"]}
                self.assertIn("source_mode_forbidden", codes)

    def test_report_secret_guard(self) -> None:
        report = build_runtime_weather_binding_report_from_canary_lock(str(_LOCK_PATH))
        blob = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn("raw_provider_payload", blob)
        self.assertNotIn("Authorization:", blob)
        self.assertNotIn("Bearer ", blob)
        self.assertNotIn("WEATHER_API_KEY=", blob)


class RuntimeWeatherBindingScriptTests(unittest.TestCase):
    def test_build_script_runs(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/build_genie_runtime_weather_binding_report.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["binding_status"], "pass")
        self.assertEqual(out["runtime_binding_status"], "design_ready_not_wired")
        self.assertEqual(out["issue_count"], 0)
        self.assertTrue(_OUT_REPORT.is_file())
        report = json.loads(_OUT_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["binding_status"], "pass")


if __name__ == "__main__":
    unittest.main()
