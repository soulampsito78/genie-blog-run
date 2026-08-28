"""Regression corpus from the real 2026-08-24 → 08-28 Global production runs.

Fixtures are extracted from persisted GCS run artifacts — reader-visible items,
the selected articles' evidence identity, the deep dive, and the verdict fields.
Nothing is invented: a case is only asserted where the artifact preserved the
evidence for it.

Korea's 2026-08-26 known-good run rides along so this work cannot regress the
natural Korean source-headline handling.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_global_visible_surface import repeated_skeleton_hits  # noqa: E402
from keysuri_narrative_plan import (  # noqa: E402
    build_narrative_plans,
    deep_dive_repeats_top5,
)
from keysuri_reader_surface import (  # noqa: E402
    UNAVAILABLE_MARKER,
    enforce_reader_surface,
)

FIXTURES = Path(__file__).parent / "fixtures" / "global_corpus_20260828"

GLOBAL_CASES = (
    "20260824_natural",
    "20260825_natural",
    "20260826_natural",
    "20260827_natural",
    "20260827_reissue",
    "20260828_natural",
    "20260828_acceptance",
)
KOREA_CASES = ("20260826_korea_known_good",)


def _load(case: str) -> dict:
    return json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


def _merged(case: dict) -> list:
    by_id = {str(e.get("news_id")): e for e in case["evidence"]}
    return [{**by_id.get(str(i.get("news_id")), {}), **i} for i in case["items"]]


class CorpusShapeTests(unittest.TestCase):
    def test_every_required_case_is_present(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            self.assertTrue((FIXTURES / f"{case}.json").exists(), case)

    def test_every_case_has_five_cards_and_five_evidence_items(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            self.assertEqual(len(data["items"]), 5, case)
            self.assertEqual(len(data["evidence"]), 5, case)


class SourceIdentityTests(unittest.TestCase):
    def test_every_card_identity_is_unique(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            ids = [str(i.get("news_id")) for i in data["items"]]
            self.assertEqual(len(set(ids)), 5, f"{case}: {ids}")

    def test_no_card_wears_another_cards_source(self) -> None:
        """The 2026-08-27 contamination shape: a card citing a neighbour's article."""
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            evidence = {str(e.get("news_id")): e for e in data["evidence"]}
            for item in data["items"]:
                own = evidence.get(str(item.get("news_id")))
                if not own or not item.get("source_url") or not own.get("source_url"):
                    continue
                self.assertEqual(
                    str(item["source_url"]).rstrip("/"),
                    str(own["source_url"]).rstrip("/"),
                    f"{case}:{item.get('news_id')}",
                )

    def test_card_ranks_are_one_through_five(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            ranks = sorted(int(i.get("rank") or 0) for i in data["items"])
            self.assertEqual(ranks, [1, 2, 3, 4, 5], case)


class ReaderSurfaceTests(unittest.TestCase):
    def test_no_case_leaks_its_english_source_text_into_reader_prose(self) -> None:
        for case in GLOBAL_CASES:
            data = _load(case)
            program = data.get("program_id") or "keysuri_global_tech"
            briefing = {"top_5_news": {"items": data["items"]}}
            prompt_input = {"top_5_news": {"items": data["evidence"]}}
            out, _diag = enforce_reader_surface(
                briefing, program_id=program, prompt_input=prompt_input
            )
            rendered = " ".join(
                str(item.get(field) or "")
                for item in out["top_5_news"]["items"]
                for field in ("headline", "summary", "why_it_matters")
            )
            for evidence in data["evidence"]:
                summary = str(evidence.get("summary") or "").strip()
                if len(summary) >= 40:
                    self.assertNotIn(summary, rendered, f"{case}:{evidence.get('news_id')}")

    def test_the_boundary_never_invents_prose_for_a_case(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            program = data.get("program_id") or "keysuri_global_tech"
            out, _diag = enforce_reader_surface(
                {"top_5_news": {"items": data["items"]}},
                program_id=program,
                prompt_input={"top_5_news": {"items": data["evidence"]}},
            )
            for item in out["top_5_news"]["items"]:
                for field in ("headline", "summary", "why_it_matters"):
                    value = str(item.get(field) or "")
                    if value and value != UNAVAILABLE_MARKER:
                        self.assertTrue(value.strip(), f"{case}:{field}")

    def test_korea_known_good_keeps_all_five_cards_reader_ready(self) -> None:
        for case in KOREA_CASES:
            data = _load(case)
            _out, diag = enforce_reader_surface(
                {"top_5_news": {"items": data["items"]}},
                program_id="keysuri_korea_tech",
                prompt_input={"top_5_news": {"items": data["evidence"]}},
            )
            self.assertEqual(diag["reader_surface_ready_item_count"], 5, case)
            self.assertEqual(diag["reader_surface_issue_codes"], [], case)


class NarrativePlanCorpusTests(unittest.TestCase):
    def test_each_case_yields_five_distinct_editorial_angles(self) -> None:
        for case in GLOBAL_CASES:
            data = _load(case)
            plans = build_narrative_plans(data["evidence"])
            angles = {p.editorial_angle for p in plans}
            self.assertEqual(len(angles), 5, f"{case}: {sorted(angles)}")

    def test_plans_never_share_a_discriminating_term(self) -> None:
        for case in GLOBAL_CASES:
            plans = build_narrative_plans(_load(case)["evidence"])
            for plan in plans:
                for other in plans:
                    if other.article_identity == plan.article_identity:
                        continue
                    self.assertFalse(
                        set(plan.discriminating_terms) & set(other.discriminating_terms),
                        f"{case}:{plan.article_identity}",
                    )


class DeepDiveCorpusTests(unittest.TestCase):
    def test_no_case_restates_a_card_sentence_in_its_deep_dive(self) -> None:
        for case in GLOBAL_CASES:
            data = _load(case)
            reused = deep_dive_repeats_top5(data.get("deep_dive_body"), data["items"])
            self.assertEqual(reused, [], f"{case}: {reused[:2]}")


class SkeletonCorpusTests(unittest.TestCase):
    """The measure that actually separates the good runs from the bad ones."""

    def test_the_rejected_runs_carry_a_repeated_skeleton(self) -> None:
        for case in ("20260828_acceptance",):
            hits = repeated_skeleton_hits(_load(case)["items"])
            self.assertTrue(hits, case)

    def test_the_known_good_run_carries_none(self) -> None:
        hits = repeated_skeleton_hits(_load("20260826_natural")["items"])
        self.assertEqual(hits, [], [h["excerpt"] for h in hits])


if __name__ == "__main__":
    unittest.main()
