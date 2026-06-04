"""Tests for Kee-Suri weather visual prompt integration (offline, no image API)."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_daily_wardrobe_resolver import RESOLVER_VERSION
from keysuri_visual_context import FORBIDDEN_SOURCE_MODES
from keysuri_weather_binding_integration import (
    KEYSURI_PROGRAMS,
    build_keysuri_weather_binding_integration_report,
)
from keysuri_weather_visual_prompt_integration import (
    HAND_POLICY,
    KOREA_HAND_POLICY,
    KOREA_MOOD,
    KOREA_POSE_POLICY,
    KOREA_TABLET_POLICY,
    KOREA_TIME_PROFILE,
    POSE_POLICY,
    PRODUCTION_REFERENCE_PARAGRAPH,
    PROMPT_CONTRACT_TYPE,
    REFERENCE_USAGE_POLICY,
    REPORT_TYPE,
    SOURCE_MODE,
    VARIATION_MODE,
    WARDROBE_LOCK,
    WEATHER_POLICY,
    build_daily_wardrobe_metadata,
    build_keysuri_weather_visual_prompt_contract,
    build_keysuri_weather_visual_prompt_contracts_from_integration_result,
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
    validate_keysuri_weather_visual_prompt_contract,
    validate_keysuri_weather_visual_prompt_report,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_INTEGRATION_PATH = _REPO / "keysuri_weather_visual_prompt_integration.py"
_OUT_REPORT = (
    _REPO
    / "output"
    / "keysuri_preview"
    / "weather_canary"
    / "keysuri_weather_visual_prompt_report.json"
)

_DAILY_WARDROBE_METADATA_KEYS = (
    "wardrobe_group",
    "wardrobe_date_kst",
    "wardrobe_palette_version",
    "wardrobe_profile_id",
    "daily_wardrobe_seed",
    "manual_override_applied",
    "resolver_version",
    "program_id",
)


def _integration() -> dict:
    return build_keysuri_weather_binding_integration_report(str(_LOCK_PATH))


def _report() -> dict:
    return build_keysuri_weather_visual_prompt_report_from_canary_lock(str(_LOCK_PATH))


class KeysuriWeatherVisualPromptReportTests(unittest.TestCase):
    def test_report_pass_from_canary_lock(self) -> None:
        report = _report()
        self.assertEqual(report["report_status"], "pass")
        self.assertEqual(report["report_type"], REPORT_TYPE)
        self.assertEqual(report["runtime_binding_status"], "design_ready_not_wired")
        self.assertEqual(report["weather_context_source"], SOURCE_MODE)
        self.assertFalse(report["ready_for_image_api_call"])
        self.assertFalse(report["ready_for_scheduler"])
        self.assertFalse(report["ready_for_production_auto_call"])
        self.assertFalse(any(report["side_effects"].values()))
        self.assertEqual(report["issues"], [])
        self.assertEqual(
            set(report["prompt_contracts"].keys()),
            set(KEYSURI_PROGRAMS),
        )

    def test_no_today_or_tomorrow_prompts(self) -> None:
        keys = set(_report()["prompt_contracts"].keys())
        self.assertNotIn("today_geenee", keys)
        for bad in ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            self.assertNotIn(bad, keys)


class KeysuriGlobalPromptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = _report()["prompt_contracts"]["keysuri_global_tech"]

    def test_global_contract_fields(self) -> None:
        c = self.contract
        self.assertEqual(c["program_id"], "keysuri_global_tech")
        self.assertEqual(c["prompt_contract_type"], PROMPT_CONTRACT_TYPE)
        self.assertEqual(c["source_mode"], SOURCE_MODE)
        self.assertEqual(c["visual_time_context"], "seoul_daytime_1230")
        self.assertEqual(c["weather_condition"], "cloudy")
        self.assertEqual(c["location"], "Seoul")
        self.assertEqual(c["variation_mode"], VARIATION_MODE)
        self.assertEqual(c["pose_policy"], POSE_POLICY)
        self.assertEqual(c["hand_policy"], HAND_POLICY)
        self.assertEqual(c["weather_policy"], WEATHER_POLICY)

    def test_global_positive_prompt(self) -> None:
        pos = self.contract["positive_prompt"].lower()
        self.assertIn("same person as the reference", pos)
        self.assertIn("same kee-suri identity", pos)
        self.assertIn("small natural variation", pos)
        self.assertIn("do not require large pose or composition change", pos)
        self.assertIn("relaxed hands", pos)
        self.assertIn("fingers mostly hidden", pos)
        self.assertIn("tablet held simply", pos)
        self.assertIn("no pointing", pos)
        self.assertIn("daytime or early afternoon", pos)
        self.assertIn("cloudy", pos)
        self.assertNotIn("winter 18:30", pos)
        self.assertNotIn("after-sunset", pos)
        self.assertNotIn("sun has already set", pos)
        self.assertNotIn("deep blue-gray seoul evening", pos)
        self.assertNotIn("tablet is optional", pos)
        self.assertNotIn("new pose and camera perspective", pos)
        self.assertNotIn("subtle briefing gesture", pos)
        self.assertNotIn("weathercaster", pos)
        self.assertNotIn("news anchor", pos)

    def test_global_negative_and_safety(self) -> None:
        neg = self.contract["negative_prompt"].lower()
        self.assertIn("no pointing finger", neg)
        self.assertIn("no tapping tablet", neg)
        self.assertIn("no stylus", neg)
        self.assertIn("not a different woman with similar clothes only", neg)
        self.assertIn("not a weathercaster", neg)
        self.assertTrue(self.contract["safety_constraints"]["no_collage"])
        self.assertTrue(self.contract["safety_constraints"]["no_public_anchor"])


class KeysuriKoreaPromptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = _report()["prompt_contracts"]["keysuri_korea_tech"]

    def test_korea_contract_fields(self) -> None:
        c = self.contract
        self.assertEqual(c["program_id"], "keysuri_korea_tech")
        self.assertEqual(c["visual_time_context"], "seoul_early_evening_1830")
        self.assertEqual(c["weather_condition"], "cloudy")
        self.assertEqual(c["pose_policy"], KOREA_POSE_POLICY)
        self.assertEqual(c["hand_policy"], KOREA_HAND_POLICY)
        self.assertEqual(c["korea_time_profile"], KOREA_TIME_PROFILE)
        self.assertEqual(c["korea_tablet_policy"], KOREA_TABLET_POLICY)
        self.assertEqual(c["korea_hand_posture_policy"], KOREA_HAND_POLICY)
        self.assertEqual(c["korea_mood"], KOREA_MOOD)

    def test_korea_positive_prompt(self) -> None:
        pos = self.contract["positive_prompt"].lower()
        self.assertIn("same person as the reference", pos)
        self.assertIn("winter 18:30", pos)
        self.assertIn("after-sunset", pos)
        self.assertIn("sun has already set", pos)
        self.assertIn("deep blue-gray seoul evening city", pos)
        self.assertIn("city lights already visible but not flashy", pos)
        self.assertIn("warm premium interior office light", pos)
        self.assertIn("calm after-work private briefing", pos)
        self.assertIn("face clearly lit", pos)
        self.assertIn("must not darken", pos)
        self.assertIn("organized after-work private briefing", pos)
        self.assertIn("tablet is optional", pos)
        self.assertIn("hands calmly clasped", pos)
        self.assertIn("already been organized", pos)
        self.assertIn("ready to brief", pos)
        self.assertIn("domestic tech", pos)
        self.assertIn("no pointing", pos)
        self.assertNotIn("city lights just beginning", pos)
        self.assertNotIn("blue-gray seoul dusk", pos)
        self.assertNotIn("early evening 18:30", pos)
        self.assertNotIn("tablet held simply at waist", pos)
        self.assertNotIn("new pose and camera perspective", pos)
        self.assertNotIn("weathercaster", pos)

    def test_korea_negative_prompt(self) -> None:
        neg = self.contract["negative_prompt"].lower()
        for phrase in (
            "bright cloudy daytime",
            "white-night office",
            "daylight-looking dusk",
            "black night",
            "cinematic noir",
            "hotel lounge",
            "bar lounge",
            "fashion editorial",
            "seductive night scene",
            "outdoor weather scene",
            "no tomorrow_geenee",
            "not a weathercaster",
        ):
            self.assertIn(phrase, neg)

    def test_identity_block(self) -> None:
        ident = self.contract["identity"]
        self.assertEqual(ident["persona_name"], "테크 비서 키수리")
        self.assertEqual(ident["role"], "private_tech_secretary")
        self.assertEqual(
            self.contract["weather_visual_usage"]["usage_type"],
            "visual_realism_only",
        )
        must_not = self.contract["weather_visual_usage"]["must_not_affect"]
        self.assertIn("wardrobe", must_not)
        self.assertIn("pose", must_not)


class KeysuriProductionProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_contract = _report()["prompt_contracts"]["keysuri_global_tech"]
        self.korea_contract = _report()["prompt_contracts"]["keysuri_korea_tech"]

    def test_reference_usage_policy(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            policy = contract["reference_usage_policy"]
            self.assertEqual(policy["reference_role"], "identity_and_wardrobe_continuity_only")
            self.assertEqual(policy["variation_mode"], VARIATION_MODE)
            self.assertNotIn("variation_required", policy)
            allowed = {x.lower() for x in policy["variation_allowed"]}
            self.assertIn("small head angle change", allowed)
            self.assertIn("window sky tone and mild city haze", allowed)

    def test_wardrobe_lock(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            lock = contract["wardrobe_lock"]
            allowed = " ".join(lock["allowed"]).lower()
            forbidden = " ".join(lock["forbidden"]).lower()
            self.assertIn("charcoal fitted suit", allowed)
            self.assertIn("ivory", allowed)
            self.assertIn("pencil skirt", allowed)
            self.assertIn("umbrella", forbidden)
            self.assertIn("raincoat", forbidden)
            self.assertIn("today_geenee wardrobe logic", forbidden)

    def test_pose_and_hand_policy(self) -> None:
        g_pose = self.global_contract["pose_variation_policy"]
        self.assertEqual(g_pose["pose_policy"], POSE_POLICY)
        self.assertEqual(g_pose["hand_policy"], HAND_POLICY)
        self.assertEqual(g_pose["weather_policy"], WEATHER_POLICY)
        must_not = " ".join(g_pose["must_not"]).lower()
        self.assertIn("pointing finger", must_not)
        self.assertIn("stylus", must_not)

        k_pose = self.korea_contract["pose_variation_policy"]
        self.assertEqual(k_pose["pose_policy"], KOREA_POSE_POLICY)
        self.assertEqual(k_pose["hand_policy"], KOREA_HAND_POLICY)
        korea_vars = " ".join(k_pose["korea_tech_allowed_variations"]).lower()
        self.assertIn("tablet optional or absent", korea_vars)
        self.assertIn("hands calmly clasped", korea_vars)

    def test_global_korea_separation(self) -> None:
        g_pos = self.global_contract["positive_prompt"].lower()
        k_pos = self.korea_contract["positive_prompt"].lower()
        self.assertIn("daytime or early afternoon", g_pos)
        self.assertIn("winter 18:30", k_pos)
        self.assertIn("after-sunset", k_pos)
        self.assertNotIn("winter 18:30", g_pos)
        self.assertNotIn("after-sunset", g_pos)
        self.assertNotIn("sun has already set", g_pos)
        self.assertIn("tablet held simply", g_pos)
        self.assertIn("tablet is optional", k_pos)
        self.assertNotIn("tablet is optional", g_pos)

    def test_production_reference_paragraph(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            pos = contract["positive_prompt"].lower()
            self.assertIn(PRODUCTION_REFERENCE_PARAGRAPH.lower(), pos)

    def test_validation_rejects_missing_reference_policy(self) -> None:
        bad = deepcopy(self.global_contract)
        del bad["reference_usage_policy"]
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("reference_usage_policy_missing", codes)

    def test_validation_rejects_variation_required(self) -> None:
        bad = deepcopy(self.global_contract)
        bad["reference_usage_policy"]["variation_required"] = ["new pose"]
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("variation_required_forbidden", codes)

    def test_validation_rejects_dramatic_pose_language(self) -> None:
        bad = deepcopy(self.global_contract)
        bad["positive_prompt"] = (
            bad["positive_prompt"] + " new pose and camera perspective different from reference"
        )
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("forbidden_aggressive_language_in_positive", codes)

    def test_validation_rejects_missing_hand_safety_negative(self) -> None:
        bad = deepcopy(self.global_contract)
        bad["negative_prompt"] = "no collage, not a weathercaster"
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("negative_prompt_missing_phrase", codes)

    def test_validation_rejects_same_pose_positive(self) -> None:
        bad = deepcopy(self.global_contract)
        bad["positive_prompt"] = bad["positive_prompt"] + " use the same pose as reference"
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("forbidden_copy_language_in_positive", codes)

    def test_validation_rejects_korea_daylight_dusk_language(self) -> None:
        bad = deepcopy(self.korea_contract)
        bad["positive_prompt"] = (
            bad["positive_prompt"] + " blue-gray Seoul dusk with city lights just beginning"
        )
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("korea_daylight_language_forbidden", codes)

    def test_static_policy_constants(self) -> None:
        self.assertEqual(
            REFERENCE_USAGE_POLICY["reference_role"],
            "identity_and_wardrobe_continuity_only",
        )
        self.assertEqual(
            WARDROBE_LOCK["wardrobe_role"],
            "premium_private_tech_secretary_professional",
        )
        self.assertEqual(REFERENCE_USAGE_POLICY["variation_mode"], VARIATION_MODE)


class KeysuriDailyWardrobeMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        report = _report()
        self.global_contract = report["prompt_contracts"]["keysuri_global_tech"]
        self.korea_contract = report["prompt_contracts"]["keysuri_korea_tech"]

    def test_daily_wardrobe_metadata_exists_on_both_programs(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            daily = contract.get("daily_wardrobe")
            self.assertIsInstance(daily, dict)
            for key in _DAILY_WARDROBE_METADATA_KEYS:
                self.assertIn(key, daily)

    def test_same_wardrobe_date_same_profile_and_seed(self) -> None:
        g_daily = self.global_contract["daily_wardrobe"]
        k_daily = self.korea_contract["daily_wardrobe"]
        self.assertEqual(g_daily["wardrobe_date_kst"], "2026-06-04")
        self.assertEqual(k_daily["wardrobe_date_kst"], "2026-06-04")
        self.assertEqual(g_daily["wardrobe_profile_id"], k_daily["wardrobe_profile_id"])
        self.assertEqual(g_daily["daily_wardrobe_seed"], k_daily["daily_wardrobe_seed"])
        self.assertEqual(g_daily["wardrobe_group"], "keysuri_daily")
        self.assertEqual(g_daily["resolver_version"], RESOLVER_VERSION)
        self.assertFalse(g_daily["manual_override_applied"])

    def test_daily_wardrobe_program_id_differs_by_program(self) -> None:
        self.assertEqual(
            self.global_contract["daily_wardrobe"]["program_id"],
            "keysuri_global_tech",
        )
        self.assertEqual(
            self.korea_contract["daily_wardrobe"]["program_id"],
            "keysuri_korea_tech",
        )

    def test_positive_prompt_still_uses_static_charcoal_ivory_wording(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            pos = contract["positive_prompt"].lower()
            self.assertIn("charcoal fitted suit", pos)
            self.assertIn("ivory or soft cream blouse", pos)

    def test_positive_prompt_does_not_include_resolver_prompt_snippet(self) -> None:
        for contract in (self.global_contract, self.korea_contract):
            pos = contract["positive_prompt"].lower()
            self.assertNotIn("not a lounge or glamour shoot", pos)
            self.assertNotIn("private korean ai tech secretary kee-suri identity:", pos)

    def test_include_daily_wardrobe_metadata_false_omits_field(self) -> None:
        integration = _integration()
        contract = build_keysuri_weather_visual_prompt_contract(
            "keysuri_global_tech",
            integration["visual_contexts"]["keysuri_global_tech"],
            include_daily_wardrobe_metadata=False,
        )
        self.assertNotIn("daily_wardrobe", contract)

    def test_missing_weather_date_fails_closed_for_metadata(self) -> None:
        integration = _integration()
        ctx = deepcopy(integration["visual_contexts"]["keysuri_global_tech"])
        del ctx["weather_date"]
        with self.assertRaises(ValueError) as exc:
            build_keysuri_weather_visual_prompt_contract(
                "keysuri_global_tech",
                ctx,
                include_daily_wardrobe_metadata=True,
            )
        self.assertIn("weather_date", str(exc.exception))

    def test_build_daily_wardrobe_metadata_helper(self) -> None:
        integration = _integration()
        ctx = integration["visual_contexts"]["keysuri_global_tech"]
        metadata = build_daily_wardrobe_metadata("keysuri_global_tech", ctx)
        self.assertEqual(metadata["wardrobe_date_kst"], "2026-06-04")
        self.assertEqual(metadata["wardrobe_profile_id"], "profile_01_charcoal_ivory")

    def test_no_forbidden_wardrobe_imports_in_integration_module(self) -> None:
        source = _INTEGRATION_PATH.read_text(encoding="utf-8")
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for mod in ("image_exec_suffixes", "weather_image_context"):
            self.assertFalse(any(mod in line for line in import_lines), msg=mod)
        self.assertTrue(any("keysuri_daily_wardrobe_resolver" in line for line in import_lines))


class KeysuriPromptContractNegativeTests(unittest.TestCase):
    def test_unknown_program_blocks(self) -> None:
        integration = _integration()
        ctx = integration["visual_contexts"]["keysuri_global_tech"]
        with self.assertRaises(ValueError):
            build_keysuri_weather_visual_prompt_contract("unknown", ctx)

    def test_tomorrow_blocks(self) -> None:
        integration = _integration()
        ctx = integration["visual_contexts"]["keysuri_global_tech"]
        for bad in ("tomorrow_geenee", "tomorrow_genie", "today_geenee"):
            with self.subTest(program=bad):
                with self.assertRaises(ValueError):
                    build_keysuri_weather_visual_prompt_contract(bad, ctx)

    def test_forbidden_source_mode_on_contract(self) -> None:
        integration = _integration()
        ctx = deepcopy(integration["visual_contexts"]["keysuri_global_tech"])
        ctx["source_mode"] = "automatic_live_weather_api_call"
        with self.assertRaises(ValueError):
            build_keysuri_weather_visual_prompt_contract("keysuri_global_tech", ctx)

    def test_positive_anchor_identity_blocks_validation(self) -> None:
        integration = _integration()
        contract = build_keysuri_weather_visual_prompt_contract(
            "keysuri_global_tech",
            integration["visual_contexts"]["keysuri_global_tech"],
        )
        bad = deepcopy(contract)
        bad["positive_prompt"] = "public news anchor on TV"
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
        self.assertIn("forbidden_identity_in_positive", codes)

    def test_ready_for_image_api_true_blocks_report(self) -> None:
        report = deepcopy(_report())
        report["ready_for_image_api_call"] = True
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_report(report)}
        self.assertIn("ready_for_image_api_call_invalid", codes)

    def test_side_effect_true_blocks(self) -> None:
        report = deepcopy(_report())
        report["side_effects"]["called_image_api"] = True
        codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_report(report)}
        self.assertIn("side_effect_invalid", codes)


class KeysuriPromptSecretGuardTests(unittest.TestCase):
    def test_report_no_secrets(self) -> None:
        report = _report()
        blob = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn("WEATHER_API_KEY=", blob)
        self.assertNotIn("raw_provider_payload", blob)
        neg = report["prompt_contracts"]["keysuri_global_tech"]["negative_prompt"].lower()
        self.assertIn("no tomorrow_geenee", neg)


class KeysuriPromptIntegrationScriptTests(unittest.TestCase):
    def test_build_script_runs(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/build_keysuri_weather_visual_prompt_report.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["report_status"], "pass")
        self.assertEqual(out["issue_count"], 0)
        self.assertFalse(out["ready_for_image_api_call"])
        self.assertTrue(_OUT_REPORT.is_file())


class KeysuriPromptContractsFromIntegrationTests(unittest.TestCase):
    def test_build_from_integration_result(self) -> None:
        integration = _integration()
        contracts = build_keysuri_weather_visual_prompt_contracts_from_integration_result(
            integration
        )
        self.assertEqual(set(contracts.keys()), set(KEYSURI_PROGRAMS))
        for pid, contract in contracts.items():
            self.assertEqual(validate_keysuri_weather_visual_prompt_contract(contract), [])
            self.assertEqual(contract["program_id"], pid)

    def test_forbidden_source_in_validation(self) -> None:
        for mode in ("scheduler_invoked_weather_call", "production_auto_call"):
            if mode in FORBIDDEN_SOURCE_MODES:
                contract = _report()["prompt_contracts"]["keysuri_global_tech"]
                bad = deepcopy(contract)
                bad["source_mode"] = mode
                codes = {i["code"] for i in validate_keysuri_weather_visual_prompt_contract(bad)}
                self.assertIn("source_mode_invalid", codes)


if __name__ == "__main__":
    unittest.main()
