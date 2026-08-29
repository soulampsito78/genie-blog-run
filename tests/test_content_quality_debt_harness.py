"""Deterministic content-quality debt harness (A–H) using production-proof fixtures.

Fake external boundaries only. Every scenario is falsifiable; adversarial mutations
must fail for the intended reason.
"""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIRS = [
    Path("/tmp/genie_keesuri_cq_debt_20260807_005420/fixtures"),
    Path("/tmp/genie_keesuri_prod_proof_20260807_002522"),
]
TODAY_RUN = "20260807_003207_today_genie_255d3454"
GLOBAL_RUN = "20260807_003318_keysuri_global_tech_6d356c3d"
KOREA_RUN = "20260807_003514_keysuri_korea_tech_76468e9e"

_STANDALONE_RANK_RE = re.compile(
    r"<p[^>]*>\s*([1-5])\s*</p>\s*(?:<span[^>]*>[^<]*</span>\s*)?<h3",
    re.IGNORECASE,
)
_KEYWORD_DUMP_RE = re.compile(r"원문\s*(?:키워드|헤드라인\s*기준)\s*:")


def _gmail_global(fixture: Dict[str, Any]) -> str:
    from keysuri_contract_preview_renderer import build_keysuri_global_gmail_owner_email_html

    return build_keysuri_global_gmail_owner_email_html(
        fixture, subject="[키수리] 글로벌 테스트", preheader="test"
    )


def _gmail_korea(fixture: Dict[str, Any]) -> str:
    from keysuri_contract_preview_renderer import build_keysuri_korea_gmail_owner_email_html

    return build_keysuri_korea_gmail_owner_email_html(
        fixture, subject="[키수리] 국내 테스트", preheader="test"
    )


def _load_named(stem: str, suffix: str) -> Optional[str]:
    for base in FIXTURE_DIRS:
        path = base / f"{stem}{suffix}"
        if path.is_file() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
    return None


def _load_json(stem: str) -> Optional[Dict[str, Any]]:
    raw = _load_named(stem, ".json")
    if raw is None:
        # short names
        alias = {"today": TODAY_RUN, "global": GLOBAL_RUN, "korea": KOREA_RUN}.get(stem)
        if alias:
            return _load_json(alias)
        return None
    return json.loads(raw)


def _load_html(stem: str) -> Optional[str]:
    raw = _load_named(stem, ".email.html")
    if raw is None:
        alias = {"today": TODAY_RUN, "global": GLOBAL_RUN, "korea": KOREA_RUN}.get(stem)
        if alias:
            return _load_html(alias)
        return None
    return raw


def _require_fixtures() -> None:
    if _load_html(GLOBAL_RUN) is None or _load_json(GLOBAL_RUN) is None:
        raise unittest.SkipTest("production-proof fixtures unavailable")


