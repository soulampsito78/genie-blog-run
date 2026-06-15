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


if __name__ == "__main__":
    unittest.main()
