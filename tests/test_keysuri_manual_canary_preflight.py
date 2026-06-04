"""Tests for Kee-Suri manual canary preflight (offline, no image API)."""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import keysuri_manual_canary_preflight as preflight
from keysuri_manual_canary_preflight import (
    BLOCK_LIVE_CALL,
    FAIL,
    PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL,
    ManualCanaryApproval,
    run_keysuri_manual_canary_preflight,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_MODULE_PATH = _REPO / "keysuri_manual_canary_preflight.py"

_PROFILE_01 = "profile_01_charcoal_ivory"
_SEED_2026_06_04 = "keysuri_daily|2026-06-04|v1|profile_01_charcoal_ivory"
_PROFILE_03 = "profile_03_graphite_champagne"
_SEED_2026_06_05 = "keysuri_daily|2026-06-05|v1|profile_03_graphite_champagne"


def _approval(
    *,
    date: str = "2026-06-04",
    program: str = "keysuri_global_tech",
    profile_id: str = _PROFILE_01,
    seed: str = _SEED_2026_06_04,
    operator_ref: str = "ops-test",
) -> ManualCanaryApproval:
    return ManualCanaryApproval(
        operator_ref=operator_ref,
        wardrobe_date_kst=date,
        program_id=program,
        expected_wardrobe_profile_id=profile_id,
        expected_daily_wardrobe_seed=seed,
    )


class KeysuriManualCanaryPreflightInputTests(unittest.TestCase):
    def test_missing_date_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(i.code == "invalid_wardrobe_date_kst" for i in result.issues))

    def test_invalid_date_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-13-40",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(i.code == "invalid_wardrobe_date_kst" for i in result.issues))

    def test_invalid_program_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="unknown_program",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(i.code == "invalid_program_id" for i in result.issues))

    def test_today_geenee_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="today_geenee",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(i.code == "forbidden_program_id" for i in result.issues))

    def test_tomorrow_geenee_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="tomorrow_geenee",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertTrue(any(i.code == "forbidden_program_id" for i in result.issues))


