"""Regression tests for multiple-JSON-object recovery in the Kee-Suri parser.

Reproduces the keysuri_korea_tech production failure where Gemini returned more
than one JSON object ("Multiple JSON objects found in model text") and the run
was blocked. The parser now selects a schema-valid candidate without merging
objects, while preserving the single-object behavior and the unrecoverable path.
"""
from __future__ import annotations

import json
import unittest

from keysuri_generation_prompt import (
    KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE,
    extract_json_candidates_from_model_text,
    extract_json_object_from_model_text,
    parse_keysuri_generated_response,
)
from keysuri_renderer import render_keysuri_owner_review_html


def _valid_korea_payload() -> dict:
    cats = [
        "korea_semiconductor",
        "korea_semiconductor",
        "global_to_korea_translation",
        "korea_startup_investment",
        "korea_big_company_strategy",
    ]
    items = [
        {
            "rank": r,
            "news_id": f"claim-live-korea-{r}",
            "headline": f"Korea headline {r}",
            "category": c,
            "summary": f"Summary {r}",
            "why_it_matters": f"Why {r}",
            "business_implication": f"Biz {r}",
            "source_ids": [f"live-src-{r}"],
            "confidence_label": "reported",
        }
        for r, c in enumerate(cats, start=1)
    ]
    return {
        "program_id": "keysuri_korea_tech",
        "generated_status": "generated_review_required",
        "operational_status": "review_required",
        "news_scope": "korea",
        "section_heading": "국내 테크 TOP 5",
        "top_5_news": {
            "news_scope": "korea",
            "section_heading": "국내 테크 TOP 5",
            "items": items,
        },
        "deep_dive": {
            "section_heading": "키수리의 딥-다이브",
            "body": "한국 기업·정책으로 읽으면 오늘 국내 반도체와 AI 흐름이 핵심입니다.",
            "confirmed_facts": ["Fact one"],
            "key_implications": ["Domestic supply-chain read-through"],
            "interpretation": "Domestic interpretation.",
            "owner_impact": "Owner impact.",
            "uncertainty": [],
            "source_ids": ["live-src-1"],
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": "원-라인 체크포인트",
            "body": "Checkpoint line.",
        },
        "closing_sources": {
            "section_heading": "마무리 및 출처 리스트",
            "closing_message": "퇴근 전 메모로 정리했습니다.",
            "source_list": [
                {
                    "source_id": "live-src-1",
                    "label": "더lec",
                    "source_name": "더lec",
                    "source_url": "https://example.com/1",
                }
            ],
        },
    }


def _valid_global_payload() -> dict:
    cats = ["ai_product", "bigtech", "semiconductor", "platform", "policy"]
    items = [
        {
            "rank": r,
            "news_id": f"g-news-{r}",
            "headline": f"Global headline {r}",
            "category": c,
            "summary": f"Summary {r}",
            "why_it_matters": f"Why {r}",
            "business_implication": f"Biz {r}",
            "source_ids": [f"g-src-{r}"],
            "confidence_label": "reported",
        }
        for r, c in enumerate(cats, start=1)
    ]
    return {
        "program_id": "keysuri_global_tech",
        "generated_status": "generated_review_required",
        "operational_status": "review_required",
        "news_scope": "global",
        "section_heading": "글로벌 테크 TOP 5",
        "top_5_news": {
            "news_scope": "global",
            "section_heading": "글로벌 테크 TOP 5",
            "items": items,
        },
        "deep_dive": {
            "section_heading": "키수리의 딥-다이브",
            "body": "Global read-through body text here for owners.",
            "key_implications": ["Implication one"],
            "source_ids": ["g-src-1"],
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": "원-라인 체크포인트",
            "body": "Checkpoint line.",
        },
        "closing_sources": {
            "section_heading": "마무리 및 출처 리스트",
            "closing_message": "마무리 메모.",
            "source_list": [
                {
                    "source_id": "g-src-1",
                    "label": "TechCrunch",
                    "source_name": "TechCrunch",
                    "source_url": "https://example.com/g1",
                }
            ],
        },
    }


def _korea_prompt_input(payload: dict) -> dict:
    return {
        "program_id": "keysuri_korea_tech",
        "top_5_news": payload["top_5_news"],
        "source_pack": {"program_id": "keysuri_korea_tech", "claims": [], "sources": []},
    }


