"""Tests for the best-effort KeeSuri owner-review cost estimate (never billing-authoritative)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from keysuri_cost_estimate import estimate_keysuri_gemini_cost


def _clear_pricing_env():
    return mock.patch.dict(
        os.environ,
        {
            "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS": "",
            "KEYSURI_COST_IMAGE_USD_PER_IMAGE": "",
            "KEYSURI_COST_KRW_PER_USD": "",
            "GENIE_COST_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_THOUGHTS_USD_PER_1M_TOKENS": "",
            "GENIE_COST_IMAGE_USD_PER_IMAGE": "",
            "GENIE_COST_KRW_PER_USD": "",
            "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE": "",
        },
        clear=False,
    )


class CostEstimateBasicTests(unittest.TestCase):
    def test_usage_present_with_full_pricing_computes_total(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "0.30",
                "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "2.50",
            },
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {
                    "prompt_token_count": 1_000_000,
                    "candidates_token_count": 500_000,
                    "thoughts_token_count": None,
                    "total_token_count": 1_500_000,
                },
                model="gemini-2.5-flash",
                program_id="keysuri_korea_tech",
                run_id="20260709_183000_keysuri_korea_tech_ab12cd34",
            )
        self.assertTrue(result["estimate_only"])
        self.assertEqual(result["usage"]["prompt_token_count"], 1_000_000)
        self.assertAlmostEqual(result["components"]["text_input_cost_usd"], 0.30)
        self.assertAlmostEqual(result["components"]["text_output_cost_usd"], 1.25)
        self.assertAlmostEqual(result["total_cost_usd"], 1.55)
        self.assertEqual(result["pricing_source"], "env")
        self.assertEqual(result["cost_estimate_status"], "estimated")
        self.assertIsNone(result["total_cost_krw"])
        self.assertNotIn("GENIE_COST_KRW_PER_USD", result.get("missing_price_env") or [])
        self.assertAlmostEqual(result["components"]["text_total_cost_usd"], 1.55)

    def test_no_usage_metadata_returns_shape_without_crashing(self) -> None:
        with _clear_pricing_env():
            result = estimate_keysuri_gemini_cost(None, model="gemini-3-flash-preview")
        self.assertTrue(result["estimate_only"])
        self.assertIsNone(result["total_cost_usd"])
        self.assertEqual(result["pricing_source"], "unknown")
        self.assertEqual(result["cost_estimate_status"], "unavailable")

    def test_model_specific_prices_allow_global_and_korea_to_differ(self) -> None:
        env = {
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_INPUT_USD_PER_1M_TOKENS": "0.90",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_OUTPUT_USD_PER_1M_TOKENS": "5.40",
            "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
        }
        with _clear_pricing_env(), mock.patch.dict(os.environ, env, clear=False):
            global_result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                model="gemini-3-flash-preview",
                program_id="keysuri_global_tech",
            )
            korea_result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                model="gemini-2.5-flash",
                program_id="keysuri_korea_tech",
            )
        self.assertAlmostEqual(global_result["total_cost_usd"], 6.30)
        self.assertAlmostEqual(korea_result["total_cost_usd"], 2.80)
        self.assertEqual(global_result["model_pricing"]["text_model_key"], "GEMINI_3_FLASH_PREVIEW")
        self.assertEqual(korea_result["model_pricing"]["text_model_key"], "GEMINI_2_5_FLASH")


class CostEstimateThoughtsTests(unittest.TestCase):
    def test_thoughts_tokens_use_dedicated_price_when_set(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "2.50",
                "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS": "5.00",
            },
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {"thoughts_token_count": 1_000_000, "candidates_token_count": 100_000},
                model="gemini-3-flash-preview",
            )
        self.assertAlmostEqual(result["components"]["text_thoughts_cost_usd"], 5.00)
        self.assertNotIn("not set", result["pricing_note"])

    def test_thoughts_tokens_fall_back_to_output_price_and_note_it(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ, {"KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "2.50"}, clear=False
        ):
            result = estimate_keysuri_gemini_cost(
                {"thoughts_token_count": 1_000_000},
                model="gemini-3-flash-preview",
            )
        self.assertAlmostEqual(result["components"]["text_thoughts_cost_usd"], 2.50)
        self.assertIn("fallback", result["pricing_note"])
        self.assertIsNone(result["unit_prices"]["thoughts_usd_per_1m_tokens"])

    def test_no_thoughts_tokens_and_no_price_leaves_component_none(self) -> None:
        with _clear_pricing_env():
            result = estimate_keysuri_gemini_cost({"prompt_token_count": 100}, model="m")
        self.assertIsNone(result["components"]["text_thoughts_cost_usd"])


class CostEstimatePricingMissingTests(unittest.TestCase):
    def test_no_unit_prices_at_all_leaves_total_none_but_keeps_usage(self) -> None:
        with _clear_pricing_env():
            result = estimate_keysuri_gemini_cost(
                {
                    "prompt_token_count": 12003,
                    "candidates_token_count": 478,
                    "thoughts_token_count": 11792,
                    "total_token_count": 24273,
                },
                model="gemini-3-flash-preview",
                program_id="keysuri_korea_tech",
                run_id="run123",
            )
        self.assertIsNone(result["total_cost_usd"])
        self.assertIsNone(result["total_cost_krw"])
        self.assertEqual(result["pricing_source"], "unknown")
        self.assertEqual(result["cost_estimate_status"], "usage_only")
        self.assertEqual(result["usage"]["prompt_token_count"], 12003)
        self.assertEqual(result["usage"]["thoughts_token_count"], 11792)
        self.assertTrue(result["pricing_note"])

    def test_partial_pricing_marks_source_as_partial(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ, {"KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "0.30"}, clear=False
        ):
            result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 500_000},
                model="m",
            )
        self.assertEqual(result["pricing_source"], "partial")
        # Only the input component is priced — total reflects known components
        # only (a partial estimate), not a full text_input+output total.
        self.assertAlmostEqual(result["total_cost_usd"], 0.30)
        self.assertIsNone(result["components"]["text_output_cost_usd"])


class CostEstimateImageTests(unittest.TestCase):
    def test_image_generated_count_adds_image_cost(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "0.10",
                "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS": "0.40",
                "KEYSURI_COST_IMAGE_USD_PER_IMAGE": "0.02",
            },
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": 1000, "candidates_token_count": 1000},
                model="m",
                image_generated_count=1,
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.02)
        self.assertGreater(result["total_cost_usd"], 0.0)

    def test_gemini_flash_image_does_not_apply_generic_image_price(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "KEYSURI_COST_IMAGE_USD_PER_IMAGE": "0.02",
                "GENIE_COST_IMAGE_USD_PER_IMAGE": "0.03",
            },
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {},
                model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
                image_generated_count=1,
            )
        self.assertIsNone(result["components"]["image_cost_usd"])
        self.assertEqual(
            result["model_pricing"]["image_pricing_status"],
            "unsupported_or_unconfigured",
        )

    def test_gemini_flash_image_uses_explicit_model_specific_image_price(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE": "0.04"},
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {},
                model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
                image_generated_count=1,
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.04)
        self.assertEqual(result["model_pricing"]["image_pricing_status"], "configured")

    def test_zero_images_with_image_price_set_costs_zero_not_none(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ, {"KEYSURI_COST_IMAGE_USD_PER_IMAGE": "0.02"}, clear=False
        ):
            result = estimate_keysuri_gemini_cost({}, model="m", image_generated_count=0)
        self.assertEqual(result["components"]["image_cost_usd"], 0.0)


class CostEstimateKrwTests(unittest.TestCase):
    def test_krw_conversion_applied_when_both_total_and_rate_known(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "1.0",
                "KEYSURI_COST_KRW_PER_USD": "1400",
            },
            clear=False,
        ):
            result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": 1_000_000}, model="m"
            )
        self.assertAlmostEqual(result["total_cost_usd"], 1.0)
        self.assertAlmostEqual(result["total_cost_krw"], 1400.0)


class CostEstimateNeverRaisesTests(unittest.TestCase):
    def test_malformed_usage_mapping_does_not_raise(self) -> None:
        with _clear_pricing_env():
            result = estimate_keysuri_gemini_cost(
                {"prompt_token_count": "not-a-number"}, model="m"
            )
        self.assertTrue(result["estimate_only"])
        self.assertIsNone(result["total_cost_usd"])

    def test_invalid_env_price_is_ignored_not_raised(self) -> None:
        with _clear_pricing_env(), mock.patch.dict(
            os.environ, {"KEYSURI_COST_INPUT_USD_PER_1M_TOKENS": "not-a-number"}, clear=False
        ):
            result = estimate_keysuri_gemini_cost({"prompt_token_count": 1000}, model="m")
        self.assertIsNone(result["unit_prices"]["input_usd_per_1m_tokens"])
        self.assertIsNone(result["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
