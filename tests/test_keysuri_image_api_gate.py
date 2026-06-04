"""Tests for Kee-Suri image API controlled dry-run gate (no image API calls)."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_image_api_gate import (
    GATE_REPORT_TYPE,
    KEYSURI_PROGRAMS,
    build_keysuri_image_api_gate_entry,
    build_keysuri_image_api_gate_report,
    build_keysuri_image_api_gate_report_from_canary_lock,
    validate_keysuri_image_api_gate_entry,
    validate_keysuri_image_api_gate_report,
)
from keysuri_weather_visual_prompt_integration import (
    REPORT_TYPE as PROMPT_REPORT_TYPE,
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_REPORT = _REPO / "output" / "keysuri_preview" / "weather_canary" / "keysuri_image_api_gate_report.json"


def _prompt_report() -> dict:
    return build_keysuri_weather_visual_prompt_report_from_canary_lock(str(_LOCK_PATH))


def _gate_report() -> dict:
    return build_keysuri_image_api_gate_report_from_canary_lock(str(_LOCK_PATH), manual_approval=False)


class KeysuriImageApiGateReportTests(unittest.TestCase):
    def test_report_pass_default_manual_approval(self) -> None:
        report = _gate_report()
        self.assertEqual(report["report_status"], "pass")
        self.assertEqual(report["report_type"], GATE_REPORT_TYPE)
        self.assertEqual(report["source_prompt_report_type"], PROMPT_REPORT_TYPE)
        self.assertEqual(report["runtime_binding_status"], "design_ready_not_wired")
        self.assertTrue(report["manual_approval_required"])
        self.assertFalse(report["manual_approval_present"])
        self.assertFalse(report["ready_for_image_api_call"])
        self.assertFalse(report["image_api_call_allowed"])
        self.assertEqual(report["image_api_call_status"], "not_called")
        self.assertFalse(report["ready_for_scheduler"])
        self.assertFalse(report["ready_for_production_auto_call"])
        self.assertFalse(any(report["side_effects"].values()))
        self.assertEqual(report["issues"], [])
        self.assertEqual(set(report["gate_entries"].keys()), set(KEYSURI_PROGRAMS))

    def test_no_today_or_tomorrow_entries(self) -> None:
        keys = set(_gate_report()["gate_entries"].keys())
        self.assertNotIn("today_geenee", keys)
        for bad in ("tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            self.assertNotIn(bad, keys)


class KeysuriImageApiGateEntryTests(unittest.TestCase):
    def test_entry_checks_default(self) -> None:
        report = _gate_report()
        for pid in KEYSURI_PROGRAMS:
            entry = report["gate_entries"][pid]
            self.assertTrue(entry["validation_passed"])
            self.assertTrue(entry["identity_checked"])
            self.assertTrue(entry["weather_usage_checked"])
            self.assertTrue(entry["safety_constraints_checked"])
            self.assertTrue(entry["secret_guard_checked"])
            self.assertTrue(entry["retirement_guard_checked"])
            self.assertTrue(entry["manual_approval_required"])
            self.assertFalse(entry["manual_approval_present"])
            self.assertFalse(entry["ready_for_image_api_call"])
            self.assertFalse(entry["image_api_call_allowed"])
            self.assertEqual(entry["image_api_call_status"], "not_called")
            self.assertEqual(entry["blocked_reasons"], [])
            snap = entry["prompt_contract_snapshot"]
            self.assertIn("positive_prompt", snap)
            self.assertIn("negative_prompt", snap)
            self.assertIn("safety_constraints", snap)
            self.assertFalse(any(entry["side_effects"].values()))


class KeysuriImageApiManualApprovalTests(unittest.TestCase):
    def test_manual_approval_false(self) -> None:
        report = build_keysuri_image_api_gate_report_from_canary_lock(
            str(_LOCK_PATH),
            manual_approval=False,
        )
        entry = report["gate_entries"]["keysuri_global_tech"]
        self.assertTrue(entry["validation_passed"])
        self.assertFalse(entry["image_api_call_allowed"])
        self.assertFalse(entry["side_effects"]["called_image_api"])

    def test_manual_approval_true_model_only(self) -> None:
        report = build_keysuri_image_api_gate_report_from_canary_lock(
            str(_LOCK_PATH),
            manual_approval=True,
        )
        entry = report["gate_entries"]["keysuri_global_tech"]
        self.assertTrue(entry["validation_passed"])
        self.assertTrue(entry["manual_approval_present"])
        self.assertTrue(entry["image_api_call_allowed"])
        self.assertTrue(entry["ready_for_image_api_call"])
        self.assertEqual(entry["image_api_call_status"], "not_called")
        self.assertFalse(entry["side_effects"]["called_image_api"])
        self.assertTrue(report["image_api_call_allowed"])
        self.assertTrue(report["ready_for_image_api_call"])


class KeysuriImageApiGateNegativeTests(unittest.TestCase):
    def test_unknown_program_blocks(self) -> None:
        contract = _prompt_report()["prompt_contracts"]["keysuri_global_tech"]
        with self.assertRaises(ValueError):
            build_keysuri_image_api_gate_entry("unknown", contract)

    def test_tomorrow_blocks(self) -> None:
        contract = _prompt_report()["prompt_contracts"]["keysuri_global_tech"]
        for bad in ("today_geenee", "tomorrow_geenee", "tomorrow_genie"):
            with self.subTest(program=bad):
                with self.assertRaises(ValueError):
                    build_keysuri_image_api_gate_entry(bad, contract)

    def test_safety_constraint_false_blocks(self) -> None:
        contract = deepcopy(_prompt_report()["prompt_contracts"]["keysuri_global_tech"])
        contract["safety_constraints"]["no_collage"] = False
        entry = build_keysuri_image_api_gate_entry("keysuri_global_tech", contract)
        self.assertFalse(entry["validation_passed"])
        self.assertFalse(entry["image_api_call_allowed"])
        self.assertTrue(
            any("safety_constraint" in r for r in entry["blocked_reasons"]),
            msg=entry["blocked_reasons"],
        )

    def test_positive_anchor_identity_blocks(self) -> None:
        contract = deepcopy(_prompt_report()["prompt_contracts"]["keysuri_korea_tech"])
        contract["positive_prompt"] = "weathercaster presenting the news"
        entry = build_keysuri_image_api_gate_entry("keysuri_korea_tech", contract)
        self.assertFalse(entry["validation_passed"])
        self.assertFalse(entry["image_api_call_allowed"])

    def test_appid_blocks(self) -> None:
        contract = deepcopy(_prompt_report()["prompt_contracts"]["keysuri_global_tech"])
        contract["positive_prompt"] += " appid=secret123"
        entry = build_keysuri_image_api_gate_entry("keysuri_global_tech", contract)
        self.assertFalse(entry["validation_passed"])
        self.assertFalse(entry["secret_guard_checked"])

    def test_called_image_api_true_blocks_validation(self) -> None:
        contract = deepcopy(_prompt_report()["prompt_contracts"]["keysuri_global_tech"])
        contract["side_effects"]["called_image_api"] = True
        entry = build_keysuri_image_api_gate_entry("keysuri_global_tech", contract)
        self.assertFalse(entry["validation_passed"])

    def test_report_ready_for_scheduler_true_blocks(self) -> None:
        report = deepcopy(_gate_report())
        report["ready_for_scheduler"] = True
        codes = {i["code"] for i in validate_keysuri_image_api_gate_report(report)}
        self.assertIn("ready_for_scheduler_invalid", codes)


class KeysuriImageApiGateSecretGuardTests(unittest.TestCase):
    def test_report_no_secrets(self) -> None:
        blob = json.dumps(_gate_report(), ensure_ascii=False)
        self.assertNotIn("appid=", blob)
        self.assertNotIn("WEATHER_API_KEY=", blob)
        self.assertNotIn("raw_provider_payload", blob)
        self.assertNotIn("Authorization:", blob)


class KeysuriImageApiGateScriptTests(unittest.TestCase):
    def test_build_script_runs(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/build_keysuri_image_api_gate_report.py"],
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
        self.assertFalse(out["image_api_call_allowed"])
        self.assertTrue(_OUT_REPORT.is_file())


class KeysuriImageApiGateReportBuilderTests(unittest.TestCase):
    def test_build_from_prompt_report(self) -> None:
        prompt_report = _prompt_report()
        report = build_keysuri_image_api_gate_report(prompt_report, manual_approval=False)
        self.assertEqual(validate_keysuri_image_api_gate_report(report), [])


if __name__ == "__main__":
    unittest.main()
