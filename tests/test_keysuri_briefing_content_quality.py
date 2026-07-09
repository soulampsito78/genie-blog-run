"""Tests for Kee-Suri three-gate preview validation report."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keysuri_briefing_content_quality import (
    _extract_source_list_region,
    validate_briefing_content_gate,
)
from keysuri_korea_longform_ux import (
    KOREA_CLOSING_PARAGRAPH_MAX_CHARS,
    count_korea_memo_action_lines,
    count_korea_memo_action_lines_in_closing,
    extract_korea_memo_action_lines_from_html,
    korea_closing_paragraph_too_long,
)
from keysuri_contract_preview_quality import validate_contract_preview_structural_gate
from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from keysuri_preview_validation_report import (
    compute_overall_status,
    validate_keysuri_contract_preview,
)
from keysuri_visual_identity_quality import validate_visual_identity_gate
from tests.test_keysuri_contract_preview_renderer import (
    build_global_contract_fixture,
    build_korea_contract_fixture,
)

_REPO = Path(__file__).resolve().parent.parent


def _premium_html(**overrides):
    fixture = build_global_contract_fixture()
    fixture.update(overrides)
    return render_keysuri_contract_preview_html(fixture, repo_root=_REPO)


def _generated_test_manifest(*, with_reference: bool = False, with_batch: bool = False) -> dict:
    manifest = {
        "schema_version": "keysuri_image_asset_manifest_v0",
        "program_id": "keysuri_global_tech",
        "slot": "12:30",
        "image_role": "top_shot",
        "image_source": "generated_test",
        "width": 1280,
        "height": 720,
        "aspect_ratio": 1.78,
        "overlay_applied": True,
        "watermark": "MirAI:ON applied",
        "prompt_profile": "keysuri_global_topshot_test_v1",
        "owner_visual_review_required": True,
        "quality_verdict": "pass" if with_batch else None,
        "selected_candidate_id": "cand_01" if with_batch else None,
        "batch_id": "batch_20260608" if with_batch else None,
        "candidate_id": "cand_01" if with_batch else None,
    }
    if with_reference:
        manifest["reference_image_path"] = "assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png"
        manifest["reference_image_sha256"] = "abc123"
    return manifest


class KeysuriPreviewValidationReportTests(unittest.TestCase):
    def test_structural_pass_alone_does_not_make_overall_pass(self) -> None:
        html = _premium_html()
        report = validate_keysuri_contract_preview(html)
        self.assertEqual(report.structural_gate.status, "pass")
        self.assertNotEqual(
            report.overall_status,
            "owner_visual_review_ready",
            "visual gate must block owner_visual_review_ready without manifest/approval",
        )

    def test_structural_gate_labeled_structural_only(self) -> None:
        html = _premium_html()
        report = validate_keysuri_contract_preview(html)
        self.assertIn("Structural", report.structural_gate.label)
        self.assertIn("HTML", report.structural_gate.label)

    def test_owner_visual_review_ready_not_equal_test_email_ready(self) -> None:
        html = _premium_html()
        report = validate_keysuri_contract_preview(html)
        self.assertFalse(report.can_send_test_email)
        self.assertFalse(report.ready_for_test_email)

    def test_data_uri_and_watermark_alone_insufficient_for_visual_pass(self) -> None:
        html = _premium_html()
        result = validate_visual_identity_gate(html)
        self.assertNotEqual(result.status, "pass")
        self.assertIn(result.status, ("fail", "manual_review_required"))

    def test_generated_image_without_reference_cannot_visual_pass(self) -> None:
        html = _premium_html()
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "hero.manifest.json"
            manifest_path.write_text(
                json.dumps(_generated_test_manifest(with_reference=False, with_batch=True)),
                encoding="utf-8",
            )
            result = validate_visual_identity_gate(html, manifest_path=str(manifest_path))
            self.assertNotEqual(result.status, "pass")
            codes = {i.code for i in result.issues}
            self.assertIn("reference_image_missing", codes)

    def test_single_shot_generated_image_without_candidate_gate_cannot_visual_pass(self) -> None:
        html = _premium_html()
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "hero.manifest.json"
            manifest_path.write_text(
                json.dumps(_generated_test_manifest(with_reference=True, with_batch=False)),
                encoding="utf-8",
            )
            result = validate_visual_identity_gate(html, manifest_path=str(manifest_path))
            self.assertNotEqual(result.status, "pass")
            codes = {i.code for i in result.issues}
            self.assertTrue(
                "single_shot_no_batch" in codes or "candidate_gate_missing" in codes,
                msg=codes,
            )

    def test_manifest_without_reference_hash_fails_or_manual_review(self) -> None:
        html = _premium_html()
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "hero.manifest.json"
            manifest_path.write_text(
                json.dumps(_generated_test_manifest(with_reference=False)),
                encoding="utf-8",
            )
            result = validate_visual_identity_gate(html, manifest_path=str(manifest_path))
            self.assertIn(result.status, ("fail", "manual_review_required"))

    def test_structural_pass_content_fail_blocks_overall(self) -> None:
        html = _premium_html(
            opening_lead="귀사의 AI 전략에 참고가 되시길 바랍니다. 오늘 신호를 정리했습니다."
        )
        report = validate_keysuri_contract_preview(html)
        self.assertEqual(report.structural_gate.status, "fail")
        self.assertEqual(report.overall_status, "blocked")

    def test_structural_pass_content_pass_visual_manual_review(self) -> None:
        html = _premium_html()
        with TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "hero.manifest.json"
            manifest_path.write_text(
                json.dumps(_generated_test_manifest(with_reference=True, with_batch=True)),
                encoding="utf-8",
            )
            report = validate_keysuri_contract_preview(html, image_manifest_path=str(manifest_path))
            self.assertEqual(report.structural_gate.status, "pass")
            self.assertEqual(report.content_briefing_gate.status, "pass")
            self.assertEqual(report.visual_identity_gate.status, "manual_review_required")
            self.assertEqual(report.overall_status, "manual_visual_review_required")
            self.assertFalse(report.ready_for_owner_visual_review)
            self.assertTrue(report.ready_for_owner_manual_visual_inspection)


class KeysuriBriefingContentQualityTests(unittest.TestCase):
    def test_catches_thin_one_line_article_briefing(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["what_happened"] = "한 줄 요약."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html)
        self.assertFalse(result.ok)
        codes = {i.code for i in result.issues}
        self.assertTrue("item_detail_too_thin" in codes or "top5_insufficient_detail" in codes)

    def test_catches_generic_implications(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["why_now"] = "지금 주목받는 신호입니다."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "generic_business_implication" for i in result.issues))

    def test_catches_missing_uncertainty_when_source_detail_thin(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["what_happened"] = "한 줄."
        fixture["deep_dive_body"] = (
            "주인님, 확인된 사실만 정리합니다. 키수리 해석도 포함합니다. "
            "운영자 관점도 있습니다. 네 번째 문장. 다섯 번째 문장."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html)
        self.assertFalse(result.ok)
        codes = {i.code for w in result.warnings for i in [w]} | {i.code for i in result.issues}
        self.assertTrue(
            "source_detail_insufficient" in codes or "unsupported_claim" in codes or "item_detail_too_thin" in codes
        )

    def test_catches_guisa(self) -> None:
        fixture = build_global_contract_fixture()
        fixture["opening_lead"] = "귀사의 전략에 참고가 되시길 바랍니다. 오늘 신호입니다. 추가 확인."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "forbidden_phrase" for i in result.issues))

    def test_catches_missing_sponsored_warning_with_global_metadata(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["selection_reason"] = (
                "반도체·인프라 신호로 선정했습니다. 공급망 압력이 커지는 구간입니다."
            )
            item["why_now"] = (
                "항목은 엔터프라이즈 배포·API 정책 변경이 겹치는 시점입니다. "
                "주인님의 파트너·비용 구조에 단기 영향이 나올 수 있습니다. "
                "반도체·인프라 병목도 함께 점검할 필요가 있습니다."
            )
            item["owner_angle"] = (
                "주인님께서는 항목을 제품 로드맵·파트너 선정 기준에 반영할지 점검하시면 됩니다. "
                "단기 과장과 장기 구조 변화를 구분해 보시는 것이 좋습니다. "
                "공급망·비용 구조 변화는 분기 단위로 재점검하시면 됩니다."
            )
            item["next_watch"] = "→ 공식 발표 확인; → 가격·일정 공개 여부 점검"
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {
            "global_top5_selection": {"policy": "keysuri_global_top5_selection_v2_diversity"},
            "claims": [
                {
                    "selection_score": 80,
                    "selection_rationale": "test",
                    "primary_category": "ai_software_platform",
                    "sponsored_warning": True,
                }
            ]
            * 5,
        }
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "sponsored_warning_missing" for i in result.issues))

    def test_catches_thin_sections_with_global_metadata(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"]:
            item["what_happened"] = "한 줄 요약."
            item["why_now"] = "짧음."
            item["owner_angle"] = "짧음."
            item["selection_reason"] = "짧음."
            item["next_watch"] = "한 가지만."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {
            "global_top5_selection": {"policy": "keysuri_global_top5_selection_v2_diversity"},
            "claims": [{"selection_score": 70, "selection_rationale": "test"}] * 5,
        }
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertFalse(result.ok)
        codes = {i.code for i in result.issues}
        self.assertTrue(
            "item_detail_too_thin" in codes
            or "missing_why_now_depth" in codes
            or "missing_selection_reason_depth" in codes
        )

    def test_catches_english_rss_leakage(self) -> None:
        fixture = build_global_contract_fixture()
        fixture["top_5_items"][0]["korean_title"] = "Google announces major Gemini update for enterprise customers"
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html)
        self.assertFalse(result.ok)
        self.assertTrue(any(i.code == "english_rss_leakage" for i in result.issues))

    def test_korea_gate_flags_global_only_labels(self) -> None:
        fixture = build_korea_contract_fixture()
        fixture["opening_lead"] = (
            "주인님, 글로벌 원인과 한국 도착 전 압력을 정리했습니다. "
            "다음 48시간 관찰 포인트도 함께 봤습니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertIn("korea_global_label_leak", codes)

    def test_korea_gate_fails_on_python_list_repr(self) -> None:
        fixture = build_korea_contract_fixture()
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        html = html.replace(
            "다음 확인 포인트",
            "다음 확인 포인트</h4><p class='block-body'>['A', 'B', 'C']",
            1,
        )
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertTrue(
            "visible_python_list_repr" in codes or "korea_next_watch_list_repr" in codes,
            codes,
        )

    def test_korea_gate_fails_on_owner_name_overuse(self) -> None:
        fixture = build_korea_contract_fixture()
        fixture["opening_lead"] = "주인님, " * 8 + "국내 적용 신호입니다."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertTrue(any(i.code == "korea_owner_name_overused" for i in result.issues))

    def test_korea_gate_fails_on_label_only_emphasis(self) -> None:
        import re

        fixture = build_korea_contract_fixture()
        fixture["top_5_items"][0]["next_day_impact_line"] = "내일 영향: 정책 신호가 반영될 수 있습니다."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        broken = re.sub(
            r'(<span class="card-emphasis-label">[^<]+</span>)\s*<span class="card-emphasis-text">[^<]*</span>',
            r"\1",
            html,
            count=1,
        )
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(broken, source_metadata=metadata)
        self.assertTrue(any(i.code == "korea_emphasis_line_missing_text" for i in result.issues))

    def test_korea_gate_fails_on_generic_checkpoint_strategy(self) -> None:
        fixture = build_korea_contract_fixture()
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        html = html.replace(
            '<div class="checkpoint">',
            '<div class="checkpoint">주인님, 내일의 사업 전략을 구체화하십시오. ',
            1,
        )
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertTrue(
            any(i.code == "korea_checkpoint_strategy_too_generic" for i in result.issues)
        )

    def test_korea_gate_fails_on_internal_score_leak(self) -> None:
        fixture = build_korea_contract_fixture()
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        html = html.replace(
            "무슨 일이 있었나",
            "국내 총점 60점(구조 7, 실행 13). 태그: korean_entity_mention. 무슨 일이 있었나",
            1,
        )
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertIn("visible_internal_score_leak", codes)

    def test_korea_gate_fails_on_snake_case_visible_token(self) -> None:
        fixture = build_korea_contract_fixture()
        fixture["top_5_items"][0]["what_happened"] = (
            "policy_capital_signal 관련 보도가 나왔습니다. 후속 확인이 필요합니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertTrue(any(i.code == "visible_snake_case_token" for i in result.issues))

    def test_korea_gate_fails_on_real_owner_review_broken_endings(self) -> None:
        import re

        fixture = build_korea_contract_fixture()
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        broken = re.sub(
            r'(<h4 class="block-label">\s*선정 이유\s*</h4>\s*<p class="block-body">).*?(</p>)',
            r"\1이 뉴스는 국내 기술 혁신과 자본 흐름에 직접적인 영향을 미칠 수 있어 국내 스타트업/투\2",
            html,
            count=1,
            flags=re.DOTALL,
        )
        broken = re.sub(
            r'(<h4 class="block-label">\s*왜 지금 중요한가\s*</h4>\s*<p class="block-body">).*?(</p>)',
            r"\1관련 정책 변화는 국내 스타트업 생태계 전반에 큰 영향을 미 미칩니다.\2",
            broken,
            count=1,
            flags=re.DOTALL,
        )
        self.assertNotEqual(html, broken)
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(broken, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertIn("korea_incomplete_sentence_ending", codes)

    def test_korea_gate_accepts_domestic_application_wording(self) -> None:
        fixture = build_korea_contract_fixture()
        fixture["opening_lead"] = (
            "주인님, 오늘 국내 적용 관점에서 다섯 신호를 정리했습니다. "
            "내일 영향과 퇴근 전 메모로 남깁니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        self.assertFalse(any(i.code == "korea_global_label_leak" for i in result.issues))
        self.assertFalse(any(i.code == "korea_lens_terms_missing" for i in result.warnings))

    def test_korea_gate_warns_on_upper_layer_only_market_copy(self) -> None:
        html = (
            '<html><body class="premium-briefing theme-korea">'
            "<main>"
            "<section>"
            "<p>주인님, 오늘 국내 적용 관점에서는 M&A와 투자유치, 정책금융, 외국인 자금, "
            "조달, 발주, 수혜주 흐름을 봅니다.</p>"
            "<p>직접 영향은 제한적입니다. 기준금리 일정만 참고 축으로 보겠습니다. "
            "직접 영향은 제한적입니다.</p>"
            "</section>"
            "</main>"
            "</body></html>"
        )
        metadata = {"korea_top5_selection": {"policy": "keysuri_korea_top5_selection_v2_duplicate_guard"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        warning_codes = {i.code for i in result.warnings}
        issue_codes = {i.code for i in result.issues}
        self.assertIn("korea_everyday_impact_lens_thin", warning_codes)
        self.assertIn("korea_upper_layer_only_without_everyday_lens", warning_codes)
        self.assertIn("korea_defensive_market_phrase_overused", issue_codes)


class KeysuriKoreaGateExtractionTests(unittest.TestCase):
    _FIXTURE_001502 = (
        _REPO / "output/keysuri_preview/html_test/keysuri_korea_live_generated_contract_preview_20260609_001502.html"
    )

    def _memo_and_source_html(self, *, with_sources: bool = True) -> str:
        sources = """
        <section id="source-appendix-section">
          <a href="https://example.com/a">source</a>
        </section>
        """ if with_sources else """
        <section id="source-appendix-section">
          <p>출처명: 더lec</p>
        </section>
        """
        return f"""
        <html><body class="premium-briefing theme-korea">
        <section id="closing-section">
          <h2>퇴근 전 메모</h2>
          <div class="evening-memo-body">
            <p>오늘은 엔비디아 방한 이슈가 HBM·파운드리·국내 AI 투자 흐름을 한 번에 묶었습니다.</p>
            <p>내일은 세 가지만 확인하시면 됩니다.</p>
            <ol class="evening-memo-actions">
              <li>삼성전자 HBM4 후속</li>
              <li>GPU 공급 약속 대상 확인</li>
              <li>국내 AI 투자 구체화</li>
            </ol>
            <p>확정되지 않은 수치와 일정은 아직 조심해서 보겠습니다.</p>
            <p class="closing-message warm-farewell">오늘도 수고 많으셨습니다.</p>
            <p class="closing-message warm-farewell">내일 아침에 다시 볼 흐름만 남겨두겠습니다.</p>
          </div>
        </section>
        {sources}
        </body></html>
        """

    def test_source_gate_uses_source_appendix_not_memo_closing(self) -> None:
        html = self._memo_and_source_html(with_sources=True)
        region = _extract_source_list_region(html)
        self.assertIn("source-appendix-section", html)
        self.assertIn("https://example.com/a", region)
        result = validate_briefing_content_gate(html)
        self.assertFalse(any(i.code == "source_list_incomplete" for i in result.issues))

    def test_source_gate_still_fails_without_urls(self) -> None:
        html = self._memo_and_source_html(with_sources=False)
        result = validate_briefing_content_gate(html)
        self.assertTrue(any(i.code == "source_list_incomplete" for i in result.issues))

    def test_memo_action_gate_counts_html_list_items(self) -> None:
        html = self._memo_and_source_html()
        lines = extract_korea_memo_action_lines_from_html(html)
        self.assertEqual(len(lines), 3)
        self.assertGreaterEqual(count_korea_memo_action_lines_in_closing(html), 2)

    def test_memo_action_gate_counts_legacy_numbered_plain_text(self) -> None:
        plain = "내일은 세 가지만 확인하시면 됩니다.\n1. 첫 번째\n2. 두 번째"
        self.assertGreaterEqual(count_korea_memo_action_lines(plain), 2)

    def test_memo_action_gate_fails_with_fewer_than_two_actions(self) -> None:
        html = """
        <section id="closing-section">
          <div class="evening-memo-body">
            <ol class="evening-memo-actions"><li>하나만</li></ol>
          </div>
        </section>
        """
        result = validate_briefing_content_gate(
            f'<html><body class="theme-korea">{html}</body></html>'
        )
        self.assertTrue(any(i.code == "korea_evening_memo_missing_actions" for i in result.issues))

    def test_closing_paragraph_gate_measures_individual_blocks_not_raw_html(self) -> None:
        html = self._memo_and_source_html()
        self.assertFalse(korea_closing_paragraph_too_long(html))

    def test_closing_paragraph_gate_still_fails_on_long_visible_paragraph(self) -> None:
        long_para = "가" * (KOREA_CLOSING_PARAGRAPH_MAX_CHARS + 1)
        self.assertTrue(korea_closing_paragraph_too_long(f"<p>{long_para}</p>"))

    def test_existing_001502_html_gate_false_positives_cleared(self) -> None:
        if not self._FIXTURE_001502.is_file():
            raise unittest.SkipTest("001502 smoke HTML fixture not present")
        html = self._FIXTURE_001502.read_text(encoding="utf-8")
        result = validate_briefing_content_gate(html)
        codes = {issue.code for issue in result.issues}
        self.assertNotIn("source_list_incomplete", codes)
        self.assertNotIn("korea_evening_memo_missing_actions", codes)
        self.assertNotIn("korea_closing_paragraph_too_long", codes)


class KeysuriVisualIdentityQualityTests(unittest.TestCase):
    def test_missing_manifest_fails(self) -> None:
        html = _premium_html()
        result = validate_visual_identity_gate(html)
        self.assertEqual(result.status, "fail")
        self.assertTrue(any(i.code == "manifest_missing" for i in result.issues))

    def test_manual_checks_listed(self) -> None:
        html = _premium_html()
        result = validate_visual_identity_gate(html)
        self.assertGreaterEqual(len(result.manual_checks), 5)
        self.assertTrue(any("bob" in c.lower() or "헤어" in c for c in result.manual_checks))


class KeysuriOverallStatusLogicTests(unittest.TestCase):
    def test_compute_blocked_on_structural_fail(self) -> None:
        from keysuri_preview_validation_report import GateResult

        structural = GateResult(gate="structural", status="fail", label="Structural / HTML quality only")
        content = GateResult(gate="content_briefing", status="pass", label="Content")
        visual = GateResult(gate="visual_identity", status="manual_review_required", label="Visual")
        overall, ready, manual, _ = compute_overall_status(structural, content, visual)
        self.assertEqual(overall, "blocked")
        self.assertFalse(ready)


class GlobalAbstractFillerQualityTests(unittest.TestCase):
    """Global items stacking abstract filler without concrete facts are low quality."""

    _METADATA = {
        "global_top5_selection": {"policy": "keysuri_global_top5_selection_v2_diversity"},
        "claims": [{"selection_score": 70, "selection_rationale": "test"}] * 5,
    }

    def test_abstract_filler_without_specifics_flagged(self) -> None:
        fixture = build_global_contract_fixture()
        item = fixture["top_5_items"][0]
        item["what_happened"] = (
            "이번 랜섬웨어 공격은 보안 업계에 많은 것을 시사합니다. "
            "방어 체계의 기반을 이해하는 데 필수적입니다. 관련 동향 파악이 중요합니다."
        )
        item["why_now"] = (
            "이 흐름은 산업 전반의 변화를 보여줍니다. 지금의 대응 태세가 중요합니다. "
            "생태계 협력을 촉진합니다."
        )
        item["owner_angle"] = (
            "보안 태세 점검이 필수적입니다. 이 신호는 많은 것을 시사합니다. "
            "흐름을 관찰하는 자세가 중요합니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html, source_metadata=self._METADATA)
        codes = {i.code for i in result.issues}
        self.assertIn("global_abstract_filler_no_specifics", codes)

    def test_abstract_filler_with_concrete_specifics_not_flagged(self) -> None:
        fixture = build_global_contract_fixture()
        item = fixture["top_5_items"][0]
        item["what_happened"] = (
            "공격 그룹 FIN12가 2026년 6월 이후 12개 기업을 노렸다는 점을 시사합니다. "
            "AI 도구로 침투 후 수동 암호화를 실행한 사실이 보고서에 담겼습니다. "
            "피해 규모는 약 4,000만 달러로 추산됩니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html, source_metadata=self._METADATA)
        codes = {i.code for i in result.issues}
        self.assertNotIn("global_abstract_filler_no_specifics", codes)

    def test_korea_items_not_subject_to_global_abstract_filler_gate(self) -> None:
        fixture = build_korea_contract_fixture()
        item = fixture["top_5_items"][0]
        item["what_happened"] = "이 신호는 많은 것을 시사합니다. 대응이 중요합니다."
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "x"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertNotIn("global_abstract_filler_no_specifics", codes)


class GlobalRepeatedCommonFillerQualityTests(unittest.TestCase):
    """Reusing the same category-generic filler sentence across TOP5 items is low quality."""

    _METADATA = {
        "global_top5_selection": {"policy": "keysuri_global_top5_selection_v2_diversity"},
        "claims": [{"selection_score": 70, "selection_rationale": "test"}] * 5,
    }

    _FILLER_AI_PLATFORM = "배포·워크플로·API 통제권 변화와 맞닿는 시점입니다."
    _FILLER_BROAD_MOVEMENT = (
        "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."
    )

    def test_filler_repeated_across_two_items_is_flagged(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"][:2]:
            item["why_now"] = (
                f"{self._FILLER_AI_PLATFORM} 이 항목은 배포 정책 변경과 직접 관련이 있습니다. "
                "구체적인 일정은 아직 공개되지 않았습니다."
            )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html, source_metadata=self._METADATA)
        codes = {i.code for i in result.issues}
        self.assertIn("global_repeated_common_filler", codes)

    def test_filler_used_once_is_not_flagged(self) -> None:
        fixture = build_global_contract_fixture()
        item = fixture["top_5_items"][0]
        item["why_now"] = (
            f"{self._FILLER_AI_PLATFORM} 이 항목은 배포 정책 변경과 직접 관련이 있습니다. "
            "구체적인 일정은 아직 공개되지 않았습니다."
        )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html, source_metadata=self._METADATA)
        codes = {i.code for i in result.issues}
        self.assertNotIn("global_repeated_common_filler", codes)

    def test_broad_movement_filler_repeated_is_flagged(self) -> None:
        fixture = build_global_contract_fixture()
        for item in fixture["top_5_items"][:3]:
            item["why_now"] = (
                f"{self._FILLER_BROAD_MOVEMENT} 이 항목의 개별 맥락은 후속 발표로 보완될 예정입니다."
            )
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_briefing_content_gate(html, source_metadata=self._METADATA)
        codes = {i.code for i in result.issues}
        self.assertIn("global_repeated_common_filler", codes)

    def test_korea_items_not_subject_to_global_filler_repeat_gate(self) -> None:
        fixture = build_korea_contract_fixture()
        for item in fixture["top_5_items"][:2]:
            item["why_now"] = self._FILLER_AI_PLATFORM
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        metadata = {"korea_top5_selection": {"policy": "x"}}
        result = validate_briefing_content_gate(html, source_metadata=metadata)
        codes = {i.code for i in result.issues}
        self.assertNotIn("global_repeated_common_filler", codes)


class GlobalPostRenderVisibleQualityWrapperTests(unittest.TestCase):
    """validate_global_post_render_visible_quality: public entry point for the
    real owner-review send path (keysuri_service_full_run.py).

    validate_briefing_content_gate's own filler-repeat check only sees item text
    via _extract_top_item_blocks()/_block_text(), which match the premium preview
    template's <article data-top-item>/<h4> markup — the Gmail-safe owner-review
    email template uses <p>-only markup and never matches that structure, so the
    same check would silently never fire on the real send path. This wrapper
    checks whole-plain-text occurrence counts instead, so it works on both.
    """

    _FILLER = "글로벌 테크는 AI만이 아니라 칩·인프라·로봇·에너지·정책이 함께 움직이는 날입니다."

    def test_flags_filler_repeated_in_p_only_gmail_style_html(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        html = (
            f"<p>항목1 본문입니다. {self._FILLER} 후속 확인이 필요합니다.</p>"
            f"<p>항목2 본문입니다. {self._FILLER} 후속 확인이 필요합니다.</p>"
        )
        result = validate_global_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn("global_repeated_common_filler", {i.code for i in result.issues})

    def test_single_use_in_p_only_html_not_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        html = f"<p>항목1 본문입니다. {self._FILLER} 후속 확인이 필요합니다.</p><p>항목2는 다른 내용입니다.</p>"
        result = validate_global_post_render_visible_quality(html)
        self.assertTrue(result.ok)
        self.assertNotIn("global_repeated_common_filler", {i.code for i in result.issues})

    def test_real_gmail_owner_email_html_with_repeated_filler_is_flagged(self) -> None:
        """Final Gmail owner-review email HTML (built by the real renderer function
        used in keysuri_service_full_run.py) must be caught by the wrapper."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_wrapper_test"
        for item in fixture["top_5_items"][:2]:
            item["why_now"] = (
                f"공식 발표와 비용 구조 변화가 겹치는 시점입니다. {self._FILLER} "
                "후속 가격·API 조건을 확인해야 합니다."
            )
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_wrapper_final_html",
            run_id="test_wrapper_final_html",
        )
        result = validate_global_post_render_visible_quality(email_html)
        self.assertFalse(result.ok)
        self.assertIn("global_repeated_common_filler", {i.code for i in result.issues})

    def test_clean_final_gmail_html_passes(self) -> None:
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_wrapper_clean"
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_wrapper_clean",
            run_id="test_wrapper_clean",
        )
        result = validate_global_post_render_visible_quality(email_html)
        self.assertTrue(result.ok, result.issues)


