"""A prose-only reissue must generate against the parent's exact TOP5."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import keysuri_service_full_run as runner


class FrozenParentPromptTests(unittest.TestCase):
    def _parent(self) -> dict:
        items = [
            {
                "rank": rank,
                "news_id": f"parent-news-{rank}",
                "headline": f"Parent headline {rank}",
                "summary": f"Parent summary {rank}",
                "source_ids": [f"parent-source-{rank}"],
            }
            for rank in range(1, 6)
        ]
        source_pack = {
            "program_id": "keysuri_global_tech",
            "sources": [{"source_id": f"parent-source-{rank}"} for rank in range(1, 6)],
            "claims": [],
        }
        return {
            "program_id": "keysuri_global_tech",
            "selected_items": items,
            "regen_source_pack_snapshot": source_pack,
            "regen_prompt_input_snapshot": {
                "program_id": "keysuri_global_tech",
                "prompt_status": "ready_for_generation",
                "top_5_news": {"items": copy.deepcopy(items)},
                "source_pack": copy.deepcopy(source_pack),
            },
        }

    def test_uses_saved_selection_without_reselecting_against_current_logs(self) -> None:
        parent = self._parent()
        with patch.object(runner, "build_keysuri_prompt_input", side_effect=AssertionError("reselected")):
            prompt_input, error = runner._regen_prompt_input_from_parent(
                parent, "keysuri_global_tech"
            )
        self.assertIsNone(error)
        self.assertEqual(
            [item["news_id"] for item in prompt_input["top_5_news"]["items"]],
            [item["news_id"] for item in parent["selected_items"]],
        )
        prompt_input["top_5_news"]["items"][0]["news_id"] = "mutated"
        self.assertEqual(
            parent["regen_prompt_input_snapshot"]["top_5_news"]["items"][0]["news_id"],
            "parent-news-1",
        )

    def test_mismatched_saved_selection_fails_closed(self) -> None:
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["top_5_news"]["items"][0]["news_id"] = "other-news"
        prompt_input, error = runner._regen_prompt_input_from_parent(
            parent, "keysuri_global_tech"
        )
        self.assertIsNone(prompt_input)
        self.assertEqual(error, "regen_parent_prompt_selection_mismatch")

    def test_missing_saved_prompt_fails_closed(self) -> None:
        parent = self._parent()
        del parent["regen_prompt_input_snapshot"]
        prompt_input, error = runner._regen_prompt_input_from_parent(
            parent, "keysuri_global_tech"
        )
        self.assertIsNone(prompt_input)
        self.assertEqual(error, "regen_missing_parent_prompt_snapshot")

    def test_wrong_program_or_unready_snapshot_fails_closed(self) -> None:
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["program_id"] = "keysuri_korea_tech"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_prompt_program_mismatch",
        )
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["prompt_status"] = "hold_review_required"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_prompt_not_ready",
        )
        parent = self._parent()
        parent["regen_source_pack_snapshot"]["program_id"] = "keysuri_korea_tech"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_source_pack_program_mismatch",
        )

    def test_exact_generated_top5_keeps_new_korean_item_prose(self) -> None:
        parent = self._parent()
        generated_items = copy.deepcopy(parent["selected_items"])
        generated_items[0]["korean_title"] = "새로 다듬은 한국어 제목"
        generated = {"top_5_news": {"items": generated_items}}

        def accept_payload(**kwargs):
            return kwargs["prompt_input"], kwargs["base_briefing"], []

        with patch.object(runner, "_build_repaired_reissue_payload", side_effect=accept_payload):
            _prompt, briefing, fields, error = runner._repair_reissue_top5_from_parent_selection(
                generated_briefing=generated,
                prompt_input=parent["regen_prompt_input_snapshot"],
                parent=parent,
                program_id="keysuri_global_tech",
                strict_frozen_parent=True,
            )
        self.assertIsNone(error)
        self.assertEqual(fields["reissue_top5_repair_source"], "gemini_output_exact_parent_top5")
        self.assertEqual(
            briefing["top_5_news"]["items"][0]["korean_title"],
            "새로 다듬은 한국어 제목",
        )

    def test_different_generated_top5_never_mix_with_new_narrative(self) -> None:
        parent = self._parent()
        parent["regen_generated_briefing_snapshot"] = {
            "top_5_news": {"items": copy.deepcopy(parent["selected_items"])},
            "deep_dive": {},
            "one_line_checkpoint": {},
            "closing_sources": {},
        }
        generated_items = copy.deepcopy(parent["selected_items"])
        generated_items[0]["news_id"] = "unrelated-news"
        generated = {"top_5_news": {"items": generated_items}, "deep_dive": {"body": "unrelated"}}

        def accept_payload(**kwargs):
            return kwargs["prompt_input"], kwargs["base_briefing"], []

        with patch.object(runner, "_build_repaired_reissue_payload", side_effect=accept_payload) as build:
            _prompt, briefing, fields, error = runner._repair_reissue_top5_from_parent_selection(
                generated_briefing=generated,
                prompt_input=parent["regen_prompt_input_snapshot"],
                parent=parent,
                program_id="keysuri_global_tech",
                strict_frozen_parent=True,
            )
        self.assertIsNone(error)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(fields["reissue_top5_repair_source"], "parent_generated_briefing_snapshot")
        self.assertNotEqual(briefing["deep_dive"].get("body"), "unrelated")


if __name__ == "__main__":
    unittest.main()
