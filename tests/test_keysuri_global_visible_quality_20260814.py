"""Global visible-quality regression — 2026-08-14 12:30 KST production incident.

Run ``20260814_123001_keysuri_global_tech_089c413b`` (revision
``genie-blog-run-00295-8xl`` @ ``260bfc0``) recorded ``validation_result="pass"``
with ``issue_codes=[]`` and delivered an owner-review email whose visible surface
carried a mid-quote subject, raw English source prose, source-pack scaffolding,
a semantically truncated feed excerpt, a category label contradicting the item's
own evidence, a mis-agreeing Korean particle, one padding template repeated
across all five TOP5 items, and a deep dive that restated ``opening_lead``.

The fixture in ``tests/fixtures/keysuri_global_20260814/`` is derived from the
production artifact, not synthesized. Near-neighbour controls in
``ValidGlobalNearNeighbourTests`` exist so the new gates cannot be tightened
into blocking legitimate mixed-language editorial copy.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from keysuri_briefing_content_quality import validate_global_post_render_visible_quality
from keysuri_briefing_content_enricher import _natural_korean_subject_phrase
from keysuri_email_identity import _shorten_core, build_keysuri_editorial_subject
from keysuri_global_signal_scoring import classify_global_tech_category
from keysuri_global_visible_surface import (
    GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH,
    GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED,
    GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
    GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT,
    GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED,
    GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL,
    GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED,
    GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED,
    GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED,
    attach_korean_subject_particle,
    balance_quote_marks,
    deep_dive_duplication_ratio,
    evaluate_global_visible_surface,
    internal_template_leak_hits,
    korean_particle_defects,
    raw_english_prose_hits,
    repeated_skeleton_hits,
    semantic_truncation_hits,
    source_excerpt_is_clipped,
    title_integrity_issues,
)
from keysuri_visible_text import contains_dangling_quoted_title_fragment

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent
    / "fixtures"
    / "keysuri_global_20260814"
    / "production_visible_surface.json"
)

PRODUCTION_RUN_ID = "20260814_123001_keysuri_global_tech_089c413b"
PRODUCTION_SUBJECT = "[운영자 검토] OpenAI introduces ‘Ultrafast: 8월 14일 글로벌 테크 브리핑"


def load_fixture() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _as_html(*blocks: str) -> str:
    body = "".join(f"<p>{block}</p>" for block in blocks if block)
    return f"<html><body>{body}</body></html>"


class ProductionFixtureIntegrityTests(unittest.TestCase):
    """The frozen evidence must keep the exact production defects."""

    def setUp(self) -> None:
        self.fixture = load_fixture()

    def test_fixture_is_the_production_run(self) -> None:
        provenance = self.fixture["_provenance"]
        self.assertEqual(provenance["run_id"], PRODUCTION_RUN_ID)
        self.assertEqual(provenance["program_id"], "keysuri_global_tech")
        self.assertEqual(provenance["trigger_source"], "scheduled_service_full_run")
        self.assertEqual(
            provenance["commit_sha"], "260bfc00134950973e49cd77039d319e82b2677f"
        )

    def test_fixture_records_that_production_passed(self) -> None:
        provenance = self.fixture["_provenance"]
        self.assertEqual(provenance["production_validation_result"], "pass")
        self.assertEqual(provenance["production_visible_text_quality_status"], "pass")
        self.assertEqual(provenance["production_issue_codes"], [])

    def test_fixture_preserves_every_visible_defect(self) -> None:
        fixture = self.fixture
        items = fixture["top_5_items"]
        self.assertEqual(fixture["owner_email_subject"], PRODUCTION_SUBJECT)
        self.assertEqual(fixture["subject_top_headline"], "OpenAI introduces ‘Ultrafast")
        self.assertIn("OpenAI is launching a preview", items[0]["what_happened"])
        self.assertIn("Public tech source (TechCrunch AI) published:", items[0]["why_now"])
        self.assertIn(
            "AI/software/platform shifts may change vendor shortlists",
            items[0]["business_implication"],
        )
        self.assertIn("We have moved from an era in which companies.", items[1]["what_happened"])
        self.assertIn("정책·규제·자본·공급망가 실제", items[1]["business_implication"])
        self.assertEqual(items[2]["category"], "hardware_device_display")
        self.assertEqual(items[2]["category_label_ko"], "하드웨어·디바이스·디스플레이")
        self.assertEqual(items[3]["category"], "hardware_device_display")
        self.assertIn("「OpenAI introduces ‘Ultrafast」", items[0]["why_it_matters"])
        self.assertIn(fixture["opening_lead"][:60], fixture["deep_dive"]["body"])


class ProductionFixtureBlocksTests(unittest.TestCase):
    """Phase 15 — the exact 2026-08-14 surface must now BLOCK."""

    def setUp(self) -> None:
        self.fixture = load_fixture()
        self.result = evaluate_global_visible_surface(
            subject=self.fixture["owner_email_subject"],
            items=self.fixture["top_5_items"],
            deep_dive=self.fixture["deep_dive"],
            opening_lead=self.fixture["opening_lead"],
        )

    def test_overall_verdict_is_block(self) -> None:
        self.assertFalse(self.result["ok"])
        self.assertTrue(self.result["blocked"])

    def test_broken_quote_subject_blocks(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED, self.result["block_issue_codes"]
        )

    def test_raw_english_source_prose_blocks(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED, self.result["block_issue_codes"]
        )

    def test_internal_source_template_phrase_blocks(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
            self.result["block_issue_codes"],
        )

    def test_truncated_nvidia_excerpt_is_detected(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED, self.result["block_issue_codes"]
        )
        sections = {
            f["section"]
            for f in self.result["findings"]
            if f["issue_code"] == GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED
        }
        self.assertEqual(sections, {"top5[2].what_happened"})

    def test_repeated_generic_filler_is_detected(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED, self.result["block_issue_codes"]
        )
        hits = repeated_skeleton_hits(self.fixture["top_5_items"])
        self.assertTrue(hits)
        self.assertEqual(hits[0]["ranks"], [1, 2, 3, 4, 5])

    def test_deep_dive_duplication_is_detected(self) -> None:
        self.assertIn(
            GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED,
            self.result["block_issue_codes"],
        )
        self.assertGreaterEqual(
            self.result["diagnostics"]["deep_dive_duplication_ratio"], 0.5
        )

    def test_wrong_category_mapping_is_detected(self) -> None:
        self.assertIn(GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH, self.result["issue_codes"])
        mismatches = self.result["diagnostics"]["category_grounding_mismatches"]
        by_rank = {m["rank"]: m for m in mismatches}
        self.assertIn(3, by_rank)
        self.assertEqual(by_rank[3]["rendered_category"], "hardware_device_display")
        self.assertEqual(by_rank[3]["evidence_category"], "ai_software_platform")

    def test_broken_korean_morphology_is_detected(self) -> None:
        self.assertIn(GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT, self.result["issue_codes"])
        defects = korean_particle_defects(
            self.fixture["top_5_items"][1]["business_implication"]
        )
        self.assertEqual(defects[0]["stem"], "망")
        self.assertEqual(defects[0]["particle"], "가")
        self.assertEqual(defects[0]["expected"], "이")

    def test_dangling_quoted_title_walker_now_flags_the_hook(self) -> None:
        self.assertTrue(
            contains_dangling_quoted_title_fragment("「OpenAI introduces ‘Ultrafast」 확인 포인트는")
        )


class ProductionFixtureFinalGateTests(unittest.TestCase):
    """Phase 14 — the gate applied to the FINAL rendered visible surface."""

    def setUp(self) -> None:
        self.fixture = load_fixture()

    def _render(self) -> str:
        blocks = [self.fixture["opening_lead"]]
        for item in self.fixture["top_5_items"]:
            blocks.append(item["headline"])
            for field in ("what_happened", "why_now", "owner_angle", "business_implication"):
                blocks.append(item[field])
        blocks.append(self.fixture["deep_dive"]["body"])
        return _as_html(*blocks)

    def test_post_render_qa_blocks_the_production_email(self) -> None:
        result = validate_global_post_render_visible_quality(
            self._render(),
            briefing_items=self.fixture["top_5_items"],
            subject=self.fixture["owner_email_subject"],
            deep_dive=self.fixture["deep_dive"],
            opening_lead=self.fixture["opening_lead"],
        )
        self.assertFalse(result.ok)
        codes = {issue.code for issue in result.issues}
        for expected in (
            GLOBAL_VISIBLE_SUBJECT_INTEGRITY_BLOCKED,
            GLOBAL_VISIBLE_INTERNAL_TEMPLATE_LEAK_BLOCKED,
            GLOBAL_VISIBLE_RAW_ENGLISH_PROSE_BLOCKED,
            GLOBAL_VISIBLE_SEMANTIC_TRUNCATION_BLOCKED,
            GLOBAL_VISIBLE_REPEATED_SKELETON_BLOCKED,
            GLOBAL_VISIBLE_DEEP_DIVE_DUPLICATION_BLOCKED,
        ):
            self.assertIn(expected, codes)

    def test_review_severity_findings_do_not_appear_as_blocking_issues(self) -> None:
        result = validate_global_post_render_visible_quality(
            self._render(),
            briefing_items=self.fixture["top_5_items"],
            subject=self.fixture["owner_email_subject"],
            deep_dive=self.fixture["deep_dive"],
            opening_lead=self.fixture["opening_lead"],
        )
        codes = {issue.code for issue in result.issues}
        self.assertNotIn(GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH, codes)
        # A Hangul particle disagreement is now BLOCK, not REVIEW: it is
        # deterministic, it is corrected automatically upstream, and anything
        # still present here is simply wrong Korean. "흐름와" and "후속를"
        # reached the owner's Gmail on 2026-08-29 while this was review-only.
        self.assertIn(GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT, codes)
        review_codes = {
            f["issue_code"] for f in result.diagnostics["visible_surface_review_findings"]
        }
        self.assertIn(GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH, review_codes)
        self.assertNotIn(GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT, review_codes)

    def test_gate_reads_the_subject_even_though_it_is_outside_the_html(self) -> None:
        clean_html = _as_html("주인님, 오늘 신호를 정리했습니다.")
        blocked = validate_global_post_render_visible_quality(
            clean_html, briefing_items=[], subject=PRODUCTION_SUBJECT
        )
        self.assertFalse(blocked.ok)
        allowed = validate_global_post_render_visible_quality(
            clean_html,
            briefing_items=[],
            subject="[운영자 검토] OpenAI, ‘Ultrafast’ 모드 공개: 8월 14일 글로벌 테크 브리핑",
        )
        self.assertTrue(allowed.ok, [i.code for i in allowed.issues])


class TitleIntegrityTests(unittest.TestCase):
    """Phase 5."""

    def test_production_subject_fails(self) -> None:
        issues = title_integrity_issues(PRODUCTION_SUBJECT)
        self.assertTrue(any(i.startswith("unbalanced_quote:‘’") for i in issues))

    def test_each_paired_delimiter_family_is_checked(self) -> None:
        for broken in (
            "OpenAI introduces ‘Ultrafast",
            "Google says “AI is the platform",
            "삼성전자 「신형 반도체 공개",
            "엔비디아 『AI 팩토리",
            'Nvidia said "we have moved',
        ):
            with self.subTest(broken=broken):
                self.assertTrue(title_integrity_issues(broken), broken)

    def test_dangling_punctuation_and_particles_fail(self) -> None:
        self.assertIn("dangling_punctuation", title_integrity_issues("OpenAI introduces,"))
        self.assertIn(
            "dangling_korean_particle", title_integrity_issues("삼성전자와 SK하이닉스의")
        )

    def test_legitimate_titles_pass(self) -> None:
        for good in (
            "OpenAI introduces ‘Ultrafast,’ a new mode that makes GPT-5.6 Sol work at 14x the speed",
            "The builder’s guide to GPT-5.6",
            "Apple’s M5 Pro doesn't ship until 2027",
            "NVIDIA AI Factory Compute Is Becoming an Investable Asset Class",
            "삼성전자, ‘나를 아는 AI’ 전략 공개",
            "8월 14일 글로벌 테크 브리핑",
            'Google says "Sheets canvas" is generally available',
        ):
            with self.subTest(good=good):
                self.assertEqual(title_integrity_issues(good), [], good)

    def test_balance_quote_marks_drops_only_the_orphan(self) -> None:
        self.assertEqual(
            balance_quote_marks("OpenAI introduces ‘Ultrafast"), "OpenAI introduces Ultrafast"
        )
        self.assertEqual(
            balance_quote_marks("OpenAI introduces ‘Ultrafast’ mode"),
            "OpenAI introduces ‘Ultrafast’ mode",
        )
        self.assertEqual(balance_quote_marks("The builder’s guide"), "The builder’s guide")


class SubjectAndHookRepairTests(unittest.TestCase):
    """The two deterministic shorteners that produced the broken quote."""

    TITLE = "OpenAI introduces ‘Ultrafast,’ a new mode that makes GPT-5.6 Sol work at 14x the speed"

    def test_shorten_core_no_longer_orphans_a_quote(self) -> None:
        core = _shorten_core(self.TITLE, max_len=55)
        self.assertEqual(core, "OpenAI introduces Ultrafast")
        self.assertEqual(title_integrity_issues(core), [])

    def test_subject_phrase_hook_no_longer_orphans_a_quote(self) -> None:
        hook = _natural_korean_subject_phrase(self.TITLE)
        self.assertEqual(hook, "OpenAI introduces Ultrafast")
        self.assertFalse(contains_dangling_quoted_title_fragment(f"「{hook}」"))

    def test_end_to_end_subject_is_clean(self) -> None:
        briefing = {
            "top_5_news": {"items": [{"rank": 1, "headline": self.TITLE}]},
        }
        subject = build_keysuri_editorial_subject(
            "keysuri_global_tech",
            generated_briefing=briefing,
            run_id="20260814_123001_keysuri_global_tech_089c413b",
        )
        self.assertEqual(title_integrity_issues(subject), [], subject)
        self.assertNotIn("‘Ultrafast:", subject)


class InternalTemplateLeakTests(unittest.TestCase):
    """Phase 7."""

    def test_production_phrase_and_near_neighbours_are_caught(self) -> None:
        for leak in (
            "Public tech source (TechCrunch AI) published: OpenAI introduces Ultrafast",
            "Public tech source (NVIDIA Blog) published: NVIDIA AI Factory Compute",
            "source summary: NVIDIA announced financing platforms",
            "public summary: Sheets canvas",
            "TechCrunch published: a new mode",
            "Live source smoke — owner-review only; not customer-final.",
        ):
            with self.subTest(leak=leak):
                self.assertTrue(internal_template_leak_hits(leak), leak)

    def test_ordinary_prose_is_not_caught(self) -> None:
        for good in (
            "TechCrunch 공개 요약에 따르면 관련 변화가 보고되었습니다.",
            "엔비디아가 발표한 자본 조달 구조를 먼저 보겠습니다.",
            "OpenAI published a preview of Ultrafast mode this week.",
            "출처는 TechCrunch AI 기사입니다.",
        ):
            with self.subTest(good=good):
                self.assertEqual(internal_template_leak_hits(good), [], good)


class LanguageSurfaceTests(unittest.TestCase):
    """Phase 6."""

    def test_raw_english_source_sentences_are_caught(self) -> None:
        for leak in (
            "OpenAI is launching a preview of a sped up version of its latest most "
            "powerful model in an effort to court enterprise users.",
            "We announced partnerships with Apollo, BlackRock, Blackstone, Brookfield, "
            "Goldman Sachs and KKR to establish independent financing platforms.",
            "Sheets canvas turns data into interactive dashboards custom study trackers "
            "seating charts and more all with a simple prompt.",
            "AI/software/platform shifts may change vendor shortlists and workflow lock-in.",
            "Device/display shifts may change edge deployment and consumer-tech spillover.",
            "Policy/capital/supply-chain moves may alter market access and timing.",
        ):
            with self.subTest(leak=leak[:50]):
                self.assertTrue(raw_english_prose_hits(leak), leak)

    def test_legitimate_mixed_language_prose_passes(self) -> None:
        for good in (
            "OpenAI가 GPT-5.6 Sol의 Ultrafast 모드를 공개했습니다.",
            "「OpenAI introduces ‘Ultrafast,’ a new mode that makes GPT-5.6 Sol work at "
            "14x the speed」 확인 포인트는 API 공개 일정입니다.",
            "NVIDIA, Apollo, BlackRock, Blackstone, Brookfield, Goldman Sachs, KKR이 "
            "참여했습니다.",
            "Google Sheets canvas와 Gemini 3 Flash Preview를 함께 보겠습니다.",
            "자세한 내용은 https://techcrunch.com/2026/08/13/openai-introduces-ultrafast/ "
            "에서 확인할 수 있습니다.",
            "삼성전자와 SK하이닉스, TSMC, Intel Foundry Services 동향을 정리했습니다.",
        ):
            with self.subTest(good=good[:50]):
                self.assertEqual(raw_english_prose_hits(good), [], good)


class TruncationTests(unittest.TestCase):
    """Phase 9."""

    NVIDIA_EXCERPT = (
        "We announced partnerships with Apollo, BlackRock, Blackstone, Brookfield, "
        "Goldman Sachs and KKR to establish independent financing platforms designed "
        "to mobilize over $500 billion of third-party capital to support the buildout "
        "of AI infrastructure over time. This is a major milestone for NVIDIA and the "
        "AI industry. We have moved from an era in which companies"
    )

    def test_production_excerpt_is_recognised_as_clipped(self) -> None:
        self.assertTrue(source_excerpt_is_clipped(self.NVIDIA_EXCERPT))

    def test_visible_text_reproducing_the_clipped_tail_is_flagged(self) -> None:
        visible = self.NVIDIA_EXCERPT + "."
        signals = {hit["signal"] for hit in semantic_truncation_hits(visible, source_excerpt=self.NVIDIA_EXCERPT)}
        self.assertIn("source_clipped_tail_reproduced", signals)
        self.assertIn("dangling_relative_clause", signals)

    def test_unpunctuated_single_sentence_summary_is_not_truncation(self) -> None:
        excerpt = "Company has also published a 300-page whitepaper to support the project"
        self.assertFalse(source_excerpt_is_clipped(excerpt))
        self.assertEqual(semantic_truncation_hits(excerpt + ".", source_excerpt=excerpt), [])

    def test_short_complete_sentences_are_not_blocked(self) -> None:
        for good in (
            "엔비디아가 자본 조달 구조를 공개했습니다.",
            "The preview is available today.",
            "Sheets canvas turns data into dashboards with a simple prompt.",
            "출시 일정은 아직 공개되지 않았습니다.",
        ):
            with self.subTest(good=good):
                self.assertEqual(semantic_truncation_hits(good), [], good)


class KoreanAssemblyTests(unittest.TestCase):
    """Phase 10."""

    def test_particle_agrees_with_jongseong(self) -> None:
        self.assertEqual(attach_korean_subject_particle("정책·규제·자본·공급망"), "정책·규제·자본·공급망이")
        self.assertEqual(attach_korean_subject_particle("하드웨어·디바이스·디스플레이"), "하드웨어·디바이스·디스플레이가")
        self.assertEqual(attach_korean_subject_particle("보안·클라우드·데이터센터"), "보안·클라우드·데이터센터가")
        self.assertEqual(attach_korean_subject_particle("AI·소프트웨어·플랫폼"), "AI·소프트웨어·플랫폼이")

    def test_every_global_category_label_assembles_cleanly(self) -> None:
        from keysuri_global_signal_scoring import CATEGORY_KO_LABELS

        for label in CATEGORY_KO_LABELS.values():
            sentence = (
                f"{attach_korean_subject_particle(label)}"
                " 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다."
            )
            with self.subTest(label=label):
                self.assertEqual(korean_particle_defects(sentence), [], sentence)

    def test_production_defect_is_reported(self) -> None:
        broken = "정책·규제·자본·공급망가 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다."
        self.assertTrue(korean_particle_defects(broken))

    def test_enricher_decision_padding_now_agrees(self) -> None:
        from keysuri_briefing_content_enricher import _item_specific_checkpoint

        sentence = _item_specific_checkpoint(
            {"primary_category": "policy_regulation_capital_supplychain"},
            {
                "primary_category": "policy_regulation_capital_supplychain",
                "category_label_ko": "정책·규제·자본·공급망",
                "statement": (
                    "NVIDIA AI Factory Compute Is Becoming an Investable Asset Class "
                    "and a new financing standard for the whole industry"
                ),
            },
            style="decision",
        )
        self.assertNotIn("공급망가", sentence)
        self.assertEqual(korean_particle_defects(sentence), [], sentence)


class CategoryGroundingTests(unittest.TestCase):
    """Phase 8 — structural, not headline-specific."""

    def test_canonical_feed_default_passes_through(self) -> None:
        primary, _secondary, _confidence, reason = classify_global_tech_category(
            "Bring your spreadsheet data to life with Sheets canvas",
            feed_default="ai_software_platform",
        )
        self.assertEqual(primary, "ai_software_platform")
        self.assertEqual(reason, "feed_default_canonical:ai_software_platform")

    def test_startup_item_does_not_become_hardware(self) -> None:
        primary, _s, _c, _r = classify_global_tech_category(
            "Investors sue Selena Gomez alleging fraud tied to her mental health startup",
            feed_default="startup",
        )
        self.assertEqual(primary, "policy_regulation_capital_supplychain")

    def test_unknown_alias_no_longer_defaults_to_hardware(self) -> None:
        primary, _s, _c, _r = classify_global_tech_category(
            "Some item with no category keywords at all",
            feed_default="totally_unknown_alias",
        )
        self.assertNotEqual(primary, "hardware_device_display")
        self.assertEqual(primary, "ai_software_platform")

    def test_genuine_hardware_default_still_maps_to_hardware(self) -> None:
        primary, _s, _c, _r = classify_global_tech_category(
            "Some item with no category keywords at all",
            feed_default="hardware_device_display",
        )
        self.assertEqual(primary, "hardware_device_display")

    def test_incoherent_item_is_reported(self) -> None:
        result = evaluate_global_visible_surface(
            items=[
                {
                    "rank": 1,
                    "primary_category": "hardware_device_display",
                    "category_label_ko": "하드웨어·디바이스·디스플레이",
                    "business_implication": (
                        "AI/software/platform shifts may change vendor shortlists."
                    ),
                }
            ]
        )
        self.assertIn(GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH, result["issue_codes"])

    def test_coherent_item_is_not_reported(self) -> None:
        result = evaluate_global_visible_surface(
            items=[
                {
                    "rank": 1,
                    "primary_category": "ai_software_platform",
                    "category_label_ko": "AI·소프트웨어·플랫폼",
                    "why_it_matters": "AI·소프트웨어·플랫폼 확인 포인트는 API 공개 일정입니다.",
                }
            ]
        )
        self.assertNotIn(GLOBAL_VISIBLE_CATEGORY_GROUNDING_MISMATCH, result["issue_codes"])


class RepetitionAndDeepDiveTests(unittest.TestCase):
    """Phases 11 and 12."""

    def test_two_items_sharing_a_skeleton_do_not_block(self) -> None:
        items = [
            {"rank": 1, "owner_angle": "「A」가 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다."},
            {"rank": 2, "owner_angle": "「B」가 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다."},
        ]
        self.assertEqual(repeated_skeleton_hits(items), [])

    def test_three_items_sharing_a_skeleton_block(self) -> None:
        items = [
            {"rank": rank, "owner_angle": f"「{name}」가 실제 비용·계약·일정 변화로 이어지는지가 판단 기준입니다."}
            for rank, name in ((1, "A"), (2, "B"), (3, "C"))
        ]
        hits = repeated_skeleton_hits(items)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["ranks"], [1, 2, 3])

    def test_distinct_editorial_sentences_do_not_repeat(self) -> None:
        items = [
            {"rank": 1, "owner_angle": "엔비디아의 자본 구조 변화가 국내 협력사 계약 일정에 미칠 영향을 봅니다."},
            {"rank": 2, "owner_angle": "구글 시트 캔버스는 사내 리포팅 도구 교체 시점을 앞당길 수 있습니다."},
            {"rank": 3, "owner_angle": "라이트매터 표준화는 데이터센터 광통신 조달 단가를 흔들 수 있습니다."},
        ]
        self.assertEqual(repeated_skeleton_hits(items), [])

    def test_deep_dive_copying_the_lead_is_flagged(self) -> None:
        lead = "주인님, 오늘 글로벌 테크 시장은 소프트웨어의 속도 혁신이 포착되었습니다."
        ratio, matched = deep_dive_duplication_ratio(lead, [lead])
        self.assertEqual(ratio, 1.0)
        self.assertTrue(matched)

    def test_genuine_synthesis_is_not_flagged(self) -> None:
        lead = "주인님, 오늘 글로벌 테크 시장은 소프트웨어의 속도 혁신이 포착되었습니다."
        deep = (
            "속도 혁신과 자본 결집은 서로 다른 시간축 위에 있습니다. "
            "전자는 분기 단위 도입 결정을, 후자는 수년 단위 인프라 계약을 움직입니다. "
            "두 축이 만나는 지점은 전력 조달 단가입니다."
        )
        ratio, _matched = deep_dive_duplication_ratio(deep, [lead])
        self.assertLess(ratio, 0.5)

    def test_repeated_judgment_label_is_reported_but_does_not_block(self) -> None:
        """관찰/기회/경계 is a closed taxonomy — a quiet day may legitimately
        repeat one label, so this is REVIEW severity, not BLOCK."""
        plain = "키수리 판단 관찰 " * 5
        result = evaluate_global_visible_surface(items=[], plain_text=plain)
        self.assertIn(GLOBAL_VISIBLE_REPEATED_LOW_INFORMATION_LABEL, result["issue_codes"])
        self.assertEqual(result["block_issue_codes"], [])
        self.assertTrue(result["ok"])

    def test_varied_judgment_labels_are_not_flagged(self) -> None:
        plain = "키수리 판단 관찰 키수리 판단 기회 키수리 판단 경계"
        result = evaluate_global_visible_surface(items=[], plain_text=plain)
        self.assertEqual(result["issue_codes"], [])


class ValidGlobalNearNeighbourTests(unittest.TestCase):
    """Phase 19 — a well-formed Global briefing must still PASS."""

    def _valid_briefing(self) -> dict:
        return {
            "subject": "[운영자 검토] OpenAI, ‘Ultrafast’ 모드 공개: 8월 14일 글로벌 테크 브리핑",
            "opening_lead": (
                "주인님, 오늘 글로벌 테크는 모델 추론 속도와 인프라 자본이라는 두 축에서 "
                "움직였습니다."
            ),
            "items": [
                {
                    "rank": 1,
                    "headline": "OpenAI introduces ‘Ultrafast,’ a new mode that makes GPT-5.6 Sol work at 14x the speed",
                    "primary_category": "ai_software_platform",
                    "category_label_ko": "AI·소프트웨어·플랫폼",
                    "summary": "OpenAI is launching a preview of a sped up version of its model.",
                    "what_happened": "OpenAI가 GPT-5.6 Sol의 추론 속도를 14배로 높인 Ultrafast 프리뷰를 열었습니다.",
                    "why_now": "엔터프라이즈 도입 문턱을 낮추려는 가격·성능 조정이 함께 왔습니다.",
                    "owner_angle": "사내 워크플로 전환 시점을 앞당길지 판단할 근거가 생겼습니다.",
                    "next_watch": "API 공개 일정; 엔터프라이즈 가격표",
                },
                {
                    "rank": 2,
                    "headline": "NVIDIA AI Factory Compute Is Becoming an Investable Asset Class",
                    "primary_category": "policy_regulation_capital_supplychain",
                    "category_label_ko": "정책·규제·자본·공급망",
                    "summary": "NVIDIA announced financing platforms with Apollo and BlackRock.",
                    "what_happened": "엔비디아가 5,000억 달러 규모 인프라 금융 플랫폼을 발표했습니다.",
                    "why_now": "컴퓨트를 자산군으로 재정의하려는 첫 대규모 시도입니다.",
                    "owner_angle": "국내 협력사 계약 구조에도 장기 조달 조건이 따라붙을 수 있습니다.",
                    "next_watch": "펀드 결성 일정; 전력 조달 계약",
                },
                {
                    "rank": 3,
                    "headline": "Bring your spreadsheet data to life with Sheets canvas",
                    "primary_category": "ai_software_platform",
                    "category_label_ko": "AI·소프트웨어·플랫폼",
                    "summary": "Sheets canvas turns data into dashboards with a simple prompt.",
                    "what_happened": "구글이 시트 데이터를 대화형 대시보드로 바꾸는 캔버스를 열었습니다.",
                    "why_now": "사내 리포팅 도구 교체 논의가 앞당겨질 수 있습니다.",
                    "owner_angle": "BI 라이선스 갱신 시점을 다시 볼 이유가 생겼습니다.",
                    "next_watch": "정식 출시 일정; 기업용 요금",
                },
            ],
            "deep_dive": {
                "body": (
                    "속도와 자본은 서로 다른 시간축 위에서 움직입니다. 전자는 분기 단위 도입 "
                    "결정을 흔들고, 후자는 수년 단위 전력·부지 계약을 확정합니다. 두 축이 "
                    "만나는 지점은 결국 단위 추론당 비용입니다."
                ),
                "key_implications": [
                    "추론 단가 하락은 사내 자동화 범위를 넓힙니다.",
                    "인프라 금융화는 조달 리드타임을 길게 만듭니다.",
                ],
                "uncertainty": "가격표가 공개되기 전까지 비용 효과는 추정치입니다.",
            },
        }

    def test_valid_briefing_passes_the_surface_gate(self) -> None:
        data = self._valid_briefing()
        result = evaluate_global_visible_surface(
            subject=data["subject"],
            items=data["items"],
            deep_dive=data["deep_dive"],
            opening_lead=data["opening_lead"],
        )
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["issue_codes"], [], result["findings"])

    def test_valid_briefing_passes_the_final_post_render_gate(self) -> None:
        data = self._valid_briefing()
        blocks = [data["opening_lead"]]
        for item in data["items"]:
            blocks.extend(
                [
                    item["headline"],
                    item["what_happened"],
                    item["why_now"],
                    item["owner_angle"],
                ]
            )
        blocks.append(data["deep_dive"]["body"])
        result = validate_global_post_render_visible_quality(
            _as_html(*blocks),
            briefing_items=data["items"],
            subject=data["subject"],
            deep_dive=data["deep_dive"],
            opening_lead=data["opening_lead"],
        )
        self.assertTrue(result.ok, [(i.code, i.message) for i in result.issues])

    def test_english_headlines_alone_never_block(self) -> None:
        rows = (
            (
                "Lightmatter launches 19-company strong initiative to standardize "
                "silicon photonics-ready infrastructure",
                "광통신 표준화 컨소시엄이 데이터센터 조달 단가를 흔들 수 있습니다.",
            ),
            (
                "The builder’s guide to GPT-5.6",
                "개발자 문서가 함께 열려 사내 적용 검토가 빨라집니다.",
            ),
            (
                "Twitch content has trained Amazon AI for years, but creators say "
                "they were never asked",
                "창작물 학습 동의 구조가 국내 계약서 문구에도 영향을 줍니다.",
            ),
        )
        items = [
            {
                "rank": idx,
                "headline": headline,
                "primary_category": "ai_software_platform",
                "category_label_ko": "AI·소프트웨어·플랫폼",
                "what_happened": what_happened,
            }
            for idx, (headline, what_happened) in enumerate(rows, start=1)
        ]
        result = evaluate_global_visible_surface(items=items)
        self.assertTrue(result["ok"], result["findings"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
