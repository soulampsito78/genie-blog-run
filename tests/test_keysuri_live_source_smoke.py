"""Tests for Kee-Suri live source-pack smoke helpers."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from keysuri_live_source_smoke import (
    GLOBAL_TECH_SMOKE_FEEDS,
    KOREA_TECH_ALLOWED_CATEGORIES,
    KOREA_TECH_SMOKE_FEEDS,
    PROGRAM_KOREA,
    SAMPLE_MARKER_PATTERNS,
    _feeds_for_program,
    build_live_source_pack,
    extract_generated_body_text,
    normalize_generated_briefing_closing_aliases,
    normalize_generated_briefing_schema_aliases,
    run_keysuri_live_source_smoke,
    scan_placeholder_markers,
    scan_sample_markers,
    FetchedFeedItem,
)
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_renderer import render_keysuri_owner_review_html
from keysuri_html_preview_validation import validate_keysuri_html_preview

_REPO = Path(__file__).resolve().parent.parent


def _fake_items(count: int = 5) -> list[FetchedFeedItem]:
    items: list[FetchedFeedItem] = []
    for idx in range(1, count + 1):
        items.append(
            FetchedFeedItem(
                feed_id=f"feed-{idx}",
                feed_name=f"Publisher {idx}",
                feed_url=f"https://publisher{idx}.example.org/feed/",
                source_tier="T3_QUALITY_PRESS",
                default_category="market_signal",
                title=f"Live tech headline {idx} from public feed",
                link=f"https://news.publisher{idx}.org/articles/live-tech-{idx}",
                published_at="2026-06-08T12:00:00+09:00",
                summary=(
                    f"Summary for live tech headline {idx}: enterprise AI platform, API workflow, "
                    "and monetization signal for operators and founders."
                ),
            )
        )
    return items


def _mock_generated_briefing(prompt_input: dict) -> dict:
    pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    sources = pack.get("sources") if isinstance(pack.get("sources"), list) else []
    source_ids = [str(s.get("source_id")) for s in sources[:2] if isinstance(s, dict)]
    top_items = []
    for idx, item in enumerate((prompt_input.get("top_5_news") or {}).get("items") or [], start=1):
        if not isinstance(item, dict):
            continue
        what_happened = (
            f"항목 {idx}에서 RSS·원문 요약에 따르면 주요 변화가 보고되었습니다. "
            f"세부 일정·수치는 원문 확인이 필요할 수 있습니다. "
            f"키수리는 확인 가능한 범위 안에서만 정리했습니다."
        )
        why_now = (
            f"항목 {idx}는 엔터프라이즈 배포·API 정책 변경이 겹치는 시점이라 "
            f"주인님의 파트너·비용 구조에 단기 영향이 나올 수 있습니다. "
            f"경쟁사 대응 일정과 공급망 리스크도 같은 주에 겹칠 수 있어 지금 점검 가치가 있습니다. "
            f"공식 후속 발표가 나오기 전까지는 과장 없이 관찰 우선이 안전합니다."
        )
        owner_angle = (
            f"주인님께서는 항목 {idx}를 제품·파트너 선정 기준에 반영할지 점검하시면 됩니다. "
            f"단기 과장과 장기 구조 변화를 구분해 보시는 것이 좋습니다. "
            f"자동화·콘텐츠 운영 로드맵에 API 비용과 배포 제약을 함께 넣어 보시길 권합니다."
        )
        selection_reason = (
            f"항목 {idx}는 글로벌 테크 신호 점수와 카테고리 다양성 기준으로 선정했습니다. "
            f"반도체·인프라·공급망 측면에서 주인님 의사결정과 연결되는 신호입니다."
        )
        next_watch = (
            f"→ 항목 {idx} 공식 발표·가격·일정 공개 여부 확인; "
            f"→ 공급망·인프라 후속 보도와 정책 변화 추적"
        )
        top_items.append(
            {
                **item,
                "korean_title": f"글로벌 AI 신호 {idx} — 공급망·플랫폼 압력",
                "headline": f"글로벌 AI 신호 {idx} — 공급망·플랫폼 압력",
                "selection_reason": selection_reason,
                "what_happened": what_happened,
                "why_now": why_now,
                "owner_angle": owner_angle,
                "briefing_item": {
                    "korean_title": f"글로벌 AI 신호 {idx} — 공급망·플랫폼 압력",
                    "selection_reason": selection_reason,
                    "what_happened": what_happened,
                    "why_now": why_now,
                    "owner_angle": owner_angle,
                    "keysuri_judgment": {
                        "label": "관찰",
                        "explanation": f"항목 {idx} — 후속 공식 발표 확인 후 활용 여부를 결정하세요.",
                    },
                    "next_watch": next_watch,
                },
                "next_watch": next_watch,
            }
        )
    return {
        "program_id": prompt_input.get("program_id"),
        "news_scope": prompt_input.get("news_scope"),
        "section_heading": prompt_input.get("section_heading"),
        "generated_status": "generated_review_required",
        "operational_status": "review_required",
        "briefing_display": {
            "opening_lead": (
                "주인님, 오늘 글로벌 테크 신호는 AI 플랫폼 통제권 이동으로 읽힙니다. "
                "공급망과 배포 레이어 압력이 동시에 커지고 있습니다. "
                "키수리는 주인님께 의사결정에 바로 쓸 수 있는 관점으로 정리했습니다."
            ),
            "selected_title": "[키수리 브리핑] AI 플랫폼 통제권 이동 신호",
            "title_candidates": [
                "[키수리 브리핑] AI 플랫폼 통제권 이동 신호",
                "[키수리] 오늘의 테크 신호 — 배포 레이어 압력",
            ],
        },
        "top_5_news": {
            "news_scope": prompt_input.get("news_scope"),
            "section_heading": prompt_input.get("section_heading"),
            "items": top_items,
        },
        "deep_dive": {
            "section_heading": "키수리의 딥-다이브",
            "body": (
                "주인님, 오늘 선정된 TOP 신호 1·2는 AI 기능 발표보다 배포·검색·개발 루틴 장악 속도에 초점이 맞춰져 있습니다. "
                "확인된 사실은 공식 블로그·보도자료·RSS 요약 범위 안에 머무릅니다. "
                "키수리 해석상 플랫폼 통제권은 모델 성능 경쟁에서 워크플로 락인 경쟁으로 이동 중입니다. "
                "한국 운영자·창업자에게는 API 가격·지역 가용성·데이터 주권이 곧바로 비용 구조에 반영될 수 있습니다. "
                "아직 불확실한 점은 각사의 상용 일정과 엔터프라이즈 계약 조건입니다."
            ),
            "confirmed_facts": ["RSS·원문 요약 범위 내 사실만 반영"],
            "interpretation": "플랫폼 통제권이 워크플로 락인 쪽으로 이동 중입니다.",
            "owner_impact": "주인님의 API·파트너 비용 구조에 직접 영향을 줄 수 있습니다.",
            "uncertainty": "상용 일정·엔터프라이즈 계약 조건은 추가 확인 필요",
            "key_implications": ["인프라 신호", "규제 압력", "워크플로 락인"],
            "source_ids": source_ids,
            "confidence_label": "reported",
        },
        "one_line_checkpoint": {
            "section_heading": "원-라인 체크포인트",
            "body": "주인님, 오늘 먼저 확인하실 포인트: 워크플로 락인 속도와 API 가격 변동입니다.",
        },
        "closing_sources": {
            "section_heading": "마무리 및 출처 리스트",
            "closing_message": "주인님, 오늘 신호 정리는 여기까지입니다. 원-라인 체크포인트 기준으로 다음 확인을 이어가시면 됩니다.",
            "source_list": [
                {
                    "source_id": str(src.get("source_id")),
                    "label": str(src.get("source_name")),
                    "url": str(src.get("source_url")),
                }
                for src in sources[:3]
                if isinstance(src, dict)
            ],
        },
    }


class KeysuriLiveSourceSmokeTests(unittest.TestCase):
    def test_sample_marker_gate_blocks_example_com(self) -> None:
        hits = scan_sample_markers("Visit https://example.com/source/global-ai-official")
        codes = {h.code for h in hits}
        self.assertIn("example_com", codes)

    def test_sample_marker_gate_blocks_fixture_ids(self) -> None:
        hits = scan_sample_markers("source_ids: global-t0-ai-official, global-t2-market-wire")
        codes = {h.code for h in hits}
        self.assertTrue({"fixture_source_id_global_t0", "fixture_source_id_market_wire"} & codes)

    def test_live_renderer_output_has_no_sample_markers(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        from keysuri_prompt_input import build_keysuri_prompt_input

        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        html = render_keysuri_owner_review_html(prompt_input, preview_mode="live_smoke")
        hits = scan_sample_markers(json.dumps(pack), html)
        self.assertEqual(hits, [], hits)
        self.assertIn("not generated briefing", html)
        self.assertNotIn("No live fetch", html)
        self.assertNotIn("No Gemini call", html)

    def test_no_send_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                unique = FetchedFeedItem(
                    feed_id=feed["feed_id"],
                    feed_name=feed["feed_name"],
                    feed_url=feed["feed_url"],
                    source_tier=feed["source_tier"],
                    default_category=feed["default_category"],
                    title=f"{pick.title} ({feed['feed_id']})",
                    link=f"{pick.link}/{feed['feed_id']}",
                    published_at=pick.published_at,
                    summary=pick.summary,
                )
                return [unique]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    out_dir=Path(tmpdir),
                    repo_root=_REPO,
                )
        self.assertFalse(result.send_attempted)
        self.assertEqual(result.send_block_reason, "send_not_requested")

    def test_send_requires_confirm(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                unique = FetchedFeedItem(
                    feed_id=feed["feed_id"],
                    feed_name=feed["feed_name"],
                    feed_url=feed["feed_url"],
                    source_tier=feed["source_tier"],
                    default_category=feed["default_category"],
                    title=f"{pick.title} ({feed['feed_id']})",
                    link=f"{pick.link}/{feed['feed_id']}",
                    published_at=pick.published_at,
                    summary=pick.summary,
                )
                return [unique]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    send=True,
                    send_confirm=None,
                    recipients=["soulampsito@gmail.com"],
                    out_dir=Path(tmpdir),
                    repo_root=_REPO,
                )
        self.assertFalse(result.send_success)
        self.assertEqual(result.send_block_reason, "confirm_send_missing")

    def test_build_live_source_pack_rejects_fixture_like_urls(self) -> None:
        bad = _fake_items(1)[0]
        bad.link = "https://example.com/bad"
        with self.assertRaises(ValueError):
            build_live_source_pack("keysuri_global_tech", [bad] * 5)

    def test_sample_marker_patterns_are_non_empty(self) -> None:
        self.assertGreaterEqual(len(SAMPLE_MARKER_PATTERNS), 8)

    def test_source_led_smoke_does_not_claim_generated_body(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        html = render_keysuri_owner_review_html(prompt_input, preview_mode="live_smoke")
        self.assertIn("not generated briefing", html)
        self.assertIn("generation_pending", html)

    def test_placeholder_gate_blocks_generation_pending(self) -> None:
        hits = scan_placeholder_markers('<p class="badge-pending">generation_pending</p>')
        self.assertTrue(hits)

    def test_generated_mode_html_blocks_generation_pending(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        generated = _mock_generated_briefing(prompt_input)
        html = render_keysuri_owner_review_html(
            prompt_input,
            generated,
            preview_mode="live_smoke_generated",
        )
        hits = scan_placeholder_markers(html)
        self.assertEqual(hits, [], hits)
        self.assertNotIn("generation_pending", html)

    def test_owner_review_validator_passes_generated_live_html(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pack = build_live_source_pack("keysuri_global_tech", _fake_items())
            prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
            generated = _mock_generated_briefing(prompt_input)
            html = render_keysuri_owner_review_html(
                prompt_input,
                generated,
                preview_mode="live_smoke_generated",
            )
            path = Path(tmpdir) / "output" / "keysuri_preview" / (
                "keysuri_global_live_source_smoke_generated_owner_review_test.html"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertTrue(result.is_pass(), result.issues)

    def test_owner_review_validator_fails_generated_html_with_generation_pending(self) -> None:
        with TemporaryDirectory() as tmpdir:
            pack = build_live_source_pack("keysuri_global_tech", _fake_items())
            prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
            html = render_keysuri_owner_review_html(prompt_input, preview_mode="live_smoke_generated")
            path = Path(tmpdir) / "output" / "keysuri_preview" / (
                "keysuri_global_live_source_smoke_generated_owner_review_bad.html"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertFalse(result.is_pass())
            codes = {issue.code for issue in result.issues}
            self.assertTrue(
                codes & {"forbidden_generation_pending", "generated_section_missing", "generated_badge_missing"},
                msg=f"expected generated-body failure, got {codes}",
            )

    def test_normalize_closing_aliases_maps_source_name_to_label(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        src = pack["sources"][0]
        generated = {
            "closing_sources": {
                "source_list": [
                    {
                        "source_id": src["source_id"],
                        "source_name": src["source_name"],
                        "source_url": src["source_url"],
                    }
                ]
            }
        }
        normalized = normalize_generated_briefing_closing_aliases(generated, prompt_input)
        entry = normalized["closing_sources"]["source_list"][0]
        self.assertEqual(entry["label"], src["source_name"])
        self.assertEqual(entry["url"], src["source_url"])

    def test_mocked_gemini_generation_path_renders_body_sections(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)
            captured: dict = {}

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                return [
                    FetchedFeedItem(
                        feed_id=feed["feed_id"],
                        feed_name=feed["feed_name"],
                        feed_url=feed["feed_url"],
                        source_tier=feed["source_tier"],
                        default_category=feed["default_category"],
                        title=f"{pick.title} ({feed['feed_id']})",
                        link=f"{pick.link}/{feed['feed_id']}",
                        published_at=pick.published_at,
                        summary=pick.summary,
                    )
                ]

            real_build = build_keysuri_prompt_input

            def _capture_prompt_input(*args, **kwargs):
                out = real_build(*args, **kwargs)
                captured["prompt_input"] = out
                return out

            def _fake_gemini(prompt_text, **kwargs):
                return json.dumps(_mock_generated_briefing(captured["prompt_input"]))

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch), mock.patch(
                "keysuri_live_source_smoke.build_keysuri_prompt_input",
                side_effect=_capture_prompt_input,
            ):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    use_gemini=True,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    gemini_caller=_fake_gemini,
                )

            self.assertTrue(result.ok, result.error or result.validation_issues)
            self.assertEqual(result.parse_status, "parsed_valid")
            html = Path(result.html_path).read_text(encoding="utf-8")
            self.assertNotIn("generation_pending", html)
            self.assertTrue(result.generated_body.get("deep_dive"))
            self.assertTrue(result.generated_body.get("one_line_checkpoint"))
            self.assertTrue(result.generated_body.get("closing_sources"))

    def test_contract_preview_requires_use_gemini(self) -> None:
        result = run_keysuri_live_source_smoke(
            allow_network=False,
            contract_preview=True,
            use_gemini=False,
            repo_root=_REPO,
        )
        self.assertFalse(result.ok)
        self.assertIn("requires --use-gemini", result.error or "")

    def test_mocked_contract_preview_path_uses_html_test_surface(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)
            captured: dict = {}
            hero = Path(tmpdir) / "hero.jpg"
            hero.write_bytes(b"fakejpeg")

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                return [
                    FetchedFeedItem(
                        feed_id=feed["feed_id"],
                        feed_name=feed["feed_name"],
                        feed_url=feed["feed_url"],
                        source_tier=feed["source_tier"],
                        default_category=feed["default_category"],
                        title=f"{pick.title} ({feed['feed_id']})",
                        link=f"{pick.link}/{feed['feed_id']}",
                        published_at=pick.published_at,
                        summary=pick.summary,
                    )
                ]

            def _capture_prompt_input(*args, **kwargs):
                out = build_keysuri_prompt_input(*args, **kwargs)
                captured["prompt_input"] = out
                return out

            def _fake_gemini(prompt_text, **kwargs):
                return json.dumps(_mock_generated_briefing(captured["prompt_input"]))

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch), mock.patch(
                "keysuri_live_source_smoke.build_keysuri_prompt_input",
                side_effect=_capture_prompt_input,
            ), mock.patch(
                "keysuri_live_source_smoke.resolve_approved_hero_image_path",
                return_value=hero,
            ):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    use_gemini=True,
                    contract_preview=True,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    gemini_caller=_fake_gemini,
                )

            self.assertTrue(result.contract_preview)
            self.assertTrue(result.image_in_html, result.validation_issues)
            html = Path(result.html_path).read_text(encoding="utf-8")
            self.assertIn("/html_test/", result.html_path.replace("\\", "/"))
            self.assertNotIn("why_it_matters:", html)
            self.assertNotIn("Source Gate / TOP 5 Selection Audit", html)
            self.assertIn("무슨 일이 있었나", html)
            self.assertIn("주인님 관점", html)
            self.assertIn('id="top-shot-image"', html)
            self.assertIn('id="premium-hero"', html)
            self.assertEqual(result.structural_gate_status, "pass")
            self.assertEqual(result.content_briefing_gate_status, "pass")
            self.assertIn(
                result.visual_identity_gate_status,
                ("fail", "manual_review_required"),
            )
            self.assertIn(
                result.preview_overall_status,
                ("blocked", "manual_visual_review_required"),
            )
            self.assertFalse(result.ready_for_owner_visual_review)

    def test_normalize_schema_aliases_maps_korean_top5_fields(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        prompt_item = (prompt_input.get("top_5_news") or {}).get("items", [])[0]
        generated = {
            "top_5_news": {
                "items": [
                    {
                        "rank": 1,
                        "news_id": prompt_item["news_id"],
                        "korean_title": "글로벌 AI 신호 — 공급망 압력",
                        "what_happened": "RSS 요약에 따르면 주요 변화가 보고되었습니다. 세부는 원문 확인이 필요합니다.",
                        "why_now": "지금 시장에서 주목받는 신호입니다. 배포 레이어에 영향을 줄 수 있습니다.",
                        "owner_angle": "주인님께서는 제품 로드맵 반영 여부를 점검하시면 됩니다.",
                    }
                ]
            }
        }
        normalized = normalize_generated_briefing_schema_aliases(generated, prompt_input)
        item = normalized["top_5_news"]["items"][0]
        self.assertEqual(item["headline"], "글로벌 AI 신호 — 공급망 압력")
        self.assertTrue(item["summary"])
        self.assertTrue(item["why_it_matters"])
        self.assertTrue(item["business_implication"])
        self.assertTrue(item["category"])
        self.assertTrue(item["source_ids"])

    def test_normalize_schema_aliases_fills_key_implications_from_confirmed_facts(self) -> None:
        pack = build_live_source_pack("keysuri_global_tech", _fake_items())
        prompt_input = build_keysuri_prompt_input("keysuri_global_tech", pack)
        generated = {
            "deep_dive": {
                "confirmed_facts": ["RSS 요약 범위 내 사실 A", "RSS 요약 범위 내 사실 B"],
                "interpretation": "플랫폼 통제권이 워크플로 락인 쪽으로 이동 중입니다.",
                "open_questions": ["상용 일정 미확정"],
            }
        }
        normalized = normalize_generated_briefing_schema_aliases(generated, prompt_input)
        implications = normalized["deep_dive"]["key_implications"]
        self.assertGreaterEqual(len(implications), 2)
        self.assertIn("RSS 요약 범위 내 사실 A", implications)

    def test_contract_preview_accepts_explicit_image_path_embeds_data_uri(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)
            captured: dict = {}
            hero = Path(tmpdir) / "keysuri_global_generated_topshot_test_mirai_on_watermarked.jpg"
            hero.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 600)
            manifest = {
                "image_source": "generated_test",
                "image_role": "top_shot",
                "width": 1280,
                "height": 720,
                "aspect_ratio": 1.78,
                "overlay_applied": True,
                "watermark": "MirAI:ON applied",
                "reference_image_path": "assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png",
                "reference_image_sha256": "abc123",
                "batch_id": "batch_test",
                "selected_candidate_id": "cand_01",
                "quality_verdict": "pass",
                "owner_visual_review_required": True,
            }
            hero.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                return [
                    FetchedFeedItem(
                        feed_id=feed["feed_id"],
                        feed_name=feed["feed_name"],
                        feed_url=feed["feed_url"],
                        source_tier=feed["source_tier"],
                        default_category=feed["default_category"],
                        title=f"{pick.title} ({feed['feed_id']})",
                        link=f"{pick.link}/{feed['feed_id']}",
                        published_at=pick.published_at,
                        summary=pick.summary,
                    )
                ]

            def _capture_prompt_input(*args, **kwargs):
                out = build_keysuri_prompt_input(*args, **kwargs)
                captured["prompt_input"] = out
                return out

            def _fake_gemini(prompt_text, **kwargs):
                return json.dumps(_mock_generated_briefing(captured["prompt_input"]))

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch), mock.patch(
                "keysuri_live_source_smoke.build_keysuri_prompt_input",
                side_effect=_capture_prompt_input,
            ):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    use_gemini=True,
                    contract_preview=True,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    gemini_caller=_fake_gemini,
                    top_shot_image_path=hero,
                )

            self.assertTrue(
                result.ok,
                result.error or result.validation_issues or result.visible_body_quality_issues,
            )
            self.assertEqual(result.image_source_mode, "explicit_test_override")
            self.assertEqual(result.preview_overall_status, "manual_visual_review_required")
            self.assertFalse(result.ready_for_owner_visual_review)
            self.assertTrue(result.ready_for_owner_manual_visual_inspection)
            self.assertIsNone(result.approved_asset_id)
            self.assertEqual(result.image_path, str(hero.resolve()))
            self.assertFalse(result.side_effects.get("called_image_api"))
            html = Path(result.html_path).read_text(encoding="utf-8")
            self.assertIn('src="data:image/', html)
            self.assertNotIn("../image_canary", html)
            style = html[html.find("<style>") : html.find("</style>")]
            self.assertIn("object-fit:contain", style.replace(" ", ""))
            self.assertNotRegex(style, r"\.top-shot-hero\{[^}]*object-fit:\s*cover")

    def test_contract_preview_default_uses_approved_registry_asset_when_present(self) -> None:
        canary = _REPO / (
            "output/keysuri_preview/image_canary/"
            "keysuri_global_canary_20260604_221233_mirai_on_watermarked.jpg"
        )
        if not canary.is_file():
            self.skipTest("approved global top watermarked asset not present locally")

        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)
            captured: dict = {}

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                return [
                    FetchedFeedItem(
                        feed_id=feed["feed_id"],
                        feed_name=feed["feed_name"],
                        feed_url=feed["feed_url"],
                        source_tier=feed["source_tier"],
                        default_category=feed["default_category"],
                        title=f"{pick.title} ({feed['feed_id']})",
                        link=f"{pick.link}/{feed['feed_id']}",
                        published_at=pick.published_at,
                        summary=pick.summary,
                    )
                ]

            def _capture_prompt_input(*args, **kwargs):
                out = build_keysuri_prompt_input(*args, **kwargs)
                captured["prompt_input"] = out
                return out

            def _fake_gemini(prompt_text, **kwargs):
                return json.dumps(_mock_generated_briefing(captured["prompt_input"]))

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch), mock.patch(
                "keysuri_live_source_smoke.build_keysuri_prompt_input",
                side_effect=_capture_prompt_input,
            ):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    use_gemini=True,
                    contract_preview=True,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    gemini_caller=_fake_gemini,
                )

            self.assertEqual(result.image_source_mode, "approved_registry")
            self.assertEqual(result.approved_asset_id, "keysuri_global_top_20260604_221233")
            self.assertEqual(Path(result.image_path).resolve(), canary.resolve())
            self.assertIn("221233_mirai_on_watermarked", result.image_path or "")
            self.assertNotIn("105936", result.image_path or "")
            self.assertEqual(result.visual_identity_gate_status, "pass")
            visual_warnings = [
                w.get("code")
                for w in (result.preview_validation or {})
                .get("visual_identity_gate", {})
                .get("warnings", [])
            ]
            self.assertNotIn("watermark_pending", visual_warnings)
            self.assertIn(
                result.preview_overall_status,
                ("owner_visual_review_ready", "manual_visual_review_required", "blocked"),
            )
            if result.preview_overall_status == "owner_visual_review_ready":
                self.assertTrue(result.ready_for_owner_visual_review)
            else:
                self.assertFalse(result.ready_for_owner_visual_review)
            self.assertFalse(result.side_effects.get("called_image_api"))

    def test_contract_preview_parse_failure_does_not_fallback_to_staged_fixture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(10)
            captured: dict = {}

            def _fetch(feed, **kwargs):
                pick = items[(hash(feed["feed_id"]) % len(items))]
                return [
                    FetchedFeedItem(
                        feed_id=feed["feed_id"],
                        feed_name=feed["feed_name"],
                        feed_url=feed["feed_url"],
                        source_tier=feed["source_tier"],
                        default_category=feed["default_category"],
                        title=f"{pick.title} ({feed['feed_id']})",
                        link=f"{pick.link}/{feed['feed_id']}",
                        published_at=pick.published_at,
                        summary=pick.summary,
                    )
                ]

            def _capture_prompt_input(*args, **kwargs):
                out = build_keysuri_prompt_input(*args, **kwargs)
                captured["prompt_input"] = out
                return out

            def _bad_gemini(prompt_text, **kwargs):
                return json.dumps({"invalid": "not a briefing schema"})

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch), mock.patch(
                "keysuri_live_source_smoke.build_keysuri_prompt_input",
                side_effect=_capture_prompt_input,
            ):
                result = run_keysuri_live_source_smoke(
                    allow_network=True,
                    use_gemini=True,
                    contract_preview=True,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    gemini_caller=_bad_gemini,
                )

            self.assertFalse(result.ok)
            self.assertIn("Gemini parse failed", result.error or "")
            self.assertTrue(result.raw_response_path)
            html_path = Path(result.html_path)
            if html_path.exists():
                html = html_path.read_text(encoding="utf-8")
                self.assertNotIn("스테이징 한국어 헤드라인", html)
                self.assertNotIn("Infrastructure signal", html)


class KeysuriKoreaTechSmokeFeedConfigTests(unittest.TestCase):
    _REQUIRED_FEED_KEYS = (
        "feed_id",
        "feed_name",
        "feed_url",
        "source_tier",
        "default_category",
        "language",
        "region",
    )

    def test_feeds_for_program_global_unchanged(self) -> None:
        feeds = _feeds_for_program("keysuri_global_tech")
        self.assertIs(feeds, GLOBAL_TECH_SMOKE_FEEDS)
        self.assertGreater(len(feeds), 0)

    def test_feeds_for_program_korea_returns_korea_feeds(self) -> None:
        feeds = _feeds_for_program("keysuri_korea_tech")
        self.assertIs(feeds, KOREA_TECH_SMOKE_FEEDS)
        self.assertGreaterEqual(len(feeds), 8)

    def test_korea_feed_metadata_and_taxonomy(self) -> None:
        feed_ids: set[str] = set()
        categories: set[str] = set()
        for feed in KOREA_TECH_SMOKE_FEEDS:
            for key in self._REQUIRED_FEED_KEYS:
                self.assertIn(key, feed, msg=f"missing {key} in {feed.get('feed_id')}")
            self.assertEqual(feed["language"], "ko")
            self.assertEqual(feed["region"], "KR")
            self.assertIn(feed["default_category"], KOREA_TECH_ALLOWED_CATEGORIES)
            feed_ids.add(feed["feed_id"])
            categories.add(feed["default_category"])
        self.assertEqual(len(feed_ids), len(KOREA_TECH_SMOKE_FEEDS))

    def test_korea_feed_source_group_coverage(self) -> None:
        categories = {f["default_category"] for f in KOREA_TECH_SMOKE_FEEDS}
        self.assertIn("korea_policy_regulation", categories)
        industrial = categories & {
            "korea_semiconductor",
            "korea_battery_energy",
            "korea_robotics_manufacturing",
        }
        self.assertGreaterEqual(len(industrial), 1)
        ecosystem = categories & {
            "korea_platform_cloud_saas",
            "korea_startup_investment",
        }
        self.assertGreaterEqual(len(ecosystem), 1)

    def test_korea_branch_does_not_change_global_feed_object(self) -> None:
        before = len(GLOBAL_TECH_SMOKE_FEEDS)
        _feeds_for_program("keysuri_korea_tech")
        self.assertEqual(len(GLOBAL_TECH_SMOKE_FEEDS), before)
        self.assertIs(_feeds_for_program("keysuri_global_tech"), GLOBAL_TECH_SMOKE_FEEDS)

    def test_korea_fetch_only_smoke_no_feed_config_error(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(15)
            for idx, item in enumerate(items):
                item.feed_id = f"korea-feed-{idx % 3 + 1}"
                item.feed_name = f"Korea Publisher {idx % 3 + 1}"
                item.link = f"https://news.korea-publisher{idx % 3 + 1}.co.kr/articles/live-{idx}"
                item.title = f"국내 테크 신호 {idx}: 반도체·AI·정책 움직임"
                item.default_category = "korea_semiconductor"
                item.summary = (
                    f"삼성전자 SK하이닉스 국내 반도체 HBM 투자 수주 입찰 일정 {idx}. "
                    "정책·조달 관련 후속 확인 필요."
                )

            cursor = {"i": 0}

            def _fetch(feed, **kwargs):
                start = cursor["i"]
                cursor["i"] += kwargs.get("max_items", 3)
                return items[start : start + kwargs.get("max_items", 3)]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    program_id=PROGRAM_KOREA,
                    max_items=5,
                    allow_network=True,
                    use_gemini=False,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                )

            self.assertNotIn("No live smoke feed list configured", result.error or "")
            self.assertGreaterEqual(result.fetched_item_count, 5)
            pack = json.loads(Path(result.source_pack_path).read_text(encoding="utf-8"))
            self.assertIn("korea_top5_selection", pack)
            debug_dir = Path(tmpdir) / "output" / "keysuri_preview" / "debug"
            korea_reports = list(debug_dir.glob("korea_top5_selection_*.json"))
            self.assertGreaterEqual(len(korea_reports), 1)
            report = json.loads(korea_reports[0].read_text(encoding="utf-8"))
            self.assertIn("final_category_distribution", report)
            self.assertIn("final_source_distribution", report)
            self.assertEqual(report.get("duplicate_guard_status"), "not_applied_no_global_report")

    def test_korea_smoke_uses_korea_scoring_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(12)
            for idx, item in enumerate(items):
                item.default_category = "korea_policy_regulation"
                item.title = f"국내 정책 신호 {idx}"
            cursor = {"i": 0}

            def _fetch(feed, **kwargs):
                start = cursor["i"]
                cursor["i"] += kwargs.get("max_items", 3)
                return items[start : start + kwargs.get("max_items", 3)]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                with mock.patch(
                    "keysuri_live_source_smoke.score_korea_candidates_from_source_pack"
                ) as korea_score:
                    with mock.patch(
                        "keysuri_live_source_smoke.score_candidates_from_source_pack"
                    ) as global_score:
                        from keysuri_korea_signal_scoring import score_candidates_from_source_pack

                        korea_score.side_effect = score_candidates_from_source_pack
                        run_keysuri_live_source_smoke(
                            program_id=PROGRAM_KOREA,
                            max_items=5,
                            allow_network=True,
                            use_gemini=False,
                            out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                            repo_root=_REPO,
                        )
                        korea_score.assert_called_once()
                        global_score.assert_not_called()

    def test_global_smoke_still_uses_global_scoring_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(12)
            cursor = {"i": 0}

            def _fetch(feed, **kwargs):
                start = cursor["i"]
                cursor["i"] += kwargs.get("max_items", 3)
                return items[start : start + kwargs.get("max_items", 3)]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                with mock.patch(
                    "keysuri_live_source_smoke.score_candidates_from_source_pack"
                ) as global_score:
                    with mock.patch(
                        "keysuri_live_source_smoke.score_korea_candidates_from_source_pack"
                    ) as korea_score:
                        from keysuri_global_signal_scoring import score_candidates_from_source_pack

                        global_score.side_effect = score_candidates_from_source_pack
                        run_keysuri_live_source_smoke(
                            program_id="keysuri_global_tech",
                            max_items=5,
                            allow_network=True,
                            use_gemini=False,
                            out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                            repo_root=_REPO,
                        )
                        global_score.assert_called_once()
                        korea_score.assert_not_called()

    def test_korea_smoke_invalid_global_report_path_fails_clearly(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(12)
            for idx, item in enumerate(items):
                item.default_category = "korea_semiconductor"
                item.title = f"국내 반도체 신호 {idx}"
            cursor = {"i": 0}

            def _fetch(feed, **kwargs):
                start = cursor["i"]
                cursor["i"] += kwargs.get("max_items", 3)
                return items[start : start + kwargs.get("max_items", 3)]

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    program_id=PROGRAM_KOREA,
                    max_items=5,
                    allow_network=True,
                    use_gemini=False,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    global_selection_report_path=Path(tmpdir) / "missing-global-report.json",
                )
            self.assertFalse(result.ok)
            self.assertIn("Global selection report not found", result.error or "")

    def test_korea_smoke_applies_duplicate_guard_with_mock_global_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            items = _fake_items(12)
            for idx, item in enumerate(items):
                item.default_category = "korea_semiconductor"
                if idx < 8:
                    item.title = f"OpenAI launches developer platform API {idx}"
                    item.summary = "OpenAI platform API workflow for enterprise developers."
                else:
                    item.title = f"삼성전자 SK하이닉스 HBM 국내 증설 수주 {idx}"
                    item.summary = "국내 반도체 HBM 증설 투자 수주 입찰 일정."
            cursor = {"i": 0}

            def _fetch(feed, **kwargs):
                start = cursor["i"]
                cursor["i"] += kwargs.get("max_items", 3)
                return items[start : start + kwargs.get("max_items", 3)]

            global_report_path = Path(tmpdir) / "global_top5_selection_mock.json"
            global_report_path.write_text(
                json.dumps(
                    {
                        "selected_top5": [
                            {
                                "source_id": "g1",
                                "title": "OpenAI launches developer platform API",
                                "url": "https://openai.com/index/platform/",
                                "summary": "OpenAI platform API workflow for enterprise developers.",
                                "primary_category": "ai_product",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch("keysuri_live_source_smoke.fetch_feed_items", side_effect=_fetch):
                result = run_keysuri_live_source_smoke(
                    program_id=PROGRAM_KOREA,
                    max_items=5,
                    allow_network=True,
                    use_gemini=False,
                    out_dir=Path(tmpdir) / "output" / "keysuri_preview",
                    repo_root=_REPO,
                    global_selection_report_path=global_report_path,
                )

            debug_dir = Path(tmpdir) / "output" / "keysuri_preview" / "debug"
            korea_reports = list(debug_dir.glob("korea_top5_selection_*.json"))
            self.assertGreaterEqual(len(korea_reports), 1)
            report = json.loads(korea_reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report.get("duplicate_guard_status"), "applied")
            self.assertGreaterEqual(report.get("duplicate_detected_count", 0), 1)
            self.assertFalse(result.side_effects.get("called_gemini"))


if __name__ == "__main__":
    unittest.main()
