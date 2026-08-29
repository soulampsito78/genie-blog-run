"""The contract must not reject a briefing the model actually wrote.

2026-08-30 isolated qualification ran the real production prompt builder, the
real Gemini client and the real parser against persisted source packs. Every
failure below was a *contract* defect, not a model defect: the model returned
five complete, well-grounded Korean cards and the pipeline threw them away.

  * ``closing_source_label_missing`` — the validator requires ``label`` on every
    ``closing_sources.source_list`` entry, and the schema example the model is
    shown lists only source_id / source_name / source_url. The model produced
    exactly what it was asked for.
  * ``top_5_news_item_why_it_matters_missing`` — the schema asks for
    ``why_it_matters`` / ``business_implication`` while the rest of the pipeline
    reads ``why_now`` / ``owner_angle``, and the prompt teaches both. The model
    answered in the other synonym on all five items.
  * ``top_5_news_item_headline_missing`` / ``source_ids`` / ``category`` /
    ``confidence_label`` — Korea answered in ``korean_title`` and did not echo
    back identity the prompt had just handed it.
  * ``top_5_sequence_mismatch`` — the model returned the same five articles with
    ranks 3 and 4 swapped. Rank is ours.
  * ``deep_dive_source_ids_empty`` / ``deep_dive_confidence_invalid`` — the deep
    dive is written about the five selected articles, so its identity is theirs.

Each repair copies or reorders identity the prompt already supplied. None
invents prose, and none crosses an article boundary.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_gemini_client import is_max_tokens_error  # noqa: E402
from keysuri_generation_prompt import (  # noqa: E402
    _repair_closing_source_labels_for_parse,
    _repair_deep_dive_identity_for_parse,
    _repair_top5_item_field_aliases_for_parse,
    _repair_top5_item_identity_for_parse,
    _repair_top5_item_order_for_parse,
)

EVIDENCE = [
    {"news_id": "n1", "source_ids": ["s1"], "category": "ai_software_platform",
     "confidence_label": "reported", "headline": "First"},
    {"news_id": "n2", "source_ids": ["s2"], "category": "semiconductor_chip_infra",
     "confidence_label": "reported", "headline": "Second"},
]
PROMPT_INPUT = {"top_5_news": {"items": EVIDENCE}}


def _briefing(items, **extra):
    out = {"top_5_news": {"items": items}}
    out.update(extra)
    return out


class ClosingSourceLabelTests(unittest.TestCase):
    def test_label_is_completed_from_the_entry_s_own_name(self) -> None:
        obj = {"closing_sources": {"source_list": [
            {"source_id": "s1", "source_name": "TechCrunch AI",
             "source_url": "https://example.com/a"}]}}
        out, diag = _repair_closing_source_labels_for_parse(obj)
        self.assertEqual(out["closing_sources"]["source_list"][0]["label"], "TechCrunch AI")
        self.assertEqual(diag["closing_source_label_repair_count"], 1)

    def test_an_existing_label_is_never_overwritten(self) -> None:
        obj = {"closing_sources": {"source_list": [
            {"source_id": "s1", "source_name": "A", "label": "kept"}]}}
        out, _ = _repair_closing_source_labels_for_parse(obj)
        self.assertEqual(out["closing_sources"]["source_list"][0]["label"], "kept")

    def test_nothing_is_invented_without_a_name(self) -> None:
        obj = {"closing_sources": {"source_list": [{"source_url": "https://x/y"}]}}
        out, diag = _repair_closing_source_labels_for_parse(obj)
        self.assertNotIn("label", out["closing_sources"]["source_list"][0])
        self.assertFalse(diag["closing_source_label_repair_applied"])


class ItemFieldAliasTests(unittest.TestCase):
    def test_the_schema_name_is_filled_from_the_synonym(self) -> None:
        items = [{"news_id": "n1", "why_now": "지금 중요한 이유입니다.",
                  "owner_angle": "주인님 관점입니다.", "what_happened": "무슨 일입니다.",
                  "korean_title": "한국어 제목"}]
        out, diag = _repair_top5_item_field_aliases_for_parse(_briefing(items))
        item = out["top_5_news"]["items"][0]
        self.assertEqual(item["why_it_matters"], "지금 중요한 이유입니다.")
        self.assertEqual(item["business_implication"], "주인님 관점입니다.")
        self.assertEqual(item["summary"], "무슨 일입니다.")
        self.assertEqual(item["headline"], "한국어 제목")
        self.assertEqual(diag["top5_item_alias_repair_count"], 4)

    def test_a_value_the_model_supplied_is_never_replaced(self) -> None:
        items = [{"news_id": "n1", "why_it_matters": "원본", "why_now": "다른 값"}]
        out, _ = _repair_top5_item_field_aliases_for_parse(_briefing(items))
        self.assertEqual(out["top_5_news"]["items"][0]["why_it_matters"], "원본")


class ItemIdentityTests(unittest.TestCase):
    def test_identity_comes_from_the_evidence_the_prompt_supplied(self) -> None:
        items = [{"news_id": "n1", "headline": "제목"}]
        out, diag = _repair_top5_item_identity_for_parse(_briefing(items), PROMPT_INPUT)
        item = out["top_5_news"]["items"][0]
        self.assertEqual(item["source_ids"], ["s1"])
        self.assertEqual(item["category"], "ai_software_platform")
        self.assertEqual(item["confidence_label"], "reported")
        self.assertTrue(diag["top5_item_identity_repair_applied"])

    def test_an_unmatched_item_never_borrows_a_neighbour_s_identity(self) -> None:
        items = [{"news_id": "unmatched", "headline": "제목"}]
        out, diag = _repair_top5_item_identity_for_parse(_briefing(items), PROMPT_INPUT)
        self.assertNotIn("source_ids", out["top_5_news"]["items"][0])
        self.assertFalse(diag["top5_item_identity_repair_applied"])


class ItemOrderTests(unittest.TestCase):
    def test_the_same_five_in_a_different_order_are_restored(self) -> None:
        items = [{"news_id": "n2", "rank": 1}, {"news_id": "n1", "rank": 2}]
        out, diag = _repair_top5_item_order_for_parse(_briefing(items), PROMPT_INPUT)
        got = [(i["news_id"], i["rank"]) for i in out["top_5_news"]["items"]]
        self.assertEqual(got, [("n1", 1), ("n2", 2)])
        self.assertTrue(diag["top5_item_order_repair_applied"])

    def test_a_different_set_of_articles_still_fails(self) -> None:
        """Reordering must never be able to hide an invented article."""
        items = [{"news_id": "n1", "rank": 1}, {"news_id": "invented", "rank": 2}]
        out, diag = _repair_top5_item_order_for_parse(_briefing(items), PROMPT_INPUT)
        self.assertFalse(diag["top5_item_order_repair_applied"])
        self.assertEqual(
            [i["news_id"] for i in out["top_5_news"]["items"]], ["n1", "invented"])


class DeepDiveIdentityTests(unittest.TestCase):
    def test_deep_dive_identity_comes_from_the_top5_it_describes(self) -> None:
        items = [{"news_id": "n1", "source_ids": ["s1"], "confidence_label": "reported"},
                 {"news_id": "n2", "source_ids": ["s2"], "confidence_label": "reported"}]
        obj = _briefing(items, deep_dive={"body": "본문"})
        out, diag = _repair_deep_dive_identity_for_parse(obj)
        self.assertEqual(out["deep_dive"]["source_ids"], ["s1", "s2"])
        self.assertEqual(out["deep_dive"]["confidence_label"], "reported")
        self.assertTrue(diag["deep_dive_identity_repair_applied"])

    def test_no_confidence_is_asserted_when_the_items_carry_none(self) -> None:
        items = [{"news_id": "n1", "source_ids": ["s1"]}]
        obj = _briefing(items, deep_dive={"body": "본문"})
        out, _ = _repair_deep_dive_identity_for_parse(obj)
        self.assertNotIn("confidence_label", out["deep_dive"])


class MaxTokensRecoveryTests(unittest.TestCase):
    """A truncated answer is as unusable as an empty one."""

    def test_both_max_tokens_shapes_trigger_recovery(self) -> None:
        self.assertTrue(is_max_tokens_error(
            RuntimeError("keysuri_gemini_max_tokens_no_text: ...")))
        self.assertTrue(is_max_tokens_error(
            RuntimeError("keysuri_gemini_max_tokens_truncated_text: ...")))

    def test_an_unrelated_error_does_not(self) -> None:
        self.assertFalse(is_max_tokens_error(RuntimeError("Vertex Gemini call failed")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
