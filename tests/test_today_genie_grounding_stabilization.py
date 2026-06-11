"""Tests for deterministic today_genie grounding stabilization (TOP3, image, vague phrase)."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from main import (
    stabilize_today_genie_image_prompt_anchors,
    stabilize_today_genie_top3_grounding,
    stabilize_today_genie_vague_phrases,
)
from publishing_policy import decide_publishing_actions
from today_genie_grounding import text_covers_headline_entities
from today_genie_top3_assembly import assemble_key_watchpoints_from_slots
from validators import (
    _body_underuses_news_when_feeds_full,
    _polish_vague_phrase_issues,
    _validate_image_prompts_news_anchoring,
    _validate_top_three_news_briefing,
)


def _sample_runtime_input() -> dict:
    news = [
        {
            "headline": "Seoul shares close at new high on tech rally, Mideast optimism",
            "source": "Yonhap",
            "date": "2026-05-29",
        },
        {
            "headline": "S&P 500 and Nasdaq close at new records, lifted by tech rally",
            "source": "CNBC",
            "date": "2026-05-29",
        },
        {
            "headline": "Japan's Nikkei scales record peak on Mideast, AI optimism",
            "source": "Reuters",
            "date": "2026-05-29",
        },
    ]
    return {
        "target_date": "2026-05-30",
        "input_feed_status": "full",
        "top_market_news": news,
        "overnight_us_market": {
            "as_of": "2026-05-29",
            "summary": "US indexes closed at records.",
        },
        "macro_indicators": {"as_of": "2026-05-29", "headline": "May inflation narrative."},
        "risk_factors": [{"risk": "Geopolitics", "detail": "Oil and ceasefire headlines."}],
    }


def _korean_only_slots() -> list[dict]:
    return [
        {
            "slot": 1,
            "headline_ko": "코스피 사상 최고치",
            "what_happened": "한국 증시가 AI 관련 종목 강세와 중동 휴전 기대감 속에서 사상 최고치를 경신하며 마감했습니다.",
            "why_it_matters_today": "오늘 장전에는 같은 수급 축이 선물과 현물 시가에 반영될 가능성이 큽니다.",
            "what_to_watch_in_korea": "코스피 선물 베이시스와 외국인·기관 순매수를 먼저 확인합니다.",
        },
        {
            "slot": 2,
            "headline_ko": "미국 증시 사상 최고치",
            "what_happened": "미국 주요 지수가 기술주 랠리에 힘입어 사상 최고치로 마감했습니다.",
            "why_it_matters_today": "오늘 장전에는 야간 흐름이 국내 대형주와 성장주에 다르게 전달될 수 있습니다.",
            "what_to_watch_in_korea": "코스피·코스닥 시가와 프로그램 매매 방향을 함께 봅니다.",
        },
        {
            "slot": 3,
            "headline_ko": "니케이 신기록",
            "what_happened": "일본 증시가 지정학적 우려 완화와 AI 낙관론 속에서 사상 최고치를 기록했습니다.",
            "why_it_matters_today": "오늘 장전에는 아시아 투자 심리와 환율 톤을 함께 점검할 필요가 있습니다.",
            "what_to_watch_in_korea": "원/달러와 아시아 선물 연동을 확인합니다.",
        },
    ]


class TodayGenieGroundingStabilizationTests(unittest.TestCase):
    def test_korean_only_slots_get_entity_grounding_anchors(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        self.assertEqual(len(wps), 3)
        from today_genie_top3_assembly import collect_valid_major_overseas_news

        headlines = [item.get("headline", "") for _, item in collect_valid_major_overseas_news(ri, 3)]
        sp_nasdaq = "S&P 500 and Nasdaq close at new records, lifted by tech rally"
        self.assertIn(sp_nasdaq, headlines)
        slot2 = wps[1]["detail"]
        self.assertIn("S&P 500", slot2)
        self.assertIn("Nasdaq", slot2)
        self.assertIn("원문 지표 기준:", slot2)
        for wp, nh in zip(wps, headlines):
            detail = wp.get("detail", "")
            self.assertTrue(text_covers_headline_entities(detail, nh), nh)

    def test_conflicting_model_text_does_not_remove_anchor(self) -> None:
        ri = _sample_runtime_input()
        slots = _korean_only_slots()
        slots[0]["what_happened"] = "완전히 다른 이슈만 서술하는 한국어 문장입니다." * 2
        wps = assemble_key_watchpoints_from_slots(slots, ri)
        detail = wps[0]["detail"]
        self.assertIn("원문 지표 기준:", detail)
        self.assertTrue(
            text_covers_headline_entities(
                detail,
                "Seoul shares close at new high on tech rally, Mideast optimism",
            )
        )

    def test_top3_validator_clears_after_anchor_injection(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        issues = _validate_top_three_news_briefing(ri, {"key_watchpoints": wps})
        codes = [i.code for i in issues]
        self.assertNotIn("top3_not_grounded_in_input_news", codes)

    def test_sp_nasdaq_slot_passes_validator_specifically(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        nh = ri["top_market_news"][1]["headline"]
        self.assertIn("S&P 500", wps[1]["detail"])
        self.assertIn("Nasdaq", wps[1]["detail"])
        self.assertTrue(text_covers_headline_entities(wps[1]["detail"], nh))

    def test_image_prompts_receive_feed_anchors_when_missing(self) -> None:
        ri = _sample_runtime_input()
        data = {
            "image_prompt_studio": "Professional Korean financial anchor in studio.",
            "image_prompt_outdoor": "Same anchor outdoors in Seoul park, sunny morning.",
        }
        out = stabilize_today_genie_image_prompt_anchors(data, ri)
        studio = out["image_prompt_studio"].lower()
        self.assertIn("include subtle visual references to:", studio)
        self.assertIn("nasdaq", studio)
        self.assertIn("s&p 500", studio)
        issues = _validate_image_prompts_news_anchoring(ri, out)
        codes = [i.code for i in issues]
        self.assertNotIn("image_prompt_underanchored_vs_news", codes)

    def test_vague_phrase_scrubbed_from_summary(self) -> None:
        data = {
            "summary": "시장은 혼조세를 보였으며 투자자들은 향후 방향성을 가늠하기 위해 지표를 봅니다.",
            "market_setup": "지수 흐름을 점검합니다.",
        }
        out = stabilize_today_genie_vague_phrases(data)
        self.assertNotIn("방향성을 가늠", out["summary"])
        issues = _polish_vague_phrase_issues(out)
        codes = [i.code for i in issues]
        self.assertNotIn("polish_vague_meta_phrase", codes)

    def test_unanchored_briefing_likely_clears_with_top3_anchors(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        data = {
            "summary": "국내 증시는 장전 변동성에 주목합니다.",
            "market_setup": "미국 증시는 사상 최고치를 경신했습니다.",
            "key_watchpoints": wps,
        }
        from validators import _joined_today_editorial_text

        all_text = _joined_today_editorial_text(data)
        self.assertFalse(_body_underuses_news_when_feeds_full(ri, all_text))


def _june8_runtime_input() -> dict:
    return {
        "target_date": "2026-06-11",
        "input_feed_status": "full",
        "top_market_news": [
            {
                "date": "2026-06-08",
                "headline": "OpenAI confidentially files for IPO, prepping Wall Street for mega AI debut",
            },
            {
                "date": "2026-06-08",
                "headline": "Trump nominates Todd Blanche for attorney general amid controversy over DOJ fund",
            },
            {
                "date": "2026-06-08",
                "headline": "Netanyahu says war with Iran, Hezbollah isn't over after Tehran says it's halting strikes",
            },
        ],
        "overnight_us_market": {
            "as_of": "2026-06-08",
            "summary": "US markets steady into Asia open.",
            "indices": {"SPX": {"close": 6000.0, "change_pct": 0.1}},
        },
        "macro_indicators": {"as_of": "2026-06-08", "headline": "Macro watch"},
        "risk_factors": [{"risk": "Geopolitics", "detail": "Middle East tension"}],
    }


def _june8_korean_slots() -> list[dict]:
    return [
        {
            "slot": 1,
            "headline_ko": "오픈AI IPO 추진",
            "what_happened": "오픈AI가 기밀 제출 방식으로 상장을 준비하며 월가의 관심이 커지고 있습니다.",
            "why_it_matters_today": "오늘 장전에는 AI 관련 대형주와 반도체 수급이 함께 점검될 수 있습니다.",
            "what_to_watch_in_korea": "코스피 시가와 외국인 순매수를 먼저 확인합니다.",
        },
        {
            "slot": 2,
            "headline_ko": "미국 법무장관 인선",
            "what_happened": "트럼프 행정부가 법무장관 후보를 지명하며 정치적 논란이 이어지고 있습니다.",
            "why_it_matters_today": "오늘 장전에는 정책 불확실성이 리스크 자산에 미치는 영향을 봅니다.",
            "what_to_watch_in_korea": "환율과 채권 금리 반응을 확인합니다.",
        },
        {
            "slot": 3,
            "headline_ko": "중동 긴장 지속",
            "what_happened": "이스라엘과 이란·헤즈볼라 갈등이 완전히 끝나지 않았다는 신호가 이어지고 있습니다.",
            "why_it_matters_today": "오늘 장전에는 유가와 지정학 리스크 프리미엄을 함께 봅니다.",
            "what_to_watch_in_korea": "원/달러와 유가 연동을 확인합니다.",
        },
    ]


class TodayGenieJune8FeedGroundingTests(unittest.TestCase):
    def test_june8_top3_grounding_clears_validator(self) -> None:
        ri = _june8_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_june8_korean_slots(), ri)
        data = stabilize_today_genie_top3_grounding({"key_watchpoints": wps}, ri)
        issues = _validate_top_three_news_briefing(ri, data)
        codes = [i.code for i in issues]
        self.assertNotIn("top3_not_grounded_in_input_news", codes)

    def test_june8_image_prompts_receive_news_anchors(self) -> None:
        ri = _june8_runtime_input()
        data = {
            "image_prompt_studio": "Professional Korean financial anchor in studio.",
            "image_prompt_outdoor": "Same anchor outdoors in Seoul, morning light.",
        }
        out = stabilize_today_genie_image_prompt_anchors(data, ri)
        studio = out["image_prompt_studio"].lower()
        self.assertIn("trump", studio)
        self.assertIn("iran", studio)
        issues = _validate_image_prompts_news_anchoring(ri, out)
        codes = [i.code for i in issues]
        self.assertNotIn("image_prompt_underanchored_vs_news", codes)

    def test_email_policy_still_blocks_validation_block(self) -> None:
        decision = decide_publishing_actions("today_genie", "block", "review_required", [], _june8_runtime_input())
        self.assertFalse(decision.send_email)

    def test_email_policy_allows_owner_send_on_pass_with_gate(self) -> None:
        os.environ["GENIE_OWNER_REVIEW_SEND"] = "1"
        os.environ["EMAIL_TO"] = "soulampsito@gmail.com,ey2133@naver.com"
        try:
            decision = decide_publishing_actions(
                "today_genie",
                "pass",
                "validated",
                [],
                _june8_runtime_input(),
            )
            self.assertTrue(decision.send_email)
        finally:
            os.environ.pop("GENIE_OWNER_REVIEW_SEND", None)
            os.environ.pop("EMAIL_TO", None)

    def test_stale_feed_date_still_enforced(self) -> None:
        from validators import _today_stale_date_issues

        runtime = {
            "target_date": "2026-06-11",
            "overnight_us_market": {"as_of": "2026-06-08"},
            "korea_japan_indices": {"as_of": "2026-05-29"},
            "macro_indicators": {"as_of": "2026-05-29"},
        }
        issues = _today_stale_date_issues({}, runtime)
        codes = [i.code for i in issues]
        self.assertIn("stale_feed_date", codes)

    def test_ungrounded_top3_still_blocked(self) -> None:
        ri = _june8_runtime_input()
        wps = [
            {
                "headline": "무관한 이슈",
                "detail": "전혀 다른 주제만 반복합니다. " * 4,
                "basis": "fact",
            }
            for _ in range(3)
        ]
        issues = _validate_top_three_news_briefing(ri, {"key_watchpoints": wps})
        codes = [i.code for i in issues]
        self.assertIn("top3_not_grounded_in_input_news", codes)


if __name__ == "__main__":
    unittest.main()
