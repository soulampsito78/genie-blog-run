"""Production-faithful recurrence-prevention harness for KeeSuri Global.

Extends tests/test_keysuri_generation_recovery.py (which already covers the
bounded-recovery attempt counts) with the scenarios that were missing. Every
case drives real production functions; the only fakes are external boundaries
(model caller, SMTP recorder). No network, no Scheduler, no image API.
"""
from __future__ import annotations

import json
import unittest

from keysuri_briefing_content_quality import (
    _find_truncated_visible_lines,
    validate_global_post_render_visible_quality,
)
from keysuri_generation_prompt import (
    GENERATION_CONTRACT_VERSION,
    MODEL_OUTPUT_SNAPSHOT_MAX_CHARS,
    _repair_program_id_for_parse,
    classify_failure_priority,
    generation_contract_record,
    parse_keysuri_generated_response,
    sanitized_model_output_snapshot,
)
from keysuri_live_source_smoke import GLOBAL_GENERATION_CALL_BUDGET
from keysuri_recurrence_metrics import (
    RECURRENCE_COUNTER_NAMES,
    aggregate_recurrence_counters,
    recurrence_counters_for_run,
)
from keysuri_service_full_run import reissue_top5_content_issue_codes

GLOBAL = "keysuri_global_tech"
KOREA = "keysuri_korea_tech"

B09B8B02_LINE = "구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가"


class SideEffectRecorder:
    """External-boundary fake: records instead of sending.

    Only meaningful when actually wired into a send path. Cases here assert the
    upstream gating signal (no publishable payload) rather than a call count on
    an unwired recorder; end-to-end SMTP counts live in
    tests/test_keysuri_generation_recovery.py, which drives the real send path.
    """

    def __init__(self) -> None:
        self.smtp_calls = 0
        self.customer_approve_calls = 0
        self.customer_final_calls = 0
        self.image_calls = 0

    def send(self, *_a, **_kw) -> bool:
        self.smtp_calls += 1
        return True


def _html(*lines: str) -> str:
    return "".join(f"<p>{line}</p>" for line in lines)


class ControlA_BudgetCeilingTests(unittest.TestCase):
    def test_global_ceiling_is_two_total_attempts(self) -> None:
        self.assertEqual(GLOBAL_GENERATION_CALL_BUDGET, 2)


class ControlB_ContractFingerprintTests(unittest.TestCase):
    def test_contract_record_carries_required_fields(self) -> None:
        rec = generation_contract_record(GLOBAL, attempt=1, model="gemini-3-flash-preview")
        self.assertEqual(rec["generation_contract_version"], GENERATION_CONTRACT_VERSION)
        self.assertEqual(rec["expected_program_id"], GLOBAL)
        self.assertEqual(rec["expected_news_scope"], "global")
        self.assertEqual(rec["required_item_count"], 5)
        self.assertTrue(rec["required_top_level_keys"])
        self.assertTrue(rec["schema_fingerprint"])
        self.assertEqual(rec["model_identifier"], "gemini-3-flash-preview")
        self.assertEqual(rec["generation_attempt"], 1)

    def test_retry_attempt_records_reason_and_number(self) -> None:
        rec = generation_contract_record(GLOBAL, attempt=2, retry_reason="contentless_first_attempt")
        self.assertEqual(rec["generation_attempt"], 2)
        self.assertEqual(rec["retry_reason"], "contentless_first_attempt")

    def test_prompt_template_fingerprint_is_stable_and_not_the_prompt(self) -> None:
        a = generation_contract_record(GLOBAL, prompt_text="TEMPLATE-A")
        b = generation_contract_record(GLOBAL, prompt_text="TEMPLATE-A")
        c = generation_contract_record(GLOBAL, prompt_text="TEMPLATE-B")
        self.assertEqual(a["prompt_template_fingerprint"], b["prompt_template_fingerprint"])
        self.assertNotEqual(a["prompt_template_fingerprint"], c["prompt_template_fingerprint"])
        self.assertNotIn("TEMPLATE-A", json.dumps(a))

    def test_schema_fingerprint_differs_across_modes(self) -> None:
        self.assertNotEqual(
            generation_contract_record(GLOBAL)["schema_fingerprint"],
            generation_contract_record(KOREA)["schema_fingerprint"],
        )

    def test_parse_failure_attaches_contract_record(self) -> None:
        r = parse_keysuri_generated_response('{"summary":"x"}', GLOBAL, {"program_id": GLOBAL})
        self.assertEqual(r["generation_contract"]["expected_program_id"], GLOBAL)


