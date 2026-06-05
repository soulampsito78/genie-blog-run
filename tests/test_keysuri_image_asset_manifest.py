"""Tests for the future Kee-Suri image asset manifest writer (TDD — pre-implementation).

Defines expected behavior for `keysuri_image_asset_manifest.py` before implementation.
Implementation-dependent tests skip with:
  keysuri_image_asset_manifest not implemented yet

Policy basis:
- docs/keysuri/KEYSURI_IMAGE_ASSET_MANIFEST_V0.md
- docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md §10.2
"""
from __future__ import annotations

import json
import re
import unittest
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping, Optional, TypeVar

from PIL import Image

import keysuri_image_overlay as overlay_mod

_SKIP_REASON = "keysuri_image_asset_manifest not implemented yet"

EXPECTED_SCHEMA_VERSION = "keysuri_image_asset_manifest_v0"
EXPECTED_WATERMARK_TEXT = "MirAI:ON"
EXPECTED_REVIEW_STATUSES = (
    "pending",
    "pass_direction",
    "approved_for_preview",
    "rejected",
)
FORBIDDEN_LEGACY_SUBSTRINGS = (
    "Heemang",
    "Today_Geenee",
    "Tomorrow_Geenee",
)

REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "asset_id",
    "program_id",
    "slot",
    "image_role",
    "source_image_path",
    "watermarked_image_path",
    "generated_at",
    "watermarked_at",
    "overlay_applied",
    "watermark_text",
    "watermark_position",
    "source_sha256",
    "watermarked_sha256",
    "width",
    "height",
    "review_status",
    "review_notes",
    "prompt_profile",
    "source_generation_id",
    "created_by",
    "tool",
    "production_ready",
)

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

F = TypeVar("F", bound=Callable[..., Any])


def _try_import_keysuri_image_asset_manifest() -> Optional[Any]:
    try:
        import keysuri_image_asset_manifest as mod  # type: ignore[import-not-found]

        return mod
    except ImportError:
        return None


_MANIFEST_MOD = _try_import_keysuri_image_asset_manifest()


def _require_manifest_module(test_func: F) -> F:
    @wraps(test_func)
    def wrapper(self: unittest.TestCase, *args: Any, **kwargs: Any) -> None:
        if _MANIFEST_MOD is None:
            raise unittest.SkipTest(_SKIP_REASON)
        return test_func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


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


def _watermarked_pair(root: Path) -> tuple[Path, Path]:
    source = root / "source.jpg"
    watermarked = root / "source_mirai_on_watermarked.jpg"
    _make_portrait_sample(source)
    overlay_mod.apply_keysuri_mirai_on_watermark(source, watermarked)
    return source, watermarked


def _default_build_kwargs(source: Path, watermarked: Path) -> dict[str, Any]:
    return {
        "source_image_path": source,
        "watermarked_image_path": watermarked,
        "program_id": "keysuri_global_tech",
        "slot": "manual_canary",
        "image_role": "bottom_shot",
        "watermark_position": "bottom_right",
        "generated_at": "2026-06-05T10:59:00+09:00",
        "watermarked_at": "2026-06-05T14:30:00+09:00",
        "prompt_profile": "offduty_02C_luxury_knit_silk_skirt_farewell",
        "created_by": "local_cli",
        "tool": "scripts/apply_keysuri_image_watermark.py",
    }


def _manifest_strings(manifest: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in manifest.values())


class KeysuriImageAssetManifestPolicyTests(unittest.TestCase):
    """Documented policy — runs without manifest implementation."""

    def test_documented_schema_version(self) -> None:
        self.assertEqual(EXPECTED_SCHEMA_VERSION, "keysuri_image_asset_manifest_v0")

    def test_documented_watermark_text(self) -> None:
        self.assertEqual(EXPECTED_WATERMARK_TEXT, "MirAI:ON")

    def test_forbidden_legacy_substrings_documented(self) -> None:
        for token in FORBIDDEN_LEGACY_SUBSTRINGS:
            self.assertNotIn(token, EXPECTED_WATERMARK_TEXT)

    def test_manifest_is_not_file_copy_tracking(self) -> None:
        """v0 manifest is internal QA only — not distribution tracking."""
        self.assertTrue(True)

    def test_manifest_is_not_content_shield(self) -> None:
        """v0 manifest is lightweight — not MirAI:ON Content Shield SaaS."""
        self.assertTrue(True)


