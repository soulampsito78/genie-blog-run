from __future__ import annotations

import hashlib
import gc
import json
import os
import tempfile
import tracemalloc
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import admin_notice_store
import admin_safety_store
import admin_store
import memory_observability
from email_sender import last_send_trace, send_genie_email


class _Blob:
    def __init__(self, store: dict[str, str], name: str, downloads: dict[str, int]) -> None:
        self._store = store
        self._downloads = downloads
        self.name = name
        self.updated = None
        self.time_created = None
        self.size: int | None = None

    def download_as_text(self, encoding: str = "utf-8") -> str:
        self._downloads[self.name] = self._downloads.get(self.name, 0) + 1
        return self._store[self.name]

    def exists(self) -> bool:
        return self.name in self._store

    def reload(self) -> None:
        self.size = len(self._store[self.name].encode("utf-8"))

    def download_as_bytes(self, *, start: int = 0, end: int | None = None) -> bytes:
        self._downloads[self.name] = self._downloads.get(self.name, 0) + 1
        payload = self._store[self.name].encode("utf-8")
        return payload[start : None if end is None else end + 1]

    def upload_from_string(self, data: str, content_type: str | None = None) -> None:
        self._store[self.name] = data


class _Bucket:
    def __init__(self, store: dict[str, str]) -> None:
        self.store = store
        self.downloads: dict[str, int] = {}
        self.max_results_seen: list[int] = []
        self.yielded = 0

    def list_blobs(self, *, prefix: str = "", max_results: int | None = None):
        if max_results is not None:
            self.max_results_seen.append(max_results)
        names = sorted(name for name in self.store if name.startswith(prefix))
        if max_results is not None:
            names = names[:max_results]
        for name in names:
            self.yielded += 1
            yield _Blob(self.store, name, self.downloads)

    def blob(self, name: str) -> _Blob:
        return _Blob(self.store, name, self.downloads)


class _SMTP:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, *_args) -> None:
        return None

    def sendmail(self, *_args) -> dict:
        return {}


