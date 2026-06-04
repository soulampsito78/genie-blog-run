"""Tests for Kee-Suri manual opt-in canary runner (R5B-II mock-only)."""
from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import keysuri_manual_opt_in_canary_runner as runner
from keysuri_manual_opt_in_canary_runner import (
    BLOCKED_ENV_CLI_MISMATCH,
    BLOCKED_INCOMPLETE_WARDROBE_APPROVAL,
    BLOCKED_NO_WARDROBE_APPROVAL,
    BLOCKED_PREFLIGHT_FAILED,
    LIVE_CALL_NOT_ENABLED_IN_R5B_II,
    PREFLIGHT_ONLY_PASS,
    DRY_RUN_READY,
    build_opt_in_prompt_source,
    main,
    parse_manual_canary_approval_from_env,
    run_keysuri_manual_opt_in_canary,
)
from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, run_keysuri_image_api_canary

_REPO = Path(__file__).resolve().parent.parent
_LOCK = _REPO / DEFAULT_LOCK_PATH
_RUNNER_PATH = _REPO / "keysuri_manual_opt_in_canary_runner.py"
_SCRIPT_PATH = _REPO / "scripts" / "run_keysuri_manual_opt_in_canary.py"
_OLD_SCRIPT = _REPO / "scripts" / "run_keysuri_image_api_canary.py"

_PROFILE_01 = "profile_01_charcoal_ivory"
_SEED_2026_06_04 = "keysuri_daily|2026-06-04|v1|profile_01_charcoal_ivory"


def _valid_env(**overrides: str) -> dict[str, str]:
    base = {
        "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "1",
        "GENIE_KEYSURI_APPROVED_WARDROBE_DATE_KST": "2026-06-04",
        "GENIE_KEYSURI_APPROVED_PROGRAM_ID": "keysuri_global_tech",
        "GENIE_KEYSURI_APPROVED_PROFILE_ID": _PROFILE_01,
        "GENIE_KEYSURI_APPROVED_SEED": _SEED_2026_06_04,
        "GENIE_KEYSURI_APPROVED_OPERATOR_REF": "test-ops",
        "GENIE_VERTEX_PROJECT_ID": "test-project",
    }
    base.update(overrides)
    return base


