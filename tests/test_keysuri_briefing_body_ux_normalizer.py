"""Tests for Kee-Suri visible briefing body UX normalizer."""
from __future__ import annotations

import unittest

from keysuri_briefing_body_ux_normalizer import (
    limit_owner_salutation_repetition,
    normalize_generated_briefing_visible_prose,
    normalize_visible_deep_dive_text,
    remove_internal_validation_markers,
    split_long_korean_paragraphs,
)
from keysuri_briefing_content_quality import validate_briefing_content_gate


class KeysuriBriefingBodyUxNormalizerTests(unittest.TestCase):
    def test_remove_internal_validation_markers(self) -> None:
        raw = (
            "TOP 신호 1·2는 물리·인프라 층과 소프트웨어·운영 층의 움직임이 겹치는지 "
            "점검하는 데 유용합니다."
        )
        cleaned = remove_internal_validation_markers(raw)
        self.assertNotIn("TOP 신호", cleaned)
        self.assertNotIn("점검하는 데 유용합니다", cleaned)

    def test_limit_owner_salutation_repetition(self) -> None:
        raw = "주인님, 첫 문장입니다. 주인님, 둘째 문장입니다. 주인님, 셋째 문장입니다."
        limited = limit_owner_salutation_repetition(raw, max_count=2)
        self.assertLessEqual(limited.count("주인님"), 2)

    def test_split_long_korean_paragraphs(self) -> None:
        raw = "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다."
        split = split_long_korean_paragraphs(raw, max_sentences=2)
        self.assertGreaterEqual(split.count("\n\n") + 1, 2)

    def test_normalize_deep_dive_natural_signal_links(self) -> None:
        items = [
            {"korean_title": "NVIDIA partners with LG and Doosan"},
            {"korean_title": "Notion restores Anthropic access"},
        ]
        body, linked = normalize_visible_deep_dive_text(
            "TOP 신호 1·2는 점검하는 데 유용합니다.",
            items,
        )
        self.assertNotIn("TOP 신호", body)
        self.assertGreaterEqual(len(linked), 2)
        self.assertGreaterEqual(body.count("\n\n") + 1, 2)
        self.assertIn("주인님", body)

    def test_generated_briefing_normalizer_preserves_hype_caution(self) -> None:
        generated = {
            "top_5_news": {
                "items": [
                    {
                        "korean_title": "Endava software delivery case",
                        "what_happened": "요약.",
                        "why_now": "지금.",
                        "owner_angle": "관점.",
                        "hype_caution": "고객 사례 과장 주의",
                    }
                ]
            },
            "deep_dive": {"body": "짧은 본문."},
        }
        out = normalize_generated_briefing_visible_prose(
            generated,
            "keysuri_global_tech",
            {"source_pack": {}},
        )
        item = out["top_5_news"]["items"][0]
        self.assertIn("과장 주의", item.get("hype_caution", ""))

    def test_metadata_linked_signals_satisfy_deep_dive_ref_check(self) -> None:
        from keysuri_briefing_content_quality import _deep_dive_references_multiple_signals

        deep_text = "주인님, 엔비디아 흐름과 Notion 이슈를 함께 봅니다."
        ok = _deep_dive_references_multiple_signals(
            deep_text,
            top_headlines=["NVIDIA AI Factory", "Notion Anthropic"],
            source_metadata={
                "deep_dive_linked_signals": ["NVIDIA AI Factory", "Notion Anthropic"],
            },
        )
        self.assertTrue(ok)

    def test_internal_marker_fails_content_gate(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture
        from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html

        fixture = build_global_contract_fixture()
        fixture["deep_dive_body"] = (
            "주인님, TOP 신호 1·2는 점검하는 데 유용합니다. "
            "첫 문장. 둘째 문장. 셋째 문장. 넷째 문장. 다섯째 문장."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=__import__("pathlib").Path(__file__).resolve().parent.parent)
        metadata = {
            "global_top5_selection": {"policy": "v2"},
            "claims": [{"selection_score": 70, "selection_rationale": "test", "primary_category": "semiconductor_chip_infra"}] * 5,
        }
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertTrue(
            any(i.code == "internal_validation_marker_visible" for i in result.issues),
            [i.code for i in result.issues],
        )


if __name__ == "__main__":
    unittest.main()
