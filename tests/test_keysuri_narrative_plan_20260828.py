"""Article-specific editorial intent, and the contract that measures it.

The 2026-08-28 17:29 Global run (ea86ff11) produced five grounded,
identity-correct, English-free cards that were rhetorically identical. Tracing
it, article-specific intent collapses in three places, earliest first:

1. evidence construction fills why_it_matters / business_implication with
   source and category templates when the claim carries none;
2. the Global contract repair reused the MAX_TOKENS *compact* prompt, which
   "drops long prose instructions" and truncates each article's summary to 160
   characters — leaving a schema and a title, which cannot differentiate five
   analyses;
3. the enricher then pads thin output from one template per field.

These tests pin the fix for (1) and (2): a bounded per-article plan derived from
that article's own evidence, and a deterministic contract that measures whether
a card says anything only its own article could support.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_article_specificity import (  # noqa: E402
    ARTICLE_SPECIFICITY_ISSUE,
    evaluate_article_specificity,
    field_is_article_specific,
    headline_swap_is_survivable,
)
from keysuri_narrative_plan import (  # noqa: E402
    build_article_narrative_plan,
    build_deep_dive_synthesis_plan,
    build_narrative_plans,
    deep_dive_repeats_top5,
)

# The five articles ea86ff11 actually selected, with their real source text.
EVIDENCE = [
    {
        "rank": 1,
        "news_id": "claim-live-techcrunch-ai-d0b5a5cfad",
        "headline": "Barret Zoph, the Thinking Machines co-founder ousted before joining OpenAI, is now at Google",
        "summary": (
            "Zoph, who co-founded Thinking Machines Lab alongside Mira Murati and also "
            "served as the startup's CTO, led a brief stint at OpenAI."
        ),
        "category": "ai_software_platform",
        "entity_keys": ["google", "openai"],
        "source_name": "TechCrunch AI",
        "source_ids": ["live-techcrunch-ai-d0b5a5cfad"],
    },
    {
        "rank": 2,
        "news_id": "claim-live-nvidia-blog-ca1c781736",
        "headline": "GeForce NOW Gives Gamers More Ways to Play at Gamescom 2026",
        "summary": (
            "NVIDIA's Gamescom announcements are revealing what's next for GeForce NOW, "
            "with new ways to play across more platforms in 2026."
        ),
        "category": "semiconductor_ai_infra",
        "entity_keys": ["nvidia"],
        "source_name": "NVIDIA Blog",
        "source_ids": ["live-nvidia-blog-ca1c781736"],
    },
    {
        "rank": 3,
        "news_id": "claim-live-techcrunch-startups-c81f5906d6",
        "headline": "Rivian's CFO is leaving the company",
        "summary": (
            "Claire McDonough is stepping down on October 30 to pursue a new opportunity, "
            "the company said Thursday."
        ),
        "category": "policy_capital_supplychain",
        "entity_keys": ["rivian"],
        "source_name": "TechCrunch",
        "source_ids": ["live-techcrunch-startups-c81f5906d6"],
    },
    {
        "rank": 4,
        "news_id": "claim-live-arstechnica-tech-lab-e94f9b29d3",
        "headline": "Claude, Codex and Hermes installed unowned code inside corporate networks",
        "summary": "227 install commands were found in corporate docs pointing at code nobody owns.",
        "category": "ai_software_platform",
        "entity_keys": ["anthropic", "openai"],
        "source_name": "Ars Technica Technology Lab",
        "source_ids": ["live-arstechnica-tech-lab-e94f9b29d3"],
    },
    {
        "rank": 5,
        "news_id": "claim-live-datacenter-dynamics-29657b5499",
        "headline": "Schwarz Group commits 5.6bn investment in data center in Mecklenburg-Vorpommern, Germany",
        "summary": "Data center will be fully powered by renewable energy.",
        "category": "security_cloud_datacenter",
        "entity_keys": ["schwarz group"],
        "source_name": "Datacenter Dynamics",
        "source_ids": ["live-datacenter-dynamics-29657b5499"],
    },
]


class NarrativePlanTests(unittest.TestCase):
    def test_every_article_gets_a_distinct_editorial_angle(self) -> None:
        plans = build_narrative_plans(EVIDENCE)
        self.assertEqual(len(plans), 5)
        self.assertEqual(len({p.editorial_angle for p in plans}), 5)

    def test_shared_category_does_not_share_an_angle(self) -> None:
        # Ranks 1 and 4 are both ai_software_platform; a personnel move and a
        # security disclosure are not one editorial intent.
        plans = {p.article_identity: p for p in build_narrative_plans(EVIDENCE)}
        first = plans[EVIDENCE[0]["news_id"]].editorial_angle
        fourth = plans[EVIDENCE[3]["news_id"]].editorial_angle
        self.assertNotEqual(first, fourth)
        self.assertTrue(first.startswith("personnel_move"), first)
        self.assertTrue(fourth.startswith("security_disclosure"), fourth)

    def test_plan_is_derived_from_this_articles_own_evidence(self) -> None:
        plans = {p.article_identity: p for p in build_narrative_plans(EVIDENCE)}
        rivian = plans[EVIDENCE[2]["news_id"]]
        self.assertIn("mcdonough", " ".join(rivian.discriminating_terms))
        self.assertIn("October 30", str(rivian.followup_basis))

    def test_a_field_without_evidence_is_unavailable_not_templated(self) -> None:
        bare = {
            "rank": 1,
            "news_id": "bare-1",
            "headline": "Something happened",
            "summary": "",
            "category": "ai_software_platform",
        }
        plan = build_article_narrative_plan(bare, [bare])
        self.assertIn("secondary_fact", plan.unavailable_fields)
        payload = plan.as_prompt_dict()
        self.assertEqual(payload["secondary_fact"], "UNAVAILABLE")
        # No category label leaked in as a stand-in for missing evidence.
        self.assertNotIn("ai_software_platform", str(payload))

    def test_discriminating_terms_exclude_the_other_articles(self) -> None:
        plans = build_narrative_plans(EVIDENCE)
        for plan in plans:
            others = [p for p in plans if p.article_identity != plan.article_identity]
            for term in plan.discriminating_terms:
                for other in others:
                    self.assertNotIn(term, other.discriminating_terms)


class ArticleSpecificityContractTests(unittest.TestCase):
    def _plan_for(self, index):
        return {p.article_identity: p for p in build_narrative_plans(EVIDENCE)}[
            EVIDENCE[index]["news_id"]
        ]

    def test_generic_prose_fails_the_contract(self) -> None:
        plan = self._plan_for(0)
        generic = "이 분야의 공개 발표로, 사업 영향은 후속 공식 발표에서 확인이 필요합니다."
        self.assertFalse(
            field_is_article_specific(generic, plan, own_title=EVIDENCE[0]["headline"])
        )

    def test_article_grounded_prose_passes(self) -> None:
        plan = self._plan_for(2)
        grounded = "클레어 맥도너(McDonough)가 10월 30일 사임합니다."
        self.assertTrue(
            field_is_article_specific(grounded, plan, own_title=EVIDENCE[2]["headline"])
        )

    def test_repeating_the_headline_is_not_specificity(self) -> None:
        # A template that interpolates the card's own title would otherwise look
        # specific on every card.
        plan = self._plan_for(0)
        echo = f"「{EVIDENCE[0]['headline']}」 관련 변화가 보고되었습니다."
        self.assertFalse(
            field_is_article_specific(echo, plan, own_title=EVIDENCE[0]["headline"])
        )

    def test_the_shipped_ea86ff11_cards_are_flagged(self) -> None:
        shipped = [
            {
                **EVIDENCE[i],
                "what_happened": "해당 사안이 공개 보도로 확인되었습니다.",
                "why_now": "후속 공식 발표에서 보완될 수 있습니다.",
                "owner_angle": "실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다.",
                "next_watch": "후속 일정과 공식 발표부터 보면 됩니다.",
            }
            for i in range(5)
        ]
        result = evaluate_article_specificity(shipped)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["generic_cards"]), 5)
        self.assertTrue(
            all(f["issue_code"] == ARTICLE_SPECIFICITY_ISSUE for f in result["findings"])
        )

    def test_a_card_anchored_in_one_field_passes(self) -> None:
        """Korean prose over an English source anchors where it can.

        "조프가 구글로 합류했습니다" is correct Korean that shares no token with
        "Barret Zoph … Google", so the contract asks the card to anchor
        somewhere — here via the company name the prose retains.
        """
        grounded = [
            {**EVIDENCE[0],
             "what_happened": "조프가 구글로 합류했습니다.",
             "why_now": "Thinking Machines 공동 창업자 출신이라는 점이 배경입니다.",
             "owner_angle": "AI 인재 이동이 이어집니다.",
             "next_watch": "후속 인사를 봅니다."},
            {**EVIDENCE[2],
             "what_happened": "맥도너가 10월 30일 사임합니다.",
             "why_now": "재무 리더십 공백이 생깁니다.",
             "owner_angle": "후임 인선이 관건입니다.",
             "next_watch": "공시를 봅니다."},
        ]
        result = evaluate_article_specificity(grounded)
        self.assertTrue(result["ok"], result["generic_cards"])
        self.assertEqual(result["generic_cards"], [])

    def test_a_card_anchored_nowhere_is_generic(self) -> None:
        unanchored = [
            {**EVIDENCE[0],
             "what_happened": "해당 분야의 공개 발표가 있었습니다.",
             "why_now": "지금 확인이 필요합니다.",
             "owner_angle": "판단 기준이 됩니다.",
             "next_watch": "후속 발표를 봅니다."},
        ]
        result = evaluate_article_specificity(unanchored)
        self.assertFalse(result["ok"])
        self.assertEqual(result["generic_cards"], [EVIDENCE[0]["news_id"]])

    def test_headline_swap_detects_a_too_generic_card(self) -> None:
        generic = {
            **EVIDENCE[0],
            "what_happened": "해당 사안이 공개 보도로 확인되었습니다.",
            "why_now": "후속 공식 발표에서 보완될 수 있습니다.",
        }
        self.assertTrue(headline_swap_is_survivable(generic, EVIDENCE[3]))

    def test_headline_swap_rejects_a_grounded_card(self) -> None:
        grounded = {
            **EVIDENCE[2],
            "what_happened": "맥도너가 10월 30일 사임한다고 밝혔습니다.",
        }
        # "30" comes from this article's evidence and no sibling's, so swapping
        # in another headline would make the card factually wrong.
        self.assertFalse(headline_swap_is_survivable(grounded, EVIDENCE[3]))


class DeepDiveSynthesisTests(unittest.TestCase):
    def test_synthesis_plan_names_pattern_and_tension(self) -> None:
        plan = build_deep_dive_synthesis_plan(build_narrative_plans(EVIDENCE))
        payload = plan.as_prompt_dict()
        self.assertNotEqual(payload["common_pattern"], "UNAVAILABLE")
        self.assertNotEqual(payload["tensions"], "UNAVAILABLE")

    def test_synthesis_is_built_from_facts_not_reader_prose(self) -> None:
        with_prose = [
            {**e, "what_happened": "읽을 수 있는 카드 문장입니다."} for e in EVIDENCE
        ]
        a = build_deep_dive_synthesis_plan(build_narrative_plans(EVIDENCE)).as_prompt_dict()
        b = build_deep_dive_synthesis_plan(build_narrative_plans(with_prose)).as_prompt_dict()
        self.assertEqual(a, b)

    def test_a_deep_dive_that_restates_a_card_is_detected(self) -> None:
        card = "맥도너가 10월 30일 사임한다고 밝혔습니다."
        items = [{**EVIDENCE[2], "what_happened": card}]
        self.assertEqual(deep_dive_repeats_top5(f"오늘의 흐름입니다. {card}", items), [card])

    def test_a_synthesizing_deep_dive_is_clean(self) -> None:
        items = [{**EVIDENCE[2], "what_happened": "맥도너가 10월 30일 사임한다고 밝혔습니다."}]
        body = "인사 이동과 설비 투자가 같은 주에 겹쳤습니다. 두 축은 자본 배분에서 만납니다."
        self.assertEqual(deep_dive_repeats_top5(body, items), [])


class CorrectivePromptCarriesIntentTests(unittest.TestCase):
    def test_contract_repair_uses_the_full_editorial_prompt(self) -> None:
        from keysuri_generation_prompt import (
            build_keysuri_corrective_generation_prompt,
        )

        prompt_input = {
            "program_id": "keysuri_global_tech",
            "top_5_news": {"news_scope": "global", "items": EVIDENCE},
            "source_pack": {"sources": [], "claims": []},
        }
        prompt = build_keysuri_corrective_generation_prompt(
            prompt_input,
            {"failure_family": "GLOBAL_MALFORMED_CONTRACT", "fixed_source_ids": []},
        )
        self.assertIn("PER-ARTICLE NARRATIVE PLANS", prompt)
        self.assertIn("DEEP DIVE SYNTHESIS PLAN", prompt)
        self.assertIn("must not share a sentence shape", prompt)
        self.assertNotIn("Kee-Suri Compact Generation Prompt", prompt)
        for evidence in EVIDENCE:
            self.assertIn(evidence["news_id"], prompt)


if __name__ == "__main__":
    unittest.main()
