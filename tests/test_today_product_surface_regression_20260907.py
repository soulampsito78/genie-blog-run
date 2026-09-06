"""2026-09-07 Today incident: product QA must diagnose, never author.

run_id 20260907_063105_today_genie_93beb901 shipped an owner-review artifact whose
whole TOP3 surface read "U.S 관련 시장 소식", "AI 관련 시장 소식", "SEC 관련 시장 소식".
Those titles were produced by a first-capitalized-English-token heuristic, and the
product-surface layer then deleted grounded sentences and inserted manufactured
leads on top of them ("U.S. U.S 관련 시장 소식 보도가 ...").

These tests pin the architecture that makes the whole class impossible:
  * reader titles come only from grounded Korean fields bound to the article;
  * the QA boundary is byte-stable with respect to customer prose;
  * an unusable surface becomes PRODUCT_REVIEW_REQUIRED, not invented copy.
"""
from __future__ import annotations

import copy
import json
import unittest

from admin_store import can_approve_customer_send
from product_surface_contract import (
    CUSTOMER_SURFACE_PASS,
    FABRICATED_GENERIC_READER_TITLE,
    HARD_FAIL,
    MISSING_GROUNDED_READER_TITLE,
    PRODUCT_REVIEW_REQUIRED,
    RAW_ENGLISH_HEADLINE,
    REPEATED_SENTENCE_SKELETON,
    REVIEW_REQUIRED,
    RUNTIME_SAFETY_PASS,
    TRUNCATED_ENGLISH_HEADLINE,
    evaluate_product_surface,
    prepare_final_customer_copy,
    runtime_safety_status,
)
from today_genie_top3_assembly import (
    assemble_key_watchpoints_from_slots,
    normalize_top3_slots_payload,
)

# The exact three articles selected by the 09-07 06:31 natural run.
_INCIDENT_NEWS = [
    {
        "headline": "U.S. Energy Secretary Wright says Iran nuclear deal may never happen",
        "source": "CNBC",
        "date": "2026-09-06",
        "news_id": "today-0acd885777f180afbdf0",
    },
    {
        "headline": "AI data centers are transforming rural land markets — and fueling a backlash",
        "source": "CNBC",
        "date": "2026-09-06",
        "news_id": "today-199658faf6f12f418f36",
    },
    {
        "headline": "SEC sues ISS as Trump administration ramps up scrutiny of proxy advisers",
        "source": "CNBC",
        "date": "2026-09-06",
        "news_id": "today-170c677876b999c89d97",
    },
]

# Every generic reader title the deleted heuristic emitted on 09-07, plus the
# splice artifact the repair pass created on top of them.
_FORBIDDEN_SURFACE_STRINGS = (
    "U.S 관련 시장 소식",
    "AI 관련 시장 소식",
    "SEC 관련 시장 소식",
    "U.S. U.S",
)


def _runtime_input(news=None):
    return {
        "top_market_news": copy.deepcopy(news if news is not None else _INCIDENT_NEWS),
        "overnight_us_market": {"summary": "S&P 500 -0.38%, Nasdaq -0.29%, Dow -0.51%."},
        "macro_indicators": {"headline": "지정학 리스크와 AI 산업 동향이 변수."},
        "risk_factors": [{"risk": "지정학", "detail": "이란 핵협상 불확실성."}],
    }


