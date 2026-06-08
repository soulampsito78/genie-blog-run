"""Tests for guarded Kee-Suri top-shot canary generation helpers."""
from __future__ import annotations

import json
import shutil
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from keysuri_approved_image_assets import REGISTRY_REL_PATH
from keysuri_topshot_test_generation import (
    BLOCKED_DRY_RUN,
    BLOCKED_MISSING_ALLOW_IMAGE_API,
    BLOCKED_MISSING_MANUAL_APPROVAL,
    PROMPT_PROFILE,
    build_topshot_dry_run_plan,
    build_topshot_output_paths,
    generate_keysuri_global_topshot_test,
)

_REPO = Path(__file__).resolve().parent.parent


class KeysuriTopshotTestGenerationTests(unittest.TestCase):
    def test_build_topshot_output_paths_use_generated_topshot_convention(self) -> None:
        with TemporaryDirectory() as tmpdir:
            source, watermarked, manifest = build_topshot_output_paths(
                Path(tmpdir),
                stamp="20260608_120000",
            )
            self.assertIn("keysuri_global_generated_topshot_20260608_120000.jpg", str(source))
            self.assertIn(
                "keysuri_global_generated_topshot_20260608_120000_mirai_on_watermarked.jpg",
                str(watermarked),
            )
            self.assertEqual(manifest, watermarked.with_suffix(".manifest.json"))
            self.assertIn("output/keysuri_preview/image_canary/", str(source).replace("\\", "/"))

    def test_default_dry_run_does_not_call_generate_image_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            with mock.patch("keysuri_topshot_test_generation.generate_image_file") as gen_mock:
                result = generate_keysuri_global_topshot_test(repo_root=repo)
            gen_mock.assert_not_called()
            self.assertTrue(result.dry_run)
            self.assertFalse(result.image_api_called)
            self.assertEqual(result.blocked_reason, BLOCKED_DRY_RUN)
            self.assertTrue(result.ok)
            self.assertIn("source_image_path", result.planned_paths)

    def test_missing_allow_image_api_blocks_live_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            with mock.patch("keysuri_topshot_test_generation.generate_image_file") as gen_mock:
                result = generate_keysuri_global_topshot_test(
                    repo_root=repo,
                    dry_run=False,
                    allow_image_api=False,
                    manual_approval=True,
                )
            gen_mock.assert_not_called()
            self.assertEqual(result.blocked_reason, BLOCKED_MISSING_ALLOW_IMAGE_API)
            self.assertFalse(result.image_api_called)

    def test_allow_image_api_without_manual_approval_blocks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            with mock.patch("keysuri_topshot_test_generation.generate_image_file") as gen_mock:
                result = generate_keysuri_global_topshot_test(
                    repo_root=repo,
                    project_id="test-project",
                    dry_run=False,
                    allow_image_api=True,
                    manual_approval=False,
                )
            gen_mock.assert_not_called()
            self.assertEqual(result.blocked_reason, BLOCKED_MISSING_MANUAL_APPROVAL)
            self.assertFalse(result.image_api_called)

    def test_live_generation_requires_both_flags_and_writes_safe_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            registry_src = _REPO / REGISTRY_REL_PATH
            registry_copy = repo / REGISTRY_REL_PATH
            registry_copy.parent.mkdir(parents=True)
            shutil.copy2(registry_src, registry_copy)
            registry_before = registry_copy.read_text(encoding="utf-8")

            out_dir = repo / "output" / "keysuri_preview" / "image_canary"
            out_dir.mkdir(parents=True)
            source = out_dir / "keysuri_global_generated_topshot_20260608_120000.jpg"
            watermarked = out_dir / "keysuri_global_generated_topshot_20260608_120000_mirai_on_watermarked.jpg"
            manifest = watermarked.with_suffix(".manifest.json")
            for path, color in ((source, (40, 50, 70)), (watermarked, (45, 55, 75))):
                buf = BytesIO()
                Image.new("RGB", (320, 480), color).save(buf, format="JPEG")
                path.write_bytes(buf.getvalue())

            with mock.patch(
                "keysuri_topshot_test_generation.generate_image_file",
                return_value=source,
            ) as gen_mock, mock.patch(
                "keysuri_topshot_test_generation.apply_keysuri_mirai_on_watermark",
                return_value=watermarked,
            ) as wm_mock, mock.patch(
                "keysuri_topshot_test_generation.build_topshot_output_paths",
                return_value=(source, watermarked, manifest),
            ):
                result = generate_keysuri_global_topshot_test(
                    repo_root=repo,
                    project_id="test-project",
                    stamp="20260608_120000",
                    dry_run=False,
                    allow_image_api=True,
                    manual_approval=True,
                )

            self.assertTrue(result.ok, result.error)
            gen_mock.assert_called_once()
            wm_mock.assert_called_once()
            self.assertTrue(result.image_api_called)
            self.assertFalse(result.dry_run)
            self.assertEqual(registry_copy.read_text(encoding="utf-8"), registry_before)

            manifest_path = Path(result.manifest_path or "")
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["program_id"], "keysuri_global_tech")
            self.assertEqual(payload["slot"], "12:30")
            self.assertEqual(payload["image_source"], "generated_test")
            self.assertEqual(payload["intended_use"], "contract_preview_test")
            self.assertTrue(payload["not_customer_final"])
            self.assertFalse(payload["approved_asset"])
            self.assertFalse(payload["registry_promoted"])
            self.assertTrue(payload["canary_only"])
            self.assertTrue(payload["requires_owner_review"])
            self.assertEqual(payload["prompt_profile"], PROMPT_PROFILE)
            self.assertEqual(payload["watermark"], "MirAI:ON applied")

    def test_build_topshot_dry_run_plan_returns_paths_under_image_canary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            plan = build_topshot_dry_run_plan(repo_root=Path(tmpdir), stamp="20260608_120000")
            self.assertTrue(plan.ok)
            self.assertTrue(plan.dry_run)
            for key in ("source_image_path", "watermarked_image_path", "manifest_path"):
                self.assertIn("output/keysuri_preview/image_canary/", plan.planned_paths[key].replace("\\", "/"))

    def test_cli_help_mentions_canary_only_and_no_registry_promotion(self) -> None:
        import subprocess
        import sys

        script = _REPO / "scripts" / "generate_keysuri_global_topshot_test.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        help_text = proc.stdout
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("canary-only", help_text.lower())
        self.assertIn("does not promote", help_text.lower())
        self.assertIn("does not update the approved image registry", help_text.lower())
        self.assertIn("--allow-image-api", help_text)
        self.assertIn("--manual-approval", help_text)

    def test_cli_default_is_dry_run_without_api(self) -> None:
        from scripts import generate_keysuri_global_topshot_test as cli_mod
        from keysuri_topshot_test_generation import TopshotGenerationResult

        dry_plan = TopshotGenerationResult(
            ok=True,
            program_id="keysuri_global_tech",
            slot="12:30",
            prompt_profile=PROMPT_PROFILE,
            model_name="gemini-2.5-flash-image",
            dry_run=True,
            blocked_reason=BLOCKED_DRY_RUN,
            planned_paths={"source_image_path": "output/keysuri_preview/image_canary/x.jpg"},
        )
        with mock.patch.object(cli_mod, "generate_keysuri_global_topshot_test", return_value=dry_plan) as gen_mock:
            rc = cli_mod.main([])
        gen_mock.assert_called_once()
        kwargs = gen_mock.call_args.kwargs
        self.assertTrue(kwargs["dry_run"])
        self.assertFalse(kwargs["allow_image_api"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