class GlobalPostRenderKnownArtifactDetectorTests(unittest.TestCase):
    """Known visible-text artifacts (signal-chip glue, badge glue, typo) must be
    caught by validate_global_post_render_visible_quality on the FINAL HTML —
    the same wrapper already wired into the real owner-review send path."""

    def test_signal_distribution_glue_zero_space_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        result = validate_global_post_render_visible_quality(
            "<p>사업 신호IEEE, 신규 표준 초안을 공개했습니다.</p>"
        )
        self.assertFalse(result.ok)
        self.assertIn(
            "global_signal_distribution_visible_text_broken", {i.code for i in result.issues}
        )

    def test_signal_distribution_glue_one_space_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        for html in (
            "<p>사업 신호 IEEE 표준 초안을 공개했습니다.</p>",
            "<p>활용 후보 구글 픽셀 11 공개.</p>",
            "<p>과장 주의 메타 신규 발표.</p>",
        ):
            with self.subTest(html=html):
                result = validate_global_post_render_visible_quality(html)
                self.assertFalse(result.ok)
                self.assertIn(
                    "global_signal_distribution_visible_text_broken",
                    {i.code for i in result.issues},
                )

    def test_badge_spacing_glue_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        for html in (
            "<p>키수리 판단 사업 신호AI 에이전트 전용 하드웨어 신호입니다.</p>",
            "<p>키수리 판단 활용 후보검증된 모델입니다.</p>",
            "<p>키수리 판단 관찰프리미엄 사양입니다.</p>",
        ):
            with self.subTest(html=html):
                result = validate_global_post_render_visible_quality(html)
                self.assertFalse(result.ok)
                self.assertIn(
                    "global_post_render_badge_spacing_broken",
                    {i.code for i in result.issues},
                )

    def test_typo_artifact_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        for html in (
            "<p>인프라 비용 구조를 살보면 됩니다.</p>",
            "<p>이 부분은 살보면 될 것 같습니다.</p>",
        ):
            with self.subTest(html=html):
                result = validate_global_post_render_visible_quality(html)
                self.assertFalse(result.ok)
                self.assertIn(
                    "global_visible_text_typo_artifact", {i.code for i in result.issues}
                )

    def test_properly_separated_badge_and_chip_text_not_flagged(self) -> None:
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        result = validate_global_post_render_visible_quality(
            "<p>키수리 판단 · 사업 신호 · AI 에이전트 전용 하드웨어 신호입니다.</p>"
            "<p>사업 신호 · 구글 픽셀 11 공개.</p>"
        )
        self.assertTrue(result.ok, result.issues)

    def test_default_global_gmail_email_has_no_known_artifacts(self) -> None:
        """Real renderer output (default fixture) must not false-positive."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_global_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import validate_global_post_render_visible_quality

        repo = Path(__file__).resolve().parents[1]
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_global_artifact_clean"
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_global_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Global Tech",
            admin_url="https://example.com/admin/runs/test_artifact_clean",
            run_id="test_artifact_clean",
        )
        result = validate_global_post_render_visible_quality(email_html)
        self.assertTrue(result.ok, result.issues)


class KoreaPostRenderVisibleQualityTests(unittest.TestCase):
    """validate_korea_post_render_visible_quality: Korea Tech counterpart of the
    global post-render wrapper, wired into the real owner-review send path.
    Targets the four visible defects observed in the 2026-07-08 Korea Tech
    production owner-review email."""

    @staticmethod
    def _strip_html(chips: list[str]) -> str:
        spans = " ".join(
            f'<span style="display:inline-block;border-radius:999px;">{chip}</span>'
            for chip in chips
        )
        return (
            "<p>오늘 국내에서 움직인 것</p>"
            "<p>오늘 한국 시장에서 돈·산업·정책이 움직인 축을 다섯 신호로 정리했습니다.</p>"
            f"{spans}"
            "<h2>국내 테크 TOP 5</h2><p>본문</p>"
        )

    def test_headline_fragment_chip_in_signal_strip_blocks(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = self._strip_html(
            ["삼성전자, '나를 아는 AI'가", "사업 신호", "사업 신호", "리스크 신호", "사업 신호"]
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn(
            "korea_signal_distribution_badge_fragment", {i.code for i in result.issues}
        )

    def test_taxonomy_only_signal_strip_passes(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = self._strip_html(["관찰", "사업 신호", "사업 신호", "리스크 신호", "과장 주의"])
        result = validate_korea_post_render_visible_quality(html)
        self.assertTrue(result.ok, result.issues)

    def test_top5_card_badges_after_strip_are_not_scanned(self) -> None:
        """Badges inside the TOP5 cards (e.g. '국내 적용') live outside the
        strip window and must not be misread as strip chips."""
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = (
            self._strip_html(["사업 신호", "리스크 신호"])
            + '<span style="border-radius:999px;">국내 적용</span>'
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertTrue(result.ok, result.issues)

    def test_double_ending_imperative_plus_bare_check_blocks(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        for text in (
            "국내 다른 대기업들의 AI 전략 발표와 방향성 변화를 비교 분석하세요 확인",
            "개인화된 AI 솔루션 개발 스타트업에 대한 투자 동향을 주시하세요 확인",
            "후속 일정을 점검하십시오 확인",
        ):
            with self.subTest(text=text):
                result = validate_korea_post_render_visible_quality(f"<li>{text}</li>")
                self.assertFalse(result.ok)
                self.assertIn(
                    "korea_visible_text_double_ending_artifact",
                    {i.code for i in result.issues},
                )

    def test_hamnida_yeobu_prose_glue_blocks(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        for text in (
            "SK하이닉스의 투자 계획 발표를 확인해야 합니다 여부",
            "수주 동향을 주시해야 합니다 여부",
            "관련 정책 일정을 점검해야 합니다 여부",
            "후속 확인이 필요합니다 여부",
        ):
            with self.subTest(text=text):
                result = validate_korea_post_render_visible_quality(f"<li>{text}</li>")
                self.assertFalse(result.ok)
                self.assertIn(
                    "korea_visible_text_hamnida_yeobu_artifact",
                    {i.code for i in result.issues},
                )

    def test_normal_observation_yeobu_and_imperative_pass_hamnida_gate(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        for text in (
            "공식 발표·가격·일정 공개 여부",
            "삼성전자 HBM4 후속 일정 여부",
            "현대차 노사 간 추가 교섭 일정 및 합의 여부를 최우선으로 확인하세요",
        ):
            with self.subTest(text=text):
                result = validate_korea_post_render_visible_quality(f"<li>{text}</li>")
                codes = {i.code for i in result.issues}
                self.assertNotIn("korea_visible_text_hamnida_yeobu_artifact", codes)

    def test_normal_imperative_and_normal_check_item_pass(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        for text in (
            "현대차 노사 간 추가 교섭 일정 및 합의 여부를 최우선으로 확인하세요",
            "삼성전자의 AI 서비스 로드맵 및 실제 제품 적용 사례 확인",
            "관련 공시를 먼저 확인하세요 확인이 필요한 항목은 별도로 표시했습니다",
        ):
            with self.subTest(text=text):
                result = validate_korea_post_render_visible_quality(f"<li>{text}</li>")
                self.assertTrue(result.ok, result.issues)

    def test_hold_field_copy_of_judgment_blocks(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        risk = (
            "국내 주요 대기업의 노사 갈등이 장기화되며 생산 차질 및 공급망 불안정성으로 "
            "이어질 수 있는 명확한 리스크 신호입니다."
        )
        html = (
            f"<p><strong>키수리 판단</strong> <span>리스크 신호</span> {risk}</p>"
            "<p><strong>내일 먼저 볼 것:</strong> 추가 교섭 일정 확인</p>"
            f"<p><strong>아직 단정하지 말 것:</strong> {risk}</p>"
            "<p>출처 ZDNet Korea</p>"
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn(
            "korea_hold_field_duplicate_judgment", {i.code for i in result.issues}
        )

    def test_default_hold_text_with_distinct_judgment_passes(self) -> None:
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = (
            "<p><strong>키수리 판단</strong> <span>사업 신호</span> "
            "국내 로봇 기업이 시장을 확대하는 구체적인 신호입니다.</p>"
            "<p><strong>내일 먼저 볼 것:</strong> 추가 수주 현황 확인</p>"
            "<p><strong>아직 단정하지 말 것:</strong> 숫자·일정이 확인되지 않은 기대감</p>"
            "<p>출처 로봇신문</p>"
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertTrue(result.ok, result.issues)

    def test_ungrounded_event_in_synthesis_blocks(self) -> None:
        """'방한' appearing in the market-judgment synthesis while no TOP5 card
        mentions it = background knowledge injected as today's signal."""
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = (
            "<h2>국내 테크 TOP 5</h2>"
            "<p>1. 삼성전자, AI 전략 발표</p><p>출처 삼성전자 뉴스룸</p>"
            "<h2>키수리의 시장 판단</h2>"
            "<p>오늘 다섯 신호를 하나로 보면, 엔비디아 방한 이슈를 축으로 움직이는 구조입니다.</p>"
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn(
            "korea_ungrounded_event_context", {i.code for i in result.issues}
        )

    def test_grounded_event_mentioned_by_top5_card_passes(self) -> None:
        """If a TOP5 card itself reports the visit, the synthesis may reference it."""
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        html = (
            "<h2>국내 테크 TOP 5</h2>"
            "<p>1. 젠슨 황 CEO 방한, 국내 반도체 협력 논의</p><p>출처 ZDNet Korea</p>"
            "<h2>키수리의 시장 판단</h2>"
            "<p>방한 이후 실제 계약이 따라오는지가 핵심입니다.</p>"
        )
        result = validate_korea_post_render_visible_quality(html)
        self.assertTrue(result.ok, result.issues)

    def test_ungrounded_event_check_skips_when_sections_missing(self) -> None:
        """Fragments without both section headings must not trip the net."""
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        result = validate_korea_post_render_visible_quality("<p>방한 관련 안내문</p>")
        self.assertTrue(result.ok, result.issues)

    def test_static_lesson_board_rendered_verbatim_blocks(self) -> None:
        from keysuri_briefing_content_quality import (
            KOREA_STATIC_LESSON_LEGACY_SENTENCES,
            validate_korea_post_render_visible_quality,
        )

        html = "".join(f"<p>{s}</p>" for s in KOREA_STATIC_LESSON_LEGACY_SENTENCES)
        result = validate_korea_post_render_visible_quality(html)
        self.assertFalse(result.ok)
        self.assertIn(
            "korea_static_lesson_section_overused", {i.code for i in result.issues}
        )

    def test_one_or_two_legacy_sentences_below_threshold_pass(self) -> None:
        from keysuri_briefing_content_quality import (
            KOREA_STATIC_LESSON_LEGACY_SENTENCES,
            validate_korea_post_render_visible_quality,
        )

        html = "".join(f"<p>{s}</p>" for s in KOREA_STATIC_LESSON_LEGACY_SENTENCES[:2])
        result = validate_korea_post_render_visible_quality(html)
        self.assertTrue(result.ok, result.issues)

    def test_clean_korea_final_gmail_email_html_passes(self) -> None:
        """Normal Korea fixture rendered through the REAL Gmail owner-email
        renderer (the exact function used on the send path) must pass."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import validate_korea_post_render_visible_quality

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_korea_qa_clean"
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_qa_clean",
            run_id="test_korea_qa_clean",
        )
        result = validate_korea_post_render_visible_quality(email_html)
        self.assertTrue(result.ok, result.issues)

    def test_korea_gmail_strip_never_renders_headline_fragment_chips(self) -> None:
        """Items whose judgment label is missing/관찰 must render a taxonomy chip
        (관찰), never a truncated headline fragment — the production defect."""
        from keysuri_contract_preview_renderer import (
            IMAGE_MODE_EMAIL,
            build_keysuri_korea_gmail_owner_email_html,
            prepare_contract_preview_fixture,
        )
        from keysuri_briefing_content_quality import (
            _korea_signal_strip_chip_texts,
            KOREA_SIGNAL_BADGE_ALLOWED_LABELS,
            validate_korea_post_render_visible_quality,
        )

        repo = Path(__file__).resolve().parents[1]
        fixture = build_korea_contract_fixture()
        fixture["top_shot_image_src"] = "cid:keysuri_topshot_korea_qa_chips"
        fixture["top_5_items"][0]["korean_title"] = "삼성전자, '나를 아는 AI'가 가장 중요하다고 강조"
        fixture["top_5_items"][0]["keysuri_judgment_label"] = "관찰"
        fixture["top_5_items"][1].pop("keysuri_judgment_label", None)
        prepare_contract_preview_fixture(fixture, repo_root=repo, image_mode=IMAGE_MODE_EMAIL)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            fixture,
            subject="[운영자 검토] Kee-Suri Korea Tech",
            admin_url="https://example.com/admin/runs/test_korea_qa_chips",
            run_id="test_korea_qa_chips",
        )
        chips = _korea_signal_strip_chip_texts(email_html)
        self.assertTrue(chips)
        for chip in chips:
            self.assertIn(chip, KOREA_SIGNAL_BADGE_ALLOWED_LABELS, chips)
        self.assertNotIn("삼성전자, '나를 아는 AI'가", email_html)
        result = validate_korea_post_render_visible_quality(email_html)
        self.assertTrue(result.ok, result.issues)


if __name__ == "__main__":
    unittest.main()