def _grounded_slots():
    return [
        {
            "slot": 1,
            "news_id": _INCIDENT_NEWS[0]["news_id"],
            "headline_ko": "미국 에너지장관, 이란 핵합의 회의론",
            "what_happened": "라이트 미국 에너지장관이 이란 핵합의가 끝내 성사되지 않을 수 있다고 밝히면서 중동 지정학 긴장이 다시 부각됐습니다.",
            "why_it_matters_today": "오늘 장전에는 국제 유가와 정유·화학 업종 투자심리에 이 발언이 먼저 반영될 수 있습니다.",
            "what_to_watch_in_korea": "코스피 정유·조선주 호가와 원/달러 환율 개장 갭을 함께 확인합니다.",
        },
        {
            "slot": 2,
            "news_id": _INCIDENT_NEWS[1]["news_id"],
            "headline_ko": "AI 데이터센터 확산과 토지 반발",
            "what_happened": "AI 데이터센터 건설이 미국 농촌 토지시장을 바꾸면서 지역사회 반발이 커지고 있다는 보도가 나왔습니다.",
            "why_it_matters_today": "금일 개장 전에는 AI 인프라 관련주의 성장 기대와 규제 리스크가 같이 저울질됩니다.",
            "what_to_watch_in_korea": "코스닥 AI 인프라·전력기기 테마의 체결강도와 거래대금을 확인합니다.",
        },
        {
            "slot": 3,
            "news_id": _INCIDENT_NEWS[2]["news_id"],
            "headline_ko": "SEC, 의결권 자문사 ISS 제소",
            "what_happened": "미국 증권거래위원회가 의결권 자문사 ISS를 제소하며 자문사 규제 강화 기조가 확인됐습니다.",
            "why_it_matters_today": "오늘 장전에는 글로벌 지배구조·주주환원 테마의 정책 불확실성이 재평가될 수 있습니다.",
            "what_to_watch_in_korea": "기관 선물 순매수와 지배구조 개편 기대가 붙은 지주사 호가를 함께 확인합니다.",
        },
    ]


def _blob(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TodayGenericTitleRegressionTests(unittest.TestCase):
    """A — the 2026-09-07 defect class must be unreachable."""

    def test_incident_headlines_never_become_generic_market_news_titles(self) -> None:
        runtime_input = _runtime_input()
        sparse = normalize_top3_slots_payload(
            {"slots": [{"news_id": item["news_id"]} for item in _INCIDENT_NEWS]}
        )
        watchpoints = assemble_key_watchpoints_from_slots(sparse, runtime_input)
        blob = _blob(watchpoints)
        for forbidden in _FORBIDDEN_SURFACE_STRINGS:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, blob)

    def test_capitalized_token_titles_are_absent_for_arbitrary_english_headlines(self) -> None:
        """Not just U.S/AI/SEC: no English headline may yield a "<token> 관련 시장 소식"."""
        headlines = [
            "Nvidia CEO Jensen Huang declines Senate testimony on AI exports",
            "Lululemon plunges after cutting its full-year outlook",
            "Powell signals patience as inflation cools",
            "OpenAI confidentially files for IPO",
            "Trump turns up the heat on Warsh as Fed rate hike looms",
        ]
        for headline in headlines:
            with self.subTest(headline=headline):
                news = [{"headline": headline, "source": "CNBC", "date": "2026-09-06", "news_id": "today-x1"}]
                runtime_input = _runtime_input(news)
                watchpoints = assemble_key_watchpoints_from_slots(
                    normalize_top3_slots_payload({"slots": [{"news_id": "today-x1"}]}),
                    runtime_input,
                )
                blob = _blob(watchpoints)
                self.assertNotIn("관련 시장 소식", blob)
                self.assertNotIn("주가 변동", blob)

    def test_generic_frame_title_is_detected_wherever_it_comes_from(self) -> None:
        """QA still diagnoses the fake-title shape if any layer ever emits one."""
        for title in (
            "U.S 관련 시장 소식",
            "AI 관련 시장 소식",
            "SEC 관련 시장 소식",
            "Lululemon 주가 변동",
            "해외시장 주요 이슈 2",
        ):
            with self.subTest(title=title):
                payload = {
                    "key_watchpoints": [
                        {"headline": title, "detail": "국내에서는 코스피 수급을 확인합니다."}
                    ]
                }
                result = evaluate_product_surface("today_genie", payload)
                self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
                self.assertIn(
                    FABRICATED_GENERIC_READER_TITLE,
                    {finding.code for finding in result.findings},
                )

    def test_grounded_korean_titles_are_preserved_and_pass(self) -> None:
        runtime_input = _runtime_input()
        watchpoints = assemble_key_watchpoints_from_slots(_grounded_slots(), runtime_input)
        titles = [wp["headline"] for wp in watchpoints]
        self.assertEqual(
            titles,
            [
                "미국 에너지장관, 이란 핵합의 회의론",
                "AI 데이터센터 확산과 토지 반발",
                "SEC, 의결권 자문사 ISS 제소",
            ],
        )
        # Source identity is never traded away to satisfy QA.
        self.assertEqual(
            [wp["news_id"] for wp in watchpoints],
            [item["news_id"] for item in _INCIDENT_NEWS],
        )
        result = evaluate_product_surface(
            "today_genie", {"key_watchpoints": watchpoints}, source_input=runtime_input
        )
        self.assertEqual(result.status, CUSTOMER_SURFACE_PASS)

    def test_same_generation_korean_alias_is_used_before_giving_up(self) -> None:
        """Authority 2: the briefing's own Korean headline, no extra model call."""
        runtime_input = _runtime_input()
        sparse = normalize_top3_slots_payload(
            {"slots": [{"news_id": item["news_id"]} for item in _INCIDENT_NEWS]}
        )
        aliases = [
            {"headline": "미국 에너지장관, 이란 핵합의 회의론", "detail": "라이트 장관이 이란 핵합의 무산 가능성을 언급했습니다."},
            {"headline": "AI 데이터센터 확산과 토지 반발", "detail": "AI 데이터센터 확산이 농촌 토지시장을 흔들고 있습니다."},
            {"headline": "SEC, 의결권 자문사 ISS 제소", "detail": "SEC가 의결권 자문사 ISS를 제소했습니다."},
        ]
        watchpoints = assemble_key_watchpoints_from_slots(
            sparse, runtime_input, model_watchpoints=aliases
        )
        self.assertEqual(
            [wp["headline"] for wp in watchpoints],
            [alias["headline"] for alias in aliases],
        )
        self.assertNotIn("관련 시장 소식", _blob(watchpoints))

    def test_no_grounded_title_marks_review_instead_of_inventing_one(self) -> None:
        runtime_input = _runtime_input()
        sparse = normalize_top3_slots_payload(
            {"slots": [{"news_id": item["news_id"]} for item in _INCIDENT_NEWS]}
        )
        watchpoints = assemble_key_watchpoints_from_slots(sparse, runtime_input)
        for wp in watchpoints:
            self.assertTrue(wp.get("product_review_required"))
        prepared = prepare_final_customer_copy(
            "today_genie", {"key_watchpoints": watchpoints}, source_input=runtime_input
        )
        diag = prepared["_product_surface_qa"]
        self.assertEqual(diag["customer_surface_status"], PRODUCT_REVIEW_REQUIRED)
        self.assertIn(MISSING_GROUNDED_READER_TITLE, diag["issue_codes"])
        # The artifact stays reviewable rather than being emptied or blocked.
        self.assertEqual(len(prepared["key_watchpoints"]), 3)