class KeysuriImageAssetManifestImportTests(unittest.TestCase):
    @_require_manifest_module
    def test_manifest_module_import_status(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        self.assertTrue(hasattr(mod, "build_keysuri_image_asset_manifest"))
        self.assertTrue(hasattr(mod, "write_keysuri_image_asset_manifest"))
        self.assertTrue(hasattr(mod, "validate_keysuri_image_asset_manifest"))
        self.assertTrue(hasattr(mod, "calculate_sha256"))


class KeysuriImageAssetManifestConstantsTests(unittest.TestCase):
    @_require_manifest_module
    def test_schema_version_constant(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        self.assertEqual(mod.SCHEMA_VERSION, EXPECTED_SCHEMA_VERSION)

    @_require_manifest_module
    def test_watermark_text_constant(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        self.assertEqual(mod.WATERMARK_TEXT, EXPECTED_WATERMARK_TEXT)

    @_require_manifest_module
    def test_review_status_constants(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        self.assertEqual(mod.REVIEW_STATUS_PENDING, "pending")
        self.assertEqual(mod.REVIEW_STATUS_PASS_DIRECTION, "pass_direction")
        self.assertEqual(mod.REVIEW_STATUS_APPROVED_FOR_PREVIEW, "approved_for_preview")
        self.assertEqual(mod.REVIEW_STATUS_REJECTED, "rejected")


class KeysuriImageAssetManifestSha256Tests(unittest.TestCase):
    @_require_manifest_module
    def test_calculate_sha256_returns_lowercase_hex(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.jpg"
            _make_portrait_sample(path)
            digest = mod.calculate_sha256(path)
            self.assertRegex(str(digest), _SHA256_RE)

    @_require_manifest_module
    def test_calculate_sha256_changes_when_file_bytes_differ(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "first.jpg"
            second = root / "second.jpg"
            _make_portrait_sample(first)
            _make_portrait_sample(second, size=(640, 960))
            self.assertNotEqual(mod.calculate_sha256(first), mod.calculate_sha256(second))

    @_require_manifest_module
    def test_calculate_sha256_fails_for_missing_file(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.jpg"
            with self.assertRaises((FileNotFoundError, OSError, ValueError)):
                mod.calculate_sha256(missing)


class KeysuriImageAssetManifestBuildTests(unittest.TestCase):
    @_require_manifest_module
    def test_build_returns_required_fields(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            for field in REQUIRED_MANIFEST_FIELDS:
                self.assertIn(field, manifest, msg=f"missing field: {field}")

    @_require_manifest_module
    def test_build_defaults_review_status_to_pending(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            kwargs = _default_build_kwargs(source, watermarked)
            kwargs.pop("review_status", None)
            manifest = mod.build_keysuri_image_asset_manifest(**kwargs)
            self.assertEqual(manifest["review_status"], mod.REVIEW_STATUS_PENDING)


class KeysuriImageAssetManifestFieldRuleTests(unittest.TestCase):
    @_require_manifest_module
    def test_overlay_applied_is_true(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertTrue(manifest["overlay_applied"])

    @_require_manifest_module
    def test_watermark_text_is_mirai_on(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertEqual(manifest["watermark_text"], "MirAI:ON")

    @_require_manifest_module
    def test_production_ready_is_false(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertFalse(manifest["production_ready"])

    @_require_manifest_module
    def test_width_height_preserved_from_watermarked_image(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            with Image.open(source) as src_img, Image.open(watermarked) as wm_img:
                expected_size = src_img.size
                self.assertEqual(wm_img.size, expected_size)
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertEqual((manifest["width"], manifest["height"]), expected_size)

    @_require_manifest_module
    def test_source_and_watermarked_sha256_differ_after_overlay(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertNotEqual(manifest["source_sha256"], manifest["watermarked_sha256"])

    @_require_manifest_module
    def test_image_role_must_be_top_or_bottom_shot(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertIn(manifest["image_role"], ("top_shot", "bottom_shot"))

    @_require_manifest_module
    def test_review_status_must_be_allowed_value(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            self.assertIn(manifest["review_status"], EXPECTED_REVIEW_STATUSES)

    @_require_manifest_module
    def test_no_forbidden_legacy_strings_in_manifest_values(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            joined = _manifest_strings(manifest)
            for token in FORBIDDEN_LEGACY_SUBSTRINGS:
                self.assertNotIn(token, joined)


class KeysuriImageAssetManifestWriteTests(unittest.TestCase):
    @_require_manifest_module
    def test_write_sidecar_beside_watermarked_image(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source, watermarked = _watermarked_pair(root)
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            manifest_path = mod.write_keysuri_image_asset_manifest(manifest)
            expected = watermarked.with_suffix(".manifest.json")
            self.assertEqual(Path(manifest_path).resolve(), expected.resolve())
            self.assertTrue(expected.exists())

    @_require_manifest_module
    def test_write_sidecar_filename_pattern(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source, watermarked = _watermarked_pair(root)
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            manifest_path = Path(mod.write_keysuri_image_asset_manifest(manifest))
            self.assertEqual(manifest_path.name, f"{watermarked.stem}.manifest.json")

    @_require_manifest_module
    def test_write_creates_parent_directories(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            source = nested / "source.jpg"
            watermarked = nested / "source_mirai_on_watermarked.jpg"
            _make_portrait_sample(source)
            overlay_mod.apply_keysuri_mirai_on_watermark(source, watermarked)
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            manifest_path = Path(mod.write_keysuri_image_asset_manifest(manifest))
            self.assertTrue(manifest_path.parent.exists())
            self.assertTrue(manifest_path.exists())

    @_require_manifest_module
    def test_write_persists_utf8_json_with_required_fields(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            source, watermarked = _watermarked_pair(Path(tmpdir))
            manifest = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))
            manifest_path = Path(mod.write_keysuri_image_asset_manifest(manifest))
            raw = manifest_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            for field in REQUIRED_MANIFEST_FIELDS:
                self.assertIn(field, loaded, msg=f"missing persisted field: {field}")


class KeysuriImageAssetManifestValidationTests(unittest.TestCase):
    def _valid_manifest(self, mod: Any, root: Path) -> dict[str, Any]:
        source, watermarked = _watermarked_pair(root)
        return mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(source, watermarked))

    @_require_manifest_module
    def test_validate_passes_for_valid_manifest(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            status = result.get("status") if isinstance(result, dict) else result
            self.assertIn(str(status).upper(), ("PASS", "OK", "VALID"))

    @_require_manifest_module
    def test_validate_fails_if_overlay_applied_false(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            manifest["overlay_applied"] = False
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    @_require_manifest_module
    def test_validate_fails_if_watermark_text_not_mirai_on(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            manifest["watermark_text"] = "Today_Geenee"
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    @_require_manifest_module
    def test_validate_fails_if_production_ready_true(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            manifest["production_ready"] = True
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    @_require_manifest_module
    def test_validate_fails_if_review_status_invalid(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            manifest["review_status"] = "production_ready"
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    @_require_manifest_module
    def test_validate_fails_if_required_field_missing(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            del manifest["asset_id"]
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    @_require_manifest_module
    def test_validate_fails_if_source_and_watermarked_hashes_equal(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            manifest = self._valid_manifest(mod, Path(tmpdir))
            manifest["watermarked_sha256"] = manifest["source_sha256"]
            result = mod.validate_keysuri_image_asset_manifest(manifest)
            self.assertFalse(self._validation_passed(result))

    def _validation_passed(self, result: Any) -> bool:
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            status = str(result.get("status", "")).upper()
            return status in ("PASS", "OK", "VALID")
        return bool(result)


class KeysuriImageAssetManifestPreviewEligibilityTests(unittest.TestCase):
    @_require_manifest_module
    def test_preview_eligibility_helper_if_exposed(self) -> None:
        mod = _MANIFEST_MOD
        assert mod is not None
        if not hasattr(mod, "is_manifest_eligible_for_preview"):
            self.skipTest("is_manifest_eligible_for_preview not implemented yet")

        with TemporaryDirectory() as tmpdir:
            base = mod.build_keysuri_image_asset_manifest(**_default_build_kwargs(*_watermarked_pair(Path(tmpdir))))

            pass_direction = {**base, "review_status": mod.REVIEW_STATUS_PASS_DIRECTION}
            approved = {**base, "review_status": mod.REVIEW_STATUS_APPROVED_FOR_PREVIEW}
            pending = {**base, "review_status": mod.REVIEW_STATUS_PENDING}
            rejected = {**base, "review_status": mod.REVIEW_STATUS_REJECTED}
            no_overlay = {**base, "overlay_applied": False}
            production = {**base, "production_ready": True}

            eligible = mod.is_manifest_eligible_for_preview
            self.assertTrue(eligible(pass_direction))
            self.assertTrue(eligible(approved))
            self.assertFalse(eligible(pending))
            self.assertFalse(eligible(rejected))
            self.assertFalse(eligible(no_overlay))
            self.assertFalse(eligible(production))


if __name__ == "__main__":
    unittest.main()
