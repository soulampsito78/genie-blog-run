"""Padding must not put one sentence skeleton on every TOP5 card.

The 2026-08-28 17:29 Global acceptance run recovered from a model-contract
collapse, produced five correctly-grounded Korean cards with zero English
leakage — and still landed in editorial REVIEW, because the enricher pads thin
model output from a fixed template per field. Anchoring each padding sentence on
its own card's title made the five sentences textually distinct but left them
structurally identical, which is exactly what
``global_visible_repeated_template_skeleton_blocked`` measures:

    5 items ranks [1,2,3,4,5]: 「X」가 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다.
    5 items ranks [1,2,3,4,5]: 「X」 세부 수치·일정은 후속 공식 발표에서 보완될 수 있습니다.
    3 items ranks [2,3,4]:     {source} 후속 공식 발표; 원문 업데이트·구체 수치 공개 여부

Rotating the padding by rank was the first answer, and it was the wrong one: it
varied the wording of sentences whose *content* still came from the category, so
the prose stayed interchangeable between articles in the same category. The
padding is gone instead. Explanatory fields now carry the model's prose or
nothing, and a field with nothing in it is withheld at the reader-surface
boundary rather than filled.

Measured across the real 08-24..08-28 corpus, category templates supplied 32% of
why_now and 29% of owner_angle before this change, and 0% after.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_briefing_content_enricher import (  # noqa: E402
    _build_what_happened,
    enrich_generated_briefing_content,
)
from keysuri_global_visible_surface import repeated_skeleton_hits  # noqa: E402

PROGRAM = "keysuri_global_tech"

# The five articles the 2026-08-28 17:29 run actually selected.
EVIDENCE = [
    {
        "rank": 1,
        "news_id": "claim-live-techcrunch-ai-d0b5a5cfad",
        "headline": "OpenAI 핵심 인력 바렛 조프, 구글 합류",
        "source_ids": ["s1"],
        "source_name": "TechCrunch AI",
        "source_url": "https://techcrunch.com/2026/08/27/barret-zoph/",
        "primary_category": "ai_software_platform",
    },
    {
        "rank": 2,
        "news_id": "claim-live-nvidia-blog-ca1c781736",
        "headline": "엔비디아, 게임스컴 2026에서 지포스 나우 확장 발표",
        "source_ids": ["s2"],
        "source_name": "NVIDIA Blog",
        "source_url": "https://blogs.nvidia.com/blog/geforce-now-gamescom-2026/",
        "primary_category": "semiconductor_ai_infra",
    },
    {
        "rank": 3,
        "news_id": "claim-live-techcrunch-startups-c81f5906d6",
        "headline": "리비안 CFO 클레어 맥도너, 10월 사임 예정",
        "source_ids": ["s3"],
        "source_name": "TechCrunch",
        "source_url": "https://techcrunch.com/2026/08/27/rivians-cfo/",
        "primary_category": "policy_capital_supplychain",
    },
    {
        "rank": 4,
        "news_id": "claim-live-arstechnica-tech-lab-e94f9b29d3",
        "headline": "클로드·코덱스 등 AI 모델, 기업 네트워크 내 보안 취약점 노출",
        "source_ids": ["s4"],
        "source_name": "Ars Technica Technology Lab",
        "source_url": "https://arstechnica.com/security/2026/08/claude-codex/",
        "primary_category": "ai_software_platform",
    },
    {
        "rank": 5,
        "news_id": "claim-live-datacenter-dynamics-29657b5499",
        "headline": "슈바르츠 그룹, 독일에 56억 유로 규모 친환경 데이터 센터 투자",
        "source_ids": ["s5"],
        "source_name": "Datacenter Dynamics",
        "source_url": "https://www.datacenterdynamics.com/en/news/schwarz-group/",
        "primary_category": "security_cloud_datacenter",
    },
]

# Deliberately thin, structurally distinct authored prose — the shape that makes
# the enricher pad, without contributing a repeat of its own.
AUTHORED_WHAT = [
    "구글이 해당 인력을 영입했다고 밝혔습니다.",
    "게임스컴 현장에서 신규 서비스 확장이 공개되었습니다.",
    "최고재무책임자가 10월 사임한다고 통보했습니다.",
    "기업 네트워크에서 소유자 없는 코드가 다수 발견됐습니다.",
    "독일 북부에 대규모 데이터센터 건설이 확정됐습니다.",
]
AUTHORED_WHY = [
    "인재 이동은 모델 개발 속도를 바꿉니다.",
    "클라우드 게이밍 점유율 경쟁이 다시 붙습니다.",
    "재무 리더십 공백은 자금 조달 조건에 영향을 줍니다.",
    "코드 검증 절차를 다시 설계해야 합니다.",
    "전력 조달 방식이 데이터센터 원가를 좌우합니다.",
]


def _thin_briefing():
    items = []
    for index, evidence in enumerate(EVIDENCE):
        items.append(
            {
                **{k: evidence[k] for k in ("rank", "news_id", "source_ids", "source_name",
                                            "source_url", "primary_category")},
                "korean_title": evidence["headline"],
                "headline": evidence["headline"],
                "what_happened": AUTHORED_WHAT[index],
                "why_now": AUTHORED_WHY[index],
            }
        )
    return {"top_5_news": {"news_scope": "global", "items": items}}


def _prompt_input():
    return {"top_5_news": {"items": EVIDENCE}, "source_pack": {}}


class PaddingVarietyTests(unittest.TestCase):
    def test_enriched_top5_has_no_repeated_sentence_skeleton(self) -> None:
        out = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        items = out["top_5_news"]["items"]
        self.assertEqual(len(items), 5)
        hits = repeated_skeleton_hits(items)
        self.assertEqual(hits, [], [h["excerpt"] for h in hits])

    def test_no_category_sentence_is_added_to_any_explanatory_field(self) -> None:
        """The category may label a card; it may not explain it.

        Every sentence below was produced by the padding engine and appeared on
        all five cards of a real run. None of them says anything about the
        article it was attached to.
        """
        out = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        blob = " ".join(
            str(item.get(field) or "")
            for item in out["top_5_news"]["items"]
            for field in ("what_happened", "why_now", "owner_angle", "next_watch")
        )
        for fragment in (
            "판단 기준입니다",
            "확인 포인트는",
            "먼저 볼 지표는",
            "추적 대상은",
            "이어지는 신호는",
            "세부 수치·일정은 후속 공식 발표에서 보완될 수 있습니다",
            "공개된 범위 밖의 계약 조건은 아직 확인되지 않았습니다",
            "예산과 일정에 실제로 반영되는지를 보고 판단합니다",
        ):
            self.assertNotIn(fragment, blob, fragment)

    def test_a_field_the_model_did_not_write_stays_empty(self) -> None:
        """Fallback filler must not stand in for missing authored prose."""
        out = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        for item in out["top_5_news"]["items"]:
            # The fixture supplies no owner_angle, and none is manufactured.
            self.assertEqual(str(item.get("owner_angle") or "").strip(), "")

    def test_authored_prose_is_kept(self) -> None:
        for index, evidence in enumerate(EVIDENCE):
            item = {**evidence, "what_happened": AUTHORED_WHAT[index]}
            visible, _thin = _build_what_happened(item, {"source_name": evidence["source_name"]})
            self.assertTrue(visible.startswith(AUTHORED_WHAT[index]), evidence["news_id"])

    def test_enrichment_is_deterministic_for_the_same_card(self) -> None:
        first = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        second = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        self.assertEqual(
            [i["what_happened"] for i in first["top_5_news"]["items"]],
            [i["what_happened"] for i in second["top_5_news"]["items"]],
        )

    def test_no_hard_coded_subject_particle_on_a_latin_source_name(self) -> None:
        """"TechCrunch이" — 이/가 depends on the Korean reading of a Latin name."""
        out = enrich_generated_briefing_content(_thin_briefing(), PROGRAM, _prompt_input())
        blob = " ".join(
            str(item.get(field) or "")
            for item in out["top_5_news"]["items"]
            for field in ("what_happened", "why_now", "selection_reason", "owner_angle")
        )
        for source in ("TechCrunch", "NVIDIA Blog", "Ars Technica", "Datacenter Dynamics"):
            for particle in ("이 ", "가 ", "은 ", "는 "):
                self.assertNotIn(f"{source}{particle}", blob, f"{source}{particle}")


if __name__ == "__main__":
    unittest.main()