class Top3SlotBindingTests(unittest.TestCase):
    """The extraction contract must actually deliver its facts to the card.

    On 2026-09-07 the extraction schema shown to the model carried no news_id
    field, so no slot matched, every extracted fact was discarded, and the whole
    TOP3 fell through to deterministic filler.
    """

    def test_extraction_schema_requires_the_binding_field(self) -> None:
        from prompts import TOP3_EXTRACTION_OUTPUT_SCHEMA

        for slot in TOP3_EXTRACTION_OUTPUT_SCHEMA["slots"]:
            self.assertIn("news_id", slot)
            self.assertIn("headline_ko", slot)

    def test_slot_without_echoed_id_still_binds_by_position(self) -> None:
        runtime_input = _runtime_input()
        slots = [
            {k: v for k, v in slot.items() if k != "news_id"}
            for slot in _grounded_slots()
        ]
        watchpoints = assemble_key_watchpoints_from_slots(
            normalize_top3_slots_payload({"slots": slots}), runtime_input
        )
        self.assertEqual(
            [wp["headline"] for wp in watchpoints],
            [slot["headline_ko"] for slot in slots],
        )
        for wp in watchpoints:
            self.assertIsNone(wp.get("product_review_required"))
        # Identity still comes from the input article, not the model.
        self.assertEqual(
            [wp["news_id"] for wp in watchpoints],
            [item["news_id"] for item in _INCIDENT_NEWS],
        )

    def test_slot_echoing_a_different_id_never_rebinds_the_card(self) -> None:
        runtime_input = _runtime_input()
        slots = []
        for slot in _grounded_slots():
            rebound = dict(slot)
            rebound["news_id"] = "today-someone-elses-article"
            slots.append(rebound)
        watchpoints = assemble_key_watchpoints_from_slots(
            normalize_top3_slots_payload({"slots": slots}), runtime_input
        )
        for wp, item in zip(watchpoints, _INCIDENT_NEWS):
            # Content from a mismatched article is refused; the card is held for
            # review rather than silently bound to the wrong story.
            self.assertTrue(wp.get("product_review_required"))
            self.assertEqual(wp["news_id"], item["news_id"])
        prepared = prepare_final_customer_copy(
            "today_genie", {"key_watchpoints": watchpoints}, source_input=runtime_input
        )
        self.assertEqual(
            prepared["_product_surface_qa"]["customer_surface_status"],
            PRODUCT_REVIEW_REQUIRED,
        )

    def test_correctly_bound_slots_pass_without_any_review_marker(self) -> None:
        runtime_input = _runtime_input()
        watchpoints = assemble_key_watchpoints_from_slots(
            normalize_top3_slots_payload({"slots": _grounded_slots()}), runtime_input
        )
        for wp in watchpoints:
            self.assertIsNone(wp.get("product_review_required"))
        prepared = prepare_final_customer_copy(
            "today_genie", {"key_watchpoints": watchpoints}, source_input=runtime_input
        )
        self.assertEqual(
            prepared["_product_surface_qa"]["customer_surface_status"],
            CUSTOMER_SURFACE_PASS,
        )


