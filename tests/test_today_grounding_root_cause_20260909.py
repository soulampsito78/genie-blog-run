"""2026-09-09: Today grounding rejected its own correctly-anchored briefing.

Natural run ``20260909_063102_today_genie_bc5aae92`` briefed exactly the three
articles it selected, in order, as faithful Korean translations:

    U.S. downplays Iran's seizure of unmanned sub in Hormuz Strait
        -> 미국, 호르무즈 해협 이란 무인잠수정 나포 축소 해석
    Bombardier points out U.S. footprint after Trump says ... build in America
        -> 트럼프 '미국 생산' 발언에 봄바디어 美 사업 강조
    Trump administration expresses 'profound concern' over Ford's ties to China
        -> 트럼프 행정부, 포드-中 관계에 '깊은 우려' 표명

The card-level authority ``_validate_top_three_news_briefing`` agreed: all three
cards were bound to their articles by canonical news_id, no issues. The
body-level check disagreed and raised ``unanchored_briefing_vs_input_news``,
because it scored English headline tokens against Korean prose — and the
pipeline's own prompt forbids copying English titles and requires translation.
Of every token across three headlines, exactly one ("ford") survived.

So the first wrong layer was neither the model nor assembly: it was one
consumer left reading the older evidence field after 2026-09-07 made canonical
news_id the primary article binding. These tests pin the corrected evidence and,
more importantly, pin that the check still fires on genuinely untethered copy.

They also pin the second defect the incident exposed: Today body_only
re-collected and re-selected news, so the remediation child briefed three
different stories from a different day than the parent it was correcting.
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List

from today_genie_top3_assembly import canonical_news_id, ensure_canonical_news_identity
from validators import (
    _body_underuses_news_when_feeds_full,
    _validate_top_three_news_briefing,
)

# The exact articles the 06:30 natural run selected, in its order.
INCIDENT_HEADLINES = [
    "U.S. downplays Iran's seizure of unmanned sub in Hormuz Strait",
    "Bombardier points out U.S. footprint after Trump says aerospace giant must build in America",
    "Trump administration expresses 'profound concern' over Ford's ties to China",
]

# The Korean reader copy it actually produced, condensed but faithful.
INCIDENT_CARDS = [
    (
        "미국, 호르무즈 해협 이란 무인잠수정 나포 축소 해석",
        "이란이 호르무즈 해협에서 미국의 무인 해군 함정을 나포했으나, 미국은 이를 즉시 해제된 "
        "사건으로 축소 해석했습니다. 오늘 장전에서는 중동 지역의 지정학적 긴장감이 고조될 수 "
        "있으며, 국내에서는 원/달러 환율 상승 압력과 외국인 투자자 동향을 우선 확인해야 합니다.",
    ),
    (
        "트럼프 '미국 생산' 발언에 봄바디어 美 사업 강조",
        "트럼프 전 대통령이 항공우주 기업은 미국 내에서 생산해야 한다고 주장하자, 봄바디어는 "
        "이미 미국 내 상당한 사업 기반을 가지고 있음을 강조했습니다. 오늘 장전에서는 보호무역 "
        "기조가 재부각되며, 국내에서는 코스피 대형 수출주와 외국인 매매 동향을 관찰해야 합니다.",
    ),
    (
        "트럼프 행정부, 포드-中 관계에 '깊은 우려' 표명",
        "트럼프 행정부가 포드 자동차의 중국과의 관계에 대해 '깊은 우려'를 표명했습니다. 오늘 "
        "장전에서는 미중 갈등 심화 우려가 재점화되며, 국내에서는 반도체·2차전지 등 대중국 "
        "의존도가 높은 코스피·코스닥 종목을 우선 확인해야 합니다.",
    ),
]

INCIDENT_BODY_TEXT = " ".join(f"{h} {d}" for h, d in INCIDENT_CARDS)

# Prose that mentions no input article at all — the case the check exists for.
UNTETHERED_BODY_TEXT = (
    "오늘 장전에는 전반적인 시장 흐름을 차분히 지켜보는 것이 좋겠습니다. "
    "외국인 수급과 환율 흐름을 확인하며 신중하게 접근하시기 바랍니다. "
    "변동성이 확대될 수 있으므로 무리한 추격 매수는 피하는 편이 좋습니다."
)


def _runtime_input(headlines: List[str]) -> Dict[str, Any]:
    return ensure_canonical_news_identity(
        {
            "input_feed_status": "full",
            "top_market_news": [
                {"headline": h, "source": "CNBC", "date": "2026-09-08"} for h in headlines
            ],
        }
    )


def _bound_data(runtime_input: Dict[str, Any], cards=INCIDENT_CARDS) -> Dict[str, Any]:
    news = runtime_input["top_market_news"]
    return {
        "key_watchpoints": [
            {"headline": h, "detail": d, "news_id": canonical_news_id(news[i])}
            for i, (h, d) in enumerate(cards)
        ]
    }


def _unbound_data(cards=INCIDENT_CARDS) -> Dict[str, Any]:
    return {"key_watchpoints": [{"headline": h, "detail": d} for h, d in cards]}


class IncidentReplayTests(unittest.TestCase):
    """The exact 2026-09-09 run must stop being rejected."""

    def setUp(self) -> None:
        self.runtime_input = _runtime_input(INCIDENT_HEADLINES)

    def test_card_level_authority_always_accepted_this_briefing(self) -> None:
        issues = _validate_top_three_news_briefing(
            self.runtime_input, _bound_data(self.runtime_input)
        )
        self.assertNotIn(
            "top3_not_grounded_in_input_news", {i.code for i in issues}
        )

    def test_body_level_check_no_longer_contradicts_it(self) -> None:
        self.assertFalse(
            _body_underuses_news_when_feeds_full(
                self.runtime_input, INCIDENT_BODY_TEXT, _bound_data(self.runtime_input)
            )
        )

    def test_english_tokens_really_are_absent_from_the_korean_copy(self) -> None:
        """The premise: translation is mandated, so token overlap cannot work."""
        from validators import _significant_tokens

        blob = INCIDENT_BODY_TEXT.lower()
        surviving = {
            t
            for h in INCIDENT_HEADLINES
            for t in _significant_tokens(h)[:8]
            if t in blob
        }
        self.assertLessEqual(len(surviving), 1, surviving)


class NotWeakenedTests(unittest.TestCase):
    """Accepting identity must not stop the check catching real defects."""

    def setUp(self) -> None:
        self.runtime_input = _runtime_input(INCIDENT_HEADLINES)

    def test_unbound_cards_with_untranslated_copy_still_fire(self) -> None:
        self.assertTrue(
            _body_underuses_news_when_feeds_full(
                self.runtime_input, INCIDENT_BODY_TEXT, _unbound_data()
            )
        )

    def test_generic_filler_fires_even_when_cards_claim_no_article(self) -> None:
        self.assertTrue(
            _body_underuses_news_when_feeds_full(
                self.runtime_input, UNTETHERED_BODY_TEXT, {"key_watchpoints": []}
            )
        )

    def test_data_absent_keeps_the_original_textual_behaviour(self) -> None:
        self.assertTrue(
            _body_underuses_news_when_feeds_full(self.runtime_input, UNTETHERED_BODY_TEXT)
        )

    def test_cards_bound_to_other_articles_do_not_count(self) -> None:
        """A card must claim *this* article, not merely carry some id."""
        other = _runtime_input(["Completely unrelated market story about copper"])
        foreign_id = canonical_news_id(other["top_market_news"][0])
        data = {
            "key_watchpoints": [
                {"headline": h, "detail": d, "news_id": foreign_id}
                for h, d in INCIDENT_CARDS
            ]
        }
        self.assertTrue(
            _body_underuses_news_when_feeds_full(
                self.runtime_input, UNTETHERED_BODY_TEXT, data
            )
        )

    def test_one_bound_card_is_not_enough(self) -> None:
        news = self.runtime_input["top_market_news"]
        data = {
            "key_watchpoints": [
                {
                    "headline": INCIDENT_CARDS[0][0],
                    "detail": INCIDENT_CARDS[0][1],
                    "news_id": canonical_news_id(news[0]),
                }
            ]
        }
        # Headline 0 binds; headline 1 has no anchor at all in this filler text.
        self.assertTrue(
            _body_underuses_news_when_feeds_full(
                self.runtime_input, UNTETHERED_BODY_TEXT, data
            )
        )


class FrozenParentBodyOnlyTests(unittest.TestCase):
    """§4: body_only repairs prose, it does not re-pick the news."""

    def _parent(self, **overrides: Any) -> Dict[str, Any]:
        meta = {
            "run_id": "20260909_063102_today_genie_bc5aae92",
            "mode": "today_genie",
            "selected_count": 3,
            "required_count": 3,
            "selected_items": [
                {"headline": h, "source": "CNBC", "date": "2026-09-08"}
                for h in INCIDENT_HEADLINES
            ],
        }
        meta.update(overrides)
        return meta

    def test_parent_selection_is_replayed_in_order(self) -> None:
        from today_genie_reissue import frozen_parent_news_selection

        frozen = frozen_parent_news_selection(self._parent())
        self.assertEqual([i["headline"] for i in frozen], INCIDENT_HEADLINES)

    def test_replayed_selection_keeps_identical_canonical_ids(self) -> None:
        from today_genie_reissue import frozen_parent_news_selection

        parent = self._parent()
        parent_ids = [canonical_news_id(i) for i in parent["selected_items"]]
        child_ids = [canonical_news_id(i) for i in frozen_parent_news_selection(parent)]
        self.assertEqual(parent_ids, child_ids)
        self.assertTrue(all(child_ids))

    def test_missing_parent_selection_fails_closed(self) -> None:
        from today_genie_reissue import frozen_parent_news_selection

        self.assertIsNone(frozen_parent_news_selection(self._parent(selected_items=[])))
        self.assertIsNone(frozen_parent_news_selection({"mode": "today_genie"}))

    def test_api_replay_skips_reselection_and_preserves_order(self) -> None:
        from main import _apply_frozen_today_news_selection

        frozen = [
            {"headline": h, "source": "CNBC", "date": "2026-09-08"}
            for h in INCIDENT_HEADLINES
        ]
        out = _apply_frozen_today_news_selection(
            {"input_feed_status": "full", "top_market_news": [{"headline": "other"}]},
            frozen,
            parent_run_id="20260909_063102_today_genie_bc5aae92",
        )
        self.assertEqual(
            [i["headline"] for i in out["top_market_news"]], INCIDENT_HEADLINES
        )
        self.assertTrue(out["today_news_selection_frozen"])
        dedup = out["sent_news_dedup"]
        self.assertEqual(dedup["dedup_summary"]["reason"], "frozen_parent_selection")
        self.assertEqual(dedup["selected_count"], 3)
        self.assertEqual(dedup["rejected_items"], [])

    def test_frozen_child_keeps_its_own_selection_evidence(self) -> None:
        """A child with no selected_items could not itself be remediated."""
        from main import _apply_frozen_today_news_selection
        from orchestrator import _dedup_fields_from_api_payload
        from today_genie_reissue import frozen_parent_news_selection

        frozen = [
            {"headline": h, "source": "CNBC", "date": "2026-09-08"}
            for h in INCIDENT_HEADLINES
        ]
        runtime_input = _apply_frozen_today_news_selection({}, frozen)
        fields = _dedup_fields_from_api_payload({"runtime_input": runtime_input})
        self.assertEqual(
            [i["headline"] for i in fields["selected_items"]], INCIDENT_HEADLINES
        )
        self.assertEqual(fields["selected_count"], 3)
        # And that persisted child can seed the next body_only in turn.
        self.assertEqual(
            [i["headline"] for i in frozen_parent_news_selection(fields)],
            INCIDENT_HEADLINES,
        )

    def test_frozen_request_field_reaches_the_api_contract(self) -> None:
        from main import JobRequest, _frozen_today_news_selection

        job = JobRequest(
            type="today_genie",
            frozen_top_market_news=[{"headline": INCIDENT_HEADLINES[0]}],
            frozen_parent_run_id="20260909_063102_today_genie_bc5aae92",
        )
        self.assertEqual(
            _frozen_today_news_selection(job), [{"headline": INCIDENT_HEADLINES[0]}]
        )
        self.assertIsNone(_frozen_today_news_selection(JobRequest(type="today_genie")))

    def test_natural_run_still_uses_the_dedup_gate(self) -> None:
        """Freezing is opt-in; a natural run must keep selecting its own news."""
        from main import _frozen_today_news_selection

        self.assertIsNone(_frozen_today_news_selection(object()))


if __name__ == "__main__":
    unittest.main()
