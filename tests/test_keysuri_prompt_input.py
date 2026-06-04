"""Tests for Kee-Suri staged prompt input composer."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from keysuri_news_contract import NEWS_SCOPE_GLOBAL, NEWS_SCOPE_KOREA, SECTION_TOP5_GLOBAL, SECTION_TOP5_KOREA
from keysuri_prompt_input import OUTPUT_CONTRACT, build_keysuri_prompt_input
from keysuri_source_gate import GateResult, GateIssue

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
