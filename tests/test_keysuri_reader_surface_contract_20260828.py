"""Contract B: one canonical reader-surface producer, proved adversarially.

The 2026-08-28 12:30 Global run completed its output with
``copy.deepcopy(prompt_input["top_5_news"])`` after the model contract collapsed
and the single corrective call failed. That structure is the evidence pack, so
five owner-review cards were built out of raw English RSS text.

These tests inject source text at every upstream stage that can reach a briefing
and prove none of it crosses into a reader field. They assert the boundary's
behaviour, not the wording of any detector.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_briefing_content_enricher import (  # noqa: E402
    _READER_SURFACE_DIAGNOSTIC_KEY,
    enrich_generated_briefing_content,
)
from keysuri_reader_surface import (  # noqa: E402
    PROSE_FIELDS,
    READER_IDENTITY_UNMATCHED,
    READER_PROSE_WAS_SOURCE_TEXT,
    UNAVAILABLE_MARKER,
    ReaderArticle,
    build_reader_article,
    enforce_reader_surface,
)

PROGRAM = "keysuri_global_tech"

# Real English source text from the 2026-08-28 owner-review artifact.
EVIDENCE = [
    {
        "rank": 1,
        "news_id": "claim-1",
        "headline": "NVIDIA’s First CPU Built for Agents Is Shipping Now",
        "summary": (
            "NVIDIA Vice President of Hyperscale and HPC Ian Buck hand-delivers Vera "
            "CPU systems across the AI ecosystem as Vera begins shipping at scale."
        ),
        "why_it_matters": "Vera begins shipping at scale across the AI ecosystem.",
        "source_ids": ["src-1"],
        "source_url": "https://blogs.nvidia.com/blog/vera-cpu/",
        "source_name": "NVIDIA Blog",
        "category": "ai_infra",
    },
    {
        "rank": 2,
        "news_id": "claim-2",
        "headline": "How OpenAI let a mob of LLM agents game a test and ransack Hugging Face",
        "summary": "OpenAI agents conspired among themselves to game a test.",
        "why_it_matters": "Agent supervision is now an operational question.",
        "source_ids": ["src-2"],
        "source_url": "https://arstechnica.com/ai/agents/",
        "source_name": "Ars Technica",
        "category": "ai_software_platform",
    },
]

PROMPT_INPUT = {"top_5_news": {"items": EVIDENCE}}


def _authored(news_id: str, **overrides):
    """A well-formed Korean card the model could legitimately have written."""
    item = {
        "rank": 1,
        "news_id": news_id,
        "headline": "엔비디아, 에이전트 전용 CPU 양산 시작",
        "summary": "엔비디아가 에이전트 워크로드를 겨냥한 첫 CPU의 대량 출하를 시작했습니다.",
        "why_it_matters": "추론 비용 구조가 바뀌면 국내 서버·부품 수요 계획도 함께 움직입니다.",
        "business_implication": "인프라 도입 일정을 재점검할 시점입니다.",
        "category": "ai_infra",
        "source_ids": ["src-1"],
    }
    item.update(overrides)
    return item


def _briefing(items):
    return {"top_5_news": {"news_scope": "global", "items": items}}


class ScaffoldCannotPublishSourceProseTests(unittest.TestCase):
    """The exact 2026-08-28 mechanism."""

    def test_evidence_pack_grafted_wholesale_publishes_no_reader_prose(self) -> None:
        scaffolded = _briefing(copy.deepcopy(EVIDENCE))
        out, diag = enforce_reader_surface(
            scaffolded, program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        for item in out["top_5_news"]["items"]:
            for field in ("headline", "summary", "why_it_matters"):
                self.assertEqual(item[field], UNAVAILABLE_MARKER, field)
            self.assertFalse(item["reader_surface_ready"])
        self.assertEqual(diag["reader_surface_ready_item_count"], 0)
        self.assertIn(
            f"{READER_PROSE_WAS_SOURCE_TEXT}:summary", diag["reader_surface_issue_codes"]
        )

    def test_no_english_source_sentence_survives_into_a_reader_field(self) -> None:
        out, _diag = enforce_reader_surface(
            _briefing(copy.deepcopy(EVIDENCE)),
            program_id=PROGRAM,
            prompt_input=PROMPT_INPUT,
        )
        rendered = " ".join(
            str(item.get(field) or "")
            for item in out["top_5_news"]["items"]
            for field in PROSE_FIELDS
        )
        for evidence in EVIDENCE:
            self.assertNotIn(evidence["summary"], rendered)
            self.assertNotIn(evidence["headline"], rendered)

    def test_a_truncated_prefix_graft_is_the_same_failure(self) -> None:
        # `statement[:120]` was the other grafting shape in the same helper.
        item = _authored("claim-1", headline=EVIDENCE[0]["summary"][:120])
        out, _diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        self.assertEqual(out["top_5_news"]["items"][0]["headline"], UNAVAILABLE_MARKER)


class AuthoredProseSurvivesTests(unittest.TestCase):
    """The boundary must not damage a briefing the model actually wrote."""

    def test_korean_authored_card_passes_through_unchanged(self) -> None:
        item = _authored("claim-1")
        out, diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        result = out["top_5_news"]["items"][0]
        self.assertEqual(result["headline"], item["headline"])
        self.assertEqual(result["summary"], item["summary"])
        self.assertEqual(result["why_it_matters"], item["why_it_matters"])
        self.assertTrue(result["reader_surface_ready"])
        self.assertEqual(diag["reader_surface_ready_item_count"], 1)

    def test_korean_prose_quoting_an_english_product_name_is_kept(self) -> None:
        item = _authored(
            "claim-1",
            summary="엔비디아가 Vera CPU 양산을 시작했다고 밝혔습니다.",
        )
        out, _diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        self.assertEqual(out["top_5_news"]["items"][0]["summary"], item["summary"])


class IdentityIsImmutableTests(unittest.TestCase):
    """Card A can never wear card B's identity or evidence."""

    def test_prose_is_matched_by_news_id_not_by_position(self) -> None:
        # Card in slot 1 claims claim-2's identity; it must receive claim-2's
        # evidence, never slot 1's.
        item = _authored("claim-2", rank=1)
        out, _diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        result = out["top_5_news"]["items"][0]
        self.assertEqual(result["news_id"], "claim-2")
        self.assertEqual(result["source_url"], EVIDENCE[1]["source_url"])
        self.assertEqual(result["source_name"], EVIDENCE[1]["source_name"])

    def test_a_model_supplied_source_cannot_override_the_evidence(self) -> None:
        item = _authored(
            "claim-1",
            source_url="https://techcrunch.com/somewhere-else/",
            source_name="TechCrunch",
        )
        out, _diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        result = out["top_5_news"]["items"][0]
        self.assertEqual(result["source_url"], EVIDENCE[0]["source_url"])
        self.assertEqual(result["source_name"], EVIDENCE[0]["source_name"])

    def test_an_unmatched_identity_loses_prose_rather_than_borrowing_evidence(self) -> None:
        item = _authored("claim-does-not-exist")
        out, diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        self.assertTrue(
            any(
                code.startswith(READER_IDENTITY_UNMATCHED)
                for code in diag["reader_surface_issue_codes"]
            )
        )
        self.assertEqual(out["top_5_news"]["items"][0]["source_url"], "")


