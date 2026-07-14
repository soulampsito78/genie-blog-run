"""Tests for the common Genie/KeeSuri generation cost estimate module."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from genie_cost_estimate import (
    calculate_image_list_price,
    estimate_genie_generation_cost,
    normalize_model_env_key,
    standard_image_pricing_for_model,
    standard_text_pricing_for_model,
)


def _clear_all_pricing_env():
    return mock.patch.dict(
        os.environ,
        {
            "GENIE_COST_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_THOUGHTS_USD_PER_1M_TOKENS": "",
            "GENIE_COST_IMAGE_USD_PER_IMAGE": "",
            "GENIE_COST_KRW_PER_USD": "",
            "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_THOUGHTS_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE": "",
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_INPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_OUTPUT_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_THOUGHTS_USD_PER_1M_TOKENS": "",
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE": "",
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
    def test_normalize_model_env_key(self) -> None:
        self.assertEqual(normalize_model_env_key("gemini-2.5-flash"), "GEMINI_2_5_FLASH")
        self.assertEqual(
            normalize_model_env_key("gemini-3-flash-preview"),
            "GEMINI_3_FLASH_PREVIEW",
        )
        self.assertEqual(
            normalize_model_env_key("gemini-2.5-flash-image"),
            "GEMINI_2_5_FLASH_IMAGE",
        )
        self.assertEqual(
            normalize_model_env_key("publishers/google/models/gemini-3-flash-preview"),
            "GEMINI_3_FLASH_PREVIEW",
        )
        self.assertEqual(
            normalize_model_env_key(
                "projects/p/locations/global/publishers/google/models/gemini-3-flash-preview"
            ),
            "GEMINI_3_FLASH_PREVIEW",
        )

    def test_model_specific_price_takes_priority_over_common_env(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_INPUT_USD_PER_1M_TOKENS": "9.00",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
            )
        self.assertAlmostEqual(result["unit_prices"]["input_usd_per_1m_tokens"], 0.30)
        self.assertEqual(result["unit_prices"]["input_price_env"], "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS")
        self.assertEqual(result["model_pricing"]["text_model_key"], "GEMINI_2_5_FLASH")

    def test_gemini_3_preview_and_gemini_25_flash_can_use_different_prices(self) -> None:
        env = {
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_INPUT_USD_PER_1M_TOKENS": "0.50",
            "GENIE_COST_GEMINI_3_FLASH_PREVIEW_OUTPUT_USD_PER_1M_TOKENS": "3.00",
            "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
        }
        with _clear_all_pricing_env(), mock.patch.dict(os.environ, env, clear=False):
            global_result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                service_family="keysuri",
                text_model="gemini-3-flash-preview",
            )
            korea_result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                service_family="keysuri",
                text_model="gemini-2.5-flash",
            )
        self.assertAlmostEqual(global_result["total_cost_usd"], 3.50)
        self.assertAlmostEqual(korea_result["total_cost_usd"], 2.80)
        self.assertEqual(global_result["model_pricing"]["provider"], "google_cloud_vertex_ai")
        self.assertEqual(global_result["model_pricing"]["pricing_tier"], "standard")
        self.assertEqual(global_result["model_pricing"]["input_usd_per_1m_tokens"], 0.50)
        self.assertEqual(
            global_result["model_pricing"]["output_and_reasoning_usd_per_1m_tokens"],
            3.00,
        )

    def test_verified_standard_contracts(self) -> None:
        flash25 = standard_text_pricing_for_model("gemini-2.5-flash")
        flash3 = standard_text_pricing_for_model("gemini-3-flash-preview")
        assert flash25 is not None and flash3 is not None
        self.assertEqual(flash25["input_usd_per_1m_tokens"], 0.30)
        self.assertEqual(flash25["output_and_reasoning_usd_per_1m_tokens"], 2.50)
        self.assertEqual(flash3["input_usd_per_1m_tokens"], 0.50)
        self.assertEqual(flash3["output_and_reasoning_usd_per_1m_tokens"], 3.00)

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
        self.assertEqual(result["cost_estimate_status"], "usage_only")
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

    def test_gemini_flash_image_does_not_use_generic_per_image_fallback(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ, {"GENIE_COST_IMAGE_USD_PER_IMAGE": "0.02"}, clear=False
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="today_genie",
                image_model="gemini-2.5-flash-image",
                image_generated_count=2,
            )
        self.assertIsNone(result["components"]["image_cost_usd"])
        self.assertIsNone(result["unit_prices"]["image_usd_per_image"])
        self.assertEqual(
            result["model_pricing"]["image_pricing_status"],
            "unsupported_or_unconfigured",
        )
        self.assertIn("image cost not calculated", result["pricing_note"])

    def test_gemini_flash_image_uses_output_image_token_env(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30.00"},
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="today_genie",
                image_model="gemini-2.5-flash-image",
                image_generated_count=2,
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.0774)
        self.assertEqual(result["image_usage"]["image_output_tokens"], 2580)
        self.assertEqual(
            result["unit_prices"]["image_price_env"],
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS",
        )
        self.assertEqual(
            result["model_pricing"]["image_pricing_status"],
            "priced_from_output_image_tokens",
        )

    def test_official_flash_image_contract_and_unit_modes(self) -> None:
        contract = standard_image_pricing_for_model("gemini-2.5-flash-image")
        assert contract is not None
        self.assertEqual(contract["output_tokens_per_image"], 1290)
        self.assertEqual(contract["output_image_usd_per_1m_tokens"], 30.0)
        self.assertAlmostEqual(
            calculate_image_list_price(
                pricing_mode="output_image_tokens",
                successful_output_count=1,
                output_image_tokens=1290,
                usd_per_1m_output_image_tokens=30.0,
            ),
            0.0387,
        )
        self.assertAlmostEqual(
            calculate_image_list_price(
                pricing_mode="per_image",
                successful_output_count=2,
                usd_per_image=0.04,
            ),
            0.08,
        )

    def test_failed_request_without_output_keeps_image_cost_unknown(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30"},
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="today_genie",
                image_model="gemini-2.5-flash-image",
                image_usage={
                    "image_request_count": 1,
                    "image_successful_output_count": 0,
                    "image_failed_request_count": 1,
                },
            )
        self.assertIsNone(result["components"]["image_cost_usd"])
        self.assertEqual(
            result["model_pricing"]["image_pricing_status"],
            "failed_request_billing_unknown",
        )

    def test_local_static_and_cache_assets_do_not_increase_cost(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30"},
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="keysuri",
                image_model="gemini-2.5-flash-image",
                image_usage={
                    "image_request_count": 0,
                    "image_successful_output_count": 0,
                    "image_locally_derived_asset_count": 2,
                    "image_cache_reuse_count": 1,
                    "image_static_fallback_count": 1,
                },
            )
        self.assertEqual(result["components"]["image_cost_usd"], 0.0)
        self.assertEqual(result["usage"]["generated_image_count"], 0)
        self.assertEqual(
            result["model_pricing"]["image_pricing_status"],
            "known_zero_paid_outputs",
        )

    def test_discarded_successful_output_is_still_priced(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30"},
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="today_genie",
                image_model="gemini-2.5-flash-image",
                image_usage={
                    "image_request_count": 1,
                    "image_successful_output_count": 2,
                    "image_discarded_output_count": 1,
                    "image_output_tokens": 2580,
                },
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.0774)

    def test_retry_metrics_price_only_successful_outputs(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {"GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30"},
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {},
                service_family="today_genie",
                image_model="gemini-2.5-flash-image",
                image_usage={
                    "image_request_count": 2,
                    "image_successful_output_count": 1,
                    "image_failed_request_count": 1,
                    "image_retry_count": 1,
                    "image_output_tokens": 1290,
                },
            )
        self.assertAlmostEqual(result["components"]["image_cost_usd"], 0.0387)
        self.assertEqual(result["image_usage"]["image_retry_count"], 1)

    def test_unknown_image_model_leaves_image_and_total_blank(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
                image_model="unknown-image-model",
                image_usage={"image_request_count": 1, "image_successful_output_count": 1},
            )
        self.assertIsNone(result["components"]["image_cost_usd"])
        self.assertIsNone(result["total_cost_usd"])
        self.assertIn("GENIE_COST_UNKNOWN_IMAGE_MODEL_USD_PER_IMAGE", result["missing_price_env"])

    def test_explicit_zero_and_unknown_image_usage_are_distinct(self) -> None:
        prices = {
            "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
            "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30",
        }
        with _clear_all_pricing_env(), mock.patch.dict(os.environ, prices, clear=False):
            known_zero = estimate_genie_generation_cost(
                {"prompt_token_count": 1000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
                image_usage={"image_request_count": 0, "image_successful_output_count": 0},
            )
            unknown = estimate_genie_generation_cost(
                {"prompt_token_count": 1000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
            )
        self.assertEqual(known_zero["components"]["image_cost_usd"], 0.0)
        self.assertIsNotNone(known_zero["total_cost_usd"])
        self.assertEqual(known_zero["cost_estimate_status"], "fully_priced_ai_model_cost")
        self.assertIsNone(unknown["components"]["image_cost_usd"])
        self.assertIsNone(unknown["total_cost_usd"])
        self.assertEqual(unknown["cost_estimate_status"], "partial_text_only")


class CostEstimateStatusTests(unittest.TestCase):
    def test_usage_without_prices_is_usage_only(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
            )
        self.assertEqual(result["cost_estimate_status"], "usage_only")
        self.assertFalse(result["price_env_configured"])

    def test_no_usage_is_unavailable(self) -> None:
        with _clear_all_pricing_env():
            result = estimate_genie_generation_cost(None, service_family="today_genie")
        self.assertEqual(result["cost_estimate_status"], "unavailable")

    def test_text_price_without_krw_is_estimated_usd(self) -> None:
        """KRW FX is optional — full text USD prices alone yield estimated status."""
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
            )
        self.assertEqual(result["cost_estimate_status"], "estimated")
        self.assertAlmostEqual(result["total_cost_usd"], 2.80)
        self.assertIsNone(result["total_cost_krw"])
        self.assertNotIn("GENIE_COST_KRW_PER_USD", result["missing_price_env"])
        self.assertAlmostEqual(result["components"]["text_total_cost_usd"], 2.80)

    def test_text_prices_without_image_env_are_partial_usd(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
                "GENIE_COST_GEMINI_2_5_FLASH_THOUGHTS_USD_PER_1M_TOKENS": "99.00",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {
                    "prompt_token_count": 12_404,
                    "candidates_token_count": 5_651,
                    "thoughts_token_count": 3_924,
                },
                service_family="keysuri",
                text_model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
                image_generated_count=2,
            )
        self.assertEqual(result["cost_estimate_status"], "partial_text_only")
        self.assertIsNone(result["total_cost_usd"])
        self.assertIsNotNone(result["components"]["text_total_cost_usd"])
        self.assertAlmostEqual(result["components"]["text_thoughts_cost_usd"], 0.00981)
        self.assertEqual(
            result["unit_prices"]["thoughts_price_env"],
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS",
        )
        self.assertEqual(
            result["unit_prices"]["deprecated_thoughts_price_env_ignored"],
            "GENIE_COST_GEMINI_2_5_FLASH_THOUGHTS_USD_PER_1M_TOKENS",
        )
        self.assertIsNone(result["components"]["image_cost_usd"])
        self.assertIsNone(result["total_cost_krw"])
        self.assertEqual(
            result["missing_price_env"],
            ["GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS"],
        )
        self.assertIn("text cost calculated; image cost not configured", result["pricing_note"])
        self.assertNotIn("GENIE_COST_KRW_PER_USD", result["missing_price_env"])
        self.assertNotIn("THOUGHTS", "|".join(result["missing_price_env"]))

    def test_reasoning_tokens_require_output_price_not_thoughts_price(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_GEMINI_2_5_FLASH_THOUGHTS_USD_PER_1M_TOKENS": "99.00",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {
                    "prompt_token_count": 1_000,
                    "candidates_token_count": 0,
                    "thoughts_token_count": 2_000,
                },
                service_family="keysuri",
                text_model="gemini-2.5-flash",
            )
        self.assertIsNone(result["components"]["text_thoughts_cost_usd"])
        self.assertIn(
            "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS",
            result["missing_price_env"],
        )
        self.assertNotIn("THOUGHTS", "|".join(result["missing_price_env"]))
        self.assertEqual(
            result["unit_prices"]["deprecated_thoughts_price_env_ignored"],
            "GENIE_COST_GEMINI_2_5_FLASH_THOUGHTS_USD_PER_1M_TOKENS",
        )

    def test_text_image_and_krw_prices_are_estimated(self) -> None:
        with _clear_all_pricing_env(), mock.patch.dict(
            os.environ,
            {
                "GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS": "0.30",
                "GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS": "2.50",
                "GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS": "30.00",
                "GENIE_COST_KRW_PER_USD": "1400",
            },
            clear=False,
        ):
            result = estimate_genie_generation_cost(
                {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000},
                service_family="today_genie",
                text_model="gemini-2.5-flash",
                image_model="gemini-2.5-flash-image",
                image_generated_count=1,
            )
        self.assertEqual(result["cost_estimate_status"], "fully_priced_ai_model_cost")
        self.assertAlmostEqual(result["total_cost_usd"], 2.8387)
        self.assertAlmostEqual(result["total_cost_krw"], 3974.18)


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
