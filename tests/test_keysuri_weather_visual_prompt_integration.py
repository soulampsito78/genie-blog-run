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
    PROMPT_CONTRACT_TYPE,
    REPORT_TYPE,
    SOURCE_MODE,
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

    def test_global_positive_prompt(self) -> None:
        pos = self.contract["positive_prompt"].lower()
        self.assertIn("private", pos)
        self.assertIn("premium", pos)
        self.assertIn("office", pos)
        self.assertIn("cloudy", pos)
        self.assertIn("daytime", pos)
        self.assertNotIn("weathercaster", pos)
        self.assertNotIn("news anchor", pos)
        self.assertNotIn("announcer", pos)

    def test_global_negative_and_safety(self) -> None:
        neg = self.contract["negative_prompt"].lower()
        self.assertIn("no collage", neg)
        self.assertIn("no text overlay", neg)
        self.assertIn("no weathercaster", neg)
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
        self.assertIn("early evening", pos)
        self.assertIn("korean tech", pos)
        self.assertIn("cloudy", pos)
        self.assertNotIn("broadcaster", pos)
        self.assertNotIn("weathercaster", pos)

    def test_identity_block(self) -> None:
        ident = self.contract["identity"]
        self.assertEqual(ident["persona_name"], "테크 비서 키수리")
        self.assertEqual(ident["role"], "private_tech_secretary")
        self.assertEqual(
            self.contract["weather_visual_usage"]["usage_type"],
            "visual_realism_only",
        )


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
        blob = json.dumps(_report(), ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn("WEATHER_API_KEY=", blob)
        self.assertNotIn("raw_provider_payload", blob)
        self.assertNotIn("Tomorrow_Geenee", blob)


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
