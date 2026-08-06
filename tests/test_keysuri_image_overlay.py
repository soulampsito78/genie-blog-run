"""Tests for the future Kee-Suri MirAI:ON image overlay utility (TDD — pre-implementation).

Defines expected behavior for `keysuri_image_overlay.py` before implementation.
Implementation-dependent tests skip with:
  keysuri_image_overlay not implemented yet

Policy basis:
- docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md §10.1
- docs/keysuri/KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md §7.6
- Genie inspection pattern: no model-generated watermark + post-process overlay
- Kee-Suri uses MirAI:ON only — not genie_image_overlay import/copy
"""
from __future__ import annotations

import inspect
import socket
import types
import unittest
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Optional, TypeVar
from unittest import mock

from PIL import Image

_SKIP_REASON = "keysuri_image_overlay not implemented yet"

EXPECTED_DEFAULT_WATERMARK_TEXT = "MirAI:ON"
EXPECTED_DEFAULT_POSITION = "bottom_right"
EXPECTED_FORBIDDEN_LEGACY_SUBSTRINGS = (
    "Heemang",
    "Today_Geenee",
    "Tomorrow_Geenee",
)

F = TypeVar("F", bound=Callable[..., Any])


def _try_import_keysuri_image_overlay() -> Optional[Any]:
    try:
        import keysuri_image_overlay as mod  # type: ignore[import-not-found]

        return mod
    except ImportError:
        return None


_OVERLAY_MOD = _try_import_keysuri_image_overlay()


def _require_overlay_module(test_func: F) -> F:
    @wraps(test_func)
    def wrapper(self: unittest.TestCase, *args: Any, **kwargs: Any) -> None:
        if _OVERLAY_MOD is None:
            raise unittest.SkipTest(_SKIP_REASON)
        return test_func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _make_portrait_sample(path: Path, *, size: tuple[int, int] = (800, 1200)) -> Path:
    """Plain portrait image with distinct upper (face-safe) and lower bands."""
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


def _apply_overlay(mod: Any, input_path: Path, output_path: Path, **kwargs: Any) -> Path:
    result = mod.apply_keysuri_mirai_on_watermark(
        str(input_path),
        str(output_path),
        **kwargs,
    )
    return Path(result)


class KeysuriImageOverlayPolicyTests(unittest.TestCase):
    """Documented policy — runs without implementation."""

    def test_documented_default_watermark_text(self) -> None:
        self.assertEqual(EXPECTED_DEFAULT_WATERMARK_TEXT, "MirAI:ON")

    def test_documented_default_position_is_bottom_right(self) -> None:
        self.assertEqual(EXPECTED_DEFAULT_POSITION, "bottom_right")

    def test_forbidden_legacy_brand_substrings_documented(self) -> None:
        for token in EXPECTED_FORBIDDEN_LEGACY_SUBSTRINGS:
            self.assertNotIn(token, EXPECTED_DEFAULT_WATERMARK_TEXT)

    @_require_overlay_module
    def test_post_process_overlay_does_not_call_image_api(self) -> None:
        """Overlay must complete with every socket denied — so no image API, ever."""
        mod = _OVERLAY_MOD
        assert mod is not None

        def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("overlay opened a socket")

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "output.jpg"
            _make_portrait_sample(input_path)
            with mock.patch.object(socket, "socket", _deny_socket), mock.patch.object(
                socket, "create_connection", _deny_socket
            ):
                _apply_overlay(mod, input_path, output_path)
            self.assertTrue(output_path.exists())

    @_require_overlay_module
    def test_post_process_overlay_does_not_modify_prompts(self) -> None:
        """The utility takes raster paths only; no prompt builder is in its graph."""
        mod = _OVERLAY_MOD
        assert mod is not None
        imported = {
            getattr(value, "__name__", "")
            for value in vars(mod).values()
            if isinstance(value, types.ModuleType)
        }
        for forbidden in (
            "keysuri_generation_prompt",
            "keysuri_bottom_shot_prompt_builder",
            "keysuri_prompt_input",
            "prompts",
        ):
            self.assertNotIn(forbidden, imported)

        params = set(inspect.signature(mod.apply_keysuri_mirai_on_watermark).parameters)
        self.assertNotIn("prompt", params)