class ControlC_FailurePriorityTests(unittest.TestCase):
    def test_no_json_outranks_everything(self) -> None:
        fc = classify_failure_priority(["program_id_mismatch", "json_extract_failed"])
        self.assertEqual(fc["primary_failure_code"], "json_extract_failed")
        self.assertEqual(fc["primary_failure_tier"], "no_extractable_json")

    def test_12c08526_shape_reports_structure_not_program_id(self) -> None:
        fc = classify_failure_priority(
            ["program_id_mismatch", "top_5_news_missing", "gemini_json_missing_required_keys"]
        )
        self.assertEqual(fc["primary_failure_tier"], "contentless_or_missing_structure")
        self.assertNotEqual(fc["primary_failure_code"], "program_id_mismatch")
        self.assertIn("program_id_mismatch", fc["secondary_failure_codes"])

    def test_conflicting_identifier_wins_when_structure_is_present(self) -> None:
        fc = classify_failure_priority(["top_5_item_count_invalid", "program_id_mismatch"])
        self.assertEqual(fc["primary_failure_code"], "program_id_mismatch")
        self.assertEqual(fc["primary_failure_tier"], "conflicting_mode_or_identifier")

    def test_section_defect_outranks_post_render(self) -> None:
        fc = classify_failure_priority(
            ["global_visible_text_truncated_deep_dive", "top_5_item_count_invalid"]
        )
        self.assertEqual(fc["primary_failure_tier"], "section_schema_defect")

    def test_unknown_codes_fall_through_to_ordinary_tier(self) -> None:
        fc = classify_failure_priority(["some_unmapped_code"])
        self.assertEqual(fc["primary_failure_code"], "some_unmapped_code")
        self.assertEqual(fc["primary_failure_tier"], "ordinary_content_validation_defect")

    def test_empty_codes_are_safe(self) -> None:
        fc = classify_failure_priority([])
        self.assertIsNone(fc["primary_failure_code"])

    def test_parse_failure_result_carries_classification(self) -> None:
        r = parse_keysuri_generated_response('{"summary":"x"}', GLOBAL, {"program_id": GLOBAL})
        self.assertEqual(
            r["failure_classification"]["primary_failure_tier"], "contentless_or_missing_structure"
        )


class ControlD_RecurrenceCounterTests(unittest.TestCase):
    def test_counter_names_are_complete(self) -> None:
        for name in ("generation_attempts", "bounded_retry_count", "retry_success",
                     "retry_exhausted", "json_extraction_failure", "contentless_response_failure",
                     "program_id_repair_count", "conflicting_program_id_block_count",
                     "schema_validation_failure", "post_render_truncation_block",
                     "global_run_success", "global_run_safe_fail"):
            self.assertIn(name, RECURRENCE_COUNTER_NAMES)

    def test_successful_run_counts_success_only(self) -> None:
        c = recurrence_counters_for_run(
            {"validation_result": "pass", "email_sent": True, "generation_attempt_count": 1}
        )
        self.assertEqual(c["global_run_success"], 1)
        self.assertEqual(c["global_run_safe_fail"], 0)
        self.assertEqual(c["generation_attempts"], 1)

    def test_retry_exhaustion_is_counted(self) -> None:
        c = recurrence_counters_for_run({
            "generation_attempt_count": 2, "global_recovery_attempted": True,
            "global_generation_budget_exhausted": True, "validation_result": "block",
        })
        self.assertEqual(c["bounded_retry_count"], 1)
        self.assertEqual(c["retry_exhausted"], 1)
        self.assertEqual(c["global_run_safe_fail"], 1)

    def test_truncation_block_counted_from_post_render_diagnostics(self) -> None:
        c = recurrence_counters_for_run({
            "validation_result": "block",
            "post_render_qa_diagnostics": {"issue_codes": ["global_visible_text_truncated_deep_dive"]},
        })
        self.assertEqual(c["post_render_truncation_block"], 1)

    def test_conflicting_program_id_block_counted(self) -> None:
        c = recurrence_counters_for_run(
            {"failure_classification": {"primary_failure_code": "program_id_mismatch",
                                        "secondary_failure_codes": []}}
        )
        self.assertEqual(c["conflicting_program_id_block_count"], 1)

    def test_program_id_repair_counted_from_parse_meta(self) -> None:
        c = recurrence_counters_for_run({"parse_meta": {"repaired_fields": ["news_scope", "program_id"]}})
        self.assertEqual(c["program_id_repair_count"], 1)

    def test_aggregation_sums_across_runs(self) -> None:
        total = aggregate_recurrence_counters([
            {"validation_result": "pass", "email_sent": True, "generation_attempt_count": 1},
            {"validation_result": "pass", "email_sent": True, "generation_attempt_count": 2,
             "global_recovery_attempted": True, "global_recovery_result": "succeeded"},
            {"validation_result": "block", "issue_codes": ["json_extract_failed"]},
        ])
        self.assertEqual(total["global_run_success"], 2)
        self.assertEqual(total["global_run_safe_fail"], 1)
        self.assertEqual(total["generation_attempts"], 3)
        self.assertEqual(total["retry_success"], 1)
        self.assertEqual(total["json_extraction_failure"], 1)

    def test_malformed_record_is_safe(self) -> None:
        self.assertEqual(recurrence_counters_for_run({})["generation_attempts"], 0)


