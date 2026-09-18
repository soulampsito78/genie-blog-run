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


if __name__ == "__main__":
    unittest.main()