def _global_prompt_input(payload: dict) -> dict:
    return {
        "program_id": "keysuri_global_tech",
        "top_5_news": payload["top_5_news"],
        "source_pack": {"program_id": "keysuri_global_tech", "claims": [], "sources": []},
    }


class MultipleJsonRecoveryTests(unittest.TestCase):
    def test_error_json_then_valid_payload_recovers(self) -> None:
        """First object is a model apology/error JSON; second is the real payload."""
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        text = (
            '{"error": "could not comply on first try", "note": "retry"}\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        self.assertEqual(result["generated_briefing"]["program_id"], "keysuri_korea_tech")
        meta = result["parse_meta"]
        self.assertTrue(meta["multiple_json_objects_detected"])
        self.assertEqual(meta["json_candidate_count"], 2)
        self.assertEqual(meta["selected_json_candidate_index"], 1)
        self.assertTrue(meta["parser_recovery_used"])

    def test_valid_payload_then_trailing_json_recovers(self) -> None:
        """First object is the valid payload; a stray JSON object trails it."""
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        text = json.dumps(payload, ensure_ascii=False) + '\n{"meta": "trailing note"}'
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        meta = result["parse_meta"]
        self.assertTrue(meta["multiple_json_objects_detected"])
        self.assertEqual(meta["json_candidate_count"], 2)
        self.assertEqual(meta["selected_json_candidate_index"], 0)
        self.assertTrue(meta["parser_recovery_used"])

    def test_two_valid_objects_ambiguous(self) -> None:
        '''Two fully valid candidates should block safely as ambiguous.'''
        payload1 = _valid_korea_payload()
        payload2 = _valid_korea_payload()
        # Change a field to bypass string deduplication but keep it valid
        payload2["top_5_news"]["items"][0]["headline"] = "Slightly different valid headline"
        pi = _korea_prompt_input(payload1)
        import json
        text = json.dumps(payload1, ensure_ascii=False) + '\n' + json.dumps(payload2, ensure_ascii=False)
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("parse_multiple_json_objects_ambiguous", codes)
        self.assertFalse(result["parse_meta"]["parser_recovery_used"])

    def test_korea_missing_news_scope_repair(self) -> None:
        '''Candidate can be repaired to news_scope="korea" when missing.'''
        payload = _valid_korea_payload()
        # Remove news_scope from top_5_news
        del payload["top_5_news"]["news_scope"]

        pi = _korea_prompt_input(payload)
        import json
        text = '{"error": "mock invalid first object"}\n' + json.dumps(payload, ensure_ascii=False)

        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        top5 = result["generated_briefing"]["top_5_news"]
        self.assertEqual(top5["news_scope"], "korea")
        self.assertTrue(top5.get("_repaired_news_scope"))

    def test_korea_empty_top_level_news_scope_repaired(self) -> None:
        payload = _valid_korea_payload()
        payload["news_scope"] = ""
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_korea_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        self.assertEqual(result["generated_briefing"]["news_scope"], "korea")
        meta = result["parse_meta"]
        self.assertTrue(meta.get("repair_applied"))
        self.assertIn("news_scope", meta.get("repaired_fields") or [])

    def test_korea_empty_top_level_section_heading_repaired(self) -> None:
        payload = _valid_korea_payload()
        payload["section_heading"] = ""
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_korea_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        self.assertEqual(result["generated_briefing"]["section_heading"], "국내 테크 TOP 5")
        meta = result["parse_meta"]
        self.assertTrue(meta.get("repair_applied"))
        self.assertIn("section_heading", meta.get("repaired_fields") or [])

    def test_korea_wrong_top_level_news_scope_not_overwritten(self) -> None:
        payload = _valid_korea_payload()
        payload["news_scope"] = "global"
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_korea_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("news_scope_mismatch", codes)
        meta = result["parse_meta"]
        self.assertEqual(meta.get("news_scope_actual"), "global")
        self.assertNotIn("news_scope", meta.get("repaired_fields") or [])

    def test_global_empty_top_level_scope_heading_repaired(self) -> None:
        payload = _valid_global_payload()
        payload["news_scope"] = ""
        payload["section_heading"] = None
        pi = _global_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_global_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        briefing = result["generated_briefing"]
        self.assertEqual(briefing["news_scope"], "global")
        self.assertEqual(briefing["section_heading"], "글로벌 테크 TOP 5")
        meta = result["parse_meta"]
        self.assertTrue(meta.get("repair_applied"))
        self.assertEqual(
            set(meta.get("repaired_fields") or []),
            {"news_scope", "section_heading"},
        )

    def test_missing_top5_news_not_invented(self) -> None:
        payload = _valid_korea_payload()
        del payload["top_5_news"]
        payload["news_scope"] = ""
        payload["section_heading"] = ""
        pi = _korea_prompt_input(_valid_korea_payload())
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_korea_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertIsNone(result["generated_briefing"])
        meta = result["parse_meta"]
        # Scope/heading may be repaired, but top_5_news must not be fabricated.
        self.assertIn("top_5_news", meta.get("missing_required_keys") or [])
        self.assertNotIn("top_5_news", meta.get("repaired_fields") or [])
        self.assertEqual(meta.get("news_scope_actual"), "korea")
        self.assertEqual(meta.get("section_heading_actual"), "국내 테크 TOP 5")

    def test_two_invalid_objects_stays_validation_blocked(self) -> None:
        """Neither object is a valid payload: keep the validation_blocked outcome."""
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        text = '{"a": 1, "explanation": "x"}\n{"b": 2, "explanation": "y"}'
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertIsNone(result["generated_briefing"])
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("parse_multiple_json_objects_unrecoverable", codes)
        meta = result["parse_meta"]
        self.assertTrue(meta["multiple_json_objects_detected"])
        self.assertEqual(meta["json_candidate_count"], 2)
        self.assertFalse(meta["parser_recovery_used"])

        # Check that candidate-level diagnostic summaries are included
        self.assertTrue(any(i.get("code") == "candidate_0_summary" or i.get("code") == "candidate_1_summary" for i in result["issues"]))

    def test_no_object_merging(self) -> None:
        """Recovery selects one whole object; it never merges fields across objects."""
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        text = (
            '{"deep_dive": {"section_heading": "WRONG"}}\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        # The selected object equals the real payload exactly — no field bled in
        # from the first (decoy) object.
        self.assertEqual(
            result["generated_briefing"]["deep_dive"]["section_heading"],
            payload["deep_dive"]["section_heading"],
        )


class SingleJsonUnchangedTests(unittest.TestCase):
    def test_single_valid_korea_unchanged(self) -> None:
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_korea_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        meta = result["parse_meta"]
        self.assertFalse(meta["multiple_json_objects_detected"])
        self.assertEqual(meta["json_candidate_count"], 1)
        self.assertFalse(meta["parser_recovery_used"])

    def test_single_valid_global_unchanged(self) -> None:
        payload = _valid_global_payload()
        pi = _global_prompt_input(payload)
        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False), "keysuri_global_tech", pi
        )
        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        self.assertFalse(result["parse_meta"]["multiple_json_objects_detected"])

    def test_single_invalid_has_no_multiple_object_marker(self) -> None:
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response('{"a": 1}', "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]
        self.assertNotIn("parse_multiple_json_objects_unrecoverable", codes)
        self.assertEqual(result["parse_meta"]["json_candidate_count"], 1)

    def test_empty_text_is_parse_failed(self) -> None:
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        result = parse_keysuri_generated_response("   ", "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parse_failed")
        self.assertEqual(result["issues"][0]["code"], "json_extract_failed")
        self.assertEqual(result["parse_meta"]["json_candidate_count"], 0)


class DeepDiveKeyImplicationsRepairTests(unittest.TestCase):
    def test_empty_key_implications_repairs_from_existing_fields(self) -> None:
        payload = _valid_korea_payload()
        payload["top_5_news"]["items"][0]["headline"] = (
            "총점 54점을 기록했으며 국내 AI 플랫폼 적용 확대"
        )
        payload["deep_dive"]["key_implications"] = []
        payload["deep_dive"]["summary"] = "국내 기업의 도입 우선순위가 다시 정리되는 장면입니다."
        payload["deep_dive"]["why_it_matters"] = "정책과 공급망 대응이 함께 움직입니다."
        pi = _korea_prompt_input(payload)

        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False),
            "keysuri_korea_tech",
            pi,
        )

        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        implications = result["generated_briefing"]["deep_dive"]["key_implications"]
        self.assertGreaterEqual(len(implications), 2)
        self.assertIn(
            KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE,
            result["parse_meta"].get("internal_issue_codes") or [],
        )
        rendered = render_keysuri_owner_review_html(pi, result["generated_briefing"])
        self.assertNotIn(KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE, rendered)
        combined = "\n".join(implications)
        self.assertNotIn("입니다입니다", combined)
        for forbidden in ("총점", "점수", "스코어", "score", "scoring"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined.lower())

    def test_missing_key_implications_key_repairs_from_existing_fields(self) -> None:
        """deep_dive.key_implications entirely absent (not just an empty list) must
        still be repairable from existing generated fields."""
        payload = _valid_korea_payload()
        payload["top_5_news"]["items"][0]["headline"] = "국내 AI 플랫폼 적용 확대 소식"
        payload["deep_dive"].pop("key_implications", None)
        payload["deep_dive"]["summary"] = "국내 기업의 도입 우선순위가 다시 정리되는 장면입니다."
        payload["deep_dive"]["why_it_matters"] = "정책과 공급망 대응이 함께 움직입니다."
        pi = _korea_prompt_input(payload)

        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False),
            "keysuri_korea_tech",
            pi,
        )

        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        implications = result["generated_briefing"]["deep_dive"]["key_implications"]
        self.assertGreaterEqual(len(implications), 2)
        self.assertIn(
            KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE,
            result["parse_meta"].get("internal_issue_codes") or [],
        )

    def test_non_list_key_implications_repairs_from_existing_fields(self) -> None:
        """deep_dive.key_implications returned as a bare string (schema drift, not
        a list at all) must still be repairable, not just the empty-list case."""
        payload = _valid_korea_payload()
        payload["top_5_news"]["items"][0]["headline"] = "국내 AI 플랫폼 적용 확대 소식"
        payload["deep_dive"]["key_implications"] = "국내 시장에 중요한 함의가 있습니다"
        payload["deep_dive"]["summary"] = "국내 기업의 도입 우선순위가 다시 정리되는 장면입니다."
        payload["deep_dive"]["why_it_matters"] = "정책과 공급망 대응이 함께 움직입니다."
        pi = _korea_prompt_input(payload)

        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False),
            "keysuri_korea_tech",
            pi,
        )

        self.assertEqual(result["parse_status"], "parsed_valid", result.get("issues"))
        implications = result["generated_briefing"]["deep_dive"]["key_implications"]
        self.assertIsInstance(implications, list)
        self.assertGreaterEqual(len(implications), 2)
        self.assertIn(
            KEYSURI_DEEP_DIVE_KEY_IMPL_REPAIR_CODE,
            result["parse_meta"].get("internal_issue_codes") or [],
        )

    def test_key_implications_repair_failure_keeps_block_with_diagnostics(self) -> None:
        payload = _valid_korea_payload()
        payload["top_5_news"]["items"] = []
        payload["deep_dive"]["body"] = ""
        payload["deep_dive"]["summary"] = ""
        payload["deep_dive"]["why_it_matters"] = ""
        payload["deep_dive"]["owner_angle"] = ""
        payload["deep_dive"]["interpretation"] = ""
        payload["deep_dive"]["owner_impact"] = ""
        payload["deep_dive"]["key_implications"] = []
        pi = _korea_prompt_input(payload)

        result = parse_keysuri_generated_response(
            json.dumps(payload, ensure_ascii=False),
            "keysuri_korea_tech",
            pi,
        )

        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("deep_dive_key_implications_empty", codes)
        meta = result["parse_meta"]
        self.assertTrue(meta.get("deep_dive_key_implications_repair_attempted"))
        self.assertFalse(meta.get("deep_dive_key_implications_repair_success"))
        self.assertEqual(
            meta.get("deep_dive_key_implications_repair_reason"),
            "insufficient_source_fields",
        )
        self.assertIsInstance(meta.get("raw_parsed_field_presence_summary"), dict)