class KeysuriManualCanaryPreflightApprovalTests(unittest.TestCase):
    def test_no_approval_blocks_live_call(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, BLOCK_LIVE_CALL)
        self.assertFalse(result.manual_approval_valid)
        self.assertEqual(result.issues, ())
        self.assertTrue(result.default_prompt_unchanged)
        self.assertTrue(result.opt_in_prompt_changed)
        self.assertTrue(result.production_flags_false)

    def test_valid_approval_passes_one_manual_call(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            approval=_approval(),
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL)
        self.assertTrue(result.manual_approval_valid)
        self.assertEqual(result.wardrobe_profile_id, _PROFILE_01)
        self.assertEqual(result.daily_wardrobe_seed, _SEED_2026_06_04)
        self.assertTrue(any(w.code == "manual_one_call_only" for w in result.warnings))

    def test_wrong_expected_profile_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            approval=_approval(profile_id="profile_02_navy_cream"),
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertFalse(result.manual_approval_valid)
        self.assertTrue(any(i.code == "approval_profile_mismatch" for i in result.issues))

    def test_wrong_expected_seed_fails(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            approval=_approval(seed="keysuri_daily|2026-06-04|v1|wrong"),
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(result.status, FAIL)
        self.assertFalse(result.manual_approval_valid)
        self.assertTrue(any(i.code == "approval_seed_mismatch" for i in result.issues))


class KeysuriManualCanaryPreflightReviewFlagsTests(unittest.TestCase):
    def test_2026_06_04_profile_01_review_required(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertTrue(result.review_required)
        self.assertFalse(result.new_visual_qa_required)

    def test_2026_06_05_profile_03_new_visual_qa_required(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-05",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertFalse(result.review_required)
        self.assertTrue(result.new_visual_qa_required)
        self.assertEqual(result.wardrobe_profile_id, _PROFILE_03)
        self.assertEqual(result.daily_wardrobe_seed, _SEED_2026_06_05)


class KeysuriManualCanaryPreflightSafetyTests(unittest.TestCase):
    def test_production_flags_false(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertTrue(result.production_flags_false)

    def test_no_image_api_client_provider_imports(self) -> None:
        source = _MODULE_PATH.read_text(encoding="utf-8")
        forbidden_modules = (
            "keysuri_image_api_canary_client",
            "keysuri_image_api_gate",
            "keysuri_image_provider_contract",
            "vertex",
            "gemini",
        )
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for mod in forbidden_modules:
            with self.subTest(module=mod):
                self.assertFalse(
                    any(mod in line for line in import_lines),
                    msg=f"forbidden import of {mod!r} in preflight module",
                )

        imported_modules = {
            getattr(mod, "__name__", "")
            for _, mod in inspect.getmembers(preflight, inspect.ismodule)
            if getattr(mod, "__name__", "")
        }
        for forbidden in forbidden_modules:
            with self.subTest(imported=forbidden):
                self.assertFalse(
                    any(name.startswith(forbidden) for name in imported_modules),
                    msg=f"forbidden loaded module matching {forbidden!r}",
                )

    def test_default_prompt_non_injected(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertTrue(result.default_prompt_unchanged)
        self.assertIsNotNone(result.wardrobe_clause)

    def test_opt_in_prompt_wardrobe_clause_only(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertTrue(result.opt_in_prompt_changed)
        self.assertNotIn(
            "not a lounge or glamour shoot",
            (result.wardrobe_clause or "").lower(),
        )
        self.assertEqual(result.status, BLOCK_LIVE_CALL)
        self.assertFalse(any(i.code == "opt_in_full_snippet_tail_injected" for i in result.issues))

    def test_global_korea_parity_same_date(self) -> None:
        result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
            check_global_korea_parity=True,
        )
        self.assertEqual(result.status, BLOCK_LIVE_CALL)
        self.assertFalse(any(i.code.startswith("parity_") for i in result.issues))


class KeysuriManualCanaryPreflightBaselineTests(unittest.TestCase):
    def test_baseline_mapping_both_programs(self) -> None:
        global_result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_global_tech",
            lock_path=_LOCK_PATH,
        )
        korea_result = run_keysuri_manual_canary_preflight(
            wardrobe_date_kst="2026-06-04",
            program_id="keysuri_korea_tech",
            lock_path=_LOCK_PATH,
        )
        self.assertEqual(
            global_result.baseline_reference_path,
            "output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg",
        )
        self.assertEqual(
            korea_result.baseline_reference_path,
            "output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg",
        )
        self.assertIsNone(global_result.baseline_file_exists)
        self.assertIsNone(korea_result.baseline_file_exists)

    def test_baseline_missing_file_warning_only(self) -> None:
        missing_baseline = (
            _REPO
            / "output/keysuri_preview/image_canary/keysuri_global_canary_missing_preflight_test.jpg"
        )
        if missing_baseline.is_file():
            missing_baseline.unlink()

        original_paths = dict(preflight._BASELINE_REFERENCE_PATHS)
        try:
            preflight._BASELINE_REFERENCE_PATHS["keysuri_global_tech"] = str(
                missing_baseline.relative_to(_REPO)
            )
            result = run_keysuri_manual_canary_preflight(
                wardrobe_date_kst="2026-06-04",
                program_id="keysuri_global_tech",
                lock_path=_LOCK_PATH,
                check_baseline_exists=True,
            )
        finally:
            preflight._BASELINE_REFERENCE_PATHS.clear()
            preflight._BASELINE_REFERENCE_PATHS.update(original_paths)

        self.assertEqual(result.status, BLOCK_LIVE_CALL)
        self.assertFalse(result.baseline_file_exists)
        self.assertTrue(any(w.code == "baseline_file_missing" for w in result.warnings))
        self.assertFalse(any(i.code == "baseline_file_missing" for i in result.issues))


if __name__ == "__main__":
    unittest.main()