class ProductSurfaceImmutabilityTests(unittest.TestCase):
    """B — the QA boundary must never touch substantive customer prose."""

    def _payloads(self):
        runtime_input = _runtime_input()
        grounded = assemble_key_watchpoints_from_slots(_grounded_slots(), runtime_input)
        sparse = assemble_key_watchpoints_from_slots(
            normalize_top3_slots_payload(
                {"slots": [{"news_id": item["news_id"]} for item in _INCIDENT_NEWS]}
            ),
            runtime_input,
        )
        defective = [
            {
                "headline": "U.S. Energy Secretary Wright says Iran nuclear…",
                "detail": "야간·장전 맥락에서 확인됩니다. 흐름이 대응 축으로 남아 있습니다.",
                "news_id": "today-0acd885777f180afbdf0",
            },
            {
                "headline": "AI 데이터센터 확산과 토지 반발",
                "detail": "야간·장전 맥락에서 확인됩니다. 흐름이 대응 축으로 남아 있습니다.",
                "news_id": "today-199658faf6f12f418f36",
            },
        ]
        return runtime_input, {
            "grounded": grounded,
            "sparse": sparse,
            "defective": defective,
        }

    def test_prepare_final_customer_copy_does_not_mutate_prose(self) -> None:
        runtime_input, cases = self._payloads()
        for name, watchpoints in cases.items():
            with self.subTest(case=name):
                payload = {
                    "title": "글로벌 혼조 속 지정학 리스크 부상",
                    "summary": "지난 금요일 미국 증시는 혼조세를 보였습니다.",
                    "key_watchpoints": watchpoints,
                }
                before = copy.deepcopy(payload)
                prepared = prepare_final_customer_copy(
                    "today_genie", payload, source_input=runtime_input
                )
                # Input payload is untouched.
                self.assertEqual(payload, before)
                # Output differs only by the additive diagnostic key.
                echoed = {k: v for k, v in prepared.items() if k != "_product_surface_qa"}
                self.assertEqual(echoed, before)
                for original, returned in zip(
                    before["key_watchpoints"], prepared["key_watchpoints"]
                ):
                    self.assertEqual(original.get("headline"), returned.get("headline"))
                    self.assertEqual(original.get("detail"), returned.get("detail"))

    def test_evaluate_product_surface_does_not_mutate_prose(self) -> None:
        runtime_input, cases = self._payloads()
        for name, watchpoints in cases.items():
            with self.subTest(case=name):
                payload = {"key_watchpoints": watchpoints}
                before = copy.deepcopy(payload)
                evaluate_product_surface(
                    "today_genie", payload, source_input=runtime_input
                )
                self.assertEqual(payload, before)

    def test_qa_never_deletes_or_inserts_sentences(self) -> None:
        """The 09-07 splice ("U.S. U.S ...") came from delete-then-insert repair."""
        runtime_input = _runtime_input()
        detail = (
            "U.S 관련 시장 소식 관련 보도입니다. U.S. Energy Secretary Wright·Iran 관련. "
            "국내에서는 코스피 선물 베이시스를 먼저 확인합니다."
        )
        payload = {
            "key_watchpoints": [
                {"headline": "U.S 관련 시장 소식", "detail": detail, "news_id": "today-0acd885777f180afbdf0"}
            ]
        }
        prepared = prepare_final_customer_copy(
            "today_genie", payload, source_input=runtime_input
        )
        self.assertEqual(prepared["key_watchpoints"][0]["detail"], detail)
        self.assertNotIn("U.S. U.S", _blob(prepared["key_watchpoints"]))
        self.assertEqual(
            prepared["_product_surface_qa"]["customer_surface_status"],
            PRODUCT_REVIEW_REQUIRED,
        )