class ExtractorContractTests(unittest.TestCase):
    def test_candidates_helper_returns_all_objects(self) -> None:
        text = '{"a": 1}\n{"b": 2}'
        candidates = extract_json_candidates_from_model_text(text)
        self.assertEqual(candidates, [{"a": 1}, {"b": 2}])

    def test_strict_extractor_still_raises_on_multiple(self) -> None:
        text = '{"a": 1}\n{"b": 2}'
        with self.assertRaises(ValueError):
            extract_json_object_from_model_text(text)

    def test_strict_extractor_returns_single(self) -> None:
        self.assertEqual(extract_json_object_from_model_text('{"a": 1}'), {"a": 1})


class UnrecoverableParseDiagnosticsTests(unittest.TestCase):
    """Reproduces the production incident (6 JSON objects, none passed schema)
    and asserts the safe-fail payload carries enough diagnostic detail to
    explain WHY — not just an unclear 'none passed schema' summary."""

    def test_six_invalid_objects_none_valid_gets_full_diagnostics(self) -> None:
        pi = _korea_prompt_input(_valid_korea_payload())
        text = "\n".join(
            json.dumps({"draft": i, "explanation": f"attempt {i}"}, ensure_ascii=False)
            for i in range(6)
        )
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]

        self.assertIn("parse_multiple_json_objects_unrecoverable", codes)
        self.assertIn("gemini_multiple_json_objects_no_valid_schema", codes)
        self.assertIn("gemini_json_recovery_failed", codes)
        self.assertIn("gemini_json_missing_required_keys", codes)

        meta = result["parse_meta"]
        self.assertEqual(meta["json_object_count"], 6)
        self.assertIsInstance(meta["candidate_index"], int)
        self.assertIsInstance(meta["candidate_top_level_keys"], list)
        self.assertTrue(meta["missing_required_keys"])
        self.assertTrue(meta["schema_error_summary"])
        self.assertTrue(meta["first_300_chars_safe_excerpt"])
        self.assertLessEqual(len(meta["first_300_chars_safe_excerpt"]), 300)
        self.assertEqual(
            meta["parse_recovery_strategy"], "best_score_candidate_selected_but_invalid"
        )
        self.assertEqual(meta["parse_failure_stage"], "schema_validation")

        # Never dump the full raw model text verbatim as a single field.
        self.assertNotEqual(meta["first_300_chars_safe_excerpt"], text)

    def test_ambiguous_multiple_valid_marks_recovery_strategy_and_stage(self) -> None:
        payload1 = _valid_korea_payload()
        payload2 = _valid_korea_payload()
        payload2["top_5_news"]["items"][0]["headline"] = "Different but also valid headline"
        pi = _korea_prompt_input(payload1)
        text = json.dumps(payload1, ensure_ascii=False) + "\n" + json.dumps(payload2, ensure_ascii=False)
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        meta = result["parse_meta"]
        self.assertEqual(meta["parse_recovery_strategy"], "ambiguous_multiple_valid_candidates")
        self.assertEqual(meta["parse_failure_stage"], "candidate_selection")

    def test_single_invalid_object_still_gets_missing_keys_and_schema_summary(self) -> None:
        pi = _korea_prompt_input(_valid_korea_payload())
        result = parse_keysuri_generated_response('{"a": 1}', "keysuri_korea_tech", pi)
        codes = [i.get("code") for i in result["issues"]]
        self.assertNotIn("parse_multiple_json_objects_unrecoverable", codes)
        self.assertIn("gemini_json_missing_required_keys", codes)
        self.assertIn("gemini_json_schema_validation_failed", codes)
        meta = result["parse_meta"]
        self.assertEqual(meta["parse_recovery_strategy"], "single_object_no_recovery_needed")
        self.assertTrue(meta["missing_required_keys"])
        self.assertIn("schema_issue_codes", meta)
        self.assertTrue(meta["schema_issue_codes"])
        # Empty/missing top-level scope/heading are repaired even on invalid payloads,
        # so diagnostics show post-repair actuals plus before-repair blanks.
        self.assertEqual(meta.get("news_scope_actual"), "korea")
        self.assertEqual(meta.get("section_heading_actual"), "국내 테크 TOP 5")
        self.assertTrue(meta.get("repair_applied"))
        self.assertEqual(
            set(meta.get("repaired_fields") or []),
            {"news_scope", "section_heading"},
        )

    def test_recoverable_case_does_not_add_failure_diagnostics(self) -> None:
        """A schema-valid recovery must stay clean — no failure-only fields leak
        into a successful parse_meta."""
        payload = _valid_korea_payload()
        pi = _korea_prompt_input(payload)
        text = '{"error": "retry"}\n' + json.dumps(payload, ensure_ascii=False)
        result = parse_keysuri_generated_response(text, "keysuri_korea_tech", pi)
        self.assertEqual(result["parse_status"], "parsed_valid")
        self.assertEqual(result["issues"], [])
        self.assertNotIn("parse_recovery_strategy", result["parse_meta"])
        self.assertNotIn("schema_error_summary", result["parse_meta"])


if __name__ == "__main__":
    unittest.main()