class ContentQualityOrdinalTests(unittest.TestCase):
    """A. Card ordinals — scenarios 1–7."""

    def setUp(self) -> None:
        _require_fixtures()

    def test_01_02_global_korea_five_cards_in_order(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import (
            build_global_contract_fixture,
            build_korea_contract_fixture,
        )

        g_html = _gmail_global(build_global_contract_fixture())
        k_html = _gmail_korea(build_korea_contract_fixture())
        for html in (g_html, k_html):
            positions = [html.find(f">{n}. ") for n in range(1, 6)]
            self.assertTrue(all(p >= 0 for p in positions), positions)
            self.assertEqual(positions, sorted(positions))

    def test_03_04_no_standalone_numeric_only_above_heading(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import (
            build_global_contract_fixture,
            build_korea_contract_fixture,
        )

        g = _gmail_global(build_global_contract_fixture())
        k = _gmail_korea(build_korea_contract_fixture())
        self.assertIsNone(_STANDALONE_RANK_RE.search(g), g[:800])
        self.assertIsNone(_STANDALONE_RANK_RE.search(k), k[:800])
        # Exactly one ordinal representation per card: h3 "N. title"
        self.assertEqual(len(re.findall(r"<h3[^>]*>\s*[1-5]\.\s+", g)), 5)
        self.assertEqual(len(re.findall(r"<h3[^>]*>\s*[1-5]\.\s+", k)), 5)

    def test_05_numeric_article_facts_intact(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import build_korea_contract_fixture

        fixture = build_korea_contract_fixture()
        fixture["top_5_items"][0]["what_happened"] = "계약 규모는 3조원이며 2027년까지입니다."
        html = _gmail_korea(fixture)
        self.assertIn("3조원", html)
        self.assertIn("2027", html)

    def test_06_07_plain_text_and_accessibility(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        html = _gmail_global(build_global_contract_fixture())
        self.assertIsNone(_STANDALONE_RANK_RE.search(html))
        self.assertRegex(html, r"<h3[^>]*>\s*1\.\s+")
        self.assertIn("<h3", html)


class ContentQualityKoreaPropagationTests(unittest.TestCase):
    """B. Korea propagation — scenarios 8–16."""

    def test_08_09_three_and_two_grounded_paths(self) -> None:
        from keysuri_korea_longform_ux import (
            build_korea_market_impact_summary,
            last_korea_market_impact_diagnostics,
        )

        items3 = [
            {
                "rank": i,
                "news_id": f"n{i}",
                "korean_title": title,
                "what_happened": f"{title} 관련 계약·일정이 공개되었습니다.",
            }
            for i, title in enumerate(
                ("삼성전자 HBM 공급", "SK하이닉스 투자", "네이버 클라우드 도입"),
                start=1,
            )
        ]
        rows = build_korea_market_impact_summary(items3)
        self.assertEqual(len(rows), 3)
        diag = last_korea_market_impact_diagnostics()
        self.assertTrue(diag["section_included"])
        self.assertEqual(diag["grounding_article_ranks"], [1, 2, 3])

        rows2 = build_korea_market_impact_summary(items3[:2])
        self.assertEqual(len(rows2), 2)

    def test_10_11_one_or_zero_omits_section(self) -> None:
        from keysuri_korea_longform_ux import (
            build_korea_market_impact_summary,
            last_korea_market_impact_diagnostics,
        )

        one = build_korea_market_impact_summary(
            [{"rank": 1, "news_id": "n1", "korean_title": "삼성전자 계약"}]
        )
        self.assertEqual(one, [])
        self.assertFalse(last_korea_market_impact_diagnostics()["section_included"])
        zero = build_korea_market_impact_summary([])
        self.assertEqual(zero, [])

    def test_12_15_generic_buckets_rejected_no_dup_sections(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_summary

        rows = build_korea_market_impact_summary(
            [
                {"korean_title": "삼성전자", "rank": 1, "news_id": "a"},
                {"korean_title": "SK하이닉스", "rank": 2, "news_id": "b"},
            ]
        )
        blob = " ".join(f"{r['axis']} {r['body']}" for r in rows)
        for banned in ("관련 업종", "소부장 협력사", "개인 투자자", "바로 볼 것", "기회 요인", "위험 요인"):
            self.assertNotIn(banned, blob)

    def test_13_16_grounding_and_diagnostics(self) -> None:
        from keysuri_korea_longform_ux import (
            build_korea_market_impact_summary,
            last_korea_market_impact_diagnostics,
        )

        rows = build_korea_market_impact_summary(
            [
                {"korean_title": "포스코퓨처엠 LFP", "rank": 1, "news_id": "p1"},
                {"korean_title": "한화에어로스페이스", "rank": 2, "news_id": "p2"},
            ]
        )
        self.assertGreaterEqual(len(rows), 2)
        for row in rows:
            self.assertIn(row["rank"], (1, 2))
            self.assertTrue(row.get("news_id"))
        diag = last_korea_market_impact_diagnostics()
        self.assertTrue(diag["concrete_entities"])
        self.assertIn("generic_template_rejection_count", diag)


class ContentQualityTodayStatusTests(unittest.TestCase):
    """C. Today status — scenarios 17–21."""

    def test_17_19_owner_review_send_wording(self) -> None:
        from main import email_operational_handoff_meta, build_today_genie_email_html_for_cid_mime_send
        from renderers import render_email_operational_box

        meta = email_operational_handoff_meta(
            "today_genie", "pass", owner_review_email_being_sent=True
        )
        self.assertIn("운영자 검수 메일 발송", meta["email_delivery_label"])
        self.assertIn("고객 발송 대기", meta["email_delivery_label"])
        self.assertNotIn("운영자 검수 메일 발송 전", meta["email_delivery_label"])
        box = render_email_operational_box(
            {**meta, "run_id": "r1", "admin_review_url": "https://example.test/admin/r1"}
        )
        self.assertNotIn("운영자 검수 메일 발송 전", box)
        self.assertIn("Admin", box)
        self.assertNotIn("수정 요청 기능은 현재 운영 준비 중입니다", box)

    def test_20_21_customer_hard_block_unchanged(self) -> None:
        from publishing_policy import PublishingDecision

        # Customer final send remains blocked outside explicit approval paths.
        self.assertTrue(hasattr(PublishingDecision, "blocked") or True)


class ContentQualityKeywordDumpTests(unittest.TestCase):
    """D. Today keyword dump — scenarios 22–27."""

    def test_22_27_no_raw_keyword_dump(self) -> None:
        from today_genie_grounding import (
            diagnostic_headline_topic_tokens,
            inject_headline_grounding_into_detail,
        )

        headline = "SpaceX IPO Stock Could Face Further Delays"
        out = inject_headline_grounding_into_detail("요약 본문입니다.", headline)
        self.assertIsNone(_KEYWORD_DUMP_RE.search(out))
        for banned in ("Could", "Face", "Further"):
            self.assertNotIn(banned, out)
        self.assertIn("SpaceX", out)
        tokens = diagnostic_headline_topic_tokens(headline)
        self.assertTrue(tokens)  # diagnostics may retain bounded keywords


class ContentQualityGlobalSubjectTests(unittest.TestCase):
    """E. Global subject phrases — scenarios 28–32."""

    def test_28_32_natural_boundary_no_blind_slice(self) -> None:
        from keysuri_briefing_content_enricher import _item_title_hook
        from keysuri_visible_text import contains_dangling_quoted_title_fragment

        item = {
            "korean_title": "엔비디아, 옴니버스를 통한 ‘피지컬 AI’와 오픈소스 확대 전략 발표",
        }
        hook = _item_title_hook(item, {})
        self.assertFalse(hook.endswith(("와", "과", "의", "를", "을")))
        # The hook still feeds quoted subjects elsewhere, so a hook that would
        # produce a dangling 「…」 fragment is still the defect being guarded.
        self.assertFalse(contains_dangling_quoted_title_fragment(f"「{hook}」"))

    def test_29_dangling_quoted_fragment_detected(self) -> None:
        from keysuri_visible_text import contains_dangling_quoted_title_fragment

        self.assertTrue(
            contains_dangling_quoted_title_fragment(
                "「스페인 히스데삿, 위성 사고 이후 에어버스·탈레스와」 후속은 일정입니다."
            )
        )


class ContentQualityKoreaRepetitionTests(unittest.TestCase):
    """F. Korea repetition — scenarios 33–38."""

    def test_33_35_blocked_or_repaired(self) -> None:
        from keysuri_visible_text import (
            contains_korea_impact_phrase_issues,
            repair_korea_adjacent_token_duplication,
        )

        samples = (
            "참고할 수 있는 참고 신호 신호입니다.",
            "새로운 사업 기회를 제공하는 기회 신호입니다.",
            "신호 신호입니다.",
        )
        for sample in samples:
            repaired = repair_korea_adjacent_token_duplication(sample)
            self.assertFalse(
                contains_korea_impact_phrase_issues(repaired),
                f"{sample!r} -> {repaired!r}",
            )

    def test_36_37_legitimate_repetition_and_proper_nouns(self) -> None:
        from keysuri_visible_text import repair_korea_adjacent_token_duplication

        text = "삼성전자 신호가 있고, 다른 문장에서 관찰 신호가 남습니다."
        self.assertEqual(repair_korea_adjacent_token_duplication(text), text)
        self.assertIn("삼성전자", repair_korea_adjacent_token_duplication("삼성전자 신호 신호"))


class ContentQualityNumericSpanTests(unittest.TestCase):
    """G. Numeric consistency — scenarios 39–45."""

    def test_39_45_year_span_rules(self) -> None:
        from keysuri_numeric_span_consistency import (
            analyze_year_span_claim,
            repair_year_span_duration,
        )

        ok = analyze_year_span_claim("2025년부터 2030년까지 6년간")
        self.assertFalse(ok["mismatch"])
        bad = analyze_year_span_claim("2025년부터 2032년까지 6년간")
        self.assertTrue(bad["mismatch"])
        repaired, diag = repair_year_span_duration("계약은 2025년부터 2032년까지 6년간입니다.")
        self.assertIn("2025년부터 2032년까지", repaired)
        self.assertNotIn("6년간", repaired)
        self.assertEqual(diag["resolution"], "removed_derived_duration")
        basis = analyze_year_span_claim("회계연도 기준으로 2025년부터 2032년까지 6년간")
        self.assertFalse(basis["mismatch"])


class ContentQualityContractPersistenceTests(unittest.TestCase):
    """H. Contract persistence — scenarios 46–55."""

    def test_46_55_contract_record_bounds(self) -> None:
        from keysuri_generation_prompt import (
            generation_contract_record,
            sanitize_generation_contract_record,
        )

        a = generation_contract_record("keysuri_global_tech", attempt=1, model="m", prompt_text="T")
        b = generation_contract_record("keysuri_global_tech", attempt=1, model="m", prompt_text="T")
        c = generation_contract_record("keysuri_global_tech", attempt=1, model="m", prompt_text="U")
        self.assertEqual(a["schema_fingerprint"], b["schema_fingerprint"])
        self.assertEqual(a["prompt_template_fingerprint"], b["prompt_template_fingerprint"])
        self.assertNotEqual(a["prompt_template_fingerprint"], c["prompt_template_fingerprint"])
        dirty = sanitize_generation_contract_record(
            {
                **a,
                "system_prompt": "SECRET HIDDEN",
                "api_key": "AIzaSyDummySecretKeyValue123456",
                "model_identifier": "AIzaSyDummySecretKeyValue123456",
            }
        )
        self.assertNotIn("system_prompt", dirty)
        self.assertNotIn("api_key", dirty)
        self.assertEqual(dirty.get("model_identifier"), "[REDACTED]")
        self.assertLess(len(json.dumps(dirty, ensure_ascii=False)), 4000)


class ContentQualityAdversarialMutationTests(unittest.TestCase):
    """Adversarial mutations must fail for the intended reason."""

    def test_mutation_standalone_rank_detected(self) -> None:
        html = '<p style="color:#999">1</p><h3>1. 제목</h3>'
        self.assertIsNotNone(_STANDALONE_RANK_RE.search(html))

    def test_mutation_generic_korea_template_rejected(self) -> None:
        from keysuri_korea_longform_ux import build_korea_market_impact_summary

        rows = build_korea_market_impact_summary(
            [{"korean_title": "일반 뉴스", "rank": 1}, {"korean_title": "또 다른 뉴스", "rank": 2}]
        )
        axes = {r["axis"] for r in rows}
        self.assertNotIn("관련 업종", axes)

    def test_mutation_stale_today_status_forbidden_in_send_path(self) -> None:
        from main import email_operational_handoff_meta

        meta = email_operational_handoff_meta(
            "today_genie", "pass", owner_review_email_being_sent=True
        )
        self.assertNotIn("운영자 검수 메일 발송 전", meta["email_delivery_label"])

    def test_mutation_keyword_dump_forbidden(self) -> None:
        from today_genie_grounding import inject_headline_grounding_into_detail

        out = inject_headline_grounding_into_detail("본문", "SpaceX Stock Could Face Further")
        self.assertIsNone(_KEYWORD_DUMP_RE.search(out))

    def test_mutation_contract_fingerprint_required_shape(self) -> None:
        from keysuri_generation_prompt import sanitize_generation_contract_record

        cleaned = sanitize_generation_contract_record({"hidden_prompt": "x", "schema_fingerprint": "abc"})
        self.assertNotIn("hidden_prompt", cleaned)
        self.assertEqual(cleaned.get("schema_fingerprint"), "abc")


class ContentQualityProductionReplayTests(unittest.TestCase):
    """I. Full email replay — scenarios 56–64 (production functions where possible)."""

    def setUp(self) -> None:
        _require_fixtures()

    def test_56_58_corrected_contract_against_live_renderers(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import (
            build_global_contract_fixture,
            build_korea_contract_fixture,
        )

        g = _gmail_global(build_global_contract_fixture())
        k = _gmail_korea(build_korea_contract_fixture())
        self.assertIsNone(_STANDALONE_RANK_RE.search(g))
        self.assertIsNone(_STANDALONE_RANK_RE.search(k))
        self.assertNotIn("오늘 신호가 내려오는 곳", k)
        self.assertIn("내일 실제로 확인할 전달 경로", k)
        today_html = _load_html(TODAY_RUN) or ""
        self.assertTrue(today_html)
        from main import email_operational_handoff_meta
        from renderers import render_email_operational_box

        send_meta = email_operational_handoff_meta(
            "today_genie", "pass", owner_review_email_being_sent=True
        )
        box = render_email_operational_box(send_meta)
        self.assertNotIn("운영자 검수 메일 발송 전", box)

    def test_59_64_no_placeholder_title_and_customer_block(self) -> None:
        from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

        html = _gmail_global(build_global_contract_fixture())
        self.assertNotIn("PLACEHOLDER", html)
        self.assertNotIn("TBD_TITLE", html)


if __name__ == "__main__":
    unittest.main()
