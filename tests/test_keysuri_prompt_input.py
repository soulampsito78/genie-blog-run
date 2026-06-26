"""Tests for Kee-Suri staged prompt input composer."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keysuri_news_contract import NEWS_SCOPE_GLOBAL, NEWS_SCOPE_KOREA, SECTION_TOP5_GLOBAL, SECTION_TOP5_KOREA
from keysuri_prompt_input import OUTPUT_CONTRACT, build_keysuri_prompt_input
from keysuri_source_gate import GateResult, GateIssue
from owner_review_exposure_log_store import append_owner_review_exposure

_REPO = Path(__file__).resolve().parent.parent


def _load_pack(name: str) -> dict:
    path = _REPO / "ops" / "feeds" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _minimal_claim(claim_id: str, *, category: str = "policy") -> dict:
    return {
        "claim_id": claim_id,
        "statement": f"Staged example statement for {claim_id}.",
        "claim_type": "general",
        "source_ids": ["s1"],
        "confidence_label": "reported",
        "category": category,
        "headline": f"Headline {claim_id}",
        "summary": f"Summary {claim_id}",
        "why_it_matters": "Staged why it matters.",
        "business_implication": "Staged business implication.",
    }


def _minimal_pack(program_id: str, claims: list[dict]) -> dict:
    return {
        "program_id": program_id,
        "generated_at": "2026-06-04T10:00:00+09:00",
        "notes": "Test pack",
        "sources": [
            {
                "source_id": "s1",
                "source_name": "Example",
                "source_url": "https://example.com/source/test",
                "source_tier": "T2_TIER1_WIRE",
                "fetched_at": "2026-06-04T10:00:00+09:00",
            }
        ],
        "claims": claims,
    }


class KeysuriPromptInputComposerTests(unittest.TestCase):
    def test_global_source_pack_ready_for_generation(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(result["prompt_status"], "ready_for_generation")
        self.assertEqual(result["prompt_profile"], "keysuri_global_tech_v1")

    def test_korea_source_pack_ready_for_generation(self) -> None:
        pack = _load_pack("keysuri_korea_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack)
        self.assertEqual(result["prompt_status"], "ready_for_generation")
        self.assertEqual(result["prompt_profile"], "keysuri_korea_tech_v1")

    def test_top_5_news_has_exactly_five_items(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        items = result["top_5_news"]["items"]
        self.assertEqual(len(items), 5)

    def test_global_news_scope(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(result["news_scope"], NEWS_SCOPE_GLOBAL)
        self.assertEqual(result["top_5_news"]["news_scope"], NEWS_SCOPE_GLOBAL)

    def test_korea_news_scope(self) -> None:
        pack = _load_pack("keysuri_korea_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack)
        self.assertEqual(result["news_scope"], NEWS_SCOPE_KOREA)
        self.assertEqual(result["top_5_news"]["news_scope"], NEWS_SCOPE_KOREA)

    def test_global_forbids_korea_top5_heading(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertIn(SECTION_TOP5_KOREA, result["forbidden_outputs"])
        self.assertEqual(result["section_heading"], SECTION_TOP5_GLOBAL)

    def test_korea_forbids_global_top5_heading(self) -> None:
        pack = _load_pack("keysuri_korea_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack)
        self.assertIn(SECTION_TOP5_GLOBAL, result["forbidden_outputs"])
        self.assertEqual(result["section_heading"], SECTION_TOP5_KOREA)

    def test_forbids_top_3(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertTrue(any("TOP 3" in entry for entry in result["forbidden_outputs"]))

    def test_block_source_gate_raises_value_error(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        blocked = GateResult(
            verdict="block",
            issues=(
                GateIssue(
                    code="test_block",
                    message="Blocked for test",
                    severity="block",
                ),
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            build_keysuri_prompt_input("keysuri_global_tech", pack, gate_result=blocked)
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_insufficient_candidates_hold_review_required(self) -> None:
        pack = _minimal_pack(
            "keysuri_global_tech",
            [_minimal_claim("c1"), _minimal_claim("c2")],
        )
        gate = GateResult(verdict="pass", issues=())
        result = build_keysuri_prompt_input("keysuri_global_tech", pack, gate_result=gate)
        self.assertEqual(result["prompt_status"], "hold_review_required")
        self.assertIsNone(result["top_5_news"])
        self.assertEqual(result["top_5_selection_result"]["verdict"], "hold")

    def test_includes_source_gate_result(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertIn(result["source_gate_result"], ("pass", "hold"))

    def test_includes_top_5_selection_result(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertIn("verdict", result["top_5_selection_result"])

    def test_includes_fixed_section_labels(self) -> None:
        pack = _load_pack("keysuri_korea_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_korea_tech", pack)
        labels = result["fixed_section_labels"]
        self.assertEqual(labels["top_5_news"], SECTION_TOP5_KOREA)
        self.assertIn("deep_dive", labels)
        self.assertIn("one_line_checkpoint", labels)
        self.assertIn("closing_sources", labels)

    def test_output_contract(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(result["output_contract"], OUTPUT_CONTRACT)
        self.assertEqual(result["output_schema_summary"]["output_contract"], OUTPUT_CONTRACT)

    def test_surfaces_candidate_funnel_summary(self) -> None:
        sources = [
            {
                "source_id": f"s{i}",
                "source_name": f"Source {i}",
                "source_url": f"https://source-{i}.example.com/news",
                "source_tier": "T2_TIER1_WIRE",
                "fetched_at": "2026-06-04T10:00:00+09:00",
            }
            for i in range(1, 7)
        ]
        claims = [
            {
                "claim_id": f"c{i}",
                "statement": f"Distinct global tech headline {i}",
                "claim_type": "general",
                "source_ids": [f"s{i}"],
                "confidence_label": "reported",
                "category": "policy",
                "headline": f"Distinct global tech headline {i}",
                "summary": f"Summary {i}",
                "why_it_matters": f"Why {i}",
                "business_implication": f"Business implication {i}",
            }
            for i in range(1, 7)
        ]
        pack = {
            "program_id": "keysuri_global_tech",
            "generated_at": "2026-06-04T10:00:00+09:00",
            "sources": sources,
            "claims": claims,
            "global_top5_selection": {
                "selected_source_ids": ["s1", "s2", "s3", "s4", "s5"],
                "watchlist_source_ids": ["s6"],
                "downstream_candidate_source_ids": ["s1", "s2", "s3", "s4", "s5", "s6"],
            },
            "source_pack_funnel_summary": {
                "scored_candidate_count": 24,
                "scored_selected_count": 5,
                "scored_watchlist_count": 2,
                "scored_rejected_count": 17,
                "replacement_pool_count": 2,
            },
        }

        result = build_keysuri_prompt_input(
            "keysuri_global_tech",
            pack,
            gate_result=GateResult(verdict="pass", issues=()),
        )

        self.assertEqual(result["prompt_status"], "ready_for_generation")
        summary = result["candidate_funnel_summary"]
        self.assertEqual(summary["scored_candidate_count"], 24)
        self.assertEqual(summary["pre_diversity_candidate_count"], 6)
        self.assertEqual(summary["post_diversity_selected_count"], 5)


class KeysuriPromptInputExposureLogMergeTests(unittest.TestCase):
    """Owner-review exposure log must merge into the cross-day dedup read path
    alongside sent_news_log, without modifying run_sent_news_dedup_gate itself.
    """

    def setUp(self) -> None:
        self.sent_tmp = tempfile.TemporaryDirectory()
        self.exposure_tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_SENT_NEWS_LOG_PATH": str(Path(self.sent_tmp.name) / "sent_news_log.json"),
                "GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH": str(
                    Path(self.exposure_tmp.name) / "owner_review_exposure_log.json"
                ),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.sent_tmp.cleanup()
        self.exposure_tmp.cleanup()

    def test_surfaces_log_read_counters_when_both_logs_empty(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(result["sent_log_read_count"], 0)
        self.assertEqual(result["exposure_log_read_count"], 0)
        self.assertTrue(result["exposure_log_read_ok"])
        self.assertEqual(result["combined_recent_log_count"], 0)
        self.assertNotIn("exposure_log_read_error_code", result)

    def test_exposure_log_only_entry_excludes_matching_candidate(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        baseline = build_keysuri_prompt_input("keysuri_global_tech", pack)
        first_item = baseline["top_5_news"]["items"][0]
        append_owner_review_exposure(
            run_id="prior-run",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[first_item],
        )
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(result["exposure_log_read_count"], 1)
        self.assertEqual(result["combined_recent_log_count"], result["sent_log_read_count"] + 1)
        selected_urls = {
            it.get("canonical_url") or it.get("url") for it in result["top_5_news"]["items"]
        }
        self.assertNotIn(first_item.get("canonical_url") or first_item.get("url"), selected_urls)

    def test_combined_count_sums_both_logs(self) -> None:
        pack = _load_pack("keysuri_global_sources.sample.json")
        baseline = build_keysuri_prompt_input("keysuri_global_tech", pack)
        items = baseline["top_5_news"]["items"]
        append_owner_review_exposure(
            run_id="prior-run",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[items[0]],
        )
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertEqual(
            result["combined_recent_log_count"],
            result["sent_log_read_count"] + result["exposure_log_read_count"],
        )

    def test_read_failure_surfaces_error_code_but_does_not_crash(self) -> None:
        exposure_path = Path(os.environ["GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH"])
        exposure_path.parent.mkdir(parents=True, exist_ok=True)
        exposure_path.write_text("{not valid json", encoding="utf-8")
        pack = _load_pack("keysuri_global_sources.sample.json")
        result = build_keysuri_prompt_input("keysuri_global_tech", pack)
        self.assertFalse(result["exposure_log_read_ok"])
        self.assertEqual(result["exposure_log_read_error_code"], "JSONDecodeError")
        self.assertEqual(result["exposure_log_read_count"], 0)
        self.assertEqual(result["prompt_status"], "ready_for_generation")

    def test_korea_and_global_exposure_logs_do_not_cross_contaminate(self) -> None:
        global_pack = _load_pack("keysuri_global_sources.sample.json")
        global_items = build_keysuri_prompt_input("keysuri_global_tech", global_pack)["top_5_news"]["items"]
        append_owner_review_exposure(
            run_id="prior-global-run",
            program_id="keysuri_global_tech",
            exposure_kind="owner_review_email",
            selected_items=[global_items[0]],
        )
        korea_pack = _load_pack("keysuri_korea_sources.sample.json")
        korea_result = build_keysuri_prompt_input("keysuri_korea_tech", korea_pack)
        self.assertEqual(korea_result["exposure_log_read_count"], 0)


class KeysuriPromptInputFixtureShapeTests(unittest.TestCase):
    def _assert_fixture_shape(self, fixture_name: str, program_id: str) -> None:
        fixture = json.loads((_REPO / "ops" / "feeds" / fixture_name).read_text(encoding="utf-8"))
        pack_name = (
            "keysuri_global_sources.sample.json"
            if program_id == "keysuri_global_tech"
            else "keysuri_korea_sources.sample.json"
        )
        built = build_keysuri_prompt_input(program_id, _load_pack(pack_name))
        for key in (
            "prompt_status",
            "prompt_profile",
            "top_5_news",
            "source_gate_result",
            "fixed_section_labels",
            "forbidden_outputs",
            "generation_instructions",
        ):
            self.assertIn(key, fixture, msg=f"missing {key} in {fixture_name}")
            self.assertIn(key, built)
        self.assertEqual(fixture["prompt_status"], built["prompt_status"])
        self.assertEqual(fixture["prompt_profile"], built["prompt_profile"])
        self.assertEqual(fixture["news_scope"], built["news_scope"])

    def test_global_prompt_input_fixture_aligned(self) -> None:
        self._assert_fixture_shape("keysuri_global_prompt_input.sample.json", "keysuri_global_tech")

    def test_korea_prompt_input_fixture_aligned(self) -> None:
        self._assert_fixture_shape("keysuri_korea_prompt_input.sample.json", "keysuri_korea_tech")


if __name__ == "__main__":
    unittest.main()
