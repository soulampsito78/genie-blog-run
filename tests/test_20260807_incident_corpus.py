"""Offline regression for the production incident corpus index (A–E)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INDEX = _REPO / "ops" / "feeds" / "incident_fixtures" / "CORPUS_INDEX.json"
_REQUIRED_INDEX_FIELDS = (
    "incident_key",
    "program_id",
    "run_id",
    "incident_id",
    "failure_class",
    "failure_stage",
    "issue_codes",
    "fixture_path",
    "harness_path",
    "closeout_doc",
    "invariant",
    "old_behavior",
    "status",
)


def _load_index() -> dict:
    return json.loads(_INDEX.read_text(encoding="utf-8"))


def _by_key(index: dict) -> dict:
    return {row["incident_key"]: row for row in index["incidents"]}


class IncidentCorpus20260807Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _load_index()
        cls.by_key = _by_key(cls.index)

    def test_01_index_lists_a_through_e_regressed(self) -> None:
        keys = [row["incident_key"] for row in self.index["incidents"]]
        self.assertEqual(keys, ["A", "B", "C", "D", "E"])
        for key in keys:
            row = self.by_key[key]
            for field in _REQUIRED_INDEX_FIELDS:
                self.assertIn(field, row)
            self.assertEqual(row["status"], "regressed")

    def test_02_all_fixtures_and_harnesses_exist(self) -> None:
        for row in self.index["incidents"]:
            fixture = _REPO / row["fixture_path"]
            harness = _REPO / row["harness_path"]
            closeout = _REPO / row["closeout_doc"]
            self.assertTrue(fixture.is_file(), msg=row["fixture_path"])
            self.assertTrue(harness.is_file(), msg=row["harness_path"])
            self.assertTrue(closeout.is_file(), msg=row["closeout_doc"])

    def test_03_incident_a_qa_never_qualifies_as_natural_completer(self) -> None:
        from today_genie_execution_identity import natural_slot_completer_qualification

        row = self.by_key["A"]
        self.assertEqual(row["failure_class"], "EXECUTION_IDENTITY/NATURAL_SLOT_FALSE_MATCH")
        fx = json.loads((_REPO / row["fixture_path"]).read_text(encoding="utf-8"))
        qa = fx["qa_artifact"]
        self.assertEqual(qa["run_id"], "20260807_003207_today_genie_255d3454")
        self.assertTrue(qa["email_sent"])
        self.assertEqual(qa["execution_class"], "qa_manual")
        self.assertEqual(fx["expected_qualification"]["qualifies"], False)

        match = natural_slot_completer_qualification(
            qa, kst_date=fx["kst_date"], scheduled_slot=fx["scheduled_slot"]
        )
        self.assertFalse(match.qualifies)
        self.assertEqual(
            match.disqualify_reason,
            fx["expected_qualification"]["disqualify_reason"],
        )
        expected_actions = fx["expected_gate_actions"]
        self.assertEqual(expected_actions["natural_request_with_qa_artifact_only"], "admit")
        self.assertEqual(
            expected_actions["adversarial_force_treat_emailed_qa_as_natural"],
            "reject_invalid_match",
        )
        self.assertEqual(
            expected_actions["legitimate_natural_duplicate_present"],
            "skip_legitimate_duplicate",
        )

    def test_04_incident_b_display_shell_fixture_fields(self) -> None:
        row = self.by_key["B"]
        self.assertEqual(row["failure_class"], "MODEL_CONTRACT_MALFORMED")
        fx = json.loads((_REPO / row["fixture_path"]).read_text(encoding="utf-8"))
        self.assertEqual(fx["run_id"], row["run_id"])
        self.assertEqual(fx["first_failed_stage"], "generation_validation")
        for key in (
            "operational_status",
            "generated_status",
            "top_5_news",
            "deep_dive",
            "one_line_checkpoint",
            "closing_sources",
        ):
            self.assertIn(key, fx["missing_required_keys"])
            self.assertNotIn(key, fx["model_display_shell"])
        for code in (
            "top_5_news_missing",
            "gemini_json_missing_required_keys",
            "gemini_json_schema_validation_failed",
        ):
            self.assertIn(code, fx["issue_codes_observed"])

    def test_05_incident_c_unicode_boundary_fixture_fields(self) -> None:
        row = self.by_key["C"]
        self.assertEqual(row["failure_class"], "VISIBLE_TEXT_UNICODE_BOUNDARY")
        fx = json.loads((_REPO / row["fixture_path"]).read_text(encoding="utf-8"))
        self.assertEqual(fx["run_id"], "20260807_131133_keysuri_global_tech_96d921fa")
        self.assertTrue(fx["visible_text_ellipsis_blocked"])
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", fx["issue_codes_observed"])
        sample = fx["blocking_pattern_example"]
        self.assertIn("Leadership..", sample)
        self.assertIn("\u201d", sample)  # ” curly double quote

    def test_06_incident_d_connector_bridge_repairs_not_blocked(self) -> None:
        from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

        row = self.by_key["D"]
        self.assertEqual(row["failure_class"], "VISIBLE_TEXT_CONNECTOR_BRIDGE")
        fx = json.loads((_REPO / row["fixture_path"]).read_text(encoding="utf-8"))
        self.assertEqual(fx["run_id"], row["run_id"])
        text = fx["blocking_pattern_example"]
        self.assertEqual(
            text,
            "KDB생명 인수전, 한국투자·한화·흥국 '3파전'…삼성·교보 불참",
        )
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        self.assertEqual(result.text, fx["expected_post_patch_title"])
        self.assertNotRegex(result.text, r"…|\.{2,}")

    def test_07_incident_e_feed_readmore_repairs_not_blocked(self) -> None:
        from keysuri_visible_text_quality import repair_korean_connector_ellipsis_text

        row = self.by_key["E"]
        self.assertEqual(row["failure_class"], "VISIBLE_TEXT_FEED_READMORE_ELLIPSIS")
        fx = json.loads((_REPO / row["fixture_path"]).read_text(encoding="utf-8"))
        self.assertEqual(fx["run_id"], row["run_id"])
        text = fx["blocking_pattern_example"]
        self.assertIn("[…]", text)
        result = repair_korean_connector_ellipsis_text(text)
        self.assertFalse(result.blocked)
        self.assertTrue(result.repaired)
        self.assertNotIn("…", result.text)


if __name__ == "__main__":
    unittest.main()
