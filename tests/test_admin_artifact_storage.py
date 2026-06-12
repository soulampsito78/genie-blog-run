"""Admin artifact storage backends: local fallback and durable GCS."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from admin_store import (
    admin_artifact_bucket_name,
    admin_artifact_gcs_prefix,
    artifact_storage_backend_name,
    artifact_store_display_path,
    check_artifact_store_ready,
    gcs_contract_preview_object_key,
    gcs_email_object_key,
    gcs_json_object_key,
    is_artifact_storage_durable,
    list_run_artifacts,
    load_run_artifact,
    load_run_email_html,
    save_run_artifact,
)
from fastapi.testclient import TestClient
from main import app


class _FakeBlob:
    def __init__(self, store: dict[str, str], key: str) -> None:
        self._store = store
        self.name = key
        self.updated = None
        self.time_created = None

    def exists(self) -> bool:
        return self.name in self._store

    def upload_from_string(self, data: str, content_type: str | None = None) -> None:
        self._store[self.name] = data

    def download_as_text(self, encoding: str = "utf-8") -> str:
        return self._store[self.name]

    def delete(self) -> None:
        self._store.pop(self.name, None)


class _FakeBucket:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def blob(self, key: str) -> _FakeBlob:
        return _FakeBlob(self._store, key)

    def list_blobs(self, *, prefix: str = "") -> list[_FakeBlob]:
        keys = sorted(k for k in self._store if k.startswith(prefix))
        return [_FakeBlob(self._store, k) for k in keys]


class AdminArtifactStorageEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_bucket = os.environ.get("GENIE_ADMIN_ARTIFACT_BUCKET")
        self._prev_prefix = os.environ.get("GENIE_ADMIN_ARTIFACT_GCS_PREFIX")
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        os.environ.pop("GENIE_ADMIN_ARTIFACT_GCS_PREFIX", None)

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_ARTIFACT_BUCKET", self._prev_bucket),
            ("GENIE_ADMIN_ARTIFACT_GCS_PREFIX", self._prev_prefix),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def test_local_backend_when_bucket_unset(self) -> None:
        self.assertIsNone(admin_artifact_bucket_name())
        self.assertEqual(artifact_storage_backend_name(), "local")
        self.assertFalse(is_artifact_storage_durable())
        err, desc = check_artifact_store_ready()
        self.assertIsNone(err)
        assert desc is not None
        self.assertEqual(desc.get("backend"), "local")
        self.assertFalse(desc.get("durable"))

    def test_gcs_key_construction(self) -> None:
        os.environ["GENIE_ADMIN_ARTIFACT_GCS_PREFIX"] = "artifacts/admin"
        run_id = "20260612_120000_today_genie_aabbccdd"
        self.assertEqual(
            gcs_json_object_key(run_id),
            "artifacts/admin/20260612_120000_today_genie_aabbccdd.json",
        )
        self.assertEqual(
            gcs_email_object_key(run_id),
            "artifacts/admin/20260612_120000_today_genie_aabbccdd.email.html",
        )
        self.assertEqual(
            gcs_contract_preview_object_key(run_id),
            "artifacts/admin/20260612_120000_today_genie_aabbccdd.contract_preview.html",
        )

    def test_durable_true_only_for_gcs_backend_name(self) -> None:
        self.assertFalse(is_artifact_storage_durable())
        os.environ["GENIE_ADMIN_ARTIFACT_BUCKET"] = "genie-artifacts-test"
        self.assertEqual(artifact_storage_backend_name(), "gcs")
        self.assertTrue(is_artifact_storage_durable())
        self.assertTrue(
            artifact_store_display_path().startswith("gs://genie-artifacts-test/")
        )


class LocalArtifactStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._runs_dir = Path(self._tmpdir.name) / "admin_runs"
        self._runs_dir.mkdir(parents=True)
        self._prev_bucket = os.environ.get("GENIE_ADMIN_ARTIFACT_BUCKET")
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        if self._prev_bucket is None:
            os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        else:
            os.environ["GENIE_ADMIN_ARTIFACT_BUCKET"] = self._prev_bucket

    @patch("admin_store.admin_runs_dir")
    def test_local_save_read_json_and_email(self, mock_runs_dir: MagicMock) -> None:
        mock_runs_dir.return_value = self._runs_dir
        run_id = "20260612_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
            },
            email_html="<p>owner review</p>",
        )
        meta = load_run_artifact(run_id)
        assert meta is not None
        self.assertEqual(meta.get("artifact_storage_backend"), "local")
        self.assertFalse(meta.get("artifact_storage_durable"))
        self.assertEqual(load_run_email_html(run_id), "<p>owner review</p>")
        listed = list_run_artifacts(limit=10)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].get("run_id"), run_id)

    @patch("admin_store.admin_runs_dir")
    def test_local_missing_run_returns_none(self, mock_runs_dir: MagicMock) -> None:
        mock_runs_dir.return_value = self._runs_dir
        run_id = "20260612_130000_today_genie_bbccddee"
        self.assertIsNone(load_run_artifact(run_id))
        self.assertIsNone(load_run_email_html(run_id))


class GcsArtifactStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._store: dict[str, str] = {}
        self._prev_bucket = os.environ.get("GENIE_ADMIN_ARTIFACT_BUCKET")
        self._prev_prefix = os.environ.get("GENIE_ADMIN_ARTIFACT_GCS_PREFIX")
        os.environ["GENIE_ADMIN_ARTIFACT_BUCKET"] = "genie-artifacts-test"
        os.environ.pop("GENIE_ADMIN_ARTIFACT_GCS_PREFIX", None)
        import admin_store as admin_store_module

        admin_store_module._gcs_client = None

    def tearDown(self) -> None:
        import admin_store as admin_store_module

        admin_store_module._gcs_client = None
        for key, prev in (
            ("GENIE_ADMIN_ARTIFACT_BUCKET", self._prev_bucket),
            ("GENIE_ADMIN_ARTIFACT_GCS_PREFIX", self._prev_prefix),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def _patch_gcs(self):
        fake_bucket = _FakeBucket(self._store)

        def _client() -> MagicMock:
            client = MagicMock()
            client.bucket.return_value = fake_bucket
            return client

        return patch("admin_store._get_gcs_client", side_effect=_client)

    def test_gcs_save_read_json_and_email(self) -> None:
        run_id = "20260612_140000_today_genie_ccddeeff"
        with self._patch_gcs():
            save_run_artifact(
                {
                    "run_id": run_id,
                    "mode": "today_genie",
                    "validation_result": "pass",
                    "workflow_status": "validated",
                    "email_sent": True,
                    "response_status": 200,
                },
                email_html="<p>gcs email</p>",
            )
            meta = load_run_artifact(run_id)
            assert meta is not None
            self.assertEqual(meta.get("artifact_storage_backend"), "gcs")
            self.assertTrue(meta.get("artifact_storage_durable"))
            self.assertEqual(load_run_email_html(run_id), "<p>gcs email</p>")
            self.assertIn(gcs_json_object_key(run_id), self._store)
            self.assertIn(gcs_email_object_key(run_id), self._store)
            listed = list_run_artifacts(limit=10)
            self.assertEqual(len(listed), 1)

    def test_gcs_optional_contract_preview_upload(self) -> None:
        run_id = "20260612_150000_keysuri_global_tech_ddeeff00"
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.html"
            preview.write_text("<html>contract</html>", encoding="utf-8")
            with self._patch_gcs():
                save_run_artifact(
                    {
                        "run_id": run_id,
                        "mode": "keysuri_global_tech",
                        "validation_result": "pass",
                        "html_path": str(preview),
                    },
                    email_html="<p>review</p>",
                )
                key = gcs_contract_preview_object_key(run_id)
                self.assertIn(key, self._store)
                meta = load_run_artifact(run_id)
                assert meta is not None
                self.assertEqual(meta.get("contract_preview_gcs_object"), key)

    def test_gcs_missing_run_returns_none(self) -> None:
        run_id = "20260612_160000_today_genie_eeff0011"
        with self._patch_gcs():
            self.assertIsNone(load_run_artifact(run_id))
            self.assertIsNone(load_run_email_html(run_id))

    def test_gcs_check_artifact_store_ready(self) -> None:
        with self._patch_gcs():
            err, desc = check_artifact_store_ready()
        self.assertIsNone(err)
        assert desc is not None
        self.assertEqual(desc.get("backend"), "gcs")
        self.assertTrue(desc.get("durable"))


class AdminRoutesArtifact404Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        self._prev_bucket = os.environ.get("GENIE_ADMIN_ARTIFACT_BUCKET")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd
        if self._prev_bucket is None:
            os.environ.pop("GENIE_ADMIN_ARTIFACT_BUCKET", None)
        else:
            os.environ["GENIE_ADMIN_ARTIFACT_BUCKET"] = self._prev_bucket

    @patch("admin_store._read_json_blob", return_value=None)
    def test_admin_run_detail_missing_artifact_404(self, _mock_read: MagicMock) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260612_170000_today_genie_ff001122"
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("실행 기록을 찾을 수 없습니다", resp.text)


if __name__ == "__main__":
    unittest.main()
