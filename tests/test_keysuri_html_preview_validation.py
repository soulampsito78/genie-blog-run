"""Tests for Kee-Suri HTML preview validator (read-only)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keysuri_html_preview_validation import validate_keysuri_html_preview

_REPO = Path(__file__).resolve().parent.parent
_CLI = _REPO / "scripts" / "validate_keysuri_html_preview.py"


def _top_item(rank: int, *, with_url: bool = True) -> str:
    url_line = (
        'URL: <a href="https://example.com/sample">https://example.com/sample</a><br>'
        if with_url
        else "URL: (missing)<br>"
    )
    return f"""
      <article class="top-item" data-top-item="{rank}">
        <h3>{rank}. Sample headline</h3>
        <div class="source-box">
          출처명: Sample Source {rank}<br>
          {url_line}
          검증 상태: sample_only / not_verified
        </div>
      </article>
    """


def _deep_dive_layers() -> str:
    return """
    <section id="deep-dive-section">
      <h2 class="section-heading">키수리의 딥-다이브</h2>
      <div class="deep-layer">
        <span class="deep-layer-number">1</span>
        <div class="deep-layer-title">물리·인프라 병목</div>
        <div class="deep-layer-body"><p>Layer one body with enough content to exceed density threshold when combined with other layers and opening text in this section for validation purposes.</p></div>
      </div>
      <div class="deep-layer">
        <span class="deep-layer-number">2</span>
        <div class="deep-layer-title">규제·주권·조달 압력</div>
        <div class="deep-layer-body"><p>Layer two body with policy and sovereignty pressure notes for readability validation.</p></div>
      </div>
      <div class="deep-layer">
        <span class="deep-layer-number">3</span>
        <div class="deep-layer-title">워크플로·락인</div>
        <div class="deep-layer-body"><p>Layer three body with workflow lock-in notes and watch question.</p></div>
      </div>
    </section>
    """


def _deep_dive_dense_block() -> str:
    return """
    <section id="deep-dive-section">
      <h2 class="section-heading">키수리의 딥-다이브</h2>
      <p>One dense paragraph without layer structure that keeps growing long enough to trigger the dense-analysis readability rule in the validator because it lacks cards separators or numbered headings for mobile readability in Kee-Suri previews and should fail when no 1/2/3 structure exists anywhere in this deep dive block for HTML preview validation tests.</p>
      <p>Second long paragraph continues the dense block pattern without any deep-layer card markup so the validator can detect a single dense wall of text instead of layered readability structure required by the Kee-Suri contract for dense analysis sections in preview HTML files under html_test.</p>
      <p>Third paragraph adds more density to ensure threshold logic treats this region as dense enough to require explicit 1/2/3 layer formatting rather than a single continuous block of prose in the deep dive section for Korea and global preview validation.</p>
    </section>
    """


def _rights_policy() -> str:
    return """
    <div class="rights-policy" id="rights-policy">
      <p>Copyright Ⓒ MirAI:ON. All rights reserved.</p>
      <p>무단 전재, 재배포 및 AI학습 이용 절대 금지</p>
    </div>
    """


def _tail_boxes(*, claimed_status: str = "PASS") -> str:
    return f"""
    <div class="op-meta" id="operation-metadata"><strong>Operation metadata (server-rendered only)</strong></div>
    <div class="compliance-box" id="compliance-checklist"><strong>Contract compliance checklist</strong></div>
    <div class="validation-box pass" id="validation-result-box">
      <strong>Validation result</strong>
      <div class="validation-status pass">validation_status: {claimed_status}</div>
    </div>
    """


def build_preview_html(
    *,
    program: str = "korea",
    include_korea_tail: bool = True,
    top_items: str | None = None,
    deep_dive: str | None = None,
    rights: str | None = None,
    extra_body: str = "",
    claimed_status: str = "PASS",
    wrong_order: bool = False,
    slot_metadata: str = "",
) -> str:
    top5_heading = "국내 테크 TOP 5" if program == "korea" else "글로벌 테크 TOP 5"
    if top_items is None:
        top_items = "".join(_top_item(i) for i in range(1, 6))
    if deep_dive is None:
        deep_dive = _deep_dive_layers()
    if rights is None:
        rights = _rights_policy()

    warm_close = ""
    bottom_shot = ""
    if include_korea_tail and program == "korea":
        bottom_shot = """
        <div class="placeholder small" id="bottom-shot-placeholder">18:30 bottom-shot preview placeholder</div>
        """
        warm_close = """
        <section id="closing-section">
          <h2>퇴근 전 메모</h2>
          <div class="evening-memo-body">
            <p>오늘은 국내 테크 핵심 이슈가 HBM·파운드리·국내 AI 투자 흐름을 한 번에 묶었습니다.</p>
            <p>내일은 세 가지만 확인하시면 됩니다.</p>
            <ol class="evening-memo-actions">
              <li>삼성전자·SK하이닉스 쪽 HBM4 협력 후속</li>
              <li>GPU 우선 공급 약속의 실제 대상과 일정</li>
            </ol>
            <p>확정되지 않은 수치와 일정은 아직 조심해서 보겠습니다.</p>
            <p class="closing-message warm-farewell">오늘도 수고 많으셨습니다.</p>
            <p class="closing-message warm-farewell">내일 아침에 다시 볼 흐름만 남겨두겠습니다.</p>
          </div>
        </section>
        """
    closing = """
    <section id="closing-section">
      <h2 class="section-heading">마무리 및 출처 리스트</h2>
      <p>Closing message sample.</p>
    </section>
    """
    checkpoint = """
    <section>
      <h2 class="section-heading">원-라인 체크포인트</h2>
      <div class="checkpoint">Decision cue sample.</div>
    </section>
    """

    if wrong_order:
        ordered_tail = warm_close + bottom_shot + checkpoint + closing + rights + _tail_boxes(claimed_status=claimed_status)
    else:
        ordered_tail = checkpoint + bottom_shot + warm_close + closing + rights + _tail_boxes(claimed_status=claimed_status)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>Preview</title></head>
<body>
  <div class="preview-banner">PREVIEW ONLY</div>
  <div class="meta-box" id="preview-metadata"><strong>Preview metadata</strong>{slot_metadata}</div>
  <p class="identity">테크 비서 키수리</p>
  <section id="top5-section">
    <h2 class="section-heading">{top5_heading}</h2>
    {top_items}
  </section>
  {deep_dive}
  {ordered_tail}
  {extra_body}
</body>
</html>
"""


