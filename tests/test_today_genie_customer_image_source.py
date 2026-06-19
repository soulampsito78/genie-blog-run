"""Customer delivery must preserve Today_Genie run-image provenance."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from renderers import today_genie_email_inline_cid_pair
from service_full_run_contract import IMAGE_GEN_GENERATED, IMAGE_SOURCE_GENERATED
from today_geenee_customer_delivery import (
    TODAY_IMAGE_REASON_GENERATED,
    TODAY_IMAGE_REASON_GENERATED_BOTTOM_MISSING,
    TODAY_IMAGE_REASON_GENERATED_FALLBACK_CONFLICT,
    TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE,
    TODAY_IMAGE_REASON_GENERATED_PATHS_MISSING,
    TODAY_IMAGE_REASON_GENERATED_STATUS_INVALID,
    TODAY_IMAGE_REASON_STATIC_FALLBACK,
    _resolve_today_genie_customer_image_result,
    last_customer_image_resolution_reason,
    send_today_geenee_customer_final_email,
)
from today_genie_orchestrator_images import (
    TodayGenieOrchestratorImageResult,
    persist_today_genie_customer_images,
)


def _generated_meta(top: str, bottom: str) -> dict:
    return {
        "run_id": "20260619_063056_today_genie_87244e62",
        "mode": "today_genie",
        "image_source": "generated",
        "image_generation_status": "generated",
        "fallback_used": False,
        "generated_image_paths": {"top": top, "bottom": bottom},
    }


class TodayGenieCustomerImageSourceTests(unittest.TestCase):
    def test_generated_paths_used_without_service_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "run_top.jpg"
            bottom = Path(tmp) / "run_bottom.jpg"
            top.write_bytes(b"top")
            bottom.write_bytes(b"bottom")
            result = _resolve_today_genie_customer_image_result(
                _generated_meta(str(top), str(bottom))
            )

        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED)
        self.assertEqual(result.source, "generated_run_images")
        self.assertEqual([row[0] for row in result.inline_parts or []], [str(top), str(bottom)])
        self.assertNotIn("static/email", " ".join(row[0] for row in result.inline_parts or []))

    @patch("today_geenee_customer_delivery.send_genie_email")
    def test_customer_mime_paths_and_cids_match_artifact(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        env = {
            "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "user@example.com",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=False):
            top = Path(tmp) / "run_top.jpg"
            bottom = Path(tmp) / "run_bottom.jpg"
            top.write_bytes(b"top")
            bottom.write_bytes(b"bottom")
            sent = send_today_geenee_customer_final_email(
                "<html><body><img src=\"cid:genie.today.top@genie-email.local\"><img src=\"cid:genie.today.bottom@genie-email.local\"></body></html>",
                _generated_meta(str(top), str(bottom)),
            )

        self.assertTrue(sent)
        parts = mock_send.call_args.kwargs["inline_jpeg_parts"]
        self.assertEqual([row[0] for row in parts], [str(top), str(bottom)])
        self.assertEqual([row[1] for row in parts], list(today_genie_email_inline_cid_pair()))

    def test_missing_bottom_blocks_without_static_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "run_top.jpg"
            top.write_bytes(b"top")
            result = _resolve_today_genie_customer_image_result(
                _generated_meta(str(top), "")
            )
        self.assertIsNone(result.inline_parts)
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED_BOTTOM_MISSING)

    def test_generated_provenance_without_paths_blocks(self) -> None:
        result = _resolve_today_genie_customer_image_result(
            {
                "image_source": "generated",
                "image_generation_status": "generated",
                "fallback_used": False,
            }
        )
        self.assertIsNone(result.inline_parts)
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED_PATHS_MISSING)

    def test_non_generated_status_blocks_generated_paths(self) -> None:
        meta = _generated_meta("output/top.jpg", "output/bottom.jpg")
        meta["image_generation_status"] = "failed"
        result = _resolve_today_genie_customer_image_result(meta)
        self.assertIsNone(result.inline_parts)
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED_STATUS_INVALID)

    def test_inaccessible_generated_paths_return_reason_code(self) -> None:
        result = _resolve_today_genie_customer_image_result(
            _generated_meta("output/missing_top.jpg", "output/missing_bottom.jpg")
        )
        self.assertIsNone(result.inline_parts)
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE)

    @patch("today_geenee_customer_delivery.send_genie_email")
    def test_inaccessible_generated_paths_block_send_with_reason(
        self, mock_send: MagicMock
    ) -> None:
        env = {
            "GENIE_CUSTOMER_EMAIL_TO": "customer@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "user@example.com",
        }
        with patch.dict(os.environ, env, clear=False):
            sent = send_today_geenee_customer_final_email(
                "<p>brief</p>",
                _generated_meta("output/missing_top.jpg", "output/missing_bottom.jpg"),
            )
        self.assertFalse(sent)
        mock_send.assert_not_called()
        self.assertEqual(
            last_customer_image_resolution_reason(),
            TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE,
        )

    def test_fallback_true_cannot_masquerade_as_generated(self) -> None:
        meta = _generated_meta("output/top.jpg", "output/bottom.jpg")
        meta["fallback_used"] = True
        result = _resolve_today_genie_customer_image_result(meta)
        self.assertIsNone(result.inline_parts)
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED_FALLBACK_CONFLICT)

    def test_static_latest_only_without_generated_provenance(self) -> None:
        result = _resolve_today_genie_customer_image_result(
            {"mode": "today_genie", "image_source": "static_fallback", "fallback_used": True}
        )
        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_STATIC_FALLBACK)
        self.assertTrue(result.inline_parts)
        self.assertTrue(all("static/email" in row[0] for row in result.inline_parts or []))

    def test_gcs_restore_recreates_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "run_top.jpg"
            bottom = Path(tmp) / "run_bottom.jpg"
            meta = _generated_meta(str(top), str(bottom))
            meta.update(
                customer_image_gcs_bucket="artifact-bucket",
                customer_image_gcs_objects={"top": "runs/top.jpg", "bottom": "runs/bottom.jpg"},
            )

            def download(_bucket: str, object_name: str, target: Path) -> None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(object_name.encode("utf-8"))

            result = _resolve_today_genie_customer_image_result(meta, download_fn=download)

        self.assertEqual(result.reason_code, TODAY_IMAGE_REASON_GENERATED)
        self.assertEqual([row[0] for row in result.inline_parts or []], [str(top), str(bottom)])

    def test_generated_images_are_persisted_with_artifact(self) -> None:
        run_id = "20260619_063056_today_genie_87244e62"
        uploads = []
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp) / "run_top.jpg"
            bottom = Path(tmp) / "run_bottom.jpg"
            top.write_bytes(b"top")
            bottom.write_bytes(b"bottom")
            image_result = TodayGenieOrchestratorImageResult(
                image_source=IMAGE_SOURCE_GENERATED,
                image_generation_status=IMAGE_GEN_GENERATED,
                generated_image_paths={"top": str(top), "bottom": str(bottom)},
                fallback_used=False,
            )

            def upload(bucket: str, object_name: str, source: Path) -> None:
                uploads.append((bucket, object_name, source))

            with patch.dict(os.environ, {"GENIE_ADMIN_ARTIFACT_BUCKET": "artifact-bucket"}):
                fields = persist_today_genie_customer_images(
                    run_id, image_result, upload_fn=upload
                )

        self.assertEqual(fields["customer_image_persistence_status"], "persisted")
        self.assertEqual(fields["customer_image_source"], "generated_run_images")
        self.assertEqual(len(uploads), 2)
        self.assertEqual({row[2] for row in uploads}, {top, bottom})


if __name__ == "__main__":
    unittest.main()
