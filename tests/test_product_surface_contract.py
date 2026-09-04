"""Unit contract for customer-visible prose across Today, Global and Korea."""
from __future__ import annotations

import unittest

from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    DUPLICATE_FILLER,
    HARD_FAIL,
    INTERNAL_KEYWORD_FRAGMENT,
    INTERNAL_PLACEHOLDER_LEAK,
    MIXED_SENTENCE_END_STYLE,
    PRODUCT_REVIEW_REQUIRED,
    RAW_ENGLISH_HEADLINE,
    REPEATED_CANNED_BRIDGE,
    REPEATED_SENTENCE_SKELETON,
    REVIEW_REQUIRED,
    RUNTIME_SAFETY_PASS,
    TRUNCATED_ENGLISH_HEADLINE,
    evaluate_product_surface,
    prepare_final_customer_copy,
    runtime_safety_status,
)


def _codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


class ProductSurfaceContractTests(unittest.TestCase):
    def test_truncated_english_heading_and_raw_source_copy_are_context_aware(self) -> None:
        source = {"top_market_news": [{"headline": "Lululemon stock plunges 10% after outlook cut"}]}
        payload = {
            "key_watchpoints": [
                {
                    "headline": "Lululemon stock plunges 1…",
                    "detail": "Lululemon stock plunges 10% after outlook cut. 국내 수급을 확인합니다.",
                }
            ]
        }
        codes = _codes(evaluate_product_surface("today_genie", payload, source_input=source))
        self.assertIn(TRUNCATED_ENGLISH_HEADLINE, codes)
        self.assertIn(RAW_ENGLISH_HEADLINE, codes)

    def test_legitimate_company_ticker_and_financial_terms_are_allowed(self) -> None:
        payload = {
            "key_watchpoints": [
                {
                    "headline": "OpenAI·NVIDIA 협력 확대",
                    "detail": "OpenAI와 NVIDIA의 GPU·API 계약 범위를 확인합니다.",
                }
            ]
        }
        self.assertEqual(
            evaluate_product_surface("today_genie", payload).status,
            CUSTOMER_SURFACE_PASS,
        )

    def test_korean_source_identity_may_match_reader_title(self) -> None:
        title = "엔비디아, 차세대 AI 인프라 투자 계획 발표"
        payload = {
            "top_5_items": [
                {"headline": title, "summary": "엔비디아가 투자 계획을 발표했습니다."}
            ]
        }
        source = {"top_5_news": {"items": [{"headline": title}]}}
        self.assertEqual(
            evaluate_product_surface(
                "keysuri_korea_tech", payload, source_input=source
            ).status,
            CUSTOMER_SURFACE_PASS,
        )

    def test_internal_keyword_fragment_is_detected(self) -> None:
        result = evaluate_product_surface(
            "today_genie",
            {"key_watchpoints": [{"detail": "Lululemon·Plunges 관련. 국내 수급을 확인합니다."}]},
        )
        self.assertIn(INTERNAL_KEYWORD_FRAGMENT, _codes(result))

    def test_repeated_skeleton_and_canned_bridge_are_detected(self) -> None:
        payload = {
            "key_watchpoints": [
                {"detail": f"야간·장전 맥락에서 기업 {i} 흐름이 대응 축으로 남아 있다."}
                for i in range(1, 4)
            ]
        }
        codes = _codes(evaluate_product_surface("today_genie", payload))
        self.assertIn(REPEATED_SENTENCE_SKELETON, codes)
        self.assertIn(REPEATED_CANNED_BRIDGE, codes)

    def test_mixed_sentence_end_style_is_detected(self) -> None:
        result = evaluate_product_surface(
            "today_genie",
            {
                "summary": "시장은 변동성을 보입니다.",
                "key_watchpoints": [{"detail": "국내 수급을 먼저 본다."}],
            },
        )
        self.assertIn(MIXED_SENTENCE_END_STYLE, _codes(result))

    def test_internal_placeholder_is_detected(self) -> None:
        result = evaluate_product_surface(
            "keysuri_global_tech",
            {"top_5_items": [{"headline": "TODO: headline", "summary": "한국어 요약입니다."}]},
        )
        self.assertIn(INTERNAL_PLACEHOLDER_LEAK, _codes(result))

    def test_duplicate_filler_sentence_is_detected(self) -> None:
        duplicate = "후속 공식 발표를 확인한 뒤 판단 범위를 다시 정합니다."
        result = evaluate_product_surface(
            "keysuri_global_tech",
            {"top_5_items": [{"summary": duplicate}, {"summary": duplicate}, {"summary": duplicate}]},
        )
        self.assertIn(DUPLICATE_FILLER, _codes(result))

    def test_today_boundary_repairs_structure_without_losing_source_identity(self) -> None:
        source = {
            "top_market_news": [
                {"news_id": "n1", "headline": "Vance says Fed should low…"},
                {"news_id": "n2", "headline": "Lululemon stock plunges 1…"},
                {"news_id": "n3", "headline": "The big August jobs repor…"},
            ]
        }
        payload = {
            "key_watchpoints": [
                {
                    "news_id": item["news_id"],
                    "headline": item["headline"],
                    "detail": f"야간·장전 맥락에서 {item['headline']} 흐름이 대응 축으로 남아 있다. 국내 지표를 먼저 본다.",
                }
                for item in source["top_market_news"]
            ]
        }
        self.assertEqual(
            evaluate_product_surface("today_genie", payload, source_input=source).status,
            PRODUCT_REVIEW_REQUIRED,
        )
        repaired = prepare_final_customer_copy("today_genie", payload, source_input=source)
        self.assertEqual(
            evaluate_product_surface("today_genie", repaired, source_input=source).status,
            CUSTOMER_SURFACE_PASS,
        )
        self.assertEqual(
            [item["news_id"] for item in repaired["key_watchpoints"]],
            ["n1", "n2", "n3"],
        )
        self.assertEqual(
            [item["headline"] for item in source["top_market_news"]],
            ["Vance says Fed should low…", "Lululemon stock plunges 1…", "The big August jobs repor…"],
        )

    def test_status_split_keeps_legacy_wire_values_distinct(self) -> None:
        self.assertEqual(runtime_safety_status("pass"), RUNTIME_SAFETY_PASS)
        self.assertEqual(runtime_safety_status("draft_only"), REVIEW_REQUIRED)
        self.assertEqual(runtime_safety_status("block"), HARD_FAIL)


if __name__ == "__main__":
    unittest.main()
