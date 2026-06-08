"""Compatibility tests: owner-review renderer vs html_test contract-validation validator.

The owner-review renderer (`keysuri_renderer.render_keysuri_owner_review_html`) and the
html_test validator (`validate_keysuri_html_preview`) target different surfaces:

- Owner-review: operational preview with audit/status blocks for offline dry-run.
- html_test: contract-validation previews under output/keysuri_preview/html_test/ per
  KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md §15.

These tests document the current gap. They do not require the owner-review renderer to
pass the html_test validator until a dedicated contract preview renderer or a
contract-validation render mode is implemented.
"""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from keysuri_generated_briefing import load_keysuri_generated_briefing_fixture
from keysuri_html_preview_validation import validate_keysuri_html_preview
from keysuri_private_briefing import SECTION_DEEP_DIVE
from keysuri_renderer import load_keysuri_prompt_input_fixture, render_keysuri_owner_review_html

_REPO = Path(__file__).resolve().parent.parent

# Flip to True only after a contract-validation renderer path is implemented.
CONTRACT_PREVIEW_RENDERER_AVAILABLE = False


def _load_prompt(name: str) -> dict:
    return load_keysuri_prompt_input_fixture(str(_REPO / "ops" / "feeds" / name))


def _load_generated(name: str) -> dict:
    return load_keysuri_generated_briefing_fixture(str(_REPO / "ops" / "feeds" / name))


def _write_html_test_preview(tmp: Path, program: str, html: str) -> Path:
    target_dir = tmp / "output" / "keysuri_preview" / "html_test"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"keysuri_{program}_contract_compat_{stamp}.html"
    path = target_dir / filename
    path.write_text(html, encoding="utf-8")
    return path


def _write_owner_review_preview(tmp: Path, program: str, html: str) -> Path:
    target_dir = tmp / "output" / "keysuri_preview"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"keysuri_{program}_generated_owner_review_preview.html"
    path.write_text(html, encoding="utf-8")
    return path


