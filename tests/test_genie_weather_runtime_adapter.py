"""Tests for GENIE Seoul weather runtime adapter."""
from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from genie_weather_runtime_adapter import (
    build_genie_weather_consumer_context,
    load_genie_runtime_weather_payload_fixture,
    normalize_genie_runtime_weather_payload,
    validate_genie_runtime_weather_payload,
)
from keysuri_visual_context import validate_keysuri_weather_context

_REPO = Path(__file__).resolve().parent.parent
_FEEDS = _REPO / "ops" / "feeds"


def _payload(name: str) -> dict:
    return load_genie_runtime_weather_payload_fixture(
        str(_FEEDS / f"genie_weather_runtime_{name}.sample.json")
    )


class GenieWeatherPayloadValidationTests(unittest.TestCase):
    def test_valid_fixtures_validate(self) -> None:
        for slug in (
            "seoul_clear",
            "seoul_cloudy",
            "seoul_rain",
            "seoul_fine_dust",
            "seoul_cold",
            "seoul_snow",
        ):
            with self.subTest(fixture=slug):
                self.assertEqual(validate_genie_runtime_weather_payload(_payload(slug)), [])

    def test_non_seoul_fails(self) -> None:
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(_payload("invalid_non_seoul"))}
        self.assertIn("location_city_invalid", codes)

    def test_tomorrow_fails(self) -> None:
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(_payload("invalid_tomorrow"))}
        self.assertIn("forbidden_retired_reference", codes)

    def test_missing_provider_mode_fails(self) -> None:
        bad = deepcopy(_payload("seoul_clear"))
        bad["provider_mode"] = ""
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(bad)}
        self.assertIn("provider_mode_invalid", codes)

    def test_missing_location_fails(self) -> None:
        bad = deepcopy(_payload("seoul_clear"))
        bad["location"] = None
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(bad)}
        self.assertIn("location_missing", codes)

    def test_wrong_timezone_fails(self) -> None:
        bad = deepcopy(_payload("seoul_clear"))
        bad["location"]["timezone"] = "UTC"
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(bad)}
        self.assertIn("location_timezone_invalid", codes)

    def test_unsupported_payload_type_fails(self) -> None:
        issues = validate_genie_runtime_weather_payload([])  # type: ignore[arg-type]
        self.assertTrue(issues)
        self.assertEqual(issues[0]["code"], "payload_invalid")

    def test_forbidden_identity_fails(self) -> None:
        bad = deepcopy(_payload("seoul_clear"))
        bad["notes"] = "테크 앵커 tone"
        codes = {i["code"] for i in validate_genie_runtime_weather_payload(bad)}
        self.assertIn("forbidden_identity_string", codes)


class GenieWeatherNormalizationTests(unittest.TestCase):
    def test_clear_maps_to_clear_or_sunny(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_clear"))
        self.assertIn(ctx["weather_condition"], ("clear", "sunny"))

    def test_cloudy_maps_to_cloudy(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_cloudy"))
        self.assertEqual(ctx["weather_condition"], "cloudy")

    def test_rain_maps_to_rainy(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_rain"))
        self.assertEqual(ctx["weather_condition"], "rainy")

    def test_snow_maps_to_snow(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_snow"))
        self.assertEqual(ctx["weather_condition"], "snow")

    def test_fine_dust_maps(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_fine_dust"))
        self.assertIn(ctx["weather_condition"], ("fine_dust", "haze"))

    def test_cold_maps_to_cold(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_cold"))
        self.assertEqual(ctx["weather_condition"], "cold")

    def test_normalized_validates_with_keysuri(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_rain"))
        self.assertEqual(validate_keysuri_weather_context(ctx), [])

    def test_source_mode_maps_provider_mode(self) -> None:
        ctx = normalize_genie_runtime_weather_payload(_payload("seoul_clear"))
        self.assertEqual(ctx["source_mode"], "offline_fixture")

    def test_raw_provider_payload_not_copied(self) -> None:
        payload = deepcopy(_payload("seoul_clear"))
        payload["raw_provider_payload"] = {"secret": "provider_blob", "nested": {"x": 1}}
        ctx = normalize_genie_runtime_weather_payload(payload)
        self.assertNotIn("raw_provider_payload", ctx)

    def test_unknown_condition_raises(self) -> None:
        bad = deepcopy(_payload("seoul_clear"))
        bad["condition_code"] = "unknown_xyz"
        bad["condition_label"] = "unknown"
        bad["fine_dust_level"] = "good"
        with self.assertRaises(ValueError):
            normalize_genie_runtime_weather_payload(bad)


class GenieWeatherConsumerContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weather = normalize_genie_runtime_weather_payload(_payload("seoul_clear"))

    def test_today_geenee_consumer(self) -> None:
        ctx = build_genie_weather_consumer_context("today_geenee", self.weather)
        self.assertEqual(ctx["consumer_id"], "today_geenee")
        self.assertEqual(ctx["schedule_time_kst"], "06:30")
        self.assertIn("market", ctx["weather_usage"].lower())
        self.assertIn("must not become weather-only", ctx["weather_usage"])
        self.assertNotIn("Tomorrow_Geenee", ctx["weather_usage"])

    def test_keysuri_global_consumer(self) -> None:
        ctx = build_genie_weather_consumer_context("keysuri_global_tech", self.weather)
        self.assertEqual(ctx["schedule_time_kst"], "12:30")
        self.assertIn("visual context", ctx["weather_usage"].lower())

    def test_keysuri_korea_consumer(self) -> None:
        ctx = build_genie_weather_consumer_context("keysuri_korea_tech", self.weather)
        self.assertEqual(ctx["schedule_time_kst"], "18:30")

    def test_tomorrow_consumer_fails(self) -> None:
        for bad in ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            with self.subTest(consumer=bad):
                with self.assertRaises(ValueError):
                    build_genie_weather_consumer_context(bad, self.weather)

    def test_unsupported_consumer_fails(self) -> None:
        with self.assertRaises(ValueError):
            build_genie_weather_consumer_context("invalid_consumer", self.weather)


class GenieWeatherConsumerScriptTests(unittest.TestCase):
    def test_build_consumer_samples_script(self) -> None:
        import json
        import subprocess

        proc = subprocess.run(
            ["python3", "scripts/build_genie_weather_consumer_samples.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("ok"))
        self.assertEqual(len(out.get("samples", [])), 18)
        sample = _REPO / "output/keysuri_preview/weather_consumers/today_geenee_clear_weather_consumer.json"
        self.assertTrue(sample.is_file())


if __name__ == "__main__":
    unittest.main()
