"""2026-09-07 18:30 Korea incident: internal pipeline concepts must never render.

run_id 20260907_183002_keysuri_korea_tech_ac93e962 shipped a customer surface in
which the retired internal category label "글로벌→한국 번역 신호" appeared three
times as a reader-facing industry axis, beside real axes like "스타트업 투자" and
"로봇 자동화" — telling customers that KeeSuri Korea is translated KeeSuri Global.

Product authority: KeeSuri Korea selects and interprets Korea signals
independently. It is never a downstream translation of KeeSuri Global. These
tests pin that at three layers: the taxonomy cannot express the concept, the
renderer cannot pass an unapproved label through, and product-surface QA detects
the whole class if it ever reappears.
"""
from __future__ import annotations

import copy
import unittest

from keysuri_korea_longform_ux import _korea_industry_label
from keysuri_korea_signal_scoring import (
    CATEGORY_KO_LABELS,
    KOREA_TECH_CATEGORIES,
    canonical_korea_category,
    classify_korea_tech_category,
)
from keysuri_visible_text import _KOREA_CATEGORY_KO
from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    INTERNAL_PIPELINE_CONCEPT,
    PRODUCT_REVIEW_REQUIRED,
    PRODUCT_SURFACE_DIAGNOSTIC_KEY,
    evaluate_product_surface,
    prepare_final_customer_copy,
)

RETIRED_SLUG = "global_to_korea_translation"
LEAKED_LABEL = "글로벌→한국 번역 신호"

# The three reader sentences exactly as customers received them at 18:31 KST.
INCIDENT_READER_SENTENCES = (
    "오늘 다섯 신호를 하나로 보면, 반도체 산업 이슈를 축으로 글로벌→한국 번역 신호, "
    "스타트업 투자, 로봇 자동화 흐름이 같은 방향으로 움직이는 시장 구조입니다.",
    "국내 TOP5를 묶으면 글로벌→한국 번역 신호, 스타트업 투자, 로봇 자동화 축이 "
    "동시에 움직이며 산업 일정·자본 배분·규제 대응이 겹칩니다.",
    "오늘은 반도체 산업 이슈가 글로벌→한국 번역 신호·스타트업 투자·로봇 자동화 "
    "흐름을 한 번에 묶었습니다.",
)

# Prose that uses 글로벌 / 한국 / 번역 legitimately and must stay clean.
LEGITIMATE_KOREA_PROSE = (
    "글로벌 기업의 한국 시장 진출이 본격화되면서 국내 경쟁 구도가 바뀌고 있습니다.",
    "네이버가 한국어 번역 기능을 출시했다고 밝혔습니다.",
    "글로벌 공급망에서 한국 기업의 역할이 커지고 있다는 평가가 나옵니다.",
    "삼성은 미래 준비를 위해 2026년 하반기 공채 절차를 시작했습니다.",
    "세계은행이 서울에서 연 에듀테크 행사에 국내 스타트업이 참가했습니다.",
    "국내 기업·산업 동향, 스타트업 투자, 로봇 자동화 축이 함께 움직입니다.",
)


def _korea_payload(summaries):
    return {
        "selected_title": "키수리 국내 테크 브리핑",
        "top_5_items": [
            {"korean_title": f"국내 테크 신호 {i}", "summary": text}
            for i, text in enumerate(summaries, start=1)
        ],
    }


def _codes(result):
    return {finding.code for finding in result.findings}


class TaxonomyProductAuthorityTests(unittest.TestCase):
    """The Korea taxonomy must not be able to express the invalid concept."""

    def test_retired_category_is_gone_from_the_taxonomy(self) -> None:
        self.assertNotIn(RETIRED_SLUG, KOREA_TECH_CATEGORIES)
        self.assertNotIn(RETIRED_SLUG, CATEGORY_KO_LABELS)
        self.assertNotIn(RETIRED_SLUG, _KOREA_CATEGORY_KO)

    def test_no_korea_category_label_implies_translation_of_global(self) -> None:
        for slug, label in CATEGORY_KO_LABELS.items():
            with self.subTest(slug=slug):
                self.assertNotIn("번역", label)
                self.assertNotIn("→", label)
                self.assertNotIn("->", label)

    def test_retired_slug_still_resolves_for_persisted_artifacts(self) -> None:
        self.assertEqual(canonical_korea_category(RETIRED_SLUG), "korea_domestic_impact")
        self.assertEqual(canonical_korea_category("korea_semiconductor"), "korea_semiconductor")

    def test_classifier_never_emits_the_retired_slug(self) -> None:
        for text in (
            "삼성, 2026년 하반기 공채 실시. 국내 투자를 확대한다.",
            "세계은행이 서울에 부른 19개국 교육 관계자, 한국 에듀테크가 만났다",
            "다이슨, 한국 경험 기반 AI 활용 글로벌 고객 지원 체계 개편",
            "국내 도입과 한국 적용이 예상되는 글로벌 발표",
        ):
            with self.subTest(text=text[:24]):
                primary, secondary, _conf, reason = classify_korea_tech_category(text)
                self.assertNotEqual(primary, RETIRED_SLUG)
                self.assertNotIn(RETIRED_SLUG, secondary)
                self.assertNotIn(RETIRED_SLUG, reason)


