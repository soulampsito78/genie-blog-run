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

    def test_global_prompt_forbids_repeated_common_filler_sentences(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("GLOBAL TECH ITEM-UNIQUE IMPACT", prompt)
        for filler in (
            "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다.",
            "배포·워크플로·API 통제권 변화와 맞닿는 시점입니다.",
            "사용자 접점·검색·쇼핑 경험 변화로 읽힙니다.",
        ):
            with self.subTest(filler=filler):
                self.assertIn(filler, prompt)

    def test_global_prompt_forbids_pixel_android_as_aerospace_defense(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("GLOBAL TECH CATEGORY CLASSIFICATION GUARD", prompt)
        for marker in ("Pixel", "Google Pixel", "Android", "smartphone", "on-device AI", "항공우주·위성·방산"):
            with self.subTest(marker=marker):
                self.assertIn(marker, prompt)

    def test_korea_prompt_excludes_global_filler_and_category_guard_blocks(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertNotIn("GLOBAL TECH ITEM-UNIQUE IMPACT", prompt)
        self.assertNotIn("GLOBAL TECH CATEGORY CLASSIFICATION GUARD", prompt)

    def test_korea_prompt_includes_korea_tech_1830_lens(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA TECH 18:30 LENS", prompt)
        self.assertIn("국내 적용", prompt)
        self.assertIn("퇴근 전 메모", prompt)
        self.assertIn("한국 기업·정책으로 읽으면", prompt)
        self.assertIn("deep_dive.key_implications: mandatory non-empty array", prompt)

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

    def test_korea_prompt_repositions_as_market_signal_briefing(self) -> None:
        """Korea Tech must be positioned as a market-signal briefing, not a news summary."""
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("국내 IT 뉴스 요약이 아니다", prompt)
        self.assertIn("한국형 테크-시장 브리핑", prompt)
        self.assertIn("돈·일·사업·투자 판단", prompt)

    def test_korea_prompt_requires_market_lens_axes(self) -> None:
        """Korea Tech must require stock/bond/FX/rate/policy/industry/jobs perspectives."""
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        for axis in (
            "주식시장",
            "채권시장",
            "환율",
            "금리",
            "정부 정책",
            "산업 생태계",
            "일자리",
            "협력사·소부장·장비·소재·부품 영향",
            "지역 채용·교육·유지보수 수요",
            "사업자·프리랜서 비용 구조와 도입 일정",
        ):
            with self.subTest(axis=axis):
                self.assertIn(axis, prompt)
        self.assertIn("KOREA MARKET SIGNAL DEPTH", prompt)
        self.assertIn("신호 순위", prompt)

    def test_korea_prompt_requires_ordinary_reader_impact_translation(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA IMPACT TRANSLATION LAYER", prompt)
        for marker in ("업종", "협력사/소부장", "일자리/지역", "개인 투자자", "사업자/프리랜서"):
            with self.subTest(marker=marker):
                self.assertIn(marker, prompt)
        for term in ("소부장", "협력사", "장비", "소재", "부품", "데이터센터", "지역", "채용", "외주", "비용 구조"):
            with self.subTest(term=term):
                self.assertIn(term, prompt)
        self.assertIn("Upper-layer market terms are allowed but insufficient by themselves", prompt)
        self.assertIn("M&A, 투자유치, 정책금융", prompt)

    def test_korea_prompt_market_repositioning_does_not_leak_into_global(self) -> None:
        """Korea-only market-signal-briefing framing must not damage the Global prompt."""
        global_prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("GLOBAL TECH BREADTH", global_prompt)
        self.assertIn("NOT an AI-only newsletter", global_prompt)
        for korea_only_marker in (
            "KOREA MARKET SIGNAL DEPTH",
            "KOREA MARKET SIGNAL BRIEFING",
            "KOREA DEEP DIVE MUST NOT RECAP TOP5",
            "KOREA RISK = HOLD CRITERIA",
            "KOREA ONE-LINE CHECKPOINT MUST BE ACTION-FORM",
            "KOREA INVESTMENT-ADVICE BOUNDARY",
            "KOREA IMPACT TRANSLATION LAYER",
            "국내 IT 뉴스 요약이 아니다",
        ):
            with self.subTest(marker=korea_only_marker):
                self.assertNotIn(korea_only_marker, global_prompt)

    def test_korea_prompt_deep_dive_forbids_top5_recap(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA DEEP DIVE MUST NOT RECAP TOP5", prompt)
        self.assertIn("ONE market-structure judgment frame", prompt)

    def test_korea_prompt_risk_requires_hold_criteria(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("무엇을 아직 단정하지 말아야 하는가", prompt)
        self.assertIn("확인되기 전까지 보류해야 하는가", prompt)

    def test_korea_prompt_checkpoint_requires_confirm_and_hold(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("내일 먼저 확인할 것", prompt)
        self.assertIn("아직 단정하지 말 것", prompt)

    def test_korea_prompt_forbids_press_release_cliches_and_recommends_market_phrasing(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA FORBIDDEN NEWS-SUMMARY STYLE", prompt)
        for phrase in ("의미 있는 신호", "영향을 줄 수 있습니다", "발표했습니다", "밝혔습니다", "추진합니다"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        self.assertIn("장비·소재·부품 협력사와 지역 채용 일정", prompt)

    def test_korea_prompt_forbids_specific_investment_directives(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA INVESTMENT-ADVICE BOUNDARY", prompt)
        self.assertIn("Never instruct 주인님 to buy or sell a specific stock", prompt)

    def test_korea_prompt_requires_explicit_market_signal_output_fields(self) -> None:
        """Phase 3: market_lens/market_impact must be explicit Gemini output, not inference."""
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("KOREA MARKET SIGNAL OUTPUT FIELDS", prompt)
        self.assertIn("market_lens: array of 1-3 labels", prompt)
        self.assertIn("채권/금리", prompt)
        self.assertIn("market_impact: exactly one Korean sentence", prompt)
        self.assertIn("NEVER contain buy/sell directives", prompt)

    def test_korea_prompt_forbids_impact_axis_names_in_market_lens(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("Do NOT use impact-axis names as market_lens labels", prompt)
        for forbidden_label in ("개인 투자자", "투자", "투자자", "수혜주"):
            with self.subTest(forbidden_label=forbidden_label):
                self.assertIn(forbidden_label, prompt)

    def test_korea_prompt_requires_single_json_object_only(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertIn("Return exactly one JSON object.", prompt)
        self.assertIn("No second corrected JSON. No duplicate JSON object.", prompt)

    def test_korea_output_schema_example_includes_market_fields(self) -> None:
        contract = build_keysuri_generation_prompt_contract(_korea_prompt())
        items = contract["required_output_schema"]["top_5_news"]["items"]
        for item in items:
            self.assertIn("market_lens", item)
            self.assertIn("market_impact", item)

    def test_global_prompt_and_schema_exclude_market_signal_fields(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertNotIn("KOREA MARKET SIGNAL OUTPUT FIELDS", prompt)
        contract = build_keysuri_generation_prompt_contract(_global_prompt())
        for item in contract["required_output_schema"]["top_5_news"]["items"]:
            self.assertNotIn("market_lens", item)
            self.assertNotIn("market_impact", item)


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


class GlobalTechSignalQualityPromptTests(unittest.TestCase):
    """Global prompt must demand fresh signals, 5W1H, and reject soft/evergreen stories."""

    def test_global_prompt_includes_signal_quality_block(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("GLOBAL TECH SIGNAL QUALITY", prompt)
        self.assertIn("EXCLUDE evergreen educational explainers", prompt)
        self.assertIn("consumer-culture / entertainment soft stories", prompt)
        self.assertIn("Corporate blog / conference recaps qualify ONLY", prompt)

    def test_global_prompt_requires_5w1h_and_48h_checkpoint(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("5W1H", prompt)
        self.assertIn("그래서 볼 것", prompt)
        self.assertIn("next-48-hours checkpoint", prompt)

    def test_global_prompt_forbids_famous_source_shortcut_and_abstract_filler(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("just because the source outlet is famous", prompt)
        for marker in ("중요합니다", "시사합니다", "촉진합니다", "보여줍니다", "필수적입니다"):
            with self.subTest(marker=marker):
                self.assertIn(marker, prompt)

    def test_global_prompt_reiterates_single_json_object(self) -> None:
        prompt = build_keysuri_generation_prompt(_global_prompt())
        self.assertIn("Output exactly one JSON object", prompt)
        self.assertIn("Return exactly one JSON object", prompt)

    def test_korea_prompt_excludes_global_signal_quality_block(self) -> None:
        prompt = build_keysuri_generation_prompt(_korea_prompt())
        self.assertNotIn("GLOBAL TECH SIGNAL QUALITY", prompt)


if __name__ == "__main__":
    unittest.main()
