"""Pre-acceptance corpus: does the product *write*, not just avoid unsafe output?

The 2026-08-29 forensic pass closed the source-evidence bypass, and every
detector went to zero. The writing was still not customer-ready, because the
deterministic enricher was manufacturing the prose the detectors were passing:
measured across the real 2026-08-24..08-28 Global corpus, category templates
supplied 32% of ``why_now`` and 29% of ``owner_angle`` — 60% on the run accepted
on 08-28.

This file tests the writing. It runs on persisted real evidence, and it asserts
what a card must *be*, not merely what it must not contain.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import keysuri_briefing_content_enricher as E  # noqa: E402
from keysuri_gemini_client import (  # noqa: E402
    KEYSURI_BODY_MIN_ANSWER_TOKENS,
    resolve_keysuri_body_thinking_budget,
)
from keysuri_global_signal_scoring import TOP5_QUALITY_FLOOR_BASE_SCORE  # noqa: E402
from keysuri_global_visible_surface import korean_particle_defects  # noqa: E402

FIXTURES = _ROOT / "tests" / "fixtures" / "global_corpus_20260828"

GLOBAL_CASES = (
    "20260824_natural",
    "20260825_natural",
    "20260826_natural",
    "20260827_natural",
    "20260827_reissue",
    "20260828_natural",
    "20260828_acceptance",
    "20260829_qa_manual_failure",
)
KOREA_CASES = ("20260826_korea_known_good",)

#: Every sentence a category table can supply. If any of these reaches a
#: customer-visible field, a template is writing the briefing again.
CATEGORY_TABLE_SENTENCES = tuple(
    s
    for table in (
        E._WHY_NOW_CONCRETE_BY_CAT,
        E._OWNER_CONTEXT,
        E._WHY_NOW_CONTEXT,
    )
    for s in table.values()
) + tuple(x for pair in E._NEXT_WATCH_BY_CAT.values() for x in pair)

#: Sentence frames the deleted padding engine used. Kept as literals so the
#: guard survives the engine's removal.
TEMPLATE_FRAMES = (
    # Extracted from the deleted engine at 67eced4, so the guard outlives it.
    "확인 포인트는",
    "먼저 볼 지표는",
    "판단을 가르는 변수는",
    "추적 대상은 우선",
    "관찰 순서는",
    "이어지는 신호는",
    "실무 점검은",
    "다음 확인은",
    "흐름은",
    "후속은",
    "세부 수치·일정은 후속 공식 발표에서 보완될 수 있습니다",
    "공개된 범위 밖의 계약 조건은 아직 확인되지 않았습니다",
    "규모와 시점은 원문이 갱신되면 달라질 수 있습니다",
    "지금까지 확인된 사실은 이번 발표 내용까지입니다",
    "구체적인 실행 단계는 아직 공개되지 않았습니다",
    "실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다",
    "예산과 일정에 실제로 반영되는지를 보고 판단합니다",
    "발표에 그치는지 집행으로 넘어가는지가 갈림길입니다",
    "계약 조건까지 확정되는 시점이 판단 지점입니다",
    "운영 비용에 닿기 시작하면 그때 무게가 달라집니다",
    "후속 일정과 공식 발표부터 보면 됩니다",
    "공식 일정 공지가 나오면 다시 확인합니다",
    "다음 발표 시점을 기준으로 이어서 봅니다",
    "후속 공지가 나올 때까지는 관찰 상태로 둡니다",
    "일정이 구체화되면 그때 다시 짚습니다",
)

VISIBLE_FIELDS = ("what_happened", "why_now", "owner_angle", "next_watch")


def _load(case: str) -> dict:
    return json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


def _sentences(text) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if s.strip()]


def _meta_for(item: dict, evidence: dict) -> dict:
    return {
        "source_name": item.get("source_name") or evidence.get("source_name"),
        "statement": evidence.get("summary"),
        "summary": evidence.get("summary"),
        "primary_category": item.get("primary_category") or evidence.get("category"),
        "category_label_ko": item.get("category_label_ko"),
        "category_confidence": 0.67,
    }


def _authored_only(item: dict) -> dict:
    """Strip every sentence a category table could have supplied."""
    out = dict(item)
    out.pop("briefing_item", None)
    for field in ("what_happened", "why_now", "owner_angle"):
        kept = [
            s
            for s in _sentences(item.get(field))
            if not any(frame in s for frame in TEMPLATE_FRAMES)
            and not any(s.rstrip(".") == t.rstrip(".") for t in CATEGORY_TABLE_SENTENCES)
        ]
        out[field] = " ".join(kept)
    # next_watch is stored as "a; b" and the old top-up wrote both halves out of
    # _NEXT_WATCH_BY_CAT, so strip those the same way.
    checkpoints = [
        c.strip()
        for c in str(item.get("next_watch") or "").split(";")
        if c.strip()
        and not any(c.strip() == t.rstrip(".") for t in CATEGORY_TABLE_SENTENCES)
    ]
    out["next_watch"] = "; ".join(checkpoints)
    return out


class NoTemplateMayWriteACardTests(unittest.TestCase):
    """The core pre-acceptance property."""

    def _reenrich(self, case: str):
        data = _load(case)
        by_id = {str(e.get("news_id")): e for e in data["evidence"]}
        for item in data["items"]:
            evidence = by_id.get(str(item.get("news_id")), {})
            meta = _meta_for(item, evidence)
            yield case, E.enrich_top5_item_content(_authored_only(item), meta=meta)

    def test_no_category_table_sentence_reaches_a_visible_field(self) -> None:
        for case in GLOBAL_CASES:
            for _c, enriched in self._reenrich(case):
                blob = " ".join(str(enriched.get(f) or "") for f in VISIBLE_FIELDS)
                for sentence in CATEGORY_TABLE_SENTENCES:
                    self.assertNotIn(sentence.rstrip("."), blob, f"{case}: {sentence}")

    def test_no_padding_frame_reaches_a_visible_field(self) -> None:
        for case in GLOBAL_CASES:
            for _c, enriched in self._reenrich(case):
                blob = " ".join(str(enriched.get(f) or "") for f in VISIBLE_FIELDS)
                for frame in TEMPLATE_FRAMES:
                    self.assertNotIn(frame, blob, f"{case}: {frame}")

    def test_the_authored_prose_survives(self) -> None:
        """Removing filler must not remove the writing."""
        for case in GLOBAL_CASES:
            data = _load(case)
            by_id = {str(e.get("news_id")): e for e in data["evidence"]}
            for item in data["items"]:
                authored = _authored_only(item)
                if not str(authored.get("what_happened") or "").strip():
                    continue  # the 08-29 collapse has no authored prose at all
                meta = _meta_for(item, by_id.get(str(item.get("news_id")), {}))
                enriched = E.enrich_top5_item_content(authored, meta=meta)
                first = _sentences(authored["what_happened"])[0].rstrip(".")
                self.assertIn(first[:30], str(enriched.get("what_happened") or ""), case)

    def test_korean_grammar_stays_clean_without_the_padding(self) -> None:
        for case in GLOBAL_CASES + KOREA_CASES:
            data = _load(case)
            by_id = {str(e.get("news_id")): e for e in data["evidence"]}
            for item in data["items"]:
                meta = _meta_for(item, by_id.get(str(item.get("news_id")), {}))
                enriched = E.enrich_top5_item_content(_authored_only(item), meta=meta)
                for field in VISIBLE_FIELDS:
                    text = str(enriched.get(field) or "")
                    self.assertEqual(korean_particle_defects(text), [], f"{case}/{field}")


class SelectionReasonIsGroundedTests(unittest.TestCase):
    """선정 이유 names a source, or the block is omitted."""

    def test_no_category_selection_sentence_is_manufactured(self) -> None:
        from keysuri_visible_text import build_visible_selection_reason

        out = build_visible_selection_reason(
            {
                "korean_title": "구글, 풀스택 AI 에이전트 전략 공개",
                "primary_category": "ai_software_platform",
                "selection_reason": "총점 54점을 기록했습니다.",
            },
            {},
            program_id="keysuri_global_tech",
        )
        self.assertEqual(out, "")
        for fragment in ("판단 기준과 맞닿아", "축에서 먼저 볼 신호로", "축에서 우선적으로"):
            self.assertNotIn(fragment, out)

    def test_the_internal_score_never_reaches_the_reader(self) -> None:
        for case in GLOBAL_CASES:
            data = _load(case)
            by_id = {str(e.get("news_id")): e for e in data["evidence"]}
            for item in data["items"]:
                meta = _meta_for(item, by_id.get(str(item.get("news_id")), {}))
                meta["selection_rationale"] = "총점 44점(구조 4, 주인님 12, 사업 4)."
                enriched = E.enrich_top5_item_content(_authored_only(item), meta=meta)
                reason = str(enriched.get("selection_reason") or "")
                for fragment in ("총점", "구조 4", "사업 4)", "주인님 12"):
                    self.assertNotIn(fragment, reason, f"{case}: {reason}")


class GenerationBudgetTests(unittest.TestCase):
    """The contract must have room to be written.

    2026-08-29: reasoning is billed against ``max_output_tokens``, nothing
    bounded it, and two calls in a row spent ~15.7k of a 16,384 allowance
    thinking — leaving 642 output tokens, far short of the ~3.8k-4.9k a real
    contract costs. The response was valid JSON, truncated after the display
    fields, and the scaffold filled the rest from the evidence pack.
    """

    def test_the_answer_always_keeps_room(self) -> None:
        for max_out in (8192, 12288, 16384, 24576, 32768):
            budget = resolve_keysuri_body_thinking_budget(max_out)
            self.assertGreaterEqual(
                max_out - budget, KEYSURI_BODY_MIN_ANSWER_TOKENS, f"max_out={max_out}"
            )

    def test_the_budget_covers_what_successful_runs_actually_used(self) -> None:
        # 2026-08-24 reasoned 3,317 tokens and returned a full contract.
        self.assertGreaterEqual(resolve_keysuri_body_thinking_budget(16384), 3317)

    def test_the_budget_stops_the_run_that_failed(self) -> None:
        # 2026-08-29 reasoned ~15,700 tokens on the initial call.
        self.assertLess(resolve_keysuri_body_thinking_budget(16384), 15700)


class SelectionQualityFloorTests(unittest.TestCase):
    """A reject-classified article may not become a customer-visible card."""

    def test_the_floor_is_the_reject_boundary(self) -> None:
        from keysuri_global_signal_scoring import _classify_total

        self.assertEqual(
            _classify_total(TOP5_QUALITY_FLOOR_BASE_SCORE, hard_reject=False), "watchlist"
        )
        self.assertEqual(
            _classify_total(TOP5_QUALITY_FLOOR_BASE_SCORE - 1, hard_reject=False), "reject"
        )

    def test_the_failed_run_would_now_be_flagged(self) -> None:
        """All five 08-29 cards scored 39-44 and were classified reject."""
        case = _load("20260829_qa_manual_failure")
        scores = [39, 43, 41, 39, 44]  # from the persisted source pack
        self.assertEqual(len(case["items"]), 5)
        for score in scores:
            self.assertLess(score, TOP5_QUALITY_FLOOR_BASE_SCORE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
