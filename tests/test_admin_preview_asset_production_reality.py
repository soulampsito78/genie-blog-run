"""Production-shaped regression tests for authenticated Admin preview assets."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from admin_preview_assets import (
    PREVIEW_ASSET_MAX_BYTES,
    PREVIEW_HTML_STREAM_CHUNK_CHARS,
    PreviewAsset,
    preview_assets_for_run,
    read_preview_asset,
    rewrite_customer_html_for_admin_preview,
    stream_customer_html_for_admin_preview,
)


RUN_ID = "20260813_183002_keysuri_korea_tech_096210a0"
BUCKET = "gen-lang-client-0667098249-genie-artifacts"
TOP_OBJECT = f"admin_runs/{RUN_ID}.images/korea_top.jpg"
BOTTOM_OBJECT = f"admin_runs/{RUN_ID}.images/korea_bottom.jpg"


def production_reality_meta() -> dict:
    """Sanitized structural copy of the historical Korea production metadata."""
    return {
        "run_id": RUN_ID,
        "top_image_cid": "keysuri_topshot_korea_20260813",
        "bottom_image_cid": "keysuri_bottomshot_korea_20260813",
        "korea_bottom_shot_cid": "keysuri_bottomshot_korea_20260813",
        "korea_generated_image_gcs_bucket": BUCKET,
        "korea_generated_top_gcs_object": TOP_OBJECT,
        "korea_generated_bottom_gcs_object": BOTTOM_OBJECT,
    }


class _ProductionBlob:
    """Models google-cloud-storage: exists() does not hydrate metadata."""

    def __init__(self, name: str):
        self.name = name
        self.content_type = None
        self.size = None

    def exists(self) -> bool:
        return True

    def reload(self) -> None:
        if self.name.endswith("missing.jpg"):
            raise FileNotFoundError(self.name)
        self.content_type = "image/png" if self.name.endswith(".png") else "image/jpeg"
        self.size = len(f"jpeg:{self.name}".encode())

    def download_as_bytes(self, *, start: int = 0, end=None) -> bytes:
        return f"jpeg:{self.name}".encode()


class _ProductionBucket:
    def blob(self, name: str) -> _ProductionBlob:
        return _ProductionBlob(name)


class ProductionRealityPreviewAssetTests(unittest.TestCase):
    def test_historical_korea_gcs_assets_hydrate_metadata_before_mime_validation(self):
        with mock.patch.dict(os.environ, {"GENIE_ARTIFACT_BUCKET": BUCKET}, clear=False), mock.patch(
            "admin_preview_assets._get_gcs_bucket", return_value=_ProductionBucket()
        ):
            top = read_preview_asset(RUN_ID, production_reality_meta(), "top")
            bottom = read_preview_asset(RUN_ID, production_reality_meta(), "bottom")

        self.assertEqual(top, (f"jpeg:{TOP_OBJECT}".encode(), "image/jpeg"))
        self.assertEqual(bottom, (f"jpeg:{BOTTOM_OBJECT}".encode(), "image/jpeg"))

    def test_current_schema_and_png_keep_exact_content_types(self):
        meta = {
            "top_image_cid": "current-top",
            "bottom_image_cid": "current-bottom",
            "customer_image_gcs_bucket": BUCKET,
            "customer_image_gcs_objects": {
                "top": f"admin_runs/{RUN_ID}.images/current-top.jpg",
                "bottom": f"admin_runs/{RUN_ID}.images/current-bottom.png",
            },
        }
        with mock.patch.dict(os.environ, {"GENIE_ARTIFACT_BUCKET": BUCKET}, clear=False), mock.patch(
            "admin_preview_assets._get_gcs_bucket", return_value=_ProductionBucket()
        ):
            self.assertEqual(read_preview_asset(RUN_ID, meta, "top")[1], "image/jpeg")
            self.assertEqual(read_preview_asset(RUN_ID, meta, "bottom")[1], "image/png")

    def test_foreign_arbitrary_and_traversal_objects_remain_blocked(self):
        cases = (
            f"admin_runs/another-run.images/top.jpg",
            "unrelated/top.jpg",
            f"admin_runs/{RUN_ID}.images/../secret.jpg",
        )
        for object_name in cases:
            with self.subTest(object_name=object_name), mock.patch.dict(
                os.environ, {"GENIE_ARTIFACT_BUCKET": BUCKET}, clear=False
            ):
                meta = production_reality_meta()
                meta["korea_generated_top_gcs_object"] = object_name
                self.assertNotIn("top", preview_assets_for_run(RUN_ID, meta))
                self.assertEqual(read_preview_asset(RUN_ID, meta, "top"), (None, None))

    def test_wrong_bucket_and_missing_recorded_object_fail_closed(self):
        wrong_bucket = production_reality_meta()
        wrong_bucket["korea_generated_image_gcs_bucket"] = "foreign-bucket"
        missing = production_reality_meta()
        missing["korea_generated_top_gcs_object"] = f"admin_runs/{RUN_ID}.images/missing.jpg"
        with mock.patch.dict(os.environ, {"GENIE_ARTIFACT_BUCKET": BUCKET}, clear=False), mock.patch(
            "admin_preview_assets._get_gcs_bucket", return_value=_ProductionBucket()
        ):
            self.assertEqual(read_preview_asset(RUN_ID, wrong_bucket, "top"), (None, None))
            self.assertEqual(read_preview_asset(RUN_ID, missing, "top"), (None, None))

    def test_admin_rewrite_does_not_mutate_stored_customer_cid_html(self):
        customer_html = (
            '<html><img src="cid:keysuri_topshot_korea_20260813">'
            '<img src="cid:keysuri_bottomshot_korea_20260813"></html>'
        )
        original = customer_html[:]
        with mock.patch.dict(os.environ, {"GENIE_ARTIFACT_BUCKET": BUCKET}, clear=False):
            preview = rewrite_customer_html_for_admin_preview(RUN_ID, production_reality_meta(), customer_html)
        self.assertEqual(customer_html, original)
        self.assertIn(f"/admin/runs/{RUN_ID}/preview-assets/top", preview)
        self.assertIn(f"/admin/runs/{RUN_ID}/preview-assets/bottom", preview)

    def test_preview_stream_never_yields_an_unbounded_html_chunk(self):
        body = "x" * (PREVIEW_HTML_STREAM_CHUNK_CHARS * 3 + 17)
        chunks = list(stream_customer_html_for_admin_preview(RUN_ID, {}, body))
        self.assertTrue(chunks)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), PREVIEW_HTML_STREAM_CHUNK_CHARS)
        self.assertTrue("".join(chunks).endswith(body))

    def test_oversized_local_preview_image_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversized.jpg"
            with path.open("wb") as handle:
                handle.truncate(PREVIEW_ASSET_MAX_BYTES + 1)
            asset = PreviewAsset(
                slot="top",
                cid="bounded-top",
                backend="local",
                local_path=path,
            )
            with mock.patch(
                "admin_preview_assets.preview_assets_for_run",
                return_value={"top": asset},
            ), mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("oversized asset must not be read"),
            ):
                self.assertEqual(read_preview_asset(RUN_ID, {}, "top"), (None, None))


if __name__ == "__main__":
    unittest.main()
