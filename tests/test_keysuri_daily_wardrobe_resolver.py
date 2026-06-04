"""Tests for Kee-Suri daily wardrobe seed resolver (offline — no image API)."""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import keysuri_daily_wardrobe_resolver as resolver
from keysuri_daily_wardrobe_resolver import (
    DEFAULT_TIMEZONE,
    DEFAULT_WARDROBE_GROUP,
    KEYSURI_IMAGE_PROGRAMS,
    RESOLVER_VERSION,
    SIDE_EFFECTS_DISABLED,
    WARDROBE_PALETTES,
    derive_wardrobe_date_kst_from_datetime,
    resolve_keysuri_daily_wardrobe,
)

_REPO = Path(__file__).resolve().parent.parent
_RESOLVER_PATH = _REPO / "keysuri_daily_wardrobe_resolver.py"
_KST = ZoneInfo("Asia/Seoul")


class KeysuriDailyWardrobeResolverTests(unittest.TestCase):
    def test_same_kst_date_global_korea_same_profile(self) -> None:
        global_result = resolve_keysuri_daily_wardrobe(
            "2026-06-04",
            "keysuri_global_tech",
        )
        korea_result = resolve_keysuri_daily_wardrobe(
            "2026-06-04",
            "keysuri_korea_tech",
        )
        self.assertEqual(
            global_result.wardrobe_profile_id,
            korea_result.wardrobe_profile_id,
        )
        self.assertEqual(
            global_result.daily_wardrobe_seed,
            korea_result.daily_wardrobe_seed,
        )
        self.assertEqual(global_result.debug.program_id, "keysuri_global_tech")
        self.assertEqual(korea_result.debug.program_id, "keysuri_korea_tech")

    def test_retry_same_date_same_seed(self) -> None:
        first = resolve_keysuri_daily_wardrobe("2026-06-04", "keysuri_global_tech")
        second = resolve_keysuri_daily_wardrobe("2026-06-04", "keysuri_global_tech")
        self.assertEqual(first, second)

    def test_manual_override_valid_both_programs(self) -> None:
        override_id = "profile_02_navy_cream"
        global_result = resolve_keysuri_daily_wardrobe(
            "2026-06-04",
            "keysuri_global_tech",
            manual_override_profile_id=override_id,
        )
        korea_result = resolve_keysuri_daily_wardrobe(
            "2026-06-04",
            "keysuri_korea_tech",
            manual_override_profile_id=override_id,
        )
        self.assertEqual(global_result.wardrobe_profile_id, override_id)
        self.assertEqual(korea_result.wardrobe_profile_id, override_id)
        self.assertTrue(global_result.debug.manual_override_applied)
        self.assertTrue(korea_result.debug.manual_override_applied)
        self.assertEqual(
            global_result.daily_wardrobe_seed,
            korea_result.daily_wardrobe_seed,
        )

    def test_invalid_override_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_keysuri_daily_wardrobe(
                "2026-06-04",
                "keysuri_global_tech",
                manual_override_profile_id="profile_99_missing",
            )
        self.assertIn("invalid_override_profile_id", str(ctx.exception))

    def test_invalid_kst_date_rejected(self) -> None:
        for bad in ("", "2026-13-40", "06-04-2026", "2026/06/04", "2026-06-04T12:00:00"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    resolve_keysuri_daily_wardrobe(bad, "keysuri_global_tech")
                self.assertIn("invalid_wardrobe_date_kst", str(ctx.exception))

    def test_wrong_wardrobe_group_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_keysuri_daily_wardrobe(
                "2026-06-04",
                "keysuri_global_tech",
                wardrobe_group="today_geenee_daily",
            )
        self.assertIn("invalid_wardrobe_group", str(ctx.exception))

    def test_unknown_palette_version_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_keysuri_daily_wardrobe(
                "2026-06-04",
                "keysuri_global_tech",
                wardrobe_palette_version="v99",
            )
        self.assertIn("unknown_palette_version", str(ctx.exception))

    def test_forbidden_program_rejected(self) -> None:
        for bad in ("today_geenee", "tomorrow_geenee", "tomorrow_genie", "unknown_program"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    resolve_keysuri_daily_wardrobe("2026-06-04", bad)
                self.assertIn("invalid_program_id", str(ctx.exception))

    def test_timezone_kst_derivation(self) -> None:
        utc_late = datetime(2026, 6, 3, 16, 30, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(
            derive_wardrobe_date_kst_from_datetime(utc_late),
            "2026-06-04",
        )
        kst_midday = datetime(2026, 6, 4, 12, 30, 0, tzinfo=_KST)
        self.assertEqual(
            derive_wardrobe_date_kst_from_datetime(kst_midday),
            "2026-06-04",
        )

    def test_naive_datetime_rejected(self) -> None:
        naive = datetime(2026, 6, 4, 12, 30, 0)
        with self.assertRaises(ValueError) as ctx:
            derive_wardrobe_date_kst_from_datetime(naive)
        self.assertIn("naive_datetime_not_allowed", str(ctx.exception))

    def test_side_effects_disabled(self) -> None:
        self.assertFalse(any(SIDE_EFFECTS_DISABLED.values()))
        expected_keys = {
            "scheduler_changes",
            "cloud_run_changes",
            "gcp_changes",
            "image_api_calls",
            "gemini_or_llm_calls",
            "production_wiring",
        }
        self.assertEqual(set(SIDE_EFFECTS_DISABLED.keys()), expected_keys)

    def test_profile_01_matches_current_lock_direction(self) -> None:
        profile = WARDROBE_PALETTES["v1"][0]
        self.assertEqual(profile.wardrobe_profile_id, "profile_01_charcoal_ivory")
        snippet = profile.prompt_snippet.lower()
        self.assertIn("charcoal", snippet)
        self.assertIn("ivory", snippet)
        self.assertIn("sleek short bob", snippet)
        self.assertIn("thin metal glasses", snippet)
        self.assertNotIn("weathercaster", snippet.replace("not a weathercaster", ""))

    def test_program_id_not_in_hash(self) -> None:
        date_str = "2026-06-04"
        global_result = resolve_keysuri_daily_wardrobe(date_str, "keysuri_global_tech")
        korea_result = resolve_keysuri_daily_wardrobe(date_str, "keysuri_korea_tech")
        self.assertEqual(global_result.wardrobe_profile_id, korea_result.wardrobe_profile_id)
        self.assertEqual(global_result.daily_wardrobe_seed, korea_result.daily_wardrobe_seed)

        payload = f"{DEFAULT_WARDROBE_GROUP}|{date_str}|v1"
        digest = __import__("hashlib").sha256(payload.encode("utf-8")).hexdigest()
        index = int(digest, 16) % len(WARDROBE_PALETTES["v1"])
        expected_profile_id = WARDROBE_PALETTES["v1"][index].wardrobe_profile_id
        self.assertEqual(global_result.wardrobe_profile_id, expected_profile_id)

    def test_no_today_geenee_imports_or_forbidden_modules(self) -> None:
        source = _RESOLVER_PATH.read_text(encoding="utf-8")
        forbidden_import_modules = (
            "image_exec_suffixes",
            "weather_image_context",
        )
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for mod in forbidden_import_modules:
            with self.subTest(module=mod):
                self.assertFalse(
                    any(mod in line for line in import_lines),
                    msg=f"forbidden import of {mod!r} in resolver module",
                )

        imported_modules = {
            getattr(mod, "__name__", "")
            for _, mod in inspect.getmembers(resolver, inspect.ismodule)
            if getattr(mod, "__name__", "").startswith(forbidden_import_modules)
        }
        self.assertEqual(imported_modules, set())

    def test_different_dates_are_deterministic(self) -> None:
        first = resolve_keysuri_daily_wardrobe("2026-06-04", "keysuri_global_tech")
        second = resolve_keysuri_daily_wardrobe("2026-06-04", "keysuri_global_tech")
        third = resolve_keysuri_daily_wardrobe("2026-06-05", "keysuri_global_tech")
        self.assertEqual(first, second)
        self.assertEqual(first.debug.resolver_version, RESOLVER_VERSION)
        self.assertEqual(third.debug.wardrobe_date_kst, "2026-06-05")
        self.assertIn(
            third.wardrobe_profile_id,
            {profile.wardrobe_profile_id for profile in WARDROBE_PALETTES["v1"]},
        )


if __name__ == "__main__":
    unittest.main()
