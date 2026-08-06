"""Global body_only reissue content integrity (no network, no send).

Covers the 2026-07-30 incident: runs 20260730_123602/_123814 published five
cards whose titles were "{source} 기반 AI·테크 신호 {rank}" with identical
generic bodies, while every gate reported pass and SMTP was accepted.
"""
from __future__ import annotations

import unittest

from keysuri_briefing_content_enricher import near_duplicate_key
from keysuri_service_full_run import (
    _reissue_clean_fallback_templates,
    _reissue_real_title,
    _repair_reissue_top5_from_live_selection,
    correlate_reissue_seeds,
    reissue_top5_content_issue_codes,
)

PROGRAM_GLOBAL = "keysuri_global_tech"


def _live_item(idx: int, *, title: str, source: str, news_id: str | None = None) -> dict:
    return {
        "rank": idx,
        "news_id": news_id or f"claim-live-src-{idx}",
        "title": title,
        "headline": title,
        "source_name": source,
        "source": source,
        "normalized_source": source.lower().replace(" ", "-"),
        "normalized_title": title.lower(),
        "canonical_url": f"https://example.invalid/{idx}",
        "url": f"https://example.invalid/{idx}",
        "source_ids": [f"live-src-{idx}"],
        "category": "market_signal",
        "confidence_label": "reported",
    }


def _english_live_items() -> list[dict]:
    specs = [
        ("Siobahn Day Grady Wants Everyone to Be AI Literate", "IEEE Spectrum"),
        ("Gemini API Managed Agents: 3.6 Flash, hooks, and more", "Google AI Blog"),
        ("Powerful Compute So Compact, Build AI Anywhere With Jetson", "NVIDIA Blog"),
        ("How GPT-5.6 fuses frontier intelligence with efficiency", "OpenAI News"),
        ("Zuckerberg predicts billions will have personal AI agents", "TechCrunch AI"),
    ]
    return [_live_item(i, title=t, source=s) for i, (t, s) in enumerate(specs, start=1)]


def _korean_model_items(live_items: list[dict]) -> list[dict]:
    out = []
    for idx, live in enumerate(live_items, start=1):
        item = dict(live)
        item["headline"] = f"제미나이 한국어 제목 {idx}"
        item["korean_title"] = f"제미나이 한국어 제목 {idx}"
        item["summary"] = f"「제미나이 한국어 제목 {idx}」 관련 공식 발표가 {idx}건 확인되었습니다."
        item["why_it_matters"] = f"해당 발표는 {idx}분기 투자 판단에 직접 영향을 줍니다."
        item["business_implication"] = f"주인님께서는 도입 비용을 {idx}순위로 점검하시면 됩니다."
        out.append(item)
    return out


_INCIDENT_SOURCES = (
    "IEEE Spectrum",
    "Google AI Blog",
    "NVIDIA Blog",
    "OpenAI News",
    "TechCrunch AI",
)

# The two template phrases the incident cards repeated verbatim across every
# card, quoted from _REISSUE_GENERIC_BODY_MARKERS.
_INCIDENT_GENERIC_SUMMARY = (
    "최신 발표를 바탕으로 AI·테크 업계에 영향을 줄 수 있는 변화로 선별했습니다."
)
_INCIDENT_GENERIC_WHY = (
    "플랫폼, 인프라, AI 활용 흐름에 영향을 줄 수 있어 주목할 필요가 있습니다."
)


def _snapshot_payload(items: list[dict]) -> dict:
    """Wrap items the way the run artifact stores a reissue model snapshot."""
    return {
        "program_id": PROGRAM_GLOBAL,
        "regen_generated_briefing_snapshot": {
            "program_id": PROGRAM_GLOBAL,
            "top_5_news": {"items": items},
        },
    }


def _incident_card(idx: int, *, headline: str, summary: str, why: str) -> dict:
    item = _live_item(idx, title=headline, source=_INCIDENT_SOURCES[idx - 1])
    item["headline"] = headline
    item["korean_title"] = headline
    item["summary"] = summary
    item["why_it_matters"] = why
    item["business_implication"] = (
        "주인님은 이 신호가 사업 운영, 파트너십, 기술 도입 우선순위에 주는 변화를 "
        "점검하면 좋겠습니다."
    )
    return item