class AdminMemoryBoundaryTests(unittest.TestCase):
    def test_run_summary_excludes_heavy_documents_and_bounds_lists(self) -> None:
        summary = admin_store.build_run_artifact_list_summary(
            {
                "run_id": "20260814_183000_keysuri_korea_tech_aaaaaaaa",
                "mode": "keysuri_korea_tech",
                "issue_codes": [f"issue-{i}" for i in range(500)],
                "policy": {"send_email": False, "full_source_pack": "x" * 100_000},
                "email_html": "<html>" + "x" * 100_000,
                "source_documents": [{"body": "x" * 100_000}],
                "image_bytes": b"x" * 100_000,
            }
        )
        self.assertTrue(summary["artifact_list_summary"])
        self.assertEqual(len(summary["issue_codes"]), 50)
        self.assertEqual(summary["policy"], {"send_email": False})
        self.assertNotIn("email_html", summary)
        self.assertNotIn("source_documents", summary)
        self.assertNotIn("image_bytes", summary)

    def test_local_run_list_uses_summary_without_loading_full_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("admin_store.admin_runs_dir", return_value=root), mock.patch(
                "admin_store._uses_gcs_backend", return_value=False
            ):
                for second in range(6):
                    run_id = f"20260814_1830{second:02d}_keysuri_korea_tech_{second:08x}"
                    admin_store.save_run_artifact(
                        {
                            "run_id": run_id,
                            "mode": "keysuri_korea_tech",
                            "validation_result": "pass",
                            "source_documents": [{"body": "x" * 100_000}],
                        }
                    )
                with mock.patch(
                    "admin_store.load_run_artifact",
                    side_effect=AssertionError("full artifact must stay detail-only"),
                ):
                    rows = admin_store.list_run_artifacts(limit=3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.get("artifact_list_summary") for row in rows))
        self.assertTrue(all("source_documents" not in row for row in rows))

    def test_gcs_run_enumeration_is_bounded_and_downloads_summaries_only(self) -> None:
        prefix = "admin_runs"
        month = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m")
        store: dict[str, str] = {}
        full_keys: list[str] = []
        for index in range(8):
            run_id = f"{month}14_1830{index:02d}_keysuri_korea_tech_{index:08x}"
            full_key = f"{prefix}/{run_id}.json"
            summary_key = f"{prefix}/{run_id}.summary.json"
            full_keys.append(full_key)
            store[full_key] = json.dumps(
                {"run_id": run_id, "mode": "keysuri_korea_tech", "source_documents": "x" * 100_000}
            )
            store[summary_key] = json.dumps(
                {"artifact_list_summary": True, "run_id": run_id, "mode": "keysuri_korea_tech"}
            )
            store[f"{prefix}/{run_id}.email.html"] = "<html>large</html>"
        bucket = _Bucket(store)
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            rows = admin_store.list_run_artifacts(limit=3)
        self.assertEqual(len(rows), 3)
        self.assertTrue(bucket.max_results_seen)
        self.assertLessEqual(max(bucket.max_results_seen), admin_store.ADMIN_RUN_LIST_GCS_SCAN_MAX)
        self.assertTrue(all(bucket.downloads.get(key, 0) == 0 for key in full_keys))
        # One extra summary establishes the page cursor; no full document is read.
        self.assertLessEqual(sum(bucket.downloads.values()), 4)

    def test_gcs_legacy_run_list_never_downloads_full_json(self) -> None:
        prefix = "admin_runs"
        day = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        store = {
            f"{prefix}/{day}_1200{index:02d}_today_genie_{index:08x}.json": json.dumps(
                {"run_id": "must-not-be-read", "source_documents": "x" * 100_000}
            )
            for index in range(10)
        }
        bucket = _Bucket(store)
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            rows = admin_store.list_run_artifacts(limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(bucket.downloads, {})
        self.assertTrue(all(row.get("summary_available") is False for row in rows))
        self.assertTrue(all(row.get("summary_source") == "legacy_object_metadata" for row in rows))

    def test_run_overflow_returns_newest_and_cursor_page(self) -> None:
        prefix = "admin_runs"
        base = datetime.now(ZoneInfo("Asia/Seoul")).replace(
            hour=1, minute=0, second=0, microsecond=0
        )
        store: dict[str, str] = {}
        run_ids: list[str] = []
        for index in range(3_000):
            stamp = base + timedelta(seconds=index)
            run_id = (
                f"{stamp.strftime('%Y%m%d_%H%M%S')}_today_genie_{index:08x}"
            )
            run_ids.append(run_id)
            store[f"{prefix}/{run_id}.json"] = "{}"
            store[f"{prefix}/{run_id}.summary.json"] = json.dumps(
                {
                    "artifact_list_summary": True,
                    "run_id": run_id,
                    "mode": "today_genie",
                    "created_at": stamp.isoformat(),
                }
            )
        bucket = _Bucket(store)
        pages: list[dict] = []
        rows: list[dict] = []
        cursor = ""
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            for _ in range(61):
                yielded_before = bucket.yielded
                page = admin_store.list_run_artifact_page(limit=50, cursor=cursor)
                self.assertLessEqual(
                    bucket.yielded - yielded_before,
                    admin_store.ADMIN_RUN_LIST_GCS_SCAN_MAX,
                )
                pages.append(page)
                rows.extend(page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
                self.assertTrue(cursor)
        expected = sorted(run_ids, reverse=True)
        self.assertEqual(len(pages), 60)
        self.assertFalse(pages[-1]["has_more"])
        self.assertEqual([row["run_id"] for row in rows], expected)
        self.assertLessEqual(
            max(bucket.max_results_seen), admin_store.ADMIN_RUN_LIST_PREFIX_SCAN_MAX
        )

    def test_local_backfill_is_explicit_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260814_120000_today_genie_abcdef12"
            (root / f"{run_id}.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "mode": "today_genie",
                        "validation_result": "pass",
                        "source_documents": [{"body": "large"}],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch("admin_store.admin_runs_dir", return_value=root), mock.patch(
                "admin_store._uses_gcs_backend", return_value=False
            ):
                dry = admin_store.backfill_recent_run_list_summaries(limit=1)
                self.assertEqual(dry["written"], 0)
                self.assertFalse(admin_store.artifact_summary_path(run_id).exists())
                applied = admin_store.backfill_recent_run_list_summaries(
                    limit=1, dry_run=False
                )
                summary = json.loads(
                    admin_store.artifact_summary_path(run_id).read_text(encoding="utf-8")
                )
        self.assertEqual(applied["written"], 1)
        self.assertNotIn("source_documents", summary)

    def test_memory_evidence_sidecar_does_not_rewrite_full_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260814_120000_today_genie_abcdef12"
            with mock.patch("admin_store.admin_runs_dir", return_value=root), mock.patch(
                "admin_store._uses_gcs_backend", return_value=False
            ):
                admin_store.save_run_artifact(
                    {"run_id": run_id, "mode": "today_genie", "validation_result": "pass"}
                )
                before = admin_store.artifact_json_path(run_id).read_bytes()
                saved = admin_store.save_run_memory_evidence(
                    run_id,
                    {
                        "source": "proc_status",
                        "peak_hwm_kib": 123,
                        "html": "must-not-persist",
                        "stages": {
                            "request_start": {"rss_kib": 100, "hwm_kib": 120},
                            "unknown": {"rss_kib": 999, "hwm_kib": 999},
                        },
                    },
                )
                loaded = admin_store.load_run_memory_evidence(run_id)
                after = admin_store.artifact_json_path(run_id).read_bytes()
                rows = admin_store.list_run_artifacts(limit=10)
        self.assertEqual(before, after)
        self.assertEqual(loaded, saved)
        self.assertNotIn("html", loaded or {})
        self.assertNotIn("unknown", (loaded or {}).get("stages", {}))
        self.assertEqual(len(rows), 1)

    def test_memory_evidence_recomputes_peak_headroom_and_hwm(self) -> None:
        normalized = admin_store._normalize_run_memory_evidence(
            {
                "source": "proc_status",
                "configured_limit_kib": 786_432,
                "peak_hwm_kib": 999_999,
                "headroom_kib": 1,
                "stages": {
                    "request_start": {"rss_kib": 200, "hwm_kib": 100},
                    "request_end": {"rss_kib": 250, "hwm_kib": 300},
                },
            }
        )
        self.assertEqual(normalized["stages"]["request_start"]["hwm_kib"], 200)
        self.assertEqual(normalized["peak_hwm_kib"], 300)
        self.assertEqual(normalized["headroom_kib"], 786_132)

    def test_memory_sidecar_reads_are_byte_bounded_local_and_gcs(self) -> None:
        run_id = "20260814_120000_today_genie_abcdef12"
        oversized = "x" * (admin_store.ADMIN_RUN_MEMORY_MAX_BYTES + 1)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "admin_store.admin_runs_dir", return_value=Path(tmp)
        ), mock.patch("admin_store._uses_gcs_backend", return_value=False):
            admin_store.artifact_memory_path(run_id).write_text(
                oversized, encoding="utf-8"
            )
            self.assertIsNone(admin_store.load_run_memory_evidence(run_id))

        key = f"admin_runs/{run_id}.memory.json"
        bucket = _Bucket({key: oversized})
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            self.assertIsNone(admin_store.load_run_memory_evidence(run_id))
        self.assertEqual(bucket.downloads, {})

    def test_configured_memory_gib_uses_768_mib_cgroup_limit(self) -> None:
        with mock.patch(
            "memory_observability.configured_memory_limit_kib",
            return_value=786_432,
        ):
            self.assertEqual(memory_observability.configured_memory_limit_gib(), 0.75)
        with mock.patch(
            "memory_observability.configured_memory_limit_kib", return_value=0
        ):
            self.assertEqual(memory_observability.configured_memory_limit_gib(), 0.5)

    def test_email_html_exists_uses_metadata_only(self) -> None:
        store = {"admin_runs/20260814_120000_today_genie_abcdef12.email.html": "large"}
        bucket = _Bucket(store)
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            self.assertTrue(
                admin_store.run_email_html_exists(
                    "20260814_120000_today_genie_abcdef12"
                )
            )
        self.assertEqual(bucket.downloads, {})

    def test_email_html_cap_blocks_oversized_local_and_gcs_reads(self) -> None:
        run_id = "20260814_120000_today_genie_abcdef12"
        oversized = "x" * (admin_store.ADMIN_EMAIL_HTML_MAX_BYTES + 1)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "admin_store.admin_runs_dir", return_value=Path(tmp)
        ), mock.patch("admin_store._uses_gcs_backend", return_value=False):
            admin_store.artifact_email_path(run_id).write_bytes(oversized.encode("utf-8"))
            self.assertFalse(admin_store.run_email_html_exists(run_id))
            self.assertIsNone(admin_store.load_run_email_html(run_id))

        key = f"admin_runs/{run_id}.email.html"
        bucket = _Bucket({key: oversized})
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            self.assertFalse(admin_store.run_email_html_exists(run_id))
            self.assertIsNone(admin_store.load_run_email_html(run_id))
        self.assertEqual(bucket.downloads, {})

    def test_email_html_gcs_read_is_metadata_checked_and_range_bounded(self) -> None:
        run_id = "20260814_120000_today_genie_abcdef12"
        key = f"admin_runs/{run_id}.email.html"
        bucket = _Bucket({key: "<html>bounded</html>"})
        with mock.patch("admin_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_store._get_gcs_bucket", return_value=bucket
        ):
            self.assertEqual(
                admin_store.load_run_email_html(run_id), "<html>bounded</html>"
            )
        self.assertEqual(bucket.downloads, {key: 1})

    def test_notice_list_reads_metadata_summary_not_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"K_SERVICE": ""}, clear=False
        ), mock.patch(
            "admin_notice_store.admin_notices_dir", return_value=Path(tmp)
        ), mock.patch("admin_notice_store._uses_gcs_backend", return_value=False):
            notice = admin_notice_store.create_notice_draft(
                notice_type="custom_notice",
                program_id="all",
                related_run_id=None,
                subject="subject",
                body_text="x" * 100_000,
                body_html="<p>" + "x" * 100_000 + "</p>",
            )
            rows = admin_notice_store.list_notices(limit=10)
        self.assertEqual(rows[0]["notice_id"], notice["notice_id"])
        self.assertNotIn("body_text", rows[0])
        self.assertNotIn("body_html", rows[0])

    def test_notice_overflow_returns_newest_and_cursor_page(self) -> None:
        base = datetime.now(ZoneInfo("Asia/Seoul")).replace(
            hour=1, minute=0, second=0, microsecond=0
        )
        store: dict[str, str] = {}
        expected: list[tuple[str, str]] = []
        for index in range(3_000):
            created = base + timedelta(microseconds=index * 100_000)
            order_key = created.strftime("%Y%m%dT%H%M%S%f")
            notice_id = f"notice_custom_notice_{created.strftime('%Y%m%d')}_{index:08x}"
            key = (
                f"{admin_notice_store.NOTICE_LIST_INDEX_PREFIX}/{order_key}_{notice_id}"
                f"{admin_notice_store.NOTICE_LIST_SUMMARY_SUFFIX}"
            )
            store[key] = json.dumps(
                {
                    "notice_list_summary": True,
                    "notice_id": notice_id,
                    "notice_type": "custom_notice",
                    "created_at": created.isoformat(),
                }
            )
            expected.append((order_key, notice_id))
        bucket = _Bucket(store)
        pages: list[dict] = []
        rows: list[dict] = []
        cursor = ""
        with mock.patch("admin_notice_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_notice_store._get_gcs_bucket", return_value=bucket
        ):
            for _ in range(61):
                yielded_before = bucket.yielded
                page = admin_notice_store.list_notice_page(limit=50, cursor=cursor)
                self.assertLessEqual(
                    bucket.yielded - yielded_before,
                    admin_notice_store.ADMIN_NOTICE_GCS_SCAN_MAX,
                )
                pages.append(page)
                rows.extend(page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
                self.assertTrue(cursor)
        newest = [notice_id for _key, notice_id in sorted(expected, reverse=True)]
        self.assertEqual(len(pages), 60)
        self.assertFalse(pages[-1]["has_more"])
        self.assertEqual([row["notice_id"] for row in rows], newest)
        self.assertLessEqual(
            max(bucket.max_results_seen),
            admin_notice_store.ADMIN_NOTICE_PREFIX_SCAN_MAX,
        )

    def test_retired_timeout_returns_before_any_artifact_scan(self) -> None:
        with mock.patch(
            "admin_store.list_run_artifacts",
            side_effect=AssertionError("retired timeout must not scan"),
        ):
            summary = admin_store.process_approval_timeouts()
        self.assertTrue(summary["retired"])
        self.assertEqual(summary["scanned"], 0)
        self.assertEqual(summary["sent"], 0)

    def test_delivery_event_history_is_bounded(self) -> None:
        meta: dict = {}
        for index in range(admin_store.MAX_CUSTOMER_DELIVERY_EVENTS_PER_RUN + 20):
            admin_store.append_customer_delivery_event(meta, {"sequence": index})
        self.assertEqual(
            len(meta["customer_delivery_events"]),
            admin_store.MAX_CUSTOMER_DELIVERY_EVENTS_PER_RUN,
        )
        self.assertEqual(
            meta["customer_delivery_event_count"],
            admin_store.MAX_CUSTOMER_DELIVERY_EVENTS_PER_RUN + 20,
        )
        self.assertTrue(meta["customer_delivery_events_truncated"])

    def test_audit_sanitizer_caps_dict_and_list_values(self) -> None:
        sanitized = admin_safety_store.sanitize_audit_metadata(
            {
                "rows": list(range(500)),
                **{f"key-{i}": i for i in range(500)},
            }
        )
        self.assertLessEqual(len(sanitized), admin_safety_store.MAX_AUDIT_METADATA_DICT_ITEMS)
        self.assertEqual(
            len(sanitized["rows"]), admin_safety_store.MAX_AUDIT_METADATA_LIST_ITEMS
        )

    def test_audit_overflow_returns_newest_and_cursor_page(self) -> None:
        base = datetime.now(ZoneInfo("Asia/Seoul")).replace(
            hour=1, minute=0, second=0, microsecond=0
        )
        store: dict[str, str] = {}
        event_ids: list[str] = []
        for index in range(3_000):
            created = base + timedelta(seconds=index)
            event_id = f"evt_{created.strftime('%Y%m%dT%H%M%S')}_{index:012x}"
            event_ids.append(event_id)
            store[
                f"{admin_safety_store.SAFETY_PREFIX}/operator_audit/{event_id}.json"
            ] = json.dumps({"event_id": event_id, "timestamp": created.isoformat()})
        bucket = _Bucket(store)
        pages: list[dict] = []
        rows: list[dict] = []
        cursor = ""
        with mock.patch("admin_safety_store._uses_gcs_backend", return_value=True), mock.patch(
            "admin_safety_store._get_gcs_bucket", return_value=bucket
        ), mock.patch(
            "admin_safety_store._gcs_download_text", side_effect=lambda name: store.get(name)
        ):
            for _ in range(61):
                yielded_before = bucket.yielded
                page = admin_safety_store.list_operator_audit_page(
                    limit=50, cursor=cursor
                )
                self.assertLessEqual(
                    bucket.yielded - yielded_before,
                    admin_safety_store.ADMIN_AUDIT_GCS_SCAN_MAX,
                )
                pages.append(page)
                rows.extend(page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
                self.assertTrue(cursor)
        expected = sorted(event_ids, reverse=True)
        self.assertEqual(len(pages), 60)
        self.assertFalse(pages[-1]["has_more"])
        self.assertEqual([row["event_id"] for row in rows], expected)
        self.assertLessEqual(
            max(bucket.max_results_seen), admin_safety_store.ADMIN_AUDIT_PREFIX_SCAN_MAX
        )

    def test_email_trace_keeps_hash_not_full_html_copy(self) -> None:
        html = "<html><body>안전한 브리핑</body></html>"
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "email_sender.smtplib.SMTP", _SMTP
        ):
            self.assertTrue(
                send_genie_email(
                    html,
                    "Subject",
                    to_addrs_override=["owner@example.com"],
                )
            )
        trace = last_send_trace()
        self.assertNotIn("mime_html_text", trace)
        self.assertEqual(
            trace["mime_html_sha256"], hashlib.sha256(html.encode("utf-8")).hexdigest()
        )
        self.assertTrue(trace["mime_html_byte_identical"])


class AdminRouteMemoryHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        from main import app

        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "admin_runs"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_PASSWORD": "memory-boundary-password",
                "GENIE_ARTIFACT_BUCKET": "",
                "GENIE_ADMIN_ARTIFACT_BUCKET": "",
            },
            clear=False,
        )
        self.run_dir_patch = mock.patch(
            "admin_store.admin_runs_dir", return_value=self.run_dir
        )
        self.env.start()
        self.run_dir_patch.start()
        self.client = TestClient(app)
        response = self.client.post(
            "/admin/login", data={"password": "memory-boundary-password"}
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self.run_dir_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_large_detail_loads_one_html_only_in_bounded_preview_route(self) -> None:
        run_id = "20260814_183000_keysuri_korea_tech_a1b2c3d4"
        marker = "ONE-CANONICAL-HTML-PAYLOAD"
        html = f"<html><body>{marker}{'x' * 1_000_000}</body></html>"
        admin_store.save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
            },
            email_html=html,
        )

        with mock.patch(
            "admin_routes.load_run_email_html",
            side_effect=AssertionError("detail projection must not load HTML"),
        ):
            detail = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn(marker, detail.text)
        self.assertIn(f'src="/admin/runs/{run_id}/email"', detail.text)

        original = admin_store.load_run_email_html
        with mock.patch(
            "admin_routes.load_run_email_html", wraps=original
        ) as load_html:
            preview = self.client.get(f"/admin/runs/{run_id}/email")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(marker, preview.text)
        load_html.assert_called_once_with(run_id)

    def test_sixty_review_routes_have_bounded_retained_memory_and_no_cache_growth(self) -> None:
        from admin_operational_status import _default_operational_status_service_cached
        from memory_observability import read_process_memory_kib

        rows = [
            {
                "artifact_list_summary": True,
                "run_id": f"20260814_1830{index:02d}_keysuri_korea_tech_{index:08x}",
                "mode": "keysuri_korea_tech",
                "validation_result": "pass",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
            }
            for index in range(8)
        ]
        with mock.patch(
            "admin_routes.list_run_artifact_page",
            return_value={
                "items": rows,
                "cursor": "",
                "next_cursor": "",
                "has_more": False,
            },
        ) as list_runs, mock.patch(
            "admin_routes._current_recipient_count", return_value=(0, True)
        ):
            for _ in range(8):
                warm = self.client.get("/admin/reviews")
                self.assertEqual(warm.status_code, 200)
            del warm
            gc.collect()
            cache_before = _default_operational_status_service_cached.cache_info().currsize
            rss_before = int(read_process_memory_kib()["rss_kib"])
            tracemalloc.start()
            tracemalloc.reset_peak()
            for _ in range(60):
                response = self.client.get("/admin/reviews")
                self.assertEqual(response.status_code, 200)
                del response
            gc.collect()
            retained_bytes, _peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            rss_after = int(read_process_memory_kib()["rss_kib"])
            cache_after = _default_operational_status_service_cached.cache_info().currsize

        self.assertEqual(list_runs.call_count, 68)
        self.assertLess(retained_bytes, 2 * 1024 * 1024)
        self.assertLess(rss_after - rss_before, 16 * 1024)
        self.assertEqual(cache_after, cache_before)

    def test_active_natural_defers_list_and_detail_but_not_health(self) -> None:
        from natural_run_activity import track_natural_run_activity

        with track_natural_run_activity(
            program_id="keysuri_korea_tech",
            kst_date="2026-08-14",
            scheduled_slot="18:30",
            execution_class="natural_scheduled",
        ), mock.patch(
            "admin_routes.list_run_artifact_page",
            side_effect=AssertionError("active natural must defer list projection"),
        ) as list_runs, mock.patch(
            "admin_routes.load_run_artifact",
            side_effect=AssertionError("active natural must defer detail projection"),
        ) as load_detail:
            review = self.client.get("/admin/reviews")
            detail = self.client.get(
                "/admin/runs/20260814_183000_keysuri_korea_tech_a1b2c3d4"
            )
            health = self.client.get("/health")

        self.assertEqual(review.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(review.headers.get("X-Genie-Admin-Projection"), "deferred")
        self.assertEqual(detail.headers.get("X-Genie-Admin-Projection"), "deferred")
        list_runs.assert_not_called()
        load_detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