def _write_preview(tmp: Path, name: str, html: str) -> Path:
    target_dir = tmp / "output" / "keysuri_preview" / "html_test"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_text(html, encoding="utf-8")
    return path


def _write_owner_review(tmp: Path, name: str, html: str) -> Path:
    target_dir = tmp / "output" / "keysuri_preview"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_text(html, encoding="utf-8")
    return path


def build_owner_review_html(*, extra_body: str = "", program: str = "global") -> str:
    top5_heading = "국내 테크 TOP 5" if program == "korea" else "글로벌 테크 TOP 5"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>Owner Review</title></head>
<body>
  <section class="notice" role="note">
    <p><strong>Owner-review 사전 검토 화면</strong></p>
    <ul>
      <li>이 화면은 테크 비서 키수리의 owner-review용 사전 검토 화면입니다.</li>
      <li>아직 고객에게 발송되지 않았습니다.</li>
      <li>최종 고객 발송 문안이 아니며 owner-review 검수용입니다.</li>
    </ul>
  </section>
  <header><h1>테크 비서 키수리</h1></header>
  <section><h2 class="top5-section-heading">{top5_heading}</h2></section>
  <section class="card audit-section" id="audit">
    <h2>Source Gate / TOP 5 Selection Audit</h2>
  </section>
  <section class="card status-section" id="status">
    <h3>Forbidden outputs / guardrails</h3>
    <ul class='forbidden-list'><li>Today_Geenee HTML email body</li></ul>
    <h3>Active scheduler (GENIE)</h3>
    <ul class='scheduler-list'><li><strong>Today_Geenee</strong> — 06:30 KST</li></ul>
  </section>
  {extra_body}
  <footer class="footer"><p>Owner Review Preview</p></footer>