class TruncationScenarioTests(unittest.TestCase):
    def test_scenario_2_b09b8b02_regression_passes_full_post_render_gate(self) -> None:
        r = validate_global_post_render_visible_quality(_html(B09B8B02_LINE))
        self.assertTrue(r.ok)
        self.assertEqual(_find_truncated_visible_lines(_html(B09B8B02_LINE)), [])

    def test_scenario_3_genuine_truncation_blocks_before_send(self) -> None:
        line = "이번 발표는 향후 국내 인프라 투자 계획에 직접적인 영향을 주는 발표가"
        r = validate_global_post_render_visible_quality(_html(line))
        # not ok => the caller returns a failure before reaching SMTP
        self.assertFalse(r.ok)
        self.assertIn("global_visible_text_truncated_deep_dive", [i.code for i in r.issues])


class ProgramIdScenarioTests(unittest.TestCase):
    def test_scenario_4_missing_program_id_repaired(self) -> None:
        out, diag = _repair_program_id_for_parse({}, GLOBAL)
        self.assertEqual(out["program_id"], GLOBAL)
        self.assertTrue(diag["program_id_repair_applied"])

    def test_scenario_5_empty_program_id_repaired(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": ""}, GLOBAL)
        self.assertEqual(out["program_id"], GLOBAL)
        self.assertTrue(diag["program_id_repair_applied"])

    def test_scenario_6_conflicting_program_id_hard_blocks_without_retry(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": KOREA}, GLOBAL)
        self.assertEqual(out["program_id"], KOREA)
        self.assertFalse(diag["program_id_repair_applied"])
        result = parse_keysuri_generated_response(
            json.dumps({"program_id": KOREA}), GLOBAL, {"program_id": GLOBAL}
        )
        self.assertNotEqual(result["parse_status"], "parsed_valid")
        self.assertIsNone(result["generated_briefing"])
        # Not in the bounded-repair eligibility set, so no corrective call.
        from keysuri_live_source_smoke import _global_contract_repair_codes
        self.assertEqual(_global_contract_repair_codes(["program_id_mismatch"]), [])

    def test_scenario_12_wrong_mode_cannot_be_converted_into_global(self) -> None:
        for wrong in (KOREA, "today_genie", "tomorrow_genie"):
            out, diag = _repair_program_id_for_parse({"program_id": wrong}, GLOBAL)
            self.assertEqual(out["program_id"], wrong, wrong)
            self.assertFalse(diag["program_id_repair_applied"], wrong)


class ContentIntegrityScenarioTests(unittest.TestCase):
    def _cards(self):
        return [
            {"headline": f"제미나이 한국어 제목 {i}", "canonical_url": f"https://example.invalid/{i}",
             "summary": f"「제미나이 한국어 제목 {i}」 관련 공식 발표가 {i}건 확인되었습니다.",
             "why_it_matters": f"해당 발표는 {i}분기 투자 판단에 영향을 줍니다.",
             "business_implication": f"도입 비용을 {i}순위로 점검하시면 됩니다."}
            for i in range(1, 6)
        ]

    def test_scenario_13_placeholder_title_blocked(self) -> None:
        cards = self._cards()
        cards[0]["headline"] = "IEEE Spectrum 기반 AI·테크 신호 1"
        self.assertIn("reissue_top5_placeholder_title", reissue_top5_content_issue_codes(cards))

    def test_scenario_14_duplicate_sentence_blocked(self) -> None:
        cards = self._cards()
        cards[0]["business_implication"] = (
            "도입 비용을 1순위로 점검하시면 됩니다. 도입 비용을, 1순위로 점검하시면 됩니다."
        )
        self.assertIn("reissue_top5_duplicate_sentence", reissue_top5_content_issue_codes(cards))

    def test_known_good_cards_pass(self) -> None:
        self.assertEqual(reissue_top5_content_issue_codes(self._cards()), [])


class SanitizationScenarioTests(unittest.TestCase):
    def test_scenario_15_no_planted_secret_survives(self) -> None:
        raw = (
            '{"a":1} X-Genie-Internal-Job-Token: zGXu_yH_TOKENVALUE '
            "api_key=AIzaSyABCDEFGHIJKLMNOP password: hunter2 secret: s3cr3tval "
            "cookie: sid=abc123 Authorization: Bearer ya29.abcdefghijklmnop"
        )
        snap = sanitized_model_output_snapshot(raw)
        self.assertTrue(snap["redaction_applied"])
        for leaked in ("zGXu_yH_TOKENVALUE", "AIzaSyABCDEFGHIJKLMNOP", "hunter2",
                       "s3cr3tval", "ya29.abcdefghijklmnop"):
            self.assertNotIn(leaked, snap["body_head"], leaked)

    def test_scenario_16_oversized_snapshot_is_bounded(self) -> None:
        raw = "y" * (MODEL_OUTPUT_SNAPSHOT_MAX_CHARS + 4321)
        snap = sanitized_model_output_snapshot(raw)
        self.assertTrue(snap["truncated"])
        self.assertEqual(snap["original_length"], len(raw))
        self.assertEqual(len(snap["body_head"]), MODEL_OUTPUT_SNAPSHOT_MAX_CHARS)

    def test_scenario_17_failed_cases_yield_no_publishable_payload(self) -> None:
        rec = SideEffectRecorder()
        for raw in ('{"summary":"x"}', "not json", json.dumps({"program_id": KOREA})):
            r = parse_keysuri_generated_response(raw, GLOBAL, {"program_id": GLOBAL})
            self.assertNotEqual(r["parse_status"], "parsed_valid")
            self.assertIsNone(r["generated_briefing"])
            self.assertIsInstance(r["raw_response_snapshot"], dict)
        # Recorder is deliberately unwired: nothing in this path may reach it.
        self.assertEqual(rec.smtp_calls, 0)
        self.assertEqual(rec.customer_approve_calls, 0)
        self.assertEqual(rec.customer_final_calls, 0)
        self.assertEqual(rec.image_calls, 0)


class CrossModeRegressionTests(unittest.TestCase):
    def test_scenario_18_global_repair_does_not_leak_into_other_modes(self) -> None:
        for mode in ("today_genie", "tomorrow_genie"):
            out, diag = _repair_program_id_for_parse({"program_id": ""}, mode)
            self.assertEqual(out["program_id"], "")
            self.assertFalse(diag["program_id_repair_attempted"], mode)

    def test_korea_keeps_its_own_deterministic_repair(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": ""}, KOREA)
        self.assertEqual(out["program_id"], KOREA)
        self.assertTrue(diag["program_id_repair_applied"])

    def test_korea_contract_is_distinct_from_global(self) -> None:
        self.assertEqual(generation_contract_record(KOREA)["expected_news_scope"], "korea")


if __name__ == "__main__":
    unittest.main()