def _incident_placeholder_and_generic_payload() -> dict:
    """Run 20260730_123814 shape: fabricated titles + fanned-out template prose."""
    items = [
        _incident_card(
            idx,
            headline=f"{_INCIDENT_SOURCES[idx - 1]} 기반 AI·테크 신호 {idx}",
            summary=_INCIDENT_GENERIC_SUMMARY,
            why=_INCIDENT_GENERIC_WHY,
        )
        for idx in range(1, 6)
    ]
    return _snapshot_payload(items)


def _incident_placeholder_only_payload() -> dict:
    """Run 20260730_123602 shape: fabricated titles, prose still individualised."""
    items = [
        _incident_card(
            idx,
            headline=f"{_INCIDENT_SOURCES[idx - 1]} 기반 AI·테크 신호 {idx}",
            summary=f"공식 발표가 {idx}건 확인되었고 세부 수치는 문서에 정리되어 있습니다.",
            why=f"도입 검토 단계에서 {idx}분기 예산 배분을 다시 볼 근거가 됩니다.",
        )
        for idx in range(1, 6)
    ]
    return _snapshot_payload(items)


def _last_known_good_payload() -> dict:
    """Run 20260730_123001 shape: real titles with article-specific prose."""
    specs = [
        ("제미나이 API가 관리형 에이전트와 훅을 공개했습니다", "관리형 에이전트"),
        ("엔비디아 젯슨이 소형 온디바이스 추론 보드를 확장했습니다", "젯슨 보드"),
        ("오픈AI가 GPT-5.6 효율 개선 결과를 공개했습니다", "GPT-5.6"),
        ("메타가 개인용 AI 에이전트 보급 전망을 제시했습니다", "개인용 에이전트"),
        ("IEEE가 AI 리터러시 교육 확대 방안을 발표했습니다", "AI 리터러시"),
    ]
    items = []
    for idx, (headline, hook) in enumerate(specs, start=1):
        items.append(
            _incident_card(
                idx,
                headline=headline,
                summary=f"「{headline}」 발표에서 {hook} 적용 범위가 구체적으로 제시되었습니다.",
                why=f"{hook} 도입 일정이 {idx}분기 기술 투자 판단을 직접 바꿉니다.",
            )
        )
    for item in items:
        item["business_implication"] = (
            f"주인님께서는 {item['headline'][:12]} 관련 예산을 우선 점검하시면 됩니다."
        )
    return _snapshot_payload(items)


class GlobalTitlePreservationTests(unittest.TestCase):
    def test_1_english_original_title_is_not_deleted_by_korean_gate(self) -> None:
        item = _live_item(1, title="How GPT-5.6 fuses frontier intelligence", source="OpenAI News")
        self.assertEqual(_reissue_real_title(item), "How GPT-5.6 fuses frontier intelligence")

    def test_12_source_rank_placeholder_is_never_generated(self) -> None:
        templates = _reissue_clean_fallback_templates(item=_live_item(1, title="", source="IEEE Spectrum"), rank=1)
        self.assertNotIn("headline", templates)
        for value in templates.values():
            self.assertNotIn("기반 AI·테크 신호", value)

    def test_fallback_templates_individualise_with_real_title_hook(self) -> None:
        templates = _reissue_clean_fallback_templates(
            item=_live_item(1, title="How GPT-5.6 fuses frontier intelligence", source="OpenAI News"),
            rank=1,
        )
        for value in templates.values():
            self.assertIn("「How GPT-5.6 fuses frontier intelligence」", value)
            self.assertNotIn("기반 AI·테크 신호", value)
            self.assertNotIn("최신 발표를 바탕으로 AI·테크 업계에 영향을 줄 수 있는 변화로 선별했습니다", value)
            self.assertNotIn("플랫폼, 인프라, AI 활용 흐름에 영향을 줄 수 있어", value)

    def test_13_real_original_title_survives_when_no_korean_headline(self) -> None:
        from keysuri_service_full_run import _normalize_reissue_visible_top5_item

        live = _english_live_items()
        item, _fields, fallback_used = _normalize_reissue_visible_top5_item(live[3], rank=4, visible_seed=None)
        self.assertEqual(item["headline"], "How GPT-5.6 fuses frontier intelligence with efficiency")
        self.assertEqual(item["title"], "How GPT-5.6 fuses frontier intelligence with efficiency")
        self.assertNotIn("기반 AI·테크 신호", item["headline"])
        # Prose still falls back without a Korean seed; the title must not.
        self.assertTrue(fallback_used)


