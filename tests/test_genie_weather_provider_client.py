"""Tests for GENIE Seoul weather provider client (mocked — no live API)."""
from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import genie_weather_provider_client as gwp

_REPO = Path(__file__).resolve().parent.parent
_FEEDS = _REPO / "ops" / "feeds"


def _load_mock(name: str) -> dict:
    return json.loads((_FEEDS / name).read_text(encoding="utf-8"))


def _mock_urlopen_factory(payload: dict, *, status: int = 200):
    body = json.dumps(payload).encode("utf-8")

    def _urlopen(url, timeout=None):
        resp = MagicMock()
        resp.status = status
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    return _urlopen


class MaskSecretTests(unittest.TestCase):
    def test_mask_none(self) -> None:
        self.assertEqual(gwp.mask_secret(None), "(missing)")

    def test_mask_short(self) -> None:
        self.assertEqual(gwp.mask_secret("abc"), "****")

    def test_mask_normal(self) -> None:
        masked = gwp.mask_secret("sk-live-abcdefghijklmnop")
        self.assertTrue(masked.startswith("****"))
        self.assertEqual(masked[-4:], "mnop")
        self.assertNotIn("sk-live-abcdefghijklmnop", masked)


class ProviderConfigEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        gwp._urlopen_fn = None

    def test_missing_provider_env(self) -> None:
        os.environ.pop("GENIE_WEATHER_PROVIDER", None)
        cfg = gwp.get_weather_provider_config_from_env()
        self.assertFalse(cfg["can_call"])
        self.assertEqual(cfg["provider"], "")

    def test_unsupported_provider(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "kma_unknown"
        cfg = gwp.get_weather_provider_config_from_env()
        self.assertFalse(cfg["can_call"])
        self.assertEqual(cfg["provider"], "kma_unknown")

    def test_openweather_missing_key(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "openweather"
        os.environ.pop("OPENWEATHER_API_KEY", None)
        os.environ.pop("WEATHER_API_KEY", None)
        cfg = gwp.get_weather_provider_config_from_env()
        self.assertFalse(cfg["can_call"])
        self.assertFalse(cfg["api_key_present"])

    def test_openweather_with_key(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "openweather"
        os.environ["OPENWEATHER_API_KEY"] = "test-openweather-secret-key-99"
        cfg = gwp.get_weather_provider_config_from_env()
        self.assertTrue(cfg["can_call"])
        self.assertTrue(cfg["api_key_present"])
        summary = gwp._public_config_summary(cfg)
        self.assertNotIn("test-openweather-secret-key-99", json.dumps(summary))
        self.assertIn("****", summary["api_key_masked"])


class ProviderConversionTests(unittest.TestCase):
    def test_openweather_to_runtime_payload(self) -> None:
        mock = _load_mock("weather_provider_openweather_seoul_current.mock.json")
        payload = gwp.convert_provider_response_to_runtime_weather_payload(
            "openweather", mock
        )
        self.assertEqual(payload["provider_mode"], "runtime_weather_api")
        self.assertEqual(payload["location"]["city"], "Seoul")
        self.assertIn(payload["condition_code"], ("clear", "sunny"))
        self.assertNotIn("raw_provider_payload", payload)

    def test_weatherapi_to_runtime_payload(self) -> None:
        mock = _load_mock("weather_provider_weatherapi_seoul_current.mock.json")
        payload = gwp.convert_provider_response_to_runtime_weather_payload(
            "weatherapi", mock
        )
        self.assertEqual(payload["location"]["timezone"], "Asia/Seoul")
        self.assertIsNotNone(payload.get("temperature_c"))


class ControlledCanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        gwp._urlopen_fn = None

    def test_missing_env_blocked_no_request(self) -> None:
        os.environ.pop("GENIE_WEATHER_PROVIDER", None)
        report = gwp.run_seoul_weather_controlled_canary()
        self.assertEqual(report["canary_status"], "blocked_missing_weather_env")
        self.assertEqual(report["request_count"], 0)
        self.assertFalse(report["runtime_side_effects"]["called_weather_api"])

    def test_unsupported_provider_blocked(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "accuweather"
        report = gwp.run_seoul_weather_controlled_canary()
        self.assertEqual(report["canary_status"], "blocked_unsupported_provider")
        self.assertEqual(report["request_count"], 0)

    def test_mocked_openweather_pass(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "openweather"
        os.environ["OPENWEATHER_API_KEY"] = "canary-test-key-0001"
        gwp._urlopen_fn = _mock_urlopen_factory(
            _load_mock("weather_provider_openweather_seoul_current.mock.json")
        )
        report = gwp.run_seoul_weather_controlled_canary()
        self.assertEqual(report["canary_status"], "pass")
        self.assertEqual(report["request_count"], 1)
        self.assertTrue(report["runtime_side_effects"]["called_weather_api"])
        self.assertFalse(report["secrets_exposed"])
        self.assertFalse(report["raw_provider_payload_saved"])
        norm = report["normalized_weather_context"]
        self.assertIsNotNone(norm)
        self.assertEqual(norm["location"], "Seoul")
        for cid in gwp.CONSUMER_IDS:
            self.assertIsNotNone(report["consumer_contexts"].get(cid))

    def test_mocked_api_error(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "openweather"
        os.environ["OPENWEATHER_API_KEY"] = "canary-test-key-0002"
        gwp._urlopen_fn = _mock_urlopen_factory({}, status=401)
        report = gwp.run_seoul_weather_controlled_canary()
        self.assertEqual(report["canary_status"], "api_error")
        self.assertEqual(report["request_count"], 1)

    def test_side_effects_all_false_except_weather_on_block(self) -> None:
        os.environ.pop("GENIE_WEATHER_PROVIDER", None)
        report = gwp.run_seoul_weather_controlled_canary()
        side = report["runtime_side_effects"]
        self.assertFalse(side["called_gemini"])
        self.assertFalse(side["called_image_api"])
        self.assertFalse(side["fetched_live_news"])
        self.assertFalse(side["sent_email"])
        self.assertFalse(side["published_naver"])
        self.assertFalse(side["changed_scheduler"])

    def test_sanitize_no_secrets_in_report(self) -> None:
        os.environ["GENIE_WEATHER_PROVIDER"] = "openweather"
        os.environ["OPENWEATHER_API_KEY"] = "super-secret-api-key-xyz9"
        gwp._urlopen_fn = _mock_urlopen_factory(
            _load_mock("weather_provider_openweather_seoul_current.mock.json")
        )
        report = gwp.run_seoul_weather_controlled_canary()
        safe = gwp.sanitize_canary_report_for_output(report)
        blob = json.dumps(safe)
        self.assertNotIn("super-secret-api-key-xyz9", blob)
        self.assertNotIn("테크 앵커", blob)
        self.assertNotIn("Tomorrow_Geenee", blob)


class CanaryScriptTests(unittest.TestCase):
    def test_script_missing_env_produces_report(self) -> None:
        import subprocess

        env = os.environ.copy()
        env.pop("GENIE_WEATHER_PROVIDER", None)
        env.pop("OPENWEATHER_API_KEY", None)
        env.pop("WEATHER_API_KEY", None)
        proc = subprocess.run(
            ["python3", "scripts/run_seoul_weather_api_canary.py"],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["canary_status"], "blocked_missing_weather_env")
        self.assertEqual(out["request_count"], 0)
        report_path = _REPO / "output/keysuri_preview/weather_canary/seoul_weather_api_canary_report.json"
        self.assertTrue(report_path.is_file())


if __name__ == "__main__":
    unittest.main()
