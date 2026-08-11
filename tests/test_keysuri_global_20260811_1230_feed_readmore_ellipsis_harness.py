"""Harness for KeeSuri Global 12:30 feed read-more ellipsis (2026-08-11).

Natural run 20260811_123001_keysuri_global_tech_6e91b786 and four recoveries
blocked on keysuri_korean_connector_ellipsis_blocked because the NVIDIA RSS
description ended with WordPress `[…]` (U+005B U+2026 U+005D). Prior repair
treated opening-bracket…closing-bracket as non-connector residual.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from keysuri_visible_text_quality import (
    KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
    repair_korean_connector_ellipsis_text,
    sanitize_quality_sample,
    validate_and_repair_keysuri_visible_text_quality,
)

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260811_1230_keysuri_global_feed_readmore_ellipsis.json"
)
_AUG10 = (
    _REPO
    / "ops"
    / "feeds"
    / "incident_fixtures"
    / "20260810_1230_keysuri_global_dash_ellipsis.json"
)


class KeysuriGlobal20260811FeedReadmoreEllipsisHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        cls.aug10 = json.loads(_AUG10.read_text(encoding="utf-8"))

    def test_01_exact_aug11_rss_residual_repairs(self) -> None:
        text = self.fx["blocking_pattern_example"]
        self.assertIn("[…]", text)
        result = repair_korean_connector_ellipsis_text(text)
        self.assertTrue(result.found)
        self.assertTrue(result.repaired)
        self.assertFalse(result.blocked)
        self.assertNotIn("…", result.text)
        self.assertNotIn("[…]", result.text)
        self.assertIn("hands-on experiences", result.text)
        self.assertIn("GeForce NOW", result.text)

    def test_02_production_sample_window_exposes_residual(self) -> None:
        text = self.fx["blocking_pattern_example"]
        sample = sanitize_quality_sample(text)
        self.assertIn("…", sample)
        self.assertIn("[", sample)

    def test_03_payload_paths_match_production_and_pass(self) -> None:
        text = self.fx["blocking_pattern_example"]
        payload = {
            "top_5_news": {
                "items": [
                    {},
                    {},
                    {},
                    {},
                    {
                        "summary": text,
                        "what_happened": text,
                        "briefing_item": {"what_happened": text},
                    },
                ]
            },
            "deep_dive": {
                "body": (
                    "오늘 눈에 띄는 점은 Evolve your marketing 흐름과 OpenAI 이슈가 "
                    "동시에 보인다는 것입니다."
                )
            },
        }
        repaired, fields = validate_and_repair_keysuri_visible_text_quality(
            payload, root_path="generated_briefing"
        )
        self.assertEqual(fields["visible_text_quality_status"], "pass")
        self.assertTrue(fields["visible_text_ellipsis_found"])
        self.assertTrue(fields["visible_text_ellipsis_repaired"])
        self.assertFalse(fields["visible_text_ellipsis_blocked"])
        self.assertNotIn(
            KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            fields.get("visible_text_quality_issue_codes") or [],
        )
        item = repaired["top_5_news"]["items"][4]
        self.assertNotIn("…", item["summary"])
        self.assertNotIn("…", item["what_happened"])

    def test_04_aug10_dash_left_edge_regression(self) -> None:
        text = self.aug10["blocking_pattern_example"]
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        self.assertNotIn("…", result.text)
        self.assertIn("Firebird", result.text)

    def test_05_aug07_curly_quote_and_korea_closing_quote_still_pass(self) -> None:
        curly = (
            "In July.. NVIDIA joined more than 200 companies and organizations in "
            "signing “Open Weights and American AI Leadership..” as an initiative."
        )
        korea = "KDB생명 인수전, 한국투자·한화·흥국 '3파전'…삼성·교보 불참"
        for text in (curly, korea):
            result = repair_korean_connector_ellipsis_text(text)
            self.assertFalse(result.blocked, msg=text)
            self.assertNotIn("…", result.text)

    def test_06_sentence_final_and_quoted_ellipsis_remain_valid(self) -> None:
        sentence_final = "정상적인 문장 끝…"
        result = repair_korean_connector_ellipsis_text(sentence_final)
        self.assertFalse(result.blocked)
        self.assertEqual(result.text, sentence_final)

        connector = "메가딜… '미르' IP 중국계 자본 품으로"
        result = repair_korean_connector_ellipsis_text(connector)
        self.assertFalse(result.blocked)
        self.assertNotIn("…", result.text)

    def test_07_genuine_paren_truncation_remains_blocked(self) -> None:
        result = repair_korean_connector_ellipsis_text("확인 불가 (…)")
        self.assertTrue(result.blocked)
        self.assertIn("…", result.text)

    def test_08_colon_and_middle_dot_left_edges_repair(self) -> None:
        for text in (
            "World of Warships:…Legends and discover",
            "흥국·…삼성",
            "today –…Firebird launched",
        ):
            result = repair_korean_connector_ellipsis_text(text)
            self.assertFalse(result.blocked, msg=text)
            self.assertNotIn("…", result.text)


if __name__ == "__main__":
    unittest.main()
