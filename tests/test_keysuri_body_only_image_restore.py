"""Regression: body_only top-image restore must use a writable assets dir."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import keysuri_service_full_run as mod


class KeysuriBodyOnlyImageRestoreWritableDirTests(unittest.TestCase):
    def test_writable_assets_dir_falls_back_when_repo_output_not_writable(self) -> None:
        orig_mkdir = Path.mkdir

        def boom(self, *args, **kwargs):
            text = str(self)
            if "keysuri_service_assets" in text and "genie_keysuri_service_assets" not in text:
                raise OSError("read-only file system")
            return orig_mkdir(self, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", boom):
            dest_dir = mod._writable_keysuri_service_assets_dir()
        self.assertIn("genie_keysuri_service_assets", str(dest_dir))
        self.assertTrue(dest_dir.is_dir())
        probe = dest_dir / "write_probe.txt"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def test_saved_top_image_reference_uses_writable_dir_for_gcs_restore(self) -> None:
        parent = {
            "run_id": "20260731_022412_keysuri_global_tech_36012cbb",
            "generated_image_gcs_uri": (
                "gs://gen-lang-client-0667098249-genie-artifacts/"
                "admin_runs/20260731_022412_keysuri_global_tech_36012cbb.images/global_top.jpg"
            ),
            "generated_image_path": "output/missing/local.jpg",
        }
        dest_dir = Path("/tmp/genie_keysuri_service_assets_test")
        dest_dir.mkdir(parents=True, exist_ok=True)
        expected = dest_dir / "20260731_022412_keysuri_global_tech_36012cbb_restored_top.jpg"
        if expected.exists():
            expected.unlink()

        def fake_download(dest, *, bucket_name, object_name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"IMG")
            return None

        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", side_effect=fake_download):
                path, fields = mod._saved_top_image_reference(parent)
        self.assertEqual(path, expected)
        self.assertTrue(fields.get("reissue_body_only_image_gcs_restored"))
        self.assertTrue(fields.get("reissue_body_only_image_local_file_present"))
        self.assertTrue(expected.is_file())


if __name__ == "__main__":
    unittest.main()
