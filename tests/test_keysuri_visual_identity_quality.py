"""Tests for Kee-Suri visual identity quality gate."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from keysuri_visual_identity_quality import MANUAL_VISUAL_CHECKS, validate_visual_identity_gate
from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

_REPO = Path(__file__).resolve().parent.parent


class KeysuriVisualIdentityGateTests(unittest.TestCase):
    def _html(self) -> str:
        return render_keysuri_contract_preview_html(build_global_contract_fixture(), repo_root=_REPO)

    def test_never_pass_without_owner_approval_on_generated_test(self) -> None:
        html = self._html()
        with TemporaryDirectory() as tmpdir:
            manifest = {
                "image_source": "generated_test",
                "image_role": "top_shot",
                "width": 1280,
                "height": 720,
                "aspect_ratio": 1.78,
                "overlay_applied": True,
                "watermark": "MirAI:ON applied",
                "reference_image_path": "assets/ref.png",
                "reference_image_sha256": "deadbeef",
                "batch_id": "batch_x",
                "selected_candidate_id": "c1",
                "quality_verdict": "pass",
                "owner_visual_review_required": True,
            }
            path = Path(tmpdir) / "m.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_visual_identity_gate(html, manifest_path=str(path))
            self.assertEqual(result.status, "manual_review_required")

    def test_pass_only_with_owner_approval_and_quality_pass(self) -> None:
        html = self._html()
        with TemporaryDirectory() as tmpdir:
            manifest = {
                "image_source": "generated_test",
                "image_role": "top_shot",
                "width": 1280,
                "height": 720,
                "aspect_ratio": 1.78,
                "overlay_applied": True,
                "watermark": "MirAI:ON applied",
                "reference_image_path": "assets/ref.png",
                "reference_image_sha256": "deadbeef",
                "batch_id": "batch_x",
                "selected_candidate_id": "c1",
                "quality_verdict": "pass",
            }
            path = Path(tmpdir) / "m.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_visual_identity_gate(
                html,
                manifest_path=str(path),
                owner_visual_approved=True,
            )
            self.assertEqual(result.status, "pass")

    def test_square_hero_without_approval_fails(self) -> None:
        html = self._html()
        with TemporaryDirectory() as tmpdir:
            manifest = {
                "image_source": "generated_test",
                "image_role": "top_shot",
                "width": 1024,
                "height": 1024,
                "overlay_applied": True,
                "watermark": "MirAI:ON applied",
                "reference_image_path": "assets/ref.png",
                "reference_image_sha256": "deadbeef",
                "batch_id": "batch_x",
                "selected_candidate_id": "c1",
                "quality_verdict": "pass",
            }
            path = Path(tmpdir) / "m.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_visual_identity_gate(html, manifest_path=str(path))
            self.assertEqual(result.status, "fail")
            self.assertTrue(any(i.code == "square_hero_without_approval" for i in result.issues))

    def test_manual_visual_checklist_complete(self) -> None:
        self.assertGreaterEqual(len(MANUAL_VISUAL_CHECKS), 8)
        joined = " ".join(MANUAL_VISUAL_CHECKS).lower()
        self.assertIn("glasses", joined)
        self.assertIn("watermark", joined.lower())

    def test_bottom_shot_manifest_blocks_global_top_role(self) -> None:
        html = self._html()
        with TemporaryDirectory() as tmpdir:
            manifest = {
                "image_role": "bottom_shot",
                "width": 896,
                "height": 1152,
                "overlay_applied": True,
                "watermark_text": "MirAI:ON",
                "review_status": "pass_direction",
            }
            path = Path(tmpdir) / "m.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_visual_identity_gate(
                html,
                manifest_path=str(path),
                program_id="keysuri_global_tech",
                requested_role="global_top",
            )
            self.assertEqual(result.status, "fail")
            self.assertTrue(any(i.code == "manifest_role_conflict" for i in result.issues))


if __name__ == "__main__":
    unittest.main()