class KeysuriRendererValidatorCompatTests(unittest.TestCase):
    """Owner-review renderer output is not html_test contract-validation compatible today."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.global_prompt = _load_prompt("keysuri_global_prompt_input.sample.json")
        cls.korea_prompt = _load_prompt("keysuri_korea_prompt_input.sample.json")
        cls.global_generated = _load_generated("keysuri_global_generated_briefing.sample.json")
        cls.korea_generated = _load_generated("keysuri_korea_generated_briefing.sample.json")

    def test_owner_review_global_html_fails_html_test_validator(self) -> None:
        html = render_keysuri_owner_review_html(self.global_prompt, self.global_generated)
        with TemporaryDirectory() as tmpdir:
            path = _write_html_test_preview(Path(tmpdir), "global", html)
            result = validate_keysuri_html_preview(str(path))

        self.assertFalse(result.is_pass(), "owner-review HTML must not pass html_test validator yet")
        self.assertEqual(result.validation_status, "FAIL")

        self.assertEqual(result.top5_sources, "FAIL")
        self.assertEqual(result.rights_policy, "FAIL")
        self.assertEqual(result.required_sections, "FAIL")
        self.assertEqual(result.deep_dive_readability, "FAIL")

        issue_codes = {issue.code for issue in result.issues}
        # Renderer uses news-card/data-rank, not data-top-item — validator sees zero TOP items.
        self.assertIn("top5_item_count_invalid", issue_codes)
        self.assertIn("rights_policy_missing", issue_codes)
        self.assertIn("deep_dive_layer_structure_missing", issue_codes)
        self.assertTrue(
            issue_codes
            & {
                "preview_metadata",
                "validation_result_box",
                "compliance_checklist",
                "operation_metadata",
            },
            msg=f"expected contract validation box / metadata issues, got {issue_codes}",
        )

    def test_owner_review_korea_html_fails_html_test_validator(self) -> None:
        html = render_keysuri_owner_review_html(self.korea_prompt, self.korea_generated)
        with TemporaryDirectory() as tmpdir:
            path = _write_html_test_preview(Path(tmpdir), "korea_1830", html)
            result = validate_keysuri_html_preview(
                str(path),
                program_id="keysuri_korea_tech",
            )

        self.assertFalse(result.is_pass())
        self.assertEqual(result.top5_sources, "FAIL")
        self.assertEqual(result.rights_policy, "FAIL")
        self.assertEqual(result.required_sections, "FAIL")

    def test_owner_review_html_lacks_contract_validation_markers(self) -> None:
        html = render_keysuri_owner_review_html(self.global_prompt, self.global_generated)

        self.assertIn("Owner Review Preview", html)
        self.assertIn("Source Gate / TOP 5 Selection Audit", html)
        self.assertIn("Today_Geenee", html)
        self.assertIn('class="news-card"', html)
        self.assertNotIn('data-top-item="1"', html)
        self.assertNotIn('id="validation-result-box"', html)
        self.assertNotIn("Copyright Ⓒ MirAI:ON. All rights reserved.", html)
        self.assertNotIn('class="deep-layer"', html)

        if SECTION_DEEP_DIVE in html:
            self.assertNotRegex(html, r'deep-layer-number|deep-layer-title')

    def test_owner_review_scheduler_table_may_fail_no_production_implication(self) -> None:
        html = render_keysuri_owner_review_html(self.global_prompt, self.global_generated)
        with TemporaryDirectory() as tmpdir:
            contract_path = _write_html_test_preview(Path(tmpdir), "global", html)
            contract_result = validate_keysuri_html_preview(str(contract_path))

        self.assertEqual(contract_result.validation_profile, "contract_preview")
        self.assertEqual(contract_result.no_production_implication, "FAIL")
        issue_codes = {issue.code for issue in contract_result.issues}
        self.assertIn("forbidden_today_geenee", issue_codes)

        with TemporaryDirectory() as tmpdir:
            owner_path = _write_owner_review_preview(Path(tmpdir), "global", html)
            owner_result = validate_keysuri_html_preview(str(owner_path), profile="owner_review")

        self.assertEqual(owner_result.validation_profile, "owner_review")
        self.assertTrue(owner_result.is_pass(), owner_result.issues)
        self.assertEqual(owner_result.no_production_implication, "PASS")

    def test_owner_review_global_html_passes_owner_review_profile(self) -> None:
        html = render_keysuri_owner_review_html(self.global_prompt, self.global_generated)
        with TemporaryDirectory() as tmpdir:
            path = _write_owner_review_preview(Path(tmpdir), "global", html)
            result = validate_keysuri_html_preview(str(path), profile="owner_review")

        self.assertTrue(result.is_pass(), result.issues)
        self.assertEqual(result.validation_profile, "owner_review")
        self.assertEqual(result.deep_dive_readability, "SKIP")
        self.assertEqual(result.rights_policy, "SKIP")

    def test_surfaces_are_documented_as_separate(self) -> None:
        """Owner-review renderer is not the html_test contract-validation preview."""
        owner_html = render_keysuri_owner_review_html(self.global_prompt, self.global_generated)

        owner_markers = (
            "Owner Review Preview",
            "Review Status &amp; Guardrails",
            "Active scheduler (GENIE)",
        )
        contract_markers = (
            'id="preview-metadata"',
            'id="validation-result-box"',
            "Contract compliance checklist",
        )

        for marker in owner_markers:
            self.assertIn(marker, owner_html)
        for marker in contract_markers:
            self.assertNotIn(marker, owner_html)

        self.assertTrue(
            CONTRACT_PREVIEW_RENDERER_AVAILABLE is False,
            "contract-validation renderer not implemented; use manual html_test previews or "
            "add render_keysuri_contract_preview_html() later",
        )


class KeysuriRendererValidatorFutureDirectionTests(unittest.TestCase):
    """Future direction: dedicated contract preview renderer or contract-validation mode."""

    @unittest.expectedFailure
    def test_owner_review_renderer_eventually_needs_contract_mode_or_separate_renderer(self) -> None:
        """Documents intended future compatibility — fails until implemented.

        When either:
        - a dedicated contract preview renderer writes html_test previews, or
        - owner-review renderer gains an explicit contract-validation mode,

        rendered output placed under output/keysuri_preview/html_test/ with a timestamped
        filename should pass validate_keysuri_html_preview().
        """
        if not CONTRACT_PREVIEW_RENDERER_AVAILABLE:
            self.fail(
                "Gap documented: owner-review renderer != html_test contract-validation "
                "preview. Implement a dedicated contract preview renderer or add "
                "contract-validation mode before expecting PASS."
            )

        prompt = _load_prompt("keysuri_global_prompt_input.sample.json")
        generated = _load_generated("keysuri_global_generated_briefing.sample.json")
        html = render_keysuri_owner_review_html(prompt, generated)

        with TemporaryDirectory() as tmpdir:
            path = _write_html_test_preview(Path(tmpdir), "global", html)
            result = validate_keysuri_html_preview(str(path))

        self.assertTrue(result.is_pass())


if __name__ == "__main__":
    unittest.main()