class RawEnglishSurfaceRegressionTests(unittest.TestCase):
    """C — the 2026-09-04 raw/truncated English regression must stay detected."""

    def test_truncated_english_reader_title_still_detected(self) -> None:
        payload = {
            "key_watchpoints": [
                {
                    "headline": "SpaceX Stock Could Face Further…",
                    "detail": "국내에서는 코스피 수급을 확인합니다.",
                }
            ]
        }
        result = evaluate_product_surface("today_genie", payload)
        self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
        self.assertIn(
            TRUNCATED_ENGLISH_HEADLINE, {finding.code for finding in result.findings}
        )

    def test_raw_english_headline_copied_into_reader_field_still_detected(self) -> None:
        payload = {
            "key_watchpoints": [
                {
                    "headline": "SEC sues ISS as Trump administration ramps up scrutiny",
                    "detail": "국내에서는 코스피 수급을 확인합니다.",
                }
            ]
        }
        result = evaluate_product_surface("today_genie", payload)
        self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
        self.assertIn(
            RAW_ENGLISH_HEADLINE, {finding.code for finding in result.findings}
        )

    def test_source_headline_leaking_into_body_still_detected(self) -> None:
        runtime_input = _runtime_input()
        payload = {
            "key_watchpoints": [
                {
                    "headline": "SEC, 의결권 자문사 ISS 제소",
                    "detail": (
                        "sec sues iss as trump administration ramps up scrutiny of proxy advisers "
                        "국내에서는 코스피 수급을 확인합니다."
                    ),
                }
            ]
        }
        result = evaluate_product_surface(
            "today_genie", payload, source_input=runtime_input
        )
        self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)


class RepeatedSkeletonRegressionTests(unittest.TestCase):
    """D — repeated canned skeletons must still raise PRODUCT_REVIEW_REQUIRED."""

    def test_known_night_premarket_skeleton_across_cards(self) -> None:
        skeleton = (
            "야간·장전 맥락에서 {topic} 보도가 확인됐고 흐름이 대응 축으로 남아 있습니다."
        )
        payload = {
            "key_watchpoints": [
                {"headline": "이란 핵합의 회의론", "detail": skeleton.format(topic="이란")},
                {"headline": "AI 데이터센터 반발", "detail": skeleton.format(topic="AI 데이터센터")},
                {"headline": "SEC의 ISS 제소", "detail": skeleton.format(topic="SEC")},
            ]
        }
        result = evaluate_product_surface("today_genie", payload)
        self.assertEqual(result.status, PRODUCT_REVIEW_REQUIRED)
        self.assertIn(
            REPEATED_SENTENCE_SKELETON, {finding.code for finding in result.findings}
        )

    def test_repeated_skeleton_is_reported_not_rewritten(self) -> None:
        skeleton = (
            "야간·장전 맥락에서 {topic} 보도가 확인됐고 흐름이 대응 축으로 남아 있습니다."
        )
        payload = {
            "key_watchpoints": [
                {"headline": "이란 핵합의 회의론", "detail": skeleton.format(topic="이란")},
                {"headline": "AI 데이터센터 반발", "detail": skeleton.format(topic="AI 데이터센터")},
            ]
        }
        before = copy.deepcopy(payload)
        prepared = prepare_final_customer_copy("today_genie", payload)
        self.assertEqual(
            [wp["detail"] for wp in prepared["key_watchpoints"]],
            [wp["detail"] for wp in before["key_watchpoints"]],
        )


