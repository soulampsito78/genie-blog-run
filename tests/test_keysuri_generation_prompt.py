"""Tests for Kee-Suri offline generation prompt contract and JSON parse guard."""
from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from keysuri_generation_prompt import (
    FORBIDDEN_IDENTITY_KO,
    FORBIDDEN_RETIRED,
    IDENTITY_TITLE,
    build_keysuri_generation_prompt,
    build_keysuri_generation_prompt_contract,
    extract_json_object_from_model_text,
    parse_keysuri_generated_response,
    validate_parsed_keysuri_generated_briefing,
)
from keysuri_renderer import (
    load_keysuri_prompt_input_fixture,
    render_keysuri_owner_review_html,
)

_REPO = Path(__file__).resolve().parent.parent
_FEEDS = _REPO / "ops" / "feeds"


def _load_prompt(name: str) -> dict:
    return load_keysuri_prompt_input_fixture(str(_FEEDS / name))


def _read_raw(name: str) -> str:
    return (_FEEDS / name).read_text(encoding="utf-8")


def _global_prompt() -> dict:
    return _load_prompt("keysuri_global_prompt_input.sample.json")


def _korea_prompt() -> dict:
    return _load_prompt("keysuri_korea_prompt_input.sample.json")


class KeysuriGenerationPromptContractTests(unittest.TestCase):
    def test_global_contract_builds(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_global_prompt())
        self.assertEqual(contract["program_id"], "keysuri_global_tech")

    def test_korea_contract_builds(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_korea_prompt())
        self.assertEqual(contract["program_id"], "keysuri_korea_tech")

    def test_contract_core_fields(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_global_prompt())
        for key in (
            "program_id",
            "news_scope",
            "section_heading",
            "required_output_schema",
            "allowed_source_ids",
            "fixed_section_labels",
            "forbidden_outputs",
            "identity_rules",
            "scheduler_rules",
            "parse_rules",
        ):
            self.assertIn(key, contract)

    def test_contract_allowed_source_ids_non_empty(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_global_prompt())
        self.assertGreater(len(contract["allowed_source_ids"]), 0)

    def test_contract_tomorrow_retirement_rule(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_global_prompt())
        retired = contract["scheduler_rules"]["retired_rules"]
        blob = "\n".join(retired)
        self.assertIn("Tomorrow_Geenee", blob)
        self.assertIn("tomorrow_genie", blob)
        self.assertIn("18:00", blob)

    def test_generated_prompt_json_only_instruction(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn("Do not wrap in markdown fences", prompt)
        self.assertIn("Do not add explanations", prompt)

    def test_generated_prompt_identity_title(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn(IDENTITY_TITLE, prompt)
        self.assertIn("프라이빗 테크 비서", prompt)

    def test_generated_prompt_forbidden_identity_absent(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        for term in FORBIDDEN_IDENTITY_KO:
            self.assertNotIn(term, prompt)

    def test_generated_prompt_retired_refs_in_rules_not_as_product(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("FORBIDDEN IDENTITY / RETIRED", prompt)
        for term in FORBIDDEN_RETIRED:
            self.assertIn(term, prompt)

    def test_global_prompt_includes_breadth_and_depth_framing(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("GLOBAL TECH BREADTH", prompt)
        self.assertIn("NOT an AI-only newsletter", prompt)
        self.assertIn("GLOBAL TECH TOP5 DEPTH", prompt)
        self.assertIn("selection_reason", prompt)
        self.assertIn("sponsored_warning", prompt)
        self.assertIn("리스크 신호", prompt)

    def test_korea_prompt_includes_korea_tech_1830_lens(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA TECH 18:30 LENS", prompt)
        self.assertIn("국내 적용", prompt)
        self.assertIn("퇴근 전 메모", prompt)
        self.assertIn("한국 기업·정책으로 읽으면", prompt)

    def test_global_prompt_excludes_korea_only_lens_block(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertNotIn("KOREA TECH 18:30 LENS", prompt)
        self.assertNotIn("한국 도착 전 압력", prompt)

    def test_korea_prompt_forbids_global_only_phrasing(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("글로벌 원인", prompt)
        self.assertIn("FORBIDDEN Korea briefing labels", prompt)
        self.assertNotIn("GLOBAL TECH BREADTH", prompt)

    def test_korea_prompt_includes_scoring_metadata_in_top5_json(self) -> None:
        prompt_input = deepcopy(_korea_prompt())
        claims = prompt_input["source_pack"]["claims"]
        claims[0]["owner_action_line"] = "내일 파트너·입찰 일정을 점검하세요."
        claims[0]["next_day_impact_line"] = "내일 영향: 정책 신호가 의사결정에 반영될 수 있습니다."
        claims[0]["angle_chip"] = "국내 적용"
        claims[0]["global_duplicate_detected"] = True
        claims[0]["korea_angle_satisfied"] = True
        prompt = build_keysuri_generation_prompt(prompt_input)
        self.assertIn("owner_action_line", prompt)
        self.assertIn("next_day_impact_line", prompt)
        self.assertIn("내일 파트너·입찰 일정을 점검하세요.", prompt)


class KeysuriJsonExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid_obj = {"program_id": "keysuri_global_tech", "generated_status": "x", "n": 1}

    def test_raw_json_object_parses(self) -> None:
        raw = json.dumps(self.valid_obj)
        parsed = extract_json_object_from_model_text(raw)
        self.assertEqual(parsed["program_id"], "keysuri_global_tech")

    def test_fenced_json_parses(self) -> None:
        raw = "```json\n" + json.dumps(self.valid_obj) + "\n```"
        parsed = extract_json_object_from_model_text(raw)
        self.assertEqual(parsed["program_id"], "keysuri_global_tech")

    def test_plain_fenced_json_parses(self) -> None:
        raw = "```\n" + json.dumps(self.valid_obj) + "\n```"
        parsed = extract_json_object_from_model_text(raw)
        self.assertEqual(parsed["program_id"], "keysuri_global_tech")

    def test_extra_text_around_json_parses(self) -> None:
        raw = "prefix\n" + json.dumps(self.valid_obj) + "\nsuffix"
        parsed = extract_json_object_from_model_text(raw)
        self.assertEqual(parsed["program_id"], "keysuri_global_tech")

    def test_invalid_json_fails(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text(_read_raw("keysuri_raw_response.invalid_json.sample.txt"))

    def test_multiple_json_objects_fail(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text(_read_raw("keysuri_raw_response.multiple_json.sample.txt"))

    def test_array_top_level_fails(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text(_read_raw("keysuri_raw_response.array_top_level.sample.txt"))

    def test_empty_object_fails(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text("{}")

    def test_no_json_fails(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text("no json here")


class KeysuriParsedResponseTests(unittest.TestCase):
    def test_global_valid_raw_parsed_valid(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_global_raw_response.valid.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertEqual(result["issues"], [])
        self.assertIsNotNone(result["generated_briefing"])

    def test_korea_valid_raw_parsed_valid(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_korea_raw_response.valid.sample.txt"),
            "keysuri_korea_tech",
            _korea_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertIsNone(result["issues"] or None)

    def test_markdown_fenced_valid(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.markdown_fenced.valid.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid")

    def test_extra_text_valid(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.extra_text.valid.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid")

    def test_invalid_schema_parsed_invalid(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.invalid_schema.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertIsNone(result["generated_briefing"])
        self.assertTrue(result["issues"])

    def test_malformed_json_parse_failed(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.invalid_json.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parse_failed")
        self.assertIsNone(result["generated_briefing"])

    def test_multiple_json_recovers_to_valid(self) -> None:
        # Fixture is a fully valid payload followed by a stray trailing JSON
        # object — the production keysuri_korea_tech failure pattern. The parser
        # now selects the valid object instead of blocking the whole run.
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.multiple_json.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        meta = result["parse_meta"]
        self.assertTrue(meta["multiple_json_objects_detected"])
        self.assertGreater(meta["json_candidate_count"], 1)
        self.assertTrue(meta["parser_recovery_used"])

    def test_array_top_level_parse_failed(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.array_top_level.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        self.assertEqual(result["parse_status"], "parse_failed")


class KeysuriGenerationPromptIntegrationTests(unittest.TestCase):
    def test_parsed_valid_renders_generated_html(self) -> None:
        prompt_input = _global_prompt()
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_global_raw_response.valid.sample.txt"),
            "keysuri_global_tech",
            prompt_input,
        )
        self.assertEqual(result["parse_status"], "parsed_valid")
        html = render_keysuri_owner_review_html(prompt_input, result["generated_briefing"])
        self.assertIn("키수리의 딥-다이브", html)
        self.assertNotIn("generation_pending", html)

    def test_parsed_invalid_does_not_render_as_generated(self) -> None:
        prompt_input = _global_prompt()
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_raw_response.invalid_schema.sample.txt"),
            "keysuri_global_tech",
            prompt_input,
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertIsNone(result["generated_briefing"])
        invalid_parsed = extract_json_object_from_model_text(
            _read_raw("keysuri_raw_response.invalid_schema.sample.txt")
        )
        with self.assertRaises(ValueError):
            render_keysuri_owner_review_html(prompt_input, invalid_parsed)

    def test_validate_parsed_wrapper(self) -> None:
        result = parse_keysuri_generated_response(
            _read_raw("keysuri_global_raw_response.valid.sample.txt"),
            "keysuri_global_tech",
            _global_prompt(),
        )
        validation = validate_parsed_keysuri_generated_briefing(
            "keysuri_global_tech",
            result["generated_briefing"],
            _global_prompt(),
        )
        self.assertTrue(validation["valid"])


class KeysuriGenerationPromptFixtureAlignmentTests(unittest.TestCase):
    def test_ops_contract_fixture_aligns_with_builder(self) -> None:
        prompt_input = _global_prompt()
        built = build_keysuri_generation_prompt_contract(prompt_input)
        on_disk = json.loads(
            (_FEEDS / "keysuri_global_generation_prompt_contract.sample.json").read_text(encoding="utf-8")
        )
        self.assertEqual(on_disk["program_id"], built["program_id"])
        self.assertEqual(on_disk["news_scope"], built["news_scope"])
        self.assertEqual(on_disk["allowed_source_ids"], built["allowed_source_ids"])


if __name__ == "__main__":
    unittest.main()
