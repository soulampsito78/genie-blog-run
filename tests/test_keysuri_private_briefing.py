"""Tests for Kee-Suri private briefing output schema and section label validation."""
from __future__ import annotations

import copy
import unittest

from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    keysuri_output_schema_example,
    validate_keysuri_private_briefing,
)
from keysuri_prompt_profiles import (
    KEYSURI_GLOBAL_TECH_V1,
    KEYSURI_KOREA_TECH_V1,
    get_keysuri_prompt_profile,
)


def _valid_global() -> dict:
    return copy.deepcopy(keysuri_output_schema_example("keysuri_global_tech"))


def _valid_korea() -> dict:
    return copy.deepcopy(keysuri_output_schema_example("keysuri_korea_tech"))


class KeysuriPrivateBriefingValidationTests(unittest.TestCase):
    def test_global_valid_passes(self) -> None:
        result = validate_keysuri_private_briefing(
            _valid_global(),
            program_id="keysuri_global_tech",
        )
        self.assertEqual(result.verdict, "pass")

    def test_korea_valid_passes(self) -> None:
        result = validate_keysuri_private_briefing(
            _valid_korea(),
            program_id="keysuri_korea_tech",
        )
        self.assertEqual(result.verdict, "pass")

    def test_global_must_use_global_top5_heading(self) -> None:
        payload = _valid_global()
        payload["top_5_news"]["section_heading"] = "TOP 5"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "top_5_news_heading_wrong" for i in result.issues))

    def test_korea_must_use_korea_top5_heading(self) -> None:
        payload = _valid_korea()
        payload["top_5_news"]["section_heading"] = "TOP 5"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_korea_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "top_5_news_heading_wrong" for i in result.issues))

    def test_deep_dive_wrong_heading_blocks(self) -> None:
        payload = _valid_global()
        payload["deep_dive"]["section_heading"] = "심층 분석"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any("deep_dive" in (i.field or "") for i in result.issues))

    def test_one_line_wrong_heading_blocks(self) -> None:
        payload = _valid_global()
        payload["one_line_checkpoint"]["section_heading"] = "핵심 요약"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")

    def test_closing_wrong_heading_blocks(self) -> None:
        payload = _valid_global()
        payload["closing_sources"]["section_heading"] = "출처"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")

    def test_deep_dive_plain_string_blocks(self) -> None:
        payload = _valid_global()
        payload["deep_dive"] = "plain string body"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "deep_dive_must_be_object" for i in result.issues))

    def test_one_line_plain_string_blocks(self) -> None:
        payload = _valid_global()
        payload["one_line_checkpoint"] = "plain string body"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "one_line_checkpoint_must_be_object" for i in result.issues))

    def test_closing_plain_string_blocks(self) -> None:
        payload = _valid_global()
        payload["closing_sources"] = "plain string body"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "closing_sources_must_be_object" for i in result.issues))

    def test_operational_status_must_be_review_required(self) -> None:
        payload = _valid_global()
        payload["operational_status"] = "approved"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "operational_status_wrong" for i in result.issues))

    def test_global_top5_on_korea_program_blocks(self) -> None:
        payload = _valid_korea()
        payload["top_5_news"]["section_heading"] = SECTION_TOP5_GLOBAL
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_korea_tech")
        self.assertEqual(result.verdict, "block")

    def test_korea_top5_on_global_program_blocks(self) -> None:
        payload = _valid_global()
        payload["top_5_news"]["section_heading"] = SECTION_TOP5_KOREA
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")


class KeysuriPromptProfileTests(unittest.TestCase):
    def test_global_profile_contains_fixed_headings(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_global_tech_v1")
        self.assertIn(SECTION_TOP5_GLOBAL, text)
        self.assertIn(SECTION_DEEP_DIVE, text)
        self.assertIn(SECTION_ONE_LINE, text)
        self.assertIn(SECTION_CLOSING, text)
        self.assertIn("review_required", text)
        self.assertNotIn('"deep_dive": "string"', text)

    def test_korea_profile_contains_fixed_headings(self) -> None:
        text = get_keysuri_prompt_profile("keysuri_korea_tech_v1")
        self.assertIn(SECTION_TOP5_KOREA, text)
        self.assertIn(SECTION_DEEP_DIVE, text)
        self.assertIn(SECTION_ONE_LINE, text)
        self.assertIn(SECTION_CLOSING, text)

    def test_profiles_forbid_renamed_labels(self) -> None:
        self.assertIn("심층 분석", KEYSURI_GLOBAL_TECH_V1)
        self.assertIn("핵심 요약", KEYSURI_GLOBAL_TECH_V1)
        self.assertIn("generic \"TOP 5\" 금지", KEYSURI_KOREA_TECH_V1)


if __name__ == "__main__":
    unittest.main()
