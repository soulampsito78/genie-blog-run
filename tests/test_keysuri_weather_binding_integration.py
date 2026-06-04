"""Tests for Kee-Suri weather binding → visual context integration dry-run."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from genie_runtime_weather_binding import load_weather_context_from_canary_lock
from keysuri_visual_context import (
    FORBIDDEN_SOURCE_MODES,
    validate_keysuri_weather_context,
)
from keysuri_weather_binding_integration import (
    INTEGRATION_TYPE,
    KEYSURI_PROGRAMS,
    build_keysuri_visual_contexts_from_canary_lock,
    build_keysuri_weather_binding_integration_report,
    validate_keysuri_weather_binding_integration_result,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_REPORT = (
    _REPO
    / "output"
    / "keysuri_preview"
    / "weather_canary"
    / "keysuri_weather_binding_integration_report.json"
)


def _weather_context() -> dict:
    return load_weather_context_from_canary_lock(str(_LOCK_PATH))


def _integration_report() -> dict:
    return build_keysuri_weather_binding_integration_report(str(_LOCK_PATH))


class KeysuriSourceModeIntegrationTests(unittest.TestCase):
    def test_sanitized_canary_lock_accepted(self) -> None:
        ctx = _weather_context()
        self.assertEqual(ctx["source_mode"], "sanitized_canary_lock")
        self.assertEqual(validate_keysuri_weather_context(ctx), [])

    def test_forbidden_source_modes_rejected(self) -> None:
        ctx = _weather_context()
        for mode in FORBIDDEN_SOURCE_MODES:
            with self.subTest(mode=mode):
                bad = deepcopy(ctx)
                bad["source_mode"] = mode
                codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
                self.assertIn("source_mode_forbidden", codes)


class KeysuriWeatherBindingIntegrationTests(unittest.TestCase):
    def test_from_canary_lock_builds_two_programs(self) -> None:
        contexts = build_keysuri_visual_contexts_from_canary_lock(str(_LOCK_PATH))
        self.assertEqual(set(contexts.keys()), set(KEYSURI_PROGRAMS))

    def test_integration_report_pass(self) -> None:
        report = _integration_report()
        self.assertEqual(report["integration_status"], "pass")
        self.assertEqual(report["integration_type"], INTEGRATION_TYPE)
        self.assertEqual(report["runtime_binding_status"], "design_ready_not_wired")
        self.assertEqual(report["weather_context_source"], "sanitized_canary_lock")
        self.assertFalse(report["ready_for_scheduler"])
        self.assertFalse(report["ready_for_production_auto_call"])
        self.assertFalse(any(report["side_effects"].values()))
        self.assertEqual(report["issues"], [])
        self.assertEqual(validate_keysuri_weather_binding_integration_result(report), [])

    def test_no_today_or_tomorrow_visual_contexts(self) -> None:
        report = _integration_report()
        keys = set(report["visual_contexts"].keys())
        self.assertNotIn("today_geenee", keys)
        for bad in ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            self.assertNotIn(bad, keys)


class KeysuriGlobalBindingVisualContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _integration_report()["visual_contexts"]["keysuri_global_tech"]

    def test_program_and_time(self) -> None:
        self.assertEqual(self.ctx["program_id"], "keysuri_global_tech")
        self.assertEqual(self.ctx["visual_time_context"], "seoul_daytime_1230")
        self.assertEqual(self.ctx["source_mode"], "sanitized_canary_lock")
        self.assertEqual(self.ctx["weather_condition"], "cloudy")
        self.assertEqual(self.ctx["location_baseline"], "Seoul")

    def test_identity_preserved(self) -> None:
        self.assertTrue(self.ctx["private_tech_secretary_identity"])
        self.assertIn("테크 비서 키수리", self.ctx["identity_label"])

    def test_no_anchor_framing_in_positive_fields(self) -> None:
        blob = " ".join(
            str(self.ctx.get(k, ""))
            for k in (
                "weather_visual_summary",
                "background_direction",
                "mood_direction",
                "program_tone",
            )
        ).lower()
        self.assertNotIn("public news anchor", blob)
        self.assertNotIn("weathercaster", blob)


class KeysuriKoreaBindingVisualContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _integration_report()["visual_contexts"]["keysuri_korea_tech"]

    def test_program_and_time(self) -> None:
        self.assertEqual(self.ctx["program_id"], "keysuri_korea_tech")
        self.assertEqual(self.ctx["visual_time_context"], "seoul_early_evening_1830")
        self.assertEqual(self.ctx["source_mode"], "sanitized_canary_lock")
        self.assertEqual(self.ctx["weather_condition"], "cloudy")
        self.assertEqual(self.ctx["location_baseline"], "Seoul")

    def test_identity_preserved(self) -> None:
        self.assertTrue(self.ctx["private_tech_secretary_identity"])
        self.assertIn("테크 비서 키수리", self.ctx["identity_label"])

    def test_no_anchor_framing_in_positive_fields(self) -> None:
        blob = " ".join(
            str(self.ctx.get(k, ""))
            for k in (
                "weather_visual_summary",
                "background_direction",
                "mood_direction",
                "program_tone",
            )
        ).lower()
        self.assertNotIn("broadcaster", blob)
        self.assertNotIn("announcer", blob)


class KeysuriIntegrationSecretGuardTests(unittest.TestCase):
    def test_report_no_secrets(self) -> None:
        report = _integration_report()
        blob = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn("WEATHER_API_KEY=", blob)
        self.assertNotIn("Authorization:", blob)
        self.assertNotIn("Bearer ", blob)
        self.assertNotIn("Tomorrow_Geenee", blob)
        self.assertNotRegex(blob, r"\b18:00\b")


class KeysuriIntegrationScriptTests(unittest.TestCase):
    def test_build_integration_report_script(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/build_keysuri_weather_binding_integration_report.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["integration_status"], "pass")
        self.assertEqual(out["issue_count"], 0)
        self.assertTrue(_OUT_REPORT.is_file())


if __name__ == "__main__":
    unittest.main()
