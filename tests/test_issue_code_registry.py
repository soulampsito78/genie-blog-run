"""Completeness and classify_repairability checks for issue_code_registry."""
from __future__ import annotations

import unittest

from issue_code_registry import (
    HARD_BLOCK_CODES,
    ISSUE_CODE_REGISTRY,
    REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
    REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
    REPAIRABILITY_TERMINAL_BLOCK,
    SEVERITY_BLOCK,
    classify_repairability,
    get_issue_code,
)


class IssueCodeRegistryTests(unittest.TestCase):
    def test_01_registry_non_empty_unique_codes(self) -> None:
        self.assertGreaterEqual(len(ISSUE_CODE_REGISTRY), 10)
        codes = [e.code for e in ISSUE_CODE_REGISTRY]
        self.assertEqual(len(codes), len(set(codes)))

    def test_02_hard_block_codes_match_block_severity(self) -> None:
        expected = {e.code for e in ISSUE_CODE_REGISTRY if e.severity == SEVERITY_BLOCK}
        self.assertEqual(set(HARD_BLOCK_CODES), expected)
        self.assertIsInstance(HARD_BLOCK_CODES, frozenset)

    def test_03_required_codes_present(self) -> None:
        required = {
            "keysuri_korean_connector_ellipsis_blocked",
            "gemini_json_missing_required_keys",
            "top_5_news_missing",
            "deep_dive_missing",
            "global_visible_text_truncated_deep_dive",
            "korea_visible_text_truncated_follow_item",
            "customer_send_ambiguity_blocked",
            "smtp_outcome_ambiguous",
            "invalid_natural_slot_match",
            "invalid_natural_slot_duplicate_match",
        }
        present = {e.code for e in ISSUE_CODE_REGISTRY}
        missing = required - present
        self.assertFalse(missing, f"missing required registry codes: {sorted(missing)}")

    def test_04_classify_known_repairability(self) -> None:
        self.assertEqual(
            classify_repairability("keysuri_korean_connector_ellipsis_blocked"),
            REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        )
        self.assertEqual(
            classify_repairability("gemini_json_missing_required_keys"),
            REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        )
        self.assertEqual(
            classify_repairability("top_5_news_missing"),
            REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE,
        )
        self.assertEqual(
            classify_repairability("global_visible_text_truncated_deep_dive"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )
        self.assertEqual(
            classify_repairability("korea_visible_text_truncated_follow_item"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )
        self.assertEqual(
            classify_repairability("smtp_outcome_ambiguous"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )
        self.assertEqual(
            classify_repairability("customer_send_ambiguity_blocked"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )
        self.assertEqual(
            classify_repairability("invalid_natural_slot_match"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )
        self.assertEqual(
            classify_repairability("top_5_item_count_invalid"),
            REPAIRABILITY_MODEL_CORRECTIVE_RETRY,
        )

    def test_05_unknown_code_fails_closed_terminal(self) -> None:
        self.assertEqual(
            classify_repairability("totally_unknown_issue_code_xyz"),
            REPAIRABILITY_TERMINAL_BLOCK,
        )

    def test_06_entry_fields_populated(self) -> None:
        entry = get_issue_code("keysuri_korean_connector_ellipsis_blocked")
        assert entry is not None
        self.assertEqual(entry.program, "shared")
        self.assertTrue(entry.stage)
        self.assertEqual(entry.severity, SEVERITY_BLOCK)
        self.assertEqual(entry.repairability, REPAIRABILITY_DETERMINISTICALLY_REPAIRABLE)
        self.assertTrue(entry.notes)


if __name__ == "__main__":
    unittest.main()