class AcceptanceAuthorityTests(unittest.TestCase):
    """E — owner review survives PRODUCT_REVIEW_REQUIRED; customer send does not."""

    def _meta(self, **overrides):
        meta = {
            "mode": "today_genie",
            "validation_result": "pass",
            "artifact_status": "emailed",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
        }
        meta.update(overrides)
        return meta

    def test_product_review_required_blocks_customer_send_with_exact_reason(self) -> None:
        allowed, reason = can_approve_customer_send(
            self._meta(customer_surface_status=PRODUCT_REVIEW_REQUIRED),
            has_email_html=True,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "product_surface_remediation_needed")

    def test_product_review_required_does_not_suppress_owner_review_artifact(self) -> None:
        """Owner review is an artifact/email decision, not an approval decision."""
        meta = self._meta(customer_surface_status=PRODUCT_REVIEW_REQUIRED)
        self.assertEqual(meta["artifact_status"], "emailed")
        self.assertEqual(meta["owner_review_status"], "pending_review")
        # Runtime safety is a separate authority and still reads PASS.
        self.assertEqual(runtime_safety_status(meta["validation_result"]), RUNTIME_SAFETY_PASS)

    def test_customer_surface_pass_does_not_block_on_product_surface(self) -> None:
        """CUSTOMER_SURFACE_PASS clears this gate; later gates (SMTP/recipient
        configuration) are environmental and out of this contract's authority."""
        _, reason = can_approve_customer_send(
            self._meta(customer_surface_status=CUSTOMER_SURFACE_PASS),
            has_email_html=True,
        )
        self.assertNotEqual(reason, "product_surface_remediation_needed")

    def test_hard_fail_runtime_safety_blocks_delivery(self) -> None:
        self.assertEqual(runtime_safety_status("block"), HARD_FAIL)
        self.assertEqual(runtime_safety_status("draft_only"), REVIEW_REQUIRED)
        allowed, reason = can_approve_customer_send(
            self._meta(validation_result="block", artifact_status="failed"),
            has_email_html=True,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "not_approvable")

    def test_scheduled_path_persists_the_product_surface_verdict(self) -> None:
        """09-07 root gap: the scheduled artifact carried no customer_surface_status."""
        from orchestrator import _product_surface_fields_from_api_payload

        fields = _product_surface_fields_from_api_payload(
            {
                "validation_result": "pass",
                "data": {
                    "_product_surface_qa": {
                        "customer_surface_status": PRODUCT_REVIEW_REQUIRED,
                        "issue_codes": [MISSING_GROUNDED_READER_TITLE],
                        "contract_version": "genie-product-surface-v1",
                    }
                },
            }
        )
        self.assertEqual(fields["customer_surface_status"], PRODUCT_REVIEW_REQUIRED)
        self.assertEqual(fields["runtime_safety_status"], RUNTIME_SAFETY_PASS)
        allowed, reason = can_approve_customer_send(
            self._meta(**fields), has_email_html=True
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "product_surface_remediation_needed")


class CrossModeIsolationTests(unittest.TestCase):
    """F — the Today fix must not change Global or Korea behavior."""

    def test_keysuri_modes_are_untouched_by_prepare_final_customer_copy(self) -> None:
        for mode in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(mode=mode):
                payload = {
                    "selected_title": "국내 스타트업 투자 동향",
                    "top_5_items": [
                        {
                            "korean_title": "국내 AI 스타트업 시리즈B 마감",
                            "summary": "국내 AI 스타트업이 시리즈B 라운드를 마감했다고 밝혔습니다.",
                        }
                    ],
                }
                before = copy.deepcopy(payload)
                prepared = prepare_final_customer_copy(mode, payload)
                self.assertEqual(payload, before)
                echoed = {
                    k: v for k, v in prepared.items() if k != "_product_surface_qa"
                }
                self.assertEqual(echoed, before)

    def test_today_only_marker_does_not_leak_into_keysuri_evaluation(self) -> None:
        result = evaluate_product_surface(
            "keysuri_global_tech",
            {
                "top_5_items": [
                    {
                        "korean_title": "국내 AI 스타트업 시리즈B 마감",
                        "summary": "국내 AI 스타트업이 시리즈B 라운드를 마감했다고 밝혔습니다.",
                    }
                ]
            },
        )
        self.assertEqual(result.status, CUSTOMER_SURFACE_PASS)


if __name__ == "__main__":
    unittest.main()
