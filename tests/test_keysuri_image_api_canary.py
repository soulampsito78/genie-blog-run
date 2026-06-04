"""Tests for Kee-Suri manual image API canary (mock-only — no live API)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from keysuri_image_api_canary_client import (
    DEFAULT_LOCK_PATH,
    DEFAULT_OUTPUT_DIR,
    REPORT_TYPE,
    build_keysuri_image_api_canary_report,
    parse_bool_manual_approval,
    run_keysuri_image_api_canary,
    sanitize_keysuri_image_api_canary_report,
    validate_keysuri_image_api_canary_report,
)
from keysuri_image_provider_contract import OUTPUT_IMAGES_DIR

_REPO = Path(__file__).resolve().parent.parent
_LOCK = _REPO / DEFAULT_LOCK_PATH
_OUT_REPORT = _REPO / "output" / "keysuri_preview" / "image_canary" / "keysuri_image_api_canary_report.json"
_SCRIPT = _REPO / "scripts" / "run_keysuri_image_api_canary.py"


def _mock_generate_ok(output_path: Path, **kwargs: object) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"MOCK_JPEG_MARKER")
    return output_path


def _mock_generate_fail(output_path: Path, **kwargs: object) -> Path:
    raise RuntimeError("mock generation failure")


class ParseBoolManualApprovalTests(unittest.TestCase):
    def test_truthy_values(self) -> None:
        for val in (True, "1", "true", "YES", "on"):
            self.assertTrue(parse_bool_manual_approval(val))

    def test_falsy_values(self) -> None:
        for val in (False, None, "", "0", "no"):
            self.assertFalse(parse_bool_manual_approval(val))


class KeysuriImageApiCanaryDefaultTests(unittest.TestCase):
    def test_no_approval_blocked(self) -> None:
        report = run_keysuri_image_api_canary()
        self.assertEqual(report["canary_status"], "blocked_no_manual_approval")
        self.assertEqual(report["request_count"], 0)
        self.assertFalse(report["side_effects"]["called_image_api"])
        self.assertFalse(report["side_effects"]["generated_image"])
        self.assertEqual(report["image_api_call_status"], "not_called")
        self.assertEqual(report["image_generation_status"], "not_generated")
        self.assertEqual(validate_keysuri_image_api_canary_report(report), [])

    def test_approval_no_program_blocked(self) -> None:
        report = run_keysuri_image_api_canary(manual_approval=True)
        self.assertEqual(report["canary_status"], "blocked_missing_program")
        self.assertEqual(report["request_count"], 0)

    def test_no_program_no_approval_first(self) -> None:
        report = run_keysuri_image_api_canary(program_id="keysuri_global_tech")
        self.assertEqual(report["canary_status"], "blocked_no_manual_approval")


class KeysuriImageApiCanaryProgramTests(unittest.TestCase):
    def test_forbidden_programs(self) -> None:
        for bad in ("today_geenee", "tomorrow_geenee", "tomorrow_genie", "unknown_slot"):
            report = run_keysuri_image_api_canary(
                program_id=bad,
                manual_approval=True,
            )
            self.assertIn(
                report["canary_status"],
                ("blocked_forbidden_program", "blocked_invalid_program"),
            )
            self.assertEqual(report["request_count"], 0)

    def test_multiple_program_rejected(self) -> None:
        report = run_keysuri_image_api_canary(
            program_id="keysuri_global_tech,keysuri_korea_tech",
            manual_approval=True,
        )
        self.assertEqual(report["request_count"], 0)
        issues = report.get("issues") or []
        self.assertTrue(any(i.get("code") == "multiple_programs_rejected" for i in issues))


class KeysuriImageApiCanaryDryRunTests(unittest.TestCase):
    def test_dry_run_ready_with_env(self) -> None:
        env = {
            "GENIE_VERTEX_PROJECT_ID": "test-project",
            "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            report = run_keysuri_image_api_canary(
                program_id="keysuri_global_tech",
                manual_approval=True,
                dry_run=True,
            )
        self.assertEqual(report["canary_status"], "dry_run_ready")
        self.assertEqual(report["request_count"], 0)
        self.assertFalse(report["side_effects"]["called_image_api"])
        self.assertIsNotNone(report.get("prompt_source"))
        self.assertEqual(report["prompt_source"]["program_id"], "keysuri_global_tech")

    def test_missing_env_blocks_call(self) -> None:
        env = {k: "" for k in ("GENIE_VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")}
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("GENIE_VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT"):
                os.environ.pop(key, None)
            report = run_keysuri_image_api_canary(
                program_id="keysuri_korea_tech",
                manual_approval=True,
                dry_run=False,
            )
        self.assertEqual(report["canary_status"], "blocked_missing_image_env")
        self.assertEqual(report["request_count"], 0)


class KeysuriImageApiCanaryMockCallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = mock.patch.dict(
            os.environ,
            {"GENIE_VERTEX_PROJECT_ID": "test-project-mock"},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_mock_called_once_global(self) -> None:
        calls: list[Path] = []

        def _track(output_path: Path, **kwargs: object) -> Path:
            calls.append(output_path)
            return _mock_generate_ok(output_path, **kwargs)

        report = run_keysuri_image_api_canary(
            program_id="keysuri_global_tech",
            manual_approval=True,
            dry_run=False,
            _generate_image_fn=_track,
        )
        self.assertEqual(report["canary_status"], "called_once")
        self.assertEqual(report["request_count"], 1)
        self.assertTrue(report["side_effects"]["called_image_api"])
        self.assertTrue(report["side_effects"]["generated_image"])
        self.assertTrue(report["side_effects"]["called_gemini"])
        self.assertEqual(report["image_api_call_status"], "called_once")
        out = str(report.get("output_image_path") or "")
        self.assertTrue(out.startswith(OUTPUT_IMAGES_DIR))
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["today_geenee_in_canary"])
        self.assertFalse(report["tomorrow_geenee_in_canary"])
        safe = sanitize_keysuri_image_api_canary_report(report)
        self.assertEqual(validate_keysuri_image_api_canary_report(safe), [])

    def test_mock_called_once_korea(self) -> None:
        report = run_keysuri_image_api_canary(
            program_id="keysuri_korea_tech",
            manual_approval=True,
            dry_run=False,
            _generate_image_fn=_mock_generate_ok,
        )
        self.assertEqual(report["canary_status"], "called_once")
        self.assertIn("korea", str(report.get("output_image_path") or ""))

    def test_mock_api_error(self) -> None:
        report = run_keysuri_image_api_canary(
            program_id="keysuri_global_tech",
            manual_approval=True,
            dry_run=False,
            _generate_image_fn=_mock_generate_fail,
        )
        self.assertEqual(report["canary_status"], "api_error")
        self.assertEqual(report["request_count"], 1)
        self.assertTrue(report["side_effects"]["called_image_api"])
        self.assertFalse(report["side_effects"]["generated_image"])
        self.assertFalse(report["raw_provider_payload_saved"])


class KeysuriImageApiCanaryReportValidationTests(unittest.TestCase):
    def test_rejects_invalid_request_count(self) -> None:
        bad = run_keysuri_image_api_canary()
        bad["request_count"] = 2
        issues = validate_keysuri_image_api_canary_report(bad)
        self.assertTrue(any(i.get("code") == "request_count_invalid" for i in issues))

    def test_rejects_output_outside_dir(self) -> None:
        bad = run_keysuri_image_api_canary()
        bad["canary_status"] = "called_once"
        bad["request_count"] = 1
        bad["output_image_path"] = "assets/keysuri/x.jpg"
        bad["image_api_call_status"] = "called_once"
        issues = validate_keysuri_image_api_canary_report(bad)
        self.assertTrue(issues)

    def test_rejects_secrets_in_report(self) -> None:
        bad = run_keysuri_image_api_canary()
        bad["notes"] = "Bearer secret-token"
        issues = validate_keysuri_image_api_canary_report(bad)
        self.assertTrue(any("forbidden" in i.get("code", "") for i in issues))


class KeysuriImageApiCanaryScriptTests(unittest.TestCase):
    def test_script_no_args_blocked(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["request_count"], 0)
        self.assertIn(out["canary_status"], ("blocked_no_manual_approval", "blocked_missing_program"))
        self.assertTrue(_OUT_REPORT.is_file())

    def test_script_check_env(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--check-env"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertIn("env_presence", out)

    def test_script_dry_run_no_api(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT),
                "--program",
                "keysuri_global_tech",
                "--dry-run",
                "--manual-approval",
            ],
            env={**os.environ, "GENIE_VERTEX_PROJECT_ID": "test-dry-run"},
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["canary_status"], "dry_run_ready")
        self.assertEqual(out["request_count"], 0)


if __name__ == "__main__":
    unittest.main()