class KeysuriImageOverlayImportTests(unittest.TestCase):
    @_require_overlay_module
    def test_overlay_module_import_status(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        self.assertTrue(hasattr(mod, "apply_keysuri_mirai_on_watermark"))


class KeysuriImageOverlayConstantsTests(unittest.TestCase):
    @_require_overlay_module
    def test_default_watermark_text_constant(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        self.assertEqual(mod.DEFAULT_WATERMARK_TEXT, "MirAI:ON")

    @_require_overlay_module
    def test_default_position_constant(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        self.assertEqual(mod.DEFAULT_POSITION, "bottom_right")

    @_require_overlay_module
    def test_forbidden_legacy_texts_constant(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        forbidden = getattr(mod, "FORBIDDEN_LEGACY_TEXTS", ())
        joined = " ".join(str(item) for item in forbidden)
        for token in ("Heemang", "Today_Geenee", "Tomorrow_Geenee"):
            self.assertIn(token, joined)


class KeysuriImageOverlayBehaviorTests(unittest.TestCase):
    @_require_overlay_module
    def test_overlay_writes_output_without_overwriting_input_by_default(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.jpg"
            output_path = root / "nested" / "output.jpg"
            _make_portrait_sample(input_path)
            before_input = Image.open(input_path).copy()
            result_path = _apply_overlay(mod, input_path, output_path)
            self.assertTrue(result_path.exists())
            self.assertEqual(result_path, output_path.resolve())
            after_input = Image.open(input_path)
            self.assertEqual(list(before_input.getdata()), list(after_input.getdata()))

    @_require_overlay_module
    def test_overlay_preserves_image_dimensions(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "output.jpg"
            _make_portrait_sample(input_path, size=(640, 960))
            before = Image.open(input_path)
            _apply_overlay(mod, input_path, output_path)
            after = Image.open(output_path)
            self.assertEqual(before.size, after.size)

    @_require_overlay_module
    def test_overlay_modifies_lower_safe_area_pixels(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "output.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            _apply_overlay(mod, input_path, output_path, position="bottom_right")
            after = Image.open(output_path)
            lower_right = (
                int(width * 0.45),
                int(height * 0.78),
                width,
                height,
            )
            self.assertTrue(_region_changed(before, after, lower_right))

    @_require_overlay_module
    def test_overlay_preserves_central_face_safe_region(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "output.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            _apply_overlay(mod, input_path, output_path, position="bottom_right")
            after = Image.open(output_path)
            face_safe = (
                int(width * 0.30),
                int(height * 0.22),
                int(width * 0.70),
                int(height * 0.50),
            )
            self.assertTrue(_region_unchanged(before, after, face_safe))

    @_require_overlay_module
    def test_position_bottom_right_default(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_default = Path(tmpdir) / "default.jpg"
            output_explicit = Path(tmpdir) / "explicit.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            _apply_overlay(mod, input_path, output_default)
            _apply_overlay(mod, input_path, output_explicit, position="bottom_right")
            after_default = Image.open(output_default)
            after_explicit = Image.open(output_explicit)
            lower_right = (
                int(width * 0.55),
                int(height * 0.80),
                width,
                height,
            )
            self.assertTrue(_region_changed(before, after_default, lower_right))
            self.assertTrue(_region_changed(before, after_explicit, lower_right))

    @_require_overlay_module
    def test_position_bottom_left_supported(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "left.jpg"
            _make_portrait_sample(input_path)
            before = Image.open(input_path)
            width, height = before.size
            _apply_overlay(mod, input_path, output_path, position="bottom_left")
            after = Image.open(output_path)
            lower_left = (
                0,
                int(height * 0.78),
                int(width * 0.55),
                height,
            )
            self.assertTrue(_region_changed(before, after, lower_left))

    @_require_overlay_module
    def test_default_label_is_mirai_on_only(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        self.assertEqual(mod.DEFAULT_WATERMARK_TEXT, "MirAI:ON")
        forbidden = getattr(mod, "FORBIDDEN_LEGACY_TEXTS", ())
        for bad in forbidden:
            self.assertNotIn(str(bad), mod.DEFAULT_WATERMARK_TEXT)

    @_require_overlay_module
    def test_supports_jpeg_and_png(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jpeg_in = root / "in.jpg"
            jpeg_out = root / "out.jpg"
            png_in = root / "in.png"
            png_out = root / "out.png"
            _make_portrait_sample(jpeg_in)
            Image.open(jpeg_in).save(png_in, format="PNG")
            _apply_overlay(mod, jpeg_in, jpeg_out)
            _apply_overlay(mod, png_in, png_out)
            self.assertTrue(jpeg_out.exists())
            self.assertTrue(png_out.exists())
            self.assertEqual(Image.open(jpeg_out).size, Image.open(jpeg_in).size)
            self.assertEqual(Image.open(png_out).size, Image.open(png_in).size)

    @_require_overlay_module
    def test_calculate_watermark_box_if_exposed(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        if not hasattr(mod, "calculate_watermark_box"):
            self.skipTest("calculate_watermark_box not implemented yet")
        box = mod.calculate_watermark_box(800, 1200, position="bottom_right")
        self.assertEqual(len(box), 4)
        x0, y0, x1, y1 = box
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        self.assertGreater(y0, 600)


class KeysuriImageOverlayRepeatApplicationTests(unittest.TestCase):
    """Pin the v0 repeat-application contract instead of skipping it.

    v0 deliberately has no duplicate-overlay detection: calling the utility on
    an already-watermarked file overlays again rather than raising. The former
    version of this class asserted that gap with an unconditional
    ``@unittest.skip`` around a ``self.fail()``, so nothing ran. These tests
    assert the behaviour v0 actually guarantees, and will fail if a future
    change silently starts rejecting or corrupting a repeat call.
    """

    @_require_overlay_module
    def test_repeat_overlay_succeeds_and_preserves_geometry(self) -> None:
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            once_path = Path(tmpdir) / "once.jpg"
            twice_path = Path(tmpdir) / "twice.jpg"
            _make_portrait_sample(input_path)
            _apply_overlay(mod, input_path, once_path)
            _apply_overlay(mod, once_path, twice_path)

            self.assertTrue(twice_path.exists())
            with Image.open(input_path) as original, Image.open(twice_path) as twice:
                self.assertEqual(twice.size, original.size)
                self.assertEqual(twice.mode, original.mode)

    @_require_overlay_module
    def test_repeat_overlay_leaves_the_face_safe_band_untouched(self) -> None:
        """A second pass must not creep into the upper portrait band."""
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            once_path = Path(tmpdir) / "once.jpg"
            twice_path = Path(tmpdir) / "twice.jpg"
            _make_portrait_sample(input_path)
            _apply_overlay(mod, input_path, once_path)
            _apply_overlay(mod, once_path, twice_path)

            with Image.open(once_path) as once, Image.open(twice_path) as twice:
                width, height = once.size
                face_safe = (
                    int(width * 0.30),
                    int(height * 0.22),
                    int(width * 0.70),
                    int(height * 0.50),
                )
                self.assertTrue(_region_unchanged(once, twice, face_safe))

    @_require_overlay_module
    def test_repeat_overlay_is_not_rejected_in_v0(self) -> None:
        """Documented v0 gap: no duplicate detection, so no exception is raised."""
        mod = _OVERLAY_MOD
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jpg"
            output_path = Path(tmpdir) / "output.jpg"
            _make_portrait_sample(input_path)
            _apply_overlay(mod, input_path, output_path)
            returned = _apply_overlay(mod, output_path, output_path)
            self.assertEqual(returned.resolve(), output_path.resolve())


if __name__ == "__main__":
    unittest.main()