class ReaderLabelAllowlistTests(unittest.TestCase):
    """The renderer must never pass an unapproved label through to prose."""

    def test_leaked_label_never_renders(self) -> None:
        self.assertEqual(_korea_industry_label(LEAKED_LABEL), "")

    def test_unapproved_internal_values_are_dropped(self) -> None:
        for raw in (
            "some_unapproved_internal_slug",
            "reason_for_category",
            "selection_score",
            "글로벌→한국 파생 신호",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_korea_industry_label(raw), "")

    def test_retired_slug_renders_as_approved_korea_prose(self) -> None:
        """Persisted artifacts stay readable without the invalid concept."""
        label = _korea_industry_label(RETIRED_SLUG)
        self.assertTrue(label)
        self.assertNotIn("번역", label)
        self.assertNotIn("→", label)

    def test_current_categories_all_render_approved_prose(self) -> None:
        for slug in KOREA_TECH_CATEGORIES:
            with self.subTest(slug=slug):
                label = _korea_industry_label(slug)
                self.assertTrue(label, f"{slug} lost its customer-facing label")
                self.assertNotIn("_", label)


class InternalConceptDetectorTests(unittest.TestCase):
    """QA must catch the class, without banning legitimate vocabulary."""

    def test_exact_incident_sentences_are_caught(self) -> None:
        result = evaluate_product_surface(
            "keysuri_korea_tech", _korea_payload(INCIDENT_READER_SENTENCES)
        )
        self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
        self.assertIn(INTERNAL_PIPELINE_CONCEPT, _codes(result))

    def test_semantic_variants_are_caught(self) -> None:
        for variant in (
            "글로벌->한국 번역 신호 축이 함께 움직입니다.",
            "글로벌⇒한국 파이프라인 신호가 확인됩니다.",
            "primary_category 는 global_to_korea_translation 입니다.",
            "keyword_hits:1 for korea_startup_investment 로 분류했습니다.",
            "source_pack 필드에서 확인된 신호입니다.",
            "selection_score 가 높은 항목입니다.",
        ):
            with self.subTest(variant=variant[:30]):
                result = evaluate_product_surface(
                    "keysuri_korea_tech", _korea_payload([variant])
                )
                self.assertIn(INTERNAL_PIPELINE_CONCEPT, _codes(result))

    def test_legitimate_global_korea_translation_prose_is_not_flagged(self) -> None:
        for text in LEGITIMATE_KOREA_PROSE:
            with self.subTest(text=text[:30]):
                result = evaluate_product_surface(
                    "keysuri_korea_tech", _korea_payload([text])
                )
                self.assertNotIn(INTERNAL_PIPELINE_CONCEPT, _codes(result))

    def test_whole_legitimate_korea_surface_stays_pass(self) -> None:
        result = evaluate_product_surface(
            "keysuri_korea_tech", _korea_payload(LEGITIMATE_KOREA_PROSE[:3])
        )
        self.assertEqual(result.status, CUSTOMER_SURFACE_PASS)

    def test_source_urls_are_not_mistaken_for_internal_identifiers(self) -> None:
        result = evaluate_product_surface(
            "keysuri_korea_tech",
            _korea_payload(
                ["출처는 https://zdnet.co.kr/view/?no=20260907153154 기사입니다."]
            ),
        )
        self.assertNotIn(INTERNAL_PIPELINE_CONCEPT, _codes(result))

    def test_detector_applies_to_today_and_global_surfaces_too(self) -> None:
        for mode, payload in (
            ("today_genie", {"key_watchpoints": [
                {"headline": "국내 증시 점검",
                 "detail": "글로벌→한국 번역 신호 축을 확인합니다."}]}),
            ("keysuri_global_tech", {"top_5_items": [
                {"korean_title": "글로벌 AI 신호",
                 "summary": "global_to_korea_translation 축으로 정리했습니다."}]}),
        ):
            with self.subTest(mode=mode):
                result = evaluate_product_surface(mode, payload)
                self.assertIn(INTERNAL_PIPELINE_CONCEPT, _codes(result))


class QaRemainsInspectOnlyTests(unittest.TestCase):
    """QA diagnoses this class; it must not rewrite product prose."""

    def test_prepare_final_customer_copy_does_not_mutate_korea_prose(self) -> None:
        payload = _korea_payload(INCIDENT_READER_SENTENCES)
        before = copy.deepcopy(payload)
        prepared = prepare_final_customer_copy("keysuri_korea_tech", payload)
        self.assertEqual(payload, before)
        echoed = {
            key: value
            for key, value in prepared.items()
            if key != PRODUCT_SURFACE_DIAGNOSTIC_KEY
        }
        self.assertEqual(echoed, before)
        self.assertEqual(
            prepared[PRODUCT_SURFACE_DIAGNOSTIC_KEY]["customer_surface_status"],
            PRODUCT_REVIEW_REQUIRED,
        )


class AcceptanceAuthorityUnchangedTests(unittest.TestCase):
    """Owner review stays available; customer send stays blocked."""

    def _meta(self, **overrides):
        meta = {
            "mode": "keysuri_korea_tech",
            "validation_result": "pass",
            "artifact_status": "emailed",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
        }
        meta.update(overrides)
        return meta

    def test_product_review_required_blocks_customer_send(self) -> None:
        from admin_store import can_approve_customer_send

        allowed, reason = can_approve_customer_send(
            self._meta(customer_surface_status=PRODUCT_REVIEW_REQUIRED),
            has_email_html=True,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "product_surface_remediation_needed")

    def test_product_review_required_does_not_suppress_owner_review(self) -> None:
        meta = self._meta(customer_surface_status=PRODUCT_REVIEW_REQUIRED)
        self.assertEqual(meta["artifact_status"], "emailed")
        self.assertEqual(meta["owner_review_status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
