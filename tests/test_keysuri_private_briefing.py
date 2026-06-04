"""Tests for Kee-Suri private briefing output schema and section label validation."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from keysuri_news_contract import NEWS_SCOPE_GLOBAL, NEWS_SCOPE_KOREA
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
    SECTION_TOP5_GLOBAL,
    SECTION_TOP5_KOREA,
    keysuri_output_schema_example,
    validate_keysuri_private_briefing,
)

_REPO = Path(__file__).resolve().parent.parent


def _load_fixture(name: str) -> dict:
    return json.loads((_REPO / "ops" / "feeds" / name).read_text(encoding="utf-8"))


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

    def test_global_sample_fixture_passes(self) -> None:
        payload = _load_fixture("keysuri_global_output.sample.json")
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "pass", msg=[(i.code, i.message) for i in result.issues])

    def test_korea_sample_fixture_passes(self) -> None:
        payload = _load_fixture("keysuri_korea_output.sample.json")
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_korea_tech")
        self.assertEqual(result.verdict, "pass", msg=[(i.code, i.message) for i in result.issues])

    def test_global_must_use_global_top5_heading(self) -> None:
        payload = _valid_global()
        payload["top_5_news"]["section_heading"] = "TOP 5"
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any("heading" in i.code for i in result.issues))

    def test_wrong_news_scope_fails(self) -> None:
        payload = _valid_global()
        payload["top_5_news"]["news_scope"] = NEWS_SCOPE_KOREA
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "top_5_news_scope_wrong" for i in result.issues))

    def test_top5_plain_list_fails(self) -> None:
        payload = _valid_global()
        payload["top_5_news"] = payload["top_5_news"]["items"]
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")

    def test_fewer_than_five_items_fails(self) -> None:
        payload = _valid_global()
        payload["top_5_news"]["items"] = payload["top_5_news"]["items"][:3]
        result = validate_keysuri_private_briefing(payload, program_id="keysuri_global_tech")
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "top_5_news_items_too_few" for i in result.issues))

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


if __name__ == "__main__":
    unittest.main()
