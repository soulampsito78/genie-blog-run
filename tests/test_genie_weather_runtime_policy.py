"""Tests for GENIE weather runtime policy and sanitized canary lock."""
from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from genie_weather_runtime_policy import (
    build_genie_weather_env_binding_policy,
    build_genie_weather_runtime_readiness_summary,
    load_genie_weather_canary_lock_fixture,
    validate_genie_weather_canary_lock,
)

_REPO = Path(__file__).resolve().parent.parent
_LOCK_PATH = _REPO / "ops" / "feeds" / "genie_weather_live_canary_lock_2026-06-04.sample.json"
_OUT_REPORT = _REPO / "output" / "keysuri_preview" / "weather_canary" / "weather_runtime_readiness_summary.json"


def _lock() -> dict:
    return load_genie_weather_canary_lock_fixture(str(_LOCK_PATH))


class GenieWeatherEnvPolicyTests(unittest.TestCase):
    def test_canonical_provider_and_key_env(self) -> None:
        policy = build_genie_weather_env_binding_policy()
        self.assertEqual(policy["provider"]["canonical_provider"], "openweather")
        self.assertEqual(policy["canonical_env"]["GENIE_WEATHER_PROVIDER"], "openweather")
        self.assertIn("openweather", policy["provider"]["supported_providers"])
        self.assertIn("weatherapi", policy["provider"]["implemented_canary_providers"])

    def test_precedence_and_blocking_policy(self) -> None:
        policy = build_genie_weather_env_binding_policy()
        prec = " ".join(policy["precedence"]).lower()
        self.assertIn("weather_api_key", prec)
        self.assertIn("blocked_missing_weather_env", prec)
        self.assertIn("blocked_unsupported_provider", prec)

    def test_local_policy_forbids_committed_secrets(self) -> None:
        local = build_genie_weather_env_binding_policy()["local_policy"]
        self.assertTrue(local["keys_must_not_be_committed"])
        self.assertTrue(local["dotenv_files_must_not_be_staged"])

    def test_cloud_run_future_policy(self) -> None:
        cr = build_genie_weather_env_binding_policy()["cloud_run_future_policy"]
        self.assertTrue(cr["use_secret_manager_or_secure_env_injection"])
        self.assertTrue(cr["do_not_commit_key_into_yaml"])

    def test_scheduler_flags_remain_false(self) -> None:
        sched = build_genie_weather_env_binding_policy()["scheduler_policy"]
        self.assertFalse(sched["ready_for_scheduler"])
        self.assertFalse(sched["ready_for_production_auto_call"])


class GenieWeatherCanaryLockValidationTests(unittest.TestCase):
    def test_sanitized_lock_fixture_passes(self) -> None:
        self.assertEqual(validate_genie_weather_canary_lock(_lock()), [])

    def test_lock_type_required(self) -> None:
        bad = deepcopy(_lock())
        bad["lock_type"] = "invalid"
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("lock_type_invalid", codes)

    def test_canary_status_must_be_pass(self) -> None:
        bad = deepcopy(_lock())
        bad["canary_status"] = "blocked"
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("canary_status_invalid", codes)

    def test_request_count_must_be_one(self) -> None:
        bad = deepcopy(_lock())
        bad["request_count"] = 0
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("request_count_invalid", codes)

    def test_location_must_be_seoul(self) -> None:
        bad = deepcopy(_lock())
        bad["location"] = "Busan"
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("location_invalid", codes)

    def test_consumers_required(self) -> None:
        bad = deepcopy(_lock())
        bad["consumer_contexts_built"] = ["today_geenee"]
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("consumer_missing", codes)

    def test_secrets_and_raw_payload_flags(self) -> None:
        lock = _lock()
        self.assertFalse(lock["secrets_exposed"])
        self.assertFalse(lock["raw_provider_payload_saved"])

    def test_runtime_side_effects(self) -> None:
        side = _lock()["runtime_side_effects"]
        self.assertTrue(side["called_weather_api"])
        self.assertFalse(side["called_gemini"])
        self.assertFalse(side["called_image_api"])
        self.assertFalse(side["fetched_live_news"])
        self.assertFalse(side["sent_email"])
        self.assertFalse(side["published_naver"])
        self.assertFalse(side["changed_scheduler"])

    def test_operational_status(self) -> None:
        self.assertEqual(_lock()["operational_status"], "review_required")


class GenieWeatherCanaryLockGuardTests(unittest.TestCase):
    def test_fixture_no_api_key_patterns(self) -> None:
        blob = json.dumps(_lock())
        self.assertNotIn("appid=", blob)
        self.assertNotIn('"raw_provider_payload":', blob)
        self.assertIn("raw_provider_payload_saved", blob)

    def test_fixture_no_forbidden_identity_or_retired(self) -> None:
        blob = json.dumps(_lock(), ensure_ascii=False)
        for bad in ("테크 앵커", "뉴스 앵커", "아나운서", "Tomorrow_Geenee", "tomorrow_genie"):
            self.assertNotIn(bad, blob)
        self.assertNotRegex(blob, r"\b18:00\b")

    def test_bad_lock_with_appid_fails(self) -> None:
        bad = deepcopy(_lock())
        bad["notes"] = "appid=secret123"
        codes = {i["code"] for i in validate_genie_weather_canary_lock(bad)}
        self.assertIn("forbidden_secret_or_raw_payload", codes)


class GenieWeatherReadinessSummaryTests(unittest.TestCase):
    def test_with_pass_lock(self) -> None:
        summary = build_genie_weather_runtime_readiness_summary(_lock())
        self.assertEqual(summary["weather_runtime_status"], "canary_passed")
        self.assertTrue(summary["canonical_provider_confirmed"])
        self.assertTrue(summary["weather_canary_passed"])
        self.assertTrue(summary["ready_for_runtime_binding_plan"])
        self.assertFalse(summary["ready_for_scheduler"])
        self.assertFalse(summary["ready_for_production_auto_call"])
        self.assertEqual(
            set(summary["consumer_contexts_confirmed"]),
            {"today_geenee", "keysuri_global_tech", "keysuri_korea_tech"},
        )

    def test_without_lock(self) -> None:
        summary = build_genie_weather_runtime_readiness_summary(None)
        self.assertEqual(summary["weather_runtime_status"], "canary_not_run")
        self.assertFalse(summary["ready_for_runtime_binding_plan"])


class GenieWeatherCanaryLockScriptTests(unittest.TestCase):
    def test_check_script_runs(self) -> None:
        proc = subprocess.run(
            ["python3", "scripts/check_genie_weather_canary_lock.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["weather_runtime_status"], "canary_passed")
        self.assertTrue(out["weather_canary_passed"])
        self.assertTrue(out["ready_for_runtime_binding_plan"])
        self.assertEqual(out["issue_count"], 0)
        self.assertTrue(_OUT_REPORT.is_file())


if __name__ == "__main__":
    unittest.main()