class CorrelationTests(unittest.TestCase):
    def test_3_news_id_match(self) -> None:
        live = _english_live_items()
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=_korean_model_items(live))
        self.assertEqual(diag["reissue_correlation_methods"], ["news_id"] * 5)
        self.assertEqual(diag["reissue_correlation_matched_count"], 5)

    def test_4_canonical_url_match_when_news_id_differs(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        for i, b in enumerate(base):
            b["news_id"] = f"model-only-{i}"
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertEqual(diag["reissue_correlation_methods"], ["canonical_url"] * 5)

    def test_5_normalized_title_source_match(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        for i, b in enumerate(base):
            b["news_id"] = f"model-only-{i}"
            b.pop("canonical_url", None)
            b.pop("url", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertEqual(diag["reissue_correlation_methods"], ["title_source"] * 5)

    def test_6_explicit_prompt_index_match(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        for i, (l, b) in enumerate(zip(live, base)):
            l["prompt_index"] = i
            b["prompt_index"] = i
            b["news_id"] = f"model-only-{i}"
            b.pop("canonical_url", None)
            b.pop("url", None)
            b.pop("normalized_title", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertEqual(diag["reissue_correlation_matched_count"], 5)

    def test_7_ambiguous_key_is_not_guessed(self) -> None:
        """Two model outputs claiming one article: drop the key, never pick one."""
        live = _english_live_items()
        base = _korean_model_items(live)
        base[1]["news_id"] = base[0]["news_id"]
        for b in (base[0], base[1]):
            b.pop("canonical_url", None)
            b.pop("url", None)
            b.pop("normalized_title", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertIsNone(seeds[0])
        self.assertIn(1, diag["reissue_correlation_unmatched_ranks"])
        self.assertFalse(diag["reissue_correlation_positional_used"])

    def test_9_no_unconditional_positional_pairing(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)[:2]
        for i, b in enumerate(base):
            b["news_id"] = f"model-only-{i}"
            b.pop("canonical_url", None)
            b.pop("url", None)
            b.pop("normalized_title", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertFalse(diag["reissue_correlation_positional_used"])
        self.assertEqual(diag["reissue_correlation_matched_count"], 0)

    def test_10_positional_recovery_only_on_verified_identical_batch(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        for i, b in enumerate(base):
            b["news_id"] = f"model-only-{i}"
            b.pop("canonical_url", None)
            b.pop("url", None)
            b.pop("normalized_title", None)
            b.pop("normalized_source", None)
            b.pop("source_name", None)
            b.pop("source", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertTrue(diag["reissue_correlation_positional_guards_passed"])
        self.assertTrue(diag["reissue_correlation_positional_used"])

    def test_11_cross_article_binding_is_prevented(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        # Only article 3 is groundable; nothing else may borrow its prose.
        keep = base[2]
        for i, b in enumerate(base):
            if b is keep:
                continue
            b["news_id"] = f"model-only-{i}"
            b.pop("canonical_url", None)
            b.pop("url", None)
            b.pop("normalized_title", None)
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        bound = [i for i, s in enumerate(seeds) if s is not None]
        self.assertEqual(bound, [2])
        for i, seed in enumerate(seeds):
            if seed is not None:
                self.assertEqual(seed.get("news_id"), live[i]["news_id"])


class ContentGateTests(unittest.TestCase):
    def _placeholder_cards(self) -> list[dict]:
        out = []
        for i, src in enumerate(["IEEE Spectrum", "Google AI Blog", "NVIDIA Blog", "OpenAI News", "TechCrunch AI"], start=1):
            out.append({
                "headline": f"{src} 기반 AI·테크 신호 {i}",
                "canonical_url": f"https://example.invalid/{i}",
                "summary": f"{src}의 최신 발표를 바탕으로 AI·테크 업계에 영향을 줄 수 있는 변화로 선별했습니다.",
                "why_it_matters": "해당 이슈는 플랫폼, 인프라, AI 활용 흐름에 영향을 줄 수 있어 주요 뉴스로 정리했습니다.",
                "business_implication": "주인님은 이 신호가 사업 운영, 파트너십, 기술 도입 우선순위에 주는 변화를 점검하면 좋겠습니다.",
            })
        return out

    def test_12_placeholder_title_blocked(self) -> None:
        self.assertIn("reissue_top5_placeholder_title", reissue_top5_content_issue_codes(self._placeholder_cards()))

    def test_14_generic_body_repeated_across_cards_blocked(self) -> None:
        self.assertIn("reissue_top5_shared_generic_body", reissue_top5_content_issue_codes(self._placeholder_cards()))

    def test_15_two_cards_sharing_one_helper_sentence_is_allowed(self) -> None:
        live = _english_live_items()
        cards = _korean_model_items(live)
        for i in (0, 1):
            cards[i]["what_happened"] = (
                f"IEEE Spectrum 공개 요약에 따르면 「{cards[i]['korean_title']}」 관련 변화가 보고되었습니다."
            )
        self.assertEqual(reissue_top5_content_issue_codes(cards), [])

    def test_16_known_good_business_implications_pass(self) -> None:
        cards = _korean_model_items(_english_live_items())
        self.assertEqual(reissue_top5_content_issue_codes(cards), [])

    def test_18_duplicate_sentence_within_card_blocked(self) -> None:
        cards = _korean_model_items(_english_live_items())
        cards[0]["business_implication"] = (
            "주인님은 이 신호가 사업 운영 파트너십 기술 도입 우선순위에 주는 변화를 점검하면 좋겠습니다. "
            "주인님은 이 신호가 사업 운영, 파트너십, 기술 도입 우선순위에 주는 변화를 점검하면 좋겠습니다."
        )
        self.assertIn("reissue_top5_duplicate_sentence", reissue_top5_content_issue_codes(cards))

    def test_19_broken_particle_join_blocked(self) -> None:
        cards = _korean_model_items(_english_live_items())
        cards[0]["business_implication"] = "점검하면 좋겠습니다. 은 이 신호가 사업 운영에 영향을 줍니다."
        self.assertIn("reissue_top5_broken_particle_join", reissue_top5_content_issue_codes(cards))

    def test_duplicate_titles_blocked(self) -> None:
        cards = _korean_model_items(_english_live_items())
        cards[1]["headline"] = cards[0]["headline"]
        cards[1]["korean_title"] = cards[0]["korean_title"]
        self.assertIn("reissue_top5_duplicate_titles", reissue_top5_content_issue_codes(cards))

    def test_source_url_required_only_in_composed_context(self) -> None:
        cards = _korean_model_items(_english_live_items())
        for c in cards:
            c.pop("canonical_url", None)
            c.pop("url", None)
        self.assertEqual(reissue_top5_content_issue_codes(cards), [])
        self.assertIn(
            "reissue_top5_source_url_missing",
            reissue_top5_content_issue_codes(cards, require_source_url=True),
        )

    def test_17_comma_only_near_duplicate_is_detected(self) -> None:
        a = "해당 이슈는 플랫폼 인프라 AI 활용 흐름에 영향을 줄 수 있습니다"
        b = "해당 이슈는 플랫폼, 인프라, AI 활용 흐름에 영향을 줄 수 있습니다."
        self.assertEqual(near_duplicate_key(a), near_duplicate_key(b))


class HoldAndSmtpTests(unittest.TestCase):
    def test_8_partial_generation_holds_without_generic_fill(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)[:2]
        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": base}},
            prompt_input={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": live}},
            program_id=PROGRAM_GLOBAL,
            parent={},
        )
        self.assertIn(
            err,
            ("reissue_top5_content_integrity_hold", "reissue_top5_live_repair_validation_failed"),
        )
        self.assertIsNone(repaired_prompt)
        self.assertIsNone(repaired_briefing)

    def test_20_21_hold_produces_no_publishable_payload(self) -> None:
        """No briefing means no owner-review artifact and no SMTP of any kind."""
        live = _english_live_items()
        for item in live:
            for key in ("title", "headline", "korean_title", "original_title", "normalized_title"):
                item[key] = ""
        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": _korean_model_items(live)[:1]}},
            prompt_input={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": live}},
            program_id=PROGRAM_GLOBAL,
            parent={},
        )
        self.assertIsNotNone(err)
        self.assertIsNone(repaired_briefing)
        self.assertTrue(fields.get("reissue_top5_content_issue_codes"))

    def test_15_model_success_with_mapping_failure_is_not_hidden(self) -> None:
        live = _english_live_items()
        base = _korean_model_items(live)
        for i, b in enumerate(base):
            b["news_id"] = "collide"
            b["canonical_url"] = "https://example.invalid/collide"
            b["normalized_title"] = "collide"
        _p, _b, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": base}},
            prompt_input={"program_id": PROGRAM_GLOBAL, "top_5_news": {"items": live}},
            program_id=PROGRAM_GLOBAL,
            parent={},
        )
        self.assertIsNotNone(err)
        self.assertIsNone(_b)


class IncidentShapeRegressionTests(unittest.TestCase):
    """Regression on the 2026-07-30 incident *shape*, rebuilt in-repo.

    The original assertions replayed artifacts from an agent scratch directory
    outside the repository. That directory is gone, so the checks silently
    skipped and the incident gate went unproven on every run. The shapes below
    are rebuilt from the documented incident (module docstring) and from the
    artifact field the reissue path actually reads,
    ``regen_generated_briefing_snapshot.top_5_news.items``, so the same gate
    runs deterministically on any machine.
    """

    @staticmethod
    def _snapshot_items(payload: dict) -> list:
        """Read items exactly where the reissue path reads them."""
        snap = payload.get("regen_generated_briefing_snapshot") or {}
        return ((snap.get("top_5_news") or {}).get("items")) or []

    def test_22_placeholder_titles_with_template_bodies_hold(self) -> None:
        """Run 20260730_123814 shape: placeholder titles + fanned-out template prose."""
        items = self._snapshot_items(_incident_placeholder_and_generic_payload())
        codes = reissue_top5_content_issue_codes(items)
        self.assertIn("reissue_top5_placeholder_title", codes)
        self.assertIn("reissue_top5_shared_generic_body", codes)

    def test_23_placeholder_titles_alone_hold(self) -> None:
        """Run 20260730_123602 shape: placeholder titles, individualised prose."""
        items = self._snapshot_items(_incident_placeholder_only_payload())
        codes = reissue_top5_content_issue_codes(items)
        self.assertIn("reissue_top5_placeholder_title", codes)

    def test_24_last_known_good_shape_passes(self) -> None:
        """Run 20260730_123001 shape: real titles, article-specific prose."""
        items = self._snapshot_items(_last_known_good_payload())
        self.assertEqual(reissue_top5_content_issue_codes(items), [])
        for it in items:
            title = str(it.get("headline") or "")
            self.assertTrue(title)
            self.assertNotIn("기반 AI·테크 신호", title)

    def test_placeholder_shape_differs_from_good_shape_only_by_content(self) -> None:
        """Guard the fixtures themselves: same structure, opposite verdict."""
        bad = self._snapshot_items(_incident_placeholder_and_generic_payload())
        good = self._snapshot_items(_last_known_good_payload())
        self.assertEqual(len(bad), len(good))
        self.assertEqual(sorted(bad[0].keys()), sorted(good[0].keys()))
        self.assertTrue(reissue_top5_content_issue_codes(bad))
        self.assertFalse(reissue_top5_content_issue_codes(good))


if __name__ == "__main__":
    unittest.main()
