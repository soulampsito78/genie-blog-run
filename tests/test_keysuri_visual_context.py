"""Tests for Kee-Suri Seoul weather-aware visual context and image prompts."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_visual_context import (
    IDENTITY_LABEL,
    build_keysuri_image_prompt,
    build_keysuri_image_prompt_text,
    build_keysuri_visual_context,
    load_keysuri_weather_context_fixture,
    validate_keysuri_weather_context,
)
from keysuri_renderer import load_keysuri_prompt_input_fixture

_REPO = Path(__file__).resolve().parent.parent
_FEEDS = _REPO / "ops" / "feeds"
_OUT = _REPO / "output" / "keysuri_preview" / "visual_prompts"

_REQUIRED_IMAGE_PROMPT_KEYS = (
    "program_id",
    "program_label",
    "news_scope",
    "section_heading",
    "schedule_time_kst",
    "visual_time_band",
    "location_baseline",
    "weather_condition",
    "weather_visual_summary",
    "background_direction",
    "lighting_direction",
    "wardrobe_direction",
    "prop_direction",
    "mood_direction",
    "identity_label",
    "persona_fixed_block",
    "negative_prompt_rules",
    "image_prompt_text",
    "source_mode",
    "operational_status",
)


def _weather(name: str) -> dict:
    return load_keysuri_weather_context_fixture(str(_FEEDS / f"keysuri_weather_seoul_{name}.sample.json"))


def _global_prompt_input() -> dict:
    return load_keysuri_prompt_input_fixture(
        str(_FEEDS / "keysuri_global_prompt_input.sample.json")
    )


def _korea_prompt_input() -> dict:
    return load_keysuri_prompt_input_fixture(
        str(_FEEDS / "keysuri_korea_prompt_input.sample.json")
    )


class KeysuriWeatherValidationTests(unittest.TestCase):
    def test_all_fixture_weather_validates(self) -> None:
        for name in ("sunny", "cloudy", "rainy", "fine_dust", "cold"):
            with self.subTest(weather=name):
                self.assertEqual(validate_keysuri_weather_context(_weather(name)), [])

    def test_non_seoul_location_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["location"] = "Busan"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("location_invalid", codes)

    def test_wrong_timezone_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["timezone"] = "UTC"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("timezone_invalid", codes)

    def test_unsupported_weather_condition_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["weather_condition"] = "typhoon"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("weather_condition_invalid", codes)

    def test_source_mode_missing_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["source_mode"] = ""
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("source_mode_invalid", codes)

    def test_tomorrow_geenee_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["notes"] = "Tomorrow_Geenee reference"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("forbidden_retired_reference", codes)

    def test_tomorrow_genie_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["source_label"] = "tomorrow_genie"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("forbidden_retired_reference", codes)

    def test_scheduler_18_00_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["notes"] = "slot at 18:00"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("forbidden_scheduler_reference", codes)

    def test_forbidden_identity_fails(self) -> None:
        bad = deepcopy(_weather("sunny"))
        bad["notes"] = "테크 앵커 tone"
        codes = {i["code"] for i in validate_keysuri_weather_context(bad)}
        self.assertIn("forbidden_identity_string", codes)


class KeysuriGlobalVisualContextTests(unittest.TestCase):
    def test_global_schedule_and_band(self) -> None:
        ctx = build_keysuri_visual_context("keysuri_global_tech", _weather("sunny"))
        self.assertEqual(ctx["schedule_time_kst"], "12:30")
        self.assertEqual(ctx["visual_time_band"], "daytime")
        self.assertEqual(ctx["section_heading"], "글로벌 테크 TOP 5")

    def test_sunny_global_daylight(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue(
            "daylight" in blob or "sunlit" in blob or "sunny" in prompt["weather_visual_summary"].lower()
        )

    def test_cloudy_global_diffused(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("cloudy"))
        self.assertIn("diffused", prompt["background_direction"].lower())

    def test_rainy_global_rain(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("rainy"))
        blob = prompt["image_prompt_text"].lower()
        self.assertIn("rain", blob)

    def test_fine_dust_global_haze(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("fine_dust"))
        self.assertIn("haz", prompt["background_direction"].lower())

    def test_cold_global_winter(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("cold"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue("cold" in blob or "winter" in blob)

    def test_global_international_direction(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue("global" in blob or "international" in blob)

    def test_global_not_newsroom_anchor(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        text = prompt["image_prompt_text"].lower()
        self.assertNotIn("테크 앵커", prompt["image_prompt_text"])
        self.assertNotIn("뉴스 앵커", prompt["image_prompt_text"])
        self.assertIn("no newsroom", text)


class KeysuriKoreaVisualContextTests(unittest.TestCase):
    def test_korea_schedule_and_band(self) -> None:
        ctx = build_keysuri_visual_context("keysuri_korea_tech", _weather("sunny"))
        self.assertEqual(ctx["schedule_time_kst"], "18:30")
        self.assertEqual(ctx["visual_time_band"], "early_evening")
        self.assertEqual(ctx["section_heading"], "국내 테크 TOP 5")

    def test_sunny_korea_evening_glow(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("sunny"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue("evening" in blob or "afternoon" in blob)

    def test_cloudy_korea_muted_evening(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("cloudy"))
        self.assertIn("evening", prompt["background_direction"].lower())

    def test_rainy_korea_evening_rain(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("rainy"))
        blob = prompt["image_prompt_text"].lower()
        self.assertIn("rain", blob)
        self.assertIn("interior", blob)

    def test_fine_dust_korea_haze(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("fine_dust"))
        self.assertIn("haz", prompt["background_direction"].lower())

    def test_cold_korea_warm_interior(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("cold"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue("warm" in blob and "interior" in blob)

    def test_korea_domestic_direction(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("sunny"))
        blob = prompt["image_prompt_text"].lower()
        self.assertTrue("korean" in blob or "domestic" in blob or "seoul" in blob)

    def test_korea_not_nightlife_cyberpunk(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("sunny"))
        text = prompt["image_prompt_text"].lower()
        self.assertIn("no nightlife", text)
        self.assertIn("no cyberpunk", text)


class KeysuriImagePromptObjectTests(unittest.TestCase):
    def test_required_keys(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        for key in _REQUIRED_IMAGE_PROMPT_KEYS:
            self.assertIn(key, prompt)

    def test_identity_and_operational_status(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_korea_tech", _weather("rainy"))
        self.assertEqual(prompt["identity_label"], IDENTITY_LABEL)
        self.assertEqual(prompt["operational_status"], "review_required")
        self.assertEqual(prompt["source_mode"], "offline_fixture")

    def test_negative_rules(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("cloudy"))
        neg = " ".join(prompt["negative_prompt_rules"]).lower()
        self.assertIn("no collage", neg)
        self.assertIn("no text", neg)
        self.assertIn("no newsroom", neg)
        self.assertIn("no public tv anchor", neg)

    def test_persona_block_present(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        self.assertIn("테크 비서 키수리", prompt["persona_fixed_block"])


class KeysuriVisualCrossScopeTests(unittest.TestCase):
    def test_global_prompt_input_with_korea_program_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_keysuri_image_prompt(
                "keysuri_korea_tech",
                _weather("sunny"),
                _global_prompt_input(),
            )

    def test_korea_prompt_input_with_global_program_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_keysuri_image_prompt(
                "keysuri_global_tech",
                _weather("sunny"),
                _korea_prompt_input(),
            )


class KeysuriVisualRetirementTests(unittest.TestCase):
    def test_image_prompt_no_retired_strings(self) -> None:
        prompt = build_keysuri_image_prompt("keysuri_global_tech", _weather("sunny"))
        text = prompt["image_prompt_text"]
        self.assertNotIn("Tomorrow_Geenee", text)
        self.assertNotIn("tomorrow_genie", text)
        self.assertNotRegex(text, r"\b18:00\b")


class KeysuriVisualPromptScriptTests(unittest.TestCase):
    def test_build_visual_prompt_samples_script(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/build_keysuri_visual_prompt_samples.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("ok"))
        self.assertEqual(len(out.get("samples", [])), 10)
        sample_path = _OUT / "keysuri_global_sunny_image_prompt.json"
        self.assertTrue(sample_path.is_file())


if __name__ == "__main__":
    unittest.main()
