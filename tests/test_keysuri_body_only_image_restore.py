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

    def test_korea_body_only_durable_preview_proof_intentional_notice_reused(self) -> None:
        import base64
        import hashlib
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_120000_keysuri_korea_tech_p1234567"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"

        top_bytes = b"TOP_IMAGE_BYTES_KOREA_EXACT"
        bottom_bytes = b"BOTTOM_IMAGE_BYTES_KOREA_EXACT"
        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes).decode("ascii")
        preview_html = (
            f'<html><body>'
            f'<figure id="top-shot-image"><img src="data:image/jpeg;base64,{top_b64}" class="top-shot-hero"/></figure>'
            f'<figure id="bottom-shot-image"><img src="data:image/jpeg;base64,{bottom_b64}" class="korea-bottom-hero"/></figure>'
            f'</body></html>'
        )

        parent = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "owner_email_inline_image_hashes": [],  # Truthful SMTP evidence for POOR notice!
            "preview_html": preview_html,
            "bottom_shot_source": "generated_v6_multi_ref",
            "bottom_shot_asset_id": "korea_bottom_anchor",
        }

        dest_dir = Path("/tmp/genie_keysuri_korea_durable_test")
        dest_dir.mkdir(parents=True, exist_ok=True)

        def fake_download(dest, *, bucket_name, object_name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if object_name == top_obj:
                dest.write_bytes(top_bytes)
            elif object_name == bottom_obj:
                dest.write_bytes(bottom_bytes)
            return None

        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", side_effect=fake_download):
                    top_path, top_meta = mod._saved_top_image_reference(parent)
                    self.assertIsNotNone(top_path)
                    self.assertTrue(top_meta["reissue_body_only_image_reused"])
                    self.assertEqual(hashlib.sha256(top_path.read_bytes()).hexdigest(), hashlib.sha256(top_bytes).hexdigest())

                    bottom_path = mod._saved_korea_bottom_image_path(parent)
                    self.assertIsNotNone(bottom_path)
                    self.assertEqual(hashlib.sha256(bottom_path.read_bytes()).hexdigest(), hashlib.sha256(bottom_bytes).hexdigest())

                    preserved, err = mod._preserved_korea_bottom_identity(parent, bottom_path)
                    self.assertIsNone(err)
                    self.assertEqual(preserved.get("bottom_shot_source"), "generated_v6_multi_ref")
                    self.assertEqual(preserved.get("bottom_shot_asset_id"), "korea_bottom_anchor")
                    # Ensure owner_email_inline_image_hashes was NOT replaced or filled
                    self.assertEqual(parent["owner_email_inline_image_hashes"], [])

    def test_korea_body_only_durable_preview_proof_fails_closed_on_bad_missing_mutated_wrong_parent(self) -> None:
        import base64
        import hashlib
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_120000_keysuri_korea_tech_p7654321"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"

        top_bytes = b"TOP_SHOT_BYTES_FAIL_TEST"
        bottom_bytes = b"BOTTOM_SHOT_BYTES_FAIL_TEST"
        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes).decode("ascii")

        valid_preview = (
            f'<figure id="top-shot-image"><img src="data:image/jpeg;base64,{top_b64}"/></figure>'
            f'<figure id="bottom-shot-image"><img src="data:image/jpeg;base64,{bottom_b64}"/></figure>'
        )

        dest_dir = Path("/tmp/genie_keysuri_korea_durable_fail_test")
        dest_dir.mkdir(parents=True, exist_ok=True)

        def fake_download(dest, *, bucket_name, object_name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(top_bytes if object_name == top_obj else bottom_bytes)
            return None

        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", side_effect=fake_download):
                    # 1. Bad proof: corrupted base64 in preview
                    bad_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": '<figure id="top-shot-image"><img src="data:image/jpeg;base64,NOT_BASE64!!!"/></figure>',
                    }
                    self.assertIsNone(mod._restore_exact_korea_parent_image(bad_parent, "top"))

                    # 2. Missing proof: preview missing
                    missing_preview_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                    }
                    self.assertIsNone(mod._restore_exact_korea_parent_image(missing_preview_parent, "top"))

                    # 3. Missing bottom object: only top object present
                    missing_bottom_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": valid_preview,
                    }
                    self.assertIsNone(mod._restore_exact_korea_parent_image(missing_bottom_parent, "top"))

                    # 4. Mutated proof: downloaded bytes don't match preview sha
                    def mutated_download(dest, *, bucket_name, object_name):
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(b"MUTATED_DIFFERENT_BYTES")
                        return None

                    with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", side_effect=mutated_download):
                        mutated_parent = {
                            "run_id": parent_run_id,
                            "mode": "keysuri_korea_tech",
                            "korea_generated_top_gcs_object": top_obj,
                            "korea_generated_bottom_gcs_object": bottom_obj,
                            "korea_generated_image_gcs_bucket": bucket,
                            "owner_email_inline_image_hashes": [],
                            "preview_html": valid_preview,
                        }
                        self.assertIsNone(mod._restore_exact_korea_parent_image(mutated_parent, "top"))

                    # 5. Wrong-parent lineage: GCS object has different run ID
                    wrong_run_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": f"{prefix}/wrong_run_id.images/korea_top.jpg",
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": valid_preview,
                    }
                    self.assertIsNone(mod._restore_exact_korea_parent_image(wrong_run_parent, "top"))

                    # 6. Wrong bucket: bucket mismatch
                    wrong_bucket_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": "unauthorized-bucket",
                        "owner_email_inline_image_hashes": [],
                        "preview_html": valid_preview,
                    }
                    self.assertIsNone(mod._restore_exact_korea_parent_image(wrong_bucket_parent, "top"))

    def test_korea_body_only_full_mime_mismatch_fails_closed(self) -> None:
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_120000_keysuri_korea_tech_mime_test"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"

        fake_cid = "cid_bottom_123"
        expected_sha = "a" * 64
        different_bytes = b"ACTUAL_BYTES_DIFFERENT"

        dest_dir = Path("/tmp/genie_keysuri_mime_mismatch_test")
        dest_dir.mkdir(parents=True, exist_ok=True)
        img_file = dest_dir / "test_bottom.jpg"
        img_file.write_bytes(different_bytes)

        parent = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "bottom_image_cid": fake_cid,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "owner_email_inline_image_hashes": [
                {"cid": fake_cid, "sha256": expected_sha, "path": str(img_file)}
            ],
        }

        # _restore_exact_korea_parent_image must return None on SHA mismatch
        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            restored = mod._restore_exact_korea_parent_image(parent, "bottom")
            self.assertIsNone(restored)

        # _preserved_korea_bottom_identity must return mismatch error
        preserved, err = mod._preserved_korea_bottom_identity(parent, img_file)
        self.assertEqual(preserved, {})
        self.assertEqual(err, "text_only_reissue_bottom_image_hash_mismatch")

    def test_run_keysuri_text_only_reissue_prerequisite_failure_paid_caller_zero(self) -> None:
        paid_caller = mock.Mock()

        # 1. Missing top image prerequisite failure -> paid caller called 0 times
        parent_no_image = {
            "run_id": "20261103_120000_keysuri_korea_tech_no_image",
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
        }
        res1 = mod.run_keysuri_text_only_reissue(
            "20261103_120000_keysuri_korea_tech_no_image",
            parent_meta=parent_no_image,
            text_caller=paid_caller,
            send_owner_email=False,
        )
        self.assertFalse(res1.get("ok"))
        self.assertEqual(res1.get("error"), "text_only_reissue_missing_saved_top_image")
        paid_caller.assert_not_called()

        # 2. Korea bottom image restore unverified -> paid caller called 0 times
        parent_bottom_unverified = {
            "run_id": "20261103_120000_keysuri_korea_tech_unverified",
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "top_image_path": "/tmp/nonexistent_top.jpg",
            "korea_generated_bottom_gcs_object": "admin_runs/unverified/korea_bottom.jpg",
        }
        existing_file = Path("/tmp/mock_existing_top.jpg")
        existing_file.write_bytes(b"TOP")
        with mock.patch.object(mod, "_saved_top_image_reference", return_value=(existing_file, {"reissue_body_only_image_local_file_present": True})):
            with mock.patch.object(mod, "_saved_korea_bottom_image_path", return_value=None):
                res2 = mod.run_keysuri_text_only_reissue(
                    "20261103_120000_keysuri_korea_tech_unverified",
                    parent_meta=parent_bottom_unverified,
                    text_caller=paid_caller,
                    send_owner_email=False,
                )
                self.assertFalse(res2.get("ok"))
                self.assertEqual(res2.get("error"), "text_only_reissue_bottom_image_restore_unverified")
                paid_caller.assert_not_called()

        # 3. Frozen-parent missing source snapshot -> paid caller called 0 times
        parent_no_snapshot = {
            "run_id": "20261103_120000_keysuri_korea_tech_no_snap",
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
        }
        with mock.patch.object(mod, "_saved_top_image_reference", return_value=(existing_file, {"reissue_body_only_image_local_file_present": True})):
            with mock.patch.object(mod, "_saved_korea_bottom_image_path", return_value=None):
                res3 = mod.run_keysuri_text_only_reissue(
                    "20261103_120000_keysuri_korea_tech_no_snap",
                    parent_meta=parent_no_snapshot,
                    frozen_parent=True,
                    text_caller=paid_caller,
                    send_owner_email=False,
                )
                self.assertFalse(res3.get("ok"))
                self.assertIn(
                    res3.get("error"),
                    ("regen_missing_parent_prompt_snapshot", "text_only_reissue_missing_parent_source_snapshot"),
                )
                paid_caller.assert_not_called()

    def test_korea_body_only_adversarial_contract_regressions(self) -> None:
        import base64
        import hashlib
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_120000_keysuri_korea_tech_adversarial"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"

        top_bytes = b"TOP_SHOT_BYTES_ADVERSARIAL"
        bottom_bytes_preview = b"BOTTOM_SHOT_BYTES_PREVIEW_VALID"
        bottom_bytes_gcs_corrupt = b"BOTTOM_SHOT_BYTES_GCS_CORRUPT"

        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes_preview).decode("ascii")

        preview_html = (
            f'<html><body>'
            f'<figure id="top-shot-image"><img src="data:image/jpeg;base64,{top_b64}" class="top-shot-hero"/></figure>'
            f'<figure id="bottom-shot-image"><img src="data:image/jpeg;base64,{bottom_b64}" class="korea-bottom-hero"/></figure>'
            f'</body></html>'
        )

        dest_dir = Path("/tmp/genie_keysuri_adv_test")
        dest_dir.mkdir(parents=True, exist_ok=True)

        def adversarial_download(dest, *, bucket_name, object_name):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if object_name == top_obj:
                dest.write_bytes(top_bytes)
            elif object_name == bottom_obj:
                dest.write_bytes(bottom_bytes_gcs_corrupt)
            return None

        # 1. Conflicting durable object / preview: top matches, bottom GCS corrupt / mismatch
        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", side_effect=adversarial_download):
                    conflict_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": preview_html,
                    }
                    # Atomic authority fails closed
                    self.assertIsNone(mod._resolve_korea_durable_preview_authority(conflict_parent))
                    self.assertIsNone(mod._restore_exact_korea_parent_image(conflict_parent, "top"))
                    self.assertIsNone(mod._restore_exact_korea_parent_image(conflict_parent, "bottom"))
                    fake_file = dest_dir / "fake_bottom.jpg"
                    fake_file.write_bytes(bottom_bytes_gcs_corrupt)
                    preserved, err = mod._preserved_korea_bottom_identity(conflict_parent, fake_file)
                    self.assertEqual(preserved, {})
                    self.assertIsNone(err)

                    # 2. Role and parent mismatches
                    # A. Swapped roles
                    swapped_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": bottom_obj,
                        "korea_generated_bottom_gcs_object": top_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": preview_html,
                    }
                    self.assertIsNone(mod._resolve_korea_durable_preview_authority(swapped_parent))

                    # B. Unknown role
                    self.assertIsNone(mod._restore_exact_korea_parent_image(conflict_parent, "sidebar"))

                    # C. Parent run ID mismatch
                    foreign_run_parent = {
                        "run_id": "different_run_id_9999",
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "preview_html": preview_html,
                    }
                    self.assertIsNone(mod._resolve_korea_durable_preview_authority(foreign_run_parent))

                    # D. Foreign html_path without parent_run_id in filename
                    foreign_html = dest_dir / "other_run_unrelated.html"
                    foreign_html.write_text(preview_html, encoding="utf-8")
                    foreign_html_parent = {
                        "run_id": parent_run_id,
                        "mode": "keysuri_korea_tech",
                        "korea_generated_top_gcs_object": top_obj,
                        "korea_generated_bottom_gcs_object": bottom_obj,
                        "korea_generated_image_gcs_bucket": bucket,
                        "owner_email_inline_image_hashes": [],
                        "html_path": str(foreign_html),
                    }
                    self.assertIsNone(mod._resolve_korea_durable_preview_authority(foreign_html_parent))

                    # E. Download issue (transient error / 503)
                    with mock.patch.object(mod, "_download_keysuri_top_image_from_gcs", return_value="503 Service Unavailable"):
                        gcs_fail_parent = {
                            "run_id": parent_run_id,
                            "mode": "keysuri_korea_tech",
                            "korea_generated_top_gcs_object": top_obj,
                            "korea_generated_bottom_gcs_object": bottom_obj,
                            "korea_generated_image_gcs_bucket": bucket,
                            "owner_email_inline_image_hashes": [],
                            "preview_html": preview_html,
                        }
                        self.assertIsNone(mod._resolve_korea_durable_preview_authority(gcs_fail_parent))

        # 3. Existing full-MIME mismatch remains strict (never falls back to preview)
        mime_cid = "cid_bottom_strict"
        valid_mime_bytes = b"MIME_BOTTOM_VALID"
        valid_mime_sha = hashlib.sha256(valid_mime_bytes).hexdigest()
        tampered_mime_bytes = b"MIME_BOTTOM_TAMPERED"
        tampered_mime_sha = hashlib.sha256(tampered_mime_bytes).hexdigest()

        tampered_file = dest_dir / "tampered_mime.jpg"
        tampered_file.write_bytes(tampered_mime_bytes)

        full_mime_parent = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "bottom_image_cid": mime_cid,
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "preview_html": preview_html,
            "owner_email_inline_image_hashes": [
                {"cid": mime_cid, "sha256": valid_mime_sha, "path": str(tampered_file)}
            ],
        }
        with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
            self.assertIsNone(mod._restore_exact_korea_parent_image(full_mime_parent, "bottom"))
            preserved, err = mod._preserved_korea_bottom_identity(full_mime_parent, tampered_file)
            self.assertEqual(preserved, {})
            self.assertEqual(err, "text_only_reissue_bottom_image_hash_mismatch")

            # Conflicting multiple hashes in owner_email_inline_image_hashes
            multi_hash_parent = {
                "run_id": parent_run_id,
                "mode": "keysuri_korea_tech",
                "bottom_image_cid": mime_cid,
                "owner_email_inline_image_hashes": [
                    {"cid": mime_cid, "sha256": valid_mime_sha},
                    {"cid": mime_cid, "sha256": tampered_mime_sha},
                ],
            }
            self.assertIsNone(mod._restore_exact_korea_parent_image(multi_hash_parent, "bottom"))
            preserved, err = mod._preserved_korea_bottom_identity(multi_hash_parent, tampered_file)
            self.assertEqual(preserved, {})
            self.assertEqual(err, "text_only_reissue_bottom_image_hash_mismatch")
            # SMTP evidence must remain untampered
            self.assertEqual(len(multi_hash_parent["owner_email_inline_image_hashes"]), 2)

        # 4. Failed prerequisites -> paidcaller0
        paid_caller = mock.Mock()
        existing_top = dest_dir / "valid_top.jpg"
        existing_top.write_bytes(top_bytes)
        existing_bottom = dest_dir / "valid_bottom.jpg"
        existing_bottom.write_bytes(bottom_bytes_preview)

        # A. Bottom image hash mismatch stops BEFORE text caller
        with mock.patch.object(mod, "_saved_top_image_reference", return_value=(existing_top, {"reissue_body_only_image_local_file_present": True})):
            with mock.patch.object(mod, "_saved_korea_bottom_image_path", return_value=existing_bottom):
                with mock.patch.object(mod, "_preserved_korea_bottom_identity", return_value=({}, "text_only_reissue_bottom_image_hash_mismatch")):
                    res_mismatch = mod.run_keysuri_text_only_reissue(
                        parent_run_id,
                        parent_meta={"run_id": parent_run_id, "mode": "keysuri_korea_tech", "program_id": "keysuri_korea_tech"},
                        text_caller=paid_caller,
                        send_owner_email=False,
                    )
                    self.assertFalse(res_mismatch.get("ok"))
                    self.assertEqual(res_mismatch.get("error"), "text_only_reissue_bottom_image_hash_mismatch")
                    paid_caller.assert_not_called()

        # B. Non-file top image when send_owner_email=True stops BEFORE text caller
        non_file_top = dest_dir / "nonexistent_top_file.jpg"
        if non_file_top.exists():
            non_file_top.unlink()
        with mock.patch.object(mod, "_saved_top_image_reference", return_value=(non_file_top, {"reissue_body_only_image_local_file_present": False})):
            res_nonfile = mod.run_keysuri_text_only_reissue(
                parent_run_id,
                parent_meta={"run_id": parent_run_id, "mode": "keysuri_korea_tech", "program_id": "keysuri_korea_tech"},
                text_caller=paid_caller,
                send_owner_email=True,
            )
            self.assertFalse(res_nonfile.get("ok"))
            self.assertEqual(res_nonfile.get("error"), "text_only_reissue_missing_saved_top_image")
            paid_caller.assert_not_called()

        # C. Unsupported mode stops BEFORE text caller
        res_unsupp = mod.run_keysuri_text_only_reissue(
            "unsupported_run",
            parent_meta={"run_id": "unsupported_run", "mode": "unsupported_mode", "program_id": "unsupported_mode"},
            text_caller=paid_caller,
            send_owner_email=False,
        )
        self.assertFalse(res_unsupp.get("ok"))
        self.assertEqual(res_unsupp.get("error"), "text_only_reissue_unsupported_mode")
        paid_caller.assert_not_called()

    def test_falsification_cold_instance_and_preview_authority_defects(self) -> None:
        import base64
        import hashlib
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_120000_keysuri_korea_tech_cold_falsification"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"
        preview_obj = f"{prefix}/{parent_run_id}.preview.html"

        top_bytes = b"TOP_IMAGE_COLD_BYTES"
        bottom_bytes = b"BOTTOM_IMAGE_COLD_BYTES"
        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes).decode("ascii")
        preview_html = (
            f'<html><body>'
            f'<figure id="top-shot-image"><img src="data:image/jpeg;base64,{top_b64}" class="top-shot-hero"/></figure>'
            f'<figure id="bottom-shot-image"><img src="data:image/jpeg;base64,{bottom_b64}" class="korea-bottom-hero"/></figure>'
            f'</body></html>'
        )

        # Cold instance parent artifact as loaded from GCS JSON: NO local preview_html, NO local file
        parent_cold = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "contract_preview_gcs_object": preview_obj,
            "owner_email_inline_image_hashes": [],
        }

        # Real storage client simulation exposing all 3 remote objects
        class FakeBlob:
            def __init__(self, data: bytes):
                self._data = data
            def exists(self):
                return True
            def download_to_filename(self, filename, **kwargs):
                Path(filename).parent.mkdir(parents=True, exist_ok=True)
                Path(filename).write_bytes(self._data)
            def download_as_bytes(self, **kwargs):
                return self._data
            def download_as_text(self, encoding="utf-8"):
                return self._data.decode(encoding)

        class FakeBucket:
            def blob(self, name):
                if name == top_obj:
                    return FakeBlob(top_bytes)
                if name == bottom_obj:
                    return FakeBlob(bottom_bytes)
                if name == preview_obj:
                    return FakeBlob(preview_html.encode("utf-8"))
                return FakeBlob(b"")

        class FakeStorageClient:
            def bucket(self, name):
                return FakeBucket()

        dest_dir = Path("/tmp/genie_keysuri_cold_falsification")
        dest_dir.mkdir(parents=True, exist_ok=True)

        with mock.patch.object(mod, "_get_gcs_client", return_value=FakeStorageClient()):
            with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
                with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                    # Falsification check 1: Cold instance with remote preview object must be hydrated and reused
                    auth = mod._resolve_korea_durable_preview_authority(parent_cold)
                    self.assertIsNotNone(auth, "DEFECT: _resolve_korea_durable_preview_authority fails on cold instance without local preview_html")

        # Falsification check 2: Duplicate contradictory role images in preview must be rejected
        duplicate_preview = (
            f'<html><body>'
            f'<figure id="top-shot-image">'
            f'<img class="top-shot-hero" src="data:image/jpeg;base64,{top_b64}"/>'
            f'<img class="top-shot-hero" src="data:image/jpeg;base64,{base64.b64encode(b"CONTRADICTORY_TOP").decode("ascii")}"/>'
            f'</figure>'
            f'</body></html>'
        )
        extracted = mod._extract_preview_data_uri(duplicate_preview, "top")
        self.assertIsNone(extracted, "DEFECT: _extract_preview_data_uri does not reject ambiguous duplicate role images")

        # Falsification check 3: Metadata-supplied _cached_korea_durable_authority bypasses proof
        injected_parent = {
            "run_id": parent_run_id,
            "_cached_korea_durable_authority": {"top": (Path("/tmp/bypass.jpg"), "fake_sha")},
        }
        self.assertIsNone(mod._resolve_korea_durable_preview_authority(injected_parent), "DEFECT: metadata-supplied _cached_korea_durable_authority bypasses verification")

    def test_cold_parent_generation_observation_and_pinning_full_flow(self) -> None:
        import base64
        import hashlib
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_183000_keysuri_korea_tech_cold_canonical"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"
        preview_obj = f"{prefix}/{parent_run_id}.preview.html"

        top_bytes = b"REALISTIC_CANONICAL_TOP_BYTES_PINNED_42"
        bottom_bytes = b"REALISTIC_CANONICAL_BOTTOM_BYTES_PINNED_42"
        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes).decode("ascii")

        # Use the actual PUBLIC canonical renderer role markers from keysuri_contract_preview_renderer.py
        realistic_preview_html = (
            '<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head><body class="premium-briefing theme-korea">\n'
            '  <header class="briefing-header"><h1 class="briefing-title">테크 비서 키수리</h1></header>\n'
            '  <figure id="top-shot-image" class="top-shot-figure hero-image-card">\n'
            f'    <img src="data:image/jpeg;base64,{top_b64}" alt="주요 테크 브리핑 이미지" class="top-shot-hero" loading="eager"/>\n'
            '  </figure>\n'
            '  <section class="briefing-content"><p>대한민국 테크 핵심 요약</p></section>\n'
            '  <figure id="bottom-shot-image" class="korea-bottom-figure">\n'
            f'    <img src="data:image/jpeg;base64,{bottom_b64}" alt="테크 비서 키수리 — 국내 18:30 마무리" class="korea-bottom-hero" loading="lazy"/>\n'
            '  </figure>\n'
            '</body></html>'
        )

        parent_cold = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "contract_preview_gcs_object": preview_obj,
            "owner_email_inline_image_hashes": [],  # Truthful empty SMTP trace for short notice
            "bottom_shot_source": "generated_v6_multi_ref",
            "bottom_shot_asset_id": "korea_bottom_anchor_42",
        }

        # Track and verify exact generation observation and kwargs passed
        preview_gen = 5001
        top_gen = 5002
        bottom_gen = 5003

        class PinnedGenerationBlob:
            def __init__(self, data: bytes, generation: int):
                self._data = data
                self.generation = generation
                self.calls = []

            def exists(self):
                return True

            def download_as_bytes(self, **kwargs):
                self.calls.append(("download_as_bytes", kwargs))
                match_gen = kwargs.get("if_generation_match")
                if match_gen is not None and int(match_gen) != self.generation:
                    raise RuntimeError(f"Generation precondition failed: {match_gen} != {self.generation}")
                return self._data

            def download_to_filename(self, filename, **kwargs):
                self.calls.append(("download_to_filename", kwargs))
                match_gen = kwargs.get("if_generation_match")
                if match_gen is not None and int(match_gen) != self.generation:
                    raise RuntimeError(f"Generation precondition failed: {match_gen} != {self.generation}")
                dest_p = Path(filename)
                dest_p.parent.mkdir(parents=True, exist_ok=True)
                dest_p.write_bytes(self._data)

        preview_blob = PinnedGenerationBlob(realistic_preview_html.encode("utf-8"), preview_gen)
        top_blob = PinnedGenerationBlob(top_bytes, top_gen)
        bottom_blob = PinnedGenerationBlob(bottom_bytes, bottom_gen)

        class PinnedBucket:
            def blob(self, name):
                if name == preview_obj:
                    return preview_blob
                if name == top_obj:
                    return top_blob
                if name == bottom_obj:
                    return bottom_blob
                raise KeyError(name)

        class PinnedClient:
            def bucket(self, name):
                if name == bucket:
                    return PinnedBucket()
                raise KeyError(name)

        dest_dir = Path("/tmp/genie_keysuri_pinned_flow_test")
        dest_dir.mkdir(parents=True, exist_ok=True)

        with mock.patch.object(mod, "_get_gcs_client", return_value=PinnedClient()):
            with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
                with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                    # 1. Authority resolution: must fetch preview with generation match, then both images with generation match
                    auth = mod._resolve_korea_durable_preview_authority(parent_cold)
                    self.assertIsNotNone(auth)
                    self.assertIn("top", auth)
                    self.assertIn("bottom", auth)

                    # Verify actual generation observation + if_generation_match kwargs passed
                    self.assertTrue(len(preview_blob.calls) >= 1)
                    prev_kw = preview_blob.calls[0][1]
                    self.assertEqual(prev_kw.get("if_generation_match"), preview_gen)

                    self.assertTrue(len(top_blob.calls) >= 1)
                    top_kw = top_blob.calls[0][1]
                    self.assertEqual(top_kw.get("if_generation_match"), top_gen)

                    self.assertTrue(len(bottom_blob.calls) >= 1)
                    bottom_kw = bottom_blob.calls[0][1]
                    self.assertEqual(bottom_kw.get("if_generation_match"), bottom_gen)

                    # Verify exact pixel bytes match
                    dest_top_file, top_sha = auth["top"]
                    dest_bottom_file, bottom_sha = auth["bottom"]
                    self.assertEqual(top_sha, hashlib.sha256(top_bytes).hexdigest())
                    self.assertEqual(bottom_sha, hashlib.sha256(bottom_bytes).hexdigest())
                    self.assertEqual(dest_top_file.read_bytes(), top_bytes)
                    self.assertEqual(dest_bottom_file.read_bytes(), bottom_bytes)

                    # 2. Exact restore functions reuse these authority files
                    restored_top = mod._restore_exact_korea_parent_image(parent_cold, "top")
                    self.assertEqual(restored_top, dest_top_file)

                    restored_bottom = mod._restore_exact_korea_parent_image(parent_cold, "bottom")
                    self.assertEqual(restored_bottom, dest_bottom_file)

                    # 3. Preserve exact verified bottom reference identity
                    preserved, err = mod._preserved_korea_bottom_identity(parent_cold, dest_bottom_file)
                    self.assertIsNone(err)
                    self.assertEqual(preserved.get("bottom_shot_source"), "generated_v6_multi_ref")
                    self.assertEqual(preserved.get("bottom_shot_asset_id"), "korea_bottom_anchor_42")

                    # 4. Truthful empty SMTP trace remains unmodified
                    self.assertEqual(parent_cold["owner_email_inline_image_hashes"], [])

    def test_generation_race_conflict_and_tampered_proof_fail_closed(self) -> None:
        import base64
        from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

        parent_run_id = "20261103_183000_keysuri_korea_tech_race_fail"
        bucket = admin_artifact_bucket_name() or "test-artifact-bucket"
        prefix = admin_artifact_gcs_prefix()
        top_obj = f"{prefix}/{parent_run_id}.images/korea_top.jpg"
        bottom_obj = f"{prefix}/{parent_run_id}.images/korea_bottom.jpg"
        preview_obj = f"{prefix}/{parent_run_id}.preview.html"

        top_bytes = b"TOP_SHOT_RACE_TEST_BYTES"
        bottom_bytes = b"BOTTOM_SHOT_RACE_TEST_BYTES"
        top_b64 = base64.b64encode(top_bytes).decode("ascii")
        bottom_b64 = base64.b64encode(bottom_bytes).decode("ascii")

        parent = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "program_id": "keysuri_korea_tech",
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "contract_preview_gcs_object": preview_obj,
            "owner_email_inline_image_hashes": [],
        }

        dest_dir = Path("/tmp/genie_keysuri_race_fail_test")
        dest_dir.mkdir(parents=True, exist_ok=True)

        # 1. Preview download generation mismatch / PreconditionFailed exception fails closed
        class RaceMismatchBlob:
            def __init__(self, data: bytes, generation: int):
                self._data = data
                self.generation = generation

            def exists(self):
                return True

            def download_as_bytes(self, **kwargs):
                raise RuntimeError("412 Precondition Failed")

            def download_to_filename(self, filename, **kwargs):
                raise RuntimeError("412 Precondition Failed")

        class RaceClient:
            def bucket(self, name):
                return RaceBucket()

        class RaceBucket:
            def blob(self, name):
                return RaceMismatchBlob(b"DATA", 9999)

        with mock.patch.object(mod, "_get_gcs_client", return_value=RaceClient()):
            with mock.patch.object(mod, "_writable_keysuri_service_assets_dir", return_value=dest_dir):
                with mock.patch.object(mod, "admin_artifact_bucket_name", return_value=bucket):
                    self.assertIsNone(mod._resolve_korea_durable_preview_authority(parent))

        # 2. _download_keysuri_top_image_from_gcs generation mismatch detection
        class MutatedGenBlob:
            def __init__(self):
                self.generation = 99999

            def exists(self):
                return True

            def download_to_filename(self, filename, **kwargs):
                pass

        class MutatedBucket:
            def blob(self, name):
                return MutatedGenBlob()

        class MutatedClient:
            def bucket(self, name):
                return MutatedBucket()

        with mock.patch.object(mod, "_get_gcs_client", return_value=MutatedClient()):
            err_code = mod._download_keysuri_top_image_from_gcs(
                dest_dir / "probe.jpg",
                bucket_name=bucket,
                object_name=top_obj,
                if_generation_match=11111,  # mismatch with 99999
            )
            self.assertEqual(err_code, "top_image_gcs_generation_mismatch")

        # 3. Canonical renderer role markers: single image with container and img class is ONE image, not duplicate
        legit_html = (
            f'<figure id="top-shot-image" class="hero-image-card"><img src="data:image/jpeg;base64,{top_b64}" class="top-shot-hero"/></figure>'
        )
        self.assertEqual(mod._extract_preview_data_uri(legit_html, "top"), top_bytes)

        # Ambiguous duplicate: container has two images -> fails closed
        duplicate_html = (
            f'<figure id="top-shot-image">'
            f'<img src="data:image/jpeg;base64,{top_b64}" class="top-shot-hero"/>'
            f'<img src="data:image/jpeg;base64,{bottom_b64}" class="top-shot-hero"/>'
            f'</figure>'
        )
        self.assertIsNone(mod._extract_preview_data_uri(duplicate_html, "top"))

        # 4. Existing nonempty SMTP trace with wrong CID/hash NEVER falls back to preview authority
        tampered_smtp_parent = {
            "run_id": parent_run_id,
            "mode": "keysuri_korea_tech",
            "top_image_cid": "cid_expected",
            "bottom_image_cid": "cid_bottom_expected",
            "korea_generated_top_gcs_object": top_obj,
            "korea_generated_bottom_gcs_object": bottom_obj,
            "korea_generated_image_gcs_bucket": bucket,
            "contract_preview_gcs_object": preview_obj,
            # Non-empty SMTP trace but wrong CID:
            "owner_email_inline_image_hashes": [
                {"cid": "cid_wrong", "sha256": "0" * 64}
            ],
        }
        self.assertIsNone(mod._restore_exact_korea_parent_image(tampered_smtp_parent, "top"))
        self.assertIsNone(mod._restore_exact_korea_parent_image(tampered_smtp_parent, "bottom"))
        bottom_probe = dest_dir / "bottom_probe.jpg"
        bottom_probe.write_bytes(bottom_bytes)
        pres, pres_err = mod._preserved_korea_bottom_identity(tampered_smtp_parent, bottom_probe)
        self.assertEqual(pres, {})
        self.assertEqual(pres_err, "text_only_reissue_bottom_image_hash_mismatch")


if __name__ == "__main__":
    unittest.main()
