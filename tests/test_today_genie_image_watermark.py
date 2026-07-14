"""Tests for the restored Today_Geenee image brand footer/watermark.

Covers the regression fixed by reconnecting ``apply_today_genie_brand_footer``
to the generated owner-review CID images (f82dbd1 behavior), including ordering
(footer applied only after the bottom image uses the top image as reference),
CID path usage, metadata, idempotency, and graceful failure.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from service_full_run_contract import (
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    ServiceImageOutcome,
    TodayGenieServiceImageBundle,
)
import today_genie_service_full_run as svc
from today_genie_service_full_run import (
    apply_today_genie_footer_to_bundle,
    generate_today_genie_service_images,
    today_genie_watermark_meta,
)
from today_genie_orchestrator_images import generate_today_genie_orchestrator_images

_DATA = {"image_prompt_studio": "studio hero", "image_prompt_outdoor": "outdoor daily"}
_RUNTIME = {"target_date": "2026-06-16"}


def _write_solid_jpeg(path: Path, color=(123, 50, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 640), color).save(path, format="JPEG", quality=95)


def _is_uniform(path: Path) -> bool:
    with Image.open(path) as im:
        extrema = im.convert("RGB").getextrema()
    return all(lo == hi for lo, hi in extrema)


class _FakeInvoke:
    """Fake invoke_vertex_image_generation that writes real solid JPEGs.

    Records, at the moment the bottom image is generated, whether the top
    reference image was still un-watermarked (uniform) — proving ordering.
    """

    def __init__(self) -> None:
        self.top_uniform_at_bottom_gen = None

    def __call__(self, *, prompt, output_path, reference_image_path=None, **kwargs):
        out = Path(output_path)
        is_bottom = out.name.endswith("_bottom.jpg")
        if is_bottom and reference_image_path and Path(reference_image_path).is_file():
            self.top_uniform_at_bottom_gen = _is_uniform(Path(reference_image_path))
        _write_solid_jpeg(out)
        return ServiceImageOutcome(
            called_image_api=True,
            image_generation_status=IMAGE_GEN_GENERATED,
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=str(out),
        )


class TodayGenieImageWatermarkTests(unittest.TestCase):
    def _run_generate(self, tmp: str, run_id: str):
        fake = _FakeInvoke()
        with patch.object(svc, "_OUTPUT_IMAGES", Path(tmp) / "today_genie"), patch.object(
            svc, "invoke_vertex_image_generation", fake
        ):
            bundle = generate_today_genie_service_images(_DATA, _RUNTIME, run_id=run_id)
        return bundle, fake

    def test_generated_top_and_bottom_get_footer_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, _ = self._run_generate(tmp, "20260616_120000_today_genie_aabbccdd")
            self.assertTrue(bundle.ok)
            self.assertTrue(bundle.watermark_applied)
            self.assertEqual(len(bundle.watermark_paths), 2)
            self.assertIsNone(bundle.watermark_error)
            # Footer makes each raster non-uniform (dark strip + text drawn).
            self.assertFalse(_is_uniform(Path(bundle.top.generated_image_path)))
            self.assertFalse(_is_uniform(Path(bundle.bottom.generated_image_path)))
            self.assertEqual(bundle.top.image_locally_derived_asset_count, 1)
            self.assertEqual(bundle.bottom.image_locally_derived_asset_count, 1)

    def test_footer_applied_after_bottom_reference_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, fake = self._run_generate(tmp, "20260616_120100_today_genie_bbccddee")
            # At the moment bottom used top as reference, top was NOT yet stamped.
            self.assertIs(fake.top_uniform_at_bottom_gen, True)
            # But the final top image IS stamped.
            self.assertFalse(_is_uniform(Path(bundle.top.generated_image_path)))

    def test_inline_cid_uses_footer_applied_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "20260616_120200_today_genie_ccddeeff"
            fake = _FakeInvoke()
            with patch.object(svc, "_OUTPUT_IMAGES", Path(tmp) / "today_genie"), patch.object(
                svc, "invoke_vertex_image_generation", fake
            ):
                result = generate_today_genie_orchestrator_images(run_id, _DATA, _RUNTIME)
            self.assertEqual(len(result.inline_parts), 2)
            self.assertNotIn(svc.WATERMARK_ISSUE_CODE, result.issue_codes)
            for path_str, _cid, _name in result.inline_parts:
                self.assertFalse(_is_uniform(Path(path_str)))

    def test_watermark_metadata_fields_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, _ = self._run_generate(tmp, "20260616_120300_today_genie_ddeeff00")
            meta = today_genie_watermark_meta(bundle)
            self.assertTrue(meta["today_genie_image_watermark_applied"])
            self.assertEqual(meta["today_genie_image_watermark_label"], "MirAI:ON")
            self.assertEqual(
                meta["today_genie_image_watermark_method"], "apply_today_genie_brand_footer"
            )
            self.assertEqual(len(meta["today_genie_image_watermark_paths"]), 2)

    def test_idempotent_no_double_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle, _ = self._run_generate(tmp, "20260616_120400_today_genie_eeff0011")
            top = Path(bundle.top.generated_image_path)
            size_after_first = top.stat().st_size
            # Re-process: marker exists, so no second stamp.
            apply_today_genie_footer_to_bundle(bundle)
            self.assertEqual(top.stat().st_size, size_after_first)

    def test_watermark_failure_records_metadata_without_raising(self) -> None:
        bundle = TodayGenieServiceImageBundle(
            top=ServiceImageOutcome(
                called_image_api=True,
                image_generation_status=IMAGE_GEN_GENERATED,
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path="output/images/today_genie/missing/missing_top.jpg",
            ),
            bottom=ServiceImageOutcome(
                called_image_api=True,
                image_generation_status=IMAGE_GEN_GENERATED,
                image_source=IMAGE_SOURCE_GENERATED,
                generated_image_path="output/images/today_genie/missing/missing_bottom.jpg",
            ),
        )
        apply_today_genie_footer_to_bundle(bundle)  # must not raise
        self.assertFalse(bundle.watermark_applied)
        self.assertIsNotNone(bundle.watermark_error)
        self.assertEqual(bundle.watermark_paths, [])


if __name__ == "__main__":
    unittest.main()
