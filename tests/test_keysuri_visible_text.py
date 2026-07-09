"""Tests for visible text serialization helpers."""
from __future__ import annotations

import unittest

from keysuri_visible_text import (
    build_visible_selection_reason,
    coerce_visible_lines,
    contains_duplicate_watch_arrows,
    contains_internal_owner_copy_leaks,
    contains_korea_impact_phrase_issues,
    contains_visible_repr_artifacts,
    contains_visible_snake_case_token,
    dedupe_sentences_in_paragraph,
    korea_checkpoint_strategy_too_generic,
    normalize_visible_text,
    polish_korea_checkpoint_text,
    repair_obvious_korean_quality_artifacts,
    render_visible_lines,
    sanitize_visible_impact_line,
    strip_watch_arrow_prefixes,
)


class KeysuriVisibleTextTests(unittest.TestCase):
    def test_list_next_watch_renders_clean_watch_lines(self) -> None:
        raw = ["삼성 HBM4 일정", "엔비디아 후속 발표"]
        out = render_visible_lines(raw, style="watch")
        self.assertIn("→ 삼성 HBM4 일정", out)
        self.assertIn("→ 엔비디아 후속 발표", out)
        self.assertNotIn("['", out)

    def test_stringified_list_next_watch_parses(self) -> None:
        raw = "['삼성 HBM4 일정', '엔비디아 후속 발표']"
        out = render_visible_lines(raw, style="watch")
        self.assertIn("삼성 HBM4 일정", out)
        self.assertNotIn("['", out)

    def test_uncertainty_list_renders_sentence_style(self) -> None:
        raw = ["GPU 공급 규모 미확정", "양산 일정 불명확"]
        out = normalize_visible_text(raw, style="sentence")
        self.assertIn("GPU 공급 규모 미확정", out)
        self.assertNotIn("['", out)

    def test_legitimate_quote_inside_sentence_allowed(self) -> None:
        raw = "정부는 'AI 팩토리' 도입을 검토 중입니다."
        out = normalize_visible_text(raw)
        self.assertIn("'AI 팩토리'", out)
        self.assertFalse(contains_visible_repr_artifacts(out))

    def test_repr_artifacts_detected(self) -> None:
        self.assertTrue(contains_visible_repr_artifacts("['A', 'B']"))
        self.assertTrue(contains_visible_repr_artifacts("&#x27;, &#x27;"))
        self.assertFalse(contains_visible_repr_artifacts("내일 영향: 정책 신호"))

    def test_coerce_visible_lines_from_dict_prefers_text_key(self) -> None:
        lines = coerce_visible_lines({"text": "국내 적용 포인트"})
        self.assertEqual(lines, ["국내 적용 포인트"])

    def test_internal_selection_reason_detected(self) -> None:
        raw = "국내 총점 60점(구조 7, 실행 13, 국내관련 +10). 태그: korean_entity_mention."
        self.assertTrue(contains_internal_owner_copy_leaks(raw))

    def test_build_visible_selection_reason_from_tags(self) -> None:
        item = {"korean_title": "삼성전자·엔비디아 HBM4 협력"}
        meta = {
            "primary_category": "korea_semiconductor",
            "selection_reason_tags": ["korean_entity_mention", "industrial_signal"],
            "reason_for_selection": "국내 총점 60점(구조 7, 실행 13, 국내관련 +10). 태그: korean_entity_mention.",
        }
        out = build_visible_selection_reason(item, meta, program_id="keysuri_korea_tech")
        self.assertNotIn("국내 총점", out)
        self.assertNotIn("태그:", out)
        self.assertNotIn("korean_entity_mention", out)
        self.assertIn("공급망", out)

    def test_global_selection_reason_replaces_internal_numeric_score(self) -> None:
        item = {
            "korean_title": "구글, 풀스택 AI 에이전트 전략 공개",
            "primary_category": "ai_software_platform",
            "selection_reason": "총점 54점을 기록했으며 AI 플랫폼 변화와 연결됩니다.",
        }

        out = build_visible_selection_reason(item, {}, program_id="keysuri_global_tech")

        self.assertIn("AI·소프트웨어·플랫폼", out)
        for forbidden in ("총점", "점수", "스코어", "score", "scoring", "기록했으며"):
            self.assertNotIn(forbidden, out.lower() if forbidden in ("score", "scoring") else out)

    def test_repair_obvious_korean_quality_artifact_repeated_token(self) -> None:
        raw = "이 흐름은 국내 산업에 어떤 영향을 미 미칠 것인가?"
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertEqual(out, "이 흐름은 국내 산업에 어떤 영향을 미칠 것인가?")
        self.assertNotIn("미 미칠", out)

    def test_repair_obvious_korean_quality_artifact_keeps_legitimate_phrase(self) -> None:
        raw = "이 이슈는 주인님께 먼저 확인하실 만한 신호입니다."
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertEqual(out, raw)

    def test_repair_fixes_orphan_possessive_before_business_domain(self) -> None:
        for raw, expected_prefix in (
            ("의 사업 영역에서도 변화가 예상됩니다.", "주인님의 사업 영역에서도"),
            ("의 사업 분야에 곧바로 영향을 줍니다.", "주인님의 사업 분야에"),
        ):
            with self.subTest(raw=raw):
                out = repair_obvious_korean_quality_artifacts(raw)
                self.assertTrue(out.startswith(expected_prefix), out)

    def test_repair_keeps_legitimate_possessive_before_business_domain(self) -> None:
        raw = "삼성전자의 사업 영역은 반도체와 가전으로 나뉩니다."
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertEqual(out, raw)
        self.assertNotIn("주인님의 사업 영역", out)

    def test_repair_removes_stray_owner_address_before_bigtech_noun(self) -> None:
        raw = "주인님 빅테크 기업들의 투자 전략이 바뀌고 있습니다."
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertEqual(out, "빅테크 기업들의 투자 전략이 바뀌고 있습니다.")
        self.assertNotIn("주인님 빅테크", out)

    def test_repair_normalizes_missing_thousands_comma_in_amount(self) -> None:
        raw = "이번 계약 규모는 1억 7 500만 달러로 추정됩니다."
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertIn("1억 7,500만 달러", out)
        self.assertNotIn("7 500만", out)

    def test_repair_amount_comma_fix_does_not_touch_unrelated_numbers(self) -> None:
        raw = "지난해 3분기 매출은 전년 대비 4% 증가했습니다."
        out = repair_obvious_korean_quality_artifacts(raw)
        self.assertEqual(out, raw)

    def test_sanitize_visible_impact_line_removes_signal_signal(self) -> None:
        raw = "글로벌→한국 번역 신호 신호가 의사결정·미팅 우선순위에 반영될 수 있습니다."
        out = sanitize_visible_impact_line(raw, category="global_to_korea_translation")
        self.assertNotIn("신호 신호", out)
        self.assertIn("글로벌 발표", out)

    def test_startup_impact_fallback_has_no_nuclear_bleed(self) -> None:
        out = sanitize_visible_impact_line(
            "스타트업 / 투자 신호가 의사결정·미팅 우선순위에 반영될 수 있습니다.",
            category="korea_startup_investment",
        )
        self.assertNotIn("원자력", out)
        self.assertNotIn("딥테크", out)
        self.assertTrue(out)

    def test_strip_watch_arrow_prefixes(self) -> None:
        raw = "→ → 삼성 일정; → 엔비디아 후속"
        out = strip_watch_arrow_prefixes(raw)
        self.assertNotIn("→ →", out)
        self.assertIn("삼성 일정", out)

    def test_dedupe_sentences_in_paragraph(self) -> None:
        sent = "젠슨 황 CEO의 발언은 시사합니다. 젠슨 황 CEO의 발언은 시사합니다."
        out = dedupe_sentences_in_paragraph(sent)
        self.assertEqual(out.count("젠슨 황 CEO의 발언은 시사합니다."), 1)

    def test_snake_case_allowlist_for_verification_status(self) -> None:
        self.assertFalse(contains_visible_snake_case_token("live_fetch / not_verified"))

    def test_snake_case_flags_internal_tag(self) -> None:
        self.assertTrue(contains_visible_snake_case_token("policy_capital_signal"))

    def test_impact_phrase_duplicate_detected(self) -> None:
        self.assertTrue(contains_korea_impact_phrase_issues("신호 신호가 반영"))
        self.assertTrue(contains_duplicate_watch_arrows("→ → A"))

    def test_polish_korea_checkpoint_adds_investment_lens(self) -> None:
        raw = (
            "주인님, 엔비디아 젠슨 황 CEO의 방한은 국내 AI·반도체 산업에 대한 "
            "글로벌 시장의 높은 기대감을 보여주었습니다. "
            "HBM, 파운드리, AI 투자 기회를 중심으로 내일의 사업 전략을 구체화하십시오."
        )
        out = polish_korea_checkpoint_text(raw)
        self.assertIn("내일의 투자 및 사업 전략을 구체화하십시오", out)
        self.assertNotIn("투자 및 투자 및", out)

    def test_polish_korea_checkpoint_idempotent(self) -> None:
        polished = polish_korea_checkpoint_text("내일의 투자 및 사업 전략을 구체화하십시오.")
        self.assertEqual(polished, "내일의 투자 및 사업 전략을 구체화하십시오.")

    def test_polish_korea_checkpoint_review_variant(self) -> None:
        out = polish_korea_checkpoint_text("사업 전략을 점검하십시오.")
        self.assertEqual(out, "투자 및 사업 전략을 점검하십시오.")

    def test_polish_korea_checkpoint_recheck_variant(self) -> None:
        raw = (
            "HBM 기술 경쟁을 중심으로 내일의 사업 전략을 재점검하십시오."
        )
        out = polish_korea_checkpoint_text(raw)
        self.assertIn("내일의 투자 및 사업 전략을 재점검하십시오", out)

    def test_korea_checkpoint_generic_detector(self) -> None:
        self.assertTrue(korea_checkpoint_strategy_too_generic("내일의 사업 전략을 구체화하십시오."))
        self.assertFalse(
            korea_checkpoint_strategy_too_generic("내일의 투자 및 사업 전략을 구체화하십시오.")
        )


if __name__ == "__main__":
    unittest.main()
