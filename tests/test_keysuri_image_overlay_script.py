"""Tests for scripts/apply_keysuri_image_watermark.py (offline local watermark CLI)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "apply_keysuri_image_watermark.py"

_FORBIDDEN_LABELS = (
    "Heemang",
    "Today_Geenee",
    "Tomorrow_Geenee",
)


def _run_script(tmp: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(_SCRIPT), *extra_args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _make_portrait_sample(path: Path, *, size: tuple[int, int] = (800, 1200)) -> Path:
    width, height = size
    image = Image.new("RGB", (width, height), color=(210, 210, 210))
    pixels = image.load()
    face_top = int(height * 0.18)
    face_bottom = int(height * 0.55)
    face_left = int(width * 0.25)
    face_right = int(width * 0.75)
    for y in range(face_top, face_bottom):
        for x in range(face_left, face_right):
            pixels[x, y] = (240, 220, 200)
    lower_top = int(height * 0.72)
    for y in range(lower_top, height):
        for x in range(width):
            pixels[x, y] = (180, 190, 200)
    image.save(path, format="JPEG", quality=95)
    return path


def _region_changed(before: Image.Image, after: Image.Image, box: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = box
    before_pixels = list(before.crop((x0, y0, x1, y1)).getdata())
    after_pixels = list(after.crop((x0, y0, x1, y1)).getdata())
    return before_pixels != after_pixels


def _region_unchanged(before: Image.Image, after: Image.Image, box: tuple[int, int, int, int]) -> bool:
    return not _region_changed(before, after, box)


def _list_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


class KeysuriImageWatermarkScriptTests(unittest.TestCase):
    def test_script_applies_watermark_to_jpeg_and_exits_zero(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(Path(payload["output_path"]).exists())

    def test_script_applies_watermark_to_png_and_exits_zero(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.png"
            _make_portrait_sample(root / "seed.jpg")
            Image.open(root / "seed.jpg").save(input_path, format="PNG")
            proc = _run_script(root, "--input", str(input_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(Path(payload["output_path"]).exists())

    def test_default_output_sibling_contains_mirai_on_watermarked(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "canary.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            output_path = Path(payload["output_path"])
            self.assertIn("_mirai_on_watermarked", output_path.name)
            self.assertEqual(output_path.parent.resolve(), root.resolve())

    def test_explicit_output_path_creates_parent_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "nested" / "out.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(Path(payload["output_path"]).resolve(), output_path.resolve())
            self.assertTrue(output_path.exists())

    def test_dimensions_are_preserved(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "output.jpg"
            _make_portrait_sample(input_path, size=(640, 960))
            before = Image.open(input_path)
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            after = Image.open(output_path)
            self.assertEqual(before.size, after.size)

    def test_lower_right_safe_area_pixels_change(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "output.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--position",
                "bottom_right",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            after = Image.open(output_path)
            lower_right = (int(width * 0.45), int(height * 0.78), width, height)
            self.assertTrue(_region_changed(before, after, lower_right))

    def test_central_face_safe_region_unchanged(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "output.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            after = Image.open(output_path)
            face_safe = (
                int(width * 0.30),
                int(height * 0.22),
                int(width * 0.70),
                int(height * 0.50),
            )
            self.assertTrue(_region_unchanged(before, after, face_safe))

    def test_bottom_left_changes_lower_left_area(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "left.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--position",
                "bottom_left",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            after = Image.open(output_path)
            lower_left = (0, int(height * 0.78), int(width * 0.55), height)
            self.assertTrue(_region_changed(before, after, lower_left))

    def test_forbidden_labels_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            for bad_label in _FORBIDDEN_LABELS:
                with self.subTest(label=bad_label):
                    proc = _run_script(
                        root,
                        "--input",
                        str(input_path),
                        "--label",
                        bad_label,
                    )
                    self.assertEqual(proc.returncode, 1, msg=proc.stderr or proc.stdout)
                    payload = json.loads(proc.stdout)
                    self.assertEqual(payload["status"], "FAIL")
                    self.assertFalse(payload["overlay_applied"])
                    self.assertIn("error", payload)

    def test_missing_input_fails_non_zero(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing = root / "missing.jpg"
            proc = _run_script(root, "--input", str(missing))
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["overlay_applied"])

    def test_unsupported_extension_fails_non_zero(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bad_input = root / "input.gif"
            bad_input.write_text("not-an-image", encoding="utf-8")
            proc = _run_script(root, "--input", str(bad_input))
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["overlay_applied"])

    def test_json_contains_required_success_fields(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "output.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(payload["overlay_applied"])
            self.assertEqual(payload["watermark_text"], "MirAI:ON")
            self.assertEqual(payload["input_path"], str(input_path.resolve()))
            self.assertEqual(payload["output_path"], str(output_path.resolve()))

    def test_role_top_shot_appears_in_json_when_provided(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path), "--role", "top_shot")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["role"], "top_shot")

    def test_role_bottom_shot_appears_in_json_when_provided(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path), "--role", "bottom_shot")
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["role"], "bottom_shot")

    def test_script_does_not_write_outside_temp_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before_files = set(_list_files(root))
            input_path = root / "input.jpg"
            output_path = root / "nested" / "out.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            after_files = set(_list_files(root))
            new_files = after_files - before_files
            self.assertTrue(new_files)
            for path in new_files:
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))


def _manifest_write_args(
    input_path: Path,
    *,
    output_path: Path | None = None,
    role: str = "bottom_shot",
    review_status: str = "pending",
    program: str = "keysuri_global_tech",
    slot: str = "manual_canary",
    extra: tuple[str, ...] = (),
) -> list[str]:
    args = [
        "--input",
        str(input_path),
        "--write-manifest",
        "--role",
        role,
        "--program",
        program,
        "--slot",
        slot,
        "--review-status",
        review_status,
        *extra,
    ]
    if output_path is not None:
        args.extend(["--output", str(output_path)])
    return args


class KeysuriImageWatermarkManifestScriptTests(unittest.TestCase):
    def test_default_behavior_without_write_manifest_does_not_create_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["manifest_written"])
            manifest_files = list(root.glob("*.manifest.json"))
            self.assertEqual(manifest_files, [])

    def test_write_manifest_creates_sidecar_beside_output_image(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "out.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, *_manifest_write_args(input_path, output_path=output_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            manifest_path = Path(payload["manifest_path"])
            expected = output_path.with_suffix(".manifest.json")
            self.assertEqual(manifest_path.resolve(), expected.resolve())
            self.assertTrue(manifest_path.exists())

    def test_manifest_json_contains_required_fields(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "out.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                *_manifest_write_args(
                    input_path,
                    output_path=output_path,
                    role="top_shot",
                    review_status="pass_direction",
                ),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "keysuri_image_asset_manifest_v0")
            self.assertEqual(manifest["watermark_text"], "MirAI:ON")
            self.assertTrue(manifest["overlay_applied"])
            self.assertFalse(manifest["production_ready"])
            self.assertEqual(manifest["image_role"], "top_shot")
            self.assertEqual(manifest["review_status"], "pass_direction")
            self.assertTrue(manifest["source_sha256"])
            self.assertTrue(manifest["watermarked_sha256"])
            self.assertNotEqual(manifest["source_sha256"], manifest["watermarked_sha256"])

    def test_manifest_output_writes_explicit_path_and_creates_parent_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "out.jpg"
            manifest_path = root / "nested" / "custom.manifest.json"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                *_manifest_write_args(input_path, output_path=output_path),
                "--manifest-output",
                str(manifest_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(Path(payload["manifest_path"]).resolve(), manifest_path.resolve())
            self.assertTrue(manifest_path.exists())

    def test_write_manifest_without_role_fails_non_zero(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(root, "--input", str(input_path), "--write-manifest")
            self.assertEqual(proc.returncode, 2, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("role", payload["error"].lower())
            self.assertFalse(list(root.glob("*.manifest.json")))

    def test_forbidden_label_with_write_manifest_writes_neither_output_nor_manifest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                "--input",
                str(input_path),
                "--write-manifest",
                "--role",
                "top_shot",
                "--label",
                "Today_Geenee",
            )
            self.assertEqual(proc.returncode, 1, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "FAIL")
            self.assertFalse(payload["overlay_applied"])
            self.assertFalse(list(root.glob("*_mirai_on_watermarked*")))
            self.assertFalse(list(root.glob("*.manifest.json")))

    def test_json_includes_manifest_written_and_manifest_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            _make_portrait_sample(input_path)
            proc = _run_script(
                root,
                *_manifest_write_args(input_path, role="bottom_shot", review_status="pending"),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["manifest_written"])
            self.assertTrue(payload["manifest_path"])
            self.assertEqual(payload["program_id"], "keysuri_global_tech")
            self.assertEqual(payload["slot"], "manual_canary")
            self.assertEqual(payload["image_role"], "bottom_shot")
            self.assertEqual(payload["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
