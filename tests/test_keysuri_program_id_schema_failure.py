"""program_id repair + schema-failure diagnostics.

Run 20260730_202944_keysuri_global_tech_12c08526 blocked with
program_id_mismatch: generated_briefing.program_id '' vs 'keysuri_global_tech'.
Its persisted parse_meta showed expected_top_level_keys_present == [] while the
scope/heading repair had already fired, so an empty-content model response
surfaced as a program_id problem.
"""
from __future__ import annotations

import unittest

from keysuri_generation_prompt import (
    MODEL_OUTPUT_SNAPSHOT_MAX_CHARS,
    _repair_program_id_for_parse,
    parse_keysuri_generated_response,
    sanitized_model_output_snapshot,
)

GLOBAL = "keysuri_global_tech"
KOREA = "keysuri_korea_tech"


class ProgramIdRepairPolicyTests(unittest.TestCase):
    def test_1_empty_program_id_is_repaired_from_run_context(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": ""}, GLOBAL)
        self.assertEqual(out["program_id"], GLOBAL)
        self.assertTrue(diag["program_id_repair_applied"])
        self.assertEqual(diag["program_id_actual_before_repair"], "")

    def test_8_missing_program_id_is_repaired(self) -> None:
        out, diag = _repair_program_id_for_parse({}, GLOBAL)
        self.assertEqual(out["program_id"], GLOBAL)
        self.assertTrue(diag["program_id_repair_applied"])

    def test_2_correct_program_id_is_left_unchanged(self) -> None:
        src = {"program_id": GLOBAL}
        out, diag = _repair_program_id_for_parse(src, GLOBAL)
        self.assertEqual(out["program_id"], GLOBAL)
        self.assertFalse(diag["program_id_repair_applied"])

    def test_7_conflicting_non_empty_program_id_is_not_overwritten(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": KOREA}, GLOBAL)
        self.assertEqual(out["program_id"], KOREA)
        self.assertFalse(diag["program_id_repair_applied"])

    def test_9_wrong_mode_cannot_be_converted_into_global(self) -> None:
        for wrong in (KOREA, "today_genie", "tomorrow_genie", "unknown"):
            out, diag = _repair_program_id_for_parse({"program_id": wrong}, GLOBAL)
            self.assertEqual(out["program_id"], wrong, wrong)
            self.assertFalse(diag["program_id_repair_applied"], wrong)

    def test_unsupported_run_context_does_not_repair(self) -> None:
        out, diag = _repair_program_id_for_parse({"program_id": ""}, "today_genie")
        self.assertEqual(out["program_id"], "")
        self.assertFalse(diag["program_id_repair_attempted"])

    def test_repair_does_not_mutate_the_source_object(self) -> None:
        src = {"program_id": ""}
        out, _diag = _repair_program_id_for_parse(src, GLOBAL)
        self.assertEqual(src["program_id"], "")
        self.assertIsNot(out, src)


class EmptyContentStillBlocksTests(unittest.TestCase):
    def test_6_program_id_repair_does_not_rescue_a_contentless_response(self) -> None:
        """The 12c08526 shape: repairing program_id must not make it publishable."""
        result = parse_keysuri_generated_response('{"summary": "x"}', GLOBAL, {"program_id": GLOBAL})
        self.assertEqual(result["parse_status"], "parsed_invalid")
        self.assertIsNone(result["generated_briefing"])
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("gemini_json_missing_required_keys", codes)
        self.assertNotIn("program_id_mismatch", codes)

    def test_conflicting_program_id_still_reports_mismatch(self) -> None:
        result = parse_keysuri_generated_response(
            '{"program_id": "keysuri_korea_tech"}', GLOBAL, {"program_id": GLOBAL}
        )
        self.assertEqual(result["parse_status"], "parsed_invalid")
        codes = [i.get("code") for i in result["issues"]]
        self.assertIn("program_id_mismatch", codes)


class SchemaFailureDiagnosticsTests(unittest.TestCase):
    def test_10_11_snapshot_is_persisted_on_parse_failure(self) -> None:
        for raw in ('{"summary": "x"}', "no json here at all", "{}"):
            result = parse_keysuri_generated_response(raw, GLOBAL, {"program_id": GLOBAL})
            snap = result.get("raw_response_snapshot")
            self.assertIsInstance(snap, dict, raw)
            self.assertTrue(snap["captured"], raw)
            self.assertEqual(snap["original_length"], len(raw), raw)
            self.assertIn(raw[:10], snap["body_head"], raw)

    def test_12_credential_shaped_tokens_are_redacted(self) -> None:
        raw = (
            '{"a":1} X-Genie-Internal-Job-Token: zGXu_yH_secret_value '
            "api_key=AIzaSyABCDEFGHIJKLMNOP password: hunter2 "
            "Authorization: Bearer ya29.abcdefghijklmnop"
        )
        snap = sanitized_model_output_snapshot(raw)
        self.assertTrue(snap["redaction_applied"])
        body = snap["body_head"]
        for leaked in ("zGXu_yH_secret_value", "AIzaSyABCDEFGHIJKLMNOP", "hunter2", "ya29.abcdefghijklmnop"):
            self.assertNotIn(leaked, body, leaked)

    def test_snapshot_is_bounded(self) -> None:
        snap = sanitized_model_output_snapshot("x" * (MODEL_OUTPUT_SNAPSHOT_MAX_CHARS + 500))
        self.assertTrue(snap["truncated"])
        self.assertEqual(len(snap["body_head"]), MODEL_OUTPUT_SNAPSHOT_MAX_CHARS)

    def test_empty_raw_text_is_marked_not_captured(self) -> None:
        snap = sanitized_model_output_snapshot("")
        self.assertFalse(snap["captured"])
        self.assertEqual(snap["original_length"], 0)


if __name__ == "__main__":
    unittest.main()
