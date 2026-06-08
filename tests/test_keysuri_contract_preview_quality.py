"""Tests for Kee-Suri contract preview visible-body quality gates."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from keysuri_contract_preview_quality import (
    GENERIC_CLOSING_PHRASES,
    STAGED_PLACEHOLDER_MARKERS,
    validate_contract_preview_visible_body,
)
from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from keysuri_html_preview_validation import validate_keysuri_html_preview
from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

_REPO = Path(__file__).resolve().parent.parent


def _premium_fixture(**overrides):
    fixture = build_global_contract_fixture()
    fixture.update(overrides)
    return fixture


class KeysuriContractPreviewQualityTests(unittest.TestCase):
    def test_fails_on_internal_labels_in_visible_body(self) -> None:
        html = """
        <html><body>
        <header class="premium-hero" id="premium-hero"></header>
        <section id="opening-lead"><p class="opening-lead">주인님, 한국어 오프닝 리드입니다. 오늘 신호를 정리했습니다.</p></section>
        <figure id="top-shot-image"><img class="top-shot-hero" src="data:image/jpeg;base64,abc"/></figure>
        <section id="top5-section" class="section-card"><article class="briefing-card" data-top-item="1">
        <h4 class="block-label">무슨 일이 있었나</h4><p class="block-body">내용.</p>
        <h4 class="block-label">왜 지금 중요한가</h4><p class="block-body">내용.</p>
        <div class="owner-angle-block"><h4 class="block-label">주인님 관점</h4><p class="block-body">내용.</p></div>
        <div class="judgment-row"><span class="judgment-badge">관찰</span></div>
        <h4 class="block-label">다음 확인 포인트</h4><p class="block-body">내용.</p>
        </article></section>
        <section id="deep-dive-section"><p>주인님, 딥다이브 문장 하나. 둘. 셋. 넷. 다섯.</p></section>
        <p>why_it_matters: exposed</p>
        <div id="rights-policy">Copyright Ⓒ MirAI:ON. All rights reserved.
        무단 전재, 재배포 및 AI학습 이용 절대 금지</div>
        <div id="operation-metadata">Operation metadata</div>
        </body></html>
        """
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        codes = {i.code for i in result.issues}
        self.assertIn("internal_label_exposed", codes)

    def test_fails_on_guisa(self) -> None:
        fixture = _premium_fixture(
            opening_lead="귀사의 AI 전략에 참고가 되시길 바랍니다. 오늘 신호를 정리했습니다. 추가 확인이 필요합니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "forbidden_phrase" for i in result.issues))

    def test_renderer_replaces_generic_closing(self) -> None:
        fixture = _premium_fixture(
            closing_message="주인님, 오늘 브리핑이 도움이 되셨기를 바랍니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        region = html.split('id="operation-metadata"')[0]
        self.assertNotIn("도움이 되셨기를 바랍니다", region)
        result = validate_contract_preview_visible_body(html)
        self.assertTrue(result.ok, msg=[i.message for i in result.issues])

    def test_fails_on_relative_hero_path(self) -> None:
        html = """
        <html><body class="premium-briefing">
        <header class="premium-hero" id="premium-hero"></header>
        <figure id="top-shot-image"><img class="top-shot-hero" src="../image_canary/hero.jpg"/></figure>
        <section id="opening-lead"><p class="opening-lead">주인님, 오프닝입니다. 신호를 정리했습니다.</p></section>
        <section id="top5-section" class="section-card"><article class="briefing-card" data-top-item="1">
        <h4 class="block-label">무슨 일이 있었나</h4><p>첫 문장. 둘째 문장.</p>
        <h4 class="block-label">왜 지금 중요한가</h4><p>내용.</p>
        <div class="owner-angle-block"><h4 class="block-label">주인님 관점</h4><p>내용.</p></div>
        <div class="judgment-row"><span class="judgment-badge">관찰</span></div>
        <h4 class="block-label">다음 확인 포인트</h4><p>내용.</p>
        </article></section>
        <section id="deep-dive-section"><p>주인님, 딥다이브. 둘. 셋. 넷. 다섯.</p></section>
        <div id="rights-policy">Copyright Ⓒ MirAI:ON. All rights reserved.</div>
        <div id="operation-metadata">meta</div>
        </body></html>
        """
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "hero_image_relative_path" for i in result.issues))

    def test_fails_on_english_primary_headline(self) -> None:
        fixture = _premium_fixture()
        fixture["top_5_items"][0]["korean_title"] = "Google announces major Gemini update for enterprise"
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "english_rss_leakage" for i in result.issues))

    def test_fails_on_one_line_rss_summary_items(self) -> None:
        fixture = _premium_fixture()
        for item in fixture["top_5_items"]:
            item["what_happened"] = "한 줄 요약."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "top5_insufficient_detail" for i in result.issues))

    def test_passes_premium_korean_fixture_with_data_uri_hero(self) -> None:
        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        result = validate_contract_preview_visible_body(html)
        self.assertTrue(result.ok, msg=[i.message for i in result.issues])
        self.assertIn("주인님", html)
        self.assertNotIn("귀사", html)
        self.assertNotIn("../image_canary", html)
        img_match = re.search(
            r'<img[^>]*class="top-shot-hero"[^>]*src="([^"]+)"'
            r'|<img[^>]*src="([^"]+)"[^>]*class="top-shot-hero"',
            html,
        )
        self.assertIsNotNone(img_match)
        assert img_match is not None
        src = img_match.group(1) or img_match.group(2)
        self.assertTrue(src.startswith("data:image/"))
        for label in ("무슨 일이 있었나", "왜 지금 중요한가", "주인님 관점", "다음 확인 포인트"):
            self.assertIn(label, html)
        for marker in ("premium-briefing", "premium-hero", "briefing-card", "owner-angle-block", "judgment-badge"):
            self.assertIn(marker, html)

    def test_juinim_in_opening_or_deep_dive(self) -> None:
        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        region = html.split('id="operation-metadata"')[0]
        self.assertIn("주인님", region)

    def test_operational_metadata_after_briefing(self) -> None:
        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        top5 = html.find('id="top5-section"')
        op = html.find('id="operation-metadata"')
        self.assertGreater(op, top5)


class KeysuriStagedPlaceholderGateTests(unittest.TestCase):
    def _minimal_premium_html(self, *, body_extra: str = "") -> str:
        return f"""
        <html><body class="premium-briefing">
        <header class="premium-hero" id="premium-hero"></header>
        <figure id="top-shot-image"><img class="top-shot-hero" src="data:image/jpeg;base64,abc"/></figure>
        <section id="opening-lead"><p class="opening-lead">주인님, 오프닝입니다. 신호를 정리했습니다.</p></section>
        <section id="top5-section" class="section-card"><article class="briefing-card" data-top-item="1">
        <h4 class="block-label">무슨 일이 있었나</h4><p>첫 문장. 둘째 문장. {body_extra}</p>
        <h4 class="block-label">왜 지금 중요한가</h4><p>내용.</p>
        <div class="owner-angle-block"><h4 class="block-label">주인님 관점</h4><p>내용.</p></div>
        <div class="judgment-row"><span class="judgment-badge">관찰</span></div>
        <h4 class="block-label">다음 확인 포인트</h4><p>내용.</p>
        </article></section>
        <section id="deep-dive-section"><p>주인님, 딥다이브. 둘. 셋. 넷. 다섯.</p></section>
        <div id="rights-policy">Copyright Ⓒ MirAI:ON. All rights reserved.</div>
        <div id="operation-metadata">meta</div>
        </body></html>
        """

    def test_fails_on_staging_korean_headline(self) -> None:
        html = self._minimal_premium_html(body_extra="스테이징 한국어 헤드라인 1")
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "staged_placeholder_leak" for i in result.issues))

    def test_fails_on_infrastructure_signal(self) -> None:
        html = self._minimal_premium_html(body_extra="Infrastructure signal")
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "staged_placeholder_leak" for i in result.issues))

    def test_fails_on_staged_global_layer(self) -> None:
        html = self._minimal_premium_html(body_extra="Staged global layer one — infrastructure movement sample.")
        result = validate_contract_preview_visible_body(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "staged_placeholder_leak" for i in result.issues))

    def test_clean_fixture_passes_staged_gate(self) -> None:
        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        result = validate_contract_preview_visible_body(html)
        self.assertTrue(result.ok, msg=[i.message for i in result.issues])
        region = html.split('id="operation-metadata"')[0]
        for marker in STAGED_PLACEHOLDER_MARKERS:
            self.assertNotIn(marker, region, msg=f"unexpected staged marker: {marker!r}")


class KeysuriPremiumDesignHandoffTests(unittest.TestCase):
    def test_handoff_visual_structure(self) -> None:
        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        self.assertIn('name="color-scheme"', html)
        self.assertIn('class="preheader-hidden"', html)
        self.assertIn('id="signal-summary"', html)
        self.assertIn('class="audit-fold"', html)
        self.assertIn('class="hero-layout"', html)
        self.assertGreaterEqual(html.count('class="judgment-label"'), 5)
        style_block = html[html.find("<style>") : html.find("</style>")]
        self.assertIn("object-fit:contain", style_block.replace(" ", ""))
        self.assertNotRegex(style_block, r"\.top-shot-hero\{[^}]*object-fit:\s*cover")
        for phrase in GENERIC_CLOSING_PHRASES:
            region = html.split('id="operation-metadata"')[0]
            self.assertNotIn(phrase, region)

    def test_contract_preview_validator_passes(self) -> None:
        from tempfile import TemporaryDirectory

        html = render_keysuri_contract_preview_html(_premium_fixture(), repo_root=_REPO)
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output/keysuri_preview/html_test"
            path.mkdir(parents=True)
            stamp = "20260608_150000"
            out = path / f"keysuri_global_1230_contract_preview_{stamp}.html"
            out.write_text(html, encoding="utf-8")
            result = validate_keysuri_html_preview(str(out), profile="contract_preview")
            self.assertEqual(result.validation_status, "PASS", result.issues)


if __name__ == "__main__":
    unittest.main()