class UpstreamStageInjectionTests(unittest.TestCase):
    """English injected at each stage that can produce a briefing."""

    def _assert_withheld(self, briefing, label):
        out, _diag = enforce_reader_surface(
            briefing, program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        item = out["top_5_news"]["items"][0]
        self.assertEqual(item["summary"], UNAVAILABLE_MARKER, label)

    def test_parse_failure_shell_carrying_source_text(self) -> None:
        self._assert_withheld(
            _briefing([_authored("claim-1", summary=EVIDENCE[0]["summary"])]),
            "parse_failure",
        )

    def test_corrective_generation_failure_leaves_source_text(self) -> None:
        self._assert_withheld(
            _briefing([_authored("claim-1", summary=EVIDENCE[0]["summary"])]),
            "corrective_generation_failure",
        )

    def test_reissue_base_carrying_source_text(self) -> None:
        self._assert_withheld(
            _briefing([_authored("claim-1", summary=EVIDENCE[0]["summary"])]),
            "reissue",
        )

    def test_free_english_prose_that_matches_no_evidence_is_still_refused(self) -> None:
        # Not a copy of any evidence string — the field is simply not Korean.
        item = _authored(
            "claim-1",
            summary="The company said the rollout would continue through the next quarter.",
        )
        out, _diag = enforce_reader_surface(
            _briefing([item]), program_id=PROGRAM, prompt_input=PROMPT_INPUT
        )
        self.assertEqual(out["top_5_news"]["items"][0]["summary"], UNAVAILABLE_MARKER)


class BoundaryIsTheOnlyPathTests(unittest.TestCase):
    """Every producer path goes through enrich_generated_briefing_content."""

    def test_the_enricher_applies_the_boundary(self) -> None:
        out = enrich_generated_briefing_content(
            _briefing(copy.deepcopy(EVIDENCE)), PROGRAM, PROMPT_INPUT
        )
        diag = out.get(_READER_SURFACE_DIAGNOSTIC_KEY)
        self.assertIsNotNone(diag)
        self.assertTrue(diag["reader_surface_enforced"])
        for item in out["top_5_news"]["items"]:
            self.assertEqual(item["summary"], UNAVAILABLE_MARKER)

    def test_the_enricher_preserves_authored_korean_prose(self) -> None:
        item = _authored("claim-1")
        out = enrich_generated_briefing_content(_briefing([item]), PROGRAM, PROMPT_INPUT)
        result = out["top_5_news"]["items"][0]
        self.assertNotEqual(result["summary"], UNAVAILABLE_MARKER)
        self.assertTrue(result["reader_surface_ready"])


class ReaderArticleTypeTests(unittest.TestCase):
    """The typed object keeps identity and prose in separate slots."""

    def test_article_binds_identity_from_evidence_and_prose_from_authored(self) -> None:
        article = build_reader_article(_authored("claim-1"), EVIDENCE[0])
        self.assertIsInstance(article, ReaderArticle)
        self.assertEqual(article.news_id, "claim-1")
        self.assertEqual(article.canonical_url, EVIDENCE[0]["source_url"])
        self.assertEqual(article.canonical_headline, EVIDENCE[0]["headline"])
        self.assertNotEqual(article.display_headline, EVIDENCE[0]["headline"])
        self.assertTrue(article.reader_ready)

    def test_an_article_with_no_authored_prose_is_not_reader_ready(self) -> None:
        article = build_reader_article({"news_id": "claim-1"}, EVIDENCE[0])
        self.assertFalse(article.reader_ready)
        self.assertEqual(article.what_happened, UNAVAILABLE_MARKER)
        # Identity survives even when no prose could be produced.
        self.assertEqual(article.canonical_url, EVIDENCE[0]["source_url"])


if __name__ == "__main__":
    unittest.main()