</body>
</html>
"""


class KeysuriHtmlPreviewValidationTests(unittest.TestCase):
    def test_minimal_pass_korea_1830_preview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_sample_20260605_130000.html",
                build_preview_html(program="korea"),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertTrue(result.is_pass())
            self.assertEqual(result.warm_close_order, "PASS")
            self.assertEqual(result.claimed_pass_consistency, "PASS")

    def test_minimal_pass_global_preview(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_global_1230_sample_20260605_130000.html",
                build_preview_html(program="global", include_korea_tail=False),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertTrue(result.is_pass())
            self.assertEqual(result.warm_close_order, "SKIP")

    def test_timestamp_1830_suffix_does_not_trigger_korea_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_global_sample_20260605_183045.html",
                build_preview_html(program="global", include_korea_tail=False),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertEqual(result.warm_close_order, "SKIP")

    def test_explicit_korea_1830_filename_triggers_order_checks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_sample_20260605_183045.html",
                build_preview_html(program="korea"),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertEqual(result.warm_close_order, "PASS")

    def test_program_id_with_slot_metadata_triggers_korea_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_sample_20260605_130010.html",
                build_preview_html(
                    program="korea",
                    slot_metadata='<span>slot: 18:30</span>',
                ),
            )
            result = validate_keysuri_html_preview(str(path), program_id="keysuri_korea_tech")
            self.assertEqual(result.warm_close_order, "PASS")

    def test_program_id_without_slot_evidence_skips_korea_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_sample_20260605_130011.html",
                build_preview_html(program="korea"),
            )
            result = validate_keysuri_html_preview(str(path), program_id="keysuri_korea_tech")
            self.assertEqual(result.warm_close_order, "SKIP")

    def test_missing_source_url_fail(self) -> None:
        broken_items = "".join(_top_item(i, with_url=(i != 3)) for i in range(1, 6))
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_missing_url_20260605_130001.html",
                build_preview_html(program="korea", top_items=broken_items),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.top5_sources, "FAIL")

    def test_missing_rights_policy_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_no_rights_20260605_130002.html",
                build_preview_html(program="korea", rights=""),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.rights_policy, "FAIL")

    def test_hashtag_section_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_hashtag_20260605_130003.html",
                build_preview_html(
                    program="korea",
                    extra_body='<section class="hashtag-section"><h2>해시태그</h2><ul class="hashtag-list"><li>#키수리</li></ul></section>',
                ),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.no_hashtags, "FAIL")

    def test_wrong_korea_warm_close_order_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_bad_order_20260605_130004.html",
                build_preview_html(program="korea", wrong_order=True),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.warm_close_order, "FAIL")

    def test_scheduler_ready_true_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_scheduler_true_20260605_130005.html",
                build_preview_html(program="korea", extra_body='<span>scheduler_ready: true</span>'),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.no_production_implication, "FAIL")

    def test_production_ready_true_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_production_true_20260605_130006.html",
                build_preview_html(program="korea", extra_body='"production_ready": true'),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.no_production_implication, "FAIL")

    def test_dense_deep_dive_without_layers_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_dense_block_20260605_130007.html",
                build_preview_html(program="korea", deep_dive=_deep_dive_dense_block()),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.deep_dive_readability, "FAIL")

    def test_claimed_pass_but_actual_fail(self) -> None:
        broken_items = "".join(_top_item(i, with_url=False) for i in range(1, 6))
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_claimed_pass_20260605_130008.html",
                build_preview_html(program="korea", top_items=broken_items, claimed_status="PASS"),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertFalse(result.is_pass())
            self.assertEqual(result.claimed_pass_consistency, "FAIL")
            codes = {issue.code for issue in result.issues}
            self.assertIn("claimed_pass_mismatch", codes)

    def test_cli_returns_non_zero_for_failing_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_preview(
                Path(tmpdir),
                "keysuri_korea_1830_cli_fail_20260605_130009.html",
                build_preview_html(program="korea", rights=""),
            )
            proc = subprocess.run(
                [sys.executable, str(_CLI), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["validation_status"], "FAIL")

    def test_contract_preview_profile_requires_html_test_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_owner_review_preview.html",
                build_owner_review_html(),
            )
            result = validate_keysuri_html_preview(str(path), profile="contract_preview")
            self.assertFalse(result.is_pass())
            self.assertEqual(result.validation_profile, "contract_preview")
            codes = {issue.code for issue in result.issues}
            self.assertIn("file_path_not_html_test_dir", codes)

    def test_owner_review_profile_passes_with_disclosure_today_geenee(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_generated_owner_review_preview.html",
                build_owner_review_html(),
            )
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertTrue(result.is_pass(), result.issues)
            self.assertEqual(result.validation_profile, "owner_review")
            self.assertEqual(result.no_production_implication, "PASS")

    def test_owner_review_profile_fails_body_today_geenee_contamination(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_generated_owner_review_preview.html",
                build_owner_review_html(extra_body="<p>Today_Geenee leaked into body</p>"),
            )
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertFalse(result.is_pass())
            self.assertEqual(result.no_production_implication, "FAIL")
            codes = {issue.code for issue in result.issues}
            self.assertTrue(
                codes & {"forbidden_today_geenee", "forbidden_today_geenee_body"},
                msg=f"expected Today_Geenee body contamination issue, got {codes}",
            )

    def test_owner_review_profile_fails_review_passed_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_generated_owner_review_preview.html",
                build_owner_review_html(extra_body='<span class="badge">review_passed</span>'),
            )
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertFalse(result.is_pass())
            self.assertEqual(result.claimed_pass_consistency, "FAIL")
            codes = {issue.code for issue in result.issues}
            self.assertIn("forbidden_review_passed", codes)

    def test_owner_review_profile_fails_sent_archived_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_generated_owner_review_preview.html",
                build_owner_review_html(extra_body="<p>sent_archived: true</p>"),
            )
            result = validate_keysuri_html_preview(str(path), profile="owner_review")
            self.assertFalse(result.is_pass())
            self.assertEqual(result.claimed_pass_consistency, "FAIL")
            codes = {issue.code for issue in result.issues}
            self.assertIn("forbidden_sent_archived", codes)

    def test_owner_review_auto_detect_from_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review(
                Path(tmpdir),
                "keysuri_global_offline_dry_run_preview.html",
                build_owner_review_html(),
            )
            result = validate_keysuri_html_preview(str(path))
            self.assertEqual(result.validation_profile, "owner_review")
            self.assertTrue(result.is_pass(), result.issues)


if __name__ == "__main__":
    unittest.main()
