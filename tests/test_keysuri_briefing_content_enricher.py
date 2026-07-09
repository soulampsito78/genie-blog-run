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


class GlobalRepeatedFillerSanitizerTests(unittest.TestCase):
    """Global cross-item filler sanitizer + concrete next_watch (QA stays strict)."""

    _FILLER_BROAD = (
        "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."
    )
    _FILLER_AI = "배포·워크플로·API 통제권 변화와 맞닿는 시점입니다."

    def test_sanitizer_reduces_repeated_filler_to_one(self) -> None:
        from keysuri_briefing_content_enricher import sanitize_global_repeated_common_filler

        items = [
            {
                "news_id": "n1",
                "primary_category": "ai_software_platform",
                "why_now": (
                    f"공식 발표와 비용 구조 변화가 겹칩니다. {self._FILLER_BROAD} "
                    "후속 가격 조건을 보면 됩니다."
                ),
            },
            {
                "news_id": "n2",
                "primary_category": "semiconductor_chip_infra",
                "why_now": (
                    f"공급 일정이 핵심입니다. {self._FILLER_BROAD} "
                    "벤치마크 발표를 보면 됩니다."
                ),
            },
        ]
        out, diag = sanitize_global_repeated_common_filler(items)
        blob = " ".join(i.get("why_now", "") for i in out)
        self.assertEqual(blob.count(self._FILLER_BROAD), 1)
        self.assertTrue(diag["sanitizer_applied"])
        self.assertGreaterEqual(diag["sanitizer_removed_count"], 1)
        self.assertIn("n2", diag["affected_item_ids"])
        self.assertTrue(out[1]["why_now"].strip())
        self.assertNotIn(self._FILLER_BROAD, out[1]["why_now"])
        self.assertIn("공급 일정", out[1]["why_now"])

    def test_sanitizer_then_post_render_qa_passes(self) -> None:
        from keysuri_briefing_content_enricher import sanitize_global_repeated_common_filler
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )

        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_sanitizer_pass"
        for item in fixture["top_5_items"][:2]:
            item["why_now"] = (
                f"공식 발표와 비용 구조 변화가 겹치는 시점입니다. {self._FILLER_BROAD} "
                "후속 가격·API 조건을 확인해야 합니다."
            )
        sanitized, diag = sanitize_global_repeated_common_filler(fixture["top_5_items"])
        fixture["top_5_items"] = sanitized
        prepare_contract_preview_fixture(fixture, repo_root=_REPO, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_sanitizer_pass",
            run_id="test_sanitizer_pass",
        )
        result = validate_global_post_render_visible_quality(
            email_html,
            sanitizer_diagnostics=diag,
        )
        self.assertTrue(result.ok, [i.message for i in result.issues])
        self.assertTrue(result.diagnostics.get("sanitizer_applied"))

    def test_qa_still_blocks_when_filler_remains_repeated(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        html = (
            f"<p>항목1. {self._FILLER_BROAD} 후속 확인.</p>"
            f"<p>항목2. {self._FILLER_BROAD} 후속 확인.</p>"
        )
        result = validate_global_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn("global_repeated_common_filler", {i.code for i in result.issues})
        phrases = result.diagnostics.get("repeated_phrases") or []
        self.assertTrue(phrases)
        self.assertGreaterEqual(phrases[0].get("repeated_count", 0), 2)

    def test_enricher_next_watch_uses_category_concrete_checkpoints(self) -> None:
        item = {
            "korean_title": "OpenAI API 가격 개편",
            "next_watch": "시장 반응을 지켜봐야 합니다.",
            "source_ids": ["s1"],
            "primary_category": "ai_software_platform",
        }
        meta = {
            "source_name": "OpenAI News",
            "primary_category": "ai_software_platform",
            "category_label_ko": "AI·소프트웨어·플랫폼",
        }
        enriched = enrich_top5_item_content(item, meta=meta)
        watch = enriched["next_watch"]
        self.assertIn("API", watch)
        self.assertNotIn("시장 반응을 지켜봐야", watch)
        self.assertGreaterEqual(_watch_checkpoint_count(watch), 2)

    def test_enrich_generated_briefing_dedupes_common_filler_across_items(self) -> None:
        prompt_input = {
            "source_pack": {
                "claims": [
                    {
                        "source_ids": ["s1"],
                        "primary_category": "ai_software_platform",
                        "selection_score": 50,
                    },
                    {
                        "source_ids": ["s2"],
                        "primary_category": "hardware_device_display",
                        "selection_score": 48,
                    },
                ],
                "sources": [
                    {"source_id": "s1", "source_name": "OpenAI"},
                    {"source_id": "s2", "source_name": "Google"},
                ],
            }
        }
        generated = {
            "top_5_news": {
                "items": [
                    {
                        "rank": 1,
                        "news_id": "n1",
                        "source_ids": ["s1"],
                        "korean_title": "테스트 A",
                        "what_happened": "공식 요약에 따르면 업데이트가 보고되었습니다. 세부 일정은 후속 발표로 보완됩니다. 공개 범위는 요약 수준입니다.",
                        "why_now": (
                            f"배포 정책이 바뀌는 시점입니다. {self._FILLER_AI} "
                            f"{self._FILLER_BROAD} 가격 조건을 보면 됩니다."
                        ),
                        "owner_angle": "파트너 조건을 보면 됩니다. API 비용 경계를 점검하면 됩니다. 단기 과장은 구분하면 됩니다.",
                        "next_watch": "API 공개 일정; 엔터프라이즈 도입",
                    },
                    {
                        "rank": 2,
                        "news_id": "n2",
                        "source_ids": ["s2"],
                        "korean_title": "테스트 B",
                        "what_happened": "공식 요약에 따르면 제품 변화가 보고되었습니다. 세부 일정은 후속 발표로 보완됩니다. 공개 범위는 요약 수준입니다.",
                        "why_now": (
                            f"검색 경험이 바뀌는 시점입니다. {self._FILLER_AI} "
                            f"{self._FILLER_BROAD} 유통 일정을 보면 됩니다."
                        ),
                        "owner_angle": "사용자 접점을 보면 됩니다. 기획 시사점을 점검하면 됩니다. 단기 과장은 구분하면 됩니다.",
                        "next_watch": "출시 일정; 유통 채널",
                    },
                ]
            },
            "deep_dive": {
                "body": (
                    "오늘 흐름은 플랫폼과 디바이스가 동시에 움직입니다. "
                    "한쪽은 API·배포 조건이고 다른 쪽은 사용자 접점입니다. "
                    "단기 과장과 구조 변화는 구분해 보시면 됩니다. "
                    "후속 공식 발표를 통해 세부 내용이 보완될 가능성이 있습니다. "
                    "운영·파트너 의사결정에 어떤 경계가 생기는지 보면 됩니다."
                )
            },
        }
        out = enrich_generated_briefing_content(generated, "keysuri_global_tech", prompt_input)
        why_blob = " ".join(
            str(i.get("why_now") or "") for i in out["top_5_news"]["items"] if isinstance(i, dict)
        )
        self.assertLessEqual(why_blob.count(self._FILLER_BROAD), 1)
        self.assertLessEqual(why_blob.count(self._FILLER_AI), 1)
        diag = out.get("_global_filler_sanitizer") or {}
        self.assertTrue(diag.get("sanitizer_applied") or why_blob.count(self._FILLER_BROAD) <= 1)


if __name__ == "__main__":
    unittest.main()
