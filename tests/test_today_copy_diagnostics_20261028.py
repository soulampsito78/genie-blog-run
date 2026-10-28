"""Known malformed copy and replay reader instructions must survive neither QA boundary."""
from copy import deepcopy
import unittest

from product_surface_contract import evaluate_product_surface, prepare_final_customer_copy
from today_genie_replay_context import (
    CONTEXT_KEY, build_today_replay_context, known_copy_grammar_conflicts,
    replay_temporal_conflicts,
)
from validators import validate_today_genie


class TodayCopyDiagnostics(unittest.TestCase):
    def test_observed_malformed_sentence_is_caught_without_mutation(self):
        rt = {}
        # Satisfy the common shape so the full Today validator is reached.
        # This is a narrow grammar regression, not a complete market fixture.
        original = {"mode": "today_genie", "title": "기술주 실적", "greeting": "안녕하세요.",
            "summary": "시장 요약입니다.", "closing_message": "마감 세션을 확인합니다.",
            "hashtags": ["#오늘의지니"],
            "channel_drafts": {"email_subject": "기술주 실적", "naver_blog_title": "기술주 실적"},
            "key_watchpoints": [], "risk_check": [], "opportunities": []}
        original["summary"] = "기술주의 우선 확인할 변수는 금리·환율·수급 흐름하는 지표가 될 수 있습니다."
        before = deepcopy(original)
        result = validate_today_genie(original, rt)
        self.assertIn("today_copy_malformed_grammar", {x.code for x in result.issues})
        self.assertNotEqual(result.result, "pass")
        surface = evaluate_product_surface("today_genie", original, source_input=rt)
        self.assertIn("today_copy_malformed_grammar", {x.code for x in surface.findings})
        prepared = prepare_final_customer_copy("today_genie", original, source_input=rt)
        self.assertEqual(prepared["summary"], before["summary"])
        self.assertEqual(original, before)

    def test_grammatical_flow_and_source_metadata_are_not_flagged(self):
        for text in ("수급 흐름을 확인하는 지표입니다.", "외국인 수급이 흐름을 바꿨습니다."):
            self.assertEqual(known_copy_grammar_conflicts({"summary": text}), [])
        self.assertEqual(known_copy_grammar_conflicts({"source_url": "https://example.org/수급흐름하는"}), [])

    def test_replay_instructions_and_historical_windows_are_distinguished(self):
        for text in ("개장 전 환율을 살펴봅니다.", "첫 30분 수급을 확인합니다.",
                     "장 초반 거래대금을 살펴보세요.", "장을 시작할 준비를 하세요.",
                     "첫 30분의 변동성을 확인해 보세요."):
            with self.subTest(text=text):
                self.assertEqual(replay_temporal_conflicts({"summary": text}), ["summary"])
        for text in ("오늘 장전 발표된 실적은 원문에 나와 있습니다.",
                     "장 초반 거래대금을 확인했습니다.",
                     "오늘 개장 전 발표된 실적의 확정 값을 확인합니다.",
                     "개장 전에 공개된 확정 실적 수치의 의미를 살펴봅니다.",
                     "첫 30분에 집계된 수급을 확인합니다.",
                     "전일 첫 30분 수급을 확인합니다.",
                     "어제 개장 전 발표된 자료를 점검합니다."):
            with self.subTest(text=text):
                self.assertEqual(replay_temporal_conflicts({"summary": text}), [])
        self.assertEqual(replay_temporal_conflicts({"summary": "전일 첫 30분은 하락했습니다. 첫 30분 수급을 확인하세요."}), ["summary"])
        self.assertEqual(replay_temporal_conflicts({"channel_drafts": {
            "email_subject": "오늘 장전 체크포인트"}}), ["channel_drafts.email_subject"])

    def test_final_surface_detects_replay_issue_without_changing_historical_copy(self):
        context = build_today_replay_context({"target_date": "2026-10-28",
            "briefing_generated_at_kst": "2026-10-28T11:21:56+09:00"},
            "20261028_063049_today_genie_5cb73e82")
        data = {CONTEXT_KEY: context, "summary": "첫 30분 수급을 확인합니다."}
        before = deepcopy(data)
        result = prepare_final_customer_copy("today_genie", data)
        self.assertIn("today_replay_temporal_conflict", {x["code"] for x in result["_product_surface_qa"]["findings"]})
        self.assertEqual(data, before)
        self.assertEqual(result["summary"], before["summary"])

    def test_natural_and_other_products_do_not_gain_replay_checks(self):
        data = {"summary": "첫 30분 수급을 확인합니다."}
        for mode in ("today_genie", "keysuri_global_tech", "keysuri_korea_tech"):
            result = evaluate_product_surface(mode, data)
            self.assertNotIn("today_replay_temporal_conflict", {x.code for x in result.findings})


if __name__ == "__main__":
    unittest.main()
