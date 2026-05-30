"""Tests for deterministic today_genie grounding stabilization (TOP3, image, vague phrase)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from main import (
    stabilize_today_genie_image_prompt_anchors,
    stabilize_today_genie_vague_phrases,
)
from today_genie_top3_assembly import (
    _headline_grounded_in_text,
    assemble_key_watchpoints_from_slots,
)
from validators import (
    _body_underuses_news_when_feeds_full,
    _polish_vague_phrase_issues,
    _validate_image_prompts_news_anchoring,
    _validate_top_three_news_briefing,
)


def _sample_runtime_input() -> dict:
    feeds_dir = Path(__file__).resolve().parents[1] / "ops" / "feeds"
    news = json.loads((feeds_dir / "top_market_news.json").read_text(encoding="utf-8"))
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
    def test_korean_only_slots_get_input_headline_anchors(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        self.assertEqual(len(wps), 3)
        from today_genie_top3_assembly import collect_valid_major_overseas_news

        headlines = [item.get("headline", "") for _, item in collect_valid_major_overseas_news(ri, 3)]
        for wp, nh in zip(wps, headlines):
            detail = wp.get("detail", "")
            self.assertIn("Input headline anchor:", detail)
            self.assertIn(nh, detail)
            self.assertTrue(_headline_grounded_in_text(nh, detail))

    def test_conflicting_model_text_does_not_remove_anchor(self) -> None:
        ri = _sample_runtime_input()
        slots = _korean_only_slots()
        slots[0]["what_happened"] = "완전히 다른 이슈만 서술하는 한국어 문장입니다." * 2
        wps = assemble_key_watchpoints_from_slots(slots, ri)
        nh = ri["top_market_news"][0]["headline"]
        self.assertIn(nh, wps[0]["detail"])

    def test_top3_validator_clears_after_anchor_injection(self) -> None:
        ri = _sample_runtime_input()
        wps = assemble_key_watchpoints_from_slots(_korean_only_slots(), ri)
        issues = _validate_top_three_news_briefing(ri, {"key_watchpoints": wps})
        codes = [i.code for i in issues]
        self.assertNotIn("top3_not_grounded_in_input_news", codes)

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


if __name__ == "__main__":
    unittest.main()
