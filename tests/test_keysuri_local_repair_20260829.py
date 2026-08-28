"""A local editorial defect must stay local.

Whole-contract regeneration is correct when nothing usable came back. It is
wrong for one card's weak ``why_now``, because it discards four good cards and
re-rolls all five. These pin the bounded alternative: repair the failed field of
the failed article from that article's own evidence, and prove nothing else
moved.

The applier — not the prompt — is the enforcement point.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_local_repair import (  # noqa: E402
    LOCAL_REPAIR_FAILED,
    LOCAL_REPAIR_REJECTED,
    apply_local_repairs,
    build_local_repair_prompt,
    build_local_repair_requests,
    is_whole_contract_failure,
    parse_local_repair_response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "global_corpus_20260828"


def _corpus(case: str) -> dict:
    return json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


def _briefing(items):
    return {"top_5_news": {"news_scope": "global", "items": copy.deepcopy(items)}}


def _case():
    data = _corpus("20260828_acceptance")
    return data["items"], data["evidence"]


def _finding(items, index, field, code="global_visible_repeated_template_skeleton_blocked"):
    return {
        "news_id": items[index]["news_id"],
        "field": field,
        "issue_code": code,
    }


class RepairRequestTests(unittest.TestCase):
    def test_a_request_carries_only_its_own_article(self) -> None:
        items, evidence = _case()
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 1, "why_now")])
        self.assertEqual(len(reqs), 1)
        req = reqs[0]
        self.assertEqual(req.news_id, items[1]["news_id"])
        payload = req.as_prompt_dict()
        for other in items:
            if other["news_id"] == req.news_id:
                continue
            self.assertNotIn(str(other["news_id"]), json.dumps(payload, ensure_ascii=False))

    def test_an_unrepairable_field_yields_no_request(self) -> None:
        items, evidence = _case()
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 0, "headline")])
        self.assertEqual(reqs, [])

    def test_an_article_without_evidence_yields_no_request(self) -> None:
        items, _evidence = _case()
        reqs = build_local_repair_requests(items, [], [_finding(items, 0, "why_now")])
        self.assertEqual(reqs, [])

    def test_the_batched_prompt_keeps_articles_separate(self) -> None:
        items, evidence = _case()
        reqs = build_local_repair_requests(
            items, evidence, [_finding(items, 1, "why_now"), _finding(items, 3, "next_watch")]
        )
        prompt = build_local_repair_prompt(reqs)
        self.assertIn(items[1]["news_id"], prompt)
        self.assertIn(items[3]["news_id"], prompt)
        self.assertIn("Never use another article's evidence", prompt)
        self.assertIn("must not share a sentence shape", prompt)


class LocalityTests(unittest.TestCase):
    """1, 2, 3 — a repair changes exactly what was authorized."""

    def _apply(self, findings, repairs):
        items, evidence = _case()
        reqs = build_local_repair_requests(items, evidence, findings)
        out, diag = apply_local_repairs(_briefing(items), repairs, reqs)
        return items, out["top_5_news"]["items"], diag

    def test_top2_why_now_failure_changes_only_top2_why_now(self) -> None:
        items, _e = _case()
        target = items[1]["news_id"]
        before, after, diag = self._apply(
            [_finding(items, 1, "why_now")],
            {(target, "why_now"): "지포스 나우 확장은 클라우드 게이밍 점유율 경쟁을 다시 엽니다."},
        )
        self.assertEqual(diag["local_repair_applied"], [{"news_id": target, "field": "why_now"}])
        for index, (was, now) in enumerate(zip(before, after)):
            for key in set(was) | set(now):
                if index == 1 and key == "why_now":
                    self.assertNotEqual(was.get(key), now.get(key))
                else:
                    self.assertEqual(was.get(key), now.get(key), f"card {index} field {key}")

    def test_top4_next_watch_failure_changes_only_top4_next_watch(self) -> None:
        items, _e = _case()
        target = items[3]["news_id"]
        before, after, diag = self._apply(
            [_finding(items, 3, "next_watch")],
            {(target, "next_watch"): "소유자 없는 설치 명령 227건의 후속 감사 결과를 봅니다."},
        )
        self.assertEqual(diag["local_repair_applied"], [{"news_id": target, "field": "next_watch"}])
        for index, (was, now) in enumerate(zip(before, after)):
            for key in set(was) | set(now):
                if index == 3 and key == "next_watch":
                    self.assertNotEqual(was.get(key), now.get(key))
                else:
                    self.assertEqual(was.get(key), now.get(key), f"card {index} field {key}")

    def test_two_defects_in_different_cards_batch_without_collateral(self) -> None:
        items, _e = _case()
        a, b = items[1]["news_id"], items[3]["news_id"]
        before, after, diag = self._apply(
            [_finding(items, 1, "why_now"), _finding(items, 3, "next_watch")],
            {
                (a, "why_now"): "클라우드 게이밍 경쟁이 다시 붙습니다.",
                (b, "next_watch"): "227건 감사 결과를 확인합니다.",
            },
        )
        self.assertEqual(len(diag["local_repair_applied"]), 2)
        changed = {
            (index, key)
            for index, (was, now) in enumerate(zip(before, after))
            for key in set(was) | set(now)
            if was.get(key) != now.get(key)
        }
        self.assertEqual(changed, {(1, "why_now"), (3, "next_watch")})


class IdentityTests(unittest.TestCase):
    """4, 6 — identity and cross-item borrowing."""

    def test_a_repair_cannot_move_identity_or_source(self) -> None:
        items, evidence = _case()
        target = items[0]["news_id"]
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 0, "why_now")])
        # A model that also tries to rewrite identity alongside the field.
        hostile = {
            (target, "why_now"): "정상 문장입니다.",
            (target, "headline"): "다른 제목",
            (target, "source_url"): "https://evil.example/",
            (target, "news_id"): items[1]["news_id"],
        }
        out, diag = apply_local_repairs(_briefing(items), hostile, reqs)
        card = out["top_5_news"]["items"][0]
        self.assertEqual(card["news_id"], items[0]["news_id"])
        self.assertEqual(card.get("headline"), items[0].get("headline"))
        self.assertEqual(card.get("source_url"), items[0].get("source_url"))
        self.assertEqual(card.get("source_name"), items[0].get("source_name"))
        self.assertTrue(diag["local_repair_rejected"])

    def test_a_repair_for_another_card_is_refused(self) -> None:
        items, evidence = _case()
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 0, "why_now")])
        out, diag = apply_local_repairs(
            _briefing(items),
            {(items[2]["news_id"], "why_now"): "다른 카드의 문장"},
            reqs,
        )
        after = out["top_5_news"]["items"]
        self.assertEqual(after[2].get("why_now"), items[2].get("why_now"))
        self.assertIn(LOCAL_REPAIR_REJECTED, diag["local_repair_issue_codes"])

    def test_a_repair_for_an_unauthorized_field_is_refused(self) -> None:
        items, evidence = _case()
        target = items[0]["news_id"]
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 0, "why_now")])
        out, diag = apply_local_repairs(
            _briefing(items), {(target, "what_happened"): "허가되지 않은 필드"}, reqs
        )
        self.assertEqual(
            out["top_5_news"]["items"][0].get("what_happened"),
            items[0].get("what_happened"),
        )
        self.assertTrue(diag["local_repair_rejected"])


class FailClosedTests(unittest.TestCase):
    """5 — a failed local repair does not escalate."""

    def test_an_empty_response_leaves_all_five_cards_untouched(self) -> None:
        items, evidence = _case()
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 1, "why_now")])
        out, diag = apply_local_repairs(_briefing(items), {}, reqs)
        self.assertEqual(out["top_5_news"]["items"], items)
        self.assertEqual(diag["local_repair_applied"], [])
        self.assertIn(LOCAL_REPAIR_FAILED, diag["local_repair_issue_codes"])

    def test_unparseable_response_yields_no_repairs(self) -> None:
        self.assertEqual(parse_local_repair_response("not json"), {})
        self.assertEqual(parse_local_repair_response(None), {})
        self.assertEqual(parse_local_repair_response({"repairs": "nope"}), {})

    def test_a_well_formed_response_parses_by_news_id_and_field(self) -> None:
        raw = json.dumps(
            {"repairs": [{"news_id": "n1", "field": "why_now", "value": "문장"}]}
        )
        self.assertEqual(parse_local_repair_response(raw), {("n1", "why_now"): "문장"})


class StabilityTests(unittest.TestCase):
    """7 — untouched fixtures stay untouched."""

    def test_no_requests_means_no_change_for_global(self) -> None:
        items, _e = _case()
        out, diag = apply_local_repairs(_briefing(items), {}, [])
        self.assertEqual(out["top_5_news"]["items"], items)
        self.assertFalse(diag["local_repair_attempted"])

    def test_no_requests_means_no_change_for_korea(self) -> None:
        data = _corpus("20260826_korea_known_good")
        out, diag = apply_local_repairs(_briefing(data["items"]), {}, [])
        self.assertEqual(out["top_5_news"]["items"], data["items"])
        self.assertFalse(diag["local_repair_attempted"])

    def test_repairing_one_card_leaves_the_known_good_korea_cards_stable(self) -> None:
        data = _corpus("20260826_korea_known_good")
        items, evidence = data["items"], data["evidence"]
        reqs = build_local_repair_requests(items, evidence, [_finding(items, 0, "why_now")])
        out, _diag = apply_local_repairs(
            _briefing(items), {(items[0]["news_id"], "why_now"): "새 문장입니다."}, reqs
        )
        self.assertEqual(out["top_5_news"]["items"][1:], items[1:])


class WholeContractBoundaryTests(unittest.TestCase):
    """8 — structural failure keeps its whole-contract correction."""

    def test_structural_failure_is_recognised(self) -> None:
        self.assertTrue(
            is_whole_contract_failure(["parse_multiple_json_objects_unrecoverable"])
        )
        self.assertTrue(is_whole_contract_failure(["top_5_news_missing"]))
        self.assertTrue(
            is_whole_contract_failure(["global_contract_scaffold_fabricated_top5"])
        )

    def test_an_editorial_defect_is_not_a_whole_contract_failure(self) -> None:
        for code in (
            "global_visible_repeated_template_skeleton_blocked",
            "global_visible_repeated_low_information_label",
            "global_abstract_filler_no_specifics",
        ):
            self.assertFalse(is_whole_contract_failure([code]), code)

    def test_the_2026_08_28_natural_run_was_a_true_structural_failure(self) -> None:
        codes = _corpus("20260828_natural")["review_issue_codes"]
        # Its recovery codes were structural; the acceptance run's were editorial.
        self.assertFalse(is_whole_contract_failure(codes))


if __name__ == "__main__":
    unittest.main()
