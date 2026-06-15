"""Tests for Kee-Suri approved image asset registry."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keysuri_approved_image_assets import (
    GLOBAL_TOP_ROLE,
    KOREA_BOTTOM_ROLE,
    KOREA_TOP_ROLE,
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    classify_image_selection,
    is_korea_bottom_sha256,
    match_registry_asset,
    resolve_approved_asset,
    resolve_approved_hero_asset,
    resolve_approved_hero_image_path,
    resolve_korea_bottom_asset,
)
from keysuri_contract_preview_renderer import render_keysuri_contract_preview_html
from keysuri_visual_identity_quality import validate_visual_identity_gate
from tests.test_keysuri_contract_preview_renderer import build_global_contract_fixture

_REPO = Path(__file__).resolve().parent.parent
_GLOBAL_TOP = _REPO / (
    "output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg"
)
_GLOBAL_TOP_WM = _REPO / (
    "output/keysuri_preview/image_canary/"
    "keysuri_global_canary_20260604_221233_mirai_on_watermarked.jpg"
)
_GLOBAL_TOP_MANIFEST = _REPO / (
    "output/keysuri_preview/image_canary/"
    "keysuri_global_canary_20260604_221233_mirai_on_watermarked.manifest.json"
)
_KOREA_TOP = _REPO / (
    "output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg"
)
_KOREA_BOTTOM = _REPO / (
    "output/keysuri_preview/image_canary/keysuri_global_canary_20260605_105936.jpg"
)
_KOREA_BOTTOM_WM = _REPO / (
    "output/keysuri_preview/image_canary/"
    "keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg"
)
_BOTTOM_MANIFEST = _REPO / (
    "output/keysuri_preview/image_canary/"
    "keysuri_global_canary_20260605_105936_mirai_on_watermarked.manifest.json"
)
_REGISTRY = _REPO / "assets/keysuri/keysuri_approved_image_assets.json"
_R6B_PROMOTION_CHECKLIST = _REPO / "docs/keysuri/KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md"
_R6B_OFFDUTY_DECISION = _REPO / "docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md"
_TITLE_BODY_CONTRACT = _REPO / "docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md"


def _write_minimal_registry(repo: Path, *, file_path: str, sha256: str, role: str = GLOBAL_TOP_ROLE) -> None:
    registry_dir = repo / "assets" / "keysuri"
    registry_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "keysuri_approved_image_assets_v1",
        "assets": [
            {
                "asset_id": "test_locked",
                "persona": "keysuri",
                "program": PROGRAM_GLOBAL,
                "slot": "12:30",
                "role": role,
                "status": "approved_locked",
                "file_path": file_path,
                "manifest_path": None,
                "sha256": sha256,
                "width": 100,
                "height": 120,
                "watermark_status": "no_watermark_or_pending_watermark",
                "approved_for": ["contract_preview"],
                "source_type": "locked_canary",
                "approved_at": "2026-06-08T00:00:00+09:00",
                "approval_note": "test",
                "replacement_policy": "test only",
            }
        ],
    }
    (registry_dir / "keysuri_approved_image_assets.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


class KeysuriApprovedImageAssetRegistryTests(unittest.TestCase):
    def test_resolve_approved_hero_asset_by_sha256(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            img = repo / "hero.jpg"
            img.write_bytes(b"approved-hero-bytes")
            sha = hashlib.sha256(img.read_bytes()).hexdigest()
            _write_minimal_registry(repo, file_path="hero.jpg", sha256=sha)
            asset = resolve_approved_hero_asset(repo, PROGRAM_GLOBAL)
            self.assertEqual(asset.asset_id, "test_locked")
            self.assertEqual(resolve_approved_hero_image_path(repo, PROGRAM_GLOBAL), img.resolve())

    def test_classify_explicit_override_not_in_registry(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            approved = repo / "hero.jpg"
            approved.write_bytes(b"approved")
            sha = hashlib.sha256(approved.read_bytes()).hexdigest()
            _write_minimal_registry(repo, file_path="hero.jpg", sha256=sha)
            candidate = repo / "candidate.jpg"
            candidate.write_bytes(b"candidate-only")
            mode = classify_image_selection(
                repo,
                candidate,
                PROGRAM_GLOBAL,
                explicit_override=True,
            )
            self.assertEqual(mode, "explicit_test_override")

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    @unittest.skipUnless(_GLOBAL_TOP.is_file(), "global top asset missing")
    @unittest.skipUnless(_GLOBAL_TOP_WM.is_file(), "global top watermarked asset missing")
    def test_global_top_resolves_to_221233_watermarked(self) -> None:
        asset = resolve_approved_hero_asset(_REPO, PROGRAM_GLOBAL, role=GLOBAL_TOP_ROLE)
        path = resolve_approved_hero_image_path(_REPO, PROGRAM_GLOBAL, role=GLOBAL_TOP_ROLE)
        self.assertEqual(asset.asset_id, "keysuri_global_top_20260604_221233")
        self.assertEqual(path.resolve(), _GLOBAL_TOP_WM.resolve())
        self.assertNotEqual(path.resolve(), _GLOBAL_TOP.resolve())

    @unittest.skipUnless(_GLOBAL_TOP_MANIFEST.is_file(), "global top manifest missing")
    def test_global_top_manifest_has_global_top_role(self) -> None:
        manifest = json.loads(_GLOBAL_TOP_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("asset_id"), "keysuri_global_top_20260604_221233")
        self.assertEqual(manifest.get("image_role"), "global_top")
        self.assertTrue(manifest.get("overlay_applied"))
        self.assertFalse(manifest.get("image_api_called"))

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    @unittest.skipUnless(_KOREA_TOP.is_file(), "korea top asset missing")
    def test_korea_top_resolves_to_225207(self) -> None:
        asset = resolve_approved_asset(_REPO, PROGRAM_KOREA, role=KOREA_TOP_ROLE)
        self.assertEqual(asset.asset_id, "keysuri_korea_top_20260604_225207")
        self.assertEqual(asset.resolved_file_path(_REPO).resolve(), _KOREA_TOP.resolve())

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    @unittest.skipUnless(_KOREA_BOTTOM.is_file(), "korea bottom asset missing")
    def test_korea_bottom_resolves_to_105936(self) -> None:
        asset = resolve_korea_bottom_asset(_REPO)
        self.assertEqual(asset.asset_id, "keysuri_korea_bottom_20260605_105936")
        self.assertEqual(asset.resolved_file_path(_REPO).resolve(), _KOREA_BOTTOM.resolve())
        self.assertEqual(asset.role, KOREA_BOTTOM_ROLE)
        self.assertEqual(asset.image_role, "bottom_shot")
        self.assertEqual(asset.status, "approved_direction_locked")
        self.assertIn("owner_review_preview", asset.approved_for)
        self.assertIn("korea_bottom_preview", asset.approved_for)
        self.assertEqual(
            asset.gcs_object,
            "assets/keysuri/korea_bottom/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg",
        )

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    def test_korea_bottom_105936_owner_review_only_registry_policy(self) -> None:
        registry = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        policy = registry.get("policy", {})
        asset = next(
            item
            for item in registry.get("assets", [])
            if item.get("asset_id") == "keysuri_korea_bottom_20260605_105936"
        )

        self.assertEqual(asset.get("role"), KOREA_BOTTOM_ROLE)
        self.assertEqual(asset.get("image_role"), "bottom_shot")
        self.assertEqual(asset.get("status"), "approved_direction_locked")
        self.assertEqual(asset.get("approved_for"), ["owner_review_preview", "korea_bottom_preview"])
        self.assertFalse(policy.get("image_generation_default"))
        self.assertTrue(policy.get("image_refresh_frozen"))
        self.assertTrue(policy.get("promotion_required_for_new_asset"))
        self.assertTrue(policy.get("global_top_cannot_fallback_to_bottom_shot"))

    @unittest.skipUnless(_R6B_PROMOTION_CHECKLIST.is_file(), "promotion checklist not present")
    @unittest.skipUnless(_R6B_OFFDUTY_DECISION.is_file(), "offduty decision not present")
    @unittest.skipUnless(_TITLE_BODY_CONTRACT.is_file(), "title/body contract not present")
    def test_korea_bottom_105936_docs_record_owner_review_only_state(self) -> None:
        docs = "\n".join(
            [
                _R6B_PROMOTION_CHECKLIST.read_text(encoding="utf-8"),
                _R6B_OFFDUTY_DECISION.read_text(encoding="utf-8"),
                _TITLE_BODY_CONTRACT.read_text(encoding="utf-8"),
            ]
        )
        required_policy_markers = [
            "owner_review_email_attachment_ready=true",
            "customer_email_attachment_ready=false",
            "scheduler_variation_ready=false",
            "production_prompt_default=false",
            "generated_variation_allowed=false",
            "KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED=false",
            "105936` is the direction reference",
            "temporary",
            "role=korea_bottom only",
        ]
        for marker in required_policy_markers:
            self.assertIn(marker, docs)

        forbidden_ready_markers = [
            "customer_email_attachment_ready=true",
            "scheduler_variation_ready=true",
            "production_prompt_default=true",
            "generated_variation_allowed=true",
        ]
        for marker in forbidden_ready_markers:
            self.assertNotIn(marker, docs)

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    @unittest.skipUnless(_GLOBAL_TOP.is_file(), "global top missing")
    @unittest.skipUnless(_GLOBAL_TOP_WM.is_file(), "global top watermarked missing")
    @unittest.skipUnless(_KOREA_BOTTOM_WM.is_file(), "korea bottom watermarked missing")
    def test_global_top_must_not_resolve_to_105936(self) -> None:
        path = resolve_approved_hero_image_path(_REPO, PROGRAM_GLOBAL, role=GLOBAL_TOP_ROLE)
        self.assertEqual(path.resolve(), _GLOBAL_TOP_WM.resolve())
        self.assertIsNone(
            match_registry_asset(
                _REPO,
                _KOREA_BOTTOM_WM,
                PROGRAM_GLOBAL,
                role=GLOBAL_TOP_ROLE,
            )
        )

    def test_is_korea_bottom_sha256(self) -> None:
        self.assertTrue(is_korea_bottom_sha256("2792aca4c5d1011e822d563ddd7108e6c96c45fa56766d4368ac65af26f7370c"))
        self.assertTrue(is_korea_bottom_sha256("c6209f406717aa68ef8be70fbfd9dbc30b882e9fae800633d570111bb1b3faf9"))
        self.assertFalse(is_korea_bottom_sha256("c27ec0bf215fd11de9bdcd0e745385048df90caa27f2cefe0244b41c68292f33"))

    @unittest.skipUnless(_GLOBAL_TOP.is_file(), "global top missing")
    @unittest.skipUnless(_BOTTOM_MANIFEST.is_file(), "bottom manifest missing")
    def test_manifest_bottom_shot_cannot_pass_as_global_top(self) -> None:
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_path"] = str(_KOREA_BOTTOM_WM)
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_visual_identity_gate(
            html,
            image_path=str(_KOREA_BOTTOM_WM),
            manifest_path=str(_BOTTOM_MANIFEST),
            program_id=PROGRAM_GLOBAL,
            repo_root=_REPO,
            requested_role=GLOBAL_TOP_ROLE,
        )
        self.assertEqual(result.status, "fail")
        codes = {i.code for i in result.issues}
        self.assertTrue(
            codes & {"fallback_role_mismatch", "manifest_role_conflict", "asset_role_mismatch"},
            f"expected role mismatch codes, got {codes}",
        )

    @unittest.skipUnless(_GLOBAL_TOP_WM.is_file(), "global top watermarked missing")
    @unittest.skipUnless(_GLOBAL_TOP_MANIFEST.is_file(), "global top manifest missing")
    def test_global_top_registry_match_passes_visual_gate_without_watermark_pending(self) -> None:
        fixture = build_global_contract_fixture()
        fixture["top_shot_image_path"] = str(_GLOBAL_TOP_WM)
        html = render_keysuri_contract_preview_html(fixture, repo_root=_REPO)
        result = validate_visual_identity_gate(
            html,
            image_path=str(_GLOBAL_TOP_WM),
            manifest_path=str(_GLOBAL_TOP_MANIFEST),
            program_id=PROGRAM_GLOBAL,
            repo_root=_REPO,
            image_source_mode="approved_registry",
            requested_role=GLOBAL_TOP_ROLE,
        )
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.approved_asset_id, "keysuri_global_top_20260604_221233")
        warning_codes = {w.code for w in result.warnings}
        self.assertNotIn("watermark_pending", warning_codes)

    @unittest.skipUnless(_REGISTRY.is_file(), "registry not present")
    def test_rejected_refresh_not_resolvable(self) -> None:
        missing = _REPO / (
            "output/keysuri_preview/image_canary/"
            "keysuri_asset_refresh_20260608_155717/candidate_01_mirai_on_watermarked.jpg"
        )
        self.assertFalse(missing.is_file())
        self.assertIsNone(
            match_registry_asset(
                _REPO,
                missing,
                PROGRAM_GLOBAL,
                role=GLOBAL_TOP_ROLE,
            )
        )


if __name__ == "__main__":
    unittest.main()
