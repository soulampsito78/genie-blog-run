"""Tests for Kee-Suri briefing content depth enricher."""
from __future__ import annotations

import unittest

from keysuri_briefing_content_enricher import (
    enrich_deep_dive_content,
    enrich_generated_briefing_content,
    enrich_korea_top5_item_content,
    enrich_top5_item_content,
)
from keysuri_briefing_content_quality import (
    _watch_checkpoint_count,
    validate_briefing_content_gate,
)
from keysuri_contract_preview_quality import _sentence_count
from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

_REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


class KeysuriBriefingContentEnricherTests(unittest.TestCase):
    def _meta(self, **kwargs) -> dict:
        base = {
            "source_name": "OpenAI News",
            "source_url": "https://openai.com/index/endava-frontiers",
            "primary_category": "ai_software_platform",
            "category_label_ko": "AI·소프트웨어·플랫폼",
            "selection_rationale": "고객 사례 신호로 선정.",
            "selection_score": 40,
        }
        base.update(kwargs)
        return base

    def test_thin_item_enriched_to_three_sentences_without_invented_facts(self) -> None:
        item = {
            "korean_title": "테스트 AI 플랫폼 업데이트",
            "what_happened": "공식 요약에 따르면 업데이트가 보고되었습니다.",
            "why_now": "지금은 배포 레이어 경쟁이 겹치는 시점입니다.",
            "owner_angle": "주인님께서는 파트너 조건을 점검하시면 됩니다.",
            "source_ids": ["live-openai-1"],
        }
        meta = self._meta(summary="Short summary.")
        enriched = enrich_top5_item_content(item, meta=meta)
        self.assertGreaterEqual(_sentence_count(enriched["what_happened"]), 3)
        self.assertGreaterEqual(_sentence_count(enriched["why_now"]), 3)
        self.assertGreaterEqual(_sentence_count(enriched["owner_angle"]), 3)
        self.assertNotIn("100%", enriched["what_happened"])
        self.assertNotIn("확정적으로", enriched["what_happened"])

    def test_thin_source_includes_additional_confirmation(self) -> None:
        item = {"korean_title": "짧은 헤드라인", "what_happened": "한 줄.", "source_ids": ["s1"]}
        meta = self._meta(summary="tiny", primary_category="semiconductor_chip_infra")
        enriched = enrich_top5_item_content(item, meta=meta)
        self.assertIn("향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.", enriched["what_happened"])
        self.assertTrue(enriched.get("detail_insufficient"))

    def test_customer_case_includes_hype_caution(self) -> None:
        item = {
            "korean_title": "Endava software delivery case",
            "what_happened": "요약 한 줄입니다.",
            "why_now": "지금 중요합니다.",
            "owner_angle": "주인님 관점입니다.",
            "source_ids": ["s1"],
        }
        meta = self._meta(
            hype_warning=True,
            is_customer_case_study=True,
            selection_classification="watchlist",
        )
        enriched = enrich_top5_item_content(item, meta=meta)
        self.assertIn("과장 주의", enriched.get("hype_caution", ""))
        self.assertTrue(
            "고객 사례" in enriched.get("hype_caution", "")
            or "사례" in enriched.get("hype_caution", "")
        )

    def test_sponsored_includes_sponsored_caution(self) -> None:
        item = {"korean_title": "Sponsored grid item", "source_ids": ["s1"]}
        meta = self._meta(is_sponsored=True, sponsored_warning=True)
        enriched = enrich_top5_item_content(item, meta=meta)
        self.assertIn("스폰서", enriched.get("hype_caution", ""))

    def test_next_watch_gets_two_items(self) -> None:
        item = {"korean_title": "신호", "next_watch": "공식 발표를 확인하세요.", "source_ids": ["s1"]}
        enriched = enrich_top5_item_content(item, meta=self._meta())
        self.assertGreaterEqual(_watch_checkpoint_count(enriched["next_watch"]), 2)

    def test_deep_dive_references_two_signals_without_internal_markers(self) -> None:
        items = [
            {"korean_title": "NVIDIA AI Factory", "primary_category": "semiconductor_chip_infra"},
            {"korean_title": "Notion Anthropic access", "primary_category": "ai_software_platform"},
        ]
        deep = {"body": "짧은 딥다이브 본문입니다."}
        enriched = enrich_deep_dive_content(deep, items)
        prompt_input = {"source_pack": {"claims": [], "sources": []}}
        out = enrich_generated_briefing_content(
            {"top_5_news": {"items": items}, "deep_dive": enriched},
            "keysuri_global_tech",
            prompt_input,
        )
        body = out["deep_dive"]["body"]
        self.assertNotIn("TOP 신호", body)
        self.assertNotIn("점검하는 데 유용합니다", body)
        self.assertIn("주인님", body)
        self.assertGreaterEqual(body.count("\n\n") + 1, 2)
        linked = out["deep_dive"].get("linked_signal_titles") or []
        self.assertGreaterEqual(len(linked), 2)

    def test_deep_dive_uncertainty_uses_official_followup_wording(self) -> None:
        items = [{"korean_title": "Signal A"}, {"korean_title": "Signal B"}]
        enriched = enrich_deep_dive_content({"body": "짧은 딥다이브 본문입니다."}, items)
        body = enriched["body"]
        self.assertNotIn("원문 확인이 필요", body)
        self.assertIn(
            "향후 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다.",
            body,
        )

    def test_enriched_fixture_passes_content_gate(self) -> None:
        fixture = build_global_contract_fixture()
        for idx, item in enumerate(fixture["top_5_items"], start=1):
            # Prompt contract requires why_now to already carry 3+ Korean sentences
            # of item-specific context; give each item distinct, sufficiently deep
            # input so the enricher's thin-source fallback padding (which can repeat
            # a shared category filler sentence across items) is never triggered.
            why_now = (
                f"{item['why_now']} "
                f"항목 {idx}는 반도체 공급망 병목과 직접 연결되는 구체적 사례입니다. "
                f"연산 자원 조달 일정이 지연되면 관련 파트너 비용에도 영향이 있습니다."
            )
            enriched = enrich_top5_item_content(
                {
                    "korean_title": item["korean_title"],
                    "what_happened": item["what_happened"],
                    "why_now": why_now,
                    "owner_angle": item["owner_angle"],
                    "selection_reason": "선정 이유 첫 문장입니다. 두 번째 선정 문장입니다.",
                    "next_watch": "→ 첫 확인; → 둘째 확인",
                    "source_ids": ["live-test-1"],
                },
                meta=self._meta(primary_category="semiconductor_chip_infra"),
            )
            item.update(enriched)
        enriched_briefing = enrich_generated_briefing_content(
            {
                "top_5_news": {
                    "items": [
                        {
                            "korean_title": item["korean_title"],
                            "what_happened": item["what_happened"],
                            "why_now": item["why_now"],
                            "owner_angle": item["owner_angle"],
                            "selection_reason": item.get("selection_reason", ""),
                            "next_watch": item.get("next_watch", ""),
                            "source_ids": ["live-test-1"],
                        }
                        for item in fixture["top_5_items"]
                    ]
                },
                "deep_dive": {"body": fixture["deep_dive_body"]},
            },
            "keysuri_global_tech",
            {"source_pack": {"claims": [], "sources": []}},
        )
        fixture["deep_dive_body"] = enriched_briefing["deep_dive"]["body"]
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {
            "global_top5_selection": {"policy": "v2"},
            "claims": [{"selection_score": 70, "selection_rationale": "test", "primary_category": "semiconductor_chip_infra"}] * 5,
            "sources": [{"source_id": "live-test-1", "source_url": fixture["top_5_items"][0]["source_url"]}],
            "deep_dive_linked_signals": enriched_briefing["deep_dive"].get("linked_signal_titles") or [],
        }
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertTrue(result.ok, [i.message for i in result.issues])

    def test_gate_still_fails_without_metadata_when_impossible(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["what_happened"] = "한 줄."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {
            "global_top5_selection": {"policy": "v2"},
            "claims": [{"selection_score": 70}] * 5,
        }
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertFalse(result.ok)

    def test_full_briefing_enricher_preserves_program_scope(self) -> None:
        prompt_input = {
            "source_pack": {
                "claims": [
                    {
                        "source_ids": ["live-openai-1"],
                        "selection_score": 50,
                        "primary_category": "ai_software_platform",
                        "category_label_ko": "AI·소프트웨어·플랫폼",
                    },
                    {
                        "source_ids": ["live-openai-2"],
                        "selection_score": 48,
                        "primary_category": "semiconductor_chip_infra",
                        "category_label_ko": "반도체·칩·AI 인프라",
                    },
                ],
                "sources": [
                    {
                        "source_id": "live-openai-1",
                        "source_name": "OpenAI News",
                        "source_url": "https://openai.com/index/test/",
                    },
                    {
                        "source_id": "live-openai-2",
                        "source_name": "NVIDIA Blog",
                        "source_url": "https://blogs.nvidia.com/blog/test/",
                    },
                ],
            }
        }
        generated = {
            "top_5_news": {
                "items": [
                    {
                        "rank": 1,
                        "news_id": "n1",
                        "source_ids": ["live-openai-1"],
                        "korean_title": "테스트 A",
                        "what_happened": "짧음.",
                    },
                    {
                        "rank": 2,
                        "news_id": "n2",
                        "source_ids": ["live-openai-2"],
                        "korean_title": "테스트 B",
                        "what_happened": "짧음.",
                    },
                ]
            },
            "deep_dive": {"body": "짧음."},
        }
        out = enrich_generated_briefing_content(generated, "keysuri_global_tech", prompt_input)
        item = out["top_5_news"]["items"][0]
        self.assertGreaterEqual(_sentence_count(item["what_happened"]), 3)
        self.assertNotIn("TOP 신호", out["deep_dive"]["body"])
        self.assertGreaterEqual(len(out["deep_dive"].get("linked_signal_titles") or []), 2)

    def test_korea_enricher_normalizes_list_next_watch(self) -> None:
        item = {
            "korean_title": "삼성전자 HBM 국내 증설",
            "next_watch": ["삼성 HBM4 일정", "엔비디아 후속 발표"],
            "source_ids": ["k1"],
        }
        meta = {"category_display_label": "국내 반도체 / 장비 / 소재"}
        enriched = enrich_korea_top5_item_content(item, meta=meta)
        self.assertIn("삼성 HBM4 일정", enriched["next_watch"])
        self.assertNotIn("['", enriched["next_watch"])

    def test_korea_enricher_uses_domestic_lens_metadata(self) -> None:
        item = {
            "korean_title": "삼성전자 HBM 국내 증설",
            "what_happened": "공식 요약에 따르면 변화가 보고되었습니다.",
            "source_ids": ["k1"],
        }
        meta = {
            "primary_category": "korea_semiconductor",
            "category_display_label": "국내 반도체 / 장비 / 소재",
            "owner_action_line": "내일 파트너·입찰 일정을 점검하세요.",
            "next_day_impact_line": "내일 영향: 반도체 신호가 우선순위에 반영될 수 있습니다.",
            "angle_chip": "국내 적용",
            "global_duplicate_detected": True,
            "korea_angle_satisfied": True,
        }
        enriched = enrich_korea_top5_item_content(item, meta=meta)
        self.assertEqual(enriched.get("angle_chip"), "국내 적용")
        self.assertIn("내일", enriched["why_now"])
        self.assertIn("국내 적용", enriched["selection_reason"])

    def test_korea_generated_enricher_avoids_internal_gate_phrases(self) -> None:
        prompt_input = {
            "source_pack": {
                "claims": [
                    {
                        "source_ids": ["k1"],
                        "primary_category": "korea_policy_regulation",
                        "category_display_label": "국내 정책 / 규제 / 공공",
                        "owner_action_line": "내일 입찰 일정을 점검하세요.",
                        "next_day_impact_line": "내일 영향: 정책 신호가 의사결정에 반영될 수 있습니다.",
                    }
                ],
                "sources": [{"source_id": "k1", "source_name": "연합뉴스"}],
            }
        }
        generated = {
            "top_5_news": {
                "items": [
                    {
                        "rank": 1,
                        "news_id": "n1",
                        "source_ids": ["k1"],
                        "korean_title": "국내 정책 신호",
                        "what_happened": "짧음.",
                    }
                ]
            },
            "deep_dive": {"body": "TOP 신호 1·2 레이어 검증 통과 문장."},
            "briefing_display": {"closing_message": "오늘 신호를 정리했습니다."},
        }
        out = enrich_generated_briefing_content(generated, "keysuri_korea_tech", prompt_input)
        self.assertNotIn("TOP 신호", out["deep_dive"]["body"])
        self.assertNotIn("gate", out["deep_dive"]["body"].lower())
        self.assertIn("글로벌 영향", out["deep_dive"]["body"])
        self.assertGreaterEqual(len(out["deep_dive"].get("korea_deep_dive_sections") or []), 5)


if __name__ == "__main__":
    unittest.main()
