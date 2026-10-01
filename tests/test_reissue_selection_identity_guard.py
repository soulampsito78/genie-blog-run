import unittest
from unittest.mock import patch

from tests.test_service_full_run import _briefing_for_live_items, _live_reselection_items

from keysuri_service_full_run import (
    _repair_reissue_top5_from_live_selection,
    KEYSURI_TOP_NEWS_COUNT,
)


class ReissueSelectionIdentityGuardTest(unittest.TestCase):
    def test_real_correlation_rejects_old_narrative_under_new_articles(self):
        live_items = _live_reselection_items(prefix="fresh-selection")
        old_items = _live_reselection_items(prefix="old-selection")
        generated = _briefing_for_live_items(old_items)
        generated["briefing_display"]["opening_lead"] = "기존 기사에 대한 도입부입니다."
        generated["deep_dive"]["body"] = "기존 기사에 대한 딥다이브입니다."
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "source_pack": {"program_id": "keysuri_global_tech", "sources": [], "claims": []},
            "top_5_news": {"items": live_items},
        }
        prompt, briefing, fields, reason = _repair_reissue_top5_from_live_selection(
            generated_briefing=generated, prompt_input=prompt_input,
            program_id="keysuri_global_tech",
            parent={"regen_generated_briefing_snapshot": generated},
        )
        self.assertIsNone(prompt)
        self.assertIsNone(briefing)
        self.assertEqual(reason, "reissue_top5_identity_unbound")
        self.assertEqual(fields["reissue_correlation_matched_count"], 0)
        self.assertTrue(fields["reissue_correlation_batch_identity_conflict"])
        self.assertFalse(fields["reissue_correlation_positional_used"])

    def _make_items(self, urls):
        return [
            {"news_id": f"id_{i}", "canonical_url": url, "source_url": url, "title": f"Title {i}"}
            for i, url in enumerate(urls)
        ]

    @patch("keysuri_service_full_run._live_selection_items_from_prompt_input")
    @patch("keysuri_service_full_run._parent_base_briefing_for_reissue")
    @patch("keysuri_service_full_run._compose_reissue_top5_visible_items")
    def test_changed_parent_and_zero_matched_rejected(self, mock_compose, mock_parent_base, mock_live):
        live_items = self._make_items([f"https://example.com/live_{i}" for i in range(KEYSURI_TOP_NEWS_COUNT)])
        parent_items = self._make_items([f"https://example.com/parent_{i}" for i in range(KEYSURI_TOP_NEWS_COUNT)])
        mock_live.return_value = live_items
        mock_parent_base.return_value = {"top_5_news": {"items": parent_items}}
        mock_compose.return_value = (live_items, [], True, {
            "reissue_correlation_matched_count": 0,
            "reissue_correlation_batch_identity_conflict": True,
        })
        prompt, briefing, fields, reason = _repair_reissue_top5_from_live_selection(
            generated_briefing={"top_5_news": {"items": live_items}},
            prompt_input={"top_5_news": {"items": live_items}},
            program_id="keysuri_korea_tech", parent={"snapshot": True},
        )
        self.assertIsNone(prompt)
        self.assertIsNone(briefing)
        self.assertEqual(reason, "reissue_top5_identity_unbound")
        self.assertTrue(fields.get("reissue_top5_identity_unbound"))
        self.assertEqual(mock_compose.call_count, 1)

    @patch("keysuri_service_full_run._live_selection_items_from_prompt_input")
    @patch("keysuri_service_full_run._parent_base_briefing_for_reissue")
    @patch("keysuri_service_full_run._compose_reissue_top5_visible_items")
    def test_unknown_parent_identity_excluded(self, mock_compose, mock_parent_base, mock_live):
        items = self._make_items([f"https://example.com/live_{i}" for i in range(KEYSURI_TOP_NEWS_COUNT)])
        mock_live.return_value = items
        mock_parent_base.return_value = {"top_5_news": {"items": [{"title": "no url"}]}}
        mock_compose.return_value = (items, [], True, {})
        prompt, briefing, fields, reason = _repair_reissue_top5_from_live_selection(
            generated_briefing={"top_5_news": {"items": items}},
            prompt_input={"top_5_news": {"items": items}},
            program_id="keysuri_korea_tech", parent={"snapshot": True},
        )
        self.assertIsNone(prompt)
        self.assertEqual(reason, "reissue_top5_identity_unbound")
        self.assertEqual(mock_compose.call_count, 1)

    @patch("keysuri_service_full_run._live_selection_items_from_prompt_input")
    @patch("keysuri_service_full_run._parent_base_briefing_for_reissue")
    @patch("keysuri_service_full_run._compose_reissue_top5_visible_items")
    def test_valid_same_url_parent_fallback_allowed(self, mock_compose, mock_parent_base, mock_live):
        items = self._make_items([f"https://example.com/same_{i}" for i in range(KEYSURI_TOP_NEWS_COUNT)])
        mock_live.return_value = items
        mock_parent_base.return_value = {"top_5_news": {"items": items}}
        mock_compose.side_effect = [
            (items, [], True, {"reissue_correlation_matched_count": 0}),
            (items, [], False, {"reissue_correlation_matched_count": KEYSURI_TOP_NEWS_COUNT}),
        ]
        with patch("keysuri_service_full_run.reissue_top5_content_issue_codes", return_value=[]), \
             patch("keysuri_service_full_run._rewrite_briefing_sources_to_items", side_effect=lambda b, it: b), \
             patch("keysuri_service_full_run._build_repaired_reissue_payload", return_value=({"prompt": True}, {"briefing": True}, [])):
            prompt, briefing, fields, reason = _repair_reissue_top5_from_live_selection(
                generated_briefing={"top_5_news": {"items": items}},
                prompt_input={"top_5_news": {"items": items}},
                program_id="keysuri_korea_tech", parent={"snapshot": True},
            )
            self.assertIsNotNone(prompt)
            self.assertIsNone(reason)
            self.assertEqual(mock_compose.call_count, 2)

    @patch("keysuri_service_full_run._live_selection_items_from_prompt_input")
    @patch("keysuri_service_full_run._compose_reissue_top5_visible_items")
    def test_valid_five_matched_gemini_success(self, mock_compose, mock_live):
        items = self._make_items([f"https://example.com/ok_{i}" for i in range(KEYSURI_TOP_NEWS_COUNT)])
        mock_live.return_value = items
        mock_compose.return_value = (items, [], False, {"reissue_correlation_matched_count": KEYSURI_TOP_NEWS_COUNT})
        with patch("keysuri_service_full_run.reissue_top5_content_issue_codes", return_value=[]), \
             patch("keysuri_service_full_run._build_repaired_reissue_payload", return_value=({"prompt": True}, {"briefing": True}, [])):
            prompt, briefing, fields, reason = _repair_reissue_top5_from_live_selection(
                generated_briefing={"top_5_news": {"items": items}},
                prompt_input={"top_5_news": {"items": items}},
                program_id="keysuri_korea_tech",
            )
            self.assertIsNotNone(prompt)
            self.assertIsNone(reason)
