"""Unit contract for customer-visible prose across Today, Global and Korea."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch
from admin_store import can_approve_customer_send
from today_genie_source_provenance import SOURCE_PROVENANCE_ISSUE
from tests.synthetic_today_source_binding import bind_synthetic_today_sources

from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    DUPLICATE_FILLER,
    HARD_FAIL,
    INTERNAL_KEYWORD_FRAGMENT,
    INTERNAL_PLACEHOLDER_LEAK,
    MIXED_SENTENCE_END_STYLE,
    PRODUCT_REVIEW_REQUIRED,
    PRODUCT_SURFACE_DIAGNOSTIC_KEY,
    RAW_ENGLISH_HEADLINE,
    REPEATED_CANNED_BRIDGE,
    REPEATED_SENTENCE_SKELETON,
    REVIEW_REQUIRED,
    RUNTIME_SAFETY_PASS,
    TRUNCATED_ENGLISH_HEADLINE,
    evaluate_product_surface,
    prepare_final_customer_copy,
    product_surface_run_fields,
    runtime_safety_status,
)


def _codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


class ProductSurfaceContractTests(unittest.TestCase):
    def _synthetic_today_provenance_fixture(self):
        payload = {"key_watchpoints": [
            {"headline": "연준 문서의 발표 조건", "detail": "연준은 회의 자료에 정책 논의의 범위를 설명했고 발표 시점은 후속 확인사항입니다."},
            {"headline": "엔비디아 공급 계약의 기준", "detail": "엔비디아는 제품별 계약 조건을 공개했으며 생산과 실제 납품은 구분할 필요가 있습니다."},
            {"headline": "운송 노선의 비용 구조", "detail": "운송 업체는 노선별 운영 계획을 설명하고 추가 계약의 범위는 별도 자료로 공개할 예정입니다."},
        ]}
        return bind_synthetic_today_sources(payload, fixture="release-provenance-counterexamples")

    def _assert_provenance_blocks_before_readiness(self, payload, source):
        before = copy.deepcopy((payload, source))
        inspected = prepare_final_customer_copy("today_genie", payload, source_input=source)
        fields = product_surface_run_fields(inspected)
        self.assertIn(SOURCE_PROVENANCE_ISSUE, fields["product_surface_issue_codes"])
        self.assertEqual(fields["customer_surface_status"], PRODUCT_REVIEW_REQUIRED)
        meta = {"mode": "today_genie", "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent", "validation_result": "pass",
                "artifact_status": "emailed", **fields}
        with patch("delegated_delivery_safety.publication_guard_required",
                   side_effect=AssertionError("Must not reach readiness")) as readiness:
            self.assertEqual(can_approve_customer_send(meta, has_email_html=True),
                             (False, "product_surface_remediation_needed"))
            readiness.assert_not_called()
        self.assertEqual((payload, source), before)

    def test_today_missing_original_links_block_partial_and_all_before_readiness(self):
        for missing_count in (1, 3):
            with self.subTest(missing=missing_count):
                payload, source = self._synthetic_today_provenance_fixture()
                for index in range(missing_count):
                    source["top_market_news"][index]["url"] = ""
                    payload["key_watchpoints"][index]["source_url"] = ""
                self._assert_provenance_blocks_before_readiness(payload, source)

    def test_today_signed_private_link_blocks_before_readiness(self):
        payload, source = self._synthetic_today_provenance_fixture()
        signed = source["top_market_news"][0]["url"] + "?x-goog-signature=synthetic-only"
        source["top_market_news"][0]["url"] = signed
        payload["key_watchpoints"][0]["source_url"] = signed
        self._assert_provenance_blocks_before_readiness(payload, source)

    def test_today_original_source_substitution_blocks_before_readiness(self):
        payload, source = self._synthetic_today_provenance_fixture()
        payload["key_watchpoints"][1]["source_url"] = "https://different.example.test/articles/synthetic-substitution"
        self._assert_provenance_blocks_before_readiness(payload, source)

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
        payload, source = bind_synthetic_today_sources(payload, fixture="company-ticker-copy")
        self.assertEqual(
            evaluate_product_surface("today_genie", payload, source_input=source).status,
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

    def test_today_boundary_inspects_without_touching_prose_or_identity(self) -> None:
        """The boundary reports; it never edits.  Rewriting here is what produced
        the 2026-09-07 "U.S. U.S 관련 시장 소식" splice."""
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
        before = copy.deepcopy(payload)
        inspected = prepare_final_customer_copy("today_genie", payload, source_input=source)
        # Still failing, because the defect is real and must reach owner review.
        self.assertEqual(
            evaluate_product_surface("today_genie", inspected, source_input=source).status,
            PRODUCT_REVIEW_REQUIRED,
        )
        # Input untouched; output differs only by the additive diagnostic key.
        self.assertEqual(payload, before)
        echoed = {
            key: value
            for key, value in inspected.items()
            if key != PRODUCT_SURFACE_DIAGNOSTIC_KEY
        }
        self.assertEqual(echoed, before)
        self.assertEqual(
            [item["news_id"] for item in inspected["key_watchpoints"]],
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


class RuntimeRiskListBoundaryTests(unittest.TestCase):
    """Portable new list boundary, collected by the existing CI module loader.

    No external baseline tree or prior13/16 test module is imported. The original
    file above is retained byte-for-byte. CI imports this module, so this class
    is collected despite the preserved earlier direct-script main guard.
    """

    def _prepare(self, payload):
        return prepare_final_customer_copy("today_genie", payload, source_input={"date": "2026-10-12"})

    def _role_paths(self, output):
        from temporal_context_diagnostic import ROLE_CONTEXT_UNKNOWN
        return [f["path"] for f in output[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["findings"]
                if f["code"] == ROLE_CONTEXT_UNKNOWN]

    def test_service_list_shape_detects_third_current_span(self):
        payload = {"summary": "현재 트럼프 전 대통령의 계획을 살핍니다.",
                   "key_watchpoints": [{"detail": "현재 밴스 의원의 입장을 점검합니다."}],
                   "risk_check": [{"risk": "정책 발언", "detail": "트럼프 전 대통령의 발언을 주시합니다.", "basis": "interpretation"}]}
        output = self._prepare(payload)
        self.assertEqual(self._role_paths(output), ["summary", "items[1].detail", "risk_check[1].detail"])
        self.assertEqual(output[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["customer_surface_status"], PRODUCT_REVIEW_REQUIRED)

    def test_each_row_collects_both_fields_in_original_order(self):
        payload = {"risk_check": [
            {"risk": "현재 트럼프 대통령의 입장입니다.", "detail": "현재 밴스 의원의 발언입니다.", "basis": "fact"},
            {"risk": "트럼프 전 대통령의 발언입니다.", "detail": "밴스 부통령의 계획입니다.", "basis": "speculation"}]}
        output = self._prepare(payload)
        self.assertEqual(self._role_paths(output), ["risk_check[1].risk", "risk_check[1].detail", "risk_check[2].risk", "risk_check[2].detail"])

    def test_skipped_rows_keep_original_positions(self):
        payload = {"risk_check": [None, "not an object", {},
                   {"risk": "", "detail": "현재 밴스 의원의 발언입니다."}, 42,
                   {"risk": "현재 트럼프 대통령입니다.", "detail": None}]}
        self.assertEqual(self._role_paths(self._prepare(payload)), ["risk_check[4].detail", "risk_check[6].risk"])

    def test_empty_and_nontext_values_are_safe(self):
        for risks in (None, [], "text", 42, [None, [], {}, {"risk": "  ", "detail": 42}, {"risk": False, "detail": None}]):
            with self.subTest(risks=risks):
                self.assertEqual(self._role_paths(self._prepare({"risk_check": risks})), [])

    def test_body_basis_order_and_input_are_preserved(self):
        payload = {"summary": "임의 교정하지 않습니다.", "risk_check": [
            {"risk": "정책", "detail": "현재 트럼프 전 대통령입니다.", "basis": "fact", "extra": [1, 2]},
            None, {"risk": "현재 밴스 부통령입니다.", "detail": "전망", "basis": "speculation"}]}
        before = copy.deepcopy(payload)
        output = self._prepare(payload)
        self.assertEqual(payload, before)
        del output[PRODUCT_SURFACE_DIAGNOSTIC_KEY]
        self.assertEqual(output, before)
        self.assertIsNot(output["risk_check"], payload["risk_check"])

    def test_object_support_and_other_product_contracts_are_retained(self):
        output = self._prepare({"risk_check": {"risk": "현재 밴스 의원입니다.", "detail": "입장을 점검합니다."}})
        self.assertEqual(self._role_paths(output), ["risk_check.risk"])
        payload = {"summary": "문구입니다.", "risk_check": [
            {"risk": "현재 트럼프 전 대통령입니다.", "detail": "현재 밴스 의원입니다."}]}
        expected_diagnostic = {"customer_surface_status": CUSTOMER_SURFACE_PASS, "customer_ready": True,
                               "issue_codes": [], "findings": [], "contract_version": "genie-product-surface-v1",
                               "structural_similarity_threshold": 0.82}
        for mode in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(mode=mode):
                result = prepare_final_customer_copy(mode, payload)
                self.assertEqual(result.pop(PRODUCT_SURFACE_DIAGNOSTIC_KEY), expected_diagnostic)
                self.assertEqual(result, payload)

    def test_existing_source_body_and_fact_boundaries_survive(self):
        from temporal_context_diagnostic import ROLE_CONTEXT_UNKNOWN
        payload = {"summary": "TODO", "key_watchpoints": [{"detail": "확인할 기사입니다."}],
                   "risk_check": [{"risk": "현재 밴스 의원의 정책입니다.", "detail": "리스크를 살펴봅니다.", "basis": "fact"}]}
        output = self._prepare(payload)
        diagnostic = output[PRODUCT_SURFACE_DIAGNOSTIC_KEY]
        self.assertIn(INTERNAL_PLACEHOLDER_LEAK, diagnostic["issue_codes"])
        self.assertIn(SOURCE_PROVENANCE_ISSUE, diagnostic["issue_codes"])
        self.assertIn(ROLE_CONTEXT_UNKNOWN, diagnostic["issue_codes"])
        self.assertEqual(self._role_paths(output), ["risk_check[1].risk"])
        self.assertEqual(diagnostic["temporal_context"]["fact_verdict"], "NOT_CERTIFIED")
