"""Tests for Kee-Suri weather visual prompt integration (offline, no image API)."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_visual_context import FORBIDDEN_SOURCE_MODES
from keysuri_weather_binding_integration import (
    KEYSURI_PROGRAMS,
    build_keysuri_weather_binding_integration_report,
)
from keysuri_weather_visual_prompt_integration import (
    HAND_POLICY,
    POSE_POLICY,
    PRODUCTION_REFERENCE_PARAGRAPH,
    PROMPT_CONTRACT_TYPE,
    REFERENCE_USAGE_POLICY,
    REPORT_TYPE,
    SOURCE_MODE,
    VARIATION_MODE,
    WARDROBE_LOCK,
    WEATHER_POLICY,
    build_keysuri_weather_visual_prompt_contract,
    build_keysuri_weather_visual_prompt_contracts_from_integration_result,
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
    validate_keysuri_weather_visual_prompt_contract,
    validate_keysuri_weather_visual_prompt_report,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_REPORT = (
    _REPO
    / "output"
    / "keysuri_preview"
    / "weather_canary"
    / "keysuri_weather_visual_prompt_report.json"
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
        self.assertIn("no pointing", pos)
        self.assertIn("weather affects window light and atmosphere only", pos)
        self.assertIn("daytime", pos)
        self.assertIn("cloudy", pos)
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

    def test_korea_positive_prompt(self) -> None:
        pos = self.contract["positive_prompt"].lower()
        self.assertIn("same person as the reference", pos)
        self.assertIn("early evening", pos)
        self.assertIn("weather affects window light and atmosphere only", pos)
        self.assertNotIn("new pose and camera perspective", pos)
        self.assertNotIn("weathercaster", pos)

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