class KeysuriManualOptInApprovalParseTests(unittest.TestCase):
    def test_no_master_approval_blocks(self) -> None:
        approval, issues = parse_manual_canary_approval_from_env(environ={})
        self.assertIsNone(approval)
        self.assertTrue(issues)

    def test_missing_fields_block(self) -> None:
        approval, issues = parse_manual_canary_approval_from_env(
            environ={"GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "1"}
        )
        self.assertIsNone(approval)
        self.assertTrue(any(BLOCKED_INCOMPLETE_WARDROBE_APPROVAL in item for item in issues))

    def test_multi_program_env_rejected(self) -> None:
        env = _valid_env(GENIE_KEYSURI_APPROVED_PROGRAM_ID="keysuri_global_tech,keysuri_korea_tech")
        approval, issues = parse_manual_canary_approval_from_env(environ=env)
        self.assertIsNone(approval)
        self.assertTrue(issues)


class KeysuriManualOptInRunnerBlockTests(unittest.TestCase):
    def test_no_approval_blocks_before_canary_client(self) -> None:
        with mock.patch.object(runner, "run_keysuri_image_api_canary") as canary_mock:
            result = run_keysuri_manual_opt_in_canary(
                check_preflight_only=True,
                environ={},
            )
        canary_mock.assert_not_called()
        self.assertEqual(result.runner_status, BLOCKED_NO_WARDROBE_APPROVAL)

    def test_wrong_profile_blocks_before_canary_client(self) -> None:
        env = _valid_env(GENIE_KEYSURI_APPROVED_PROFILE_ID="profile_02_navy_cream")
        with mock.patch.object(runner, "run_keysuri_image_api_canary") as canary_mock:
            result = run_keysuri_manual_opt_in_canary(
                check_preflight_only=True,
                environ=env,
            )
        canary_mock.assert_not_called()
        self.assertEqual(result.runner_status, BLOCKED_PREFLIGHT_FAILED)

    def test_wrong_seed_blocks_before_canary_client(self) -> None:
        env = _valid_env(GENIE_KEYSURI_APPROVED_SEED="keysuri_daily|2026-06-04|v1|wrong")
        with mock.patch.object(runner, "run_keysuri_image_api_canary") as canary_mock:
            result = run_keysuri_manual_opt_in_canary(
                check_preflight_only=True,
                environ=env,
            )
        canary_mock.assert_not_called()
        self.assertEqual(result.runner_status, BLOCKED_PREFLIGHT_FAILED)

    def test_env_cli_mismatch_blocks(self) -> None:
        env = _valid_env()
        result = run_keysuri_manual_opt_in_canary(
            wardrobe_date_kst="2026-06-05",
            program_id="keysuri_global_tech",
            check_preflight_only=True,
            environ=env,
        )
        self.assertEqual(result.runner_status, BLOCKED_ENV_CLI_MISMATCH)

    def test_live_call_not_enabled_without_dry_run(self) -> None:
        env = _valid_env()
        with mock.patch.object(runner, "run_keysuri_image_api_canary") as canary_mock:
            result = run_keysuri_manual_opt_in_canary(environ=env)
        canary_mock.assert_not_called()
        self.assertEqual(result.runner_status, LIVE_CALL_NOT_ENABLED_IN_R5B_II)


class KeysuriManualOptInRunnerSuccessTests(unittest.TestCase):
    def test_check_preflight_only_success_without_canary_client(self) -> None:
        env = _valid_env()
        with mock.patch.object(runner, "run_keysuri_image_api_canary") as canary_mock:
            result = run_keysuri_manual_opt_in_canary(
                check_preflight_only=True,
                environ=env,
            )
        canary_mock.assert_not_called()
        self.assertEqual(result.runner_status, PREFLIGHT_ONLY_PASS)
        self.assertEqual(result.preflight_status, "PREFLIGHT_PASS_FOR_ONE_MANUAL_CALL")
        self.assertIn("No image API was called in R5B-II implementation mode.", result.audit_text)

    def test_dry_run_reaches_canary_client_once(self) -> None:
        env = _valid_env()
        with mock.patch.object(
            runner,
            "run_keysuri_image_api_canary",
            wraps=run_keysuri_image_api_canary,
        ) as canary_mock:
            result = run_keysuri_manual_opt_in_canary(
                dry_run=True,
                environ=env,
            )
        canary_mock.assert_called_once()
        self.assertEqual(result.runner_status, DRY_RUN_READY)
        self.assertEqual(result.canary_report["request_count"], 0)
        self.assertFalse(result.canary_report["side_effects"]["called_image_api"])
        pos = result.canary_report["prompt_source"]["positive_prompt"].lower()
        self.assertIn("fitted premium business silhouette", pos)
        self.assertNotIn("not a lounge or glamour shoot", pos)

    def test_mock_generate_calls_once_and_no_retry(self) -> None:
        env = _valid_env()
        calls: list[Path] = []

        def _mock_generate(output_path: Path, **kwargs: object) -> Path:
            calls.append(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"MOCK")
            return output_path

        result = run_keysuri_manual_opt_in_canary(
            environ=env,
            _generate_image_fn=_mock_generate,
            _allow_mock_generate_for_tests=True,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.canary_report["request_count"], 1)
        self.assertEqual(result.canary_report["canary_status"], "called_once")

    def test_mock_failure_does_not_retry(self) -> None:
        env = _valid_env()
        calls = 0

        def _mock_fail(output_path: Path, **kwargs: object) -> Path:
            nonlocal calls
            calls += 1
            raise RuntimeError("mock failure")

        with mock.patch.object(runner, "run_keysuri_image_api_canary", wraps=run_keysuri_image_api_canary):
            result = run_keysuri_manual_opt_in_canary(
                environ=env,
                _generate_image_fn=_mock_fail,
                _allow_mock_generate_for_tests=True,
            )
        self.assertEqual(calls, 1)
        self.assertEqual(result.canary_report["canary_status"], "api_error")
        self.assertEqual(result.canary_report["request_count"], 1)


class KeysuriManualOptInPromptSourceTests(unittest.TestCase):
    def test_opt_in_prompt_source_profile_01_2026_06_04(self) -> None:
        source = build_opt_in_prompt_source(
            lock_path=_LOCK,
            program_id="keysuri_global_tech",
            wardrobe_date_kst="2026-06-04",
        )
        pos = source["positive_prompt"].lower()
        self.assertEqual(source["wardrobe_profile_id"], _PROFILE_01)
        self.assertEqual(source["daily_wardrobe_seed"], _SEED_2026_06_04)
        self.assertTrue(source["wardrobe_prompt_injected"])
        self.assertIn("charcoal fitted suit with ivory blouse", pos)
        self.assertIn("fitted premium business silhouette", pos)
        self.assertNotIn("not a lounge or glamour shoot", pos)


class KeysuriManualOptInRunnerSafetyTests(unittest.TestCase):
    def test_no_forbidden_imports(self) -> None:
        source = _RUNNER_PATH.read_text(encoding="utf-8")
        forbidden = (
            "google.cloud",
            "vertex",
            "gemini",
            "today_geenee",
            "tomorrow_geenee",
        )
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for mod in forbidden:
            with self.subTest(module=mod):
                self.assertFalse(any(mod in line for line in import_lines))

    def test_no_git_commands_in_source(self) -> None:
        source = _RUNNER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("git add", source)
        self.assertNotIn("subprocess", source)

    def test_script_exists_and_default_blocks(self) -> None:
        self.assertTrue(_SCRIPT_PATH.is_file())
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([])
        self.assertNotEqual(code, 0)
        self.assertIn(BLOCKED_NO_WARDROBE_APPROVAL, buf.getvalue())

    def test_existing_default_canary_script_unchanged(self) -> None:
        old = _OLD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("run_keysuri_image_api_canary", old)
        self.assertNotIn("manual_opt_in", old)


class KeysuriImageApiCanaryOverrideTests(unittest.TestCase):
    def test_default_path_unchanged_without_override(self) -> None:
        env = {
            "GENIE_VERTEX_PROJECT_ID": "test-project",
            "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            default_report = run_keysuri_image_api_canary(
                program_id="keysuri_global_tech",
                manual_approval=True,
                dry_run=True,
            )
        pos = default_report["prompt_source"]["positive_prompt"].lower()
        self.assertNotIn("fitted premium business silhouette", pos)
        self.assertFalse(default_report.get("wardrobe_prompt_injected"))

    def test_prompt_source_override_used_for_dry_run(self) -> None:
        override = build_opt_in_prompt_source(
            lock_path=_LOCK,
            program_id="keysuri_global_tech",
            wardrobe_date_kst="2026-06-04",
        )
        env = {
            "GENIE_VERTEX_PROJECT_ID": "test-project",
            "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            report = run_keysuri_image_api_canary(
                program_id="keysuri_global_tech",
                manual_approval=True,
                dry_run=True,
                prompt_source_override=override,
            )
        self.assertEqual(report["canary_status"], "dry_run_ready")
        self.assertTrue(report["wardrobe_prompt_injected"])
        self.assertIn("fitted premium business silhouette", report["prompt_source"]["positive_prompt"].lower())


if __name__ == "__main__":
    unittest.main()
