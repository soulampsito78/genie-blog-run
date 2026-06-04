"""Tests for Kee-Suri generated briefing adapter contract."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from keysuri_generated_briefing import (
    GENERATED_STATUS_REQUIRED,
    build_keysuri_generated_briefing_preview_payload,
    load_keysuri_generated_briefing_fixture,
    validate_keysuri_generated_briefing,
)
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
)
from keysuri_renderer import load_keysuri_prompt_input_fixture

_REPO = Path(__file__).resolve().parent.parent


def _load_prompt(name: str) -> dict:
    return load_keysuri_prompt_input_fixture(str(_REPO / "ops" / "feeds" / name))


def _load_generated(name: str) -> dict:
    return load_keysuri_generated_briefing_fixture(str(_REPO / "ops" / "feeds" / name))


def _codes(issues: list) -> set[str]:
    return {i["code"] for i in issues}


class KeysuriGeneratedBriefingFixtureTests(unittest.TestCase):
    def test_global_fixture_passes_with_prompt_input(self) -> None:
        prompt = _load_prompt("keysuri_global_prompt_input.sample.json")
        gen = _load_generated("keysuri_global_generated_briefing.sample.json")
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", gen, prompt
        )
        self.assertEqual(issues, [])

    def test_korea_fixture_passes_with_prompt_input(self) -> None:
        prompt = _load_prompt("keysuri_korea_prompt_input.sample.json")
        gen = _load_generated("keysuri_korea_generated_briefing.sample.json")
        issues = validate_keysuri_generated_briefing(
            "keysuri_korea_tech", gen, prompt
        )
        self.assertEqual(issues, [])


class KeysuriGeneratedBriefingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_prompt = _load_prompt("keysuri_global_prompt_input.sample.json")
        self.korea_prompt = _load_prompt("keysuri_korea_prompt_input.sample.json")
        self.global_gen = _load_generated("keysuri_global_generated_briefing.sample.json")
        self.korea_gen = _load_generated("keysuri_korea_generated_briefing.sample.json")

    def test_wrong_program_id_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["program_id"] = "keysuri_korea_tech"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("program_id_mismatch", _codes(issues))

    def test_wrong_news_scope_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["news_scope"] = "korea"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("news_scope_mismatch", _codes(issues))

    def test_wrong_section_heading_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["section_heading"] = "국내 테크 TOP 5"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("section_heading_mismatch", _codes(issues))

    def test_wrong_top5_sequence_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        items = bad["top_5_news"]["items"]
        items[0], items[1] = items[1], items[0]
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("top_5_sequence_mismatch", _codes(issues))

    def test_missing_top5_item_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["top_5_news"]["items"] = bad["top_5_news"]["items"][:4]
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        codes = _codes(issues)
        self.assertTrue(
            "top_5_sequence_mismatch" in codes or "top_5_item_count_invalid" in codes
        )

    def test_extra_top5_item_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        extra = copy.deepcopy(bad["top_5_news"]["items"][-1])
        extra["rank"] = 6
        extra["news_id"] = "global-claim-extra"
        bad["top_5_news"]["items"].append(extra)
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("top_5_sequence_mismatch", _codes(issues))

    def test_wrong_deep_dive_heading_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["deep_dive"]["section_heading"] = "심층 분석"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("deep_dive_heading_invalid", _codes(issues))

    def test_empty_deep_dive_body_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["deep_dive"]["body"] = ""
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("deep_dive_body_empty", _codes(issues))

    def test_empty_key_implications_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["deep_dive"]["key_implications"] = []
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("deep_dive_key_implications_empty", _codes(issues))

    def test_unverified_deep_dive_confidence_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["deep_dive"]["confidence_label"] = "unverified"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("deep_dive_confidence_unverified", _codes(issues))

    def test_invalid_source_id_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["deep_dive"]["source_ids"] = ["nonexistent-source-id"]
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("deep_dive_source_id_invalid", _codes(issues))

    def test_wrong_one_line_heading_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["one_line_checkpoint"]["section_heading"] = "핵심 요약"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("one_line_heading_invalid", _codes(issues))

    def test_empty_one_line_body_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["one_line_checkpoint"]["body"] = "  "
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("one_line_body_empty", _codes(issues))

    def test_wrong_closing_heading_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["closing_sources"]["section_heading"] = "출처"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("closing_heading_invalid", _codes(issues))

    def test_empty_closing_source_list_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["closing_sources"]["source_list"] = []
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("closing_source_list_empty", _codes(issues))

    def test_forbidden_identity_strings_fail(self) -> None:
        for term in ("테크 앵커", "뉴스 앵커", "아나운서"):
            with self.subTest(term=term):
                bad = copy.deepcopy(self.global_gen)
                bad["deep_dive"]["body"] = f"staged copy with {term}"
                issues = validate_keysuri_generated_briefing(
                    "keysuri_global_tech", bad, self.global_prompt
                )
                self.assertIn("forbidden_identity_string", _codes(issues))

    def test_tomorrow_geenee_fails(self) -> None:
        for term in ("Tomorrow_Geenee", "tomorrow_genie"):
            with self.subTest(term=term):
                bad = copy.deepcopy(self.global_gen)
                bad["one_line_checkpoint"]["body"] = f"reference {term}"
                issues = validate_keysuri_generated_briefing(
                    "keysuri_global_tech", bad, self.global_prompt
                )
                self.assertIn("forbidden_retired_reference", _codes(issues))

    def test_scheduler_18_00_fails(self) -> None:
        bad = copy.deepcopy(self.global_gen)
        bad["closing_sources"]["closing_message"] = "slot at 18:00"
        issues = validate_keysuri_generated_briefing(
            "keysuri_global_tech", bad, self.global_prompt
        )
        self.assertIn("forbidden_retired_reference", _codes(issues))

    def test_korea_valid_passes(self) -> None:
        issues = validate_keysuri_generated_briefing(
            "keysuri_korea_tech", self.korea_gen, self.korea_prompt
        )
        self.assertEqual(issues, [])

    def test_preview_payload_pending_mode(self) -> None:
        payload = build_keysuri_generated_briefing_preview_payload(self.global_prompt)
        self.assertEqual(payload["generation_mode"], "pending")
        self.assertIsNone(payload["generated_briefing"])
        self.assertEqual(payload["generated_validation_issues"], [])

    def test_preview_payload_generated_mode(self) -> None:
        payload = build_keysuri_generated_briefing_preview_payload(
            self.global_prompt, self.global_gen
        )
        self.assertEqual(payload["generation_mode"], "generated")
        self.assertEqual(payload["generated_status"], GENERATED_STATUS_REQUIRED)
        self.assertEqual(payload["generated_validation_issues"], [])

    def test_section_constants_match_contract(self) -> None:
        self.assertEqual(self.global_gen["deep_dive"]["section_heading"], SECTION_DEEP_DIVE)
        self.assertEqual(
            self.global_gen["one_line_checkpoint"]["section_heading"], SECTION_ONE_LINE
        )
        self.assertEqual(
            self.global_gen["closing_sources"]["section_heading"], SECTION_CLOSING
        )


if __name__ == "__main__":
    unittest.main()
