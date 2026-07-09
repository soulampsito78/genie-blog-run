"""Tests for the common Genie/KeeSuri generation cost estimate module."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from genie_cost_estimate import estimate_genie_generation_cost


def _clear_all_pricing_env():
    return mock.patch.dict(
        os.environ,
        {
            "GENIE_COST_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_THOUGHTS_USD_PER_1M_TOKENS": "",
            "GENIE_COST_IMAGE_USD_PER_IMAGE": "",
            "GENIE_COST_KRW_PER_USD": "",
            "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_IMAGE_USD_PER_IMAGE": "",
            "KEYSURI_COST_KRW_PER_USD": "",
        },
        clear=False,
    )


class ServiceFamilySchemaTests(unittest.TestCase):
    def test_today_genie_service_family_and_model_shape(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1000, "candidates_token_count": 200},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
                mode="today_genie",
                run_id="20260709_060000_today_genie_ab12cd34",
            )
        self.assertTrue(result["estimate_only"])
        self.assertEqual(result["service_family"], "today_genie")
        self.assertEqual(result["mode"], "today_genie")
        self.assertEqual(result["run_id"], "20260709_060000_today_genie_ab12cd34")
        self.assertEqual(result["model"]["text_model"], "gemini-2.5-flash")
        self.assertIsNone(result["model"]["image_model"])
        self.assertEqual(result["usage"]["generated_image_count"], 0)
        self.assertIn("infra_cost_usd", result["components"])
        self.assertIsNone(result["components"]["infra_cost_usd"])

    def test_tomorrow_genie_service_family(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                None, service_family="tomorrow_genie", mode="tomorrow_genie"
            )
        self.assertEqual(result["service_family"], "tomorrow_genie")
        self.assertEqual(result["pricing_source"], "unknown")

    def test_keysuri_service_family(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 500},
                service_family="keysuri",
                program_id="keysuri_korea_tech",
            )
        self.assertEqual(result["service_family"], "keysuri")
        self.assertEqual(result["program_id"], "keysuri_korea_tech")


class EnvPriorityTests(unittest.TestCase):
    def test_genie_cost_env_takes_priority_over_legacy_keysuri_env(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_INPUT_USD_PER_1M_TOKENS": "1.0",
                "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "9.0",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000}, service_family="genie"
            )
        self.assertAlmostEqual(result["unit_prices"]["input_usd_per_1m_tokens"], 1.0)
        self.assertAlmostEqual(result["total_cost_usd"], 1.0)

    def test_legacy_keysuri_env_used_when_genie_env_unset(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ, {"KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "0.30"}, clear=False
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000}, service_family="keysuri"
            )
        self.assertAlmostEqual(result["unit_prices"]["input_usd_per_1m_tokens"], 0.30)

    def test_no_env_at_all_is_unknown_but_preserves_usage(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 12003, "thoughts_token_count": 11792},
                service_family="today_genie",
            )
        self.assertEqual(result["pricing_source"], "unknown")
        self.assertIsNone(result["total_cost_usd"])
        self.assertEqual(result["usage"]["prompt_token_count"], 12003)
        self.assertEqual(result["usage"]["thoughts_token_count"], 11792)


class ImageCostTests(unittest.TestCase):
    def test_image_generated_count_folds_into_total(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ, {"GENIE_COST_IMAGE_USD_PER_IMAGE": "0.02"}, clear=False
        ):
            result = estimate_genie_generation_cost(
                {}, service_family="today_genie", image_generated_count=2
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.04)
        self.assertAlmostEqual(result["total_cost_usd"], 0.04)
        self.assertEqual(result["usage"]["generated_image_count"], 2)


class NeverRaisesTests(unittest.TestCase):
    def test_malformed_usage_does_not_raise(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                {"prompt_token_count": "not-a-number"}, service_family="today_genie"
            )
        self.assertTrue(result["estimate_only"])
        self.assertIsNone(result["total_cost_usd"])

    def test_invalid_env_value_is_ignored(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ, {"GENIE_COST_INPUT_USD_PER_1M_TOKENS": "garbage"}, clear=False
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1000}, service_family="today_genie"
            )
        self.assertIsNone(result["unit_prices"]["input_usd_per_1m_tokens"])


if __name__ == "__main__":
    unittest.main()
